"""Image-only K-1 scans generated from the seed.

The PDFs are not stored in the repository. ``k1lens generate --scans`` and CI
rebuild them from seed 1065. The same seed and count rewrite the same bytes
on one machine. ``docs/scan-hashes.json`` is pinned to the CI runner image.
Eight documents differ on another Linux box. CI checks the bytes; a local
comparison is skipped outside CI.
Six extra pages are damaged on purpose (very low DPI, heavy
skew, a coffee stain, handwritten strokes, cropped boxes, and a nearly blank
page). The extractor is not adjusted for those pages.
"""

from __future__ import annotations

import io
import math
import random
import tempfile
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter
from reportlab.lib.pagesizes import letter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.models import ScheduleK1
from k1lens.generate.build import Variant, build_document
from k1lens.generate.corpus import (
    DEFAULT_SEED,
    GroundTruthFile,
    Manifest,
    ManifestDocument,
)
from k1lens.generate.dev_b import render_dev_b
from k1lens.generate.dev_layouts import render_dev
from k1lens.generate.pdf import PAGE_H, PAGE_W, _write_vector

SCAN_COUNT = 24
MIN_SCANS = 20
SCAN_VERSION = "scans-2"
LAYOUTS = ("catalog", "dev_statement", "dev_b")
# Catalog pages built to fail. The order is the K1-FAIL document order.
FAILURE_MODES = ("low_dpi", "skew", "stain", "handwriting", "crop", "blank")
FAILURE_COUNT = len(FAILURE_MODES)
_LOW_DPI = 40
_SKEW_DEGREES = 20.0
_SKEW_SHEAR = 0.45
_CROP_KEEP = 0.28
_BLANK_WHITE = 0.992
# One faint scan in each layout, at three different DPI steps. Not the same
# slot as a single DPI, so a 0% faint page is not also "every 300 DPI scan".
_FAINT_INDEXES = frozenset({4, 9, 14})
_DPI_LADDER = (150, 170, 190, 210, 230, 250, 275, 300)
_BLUR_LADDER = (0.2, 0.4, 0.6, 0.9, 1.2, 0.3, 0.8, 1.0)


@dataclass(frozen=True, slots=True)
class ScanRecipe:
    layout: str
    dpi: int
    rotation: float
    skew: float
    noise: float
    blur: float
    jpeg_quality: int
    contrast: float
    brightness: float
    faint: bool
    failure: str = ""

    @property
    def variant(self) -> str:
        if self.failure:
            return "scan_hard"
        return f"scan_{self.layout}"

    def describe(self) -> str:
        faint = " faint" if self.faint else ""
        body = (
            f"dpi={self.dpi} rot={self.rotation:.2f} skew={self.skew:.3f} "
            f"noise={self.noise:.1f} blur={self.blur:.2f} jpeg={self.jpeg_quality} "
            f"contrast={self.contrast:.2f}{faint}"
        )
        if self.failure:
            return f"failure={self.failure} {body}"
        return body


def generate_scans(
    dest: Path,
    *,
    seed: int = DEFAULT_SEED,
    count: int = SCAN_COUNT,
    include_failures: bool = True,
) -> Manifest:
    """Write ``count`` mild scans, plus the known-failure pages by default.

    ``count`` must be at least 20 when the failure pages are included. The
    failure pages are extra. Their ids are ``K1-FAIL-0001`` through
    ``K1-FAIL-0006``, and their economics use a separate random stream so
    the mild scans stay on the original stream. ``include_failures=False``
    writes only the mild scans and allows a smaller ``count``.
    """

    if include_failures and count < MIN_SCANS:
        raise ValueError(f"scan corpus must include at least {MIN_SCANS} documents")
    if count < 1:
        raise ValueError("scan corpus must include at least 1 document")
    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("K1-*"):
        if stale.suffix in {".pdf", ".json"}:
            stale.unlink()
    doc_rng = random.Random(seed)
    recipes = scan_recipes(count, random.Random(seed + 1065))
    documents: list[ManifestDocument] = []
    for index, recipe in enumerate(recipes, start=1):
        documents.append(_emit(dest, doc_rng, index, f"K1-SCAN-{index:04d}", recipe))
    if include_failures:
        documents.extend(_failure_documents(dest, seed))
    manifest = Manifest(
        seed=seed,
        count=len(documents),
        generator_version=SCAN_VERSION,
        documents=documents,
    )
    (dest / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def scan_recipes(count: int, rng: random.Random) -> list[ScanRecipe]:
    """One recipe per document. Layouts cycle so each layout appears."""

    recipes: list[ScanRecipe] = []
    for index in range(count):
        layout = LAYOUTS[index % len(LAYOUTS)]
        faint = index in _FAINT_INDEXES
        rotation = rng.uniform(-2.5, 2.5)
        if abs(rotation) < 0.4:
            rotation = 0.8 if rotation >= 0 else -0.8
        skew = rng.uniform(-0.045, 0.045)
        if abs(skew) < 0.01:
            skew = 0.02 if skew >= 0 else -0.02
        recipes.append(
            ScanRecipe(
                layout=layout,
                dpi=_DPI_LADDER[index % len(_DPI_LADDER)],
                rotation=rotation,
                skew=skew,
                noise=rng.uniform(4.0, 14.0),
                blur=_BLUR_LADDER[index % len(_BLUR_LADDER)],
                jpeg_quality=40 if faint else rng.choice((55, 70, 82, 90)),
                contrast=0.42 if faint else rng.uniform(0.9, 1.0),
                brightness=0.72 if faint else 1.0,
                faint=faint,
            )
        )
    return recipes


def _hard(
    failure: str,
    *,
    dpi: int = 200,
    rotation: float = 0.0,
    skew: float = 0.0,
    jpeg_quality: int = 80,
) -> ScanRecipe:
    return ScanRecipe(
        layout="catalog",
        dpi=dpi,
        rotation=rotation,
        skew=skew,
        noise=0.0,
        blur=0.0,
        jpeg_quality=jpeg_quality,
        contrast=1.0,
        brightness=1.0,
        faint=False,
        failure=failure,
    )


def failure_recipes() -> list[ScanRecipe]:
    """Catalog pages damaged so the extractor should fail. Parameters are fixed."""

    return [
        _hard("low_dpi", dpi=_LOW_DPI, jpeg_quality=70),
        _hard("skew", rotation=_SKEW_DEGREES, skew=_SKEW_SHEAR),
        _hard("stain", jpeg_quality=75),
        _hard("handwriting"),
        _hard("crop", jpeg_quality=85),
        _hard("blank", jpeg_quality=70),
    ]


def failure_mode_of(degradation: str) -> str:
    """Return the failure name stored on a scan, or an empty string."""

    token = degradation.split(" ", 1)[0]
    if token.startswith("failure="):
        return token.removeprefix("failure=")
    return ""


def _emit(
    dest: Path,
    rng: random.Random,
    index: int,
    document_id: str,
    recipe: ScanRecipe,
) -> ManifestDocument:
    document = build_document(rng, index, Variant.CLEAN).model_copy(
        update={"document_id": document_id, "variant": recipe.variant}
    )
    pdf_name = f"{document_id}.pdf"
    json_name = f"{document_id}.json"
    _render_scan(document, dest / pdf_name, recipe)
    truth = GroundTruthFile(planted_defects=[], document=document)
    (dest / json_name).write_text(truth.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return ManifestDocument(
        document_id=document_id,
        variant=recipe.variant,
        pdf=pdf_name,
        ground_truth=json_name,
        planted_defects=[],
        layout=recipe.layout,
        dpi=recipe.dpi,
        degradation=recipe.describe(),
    )


def _failure_documents(dest: Path, seed: int) -> list[ManifestDocument]:
    rng = random.Random(seed + 4242)
    documents: list[ManifestDocument] = []
    for index, recipe in enumerate(failure_recipes(), start=1):
        documents.append(_emit(dest, rng, 9000 + index, f"K1-FAIL-{index:04d}", recipe))
    return documents


def _render_scan(document: ScheduleK1, dest: Path, recipe: ScanRecipe) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        vector = Path(tmp) / "vector.pdf"
        _write_vector_for(document, vector, recipe.layout)
        images = _raster_pages(vector, recipe)
    _write_image_pdf(images, dest, document.document_id)


def _write_vector_for(document: ScheduleK1, dest: Path, layout: str) -> None:
    if layout == "catalog":
        _write_vector(document, dest, rotate=False)
        return
    if layout == "dev_statement":
        render_dev(document, dest, kind="dev_statement")
        return
    if layout == "dev_b":
        render_dev_b(document, dest)
        return
    raise ValueError(f"Unknown scan layout {layout}")


def _raster_pages(src: Path, recipe: ScanRecipe) -> list[Image.Image]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(src))
    images: list[Image.Image] = []
    try:
        scale = recipe.dpi / 72
        for index in range(len(pdf)):
            page = pdf[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil().convert("RGB")
            images.append(_degrade(image, recipe))
    finally:
        pdf.close()
    return images


def _degrade(image: Image.Image, recipe: ScanRecipe) -> Image.Image:
    if recipe.failure in {"stain", "handwriting", "crop", "blank", "low_dpi"}:
        return _jpeg(_damage(image, recipe.failure), recipe.jpeg_quality)
    image = image.rotate(
        recipe.rotation,
        expand=True,
        fillcolor=(255, 255, 255),
        resample=Image.Resampling.BICUBIC,
    )
    image = _shear(image, recipe.skew)
    if recipe.blur > 0:
        image = image.filter(ImageFilter.GaussianBlur(radius=recipe.blur))
    image = ImageEnhance.Contrast(image).enhance(recipe.contrast)
    if recipe.brightness != 1.0:
        image = ImageEnhance.Brightness(image).enhance(recipe.brightness)
    if recipe.noise > 0:
        image = _add_noise(image, recipe)
    return _jpeg(image, recipe.jpeg_quality)


def _damage(image: Image.Image, failure: str) -> Image.Image:
    if failure == "stain":
        return _coffee_stain(image)
    if failure == "handwriting":
        return _handwritten(image)
    if failure == "crop":
        return _crop_boxes(image)
    if failure == "blank":
        return _nearly_blank(image)
    return image


def _coffee_stain(image: Image.Image) -> Image.Image:
    """Translucent brown ellipses over the middle of the page."""

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    width, height = image.size
    blobs = (
        (0.42, 0.28, 0.40, 0.20, 210),
        (0.48, 0.48, 0.46, 0.22, 200),
        (0.36, 0.68, 0.42, 0.20, 195),
        (0.58, 0.82, 0.36, 0.16, 185),
    )
    for center_x, center_y, radius_x, radius_y, alpha in blobs:
        box = (
            int((center_x - radius_x) * width),
            int((center_y - radius_y) * height),
            int((center_x + radius_x) * width),
            int((center_y + radius_y) * height),
        )
        draw.ellipse(box, fill=(112, 74, 36, alpha))
    stained = Image.alpha_composite(image.convert("RGBA"), overlay)
    return stained.convert("RGB")


def _handwritten(image: Image.Image) -> Image.Image:
    """Pen strikes and a scribble across printed lines. Not a typed digit."""

    marked = image.copy()
    draw = ImageDraw.Draw(marked)
    width, height = image.size
    pen = max(4, height // 160)
    ink = (25, 35, 110)
    row = 0.12
    while row <= 0.92:
        y_pos = int(height * row)
        draw.line(
            (int(width * 0.06), y_pos, int(width * 0.88), y_pos + pen),
            fill=ink,
            width=pen,
        )
        row += 0.045
    for start in (0.20, 0.48, 0.70):
        points: list[tuple[int, int]] = []
        x_pos = int(width * 0.10)
        y_pos = int(height * start)
        step = max(8, width // 55)
        for index in range(22):
            x_pos += step
            y_pos += step if index % 4 < 2 else -step
            points.append((x_pos, y_pos))
        draw.line(points, fill=ink, width=pen + 1)
    return marked


def _crop_boxes(image: Image.Image) -> Image.Image:
    """Keep the top of the page and replace the rest with white."""

    width, height = image.size
    kept = image.crop((0, 0, width, max(1, int(height * _CROP_KEEP))))
    page = Image.new("RGB", (width, height), (255, 255, 255))
    page.paste(kept, (0, 0))
    return page


def _nearly_blank(image: Image.Image) -> Image.Image:
    white = Image.new("RGB", image.size, (255, 255, 255))
    return Image.blend(image, white, _BLANK_WHITE)


def _shear(image: Image.Image, skew: float) -> Image.Image:
    width, height = image.size
    extra = int(abs(skew) * height) + 1
    return image.transform(
        (width + extra, height),
        Image.Transform.AFFINE,
        (1, -skew, 0 if skew > 0 else extra, 0, 1, 0),
        resample=Image.Resampling.BICUBIC,
        fillcolor=(255, 255, 255),
    )


def _add_noise(image: Image.Image, recipe: ScanRecipe) -> Image.Image:
    width, height = image.size
    small_w = max(1, width // 10)
    small_h = max(1, height // 10)
    rng = random.Random(
        f"{recipe.dpi}:{round(recipe.rotation * 1000)}:{round(recipe.noise * 1000)}:"
        f"{round(recipe.skew * 1000)}:{width}:{height}"
    )
    raw = bytearray(small_w * small_h)
    for index in range(len(raw)):
        sample = 128 + _gauss(rng) * recipe.noise
        raw[index] = max(0, min(255, int(sample)))
    small = Image.frombytes("L", (small_w, small_h), bytes(raw))
    layer = small.resize((width, height), Image.Resampling.BILINEAR)
    merged = Image.merge("RGB", (layer, layer, layer))
    return ImageChops.add(image, merged, scale=1.0, offset=-128)


def _gauss(rng: random.Random) -> float:
    u1 = max(rng.random(), 1e-12)
    u2 = rng.random()
    return math.sqrt(-2.0 * math.log(u1)) * math.cos(math.tau * u2)


def _jpeg(image: Image.Image, quality: int) -> Image.Image:
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=quality, subsampling=0)
    buffer.seek(0)
    with Image.open(buffer) as compressed:
        return compressed.convert("RGB")


def _write_image_pdf(images: list[Image.Image], dest: Path, document_id: str) -> None:
    canvas = Canvas(str(dest), pagesize=letter, invariant=1)
    canvas.setTitle(f"{document_id} synthetic Schedule K-1 scan")
    canvas.setAuthor("K1-Lens synthetic generator")
    for image in images:
        canvas.drawImage(
            ImageReader(image),
            0,
            0,
            width=PAGE_W,
            height=PAGE_H,
            preserveAspectRatio=True,
            anchor="c",
            mask="auto",
        )
        canvas.showPage()
    canvas.save()

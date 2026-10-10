"""OCR for image-only PDFs.

This path is deterministic and does not call a model API. It runs when a PDF
has no field labels and a Tesseract binary is installed. Set
``K1LENS_ENABLE_OCR`` to ``0``, ``false``, or ``no`` to skip it.

Each line keeps Tesseract's mean word confidence. A label that is one edit
from exactly one known field label is accepted, and that weaker match is
recorded on the observation. A period after an abbreviation-shaped token
is kept: a short capitalized token or a run of initials, such as L.P.,
Jr., Bros., or J. R. A separator period after any other token is dropped.
The review threshold is not applied here.

Tesseract is given a subprocess timeout and ``OMP_THREAD_LIMIT=1`` so a
busy machine does not stretch one page into the timeout. The timeout itself
is not shortened. A page that times out, or whose process fails, is
recorded on the read. The rules engine turns that into an error, so the
document stays in review.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image

from k1lens.domain.fields import CODED_BOXES, SCALAR_BY_LABEL
from k1lens.extract.confidence import LABEL_EXACT, LABEL_ONE_EDIT, clamp_unit
from k1lens.extract.geometry import PlacedPair, PlacedWord, pair_grouped_lines, pair_line
from k1lens.extract.labels import resolve_field_label
from k1lens.extract.text import Observed, proximity_from_gap

logger = logging.getLogger(__name__)

# pytesseract treats 0 as "wait forever". A letter page at this render scale
# finishes well under a minute; the bound is here so a hung process ends.
TESSERACT_TIMEOUT_SECONDS = 120


# One OpenMP thread per Tesseract process. Several OCR jobs at the default
# of 4 threads each stall each other. The timeout above is unchanged.
def limit_openmp_threads() -> None:
    """Keep this process, and the Tesseract children it starts, on one thread."""

    os.environ["OMP_THREAD_LIMIT"] = "1"


limit_openmp_threads()

_CODE = re.compile(r"^[A-Z]{1,2}$")
_LEADING_NOISE = re.compile(r"^[^A-Za-z0-9]+")
_DIGIT_UPPER = re.compile(r"(\d)([A-Z])")


@dataclass(frozen=True, slots=True)
class OcrWord:
    text: str
    confidence: float
    left: float
    top: float
    width: float
    height: float


@dataclass(frozen=True, slots=True)
class OcrLine:
    text: str
    confidence: float
    words: tuple[OcrWord, ...] = ()
    # Words Tesseract scored below zero. A street unit in here is kept and held.
    dropped: tuple[OcrWord, ...] = ()


@dataclass(frozen=True, slots=True)
class OcrRead:
    """Fields read from OCR, and the 1-based pages whose OCR failed.

    ``failed_pages`` is empty when every page was read. A timeout, a killed
    Tesseract process, or a render error puts that page here. The caller
    copies the tuple onto the document.
    """

    fields: dict[str, list[Observed]]
    failed_pages: tuple[int, ...]


def tesseract_version() -> str | None:
    """The first line of ``tesseract --version``, or None when it is not installed.

    Ubuntu CI and this repository's measurements use 5.3.4. The Docker image
    uses Debian bookworm's 5.3.0. Rasterized floors sit under both.
    """

    binary = shutil.which("tesseract")
    if binary is None:
        return None
    try:
        completed = subprocess.run(
            [binary, "--version"],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
            env=_tesseract_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    text = completed.stdout or completed.stderr
    line = text.splitlines()
    if not line:
        return None
    return line[0].strip()


def ocr_enabled() -> bool:
    flag = os.environ.get("K1LENS_ENABLE_OCR", "auto").strip().lower()
    if flag in {"0", "false", "no", "off"}:
        return False
    if flag in {"1", "true", "yes", "on"}:
        return True
    return shutil.which("tesseract") is not None


def ocr_word_confidence(mean_word_confidence: float) -> float:
    """Map a 0-100 Tesseract mean onto 0-1. Values outside that range are clipped."""

    return clamp_unit(mean_word_confidence / 100.0)


def repair_ocr_line(line: str) -> str:
    text = re.sub(r"\s+", " ", line).strip()
    text = _LEADING_NOISE.sub("", text)
    if ":" not in text and ";" in text:
        text = text.replace(";", ":", 1)
    return text


def resolve_label(label: str, known: set[str] | None = None) -> tuple[str, float]:
    """Return a known label and a match score.

    An exact label scores ``LABEL_EXACT``. A label one edit from exactly one
    known field scores ``LABEL_ONE_EDIT``. Anything else is returned unchanged
    with score 0, and the assembler ignores it.
    """

    names = known if known is not None else set(SCALAR_BY_LABEL)
    cleaned = _DIGIT_UPPER.sub(r"\1 \2", label.strip())
    cleaned = re.sub(r"\bpet\b", "pct", cleaned)
    if cleaned in names or _is_coded_label(cleaned):
        return cleaned, LABEL_EXACT
    matches = [name for name in names if within_one_edit(cleaned, name)]
    if len(matches) == 1:
        return matches[0], LABEL_ONE_EDIT
    if known is None:
        resolved = resolve_field_label(cleaned)
        if resolved is not None:
            return resolved
    return cleaned, 0.0


def within_one_edit(left: str, right: str) -> bool:
    if left == right:
        return False
    if abs(len(left) - len(right)) > 1:
        return False
    if len(left) == len(right):
        return sum(a != b for a, b in zip(left, right, strict=True)) == 1
    shorter, longer = (left, right) if len(left) < len(right) else (right, left)
    index = 0
    for char in longer:
        if index < len(shorter) and shorter[index] == char:
            index += 1
    return index == len(shorter)


def read_ocr(pdf_path: Path, *, only_pages: tuple[int, ...] | None = None) -> OcrRead | None:
    """Read an image-only PDF, or the listed pages. None means OCR is off.

    A page that fails stays in ``failed_pages`` and is not dropped. Other
    pages are still read. ``only_pages`` limits the work to pages that have
    no usable text layer.
    """

    if not ocr_enabled():
        return None
    wanted = None if only_pages is None else set(only_pages)
    try:
        pages = _pages_for_ocr(pdf_path, wanted)
    except Exception as exc:
        logger.exception("OCR render failed for %s (%s)", pdf_path.name, type(exc).__name__)
        failed = _document_pages(pdf_path) if wanted is None else tuple(sorted(wanted))
        return OcrRead({}, failed)
    observed: dict[str, list[Observed]] = {}
    failed_list: list[int] = []
    for page_number, image in pages:
        try:
            lines = recognize_lines(image)
        except Exception as exc:
            logger.exception(
                "OCR recognize failed for %s page %s (%s)",
                pdf_path.name,
                page_number,
                type(exc).__name__,
            )
            failed_list.append(page_number)
            continue
        free: list[list[PlacedWord]] = []
        confidence: dict[tuple[str, float, float], float] = {}
        for line in lines:
            repaired = repair_ocr_line(line.text)
            if ":" in repaired:
                _absorb(observed, line, page_number)
                free.append([])
                continue
            placed: list[PlacedWord] = []
            for word in line.words:
                box = PlacedWord(
                    text=word.text,
                    x0=word.left,
                    top=word.top,
                    x1=word.left + word.width,
                    bottom=word.top + word.height,
                )
                placed.append(box)
                confidence[(word.text, round(box.x0, 1), round(box.top, 1))] = word.confidence
            free.append(placed)
        for pair in pair_grouped_lines(free):
            _emit_geometry(observed, pair, confidence, page_number)
    return OcrRead(observed, tuple(failed_list))


def ocr_plain_text(result: OcrRead) -> str | None:
    """Label lines from a read, or None when no field was recognized."""

    parts = [f"{label}: {item.raw}" for label, rows in result.fields.items() for item in rows]
    text = "\n".join(parts)
    return text or None


def maybe_ocr(pdf_path: Path) -> str | None:
    result = read_ocr(pdf_path)
    if result is None:
        return None
    return ocr_plain_text(result)


def _document_pages(pdf_path: Path) -> tuple[int, ...]:
    """1-based page numbers, or ``(1,)`` when the file itself cannot be opened."""

    try:
        import pypdfium2 as pdfium

        pdf = pdfium.PdfDocument(str(pdf_path))
        try:
            count = len(pdf)
        finally:
            pdf.close()
    except Exception:
        logger.exception("OCR could not open %s", pdf_path.name)
        return (1,)
    if count < 1:
        return (1,)
    return tuple(range(1, count + 1))


def render_pages(pdf_path: Path) -> list[Image.Image]:
    return [image for _number, image in _render_numbered(pdf_path, None)]


def _pages_for_ocr(pdf_path: Path, only_pages: set[int] | None) -> list[tuple[int, Image.Image]]:
    """Numbered page images. Goes through ``render_pages`` so a test can replace it."""

    pages = list(enumerate(render_pages(pdf_path), start=1))
    if only_pages is None:
        return pages
    return [item for item in pages if item[0] in only_pages]


def _render_numbered(pdf_path: Path, only_pages: set[int] | None) -> list[tuple[int, Image.Image]]:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    images: list[tuple[int, Image.Image]] = []
    try:
        for index in range(len(pdf)):
            number = index + 1
            if only_pages is not None and number not in only_pages:
                continue
            page = pdf[index]
            bitmap = page.render(scale=2)
            images.append((number, bitmap.to_pil().convert("RGB")))
    finally:
        pdf.close()
    return images


def _tesseract_env() -> dict[str, str]:
    """Environment for a Tesseract child. One OpenMP thread, timeout unchanged."""

    env = dict(os.environ)
    env["OMP_THREAD_LIMIT"] = "1"
    os.environ["OMP_THREAD_LIMIT"] = "1"
    return env


def _bind_tesseract_env() -> None:
    """Pass ``OMP_THREAD_LIMIT=1`` on the env of every Tesseract subprocess.

    pytesseract builds ``Popen`` kwargs in ``subprocess_args``. Replacing
    that env is what the child actually inherits.
    """

    import importlib
    from typing import Any

    runner: Any = importlib.import_module("pytesseract.pytesseract")

    if getattr(runner, "_k1lens_thread_limit", False):
        return
    original = runner.subprocess_args

    def subprocess_args(include_stdout: bool = True) -> dict[str, object]:
        raw = original(include_stdout=include_stdout)
        updated: dict[str, object] = dict(raw) if isinstance(raw, dict) else {}
        updated["env"] = _tesseract_env()
        return updated

    runner.subprocess_args = subprocess_args
    runner._k1lens_thread_limit = True


def recognize_lines(image: Image.Image) -> list[OcrLine]:
    import pytesseract

    _bind_tesseract_env()
    data = pytesseract.image_to_data(
        image,
        output_type=pytesseract.Output.DICT,
        timeout=TESSERACT_TIMEOUT_SECONDS,
    )
    groups: dict[tuple[int, int, int], list[OcrWord]] = {}
    dropped: dict[tuple[int, int, int], list[OcrWord]] = {}
    texts = data["text"]
    for index, raw in enumerate(texts):
        word = str(raw).strip()
        if word == "":
            continue
        try:
            confidence = float(data["conf"][index])
        except (TypeError, ValueError):
            continue
        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        token = OcrWord(
            text=word,
            confidence=confidence,
            left=_ocr_float(data, "left", index),
            top=_ocr_float(data, "top", index),
            width=_ocr_float(data, "width", index),
            height=_ocr_float(data, "height", index),
        )
        if confidence < 0:
            dropped.setdefault(key, []).append(token)
            continue
        groups.setdefault(key, []).append(token)
    lines: list[OcrLine] = []
    for key in sorted(set(groups) | set(dropped)):
        words = groups.get(key, [])
        if not words:
            continue
        text = " ".join(word.text for word in words)
        mean = sum(word.confidence for word in words) / len(words)
        lines.append(
            OcrLine(
                text=text,
                confidence=mean,
                words=tuple(words),
                dropped=tuple(dropped.get(key, ())),
            )
        )
    return lines


# A trailing period stays when the last token is abbreviation-shaped: a run
# of initials (``L.P.``, ``J.``) or a short title-case token (``Jr.``,
# ``Bros.``, ``Assoc.``). A yes/no word is not an abbreviation, so ``Yes.``
# and ``No.`` lose the separator. ``LLC.`` and ``00-0000007.`` do too.
_INITIALS = re.compile(r"(?:[A-Z]\.)+")
_SHORT_CAP = re.compile(r"[A-Z][a-z]{1,5}\.")
_YES_NO_WORD = re.compile(r"(?i)^(yes|no|true|false|y|n)$")


def _abbreviation_shaped(value: str) -> bool:
    parts = value.split()
    if not parts:
        return False
    last = parts[-1]
    if _YES_NO_WORD.fullmatch(last.rstrip(".")) is not None:
        return False
    if _INITIALS.fullmatch(last):
        return True
    return _SHORT_CAP.fullmatch(last) is not None


def _strip_separator_period(value: str) -> str:
    if value.endswith(".") and value != "." and not _abbreviation_shaped(value):
        return value[:-1]
    return value


def _recover_street_unit(label: str, value: str, line: OcrLine) -> tuple[str, bool]:
    """Append a dropped unit or suite number. A dropped token is unsure."""

    from k1lens.domain.fields import SCALAR_BY_LABEL
    from k1lens.extract.geometry import _unit_run, ends_with_unit

    spec = SCALAR_BY_LABEL.get(label)
    if spec is None or not spec.path.endswith(".street") or not line.dropped:
        return value, False
    if ends_with_unit(value):
        return value, False
    kept_right = max((word.left + word.width for word in line.words), default=0.0)
    tail = [
        word
        for word in sorted(line.dropped, key=lambda item: item.left)
        if word.left >= kept_right - 1.0
    ]
    placed = [
        PlacedWord(
            text=word.text,
            x0=word.left,
            top=word.top,
            x1=word.left + word.width,
            bottom=word.top + word.height,
        )
        for word in tail
    ]
    count = _unit_run(placed)
    if count == 0:
        return value, False
    extra = " ".join(word.text for word in tail[:count])
    if extra == "":
        return value, False
    return f"{value} {extra}".strip(), True


def _street_ends_with_unit(label: str, value: str) -> bool:
    from k1lens.domain.fields import SCALAR_BY_LABEL
    from k1lens.extract.geometry import ends_with_unit

    spec = SCALAR_BY_LABEL.get(label)
    return spec is not None and spec.path.endswith(".street") and ends_with_unit(value)


def _low_confidence_unit(
    label: str, value: str, words: tuple[OcrWord, ...] | list[OcrWord]
) -> bool:
    """A street unit read below 90 stays in review. The digits are still kept."""

    from k1lens.domain.fields import SCALAR_BY_LABEL
    from k1lens.extract.geometry import ends_with_unit

    spec = SCALAR_BY_LABEL.get(label)
    if spec is None or not spec.path.endswith(".street") or not ends_with_unit(value):
        return False
    last = value.split()[-1]
    scores = [word.confidence for word in words if word.text == last]
    return bool(scores) and min(scores) < 90.0


def _absorb(observed: dict[str, list[Observed]], line: OcrLine, page: int) -> None:
    repaired = repair_ocr_line(line.text)
    if ":" not in repaired:
        _absorb_geometry(observed, line, page)
        return
    label, raw = repaired.split(":", 1)
    label, label_score = resolve_label(label.strip())
    value = _strip_separator_period(raw.strip())
    value, unsure = _recover_street_unit(label, value, line)
    if label == "" or value == "":
        return
    row = Observed(
        raw=value,
        page=page,
        bbox=None,
        extractor="ocr",
        label_score=label_score,
        ocr_confidence=ocr_word_confidence(line.confidence),
        truncated=unsure or _low_confidence_unit(label, value, line.words),
        id_digit_confidence=_id_digit_confidence(
            label,
            [word.confidence for word in line.words if any(char.isdigit() for char in word.text)],
        ),
    )
    rows = observed.setdefault(label, [])
    if _is_coded_label(label):
        if any(item.raw == value for item in rows):
            return
        rows.append(row)
        return
    if any(item.raw != value for item in rows):
        observed[label] = [replace_conflict(item) for item in rows]
        observed[label].append(replace_conflict(row))
        return
    if not rows:
        rows.append(row)


def replace_conflict(obs: Observed) -> Observed:
    return replace(obs, conflict=True)


def _emit_geometry(
    observed: dict[str, list[Observed]],
    pair: PlacedPair,
    confidence: dict[tuple[str, float, float], float],
    page: int,
) -> None:
    """Record one geometry pair. Confidence is the mean of the value's words."""

    wanted = set(pair.value.split())
    scores = [
        score
        for (text, x0, _top), score in confidence.items()
        if text in wanted and pair.bbox[0] - 1.0 <= x0 <= pair.bbox[2] + 1.0
    ]
    mean = sum(scores) / len(scores) if scores else 0.0
    last = pair.value.split()[-1] if pair.value.split() else ""
    unit_scores = [
        score
        for (text, x0, _top), score in confidence.items()
        if text == last and pair.bbox[0] - 1.0 <= x0 <= pair.bbox[2] + 1.0
    ]
    low_unit = (
        bool(unit_scores)
        and min(unit_scores) < 90.0
        and _street_ends_with_unit(pair.label, pair.value)
    )
    row = Observed(
        raw=pair.value,
        page=page,
        bbox=pair.bbox,
        extractor="ocr",
        label_score=pair.label_score,
        proximity=proximity_from_gap(pair.gap),
        ocr_confidence=ocr_word_confidence(mean),
        position_paired=True,
        neighbor_line=pair.neighbor_line,
        neighbor_column=pair.neighbor_column,
        truncated=pair.truncated or low_unit,
        caption_slot=pair.caption_slot,
        id_digit_confidence=_id_digit_confidence(pair.label, _digit_scores(pair.value, confidence)),
    )
    _keep(observed, pair.label, row)


def _absorb_geometry(observed: dict[str, list[Observed]], line: OcrLine, page: int) -> None:
    """Same-line label and amount from OCR word boxes, with no colon."""

    if not line.words:
        return
    placed = [
        PlacedWord(
            text=word.text,
            x0=word.left,
            top=word.top,
            x1=word.left + word.width,
            bottom=word.top + word.height,
        )
        for word in line.words
    ]
    for pair in pair_line(placed):
        confidence = _pair_confidence(line, pair.value)
        row = Observed(
            raw=pair.value,
            page=page,
            bbox=pair.bbox,
            extractor="ocr",
            label_score=pair.label_score,
            proximity=proximity_from_gap(pair.gap),
            ocr_confidence=ocr_word_confidence(confidence),
            position_paired=True,
            neighbor_line=pair.neighbor_line,
            neighbor_column=pair.neighbor_column,
            truncated=pair.truncated or _low_confidence_unit(pair.label, pair.value, line.words),
            caption_slot=pair.caption_slot,
            id_digit_confidence=_id_digit_confidence(
                pair.label,
                [
                    word.confidence
                    for word in line.words
                    if any(char.isdigit() for char in word.text) and word.text in pair.value.split()
                ],
            ),
        )
        _keep(observed, pair.label, row)


def _id_digit_confidence(label: str, scores: list[float]) -> float | None:
    """Lowest OCR score among digit words of an EIN or TIN, or None for other fields."""

    spec = SCALAR_BY_LABEL.get(label)
    if spec is None or spec.path not in {"part_i.ein", "part_ii.tin"}:
        return None
    if not scores:
        return None
    return ocr_word_confidence(min(scores))


def _digit_scores(value: str, confidence: dict[tuple[str, float, float], float]) -> list[float]:
    wanted = {token for token in value.split() if any(char.isdigit() for char in token)}
    return [score for (text, _x0, _top), score in confidence.items() if text in wanted]


def _pair_confidence(line: OcrLine, value: str) -> float:
    wanted = set(value.split())
    chosen = [word.confidence for word in line.words if word.text in wanted]
    if not chosen:
        return line.confidence
    return sum(chosen) / len(chosen)


def _keep(observed: dict[str, list[Observed]], label: str, row: Observed) -> None:
    rows = observed.setdefault(label, [])
    if _is_coded_label(label):
        if any(item.raw == row.raw for item in rows):
            return
        rows.append(row)
        return
    if any(item.raw != row.raw for item in rows):
        observed[label] = [replace_conflict(item) for item in rows]
        observed[label].append(replace_conflict(row))
        return
    if not rows:
        rows.append(row)


def _ocr_float(data: dict[str, list[object]], key: str, index: int) -> float:
    column = data.get(key)
    if column is None or index >= len(column):
        return 0.0
    raw = column[index]
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def _is_coded_label(label: str) -> bool:
    for box in CODED_BOXES:
        prefix = f"{box.pdf_prefix} "
        if not label.startswith(prefix):
            continue
        code = label[len(prefix) :].strip().upper()
        return _CODE.fullmatch(code) is not None
    return False

"""Deterministic extraction and the OCR path for image-only PDFs."""

import os
import random
import shutil
from decimal import Decimal
from pathlib import Path

import pytest

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.extract.assemble import assemble
from k1lens.extract.confidence import LABEL_EXACT, LABEL_ONE_EDIT
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.factory import get_extractor
from k1lens.extract.ocr import (
    TESSERACT_TIMEOUT_SECONDS,
    OcrLine,
    maybe_ocr,
    ocr_enabled,
    ocr_word_confidence,
    read_ocr,
    recognize_lines,
    repair_ocr_line,
    resolve_label,
)
from k1lens.extract.text import Observed, parse_lines
from k1lens.generate.build import Variant
from k1lens.generate.corpus import generate_corpus, load_ground_truth
from k1lens.generate.pdf import render_pdf


def test_parse_lines_ignores_headings() -> None:
    parsed = parse_lines("SYNTHETIC SAMPLE\nA Partnership EIN: 00-0000001\n\nPART I")
    assert parsed == {"A Partnership EIN": "00-0000001"}


def test_text_layer_extracts_when_ocr_is_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "0")
    dest = tmp_path / "docs"
    generate_corpus(
        dest,
        seed=21,
        count=4,
        plan=(Variant.CLEAN, Variant.ROTATED, Variant.RASTERIZED, Variant.MISSING_FIELDS),
    )
    extractor = DeterministicExtractor()
    clean = extractor.extract(dest / "K1-0001.pdf")
    truth = load_ground_truth(dest / "K1-0001.json").document
    assert clean.part_i.ein.value == truth.part_i.ein.value
    assert clean.part_ii.capital.ending.value == truth.part_ii.capital.ending.value
    assert clean.part_i.ein.provenance.page == 1
    assert clean.part_i.ein.provenance.bbox is not None
    assert clean.part_iii.ordinary_business_income.provenance.page == 2
    assert clean.part_iii.ordinary_business_income.confidence > REVIEW_THRESHOLD
    assert clean.part_i.ein.confidence > REVIEW_THRESHOLD

    rotated = extractor.extract(dest / "K1-0002.pdf")
    rotated_truth = load_ground_truth(dest / "K1-0002.json").document
    assert rotated.part_i.name.value == rotated_truth.part_i.name.value

    scanned = extractor.extract(dest / "K1-0003.pdf")
    assert scanned.part_i.ein.value is None
    assert scanned.part_i.ein.confidence == 0

    missing = extractor.extract(dest / "K1-0004.pdf")
    assert missing.part_i.ein.value is None
    assert missing.part_ii.capital.beginning.value is not None


def test_unparseable_money_lowers_confidence() -> None:
    observed = {
        "1 Ordinary business income": Observed("n/a", 2, None, "deterministic"),
        "TAX YEAR": Observed("1999", 1, None, "deterministic"),
        "DOCUMENT ID": Observed("not-an-id", 1, None, "deterministic"),
        "VARIANT": Observed("", 1, None, "deterministic"),
    }
    document = assemble(
        "notes", {key: [value] for key, value in observed.items()}, extractor="deterministic"
    )
    assert document.document_id == "K1-UNKNOWN"
    assert document.tax_year == 1999
    assert document.variant == "unknown"
    assert document.part_iii.ordinary_business_income.value is None
    assert document.part_iii.ordinary_business_income.confidence <= 0.25


def test_coded_line_and_confidence_clamp() -> None:
    observed = {
        "11 Other income A": Observed(
            "1500", 2, (1, 2, 3, 4), "deterministic", label_score=1.4, proximity=1.0
        ),
        "11 Other income B": Observed("250", 2, None, "deterministic", label_score=1.0),
        "11 Other income not-a-code": Observed("5", 2, None, "deterministic"),
        "A Partnership EIN": Observed("00-0000001", 1, None, "deterministic"),
        "B Partnership name": Observed("SAMPLE Partners LP", 1, None, "deterministic"),
        "5 Interest income": Observed("10.00", 1, None, "deterministic"),
    }
    document = assemble(
        "K1-0008", {key: [value] for key, value in observed.items()}, extractor="deterministic"
    )
    assert len(document.part_iii.other_income) == 2
    codes = {item.code for item in document.part_iii.other_income}
    assert codes == {"A", "B"}
    by_code = {item.code: item.amount.confidence for item in document.part_iii.other_income}
    assert 0.0 <= by_code["A"] <= 1.0
    assert by_code["A"] > by_code["B"]


def test_unknown_backend() -> None:
    with pytest.raises(ValueError, match="Unknown extraction backend"):
        get_extractor("textract")


def test_ocr_can_be_disabled(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "0")
    assert ocr_enabled() is False
    document = render_one(tmp_path, Variant.RASTERIZED)
    assert read_ocr(document) is None
    assert maybe_ocr(document) is None


def test_ocr_auto_follows_the_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("K1LENS_ENABLE_OCR", raising=False)
    monkeypatch.setattr("k1lens.extract.ocr.shutil.which", lambda name: None)
    assert ocr_enabled() is False
    monkeypatch.setattr("k1lens.extract.ocr.shutil.which", lambda name: "/usr/bin/tesseract")
    assert ocr_enabled() is True


def test_tesseract_version_is_recorded() -> None:
    from k1lens.extract.ocr import tesseract_version

    version = tesseract_version()
    if shutil.which("tesseract") is None:
        assert version is None
        return
    assert version is not None
    assert version.startswith("tesseract ")


def test_ocr_word_confidence_is_a_unit_interval() -> None:
    assert ocr_word_confidence(0) == pytest.approx(0.0)
    assert ocr_word_confidence(90) == pytest.approx(0.9)
    assert ocr_word_confidence(100) == pytest.approx(1.0)
    assert ocr_word_confidence(-5) == pytest.approx(0.0)
    assert ocr_word_confidence(250) == pytest.approx(1.0)


def test_ocr_repairs_labels_without_guessing_two_ways() -> None:
    assert repair_ocr_line("  'L Withdrawals and distributions; 11160.00") == (
        "L Withdrawals and distributions: 11160.00"
    )
    assert resolve_label("J Profit ending pet") == ("J Profit ending pct", LABEL_EXACT)
    assert resolve_label("Ya Net long-term capital gain") == (
        "9a Net long-term capital gain",
        LABEL_ONE_EDIT,
    )
    assert resolve_label("CRS center") == ("CRS center", 0.0)
    assert resolve_label("cab", known={"cat", "car"}) == ("cab", 0.0)
    assert resolve_label("19 Distributions A") == ("19 Distributions A", LABEL_EXACT)
    assert resolve_label("19 Distributions C")[0] == "19 Distributions C"


def test_ocr_line_is_used_with_low_confidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "yes")
    pdf = render_one(tmp_path, Variant.RASTERIZED)

    def lines(image: object) -> list[OcrLine]:
        assert image is not None
        return [
            OcrLine("A Partnership EIN: 00-0000007.", 90),
            OcrLine("B Partnership name: SAMPLE Harbor LP", 95),
            OcrLine("5 Interest income: 12.00", 95),
            OcrLine("L Withdrawals and distributions; 10.00", 40),
        ]

    monkeypatch.setattr("k1lens.extract.ocr.recognize_lines", lines)
    monkeypatch.setattr("k1lens.extract.ocr.render_pages", lambda path: [object()])
    extracted = DeterministicExtractor().extract(pdf)
    assert extracted.part_i.ein.value == "00-0000007"
    assert extracted.part_i.ein.provenance.extractor == "ocr"
    assert extracted.part_i.ein.provenance.page == 1
    assert extracted.part_i.ein.confidence > extracted.part_ii.capital.withdrawals.confidence
    assert extracted.part_i.ein.confidence > REVIEW_THRESHOLD
    assert extracted.part_ii.capital.withdrawals.confidence < REVIEW_THRESHOLD
    assert extracted.part_ii.capital.withdrawals.value == Decimal("10.00")
    text = maybe_ocr(pdf)
    assert text is not None
    assert "A Partnership EIN: 00-0000007" in text


def test_ocr_failure_is_recorded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "1")
    pdf = render_one(tmp_path, Variant.CLEAN)

    def explode(image: object) -> list[OcrLine]:
        raise ImportError("tesseract missing")

    monkeypatch.setattr("k1lens.extract.ocr.recognize_lines", explode)
    with caplog.at_level("ERROR"):
        failed = read_ocr(pdf)
    assert failed is not None
    assert failed.fields == {}
    assert failed.failed_pages
    assert "OCR recognize failed" in caplog.text
    assert "ImportError" in caplog.text
    assert "tesseract missing" in caplog.text

    def boom(path: Path) -> list[object]:
        raise RuntimeError("render failed")

    monkeypatch.setattr("k1lens.extract.ocr.render_pages", boom)
    caplog.clear()
    with caplog.at_level("ERROR"):
        rendered = read_ocr(pdf)
        assert maybe_ocr(pdf) is None
    assert rendered is not None
    assert rendered.failed_pages
    assert "OCR render failed" in caplog.text
    assert "RuntimeError" in caplog.text
    assert "render failed" in caplog.text


def test_ocr_blank_text_is_not_a_page_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "true")
    pdf = render_one(tmp_path, Variant.RASTERIZED)
    monkeypatch.setattr("k1lens.extract.ocr.recognize_lines", lambda image: [OcrLine("   ", 10)])
    monkeypatch.setattr("k1lens.extract.ocr.render_pages", lambda path: [object()])
    result = read_ocr(pdf)
    assert result is not None
    assert result.fields == {}
    assert result.failed_pages == ()
    assert maybe_ocr(pdf) is None


def test_a_killed_ocr_page_is_a_review_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Page 2 dies with SIGTERM. Page 1's EIN is kept, and the document stays in review."""

    import pytesseract

    from k1lens.review.store import unresolved_issues
    from k1lens.validate.engine import validate_document

    monkeypatch.setenv("K1LENS_ENABLE_OCR", "yes")
    pdf = render_one(tmp_path, Variant.RASTERIZED)

    def lines(image: object) -> list[OcrLine]:
        if image == "page-2":
            raise pytesseract.TesseractError(-15, "SIGTERM")
        return [
            OcrLine("A Partnership EIN: 00-0000007", 95),
            OcrLine("B Partnership name: SAMPLE Harbor LP", 95),
            OcrLine("E Partner TIN: 000-00-0001", 95),
            OcrLine("F Partner name: SAMPLE Partner", 95),
        ]

    monkeypatch.setattr("k1lens.extract.ocr.recognize_lines", lines)
    monkeypatch.setattr("k1lens.extract.ocr.render_pages", lambda path: ["page-1", "page-2"])
    extracted = DeterministicExtractor().extract(pdf)
    assert extracted.ocr_failed_pages == [2]
    assert extracted.part_i.ein.value == "00-0000007"
    assert extracted.layout_recognized is True
    assert extracted.part_i.ein.confidence >= REVIEW_THRESHOLD
    findings = validate_document(extracted)
    ocr = [item for item in findings if item.rule_id == "ocr_page"]
    assert len(ocr) == 1
    assert ocr[0].severity.value == "error"
    assert ocr[0].field_path == "ocr_failed_pages"
    issues = unresolved_issues(extracted, findings, REVIEW_THRESHOLD, set())
    ocr_issues = [issue for issue in issues if issue.startswith("ocr_failed_pages:")]
    assert ocr_issues
    others = {issue.split(":", 1)[0] for issue in issues if issue not in ocr_issues}
    still = unresolved_issues(extracted, findings, REVIEW_THRESHOLD, others)
    assert still == ocr_issues


def test_an_unreadable_file_is_still_an_ocr_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "1")
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"not a pdf")

    def boom(path: Path) -> list[object]:
        raise RuntimeError("render failed")

    monkeypatch.setattr("k1lens.extract.ocr.render_pages", boom)
    result = read_ocr(pdf)
    assert result is not None
    assert result.fields == {}
    assert result.failed_pages == (1,)

    import pypdfium2

    class _Empty:
        def __len__(self) -> int:
            return 0

        def close(self) -> None:
            return None

    monkeypatch.setattr(pypdfium2, "PdfDocument", lambda path: _Empty())
    empty = read_ocr(pdf)
    assert empty is not None
    assert empty.failed_pages == (1,)


def test_tesseract_call_has_a_subprocess_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    seen: dict[str, object] = {}
    module = types.ModuleType("pytesseract")

    def image_to_data(
        image: object, output_type: object = None, timeout: int = 0
    ) -> dict[str, list[object]]:
        seen["timeout"] = timeout
        seen["output_type"] = output_type
        return {"text": [], "conf": [], "block_num": [], "par_num": [], "line_num": []}

    module.image_to_data = image_to_data  # type: ignore[attr-defined]
    module.Output = types.SimpleNamespace(DICT="dict")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    assert recognize_lines(object()) == []  # type: ignore[arg-type]
    assert seen["timeout"] == TESSERACT_TIMEOUT_SECONDS
    assert isinstance(seen["timeout"], int)
    assert int(str(seen["timeout"])) > 0
    readme = Path("README.md").read_text(encoding="utf-8")
    design = Path("docs/DESIGN.md").read_text(encoding="utf-8")
    assert os.environ.get("OMP_THREAD_LIMIT") == "1"
    assert f"{TESSERACT_TIMEOUT_SECONDS} second" in readme
    assert f"{TESSERACT_TIMEOUT_SECONDS} second" in design
    assert "`ocr_page`" in readme
    assert "`ocr_page`" in design
    assert "OMP_THREAD_LIMIT" in readme
    assert "OMP_THREAD_LIMIT" in design
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "OMP_THREAD_LIMIT=1" in dockerfile


def test_tesseract_child_env_limits_openmp_threads() -> None:
    import pytesseract.pytesseract as runner

    from k1lens.extract.ocr import _bind_tesseract_env

    _bind_tesseract_env()
    env = runner.subprocess_args()["env"]
    assert isinstance(env, dict)
    assert env["OMP_THREAD_LIMIT"] == "1"


def test_recognize_lines_groups_words(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys
    import types

    module = types.ModuleType("pytesseract")

    def image_to_data(
        image: object, output_type: object = None, timeout: int = 0
    ) -> dict[str, list[object]]:
        assert output_type is module.Output.DICT  # type: ignore[attr-defined]
        assert timeout == TESSERACT_TIMEOUT_SECONDS
        return {
            "text": ["A", "Partnership", "EIN:", "00-0000001", ""],
            "conf": ["90", "80", "95", "70", "-1"],
            "block_num": [1, 1, 1, 1, 1],
            "par_num": [1, 1, 1, 1, 1],
            "line_num": [1, 1, 1, 1, 1],
        }

    module.image_to_data = image_to_data  # type: ignore[attr-defined]
    module.Output = types.SimpleNamespace(DICT="dict")  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pytesseract", module)
    lines = recognize_lines(object())  # type: ignore[arg-type]
    assert len(lines) == 1
    assert lines[0].text == "A Partnership EIN: 00-0000001"
    assert lines[0].confidence == pytest.approx(83.75)
    assert [word.text for word in lines[0].words] == [
        "A",
        "Partnership",
        "EIN:",
        "00-0000001",
    ]


@pytest.mark.slow
def test_real_ocr_on_a_raster_reads_the_ein(
    tmp_path: Path,
) -> None:
    """A real raster is read by Tesseract. Word confidence may clear 0.80.

    The previous name said the raster stays below review. The assertions never
    checked that, and a clean scan often does clear the threshold. The low
    confidence case is ``test_ocr_line_is_used_with_low_confidence``.
    """

    if shutil.which("tesseract") is None:
        pytest.skip("tesseract is not installed")
    dest = tmp_path / "scan"
    generate_corpus(dest, seed=4, count=1, plan=(Variant.RASTERIZED,))
    extracted = DeterministicExtractor().extract(dest / "K1-0001.pdf")
    truth = load_ground_truth(dest / "K1-0001.json").document
    assert extracted.part_i.ein.provenance.extractor == "ocr"
    assert extracted.part_i.ein.value == truth.part_i.ein.value
    assert 0.0 < extracted.part_i.ein.confidence <= 1.0
    assert extracted.part_iii.ordinary_business_income.provenance.page == 2


def render_one(tmp_path: Path, variant: Variant) -> Path:
    dest = tmp_path / variant.value
    generate_corpus(dest, seed=4, count=1, plan=(variant,))
    return dest / "K1-0001.pdf"


def test_rotation_caps_fields_when_the_baseline_splits() -> None:
    clean = DeterministicExtractor().extract(Path("fixtures/synthetic/K1-0001.pdf"))
    rotated = DeterministicExtractor().extract(Path("fixtures/synthetic/K1-0005.pdf"))
    # Without a roster the name and city stay under 0.80. Rotation also holds
    # the EIN, because the baseline split is a separate check.
    assert clean.part_i.name.value == "SAMPLE Harborline Capital LP"
    assert clean.part_i.name.confidence < REVIEW_THRESHOLD
    assert clean.part_i.city.confidence < REVIEW_THRESHOLD
    assert rotated.variant == "rotated"
    assert rotated.part_i.ein.value is not None
    assert rotated.part_i.ein.confidence < REVIEW_THRESHOLD
    assert rotated.part_i.name.confidence < REVIEW_THRESHOLD
    assert rotated.tax_year is not None
    assert rotated.tax_year_confidence is not None
    assert rotated.tax_year_confidence < REVIEW_THRESHOLD
    assert clean.tax_year_confidence is not None
    assert clean.tax_year_confidence >= REVIEW_THRESHOLD


def test_extractor_reads_a_spread_of_generated_codes(tmp_path: Path) -> None:
    from k1lens.generate.build import PART_III_CODES, build_document

    rng = random.Random(1065)
    document = None
    for index in range(1, 15):
        candidate = build_document(rng, index, Variant.CLEAN)
        codes = {item.code for item in candidate.part_iii.other_income}
        if len(codes) >= 2 and codes <= set(PART_III_CODES["11"]):
            document = candidate
            break
    assert document is not None
    dest = tmp_path / "codes.pdf"
    render_pdf(document, dest)
    extracted = DeterministicExtractor().extract(dest)
    assert {item.code: item.amount.value for item in extracted.part_iii.other_income} == {
        item.code: item.amount.value for item in document.part_iii.other_income
    }
    assert {item.code for item in extracted.part_iii.distributions} <= set(PART_III_CODES["19"])


def test_render_pdf_clean_path(tmp_path: Path) -> None:
    from k1lens.generate.build import build_document

    document = build_document(__import__("random").Random(1), 1, Variant.CLEAN)
    dest = tmp_path / "one.pdf"
    render_pdf(document, dest)
    assert dest.read_bytes().startswith(b"%PDF")

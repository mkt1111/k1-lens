"""Synthetic corpus: reproducible, consistent, and visibly fake."""

import random
from decimal import Decimal
from pathlib import Path

import pdfplumber
import pytest

from k1lens.generate.build import INCONSISTENT_DELTA, PART_III_CODES, Variant, build_document
from k1lens.generate.corpus import generate_corpus, load_ground_truth, load_manifest
from k1lens.generate.ensure import corpus_ready, ensure_corpus
from k1lens.generate.income import synthetic_net_income
from k1lens.validate.engine import validate_document


def test_same_seed_rewrites_the_same_json_and_pdf(tmp_path: Path) -> None:
    plan = (Variant.CLEAN, Variant.ROTATED, Variant.RASTERIZED)
    first = tmp_path / "a"
    second = tmp_path / "b"
    generate_corpus(first, seed=1065, count=3, plan=plan)
    generate_corpus(second, seed=1065, count=3, plan=plan)
    for name in ("manifest.json", "K1-0001.json", "K1-0001.pdf", "K1-0003.pdf"):
        assert (first / name).read_bytes() == (second / name).read_bytes()


def test_variant_does_not_change_the_underlying_economics() -> None:
    rng_a = random.Random(99)
    rng_b = random.Random(99)
    clean = build_document(rng_a, 1, Variant.CLEAN)
    broken = build_document(rng_b, 1, Variant.INCONSISTENT_CAPITAL)
    assert clean.part_ii.capital.beginning == broken.part_ii.capital.beginning
    assert (
        broken.part_ii.capital.ending.value
        == clean.part_ii.capital.ending.value + INCONSISTENT_DELTA
    )


def test_clean_documents_are_internally_consistent() -> None:
    document = build_document(random.Random(5), 2, Variant.CLEAN)
    assert document.part_i.name.value is not None
    assert "SAMPLE" in document.part_i.name.value
    assert document.part_i.ein.value is not None
    assert document.part_i.ein.value.startswith("00-")
    income = synthetic_net_income(document.part_iii)
    assert document.part_ii.capital.current_year_net_income.value == income
    services = document.part_iii.guaranteed_payments_services.value
    capital = document.part_iii.guaranteed_payments_capital.value
    total = document.part_iii.guaranteed_payments_total.value
    assert services is not None and capital is not None and total is not None
    assert total == services + capital
    ordinary = document.part_iii.ordinary_dividends.value or Decimal("0")
    qualified = document.part_iii.qualified_dividends.value or Decimal("0")
    assert qualified <= ordinary
    errors = [
        item.rule_id
        for item in validate_document(document, tolerance=Decimal("0"))
        if item.severity.value == "error"
    ]
    assert set(errors) == {"no_roster"}


def test_pdf_text_contains_labels_and_raster_does_not(tmp_path: Path) -> None:
    dest = tmp_path / "pdfs"
    generate_corpus(
        dest,
        seed=3,
        count=3,
        plan=(Variant.CLEAN, Variant.ROTATED, Variant.RASTERIZED),
    )
    with pdfplumber.open(dest / "K1-0001.pdf") as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "SYNTHETIC SAMPLE" in text
    assert "A Partnership EIN:" in text
    assert "PART III" in text
    with pdfplumber.open(dest / "K1-0002.pdf") as pdf:
        rotated = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "A Partnership EIN:" in rotated
    with pdfplumber.open(dest / "K1-0003.pdf") as pdf:
        scanned = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "Partnership EIN" not in scanned


def test_missing_fields_are_absent_from_the_pdf(tmp_path: Path) -> None:
    dest = tmp_path / "missing"
    generate_corpus(dest, seed=3, count=1, plan=(Variant.MISSING_FIELDS,))
    truth = load_ground_truth(dest / "K1-0001.json")
    assert truth.planted_defects == ["required_fields"]
    assert truth.document.part_i.ein.value is None
    with pdfplumber.open(dest / "K1-0001.pdf") as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "A Partnership EIN:" not in text
    assert "F Partner name:" not in text
    assert "L Ending capital:" not in text


def test_part_iii_codes_are_a_spread_not_only_a() -> None:
    seen: dict[str, set[str]] = {box: set() for box in PART_III_CODES}
    rng = random.Random(1065)
    for index in range(1, 15):
        document = build_document(rng, index, Variant.CLEAN)
        seen["11"].update(item.code for item in document.part_iii.other_income)
        seen["13"].update(item.code for item in document.part_iii.other_deductions)
        seen["14"].update(item.code for item in document.part_iii.self_employment)
        seen["15"].update(item.code for item in document.part_iii.credits)
        seen["17"].update(item.code for item in document.part_iii.amt_items)
        seen["18"].update(item.code for item in document.part_iii.tax_exempt_and_nondeductible)
        seen["19"].update(item.code for item in document.part_iii.distributions)
        seen["20"].update(item.code for item in document.part_iii.other_information)
        distributed = sum(
            (item.amount.value or Decimal("0") for item in document.part_iii.distributions),
            start=Decimal("0"),
        )
        withdrawals = document.part_ii.capital.withdrawals.value or Decimal("0")
        assert distributed == withdrawals
        assert all(code in PART_III_CODES["19"] for code in seen["19"])
    for box, codes in seen.items():
        assert len(codes) >= 2, box
        assert codes <= set(PART_III_CODES[box])
        assert codes != {"A"}


def test_seed_rewrites_the_same_bytes(tmp_path: Path) -> None:
    first = tmp_path / "a"
    second = tmp_path / "b"
    generate_corpus(first, seed=1065, count=14)
    generate_corpus(second, seed=1065, count=14)
    manifest = load_manifest(first)
    assert manifest.seed == 1065
    assert manifest.count == 14
    assert load_manifest(second) == manifest
    for entry in manifest.documents:
        assert (first / entry.ground_truth).read_bytes() == (
            second / entry.ground_truth
        ).read_bytes()
        assert (first / entry.pdf).read_bytes() == (second / entry.pdf).read_bytes()


def test_manifest_records_seed(tmp_path: Path) -> None:
    dest = tmp_path / "corpus"
    manifest = generate_corpus(dest, seed=1065, count=2, plan=(Variant.CLEAN, Variant.CLEAN))
    loaded = load_manifest(dest)
    assert loaded == manifest
    assert loaded.synthetic_only is True
    assert loaded.seed == 1065


def test_page_overflow_and_rotation_still_write_a_pdf(tmp_path: Path) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen.canvas import Canvas

    from k1lens.generate.pdf import _draw_page

    dest = tmp_path / "overflow.pdf"
    canvas = Canvas(str(dest), pagesize=letter, invariant=1)
    _draw_page(canvas, ["SYNTHETIC SAMPLE"] + ["line of text"] * 200, rotate=True)
    canvas.save()
    assert dest.stat().st_size > 100


def test_ensure_corpus_writes_only_when_the_manifest_is_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def record(name: str):
        def inner(dest: Path, **_kwargs: object) -> None:
            seen.append(name)
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "manifest.json").write_text("{}\n", encoding="utf-8")

        return inner

    monkeypatch.setattr("k1lens.generate.ensure.generate_corpus", record("synthetic"))
    monkeypatch.setattr("k1lens.generate.ensure.generate_dev", record("dev"))
    monkeypatch.setattr("k1lens.generate.ensure.generate_dev_b", record("dev_b"))
    monkeypatch.setattr("k1lens.generate.ensure.generate_dev_geometry", record("dev_geometry"))
    monkeypatch.setattr("k1lens.generate.ensure.generate_scans", record("scans"))
    for kind in ("synthetic", "dev", "dev_b", "dev_geometry", "scans"):
        ensure_corpus(tmp_path / kind, kind)
        ensure_corpus(tmp_path / kind, kind)
    assert seen == ["synthetic", "dev", "dev_b", "dev_geometry", "scans"]
    ready = tmp_path / "ready"
    ready.mkdir()
    (ready / "manifest.json").write_text("{}\n", encoding="utf-8")
    assert corpus_ready(ready)
    with pytest.raises(ValueError, match="Unknown corpus"):
        ensure_corpus(tmp_path / "other", "other")

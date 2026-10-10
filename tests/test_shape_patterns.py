"""Shape-gate regressions with generated wording, plus the audit follow-ups.

The phrases are built from patterns. They are not a fixed probe list.
"""

from __future__ import annotations

import random
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas
from typer.testing import CliRunner

from k1lens.cli import app
from k1lens.domain.access import get_extracted
from k1lens.domain.fields import REVIEW_THRESHOLD, SCALAR_FIELDS
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import begins_with_cross_reference
from k1lens.extract.confidence import city_shape_ok, name_shape_ok
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.ocr import OcrLine, _absorb, read_ocr
from k1lens.generate.build import Variant, build_document
from k1lens.review.errors import ApprovalBlockedError
from k1lens.review.store import ReviewStore, _chain_hash, verify_database
from k1lens.validate.engine import validate_document
from test_review_probes import _LAB, _base_lines, _draw_probe, _no_confident_wrong

_OPENERS = ("Not", "No", "Never")
_TAILS = ("ready", "listed", "posted", "finalized")
_AGENCIES = (
    "Department of Revenue",
    "Internal Revenue Bureau",
    "United States Customs Office",
)
_CITIES = ("St. Louis", "Ft. Wayne", "Kansas City", "Wilkes-Barre")
_REAL_NAMES = ("4 Creeks Holdings LP", "12 Summit Partners LLC", "Mina Calder")
_STREETS = ("88 Harbor Road", "15 Cedar Lane", "400 Pine Street")
_STATUS = ("Held for review", "Awaiting signature", "Redacted entry")


def test_generated_non_names_stay_under_review(tmp_path: Path) -> None:
    phrases = [f"{opener} {tail}" for opener in _OPENERS for tail in _TAILS]
    phrases.extend(_AGENCIES)
    phrases.extend(_STATUS)
    phrases.extend(_STREETS)
    for phrase in phrases:
        assert name_shape_ok(phrase) is False, phrase
    batches: list[list[tuple[str, str]]] = []
    current: list[tuple[str, str]] = []
    for phrase in phrases:
        if any(path == "part_i.name" for path, _value in current):
            batches.append(current)
            current = []
        current.append(("part_i.name", phrase))
    batches.append(current)
    for index, rows in enumerate(batches):
        document = _draw_probe(
            [*_base_lines(), *[f"{_LAB[path]}  {value}" for path, value in rows]],
            tmp_path / f"shape-{index}.pdf",
        )
        _no_confident_wrong(document, rows)
        for path, value in rows:
            got = get_extracted(document, path)
            if got.value is not None:
                assert got.confidence < REVIEW_THRESHOLD, (value, got.confidence)


def test_generated_names_and_cities_that_fit_stay_under_0_80(tmp_path: Path) -> None:
    for city in _CITIES:
        assert city_shape_ok(city) is True, city
    for name in _REAL_NAMES:
        assert name_shape_ok(name) is True, name
    document = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']}  {_REAL_NAMES[0]}",
            f"{_LAB['part_ii.name']}  {_REAL_NAMES[2]}",
            f"{_LAB['part_i.city']}  {_CITIES[0]}",
            f"{_LAB['part_ii.city']}  {_CITIES[2]}",
        ],
        tmp_path / "fitting.pdf",
    )
    clears = [
        ("part_i.name", _REAL_NAMES[0]),
        ("part_i.city", _CITIES[0]),
        ("part_ii.city", _CITIES[2]),
    ]
    held = [
        ("part_ii.name", _REAL_NAMES[2]),
    ]
    _no_confident_wrong(document, clears + held)
    for path, gold in clears:
        got = get_extracted(document, path)
        assert got.value == gold
        assert got.confidence < REVIEW_THRESHOLD
    for path, gold in held:
        got = get_extracted(document, path)
        assert got.value == gold
        assert got.confidence < REVIEW_THRESHOLD


def test_a_numbered_name_is_not_replaced_by_the_street(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            _LAB["part_ii.name"],
            "4 Creeks Holdings LP",
            "88 Harbor Road",
        ],
        tmp_path / "numbered.pdf",
    )
    assert document.part_ii.name.value == "4 Creeks Holdings LP"
    assert document.part_ii.name.confidence < REVIEW_THRESHOLD
    assert document.part_ii.street.value != "4 Creeks Holdings LP"


def test_a_non_name_next_line_leaves_the_label_open(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            _LAB["part_ii.name"],
            "Filing line",
            "Mina Calder",
        ],
        tmp_path / "next.pdf",
    )
    assert document.part_ii.name.value == "Mina Calder"
    assert document.part_ii.name.confidence < REVIEW_THRESHOLD


def test_a_longer_printed_caption_is_not_stored_as_the_name(tmp_path: Path) -> None:
    label = next(spec.pdf_label for spec in SCALAR_FIELDS if spec.path == "part_i.name")
    document = _draw_probe(
        [
            *_base_lines(),
            (f"{label} address, city, state, and ZIP code Northwind Partners LP"),
        ],
        tmp_path / "caption.pdf",
    )
    assert document.part_i.name.value == "Northwind Partners LP"
    assert "address" not in str(document.part_i.name.value)


def test_repeated_marks_of_one_character_are_leaders(tmp_path: Path) -> None:
    marks = ("+++", "###", "$$$")
    cities = ("Denver", "Austin", "Boston")
    lines = [*_base_lines()]
    paths = ("part_i.city", "part_ii.city", "part_i.city")
    for mark, city, path in zip(marks, cities, paths, strict=True):
        lines.append(f"{_LAB[path]}  {mark} {city}")
    document = _draw_probe(lines, tmp_path / "marks.pdf")
    assert document.part_i.city.value == "Boston"
    assert document.part_ii.city.value == "Austin"
    glued = _draw_probe(
        [*_base_lines(), f"{_LAB['part_ii.city']}  ###Austin"],
        tmp_path / "glued.pdf",
    )
    assert glued.part_ii.city.value == "Austin"


def test_abbreviation_shaped_tokens_keep_their_period() -> None:
    label = _LAB["part_i.name"]
    samples = ("Quinn Bros.", "Mara Assoc.", "J. T. Hale")
    observed: dict[str, list[object]] = {}
    for sample in samples:
        _absorb(observed, OcrLine(f"{label}: {sample}", 0.95), 1)
        assert observed[label][-1].raw == sample
    _absorb(observed, OcrLine(f"{label}: Harbor LLC.", 0.95), 1)
    assert observed[label][-1].raw == "Harbor LLC"


def test_enclosed_starts_a_cross_reference(tmp_path: Path) -> None:
    assert begins_with_cross_reference("Enclosed schedule") is True
    assert begins_with_cross_reference("Enclosure Partners LP") is False
    document = _draw_probe(
        [*_base_lines(), f"{_LAB['part_ii.name']}  Enclosed schedule"],
        tmp_path / "enclosed.pdf",
    )
    assert document.part_ii.name.value is None


def test_the_audit_hash_covers_the_actor() -> None:
    left = _chain_hash(
        "0" * 64,
        document_id="K1-1",
        field_path="part_i.city",
        action="correct",
        old_value="Austin",
        new_value="Denver",
        actor="Ada Reviewer",
        created_at="2026-01-01T00:00:00Z",
    )
    right = _chain_hash(
        "0" * 64,
        document_id="K1-1",
        field_path="part_i.city",
        action="correct",
        old_value="Austin",
        new_value="Denver",
        actor="Bea Reviewer",
        created_at="2026-01-01T00:00:00Z",
    )
    assert left != right


def test_confirming_a_blank_required_field_resolves_the_finding(tmp_path: Path) -> None:
    from k1lens.roster import roster_from_documents

    document = build_document(random.Random(4), 1, Variant.CLEAN)
    store = ReviewStore(tmp_path / "review.db", roster=roster_from_documents([document]))
    payload = document.model_dump(mode="json")
    payload["part_ii"]["name"]["value"] = None
    payload["part_ii"]["name"]["confidence"] = 1.0
    blanked = ScheduleK1.model_validate(payload)
    store.upsert(blanked, b"%PDF-1.4", validate_document(blanked, roster=store.roster))
    with pytest.raises(ApprovalBlockedError):
        store.approve(blanked.document_id, "Ada Reviewer")
    store.override(blanked.document_id, "part_ii.name", "Blank is correct", "Ada Reviewer")
    assert "part_ii.name" in store.override_paths(blanked.document_id)
    with pytest.raises(ApprovalBlockedError):
        store.approve(blanked.document_id, "Ada Reviewer")
    stored = store.get(blanked.document_id)
    assert stored is not None
    assert any(
        item.rule_id == "identity_mismatch" and item.field_path == "part_ii.street"
        for item in stored.findings
    )


def test_approval_reopens_for_a_correction_a_coded_line_and_a_small_amount(
    tmp_path: Path,
) -> None:
    from k1lens.roster import roster_from_documents

    document = build_document(random.Random(5), 1, Variant.CLEAN)
    fresh = build_document(random.Random(6), 2, Variant.CLEAN)
    coded = build_document(random.Random(7), 3, Variant.CLEAN)
    store = ReviewStore(
        tmp_path / "review.db",
        roster=roster_from_documents([document, fresh, coded]),
    )
    store.upsert(document, b"%PDF-1.4", [])
    store.approve(document.document_id, "Ada Reviewer")
    store.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    corrected = store.get(document.document_id)
    assert corrected is not None
    assert corrected.status == "pending"
    assert any(entry.action == "reopen" for entry in store.audit(document.document_id))

    store.upsert(fresh, b"%PDF-1.4", [])
    store.approve(fresh.document_id, "Ada Reviewer")
    payload = fresh.model_dump(mode="json")
    amount = payload["part_iii"]["ordinary_business_income"]["value"]
    payload["part_iii"]["ordinary_business_income"]["value"] = str(
        Decimal(str(amount)) + Decimal("0.40")
    )
    changed = ScheduleK1.model_validate(payload)
    store.upsert(changed, b"%PDF-1.4", [])
    stored = store.get(fresh.document_id)
    assert stored is not None and stored.status == "pending"

    store.upsert(coded, b"%PDF-1.4", [])
    store.approve(coded.document_id, "Ada Reviewer")
    body = coded.model_dump(mode="json")
    box = body["part_iii"]["other_income"]
    assert box
    box[0]["code"] = "Z" if box[0]["code"] != "Z" else "Y"
    store.upsert(ScheduleK1.model_validate(body), b"%PDF-1.4", [])
    recoded = store.get(coded.document_id)
    assert recoded is not None and recoded.status == "pending"


def test_full_truncation_and_a_later_append_still_fail_verify(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    store = ReviewStore(db)
    document = build_document(random.Random(8), 1, Variant.CLEAN)
    store.upsert(document, b"%PDF-1.4", [])
    store.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    store.correct(document.document_id, "part_i.city", "Memphis", "Ada Reviewer")
    conn = sqlite3.connect(db)
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.execute("DELETE FROM audit_log")
    conn.executescript(
        """
        CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        """
    )
    conn.commit()
    conn.close()
    emptied = verify_database(db)
    assert emptied == ["audit log tail does not match the stored head"]

    gap_db = tmp_path / "gap.db"
    gap = ReviewStore(gap_db)
    gap.upsert(document, b"%PDF-1.4", [])
    gap.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    gap.correct(document.document_id, "part_i.city", "Memphis", "Ada Reviewer")
    conn = sqlite3.connect(gap_db)
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.execute("DELETE FROM audit_log WHERE id = (SELECT MAX(id) FROM audit_log)")
    conn.executescript(
        """
        CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        """
    )
    conn.commit()
    conn.close()
    gap.correct(document.document_id, "part_i.city", "Boston", "Ada Reviewer")
    problems = verify_database(gap_db)
    assert "audit log tail does not match the stored head" in problems

    tip_db = tmp_path / "tip.db"
    tip_store = ReviewStore(tip_db)
    tip_store.upsert(document, b"%PDF-1.4", [])
    conn = sqlite3.connect(tip_db)
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.execute("UPDATE audit_head SET tip_hash = ? WHERE id = 1", ("ab" * 32,))
    conn.executescript(
        """
        CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        """
    )
    conn.commit()
    conn.close()
    tipped = verify_database(tip_db)
    assert "audit log tail does not match the stored head" in tipped


def test_a_corrupt_pdf_is_skipped_with_a_finding(tmp_path: Path) -> None:
    pdf = tmp_path / "broken.pdf"
    pdf.write_bytes(b"%PDF-1.4\nthis is not a pdf")
    document = DeterministicExtractor().extract(pdf)
    assert document.ocr_failed_pages == [1]
    assert any(item.rule_id == "ocr_page" for item in validate_document(document))


def test_an_image_only_later_page_is_named(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path = tmp_path / "mixed.pdf"
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 9)
    canvas.drawString(40, 720, f"{_LAB['part_i.ein']}  00-0000001")
    canvas.showPage()
    canvas.showPage()
    canvas.save()
    seen: dict[str, object] = {}

    def fake_read(pdf_path: Path, *, only_pages: tuple[int, ...] | None = None) -> object:
        del pdf_path
        seen["pages"] = only_pages
        return read_ocr.__wrapped__ if False else None  # type: ignore[attr-defined]

    from k1lens.extract.ocr import OcrRead

    def fake(pdf_path: Path, *, only_pages: tuple[int, ...] | None = None) -> OcrRead:
        del pdf_path
        seen["pages"] = only_pages
        return OcrRead({}, ())

    monkeypatch.setattr("k1lens.extract.deterministic.read_ocr", fake)
    document = DeterministicExtractor().extract(path)
    assert seen["pages"] == (2,)
    assert 2 not in document.ocr_failed_pages


def test_a_bad_tolerance_is_a_clean_cli_error() -> None:
    result = CliRunner().invoke(app, ["validate", "--tolerance", "nope", "--input", "."])
    assert result.exit_code == 2
    text = result.output + (result.stderr or "")
    assert "Traceback" not in text
    assert "Not a number" in text


def test_chain_genesis_is_stable() -> None:
    assert _chain_hash(
        "0" * 64,
        document_id="K1-1",
        field_path=None,
        action="ingest",
        old_value=None,
        new_value=None,
        actor="system",
        created_at="t",
    )

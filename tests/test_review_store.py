"""The audit log is append-only across re-ingest."""

import random
import sqlite3
from decimal import Decimal
from pathlib import Path

import pytest

import k1lens.review.store as store_module
from k1lens.domain.models import ScheduleK1
from k1lens.generate.build import Variant, build_document
from k1lens.review.errors import ApprovalBlockedError, InvalidFieldValueError
from k1lens.review.store import ReviewStore, approved_snapshot
from k1lens.roster import roster_from_documents
from k1lens.validate.engine import validate_document


def test_reingest_keeps_reviewer_corrections(tmp_path: Path) -> None:
    store = ReviewStore(tmp_path / "review.db")
    document = build_document(random.Random(8), 1, Variant.CLEAN)
    pdf = b"%PDF-1.4 synthetic"
    store.upsert(document, pdf, [], actor="system")
    store.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    store.upsert(document, pdf, [], actor="system")

    entries = store.audit(document.document_id)
    actions = [entry.action for entry in entries]
    assert actions.count("ingest") == 2
    corrections = [entry for entry in entries if entry.action == "correct"]
    assert len(corrections) == 1
    assert corrections[0].actor == "Ada Reviewer"
    assert corrections[0].new_value == "Nashville"
    assert corrections[0].field_path == "part_i.city"


def _with_interest(base: ScheduleK1, value: str, confidence: float) -> ScheduleK1:
    payload = base.model_dump(mode="json")
    payload["part_iii"]["interest_income"]["value"] = value
    payload["part_iii"]["interest_income"]["confidence"] = confidence
    return ScheduleK1.model_validate(payload)


def test_override_does_not_cover_a_reingested_value(tmp_path: Path) -> None:
    base = build_document(random.Random(4), 2, Variant.CLEAN)
    store = ReviewStore(tmp_path / "review.db", roster=roster_from_documents([base]))
    original = _with_interest(base, "100.00", 0.20)
    store.upsert(original, b"%PDF-1.4", validate_document(original))
    store.override(
        original.document_id,
        "part_iii.interest_income",
        "Checked 100.00 against the statement",
        "ada",
    )
    approved = store.approve(original.document_id, "ada")
    assert approved.status == "approved"
    changed = _with_interest(base, "999999.00", 0.20)
    store.upsert(changed, b"%PDF-1.4", validate_document(changed))
    after = store.get(original.document_id)
    assert after is not None
    assert after.status == "pending"
    assert after.document.part_iii.interest_income.value == Decimal("999999.00")
    with pytest.raises(ApprovalBlockedError, match=r"part_iii\.interest_income"):
        store.approve(original.document_id, "bob")
    conn = sqlite3.connect(tmp_path / "review.db")
    conn.execute(
        "UPDATE documents SET status = 'approved', approved_by = 'ada', approved_at = 't' "
        "WHERE document_id = ?",
        (original.document_id,),
    )
    conn.commit()
    conn.close()
    with pytest.raises(ApprovalBlockedError, match="unresolved review items"):
        store.assert_exportable()
    with pytest.raises(InvalidFieldValueError, match="Unknown field"):
        store.override(original.document_id, "part_iii.no_such_field", "typo", "ada")
    assert any(entry.action == "reopen" for entry in store.audit(original.document_id))


def test_a_correction_between_gate_and_write_does_not_get_approved(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = build_document(random.Random(4), 2, Variant.CLEAN)
    store = ReviewStore(tmp_path / "review.db", roster=roster_from_documents([document]))
    store.upsert(document, b"%PDF-1.4", validate_document(document, roster=store.roster))
    fired = {"done": False}

    def interleaved(record: ScheduleK1) -> str:
        snapshot = approved_snapshot(record)
        if not fired["done"]:
            fired["done"] = True
            store.correct(document.document_id, "part_iii.interest_income", "424242.00", "Bob")
        return snapshot

    monkeypatch.setattr(store_module, "approved_snapshot", interleaved)
    with pytest.raises(ApprovalBlockedError):
        store.approve(document.document_id, "Ada")
    final = store.get(document.document_id)
    assert final is not None
    assert final.status == "pending"
    assert final.document.part_iii.interest_income.value == Decimal("424242.00")
    approve_rows = [
        entry for entry in store.audit(document.document_id) if entry.action == "approve"
    ]
    assert approve_rows == [] or "424242.00" in (approve_rows[-1].new_value or "")

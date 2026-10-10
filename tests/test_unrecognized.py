"""An unrecognized layout cannot clear the review threshold."""

from pathlib import Path

from fastapi.testclient import TestClient
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import CODED_BOXES, REVIEW_THRESHOLD, SCALAR_FIELDS
from k1lens.domain.models import ScheduleK1
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.review.app import create_app


def _confidences(document: ScheduleK1) -> list[float]:
    scores = [get_extracted(document, spec.path).confidence for spec in SCALAR_FIELDS]
    for box in CODED_BOXES:
        scores.extend(item.amount.confidence for item in get_coded(document, box.path))
    return scores


def _prose_pdf(dest: Path) -> None:
    canvas = Canvas(str(dest), pagesize=(612, 792), invariant=1)
    lines = [
        "MEMORANDUM",
        "To: Investment committee",
        "From: SAMPLE Operations",
        "Subject: Quarterly update",
        "Date: October 2024",
        "Note: This letter is not a tax form.",
        "Action: Please review the attached minutes.",
        "Amount: See the workbook.",
        "Status: Draft",
        "Owner: SAMPLE Operations",
        "Interest income: 10.00",
        "Page: 1",
        "Copy: File",
    ]
    y = 740
    for line in lines:
        canvas.drawString(72, y, line)
        y -= 18
    canvas.save()


def test_catalog_layout_stays_recognized() -> None:
    document = DeterministicExtractor().extract(Path("fixtures/synthetic/K1-0001.pdf"))
    assert document.layout_recognized is True
    assert document.part_i.ein.confidence >= REVIEW_THRESHOLD


def test_prose_layout_is_flagged_and_every_field_is_below_threshold(tmp_path: Path) -> None:
    pdf = tmp_path / "memo.pdf"
    _prose_pdf(pdf)
    document = DeterministicExtractor().extract(pdf)
    assert document.layout_recognized is False
    assert _confidences(document)
    assert all(score < REVIEW_THRESHOLD for score in _confidences(document))

    fixture_dir = tmp_path / "queue"
    fixture_dir.mkdir()
    application = create_app(
        db_path=tmp_path / "review.db",
        fixture_dir=fixture_dir,
        auto_ingest=False,
    )
    with TestClient(application) as client:
        from k1lens.review.store import ReviewStore
        from k1lens.validate.engine import validate_document

        store = ReviewStore(tmp_path / "review.db")
        store.upsert(document, pdf.read_bytes(), validate_document(document), actor="system")
        page = client.get("/")
        assert page.status_code == 200
        assert "Unrecognized layout" in page.text
        detail = client.get(f"/documents/{document.document_id}")
        assert detail.status_code == 200
        assert "Unrecognized layout" in detail.text
        assert "needs a person" in detail.text
        assert 'class="pdf-preview"' in detail.text
        blank = client.post(f"/documents/{document.document_id}/approve", data={"actor": ""})
        assert blank.status_code == 400
        assert "A reviewer name is required" in blank.text
        assert "Unrecognized layout" in blank.text
        literal = client.post(
            f"/documents/{document.document_id}/approve", data={"actor": "reviewer"}
        )
        assert literal.status_code == 400
        assert "A reviewer name is required" in literal.text

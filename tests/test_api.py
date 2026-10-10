"""Review UI and JSON API."""

import random
import sqlite3
from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from k1lens.domain.models import ScheduleK1
from k1lens.generate.build import Variant, build_document
from k1lens.generate.corpus import generate_corpus
from k1lens.review.app import create_app
from k1lens.review.store import ReviewStore
from k1lens.roster import dump_roster, roster_from_documents
from k1lens.validate.engine import validate_document


def test_queue_page_lists_documents_and_findings(client: TestClient) -> None:
    page = client.get("/")
    assert page.status_code == 200
    assert "Synthetic data only" in page.text
    assert "K1-0001" in page.text
    assert "inconsistent_capital" in page.text
    detail = client.get("/documents/K1-0002")
    assert detail.status_code == 200
    assert "capital_reconciles" in detail.text
    assert "Source PDF" in detail.text
    missing = client.get("/documents/K1-9999")
    assert missing.status_code == 404
    assert "not in the review queue" in missing.text


def test_correction_approval_audit_and_export(client: TestClient) -> None:
    updated = client.post(
        "/api/documents/K1-0001/corrections",
        json={"field_path": "part_iii.interest_income", "value": "123.45", "actor": "ada"},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["document"]["part_iii"]["interest_income"]["value"] == "123.45"
    assert body["document"]["part_iii"]["interest_income"]["provenance"]["extractor"] == "human:ada"
    assert body["status"] == "pending"

    form = client.post(
        "/documents/K1-0001/fields",
        data={"field_path": "part_i.name", "value": "SAMPLE Renamed Partners LP", "actor": "ada"},
        follow_redirects=False,
    )
    assert form.status_code == 303

    bad = client.post(
        "/api/documents/K1-0001/corrections",
        json={"field_path": "part_iii.interest_income", "value": "nope", "actor": "ada"},
    )
    assert bad.status_code == 400
    unknown = client.post(
        "/api/documents/K1-0001/corrections",
        json={"field_path": "no.such.field", "value": "1", "actor": "ada"},
    )
    assert unknown.status_code == 400
    blank_actor = client.post(
        "/api/documents/K1-0001/corrections",
        json={"field_path": "part_i.city", "value": "Chicago", "actor": "   "},
    )
    assert blank_actor.status_code == 400

    # A title-case partner name has no structural marker, so it stays in
    # review until a person confirms the printed value.
    partner = client.get("/api/documents/K1-0001").json()["document"]["part_ii"]["name"]["value"]
    confirmed = client.post(
        "/api/documents/K1-0001/corrections",
        json={"field_path": "part_ii.name", "value": partner, "actor": "ada"},
    )
    assert confirmed.status_code == 200
    _install_roster(client, "K1-0001")

    approved = client.post("/api/documents/K1-0001/approve", json={"actor": "ada"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by"] == "ada"

    reopened = client.post(
        "/documents/K1-0001/fields",
        data={"field_path": "part_i.city", "value": "Nashville", "actor": "ada"},
        follow_redirects=True,
    )
    assert reopened.status_code == 200
    audit = client.get("/api/documents/K1-0001/audit")
    actions = [entry["action"] for entry in audit.json()]
    assert "correct" in actions
    assert "approve" in actions
    assert "reopen" in actions

    _install_roster(client, "K1-0001")
    client.post("/api/documents/K1-0001/approve", json={"actor": "ada"})
    csv_export = client.get("/api/export/csv")
    assert csv_export.status_code == 200
    assert "K1-0001" in csv_export.text
    assert "K1-0002" not in csv_export.text
    assert "123.45" in csv_export.text
    workbook = load_workbook(BytesIO(client.get("/api/export/xlsx").content))
    sheet = workbook["approved_k1s"]
    assert sheet.freeze_panes == "A2"
    assert sheet["A2"].value == "K1-0001"


def test_api_documents_pdf_and_filters(client: TestClient) -> None:
    listing = client.get("/api/documents")
    assert listing.status_code == 200
    assert len(listing.json()) == 5
    assert client.get("/api/documents", params={"status": "approved"}).json() == []
    assert client.get("/api/documents", params={"status": "nope"}).status_code == 400
    document = client.get("/api/documents/K1-0004")
    assert document.status_code == 200
    assert document.json()["variant"] == "invalid_ein"
    findings = client.get("/api/documents/K1-0004/findings")
    assert any(item["rule_id"] == "ein_format" for item in findings.json())
    pdf = client.get("/documents/K1-0001/pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert client.get("/api/documents/K1-0001/pdf").content.startswith(b"%PDF")
    assert client.get("/api/documents/K1-missing").status_code == 404
    assert client.get("/api/documents/K1-missing/audit").status_code == 404
    assert client.get("/api/health").json() == {"status": "ok"}
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    paths = schema.json()["paths"]
    assert "/api/documents/{document_id}/corrections" in paths
    assert "/api/export/xlsx" in paths
    docs = client.get("/docs")
    assert docs.status_code == 200
    assert "cdn.jsdelivr.net" not in docs.text
    assert "fastapi.tiangolo.com" not in docs.text
    assert "/static/swagger/swagger-ui-bundle.js" in docs.text
    script = client.get("/static/swagger/swagger-ui-bundle.js")
    assert script.status_code == 200
    assert b"SwaggerUIBundle" in script.content
    assert client.get("/static/swagger/swagger-ui.css").status_code == 200
    assert client.get("/redoc").status_code == 404


def test_tax_year_is_a_review_field(tmp_path) -> None:
    dest = tmp_path / "corpus"
    generate_corpus(dest, seed=11, count=2, plan=(Variant.CLEAN, Variant.ROTATED))
    application = create_app(db_path=tmp_path / "review.db", fixture_dir=dest, auto_ingest=True)
    with TestClient(application) as client:
        rotated = client.get("/documents/K1-0002")
        assert rotated.status_code == 200
        year_at = rotated.text.index('id="value-tax_year"')
        assert "field low" in rotated.text[year_at - 500 : year_at]
        clean = client.get("/documents/K1-0001")
        clean_at = clean.text.index('id="value-tax_year"')
        assert "field low" not in clean.text[clean_at - 500 : clean_at]
        corrected = client.post(
            "/api/documents/K1-0002/corrections",
            json={"field_path": "tax_year", "value": "2023", "actor": "ada"},
        )
        assert corrected.status_code == 200
        body = corrected.json()["document"]
        assert body["tax_year"] == 2023
        assert body["tax_year_confidence"] == 1.0
        assert body["tax_year_extractor"] == "human:ada"


def test_bad_form_value_rerenders(client: TestClient) -> None:
    response = client.post(
        "/documents/K1-0001/fields",
        data={"field_path": "part_iii.interest_income", "value": "abc", "actor": "ada"},
    )
    assert response.status_code == 400
    assert "not a number" in response.text


def test_heldout_fixture_serves_a_clean_document_and_a_letter(tmp_path: Path) -> None:
    """The API probe looks for fixtures/heldout, which is not a generated set."""

    application = create_app(
        db_path=tmp_path / "heldout.db",
        fixture_dir=Path("fixtures/heldout"),
        auto_ingest=True,
    )
    with TestClient(application) as test_client:
        documents = test_client.get("/api/documents").json()
        unrecognized = [item for item in documents if not item["layout_recognized"]]
        catalog = [item for item in documents if item["layout_recognized"]]
        assert unrecognized
        assert catalog
        findings = test_client.get(f"/api/documents/{catalog[0]['document_id']}/findings").json()
        assert any(item["rule_id"] == "no_roster" for item in findings)
        assert catalog[0]["low_confidence_count"] >= 1
        assert test_client.get(
            f"/api/documents/{catalog[0]['document_id']}/pdf"
        ).content.startswith(b"%PDF")


def test_empty_queue_and_header_only_export(tmp_path) -> None:
    application = create_app(
        db_path=tmp_path / "empty.db", fixture_dir=tmp_path / "missing", auto_ingest=True
    )
    with TestClient(application) as test_client:
        page = test_client.get("/")
        assert page.status_code == 200
        assert "queue is empty" in page.text
        csv_export = test_client.get("/api/export/csv")
        assert csv_export.text.splitlines()[0].startswith("document_id")
        assert len(csv_export.text.splitlines()) == 1
        missing = test_client.post("/documents/K1-0001/approve", data={"actor": "ada"})
        assert missing.status_code == 404


def _issues(response: object) -> str:
    body = response.json()  # type: ignore[attr-defined]
    detail = body["detail"]
    if isinstance(detail, list):
        return "\n".join(str(item) for item in detail)
    return str(detail)


def _install_roster(client: TestClient, document_id: str) -> None:
    body = client.get(f"/api/documents/{document_id}").json()["document"]
    roster = roster_from_documents([ScheduleK1.model_validate(body)])
    posted = client.post("/api/roster", json=dump_roster(roster))
    assert posted.status_code == 200


def _client_for(tmp_path: Path, document: ScheduleK1) -> tuple[TestClient, Path]:
    db = tmp_path / "review.db"
    roster = roster_from_documents([document])
    store = ReviewStore(db, roster=roster)
    store.upsert(document, b"%PDF-1.4", validate_document(document, roster=roster))
    application = create_app(db_path=db, roster=roster)
    return TestClient(application), db


def test_approve_is_409_for_each_blocking_reason(tmp_path: Path) -> None:
    capital = build_document(random.Random(4), 2, Variant.INCONSISTENT_CAPITAL)
    year = build_document(random.Random(4), 3, Variant.CLEAN)
    year_payload = year.model_dump(mode="json")
    year_payload["tax_year_confidence"] = 0.2
    year = ScheduleK1.model_validate(year_payload)
    coded = build_document(random.Random(4), 4, Variant.CLEAN)
    coded_payload = coded.model_dump(mode="json")
    coded_payload["part_iii"]["other_income"][0]["amount"]["confidence"] = 0.2
    coded = ScheduleK1.model_validate(coded_payload)
    expected = (
        (capital, "part_ii.capital.ending"),
        (year, "tax_year"),
        (coded, "part_iii.other_income["),
    )
    for index, (document, needle) in enumerate(expected):
        client, _db = _client_for(tmp_path / f"case-{index}", document)
        with client:
            blocked = client.post(
                f"/api/documents/{document.document_id}/approve",
                json={"actor": "ada"},
            )
            assert blocked.status_code == 409
            text = _issues(blocked)
            assert needle in text
            for line in text.splitlines():
                path = line.split(":", 1)[0]
                form = client.post(
                    f"/documents/{document.document_id}/overrides",
                    data={"field_path": path, "reason": "Checked the page", "actor": "ada"},
                    follow_redirects=False,
                )
                assert form.status_code == 303
            approved = client.post(
                f"/api/documents/{document.document_id}/approve",
                json={"actor": "ada"},
            )
            assert approved.status_code == 200
            assert approved.json()["status"] == "approved"


def test_export_is_409_while_any_document_is_blocked(tmp_path: Path) -> None:
    document = build_document(random.Random(4), 3, Variant.CLEAN)
    payload = document.model_dump(mode="json")
    payload["tax_year_confidence"] = 0.2
    document = ScheduleK1.model_validate(payload)
    client, db = _client_for(tmp_path, document)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE documents SET status = 'approved', approved_by = 'ada', approved_at = 't' "
        "WHERE document_id = ?",
        (document.document_id,),
    )
    conn.commit()
    conn.close()
    with client:
        blocked = client.get("/api/export/csv")
        assert blocked.status_code == 409
        assert "unresolved review items" in _issues(blocked)
        form = client.post(
            f"/documents/{document.document_id}/overrides",
            data={"field_path": "tax_year", "reason": "Year checked", "actor": "ada"},
            follow_redirects=False,
        )
        assert form.status_code == 303
        exported = client.get("/api/export/csv")
        assert exported.status_code == 200
        assert document.document_id in exported.text


def test_preview_of_a_corrupt_pdf_is_422(tmp_path: Path) -> None:
    dest = tmp_path / "corpus"
    generate_corpus(dest, seed=7, count=1, plan=(Variant.CLEAN,))
    db = tmp_path / "review.db"
    application = create_app(db_path=db, fixture_dir=dest, auto_ingest=True)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE documents SET pdf = ? WHERE document_id = 'K1-0001'",
        (b"%PDF-1.4 broken",),
    )
    conn.commit()
    conn.close()
    with TestClient(application) as client:
        preview = client.get("/documents/K1-0001/preview.png")
    assert preview.status_code == 422
    assert preview.json()["detail"] == "PDF preview failed"

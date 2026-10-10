"""FastAPI review UI and JSON API."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

from k1lens import __version__
from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import ScheduleK1
from k1lens.export.writers import ExportRecord, records_to_csv, records_to_xlsx
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.review.errors import (
    ApprovalBlockedError,
    DocumentNotFoundError,
    InvalidFieldValueError,
)
from k1lens.review.ingest import ingest_fixtures
from k1lens.review.preview import pdf_preview_png
from k1lens.review.store import DocumentSummary, ReviewStore, require_actor
from k1lens.review.view import build_rows, group_rows
from k1lens.roster import Roster, parse_roster
from k1lens.validate.engine import Finding

_PACKAGE = Path(__file__).resolve().parent
_TEMPLATES = Jinja2Templates(directory=str(_PACKAGE / "templates"))


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str


class SummaryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    tax_year: int | None
    partnership_name: str | None
    partner_name: str | None
    variant: str
    status: str
    error_count: int
    warning_count: int
    low_confidence_count: int
    layout_recognized: bool


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    status: str
    variant: str
    approved_by: str | None
    approved_at: str | None
    document: ScheduleK1
    findings: list[Finding]


class CorrectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str = Field(min_length=1)
    value: str
    actor: str = Field(min_length=1, max_length=200)


class ApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    actor: str = Field(min_length=1, max_length=200)


class AuditResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int
    document_id: str
    field_path: str | None
    action: str
    old_value: str | None
    new_value: str | None
    actor: str
    created_at: str


def create_app(
    *,
    db_path: Path,
    fixture_dir: Path | None = None,
    auto_ingest: bool = False,
    reingest: bool = False,
    threshold: float = REVIEW_THRESHOLD,
    roster: Roster | None = None,
) -> FastAPI:
    """Build the review app.

    When ``auto_ingest`` is set and the database is empty, a fixture manifest
    in ``fixture_dir`` is extracted with the deterministic backend and loaded.
    """

    store = ReviewStore(db_path, roster=roster, threshold=threshold)
    if fixture_dir is not None and (reingest or (auto_ingest and store.count() == 0)):
        manifest = fixture_dir / "manifest.json"
        if manifest.is_file():
            ingest_fixtures(store, fixture_dir, DeterministicExtractor(), threshold=threshold)

    app = FastAPI(
        title="K1-Lens",
        version=__version__,
        summary="Synthetic Schedule K-1 review API",
        description=(
            "Review queue for synthetic IRS Schedule K-1 (Form 1065) extractions. "
            "Correct a field, approve a document, and export approved rows as CSV or Excel. "
            "The HTML UI is served at /. Every document in this demo is synthetic. "
            "Swagger UI at /docs is served from this app. It does not load a CDN."
        ),
        docs_url=None,
        redoc_url=None,
    )
    app.state.store = store
    app.state.threshold = threshold
    app.mount("/static", StaticFiles(directory=str(_PACKAGE / "static")), name="static")

    @app.get("/docs", include_in_schema=False)
    def swagger_ui() -> HTMLResponse:
        return get_swagger_ui_html(
            openapi_url=app.openapi_url or "/openapi.json",
            title="K1-Lens API",
            swagger_js_url="/static/swagger/swagger-ui-bundle.js",
            swagger_css_url="/static/swagger/swagger-ui.css",
            swagger_favicon_url="/static/favicon.png",
        )

    @app.post("/api/roster", tags=["roster"])
    def replace_roster(body: dict[str, Any]) -> dict[str, int]:
        """Install a client roster and recheck every document already in the queue."""

        try:
            loaded = parse_roster(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        store.set_roster(loaded)
        return {
            "partnerships": len(loaded.partnerships),
            "investors": len(loaded.investors),
        }

    @app.get("/api/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        """Liveness check. Does not report extraction accuracy."""

        return HealthResponse(status="ok")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def list_page(request: Request) -> HTMLResponse:
        documents = store.list_documents(threshold=threshold)
        return _TEMPLATES.TemplateResponse(
            request,
            "list.html",
            {"documents": documents, "threshold_pct": _pct(threshold)},
        )

    @app.get("/documents/{document_id}", response_class=HTMLResponse, include_in_schema=False)
    def detail_page(request: Request, document_id: str, error: str | None = None) -> HTMLResponse:
        record = store.get(document_id)
        if record is None:
            return _TEMPLATES.TemplateResponse(
                request,
                "missing.html",
                {"document_id": document_id},
                status_code=404,
            )
        return _detail(request, record.document_id, error=error)

    @app.post("/documents/{document_id}/fields", include_in_schema=False)
    def correct_form(
        request: Request,
        document_id: str,
        field_path: str = Form(),
        value: str = Form(""),
        actor: str = Form(""),
    ) -> Response:
        try:
            actor_name = require_actor(actor)
            store.correct(document_id, field_path, value, actor_name)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        except InvalidFieldValueError as exc:
            return _detail(request, document_id, error=str(exc), status_code=400)
        return RedirectResponse(f"/documents/{document_id}", status_code=303)

    @app.post("/documents/{document_id}/overrides", include_in_schema=False)
    def override_form(
        request: Request,
        document_id: str,
        field_path: str = Form(),
        reason: str = Form(""),
        actor: str = Form(""),
    ) -> Response:
        try:
            store.override(document_id, field_path, reason, require_actor(actor))
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        except InvalidFieldValueError as exc:
            return _detail(request, document_id, error=str(exc), status_code=400)
        return RedirectResponse(f"/documents/{document_id}", status_code=303)

    @app.post("/documents/{document_id}/approve", include_in_schema=False)
    def approve_form(request: Request, document_id: str, actor: str = Form("")) -> Response:
        try:
            store.approve(document_id, require_actor(actor), threshold=threshold)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        except InvalidFieldValueError as exc:
            return _detail(request, document_id, error=str(exc), status_code=400)
        except ApprovalBlockedError as exc:
            return _detail(request, document_id, error=str(exc), status_code=400)
        return RedirectResponse(f"/documents/{document_id}", status_code=303)

    @app.get("/documents/{document_id}/pdf", include_in_schema=False)
    def pdf(document_id: str) -> Response:
        try:
            payload = store.pdf(document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        return Response(content=payload, media_type="application/pdf")

    @app.get("/documents/{document_id}/preview.png", include_in_schema=False)
    def pdf_preview(document_id: str) -> Response:
        try:
            payload = pdf_preview_png(store.pdf(document_id))
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="PDF preview failed") from exc
        return Response(content=payload, media_type="image/png")

    @app.get("/api/documents", response_model=list[SummaryResponse], tags=["documents"])
    def list_documents(status: str | None = None) -> list[SummaryResponse]:
        """List queued documents. ``status`` is ``pending`` or ``approved``."""

        if status is not None and status not in {"pending", "approved"}:
            raise HTTPException(status_code=400, detail="status must be pending or approved")
        return [_summary(item) for item in store.list_documents(status=status, threshold=threshold)]

    @app.get("/api/documents/{document_id}", response_model=DocumentResponse, tags=["documents"])
    def get_document(document_id: str) -> DocumentResponse:
        """Return the working extraction, findings, and approval state."""

        return _document(document_id)

    @app.get(
        "/api/documents/{document_id}/findings", response_model=list[Finding], tags=["documents"]
    )
    def get_findings(document_id: str) -> list[Finding]:
        """Validation findings for the current field values."""

        return _document(document_id).findings

    @app.post(
        "/api/documents/{document_id}/corrections", response_model=DocumentResponse, tags=["review"]
    )
    def correct_document(document_id: str, body: CorrectionRequest) -> DocumentResponse:
        """Correct one field. The actor is recorded in the audit log.

        A blank value clears the field. Saving a correction reopens an approved document.
        """

        try:
            store.correct(document_id, body.field_path, body.value, _actor(body.actor))
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        except InvalidFieldValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return _document(document_id)

    @app.post(
        "/api/documents/{document_id}/approve", response_model=DocumentResponse, tags=["review"]
    )
    def approve_document(document_id: str, body: ApproveRequest) -> DocumentResponse:
        """Approve the current values. Approval is recorded with the actor and time."""

        try:
            store.approve(document_id, _actor(body.actor), threshold=threshold)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        except InvalidFieldValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except ApprovalBlockedError as exc:
            raise HTTPException(status_code=409, detail=exc.issues) from exc
        return _document(document_id)

    @app.get(
        "/api/documents/{document_id}/audit", response_model=list[AuditResponse], tags=["review"]
    )
    def document_audit(document_id: str) -> list[AuditResponse]:
        """Who changed what, and when."""

        try:
            entries = store.audit(document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        return [AuditResponse.model_validate(entry, from_attributes=True) for entry in entries]

    @app.get("/api/documents/{document_id}/pdf", tags=["documents"])
    def document_pdf(document_id: str) -> Response:
        """Source PDF bytes for the queued document."""

        try:
            payload = store.pdf(document_id)
        except DocumentNotFoundError as exc:
            raise HTTPException(status_code=404, detail="Document not found") from exc
        return Response(content=payload, media_type="application/pdf")

    @app.get("/api/export/csv", tags=["export"])
    def export_csv() -> Response:
        """CSV of approved documents only. Money columns are decimal strings."""

        _require_exportable()
        payload = records_to_csv(_export_records())
        return Response(
            content=payload,
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": "attachment; filename=k1-approved.csv"},
        )

    @app.get("/api/export/xlsx", tags=["export"])
    def export_xlsx() -> Response:
        """Excel workbook of approved documents only."""

        _require_exportable()
        payload = records_to_xlsx(_export_records())
        return Response(
            content=payload,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": "attachment; filename=k1-approved.xlsx"},
        )

    def _document(document_id: str) -> DocumentResponse:
        record = store.get(document_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Document not found")
        return DocumentResponse(
            document_id=record.document_id,
            status=record.status,
            variant=record.variant,
            approved_by=record.approved_by,
            approved_at=record.approved_at,
            document=record.document,
            findings=record.findings,
        )

    def _require_exportable() -> None:
        try:
            store.assert_exportable(threshold=threshold)
        except ApprovalBlockedError as exc:
            raise HTTPException(status_code=409, detail=exc.issues) from exc

    def _export_records() -> list[ExportRecord]:
        return [
            ExportRecord(
                document=record.document,
                approved_by=record.approved_by or "",
                approved_at=record.approved_at or "",
                findings=tuple(record.findings),
            )
            for record in store.approved()
        ]

    def _detail(
        request: Request, document_id: str, *, error: str | None = None, status_code: int = 200
    ) -> HTMLResponse:
        record = store.get(document_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Document not found")
        rows = build_rows(record.document, record.findings, threshold=threshold)
        return _TEMPLATES.TemplateResponse(
            request,
            "detail.html",
            {
                "record": record,
                "groups": group_rows(rows),
                "audit_entries": store.audit(document_id),
                "error": error,
                "threshold_pct": _pct(threshold),
                "error_count": sum(
                    1 for finding in record.findings if finding.severity.value == "error"
                ),
                "warning_count": sum(
                    1 for finding in record.findings if finding.severity.value == "warning"
                ),
            },
            status_code=status_code,
        )

    return app


def _summary(item: DocumentSummary) -> SummaryResponse:
    return SummaryResponse(
        document_id=item.document_id,
        tax_year=item.tax_year,
        partnership_name=item.partnership_name,
        partner_name=item.partner_name,
        variant=item.variant,
        status=item.status,
        error_count=item.error_count,
        warning_count=item.warning_count,
        low_confidence_count=item.low_confidence_count,
        layout_recognized=item.layout_recognized,
    )


def _actor(actor: str) -> str:
    try:
        return require_actor(actor)
    except InvalidFieldValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _pct(threshold: float) -> int:
    return round(threshold * 100)

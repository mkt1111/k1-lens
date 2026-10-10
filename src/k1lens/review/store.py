"""SQLite review queue and audit log."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from k1lens.domain.access import (
    UnknownFieldError,
    apply_correction,
    get_coded,
    get_extracted,
    kind_for_path,
    parse_review_value,
)
from k1lens.domain.fields import CODED_BOXES, REVIEW_THRESHOLD, SCALAR_FIELDS, FieldKind
from k1lens.domain.models import CodedAmount, ScheduleK1
from k1lens.domain.parsing import format_value, values_equal
from k1lens.review.errors import (
    ApprovalBlockedError,
    DocumentNotFoundError,
    InvalidFieldValueError,
)
from k1lens.roster import Roster, bind_roster, lifted_identity_paths
from k1lens.validate.engine import Finding, validate_document

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    document_id TEXT PRIMARY KEY,
    tax_year INTEGER,
    partnership_name TEXT,
    partner_name TEXT,
    variant TEXT NOT NULL,
    status TEXT NOT NULL,
    pdf BLOB NOT NULL,
    payload_json TEXT NOT NULL,
    findings_json TEXT NOT NULL,
    approved_by TEXT,
    approved_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id TEXT NOT NULL,
    field_path TEXT,
    action TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    actor TEXT NOT NULL,
    created_at TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    row_hash TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'audit_log is append-only');
END;
CREATE TABLE IF NOT EXISTS audit_head (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    row_count INTEGER NOT NULL,
    tip_hash TEXT NOT NULL
);
"""

_GENESIS = "0" * 64


@dataclass(frozen=True, slots=True)
class AuditEntry:
    id: int
    document_id: str
    field_path: str | None
    action: str
    old_value: str | None
    new_value: str | None
    actor: str
    created_at: str


@dataclass(frozen=True, slots=True)
class StoredDocument:
    document_id: str
    tax_year: int | None
    partnership_name: str | None
    partner_name: str | None
    variant: str
    status: str
    pdf: bytes
    document: ScheduleK1
    findings: list[Finding]
    approved_by: str | None
    approved_at: str | None
    updated_at: str


@dataclass(frozen=True, slots=True)
class DocumentSummary:
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


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


class ReviewStore:
    def __init__(
        self,
        db_path: Path,
        *,
        roster: Roster | None = None,
        threshold: float = REVIEW_THRESHOLD,
    ) -> None:
        self.db_path = db_path
        self._roster = roster
        self._threshold = threshold
        if db_path.parent != Path():
            db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(_SCHEMA)

    @property
    def roster(self) -> Roster | None:
        return self._roster

    def set_roster(self, roster: Roster | None) -> None:
        """Replace the roster and recheck every stored document."""

        self._roster = roster
        for document_id in self._document_ids():
            current = self.get(document_id)
            if current is None:
                continue
            updated = bind_roster(current.document, roster, threshold=self._threshold)
            findings = validate_document(updated, roster=roster)
            now = utc_now()
            with self._connect() as conn:
                conn.execute(
                    """
                    UPDATE documents
                    SET payload_json = ?, findings_json = ?, updated_at = ?
                    WHERE document_id = ?
                    """,
                    (
                        updated.model_dump_json(),
                        _findings_json(findings),
                        now,
                        document_id,
                    ),
                )
                _audit_roster_lifts(
                    conn,
                    before=current.document,
                    after=updated,
                    actor="system",
                    created_at=now,
                    threshold=self._threshold,
                )

    def _document_ids(self) -> list[str]:
        with self._connect() as conn:
            rows = conn.execute("SELECT document_id FROM documents ORDER BY document_id").fetchall()
        return [str(row["document_id"]) for row in rows]

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS n FROM documents").fetchone()
        if row is None:
            return 0
        return int(row["n"])

    def upsert(
        self,
        document: ScheduleK1,
        pdf: bytes,
        findings: list[Finding],
        *,
        actor: str = "system",
    ) -> None:
        now = utc_now()
        existing = self.get(document.document_id)
        stored = bind_roster(document, self._roster, threshold=self._threshold)
        status = "pending"
        approved_by: str | None = None
        approved_at: str | None = None
        changes: list[tuple[str, str | None, str | None]] = []
        if existing is not None:
            stored = preserve_human_fields(existing.document, stored)
            stored = bind_roster(stored, self._roster, threshold=self._threshold)
            changes = _changed_fields(existing.document, stored)
            # A changed value returns the record to the needs-review queue
            # (stored as ``pending``). An unchanged re-ingest keeps an approval.
            if existing.status == "approved" and not changes:
                status = "approved"
                approved_by = existing.approved_by
                approved_at = existing.approved_at
        findings = validate_document(stored, roster=self._roster)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    document_id, tax_year, partnership_name, partner_name, variant, status,
                    pdf, payload_json, findings_json, approved_by, approved_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    tax_year = excluded.tax_year,
                    partnership_name = excluded.partnership_name,
                    partner_name = excluded.partner_name,
                    variant = excluded.variant,
                    status = excluded.status,
                    pdf = excluded.pdf,
                    payload_json = excluded.payload_json,
                    findings_json = excluded.findings_json,
                    approved_by = excluded.approved_by,
                    approved_at = excluded.approved_at,
                    updated_at = excluded.updated_at
                """,
                (
                    stored.document_id,
                    stored.tax_year,
                    stored.part_i.name.value,
                    stored.part_ii.name.value,
                    stored.variant,
                    status,
                    pdf,
                    stored.model_dump_json(),
                    _findings_json(findings),
                    approved_by,
                    approved_at,
                    now,
                ),
            )
            if changes:
                for field_path, old_value, new_value in changes:
                    _audit(
                        conn,
                        document_id=stored.document_id,
                        field_path=field_path,
                        action="ingest",
                        old_value=old_value,
                        new_value=new_value,
                        actor=actor,
                        created_at=now,
                    )
            else:
                _audit(
                    conn,
                    document_id=stored.document_id,
                    field_path=None,
                    action="ingest",
                    old_value=None,
                    new_value=document.variant,
                    actor=actor,
                    created_at=now,
                )
            if existing is not None and existing.status == "approved" and changes:
                _audit(
                    conn,
                    document_id=stored.document_id,
                    field_path=None,
                    action="reopen",
                    old_value="approved",
                    new_value="pending",
                    actor=actor,
                    created_at=now,
                )
            _audit_roster_lifts(
                conn,
                before=document,
                after=stored,
                actor=actor,
                created_at=now,
                threshold=self._threshold,
            )

    def list_documents(
        self, *, status: str | None = None, threshold: float = REVIEW_THRESHOLD
    ) -> list[DocumentSummary]:
        query = (
            "SELECT document_id, tax_year, partnership_name, partner_name, variant, status, "
            "payload_json, findings_json FROM documents"
        )
        params: tuple[str, ...] = ()
        if status is not None:
            query += " WHERE status = ?"
            params = (status,)
        query += " ORDER BY document_id"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        summaries: list[DocumentSummary] = []
        for row in rows:
            document = ScheduleK1.model_validate_json(row["payload_json"])
            findings = _load_findings(row["findings_json"])
            summaries.append(
                DocumentSummary(
                    document_id=row["document_id"],
                    tax_year=row["tax_year"],
                    partnership_name=row["partnership_name"],
                    partner_name=row["partner_name"],
                    variant=row["variant"],
                    status=row["status"],
                    error_count=sum(1 for finding in findings if finding.severity.value == "error"),
                    warning_count=sum(
                        1 for finding in findings if finding.severity.value == "warning"
                    ),
                    low_confidence_count=low_confidence_count(document, threshold),
                    layout_recognized=document.layout_recognized,
                )
            )
        return summaries

    def get(self, document_id: str) -> StoredDocument | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
        if row is None:
            return None
        return _stored(row)

    def pdf(self, document_id: str) -> bytes:
        document = self._require(document_id)
        return document.pdf

    def correct(
        self, document_id: str, field_path: str, raw_value: str, actor: str
    ) -> StoredDocument:
        actor = require_actor(actor)
        current = self._require(document_id)
        try:
            kind = kind_for_path(field_path)
            parsed = parse_review_value(kind, raw_value)
            updated = apply_correction(current.document, field_path, parsed, actor)
        except UnknownFieldError as exc:
            raise InvalidFieldValueError(f"Unknown field {field_path}") from exc
        except ValueError as exc:
            raise InvalidFieldValueError(str(exc)) from exc
        before_lift = updated
        updated = bind_roster(updated, self._roster, threshold=self._threshold)
        findings = validate_document(updated, roster=self._roster)
        now = utc_now()
        old_display = _display(get_value(current.document, field_path))
        new_display = _display(get_value(updated, field_path))
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE documents SET
                    tax_year = ?,
                    partnership_name = ?,
                    partner_name = ?,
                    status = 'pending',
                    payload_json = ?,
                    findings_json = ?,
                    approved_by = NULL,
                    approved_at = NULL,
                    updated_at = ?
                WHERE document_id = ?
                """,
                (
                    updated.tax_year,
                    updated.part_i.name.value,
                    updated.part_ii.name.value,
                    updated.model_dump_json(),
                    _findings_json(findings),
                    now,
                    document_id,
                ),
            )
            _audit(
                conn,
                document_id=document_id,
                field_path=field_path,
                action="correct",
                old_value=old_display,
                new_value=new_display,
                actor=actor,
                created_at=now,
            )
            if current.status == "approved":
                _audit(
                    conn,
                    document_id=document_id,
                    field_path=field_path,
                    action="reopen",
                    old_value="approved",
                    new_value="pending",
                    actor=actor,
                    created_at=now,
                )
            _audit_roster_lifts(
                conn,
                before=before_lift,
                after=updated,
                actor=actor,
                created_at=now,
                threshold=self._threshold,
            )
        stored = self.get(document_id)
        if stored is None:
            raise DocumentNotFoundError(document_id)
        return stored

    def override(
        self, document_id: str, field_path: str, reason: str, actor: str
    ) -> StoredDocument:
        actor = require_actor(actor)
        current = self._require(document_id)
        text = " ".join(reason.split())
        if text == "":
            raise InvalidFieldValueError("An override needs a reason")
        if field_path.strip() == "":
            raise InvalidFieldValueError("An override needs a field")
        try:
            kind_for_path(field_path)
        except UnknownFieldError as exc:
            raise InvalidFieldValueError(f"Unknown field {field_path}") from exc
        covered = _field_text(current.document, field_path)
        now = utc_now()
        with self._connect() as conn:
            _audit(
                conn,
                document_id=document_id,
                field_path=field_path,
                action="override",
                old_value=text,
                new_value=covered,
                actor=actor,
                created_at=now,
            )
        stored = self.get(document_id)
        if stored is None:
            raise DocumentNotFoundError(document_id)
        return stored

    def approve(
        self, document_id: str, actor: str, *, threshold: float = REVIEW_THRESHOLD
    ) -> StoredDocument:
        actor = require_actor(actor)
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM documents WHERE document_id = ?",
                (document_id,),
            ).fetchone()
            if row is None:
                raise DocumentNotFoundError(document_id)
            current = _stored(row)
            payload = str(row["payload_json"])
        issues = unresolved_issues(
            current.document,
            current.findings,
            threshold,
            self.override_paths(document_id, current.document),
        )
        if issues:
            raise ApprovalBlockedError(issues)
        # A correction that commits after this check changes payload_json.
        # The update below matches only the payload that was just checked.
        snapshot = approved_snapshot(current.document)
        now = utc_now()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE documents
                SET status = 'approved', approved_by = ?, approved_at = ?, updated_at = ?
                WHERE document_id = ? AND payload_json = ?
                """,
                (actor, now, now, document_id, payload),
            )
            if cursor.rowcount != 1:
                raise ApprovalBlockedError(["The document changed before approval was saved"])
            _audit(
                conn,
                document_id=document_id,
                field_path=None,
                action="approve",
                old_value=current.status,
                new_value=snapshot,
                actor=actor,
                created_at=now,
            )
        stored = self.get(document_id)
        if stored is None:
            raise DocumentNotFoundError(document_id)
        return stored

    def audit(self, document_id: str) -> list[AuditEntry]:
        self._require(document_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM audit_log WHERE document_id = ? ORDER BY id
                """,
                (document_id,),
            ).fetchall()
        return [
            AuditEntry(
                id=int(row["id"]),
                document_id=row["document_id"],
                field_path=row["field_path"],
                action=row["action"],
                old_value=row["old_value"],
                new_value=row["new_value"],
                actor=row["actor"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def approved(self) -> list[StoredDocument]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM documents WHERE status = 'approved' ORDER BY document_id"
            ).fetchall()
        return [_stored(row) for row in rows]

    def override_paths(self, document_id: str, document: ScheduleK1 | None = None) -> set[str]:
        """Paths whose override still matches the value it was given for."""

        current = document
        if current is None:
            stored = self.get(document_id)
            if stored is None:
                return set()
            current = stored.document
        covered: set[str] = set()
        for entry in self.audit(document_id):
            if entry.action != "override" or not entry.field_path:
                continue
            # An empty string is a real value: confirming a blank field.
            if entry.new_value == _field_text(current, entry.field_path):
                covered.add(entry.field_path)
        return covered

    def assert_exportable(self, *, threshold: float = REVIEW_THRESHOLD) -> None:
        blocked: list[str] = []
        for record in self.approved():
            issues = unresolved_issues(
                record.document,
                record.findings,
                threshold,
                self.override_paths(record.document_id, record.document),
            )
            if issues:
                blocked.append(record.document_id)
        if blocked:
            raise ApprovalBlockedError(
                [f"{document_id} still has unresolved review items" for document_id in blocked]
            )

    def _require(self, document_id: str) -> StoredDocument:
        document = self.get(document_id)
        if document is None:
            raise DocumentNotFoundError(document_id)
        return document


def low_confidence_count(document: ScheduleK1, threshold: float) -> int:
    count = 0
    if document.tax_year_confidence is not None and document.tax_year_confidence < threshold:
        count += 1
    for spec in SCALAR_FIELDS:
        if get_extracted(document, spec.path).confidence < threshold:
            count += 1
    for box in CODED_BOXES:
        for item in get_coded(document, box.path):
            if item.amount.confidence < threshold:
                count += 1
    return count


def get_value(document: ScheduleK1, path: str) -> object:
    from k1lens.domain.access import parse_coded_path

    if path == "tax_year":
        return document.tax_year
    if path == "ocr_failed_pages":
        if not document.ocr_failed_pages:
            return None
        return ", ".join(str(page) for page in document.ocr_failed_pages)
    coded = parse_coded_path(path)
    if coded is None:
        return get_extracted(document, path).value
    base, code, index = coded
    matches = [item for item in get_coded(document, base) if item.code.upper() == code]
    if index < 1 or index > len(matches):
        return None
    return matches[index - 1].amount.value


def _display(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _field_text(document: ScheduleK1, path: str) -> str:
    """The stored value an override is bound to, in the same form as an ingest row."""

    value = get_value(document, path)
    if value is None:
        return ""
    if path == "tax_year":
        return str(value)
    return _shown(kind_for_path(path), value) or ""


def _findings_json(findings: list[Finding]) -> str:
    return json.dumps([finding.model_dump(mode="json") for finding in findings])


def _load_findings(payload: str) -> list[Finding]:
    raw = json.loads(payload)
    if not isinstance(raw, list):
        return []
    return [Finding.model_validate(item) for item in raw]


def _stored(row: sqlite3.Row) -> StoredDocument:
    return StoredDocument(
        document_id=row["document_id"],
        tax_year=row["tax_year"],
        partnership_name=row["partnership_name"],
        partner_name=row["partner_name"],
        variant=row["variant"],
        status=row["status"],
        pdf=bytes(row["pdf"]),
        document=ScheduleK1.model_validate_json(row["payload_json"]),
        findings=_load_findings(row["findings_json"]),
        approved_by=row["approved_by"],
        approved_at=row["approved_at"],
        updated_at=row["updated_at"],
    )


def require_actor(actor: str) -> str:
    text = " ".join(actor.split())
    if text == "" or text.casefold() == "reviewer":
        raise InvalidFieldValueError("A reviewer name is required")
    if len(text) > 200:
        raise InvalidFieldValueError("Reviewer name is too long")
    return text


def unresolved_issues(
    document: ScheduleK1,
    findings: list[Finding],
    threshold: float,
    overrides: set[str],
) -> list[str]:
    issues: list[str] = []
    for finding in findings:
        if finding.severity.value != "error" or finding.field_path in overrides:
            continue
        issues.append(f"{finding.field_path}: {finding.message}")
    if (
        document.tax_year_confidence is not None
        and document.tax_year_confidence < threshold
        and "tax_year" not in overrides
    ):
        issues.append(
            f"tax_year: confidence {document.tax_year_confidence:.2f} is below {threshold:.2f}"
        )
    for spec in SCALAR_FIELDS:
        field = get_extracted(document, spec.path)
        if field.confidence < threshold and spec.path not in overrides:
            issues.append(
                f"{spec.path}: confidence {field.confidence:.2f} is below {threshold:.2f}"
            )
    for box in CODED_BOXES:
        items = get_coded(document, box.path)
        counts: dict[str, int] = {}
        for item in items:
            counts[item.code] = counts.get(item.code, 0) + 1
        seen: dict[str, int] = {}
        for item in items:
            seen[item.code] = seen.get(item.code, 0) + 1
            if counts[item.code] == 1:
                path = f"{box.path}[{item.code}]"
            else:
                path = f"{box.path}[{item.code}]#{seen[item.code]}"
            if item.amount.confidence < threshold and path not in overrides:
                issues.append(
                    f"{path}: confidence {item.amount.confidence:.2f} is below {threshold:.2f}"
                )
    return issues


def approved_snapshot(document: ScheduleK1) -> str:
    values: dict[str, object] = {"tax_year": document.tax_year}
    for spec in SCALAR_FIELDS:
        values[spec.path] = get_extracted(document, spec.path).value
    for box in CODED_BOXES:
        values[box.path] = [
            {
                "code": item.code,
                "amount": None if item.amount.value is None else str(item.amount.value),
            }
            for item in get_coded(document, box.path)
        ]
    return json.dumps({"status": "approved", "values": values}, sort_keys=True, default=str)


def _changed_fields(
    before: ScheduleK1, after: ScheduleK1
) -> list[tuple[str, str | None, str | None]]:
    """Fields whose values differ. Human-preserved values match and are omitted."""

    rows: list[tuple[str, str | None, str | None]] = []
    old_pages = ", ".join(str(page) for page in before.ocr_failed_pages)
    new_pages = ", ".join(str(page) for page in after.ocr_failed_pages)
    if old_pages != new_pages:
        rows.append(("ocr_failed_pages", old_pages or None, new_pages or None))
    if before.tax_year != after.tax_year:
        rows.append(("tax_year", _plain(before.tax_year), _plain(after.tax_year)))
    for spec in SCALAR_FIELDS:
        old = get_extracted(before, spec.path).value
        new = get_extracted(after, spec.path).value
        if _same_value(spec.kind, old, new):
            continue
        rows.append((spec.path, _shown(spec.kind, old), _shown(spec.kind, new)))
    for box in CODED_BOXES:
        old_text = _coded_text(get_coded(before, box.path))
        new_text = _coded_text(get_coded(after, box.path))
        if old_text == new_text:
            continue
        rows.append((box.path, old_text, new_text))
    return rows


def _plain(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _shown(kind: FieldKind, value: object) -> str | None:
    if value is None:
        return None
    return format_value(kind, value)


def _same_value(kind: FieldKind, old: object, new: object) -> bool:
    try:
        return values_equal(kind, old, new, Decimal("0"))
    except (ArithmeticError, ValueError):
        return _plain(old) == _plain(new)


def _coded_text(items: list[CodedAmount]) -> str | None:
    if not items:
        return None
    parts: list[str] = []
    for item in items:
        amount = item.amount.value
        shown = "" if amount is None else format_value(FieldKind.MONEY, amount)
        parts.append(f"{item.code}={shown}")
    return ";".join(parts)


def preserve_human_fields(stored: ScheduleK1, fresh: ScheduleK1) -> ScheduleK1:
    data = fresh.model_dump(mode="json")
    _merge_tree(data, stored.model_dump(mode="json"))
    return ScheduleK1.model_validate(data)


def verify_database(db_path: Path) -> list[str]:
    """Return problems in the append-only hash chain. An empty list means it holds.

    A tail truncation is a problem, including a log that was emptied and a
    gap left after a later append. Edits to the ``documents`` table are not
    checked. Anyone who rewrites the file can rebuild the chain and the head.
    A file that is not this schema is one problem line.
    """

    problems: list[str] = []
    try:
        conn = sqlite3.connect(db_path)
    except sqlite3.Error:
        return ["not a K1-Lens database"]
    conn.row_factory = sqlite3.Row
    try:
        try:
            tables = {
                str(row["name"])
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
        except sqlite3.Error:
            return ["not a K1-Lens database"]
        if "audit_log" not in tables or "audit_head" not in tables:
            return ["not a K1-Lens database"]
        names = {
            str(row["name"])
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_log'"
            )
        }
        for name in ("audit_log_no_update", "audit_log_no_delete"):
            if name not in names:
                problems.append(f"missing trigger {name}")
        rows = conn.execute("SELECT * FROM audit_log ORDER BY id").fetchall()
        previous = _GENESIS
        for row in rows:
            if str(row["prev_hash"]) != previous:
                problems.append(f"row {row['id']} prev_hash does not match the previous row")
            expected = _chain_hash(
                previous,
                document_id=str(row["document_id"]),
                field_path=row["field_path"],
                action=str(row["action"]),
                old_value=row["old_value"],
                new_value=row["new_value"],
                actor=str(row["actor"]),
                created_at=str(row["created_at"]),
            )
            if str(row["row_hash"]) != expected:
                problems.append(f"row {row['id']} row_hash does not match its contents")
            previous = str(row["row_hash"])
        if rows:
            try:
                conn.execute("UPDATE audit_log SET actor = actor WHERE id = ?", (rows[0]["id"],))
                problems.append("UPDATE on audit_log was not blocked")
            except sqlite3.Error:
                pass
            try:
                conn.execute("DELETE FROM audit_log WHERE id = ?", (rows[0]["id"],))
                problems.append("DELETE on audit_log was not blocked")
            except sqlite3.Error:
                pass
            conn.rollback()
        head = conn.execute("SELECT row_count, tip_hash FROM audit_head WHERE id = 1").fetchone()
        if not rows:
            if head is not None and (
                int(head["row_count"]) != 0 or str(head["tip_hash"]) != _GENESIS
            ):
                problems.append("audit log tail does not match the stored head")
        else:
            ids = [int(row["id"]) for row in rows]
            if ids != list(range(1, ids[-1] + 1)):
                problems.append("audit log tail does not match the stored head")
            tip = str(rows[-1]["row_hash"])
            if head is None or int(head["row_count"]) != len(rows) or str(head["tip_hash"]) != tip:
                problems.append("audit log tail does not match the stored head")
    except sqlite3.Error:
        problems.append("not a K1-Lens database")
    finally:
        conn.rollback()
        conn.close()
    return problems


def _audit_roster_lifts(
    conn: sqlite3.Connection,
    *,
    before: ScheduleK1,
    after: ScheduleK1,
    actor: str,
    created_at: str,
    threshold: float,
) -> None:
    """Record each identity field a full exact match lifted to the threshold.

    ``new_value`` is the page string. The roster text is not what was stored.
    """

    for path in lifted_identity_paths(before, after, threshold=threshold):
        _audit(
            conn,
            document_id=after.document_id,
            field_path=path,
            action="roster_exact_match",
            old_value=_display(get_extracted(before, path).confidence),
            new_value=_display(get_extracted(after, path).value),
            actor=actor,
            created_at=created_at,
        )


def _audit(
    conn: sqlite3.Connection,
    *,
    document_id: str,
    field_path: str | None,
    action: str,
    old_value: str | None,
    new_value: str | None,
    actor: str,
    created_at: str,
) -> None:
    row = conn.execute("SELECT row_hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    previous = _GENESIS if row is None else str(row["row_hash"])
    digest = _chain_hash(
        previous,
        document_id=document_id,
        field_path=field_path,
        action=action,
        old_value=old_value,
        new_value=new_value,
        actor=actor,
        created_at=created_at,
    )
    conn.execute(
        """
        INSERT INTO audit_log (
            document_id, field_path, action, old_value, new_value, actor, created_at,
            prev_hash, row_hash
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            document_id,
            field_path,
            action,
            old_value,
            new_value,
            actor,
            created_at,
            previous,
            digest,
        ),
    )
    count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
    total = 0 if count is None else int(count[0])
    conn.execute(
        """
        INSERT INTO audit_head (id, row_count, tip_hash) VALUES (1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            row_count = excluded.row_count,
            tip_hash = excluded.tip_hash
        """,
        (total, digest),
    )


def _chain_hash(
    previous: str,
    *,
    document_id: str,
    field_path: str | None,
    action: str,
    old_value: str | None,
    new_value: str | None,
    actor: str,
    created_at: str,
) -> str:
    payload = "\n".join(
        [
            previous,
            document_id,
            field_path or "",
            action,
            old_value or "",
            new_value or "",
            actor,
            created_at,
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _merge_tree(fresh: object, stored: object) -> None:
    if isinstance(fresh, dict) and isinstance(stored, dict):
        if "confidence" in fresh and "provenance" in fresh and _is_human(stored):
            fresh["value"] = stored.get("value")
            fresh["confidence"] = stored.get("confidence")
            fresh["provenance"] = stored.get("provenance")
            return
        for key, value in fresh.items():
            if key in stored:
                _merge_tree(value, stored[key])
        return
    if not isinstance(fresh, list) or not isinstance(stored, list):
        return
    if _coded_list(fresh) and _coded_list(stored):
        _merge_coded(fresh, stored)


def _coded_list(node: list[object]) -> bool:
    return all(isinstance(item, dict) and "code" in item and "amount" in item for item in node)


def _merge_coded(fresh: list[object], stored: list[object]) -> None:
    used = [False] * len(fresh)
    for item in stored:
        if not isinstance(item, dict):
            continue
        amount = item.get("amount")
        if not isinstance(amount, dict) or not _is_human(amount):
            continue
        code = str(item.get("code", "")).upper()
        placed = False
        for index, target in enumerate(fresh):
            if used[index] or not isinstance(target, dict):
                continue
            if str(target.get("code", "")).upper() != code:
                continue
            target_amount = target.get("amount")
            if isinstance(target_amount, dict):
                _merge_tree(target_amount, amount)
            used[index] = True
            placed = True
            break
        if not placed:
            fresh.append(item)


def _is_human(node: dict[str, object]) -> bool:
    provenance = node.get("provenance")
    if not isinstance(provenance, dict):
        return False
    extractor = provenance.get("extractor")
    return isinstance(extractor, str) and extractor.startswith("human:")

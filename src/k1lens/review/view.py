"""Rows the review page renders. Kept out of the template so it can be tested."""

from __future__ import annotations

from dataclasses import dataclass

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import CODED_BOXES, REVIEW_THRESHOLD, SCALAR_FIELDS, FieldKind
from k1lens.domain.models import Provenance, ScheduleK1
from k1lens.domain.parsing import format_value
from k1lens.validate.engine import Finding, Severity


@dataclass(frozen=True, slots=True)
class FieldRow:
    path: str
    label: str
    section: str
    kind: str
    value: str
    confidence: float
    low_confidence: bool
    provenance: str
    css_class: str
    messages: tuple[str, ...]


def build_rows(
    document: ScheduleK1,
    findings: list[Finding],
    *,
    threshold: float = REVIEW_THRESHOLD,
) -> list[FieldRow]:
    by_path: dict[str, list[Finding]] = {}
    for finding in findings:
        by_path.setdefault(finding.field_path, []).append(finding)
    rows: list[FieldRow] = []
    # An unscored year belongs to a generator record. Extraction always sets a
    # confidence, and that is what the review queue loads.
    year_confidence = 1.0 if document.tax_year_confidence is None else document.tax_year_confidence
    rows.append(
        _row(
            path="tax_year",
            label="TAX YEAR",
            section="Tax year",
            kind=FieldKind.INT,
            value=document.tax_year,
            confidence=year_confidence,
            provenance=Provenance(field_name="TAX YEAR", extractor=document.tax_year_extractor),
            findings=by_path.get("tax_year", []),
            threshold=threshold,
        )
    )
    for spec in SCALAR_FIELDS:
        field = get_extracted(document, spec.path)
        rows.append(
            _row(
                path=spec.path,
                label=spec.pdf_label,
                section=spec.section,
                kind=spec.kind,
                value=field.value,
                confidence=field.confidence,
                provenance=field.provenance,
                findings=by_path.get(spec.path, []),
                threshold=threshold,
            )
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
            rows.append(
                _row(
                    path=path,
                    label=f"{box.pdf_prefix} {item.code}",
                    section=box.section,
                    kind=FieldKind.MONEY,
                    value=item.amount.value,
                    confidence=item.amount.confidence,
                    provenance=item.amount.provenance,
                    findings=by_path.get(path, []),
                    threshold=threshold,
                )
            )
    return rows


def group_rows(rows: list[FieldRow]) -> list[tuple[str, list[FieldRow]]]:
    groups: list[tuple[str, list[FieldRow]]] = []
    for row in rows:
        if not groups or groups[-1][0] != row.section:
            groups.append((row.section, [row]))
        else:
            groups[-1][1].append(row)
    return groups


def _row(
    *,
    path: str,
    label: str,
    section: str,
    kind: FieldKind,
    value: object,
    confidence: float,
    provenance: Provenance,
    findings: list[Finding],
    threshold: float,
) -> FieldRow:
    severities = {finding.severity for finding in findings}
    low = confidence < threshold
    if Severity.ERROR in severities:
        css = "error"
    elif low:
        css = "low"
    elif Severity.WARNING in severities:
        css = "warning"
    else:
        css = ""
    return FieldRow(
        path=path,
        label=label,
        section=section,
        kind=kind.value,
        value=format_value(kind, value),
        confidence=confidence,
        low_confidence=low,
        provenance=format_provenance(provenance),
        css_class=css,
        messages=tuple(finding.message for finding in findings),
    )


def format_provenance(provenance: Provenance) -> str:
    parts: list[str] = []
    if provenance.page is not None:
        parts.append(f"p.{provenance.page}")
    if provenance.bbox is not None:
        x0, y0, x1, y1 = provenance.bbox
        parts.append(f"bbox {x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}")
    if provenance.field_name:
        parts.append(provenance.field_name)
    if provenance.extractor:
        parts.append(provenance.extractor)
    return " · ".join(parts)

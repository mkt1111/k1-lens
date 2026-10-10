"""Rules that audit a Schedule K-1 without calling a model.

Each rule returns structured findings. Arithmetic uses Decimal. The capital
account check follows item L on Form 1065 Schedule K-1, including the
"other increase (decrease)" line:

    beginning + contributed + current-year net income + other - withdrawals = ending
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from k1lens.domain.access import get_extracted
from k1lens.domain.fields import CAPITAL_COMPONENTS, PERCENT_PATHS, SCALAR_FIELDS
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import is_ein_text, is_ssn_text

DEFAULT_TOLERANCE = Decimal("1.00")
EIN_PATTERN_MESSAGE = "EIN must be NN-NNNNNNN"


class Severity(StrEnum):
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class Finding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rule_id: str
    severity: Severity
    message: str
    field_path: str
    expected: str | None = None
    actual: str | None = None


def capital_delta(
    beginning: Decimal,
    contributed: Decimal,
    current_year_net_income: Decimal,
    other_increase_decrease: Decimal,
    withdrawals: Decimal,
    ending: Decimal,
) -> Decimal:
    """Signed difference of the item L equation. Zero means the account ties."""

    expected = (
        beginning + contributed + current_year_net_income + other_increase_decrease - withdrawals
    )
    return expected - ending


def _money(value: object) -> Decimal:
    return Decimal(str(value))


def validate_document(
    doc: ScheduleK1,
    *,
    tolerance: Decimal = DEFAULT_TOLERANCE,
    roster: object | None = None,
) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_required(doc))
    findings.extend(_ein(doc))
    findings.extend(_tin(doc))
    findings.extend(_percentages(doc))
    findings.extend(_withdrawals(doc))
    findings.extend(_capital(doc, tolerance))
    findings.extend(_guaranteed_payments(doc, tolerance))
    findings.extend(_synthetic_marker(doc))
    findings.extend(_ocr_pages(doc))
    findings.extend(_roster_holds(doc, roster))
    return _sorted(findings)


def validate_payload(
    payload: dict[str, Any],
    *,
    tolerance: Decimal = DEFAULT_TOLERANCE,
    roster: object | None = None,
) -> list[Finding]:
    """Validate raw JSON. Type errors become findings; a valid payload is ruled next."""

    try:
        doc = ScheduleK1.model_validate(payload)
    except ValidationError as exc:
        return _sorted(_type_findings(exc))
    return validate_document(doc, tolerance=tolerance, roster=roster)


def _type_findings(exc: ValidationError) -> list[Finding]:
    findings: list[Finding] = []
    for error in exc.errors():
        loc = ".".join(str(part) for part in error["loc"])
        findings.append(
            Finding(
                rule_id="type_check",
                severity=Severity.ERROR,
                message=error["msg"],
                field_path=loc or "<root>",
                actual=_short(error.get("input")),
            )
        )
    return findings


def _required(doc: ScheduleK1) -> list[Finding]:
    findings: list[Finding] = []
    for spec in SCALAR_FIELDS:
        if not spec.required:
            continue
        value = get_extracted(doc, spec.path).value
        if value is None or (isinstance(value, str) and value.strip() == ""):
            findings.append(
                Finding(
                    rule_id="required_fields",
                    severity=Severity.ERROR,
                    message=f"Required field {spec.pdf_label} is missing.",
                    field_path=spec.path,
                )
            )
    if doc.tax_year is None:
        findings.append(
            Finding(
                rule_id="required_fields",
                severity=Severity.ERROR,
                message="Tax year is missing.",
                field_path="tax_year",
            )
        )
    return findings


def _ein(doc: ScheduleK1) -> list[Finding]:
    ein = doc.part_i.ein.value
    if ein is None or ein.strip() == "":
        return []
    if is_ein_text(ein):
        return []
    return [
        Finding(
            rule_id="ein_format",
            severity=Severity.ERROR,
            message=f"Partnership EIN {ein!r} is not in NN-NNNNNNN form. {EIN_PATTERN_MESSAGE}.",
            field_path="part_i.ein",
            expected="NN-NNNNNNN",
            actual=ein,
        )
    ]


def _tin(doc: ScheduleK1) -> list[Finding]:
    tin = doc.part_ii.tin.value
    if tin is None or tin.strip() == "":
        return []
    if is_ein_text(tin) or is_ssn_text(tin):
        return []
    return [
        Finding(
            rule_id="tin_format",
            severity=Severity.ERROR,
            message=f"Partner TIN {tin!r} is not an EIN (NN-NNNNNNN) or SSN (NNN-NN-NNNN).",
            field_path="part_ii.tin",
            expected="NN-NNNNNNN or NNN-NN-NNNN",
            actual=tin,
        )
    ]


def _percentages(doc: ScheduleK1) -> list[Finding]:
    findings: list[Finding] = []
    for path in PERCENT_PATHS:
        value = get_extracted(doc, path).value
        if value is None:
            continue
        number = _money(value)
        if number < 0 or number > 100:
            findings.append(
                Finding(
                    rule_id="percentage_range",
                    severity=Severity.ERROR,
                    message=f"{path} is {number}, outside 0 to 100.",
                    field_path=path,
                    expected="0 to 100",
                    actual=str(number),
                )
            )
    return findings


def _withdrawals(doc: ScheduleK1) -> list[Finding]:
    """Withdrawals and box 19 distributions are stored as non-negative amounts.

    Item L subtracts withdrawals. A negative amount would add cash back.
    """

    findings: list[Finding] = []
    withdrawals = doc.part_ii.capital.withdrawals.value
    if withdrawals is not None and withdrawals < 0:
        findings.append(
            Finding(
                rule_id="withdrawals_non_negative",
                severity=Severity.ERROR,
                message=(
                    "Withdrawals and distributions must be non-negative. "
                    "Item L subtracts that amount."
                ),
                field_path="part_ii.capital.withdrawals",
                expected=">= 0",
                actual=str(withdrawals),
            )
        )
    for item in doc.part_iii.distributions:
        amount = item.amount.value
        if amount is None or amount >= 0:
            continue
        findings.append(
            Finding(
                rule_id="withdrawals_non_negative",
                severity=Severity.ERROR,
                message=(
                    f"Distribution code {item.code} is negative. Box 19 amounts are non-negative."
                ),
                field_path=f"part_iii.distributions[{item.code}]",
                expected=">= 0",
                actual=str(amount),
            )
        )
    return findings


def _capital(doc: ScheduleK1, tolerance: Decimal) -> list[Finding]:
    values: dict[str, Decimal | None] = {}
    missing: list[str] = []
    for path in CAPITAL_COMPONENTS:
        raw = get_extracted(doc, path).value
        if raw is None:
            missing.append(path)
            values[path] = None
        else:
            values[path] = _money(raw)
    if missing:
        return [
            Finding(
                rule_id="capital_incomplete",
                severity=Severity.WARNING,
                message="Capital account is incomplete, so the item L equation was not tested.",
                field_path=missing[0],
                actual=", ".join(missing),
            )
        ]
    beginning = values["part_ii.capital.beginning"]
    contributed = values["part_ii.capital.contributed"]
    income = values["part_ii.capital.current_year_net_income"]
    other = values["part_ii.capital.other_increase_decrease"]
    withdrawals = values["part_ii.capital.withdrawals"]
    ending = values["part_ii.capital.ending"]
    assert beginning is not None
    assert contributed is not None
    assert income is not None
    assert other is not None
    assert withdrawals is not None
    assert ending is not None
    delta = capital_delta(beginning, contributed, income, other, withdrawals, ending)
    if abs(delta) <= tolerance:
        return []
    expected = ending + delta
    return [
        Finding(
            rule_id="capital_reconciles",
            severity=Severity.ERROR,
            message=(
                "Capital account does not reconcile: beginning + contributions + "
                "current-year net income + other increase (decrease) - withdrawals "
                f"is {expected}, ending is {ending} (difference {delta}, tolerance {tolerance})."
            ),
            field_path="part_ii.capital.ending",
            expected=str(expected),
            actual=str(ending),
        )
    ]


def _guaranteed_payments(doc: ScheduleK1, tolerance: Decimal) -> list[Finding]:
    services = doc.part_iii.guaranteed_payments_services.value
    capital = doc.part_iii.guaranteed_payments_capital.value
    total = doc.part_iii.guaranteed_payments_total.value
    if services is None or capital is None or total is None:
        return []
    expected = _money(services) + _money(capital)
    actual = _money(total)
    if abs(expected - actual) <= tolerance:
        return []
    return [
        Finding(
            rule_id="guaranteed_payments_total",
            severity=Severity.WARNING,
            message="Box 4c does not equal box 4a plus box 4b.",
            field_path="part_iii.guaranteed_payments_total",
            expected=str(expected),
            actual=str(actual),
        )
    ]


def _roster_holds(doc: ScheduleK1, roster: object | None) -> list[Finding]:
    """Identity stays in review unless a supplied roster matches the whole section."""

    from k1lens.roster import Roster, identity_holds

    if roster is None:
        loaded: Roster | None = None
    elif isinstance(roster, Roster):
        loaded = roster
    else:
        raise TypeError("The roster is not a parsed roster. Identity findings are not dropped.")
    findings: list[Finding] = []
    for hold in identity_holds(doc, loaded):
        if hold.rule_id == "duplicate_roster_key":
            findings.append(
                Finding(
                    rule_id="duplicate_roster_key",
                    severity=Severity.ERROR,
                    message=hold.message,
                    field_path=hold.field_path,
                )
            )
            continue
        if hold.rule_id == "no_roster":
            rule_id = "no_roster"
        elif hold.rule_id == "no_tin":
            rule_id = "no_tin"
        elif hold.rule_id == "no_roster_match":
            rule_id = "no_roster_match"
        elif hold.rule_id == "identity_mismatch":
            rule_id = "identity_mismatch"
        elif hold.rule_id == "new_partner":
            rule_id = "new_partner"
        else:
            continue
        findings.append(
            Finding(
                rule_id=rule_id,
                severity=Severity.ERROR,
                message=hold.message,
                field_path=hold.field_path,
            )
        )
    return findings


def _ocr_pages(doc: ScheduleK1) -> list[Finding]:
    """A page that failed OCR was not read. That is an error, not a log line.

    Overriding ``ocr_failed_pages`` is how a person accepts the gap. Until
    then the document cannot go straight through or be approved.
    """

    pages = doc.ocr_failed_pages
    if not pages:
        return []
    shown = ", ".join(str(page) for page in pages)
    if len(pages) == 1:
        message = (
            f"OCR failed on page {shown}. That page was not read, so this document stays in review."
        )
    else:
        message = (
            f"OCR failed on pages {shown}. "
            "Those pages were not read, so this document stays in review."
        )
    return [
        Finding(
            rule_id="ocr_page",
            severity=Severity.ERROR,
            message=message,
            field_path="ocr_failed_pages",
            actual=shown,
        )
    ]


def _synthetic_marker(doc: ScheduleK1) -> list[Finding]:
    findings: list[Finding] = []
    for path in ("part_i.name", "part_ii.name"):
        value = get_extracted(doc, path).value
        if not isinstance(value, str) or value.strip() == "":
            continue
        if "SAMPLE" not in value.upper():
            findings.append(
                Finding(
                    rule_id="synthetic_marker",
                    severity=Severity.WARNING,
                    message="Name is missing the SAMPLE marker. Synthetic documents only.",
                    field_path=path,
                    actual=value,
                )
            )
    return findings


def _short(value: object) -> str | None:
    if value is None:
        return None
    text = str(value)
    if len(text) > 200:
        return text[:200]
    return text


def _sorted(findings: list[Finding]) -> list[Finding]:
    severity_order = {Severity.ERROR: 0, Severity.WARNING: 1, Severity.INFO: 2}
    return sorted(
        findings, key=lambda item: (severity_order[item.severity], item.rule_id, item.field_path)
    )

"""Construct a Schedule K-1 whose fields are all present and empty."""

from __future__ import annotations

from decimal import Decimal

from k1lens.domain.models import (
    CapitalAccount,
    Extracted,
    PartI,
    PartII,
    PartIII,
    Provenance,
    ScheduleK1,
)


def extracted[T](
    value: T | None,
    *,
    label: str,
    extractor: str,
    page: int | None = None,
    confidence: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> Extracted[T]:
    if confidence is None:
        confidence = 0.0 if value is None else 1.0
    return Extracted[T](
        value=value,
        confidence=confidence,
        provenance=Provenance(
            page=page,
            bbox=bbox,
            field_name=label,
            extractor=extractor,
        ),
    )


def _s(
    label: str,
    extractor: str,
    value: str | None = None,
    page: int | None = None,
    confidence: float | None = None,
) -> Extracted[str]:
    return extracted(value, label=label, extractor=extractor, page=page, confidence=confidence)


def _m(
    label: str,
    extractor: str,
    value: Decimal | None = None,
    page: int | None = None,
    confidence: float | None = None,
) -> Extracted[Decimal]:
    return extracted(value, label=label, extractor=extractor, page=page, confidence=confidence)


def _b(
    label: str,
    extractor: str,
    value: bool | None = None,
    page: int | None = None,
    confidence: float | None = None,
) -> Extracted[bool]:
    return extracted(value, label=label, extractor=extractor, page=page, confidence=confidence)


def blank_schedule(
    document_id: str,
    *,
    extractor: str = "deterministic",
    variant: str = "unknown",
    tax_year: int | None = None,
) -> ScheduleK1:
    """A document with every field slot present and no values."""

    source = extractor
    return ScheduleK1(
        document_id=document_id,
        tax_year=tax_year,
        synthetic=True,
        variant=variant,
        part_i=PartI(
            ein=_s("A Partnership EIN", source),
            name=_s("B Partnership name", source),
            street=_s("B Partnership street", source),
            city=_s("B Partnership city", source),
            state=_s("B Partnership state", source),
            zip_code=_s("B Partnership ZIP", source),
            irs_center=_s("C IRS center", source),
            is_ptp=_b("D PTP", source),
        ),
        part_ii=PartII(
            tin=_s("E Partner TIN", source),
            name=_s("F Partner name", source),
            street=_s("F Partner street", source),
            city=_s("F Partner city", source),
            state=_s("F Partner state", source),
            zip_code=_s("F Partner ZIP", source),
            is_general_partner=_b("G General partner", source),
            is_domestic=_b("H1 Domestic partner", source),
            entity_type=_s("I1 Entity type", source),
            is_retirement_plan=_b("I2 Retirement plan", source),
            profit_beginning=_m("J Profit beginning pct", source),
            profit_ending=_m("J Profit ending pct", source),
            loss_beginning=_m("J Loss beginning pct", source),
            loss_ending=_m("J Loss ending pct", source),
            capital_share_beginning=_m("J Capital beginning pct", source),
            capital_share_ending=_m("J Capital ending pct", source),
            liability_nonrecourse=_m("K Nonrecourse", source),
            liability_qualified_nonrecourse=_m("K Qualified nonrecourse", source),
            liability_recourse=_m("K Recourse", source),
            capital_method=_s("L Capital method", source),
            capital=CapitalAccount(
                beginning=_m("L Beginning capital", source),
                contributed=_m("L Capital contributed", source),
                current_year_net_income=_m("L Current year net income", source),
                other_increase_decrease=_m("L Other increase decrease", source),
                withdrawals=_m("L Withdrawals and distributions", source),
                ending=_m("L Ending capital", source),
            ),
            contributed_builtin_gain=_b("M Built-in gain property", source),
        ),
        part_iii=PartIII(
            ordinary_business_income=_m("1 Ordinary business income", source),
            net_rental_real_estate=_m("2 Net rental real estate income", source),
            other_net_rental=_m("3 Other net rental income", source),
            guaranteed_payments_services=_m("4a Guaranteed payments for services", source),
            guaranteed_payments_capital=_m("4b Guaranteed payments for capital", source),
            guaranteed_payments_total=_m("4c Total guaranteed payments", source),
            interest_income=_m("5 Interest income", source),
            ordinary_dividends=_m("6a Ordinary dividends", source),
            qualified_dividends=_m("6b Qualified dividends", source),
            dividend_equivalents=_m("6c Dividend equivalents", source),
            royalties=_m("7 Royalties", source),
            net_short_term_capital_gain=_m("8 Net short-term capital gain", source),
            net_long_term_capital_gain=_m("9a Net long-term capital gain", source),
            collectibles_gain=_m("9b Collectibles gain", source),
            unrecaptured_1250_gain=_m("9c Unrecaptured section 1250 gain", source),
            net_section_1231_gain=_m("10 Net section 1231 gain", source),
            other_income=[],
            section_179_deduction=_m("12 Section 179 deduction", source),
            other_deductions=[],
            self_employment=[],
            credits=[],
            schedule_k3_attached=_b("16 Schedule K-3 attached", source),
            amt_items=[],
            tax_exempt_and_nondeductible=[],
            distributions=[],
            other_information=[],
            foreign_taxes_paid=_m("21 Foreign taxes paid or accrued", source),
        ),
    )

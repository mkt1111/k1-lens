"""Simplified current-year net income used by the sample generator.

This is not a Form 1065 tax bridge. It exists so synthetic capital accounts
have a coherent story. The validator does not recompute item L from Part III,
because on a real K-1 those amounts are not required to match line for line.
"""

from __future__ import annotations

from decimal import Decimal

from k1lens.domain.models import CodedAmount, PartIII


def _amount(value: Decimal | None) -> Decimal:
    if value is None:
        return Decimal("0")
    return value


def _coded(items: list[CodedAmount]) -> Decimal:
    return sum((_amount(item.amount.value) for item in items), start=Decimal("0"))


def synthetic_net_income(part_iii: PartIII) -> Decimal:
    income = (
        _amount(part_iii.ordinary_business_income.value)
        + _amount(part_iii.net_rental_real_estate.value)
        + _amount(part_iii.other_net_rental.value)
        + _amount(part_iii.interest_income.value)
        + _amount(part_iii.ordinary_dividends.value)
        + _amount(part_iii.royalties.value)
        + _amount(part_iii.net_short_term_capital_gain.value)
        + _amount(part_iii.net_long_term_capital_gain.value)
        + _amount(part_iii.net_section_1231_gain.value)
        + _coded(part_iii.other_income)
    )
    deductions = _amount(part_iii.section_179_deduction.value) + _coded(part_iii.other_deductions)
    return income - deductions

"""Return of capital, preferred return, GP catch-up, and carried interest.

This is a single distribution, not a fund-administration system. Preferred
return is simple interest on the unreturned capital used for that style.
There is no clawback, no management fee, and no multi-deal schedule.

American (deal-by-deal) uses ``unreturned_capital`` and ignores a fund-level
shortfall, so a deal that has returned its own capital can pay carry while
the fund still has unreturned capital elsewhere.

European (whole fund) uses ``fund_unreturned_capital`` when it is set, so a
distribution returns fund-level capital before any carry.

Rates are fractions: ``0.08`` is an 8% preferred return, ``0.20`` is a 20% carry.
``catch_up_gp_share`` of ``1`` means the catch-up tier is paid entirely to the GP
until the GP holds ``carry_rate`` of profits above returned capital.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

CENT = Decimal("0.01")


class WaterfallStyle(StrEnum):
    AMERICAN = "american"
    EUROPEAN = "european"


class WaterfallInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: WaterfallStyle
    distributable: Decimal = Field(ge=0)
    unreturned_capital: Decimal = Field(ge=0)
    preferred_rate: Decimal = Field(ge=0, le=1)
    years: Decimal = Field(ge=0)
    carry_rate: Decimal = Field(ge=0, lt=1)
    catch_up_gp_share: Decimal = Field(default=Decimal("1"), ge=0, le=1)
    accrued_preferred: Decimal | None = Field(default=None, ge=0)
    fund_unreturned_capital: Decimal | None = Field(default=None, ge=0)
    fund_accrued_preferred: Decimal | None = Field(default=None, ge=0)


class WaterfallResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    style: WaterfallStyle
    return_of_capital: Decimal
    preferred_return: Decimal
    gp_catch_up: Decimal
    lp_catch_up: Decimal
    residual_lp: Decimal
    residual_gp: Decimal
    unreturned_capital_used: Decimal
    accrued_preferred_used: Decimal

    @property
    def total(self) -> Decimal:
        return (
            self.return_of_capital
            + self.preferred_return
            + self.gp_catch_up
            + self.lp_catch_up
            + self.residual_lp
            + self.residual_gp
        )

    @property
    def gp_profit(self) -> Decimal:
        return self.gp_catch_up + self.residual_gp

    @property
    def lp_profit(self) -> Decimal:
        return self.preferred_return + self.lp_catch_up + self.residual_lp


def distribute(request: WaterfallInput) -> WaterfallResult:
    unreturned, accrued = _balances(request)
    cash = _cents(request.distributable)
    unreturned = _cents(unreturned)
    accrued = _cents(accrued)

    return_of_capital = min(cash, unreturned)
    remaining = cash - return_of_capital
    preferred = min(remaining, accrued)
    remaining -= preferred

    gp_catch_up, lp_catch_up, remaining = _catch_up(
        remaining,
        preferred,
        request.carry_rate,
        request.catch_up_gp_share,
    )
    residual_gp = _cents(remaining * request.carry_rate)
    residual_lp = remaining - residual_gp
    return WaterfallResult(
        style=request.style,
        return_of_capital=return_of_capital,
        preferred_return=preferred,
        gp_catch_up=gp_catch_up,
        lp_catch_up=lp_catch_up,
        residual_lp=residual_lp,
        residual_gp=residual_gp,
        unreturned_capital_used=unreturned,
        accrued_preferred_used=accrued,
    )


def accrued_preferred(
    unreturned_capital: Decimal, preferred_rate: Decimal, years: Decimal
) -> Decimal:
    """Simple interest. ``unreturned * rate * years``, rounded to cents."""

    return _cents(unreturned_capital * preferred_rate * years)


def _balances(request: WaterfallInput) -> tuple[Decimal, Decimal]:
    if request.style is WaterfallStyle.EUROPEAN and request.fund_unreturned_capital is not None:
        unreturned = request.fund_unreturned_capital
        if request.fund_accrued_preferred is not None:
            accrued = request.fund_accrued_preferred
        elif request.accrued_preferred is not None:
            accrued = request.accrued_preferred
        else:
            accrued = accrued_preferred(unreturned, request.preferred_rate, request.years)
        return unreturned, accrued

    unreturned = request.unreturned_capital
    if request.accrued_preferred is not None:
        accrued = request.accrued_preferred
    else:
        accrued = accrued_preferred(unreturned, request.preferred_rate, request.years)
    return unreturned, accrued


def _catch_up(
    remaining: Decimal,
    preferred: Decimal,
    carry_rate: Decimal,
    gp_share: Decimal,
) -> tuple[Decimal, Decimal, Decimal]:
    if remaining == 0 or carry_rate == 0 or gp_share == 0 or preferred == 0:
        return Decimal("0.00"), Decimal("0.00"), remaining
    target_gp = _cents((carry_rate / (Decimal("1") - carry_rate)) * preferred)
    if gp_share == 1:
        gp_amount = min(remaining, target_gp)
        return gp_amount, Decimal("0.00"), remaining - gp_amount
    dollars_needed = _cents(target_gp / gp_share)
    dollars = min(remaining, dollars_needed)
    gp_amount = _cents(dollars * gp_share)
    if gp_amount > dollars:
        gp_amount = dollars
    lp_amount = dollars - gp_amount
    return gp_amount, lp_amount, remaining - dollars


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)

"""Distribution waterfall invariants."""

from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from pydantic import ValidationError

from k1lens.waterfall.distribute import WaterfallInput, WaterfallStyle, distribute

CASH = st.decimals(
    min_value="0", max_value="1000000", places=2, allow_nan=False, allow_infinity=False
)
RATE = st.decimals(min_value="0", max_value="0.5", places=4, allow_nan=False, allow_infinity=False)
CARRY = st.decimals(min_value="0", max_value="0.5", places=2, allow_nan=False, allow_infinity=False)
YEARS = st.decimals(min_value="0", max_value="10", places=2, allow_nan=False, allow_infinity=False)
SHARE = st.decimals(min_value="0", max_value="1", places=2, allow_nan=False, allow_infinity=False)


def test_fully_funded_deal_pays_twenty_percent_carry() -> None:
    result = distribute(
        WaterfallInput(
            style=WaterfallStyle.AMERICAN,
            distributable=Decimal("2000"),
            unreturned_capital=Decimal("1000"),
            preferred_rate=Decimal("0.08"),
            years=Decimal("1"),
            carry_rate=Decimal("0.20"),
            accrued_preferred=Decimal("80"),
        )
    )
    assert result.total == Decimal("2000.00")
    assert result.return_of_capital == Decimal("1000.00")
    assert result.preferred_return == Decimal("80.00")
    assert result.gp_catch_up == Decimal("20.00")
    assert result.gp_profit == Decimal("200.00")
    assert result.lp_profit == Decimal("800.00")


def test_american_can_pay_carry_while_the_fund_is_still_short() -> None:
    common = dict(
        distributable=Decimal("100000"),
        unreturned_capital=Decimal("0"),
        preferred_rate=Decimal("0.08"),
        years=Decimal("0"),
        carry_rate=Decimal("0.20"),
        accrued_preferred=Decimal("0"),
        fund_unreturned_capital=Decimal("500000"),
    )
    american = distribute(WaterfallInput(style=WaterfallStyle.AMERICAN, **common))
    european = distribute(WaterfallInput(style=WaterfallStyle.EUROPEAN, **common))
    assert american.gp_profit == Decimal("20000.00")
    assert european.return_of_capital == Decimal("100000.00")
    assert european.gp_profit == Decimal("0.00")


def test_partial_catch_up_splits_the_tier() -> None:
    result = distribute(
        WaterfallInput(
            style=WaterfallStyle.AMERICAN,
            distributable=Decimal("1100"),
            unreturned_capital=Decimal("1000"),
            preferred_rate=Decimal("0"),
            years=Decimal("0"),
            carry_rate=Decimal("0.20"),
            accrued_preferred=Decimal("80"),
            catch_up_gp_share=Decimal("0.50"),
        )
    )
    assert result.preferred_return == Decimal("80.00")
    assert result.gp_catch_up > 0
    assert result.lp_catch_up > 0
    assert result.residual_gp == 0
    assert result.total == Decimal("1100.00")


def test_european_fund_preferred_is_computed_when_unset() -> None:
    result = distribute(
        WaterfallInput(
            style=WaterfallStyle.EUROPEAN,
            distributable=Decimal("5000"),
            unreturned_capital=Decimal("100"),
            preferred_rate=Decimal("0.08"),
            years=Decimal("2"),
            carry_rate=Decimal("0.20"),
            fund_unreturned_capital=Decimal("1000"),
        )
    )
    assert result.unreturned_capital_used == Decimal("1000.00")
    assert result.accrued_preferred_used == Decimal("160.00")
    assert result.return_of_capital == Decimal("1000.00")
    assert result.preferred_return == Decimal("160.00")


def test_zero_carry_pays_the_gp_nothing() -> None:
    result = distribute(
        WaterfallInput(
            style=WaterfallStyle.EUROPEAN,
            distributable=Decimal("500"),
            unreturned_capital=Decimal("100"),
            preferred_rate=Decimal("0.08"),
            years=Decimal("1"),
            carry_rate=Decimal("0"),
        )
    )
    assert result.gp_profit == 0
    assert result.total == Decimal("500.00")


def test_rejects_negative_cash_and_full_carry() -> None:
    with pytest.raises(ValidationError):
        WaterfallInput(
            style=WaterfallStyle.AMERICAN,
            distributable=Decimal("-1"),
            unreturned_capital=Decimal("0"),
            preferred_rate=Decimal("0"),
            years=Decimal("0"),
            carry_rate=Decimal("0.2"),
        )
    with pytest.raises(ValidationError):
        WaterfallInput(
            style=WaterfallStyle.AMERICAN,
            distributable=Decimal("1"),
            unreturned_capital=Decimal("0"),
            preferred_rate=Decimal("0"),
            years=Decimal("0"),
            carry_rate=Decimal("1"),
        )


@given(
    cash=CASH,
    unreturned=CASH,
    rate=RATE,
    years=YEARS,
    carry=CARRY,
    share=SHARE,
    style=st.sampled_from([WaterfallStyle.AMERICAN, WaterfallStyle.EUROPEAN]),
    fund_short=st.booleans(),
)
@settings(max_examples=60, deadline=None)
def test_distribution_conserves_cash(
    cash: Decimal,
    unreturned: Decimal,
    rate: Decimal,
    years: Decimal,
    carry: Decimal,
    share: Decimal,
    style: WaterfallStyle,
    fund_short: bool,
) -> None:
    fund_unreturned = unreturned + Decimal("1000") if fund_short else None
    result = distribute(
        WaterfallInput(
            style=style,
            distributable=cash,
            unreturned_capital=unreturned,
            preferred_rate=rate,
            years=years,
            carry_rate=carry,
            catch_up_gp_share=share,
            fund_unreturned_capital=fund_unreturned,
        )
    )
    assert result.total == cash.quantize(Decimal("0.01"))
    assert result.return_of_capital >= 0
    assert result.preferred_return >= 0
    assert result.gp_catch_up >= 0
    assert result.lp_catch_up >= 0
    assert result.residual_lp >= 0
    assert result.residual_gp >= 0
    assert result.return_of_capital <= result.unreturned_capital_used
    assert result.preferred_return <= result.accrued_preferred_used
    if carry == 0 or share == 0:
        assert result.gp_catch_up == 0

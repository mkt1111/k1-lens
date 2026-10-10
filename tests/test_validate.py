"""Rules engine, including property tests of the capital-account equation."""

import random
import re
from decimal import Decimal
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from k1lens.domain.models import ScheduleK1
from k1lens.generate.build import Variant, build_document
from k1lens.validate.engine import capital_delta, validate_document, validate_payload

MONEY = st.decimals(
    min_value=Decimal("-1000000"),
    max_value=Decimal("1000000"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)
TOLERANCE = st.decimals(
    min_value=Decimal("0"),
    max_value=Decimal("100"),
    places=2,
    allow_nan=False,
    allow_infinity=False,
)


def _ids(document: ScheduleK1, tolerance: Decimal = Decimal("1")) -> set[str]:
    return {finding.rule_id for finding in validate_document(document, tolerance=tolerance)}


def _with_capital(document: ScheduleK1, **values: Decimal | None) -> ScheduleK1:
    payload = document.model_dump(mode="json")
    for name, value in values.items():
        node = payload["part_ii"]["capital"][name]
        node["value"] = None if value is None else str(value)
        node["confidence"] = 0 if value is None else 1
    return ScheduleK1.model_validate(payload)


@pytest.fixture(scope="module")
def base() -> ScheduleK1:
    return build_document(random.Random(11), 1, Variant.CLEAN)


def test_clean_document_has_no_errors(base: ScheduleK1) -> None:
    findings = validate_document(base, tolerance=Decimal("0.01"))
    errors = [finding for finding in findings if finding.severity.value == "error"]
    assert errors
    assert {finding.rule_id for finding in errors} == {"no_roster"}


def test_missing_required_fields_and_incomplete_capital() -> None:
    document = build_document(random.Random(11), 4, Variant.MISSING_FIELDS)
    rules = _ids(document)
    assert "required_fields" in rules
    assert "capital_incomplete" in rules
    assert "capital_reconciles" not in rules
    assert "ein_format" not in rules


def test_inconsistent_capital_is_an_error() -> None:
    document = build_document(random.Random(11), 5, Variant.INCONSISTENT_CAPITAL)
    findings = [
        item for item in validate_document(document) if item.rule_id == "capital_reconciles"
    ]
    assert len(findings) == 1
    assert findings[0].severity.value == "error"
    assert findings[0].field_path == "part_ii.capital.ending"


def test_invalid_ein_and_percentage_variants() -> None:
    ein_doc = build_document(random.Random(11), 6, Variant.INVALID_EIN)
    assert "ein_format" in _ids(ein_doc)
    percent_doc = build_document(random.Random(11), 7, Variant.INVALID_PERCENTAGE)
    assert "percentage_range" in _ids(percent_doc)


def test_tin_format_and_synthetic_marker(base: ScheduleK1) -> None:
    payload = base.model_dump(mode="json")
    payload["part_ii"]["tin"]["value"] = "12"
    payload["part_i"]["name"]["value"] = "Northwind Partners LP"
    document = ScheduleK1.model_validate(payload)
    rules = _ids(document)
    assert "tin_format" in rules
    assert "synthetic_marker" in rules


def test_negative_withdrawals_and_distributions_are_errors(base: ScheduleK1) -> None:
    negative = _with_capital(base, withdrawals=Decimal("-10.00"))
    withdrawal_paths = [
        item.field_path
        for item in validate_document(negative)
        if item.rule_id == "withdrawals_non_negative"
    ]
    assert "part_ii.capital.withdrawals" in withdrawal_paths

    payload = base.model_dump(mode="json")
    payload["part_iii"]["distributions"] = [
        {
            "code": "C",
            "description": None,
            "amount": {
                "value": "-2.00",
                "confidence": 1.0,
                "provenance": {
                    "page": 2,
                    "bbox": None,
                    "field_name": "19 Distributions C",
                    "extractor": "test",
                },
            },
        }
    ]
    document = ScheduleK1.model_validate(payload)
    paths = [
        item.field_path
        for item in validate_document(document)
        if item.rule_id == "withdrawals_non_negative"
    ]
    assert paths == ["part_iii.distributions[C]"]
    assert "withdrawals_non_negative" not in _ids(base)


def test_guaranteed_payments_warning(base: ScheduleK1) -> None:
    payload = base.model_dump(mode="json")
    payload["part_iii"]["guaranteed_payments_total"]["value"] = "99999.00"
    document = ScheduleK1.model_validate(payload)
    findings = validate_document(document)
    assert any(
        item.rule_id == "guaranteed_payments_total" and item.severity.value == "warning"
        for item in findings
    )


def test_type_check_findings_from_raw_json(base: ScheduleK1) -> None:
    payload = base.model_dump(mode="json")
    payload["part_ii"]["profit_ending"]["value"] = {"not": "a number"}
    payload["synthetic"] = False
    findings = validate_payload(payload)
    assert findings
    assert all(item.rule_id == "type_check" for item in findings)


def test_percentage_boundaries(base: ScheduleK1) -> None:
    for value, ok in (
        ("0", True),
        ("100", True),
        ("40.5", True),
        ("-0.01", False),
        ("100.01", False),
    ):
        payload = base.model_dump(mode="json")
        payload["part_ii"]["loss_ending"]["value"] = value
        document = ScheduleK1.model_validate(payload)
        matched = "percentage_range" in _ids(document)
        assert matched is not ok


def test_valid_ein_and_ssn_shapes_pass(base: ScheduleK1) -> None:
    payload = base.model_dump(mode="json")
    payload["part_i"]["ein"]["value"] = "00-1234567"
    payload["part_ii"]["tin"]["value"] = "000-00-6789"
    document = ScheduleK1.model_validate(payload)
    rules = _ids(document)
    assert "ein_format" not in rules
    assert "tin_format" not in rules


@given(
    beginning=MONEY,
    contributed=MONEY,
    income=MONEY,
    other=MONEY,
    withdrawals=MONEY,
    tolerance=TOLERANCE,
)
@settings(max_examples=50, deadline=None)
def test_capital_rule_matches_the_equation(
    base: ScheduleK1,
    beginning: Decimal,
    contributed: Decimal,
    income: Decimal,
    other: Decimal,
    withdrawals: Decimal,
    tolerance: Decimal,
) -> None:
    ending = beginning + contributed + income + other - withdrawals
    assert capital_delta(beginning, contributed, income, other, withdrawals, ending) == 0
    tied = _with_capital(
        base,
        beginning=beginning,
        contributed=contributed,
        current_year_net_income=income,
        other_increase_decrease=other,
        withdrawals=withdrawals,
        ending=ending,
    )
    assert "capital_reconciles" not in _ids(tied, tolerance)
    broken_ending = ending + tolerance + Decimal("0.01")
    broken = _with_capital(
        base,
        beginning=beginning,
        contributed=contributed,
        current_year_net_income=income,
        other_increase_decrease=other,
        withdrawals=withdrawals,
        ending=broken_ending,
    )
    assert "capital_reconciles" in _ids(broken, tolerance)
    delta = capital_delta(beginning, contributed, income, other, withdrawals, broken_ending)
    assert abs(delta) > tolerance


@given(ein=st.from_regex(r"[0-9]{2}-[0-9]{7}", fullmatch=True))
@settings(max_examples=20, deadline=None)
def test_well_formed_eins_pass(base: ScheduleK1, ein: str) -> None:
    payload = base.model_dump(mode="json")
    payload["part_i"]["ein"]["value"] = ein
    document = ScheduleK1.model_validate(payload)
    assert "ein_format" not in _ids(document)


def test_readme_lists_every_engine_rule() -> None:
    source = Path("src/k1lens/validate/engine.py").read_text(encoding="utf-8")
    rule_ids = set(re.findall(r'rule_id="([^"]+)"', source))
    readme = Path("README.md").read_text(encoding="utf-8")
    missing = sorted(rule_id for rule_id in rule_ids if f"`{rule_id}`" not in readme)
    assert missing == []
    assert "capital_incomplete" in rule_ids

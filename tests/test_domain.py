"""Schema, parsing, and field updates."""

import random
from decimal import Decimal

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from k1lens.domain.access import UnknownFieldError, apply_correction, get_extracted
from k1lens.domain.blank import blank_schedule
from k1lens.domain.fields import SCALAR_FIELDS, FieldKind
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import format_decimal, parse_bool, parse_decimal, values_equal
from k1lens.generate.build import Variant, build_document


def test_blank_schedule_has_every_scalar_field() -> None:
    document = blank_schedule("K1-TEST")
    for spec in SCALAR_FIELDS:
        field = get_extracted(document, spec.path)
        assert field.value is None
        assert field.confidence == 0
    assert document.synthetic is True


def test_ocr_page_numbers_start_at_one() -> None:
    document = build_document(random.Random(1), 1, Variant.CLEAN)
    payload = document.model_dump(mode="json")
    assert "ocr_failed_pages" not in payload
    payload["ocr_failed_pages"] = [0]
    with pytest.raises(ValueError, match="start at 1"):
        ScheduleK1.model_validate(payload)
    payload["ocr_failed_pages"] = [2]
    loaded = ScheduleK1.model_validate(payload)
    assert loaded.ocr_failed_pages == [2]
    assert "ocr_failed_pages" in loaded.model_dump(mode="json")


def test_generator_json_omits_unset_read_facts() -> None:
    """A new provenance default must not rewrite a generated scan file."""

    document = build_document(random.Random(1), 1, Variant.CLEAN)
    payload = document.model_dump_json()
    assert "id_digit_confidence" not in payload
    assert "evidence_confidence" not in payload
    assert "own_region" not in payload
    data = document.model_dump(mode="json")
    ein = data["part_i"]["ein"]
    assert isinstance(ein, dict)
    source = ein["provenance"]
    assert isinstance(source, dict)
    source["id_digit_confidence"] = 0.4
    source["evidence_confidence"] = 0.92
    source["own_region"] = False
    restored = ScheduleK1.model_validate(data)
    again = restored.model_dump(mode="json")
    kept = again["part_i"]["ein"]["provenance"]
    assert kept["id_digit_confidence"] == 0.4
    assert kept["evidence_confidence"] == 0.92
    assert kept["own_region"] is False
    city = again["part_i"]["city"]["provenance"]
    assert "id_digit_confidence" not in city
    assert "own_region" not in city


def test_rejects_non_synthetic_documents() -> None:
    document = build_document(random.Random(1), 1, Variant.CLEAN)
    payload = document.model_dump(mode="json")
    payload["synthetic"] = False
    with pytest.raises(ValueError, match="synthetic"):
        ScheduleK1.model_validate(payload)


def test_round_trip_json() -> None:
    document = build_document(random.Random(2), 3, Variant.CLEAN)
    again = ScheduleK1.model_validate_json(document.model_dump_json())
    assert again == document


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,200.50", Decimal("1200.50")),
        ("$10", Decimal("10")),
        ("(15.25)", Decimal("-15.25")),
        ("40-", Decimal("-40")),
        ("+8.5", Decimal("8.5")),
    ],
)
def test_parse_decimal(raw: str, expected: Decimal) -> None:
    assert parse_decimal(raw) == expected


def test_parse_decimal_rejects_blank_and_text() -> None:
    with pytest.raises(ValueError):
        parse_decimal("   ")
    with pytest.raises(ValueError):
        parse_decimal("n/a")


def test_parse_bool() -> None:
    assert parse_bool("Yes") is True
    assert parse_bool("no") is False
    with pytest.raises(ValueError):
        parse_bool("maybe")


@given(
    value=st.decimals(
        min_value=Decimal("-1000000"),
        max_value=Decimal("1000000"),
        places=2,
        allow_nan=False,
        allow_infinity=False,
    )
)
@settings(max_examples=40)
def test_decimal_format_round_trip(value: Decimal) -> None:
    assert parse_decimal(format_decimal(value)) == value.quantize(Decimal("0.01"))


def test_values_equal_respects_tolerance_and_text() -> None:
    assert values_equal(FieldKind.MONEY, Decimal("1.00"), Decimal("1.50"), Decimal("1"))
    assert not values_equal(FieldKind.MONEY, Decimal("1"), None, Decimal("1"))
    assert values_equal(FieldKind.STRING, " SAMPLE ", "SAMPLE", Decimal("0"))
    assert values_equal(FieldKind.BOOL, True, True, Decimal("0"))
    assert values_equal(FieldKind.INT, 2, 2, Decimal("0"))
    assert values_equal(FieldKind.MONEY, None, None, Decimal("0"))


def test_correction_updates_value_confidence_and_provenance() -> None:
    document = build_document(random.Random(3), 1, Variant.CLEAN)
    updated = apply_correction(document, "part_i.ein", "00-9999999", "ada lovelace")
    field = updated.part_i.ein
    assert field.value == "00-9999999"
    assert field.confidence == 1
    assert field.provenance.extractor == "human:ada lovelace"
    assert field.provenance.page == document.part_i.ein.provenance.page


def test_tax_year_correction_sets_reviewer_confidence() -> None:
    document = build_document(random.Random(3), 1, Variant.CLEAN)
    updated = apply_correction(document, "tax_year", 2024, "ada")
    assert updated.tax_year == 2024
    assert updated.tax_year_confidence == 1
    assert updated.tax_year_extractor == "human:ada"
    cleared = apply_correction(updated, "tax_year", None, "ada")
    assert cleared.tax_year is None
    assert cleared.tax_year_confidence == 0


def test_clearing_a_field_zeroes_confidence() -> None:
    document = build_document(random.Random(3), 1, Variant.CLEAN)
    updated = apply_correction(document, "part_iii.interest_income", None, "ada")
    assert updated.part_iii.interest_income.value is None
    assert updated.part_iii.interest_income.confidence == 0


def test_coded_correction_and_unknown_path() -> None:
    document = build_document(random.Random(4), 2, Variant.CLEAN)
    payload = document.model_dump(mode="json")
    payload["part_iii"]["distributions"] = [
        {
            "code": "A",
            "description": None,
            "amount": {
                "value": "10.00",
                "confidence": 0.4,
                "provenance": {
                    "page": 2,
                    "bbox": [1, 2, 3, 4],
                    "field_name": "19 Distributions A",
                    "extractor": "deterministic",
                },
            },
        }
    ]
    document = ScheduleK1.model_validate(payload)
    updated = apply_correction(document, "part_iii.distributions[a]", "12.50", "ada")
    assert updated.part_iii.distributions[0].amount.value == Decimal("12.50")
    with pytest.raises(UnknownFieldError):
        apply_correction(document, "part_iii.distributions[Z]", "1", "ada")
    with pytest.raises(UnknownFieldError):
        apply_correction(document, "not.a.field", "1", "ada")

"""Public K-1 line names, not fixture captions, drive label matching."""

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.extract.labels import _ABBREV, ABBREV_SOURCE, resolve_field_label


def test_abbreviation_keys_are_sourced() -> None:
    assert set(ABBREV_SOURCE) == set(_ABBREV)
    assert set(ABBREV_SOURCE.values()) <= {"irs-k1-1065", "general-accounting"}
    leaked = {
        "begin",
        "distr",
        "distrib",
        "divs",
        "empl",
        "equiv",
        "guar",
        "pmts",
        "yrs",
        "ptrshp",
        "addr",
        "withdr",
        "nonrec",
        "unrecapt",
    }
    assert leaked.isdisjoint(ABBREV_SOURCE)


def test_box_number_anchors_a_unique_line() -> None:
    resolved = resolve_field_label("1 Ordinary business income (loss)")
    assert resolved is not None
    assert resolved[0] == "1 Ordinary business income"
    assert resolved[1] >= 0.85


def test_abbreviations_of_form_words_match() -> None:
    resolved = resolve_field_label("5 Interest inc.")
    assert resolved is not None
    assert resolved[0] == "5 Interest income"
    ordinary = resolve_field_label("Ord. business inc.")
    assert ordinary is not None
    assert ordinary[0] == "1 Ordinary business income"


def test_coded_line_needs_a_letter_and_refuses_a_bare_box() -> None:
    refused = resolve_field_label("19")
    assert refused is None
    resolved = resolve_field_label("19 Distributions code A")
    assert resolved is not None
    assert resolved[0] == "19 Distributions A"


def test_shared_box_without_a_description_is_refused() -> None:
    assert resolve_field_label("L") is None
    assert resolve_field_label("Item L") is None


def test_item_l_lines_stay_distinct() -> None:
    beginning = resolve_field_label("L Beginning capital account")
    ending = resolve_field_label("L Ending capital account")
    assert beginning is not None and beginning[0] == "L Beginning capital"
    assert ending is not None and ending[0] == "L Ending capital"
    assert resolve_field_label("L capital account") is None


def test_nonrecourse_does_not_absorb_the_qualified_line() -> None:
    plain = resolve_field_label("K Nonrecourse")
    qualified = resolve_field_label("K Qualified nonrecourse financing")
    assert plain is not None and plain[0] == "K Nonrecourse"
    assert qualified is not None and qualified[0] == "K Qualified nonrecourse"


def test_a_box_number_that_contradicts_the_description_is_refused() -> None:
    assert resolve_field_label("1 Interest income") is None


def test_a_thin_unboxed_token_is_refused() -> None:
    assert resolve_field_label("Interest") is None
    assert resolve_field_label("Income") is None


def test_official_unboxed_title_matches() -> None:
    resolved = resolve_field_label("Partnership's employer identification number")
    assert resolved is not None
    assert resolved[0] == "A Partnership EIN"
    assert resolved[1] >= REVIEW_THRESHOLD

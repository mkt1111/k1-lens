"""General review rules for free text, layout, and OCR punctuation.

The strings are built from the rule. They are not a probe list.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.parsing import (
    canonicalize_capital_method,
    canonicalize_entity_type,
    entity_type_ok,
    parse_bool,
)
from k1lens.extract.confidence import (
    city_shape_ok,
    identity_may_clear,
    name_shape_ok,
    strip_caption_prefix,
)
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.geometry import PlacedWord, pair_words
from k1lens.extract.ocr import OcrLine, OcrWord, _absorb, _strip_separator_period

_ANCHORS = (
    ("A Partnership EIN", "00-0000001"),
    ("B Partnership street", "100 Main St"),
    ("B Partnership state", "CA"),
    ("B Partnership ZIP", "94105"),
    ("E Partner TIN", "000-00-0001"),
    ("F Partner street", "200 Oak Ave"),
    ("F Partner state", "NY"),
    ("F Partner ZIP", "10001"),
)


def _draw(path: Path, lines: list[tuple[str, str]]) -> object:
    canvas = Canvas(str(path), pagesize=letter)
    y = 720
    for label, value in (*_ANCHORS, *lines):
        canvas.drawString(48, y, f"{label}: {value}")
        y -= 16
    canvas.save()
    return DeterministicExtractor().extract(path)


def test_structural_names_pass_the_own_box_gate_and_stay_under_0_80(
    tmp_path: Path,
) -> None:
    names = (
        "McDonald Holdings L.P.",
        "MacArthur & Cole L.L.C.",
        "O'Brien Capital LP",
        "De La Cruz Fund II",
        "Harbor Growth Fund 3",
        "Jordan Smith Inc.",
    )
    for name in names:
        assert name_shape_ok(name) is True, name
        assert identity_may_clear("part_i.name", name, own_box=True) is True, name
        assert identity_may_clear("part_i.name", name, own_box=False) is False
    assert name_shape_ok("Quarterly Briefing") is True
    assert identity_may_clear("part_i.name", "Quarterly Briefing", own_box=True) is False
    document = _draw(tmp_path / "names.pdf", [("B Partnership name", names[0])])
    assert document.part_i.name.value == "McDonald Holdings L.P."
    assert document.part_i.name.confidence < REVIEW_THRESHOLD


def test_city_particles_and_multi_word_cities_pass_the_shape(tmp_path: Path) -> None:
    cities = ("St. Louis", "Ft. Worth", "Rio de Janeiro", "Kansas City")
    for city in cities:
        assert city_shape_ok(city) is True, city
        assert identity_may_clear("part_i.city", city, own_box=True) is True
    document = _draw(tmp_path / "city.pdf", [("B Partnership city", "Rio de Janeiro")])
    assert document.part_i.city.value == "Rio de Janeiro"
    assert document.part_i.city.confidence < REVIEW_THRESHOLD


def test_canonical_entity_strings_clear_and_a_paraphrase_does_not(tmp_path: Path) -> None:
    for printed, stored in (
        ("L.L.C.", "LLC"),
        ("S corporation", "S corporation"),
        ("Exempt organization", "Exempt organization"),
        ("Estate", "Estate"),
        ("Trust", "Trust"),
    ):
        assert entity_type_ok(printed) is True
        assert canonicalize_entity_type(printed) == stored
        assert identity_may_clear("part_ii.entity_type", stored, own_box=True) is True
    document = _draw(tmp_path / "entity.pdf", [("I1 Entity type", "L.L.C.")])
    assert document.part_ii.entity_type.value == "LLC"
    assert document.part_ii.entity_type.confidence >= REVIEW_THRESHOLD
    paraphrase = _draw(tmp_path / "para.pdf", [("I1 Entity type", "Closely held firm")])
    assert paraphrase.part_ii.entity_type.confidence < REVIEW_THRESHOLD


def test_a_caption_prefix_that_was_stripped_stays_under_review(tmp_path: Path) -> None:
    stored, stripped = strip_caption_prefix("part_i.name", "see instructions Northwind Partners LP")
    assert stripped is True
    assert stored == "Northwind Partners LP"
    assert identity_may_clear("part_i.name", stored, own_box=True, prefix_stripped=True) is False
    document = _draw(
        tmp_path / "prefix.pdf",
        [("B Partnership name", "see instructions Northwind Partners LP")],
    )
    assert document.part_i.name.value == "Northwind Partners LP"
    assert document.part_i.name.confidence < REVIEW_THRESHOLD


def test_yes_and_no_lose_a_separator_period_and_a_checked_method_parses() -> None:
    assert parse_bool("Yes.") is True
    assert parse_bool("No.") is False
    assert _strip_separator_period("Yes.") == "Yes"
    assert _strip_separator_period("No.") == "No"
    assert _strip_separator_period("Quinn Bros.") == "Quinn Bros."
    assert canonicalize_capital_method("X Tax basis.") == "Tax basis"
    assert canonicalize_capital_method("Tax basis.") == "Tax basis"
    label = "D PTP"
    observed: dict[str, list[object]] = {}
    _absorb(observed, OcrLine(f"{label}: Yes.", 90.0), 1)
    assert observed[label][0].raw == "Yes"


def test_a_wrapped_value_keeps_the_first_line_and_stays_under_review(tmp_path: Path) -> None:
    words = (
        PlacedWord("B", 40, 100, 52, 110),
        PlacedWord("Partnership", 56, 100, 130, 110),
        PlacedWord("name", 134, 100, 170, 110),
        PlacedWord("Northwind", 180, 100, 250, 110),
        PlacedWord("Partners", 254, 100, 310, 110),
        PlacedWord("LP", 314, 100, 330, 110),
        PlacedWord("Holdings", 180, 114, 240, 124),
    )
    found = {pair.label: pair for pair in pair_words(words)}
    pair = found["B Partnership name"]
    assert pair.value == "Northwind Partners LP"
    assert pair.truncated is True
    canvas = Canvas(str(tmp_path / "wrap.pdf"), pagesize=letter)
    y = 720
    for label, value in _ANCHORS:
        canvas.drawString(48, y, f"{label}: {value}")
        y -= 16
    canvas.drawString(48, y, "B Partnership name: Northwind Partners LP")
    canvas.drawString(230, y - 14, "Holdings")
    canvas.save()
    document = DeterministicExtractor().extract(tmp_path / "wrap.pdf")
    assert document.part_i.name.value == "Northwind Partners LP"
    assert document.part_i.name.confidence < REVIEW_THRESHOLD


def test_a_caption_above_does_not_take_the_neighboring_column() -> None:
    words = (
        PlacedWord("B", 40, 100, 52, 110),
        PlacedWord("Partnership's", 56, 100, 140, 110),
        PlacedWord("name,", 144, 100, 180, 110),
        PlacedWord("address,", 184, 100, 240, 110),
        PlacedWord("city,", 244, 100, 280, 110),
        PlacedWord("state,", 284, 100, 320, 110),
        PlacedWord("and", 324, 100, 348, 110),
        PlacedWord("ZIP", 352, 100, 376, 110),
        PlacedWord("code", 380, 100, 410, 110),
        PlacedWord("Northwind", 40, 124, 110, 134),
        PlacedWord("Partners", 114, 124, 180, 134),
        PlacedWord("LP", 184, 124, 204, 134),
        PlacedWord("Austin", 400, 124, 450, 134),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found["B Partnership name"] == "Northwind Partners LP"
    assert "Austin" not in found["B Partnership name"]


def test_an_auxiliary_row_is_not_an_address() -> None:
    words = (
        PlacedWord("B", 40, 100, 52, 110),
        PlacedWord("Partnership", 56, 100, 130, 110),
        PlacedWord("street", 134, 100, 180, 110),
        PlacedWord("Statement", 40, 124, 110, 134),
        PlacedWord("4", 114, 124, 128, 134),
        PlacedWord("100", 40, 148, 64, 158),
        PlacedWord("Main", 68, 148, 100, 158),
        PlacedWord("Street", 104, 148, 150, 158),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found.get("B Partnership street") == "100 Main Street"
    assert "Statement" not in found.get("B Partnership street", "")


def test_a_street_keeps_a_trailing_unit_past_a_short_gap() -> None:
    words = (
        PlacedWord("B", 40, 100, 52, 110),
        PlacedWord("Partnership", 56, 100, 130, 110),
        PlacedWord("street", 134, 100, 180, 110),
        PlacedWord("100", 190, 100, 214, 110),
        PlacedWord("Main", 218, 100, 250, 110),
        PlacedWord("Street", 254, 100, 290, 110),
        PlacedWord("Suite", 312, 100, 348, 110),
        PlacedWord("4", 352, 100, 364, 110),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found["B Partnership street"] == "100 Main Street Suite 4"


def test_a_dropped_ocr_unit_is_kept_and_held() -> None:
    label = "B Partnership street"
    line = OcrLine(
        f"{label}: 100 Main Street",
        95.0,
        words=(
            OcrWord("100", 95, 10, 10, 20, 8),
            OcrWord("Main", 95, 32, 10, 30, 8),
            OcrWord("Street", 95, 64, 10, 40, 8),
        ),
        dropped=(OcrWord("4", -1, 110, 10, 12, 8),),
    )
    observed: dict[str, list[object]] = {}
    _absorb(observed, line, 1)
    assert observed[label][0].raw == "100 Main Street 4"
    assert observed[label][0].truncated is True

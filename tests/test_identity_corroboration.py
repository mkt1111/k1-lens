"""A name or a city stays under 0.80 without a roster. An exact entity type
can reach the threshold.

The phrases below are built for the rule. They are not a probe list.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.extract.confidence import identity_may_clear, strip_trailing_punctuation
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.geometry import PlacedWord, pair_words

# Enough catalog lines that the page is a recognized layout. The field
# under test is drawn separately so these anchors do not fill it.
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


def _draw(path: Path, lines: list[tuple[str, str]]) -> None:
    canvas = Canvas(str(path), pagesize=letter)
    y = 720
    for label, value in (*_ANCHORS, *lines):
        canvas.drawString(48, y, f"{label}: {value}")
        y -= 16
    canvas.save()


def _name(path: Path, value: str) -> object:
    _draw(path, [("B Partnership name", value), ("F Partner name", "Northwind Partners LP")])
    return DeterministicExtractor().extract(path)


def test_a_title_case_phrase_in_the_value_slot_stays_under_review(tmp_path: Path) -> None:
    """A status-shaped phrase is not a name just because each word is capitalized."""

    document = _name(tmp_path / "phrase.pdf", "Quarterly Briefing")
    assert document.part_i.name.value == "Quarterly Briefing"
    assert document.part_i.name.confidence < REVIEW_THRESHOLD
    assert identity_may_clear("part_i.name", "Quarterly Briefing", own_box=True) is False


def test_a_copy_line_read_as_the_partner_name_stays_under_review(tmp_path: Path) -> None:
    """A short designation and a form legend are not structural names."""

    copy_line = _name(tmp_path / "copy.pdf", "Notice B")
    assert copy_line.part_i.name.value == "Notice B"
    assert copy_line.part_i.name.confidence < REVIEW_THRESHOLD
    legend = _name(tmp_path / "legend.pdf", "Schedule K-1 (Form 1065)")
    assert legend.part_i.name.confidence < REVIEW_THRESHOLD


def test_a_blank_name_is_not_taken_from_the_city_line() -> None:
    words = (
        PlacedWord("F", 40, 100, 48, 109),
        PlacedWord("Partner", 52, 100, 100, 109),
        PlacedWord("name", 104, 100, 140, 109),
        PlacedWord("Lakeside", 40, 114, 90, 123),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert "F Partner name" not in found


def test_two_column_names_are_not_one_value() -> None:
    words = (
        PlacedWord("B", 40, 100, 48, 109),
        PlacedWord("Partnership", 52, 100, 110, 109),
        PlacedWord("name", 114, 100, 140, 109),
        PlacedWord("Northwind", 150, 100, 210, 109),
        PlacedWord("Partners", 214, 100, 260, 109),
        PlacedWord("LP", 264, 100, 280, 109),
        PlacedWord("Avery", 304, 100, 340, 109),
        PlacedWord("Quinn", 344, 100, 380, 109),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found["B Partnership name"] == "Northwind Partners LP"
    assert "Avery" not in found["B Partnership name"]
    joined = "Northwind Partners LP Avery Quinn"
    assert identity_may_clear("part_i.name", joined, own_box=True) is False


def test_a_trailing_period_on_a_city_is_removed(tmp_path: Path) -> None:
    _draw(tmp_path / "city.pdf", [("B Partnership city", "Lakeside.")])
    document = DeterministicExtractor().extract(tmp_path / "city.pdf")
    assert strip_trailing_punctuation("Lakeside.") == "Lakeside"
    assert document.part_i.city.value == "Lakeside"
    assert document.part_i.city.confidence < REVIEW_THRESHOLD


def test_a_two_word_city_in_its_own_box_stays_under_0_80(tmp_path: Path) -> None:
    """A two-word city in its own box stays under 0.80.

    A value that is not from its own box fails the shape gate.
    """

    _draw(tmp_path / "city.pdf", [("B Partnership city", "Maple Hollow")])
    document = DeterministicExtractor().extract(tmp_path / "city.pdf")
    assert document.part_i.city.value == "Maple Hollow"
    assert document.part_i.city.confidence < REVIEW_THRESHOLD
    assert identity_may_clear("part_i.city", "Maple Hollow", own_box=False) is False


def test_an_exact_irs_entity_type_can_clear_and_a_paraphrase_cannot(tmp_path: Path) -> None:
    _draw(tmp_path / "exact.pdf", [("I1 Entity type", "Individual")])
    exact = DeterministicExtractor().extract(tmp_path / "exact.pdf")
    assert exact.part_ii.entity_type.value == "Individual"
    assert exact.part_ii.entity_type.confidence >= REVIEW_THRESHOLD
    _draw(tmp_path / "para.pdf", [("I1 Entity type", "Closely held firm")])
    paraphrase = DeterministicExtractor().extract(tmp_path / "para.pdf")
    assert paraphrase.part_ii.entity_type.confidence < REVIEW_THRESHOLD
    assert identity_may_clear("part_ii.entity_type", "Individual", own_box=False) is False

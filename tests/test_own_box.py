"""Own-box address values stay under 0.80 without a roster. A caption slot,
an unlinked city, and another column's value stay in review.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.extract.assemble import assemble
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.geometry import PlacedWord, pair_words
from k1lens.extract.labels import LayoutStats
from k1lens.extract.text import Observed

_STATS = LayoutStats(seen_lines=8, strong_anchors=8)


def _obs(
    raw: str,
    *,
    bbox: tuple[float, float, float, float] | None = (40.0, 200.0, 160.0, 210.0),
    caption_slot: bool = False,
    neighbor_line: bool = False,
) -> Observed:
    return Observed(
        raw=raw,
        page=1,
        bbox=bbox,
        extractor="deterministic",
        label_score=1.0,
        proximity=1.0,
        anchored=True,
        caption_slot=caption_slot,
        neighbor_line=neighbor_line,
    )


def test_a_city_without_a_state_or_zip_stays_under_review() -> None:
    """A place-shaped line is not enough when nothing nearby is a state or ZIP."""

    document = assemble(
        "K1-CITY",
        {"B Partnership city": [_obs("Amended Return")]},
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert document.part_i.city.value == "Amended Return"
    assert document.part_i.city.confidence < REVIEW_THRESHOLD


def test_a_city_stays_under_0_80_when_the_state_is_in_the_same_column() -> None:
    document = assemble(
        "K1-CITY",
        {
            "B Partnership city": [_obs("Portland", bbox=(40.0, 200.0, 120.0, 210.0))],
            "B Partnership state": [_obs("OR", bbox=(40.0, 214.0, 60.0, 224.0))],
        },
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert document.part_i.city.value == "Portland"
    assert document.part_i.city.confidence < REVIEW_THRESHOLD


def test_a_state_token_with_a_stuck_digit_still_links_the_city() -> None:
    """``MA 2`` is still the state line. The city keeps its own confidence."""

    document = assemble(
        "K1-CITY",
        {
            "F Partner city": [_obs("Boston", bbox=None)],
            "F Partner state": [_obs("MA 2", bbox=None)],
        },
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert document.part_ii.city.value == "Boston"
    assert document.part_ii.city.confidence < REVIEW_THRESHOLD
    assert document.part_ii.state.confidence < REVIEW_THRESHOLD


def test_a_state_in_the_other_column_does_not_corroborate_the_city() -> None:
    document = assemble(
        "K1-CITY",
        {
            "B Partnership city": [_obs("Portland", bbox=(40.0, 200.0, 120.0, 210.0))],
            "B Partnership state": [_obs("OR", bbox=(360.0, 214.0, 380.0, 224.0))],
        },
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert document.part_i.city.value == "Portland"
    assert document.part_i.city.confidence < REVIEW_THRESHOLD


def test_a_caption_string_in_the_value_slot_stays_under_review() -> None:
    document = assemble(
        "K1-CAP",
        {
            "B Partnership city": [_obs("F Partner name")],
            "B Partnership state": [_obs("OR", bbox=(40.0, 214.0, 60.0, 224.0))],
        },
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert document.part_i.city.confidence < REVIEW_THRESHOLD


def test_a_line_in_the_caption_slot_stays_under_review() -> None:
    document = assemble(
        "K1-SLOT",
        {"B Partnership name": [_obs("Northwind Partners LP", caption_slot=True)]},
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert document.part_i.name.value == "Northwind Partners LP"
    assert document.part_i.name.confidence < REVIEW_THRESHOLD


def test_a_marked_name_under_its_own_caption_stays_under_0_80() -> None:
    document = assemble(
        "K1-NAME",
        {"B Partnership name": [_obs("Northwind Partners LP")]},
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert document.part_i.name.confidence < REVIEW_THRESHOLD
    held = assemble(
        "K1-NAME",
        {"B Partnership name": [_obs("Northwind Partners LP", neighbor_line=True)]},
        extractor="deterministic",
        layout_stats=_STATS,
    )
    assert held.part_i.name.confidence < REVIEW_THRESHOLD


def test_each_caption_keeps_only_the_value_in_its_column() -> None:
    """The state under the other caption is not this field, even when the
    caption text runs toward that column.
    """

    words = (
        PlacedWord("B", 40, 100, 48, 109),
        PlacedWord("Partnership", 52, 100, 140, 109),
        PlacedWord("state", 144, 100, 250, 109),
        PlacedWord("F", 300, 100, 308, 109),
        PlacedWord("Partner", 312, 100, 360, 109),
        PlacedWord("state", 364, 100, 400, 109),
        PlacedWord("OR", 40, 114, 58, 123),
        PlacedWord("WA", 300, 114, 322, 123),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found["B Partnership state"] == "OR"
    assert found["F Partner state"] == "WA"

    missing_left = tuple(word for word in words if word.text != "OR")
    one_sided = {pair.label: pair.value for pair in pair_words(missing_left)}
    assert one_sided.get("B Partnership state") != "WA"
    assert one_sided["F Partner state"] == "WA"


def test_stacked_address_fields_on_a_page_stay_under_0_80(tmp_path: Path) -> None:
    """A value on the next line, in the caption's column, is that field's box."""

    path = tmp_path / "stacked.pdf"
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 10)
    rows = [
        ("A Partnership EIN", "00-0000108"),
        ("B Partnership name", "Northwind Partners LP"),
        ("B Partnership street", "10 Oak Avenue"),
        ("B Partnership city", "Portland"),
        ("B Partnership state", "OR"),
        ("B Partnership ZIP", "97201"),
        ("E Partner TIN", "000-00-0108"),
        ("I1 Entity type", "Partnership"),
        ("1 Ordinary business income", "15.00"),
        ("L Beginning capital", "100.00"),
        ("L Ending capital", "100.00"),
    ]
    y = 720.0
    for label, value in rows:
        canvas.drawString(48, y, label)
        y -= 12
        canvas.drawString(48, y, value)
        y -= 16
    canvas.save()
    document = DeterministicExtractor().extract(path)
    assert document.part_i.name.value == "Northwind Partners LP"
    assert document.part_i.name.confidence < REVIEW_THRESHOLD
    assert document.part_i.city.value == "Portland"
    assert document.part_i.city.confidence < REVIEW_THRESHOLD
    assert document.part_i.state.value == "OR"
    assert document.part_i.state.confidence < REVIEW_THRESHOLD
    assert document.part_i.street.value == "10 Oak Avenue"
    assert document.part_i.street.confidence < REVIEW_THRESHOLD

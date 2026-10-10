"""Colon-free label and amount pairing. No external documents."""

from decimal import Decimal
from pathlib import Path

import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.extract.assemble import assemble
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.geometry import (
    PlacedWord,
    pair_line,
    pair_words,
    pairs_from_cells,
    value_in_label_region,
)
from k1lens.extract.labels import LayoutStats
from k1lens.extract.ocr import OcrLine, OcrWord, _absorb
from k1lens.extract.text import Observed
from k1lens.generate.corpus import load_ground_truth
from k1lens.generate.geometry import GEOMETRY_PLAN, generate_dev_geometry


def test_colon_free_layouts_read_catalog_fields(tmp_path: Path) -> None:
    dest = tmp_path / "geometry"
    manifest = generate_dev_geometry(dest, seed=1065)
    assert manifest.count == len(GEOMETRY_PLAN)
    assert {item.variant for item in manifest.documents} == set(GEOMETRY_PLAN)
    for entry in manifest.documents:
        gold = load_ground_truth(dest / entry.ground_truth).document
        extracted = DeterministicExtractor().extract(dest / entry.pdf)
        assert extracted.layout_recognized is True
        income = extracted.part_iii.ordinary_business_income.value
        assert income == gold.part_iii.ordinary_business_income.value
        assert income is not None
        assert extracted.part_i.ein.value == gold.part_i.ein.value
        assert extracted.part_i.state.value == gold.part_i.state.value
        assert extracted.tax_year == gold.tax_year
        assert extracted.part_ii.capital.ending.value == gold.part_ii.capital.ending.value


def test_two_columns_do_not_swap_amounts(tmp_path: Path) -> None:
    dest = tmp_path / "columns"
    generate_dev_geometry(dest, seed=3)
    gold = load_ground_truth(dest / "K1-0005.json").document
    assert gold.variant == "two_column"
    extracted = DeterministicExtractor().extract(dest / "K1-0005.pdf")
    assert extracted.part_iii.interest_income.value == gold.part_iii.interest_income.value
    rental = gold.part_iii.net_rental_real_estate.value
    assert extracted.part_iii.net_rental_real_estate.value == rental
    assert extracted.part_iii.ordinary_business_income.value != rental


def test_grid_cells_resolve_without_word_positions() -> None:
    rows = [
        ["Box", "Description", "Amount"],
        ["1", "Ordinary business income", "100.00"],
        ["5", "Interest income", "20.00"],
        ["A", "Partnership EIN", "00-0000001"],
    ]
    found = {label: value for label, value, _score in pairs_from_cells(rows)}
    assert found["1 Ordinary business income"] == "100.00"
    assert found["5 Interest income"] == "20.00"
    assert found["A Partnership EIN"] == "00-0000001"


def test_ocr_word_boxes_pair_a_line_with_no_colon() -> None:
    line = OcrLine(
        text="1 Ordinary business income 15.00",
        confidence=90,
        words=(
            OcrWord("1", 90, 10, 10, 8, 10),
            OcrWord("Ordinary", 90, 24, 10, 50, 10),
            OcrWord("business", 90, 80, 10, 50, 10),
            OcrWord("income", 90, 136, 10, 40, 10),
            OcrWord("15.00", 95, 400, 10, 36, 10),
        ),
    )
    observed: dict[str, list[Observed]] = {}
    _absorb(observed, line, 1)
    assert observed["1 Ordinary business income"][0].raw == "15.00"
    assert observed["1 Ordinary business income"][0].ocr_confidence == pytest.approx(0.95)


def test_invalid_state_and_scientific_money_stay_under_review() -> None:
    stats = LayoutStats(seen_lines=8, strong_anchors=8)
    state = assemble(
        "K1-STATE",
        {
            "B Partnership state": [
                Observed(
                    raw="Ca",
                    page=1,
                    bbox=(0, 0, 10, 10),
                    extractor="ocr",
                    proximity=1.0,
                    ocr_confidence=0.9,
                )
            ],
            "F Partner state": [
                Observed(
                    raw="C4",
                    page=1,
                    bbox=(0, 0, 10, 10),
                    extractor="ocr",
                    proximity=1.0,
                    ocr_confidence=0.9,
                )
            ],
        },
        extractor="ocr",
        layout_stats=stats,
    )
    assert state.part_i.state.value == "CA"
    assert state.part_i.state.confidence < REVIEW_THRESHOLD
    assert state.part_ii.state.value == "C4"
    assert state.part_ii.state.confidence < REVIEW_THRESHOLD
    method = assemble(
        "K1-METHOD",
        {
            "L Capital method": [
                Observed(
                    raw="other",
                    page=1,
                    bbox=(0, 0, 10, 10),
                    extractor="ocr",
                    proximity=1.0,
                    ocr_confidence=0.9,
                )
            ],
        },
        extractor="ocr",
        layout_stats=stats,
    )
    assert method.part_ii.capital_method.value == "Other"

    money = assemble(
        "K1-MONEY",
        {
            "1 Ordinary business income": [
                Observed(
                    raw="1E3",
                    page=1,
                    bbox=(0, 0, 10, 10),
                    extractor="deterministic",
                    proximity=1.0,
                )
            ],
            "5 Interest income": [
                Observed(
                    raw="12.345,67",
                    page=1,
                    bbox=(0, 0, 10, 10),
                    extractor="deterministic",
                    proximity=1.0,
                )
            ],
        },
        extractor="deterministic",
        layout_stats=stats,
    )
    assert money.part_iii.ordinary_business_income.value is None
    assert money.part_iii.ordinary_business_income.confidence <= 0.25
    assert money.part_iii.interest_income.value is None
    assert money.part_iii.interest_income.confidence <= 0.25


def test_an_irs_caption_does_not_become_the_partnership_name(tmp_path: Path) -> None:
    """The form's own caption is the label. Leftover words are not the name."""

    path = tmp_path / "irs-face.pdf"
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 9)
    y = 720
    for row in (
        "A Partnership's employer identification number  00-0000001",
        "B Partnership's name, address, city, state, and ZIP code  SAMPLE Stoneorchard Partners LP",
        "C IRS center where partnership filed return  Ogden",
        "F Name, address, city, state, and ZIP code for partner entered in E  SAMPLE Drew Patel",
    ):
        canvas.drawString(40, y, row)
        y -= 16
    canvas.save()
    document = DeterministicExtractor().extract(path)
    assert document.part_i.name.value == "SAMPLE Stoneorchard Partners LP"
    assert document.part_i.irs_center.value == "Ogden"
    assert document.part_i.ein.value == "00-0000001"
    assert document.part_ii.name.value == "SAMPLE Drew Patel"
    assert "where partnership" not in str(document.part_i.irs_center.value).lower()
    assert "city" not in str(document.part_i.name.value).lower()
    assert not str(document.part_ii.name.value).startswith("E ")


def test_a_name_with_caption_words_stays_under_review(tmp_path: Path) -> None:
    path = tmp_path / "caption-name.pdf"
    _draw(path, [("B Partnership name", "SAMPLE Harborline Capital LP", 400)])
    document = DeterministicExtractor().extract(path)
    assert document.part_i.name.value == "SAMPLE Harborline Capital LP"
    assert document.part_i.name.confidence < 0.80


def test_recourse_amount_is_not_in_the_qualified_region() -> None:
    words = (
        PlacedWord("K", 40, 100, 48, 109),
        PlacedWord("Qualified", 52, 100, 110, 109),
        PlacedWord("nonrecourse", 114, 100, 190, 109),
        PlacedWord("100.00", 200, 100, 250, 109),
        PlacedWord("K", 320, 100, 328, 109),
        PlacedWord("Recourse", 332, 100, 390, 109),
        PlacedWord("300.00", 400, 100, 450, 109),
    )
    assert value_in_label_region("K Qualified nonrecourse", "100.00", words)
    assert not value_in_label_region("K Qualified nonrecourse", "300.00", words)
    assert value_in_label_region("K Recourse", "300.00", words)


def test_an_amount_on_the_next_line_stays_in_its_column() -> None:
    """The amount under a label belongs to that column, not the neighbor."""

    words = (
        PlacedWord("L", 40, 100, 48, 109),
        PlacedWord("Beginning", 52, 100, 110, 109),
        PlacedWord("capital", 114, 100, 160, 109),
        PlacedWord("L", 330, 100, 338, 109),
        PlacedWord("Ending", 342, 100, 390, 109),
        PlacedWord("capital", 394, 100, 440, 109),
        PlacedWord("122864.00", 40, 112, 100, 121),
        PlacedWord("281152.00", 330, 112, 400, 121),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found["L Beginning capital"] == "122864.00"
    assert found["L Ending capital"] == "281152.00"


def test_a_value_wider_than_its_label_keeps_the_trailing_words() -> None:
    """A name under its own caption stays one value, in that caption's column."""

    words = (
        PlacedWord("B", 40, 100, 48, 109),
        PlacedWord("Partnership", 52, 100, 110, 109),
        PlacedWord("name", 114, 100, 140, 109),
        PlacedWord("SAMPLE", 40, 112, 78, 121),
        PlacedWord("Stoneorchard", 82, 112, 150, 121),
        PlacedWord("Partners", 154, 112, 200, 121),
        PlacedWord("LP", 204, 112, 220, 121),
    )
    found = {pair.label: pair for pair in pair_words(words)}
    assert found["B Partnership name"].value == "SAMPLE Stoneorchard Partners LP"
    assert found["B Partnership name"].neighbor_line is False


def test_a_street_starting_with_a_box_number_stays_on_that_line() -> None:
    """``10`` is a box token. On the street's own line it is still the address."""

    words = (
        PlacedWord("B", 40, 100, 48, 109),
        PlacedWord("Partnership", 52, 100, 110, 109),
        PlacedWord("street", 114, 100, 150, 109),
        PlacedWord("10", 400, 100, 414, 109),
        PlacedWord("Oak", 418, 100, 440, 109),
        PlacedWord("Avenue", 444, 100, 490, 109),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found["B Partnership street"] == "10 Oak Avenue"


def test_two_coded_labels_keep_the_amount_under_each_column() -> None:
    """The right-hand code is the next label, not the left-hand value."""

    words = (
        PlacedWord("13", 40, 100, 52, 109),
        PlacedWord("Other", 56, 100, 90, 109),
        PlacedWord("deductions", 94, 100, 150, 109),
        PlacedWord("A", 154, 100, 162, 109),
        PlacedWord("13", 330, 100, 342, 109),
        PlacedWord("Other", 346, 100, 380, 109),
        PlacedWord("deductions", 384, 100, 440, 109),
        PlacedWord("B", 444, 100, 452, 109),
        PlacedWord("316.00", 40, 112, 80, 121),
        PlacedWord("2142.00", 330, 112, 380, 121),
    )
    found = {pair.label: pair.value for pair in pair_words(words)}
    assert found["13 Other deductions A"] == "316.00"
    assert found["13 Other deductions B"] == "2142.00"


def test_an_amount_far_below_the_label_is_not_paired() -> None:
    words = (
        PlacedWord("L", 40, 100, 48, 109),
        PlacedWord("Beginning", 52, 100, 110, 109),
        PlacedWord("capital", 114, 100, 160, 109),
        PlacedWord("122864.00", 40, 180, 100, 189),
    )
    assert pair_words(words) == []


def test_stacked_layouts_read_the_amount_under_the_label(tmp_path: Path) -> None:
    dest = tmp_path / "stacked"
    manifest = generate_dev_geometry(dest, seed=1065)
    stacked = [item for item in manifest.documents if item.variant == "stacked"]
    columns = [item for item in manifest.documents if item.variant == "stacked_columns"]
    assert len(stacked) == 2
    assert len(columns) == 2
    for entry in (*stacked, *columns):
        gold = load_ground_truth(dest / entry.ground_truth).document
        extracted = DeterministicExtractor().extract(dest / entry.pdf)
        assert extracted.layout_recognized is True
        assert extracted.part_i.name.value == gold.part_i.name.value
        assert extracted.part_ii.name.value == gold.part_ii.name.value
        assert extracted.part_i.street.value == gold.part_i.street.value
        assert extracted.part_ii.street.value == gold.part_ii.street.value
        assert extracted.part_ii.capital.beginning.value == gold.part_ii.capital.beginning.value
        assert extracted.part_ii.capital.ending.value == gold.part_ii.capital.ending.value
        assert (
            extracted.part_iii.ordinary_business_income.value
            == gold.part_iii.ordinary_business_income.value
        )


def test_a_coded_letter_is_not_a_part_i_box() -> None:
    """``C 824.00`` is a code and an amount, not ``C IRS center``."""

    coded = pair_line(
        (
            PlacedWord("C", 10, 10, 20, 20),
            PlacedWord("824.00", 40, 10, 90, 20),
        )
    )
    assert coded == []
    income = pair_line(
        (
            PlacedWord("1", 10, 10, 18, 20),
            PlacedWord("16098.00", 400, 10, 460, 20),
        )
    )
    assert [(item.label, item.value) for item in income] == [
        ("1 Ordinary business income", "16098.00")
    ]
    center = pair_line(
        (
            PlacedWord("C", 10, 30, 20, 40),
            PlacedWord("Ogden", 40, 30, 80, 40),
        )
    )
    assert [(item.label, item.value) for item in center] == [("C IRS center", "Ogden")]


def test_right_aligned_gap_scores_below_a_short_gap(tmp_path: Path) -> None:
    """A wide gap lowers proximity. A short gap does not. The weights are unchanged."""

    anchors = [
        ("TAX YEAR", "2024", 140),
        ("A Partnership EIN", "00-0000001", 200),
        ("B Partnership name", "SAMPLE One LP", 220),
        ("5 Interest income", "20.00", 180),
    ]
    tight = tmp_path / "tight.pdf"
    wide = tmp_path / "wide.pdf"
    _draw(tight, [*anchors, ("1 Ordinary business income", "100.00", 220)])
    _draw(wide, [*anchors, ("1 Ordinary business income", "100.00", 540)])
    tight_score = DeterministicExtractor().extract(tight).part_iii.ordinary_business_income
    wide_score = DeterministicExtractor().extract(wide).part_iii.ordinary_business_income
    assert tight_score.value == Decimal("100.00")
    assert wide_score.value == Decimal("100.00")
    assert wide_score.confidence < tight_score.confidence


def _draw(path: Path, rows: list[tuple[str, str, float]]) -> None:
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 10)
    y = 700
    for label, value, value_x in rows:
        canvas.drawString(40, y, label)
        canvas.drawString(value_x, y, value)
        y -= 16
    canvas.save()

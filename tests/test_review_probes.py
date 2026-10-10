"""Precision-first checks from the independent probes. Recorded HTTP only.

Each behavioral probe has an assertion here. Measurement scripts that only
print a distribution stay out of this file: abbreviation sourcing is
``test_labels.py``, the item L penalty is ``test_confidence.py``, and
development captions stay out of the matcher in ``test_dev_b.py``.
"""

import json
import random
import sqlite3
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas
from typer.testing import CliRunner

from k1lens.cli import app
from k1lens.domain.access import get_extracted
from k1lens.domain.fields import REVIEW_THRESHOLD, SCALAR_FIELDS
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import parse_decimal
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.hybrid import HybridExtractor
from k1lens.extract.llm import LLMExtractor
from k1lens.extract.ocr import OcrLine, _absorb
from k1lens.generate.build import Variant, build_document
from k1lens.generate.corpus import load_ground_truth
from k1lens.generate.dev_layouts import generate_dev
from k1lens.generate.geometry import generate_dev_geometry
from k1lens.generate.pdf import render_pdf
from k1lens.review.store import _GENESIS, ReviewStore, _chain_hash, verify_database


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "K1LENS_LLM_PROVIDER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("K1LENS_OPENAI_MODEL", "gpt-test")


def _reply(fields: dict[str, object]) -> httpx.Response:
    body = {"choices": [{"message": {"content": json.dumps({"fields": fields})}}]}
    return httpx.Response(200, json=body)


def test_malformed_thousands_are_rejected() -> None:
    accepted = {
        "12,345": Decimal("12345"),
        "(1,234.56)": Decimal("-1234.56"),
        "1,234.56-": Decimal("-1234.56"),
        "$1,234": Decimal("1234"),
        "12.50": Decimal("12.50"),
        "2.5": Decimal("2.5"),
    }
    for raw, expected in accepted.items():
        assert parse_decimal(raw) == expected
    for raw in ("0,50", "12,34", "1,2,3", "1,23,456.00", "-94,89", "12,500000"):
        with pytest.raises(ValueError, match="thousands"):
            parse_decimal(raw)
    for raw in ("12.345,67", "1.234,56", "1.234.567,89"):
        with pytest.raises(ValueError, match="US number"):
            parse_decimal(raw)
    # Exactly three digits after the dot is ambiguous (1.234 could be 1234).
    for raw in ("1.234", "12.345", "2.500"):
        with pytest.raises(ValueError, match="ambiguous"):
            parse_decimal(raw)
    for raw in ("1E3", "1e3"):
        with pytest.raises(ValueError, match="scientific"):
            parse_decimal(raw)
    for raw in ("12 345",):
        with pytest.raises(ValueError, match="multiple"):
            parse_decimal(raw)
    with pytest.raises(ValueError, match="not a number"):
        parse_decimal("1.234.567")


def test_ambiguous_commas_on_a_recognized_page_are_not_confident(tmp_path: Path) -> None:
    """A catalog page that prints 0,50 must not store 50 at 0.80 or above."""

    from k1lens.generate import pdf as gpdf

    document = build_document(random.Random(8), 1, Variant.CLEAN)
    pages = gpdf._pages(document)
    wrong = {"0,50": Decimal("50"), "12,34": Decimal("1234"), "1,2,3": Decimal("123")}
    for token, guessed in wrong.items():
        path = tmp_path / f"{token.replace(',', '_')}.pdf"
        canvas = Canvas(str(path), pagesize=letter, invariant=1)
        for lines in pages:
            rewritten = [
                f"5 Interest income: {token}" if line.startswith("5 Interest income:") else line
                for line in lines
            ]
            gpdf._draw_page(canvas, rewritten, rotate=False)
            canvas.showPage()
        canvas.save()
        got = DeterministicExtractor().extract(path)
        assert got.layout_recognized is True
        interest = got.part_iii.interest_income
        assert interest.value != guessed
        assert interest.confidence < REVIEW_THRESHOLD


def test_three_decimal_amounts_on_a_recognized_page_are_not_confident(tmp_path: Path) -> None:
    """``1.234`` can mean 1.234 or 1234. Neither reading clears 0.80."""

    from k1lens.generate import pdf as gpdf

    document = build_document(random.Random(8), 1, Variant.CLEAN)
    pages = gpdf._pages(document)
    for token in ("1.234", "12.345", "2.500"):
        path = tmp_path / f"{token.replace('.', '_')}.pdf"
        canvas = Canvas(str(path), pagesize=letter, invariant=1)
        for lines in pages:
            rewritten = [
                f"5 Interest income: {token}" if line.startswith("5 Interest income:") else line
                for line in lines
            ]
            gpdf._draw_page(canvas, rewritten, rotate=False)
            canvas.showPage()
        canvas.save()
        got = DeterministicExtractor().extract(path)
        assert got.layout_recognized is True
        interest = got.part_iii.interest_income
        assert interest.confidence < REVIEW_THRESHOLD
        assert interest.value is None


def test_irs_captions_are_not_the_name_or_the_center(tmp_path: Path) -> None:
    """Full public captions, including the trailing instruction, are not the value."""

    path = tmp_path / "irs-captions.pdf"
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 9)
    y = 720
    rows = (
        "A Partnership's employer identification number  00-0000001",
        "B Partnership's name, address, city, state, and ZIP code  SAMPLE Stoneorchard Partners LP",
        "C IRS center where partnership filed return  Ogden",
        (
            "E Partner's SSN or TIN. Do not use TIN of a disregarded entity. "
            "See instructions.  000-00-0001"
        ),
        (
            "F Name, address, city, state, and ZIP code for partner entered in E. "
            "See instructions.  SAMPLE Drew Patel"
        ),
        "I1 What type of entity is this partner?  Individual",
    )
    for row in rows:
        canvas.drawString(40, y, row)
        y -= 16
    canvas.save()
    document = DeterministicExtractor().extract(path)
    assert document.part_i.ein.value == "00-0000001"
    assert document.part_i.name.value == "SAMPLE Stoneorchard Partners LP"
    assert document.part_i.irs_center.value == "Ogden"
    assert document.part_ii.tin.value == "000-00-0001"
    assert document.part_ii.name.value == "SAMPLE Drew Patel"
    assert document.part_ii.entity_type.value == "Individual"


_LAB = {spec.path: spec.pdf_label for spec in SCALAR_FIELDS}
_FREE_TEXT_BASE = (
    ("part_i.ein", "00-0000001"),
    ("part_i.street", "100 Main St"),
    ("part_i.state", "CA"),
    ("part_i.zip_code", "94105"),
    ("part_ii.tin", "000-00-0001"),
    ("part_ii.street", "200 Oak Ave"),
    ("part_ii.state", "NY"),
    ("part_ii.zip_code", "10001"),
)
_Line = str | tuple[tuple[float, str], ...]


def _draw_probe(lines: list[_Line], dest: Path) -> ScheduleK1:
    canvas = Canvas(str(dest), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 9)
    y = 740
    for item in lines:
        if isinstance(item, tuple):
            for x, text in item:
                canvas.drawString(x, y, text)
        else:
            canvas.drawString(40, y, item)
        y -= 14
    canvas.save()
    return DeterministicExtractor().extract(dest)


def _base_lines() -> list[_Line]:
    return [f"{_LAB[path]}  {value}" for path, value in _FREE_TEXT_BASE]


def _assert_not_confident_wrong(document: ScheduleK1, checks: list[tuple[str, str]]) -> None:
    """Gold ``None`` must be missing. Any other miss stays under 0.80."""

    for path, gold in checks:
        got = get_extracted(document, path)
        if gold == "None":
            assert got.value is None, path
            continue
        if got.value is not None and str(got.value) != gold:
            assert got.confidence < REVIEW_THRESHOLD, (path, got.value, got.confidence)


def test_leader_dots_are_not_part_of_the_value(tmp_path: Path) -> None:
    lines = [
        *_base_lines(),
        f"{_LAB['part_i.name']} ........................ SAMPLE Alder Fund LP",
        f"{_LAB['part_i.city']} ............................ Denver",
        f"{_LAB['part_ii.name']} ........................ SAMPLE Drew Patel",
        f"{_LAB['part_ii.city']} ............................ Austin",
        f"{_LAB['part_ii.entity_type']} ...................... Individual",
        f"{_LAB['part_ii.capital_method']} ................... Tax basis",
    ]
    document = _draw_probe(lines, tmp_path / "dots.pdf")
    _assert_not_confident_wrong(
        document,
        [
            ("part_i.name", "SAMPLE Alder Fund LP"),
            ("part_i.city", "Denver"),
            ("part_ii.name", "SAMPLE Drew Patel"),
            ("part_ii.city", "Austin"),
            ("part_ii.entity_type", "Individual"),
            ("part_ii.capital_method", "Tax basis"),
        ],
    )
    assert document.part_i.name.value == "SAMPLE Alder Fund LP"
    assert document.part_i.city.value == "Denver"
    assert document.part_ii.entity_type.value == "Individual"
    assert document.part_ii.capital_method.value == "Tax basis"


def test_unknown_caption_tails_stay_under_review(tmp_path: Path) -> None:
    lines = [
        *_base_lines(),
        f"{_LAB['part_i.city']} or locality  Denver",
        f"{_LAB['part_ii.entity_type']} per records  Individual",
        f"{_LAB['part_ii.capital_method']} used  Tax basis",
        f"{_LAB['part_ii.name']} as shown  SAMPLE Drew Patel",
    ]
    document = _draw_probe(lines, tmp_path / "tail.pdf")
    _assert_not_confident_wrong(
        document,
        [
            ("part_i.city", "Denver"),
            ("part_ii.entity_type", "Individual"),
            ("part_ii.capital_method", "Tax basis"),
            ("part_ii.name", "SAMPLE Drew Patel"),
        ],
    )


def test_a_heading_beside_a_heading_is_not_the_value(tmp_path: Path) -> None:
    lines: list[_Line] = [
        *_base_lines(),
        ((40, _LAB["part_ii.capital_method"]), (320, "Part III Current Year Items")),
        ((40, "X Tax basis"),),
        ((40, _LAB["part_ii.entity_type"]), (320, "Summary of allocations")),
    ]
    document = _draw_probe(lines, tmp_path / "heads.pdf")
    _assert_not_confident_wrong(
        document,
        [("part_ii.capital_method", "Tax basis"), ("part_ii.entity_type", "None")],
    )


def test_a_next_line_stray_is_not_the_value(tmp_path: Path) -> None:
    lines: list[_Line] = [
        *_base_lines(),
        ((40, _LAB["part_iii.interest_income"]),),
        ((44, "12"),),
        ((40, _LAB["part_ii.name"]),),
        ((44, "See statement"),),
        ((40, _LAB["part_i.city"]),),
        ((44, "Page 2"),),
    ]
    document = _draw_probe(lines, tmp_path / "stray.pdf")
    _assert_not_confident_wrong(
        document,
        [
            ("part_iii.interest_income", "None"),
            ("part_ii.name", "None"),
            ("part_i.city", "None"),
        ],
    )


def test_next_line_amounts_stay_in_their_columns(tmp_path: Path) -> None:
    lines: list[_Line] = [
        *_base_lines(),
        (
            (40, _LAB["part_iii.interest_income"]),
            (320, _LAB["part_iii.ordinary_dividends"]),
        ),
        ((330, "1,111.00"), (60, "2,222.00")),
    ]
    document = _draw_probe(lines, tmp_path / "twocol.pdf")
    _assert_not_confident_wrong(
        document,
        [
            ("part_iii.interest_income", "2222.00"),
            ("part_iii.ordinary_dividends", "1111.00"),
        ],
    )


def test_a_value_two_rows_below_is_not_confident_wrong(tmp_path: Path) -> None:
    lines: list[_Line] = [
        *_base_lines(),
        ((40, _LAB["part_iii.royalties"]),),
        ((40, ""),),
        ((44, "3,333.00"),),
    ]
    document = _draw_probe(lines, tmp_path / "gap.pdf")
    _assert_not_confident_wrong(document, [("part_iii.royalties", "3333.00")])


def _no_confident_wrong(document: ScheduleK1, checks: list[tuple[str, str | None]]) -> None:
    """The probe flag: a stored value that differs from gold at 0.80 or above."""

    for path, gold in checks:
        got = get_extracted(document, path)
        confident_wrong = (
            got.value is not None
            and str(got.value) != str(gold)
            and got.confidence >= REVIEW_THRESHOLD
        )
        assert not confident_wrong, (path, gold, got.value, got.confidence)


def test_abbreviation_periods_stay_in_the_name(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']}  Alder Growth Fund, L.P.",
            f"{_LAB['part_ii.name']}  Jordan Smith Jr.",
            f"{_LAB['part_i.city']}  Denver",
        ],
        tmp_path / "periods.pdf",
    )
    checks: list[tuple[str, str | None]] = [
        ("part_i.name", "Alder Growth Fund, L.P."),
        ("part_ii.name", "Jordan Smith Jr."),
        ("part_i.city", "Denver"),
    ]
    _no_confident_wrong(document, checks)
    assert document.part_i.name.value == "Alder Growth Fund, L.P."
    assert document.part_ii.name.value == "Jordan Smith Jr."


def test_underscore_hyphen_and_equals_leaders_are_not_the_value(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']} ________________ Alder Growth Fund LP",
            f"{_LAB['part_ii.name']} ---------------- Jordan Smith",
            f"{_LAB['part_i.city']} ================ Denver",
            f"{_LAB['part_ii.entity_type']} ___ Individual",
        ],
        tmp_path / "leaders.pdf",
    )
    checks: list[tuple[str, str | None]] = [
        ("part_i.name", "Alder Growth Fund LP"),
        ("part_ii.name", "Jordan Smith"),
        ("part_i.city", "Denver"),
        ("part_ii.entity_type", "Individual"),
    ]
    _no_confident_wrong(document, checks)
    assert document.part_i.name.value == "Alder Growth Fund LP"
    assert document.part_i.city.value == "Denver"
    assert document.part_ii.entity_type.value == "Individual"


def test_a_cross_reference_in_the_value_slot_is_not_stored(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']}  See addendum",
            f"{_LAB['part_ii.name']}  See Schedule K-3",
            f"{_LAB['part_i.city']}  Refer to footnote 9",
            f"{_LAB['part_ii.city']}  Refer to page two",
        ],
        tmp_path / "xref.pdf",
    )
    checks: list[tuple[str, str | None]] = [
        ("part_i.name", None),
        ("part_ii.name", None),
        ("part_i.city", None),
        ("part_ii.city", None),
    ]
    _no_confident_wrong(document, checks)
    assert document.part_i.name.value is None
    assert document.part_ii.name.value is None
    assert document.part_i.city.value is None
    assert document.part_ii.city.value is None


def test_a_cross_reference_that_looks_like_a_name_is_not_stored(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']}  See cover letter",
            f"{_LAB['part_ii.name']}  See enclosed letter",
        ],
        tmp_path / "cover.pdf",
    )
    checks: list[tuple[str, str | None]] = [
        ("part_i.name", None),
        ("part_ii.name", None),
    ]
    _no_confident_wrong(document, checks)
    assert document.part_i.name.value is None
    assert document.part_ii.name.value is None


def test_parenthesized_instruction_references_are_not_the_value(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            (
                "E Partner's SSN or TIN (Do not use TIN of a disregarded entity. "
                "See instructions.)  000-00-0002"
            ),
            "I1 What type of entity is this partner? (see instructions)  Partnership",
            (
                "F Name, address, city, state, and ZIP code for partner entered in E. "
                "See instructions.  Jordan Smith"
            ),
        ],
        tmp_path / "parens.pdf",
    )
    checks: list[tuple[str, str | None]] = [
        ("part_ii.tin", "000-00-0002"),
        ("part_ii.entity_type", "Partnership"),
        ("part_ii.name", "Jordan Smith"),
    ]
    _no_confident_wrong(document, checks)
    assert document.part_ii.entity_type.value == "Partnership"
    assert document.part_ii.name.value == "Jordan Smith"


def test_an_ocr_city_needs_the_same_word_confidence_as_a_name() -> None:
    from k1lens.extract.confidence import position_free_text_ok

    assert position_free_text_ok("part_i.city", "Denver", ocr_confidence=0.85) is False
    assert position_free_text_ok("part_i.city", "Denver", ocr_confidence=0.90) is True
    assert position_free_text_ok("part_ii.name", "Jordan Smith", ocr_confidence=0.89) is False


def test_a_colon_line_that_fails_its_shape_stays_under_review(tmp_path: Path) -> None:
    """A colon line uses the same shape gate as a position pair."""

    document = _draw_probe(
        [
            *[f"{_LAB[path]}: {value}" for path, value in _FREE_TEXT_BASE],
            f"{_LAB['part_i.name']}: Capital Income Partners LP",
            f"{_LAB['part_i.city']}: Lake City",
            f"{_LAB['part_ii.entity_type']}: C corp",
            f"{_LAB['part_ii.capital_method']}: Income tax basis",
            f"{_LAB['part_i.irs_center']}: E-file",
        ],
        tmp_path / "colon-shape.pdf",
    )
    checks = [
        ("part_i.name", "Capital Income Partners LP"),
        ("part_i.city", "Lake City"),
        ("part_ii.entity_type", "C corp"),
        ("part_ii.capital_method", "Income tax basis"),
        ("part_i.irs_center", "E-file"),
    ]
    _no_confident_wrong(document, checks)
    for path, gold in checks:
        got = get_extracted(document, path)
        assert got.value == gold
    for path in ("part_ii.entity_type", "part_ii.capital_method", "part_i.irs_center"):
        assert get_extracted(document, path).confidence < REVIEW_THRESHOLD


def test_note_phrases_are_not_stored(tmp_path: Path) -> None:
    notes = [
        ("part_i.name", "Not applicable"),
        ("part_ii.name", "Unknown"),
        ("part_i.city", "Not provided"),
        ("part_i.irs_center", "Not applicable"),
        ("part_ii.capital_method", "Not provided"),
        ("part_ii.entity_type", "Unknown"),
    ]
    for title, sep in (("colon", ": "), ("position", "  ")):
        document = _draw_probe(
            [
                *[f"{_LAB[path]}{sep}{value}" for path, value in _FREE_TEXT_BASE],
                *[f"{_LAB[path]}{sep}{value}" for path, value in notes],
            ],
            tmp_path / f"notes-{title}.pdf",
        )
        checks = [(path, None) for path, _value in notes]
        _no_confident_wrong(document, checks)
        for path, _value in notes:
            assert get_extracted(document, path).value is None


def test_a_name_that_only_shares_letters_with_a_note_is_kept(tmp_path: Path) -> None:
    first = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']}  Perry Ridge Partners LP",
            f"{_LAB['part_ii.name']}  Per Holmberg",
            f"{_LAB['part_i.city']}  Perrysburg",
            f"{_LAB['part_ii.city']}  Seeley Lake",
        ],
        tmp_path / "per.pdf",
    )
    first_checks = [
        ("part_i.name", "Perry Ridge Partners LP"),
        ("part_ii.name", "Per Holmberg"),
        ("part_i.city", "Perrysburg"),
        ("part_ii.city", "Seeley Lake"),
    ]
    _no_confident_wrong(first, first_checks)
    for path, gold in first_checks:
        assert get_extracted(first, path).value == gold
    second = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']}  Attached Dwelling Partners LLC",
            f"{_LAB['part_ii.name']}  Per-Anders Wikstrom",
        ],
        tmp_path / "attached.pdf",
    )
    second_checks = [
        ("part_i.name", "Attached Dwelling Partners LLC"),
        ("part_ii.name", "Per-Anders Wikstrom"),
    ]
    _no_confident_wrong(second, second_checks)
    for path, gold in second_checks:
        assert get_extracted(second, path).value == gold


def test_repeated_leader_marks_are_not_part_of_the_value(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']} ~~~~~~~~~~~~~~ Alder Growth Fund LP",
            f"{_LAB['part_ii.name']} ************ Jordan Smith",
            f"{_LAB['part_i.city']} ::::::::::: Denver",
            f"{_LAB['part_ii.city']} ..........Boulder",
        ],
        tmp_path / "marks.pdf",
    )
    checks = [
        ("part_i.name", "Alder Growth Fund LP"),
        ("part_ii.name", "Jordan Smith"),
        ("part_i.city", "Denver"),
        ("part_ii.city", "Boulder"),
    ]
    _no_confident_wrong(document, checks)
    for path, gold in checks:
        assert get_extracted(document, path).value == gold


def test_a_name_is_not_taken_from_another_column(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            (
                (
                    40,
                    "F Name, address, city, state, and ZIP code for partner entered in E.",
                ),
                (380, "17 Prior-period reconciliation"),
            ),
            ((52, "Jordan Smith"), (380, "Memo items")),
        ],
        tmp_path / "columns.pdf",
    )
    _no_confident_wrong(document, [("part_ii.name", "Jordan Smith")])
    assert document.part_ii.name.value == "Jordan Smith"
    assert "reconciliation" not in str(document.part_ii.name.value)
    assert "Memo" not in str(document.part_ii.name.value)


def test_a_caption_like_next_line_is_not_the_name(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            _LAB["part_ii.name"],
            "Attention line",
            "Jordan Smith",
        ],
        tmp_path / "attention.pdf",
    )
    _no_confident_wrong(document, [("part_ii.name", "Jordan Smith")])
    assert document.part_ii.name.value == "Jordan Smith"


def test_an_ocr_colon_line_keeps_an_abbreviation_period(tmp_path: Path) -> None:
    import pypdfium2 as pdfium

    source = tmp_path / "text.pdf"
    canvas = Canvas(str(source), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 11)
    y = 740
    rows = [f"{_LAB[path]}: {value}" for path, value in _FREE_TEXT_BASE] + [
        f"{_LAB['part_i.name']}: Alder Growth Fund, L.P.",
        f"{_LAB['part_ii.name']}: Jordan Smith Jr.",
        f"{_LAB['part_i.city']}: Denver",
    ]
    for row in rows:
        canvas.drawString(50, y, row)
        y -= 18
    canvas.save()
    image = pdfium.PdfDocument(str(source))[0].render(scale=300 / 72).to_pil().convert("L")
    dest = tmp_path / "scan.pdf"
    image.save(str(dest), "PDF", resolution=300.0)
    document = DeterministicExtractor().extract(dest)
    checks = [
        ("part_i.name", "Alder Growth Fund, L.P."),
        ("part_ii.name", "Jordan Smith Jr."),
        ("part_i.city", "Denver"),
    ]
    _no_confident_wrong(document, checks)
    assert document.part_i.name.value == "Alder Growth Fund, L.P."
    assert document.part_ii.name.value == "Jordan Smith Jr."


def test_two_column_recourse_is_not_qualified_nonrecourse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    dest = tmp_path / "geometry"
    manifest = generate_dev_geometry(dest, seed=1065)
    entry = next(item for item in manifest.documents if item.variant == "two_column")
    pdf = dest / entry.pdf
    gold = load_ground_truth(dest / entry.ground_truth).document
    qualified = get_extracted(gold, "part_ii.liability_qualified_nonrecourse")
    recourse = get_extracted(gold, "part_ii.liability_recourse")
    assert qualified.value is not None and recourse.value is not None

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply(
            {"K Qualified nonrecourse": {"value": str(recourse.value), "confidence": 1.0}}
        )

    document = HybridExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        pdf
    )
    kept = document.part_ii.liability_qualified_nonrecourse
    assert not (kept.value == recourse.value and kept.confidence >= REVIEW_THRESHOLD)
    assert kept.value == qualified.value


def test_swapped_on_page_amounts_stay_under_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    path = tmp_path / "swap.pdf"
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 10)
    canvas.drawString(40, 700, "1 Ordinary business income")
    canvas.drawString(320, 700, "100.00")
    canvas.drawString(40, 680, "5 Interest income")
    canvas.drawString(320, 680, "200.00")
    canvas.save()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply(
            {
                "1 Ordinary business income": {"value": "200.00", "confidence": 1.0},
                "5 Interest income": {"value": "100.00", "confidence": 1.0},
            }
        )

    document = HybridExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        path
    )
    income = document.part_iii.ordinary_business_income
    interest = document.part_iii.interest_income
    assert not (income.value == Decimal("200.00") and income.confidence >= REVIEW_THRESHOLD)
    assert not (interest.value == Decimal("100.00") and interest.confidence >= REVIEW_THRESHOLD)


def test_a_blank_line_is_not_filled_with_zero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    path = tmp_path / "blank.pdf"
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 10)
    canvas.drawString(40, 700, "A Partnership EIN  00-0000001")
    canvas.drawString(40, 680, "B Partnership name  SAMPLE One LP")
    canvas.drawString(40, 660, "5 Interest income")
    canvas.save()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply({"5 Interest income": {"value": "0.00", "confidence": 1.0}})

    document = HybridExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        path
    )
    assert document.part_iii.interest_income.value is None


def test_a_model_value_that_fails_format_is_discarded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    path = tmp_path / "format.pdf"
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 10)
    canvas.drawString(40, 700, "B Partnership state  CA")
    canvas.drawString(40, 680, "F Partner name  SAMPLE Drew Patel")
    canvas.save()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply(
            {
                "B Partnership state": {"value": "ZZ", "confidence": 1.0},
                "F Partner name": {"value": "Gérporatién", "confidence": 1.0},
            }
        )

    document = HybridExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        path
    )
    assert document.part_i.state.value != "ZZ"
    assert document.part_ii.name.value != "Gérporatién"


def test_llm_swap_of_printed_amounts_stays_under_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    document = build_document(random.Random(8), 1, Variant.CLEAN)
    pdf = tmp_path / "clean.pdf"
    render_pdf(document, pdf)
    interest = document.part_iii.interest_income.value
    dividends = document.part_iii.ordinary_dividends.value
    assert interest is not None and dividends is not None
    assert interest != dividends

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply(
            {
                "5 Interest income": {"value": str(dividends), "confidence": 1.0},
                "6a Ordinary dividends": {"value": str(interest), "confidence": 1.0},
            }
        )

    got = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(pdf)
    assert got.part_iii.interest_income.confidence < REVIEW_THRESHOLD
    assert got.part_iii.ordinary_dividends.confidence < REVIEW_THRESHOLD


def test_llm_two_column_swap_stays_under_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    dest = tmp_path / "geometry"
    manifest = generate_dev_geometry(dest, seed=1065)
    entry = next(item for item in manifest.documents if item.variant == "two_column")
    pdf = dest / entry.pdf
    gold = load_ground_truth(dest / entry.ground_truth).document
    qualified = get_extracted(gold, "part_ii.liability_qualified_nonrecourse")
    recourse = get_extracted(gold, "part_ii.liability_recourse")
    assert qualified.value is not None and recourse.value is not None
    assert qualified.value != recourse.value

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply(
            {
                "K Qualified nonrecourse": {"value": str(recourse.value), "confidence": 1.0},
                "K Recourse": {"value": str(qualified.value), "confidence": 1.0},
            }
        )

    got = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(pdf)
    left = got.part_ii.liability_qualified_nonrecourse
    right = got.part_ii.liability_recourse
    assert not (left.value == recourse.value and left.confidence >= REVIEW_THRESHOLD)
    assert not (right.value == qualified.value and right.confidence >= REVIEW_THRESHOLD)


def test_hybrid_swap_on_a_statement_page_stays_under_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    dest = tmp_path / "dev"
    manifest = generate_dev(dest, seed=1065)
    entry = next(item for item in manifest.documents if item.variant == "dev_statement")
    pdf = dest / entry.pdf
    gold = load_ground_truth(dest / entry.ground_truth).document
    interest = gold.part_iii.interest_income.value
    dividends = gold.part_iii.ordinary_dividends.value
    assert interest is not None and dividends is not None

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply(
            {
                "5 Interest income": {"value": str(dividends), "confidence": 1.0},
                "6a Ordinary dividends": {"value": str(interest), "confidence": 1.0},
            }
        )

    got = HybridExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(pdf)
    assert got.layout_recognized is False
    assert got.part_iii.interest_income.confidence < REVIEW_THRESHOLD
    assert got.part_iii.ordinary_dividends.confidence < REVIEW_THRESHOLD


def test_reingest_of_an_approved_record_returns_it_to_pending(tmp_path: Path) -> None:
    from k1lens.roster import roster_from_documents

    document = build_document(random.Random(8), 1, Variant.CLEAN)
    store = ReviewStore(tmp_path / "review.db", roster=roster_from_documents([document]))
    pdf = b"%PDF-1.4 synthetic"
    store.upsert(document, pdf, [])
    store.approve(document.document_id, "Ada Reviewer")
    original = get_extracted(document, "part_iii.ordinary_business_income").value
    assert original is not None
    payload = document.model_dump(mode="json")
    payload["part_iii"]["ordinary_business_income"]["value"] = "999999.00"
    changed = ScheduleK1.model_validate(payload)
    store.upsert(changed, pdf, [])
    stored = store.get(document.document_id)
    assert stored is not None
    assert stored.status == "pending"
    assert stored.approved_by is None
    row = next(
        entry
        for entry in store.audit(document.document_id)
        if entry.field_path == "part_iii.ordinary_business_income"
    )
    assert row.old_value is not None and str(original) in row.old_value.replace(",", "")
    assert row.new_value == "999999.00"


def test_a_rewritten_audit_file_is_the_disclosed_limit(tmp_path: Path) -> None:
    """Triggers block an in-place edit. A rewritten file can rebuild the chain."""

    db = tmp_path / "review.db"
    store = ReviewStore(db)
    document = build_document(random.Random(8), 1, Variant.CLEAN)
    store.upsert(document, b"%PDF-1.4 synthetic", [])
    store.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    assert verify_database(db) == []
    conn = sqlite3.connect(db)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE audit_log SET actor = 'Mallory' WHERE id = 2")
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.execute("UPDATE audit_log SET actor = 'Mallory' WHERE id = 2")
    conn.commit()
    forged = verify_database(db)
    assert "row 2 row_hash does not match its contents" in forged
    rows = conn.execute(
        "SELECT id, document_id, field_path, action, old_value, new_value, actor, created_at "
        "FROM audit_log ORDER BY id"
    ).fetchall()
    previous = _GENESIS
    for row in rows:
        digest = _chain_hash(
            previous,
            document_id=row[1],
            field_path=row[2],
            action=row[3],
            old_value=row[4],
            new_value=row[5],
            actor=row[6],
            created_at=row[7],
        )
        conn.execute(
            "UPDATE audit_log SET prev_hash = ?, row_hash = ? WHERE id = ?",
            (previous, digest, row[0]),
        )
        previous = digest
    conn.execute(
        "UPDATE audit_head SET row_count = ?, tip_hash = ? WHERE id = 1",
        (len(rows), previous),
    )
    conn.executescript(
        """
        CREATE TRIGGER audit_log_no_update
        BEFORE UPDATE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only');
        END;
        CREATE TRIGGER audit_log_no_delete
        BEFORE DELETE ON audit_log
        BEGIN
            SELECT RAISE(ABORT, 'audit_log is append-only');
        END;
        """
    )
    conn.commit()
    conn.close()
    assert verify_database(db) == []


_SHAPE_ROWS = (
    ("part_i.name", "Fund"),
    ("part_ii.name", "Partner name as shown"),
    ("part_i.city", "Denver Colorado USA Metro"),
    ("part_ii.entity_type", "Banana"),
    ("part_ii.capital_method", "Whatever basis maybe"),
    ("part_i.irs_center", "Springfield"),
    ("part_ii.name", "Estate of Jordan Smith"),
    ("part_ii.entity_type", "C corp"),
    ("part_ii.capital_method", "Income tax basis"),
)


@pytest.mark.parametrize("separator", ["  ", ": "])
def test_colon_line_values_that_fail_the_shape_check_stay_in_review(
    tmp_path: Path, separator: str
) -> None:
    batches: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for path, value in _SHAPE_ROWS:
        if path in current:
            batches.append(current)
            current = {}
        current[path] = value
    batches.append(current)
    for index, rows in enumerate(batches):
        document = _draw_probe(
            [
                *_base_lines(),
                *[f"{_LAB[path]}{separator}{value}" for path, value in rows.items()],
            ],
            tmp_path / f"shape-{index}-{separator.strip() or 'gap'}.pdf",
        )
        assert document.layout_recognized is True
        for path, value in rows.items():
            got = get_extracted(document, path)
            # A repeated caption can be read as more of the label. The
            # remainder is still this value, and it stays in review.
            if got.value is not None:
                assert str(got.value) == value or str(got.value) in value
            assert got.confidence < REVIEW_THRESHOLD


@pytest.mark.parametrize("separator", ["  ", ": "])
def test_note_words_in_the_value_slot_are_not_stored(tmp_path: Path, separator: str) -> None:
    notes = (
        ("part_i.name", "Not applicable"),
        ("part_ii.name", "Not provided"),
        ("part_i.city", "Not applicable"),
        ("part_ii.city", "N/A"),
        ("part_i.irs_center", "None"),
    )
    document = _draw_probe(
        [
            *_base_lines(),
            *[f"{_LAB[path]}{separator}{value}" for path, value in notes],
        ],
        tmp_path / f"notes-{separator.strip() or 'gap'}.pdf",
    )
    checks = [(path, None) for path, _value in notes]
    _no_confident_wrong(document, checks)
    for path, _value in notes:
        assert get_extracted(document, path).value is None


def test_tilde_asterisk_and_colon_leaders_are_not_the_value(tmp_path: Path) -> None:
    document = _draw_probe(
        [
            *_base_lines(),
            f"{_LAB['part_i.name']} ~~~~~~~~~~~~ Alder Growth Fund LP",
            f"{_LAB['part_ii.name']} ************ Jordan Smith",
            f"{_LAB['part_i.city']} :::::::::::: Denver",
        ],
        tmp_path / "leaders.pdf",
    )
    checks = [
        ("part_i.name", "Alder Growth Fund LP"),
        ("part_ii.name", "Jordan Smith"),
        ("part_i.city", "Denver"),
    ]
    _no_confident_wrong(document, checks)
    assert document.part_i.name.value == "Alder Growth Fund LP"
    assert document.part_ii.name.value == "Jordan Smith"
    assert document.part_i.city.value == "Denver"


def test_ocr_colon_line_keeps_a_trailing_abbreviation_period() -> None:
    observed: dict[str, list] = {}
    _absorb(
        observed,
        OcrLine(f"{_LAB['part_i.name']}: Alder Growth Fund, L.P.", 0.95),
        1,
    )
    _absorb(
        observed,
        OcrLine(f"{_LAB['part_ii.name']}: Jordan Smith Jr.", 0.95),
        1,
    )
    assert observed[_LAB["part_i.name"]][0].raw == "Alder Growth Fund, L.P."
    assert observed[_LAB["part_ii.name"]][0].raw == "Jordan Smith Jr."


def test_partner_name_is_not_taken_from_a_neighbor(tmp_path: Path) -> None:
    pages: list[list] = [
        [
            *_base_lines(),
            (
                (40, _LAB["part_ii.name"]),
                (200, "Summit Ridge Holdings"),
                (360, "100.00"),
            ),
        ],
        [*_base_lines(), _LAB["part_ii.name"], ((44, "Beneficial Owner Copy"),)],
        [*_base_lines(), _LAB["part_ii.name"], ((44, "Prepared By Avery Chen"),)],
    ]
    for index, lines in enumerate(pages):
        document = _draw_probe(lines, tmp_path / f"neighbor-{index}.pdf")
        _no_confident_wrong(document, [("part_ii.name", None)])


def test_verify_catches_a_rewritten_row_with_triggers_intact(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    store = ReviewStore(db)
    document = build_document(random.Random(8), 1, Variant.CLEAN)
    store.upsert(document, b"%PDF-1.4", [])
    store.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    store.correct(document.document_id, "part_i.city", "Memphis", "Ada Reviewer")
    triggers = """
    CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
    CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
    BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
    """
    conn = sqlite3.connect(db)
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.execute("UPDATE audit_log SET new_value = 'forged' WHERE id = 2")
    conn.executescript(triggers)
    conn.commit()
    conn.close()
    assert verify_database(db) == ["row 2 row_hash does not match its contents"]

    conn = sqlite3.connect(db)
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.execute("UPDATE audit_log SET prev_hash = 'not-the-previous' WHERE id = 2")
    conn.executescript(triggers)
    conn.commit()
    conn.close()
    problems = verify_database(db)
    assert "row 2 prev_hash does not match the previous row" in problems

    bare = tmp_path / "bare.db"
    bare_store = ReviewStore(bare)
    bare_store.upsert(document, b"%PDF-1.4", [])
    conn = sqlite3.connect(bare)
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.commit()
    conn.close()
    missing = verify_database(bare)
    assert "missing trigger audit_log_no_update" in missing
    assert "missing trigger audit_log_no_delete" in missing


def test_verify_detects_a_truncated_tail(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    store = ReviewStore(db)
    document = build_document(random.Random(8), 1, Variant.CLEAN)
    store.upsert(document, b"%PDF-1.4", [])
    store.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    store.correct(document.document_id, "part_i.city", "Memphis", "Ada Reviewer")
    conn = sqlite3.connect(db)
    conn.executescript("DROP TRIGGER audit_log_no_update; DROP TRIGGER audit_log_no_delete;")
    conn.execute("DELETE FROM audit_log WHERE id = (SELECT MAX(id) FROM audit_log)")
    conn.executescript(
        """
        CREATE TRIGGER audit_log_no_update BEFORE UPDATE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        CREATE TRIGGER audit_log_no_delete BEFORE DELETE ON audit_log
        BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
        """
    )
    conn.commit()
    conn.close()
    problems = verify_database(db)
    assert problems == ["audit log tail does not match the stored head"]


def test_verify_audit_rejects_a_bad_file(tmp_path: Path) -> None:
    runner = CliRunner()
    text = tmp_path / "not.db"
    text.write_text("hello", encoding="utf-8")
    rejected = runner.invoke(app, ["verify-audit", "--db", str(text)])
    assert rejected.exit_code == 1
    assert rejected.exception is None or not isinstance(rejected.exception, sqlite3.DatabaseError)
    assert "Traceback" not in rejected.output
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    blank = runner.invoke(app, ["verify-audit", "--db", str(empty)])
    assert blank.exit_code == 1
    assert "Traceback" not in blank.output
    blank_lines = [line for line in blank.output.splitlines() if line.strip()]
    assert blank_lines == ["not a K1-Lens database"]

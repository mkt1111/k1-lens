"""Colon-free development layouts.

Each page prints a catalog label and its value with no colon. The layouts
are a right-aligned amount, a box grid, two columns on one baseline, a
statement that mixes those, and a label with the amount on the next line.
The labels are the catalog strings. This set was written with the extractor,
so it is a seen development set. The held-out set is scored by an independent
reviewer; not in this repo.
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import cast

from reportlab.lib.colors import black
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import (
    CODED_BY_PATH,
    LABEL_DOCUMENT_ID,
    LABEL_TAX_YEAR,
    LABEL_VARIANT,
    SCALAR_FIELDS,
    FieldKind,
)
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import format_value
from k1lens.generate.build import Variant, build_document
from k1lens.generate.corpus import (
    DEFAULT_SEED,
    GroundTruthFile,
    Manifest,
    ManifestDocument,
)
from k1lens.generate.pdf import draw_sample_watermark

GEOMETRY_VERSION = "dev-geometry-2"
GEOMETRY_PLAN: tuple[str, ...] = (
    "face_aligned",
    "face_aligned",
    "box_grid",
    "box_grid",
    "two_column",
    "two_column",
    "statement_columns",
    "statement_columns",
    "stacked",
    "stacked",
    "stacked_columns",
    "stacked_columns",
)

_PAGE_W = cast(float, letter[0])
_PAGE_H = cast(float, letter[1])
_INCH = cast(float, inch)
_LEFT = 0.55 * _INCH
_RIGHT = _PAGE_W - 0.55 * _INCH
_TOP = _PAGE_H - 0.55 * _INCH
_BOTTOM = 0.5 * _INCH


def generate_dev_geometry(dest: Path, *, seed: int = DEFAULT_SEED) -> Manifest:
    """Write the colon-free development set. The same seed rewrites the files."""

    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("K1-*"):
        if stale.suffix in {".pdf", ".json"}:
            stale.unlink()
    rng = random.Random(seed)
    documents: list[ManifestDocument] = []
    for index, kind in enumerate(GEOMETRY_PLAN, start=1):
        document = build_document(rng, index, Variant.CLEAN).model_copy(update={"variant": kind})
        pdf_name = f"{document.document_id}.pdf"
        json_name = f"{document.document_id}.json"
        render_geometry(document, dest / pdf_name, kind=kind)
        truth = GroundTruthFile(planted_defects=[], document=document)
        (dest / json_name).write_text(truth.model_dump_json(indent=2) + "\n", encoding="utf-8")
        documents.append(
            ManifestDocument(
                document_id=document.document_id,
                variant=kind,
                pdf=pdf_name,
                ground_truth=json_name,
                planted_defects=[],
            )
        )
    manifest = Manifest(
        seed=seed,
        count=len(documents),
        generator_version=GEOMETRY_VERSION,
        documents=documents,
    )
    (dest / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def render_geometry(document: ScheduleK1, dest: Path, *, kind: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(dest), pagesize=letter, invariant=1)
    canvas.setTitle(f"{document.document_id} synthetic colon-free K-1")
    canvas.setAuthor("K1-Lens synthetic generator")
    if kind == "face_aligned":
        _face(canvas, _rows(document))
    elif kind == "box_grid":
        _grid(canvas, _rows(document))
    elif kind == "two_column":
        _columns(canvas, _rows(document))
    elif kind == "statement_columns":
        _statement(canvas, document)
    elif kind == "stacked":
        _stacked(canvas, _rows(document))
    elif kind == "stacked_columns":
        _stacked_columns(canvas, _rows(document))
    else:
        raise ValueError(f"Unknown colon-free layout {kind}")
    canvas.save()


def _rows(document: ScheduleK1) -> list[tuple[str, str]]:
    year = "" if document.tax_year is None else str(document.tax_year)
    rows: list[tuple[str, str]] = [
        (LABEL_TAX_YEAR, year),
        (LABEL_DOCUMENT_ID, document.document_id),
        (LABEL_VARIANT, document.variant),
    ]
    rows.extend(_section_rows(document, part_iii=None))
    return rows


def _section_rows(document: ScheduleK1, *, part_iii: bool | None) -> list[tuple[str, str]]:
    rows: list[tuple[str, str]] = []
    for spec in SCALAR_FIELDS:
        in_part_iii = spec.section == "Part III"
        if part_iii is True and not in_part_iii:
            continue
        if part_iii is False and in_part_iii:
            continue
        value = get_extracted(document, spec.path).value
        if value is None:
            continue
        rows.append((spec.pdf_label, format_value(spec.kind, value)))
    if part_iii is False:
        return rows
    for path, box in CODED_BY_PATH.items():
        for item in get_coded(document, path):
            amount = item.amount.value
            if amount is None:
                continue
            rows.append((f"{box.pdf_prefix} {item.code}", format_value(FieldKind.MONEY, amount)))
    return rows


def _new_page(canvas: Canvas) -> None:
    canvas.showPage()
    draw_sample_watermark(canvas)
    canvas.setFillColor(black)
    canvas.setFont("Helvetica", 8)


def _start(canvas: Canvas) -> float:
    draw_sample_watermark(canvas)
    canvas.setFillColor(black)
    canvas.setFont("Helvetica", 8)
    return _TOP


def _face(canvas: Canvas, rows: list[tuple[str, str]]) -> None:
    y = _start(canvas)
    for label, value in rows:
        if y < _BOTTOM:
            _new_page(canvas)
            y = _TOP
        canvas.drawString(_LEFT, y, label)
        canvas.drawRightString(_RIGHT, y, value)
        y -= 11


def _grid(canvas: Canvas, rows: list[tuple[str, str]]) -> None:
    """Box, description, and amount, with ruling lines pdfplumber can see."""

    y = _start(canvas)
    box_x = _LEFT
    desc_x = _LEFT + 42
    amount_right = _RIGHT
    row_h = 13
    width = _RIGHT - _LEFT
    for label, value in rows:
        if y < _BOTTOM + row_h:
            _new_page(canvas)
            y = _TOP
        box, description = _split_label(label)
        bottom = y - 3
        canvas.rect(box_x, bottom, width, row_h, stroke=1, fill=0)
        canvas.line(desc_x, bottom, desc_x, bottom + row_h)
        canvas.line(amount_right - 90, bottom, amount_right - 90, bottom + row_h)
        canvas.setFillColor(black)
        canvas.drawString(box_x + 3, y, box)
        canvas.drawString(desc_x + 4, y, description)
        canvas.drawRightString(amount_right - 4, y, value)
        y -= row_h


def _columns(canvas: Canvas, rows: list[tuple[str, str]]) -> None:
    y = _start(canvas)
    mid = _PAGE_W / 2
    left_value = mid - 14
    right_label = mid + 8
    pairs = list(zip(rows[0::2], rows[1::2], strict=False))
    leftover = rows[-1] if len(rows) % 2 == 1 else None
    for left, right in pairs:
        if y < _BOTTOM:
            _new_page(canvas)
            y = _TOP
        canvas.drawString(_LEFT, y, left[0])
        canvas.drawRightString(left_value, y, left[1])
        canvas.drawString(right_label, y, right[0])
        canvas.drawRightString(_RIGHT, y, right[1])
        y -= 12
    if leftover is not None:
        if y < _BOTTOM:
            _new_page(canvas)
            y = _TOP
        canvas.drawString(_LEFT, y, leftover[0])
        canvas.drawRightString(left_value, y, leftover[1])


def _stacked(canvas: Canvas, rows: list[tuple[str, str]]) -> None:
    """The label, then the amount on the next line, in the same column."""

    y = _start(canvas)
    for label, value in rows:
        if y < _BOTTOM + 16:
            _new_page(canvas)
            y = _TOP
        canvas.drawString(_LEFT, y, label)
        y -= 12
        canvas.drawString(_LEFT, y, value)
        y -= 14


def _stacked_columns(canvas: Canvas, rows: list[tuple[str, str]]) -> None:
    """Two labels on one line. Each amount is on the next line, under its label."""

    y = _start(canvas)
    right_x = _PAGE_W / 2 + 8
    pairs = list(zip(rows[0::2], rows[1::2], strict=False))
    leftover = rows[-1] if len(rows) % 2 == 1 else None
    for left, right in pairs:
        if y < _BOTTOM + 16:
            _new_page(canvas)
            y = _TOP
        canvas.drawString(_LEFT, y, left[0])
        canvas.drawString(right_x, y, right[0])
        y -= 12
        canvas.drawString(_LEFT, y, left[1])
        canvas.drawString(right_x, y, right[1])
        y -= 14
    if leftover is not None:
        if y < _BOTTOM + 16:
            _new_page(canvas)
            y = _TOP
        canvas.drawString(_LEFT, y, leftover[0])
        y -= 12
        canvas.drawString(_LEFT, y, leftover[1])


def _statement(canvas: Canvas, document: ScheduleK1) -> None:
    """Part I and Part II on one column. Part III in two columns."""

    _face(canvas, _section_rows(document, part_iii=False))
    _new_page(canvas)
    year = "" if document.tax_year is None else str(document.tax_year)
    header = [
        (LABEL_TAX_YEAR, year),
        (LABEL_DOCUMENT_ID, document.document_id),
    ]
    _columns(canvas, header + _section_rows(document, part_iii=True))


def _split_label(label: str) -> tuple[str, str]:
    box, _sep, rest = label.partition(" ")
    if rest == "":
        return "", label
    return box, rest

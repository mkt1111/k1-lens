"""Development layouts the in-distribution extractor was not written against.

``layout_shift`` prints the same catalog labels in a different order, font,
and spacing. A high score on that set shows the line parser is not tied to
the generator's coordinates. It still uses the shared label strings.

``dev_statement`` is a second layout with different wording. Those captions
were inspected while tuning later label matching, so this set is a development
set. The strings stay out of the extractor catalog. The held-out set is
scored by an independent reviewer; not in this repo.
"""

from __future__ import annotations

import random
from pathlib import Path

from reportlab.lib.colors import black
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import CODED_BY_PATH, SCALAR_BY_PATH, SCALAR_FIELDS, FieldKind
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

DEV_LAYOUT_VERSION = "dev-layouts-1"
DEV_LAYOUT_PLAN: tuple[str, ...] = (
    "layout_shift",
    "layout_shift",
    "layout_shift",
    "layout_shift",
    "dev_statement",
    "dev_statement",
    "dev_statement",
    "dev_statement",
)

# Alternate wording for the dev statement layout. Kept out of the extractor.
DEV_STATEMENT_LABELS: dict[str, str] = {
    "part_i.ein": "Partnership employer identification number",
    "part_i.name": "Partnership legal name",
    "part_i.street": "Partnership mailing street",
    "part_i.city": "Partnership mailing city",
    "part_i.state": "Partnership mailing state",
    "part_i.zip_code": "Partnership postal code",
    "part_i.irs_center": "Service center where filed",
    "part_i.is_ptp": "Publicly traded partnership flag",
    "part_ii.tin": "Partner taxpayer identifier",
    "part_ii.name": "Partner legal name",
    "part_ii.street": "Partner mailing street",
    "part_ii.city": "Partner mailing city",
    "part_ii.state": "Partner mailing state",
    "part_ii.zip_code": "Partner postal code",
    "part_ii.is_general_partner": "General partner flag",
    "part_ii.is_domestic": "Domestic partner flag",
    "part_ii.entity_type": "Partner entity classification",
    "part_ii.is_retirement_plan": "Retirement plan partner flag",
    "part_ii.profit_beginning": "Profit share at opening",
    "part_ii.profit_ending": "Profit share at closing",
    "part_ii.loss_beginning": "Loss share at opening",
    "part_ii.loss_ending": "Loss share at closing",
    "part_ii.capital_share_beginning": "Capital share at opening",
    "part_ii.capital_share_ending": "Capital share at closing",
    "part_ii.liability_nonrecourse": "Nonrecourse liabilities",
    "part_ii.liability_qualified_nonrecourse": "Qualified nonrecourse financing",
    "part_ii.liability_recourse": "Recourse liabilities",
    "part_ii.capital_method": "Method of capital accounting",
    "part_ii.capital.beginning": "Capital at start of year",
    "part_ii.capital.contributed": "Capital contributed during year",
    "part_ii.capital.current_year_net_income": "Net income per books",
    "part_ii.capital.other_increase_decrease": "Other capital increase or decrease",
    "part_ii.capital.withdrawals": "Cash and property distributed",
    "part_ii.capital.ending": "Capital at end of year",
    "part_ii.contributed_builtin_gain": "Contributed property with built-in gain",
    "part_iii.ordinary_business_income": "Ordinary income from trade or business",
    "part_iii.net_rental_real_estate": "Net rental income from real estate",
    "part_iii.other_net_rental": "Net rental income from other property",
    "part_iii.guaranteed_payments_services": "Guaranteed payments for services rendered",
    "part_iii.guaranteed_payments_capital": "Guaranteed payments for use of capital",
    "part_iii.guaranteed_payments_total": "Guaranteed payments combined total",
    "part_iii.interest_income": "Interest earned",
    "part_iii.ordinary_dividends": "Dividend income ordinary",
    "part_iii.qualified_dividends": "Dividend income qualified",
    "part_iii.dividend_equivalents": "Dividend equivalents amount",
    "part_iii.royalties": "Royalty income",
    "part_iii.net_short_term_capital_gain": "Short-term capital gain or loss",
    "part_iii.net_long_term_capital_gain": "Long-term capital gain or loss",
    "part_iii.collectibles_gain": "Collectibles gain or loss",
    "part_iii.unrecaptured_1250_gain": "Unrecaptured section 1250 gain amount",
    "part_iii.net_section_1231_gain": "Section 1231 gain or loss",
    "part_iii.section_179_deduction": "Section 179 expense",
    "part_iii.schedule_k3_attached": "Schedule K-3 is attached",
    "part_iii.foreign_taxes_paid": "Foreign taxes paid",
}

DEV_STATEMENT_CODED: dict[str, str] = {
    "part_iii.other_income": "Additional income code",
    "part_iii.other_deductions": "Additional deduction code",
    "part_iii.self_employment": "Self employment earnings code",
    "part_iii.credits": "Credit code",
    "part_iii.amt_items": "Alternative minimum tax code",
    "part_iii.tax_exempt_and_nondeductible": "Tax exempt income code",
    "part_iii.distributions": "Distribution code",
    "part_iii.other_information": "Other information code",
}

_PAGE_W, _PAGE_H = letter
_STATEMENT_ORDER: tuple[str, ...] = (
    "part_ii.capital.beginning",
    "part_ii.capital.contributed",
    "part_ii.capital.current_year_net_income",
    "part_ii.capital.other_increase_decrease",
    "part_ii.capital.withdrawals",
    "part_ii.capital.ending",
    "part_ii.capital_method",
    "part_i.ein",
    "part_i.name",
    "part_i.street",
    "part_i.city",
    "part_i.state",
    "part_i.zip_code",
    "part_i.irs_center",
    "part_i.is_ptp",
    "part_ii.tin",
    "part_ii.name",
    "part_ii.street",
    "part_ii.city",
    "part_ii.state",
    "part_ii.zip_code",
    "part_ii.is_general_partner",
    "part_ii.is_domestic",
    "part_ii.entity_type",
    "part_ii.is_retirement_plan",
    "part_ii.profit_beginning",
    "part_ii.profit_ending",
    "part_ii.loss_beginning",
    "part_ii.loss_ending",
    "part_ii.capital_share_beginning",
    "part_ii.capital_share_ending",
    "part_ii.liability_nonrecourse",
    "part_ii.liability_qualified_nonrecourse",
    "part_ii.liability_recourse",
    "part_ii.contributed_builtin_gain",
    "part_iii.foreign_taxes_paid",
    "part_iii.section_179_deduction",
    "part_iii.ordinary_business_income",
    "part_iii.net_rental_real_estate",
    "part_iii.other_net_rental",
    "part_iii.guaranteed_payments_services",
    "part_iii.guaranteed_payments_capital",
    "part_iii.guaranteed_payments_total",
    "part_iii.interest_income",
    "part_iii.ordinary_dividends",
    "part_iii.qualified_dividends",
    "part_iii.dividend_equivalents",
    "part_iii.royalties",
    "part_iii.net_short_term_capital_gain",
    "part_iii.net_long_term_capital_gain",
    "part_iii.collectibles_gain",
    "part_iii.unrecaptured_1250_gain",
    "part_iii.net_section_1231_gain",
    "part_iii.schedule_k3_attached",
)


def generate_dev(dest: Path, *, seed: int = DEFAULT_SEED) -> Manifest:
    """Write the development-layout corpus. Same seed rewrites the same files."""

    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("K1-*"):
        if stale.suffix in {".pdf", ".json"}:
            stale.unlink()
    rng = random.Random(seed)
    documents: list[ManifestDocument] = []
    for index, kind in enumerate(DEV_LAYOUT_PLAN, start=1):
        document = build_document(rng, index, Variant.CLEAN).model_copy(update={"variant": kind})
        pdf_name = f"{document.document_id}.pdf"
        json_name = f"{document.document_id}.json"
        render_dev(document, dest / pdf_name, kind=kind)
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
        generator_version=DEV_LAYOUT_VERSION,
        documents=documents,
    )
    (dest / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def render_dev(document: ScheduleK1, dest: Path, *, kind: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if kind == "layout_shift":
        lines = _layout_shift_lines(document)
        _write(dest, document, lines, font="Times-Roman", size=10, leading=16, margin=1.05 * inch)
        return
    if kind == "dev_statement":
        lines = _dev_statement_lines(document)
        _write(dest, document, lines, font="Courier", size=8, leading=12, margin=0.7 * inch)
        return
    raise ValueError(f"Unknown development layout {kind}")


def _layout_shift_lines(document: ScheduleK1) -> list[str]:
    """Catalog labels, reversed within each section, with spacer lines."""

    header = [
        "SAMPLE FACSIMILE - NOT A FILED RETURN",
        "Partner schedule, alternate arrangement",
        f"TAX YEAR: {document.tax_year if document.tax_year is not None else ''}",
        f"DOCUMENT ID: {document.document_id}",
        f"VARIANT: {document.variant}",
        "Names and amounts are fictitious.",
        "",
        "PARTNER BLOCK",
    ]
    partner = _catalog_section(document, "Part II")
    capital = _catalog_section(document, "Capital account")
    partnership = _catalog_section(document, "Part I")
    income = list(reversed(_catalog_part_iii(document)))
    body = [
        *partner,
        "",
        "CAPITAL BLOCK",
        *capital,
        "",
        "PARTNERSHIP BLOCK",
        *partnership,
    ]
    spaced: list[str] = []
    for line in body:
        spaced.append(line)
        if line and not line.startswith("PARTNER") and not line.startswith("CAPITAL"):
            spaced.append("")
    return header + spaced + ["", "INCOME BLOCK"] + income


def _dev_statement_lines(document: ScheduleK1) -> list[str]:
    """Development layout. Captions are not the catalog labels.

    Capital lines put the amount on the following line, with no colon.
    The other lines use ``caption: value`` with the dev-statement wording.
    """

    lines = [
        "PARTNER SHARE STATEMENT",
        "Sample only. This is not a Schedule K-1 facsimile.",
        f"Form year {document.tax_year if document.tax_year is not None else ''}",
        f"File number {document.document_id}",
        "",
        "CAPITAL ACCOUNT",
    ]
    capital_paths = {
        "part_ii.capital.beginning",
        "part_ii.capital.contributed",
        "part_ii.capital.current_year_net_income",
        "part_ii.capital.other_increase_decrease",
        "part_ii.capital.withdrawals",
        "part_ii.capital.ending",
    }
    for path in _STATEMENT_ORDER:
        if path in capital_paths:
            lines.extend(_stacked(document, path))
        else:
            line = _dev_statement_scalar(document, path)
            if line is not None:
                lines.append(line)
    lines.append("")
    lines.append("CODED ITEMS")
    for path, caption in DEV_STATEMENT_CODED.items():
        for item in get_coded(document, path):
            amount = item.amount.value
            if amount is None:
                continue
            lines.append(caption)
            lines.append(f"    {item.code}    {format_value(FieldKind.MONEY, amount)}")
    lines.append("")
    lines.append("End of partner share statement. Synthetic data only.")
    return lines


def _catalog_section(document: ScheduleK1, section: str) -> list[str]:
    lines: list[str] = []
    for spec in reversed(tuple(spec for spec in SCALAR_FIELDS if spec.section == section)):
        line = _catalog_line(document, spec.path)
        if line is not None:
            lines.append(line)
    return lines


def _catalog_part_iii(document: ScheduleK1) -> list[str]:
    lines: list[str] = []
    for spec in SCALAR_FIELDS:
        if spec.section != "Part III":
            continue
        line = _catalog_line(document, spec.path)
        if line is not None:
            lines.append(line)
    for path, box in CODED_BY_PATH.items():
        for item in get_coded(document, path):
            amount = item.amount.value
            if amount is None:
                continue
            lines.append(f"{box.pdf_prefix} {item.code}: {format_value(FieldKind.MONEY, amount)}")
    return lines


def _catalog_line(document: ScheduleK1, path: str) -> str | None:
    spec = SCALAR_BY_PATH[path]
    value = get_extracted(document, path).value
    if value is None:
        return None
    return f"{spec.pdf_label}: {format_value(spec.kind, value)}"


def _dev_statement_scalar(document: ScheduleK1, path: str) -> str | None:
    spec = SCALAR_BY_PATH[path]
    value = get_extracted(document, path).value
    if value is None:
        return None
    return f"{DEV_STATEMENT_LABELS[path]}: {format_value(spec.kind, value)}"


def _stacked(document: ScheduleK1, path: str) -> list[str]:
    spec = SCALAR_BY_PATH[path]
    value = get_extracted(document, path).value
    if value is None:
        return []
    return [
        DEV_STATEMENT_LABELS[path],
        f"    {format_value(spec.kind, value)}",
    ]


def _write(
    dest: Path,
    document: ScheduleK1,
    lines: list[str],
    *,
    font: str,
    size: int,
    leading: int,
    margin: float,
) -> None:
    canvas = Canvas(str(dest), pagesize=letter, invariant=1)
    canvas.setTitle(f"{document.document_id} synthetic development K-1")
    canvas.setAuthor("K1-Lens synthetic generator")
    y = _PAGE_H - 0.6 * inch
    bottom = 0.55 * inch
    draw_sample_watermark(canvas)
    canvas.setFillColor(black)
    canvas.setFont(font, size)
    for line in lines:
        if y < bottom:
            canvas.showPage()
            draw_sample_watermark(canvas)
            canvas.setFillColor(black)
            canvas.setFont(font, size)
            y = _PAGE_H - 0.6 * inch
        canvas.drawString(margin, y, line)
        y -= leading if line else leading * 0.45
    canvas.save()

"""Development set: a fund-administrator supplemental statement.

The captions are a broker-style restatement of Schedule K-1 (Form 1065)
items. They are not the in-distribution catalog and not the dev-statement
wording. This module is the only place those captions exist. The extractor
must not import them.

This is a development set. The captions were inspected, and the amounts are
the same records as in-distribution K1-0001 through K1-0004 with only the
captions changed. The held-out set is scored by an independent reviewer;
not in this repo. The typeface is Helvetica, the same family as the
in-distribution facsimiles.
"""

from __future__ import annotations

import random
from pathlib import Path

from reportlab.lib.colors import black
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import SCALAR_BY_PATH, FieldKind
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

DEV_B_VERSION = "dev-b-1"
DEV_B_PLAN: tuple[str, ...] = (
    "dev_b",
    "dev_b",
    "dev_b",
    "dev_b",
)

# Fund-administrator captions. Not imported by the extractor.
ADMIN_LABELS: dict[str, str] = {
    "part_i.ein": "Box A Ptrshp EIN",
    "part_i.name": "Box B Ptrshp legal name",
    "part_i.street": "Box B Ptrshp street addr.",
    "part_i.city": "Box B Ptrshp city",
    "part_i.state": "Box B Ptrshp state",
    "part_i.zip_code": "Box B Ptrshp ZIP",
    "part_i.irs_center": "Box C IRS ctr where filed",
    "part_i.is_ptp": "Box D PTP checkbox",
    "part_ii.tin": "Box E Partner TIN",
    "part_ii.name": "Box F Partner legal name",
    "part_ii.street": "Box F Partner street addr.",
    "part_ii.city": "Box F Partner city",
    "part_ii.state": "Box F Partner state",
    "part_ii.zip_code": "Box F Partner ZIP",
    "part_ii.is_general_partner": "Box G General partner checkbox",
    "part_ii.is_domestic": "Box H1 Domestic partner checkbox",
    "part_ii.entity_type": "Box I1 Partner entity type",
    "part_ii.is_retirement_plan": "Box I2 Retirement plan checkbox",
    "part_ii.profit_beginning": "Item J Profit beg. pct",
    "part_ii.profit_ending": "Item J Profit end. pct",
    "part_ii.loss_beginning": "Item J Loss beg. pct",
    "part_ii.loss_ending": "Item J Loss end. pct",
    "part_ii.capital_share_beginning": "Item J Cap. beg. pct",
    "part_ii.capital_share_ending": "Item J Cap. end. pct",
    "part_ii.liability_nonrecourse": "Item K Nonrec. liabilities",
    "part_ii.liability_qualified_nonrecourse": "Item K Qual. nonrec. financing",
    "part_ii.liability_recourse": "Item K Recourse liabilities",
    "part_ii.capital_method": "Item L Cap. acct. method",
    "part_ii.capital.beginning": "Item L Beg. capital acct.",
    "part_ii.capital.contributed": "Item L Cap. contributed during yr",
    "part_ii.capital.current_year_net_income": "Item L Current yr net inc. (loss)",
    "part_ii.capital.other_increase_decrease": "Item L Other incr. (decr.)",
    "part_ii.capital.withdrawals": "Item L Withdr. and dist.",
    "part_ii.capital.ending": "Item L End. capital acct.",
    "part_ii.contributed_builtin_gain": "Item M Built-in gain prop. contributed",
    "part_iii.ordinary_business_income": "Ln 1 Ord. business inc. (loss)",
    "part_iii.net_rental_real_estate": "Ln 2 Net rental RE inc. (loss)",
    "part_iii.other_net_rental": "Ln 3 Other net rental inc. (loss)",
    "part_iii.guaranteed_payments_services": "Ln 4a Guar. pmts for services",
    "part_iii.guaranteed_payments_capital": "Ln 4b Guar. pmts for capital",
    "part_iii.guaranteed_payments_total": "Ln 4c Total guar. pmts",
    "part_iii.interest_income": "Ln 5 Interest inc.",
    "part_iii.ordinary_dividends": "Ln 6a Ord. dividends",
    "part_iii.qualified_dividends": "Ln 6b Qual. dividends",
    "part_iii.dividend_equivalents": "Ln 6c Dividend equiv.",
    "part_iii.royalties": "Ln 7 Royalties",
    "part_iii.net_short_term_capital_gain": "Ln 8 Net ST cap. gain (loss)",
    "part_iii.net_long_term_capital_gain": "Ln 9a Net LT cap. gain (loss)",
    "part_iii.collectibles_gain": "Ln 9b Collectibles (28%) gain (loss)",
    "part_iii.unrecaptured_1250_gain": "Ln 9c Unrecapt. sec. 1250 gain",
    "part_iii.net_section_1231_gain": "Ln 10 Net sec. 1231 gain (loss)",
    "part_iii.section_179_deduction": "Ln 12 Sec. 179 ded.",
    "part_iii.schedule_k3_attached": "Ln 16 Sch. K-3 attached",
    "part_iii.foreign_taxes_paid": "Ln 21 Foreign taxes paid or accrued",
}

ADMIN_CODED: dict[str, str] = {
    "part_iii.other_income": "Ln 11 Other inc. code",
    "part_iii.other_deductions": "Ln 13 Other ded. code",
    "part_iii.self_employment": "Ln 14 Self-empl. earnings code",
    "part_iii.credits": "Ln 15 Credits code",
    "part_iii.amt_items": "Ln 17 AMT items code",
    "part_iii.tax_exempt_and_nondeductible": "Ln 18 Tax-exempt inc. code",
    "part_iii.distributions": "Ln 19 Dist. code",
    "part_iii.other_information": "Ln 20 Other info. code",
}

_PAGE_W, _PAGE_H = letter


def generate_dev_b(dest: Path, *, seed: int = DEFAULT_SEED) -> Manifest:
    """Write the fund-administrator development set. Same seed, same files."""

    dest.mkdir(parents=True, exist_ok=True)
    for stale in dest.glob("K1-*"):
        if stale.suffix in {".pdf", ".json"}:
            stale.unlink()
    rng = random.Random(seed)
    documents: list[ManifestDocument] = []
    for index, kind in enumerate(DEV_B_PLAN, start=1):
        document = build_document(rng, index, Variant.CLEAN).model_copy(update={"variant": kind})
        pdf_name = f"{document.document_id}.pdf"
        json_name = f"{document.document_id}.json"
        render_dev_b(document, dest / pdf_name)
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
        generator_version=DEV_B_VERSION,
        documents=documents,
    )
    (dest / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return manifest


def render_dev_b(document: ScheduleK1, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _write(dest, document, _admin_lines(document))


def _admin_lines(document: ScheduleK1) -> list[str]:
    year = document.tax_year if document.tax_year is not None else ""
    lines = [
        "HARBOR LANE FUND SERVICES",
        "Investor tax package, supplemental statement",
        "Schedule K-1 (Form 1065) items restated for the limited partner.",
        "Not the IRS form. Synthetic sample. Do not file.",
        f"Reporting period: {year}",
        f"Administrator file: {document.document_id}",
        "Custody account: SAMPLE",
        "",
        "PARTNERSHIP BLOCK",
    ]
    for path in (
        "part_i.ein",
        "part_i.name",
        "part_i.street",
        "part_i.city",
        "part_i.state",
        "part_i.zip_code",
        "part_i.irs_center",
        "part_i.is_ptp",
    ):
        _append_scalar(lines, document, path)
    lines.append("")
    lines.append("INVESTOR BLOCK")
    for path in (
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
        "part_ii.capital_method",
        "part_ii.capital.beginning",
        "part_ii.capital.contributed",
        "part_ii.capital.current_year_net_income",
        "part_ii.capital.other_increase_decrease",
        "part_ii.capital.withdrawals",
        "part_ii.capital.ending",
        "part_ii.contributed_builtin_gain",
    ):
        _append_scalar(lines, document, path)
    lines.append("")
    lines.append("TAXABLE INCOME LINES")
    for path in (
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
        "part_iii.section_179_deduction",
        "part_iii.schedule_k3_attached",
        "part_iii.foreign_taxes_paid",
    ):
        _append_scalar(lines, document, path)
    lines.append("")
    lines.append("CODED LINES")
    for path, caption in ADMIN_CODED.items():
        for item in get_coded(document, path):
            amount = item.amount.value
            if amount is None:
                continue
            lines.append(f"{caption} {item.code}: {format_value(FieldKind.MONEY, amount)}")
    lines.append("")
    lines.append("End of Harbor Lane supplemental statement. Synthetic data only.")
    return lines


def _append_scalar(lines: list[str], document: ScheduleK1, path: str) -> None:
    spec = SCALAR_BY_PATH[path]
    value = get_extracted(document, path).value
    if value is None:
        return
    lines.append(f"{ADMIN_LABELS[path]}: {format_value(spec.kind, value)}")


def _write(dest: Path, document: ScheduleK1, lines: list[str]) -> None:
    canvas = Canvas(str(dest), pagesize=letter, invariant=1)
    canvas.setTitle(f"{document.document_id} synthetic fund-admin statement")
    canvas.setAuthor("K1-Lens synthetic generator")
    y = _PAGE_H - 0.6 * inch
    bottom = 0.55 * inch
    draw_sample_watermark(canvas)
    canvas.setFillColor(black)
    canvas.setFont("Helvetica", 9)
    for line in lines:
        if y < bottom:
            canvas.showPage()
            draw_sample_watermark(canvas)
            canvas.setFillColor(black)
            canvas.setFont("Helvetica", 9)
            y = _PAGE_H - 0.6 * inch
        canvas.drawString(0.7 * inch, y, line)
        y -= 13 if line else 6
    canvas.save()

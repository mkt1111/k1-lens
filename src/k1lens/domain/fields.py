"""Shared catalog of K-1 labels.

The generator prints these labels, the extractors read them, and the review
UI lists them. Keeping one catalog is what keeps those three in step.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

# A field at or above this confidence is not highlighted for human review.
REVIEW_THRESHOLD = 0.8


class FieldKind(StrEnum):
    STRING = "str"
    MONEY = "money"
    PERCENT = "percent"
    BOOL = "bool"
    INT = "int"


@dataclass(frozen=True, slots=True)
class FieldSpec:
    path: str
    pdf_label: str
    section: str
    kind: FieldKind
    required: bool
    box: str


@dataclass(frozen=True, slots=True)
class CodedBoxSpec:
    path: str
    pdf_prefix: str
    section: str
    box: str


PART_III = "Part III"

SCALAR_FIELDS: tuple[FieldSpec, ...] = (
    FieldSpec("part_i.ein", "A Partnership EIN", "Part I", FieldKind.STRING, True, "A"),
    FieldSpec("part_i.name", "B Partnership name", "Part I", FieldKind.STRING, True, "B"),
    FieldSpec("part_i.street", "B Partnership street", "Part I", FieldKind.STRING, False, "B"),
    FieldSpec("part_i.city", "B Partnership city", "Part I", FieldKind.STRING, False, "B"),
    FieldSpec("part_i.state", "B Partnership state", "Part I", FieldKind.STRING, False, "B"),
    FieldSpec("part_i.zip_code", "B Partnership ZIP", "Part I", FieldKind.STRING, False, "B"),
    FieldSpec("part_i.irs_center", "C IRS center", "Part I", FieldKind.STRING, False, "C"),
    FieldSpec("part_i.is_ptp", "D PTP", "Part I", FieldKind.BOOL, False, "D"),
    FieldSpec("part_ii.tin", "E Partner TIN", "Part II", FieldKind.STRING, True, "E"),
    FieldSpec("part_ii.name", "F Partner name", "Part II", FieldKind.STRING, True, "F"),
    FieldSpec("part_ii.street", "F Partner street", "Part II", FieldKind.STRING, False, "F"),
    FieldSpec("part_ii.city", "F Partner city", "Part II", FieldKind.STRING, False, "F"),
    FieldSpec("part_ii.state", "F Partner state", "Part II", FieldKind.STRING, False, "F"),
    FieldSpec("part_ii.zip_code", "F Partner ZIP", "Part II", FieldKind.STRING, False, "F"),
    FieldSpec(
        "part_ii.is_general_partner", "G General partner", "Part II", FieldKind.BOOL, False, "G"
    ),
    FieldSpec("part_ii.is_domestic", "H1 Domestic partner", "Part II", FieldKind.BOOL, False, "H1"),
    FieldSpec("part_ii.entity_type", "I1 Entity type", "Part II", FieldKind.STRING, False, "I1"),
    FieldSpec(
        "part_ii.is_retirement_plan",
        "I2 Retirement plan",
        "Part II",
        FieldKind.BOOL,
        False,
        "I2",
    ),
    FieldSpec(
        "part_ii.profit_beginning",
        "J Profit beginning pct",
        "Part II",
        FieldKind.PERCENT,
        False,
        "J",
    ),
    FieldSpec(
        "part_ii.profit_ending", "J Profit ending pct", "Part II", FieldKind.PERCENT, False, "J"
    ),
    FieldSpec(
        "part_ii.loss_beginning", "J Loss beginning pct", "Part II", FieldKind.PERCENT, False, "J"
    ),
    FieldSpec("part_ii.loss_ending", "J Loss ending pct", "Part II", FieldKind.PERCENT, False, "J"),
    FieldSpec(
        "part_ii.capital_share_beginning",
        "J Capital beginning pct",
        "Part II",
        FieldKind.PERCENT,
        False,
        "J",
    ),
    FieldSpec(
        "part_ii.capital_share_ending",
        "J Capital ending pct",
        "Part II",
        FieldKind.PERCENT,
        False,
        "J",
    ),
    FieldSpec(
        "part_ii.liability_nonrecourse",
        "K Nonrecourse",
        "Part II",
        FieldKind.MONEY,
        False,
        "K",
    ),
    FieldSpec(
        "part_ii.liability_qualified_nonrecourse",
        "K Qualified nonrecourse",
        "Part II",
        FieldKind.MONEY,
        False,
        "K",
    ),
    FieldSpec("part_ii.liability_recourse", "K Recourse", "Part II", FieldKind.MONEY, False, "K"),
    FieldSpec(
        "part_ii.capital_method",
        "L Capital method",
        "Capital account",
        FieldKind.STRING,
        False,
        "L",
    ),
    FieldSpec(
        "part_ii.capital.beginning",
        "L Beginning capital",
        "Capital account",
        FieldKind.MONEY,
        True,
        "L",
    ),
    FieldSpec(
        "part_ii.capital.contributed",
        "L Capital contributed",
        "Capital account",
        FieldKind.MONEY,
        True,
        "L",
    ),
    FieldSpec(
        "part_ii.capital.current_year_net_income",
        "L Current year net income",
        "Capital account",
        FieldKind.MONEY,
        True,
        "L",
    ),
    FieldSpec(
        "part_ii.capital.other_increase_decrease",
        "L Other increase decrease",
        "Capital account",
        FieldKind.MONEY,
        True,
        "L",
    ),
    FieldSpec(
        "part_ii.capital.withdrawals",
        "L Withdrawals and distributions",
        "Capital account",
        FieldKind.MONEY,
        True,
        "L",
    ),
    FieldSpec(
        "part_ii.capital.ending",
        "L Ending capital",
        "Capital account",
        FieldKind.MONEY,
        True,
        "L",
    ),
    FieldSpec(
        "part_ii.contributed_builtin_gain",
        "M Built-in gain property",
        "Part II",
        FieldKind.BOOL,
        False,
        "M",
    ),
    FieldSpec(
        "part_iii.ordinary_business_income",
        "1 Ordinary business income",
        PART_III,
        FieldKind.MONEY,
        False,
        "1",
    ),
    FieldSpec(
        "part_iii.net_rental_real_estate",
        "2 Net rental real estate income",
        PART_III,
        FieldKind.MONEY,
        False,
        "2",
    ),
    FieldSpec(
        "part_iii.other_net_rental",
        "3 Other net rental income",
        PART_III,
        FieldKind.MONEY,
        False,
        "3",
    ),
    FieldSpec(
        "part_iii.guaranteed_payments_services",
        "4a Guaranteed payments for services",
        PART_III,
        FieldKind.MONEY,
        False,
        "4a",
    ),
    FieldSpec(
        "part_iii.guaranteed_payments_capital",
        "4b Guaranteed payments for capital",
        PART_III,
        FieldKind.MONEY,
        False,
        "4b",
    ),
    FieldSpec(
        "part_iii.guaranteed_payments_total",
        "4c Total guaranteed payments",
        PART_III,
        FieldKind.MONEY,
        False,
        "4c",
    ),
    FieldSpec(
        "part_iii.interest_income", "5 Interest income", PART_III, FieldKind.MONEY, False, "5"
    ),
    FieldSpec(
        "part_iii.ordinary_dividends",
        "6a Ordinary dividends",
        PART_III,
        FieldKind.MONEY,
        False,
        "6a",
    ),
    FieldSpec(
        "part_iii.qualified_dividends",
        "6b Qualified dividends",
        PART_III,
        FieldKind.MONEY,
        False,
        "6b",
    ),
    FieldSpec(
        "part_iii.dividend_equivalents",
        "6c Dividend equivalents",
        PART_III,
        FieldKind.MONEY,
        False,
        "6c",
    ),
    FieldSpec("part_iii.royalties", "7 Royalties", PART_III, FieldKind.MONEY, False, "7"),
    FieldSpec(
        "part_iii.net_short_term_capital_gain",
        "8 Net short-term capital gain",
        PART_III,
        FieldKind.MONEY,
        False,
        "8",
    ),
    FieldSpec(
        "part_iii.net_long_term_capital_gain",
        "9a Net long-term capital gain",
        PART_III,
        FieldKind.MONEY,
        False,
        "9a",
    ),
    FieldSpec(
        "part_iii.collectibles_gain", "9b Collectibles gain", PART_III, FieldKind.MONEY, False, "9b"
    ),
    FieldSpec(
        "part_iii.unrecaptured_1250_gain",
        "9c Unrecaptured section 1250 gain",
        PART_III,
        FieldKind.MONEY,
        False,
        "9c",
    ),
    FieldSpec(
        "part_iii.net_section_1231_gain",
        "10 Net section 1231 gain",
        PART_III,
        FieldKind.MONEY,
        False,
        "10",
    ),
    FieldSpec(
        "part_iii.section_179_deduction",
        "12 Section 179 deduction",
        PART_III,
        FieldKind.MONEY,
        False,
        "12",
    ),
    FieldSpec(
        "part_iii.schedule_k3_attached",
        "16 Schedule K-3 attached",
        PART_III,
        FieldKind.BOOL,
        False,
        "16",
    ),
    FieldSpec(
        "part_iii.foreign_taxes_paid",
        "21 Foreign taxes paid or accrued",
        PART_III,
        FieldKind.MONEY,
        False,
        "21",
    ),
)

CODED_BOXES: tuple[CodedBoxSpec, ...] = (
    CodedBoxSpec("part_iii.other_income", "11 Other income", PART_III, "11"),
    CodedBoxSpec("part_iii.other_deductions", "13 Other deductions", PART_III, "13"),
    CodedBoxSpec("part_iii.self_employment", "14 Self-employment", PART_III, "14"),
    CodedBoxSpec("part_iii.credits", "15 Credits", PART_III, "15"),
    CodedBoxSpec("part_iii.amt_items", "17 AMT items", PART_III, "17"),
    CodedBoxSpec("part_iii.tax_exempt_and_nondeductible", "18 Tax-exempt income", PART_III, "18"),
    CodedBoxSpec("part_iii.distributions", "19 Distributions", PART_III, "19"),
    CodedBoxSpec("part_iii.other_information", "20 Other information", PART_III, "20"),
)

SCALAR_BY_LABEL: dict[str, FieldSpec] = {spec.pdf_label: spec for spec in SCALAR_FIELDS}
SCALAR_BY_PATH: dict[str, FieldSpec] = {spec.path: spec for spec in SCALAR_FIELDS}
CODED_BY_PATH: dict[str, CodedBoxSpec] = {spec.path: spec for spec in CODED_BOXES}

LABEL_TAX_YEAR = "TAX YEAR"
LABEL_DOCUMENT_ID = "DOCUMENT ID"
LABEL_VARIANT = "VARIANT"

CAPITAL_COMPONENTS: tuple[str, ...] = (
    "part_ii.capital.beginning",
    "part_ii.capital.contributed",
    "part_ii.capital.current_year_net_income",
    "part_ii.capital.other_increase_decrease",
    "part_ii.capital.withdrawals",
    "part_ii.capital.ending",
)

PERCENT_PATHS: tuple[str, ...] = tuple(
    spec.path for spec in SCALAR_FIELDS if spec.kind is FieldKind.PERCENT
)

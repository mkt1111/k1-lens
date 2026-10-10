"""Build one internally consistent synthetic Schedule K-1, then apply a variant."""

from __future__ import annotations

import random
from decimal import Decimal
from enum import StrEnum

from k1lens.domain.access import UnknownFieldError, parse_coded_path
from k1lens.domain.blank import extracted
from k1lens.domain.models import (
    CapitalAccount,
    CodedAmount,
    Extracted,
    PartI,
    PartII,
    PartIII,
    ScheduleK1,
)
from k1lens.generate.income import synthetic_net_income
from k1lens.generate.samples import (
    CAPITAL_METHODS,
    CITIES,
    ENTITY_TYPES,
    IRS_CENTERS,
    PARTNER_NAMES,
    PARTNERSHIP_NAMES,
    STREETS,
    TAX_YEARS,
)

PAGE_ONE = 1
PAGE_TWO = 2
GROUND_TRUTH = "ground_truth"
INCONSISTENT_DELTA = Decimal("5000.00")

# Realistic subsets of the Form 1065 Schedule K-1 code lists. Not every code
# on the form, and not only code A.
PART_III_CODES: dict[str, tuple[str, ...]] = {
    "11": ("A", "B", "C", "E", "F"),
    "13": ("A", "B", "H", "I", "W"),
    "14": ("A", "C"),
    "15": ("A", "C", "P"),
    "17": ("A", "B", "C"),
    "18": ("A", "B", "C"),
    "19": ("A", "C"),
    "20": ("A", "B", "N", "V", "Z"),
}


class Variant(StrEnum):
    CLEAN = "clean"
    ROTATED = "rotated"
    RASTERIZED = "rasterized"
    MISSING_FIELDS = "missing_fields"
    INCONSISTENT_CAPITAL = "inconsistent_capital"
    INVALID_EIN = "invalid_ein"
    INVALID_PERCENTAGE = "invalid_percentage"


PLANTED_DEFECTS: dict[Variant, tuple[str, ...]] = {
    Variant.CLEAN: (),
    Variant.ROTATED: (),
    Variant.RASTERIZED: (),
    Variant.MISSING_FIELDS: ("required_fields",),
    Variant.INCONSISTENT_CAPITAL: ("capital_reconciles",),
    Variant.INVALID_EIN: ("ein_format",),
    Variant.INVALID_PERCENTAGE: ("percentage_range",),
}

DEFAULT_PLAN: tuple[Variant, ...] = (
    Variant.CLEAN,
    Variant.CLEAN,
    Variant.CLEAN,
    Variant.CLEAN,
    Variant.ROTATED,
    Variant.ROTATED,
    Variant.RASTERIZED,
    Variant.RASTERIZED,
    Variant.MISSING_FIELDS,
    Variant.MISSING_FIELDS,
    Variant.INCONSISTENT_CAPITAL,
    Variant.INCONSISTENT_CAPITAL,
    Variant.INVALID_EIN,
    Variant.INVALID_PERCENTAGE,
)


def plan_for_count(count: int, plan: tuple[Variant, ...] | None = None) -> list[Variant]:
    if count < 1:
        raise ValueError("count must be at least 1")
    base = list(plan or DEFAULT_PLAN)
    if count <= len(base):
        return base[:count]
    out: list[Variant] = []
    while len(out) < count:
        out.extend(base)
    return out[:count]


def build_document(rng: random.Random, index: int, variant: Variant) -> ScheduleK1:
    """Build the document at ``index`` (1-based).

    Amounts depend on the seed and the index, not on the variant. Defects are
    applied afterwards, so two corpora that share a seed have the same economics
    at the same index.
    """

    consistent = _consistent(rng, index)
    return apply_variant(consistent, variant, index)


def apply_variant(doc: ScheduleK1, variant: Variant, index: int) -> ScheduleK1:
    data = doc.model_dump(mode="json")
    data["variant"] = variant.value
    if variant is Variant.MISSING_FIELDS:
        for path in ("part_i.ein", "part_ii.name", "part_ii.capital.ending"):
            _clear(data, path)
    elif variant is Variant.INCONSISTENT_CAPITAL:
        node = _node(data, "part_ii.capital.ending")
        node["value"] = str(Decimal(str(node["value"])) + INCONSISTENT_DELTA)
    elif variant is Variant.INVALID_EIN:
        node = _node(data, "part_i.ein")
        node["value"] = f"00-{index:05d}"
    elif variant is Variant.INVALID_PERCENTAGE:
        node = _node(data, "part_ii.profit_ending")
        node["value"] = "140.00"
        node["confidence"] = 1.0
    return ScheduleK1.model_validate(data)


def _clear(data: dict[str, object], path: str) -> None:
    node = _node(data, path)
    node["value"] = None
    node["confidence"] = 0.0
    provenance = node.get("provenance")
    if isinstance(provenance, dict):
        provenance["page"] = None
        provenance["bbox"] = None


def _node(data: dict[str, object], path: str) -> dict[str, object]:
    coded = parse_coded_path(path)
    if coded is not None:
        raise UnknownFieldError(path)
    current: object = data
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise UnknownFieldError(path)
        current = current[part]
    if not isinstance(current, dict):
        raise UnknownFieldError(path)
    return current


def _consistent(rng: random.Random, index: int) -> ScheduleK1:
    tax_year = rng.choice(TAX_YEARS)
    partnership = rng.choice(PARTNERSHIP_NAMES)
    partner = rng.choice(PARTNER_NAMES)
    p_street = rng.choice(STREETS)
    p_city, p_state, p_zip = rng.choice(CITIES)
    f_street = rng.choice(STREETS)
    f_city, f_state, f_zip = rng.choice(CITIES)
    entity = rng.choice(ENTITY_TYPES)
    general = _flag(rng, 0.3)
    domestic = _flag(rng, 0.9)
    retirement = _flag(rng, 0.05)
    ptp = _flag(rng, 0.05)
    irs_center = rng.choice(IRS_CENTERS)
    method = rng.choice(CAPITAL_METHODS)
    profit_b, profit_e = _pair(rng)
    loss_b, loss_e = _pair(rng)
    cap_b, cap_e = _pair(rng)
    nonrecourse = _dollars(rng, 0, 20000)
    qualified = _dollars(rng, 0, 20000)
    recourse = _dollars(rng, 0, 10000)
    beginning = _dollars(rng, 50000, 400000)
    contributed = _dollars(rng, 0, 80000)
    ordinary = _dollars(rng, -5000, 40000)
    rental = _sometimes(rng, 0, 15000, 0.4)
    other_rental = _sometimes(rng, 0, 8000, 0.2)
    gp_services = _sometimes(rng, 0, 20000, 0.35)
    gp_capital = _sometimes(rng, 0, 5000, 0.15)
    interest = _sometimes(rng, 0, 8000, 0.7)
    dividends = _sometimes(rng, 0, 6000, 0.55)
    qualified_div = min(dividends, _dollars(rng, 0, int(dividends) if dividends > 0 else 0))
    equivalents = _sometimes(rng, 0, 2000, 0.15)
    royalties = _sometimes(rng, 0, 4000, 0.2)
    stcg = _sometimes(rng, -3000, 8000, 0.4)
    ltcg = _sometimes(rng, -2000, 12000, 0.5)
    collectibles = min(max(ltcg, Decimal("0")), _dollars(rng, 0, int(max(ltcg, Decimal("0")))))
    unrecaptured = min(
        max(ltcg, Decimal("0")) - collectibles,
        _dollars(rng, 0, int(max(ltcg - collectibles, Decimal("0")))),
    )
    sec1231 = _sometimes(rng, -2000, 6000, 0.25)
    other_income_lines = _spread(rng, PART_III_CODES["11"], 100, 5000, 0.55)
    section_179 = _sometimes(rng, 0, 4000, 0.25)
    other_deduction_lines = _spread(rng, PART_III_CODES["13"], 50, 3000, 0.55)
    foreign_tax = _sometimes(rng, 0, 1500, 0.2)
    other_increase = _dollars(rng, -2000, 2000)
    withdrawals = _dollars(rng, 0, 25000)
    builtin = _flag(rng, 0.1)
    k3 = _flag(rng, 0.2)
    self_employment = max(ordinary, Decimal("0")) if general else Decimal("0")
    self_employment_lines = _allocate(rng, self_employment, PART_III_CODES["14"])
    credit_lines = _spread(rng, PART_III_CODES["15"], 50, 2000, 0.4)
    amt_lines = _spread(rng, PART_III_CODES["17"], 25, 1500, 0.45)
    tax_exempt_lines = _spread(rng, PART_III_CODES["18"], 50, 1500, 0.4)
    distribution_lines = _allocate(rng, withdrawals, PART_III_CODES["19"])
    other_info_lines = _spread(rng, PART_III_CODES["20"], 25, 1000, 0.4)

    def money(label: str, value: Decimal, page: int) -> Extracted[Decimal]:
        return extracted(value, label=label, extractor=GROUND_TRUTH, page=page, confidence=1.0)

    def text(label: str, value: str, page: int) -> Extracted[str]:
        return extracted(value, label=label, extractor=GROUND_TRUTH, page=page, confidence=1.0)

    def flag(label: str, value: bool, page: int) -> Extracted[bool]:
        return extracted(value, label=label, extractor=GROUND_TRUTH, page=page, confidence=1.0)

    def coded(box_label: str, code: str, value: Decimal) -> CodedAmount:
        return CodedAmount(
            code=code,
            amount=extracted(
                value,
                label=f"{box_label} {code}",
                extractor=GROUND_TRUTH,
                page=PAGE_TWO,
                confidence=1.0,
            ),
        )

    part_iii = PartIII(
        ordinary_business_income=money("1 Ordinary business income", ordinary, PAGE_TWO),
        net_rental_real_estate=money("2 Net rental real estate income", rental, PAGE_TWO),
        other_net_rental=money("3 Other net rental income", other_rental, PAGE_TWO),
        guaranteed_payments_services=money(
            "4a Guaranteed payments for services", gp_services, PAGE_TWO
        ),
        guaranteed_payments_capital=money(
            "4b Guaranteed payments for capital", gp_capital, PAGE_TWO
        ),
        guaranteed_payments_total=money(
            "4c Total guaranteed payments", gp_services + gp_capital, PAGE_TWO
        ),
        interest_income=money("5 Interest income", interest, PAGE_TWO),
        ordinary_dividends=money("6a Ordinary dividends", dividends, PAGE_TWO),
        qualified_dividends=money("6b Qualified dividends", qualified_div, PAGE_TWO),
        dividend_equivalents=money("6c Dividend equivalents", equivalents, PAGE_TWO),
        royalties=money("7 Royalties", royalties, PAGE_TWO),
        net_short_term_capital_gain=money("8 Net short-term capital gain", stcg, PAGE_TWO),
        net_long_term_capital_gain=money("9a Net long-term capital gain", ltcg, PAGE_TWO),
        collectibles_gain=money("9b Collectibles gain", collectibles, PAGE_TWO),
        unrecaptured_1250_gain=money("9c Unrecaptured section 1250 gain", unrecaptured, PAGE_TWO),
        net_section_1231_gain=money("10 Net section 1231 gain", sec1231, PAGE_TWO),
        other_income=[
            coded("11 Other income", code, amount) for code, amount in other_income_lines
        ],
        section_179_deduction=money("12 Section 179 deduction", section_179, PAGE_TWO),
        other_deductions=[
            coded("13 Other deductions", code, amount) for code, amount in other_deduction_lines
        ],
        self_employment=[
            coded("14 Self-employment", code, amount) for code, amount in self_employment_lines
        ],
        credits=[coded("15 Credits", code, amount) for code, amount in credit_lines],
        schedule_k3_attached=flag("16 Schedule K-3 attached", k3, PAGE_TWO),
        amt_items=[coded("17 AMT items", code, amount) for code, amount in amt_lines],
        tax_exempt_and_nondeductible=[
            coded("18 Tax-exempt income", code, amount) for code, amount in tax_exempt_lines
        ],
        distributions=[
            coded("19 Distributions", code, amount) for code, amount in distribution_lines
        ],
        other_information=[
            coded("20 Other information", code, amount) for code, amount in other_info_lines
        ],
        foreign_taxes_paid=money("21 Foreign taxes paid or accrued", foreign_tax, PAGE_TWO),
    )
    net_income = synthetic_net_income(part_iii)
    ending = beginning + contributed + net_income + other_increase - withdrawals
    tin = f"000-00-{index:04d}" if entity == "Individual" else f"00-{index + 1_000_000:07d}"
    return ScheduleK1(
        document_id=f"K1-{index:04d}",
        tax_year=tax_year,
        synthetic=True,
        variant=Variant.CLEAN.value,
        part_i=PartI(
            ein=text("A Partnership EIN", f"00-{index:07d}", PAGE_ONE),
            name=text("B Partnership name", partnership, PAGE_ONE),
            street=text("B Partnership street", p_street, PAGE_ONE),
            city=text("B Partnership city", p_city, PAGE_ONE),
            state=text("B Partnership state", p_state, PAGE_ONE),
            zip_code=text("B Partnership ZIP", p_zip, PAGE_ONE),
            irs_center=text("C IRS center", irs_center, PAGE_ONE),
            is_ptp=flag("D PTP", ptp, PAGE_ONE),
        ),
        part_ii=PartII(
            tin=text("E Partner TIN", tin, PAGE_ONE),
            name=text("F Partner name", partner, PAGE_ONE),
            street=text("F Partner street", f_street, PAGE_ONE),
            city=text("F Partner city", f_city, PAGE_ONE),
            state=text("F Partner state", f_state, PAGE_ONE),
            zip_code=text("F Partner ZIP", f_zip, PAGE_ONE),
            is_general_partner=flag("G General partner", general, PAGE_ONE),
            is_domestic=flag("H1 Domestic partner", domestic, PAGE_ONE),
            entity_type=text("I1 Entity type", entity, PAGE_ONE),
            is_retirement_plan=flag("I2 Retirement plan", retirement, PAGE_ONE),
            profit_beginning=money("J Profit beginning pct", profit_b, PAGE_ONE),
            profit_ending=money("J Profit ending pct", profit_e, PAGE_ONE),
            loss_beginning=money("J Loss beginning pct", loss_b, PAGE_ONE),
            loss_ending=money("J Loss ending pct", loss_e, PAGE_ONE),
            capital_share_beginning=money("J Capital beginning pct", cap_b, PAGE_ONE),
            capital_share_ending=money("J Capital ending pct", cap_e, PAGE_ONE),
            liability_nonrecourse=money("K Nonrecourse", nonrecourse, PAGE_ONE),
            liability_qualified_nonrecourse=money("K Qualified nonrecourse", qualified, PAGE_ONE),
            liability_recourse=money("K Recourse", recourse, PAGE_ONE),
            capital_method=text("L Capital method", method, PAGE_ONE),
            capital=CapitalAccount(
                beginning=money("L Beginning capital", beginning, PAGE_ONE),
                contributed=money("L Capital contributed", contributed, PAGE_ONE),
                current_year_net_income=money("L Current year net income", net_income, PAGE_ONE),
                other_increase_decrease=money(
                    "L Other increase decrease", other_increase, PAGE_ONE
                ),
                withdrawals=money("L Withdrawals and distributions", withdrawals, PAGE_ONE),
                ending=money("L Ending capital", ending, PAGE_ONE),
            ),
            contributed_builtin_gain=flag("M Built-in gain property", builtin, PAGE_ONE),
        ),
        part_iii=part_iii,
    )


def _flag(rng: random.Random, probability: float) -> bool:
    return rng.random() < probability


def _dollars(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low, high))


def _spread(
    rng: random.Random,
    codes: tuple[str, ...],
    low: int,
    high: int,
    probability: float,
) -> list[tuple[str, Decimal]]:
    """Draw one to three distinct codes, or nothing."""

    if rng.random() >= probability:
        return []
    count = rng.randint(1, min(3, len(codes)))
    chosen = rng.sample(list(codes), count)
    return [(code, _dollars(rng, low, high)) for code in chosen]


def _allocate(
    rng: random.Random, total: Decimal, codes: tuple[str, ...]
) -> list[tuple[str, Decimal]]:
    """Split a non-negative total across one or two codes. The parts sum to it."""

    if total <= 0:
        return []
    # Two codes whenever the amount can be split. A one-code draw is the
    # fallback for a total of 1, so a corpus is not stuck on code A.
    count = 2 if len(codes) > 1 and total >= 2 else 1
    chosen = rng.sample(list(codes), count)
    if count == 1 or total < 2:
        return [(chosen[0], total)]
    first = Decimal(rng.randint(1, int(total) - 1))
    return [(chosen[0], first), (chosen[1], total - first)]


def _sometimes(rng: random.Random, low: int, high: int, probability: float) -> Decimal:
    amount = _dollars(rng, low, high)
    if rng.random() < probability:
        return amount
    return Decimal("0")


def _pair(rng: random.Random) -> tuple[Decimal, Decimal]:
    beginning = Decimal(rng.randint(1, 30))
    ending = Decimal(rng.randint(1, 30))
    if rng.random() < 0.5:
        ending = beginning
    return beginning, ending

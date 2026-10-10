"""Pydantic schema for a synthetic IRS Schedule K-1 (Form 1065)."""

from __future__ import annotations

from decimal import Decimal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_validator,
    model_serializer,
    model_validator,
)


class Provenance(BaseModel):
    """Where an extracted value came from."""

    model_config = ConfigDict(extra="forbid")

    page: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    field_name: str | None = None
    extractor: str | None = None
    # Lowest OCR confidence among digit words of an EIN or TIN. None on a
    # text-layer read. Identity matching refuses an OCR id below the threshold.
    id_digit_confidence: float | None = None
    # Confidence before the roster hold. A full exact match lifts the field
    # to the review threshold. It does not copy this number back.
    evidence_confidence: float | None = None
    # False when the value was not read from this field's own region:
    # another column, an unanchored read, or a model value.
    own_region: bool = True

    @model_serializer(mode="wrap")
    def _omit_unset_read_facts(self, handler: SerializerFunctionWrapHandler) -> object:
        """Keep generated ground truth byte-stable.

        These facts are absent on a generator record. Writing the defaults
        into every provenance object would change every scan file's hash
        without changing the page.
        """

        data = handler(self)
        if isinstance(data, dict):
            if data.get("id_digit_confidence") is None:
                data.pop("id_digit_confidence", None)
            if data.get("evidence_confidence") is None:
                data.pop("evidence_confidence", None)
            if data.get("own_region") is True:
                data.pop("own_region", None)
        return data


class Extracted[T](BaseModel):
    """A single value with confidence and source provenance.

    ``confidence`` is 0 when the value is missing and 1 when a reviewer has
    accepted or entered it. Extractors set a value in between.
    """

    model_config = ConfigDict(extra="forbid")

    value: T | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    provenance: Provenance = Field(default_factory=Provenance)


class CodedAmount(BaseModel):
    """One coded line under a Part III box (for example 11A or 19A)."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=1, max_length=2)
    amount: Extracted[Decimal]
    description: str | None = None


class PartI(BaseModel):
    """Part I, information about the partnership."""

    model_config = ConfigDict(extra="forbid")

    ein: Extracted[str]
    name: Extracted[str]
    street: Extracted[str]
    city: Extracted[str]
    state: Extracted[str]
    zip_code: Extracted[str]
    irs_center: Extracted[str]
    is_ptp: Extracted[bool]


class CapitalAccount(BaseModel):
    """Part II item L, partner's capital account analysis.

    The form's arithmetic, which the rules engine checks, is:

    ending = beginning + contributed + current year net income
             + other increase (decrease) - withdrawals and distributions
    """

    model_config = ConfigDict(extra="forbid")

    beginning: Extracted[Decimal]
    contributed: Extracted[Decimal]
    current_year_net_income: Extracted[Decimal]
    other_increase_decrease: Extracted[Decimal]
    withdrawals: Extracted[Decimal]
    ending: Extracted[Decimal]


class PartII(BaseModel):
    """Part II, information about the partner."""

    model_config = ConfigDict(extra="forbid")

    tin: Extracted[str]
    name: Extracted[str]
    street: Extracted[str]
    city: Extracted[str]
    state: Extracted[str]
    zip_code: Extracted[str]
    is_general_partner: Extracted[bool]
    is_domestic: Extracted[bool]
    entity_type: Extracted[str]
    is_retirement_plan: Extracted[bool]
    profit_beginning: Extracted[Decimal]
    profit_ending: Extracted[Decimal]
    loss_beginning: Extracted[Decimal]
    loss_ending: Extracted[Decimal]
    capital_share_beginning: Extracted[Decimal]
    capital_share_ending: Extracted[Decimal]
    liability_nonrecourse: Extracted[Decimal]
    liability_qualified_nonrecourse: Extracted[Decimal]
    liability_recourse: Extracted[Decimal]
    capital_method: Extracted[str]
    capital: CapitalAccount
    contributed_builtin_gain: Extracted[bool]


class PartIII(BaseModel):
    """Part III boxes 1 through 21, practical scalar and coded lines.

    Boxes that are a single amount on the form are scalars. Boxes that take
    IRS codes (11, 13, 14, 15, 17, 18, 19, 20) are lists. Box 16 is the
    Schedule K-3 checkbox. Box 21 is foreign taxes paid or accrued.
    """

    model_config = ConfigDict(extra="forbid")

    ordinary_business_income: Extracted[Decimal]
    net_rental_real_estate: Extracted[Decimal]
    other_net_rental: Extracted[Decimal]
    guaranteed_payments_services: Extracted[Decimal]
    guaranteed_payments_capital: Extracted[Decimal]
    guaranteed_payments_total: Extracted[Decimal]
    interest_income: Extracted[Decimal]
    ordinary_dividends: Extracted[Decimal]
    qualified_dividends: Extracted[Decimal]
    dividend_equivalents: Extracted[Decimal]
    royalties: Extracted[Decimal]
    net_short_term_capital_gain: Extracted[Decimal]
    net_long_term_capital_gain: Extracted[Decimal]
    collectibles_gain: Extracted[Decimal]
    unrecaptured_1250_gain: Extracted[Decimal]
    net_section_1231_gain: Extracted[Decimal]
    other_income: list[CodedAmount] = Field(default_factory=list)
    section_179_deduction: Extracted[Decimal]
    other_deductions: list[CodedAmount] = Field(default_factory=list)
    self_employment: list[CodedAmount] = Field(default_factory=list)
    credits: list[CodedAmount] = Field(default_factory=list)
    schedule_k3_attached: Extracted[bool]
    amt_items: list[CodedAmount] = Field(default_factory=list)
    tax_exempt_and_nondeductible: list[CodedAmount] = Field(default_factory=list)
    distributions: list[CodedAmount] = Field(default_factory=list)
    other_information: list[CodedAmount] = Field(default_factory=list)
    foreign_taxes_paid: Extracted[Decimal]


class ScheduleK1(BaseModel):
    """One partner's Schedule K-1 (Form 1065).

    K1-Lens stores only synthetic documents. ``synthetic`` must stay true.
    """

    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(pattern=r"^K1-[A-Za-z0-9-]+$")
    tax_year: int | None = Field(default=None, ge=1990, le=2100)
    # None means the generator did not score this field. The extractor always sets it.
    tax_year_confidence: float | None = Field(default=None, ge=0, le=1)
    tax_year_extractor: str | None = None
    synthetic: bool = True
    variant: str = "unknown"
    layout_recognized: bool = True
    # 1-based pages whose OCR failed. Empty when OCR did not run or every page was read.
    ocr_failed_pages: list[int] = Field(default_factory=list)
    part_i: PartI
    part_ii: PartII
    part_iii: PartIII

    @field_validator("ocr_failed_pages")
    @classmethod
    def _ocr_pages_start_at_one(cls, pages: list[int]) -> list[int]:
        if any(page < 1 for page in pages):
            raise ValueError("OCR page numbers start at 1")
        return pages

    @model_validator(mode="after")
    def _synthetic_only(self) -> ScheduleK1:
        if not self.synthetic:
            raise ValueError("K1-Lens accepts synthetic documents only")
        return self

    @model_serializer(mode="wrap")
    def _omit_unscored_tax_year(self, handler: SerializerFunctionWrapHandler) -> object:
        """Leave generator JSON unchanged when optional scores were not set."""

        data = handler(self)
        if isinstance(data, dict):
            if data.get("tax_year_confidence") is None:
                data.pop("tax_year_confidence", None)
            if data.get("tax_year_extractor") is None:
                data.pop("tax_year_extractor", None)
            if data.get("ocr_failed_pages") in (None, []):
                data.pop("ocr_failed_pages", None)
        return data

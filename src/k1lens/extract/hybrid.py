"""Deterministic extraction, with a model only for numeric gaps.

The model is not called when every field is present and at or above the review
threshold on a recognized layout. With no API key and no injected client, this
returns the deterministic record and does not raise.

Identity fields are not taken from the model at any confidence. A numeric
proposal is stored only when that string appears in the field's own label
region, the rules value is missing, and the stored confidence stays under
the review threshold and at or below the model's own number. The
unrecognized-layout cap still applies. The LLM-only path stops on a
persistent 5xx, a timeout, or a malformed reply. This hybrid path keeps
the deterministic values in those cases.

A malformed model reply is retried once. If it is still unusable, this keeps
the deterministic values, logs the failure, and does not raise. A 5xx or a
timeout does the same. A 429 still stops the run after one retry.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

from k1lens.domain.access import UnknownFieldError, get_coded, get_extracted, kind_for_path
from k1lens.domain.fields import (
    CODED_BOXES,
    CODED_BY_PATH,
    LABEL_TAX_YEAR,
    REVIEW_THRESHOLD,
    SCALAR_FIELDS,
    FieldKind,
)
from k1lens.domain.models import CodedAmount, Extracted, ScheduleK1
from k1lens.extract.base import (
    ExtractionError,
    Extractor,
    MalformedReply,
    SpendCeilingExceeded,
    UnpricedModelError,
)
from k1lens.extract.confidence import below_review_threshold, clamp_unit
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.geometry import PlacedWord, value_in_label_region
from k1lens.extract.llm import (
    LLMExtractor,
    LlmUsage,
    SpendGuard,
    configured_provider,
)
from k1lens.extract.redact import redact_secrets
from k1lens.roster import ROSTER_IDENTITY_PATHS

logger = logging.getLogger(__name__)


@dataclass
class DocumentTrace:
    """One hybrid document, kept in memory for the live report."""

    document_id: str
    pages: int
    requested: tuple[str, ...]
    malformed: bool
    llm_calls: int
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    deterministic: ScheduleK1
    llm: ScheduleK1 | None
    final: ScheduleK1


class HybridExtractor:
    name = "hybrid"

    def __init__(
        self,
        client: httpx.Client | None = None,
        deterministic: Extractor | None = None,
        *,
        spend: SpendGuard | None = None,
        provider: str | None = None,
        vision: bool = False,
    ) -> None:
        self._client = client
        self._deterministic = (
            deterministic if deterministic is not None else DeterministicExtractor()
        )
        self._llm = LLMExtractor(client=client, spend=spend, provider=provider, vision=vision)
        self.usage: LlmUsage = self._llm.usage
        self.traces: list[DocumentTrace] = []

    def extract(self, pdf_path: Path, *, threshold: float = REVIEW_THRESHOLD) -> ScheduleK1:
        primary = self._deterministic.extract(pdf_path, threshold=threshold)
        before_calls = self._llm.usage.calls
        before_in = self._llm.usage.input_tokens
        before_out = self._llm.usage.output_tokens
        before_cost = self._llm.usage.estimated_cost_usd
        requested: tuple[str, ...] = ()
        malformed = False
        fallback: ScheduleK1 | None = None
        final = primary
        call = _can_call(self._client) and (
            not primary.layout_recognized or _has_gap(primary, threshold)
        )
        if call:
            requested = _gap_paths(primary, threshold)
            try:
                fallback = self._llm.extract_document(
                    pdf_path,
                    threshold=threshold,
                    apply_layout_cap=False,
                )
                final = _merge(
                    primary,
                    fallback,
                    threshold,
                    self._llm.last_page_words,
                )
            except MalformedReply as exc:
                logger.warning(
                    "LLM fallback failed for %s (%s). Keeping deterministic values.",
                    pdf_path.name,
                    redact_secrets(str(exc)),
                )
                malformed = True
            except (SpendCeilingExceeded, UnpricedModelError):
                raise
            except ExtractionError as exc:
                if not _keep_deterministic(exc):
                    raise
                logger.warning(
                    "LLM fallback failed for %s (%s). Keeping deterministic values.",
                    pdf_path.name,
                    redact_secrets(str(exc)),
                )
        self.traces.append(
            DocumentTrace(
                document_id=pdf_path.stem,
                pages=_page_count(pdf_path),
                requested=requested,
                malformed=malformed,
                llm_calls=self._llm.usage.calls - before_calls,
                input_tokens=self._llm.usage.input_tokens - before_in,
                output_tokens=self._llm.usage.output_tokens - before_out,
                estimated_cost_usd=_cost_delta(before_cost, self._llm.usage.estimated_cost_usd),
                deterministic=primary,
                llm=fallback,
                final=final,
            )
        )
        return final


def _keep_deterministic(exc: ExtractionError) -> bool:
    """A 5xx or a timeout keeps the deterministic record. A 429 does not."""

    text = str(exc)
    if "Timeout" in text:
        return True
    marker = "status "
    index = text.rfind(marker)
    if index < 0:
        return False
    digits: list[str] = []
    for char in text[index + len(marker) :]:
        if not char.isdigit():
            break
        digits.append(char)
    if not digits:
        return False
    code = int("".join(digits))
    return 500 <= code <= 599


def _can_call(client: httpx.Client | None) -> bool:
    if client is not None:
        return True
    return configured_provider() is not None


def _has_gap(document: ScheduleK1, threshold: float) -> bool:
    if document.tax_year is None or (document.tax_year_confidence or 0.0) < threshold:
        return True
    for spec in SCALAR_FIELDS:
        field = get_extracted(document, spec.path)
        if field.value is None or field.confidence < threshold:
            return True
    for box in CODED_BOXES:
        for item in get_coded(document, box.path):
            if item.amount.value is None or item.amount.confidence < threshold:
                return True
    return False


def _merge(
    primary: ScheduleK1,
    fallback: ScheduleK1,
    threshold: float,
    words: list[PlacedWord],
) -> ScheduleK1:
    """Fill missing numeric fields from the model. Identity stays with the rules."""

    data = primary.model_dump(mode="json")
    fill_missing = not primary.layout_recognized
    _merge_year(data, primary, fallback, threshold, words)
    for spec in SCALAR_FIELDS:
        accepted = _accepted(
            get_extracted(primary, spec.path),
            get_extracted(fallback, spec.path),
            path=spec.path,
            label=spec.pdf_label,
            words=words,
            threshold=threshold,
        )
        if accepted is not None:
            _assign(data, spec.path, accepted.model_dump(mode="json"))
    for box in CODED_BOXES:
        merged = _merge_coded(
            get_coded(primary, box.path),
            get_coded(fallback, box.path),
            threshold,
            fill_missing=fill_missing,
            words=words,
            path=box.path,
        )
        _assign(data, box.path, merged)
    return ScheduleK1.model_validate(data)


def _merge_year(
    data: dict[str, Any],
    primary: ScheduleK1,
    fallback: ScheduleK1,
    threshold: float,
    words: list[PlacedWord],
) -> None:
    if fallback.tax_year is None:
        return
    if not _is_gap(primary.tax_year, primary.tax_year_confidence or 0.0, threshold):
        return
    if primary.tax_year is not None and primary.tax_year == fallback.tax_year:
        return
    # A different year is not agreement. Keep the rules year and its finding.
    if primary.tax_year is not None:
        return
    confidence = min(fallback.tax_year_confidence or 0.0, below_review_threshold(threshold))
    grounded = value_in_label_region(LABEL_TAX_YEAR, str(fallback.tax_year), words)
    if not grounded:
        return
    data["tax_year"] = fallback.tax_year
    data["tax_year_confidence"] = confidence
    data["tax_year_extractor"] = fallback.tax_year_extractor


def _is_gap(value: object, confidence: float, threshold: float) -> bool:
    return value is None or confidence < threshold


def _accepted(
    current: Extracted[Any],
    other: Extracted[Any],
    *,
    path: str,
    label: str,
    words: list[PlacedWord],
    threshold: float,
) -> Extracted[Any] | None:
    """A missing numeric model value in this label's region, or None.

    Identity is never taken from the model. A value the rules already stored
    stays, even when its confidence is low. Outside the label region the
    model value is not on the page there, so it is not stored.
    """

    if path in ROSTER_IDENTITY_PATHS:
        return None
    try:
        kind = kind_for_path(path)
    except UnknownFieldError:
        return None
    if kind not in {FieldKind.MONEY, FieldKind.PERCENT}:
        return None
    if current.value is not None or other.value is None:
        return None
    if not _is_gap(current.value, current.confidence, threshold):
        return None
    text = _as_text(other.value)
    if text == "":
        return None
    if not value_in_label_region(label, text, words):
        return None
    reported = _finite_confidence(other.confidence)
    if reported is None:
        return None
    capped = min(reported, below_review_threshold(threshold))
    return other.model_copy(update={"confidence": capped, "provenance": other.provenance})


def _finite_confidence(value: float) -> float | None:
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return clamp_unit(value)


def _as_text(value: object) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _merge_coded(
    primary: list[CodedAmount],
    fallback: list[CodedAmount],
    threshold: float,
    *,
    fill_missing: bool,
    words: list[PlacedWord],
    path: str,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = [item.model_dump(mode="json") for item in primary]
    consumed: set[int] = set()
    for index, item in enumerate(primary):
        if not _is_gap(item.amount.value, item.amount.confidence, threshold):
            continue
        match_at = _next_coded(fallback, item.code, consumed)
        if match_at is None:
            continue
        accepted = _accepted(
            item.amount,
            fallback[match_at].amount,
            path=f"{path}[{item.code}]",
            label=f"{CODED_BY_PATH[path].pdf_prefix} {item.code}",
            words=words,
            threshold=threshold,
        )
        if accepted is None:
            continue
        result[index] = (
            fallback[match_at].model_copy(update={"amount": accepted}).model_dump(mode="json")
        )
    if fill_missing:
        present = {item.code for item in primary}
        for pos, item in enumerate(fallback):
            if pos in consumed or item.code in present or item.amount.value is None:
                continue
            amount = item.amount
            label = f"{CODED_BY_PATH[path].pdf_prefix} {item.code}"
            if not value_in_label_region(label, _as_text(amount.value), words):
                continue
            capped = min(float(amount.confidence), below_review_threshold(threshold))
            stored = item.model_copy(
                update={"amount": amount.model_copy(update={"confidence": capped})}
            )
            result.append(stored.model_dump(mode="json"))
            present.add(item.code)
    return result


def _next_coded(fallback: list[CodedAmount], code: str, consumed: set[int]) -> int | None:
    for index, item in enumerate(fallback):
        if index in consumed or item.code != code:
            continue
        consumed.add(index)
        return index
    return None


def _gap_paths(document: ScheduleK1, threshold: float) -> tuple[str, ...]:
    paths: list[str] = []
    if _is_gap(document.tax_year, document.tax_year_confidence or 0.0, threshold):
        paths.append("tax_year")
    for spec in SCALAR_FIELDS:
        field = get_extracted(document, spec.path)
        if _is_gap(field.value, field.confidence, threshold):
            paths.append(spec.path)
    for box in CODED_BOXES:
        counts: dict[str, int] = {}
        for item in get_coded(document, box.path):
            counts[item.code] = counts.get(item.code, 0) + 1
            key = f"{box.path}[{item.code}]"
            if counts[item.code] > 1:
                key = f"{key}#{counts[item.code]}"
            if _is_gap(item.amount.value, item.amount.confidence, threshold):
                paths.append(key)
    return tuple(paths)


def _page_count(pdf_path: Path) -> int:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(str(pdf_path))
    try:
        return max(len(pdf), 1)
    finally:
        pdf.close()


def _cost_delta(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return after - before


def _assign(data: dict[str, Any], path: str, value: object) -> None:
    node: Any = data
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value

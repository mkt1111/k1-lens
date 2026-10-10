"""Optional LLM backend. Skipped cleanly when no API key is configured.

The model is asked for JSON keyed by the same labels the deterministic parser
uses. Responses are validated before they become a Schedule K-1. Tests inject
an httpx client; nothing in the default path calls the network.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from k1lens.domain.fields import CODED_BOXES, REVIEW_THRESHOLD, SCALAR_BY_LABEL, SCALAR_FIELDS
from k1lens.domain.models import ScheduleK1
from k1lens.extract.assemble import assemble, has_field_labels
from k1lens.extract.base import (
    ExtractionError,
    LLMNotConfiguredError,
    MalformedReply,
    SpendCeilingExceeded,
    UnpricedModelError,
)
from k1lens.extract.confidence import LABEL_EXACT, clamp_unit
from k1lens.extract.geometry import PlacedWord, page_words, value_in_label_region
from k1lens.extract.labels import canonicalize_observed
from k1lens.extract.ocr import ocr_enabled, ocr_plain_text, read_ocr, render_pages
from k1lens.extract.redact import install_secret_redaction, redact_secrets
from k1lens.extract.text import (
    Observed,
    UnreadablePdf,
    iter_labeled_lines,
    plain_text,
    read_observed,
)

logger = logging.getLogger(__name__)

DEFAULT_OPENAI_MODEL = "gpt-4o-mini"
DEFAULT_SPEND_CEILING_USD = 3.0
# Above the published low-detail image token count for gpt-4o-mini, so the
# pre-call check does not under-budget a page image.
LOW_DETAIL_IMAGE_TOKENS = 3000
MAX_OUTPUT_TOKENS = 4096

_SYSTEM = (
    "You extract fields from a synthetic IRS Schedule K-1 (Form 1065) facsimile. "
    "Return only JSON with a fields array. Each item has label, value, and confidence. "
    "Use the label strings exactly. Copy values from the text. Use null when a label is absent. "
    "Do not invent taxpayer data. The document is synthetic."
)

# Strict structured output. OpenAI requires every property to be required and
# additionalProperties false. The parser also accepts the older label map.
_OPENAI_FIELD_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": ["string", "null"]},
                    "confidence": {"type": ["number", "null"]},
                },
                "required": ["label", "value", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["fields"],
    "additionalProperties": False,
}


class LlmFieldIn(BaseModel):
    model_config = ConfigDict(extra="ignore")

    value: str | int | float | bool | None = None
    confidence: float | None = None


class LlmDocumentIn(BaseModel):
    """Model reply. ``fields`` may be a label map or the structured-output rows."""

    model_config = ConfigDict(extra="ignore")

    fields: dict[str, LlmFieldIn] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _rows_to_map(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        rows = data.get("fields")
        if not isinstance(rows, list):
            return data
        mapped: dict[str, object] = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("label"), str):
                raise ValueError("each field row needs a string label")
            mapped[row["label"]] = {"value": row.get("value"), "confidence": row.get("confidence")}
        return {**data, "fields": mapped}


# USD per 1,000,000 tokens. Published list prices, used only as an estimate.
# An unlisted model leaves the cost unset. This is not an invoice.
# gpt-4o-mini: text and image input, OpenAI list price $0.15 / $0.60.
_LIST_PRICE_PER_MILLION: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "claude-sonnet-4-5": (3.00, 15.00),
}


class SpendGuard:
    """Stop before a call whose conservative estimate would pass the ceiling."""

    def __init__(self, ceiling_usd: float) -> None:
        if not math.isfinite(ceiling_usd):
            raise ValueError("Spend ceiling must be a finite number greater than zero")
        if ceiling_usd <= 0:
            raise ValueError("Spend ceiling must be positive")
        self.ceiling_usd = ceiling_usd
        self.spent_usd = 0.0

    def allow(self, estimate_usd: float) -> None:
        if self.spent_usd + estimate_usd > self.ceiling_usd + 1e-9:
            raise SpendCeilingExceeded(self.spent_usd, self.ceiling_usd)

    def add(self, actual_usd: float) -> None:
        self.spent_usd += actual_usd


@dataclass
class LlmUsage:
    """Token counts from model responses. Cost is a list-price estimate."""

    calls: int = 0
    malformed_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_seconds: float = 0.0
    estimated_cost_usd: float | None = 0.0

    def record(
        self, *, model: str, input_tokens: int, output_tokens: int, latency_seconds: float
    ) -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.latency_seconds += latency_seconds
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        if cost is None or self.estimated_cost_usd is None:
            self.estimated_cost_usd = None
            return
        self.estimated_cost_usd += cost


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """Return a list-price estimate, or None when ``model`` is not priced here."""

    rates = _rates_for(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    return (input_tokens * input_rate + output_tokens * output_rate) / 1_000_000


def estimate_request_usd(model: str, text: str, image_count: int) -> float | None:
    """Upper bound used before a call. Output is capped at ``MAX_OUTPUT_TOKENS``."""

    rates = _rates_for(model)
    if rates is None:
        return None
    input_rate, output_rate = rates
    input_tokens = max(len(text) // 4, 1) + 500 + image_count * LOW_DETAIL_IMAGE_TOKENS
    return (input_tokens * input_rate + MAX_OUTPUT_TOKENS * output_rate) / 1_000_000


def _rates_for(model: str) -> tuple[float, float] | None:
    for name, rates in _LIST_PRICE_PER_MILLION.items():
        if model == name or model.startswith(f"{name}-"):
            return rates
    return None


class LLMExtractor:
    name = "llm"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        spend: SpendGuard | None = None,
        provider: str | None = None,
        vision: bool = False,
    ) -> None:
        self._client = client
        self._spend = spend
        self._provider = provider
        self._vision = vision
        self.usage = LlmUsage()
        self.last_page_text = ""
        self.last_page_words: list[PlacedWord] = []

    def extract(self, pdf_path: Path, *, threshold: float = REVIEW_THRESHOLD) -> ScheduleK1:
        return self.extract_document(pdf_path, threshold=threshold, apply_layout_cap=True)

    def extract_document(
        self,
        pdf_path: Path,
        *,
        threshold: float = REVIEW_THRESHOLD,
        apply_layout_cap: bool = True,
        vision: bool | None = None,
    ) -> ScheduleK1:
        provider = _provider_for_call(self._client, forced=self._provider)
        if provider is None:
            raise LLMNotConfiguredError(
                "LLM backend skipped: set OPENAI_API_KEY or ANTHROPIC_API_KEY. "
                "The deterministic backend does not need a key."
            )
        use_vision = self._vision if vision is None else vision
        try:
            text_layer = plain_text(pdf_path)
        except UnreadablePdf:
            return assemble(
                pdf_path.stem,
                {},
                extractor=self.name,
                threshold=threshold,
                ocr_failed_pages=(1,),
            )
        text = text_layer
        images: list[str] = []
        ocr_failed: tuple[int, ...] = ()
        if text_layer.strip() == "" and ocr_enabled():
            ocr = read_ocr(pdf_path)
            if ocr is not None:
                text = ocr_plain_text(ocr) or ""
                ocr_failed = ocr.failed_pages
        self.last_page_text = text
        self.last_page_words = page_words(pdf_path)
        if use_vision and text_layer.strip() == "":
            images = _jpeg_data_urls(pdf_path)
        if text.strip() == "" and not images:
            return assemble(
                pdf_path.stem,
                {},
                extractor=self.name,
                threshold=threshold,
                ocr_failed_pages=ocr_failed,
            )
        payload = self._complete_with_retry(provider, text, images, pdf_path)
        observed = _observed_from_payload(payload, self.last_page_words)
        try:
            layout_source = read_observed(pdf_path, extractor=self.name)
        except UnreadablePdf:
            layout_source = {}
        if not has_field_labels(layout_source) and text.strip():
            for label, rows in _page_observations(text).items():
                layout_source.setdefault(label, []).extend(rows)
        _page, layout_stats = canonicalize_observed(layout_source)
        return assemble(
            pdf_path.stem,
            observed,
            extractor=self.name,
            layout_stats=layout_stats,
            threshold=threshold,
            apply_layout_cap=apply_layout_cap,
            ocr_failed_pages=ocr_failed,
        )

    def _complete_with_retry(
        self, provider: str, text: str, images: list[str], pdf_path: Path
    ) -> LlmDocumentIn:
        """Call the model. A malformed reply is tried once more, then raised."""

        last: MalformedReply | None = None
        for attempt in (1, 2):
            try:
                return self._complete(provider, text, images)
            except MalformedReply as exc:
                self.usage.malformed_calls += 1
                last = exc
                logger.warning(
                    "Malformed LLM reply for %s on attempt %s: %s",
                    pdf_path.name,
                    attempt,
                    redact_secrets(str(exc)),
                )
        assert last is not None
        raise last

    def _complete(self, provider: str, text: str, images: list[str]) -> LlmDocumentIn:
        install_secret_redaction()
        client = self._client or httpx.Client(timeout=120.0)
        owns_client = self._client is None
        try:
            response, content, model, started = self._exchange(client, provider, text, images)
        finally:
            if owns_client:
                client.close()
        elapsed = time.perf_counter() - started
        body = _json_body(response)
        input_tokens, output_tokens = _token_counts(provider, body)
        self.usage.record(
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_seconds=elapsed,
        )
        if self._spend is not None:
            actual = estimate_cost_usd(model, input_tokens, output_tokens)
            self._spend.add(0.0 if actual is None else actual)
        return _parse_content(content)

    def _exchange(
        self, client: httpx.Client, provider: str, text: str, images: list[str]
    ) -> tuple[httpx.Response, str, str, float]:
        """Post once. A 429 or 5xx is tried once more, then raised with its status."""

        try:
            return self._once(client, provider, text, images)
        except ExtractionError as exc:
            status = _transient_status(exc)
            if status is None:
                raise
            logger.warning("Transient LLM status %s; retrying once", status)
        return self._once(client, provider, text, images)

    def _once(
        self, client: httpx.Client, provider: str, text: str, images: list[str]
    ) -> tuple[httpx.Response, str, str, float]:
        started = time.perf_counter()
        sent_model: list[str] = []
        try:
            response, content = self._post(client, provider, text, images, sent_model)
        except ExtractionError:
            if sent_model:
                self._charge_estimate(sent_model[0], text, len(images))
            raise
        except httpx.HTTPError as exc:
            name = type(exc).__name__
            raise ExtractionError(f"LLM request failed ({name})") from None
        return response, content, sent_model[0], started

    def _post(
        self,
        client: httpx.Client,
        provider: str,
        text: str,
        images: list[str],
        sent_model: list[str],
    ) -> tuple[httpx.Response, str]:
        if provider == "openai":
            request_body = _openai_body(text, images)
            model = str(request_body["model"])
            self._reserve(model, text, len(images))
            response = client.post(
                _openai_url(),
                headers={
                    "Authorization": f"Bearer {os.environ.get('OPENAI_API_KEY', '')}",
                    "Content-Type": "application/json",
                },
                json=request_body,
            )
            sent_model.append(model)
            self.usage.calls += 1
            return response, _openai_content(response)
        request_body = _anthropic_body(text)
        model = str(request_body["model"])
        self._reserve(model, text, 0)
        response = client.post(
            _anthropic_url(),
            headers={
                "x-api-key": os.environ.get("ANTHROPIC_API_KEY", ""),
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json=request_body,
        )
        sent_model.append(model)
        self.usage.calls += 1
        return response, _anthropic_content(response)

    def _reserve(self, model: str, text: str, image_count: int) -> None:
        if self._spend is None:
            return
        estimate = estimate_request_usd(model, text, image_count)
        if estimate is None:
            raise UnpricedModelError(model)
        self._spend.allow(estimate)

    def _charge_estimate(self, model: str, text: str, image_count: int) -> None:
        if self._spend is None:
            return
        estimate = estimate_request_usd(model, text, image_count)
        if estimate is not None:
            self._spend.add(estimate)


def configured_provider() -> str | None:
    requested = os.environ.get("K1LENS_LLM_PROVIDER", "").strip().lower()
    openai_key = os.environ.get("OPENAI_API_KEY", "").strip()
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if requested == "openai":
        return "openai" if openai_key else None
    if requested == "anthropic":
        return "anthropic" if anthropic_key else None
    if requested != "":
        return None
    if openai_key:
        return "openai"
    if anthropic_key:
        return "anthropic"
    return None


def llm_configured() -> bool:
    return configured_provider() is not None


def _provider_for_call(client: httpx.Client | None, *, forced: str | None = None) -> str | None:
    """Provider for a request.

    An injected client is a recorded response. It may run without an API key.
    A live call still needs a configured provider. ``forced`` is how ``--live``
    selects OpenAI when that is the only key set.
    """

    if forced in {"openai", "anthropic"}:
        if forced == "openai" and os.environ.get("OPENAI_API_KEY", "").strip():
            return "openai"
        if forced == "anthropic" and os.environ.get("ANTHROPIC_API_KEY", "").strip():
            return "anthropic"
        if client is not None:
            return forced
        return None
    provider = configured_provider()
    if provider is not None:
        return provider
    if client is None:
        return None
    requested = os.environ.get("K1LENS_LLM_PROVIDER", "").strip().lower()
    if requested in {"openai", "anthropic"}:
        return requested
    return "openai"


def _token_counts(provider: str, body: object) -> tuple[int, int]:
    if not isinstance(body, dict):
        return 0, 0
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return 0, 0
    if provider == "openai":
        return _as_int(usage.get("prompt_tokens")), _as_int(usage.get("completion_tokens"))
    return _as_int(usage.get("input_tokens")), _as_int(usage.get("output_tokens"))


def _as_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0
    return int(value)


def _openai_url() -> str:
    base = os.environ.get("K1LENS_OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    return f"{base}/chat/completions"


def _anthropic_url() -> str:
    base = os.environ.get("K1LENS_ANTHROPIC_BASE_URL", "https://api.anthropic.com/v1").rstrip("/")
    return f"{base}/messages"


_CODE_HINTS: dict[str, str] = {
    "11 Other income": "A, B, C, E, F",
    "13 Other deductions": "A, B, H, I, W",
    "14 Self-employment": "A, C",
    "15 Credits": "A, C, P",
    "17 AMT items": "A, B, C",
    "18 Tax-exempt income": "A, B, C",
    "19 Distributions": "A, C",
    "20 Other information": "A, B, N, V, Z",
}


def _prompt(text: str) -> str:
    labels = [spec.pdf_label for spec in SCALAR_FIELDS]
    labels.extend(
        f"{spec.pdf_prefix} <code>  codes {_CODE_HINTS[spec.pdf_prefix]}" for spec in CODED_BOXES
    )
    listing = "\n".join(f"- {label}" for label in labels)
    return (
        "Labels:\n"
        f"{listing}\n\n"
        "Coded boxes can carry more than one letter. Emit one field per code that "
        "appears, using the prefix plus the code, for example '11 Other income B'. "
        "Do not invent code A when another code is printed.\n\n"
        f"Document text:\n{text}"
    )


def _openai_body(text: str, images: list[str] | None = None) -> dict[str, Any]:
    user: str | list[dict[str, Any]]
    if images:
        user = [{"type": "text", "text": _prompt(text)}]
        user.extend(
            {
                "type": "image_url",
                "image_url": {"url": url, "detail": "low"},
            }
            for url in images
        )
    else:
        user = _prompt(text)
    return {
        "model": os.environ.get("K1LENS_OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
        "temperature": 0,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "schedule_k1_fields",
                "strict": True,
                "schema": _OPENAI_FIELD_SCHEMA,
            },
        },
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {"role": "user", "content": user},
        ],
    }


def _anthropic_body(text: str) -> dict[str, Any]:
    return {
        "model": os.environ.get("K1LENS_ANTHROPIC_MODEL", "claude-sonnet-4-5"),
        "max_tokens": 8000,
        "temperature": 0,
        "system": _SYSTEM,
        "messages": [{"role": "user", "content": _prompt(text)}],
    }


def _openai_content(response: httpx.Response) -> str:
    _raise_for_status(response)
    body = _json_body(response)
    try:
        content = body["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MalformedReply("OpenAI response did not include message content") from exc
    if not isinstance(content, str):
        raise MalformedReply("OpenAI message content was not text")
    return content


def _anthropic_content(response: httpx.Response) -> str:
    _raise_for_status(response)
    body = _json_body(response)
    try:
        blocks = body["content"]
        text = blocks[0]["text"]
    except (KeyError, IndexError, TypeError) as exc:
        raise MalformedReply("Anthropic response did not include text content") from exc
    if not isinstance(text, str):
        raise MalformedReply("Anthropic content was not text")
    return text


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError:
        raise ExtractionError(f"LLM request failed with status {response.status_code}") from None


def _json_body(response: httpx.Response) -> Any:
    try:
        return response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise MalformedReply("LLM response was not valid JSON") from exc


def _transient_status(exc: ExtractionError) -> int | None:
    """A 429 or 5xx can be tried once more. Other failures stop immediately."""

    if isinstance(
        exc, (MalformedReply, SpendCeilingExceeded, UnpricedModelError, LLMNotConfiguredError)
    ):
        return None
    marker = "status "
    index = str(exc).rfind(marker)
    if index < 0:
        return None
    digits: list[str] = []
    for char in str(exc)[index + len(marker) :]:
        if not char.isdigit():
            break
        digits.append(char)
    if not digits:
        return None
    code = int("".join(digits))
    if code == 429 or 500 <= code <= 599:
        return code
    return None


def _parse_content(content: str) -> LlmDocumentIn:
    payload = _json_object(content)
    try:
        return LlmDocumentIn.model_validate(payload)
    except ValidationError as exc:
        raise MalformedReply("LLM JSON did not match the expected shape") from exc


def _json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise MalformedReply("LLM response did not contain JSON")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise MalformedReply("LLM response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise MalformedReply("LLM JSON root was not an object")
    return parsed


def _observed_from_payload(
    payload: LlmDocumentIn, words: list[PlacedWord]
) -> dict[str, list[Observed]]:
    observed: dict[str, list[Observed]] = {}
    for label, field in payload.fields.items():
        coerced = _coerce(field.value)
        if coerced is None:
            continue
        reported = _model_confidence(field.confidence)
        if reported is None:
            continue
        known = label in SCALAR_BY_LABEL or _is_coded_prompt_label(label)
        observed[label] = [
            Observed(
                raw=coerced,
                page=None,
                bbox=None,
                extractor="llm",
                label_score=LABEL_EXACT if known else 0.0,
                reported_confidence=reported,
                grounded=value_in_label_region(label, coerced, words),
            )
        ]
    return observed


def _model_confidence(value: float | None) -> float | None:
    """Clamp a finite model score into 0..1. A non-finite score is rejected."""

    if value is None:
        return 0.5
    if value != value or value in {float("inf"), float("-inf")}:
        return None
    return clamp_unit(value)


def _page_observations(text: str) -> dict[str, list[Observed]]:
    grouped: dict[str, list[Observed]] = {}
    for label, raw in iter_labeled_lines(text):
        grouped.setdefault(label, []).append(
            Observed(raw=raw, page=None, bbox=None, extractor="llm", label_score=1.0)
        )
    return grouped


def _is_coded_prompt_label(label: str) -> bool:
    for box in CODED_BOXES:
        prefix = f"{box.pdf_prefix} "
        if not label.startswith(prefix):
            continue
        code = label[len(prefix) :].strip()
        return code.isalpha() and 1 <= len(code) <= 2
    return False


def _coerce(value: str | int | float | bool | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, int):
        return str(value)
    return format(value, "f")


def _jpeg_data_urls(pdf_path: Path) -> list[str]:
    """Low-detail page images. The model name is vision-capable; detail stays low."""

    import base64
    import io

    urls: list[str] = []
    for image in render_pages(pdf_path):
        image.thumbnail((1024, 1024))
        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=60)
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
        urls.append(f"data:image/jpeg;base64,{encoded}")
    return urls

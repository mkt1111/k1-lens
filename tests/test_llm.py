"""LLM backend with recorded HTTP responses. No live API calls."""

import json
from pathlib import Path

import httpx
import pytest

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.blank import blank_schedule
from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import ScheduleK1
from k1lens.eval.harness import evaluate
from k1lens.extract.assemble import assemble
from k1lens.extract.base import ExtractionError, LLMNotConfiguredError, MalformedReply
from k1lens.extract.confidence import LLM_ONLY_CONFIDENCE_CAP, llm_only_confidence_cap
from k1lens.extract.labels import LayoutStats
from k1lens.extract.llm import LLMExtractor, configured_provider
from k1lens.extract.ocr import OcrRead
from k1lens.extract.text import Observed, parse_lines, plain_text
from k1lens.generate.build import Variant
from k1lens.generate.corpus import (
    GENERATOR_VERSION,
    GroundTruthFile,
    Manifest,
    ManifestDocument,
    generate_corpus,
)
from k1lens.roster import ROSTER_IDENTITY_PATHS


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "K1LENS_LLM_PROVIDER",
        "K1LENS_OPENAI_BASE_URL",
        "K1LENS_ANTHROPIC_BASE_URL",
        "K1LENS_OPENAI_MODEL",
        "K1LENS_ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _pdf(tmp_path: Path, variant: Variant = Variant.CLEAN) -> Path:
    dest = tmp_path / "llm"
    generate_corpus(dest, seed=8, count=1, plan=(variant,))
    return dest / "K1-0001.pdf"


def test_skips_when_no_key_is_set(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    with pytest.raises(LLMNotConfiguredError, match="skipped"):
        LLMExtractor().extract(_pdf(tmp_path))


def test_openai_recorded_response(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("K1LENS_OPENAI_MODEL", "gpt-test")
    seen: dict[str, object] = {}

    pdf = _pdf(tmp_path)
    page = parse_lines(plain_text(pdf))

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("Authorization")
        body = json.loads(request.content.decode())
        seen["model"] = body["model"]
        seen["response_format"] = body["response_format"]
        content = body["messages"][1]["content"]
        assert "A Partnership EIN" in content
        assert "11 Other income <code>  codes A, B, C, E, F" in content
        payload = {
            "fields": {
                "A Partnership EIN": {"value": page["A Partnership EIN"], "confidence": 0.99},
                "B Partnership name": {"value": "SAMPLE Not On The Page LP", "confidence": 1.0},
                "D PTP": {"value": False, "confidence": 0.5},
                "1 Ordinary business income": {"value": 1500, "confidence": None},
                "5 Interest income": {"value": "999999.00", "confidence": 1.0},
                "TAX YEAR": {"value": page.get("TAX YEAR", "2023"), "confidence": 0.9},
            }
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    document = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        pdf
    )
    assert seen["auth"] == "Bearer test-key"
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["model"] == "gpt-test"
    response_format = seen["response_format"]
    assert isinstance(response_format, dict)
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"]["properties"]["fields"]["type"] == "array"
    assert document.part_i.ein.value == page["A Partnership EIN"]
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD
    assert document.part_i.name.value == "SAMPLE Not On The Page LP"
    assert document.part_i.name.confidence < REVIEW_THRESHOLD
    assert document.part_iii.interest_income.confidence < REVIEW_THRESHOLD
    assert document.part_i.is_ptp.value is False
    assert document.part_iii.ordinary_business_income.value == pytest.approx(1500)
    assert document.synthetic is True


def test_recorded_anthropic_fenced_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    monkeypatch.setenv("K1LENS_ANTHROPIC_BASE_URL", "https://example.test/v1")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["x-api-key"] == "anthropic-test"
        assert request.url.host == "example.test"
        payload = (
            '{"fields": {"F Partner name": {"value": "SAMPLE Jules Moreau", "confidence": 0.7}}}'
        )
        text = f"```json\n{payload}\n```"
        return httpx.Response(200, json={"content": [{"type": "text", "text": text}]})

    document = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        _pdf(tmp_path)
    )
    assert document.part_ii.name.value == "SAMPLE Jules Moreau"


def test_recorded_raster_without_text_does_not_call_the_api(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "0")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    document = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        _pdf(tmp_path, Variant.RASTERIZED)
    )
    assert document.part_i.ein.value is None


def test_recorded_response_sends_ocr_text_when_the_page_has_no_text_layer(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "1")
    monkeypatch.setattr(
        "k1lens.extract.llm.read_ocr",
        lambda path: OcrRead(
            fields={"A Partnership EIN": [Observed("00-0000009", 1, None, "ocr")]},
            failed_pages=(),
        ),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"00-0000009" in request.content
        body = '{"fields": {"A Partnership EIN": {"value": "00-0000009", "confidence": 0.4}}}'
        return httpx.Response(200, json={"choices": [{"message": {"content": body}}]})

    document = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        _pdf(tmp_path, Variant.RASTERIZED)
    )
    assert document.part_i.ein.value == "00-0000009"


def test_a_non_utf8_body_is_a_malformed_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(200, content=b"\xff\xfe not text")

    with pytest.raises(ExtractionError, match="JSON"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
            _pdf(tmp_path)
        )
    assert calls["n"] == 2


def test_recorded_http_error_and_bad_json(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)

    def failed(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "nope"})

    with pytest.raises(ExtractionError, match="status 500"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(failed))).extract(pdf)

    def bad(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    with pytest.raises(ExtractionError, match="JSON"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(bad))).extract(pdf)

    def wrong_shape(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": "[1, 2]"}}]})

    with pytest.raises(ExtractionError):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(wrong_shape))).extract(pdf)

    def missing_content(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    with pytest.raises(ExtractionError, match="content"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(missing_content))).extract(
            pdf
        )


def test_recorded_anthropic_missing_content(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "k")
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "anthropic")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"content": []})

    with pytest.raises(ExtractionError, match="Anthropic"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
            _pdf(tmp_path)
        )


def test_provider_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    _clear(monkeypatch)
    assert configured_provider() is None
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "b")
    assert configured_provider() == "openai"
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "anthropic")
    assert configured_provider() == "anthropic"
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY")
    assert configured_provider() is None
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "other")
    monkeypatch.setenv("OPENAI_API_KEY", "a")
    assert configured_provider() is None


def test_recorded_anthropic_usage_is_priced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test")
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("K1LENS_ANTHROPIC_MODEL", "claude-sonnet-4-5")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": '{"fields": {}}'}],
                "usage": {"input_tokens": 2000, "output_tokens": 50},
            },
        )

    extractor = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler)))
    extractor.extract(_pdf(tmp_path))
    assert extractor.usage.calls == 1
    assert extractor.usage.input_tokens == 2000
    assert extractor.usage.output_tokens == 50
    assert extractor.usage.estimated_cost_usd == pytest.approx(
        2000 * 3.00 / 1_000_000 + 50 * 15.00 / 1_000_000
    )


def test_recorded_unpriced_model_leaves_cost_unset(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("K1LENS_OPENAI_MODEL", "gpt-test")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"fields": {}}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 4},
            },
        )

    extractor = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler)))
    extractor.extract(_pdf(tmp_path))
    assert extractor.usage.input_tokens == 10
    assert extractor.usage.estimated_cost_usd is None


def test_transient_status_is_retried_once(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        if calls == 1:
            return httpx.Response(429, json={"error": "slow"})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"fields": {}}'}}]})

    extractor = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler)))
    extractor.extract(_pdf(tmp_path))
    assert calls == 2
    assert extractor.usage.calls == 2


def test_a_persistent_5xx_stops_with_the_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(503, json={"error": "down"})

    with pytest.raises(ExtractionError, match="status 503"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
            _pdf(tmp_path)
        )
    assert calls == 2


def test_a_client_error_is_not_retried(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(400, json={"error": "bad"})

    with pytest.raises(ExtractionError, match="status 400"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
            _pdf(tmp_path)
        )
    assert calls == 1


def test_strict_array_reply_is_parsed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen.canvas import Canvas

    from k1lens.domain.fields import SCALAR_FIELDS

    labels = {spec.path: spec.pdf_label for spec in SCALAR_FIELDS}
    pdf = tmp_path / "array.pdf"
    canvas = Canvas(str(pdf), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 9)
    rows = [
        f"{labels['part_i.ein']}: 00-0000001",
        f"{labels['part_i.street']}: 100 Main St",
        f"{labels['part_i.state']}: CA",
        f"{labels['part_i.zip_code']}: 94105",
        f"{labels['part_ii.tin']}: 000-00-0001",
        f"{labels['part_ii.street']}: 200 Oak Ave",
        f"{labels['part_ii.state']}: NY",
        f"{labels['part_ii.zip_code']}: 10001",
    ]
    y = 740
    for row in rows:
        canvas.drawString(40, y, row)
        y -= 14
    canvas.save()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        payload = {
            "fields": [{"label": "A Partnership EIN", "value": "00-0000001", "confidence": 0.95}]
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    document = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        pdf
    )
    assert calls["n"] == 1
    assert document.part_i.ein.value == "00-0000001"
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD


def test_a_non_json_200_is_a_malformed_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(200, content=b"<html>nope</html>")

    with pytest.raises(MalformedReply, match="not valid JSON"):
        LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
            _pdf(tmp_path)
        )
    assert calls == 2


_ANCHORS = (
    "TAX YEAR: 2024",
    "A Partnership EIN: 00-0000001",
    "B Partnership name: SAMPLE Northwind Partners LP",
    "E Partner TIN: 000-00-0001",
    "F Partner name: SAMPLE Jules Moreau",
    "1 Ordinary business income: 10.00",
)


def _draw(path: Path, rows: list[str]) -> None:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 9)
    y = 740
    for row in rows:
        canvas.drawString(40, y, row)
        y -= 16
    canvas.save()


def _reply(fields: dict[str, object]) -> httpx.Response:
    payload = {"fields": fields}
    return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(payload)}}]})


def _llm(pdf: Path, fields: dict[str, object]) -> ScheduleK1:
    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply(fields)

    return LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(pdf)


def test_both_option_words_at_model_confidence_one_stay_under_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The page prints Yes and No and marks Yes. The model picks No at 1.0.

    Both words sit in the label region, so the unmarked word is grounded.
    Llm mode still stores it under 0.80.
    """

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = tmp_path / "both.pdf"
    _draw(pdf, [*_ANCHORS, "D PTP: Yes X No"])
    document = _llm(pdf, {"D PTP": {"value": False, "confidence": 1.0}})
    field = document.part_i.is_ptp
    assert document.layout_recognized is True
    assert field.value is False
    assert field.provenance.own_region is False
    assert field.provenance.extractor == "llm"
    assert field.confidence == LLM_ONLY_CONFIDENCE_CAP
    assert field.confidence < REVIEW_THRESHOLD


@pytest.mark.parametrize(
    ("kind", "label", "text", "path"),
    [
        ("money", "5 Interest income", "1500.00", "part_iii.interest_income"),
        ("percent", "J Profit beginning pct", "25.00", "part_ii.profit_beginning"),
        ("bool", "D PTP", "Yes", "part_i.is_ptp"),
        ("string", "I1 Entity type", "Individual", "part_ii.entity_type"),
        ("coded", "11 Other income A", "100.00", "part_iii.other_income"),
    ],
    ids=["money", "percent", "bool", "string", "coded"],
)
def test_in_region_llm_value_at_confidence_one_stays_under_review(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    kind: str,
    label: str,
    text: str,
    path: str,
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = tmp_path / f"{kind}.pdf"
    _draw(pdf, [*_ANCHORS, f"{label}: {text}"])
    document = _llm(pdf, {label: {"value": text, "confidence": 1.0}})
    assert document.layout_recognized is True
    if kind == "coded":
        items = get_coded(document, path)
        assert len(items) == 1
        field = items[0].amount
    else:
        field = get_extracted(document, path)
    assert field.value is not None
    assert field.provenance.extractor == "llm"
    assert field.provenance.own_region is False
    assert field.confidence == LLM_ONLY_CONFIDENCE_CAP
    assert field.confidence < REVIEW_THRESHOLD
    if kind == "string":
        assert path not in ROSTER_IDENTITY_PATHS


def _llm_money(threshold: float) -> float:
    assembled = assemble(
        "K1-CAP",
        {
            "5 Interest income": [
                Observed(
                    "1500.00",
                    1,
                    None,
                    "llm",
                    label_score=1.0,
                    reported_confidence=1.0,
                    grounded=True,
                    anchored=True,
                )
            ]
        },
        extractor="llm",
        layout_stats=LayoutStats(seen_lines=8, strong_anchors=8),
        threshold=threshold,
    )
    field = assembled.part_iii.interest_income
    assert field.provenance.extractor == "llm"
    assert field.provenance.own_region is False
    return field.confidence


def test_an_llm_tax_year_at_model_confidence_one_stays_under_review() -> None:
    """The tax year is capped on its own path. Skipping that path clears 0.80.

    A full label score plus a model confidence of 1.0 scores about 0.83
    before the cap. The year does not go through the scalar parser.
    """

    document = assemble(
        "K1-YEAR",
        {
            "TAX YEAR": [
                Observed(
                    "2024",
                    1,
                    None,
                    "llm",
                    label_score=1.0,
                    reported_confidence=1.0,
                    grounded=True,
                    anchored=True,
                )
            ]
        },
        extractor="llm",
        layout_stats=LayoutStats(seen_lines=8, strong_anchors=8),
    )
    assert document.layout_recognized is True
    assert document.tax_year == 2024
    assert document.tax_year_extractor == "llm"
    assert document.tax_year_confidence == LLM_ONLY_CONFIDENCE_CAP
    assert document.tax_year_confidence is not None
    assert document.tax_year_confidence < REVIEW_THRESHOLD


def test_llm_cap_stays_at_the_named_cap_when_the_threshold_is_above_0_80() -> None:
    score = _llm_money(0.90)
    assert score == LLM_ONLY_CONFIDENCE_CAP
    assert score < 0.90


def test_llm_cap_drops_when_the_threshold_is_below_0_80() -> None:
    score = _llm_money(0.50)
    assert score == llm_only_confidence_cap(0.50)
    assert score < 0.50
    assert score < LLM_ONLY_CONFIDENCE_CAP


def test_assemble_caps_an_llm_value_whose_own_region_is_false() -> None:
    assembled = assemble(
        "K1-CAP",
        {
            "5 Interest income": [
                Observed(
                    "1500.00",
                    1,
                    None,
                    "llm",
                    label_score=1.0,
                    reported_confidence=1.0,
                    grounded=True,
                    anchored=True,
                )
            ]
        },
        extractor="llm",
        layout_stats=LayoutStats(seen_lines=8, strong_anchors=8),
    )
    field = assembled.part_iii.interest_income
    assert field.value is not None
    assert field.provenance.own_region is False
    assert field.confidence == LLM_ONLY_CONFIDENCE_CAP
    assert field.confidence < REVIEW_THRESHOLD


def test_recorded_both_options_checkbox_is_not_confident_wrong(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Eval's confident-wrong gate sees a both-options checkbox. No API call."""

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    dest = tmp_path / "checkbox"
    dest.mkdir()
    _draw(dest / "K1-CHECK.pdf", [*_ANCHORS, "D PTP: Yes X No"])
    truth = blank_schedule("K1-CHECK", extractor="generator", variant="clean", tax_year=2024)
    data = truth.model_dump(mode="json")
    data["part_i"]["is_ptp"]["value"] = True
    data["part_i"]["is_ptp"]["confidence"] = 1.0
    document = ScheduleK1.model_validate(data)
    payload = GroundTruthFile(planted_defects=[], document=document)
    (dest / "K1-CHECK.json").write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")
    manifest = Manifest(
        seed=1065,
        count=1,
        generator_version=GENERATOR_VERSION,
        documents=[
            ManifestDocument(
                document_id="K1-CHECK",
                variant="clean",
                pdf="K1-CHECK.pdf",
                ground_truth="K1-CHECK.json",
                planted_defects=[],
            )
        ],
    )
    (dest / "manifest.json").write_text(manifest.model_dump_json(indent=2) + "\n", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _reply({"D PTP": {"value": False, "confidence": 1.0}})

    extractor = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler)))
    report = evaluate(dest, extractor=extractor, distribution="in_distribution")
    assert report.confident_wrong == []
    predicted = extractor.extract(dest / "K1-CHECK.pdf")
    field = predicted.part_i.is_ptp
    assert predicted.layout_recognized is True
    assert field.value is False
    assert field.confidence == LLM_ONLY_CONFIDENCE_CAP
    assert field.confidence < REVIEW_THRESHOLD

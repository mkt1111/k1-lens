"""Hybrid extraction with recorded HTTP responses. No live API calls."""

import json
import re
from pathlib import Path

import httpx
import pytest
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen.canvas import Canvas

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import ScheduleK1
from k1lens.eval.compare import compare_set, render_comparison
from k1lens.extract.base import Extractor
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.factory import get_extractor
from k1lens.extract.geometry import page_words
from k1lens.extract.hybrid import HybridExtractor, _merge
from k1lens.extract.llm import estimate_cost_usd
from k1lens.extract.text import plain_text
from k1lens.generate.build import Variant
from k1lens.generate.corpus import generate_corpus
from k1lens.generate.dev_layouts import generate_dev
from k1lens.validate.engine import validate_document


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "K1LENS_LLM_PROVIDER",
        "K1LENS_OPENAI_MODEL",
        "K1LENS_ANTHROPIC_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def _pdf(tmp_path: Path) -> Path:
    dest = tmp_path / "hybrid"
    generate_corpus(dest, seed=8, count=1, plan=(Variant.CLEAN,))
    return dest / "K1-0001.pdf"


class _Fixed:
    name = "deterministic"

    def __init__(self, document: ScheduleK1) -> None:
        self._document = document

    def extract(self, pdf_path: Path, *, threshold: float = REVIEW_THRESHOLD) -> ScheduleK1:
        del pdf_path, threshold
        return self._document


def _response(fields: dict[str, object], *, usage: dict[str, int] | None = None) -> httpx.Response:
    body: dict[str, object] = {
        "choices": [{"message": {"content": json.dumps({"fields": fields})}}]
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_merge_keeps_an_ocr_page_failure() -> None:
    """A model fill does not erase a page that OCR failed to read."""

    import random

    from k1lens.generate.build import build_document
    from k1lens.validate.engine import validate_document

    primary = build_document(random.Random(1), 1, Variant.CLEAN).model_copy(
        update={"ocr_failed_pages": [2]}
    )
    fallback = primary.model_copy(update={"ocr_failed_pages": []})
    merged = _merge(primary, fallback, REVIEW_THRESHOLD, [])
    assert merged.ocr_failed_pages == [2]
    assert any(item.rule_id == "ocr_page" for item in validate_document(merged))


def test_hybrid_does_nothing_without_a_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    pdf = _pdf(tmp_path)
    hybrid = HybridExtractor()
    document = hybrid.extract(pdf)
    assert hybrid.usage.calls == 0
    assert document.part_i.ein.value == DeterministicExtractor().extract(pdf).part_i.ein.value


def test_a_title_case_partner_name_still_asks_the_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A clean page is recognized. The partner name has no structural marker.

    That field stays under 0.80, so the model is called. An amount that
    already cleared is not what opened the gap.
    """

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return _response({})

    document = HybridExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        _pdf(tmp_path)
    )
    assert document.layout_recognized is True
    assert calls == 1
    assert document.part_i.ein.confidence >= REVIEW_THRESHOLD
    assert document.part_ii.name.confidence < REVIEW_THRESHOLD


def test_only_the_low_confidence_field_is_replaced(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("K1LENS_OPENAI_MODEL", "gpt-4o-mini")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    city = primary.part_i.city.value
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["value"] = "99-9999999"
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)
    ein = str(primary.part_i.ein.value)

    def handler(request: httpx.Request) -> httpx.Response:
        fields = {
            "A Partnership EIN": {"value": ein, "confidence": 0.99},
            "B Partnership city": {"value": "SHOULD NOT REPLACE", "confidence": 0.99},
        }
        return _response(
            fields,
            usage={"prompt_tokens": 1000, "completion_tokens": 100},
        )

    hybrid = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    )
    document = hybrid.extract(pdf)
    assert document.part_i.ein.value == "99-9999999"
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD
    assert document.part_i.ein.provenance.extractor != "llm"
    assert document.part_i.city.value == city
    assert document.part_i.city.provenance.extractor != "llm"
    assert hybrid.usage.calls == 1
    assert hybrid.usage.input_tokens == 1000
    assert hybrid.usage.output_tokens == 100
    assert hybrid.usage.estimated_cost_usd == pytest.approx(0.00021)


def test_agreed_identity_and_a_repeated_amount_stay_below_0_80(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An unmarked partner name both sides spell the same way stays under 0.80.

    An amount the model only repeats is still one reading of the page.
    A city that already has its own shape is not lifted by repeating it.
    """

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    rental = primary.part_iii.net_rental_real_estate.value
    name = primary.part_ii.name.value
    city = primary.part_i.city.value
    assert rental is not None and isinstance(name, str) and city is not None
    assert primary.part_ii.name.confidence < REVIEW_THRESHOLD
    data = primary.model_dump(mode="json")
    data["part_iii"]["net_rental_real_estate"]["confidence"] = 0.78
    data["part_iii"]["net_rental_real_estate"]["provenance"]["extractor"] = "ocr"
    data["part_i"]["city"]["confidence"] = 0.55
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response(
            {
                "2 Net rental real estate income": {"value": str(rental), "confidence": 0.99},
                "F Partner name": {"value": name, "confidence": 0.99},
                "B Partnership city": {"value": city, "confidence": 0.99},
            }
        )

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert document.part_iii.net_rental_real_estate.value == rental
    assert document.part_iii.net_rental_real_estate.confidence == pytest.approx(0.78)
    assert document.part_iii.net_rental_real_estate.confidence < REVIEW_THRESHOLD
    assert document.part_iii.net_rental_real_estate.provenance.extractor == "ocr"
    assert document.part_ii.name.value == name
    assert document.part_ii.name.confidence < REVIEW_THRESHOLD
    assert document.part_ii.name.provenance.extractor != "llm"
    assert document.part_i.city.value == city
    assert document.part_i.city.confidence == pytest.approx(0.55)


def test_agreement_cannot_raise_a_model_confidence_of_0_30(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A second reading does not lift past the confidence the model reported."""

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    name = primary.part_ii.name.value
    assert isinstance(name, str)
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["value"] = "99-9999999"
    data["part_i"]["ein"]["confidence"] = 0.20
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response(
            {
                "F Partner name": {"value": name, "confidence": 0.30},
                "A Partnership EIN": {"value": str(primary.part_i.ein.value), "confidence": 0.30},
            }
        )

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert document.part_ii.name.value == name
    assert document.part_ii.name.confidence < REVIEW_THRESHOLD
    assert document.part_ii.name.provenance.extractor != "llm"
    assert document.part_i.ein.value == "99-9999999"
    assert document.part_i.ein.confidence == pytest.approx(0.20)


def test_a_model_value_that_disagrees_with_the_page_stays_in_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        "k1lens.extract.hybrid.value_in_label_region", lambda label, raw, words: False
    )
    monkeypatch.setattr("k1lens.extract.llm.value_in_label_region", lambda label, raw, words: False)
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    ending = primary.part_ii.capital.ending.value
    assert ending is not None
    data = primary.model_dump(mode="json")
    data["part_ii"]["capital"]["ending"]["value"] = str(ending + 100)
    data["part_ii"]["capital"]["ending"]["confidence"] = 0.4
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response({"L Ending capital": {"value": str(ending), "confidence": 0.99}})

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert document.part_ii.capital.ending.value == ending + 100
    assert document.part_ii.capital.ending.confidence < REVIEW_THRESHOLD
    assert any(item.rule_id == "capital_reconciles" for item in validate_document(document))


def test_a_model_ending_that_contradicts_the_printed_amount_keeps_the_finding(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """286152.00 is what the page read. 281152.00 would make item L tie.

    The model must not replace the page or clear the reconciliation error.
    """

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    capital = data["part_ii"]["capital"]
    capital["beginning"]["value"] = "281152.00"
    capital["contributed"]["value"] = "0.00"
    capital["current_year_net_income"]["value"] = "0.00"
    capital["other_increase_decrease"]["value"] = "0.00"
    capital["withdrawals"]["value"] = "0.00"
    capital["ending"]["value"] = "286152.00"
    capital["ending"]["confidence"] = 0.4
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response({"L Ending capital": {"value": "281152.00", "confidence": 0.99}})

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert document.part_ii.capital.ending.value is not None
    assert format(document.part_ii.capital.ending.value, "f") == "286152.00"
    assert document.part_ii.capital.ending.confidence < REVIEW_THRESHOLD
    assert any(item.rule_id == "capital_reconciles" for item in validate_document(document))


def test_malformed_reply_retries_once_and_keeps_deterministic_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})

    hybrid = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    )
    with caplog.at_level("WARNING"):
        document = hybrid.extract(pdf)
    assert calls == 2
    assert hybrid.usage.malformed_calls == 2
    assert document.part_i.ein.value == low.part_i.ein.value
    assert document.part_i.ein.confidence == pytest.approx(0.2)
    assert document.part_i.ein.provenance.extractor != "llm"
    assert "Keeping deterministic values" in caplog.text
    assert hybrid.traces[-1].malformed is True


def test_a_valid_retry_replaces_the_malformed_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    ein = str(primary.part_i.ein.value)
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["value"] = "99-9999999"
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        if calls == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": "{"}}]})
        return _response({"A Partnership EIN": {"value": ein, "confidence": 0.99}})

    hybrid = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    )
    document = hybrid.extract(pdf)
    assert calls == 2
    assert hybrid.usage.malformed_calls == 1
    assert document.part_i.ein.value == "99-9999999"
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD


def test_ungrounded_value_stays_under_the_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["part_i"]["name"]["confidence"] = 0.1
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        return _response({"B Partnership name": {"value": "Mara Ellison LP", "confidence": 1.0}})

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert document.part_i.name.value == low.part_i.name.value
    assert document.part_i.name.value != "Mara Ellison LP"
    assert document.part_i.name.confidence == pytest.approx(0.1)


def test_a_page_ein_outside_its_label_region_stays_below_0_80(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    dest = tmp_path / "dev"
    generate_dev(dest, seed=4)
    pdf = dest / "K1-0005.pdf"
    primary = DeterministicExtractor().extract(pdf)
    assert primary.layout_recognized is False
    page = plain_text(pdf)
    found = re.search(r"\d{2}-\d{7}", page)
    assert found is not None
    ein = found.group(0)

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {
                "A Partnership EIN": {"value": ein, "confidence": 0.99},
                "B Partnership name": {"value": "NOT ON THE PAGE LP", "confidence": 1.0},
                "11 Other income Z": {"value": "999999.00", "confidence": 0.99},
            }
        )

    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["value"] = "99-9999999"
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)
    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert document.layout_recognized is False
    # The statement caption is not the catalog label, so the EIN is on the
    # page but not in that field's label region. A page-wide hit does not clear.
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD
    assert document.part_i.ein.value == "99-9999999"
    assert document.part_i.name.value != "NOT ON THE PAGE LP"
    assert document.part_i.name.confidence < REVIEW_THRESHOLD
    added = [item for item in document.part_iii.other_income if item.code == "Z"]
    assert not added


def test_non_json_body_is_a_malformed_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="<html>gateway</html>")

    hybrid = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    )
    document = hybrid.extract(pdf)
    assert document.part_i.ein.value == low.part_i.ein.value
    assert hybrid.usage.malformed_calls >= 1


def test_hybrid_keeps_deterministic_values_on_5xx_or_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)
    calls = {"n": 0}

    def down(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(503, json={"error": "down"})

    hybrid = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(down)),
        deterministic=_Fixed(low),
    )
    document = hybrid.extract(pdf)
    assert calls["n"] == 2
    assert document.part_i.ein.value == low.part_i.ein.value

    def timeout(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ReadTimeout("timed out")

    again = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(timeout)),
        deterministic=_Fixed(low),
    )
    kept = again.extract(pdf)
    assert kept.part_i.ein.value == low.part_i.ein.value


def test_hybrid_stops_on_a_persistent_429_and_on_a_connection_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from k1lens.extract.base import ExtractionError

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)
    calls = {"n": 0}

    def limited(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return httpx.Response(429, json={"error": "slow"})

    hybrid = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(limited)),
        deterministic=_Fixed(low),
    )
    with pytest.raises(ExtractionError, match="status 429"):
        hybrid.extract(pdf)
    assert calls["n"] == 2

    def offline(request: httpx.Request) -> httpx.Response:
        del request
        raise httpx.ConnectError("network down")

    stopped = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(offline)),
        deterministic=_Fixed(low),
    )
    with pytest.raises(ExtractionError, match="ConnectError"):
        stopped.extract(pdf)


def test_hybrid_keeps_deterministic_values_on_a_non_utf8_body(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, content=b"\xff\xfe")

    hybrid = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    )
    document = hybrid.extract(pdf)
    assert document.part_i.ein.value == low.part_i.ein.value
    assert hybrid.usage.malformed_calls >= 1


def test_ungrounded_model_tax_year_stays_in_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["tax_year"] = None
    data["tax_year_confidence"] = None
    low = ScheduleK1.model_validate(data)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return _response({"TAX YEAR": {"value": 1999, "confidence": 0.99}})

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert calls["n"] == 1
    assert document.tax_year is None


def test_out_of_region_model_coded_amount_stays_in_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = _pdf(tmp_path)
    primary = DeterministicExtractor().extract(pdf)
    data = primary.model_dump(mode="json")
    data["layout_recognized"] = False
    data["part_iii"]["other_income"] = []
    low = ScheduleK1.model_validate(data)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        calls["n"] += 1
        return _response({"11 Other income Z": {"value": "999999.00", "confidence": 0.99}})

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert calls["n"] == 1
    added = [item for item in document.part_iii.other_income if item.code == "Z"]
    assert not added


def test_merge_caps_an_ungrounded_year_the_model_scored_high(tmp_path: Path) -> None:
    """The merge cap is what holds the year. The model leg may already be high."""

    primary = DeterministicExtractor().extract(_pdf(tmp_path))
    payload = primary.model_dump(mode="json")
    payload["tax_year"] = None
    payload["tax_year_confidence"] = None
    primary = ScheduleK1.model_validate(payload)
    fallback_payload = primary.model_dump(mode="json")
    fallback_payload["tax_year"] = 1999
    fallback_payload["tax_year_confidence"] = 0.99
    fallback = ScheduleK1.model_validate(fallback_payload)
    merged = _merge(primary, fallback, REVIEW_THRESHOLD, [])
    assert merged.tax_year is None


def test_merge_caps_an_out_of_region_coded_amount_the_model_scored_high(
    tmp_path: Path,
) -> None:
    """A missing code filled from the model stays in review when it is not on the line."""

    primary = DeterministicExtractor().extract(_pdf(tmp_path))
    sample = primary.part_iii.other_income[0].model_dump(mode="json")
    sample["code"] = "Z"
    sample["amount"]["value"] = "999999.00"
    sample["amount"]["confidence"] = 0.99
    payload = primary.model_dump(mode="json")
    payload["layout_recognized"] = False
    payload["part_iii"]["other_income"] = []
    primary = ScheduleK1.model_validate(payload)
    fallback_payload = primary.model_dump(mode="json")
    fallback_payload["part_iii"]["other_income"] = [sample]
    fallback = ScheduleK1.model_validate(fallback_payload)
    merged = _merge(primary, fallback, REVIEW_THRESHOLD, [])
    added = [item for item in merged.part_iii.other_income if item.code == "Z"]
    assert not added


# below_review_threshold at the default, at 0.60, and just under 0.49.
_FILL_CAPS = (
    (0.80, 0.49),
    (0.60, 0.49),
    (0.40, 0.39),
)


def _catalog(tmp_path: Path, threshold: float) -> tuple[Path, ScheduleK1]:
    pdf = _pdf(tmp_path)
    return pdf, DeterministicExtractor().extract(pdf, threshold=threshold)


@pytest.mark.parametrize(("threshold", "cap"), _FILL_CAPS)
def test_merge_caps_a_grounded_money_fill(tmp_path: Path, threshold: float, cap: float) -> None:
    """A missing amount in its own label region is stored, and the fill cap holds it.

    The cap is 0.49 at thresholds 0.80 and 0.60, and 0.39 at 0.40.
    """

    pdf, record = _catalog(tmp_path, threshold)
    printed = record.part_iii.interest_income.value
    assert printed is not None
    primary_data = record.model_dump(mode="json")
    primary_data["part_iii"]["interest_income"]["value"] = None
    primary_data["part_iii"]["interest_income"]["confidence"] = 0.0
    primary = ScheduleK1.model_validate(primary_data)
    fallback_data = record.model_dump(mode="json")
    fallback_data["part_iii"]["interest_income"]["confidence"] = 0.99
    fallback = ScheduleK1.model_validate(fallback_data)
    merged = _merge(primary, fallback, threshold, page_words(pdf))
    stored = merged.part_iii.interest_income
    assert stored.value == printed
    assert stored.confidence == pytest.approx(cap)
    assert stored.confidence < threshold


@pytest.mark.parametrize(("threshold", "cap"), _FILL_CAPS)
def test_merge_does_not_raise_a_grounded_money_fill(
    tmp_path: Path, threshold: float, cap: float
) -> None:
    """A model report of 0.30 is stored at 0.30. Agreement does not lift it to the cap."""

    pdf, record = _catalog(tmp_path, threshold)
    printed = record.part_iii.interest_income.value
    assert printed is not None
    primary_data = record.model_dump(mode="json")
    primary_data["part_iii"]["interest_income"]["value"] = None
    primary_data["part_iii"]["interest_income"]["confidence"] = 0.0
    primary = ScheduleK1.model_validate(primary_data)
    fallback_data = record.model_dump(mode="json")
    fallback_data["part_iii"]["interest_income"]["confidence"] = 0.30
    fallback = ScheduleK1.model_validate(fallback_data)
    merged = _merge(primary, fallback, threshold, page_words(pdf))
    stored = merged.part_iii.interest_income
    assert stored.value == printed
    assert stored.confidence == pytest.approx(min(0.30, cap))


@pytest.mark.parametrize(("threshold", "cap"), _FILL_CAPS)
def test_merge_caps_an_appended_coded_line(tmp_path: Path, threshold: float, cap: float) -> None:
    """An unrecognized layout appends one missing coded line, under the fill cap."""

    pdf, record = _catalog(tmp_path, threshold)
    sample = record.part_iii.other_income[0]
    code = sample.code
    printed = sample.amount.value
    assert printed is not None
    primary_data = record.model_dump(mode="json")
    primary_data["layout_recognized"] = False
    kept: list[object] = []
    removed = False
    for item in primary_data["part_iii"]["other_income"]:
        if not removed and item["code"] == code:
            removed = True
            continue
        kept.append(item)
    assert removed
    primary_data["part_iii"]["other_income"] = kept
    primary = ScheduleK1.model_validate(primary_data)
    fallback_data = record.model_dump(mode="json")
    for item in fallback_data["part_iii"]["other_income"]:
        if item["code"] == code:
            item["amount"]["confidence"] = 0.99
            break
    fallback = ScheduleK1.model_validate(fallback_data)
    merged = _merge(primary, fallback, threshold, page_words(pdf))
    matched = [item for item in merged.part_iii.other_income if item.code == code]
    assert len(matched) == 1
    assert matched[0].amount.value == printed
    assert matched[0].amount.confidence == pytest.approx(cap)
    assert matched[0].amount.confidence < threshold


@pytest.mark.parametrize(("threshold", "cap"), _FILL_CAPS)
def test_merge_caps_a_grounded_tax_year(tmp_path: Path, threshold: float, cap: float) -> None:
    """A missing tax year printed in its own region is stored under the fill cap."""

    pdf, record = _catalog(tmp_path, threshold)
    printed = record.tax_year
    assert printed is not None
    primary_data = record.model_dump(mode="json")
    primary_data["tax_year"] = None
    primary_data["tax_year_confidence"] = None
    primary = ScheduleK1.model_validate(primary_data)
    fallback_data = record.model_dump(mode="json")
    fallback_data["tax_year"] = printed
    fallback_data["tax_year_confidence"] = 0.99
    fallback = ScheduleK1.model_validate(fallback_data)
    merged = _merge(primary, fallback, threshold, page_words(pdf))
    assert merged.tax_year == printed
    assert merged.tax_year_confidence == pytest.approx(cap)
    assert merged.tax_year_confidence is not None
    assert merged.tax_year_confidence < threshold


def test_merge_refuses_an_amount_printed_in_another_box(tmp_path: Path) -> None:
    """Box 5 stays empty when the model offers an amount that belongs to another box."""

    pdf, record = _catalog(tmp_path, REVIEW_THRESHOLD)
    ordinary = record.part_iii.ordinary_business_income.value
    interest = record.part_iii.interest_income.value
    assert ordinary is not None and interest is not None
    assert ordinary != interest
    primary_data = record.model_dump(mode="json")
    primary_data["part_iii"]["interest_income"]["value"] = None
    primary_data["part_iii"]["interest_income"]["confidence"] = 0.0
    primary = ScheduleK1.model_validate(primary_data)
    fallback_data = record.model_dump(mode="json")
    fallback_data["part_iii"]["interest_income"]["value"] = fallback_data["part_iii"][
        "ordinary_business_income"
    ]["value"]
    fallback_data["part_iii"]["interest_income"]["confidence"] = 0.99
    fallback = ScheduleK1.model_validate(fallback_data)
    merged = _merge(primary, fallback, REVIEW_THRESHOLD, page_words(pdf))
    assert merged.part_iii.interest_income.value is None


def test_merge_refuses_identity_from_the_model(tmp_path: Path) -> None:
    """A printed EIN, partnership city, or partner name is not filled from the model."""

    pdf, record = _catalog(tmp_path, REVIEW_THRESHOLD)
    assert record.part_i.ein.value
    assert record.part_i.city.value
    assert record.part_ii.name.value
    primary_data = record.model_dump(mode="json")
    for section, field in (("part_i", "ein"), ("part_i", "city"), ("part_ii", "name")):
        primary_data[section][field]["value"] = None
        primary_data[section][field]["confidence"] = 0.0
    primary = ScheduleK1.model_validate(primary_data)
    fallback_data = record.model_dump(mode="json")
    for section, field in (("part_i", "ein"), ("part_i", "city"), ("part_ii", "name")):
        fallback_data[section][field]["confidence"] = 0.99
    fallback = ScheduleK1.model_validate(fallback_data)
    merged = _merge(primary, fallback, REVIEW_THRESHOLD, page_words(pdf))
    assert merged.part_i.ein.value is None
    assert merged.part_i.city.value is None
    assert merged.part_ii.name.value is None


def test_compare_without_a_key_skips_the_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    dest = tmp_path / "one"
    generate_corpus(dest, seed=3, count=1, plan=(Variant.CLEAN,))
    compared = compare_set(dest, distribution="in_distribution")
    text = render_comparison([compared])
    assert "No live model call was made" in text
    assert "Confident wrong" in text
    assert "Cost / document" in text
    assert "Latency" in text
    names = [row.backend for row in compared.backends]
    assert names == ["deterministic", "llm", "hybrid"]
    assert compared.backends[1].skipped is True
    assert compared.backends[2].llm_calls == 0
    assert compared.backends[0].confident_wrong == 0


def test_compare_recorded_responses_report_cost_and_latency(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "openai")
    monkeypatch.setenv("K1LENS_OPENAI_MODEL", "gpt-4o-mini")
    dest = tmp_path / "gap"
    generate_corpus(dest, seed=3, count=1, plan=(Variant.MISSING_FIELDS,))

    def handler(request: httpx.Request) -> httpx.Response:
        return _response(
            {},
            usage={"prompt_tokens": 1000, "completion_tokens": 100},
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    compared = compare_set(dest, distribution="in_distribution", client=client)
    text = render_comparison([compared])
    assert "Accuracy" in text
    assert "Precision" in text
    model = compared.backends[1]
    hybrid = compared.backends[2]
    assert model.skipped is False
    assert model.llm_calls == 1
    assert model.estimated_cost_usd == pytest.approx(0.00021)
    assert model.cost_per_document_usd == pytest.approx(0.00021)
    assert model.latency_seconds is not None and model.latency_seconds >= 0
    assert hybrid.llm_calls == 1
    assert "$0.000210" in text


def test_unpriced_model_has_no_cost() -> None:
    assert estimate_cost_usd("gpt-4o-mini", 1_000_000, 0) == pytest.approx(0.15)
    assert estimate_cost_usd("gpt-4o-mini-2024-07-18", 0, 1_000_000) == pytest.approx(0.60)
    assert estimate_cost_usd("gpt-test", 10, 10) is None


def test_factory_returns_hybrid() -> None:
    extractor: Extractor = get_extractor("hybrid")
    assert extractor.name == "hybrid"


def test_two_column_recourse_does_not_replace_qualified_nonrecourse(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The recourse amount is the next column. It must not clear as qualified."""

    from k1lens.generate.geometry import generate_dev_geometry

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    dest = tmp_path / "geom"
    generate_dev_geometry(dest, seed=1065)
    pdf = dest / "K1-0005.pdf"
    primary = DeterministicExtractor().extract(pdf)
    qualified = primary.part_ii.liability_qualified_nonrecourse
    recourse = primary.part_ii.liability_recourse
    assert qualified.value is not None and recourse.value is not None
    assert qualified.value != recourse.value
    assert qualified.confidence < REVIEW_THRESHOLD

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response(
            {"K Qualified nonrecourse": {"value": str(recourse.value), "confidence": 1.0}}
        )

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(primary),
    ).extract(pdf)
    kept = document.part_ii.liability_qualified_nonrecourse
    assert kept.value == qualified.value
    assert kept.confidence < REVIEW_THRESHOLD
    assert kept.confidence == pytest.approx(qualified.confidence)


def test_a_swapped_on_page_amount_does_not_clear_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Both amounts are on the page. Each must sit next to its own label."""

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = tmp_path / "swap.pdf"
    _face(
        pdf,
        [
            ("1 Ordinary business income", "100.00"),
            ("5 Interest income", "200.00"),
        ],
    )

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response(
            {
                "1 Ordinary business income": {"value": "200.00", "confidence": 0.99},
                "5 Interest income": {"value": "100.00", "confidence": 0.99},
            }
        )

    document = HybridExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        pdf
    )
    assert document.layout_recognized is False
    assert document.part_iii.ordinary_business_income.confidence < REVIEW_THRESHOLD
    assert document.part_iii.interest_income.confidence < REVIEW_THRESHOLD


def test_region_grounded_ein_on_an_unrecognized_layout_stays_below_0_80(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = tmp_path / "ein.pdf"
    _face(pdf, [("A Partnership EIN", "00-0000099")])
    primary = DeterministicExtractor().extract(pdf)
    assert primary.layout_recognized is False
    data = primary.model_dump(mode="json")
    data["part_i"]["ein"]["value"] = "99-9999999"
    data["part_i"]["ein"]["confidence"] = 0.2
    low = ScheduleK1.model_validate(data)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response({"A Partnership EIN": {"value": "00-0000099", "confidence": 0.99}})

    document = HybridExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        deterministic=_Fixed(low),
    ).extract(pdf)
    assert document.part_i.ein.value == "99-9999999"
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD


def test_llm_only_unrecognized_layout_stays_under_review(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from k1lens.extract.llm import LLMExtractor

    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    pdf = tmp_path / "ein.pdf"
    _face(pdf, [("A Partnership EIN", "00-0000099")])

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _response({"A Partnership EIN": {"value": "00-0000099", "confidence": 0.99}})

    document = LLMExtractor(client=httpx.Client(transport=httpx.MockTransport(handler))).extract(
        pdf
    )
    assert document.layout_recognized is False
    assert document.part_i.ein.value == "00-0000099"
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD


def test_a_model_amount_outside_the_label_region_is_not_stored() -> None:
    """A missing amount is not filled when the model string is not in that region."""

    from k1lens.domain.blank import blank_schedule

    primary = blank_schedule("K1-GAP", tax_year=2024)
    data = primary.model_dump(mode="json")
    node = data["part_iii"]["ordinary_business_income"]
    node["value"] = "15.00"
    node["confidence"] = 0.99
    node["provenance"]["extractor"] = "llm"
    fallback = ScheduleK1.model_validate(data)
    merged = _merge(primary, fallback, REVIEW_THRESHOLD, [])
    assert merged.part_iii.ordinary_business_income.value is None


def test_model_confidence_outside_zero_to_one_is_clamped_or_rejected() -> None:
    from k1lens.extract.hybrid import _finite_confidence
    from k1lens.extract.llm import LlmDocumentIn, _model_confidence, _observed_from_payload

    assert _finite_confidence(1.5) == 1.0
    assert _finite_confidence(-0.4) == 0.0
    assert _finite_confidence(float("nan")) is None
    assert _finite_confidence(float("inf")) is None
    assert _model_confidence(1.5) == 1.0
    assert _model_confidence(-0.4) == 0.0
    assert _model_confidence(None) == 0.5
    assert _model_confidence(float("nan")) is None
    payload = LlmDocumentIn.model_validate(
        {
            "fields": {
                "1 Ordinary business income": {"value": "15.00", "confidence": float("nan")},
                "5 Interest income": {"value": "10.00", "confidence": 1.5},
            }
        }
    )
    observed = _observed_from_payload(payload, [])
    assert "1 Ordinary business income" not in observed
    assert observed["5 Interest income"][0].reported_confidence == 1.0


def _face(path: Path, rows: list[tuple[str, str]]) -> None:
    canvas = Canvas(str(path), pagesize=letter, invariant=1)
    canvas.setFont("Helvetica", 10)
    y = 700
    for label, value in rows:
        canvas.drawString(40, y, label)
        canvas.drawString(220, y, value)
        y -= 18
    canvas.save()

"""Live eval harness with recorded responses. No network calls."""

import json
import logging
import math
import os
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from k1lens.cli import _compare_targets, app
from k1lens.eval.live import LIVE_JSON, LIVE_MARKDOWN, _delta_cost, run_live
from k1lens.extract.base import ExtractionError, SpendCeilingExceeded, UnpricedModelError
from k1lens.extract.llm import (
    LLMExtractor,
    SpendGuard,
    estimate_request_usd,
)
from k1lens.extract.redact import install_secret_redaction, redact_secrets
from k1lens.generate.build import Variant
from k1lens.generate.corpus import generate_corpus

_KEY = "sk-test-live-key-0123456789"
runner = CliRunner()


def test_live_report_defaults_write_into_docs_eval_live() -> None:
    assert Path("docs/eval-live/report.md") == LIVE_MARKDOWN
    assert Path("docs/eval-live/report.json") == LIVE_JSON
    result = runner.invoke(app, ["eval", "--help"])
    assert result.exit_code == 0
    assert "docs/eval-live/report.md" in result.stdout
    assert "docs/eval-live.md" not in result.stdout


def _clear(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "K1LENS_LLM_PROVIDER",
        "K1LENS_OPENAI_MODEL",
        "K1LENS_ANTHROPIC_MODEL",
        "K1LENS_ENABLE_OCR",
    ):
        monkeypatch.delenv(name, raising=False)


def _gap(dest: Path, count: int = 1) -> Path:
    generate_corpus(dest, seed=3, count=count, plan=(Variant.MISSING_FIELDS,))
    return dest


def _ok(usage: dict[str, int] | None = None) -> httpx.Response:
    body: dict[str, object] = {
        "choices": [{"message": {"content": json.dumps({"fields": {}})}}],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(200, json=body)


def test_default_live_command_covers_every_set() -> None:
    targets = _compare_targets(Path("fixtures/synthetic"), "in_distribution")
    assert [item[0] for item in targets] == [
        "in_distribution",
        "dev",
        "dev_b",
        "dev_geometry",
        "scans",
    ]
    one = _compare_targets(Path("fixtures/custom"), "dev")
    assert one == [("dev", Path("fixtures/custom"), "dev")]


def test_redact_removes_the_key_and_headers(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-test-key-9876")
    text = redact_secrets(
        f"key {_KEY} and anthropic-test-key-9876\n"
        f"Authorization: Bearer {_KEY}\n"
        "x-api-key: anthropic-test-key-9876"
    )
    assert _KEY not in text
    assert "anthropic-test-key-9876" not in text
    assert text.count("[redacted]") == 4
    install_secret_redaction()
    install_secret_redaction()
    assert logging.getLogger("httpx").level == logging.WARNING
    logging.getLogger("httpx").setLevel(logging.DEBUG)
    with caplog.at_level(logging.DEBUG, logger="httpx"):
        logging.getLogger("httpx").debug("Authorization: Bearer %s", _KEY)
    assert _KEY not in caplog.text
    assert "[redacted]" in caplog.text


def test_live_report_has_the_score_fields(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    monkeypatch.setenv("K1LENS_LLM_PROVIDER", "anthropic")
    corpus = _gap(tmp_path / "gaps", count=2)
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["Authorization"] == f"Bearer {_KEY}"
        return _ok({"prompt_tokens": 1000, "completion_tokens": 100})

    markdown = tmp_path / "eval-live.md"
    payload = tmp_path / "eval-live.json"
    result = run_live(
        [("in_distribution", corpus, "synthetic")],
        backend="hybrid",
        report_md=markdown,
        report_json=payload,
        max_documents=1,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert os.environ.get("K1LENS_LLM_PROVIDER") == "anthropic"
    assert calls == ["https://api.openai.com/v1/chat/completions"]
    assert result.model == "gpt-4o-mini"
    assert result.spend_ceiling_usd == 3.0
    assert result.max_documents == 1
    assert result.input_tokens == 1000
    assert result.output_tokens == 100
    assert result.stopped == ""
    assert len(result.sets) == 1
    row = result.sets[0]
    assert row.documents == 1
    assert row.accuracy is not None
    assert row.precision is not None
    assert row.confident_wrong == 0
    assert row.straight_through_rate is not None
    assert row.cost_per_document_usd == pytest.approx(0.00021)
    written = json.loads(payload.read_text(encoding="utf-8"))
    assert written["backend"] == "hybrid"
    assert written["sets"][0]["input_tokens"] == 1000
    assert written["sets"][0]["output_tokens"] == 100
    assert written["sets"][0]["cost_per_document_usd"] == pytest.approx(0.00021)
    assert "latency_seconds" in written["sets"][0]
    report = markdown.read_text(encoding="utf-8")
    assert "uv run k1lens eval --backend hybrid --live" in report
    assert "Cost / document" in report
    assert "Cost / page" in report
    assert "Straight-through" in report
    assert "vs deterministic" in report
    assert "Det confidence" in report
    assert "Fields requested" in report
    assert written["model"] == "gpt-4o-mini"
    assert "malformed_calls" in written
    assert "fields_requested" in written
    detail = written["sets"][0]["detail"]
    assert detail[0]["document_id"]
    assert "fields" in detail[0]
    assert "deterministic_confidence" in detail[0]["fields"][0]
    assert "llm_value" in detail[0]["fields"][0]
    assert "correct" in detail[0]["fields"][0]
    combined = report + payload.read_text(encoding="utf-8")
    assert _KEY not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined
    assert "exception class" in report
    assert "429" in report


def test_malformed_reply_does_not_abort_the_live_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps", count=2)

    def handler(request: httpx.Request) -> httpx.Response:
        if b"K1-0001" in request.content:
            return httpx.Response(200, json={"choices": [{"message": {"content": "not json"}}]})
        return _ok({"prompt_tokens": 100, "completion_tokens": 20})

    result = run_live(
        [("in_distribution", corpus, "synthetic")],
        backend="hybrid",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result.stopped == ""
    assert result.sets[0].documents == 2
    assert result.sets[0].malformed_calls == 2
    assert result.sets[0].detail[0].malformed is True
    assert result.sets[0].detail[1].malformed is False
    text = (tmp_path / "live.md").read_text(encoding="utf-8")
    payload = (tmp_path / "live.json").read_text(encoding="utf-8")
    assert _KEY not in text
    assert _KEY not in payload
    assert "Authorization" not in text
    assert "Bearer" not in payload


def test_spend_ceiling_stops_before_the_next_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    first = _gap(tmp_path / "first", count=2)
    second = _gap(tmp_path / "second")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        nonlocal calls
        calls += 1
        return _ok({"prompt_tokens": 20_000_000, "completion_tokens": 0})

    result = run_live(
        [
            ("in_distribution", first, "synthetic"),
            ("dev", second, "dev"),
        ],
        backend="hybrid",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        ceiling_usd=3.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert calls == 1
    assert len(result.sets) == 1
    assert result.sets[0].documents == 1
    assert "Spend ceiling" in result.stopped
    assert result.estimated_cost_usd == pytest.approx(3.0, abs=1e-6)
    assert _KEY not in (tmp_path / "live.md").read_text(encoding="utf-8")
    assert _KEY not in (tmp_path / "live.json").read_text(encoding="utf-8")


def test_ceiling_reached_does_not_open_the_next_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    first = _gap(tmp_path / "first")
    opened: list[str] = []

    def ensure(path: Path, kind: str) -> None:
        del path
        opened.append(kind)

    monkeypatch.setattr("k1lens.eval.live.ensure_corpus", ensure)

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _ok({"prompt_tokens": 20_000_000, "completion_tokens": 0})

    result = run_live(
        [
            ("in_distribution", first, "synthetic"),
            ("dev", tmp_path / "second", "dev"),
        ],
        backend="hybrid",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        ceiling_usd=3.0,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert opened == []
    assert len(result.sets) == 1
    assert result.sets[0].documents == 1
    assert "Spend ceiling" in result.stopped


def test_missing_manifest_is_generated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    dest = tmp_path / "fresh"

    def ensure(path: Path, kind: str) -> None:
        assert kind == "synthetic"
        generate_corpus(path, seed=4, count=1, plan=(Variant.CLEAN,))

    monkeypatch.setattr("k1lens.eval.live.ensure_corpus", ensure)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    result = run_live(
        [("in_distribution", dest, "synthetic")],
        backend="hybrid",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert result.stopped == ""
    assert result.sets[0].documents == 1
    assert (dest / "manifest.json").is_file()


def test_transport_error_hides_the_key_and_closes_the_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps")
    closed: list[bool] = []

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs

        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            del args, kwargs
            raise httpx.ConnectError("network down")

        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr("k1lens.extract.llm.httpx.Client", _Client)
    with pytest.raises(ExtractionError, match="LLM request failed") as caught:
        LLMExtractor(spend=SpendGuard(3)).extract(corpus / "K1-0001.pdf")
    assert closed == [True]
    assert caught.value.__cause__ is None
    assert _KEY not in str(caught.value)
    assert "ConnectError" in str(caught.value)
    assert _delta_cost(None, 1.0) is None
    assert _delta_cost(1.0, None) is None


def test_a_live_run_records_the_status_after_one_retry(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(502, json={"error": "bad gateway"})

    result = run_live(
        [("in_distribution", corpus, "synthetic")],
        backend="llm",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert calls == 2
    assert "status 502" in result.stopped
    assert result.sets[0].documents == 0
    assert "status 502" in (tmp_path / "live.md").read_text(encoding="utf-8")


def test_a_live_run_names_the_exception_class(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        raise httpx.ConnectError("network down")

    result = run_live(
        [("in_distribution", corpus, "synthetic")],
        backend="llm",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert calls == 1
    assert "ConnectError" in result.stopped
    assert _KEY not in result.stopped


def test_live_run_writes_a_report_after_a_non_json_reply(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps")

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(200, text="<html>gateway</html>")

    report = tmp_path / "live.md"
    result = run_live(
        [("in_distribution", corpus, "synthetic")],
        backend="llm",
        report_md=report,
        report_json=tmp_path / "live.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert report.is_file()
    assert "JSON" in result.stopped or "malformed" in result.stopped.lower()
    assert "Stopped:" in report.read_text(encoding="utf-8")


def test_a_non_json_200_does_not_stop_hybrid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        del request
        calls += 1
        return httpx.Response(200, content=b"not-json")

    result = run_live(
        [("in_distribution", corpus, "synthetic")],
        backend="hybrid",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert calls == 2
    assert result.stopped == ""
    assert result.sets[0].documents == 1
    assert result.sets[0].malformed_calls == 2
    assert result.sets[0].detail[0].malformed is True


def test_max_spend_must_be_a_finite_positive_number(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    called: list[float] = []

    def fake_run_live(*args: object, **kwargs: object) -> object:
        del args
        called.append(float(kwargs["ceiling_usd"]))  # type: ignore[arg-type]
        raise AssertionError("run_live should not be called")

    monkeypatch.setattr("k1lens.cli.run_live", fake_run_live)
    for value in ("nan", "inf", "-1", "0"):
        called.clear()
        result = runner.invoke(
            app,
            [
                "eval",
                "--live",
                "--backend",
                "hybrid",
                "--max-spend",
                value,
                "--report",
                str(tmp_path / "live.md"),
            ],
        )
        assert result.exit_code == 2
        assert called == []
        assert "Traceback" not in result.output


def test_spend_guard_rejects_nan() -> None:
    with pytest.raises(ValueError):
        SpendGuard(float("nan"))
    with pytest.raises(ValueError):
        SpendGuard(float("inf"))
    with pytest.raises(ValueError):
        SpendGuard(0)
    with pytest.raises(ValueError):
        SpendGuard(-1)
    guard = SpendGuard(1.0)
    guard.allow(1.0)
    guard.add(1.0)
    with pytest.raises(SpendCeilingExceeded):
        guard.allow(1e-6)
    assert math.isfinite(guard.ceiling_usd)


def test_tiny_ceiling_sends_no_request(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps")
    assert estimate_request_usd("gpt-4o-mini", "x", 0) is not None
    assert estimate_request_usd("gpt-4o-mini", "x", 0) > 0.0001

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    result = run_live(
        [("in_distribution", corpus, "synthetic")],
        backend="llm",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        ceiling_usd=0.0001,
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert "Spend ceiling" in result.stopped
    assert result.estimated_cost_usd == 0
    assert result.sets[0].documents == 0
    report = (tmp_path / "live.md").read_text(encoding="utf-8")
    assert "n/a" in report


def test_unpriced_model_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    result = run_live(
        [("in_distribution", tmp_path / "unused", "synthetic")],
        backend="llm",
        report_md=tmp_path / "live.md",
        report_json=tmp_path / "live.json",
        model="gpt-test",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    assert "no list price" in result.stopped
    assert result.sets == ()
    assert not (tmp_path / "unused" / "manifest.json").exists()


def test_unpriced_model_is_refused_before_post(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    monkeypatch.setenv("K1LENS_OPENAI_MODEL", "gpt-test")
    corpus = _gap(tmp_path / "gaps")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError(request.url)

    with pytest.raises(UnpricedModelError, match="no list price"):
        LLMExtractor(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            spend=SpendGuard(3),
        ).extract(corpus / "K1-0001.pdf")


def test_failed_call_charges_the_estimate_and_hides_the_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    corpus = _gap(tmp_path / "gaps")
    spend = SpendGuard(3)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == f"Bearer {_KEY}"
        return httpx.Response(401, json={"error": {"message": _KEY}})

    with pytest.raises(ExtractionError, match="status 401") as caught:
        LLMExtractor(
            client=httpx.Client(transport=httpx.MockTransport(handler)),
            spend=spend,
        ).extract(corpus / "K1-0001.pdf")
    assert _KEY not in str(caught.value)
    assert "Authorization" not in str(caught.value)
    assert spend.spent_usd > 0


def test_vision_request_uses_low_detail_on_a_page_without_text(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    monkeypatch.setenv("K1LENS_ENABLE_OCR", "0")
    dest = tmp_path / "raster"
    generate_corpus(dest, seed=8, count=1, plan=(Variant.RASTERIZED,))
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        seen["model"] = body["model"]
        seen["content"] = body["messages"][1]["content"]
        return _ok({"prompt_tokens": 20, "completion_tokens": 5})

    document = LLMExtractor(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        spend=SpendGuard(3),
        vision=True,
    ).extract(dest / "K1-0001.pdf")
    content = seen["content"]
    assert isinstance(content, list)
    images = [part for part in content if part["type"] == "image_url"]
    assert images
    assert images[0]["image_url"]["detail"] == "low"
    assert str(images[0]["image_url"]["url"]).startswith("data:image/jpeg;base64,")
    assert seen["model"] == "gpt-4o-mini"
    assert document.part_i.ein.value is None


def test_live_command_requires_the_key_and_writes_both_reports(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clear(monkeypatch)
    missing = runner.invoke(
        app,
        ["eval", "--backend", "hybrid", "--live", "--fixtures", str(tmp_path)],
    )
    assert missing.exit_code == 2
    assert "OPENAI_API_KEY" in missing.stderr
    assert "not printed" in missing.stderr

    both = runner.invoke(app, ["eval", "--backend", "hybrid", "--live", "--compare"])
    assert both.exit_code == 2
    assert "not both" in both.stderr

    monkeypatch.setenv("OPENAI_API_KEY", _KEY)
    rejected = runner.invoke(app, ["eval", "--backend", "deterministic", "--live"])
    assert rejected.exit_code == 2
    assert "hybrid" in rejected.stderr
    documents = runner.invoke(
        app,
        ["eval", "--backend", "hybrid", "--live", "--max-documents", "0"],
    )
    assert documents.exit_code == 2
    spend = runner.invoke(
        app,
        ["eval", "--backend", "hybrid", "--live", "--max-spend", "0"],
    )
    assert spend.exit_code == 2
    combined = missing.output + both.output + rejected.output + documents.output + spend.output
    assert _KEY not in combined

    corpus = tmp_path / "one"
    generate_corpus(corpus, seed=5, count=1, plan=(Variant.CLEAN,))
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        assert _KEY not in str(request.url)
        return _ok({"prompt_tokens": 10, "completion_tokens": 5})

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            del args, kwargs
            self._inner = httpx.Client(transport=httpx.MockTransport(handler))

        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return self._inner.post(*args, **kwargs)  # type: ignore[arg-type]

        def close(self) -> None:
            self._inner.close()

    monkeypatch.setattr("k1lens.extract.llm.httpx.Client", _Client)
    report = tmp_path / "out.md"
    result = runner.invoke(
        app,
        [
            "eval",
            "--backend",
            "hybrid",
            "--live",
            "--fixtures",
            str(corpus),
            "--distribution",
            "in_distribution",
            "--report",
            str(report),
            "--max-documents",
            "1",
            "--max-spend",
            "3",
        ],
    )
    assert result.exit_code == 0, result.output
    assert _KEY not in result.output
    assert report.is_file()
    payload = tmp_path / "out.json"
    assert payload.is_file()
    written = json.loads(payload.read_text(encoding="utf-8"))
    assert written["backend"] == "hybrid"
    assert written["model"] == "gpt-4o-mini"
    assert "cost_per_document_usd" in written["sets"][0]
    assert _KEY not in report.read_text(encoding="utf-8")
    assert _KEY not in payload.read_text(encoding="utf-8")

    priced = tmp_path / "priced.md"
    before = len(calls)
    refused = runner.invoke(
        app,
        [
            "eval",
            "--backend",
            "llm",
            "--live",
            "--model",
            "gpt-test",
            "--fixtures",
            str(corpus),
            "--report",
            str(priced),
        ],
    )
    assert refused.exit_code == 2
    assert "no list price" in refused.stderr
    assert _KEY not in refused.output
    assert len(calls) == before


def test_live_eval_sets_the_openmp_limit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)

    def stop(*args: object, **kwargs: object) -> object:
        assert os.environ["OMP_THREAD_LIMIT"] == "1"
        raise RuntimeError("stop")

    monkeypatch.setattr("k1lens.eval.live._run_live", stop)
    with pytest.raises(RuntimeError, match="stop"):
        run_live(
            [],
            backend="deterministic",
            report_md=tmp_path / "live.md",
            report_json=tmp_path / "live.json",
        )

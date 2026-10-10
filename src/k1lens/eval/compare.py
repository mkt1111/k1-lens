"""Score deterministic, model-only, and hybrid extraction on one corpus."""

from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.eval.harness import evaluate
from k1lens.eval.metrics import Counts
from k1lens.extract.base import Extractor
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.hybrid import HybridExtractor
from k1lens.extract.llm import LLMExtractor, llm_configured
from k1lens.validate.engine import DEFAULT_TOLERANCE


@dataclass(frozen=True, slots=True)
class BackendResult:
    backend: str
    skipped: bool
    reason: str
    accuracy: str
    precision: str
    confident_wrong: int | None
    documents: int | None
    latency_seconds: float | None
    latency_per_document: float | None
    estimated_cost_usd: float | None
    cost_per_document_usd: float | None
    llm_calls: int
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class SetComparison:
    distribution: str
    fixture_dir: str
    live_model: bool
    backends: tuple[BackendResult, ...]


def compare_set(
    fixture_dir: Path,
    *,
    distribution: str,
    threshold: float = REVIEW_THRESHOLD,
    tolerance: Decimal = DEFAULT_TOLERANCE,
    client: httpx.Client | None = None,
    roster: object | None = None,
    roster_path: str = "",
) -> SetComparison:
    """Run the three backends. With no key and no client, the model row is skipped."""

    live = client is not None or llm_configured()
    deterministic = _score(
        "deterministic",
        DeterministicExtractor(),
        fixture_dir,
        distribution=distribution,
        threshold=threshold,
        tolerance=tolerance,
        roster=roster,
        roster_path=roster_path,
    )
    if not live:
        model = _skipped("llm", "no API key is set")
        hybrid_engine: Extractor = HybridExtractor()
    else:
        model = _score(
            "llm",
            LLMExtractor(client=client),
            fixture_dir,
            distribution=distribution,
            threshold=threshold,
            tolerance=tolerance,
            roster=roster,
            roster_path=roster_path,
        )
        hybrid_engine = HybridExtractor(client=client)
    hybrid = _score(
        "hybrid",
        hybrid_engine,
        fixture_dir,
        distribution=distribution,
        threshold=threshold,
        tolerance=tolerance,
        roster=roster,
        roster_path=roster_path,
    )
    return SetComparison(
        distribution=distribution,
        fixture_dir=str(fixture_dir),
        live_model=live,
        backends=(deterministic, model, hybrid),
    )


def render_comparison(sections: list[SetComparison]) -> str:
    live = any(section.live_model for section in sections)
    if live:
        banner = (
            "This run called a model. Cost is a list-price estimate from the token "
            "counts in the response, not an invoice. An unpriced model leaves cost blank."
        )
    else:
        banner = (
            "No live model call was made. No API key is set, so the LLM-only backend "
            "was skipped and hybrid used the deterministic extractor. "
            "`uv run k1lens eval --backend hybrid --live` is the command that calls "
            "OpenAI once OPENAI_API_KEY is set. No live run has been checked in."
        )
    lines = [
        "# Backend comparison",
        "",
        banner,
        "",
        "Accuracy is `(correct + both null) / comparisons`. "
        "Precision is `correct / (correct + mismatch + spurious)`. "
        "A confident wrong value is a mismatch or a spurious extraction at or above "
        "the review threshold.",
        "",
    ]
    for section in sections:
        lines.extend(
            [
                f"## {section.distribution}",
                "",
                f"Fixtures: `{section.fixture_dir}`.",
                "",
                "| Backend | Accuracy | Precision | Confident wrong | "
                "Cost / document | Latency | LLM calls |",
                "| --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for row in section.backends:
            lines.append(
                "| "
                + " | ".join(
                    [
                        row.backend,
                        row.reason if row.skipped else row.accuracy,
                        "" if row.skipped else row.precision,
                        "" if row.confident_wrong is None else str(row.confident_wrong),
                        _money(row.cost_per_document_usd),
                        _latency(row),
                        str(row.llm_calls),
                    ]
                )
                + " |"
            )
        lines.append("")
    return "\n".join(lines)


def _score(
    backend: str,
    extractor: Extractor,
    fixture_dir: Path,
    *,
    distribution: str,
    threshold: float,
    tolerance: Decimal,
    roster: object | None = None,
    roster_path: str = "",
) -> BackendResult:
    from k1lens.roster import Roster

    started = time.perf_counter()
    loaded = roster if isinstance(roster, Roster) else None
    report = evaluate(
        fixture_dir,
        backend=backend,
        tolerance=tolerance,
        extractor=extractor,
        threshold=threshold,
        distribution=distribution,
        roster=loaded,
        roster_path=roster_path,
    )
    elapsed = time.perf_counter() - started
    usage = getattr(extractor, "usage", None)
    calls = int(getattr(usage, "calls", 0))
    input_tokens = int(getattr(usage, "input_tokens", 0))
    output_tokens = int(getattr(usage, "output_tokens", 0))
    cost = getattr(usage, "estimated_cost_usd", 0.0)
    if not isinstance(cost, int | float):
        cost_value: float | None = None
    else:
        cost_value = float(cost)
    per_doc_cost = _per(cost_value, report.documents)
    per_doc_latency = _per(elapsed, report.documents)
    return BackendResult(
        backend=backend,
        skipped=False,
        reason="",
        accuracy=_accuracy(report.overall),
        precision=_precision(report.overall),
        confident_wrong=len(report.confident_wrong),
        documents=report.documents,
        latency_seconds=elapsed,
        latency_per_document=per_doc_latency,
        estimated_cost_usd=cost_value,
        cost_per_document_usd=per_doc_cost,
        llm_calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def _skipped(backend: str, reason: str) -> BackendResult:
    return BackendResult(
        backend=backend,
        skipped=True,
        reason=reason,
        accuracy="",
        precision="",
        confident_wrong=None,
        documents=None,
        latency_seconds=None,
        latency_per_document=None,
        estimated_cost_usd=None,
        cost_per_document_usd=None,
        llm_calls=0,
        input_tokens=0,
        output_tokens=0,
    )


def _accuracy(counts: Counts) -> str:
    if counts.accuracy is None:
        return "n/a"
    return f"{counts.accuracy * 100:.1f}% ({counts.correct + counts.both_null}/{counts.total})"


def _precision(counts: Counts) -> str:
    if counts.precision is None:
        return "n/a"
    denominator = counts.correct + counts.mismatch + counts.spurious
    return f"{counts.precision * 100:.1f}% ({counts.correct}/{denominator})"


def _per(total: float | None, documents: int) -> float | None:
    if total is None or documents <= 0:
        return None
    return total / documents


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.6f}"


def _latency(row: BackendResult) -> str:
    if row.latency_seconds is None or row.latency_per_document is None:
        return "n/a"
    return f"{row.latency_seconds:.2f}s ({row.latency_per_document:.2f}s/doc)"

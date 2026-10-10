"""Live model eval. One command, a hard spend ceiling, and a report to commit.

The command does not print the API key or request headers. Tests pass a
recorded client. Nothing in this module calls the network by itself.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

import httpx

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import CODED_BOXES, REVIEW_THRESHOLD, SCALAR_FIELDS
from k1lens.domain.models import ScheduleK1
from k1lens.eval.harness import EvalReport, evaluate
from k1lens.eval.metrics import Counts, judgments_for
from k1lens.extract.base import SpendCeilingExceeded
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.extract.hybrid import DocumentTrace, HybridExtractor
from k1lens.extract.llm import (
    DEFAULT_OPENAI_MODEL,
    DEFAULT_SPEND_CEILING_USD,
    LLMExtractor,
    SpendGuard,
    estimate_cost_usd,
)
from k1lens.extract.ocr import limit_openmp_threads
from k1lens.extract.redact import redact_secrets
from k1lens.generate.corpus import load_ground_truth, load_manifest
from k1lens.generate.ensure import ensure_corpus
from k1lens.roster import Roster
from k1lens.validate.engine import DEFAULT_TOLERANCE

LIVE_MARKDOWN = Path("docs/eval-live/report.md")
LIVE_JSON = Path("docs/eval-live/report.json")


@dataclass(frozen=True, slots=True)
class LiveField:
    field: str
    deterministic_value: str | None
    deterministic_confidence: float | None
    llm_value: str | None
    final_value: str | None
    final_confidence: float | None
    correct: bool


@dataclass(frozen=True, slots=True)
class LiveDocument:
    document_id: str
    pages: int
    llm_calls: int
    fields_requested: int
    malformed: bool
    estimated_cost_usd: float | None
    cost_per_page_usd: float | None
    hybrid_accuracy: str
    deterministic_accuracy: str
    hybrid_precision: str
    deterministic_precision: str
    hybrid_straight_through: bool
    deterministic_straight_through: bool
    hybrid_confident_wrong: int
    deterministic_confident_wrong: int
    fields: tuple[LiveField, ...]


@dataclass(frozen=True, slots=True)
class LiveSet:
    distribution: str
    fixture_dir: str
    documents: int
    accuracy: float | None
    accuracy_label: str
    precision: float | None
    precision_label: str
    confident_wrong: int
    straight_through: int
    straight_through_rate: float | None
    input_tokens: int
    output_tokens: int
    estimated_cost_usd: float | None
    cost_per_document_usd: float | None
    cost_per_page_usd: float | None
    llm_calls: int
    malformed_calls: int
    fields_requested: int
    detail: tuple[LiveDocument, ...]
    latency_seconds: float


@dataclass(frozen=True, slots=True)
class LiveRun:
    backend: str
    model: str
    spend_ceiling_usd: float
    max_documents: int | None
    estimated_cost_usd: float
    input_tokens: int
    output_tokens: int
    latency_seconds: float
    stopped: str
    sets: tuple[LiveSet, ...]

    def to_json(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "model": self.model,
            "spend_ceiling_usd": self.spend_ceiling_usd,
            "max_documents": self.max_documents,
            "estimated_cost_usd": self.estimated_cost_usd,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "llm_calls": sum(row.llm_calls for row in self.sets),
            "malformed_calls": sum(row.malformed_calls for row in self.sets),
            "fields_requested": sum(row.fields_requested for row in self.sets),
            "latency_seconds": self.latency_seconds,
            "stopped": self.stopped or None,
            "sets": [
                {
                    "distribution": row.distribution,
                    "fixture_dir": row.fixture_dir,
                    "documents": row.documents,
                    "accuracy": row.accuracy,
                    "precision": row.precision,
                    "confident_wrong": row.confident_wrong,
                    "straight_through": row.straight_through,
                    "straight_through_rate": row.straight_through_rate,
                    "input_tokens": row.input_tokens,
                    "output_tokens": row.output_tokens,
                    "estimated_cost_usd": row.estimated_cost_usd,
                    "cost_per_document_usd": row.cost_per_document_usd,
                    "cost_per_page_usd": row.cost_per_page_usd,
                    "llm_calls": row.llm_calls,
                    "malformed_calls": row.malformed_calls,
                    "fields_requested": row.fields_requested,
                    "latency_seconds": row.latency_seconds,
                    "detail": [_document_json(item) for item in row.detail],
                }
                for row in self.sets
            ],
        }


def run_live(
    targets: list[tuple[str, Path, str]],
    *,
    backend: str,
    report_md: Path,
    report_json: Path,
    model: str = DEFAULT_OPENAI_MODEL,
    ceiling_usd: float = DEFAULT_SPEND_CEILING_USD,
    max_documents: int | None = None,
    threshold: float = REVIEW_THRESHOLD,
    tolerance: Decimal = DEFAULT_TOLERANCE,
    client: httpx.Client | None = None,
    roster: Roster | None = None,
    roster_path: str = "",
) -> LiveRun:
    """Score ``targets`` and write markdown plus JSON. Returns the run."""

    limit_openmp_threads()
    saved = {name: os.environ.get(name) for name in ("K1LENS_OPENAI_MODEL", "K1LENS_LLM_PROVIDER")}
    try:
        return _run_live(
            targets,
            backend=backend,
            report_md=report_md,
            report_json=report_json,
            model=model,
            ceiling_usd=ceiling_usd,
            max_documents=max_documents,
            threshold=threshold,
            tolerance=tolerance,
            client=client,
            roster=roster,
            roster_path=roster_path,
        )
    finally:
        for name, value in saved.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def _run_live(
    targets: list[tuple[str, Path, str]],
    *,
    backend: str,
    report_md: Path,
    report_json: Path,
    model: str,
    ceiling_usd: float,
    max_documents: int | None,
    threshold: float,
    tolerance: Decimal,
    client: httpx.Client | None,
    roster: Roster | None,
    roster_path: str,
) -> LiveRun:
    spend = SpendGuard(ceiling_usd)
    engine = _engine(backend, client=client, spend=spend, model=model)
    rows: list[LiveSet] = []
    stopped = ""
    trace_at = 0
    if estimate_cost_usd(model, 1, 1) is None:
        stopped = (
            f"Model {model} has no list price in this repo, so the spend ceiling "
            "cannot be enforced."
        )
    else:
        for distribution, path, kind in targets:
            if stopped:
                break
            if spend.spent_usd >= spend.ceiling_usd - 1e-9:
                stopped = str(SpendCeilingExceeded(spend.spent_usd, spend.ceiling_usd))
                break
            if not (path / "manifest.json").is_file():
                ensure_corpus(path, kind)
            before_in = engine.usage.input_tokens
            before_out = engine.usage.output_tokens
            before_cost = engine.usage.estimated_cost_usd
            before_calls = engine.usage.calls
            before_malformed = engine.usage.malformed_calls
            started = time.perf_counter()
            scored = evaluate(
                path,
                backend=backend,
                tolerance=tolerance,
                extractor=engine,
                threshold=threshold,
                distribution=distribution,
                max_documents=max_documents,
                roster=roster,
                roster_path=roster_path,
            )
            elapsed = time.perf_counter() - started
            traces: tuple[DocumentTrace, ...] = ()
            if isinstance(engine, HybridExtractor):
                traces = tuple(engine.traces[trace_at:])
                trace_at = len(engine.traces)
            deterministic = None
            if scored.documents > 0:
                deterministic = evaluate(
                    path,
                    backend="deterministic",
                    tolerance=tolerance,
                    extractor=DeterministicExtractor(),
                    threshold=threshold,
                    distribution=distribution,
                    max_documents=scored.documents,
                    roster=roster,
                    roster_path=roster_path,
                )
            rows.append(
                _set_row(
                    scored,
                    input_tokens=engine.usage.input_tokens - before_in,
                    output_tokens=engine.usage.output_tokens - before_out,
                    cost=_delta_cost(before_cost, engine.usage.estimated_cost_usd),
                    latency_seconds=elapsed,
                    llm_calls=engine.usage.calls - before_calls,
                    malformed_calls=engine.usage.malformed_calls - before_malformed,
                    traces=traces,
                    deterministic=deterministic,
                    tolerance=tolerance,
                )
            )
            if scored.stopped_reason:
                stopped = scored.stopped_reason
    result = LiveRun(
        backend=backend,
        model=model,
        spend_ceiling_usd=ceiling_usd,
        max_documents=max_documents,
        estimated_cost_usd=spend.spent_usd,
        input_tokens=engine.usage.input_tokens,
        output_tokens=engine.usage.output_tokens,
        latency_seconds=sum(row.latency_seconds for row in rows),
        stopped=stopped,
        sets=tuple(rows),
    )
    report_md.parent.mkdir(parents=True, exist_ok=True)
    text = redact_secrets(render_live(result))
    payload = redact_secrets(json.dumps(result.to_json(), indent=2) + "\n")
    report_md.write_text(text, encoding="utf-8")
    report_json.write_text(payload, encoding="utf-8")
    return result


def render_live(run: LiveRun) -> str:
    stopped = run.stopped or "no"
    cap = "all" if run.max_documents is None else str(run.max_documents)
    lines = [
        "# Live evaluation",
        "",
        "Produced by `uv run k1lens eval --backend hybrid --live`.",
        "Cost is a list-price estimate from token counts, not an invoice.",
        "The API key and request headers are not written here.",
        "A numeric model proposal is stored only when the rules value is missing "
        "and that string appears in the field's own label region. A disagreeing "
        "model value is not stored. Its confidence is never raised: if the model "
        "said 0.30, the stored score stays at most 0.30, and a filled gap stays "
        "under the review threshold. A model identity value stays under 0.80. "
        "Name, street, city, state, and ZIP are lifted to exactly the review "
        "threshold, and not higher, only when the key id is a confident read and "
        "every field in that section matches the same roster record from its own "
        "region. A partial match lifts nothing. The stored value is the page "
        "string, and each lifted field is an audit row with reason "
        "roster_exact_match. Llm mode never clears a field. Every llm value "
        "goes to review.",
        "The LLM-only path stops on a persistent 5xx after one retry, on a timeout "
        "at the first failure, and on a malformed reply after one retry. Hybrid keeps "
        "the deterministic values in those three cases and the run continues. A 200 "
        "whose body is not JSON is a malformed reply.",
        "A 429 is retried once. If it fails again, the run stops and the stopped "
        "reason includes that status. Any other request failure stops the run on the "
        "first failure, and the stopped reason names the exception class.",
        "Page images are attached at low detail only when the PDF has no text layer.",
        "",
        f"- Backend: `{run.backend}`",
        f"- Model: `{run.model}`",
        f"- Spend ceiling: ${run.spend_ceiling_usd:.2f}",
        f"- Estimated spend: ${run.estimated_cost_usd:.6f}",
        f"- Max documents per set: {cap}",
        f"- Input tokens: {run.input_tokens}",
        f"- Output tokens: {run.output_tokens}",
        f"- LLM calls: {sum(row.llm_calls for row in run.sets)}",
        f"- Malformed replies: {sum(row.malformed_calls for row in run.sets)}",
        f"- Fields requested: {sum(row.fields_requested for row in run.sets)}",
        f"- Latency: {run.latency_seconds:.2f}s",
        f"- Stopped: {stopped}",
        "",
        "| Set | Documents | Accuracy | Precision | Confident wrong | "
        "Straight-through | Tokens in | Tokens out | LLM calls | Malformed | "
        "Fields requested | Cost / document | Cost / page | Latency |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in run.sets:
        rate = _rate(row.straight_through_rate, row.straight_through, row.documents)
        lines.append(
            "| "
            + " | ".join(
                [
                    row.distribution,
                    str(row.documents),
                    row.accuracy_label,
                    row.precision_label,
                    str(row.confident_wrong),
                    rate,
                    str(row.input_tokens),
                    str(row.output_tokens),
                    str(row.llm_calls),
                    str(row.malformed_calls),
                    str(row.fields_requested),
                    _money(row.cost_per_document_usd),
                    _money(row.cost_per_page_usd),
                    f"{row.latency_seconds:.2f}s",
                ]
            )
            + " |"
        )
    for row in run.sets:
        lines.extend(_set_detail(row, run.backend))
    lines.append("")
    return "\n".join(lines)


def _set_detail(row: LiveSet, backend: str) -> list[str]:
    lines = [
        "",
        f"## {row.distribution}",
        "",
        f"### {backend} vs deterministic",
        "",
        "| Document | Pages | LLM calls | Fields requested | Malformed | "
        f"{backend} accuracy | Deterministic accuracy | {backend} precision | "
        "Deterministic precision | "
        f"{backend} straight-through | Deterministic straight-through | "
        f"{backend} confident wrong | Deterministic confident wrong | "
        "Cost | Cost / page |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | "
        "--- | --- | --- | --- | --- | --- | --- |",
    ]
    for item in row.detail:
        lines.append(
            "| "
            + " | ".join(
                [
                    item.document_id,
                    str(item.pages),
                    str(item.llm_calls),
                    str(item.fields_requested),
                    "yes" if item.malformed else "no",
                    item.hybrid_accuracy,
                    item.deterministic_accuracy,
                    item.hybrid_precision,
                    item.deterministic_precision,
                    "yes" if item.hybrid_straight_through else "no",
                    "yes" if item.deterministic_straight_through else "no",
                    str(item.hybrid_confident_wrong),
                    str(item.deterministic_confident_wrong),
                    _money(item.estimated_cost_usd),
                    _money(item.cost_per_page_usd),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "### Fields",
            "",
            "| Document | Field | Deterministic | Det confidence | LLM | "
            "Final | Final confidence | Correct |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for item in row.detail:
        for field in item.fields:
            lines.append(
                "| "
                + " | ".join(
                    [
                        item.document_id,
                        field.field,
                        _md(field.deterministic_value),
                        _conf(field.deterministic_confidence),
                        _md(field.llm_value),
                        _md(field.final_value),
                        _conf(field.final_confidence),
                        "yes" if field.correct else "no",
                    ]
                )
                + " |"
            )
    return lines


def _engine(
    backend: str,
    *,
    client: httpx.Client | None,
    spend: SpendGuard,
    model: str,
) -> HybridExtractor | LLMExtractor:
    os.environ["K1LENS_OPENAI_MODEL"] = model
    os.environ["K1LENS_LLM_PROVIDER"] = "openai"
    if backend == "llm":
        return LLMExtractor(client=client, spend=spend, provider="openai", vision=True)
    return HybridExtractor(client=client, spend=spend, provider="openai", vision=True)


def _set_row(
    report: EvalReport,
    *,
    input_tokens: int,
    output_tokens: int,
    cost: float | None,
    latency_seconds: float,
    llm_calls: int,
    malformed_calls: int,
    traces: tuple[DocumentTrace, ...],
    deterministic: EvalReport | None,
    tolerance: Decimal,
) -> LiveSet:
    per_doc = None if cost is None or report.documents <= 0 else cost / report.documents
    rate = None if report.documents <= 0 else report.straight_through / report.documents
    documents = _live_documents(report, deterministic, traces, tolerance)
    pages = sum(item.pages for item in documents)
    per_page = None if cost is None or pages <= 0 else cost / pages
    return LiveSet(
        distribution=report.distribution,
        fixture_dir=report.fixture_dir,
        documents=report.documents,
        accuracy=report.overall.accuracy,
        accuracy_label=_accuracy(report.overall),
        precision=report.overall.precision,
        precision_label=_precision(report.overall),
        confident_wrong=len(report.confident_wrong),
        straight_through=report.straight_through,
        straight_through_rate=rate,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        estimated_cost_usd=cost,
        cost_per_document_usd=per_doc,
        cost_per_page_usd=per_page,
        llm_calls=llm_calls,
        malformed_calls=malformed_calls,
        fields_requested=sum(len(trace.requested) for trace in traces),
        detail=documents,
        latency_seconds=latency_seconds,
    )


def _delta_cost(before: float | None, after: float | None) -> float | None:
    if before is None or after is None:
        return None
    return after - before


def _accuracy(counts: Counts) -> str:
    if counts.accuracy is None:
        return "n/a"
    hit = counts.correct + counts.both_null
    return f"{counts.accuracy * 100:.1f}% ({hit}/{counts.total})"


def _precision(counts: Counts) -> str:
    if counts.precision is None:
        return "n/a"
    denominator = counts.correct + counts.mismatch + counts.spurious
    return f"{counts.precision * 100:.1f}% ({counts.correct}/{denominator})"


def _money(value: float | None) -> str:
    if value is None:
        return "n/a"
    return f"${value:.6f}"


def _rate(rate: float | None, numerator: int, denominator: int) -> str:
    if rate is None:
        return "n/a"
    return f"{rate * 100:.1f}% ({numerator}/{denominator})"


def _live_documents(
    report: EvalReport,
    deterministic: EvalReport | None,
    traces: tuple[DocumentTrace, ...],
    tolerance: Decimal,
) -> tuple[LiveDocument, ...]:
    det_by_id = {}
    if deterministic is not None:
        det_by_id = {item.document_id: item for item in deterministic.by_document}
    trace_by_id = {trace.document_id: trace for trace in traces}
    gold = _gold_by_id(Path(report.fixture_dir))
    rows: list[LiveDocument] = []
    for item in report.by_document:
        trace = trace_by_id.get(item.document_id)
        other = det_by_id.get(item.document_id)
        pages = trace.pages if trace is not None else 1
        cost = trace.estimated_cost_usd if trace is not None else None
        per_page = None if cost is None or pages <= 0 else cost / pages
        fields: tuple[LiveField, ...] = ()
        if trace is not None and item.document_id in gold:
            fields = _field_rows(trace, gold[item.document_id], tolerance, item.variant)
        rows.append(
            LiveDocument(
                document_id=item.document_id,
                pages=pages,
                llm_calls=trace.llm_calls if trace is not None else 0,
                fields_requested=len(trace.requested) if trace is not None else 0,
                malformed=trace.malformed if trace is not None else False,
                estimated_cost_usd=cost,
                cost_per_page_usd=per_page,
                hybrid_accuracy=_accuracy(item.counts),
                deterministic_accuracy=_accuracy(other.counts) if other is not None else "n/a",
                hybrid_precision=_precision(item.counts),
                deterministic_precision=_precision(other.counts) if other is not None else "n/a",
                hybrid_straight_through=item.straight_through,
                deterministic_straight_through=(
                    other.straight_through if other is not None else False
                ),
                hybrid_confident_wrong=_wrong(report, item.document_id),
                deterministic_confident_wrong=_wrong(deterministic, item.document_id),
                fields=fields,
            )
        )
    return tuple(rows)


def _gold_by_id(fixture_dir: Path) -> dict[str, ScheduleK1]:
    if not (fixture_dir / "manifest.json").is_file():
        return {}
    found: dict[str, ScheduleK1] = {}
    for entry in load_manifest(fixture_dir).documents:
        found[entry.document_id] = load_ground_truth(fixture_dir / entry.ground_truth).document
    return found


def _field_rows(
    trace: DocumentTrace,
    gold: ScheduleK1,
    tolerance: Decimal,
    variant: str,
) -> tuple[LiveField, ...]:
    judged = {
        item.path: item.outcome
        for item in judgments_for(
            gold, trace.final, tolerance, variant=variant, document_id=trace.document_id
        )
    }
    deterministic = _values(trace.deterministic)
    model = _values(trace.llm) if trace.llm is not None else {}
    final = _values(trace.final)
    rows: list[LiveField] = []
    for path in judged:
        det_value, det_confidence = deterministic.get(path, (None, None))
        llm_value, _llm_confidence = model.get(path, (None, None))
        final_value, final_confidence = final.get(path, (None, None))
        rows.append(
            LiveField(
                field=path,
                deterministic_value=det_value,
                deterministic_confidence=det_confidence,
                llm_value=llm_value,
                final_value=final_value,
                final_confidence=final_confidence,
                correct=judged[path] in {"correct", "both_null"},
            )
        )
    return tuple(rows)


def _values(document: ScheduleK1) -> dict[str, tuple[str | None, float | None]]:
    found: dict[str, tuple[str | None, float | None]] = {
        "tax_year": (_cell(document.tax_year), document.tax_year_confidence)
    }
    for spec in SCALAR_FIELDS:
        field = get_extracted(document, spec.path)
        found[spec.path] = (_cell(field.value), field.confidence)
    for box in CODED_BOXES:
        grouped: dict[str, list[tuple[str | None, float]]] = {}
        for item in get_coded(document, box.path):
            grouped.setdefault(item.code, []).append(
                (_cell(item.amount.value), item.amount.confidence)
            )
        for code, amounts in grouped.items():
            for index, (value, confidence) in enumerate(amounts, start=1):
                key = f"{box.path}[{code}]"
                if len(amounts) > 1:
                    key = f"{key}#{index}"
                found[key] = (value, confidence)
    return found


def _wrong(report: EvalReport | None, document_id: str) -> int:
    if report is None:
        return 0
    return sum(1 for item in report.confident_wrong if item.document_id == document_id)


def _document_json(item: LiveDocument) -> dict[str, object]:
    return {
        "document_id": item.document_id,
        "pages": item.pages,
        "llm_calls": item.llm_calls,
        "fields_requested": item.fields_requested,
        "malformed": item.malformed,
        "estimated_cost_usd": item.estimated_cost_usd,
        "cost_per_page_usd": item.cost_per_page_usd,
        "hybrid_accuracy": item.hybrid_accuracy,
        "deterministic_accuracy": item.deterministic_accuracy,
        "hybrid_precision": item.hybrid_precision,
        "deterministic_precision": item.deterministic_precision,
        "hybrid_straight_through": item.hybrid_straight_through,
        "deterministic_straight_through": item.deterministic_straight_through,
        "hybrid_confident_wrong": item.hybrid_confident_wrong,
        "deterministic_confident_wrong": item.deterministic_confident_wrong,
        "fields": [
            {
                "field": field.field,
                "deterministic_value": field.deterministic_value,
                "deterministic_confidence": field.deterministic_confidence,
                "llm_value": field.llm_value,
                "final_value": field.final_value,
                "final_confidence": field.final_confidence,
                "correct": field.correct,
            }
            for field in item.fields
        ],
    }


def _cell(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _md(value: str | None) -> str:
    if value is None:
        return ""
    return value.replace("|", "\\|").replace("\n", " ")


def _conf(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.4f}"

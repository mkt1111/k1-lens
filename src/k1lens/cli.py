"""Command line for generate, extract, validate, eval, and serve."""

from __future__ import annotations

import json
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Annotated

import typer
import uvicorn

from k1lens import __version__
from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.eval.baseline import baseline_failures, load_floors
from k1lens.eval.compare import SetComparison, compare_set, render_comparison
from k1lens.eval.harness import evaluate
from k1lens.eval.live import LIVE_JSON, LIVE_MARKDOWN, run_live
from k1lens.eval.report import counts_line, render_report
from k1lens.extract.factory import get_extractor, llm_configured
from k1lens.extract.llm import DEFAULT_OPENAI_MODEL, DEFAULT_SPEND_CEILING_USD
from k1lens.extract.ocr import limit_openmp_threads
from k1lens.generate.corpus import DEFAULT_SEED, generate_corpus, load_manifest
from k1lens.generate.dev_b import generate_dev_b
from k1lens.generate.dev_layouts import generate_dev
from k1lens.generate.ensure import ensure_corpus
from k1lens.generate.geometry import generate_dev_geometry
from k1lens.generate.scans import FAILURE_COUNT, SCAN_COUNT, generate_scans
from k1lens.review.app import create_app
from k1lens.review.store import verify_database
from k1lens.roster import Roster, bind_roster, dump_roster, load_roster, roster_from_fixture_dir
from k1lens.validate.engine import validate_payload


def _tolerance_amount(text: str) -> Decimal:
    """Parse a dollar tolerance. A bad token is a one-line error, not a traceback."""

    try:
        return Decimal(text)
    except InvalidOperation:
        typer.echo(f"Not a number: {text}", err=True)
        raise typer.Exit(code=2) from None


RosterOption = Annotated[
    Path | None,
    typer.Option(
        "--roster",
        help=(
            "Client roster JSON. Partnership rows match the EIN. Investor rows "
            "match the partner TIN. Without this file, identity fields stay in review."
        ),
        envvar="K1LENS_ROSTER",
    ),
]


def _load_cli_roster(path: Path | None) -> tuple[Roster | None, str]:
    if path is None:
        return None, ""
    if not path.is_file():
        typer.echo(f"No roster file at {path}.", err=True)
        raise typer.Exit(code=2)
    try:
        return load_roster(path), str(path)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        typer.echo(f"Roster {path}: {exc}", err=True)
        raise typer.Exit(code=2) from None


def _threshold_in_range(value: float) -> float:
    """Reject a review threshold outside 0 to 1, including NaN."""

    if value != value or value < 0.0 or value > 1.0:
        raise typer.BadParameter("threshold must be between 0 and 1")
    return value


app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Extract, validate, and review synthetic IRS Schedule K-1 (Form 1065) documents.",
)


def _version(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit


@app.callback()
def callback(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_version, is_eager=True, help="Print the version and exit."
        ),
    ] = False,
) -> None:
    """K1-Lens uses synthetic documents only."""


@app.command()
def generate(
    out: Annotated[
        Path, typer.Option("--out", help="Directory for PDFs, ground truth, and manifest.")
    ] = Path("fixtures/synthetic"),
    seed: Annotated[
        int, typer.Option("--seed", help="RNG seed. The same seed rewrites the same corpus.")
    ] = DEFAULT_SEED,
    count: Annotated[int, typer.Option("--count", help="How many documents to write.")] = 14,
    dev: Annotated[
        bool,
        typer.Option(
            "--dev",
            help="Write the development layouts instead of the in-distribution corpus.",
        ),
    ] = False,
    dev_b: Annotated[
        bool,
        typer.Option(
            "--dev-b",
            help="Write the fund-administrator development set.",
        ),
    ] = False,
    dev_geometry: Annotated[
        bool,
        typer.Option(
            "--dev-geometry",
            help=(
                "Write colon-free development layouts: right-aligned amounts, "
                "a box grid, and two columns. Seen development set, not held-out."
            ),
        ),
    ] = False,
    scans: Annotated[
        bool,
        typer.Option(
            "--scans",
            help=(
                "Write image-only scans from the seed. They are not stored in git. "
                f"The default count is {SCAN_COUNT}, plus {FAILURE_COUNT} known-failure pages."
            ),
        ),
    ] = False,
) -> None:
    """Write a seeded synthetic K-1 corpus. Names and EINs are fictitious."""

    selected = sum((dev, dev_b, dev_geometry, scans))
    if selected > 1:
        typer.echo("Choose one of --dev, --dev-b, --dev-geometry, or --scans.", err=True)
        raise typer.Exit(code=2)
    if dev_geometry:
        manifest = generate_dev_geometry(out, seed=seed)
    elif dev_b:
        manifest = generate_dev_b(out, seed=seed)
    elif dev:
        manifest = generate_dev(out, seed=seed)
    elif scans:
        scan_count = SCAN_COUNT if count == 14 else count
        try:
            manifest = generate_scans(out, seed=seed, count=scan_count)
        except ValueError as exc:
            typer.echo(str(exc), err=True)
            raise typer.Exit(code=2) from exc
    else:
        manifest = generate_corpus(out, seed=seed, count=count)
    typer.echo(f"Wrote {manifest.count} synthetic documents to {out} (seed {manifest.seed}).")


@app.command()
def extract(
    fixtures: Annotated[
        Path, typer.Option("--fixtures", help="Corpus directory with manifest.json.")
    ] = Path("fixtures/synthetic"),
    out: Annotated[Path, typer.Option("--out", help="Where to write extracted JSON.")] = Path(
        "out/extracted"
    ),
    backend: Annotated[
        str,
        typer.Option(
            "--backend",
            help="deterministic (default), hybrid (model only for gaps), or llm.",
        ),
    ] = "deterministic",
    roster: RosterOption = None,
) -> None:
    """Extract every PDF in a corpus."""

    loaded, _roster_path = _load_cli_roster(roster)
    if backend == "llm" and not llm_configured():
        typer.echo(
            "LLM backend skipped: no API key is set. The deterministic backend needs no key."
        )
        raise typer.Exit(code=0)
    manifest = load_manifest(fixtures)
    from k1lens.extract.base import ExtractionError

    engine = get_extractor(backend)
    out.mkdir(parents=True, exist_ok=True)
    failed = 0
    for entry in manifest.documents:
        try:
            document = engine.extract(fixtures / entry.pdf)
        except (ExtractionError, OSError, ValueError) as exc:
            typer.echo(f"{entry.document_id}: {exc}", err=True)
            failed += 1
            continue
        document = document.model_copy(
            update={"document_id": entry.document_id, "variant": entry.variant}
        )
        document = bind_roster(document, loaded)
        (out / f"{entry.document_id}.json").write_text(
            document.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )
    if failed:
        typer.echo(f"Skipped {failed} document(s).", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Extracted {manifest.count} documents with {engine.name} into {out}.")


@app.command()
def validate(
    input_dir: Annotated[
        Path, typer.Option("--input", help="Directory of extracted or ground-truth JSON.")
    ] = Path("out/extracted"),
    out: Annotated[Path, typer.Option("--out", help="Directory for findings JSON.")] = Path(
        "out/findings"
    ),
    tolerance: Annotated[
        str,
        typer.Option("--tolerance", help="Absolute dollar tolerance for capital reconciliation."),
    ] = "1.00",
    roster: RosterOption = None,
) -> None:
    """Run the rules engine and write one findings file per document."""

    tolerance_amount = _tolerance_amount(tolerance)
    loaded, _roster_path = _load_cli_roster(roster)

    out.mkdir(parents=True, exist_ok=True)
    paths = sorted(path for path in input_dir.glob("*.json") if path.name != "manifest.json")
    if not paths:
        raise typer.BadParameter(f"No JSON files in {input_dir}")
    errors = 0
    for path in paths:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            typer.echo(f"{path.name}: not valid JSON", err=True)
            raise typer.Exit(code=2) from None
        document_payload = (
            payload["document"] if isinstance(payload, dict) and "document" in payload else payload
        )
        findings = validate_payload(document_payload, tolerance=tolerance_amount, roster=loaded)
        errors += sum(1 for finding in findings if finding.severity.value == "error")
        (out / f"{path.stem}.findings.json").write_text(
            json.dumps([finding.model_dump(mode="json") for finding in findings], indent=2) + "\n",
            encoding="utf-8",
        )
    typer.echo(f"Validated {len(paths)} documents. Error findings: {errors}. Wrote {out}.")


@app.command("eval")
def eval_cmd(
    fixtures: Annotated[Path, typer.Option("--fixtures", help="Corpus directory.")] = Path(
        "fixtures/synthetic"
    ),
    backend: Annotated[str, typer.Option("--backend", help="Extractor backend.")] = "deterministic",
    report: Annotated[Path, typer.Option("--report", help="Markdown report path.")] = Path(
        "docs/eval-report.md"
    ),
    tolerance: Annotated[str, typer.Option("--tolerance")] = "1.00",
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Confidence below this is flagged for review. Must be from 0 to 1.",
            envvar="K1LENS_REVIEW_THRESHOLD",
            callback=_threshold_in_range,
        ),
    ] = REVIEW_THRESHOLD,
    distribution: Annotated[
        str,
        typer.Option(
            "--distribution",
            help="in_distribution, dev, dev_b, dev_geometry, or scans. Selects the baseline block.",
        ),
    ] = "in_distribution",
    baseline: Annotated[
        Path | None,
        typer.Option("--baseline", help="JSON floors. Exit 1 when a headline is below."),
    ] = None,
    compare: Annotated[
        bool,
        typer.Option(
            "--compare",
            help=(
                "Score deterministic, LLM-only, and hybrid without a spend ceiling. "
                "With the default fixtures this runs every set. No API key skips the model."
            ),
        ),
    ] = False,
    live: Annotated[
        bool,
        typer.Option(
            "--live",
            help=(
                "Call OpenAI. Requires OPENAI_API_KEY and nothing else. "
                "Writes docs/eval-live/report.md and docs/eval-live/report.json."
            ),
        ),
    ] = False,
    max_spend: Annotated[
        float,
        typer.Option(
            "--max-spend",
            help="Hard per-run spend ceiling in USD. The next call stops before this.",
        ),
    ] = DEFAULT_SPEND_CEILING_USD,
    max_documents: Annotated[
        int | None,
        typer.Option(
            "--max-documents",
            help="Score at most this many documents in each set.",
        ),
    ] = None,
    model: Annotated[
        str | None,
        typer.Option(
            "--model",
            help=f"OpenAI model. Default {DEFAULT_OPENAI_MODEL}, which accepts page images.",
        ),
    ] = None,
    roster: RosterOption = None,
) -> None:
    """Score extraction against ground truth and write a markdown report."""

    limit_openmp_threads()
    tolerance_amount = _tolerance_amount(tolerance)
    loaded, roster_path = _load_cli_roster(roster)

    if live and compare:
        typer.echo("Use --live or --compare, not both.", err=True)
        raise typer.Exit(code=2)
    if live:
        _run_live_command(
            fixtures=fixtures,
            distribution=distribution,
            backend=backend,
            report=report,
            threshold=threshold,
            tolerance=tolerance_amount,
            max_spend=max_spend,
            max_documents=max_documents,
            model=model or os.environ.get("K1LENS_OPENAI_MODEL", DEFAULT_OPENAI_MODEL),
            roster=loaded,
            roster_path=roster_path,
        )
        return

    if compare:
        if report == Path("docs/eval-report.md"):
            report = Path("out/eval-compare.md")
        sections: list[SetComparison] = []
        for dist, path, kind in _compare_targets(fixtures, distribution):
            if not (path / "manifest.json").is_file():
                ensure_corpus(path, kind, seed=DEFAULT_SEED)
            sections.append(
                compare_set(
                    path,
                    distribution=dist,
                    threshold=threshold,
                    tolerance=tolerance_amount,
                    roster=loaded,
                    roster_path=roster_path,
                )
            )
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(render_comparison(sections), encoding="utf-8")
        typer.echo(f"Compared {len(sections)} set(s). Wrote {report}.")
        if not llm_configured():
            typer.echo(
                "No live model call was made. Set OPENAI_API_KEY or ANTHROPIC_API_KEY "
                "and run k1lens eval --compare again."
            )
        return

    if backend == "llm" and not llm_configured():
        typer.echo("LLM backend skipped: no API key is set.")
        raise typer.Exit(code=0)
    result = evaluate(
        fixtures,
        backend=backend,
        tolerance=tolerance_amount,
        threshold=threshold,
        distribution=distribution,
        roster=loaded,
        roster_path=roster_path,
    )
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(render_report(result), encoding="utf-8")
    catch = f"{result.ground_truth_catch.caught}/{result.ground_truth_catch.expected}"
    summary = f"{result.documents} documents, {counts_line(result.overall)}."
    typer.echo(f"{summary} Ground-truth catch {catch}. Wrote {report}.")
    if baseline is not None:
        failures = baseline_failures(result, load_floors(baseline, distribution))
        if failures:
            for failure in failures:
                typer.echo(failure, err=True)
            raise typer.Exit(code=1)


@app.command()
def serve(
    fixtures: Annotated[
        Path, typer.Option("--fixtures", help="Corpus to ingest when the database is empty.")
    ] = Path("fixtures/synthetic"),
    db: Annotated[Path, typer.Option("--db", help="SQLite path.", envvar="K1LENS_DB")] = Path(
        "data/k1lens.db"
    ),
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8000,
    reingest: Annotated[
        bool,
        typer.Option(
            "--reingest",
            help="Read fixtures into the existing database. Does not delete it.",
        ),
    ] = False,
    no_ingest: Annotated[
        bool, typer.Option("--no-ingest", help="Start without loading fixtures.")
    ] = False,
    threshold: Annotated[
        float,
        typer.Option(
            "--threshold",
            help="Confidence below this is highlighted for review. Must be from 0 to 1.",
            envvar="K1LENS_REVIEW_THRESHOLD",
            callback=_threshold_in_range,
        ),
    ] = REVIEW_THRESHOLD,
    roster: RosterOption = None,
) -> None:
    """Start the review UI and JSON API."""

    loaded, _roster_path = _load_cli_roster(roster)

    if not no_ingest and not (fixtures / "manifest.json").is_file():
        if fixtures == Path("fixtures/synthetic"):
            generate_corpus(fixtures, seed=DEFAULT_SEED, count=14)
            typer.echo(f"Generated {fixtures} from seed {DEFAULT_SEED}.")
        else:
            typer.echo(
                f"No fixture manifest at {fixtures / 'manifest.json'}. "
                "Starting with an empty queue."
            )
    application = create_app(
        db_path=db,
        fixture_dir=fixtures,
        auto_ingest=not no_ingest,
        reingest=reingest,
        threshold=threshold,
        roster=loaded,
    )
    typer.echo(f"K1-Lens review UI at http://{host}:{port}")
    uvicorn.run(application, host=host, port=port)


@app.command("verify-audit")
def verify_audit(
    db: Annotated[Path, typer.Option("--db", help="SQLite path.", envvar="K1LENS_DB")] = Path(
        "data/k1lens.db"
    ),
) -> None:
    """Check the append-only hash chain and the update/delete triggers."""

    if not db.is_file():
        typer.echo(f"No database at {db}.", err=True)
        raise typer.Exit(code=1)
    problems = verify_database(db)
    if problems:
        for problem in problems:
            typer.echo(problem, err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Audit log verified: {db}")


@app.command("write-roster")
def write_roster_cmd(
    fixtures: Annotated[
        Path, typer.Option("--fixtures", help="Corpus whose ground truth supplies identity.")
    ] = Path("fixtures/synthetic"),
    out: Annotated[Path, typer.Option("--out", help="Where to write the roster JSON.")] = Path(
        "out/roster.json"
    ),
) -> None:
    """Copy identity from ground truth into a roster file.

    Those documents' identity was known before scoring. Pass the file to
    ``k1lens eval --roster``. Eval does not build this file.
    """

    if not (fixtures / "manifest.json").is_file():
        typer.echo(f"No fixture manifest at {fixtures / 'manifest.json'}.", err=True)
        raise typer.Exit(code=2)
    built = roster_from_fixture_dir(fixtures)
    payload = dump_roster(built)
    payload["note"] = (
        "Copied from this corpus's ground truth, so those documents' identity "
        "was known before scoring. EINs use the 00- prefix and SSNs use 000-. "
        "Obviously synthetic. Not issued by the IRS or SSA. No real people."
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    typer.echo(
        f"Wrote {len(built.partnerships)} partnerships and {len(built.investors)} "
        f"investors to {out}."
    )


def _run_live_command(
    *,
    fixtures: Path,
    distribution: str,
    backend: str,
    report: Path,
    threshold: float,
    tolerance: Decimal,
    max_spend: float,
    max_documents: int | None,
    model: str,
    roster: Roster | None,
    roster_path: str,
) -> None:
    if backend not in {"hybrid", "llm"}:
        typer.echo("A live eval needs --backend hybrid or --backend llm.", err=True)
        raise typer.Exit(code=2)
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        typer.echo(
            "Set OPENAI_API_KEY to run a live eval. The key is not printed.",
            err=True,
        )
        raise typer.Exit(code=2)
    if max_documents is not None and max_documents < 1:
        typer.echo("--max-documents must be at least 1.", err=True)
        raise typer.Exit(code=2)
    if not math.isfinite(max_spend) or max_spend <= 0:
        typer.echo("--max-spend must be a finite number greater than zero.", err=True)
        raise typer.Exit(code=2)
    markdown = LIVE_MARKDOWN if report == Path("docs/eval-report.md") else report
    payload = LIVE_JSON if markdown == LIVE_MARKDOWN else markdown.with_suffix(".json")
    result = run_live(
        _compare_targets(fixtures, distribution),
        backend=backend,
        report_md=markdown,
        report_json=payload,
        model=model,
        ceiling_usd=max_spend,
        max_documents=max_documents,
        threshold=threshold,
        tolerance=tolerance,
        roster=roster,
        roster_path=roster_path,
    )
    typer.echo(f"Live eval wrote {markdown} and {payload}.")
    typer.echo(
        f"Model {result.model}. Estimated spend ${result.estimated_cost_usd:.6f} "
        f"of ${result.spend_ceiling_usd:.2f}."
    )
    if result.stopped:
        typer.echo(result.stopped, err=True)
        raise typer.Exit(code=2)


def _compare_targets(fixtures: Path, distribution: str) -> list[tuple[str, Path, str]]:
    """Every seeded set, unless the caller pointed at one corpus."""

    if fixtures == Path("fixtures/synthetic") and distribution == "in_distribution":
        return [
            ("in_distribution", Path("fixtures/synthetic"), "synthetic"),
            ("dev", Path("fixtures/dev"), "dev"),
            ("dev_b", Path("fixtures/dev_b"), "dev_b"),
            ("dev_geometry", Path("fixtures/dev_geometry"), "dev_geometry"),
            ("scans", Path("fixtures/scans"), "scans"),
        ]
    kinds = {
        "in_distribution": "synthetic",
        "dev": "dev",
        "dev_b": "dev_b",
        "dev_geometry": "dev_geometry",
        "scans": "scans",
    }
    return [(distribution, fixtures, kinds.get(distribution, "synthetic"))]


def main() -> None:
    app()


if __name__ == "__main__":
    main()

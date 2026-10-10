"""CLI commands."""

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from k1lens.cli import app

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.stdout


def test_generate_extract_validate_eval(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    generated = runner.invoke(
        app, ["generate", "--out", str(corpus), "--seed", "5", "--count", "2"]
    )
    assert generated.exit_code == 0, generated.stdout
    assert (corpus / "manifest.json").is_file()
    extracted = tmp_path / "extracted"
    extract = runner.invoke(
        app,
        [
            "extract",
            "--fixtures",
            str(corpus),
            "--out",
            str(extracted),
            "--backend",
            "deterministic",
        ],
    )
    assert extract.exit_code == 0, extract.stdout
    assert (extracted / "K1-0001.json").is_file()
    findings = tmp_path / "findings"
    validated = runner.invoke(app, ["validate", "--input", str(extracted), "--out", str(findings)])
    assert validated.exit_code == 0, validated.stdout
    assert (findings / "K1-0001.findings.json").is_file()
    report = tmp_path / "report.md"
    evaluated = runner.invoke(app, ["eval", "--fixtures", str(corpus), "--report", str(report)])
    assert evaluated.exit_code == 0, evaluated.stdout
    assert "Accuracy" in report.read_text(encoding="utf-8")


def test_eval_exits_when_a_headline_is_under_the_baseline(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    generated = runner.invoke(
        app, ["generate", "--out", str(corpus), "--seed", "5", "--count", "1"]
    )
    assert generated.exit_code == 0, generated.stdout
    floors = tmp_path / "floors.json"
    floors.write_text(
        '{"in_distribution": {"overall_accuracy": 1.5}}\n',
        encoding="utf-8",
    )
    report = tmp_path / "report.md"
    evaluated = runner.invoke(
        app,
        [
            "eval",
            "--fixtures",
            str(corpus),
            "--report",
            str(report),
            "--baseline",
            str(floors),
            "--distribution",
            "in_distribution",
        ],
    )
    assert evaluated.exit_code == 1
    assert "overall_accuracy" in evaluated.output


def test_eval_command_sets_the_openmp_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OMP_THREAD_LIMIT", raising=False)

    def stop(*args: object, **kwargs: object) -> object:
        assert os.environ["OMP_THREAD_LIMIT"] == "1"
        raise RuntimeError("stop")

    monkeypatch.setattr("k1lens.cli.evaluate", stop)
    result = runner.invoke(
        app,
        ["eval", "--fixtures", str(tmp_path), "--report", str(tmp_path / "report.md")],
    )
    assert result.exit_code != 0
    assert result.exception is not None
    assert "stop" in str(result.exception)


def test_llm_commands_skip_without_a_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("K1LENS_LLM_PROVIDER", raising=False)
    corpus = tmp_path / "corpus"
    runner.invoke(app, ["generate", "--out", str(corpus), "--count", "1"])
    extract = runner.invoke(app, ["extract", "--backend", "llm", "--fixtures", str(corpus)])
    assert extract.exit_code == 0
    assert "skipped" in extract.stdout.lower()
    evaluated = runner.invoke(app, ["eval", "--backend", "llm", "--fixtures", str(corpus)])
    assert evaluated.exit_code == 0
    assert "skipped" in evaluated.stdout.lower()


def test_validate_requires_json(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", "--input", str(tmp_path)])
    assert result.exit_code != 0


def test_serve_does_not_block(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    calls: dict[str, object] = {}

    def fake_run(application: object, host: str, port: int) -> None:
        calls["host"] = host
        calls["port"] = port
        calls["title"] = getattr(application, "title", "")

    monkeypatch.setattr("k1lens.cli.uvicorn.run", fake_run)
    db = tmp_path / "nested" / "k1.db"
    from k1lens.generate.build import Variant, build_document
    from k1lens.review.store import ReviewStore

    store = ReviewStore(db)
    document = build_document(__import__("random").Random(1), 1, Variant.CLEAN)
    store.upsert(document, b"%PDF-1.4", [], actor="system")
    before = store.audit(document.document_id)
    result = runner.invoke(
        app,
        [
            "serve",
            "--reingest",
            "--db",
            str(db),
            "--host",
            "0.0.0.0",
            "--port",
            "8765",
            "--fixtures",
            str(tmp_path / "absent"),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert calls == {"host": "0.0.0.0", "port": 8765, "title": "K1-Lens"}
    assert "empty queue" in result.stdout.lower()
    assert db.is_file()
    again = ReviewStore(db)
    assert again.get(document.document_id) is not None
    assert [entry.action for entry in again.audit(document.document_id)] == [
        entry.action for entry in before
    ]


def test_compare_targets_cover_every_set_unless_one_corpus_is_chosen() -> None:
    from k1lens.cli import _compare_targets

    every = _compare_targets(Path("fixtures/synthetic"), "in_distribution")
    assert [name for name, _path, _kind in every] == [
        "in_distribution",
        "dev",
        "dev_b",
        "dev_geometry",
        "scans",
    ]
    one = _compare_targets(Path("/tmp/k1-one"), "dev_b")
    assert one == [("dev_b", Path("/tmp/k1-one"), "dev_b")]
    unknown = _compare_targets(Path("/tmp/k1-one"), "other")
    assert unknown == [("other", Path("/tmp/k1-one"), "synthetic")]


def test_compare_on_one_corpus_skips_the_model_without_a_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("K1LENS_LLM_PROVIDER", raising=False)
    corpus = tmp_path / "corpus"
    generated = runner.invoke(
        app, ["generate", "--out", str(corpus), "--seed", "5", "--count", "1"]
    )
    assert generated.exit_code == 0, generated.stdout
    report = tmp_path / "compare.md"
    compared = runner.invoke(
        app,
        [
            "eval",
            "--compare",
            "--fixtures",
            str(corpus),
            "--distribution",
            "in_distribution",
            "--report",
            str(report),
        ],
    )
    assert compared.exit_code == 0, compared.stdout
    assert "No live model call was made" in compared.stdout
    text = report.read_text(encoding="utf-8")
    assert "no API key is set" in text
    assert "Cost / document" in text
    assert "Latency" in text


def test_serve_generates_the_default_corpus_when_it_is_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("k1lens.cli.uvicorn.run", lambda *_args, **_kwargs: None)

    def fake_app(**_kwargs: object) -> object:
        return type("App", (), {"title": "K1-Lens"})()

    monkeypatch.setattr("k1lens.cli.create_app", fake_app)
    seen: dict[str, object] = {}

    def fake_generate(dest: Path, seed: int, count: int) -> None:
        seen["dest"] = dest
        seen["seed"] = seed
        seen["count"] = count
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "manifest.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr("k1lens.cli.generate_corpus", fake_generate)
    result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.stdout
    assert seen == {"dest": Path("fixtures/synthetic"), "seed": 1065, "count": 14}
    assert "Generated" in result.stdout


def test_verify_audit_checks_the_chain(tmp_path: Path) -> None:
    missing = runner.invoke(app, ["verify-audit", "--db", str(tmp_path / "absent.db")])
    assert missing.exit_code == 1
    assert "No database" in missing.stderr

    from k1lens.generate.build import Variant, build_document
    from k1lens.review.store import ReviewStore

    db = tmp_path / "audit.db"
    store = ReviewStore(db)
    document = build_document(__import__("random").Random(3), 1, Variant.CLEAN)
    store.upsert(document, b"%PDF-1.4", [], actor="system")
    store.correct(document.document_id, "part_i.city", "Nashville", "Ada Reviewer")
    verified = runner.invoke(app, ["verify-audit", "--db", str(db)])
    assert verified.exit_code == 0, verified.stdout
    assert "Audit log verified" in verified.stdout


def test_threshold_must_be_between_zero_and_one(tmp_path: Path) -> None:
    high = runner.invoke(
        app,
        [
            "eval",
            "--threshold",
            "1.5",
            "--fixtures",
            str(tmp_path),
            "--report",
            str(tmp_path / "r.md"),
        ],
    )
    assert high.exit_code == 2
    assert "between 0 and 1" in high.output
    low = runner.invoke(app, ["serve", "--threshold", "-0.01", "--no-ingest"])
    assert low.exit_code == 2
    assert "between 0 and 1" in low.output


def test_validate_rejects_a_roster_file_that_is_not_a_roster(tmp_path: Path) -> None:
    from k1lens.domain.blank import blank_schedule

    document = blank_schedule("K1-BAD-ROSTER", extractor="deterministic", tax_year=2024)
    source = tmp_path / "extracted"
    source.mkdir()
    (source / "K1-BAD-ROSTER.json").write_text(document.model_dump_json(), encoding="utf-8")
    roster = tmp_path / "not-a-roster.json"
    roster.write_text("[]\n", encoding="utf-8")
    out = tmp_path / "findings"
    result = runner.invoke(
        app,
        [
            "validate",
            "--input",
            str(source),
            "--out",
            str(out),
            "--roster",
            str(roster),
        ],
    )
    assert result.exit_code == 2
    assert "Roster" in result.output
    assert "must be a JSON object" in result.output
    assert not (out / "K1-BAD-ROSTER.findings.json").is_file()

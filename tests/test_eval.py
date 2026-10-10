"""Eval arithmetic and the markdown report."""

import json
import random
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from k1lens.domain.fields import FieldKind
from k1lens.domain.models import ScheduleK1
from k1lens.eval.baseline import _actual, baseline_failures, load_floors
from k1lens.eval.harness import CatchRate, DocumentScore, evaluate
from k1lens.eval.metrics import Counts, Judgment, calibration_buckets, classify, review_flag
from k1lens.eval.report import confident_wrong_lines, known_failure_lines, render_report
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.generate.build import Variant, build_document
from k1lens.generate.corpus import generate_corpus


def test_classify_outcomes() -> None:
    tolerance = Decimal("0.01")
    assert classify(FieldKind.MONEY, None, None, tolerance).both_null == 1
    assert classify(FieldKind.MONEY, Decimal("1"), None, tolerance).missed == 1
    assert classify(FieldKind.MONEY, None, Decimal("1"), tolerance).spurious == 1
    assert classify(FieldKind.MONEY, Decimal("1"), Decimal("1"), tolerance).correct == 1
    assert classify(FieldKind.STRING, "a", "b", tolerance).mismatch == 1


def test_eval_on_a_small_corpus(tmp_path: Path) -> None:
    dest = tmp_path / "eval"
    generate_corpus(
        dest,
        seed=15,
        count=3,
        plan=(Variant.CLEAN, Variant.INCONSISTENT_CAPITAL, Variant.RASTERIZED),
    )
    report = evaluate(dest, backend="deterministic", extractor=DeterministicExtractor())
    text = render_report(report)
    assert "K1-Lens evaluation report" in text
    assert "Synthetic data only" in text
    assert report.documents == 3
    assert report.ground_truth_catch.expected == 1
    assert report.ground_truth_catch.caught == 1
    assert report.by_variant["clean"].accuracy == 1
    assert report.text_layer.accuracy == 1
    assert report.rasterized.total > 0
    assert "By source" in text
    assert "Reliability" in text
    assert "Expected calibration error" in text
    assert "Straight-through" in text
    assert "tax_year" in report.by_field
    assert report.confident_wrong == []
    wrong_rate = report.review_flags["overall"].wrong_rate
    assert wrong_rate is None or 0.0 <= wrong_rate <= 1.0
    raster_rate = report.review_flags["rasterized"].incorrect_rate
    assert raster_rate is None or 0.0 <= raster_rate <= 1.0
    assert "`part_i.ein`" in text


def test_known_failure_section_lists_a_confident_wrong_value() -> None:
    missed = Judgment(
        "scan_hard", "part_i.ein", "missed", 0.0, "ocr", "K1-FAIL-0006", "00-1", "null"
    )
    wrong = Judgment(
        "scan_hard",
        "part_iii.ordinary_business_income",
        "mismatch",
        0.91,
        "ocr",
        "K1-FAIL-0001",
        "100.00",
        "10.00",
    )
    flagged = Judgment(
        "scan_hard",
        "part_i.name",
        "mismatch",
        0.40,
        "ocr",
        "K1-FAIL-0001",
        "SAMPLE",
        "SMPLE",
    )
    score = DocumentScore(
        document_id="K1-FAIL-0001",
        variant="scan_hard",
        layout="catalog",
        dpi=40,
        degradation="failure=low_dpi",
        counts=Counts(correct=1, missed=1, mismatch=2),
        straight_through=False,
        failure="low_dpi",
        errors=(wrong, flagged, missed),
    )
    text = "\n".join(known_failure_lines([score], threshold=0.8))
    assert "Known failure cases" in text
    assert "K1-FAIL-0001" in text
    assert "low_dpi" in text
    assert "100.00" in text
    assert "0.91" in text
    assert "no" in text
    assert "Missed 1 field" in text
    listed = "\n".join(confident_wrong_lines([wrong], threshold=0.8))
    assert "Count: 1." in listed
    assert "ordinary_business_income" in listed
    assert "Count: 0." in "\n".join(confident_wrong_lines([], threshold=0.8))


def test_review_flag_counts_only_low_confidence_errors() -> None:
    items = [
        Judgment("clean", "a", "correct", 0.95, "deterministic"),
        Judgment("rasterized", "b", "mismatch", 0.62, "ocr"),
        Judgment("rasterized", "c", "missed", 0.0, "deterministic"),
        Judgment("clean", "d", "mismatch", 0.95, "deterministic"),
    ]
    flag = review_flag(items)
    assert flag.wrong == 2
    assert flag.wrong_flagged == 1
    assert flag.wrong_rate == pytest.approx(0.5)
    assert flag.incorrect == 3
    assert flag.incorrect_flagged == 2
    buckets = calibration_buckets(items)
    assert buckets[0].label == "0.00-0.19"
    assert buckets[0].errors == 1
    assert buckets[-1].correct == 1
    assert buckets[-1].errors == 1
    assert buckets[1].comparisons == 0
    assert buckets[1].accuracy is None


def test_baseline_failure_names_the_short_metric(tmp_path: Path) -> None:
    from k1lens.eval.baseline import baseline_failures, load_floors

    dest = tmp_path / "tiny"
    generate_corpus(dest, seed=15, count=1, plan=(Variant.CLEAN,))
    report = evaluate(dest, distribution="in_distribution")
    floors_path = tmp_path / "baseline.json"
    floors_path.write_text(
        '{"in_distribution": {"overall_accuracy": 1.5, "note": "impossible"}, '
        '"dev": {"overall_accuracy": 0}}\n',
        encoding="utf-8",
    )
    failures = baseline_failures(report, load_floors(floors_path, "in_distribution"))
    assert len(failures) == 1
    assert "overall_accuracy" in failures[0]
    assert baseline_failures(report, {"overall_accuracy": 0.0}) == []
    assert baseline_failures(report, {"max_confident_wrong": 0.0}) == []
    ceiling = baseline_failures(report, {"max_confident_wrong": -1.0})
    assert ceiling and "ceiling" in ceiling[0]
    missing = baseline_failures(report, {"variant:not_a_variant": 0.5})
    assert missing and "no rate" in missing[0]
    with pytest.raises(ValueError, match="Unknown baseline key"):
        baseline_failures(report, {"not_a_metric": 0.1})
    empty = tmp_path / "empty.json"
    empty.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="in_distribution"):
        load_floors(empty, "in_distribution")
    empty.write_text('{"in_distribution": []}', encoding="utf-8")
    with pytest.raises(ValueError, match="object"):
        load_floors(empty, "in_distribution")
    empty.write_text('{"in_distribution": {"overall_accuracy": "high"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="not a number"):
        load_floors(empty, "in_distribution")


def test_mismatch_lowers_precision(tmp_path: Path) -> None:
    dest = tmp_path / "mismatch"
    generate_corpus(dest, seed=15, count=1, plan=(Variant.CLEAN,))
    truth = build_document(random.Random(0), 1, Variant.CLEAN)

    class Wrong:
        name = "wrong"

        def extract(self, pdf_path: Path, *, threshold: float = 0.8) -> ScheduleK1:
            document = truth.model_copy(deep=True)
            payload = document.model_dump(mode="json")
            payload["part_i"]["ein"]["value"] = "00-9999999"
            payload["document_id"] = "K1-0001"
            return ScheduleK1.model_validate(payload)

    report = evaluate(dest, extractor=Wrong())
    assert report.by_field["part_i.ein"].mismatch == 1
    assert report.overall.precision is not None
    assert report.overall.precision < 1


def test_every_baseline_set_caps_confident_wrong_at_zero() -> None:
    path = Path("docs/eval-baseline.json")
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert set(payload) == {"in_distribution", "dev", "dev_b", "dev_geometry", "scans"}
    for name in payload:
        assert payload[name]["max_confident_wrong"] == 0
        assert load_floors(path, name)["max_confident_wrong"] == 0.0


def test_baseline_reader_enforces_ceilings_and_floors() -> None:
    report = SimpleNamespace(
        text_layer=Counts(correct=10),
        rasterized=Counts(correct=8, missed=2),
        overall=Counts(correct=9, mismatch=1),
        ground_truth_catch=CatchRate(caught=1, expected=1),
        documents=4,
        straight_through=1,
        confident_wrong=[object(), object()],
        by_variant={"layout_shift": Counts(correct=3, missed=1)},
    )
    assert _actual(report, "text_layer_accuracy") == 1
    assert _actual(report, "text_layer_precision") == 1
    assert _actual(report, "rasterized_accuracy") == pytest.approx(0.8)
    assert _actual(report, "rasterized_precision") == 1
    assert _actual(report, "overall_accuracy") == pytest.approx(0.9)
    assert _actual(report, "overall_precision") == pytest.approx(0.9)
    assert _actual(report, "ground_truth_catch_rate") == 1
    assert _actual(report, "min_documents") == 4
    assert _actual(report, "confident_wrong") == 2
    assert _actual(report, "straight_through_rate") == pytest.approx(0.25)
    assert _actual(report, "variant:layout_shift") == pytest.approx(0.75)
    assert _actual(report, "variant_precision:layout_shift") == 1
    assert _actual(report, "variant:absent") is None
    assert _actual(report, "variant_precision:absent") is None
    empty = SimpleNamespace(documents=0, straight_through=0)
    assert _actual(empty, "straight_through_rate") is None
    ceiling = baseline_failures(report, {"max_confident_wrong": 0})
    assert ceiling and "above ceiling" in ceiling[0]
    floor = baseline_failures(report, {"overall_accuracy": 0.99})
    assert floor and "below floor" in floor[0]
    assert baseline_failures(report, {"max_confident_wrong": 2}) == []
    missing = baseline_failures(report, {"variant:absent": 0.5})
    assert missing and "no rate" in missing[0]
    assert baseline_failures(report, {"variant:absent": 0}) == []
    with pytest.raises(ValueError, match="Unknown baseline key"):
        _actual(report, "not_a_key")

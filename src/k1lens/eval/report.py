"""Markdown rendering for an eval report."""

from __future__ import annotations

from k1lens.eval.harness import CatchRate, DocumentScore, EvalReport
from k1lens.eval.metrics import CalibrationBucket, Counts, Judgment, ReviewFlag


def render_report(report: EvalReport) -> str:
    lines = [
        "# K1-Lens evaluation report",
        "",
        *_intro(report),
        "",
        "## Run",
        "",
        f"- Backend: `{report.backend}`",
        f"- Fixtures: `{report.fixture_dir}`",
        f"- Seed: {report.seed}",
        f"- Documents: {report.documents}",
        f"- OCR enabled: {'yes' if report.ocr_enabled else 'no'}",
        f"- Tesseract: {report.tesseract_version or 'not installed'}",
        f"- Roster: {report.roster_path or 'none'}",
        (
            "- Confidently read ids: "
            f"{report.confident_id_sections} of {report.id_sections} sections"
        ),
        f"- Money tolerance: {report.tolerance}",
        f"- Distribution: `{report.distribution}`",
        f"- Review threshold: {report.threshold:.2f}",
        "",
        "## Overall",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Comparisons | {report.overall.total} |",
        f"| Accuracy | {_metric(report.overall, 'accuracy')} |",
        f"| Precision | {_metric(report.overall, 'precision')} |",
        f"| Recall | {_metric(report.overall, 'recall')} |",
        f"| Correct | {report.overall.correct} |",
        f"| Both null | {report.overall.both_null} |",
        f"| Mismatch | {report.overall.mismatch} |",
        f"| Missed | {report.overall.missed} |",
        f"| Spurious | {report.overall.spurious} |",
        f"| Straight-through | {_straight(report)} |",
        "",
        "Straight-through counts documents that need no review. Field accuracy above",
        "counts fields. A document can be field-accurate and still fail a required-field",
        "rule, including a missing tax year.",
        "",
        "## By source",
        "",
        "Text layer is every variant that still has text. Image-only variants are",
        "`rasterized` and `scan_*`. Those pages are read with Tesseract. Overall",
        "is the two together.",
        "",
        "| Scope | Comparisons | Accuracy | Precision | Recall |",
        "| --- | --- | --- | --- | --- |",
        _scope_row("text layer", report.text_layer),
        _scope_row("rasterized", report.rasterized),
        _scope_row("overall", report.overall),
        "",
        "## Review flags",
        "",
        f"The review UI highlights a field when its confidence is below {report.threshold:.2f}.",
        "A wrong value is a mismatch or a spurious extraction.",
        "An incorrect comparison also includes a miss.",
        f"OCR fields routed to review: {report.ocr_fields_flagged}/{report.ocr_fields}.",
        "",
        "| Scope | Wrong values flagged | Incorrect comparisons flagged |",
        "| --- | --- | --- |",
        _flag_row("text layer", report.review_flags["text_layer"]),
        _flag_row("rasterized", report.review_flags["rasterized"]),
        _flag_row("overall", report.review_flags["overall"]),
        "",
        "## Reliability",
        "",
        "Text-layer confidence takes few distinct values because the signals are coarse:",
        "an exact label, one proximity bin for a normal line, and a format check.",
        "This is a reliability table for those levels, not a fitted probability.",
        "Each comparison falls in the bucket of the confidence the extractor stored.",
        "An error is a mismatch, a miss, or a spurious value.",
        _calibration_sentence(report.calibration),
        _ece_sentence(report.calibration_error, report.distinct_confidences),
        "",
        "| Confidence | Comparisons | Mean confidence | Accuracy | Errors | Error rate |",
        "| --- | --- | --- | --- | --- | --- |",
        *[_bucket_row(bucket) for bucket in report.calibration],
        "",
        "## Validation catch rate",
        "",
        "Caught means the rules engine emitted an error whose rule id is the planted defect.",
        "Ground truth measures the rules. Post-extraction measures whether the defect",
        "is still visible after extraction.",
        "",
        "| Scope | Value |",
        "| --- | --- |",
        f"| Ground truth | {_catch(report.ground_truth_catch)} |",
        f"| Post-extraction | {_catch(report.extraction_catch)} |",
        "",
        "## By variant",
        "",
        "| Variant | Comparisons | Accuracy | Precision | Recall | Straight-through |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for variant, counts in report.by_variant.items():
        documents = report.documents_by_variant.get(variant, 0)
        passed = report.straight_through_by_variant.get(variant, 0)
        lines.append(
            "| "
            + " | ".join(
                [
                    variant,
                    str(counts.total),
                    _rate(counts.accuracy, counts.correct + counts.both_null, counts.total),
                    _optional_rate(
                        counts.precision,
                        counts.correct,
                        counts.correct + counts.mismatch + counts.spurious,
                    ),
                    _optional_rate(
                        counts.recall,
                        counts.correct,
                        counts.correct + counts.mismatch + counts.missed,
                    ),
                    _rate(passed / documents if documents else None, passed, documents),
                ]
            )
            + " |"
        )
    if report.distribution == "scans":
        lines.extend(
            [
                "",
                "## By document",
                "",
                "Each row is one image-only scan. Straight-through is that document",
                "passing with no review needed.",
                "",
                (
                    "| Document | Layout | DPI | Accuracy | Precision | Recall "
                    "| Straight-through | Degradation |"
                ),
                "| --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for score in report.by_document:
            counts = score.counts
            passed = 1 if score.straight_through else 0
            dpi = "" if score.dpi is None else str(score.dpi)
            lines.append(
                "| "
                + " | ".join(
                    [
                        score.document_id,
                        score.layout or score.variant,
                        dpi,
                        _rate(
                            counts.accuracy,
                            counts.correct + counts.both_null,
                            counts.total,
                        ),
                        _optional_rate(
                            counts.precision,
                            counts.correct,
                            counts.correct + counts.mismatch + counts.spurious,
                        ),
                        _optional_rate(
                            counts.recall,
                            counts.correct,
                            counts.correct + counts.mismatch + counts.missed,
                        ),
                        _rate(float(passed), passed, 1),
                        score.degradation,
                    ]
                )
                + " |"
            )
        lines.extend(confident_wrong_lines(report.confident_wrong, threshold=report.threshold))
        lines.extend(known_failure_lines(report.by_document, threshold=report.threshold))
    lines.extend(
        [
            "",
            "## By field",
            "",
            "| Field | Comparisons | Accuracy | Precision | Recall | Missed | Mismatch |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for path, counts in report.by_field.items():
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{path}`",
                    str(counts.total),
                    _rate(counts.accuracy, counts.correct + counts.both_null, counts.total),
                    _optional_rate(
                        counts.precision,
                        counts.correct,
                        counts.correct + counts.mismatch + counts.spurious,
                    ),
                    _optional_rate(
                        counts.recall,
                        counts.correct,
                        counts.correct + counts.mismatch + counts.missed,
                    ),
                    str(counts.missed),
                    str(counts.mismatch),
                ]
            )
            + " |"
        )
    lines.extend(["", "## Definitions", ""])
    lines.extend(f"- {note}" for note in _definitions())
    if report.notes:
        lines.extend(["", "## Notes", ""])
        lines.extend(f"- {note}" for note in report.notes)
    lines.append("")
    return "\n".join(lines)


def _intro(report: EvalReport) -> list[str]:
    if report.distribution == "scans":
        return [
            "Synthetic data only. These scans were generated from the seed for this",
            "run. The image PDFs are not stored in the repository. The extractor is",
            "the deterministic backend with Tesseract.",
        ]
    return [
        "Synthetic data only. These numbers are from a corpus generated from the seed",
        "and the deterministic extractor unless the header says otherwise.",
    ]


def _straight(report: EvalReport) -> str:
    if report.documents == 0:
        return "n/a"
    rate = report.straight_through / report.documents
    return _rate(rate, report.straight_through, report.documents)


def _metric(counts: Counts, kind: str) -> str:
    if kind == "accuracy":
        numer = counts.correct + counts.both_null
        return _rate(counts.accuracy, numer, counts.total)
    if kind == "precision":
        denom = counts.correct + counts.mismatch + counts.spurious
        return _optional_rate(counts.precision, counts.correct, denom)
    denom = counts.correct + counts.mismatch + counts.missed
    return _optional_rate(counts.recall, counts.correct, denom)


def _rate(rate: float | None, numer: int, denom: int) -> str:
    if rate is None or denom == 0:
        return "n/a"
    return f"{rate * 100:.1f}% ({numer}/{denom})"


def _optional_rate(rate: float | None, numer: int, denom: int) -> str:
    if rate is None or denom == 0:
        return "n/a"
    return f"{rate * 100:.1f}% ({numer}/{denom})"


def _scope_row(label: str, counts: Counts) -> str:
    return (
        "| "
        + " | ".join(
            [
                label,
                str(counts.total),
                _rate(counts.accuracy, counts.correct + counts.both_null, counts.total),
                _optional_rate(
                    counts.precision,
                    counts.correct,
                    counts.correct + counts.mismatch + counts.spurious,
                ),
                _optional_rate(
                    counts.recall,
                    counts.correct,
                    counts.correct + counts.mismatch + counts.missed,
                ),
            ]
        )
        + " |"
    )


def _flag_row(label: str, flag: ReviewFlag) -> str:
    wrong = _optional_rate(flag.wrong_rate, flag.wrong_flagged, flag.wrong)
    incorrect = _optional_rate(flag.incorrect_rate, flag.incorrect_flagged, flag.incorrect)
    return f"| {label} | {wrong} | {incorrect} |"


def _bucket_row(bucket: CalibrationBucket) -> str:
    accuracy = _rate(bucket.accuracy, bucket.correct + bucket.both_null, bucket.comparisons)
    error_rate = _rate(bucket.error_rate, bucket.errors, bucket.comparisons)
    mean = "n/a" if bucket.mean_confidence is None else f"{bucket.mean_confidence:.3f}"
    return (
        f"| {bucket.label} | {bucket.comparisons} | {mean} | {accuracy} | "
        f"{bucket.errors} | {error_rate} |"
    )


def _ece_sentence(error: float | None, distinct: int) -> str:
    if error is None:
        return f"Distinct confidence values: {distinct}. Expected calibration error: n/a."
    return (
        f"Distinct confidence values: {distinct}. "
        f"Expected calibration error (bucket ECE): {error:.3f}."
    )


def _calibration_sentence(buckets: list[CalibrationBucket]) -> str:
    populated = [
        bucket for bucket in buckets if bucket.comparisons > 0 and bucket.error_rate is not None
    ]
    if len(populated) < 2:
        return "Not enough populated buckets to compare error rates."
    low = populated[0]
    high = populated[-1]
    low_rate = _rate(low.error_rate, low.errors, low.comparisons)
    high_rate = _rate(high.error_rate, high.errors, high.comparisons)
    low_higher = (
        low.error_rate is not None
        and high.error_rate is not None
        and low.error_rate > high.error_rate
    )
    if low_higher:
        relation = "higher than"
    elif low.error_rate == high.error_rate:
        relation = "the same as"
    else:
        relation = "not higher than"
    return (
        f"The lowest populated bucket ({low.label}) has error rate {low_rate}, "
        f"which is {relation} the highest populated bucket ({high.label}) at {high_rate}. "
        "A format failure, an item L mismatch, or an untested item L account can "
        "also lower confidence on a value that still matches the facsimile, so a "
        "middle bucket can be mostly correct."
    )


def _catch(catch: CatchRate) -> str:
    if catch.expected == 0 or catch.rate is None:
        return "n/a"
    return f"{catch.rate * 100:.1f}% ({catch.caught}/{catch.expected})"


def _definitions() -> list[str]:
    return [
        "Accuracy = (correct + both null) / comparisons.",
        "Precision = correct / (correct + mismatch + spurious).",
        "Precision is n/a when that denominator is zero.",
        "Recall = correct / (correct + mismatch + missed).",
        "Recall is n/a when that denominator is zero.",
        "Money and percentages match within the absolute tolerance.",
        "Other fields match exactly.",
        "Coded lines are scored per code.",
        "Tax year is one comparison per document.",
        "A code present on only one side is a miss or a spurious value.",
        (
            "Straight-through = documents with no error-severity finding and no field "
            "below the review threshold, including tax year, divided by documents."
        ),
        "Warnings do not block straight-through.",
        "A wrong value is flagged when its confidence is below the review threshold.",
        "Calibration buckets are half-open ranges of stored confidence. 1.00 is in the top bucket.",
    ]


def confident_wrong_lines(items: list[Judgment], *, threshold: float) -> list[str]:
    """List mismatches and spurious values that cleared the review threshold."""

    lines = [
        "",
        "## Confident wrong values",
        "",
        "A confident wrong value is a mismatch or a spurious extraction whose",
        f"confidence is at or above {threshold:.2f}. Each one is a bug. The scan",
        "baseline ceiling is the count on the measured run. A higher count fails CI.",
        "",
        f"Count: {len(items)}.",
        "",
    ]
    if not items:
        return lines
    lines.extend(
        [
            "| Document | Field | Gold | Predicted | Confidence |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for item in items:
        lines.append(
            f"| {item.document_id} | `{item.path}` | {_cell(item.gold)} | "
            f"{_cell(item.predicted)} | {item.confidence:.2f} |"
        )
    return lines


def known_failure_lines(scores: list[DocumentScore], *, threshold: float) -> list[str]:
    """Summarize the pages that were damaged on purpose."""

    hard = [score for score in scores if score.failure]
    if not hard:
        return []
    lines = [
        "",
        "## Known failure cases",
        "",
        "These pages are damaged on purpose. The extractor is not adjusted for them.",
        "A miss is a ground-truth value the extractor left empty. A mismatch is a",
        "different value. A confident wrong value cleared the review threshold and",
        "was not flagged. That is a bug.",
        "",
        (
            "| Document | Failure | Accuracy | Missed | Mismatch | Spurious "
            "| Confident wrong | Straight-through |"
        ),
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for score in hard:
        counts = score.counts
        wrong = _confident_count(score.errors, threshold)
        passed = 1 if score.straight_through else 0
        lines.append(
            "| "
            + " | ".join(
                [
                    score.document_id,
                    score.failure,
                    _rate(counts.accuracy, counts.correct + counts.both_null, counts.total),
                    str(counts.missed),
                    str(counts.mismatch),
                    str(counts.spurious),
                    str(wrong),
                    _rate(float(passed), passed, 1),
                ]
            )
            + " |"
        )
    for score in hard:
        lines.extend(_failure_detail(score, threshold))
    return lines


def _confident_count(items: tuple[Judgment, ...] | list[Judgment], threshold: float) -> int:
    return sum(
        1
        for item in items
        if item.outcome in {"mismatch", "spurious"} and item.confidence >= threshold
    )


def _failure_detail(score: DocumentScore, threshold: float) -> list[str]:
    mismatches = [item for item in score.errors if item.outcome in {"mismatch", "spurious"}]
    misses = [item for item in score.errors if item.outcome == "missed"]
    lines = ["", f"### {score.document_id} ({score.failure})", ""]
    if mismatches:
        lines.extend(
            [
                "| Field | Outcome | Gold | Predicted | Confidence | Flagged |",
                "| --- | --- | --- | --- | --- | --- |",
            ]
        )
        for item in mismatches:
            flagged = "yes" if item.confidence < threshold else "no"
            lines.append(
                f"| `{item.path}` | {item.outcome} | {_cell(item.gold)} | "
                f"{_cell(item.predicted)} | {item.confidence:.2f} | {flagged} |"
            )
        lines.append("")
    if misses:
        sample = ", ".join(f"`{item.path}`" for item in misses[:8])
        extra = len(misses) - min(len(misses), 8)
        more = f", and {extra} more" if extra > 0 else ""
        above = sum(1 for item in misses if item.confidence >= threshold)
        noun = "field" if len(misses) == 1 else "fields"
        lines.append(f"Missed {len(misses)} {noun}, including {sample}{more}.")
        lines.append(f"Missed fields at or above {threshold:.2f}: {above}.")
    if not mismatches and not misses:
        lines.append("No field errors.")
    return lines


def _cell(value: str) -> str:
    return value.replace("|", "/")


def counts_line(counts: Counts) -> str:
    accuracy = _rate(counts.accuracy, counts.correct + counts.both_null, counts.total)
    return f"accuracy {accuracy}"

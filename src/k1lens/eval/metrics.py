"""Field-level precision, recall, and accuracy.

A comparison is one field on one document.

- correct: both sides non-null and equal within tolerance
- both_null: both sides null
- mismatch: both sides non-null and not equal
- missed: ground truth is non-null and the extraction is null
- spurious: ground truth is null and the extraction is non-null

Accuracy is (correct + both_null) / comparisons.
Precision is correct / (correct + mismatch + spurious).
Recall is correct / (correct + mismatch + missed).
Rates are null when the denominator is zero.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from k1lens.domain.access import get_coded, get_extracted
from k1lens.domain.fields import CODED_BOXES, REVIEW_THRESHOLD, SCALAR_FIELDS, FieldKind
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import values_equal


@dataclass
class Counts:
    correct: int = 0
    both_null: int = 0
    mismatch: int = 0
    missed: int = 0
    spurious: int = 0

    def add(self, other: Counts) -> Counts:
        return Counts(
            correct=self.correct + other.correct,
            both_null=self.both_null + other.both_null,
            mismatch=self.mismatch + other.mismatch,
            missed=self.missed + other.missed,
            spurious=self.spurious + other.spurious,
        )

    @property
    def total(self) -> int:
        return self.correct + self.both_null + self.mismatch + self.missed + self.spurious

    @property
    def accuracy(self) -> float | None:
        if self.total == 0:
            return None
        return (self.correct + self.both_null) / self.total

    @property
    def precision(self) -> float | None:
        denominator = self.correct + self.mismatch + self.spurious
        if denominator == 0:
            return None
        return self.correct / denominator

    @property
    def recall(self) -> float | None:
        denominator = self.correct + self.mismatch + self.missed
        if denominator == 0:
            return None
        return self.correct / denominator


def classify(kind: FieldKind, gold: object, pred: object, tolerance: Decimal) -> Counts:
    if gold is None and pred is None:
        return Counts(both_null=1)
    if gold is None:
        return Counts(spurious=1)
    if pred is None:
        return Counts(missed=1)
    if values_equal(kind, gold, pred, tolerance):
        return Counts(correct=1)
    return Counts(mismatch=1)


@dataclass(frozen=True, slots=True)
class Judgment:
    """One field comparison, with the confidence the extractor assigned."""

    variant: str
    path: str
    outcome: str
    confidence: float
    extractor: str | None
    document_id: str = ""
    gold: str = ""
    predicted: str = ""


@dataclass(frozen=True, slots=True)
class ReviewFlag:
    """How many incorrect extractions were below the review threshold."""

    wrong: int
    wrong_flagged: int
    incorrect: int
    incorrect_flagged: int

    @property
    def wrong_rate(self) -> float | None:
        if self.wrong == 0:
            return None
        return self.wrong_flagged / self.wrong

    @property
    def incorrect_rate(self) -> float | None:
        if self.incorrect == 0:
            return None
        return self.incorrect_flagged / self.incorrect


@dataclass(frozen=True, slots=True)
class CalibrationBucket:
    label: str
    comparisons: int
    correct: int
    both_null: int
    errors: int
    mean_confidence: float | None = None

    @property
    def accuracy(self) -> float | None:
        if self.comparisons == 0:
            return None
        return (self.correct + self.both_null) / self.comparisons

    @property
    def error_rate(self) -> float | None:
        if self.comparisons == 0:
            return None
        return self.errors / self.comparisons


_BUCKETS: tuple[tuple[float, float, str], ...] = (
    (0.0, 0.2, "0.00-0.19"),
    (0.2, 0.4, "0.20-0.39"),
    (0.4, 0.6, "0.40-0.59"),
    (0.6, 0.8, "0.60-0.79"),
    (0.8, 1.01, "0.80-1.00"),
)


def compare_documents(gold: ScheduleK1, pred: ScheduleK1, tolerance: Decimal) -> dict[str, Counts]:
    scores: dict[str, Counts] = {}
    for spec in SCALAR_FIELDS:
        scores[spec.path] = classify(
            spec.kind,
            get_extracted(gold, spec.path).value,
            get_extracted(pred, spec.path).value,
            tolerance,
        )
    scores["tax_year"] = classify(FieldKind.INT, gold.tax_year, pred.tax_year, tolerance)
    for box in CODED_BOXES:
        for path, gold_value, pred_value, _confidence, _extractor in _aligned_coded(
            gold, pred, box.path
        ):
            scores[path] = classify(FieldKind.MONEY, gold_value, pred_value, tolerance)
    return scores


def merge_scores(parts: list[dict[str, Counts]]) -> dict[str, Counts]:
    merged: dict[str, Counts] = {}
    for part in parts:
        for path, counts in part.items():
            merged[path] = merged.get(path, Counts()).add(counts)
    return merged


def sum_counts(scores: dict[str, Counts]) -> Counts:
    total = Counts()
    for counts in scores.values():
        total = total.add(counts)
    return total


def judgments_for(
    gold: ScheduleK1,
    pred: ScheduleK1,
    tolerance: Decimal,
    *,
    variant: str,
    document_id: str = "",
) -> list[Judgment]:
    found: list[Judgment] = []
    for spec in SCALAR_FIELDS:
        gold_value = get_extracted(gold, spec.path).value
        pred_value = get_extracted(pred, spec.path).value
        confidence, extractor = _scalar_meta(pred, spec.path)
        found.append(
            Judgment(
                variant=variant,
                path=spec.path,
                outcome=_outcome(spec.kind, gold_value, pred_value, tolerance),
                confidence=confidence,
                extractor=extractor,
                document_id=document_id,
                gold=_show(gold_value),
                predicted=_show(pred_value),
            )
        )
    year_confidence = 0.0 if pred.tax_year_confidence is None else pred.tax_year_confidence
    found.append(
        Judgment(
            variant=variant,
            path="tax_year",
            outcome=_outcome(FieldKind.INT, gold.tax_year, pred.tax_year, tolerance),
            confidence=year_confidence,
            extractor=pred.tax_year_extractor,
            document_id=document_id,
            gold=_show(gold.tax_year),
            predicted=_show(pred.tax_year),
        )
    )
    for box in CODED_BOXES:
        for path, gold_value, pred_value, confidence, extractor in _aligned_coded(
            gold, pred, box.path
        ):
            found.append(
                Judgment(
                    variant=variant,
                    path=path,
                    outcome=_outcome(FieldKind.MONEY, gold_value, pred_value, tolerance),
                    confidence=confidence,
                    extractor=extractor,
                    document_id=document_id,
                    gold=_show(gold_value),
                    predicted=_show(pred_value),
                )
            )
    return found


def review_flag(items: list[Judgment], *, threshold: float = REVIEW_THRESHOLD) -> ReviewFlag:
    wrong = 0
    wrong_flagged = 0
    incorrect = 0
    incorrect_flagged = 0
    for item in items:
        if item.outcome in {"mismatch", "spurious"}:
            wrong += 1
            incorrect += 1
            if item.confidence < threshold:
                wrong_flagged += 1
                incorrect_flagged += 1
        elif item.outcome == "missed":
            incorrect += 1
            if item.confidence < threshold:
                incorrect_flagged += 1
    return ReviewFlag(
        wrong=wrong,
        wrong_flagged=wrong_flagged,
        incorrect=incorrect,
        incorrect_flagged=incorrect_flagged,
    )


def calibration_buckets(items: list[Judgment]) -> list[CalibrationBucket]:
    buckets: list[CalibrationBucket] = []
    for low, high, label in _BUCKETS:
        chosen = [item for item in items if low <= item.confidence < high]
        errors = sum(item.outcome in {"mismatch", "missed", "spurious"} for item in chosen)
        mean = None
        if chosen:
            mean = sum(item.confidence for item in chosen) / len(chosen)
        buckets.append(
            CalibrationBucket(
                label=label,
                comparisons=len(chosen),
                correct=sum(item.outcome == "correct" for item in chosen),
                both_null=sum(item.outcome == "both_null" for item in chosen),
                errors=errors,
                mean_confidence=mean,
            )
        )
    return buckets


def expected_calibration_error(items: list[Judgment]) -> float | None:
    """Bucket ECE: sum of |accuracy - mean confidence| weighted by bucket size."""

    if not items:
        return None
    total = 0.0
    for bucket in calibration_buckets(items):
        if bucket.comparisons == 0 or bucket.accuracy is None or bucket.mean_confidence is None:
            continue
        total += (bucket.comparisons / len(items)) * abs(bucket.accuracy - bucket.mean_confidence)
    return total


def distinct_confidence_count(items: list[Judgment]) -> int:
    return len({round(item.confidence, 4) for item in items})


def _aligned_coded(
    gold: ScheduleK1, pred: ScheduleK1, path: str
) -> list[tuple[str, object, object, float, str | None]]:
    gold_items = get_coded(gold, path)
    pred_items = get_coded(pred, path)
    codes: list[str] = []
    for item in (*gold_items, *pred_items):
        if item.code not in codes:
            codes.append(item.code)
    rows: list[tuple[str, object, object, float, str | None]] = []
    for code in codes:
        gold_values = [item.amount.value for item in gold_items if item.code == code]
        pred_rows = [item for item in pred_items if item.code == code]
        count = max(len(gold_values), len(pred_rows))
        for index in range(count):
            gold_value = gold_values[index] if index < len(gold_values) else None
            if index < len(pred_rows):
                pred_value = pred_rows[index].amount.value
                confidence = pred_rows[index].amount.confidence
                extractor = pred_rows[index].amount.provenance.extractor
            else:
                pred_value = None
                confidence = 0.0
                extractor = None
            key = f"{path}[{code}]" if count == 1 else f"{path}[{code}]#{index + 1}"
            rows.append((key, gold_value, pred_value, confidence, extractor))
    return rows


def _outcome(kind: FieldKind, gold: object, pred: object, tolerance: Decimal) -> str:
    if gold is None and pred is None:
        return "both_null"
    if gold is None:
        return "spurious"
    if pred is None:
        return "missed"
    if values_equal(kind, gold, pred, tolerance):
        return "correct"
    return "mismatch"


def _show(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, Decimal):
        return format(value, "f")
    return str(value)


def _scalar_meta(document: ScheduleK1, path: str) -> tuple[float, str | None]:
    field = get_extracted(document, path)
    return field.confidence, field.provenance.extractor

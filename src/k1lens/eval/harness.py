"""Run extraction over a synthetic corpus and score it."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.eval.metrics import (
    CalibrationBucket,
    Counts,
    Judgment,
    ReviewFlag,
    calibration_buckets,
    compare_documents,
    distinct_confidence_count,
    expected_calibration_error,
    judgments_for,
    merge_scores,
    review_flag,
    sum_counts,
)
from k1lens.extract.assemble import assemble
from k1lens.extract.base import ExtractionError, Extractor
from k1lens.extract.factory import get_extractor
from k1lens.extract.ocr import ocr_enabled, tesseract_version
from k1lens.generate.corpus import load_ground_truth, load_manifest
from k1lens.generate.scans import failure_mode_of
from k1lens.review.store import unresolved_issues
from k1lens.roster import Roster, bind_roster, count_confident_ids
from k1lens.validate.engine import DEFAULT_TOLERANCE, Finding, validate_document

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CatchRate:
    caught: int
    expected: int

    @property
    def rate(self) -> float | None:
        if self.expected == 0:
            return None
        return self.caught / self.expected


@dataclass(frozen=True, slots=True)
class DocumentScore:
    document_id: str
    variant: str
    layout: str
    dpi: int | None
    degradation: str
    counts: Counts
    straight_through: bool
    failure: str = ""
    errors: tuple[Judgment, ...] = ()


def is_image_only(variant: str) -> bool:
    """True for a page with no text layer.

    ``rasterized`` is the two committed catalog scans. ``scan_*`` is the
    generated scan corpus: catalog, dev_statement, and dev_b layouts.
    """

    return variant == "rasterized" or variant.startswith("scan_")


@dataclass
class EvalReport:
    backend: str
    fixture_dir: str
    seed: int
    documents: int
    ocr_enabled: bool
    tolerance: str
    overall: Counts
    text_layer: Counts
    rasterized: Counts
    by_field: dict[str, Counts]
    by_variant: dict[str, Counts]
    ground_truth_catch: CatchRate
    extraction_catch: CatchRate
    review_flags: dict[str, ReviewFlag]
    calibration: list[CalibrationBucket]
    calibration_error: float | None
    distinct_confidences: int
    ocr_fields: int
    ocr_fields_flagged: int
    threshold: float
    distribution: str
    straight_through: int
    straight_through_by_variant: dict[str, int]
    documents_by_variant: dict[str, int]
    tesseract_version: str | None
    by_document: list[DocumentScore] = field(default_factory=list)
    confident_wrong: list[Judgment] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stopped_reason: str = ""
    roster_path: str = ""
    confident_id_sections: int = 0
    id_sections: int = 0


def evaluate(
    fixture_dir: Path,
    *,
    backend: str = "deterministic",
    tolerance: Decimal = DEFAULT_TOLERANCE,
    extractor: Extractor | None = None,
    threshold: float = REVIEW_THRESHOLD,
    distribution: str = "in_distribution",
    max_documents: int | None = None,
    roster: Roster | None = None,
    roster_path: str = "",
) -> EvalReport:
    manifest = load_manifest(fixture_dir)
    engine = extractor if extractor is not None else get_extractor(backend)
    entries = list(manifest.documents)
    if max_documents is not None:
        entries = entries[:max_documents]
    per_document: list[dict[str, Counts]] = []
    by_variant_parts: dict[str, list[dict[str, Counts]]] = {}
    judgments: list[Judgment] = []
    truth_cases: list[tuple[list[str], list[Finding]]] = []
    extract_cases: list[tuple[list[str], list[Finding]]] = []
    straight_through = 0
    straight_by_variant: dict[str, int] = {}
    documents_by_variant: dict[str, int] = {}
    by_document: list[DocumentScore] = []
    confident_wrong: list[Judgment] = []
    stopped_reason = ""
    confident_id_sections = 0
    for entry in entries:
        truth = load_ground_truth(fixture_dir / entry.ground_truth)
        try:
            predicted = engine.extract(fixture_dir / entry.pdf, threshold=threshold)
        except ExtractionError as exc:
            stopped_reason = _public_error(exc)
            break
        except Exception as exc:
            logger.exception("Skipping %s (%s)", entry.pdf, type(exc).__name__)
            predicted = assemble(
                entry.document_id,
                {},
                extractor=getattr(engine, "name", "deterministic"),
                threshold=threshold,
                ocr_failed_pages=(1,),
            )
        predicted = predicted.model_copy(
            update={"document_id": entry.document_id, "variant": entry.variant}
        )
        predicted = bind_roster(predicted, roster, threshold=threshold)
        confident_id_sections += count_confident_ids(predicted, threshold=threshold)
        scores = compare_documents(truth.document, predicted, tolerance)
        per_document.append(scores)
        by_variant_parts.setdefault(entry.variant, []).append(scores)
        doc_judgments = judgments_for(
            truth.document,
            predicted,
            tolerance,
            variant=entry.variant,
            document_id=entry.document_id,
        )
        judgments.extend(doc_judgments)
        mode = failure_mode_of(entry.degradation)
        for item in doc_judgments:
            if item.outcome in {"mismatch", "spurious"} and item.confidence >= threshold:
                confident_wrong.append(item)
        truth_cases.append(
            (
                list(truth.planted_defects),
                validate_document(truth.document, tolerance=tolerance, roster=roster),
            )
        )
        extracted_findings = validate_document(predicted, tolerance=tolerance, roster=roster)
        extract_cases.append((list(truth.planted_defects), extracted_findings))
        documents_by_variant[entry.variant] = documents_by_variant.get(entry.variant, 0) + 1
        passed = not unresolved_issues(predicted, extracted_findings, threshold, set())
        if passed:
            straight_through += 1
            straight_by_variant[entry.variant] = straight_by_variant.get(entry.variant, 0) + 1
        by_document.append(
            DocumentScore(
                document_id=entry.document_id,
                variant=entry.variant,
                layout=entry.layout,
                dpi=entry.dpi,
                degradation=entry.degradation,
                counts=sum_counts(scores),
                straight_through=passed,
                failure=mode,
                errors=tuple(
                    item
                    for item in doc_judgments
                    if mode and item.outcome in {"mismatch", "missed", "spurious"}
                ),
            )
        )
    by_field = merge_scores(per_document)
    by_variant = {
        variant: sum_counts(merge_scores(parts))
        for variant, parts in sorted(by_variant_parts.items())
    }
    text_items = [item for item in judgments if not is_image_only(item.variant)]
    raster_items = [item for item in judgments if is_image_only(item.variant)]
    ocr_items = [item for item in judgments if item.extractor == "ocr"]

    return EvalReport(
        backend=engine.name,
        fixture_dir=str(fixture_dir),
        seed=manifest.seed,
        documents=len(by_document),
        ocr_enabled=ocr_enabled(),
        tolerance=str(tolerance),
        overall=sum_counts(by_field),
        text_layer=_counts_from(text_items),
        rasterized=_counts_from(raster_items),
        by_field=by_field,
        by_variant=by_variant,
        ground_truth_catch=_catch(truth_cases),
        extraction_catch=_catch(extract_cases),
        review_flags={
            "text_layer": review_flag(text_items, threshold=threshold),
            "rasterized": review_flag(raster_items, threshold=threshold),
            "overall": review_flag(judgments, threshold=threshold),
        },
        calibration=calibration_buckets(judgments),
        calibration_error=expected_calibration_error(judgments),
        distinct_confidences=distinct_confidence_count(judgments),
        ocr_fields=len(ocr_items),
        ocr_fields_flagged=sum(item.confidence < threshold for item in ocr_items),
        threshold=threshold,
        distribution=distribution,
        straight_through=straight_through,
        straight_through_by_variant=straight_by_variant,
        documents_by_variant=documents_by_variant,
        tesseract_version=tesseract_version(),
        by_document=by_document,
        confident_wrong=confident_wrong,
        notes=_notes(
            manifest.seed,
            distribution=distribution,
            threshold=threshold,
            roster_path=roster_path,
        ),
        stopped_reason=stopped_reason,
        roster_path=roster_path,
        confident_id_sections=confident_id_sections,
        id_sections=2 * len(by_document),
    )


def _public_error(exc: ExtractionError) -> str:
    """Drop request details. The message must not carry a key or headers."""

    from k1lens.extract.redact import redact_secrets

    return redact_secrets(str(exc))


def _catch(cases: list[tuple[list[str], list[Finding]]]) -> CatchRate:
    expected = 0
    caught = 0
    for defects, findings in cases:
        for rule_id in defects:
            expected += 1
            if any(
                finding.rule_id == rule_id and finding.severity.value == "error"
                for finding in findings
            ):
                caught += 1
    return CatchRate(caught=caught, expected=expected)


def _counts_from(items: list[Judgment]) -> Counts:
    total = Counts()
    for item in items:
        total = total.add(_one(item.outcome))
    return total


def _one(outcome: str) -> Counts:
    if outcome == "correct":
        return Counts(correct=1)
    if outcome == "both_null":
        return Counts(both_null=1)
    if outcome == "mismatch":
        return Counts(mismatch=1)
    if outcome == "missed":
        return Counts(missed=1)
    return Counts(spurious=1)


def _notes(seed: int, *, distribution: str, threshold: float, roster_path: str) -> list[str]:
    notes = [
        f"Ground truth was produced by the synthetic generator with seed {seed}.",
        "No taxpayer data is in this run.",
        (
            "Confidence is computed from label-match quality, text-layer presence or "
            "Tesseract word confidence, label/value proximity, parse and format checks, "
            "and whether item L reconciles or could not be tested. It does not use ground truth."
        ),
        f"A field is flagged for review when its confidence is below {threshold:.2f}.",
        (
            "A label one edit from exactly one known field label is accepted on OCR "
            "lines, at a lower label score. A period in an abbreviation or an "
            "initial, such as L.P. or Jr., is kept. Yes. and No. lose the separator "
            "period, and a trailing period on a capital-method checkbox is dropped."
        ),
        (
            "Other labels are matched from the public Schedule K-1 (Form 1065) box "
            "numbers, line names, and codes. Case and punctuation are normalized. "
            "Abbreviations are only those the IRS prints (EIN, SSN, TIN, PTP, AMT) "
            "or general accounting shortenings of the form's own words. A line is "
            "kept only when it beats the runner-up by a margin. An ambiguous line "
            "is left blank."
        ),
        (
            "When too few lines match, the document is an unrecognized layout. "
            "Deterministic field confidence is capped below the review threshold, "
            "including a lower --threshold, and the review UI says the layout was "
            "not recognized. The LLM-only backend uses that same cap. The "
            "unrecognized-layout cap still applies, including after a roster match: "
            "an unrecognized page does not clear identity. A numeric model proposal "
            "is stored only when the rules value is missing and the string appears "
            "in that field's own label region. Its confidence is never raised above "
            "the number the model reported, and it stays under the review threshold. "
            "A non-finite model confidence is rejected. A finite confidence outside "
            "0 to 1 is clamped. Identity is not taken from the model at any "
            "confidence. A disagreeing model value is not stored. "
            "The LLM-only path stops on a persistent 5xx, a timeout, or a "
            "malformed reply. Hybrid keeps the deterministic values in those cases."
        ),
        (
            "Name, street, city, state, and ZIP are lifted to exactly the review "
            "threshold, and not higher, only when a roster is passed, the key id was "
            "read confidently and passes the format check, and every field in that "
            "section matches the same record. Each value has to be read from its own "
            "field region. A fallback, a repair, or a model value lifts nothing in "
            "that section. A partial match lifts nothing. An unrecognized layout "
            "lifts nothing. The partnership section is keyed by the EIN. The partner "
            "section is keyed by the TIN. The key must be nine digits in the EIN or "
            "SSN dash pattern, including the synthetic 00- and 000- ranges. An OCR "
            "id whose digit-word confidence is under the threshold is not a key. A "
            "text-layer id under the threshold is not a key. Digits are not "
            "repaired, guessed, or check-digit-corrected. A masked id is no_tin. "
            "Without a roster the finding is no_roster. A confident key with no "
            "record is new_partner. A key that is well formed but not confident is "
            "no_roster_match. Two roster records with the same EIN or TIN are "
            "duplicate_roster_key and are not a match. A key that matches, with any "
            "field different or blank on either side, is identity_mismatch. The "
            "value stored is the page string. Each lifted field is an audit row "
            "with reason roster_exact_match. A lift needs a confident id plus a "
            "full exact match. Entity type is not in this set. The form prints no "
            "options for that item, and a roster match does not clear it."
        ),
        (
            "Text-layer confidence takes few distinct values. An exact catalog "
            "label, a short gap (proximity 1), a text-layer source, and a "
            "successful parse with no format rule land at 0.92. A format check "
            "adds 0.08. A wide label-to-value gap, OCR word confidence, a failed "
            "parse, a failed format check, and the item L penalty move the score. "
            "The reliability table and the expected calibration error describe "
            "those levels. They are not a fitted probability."
        ),
        "A wrong value is a mismatch or a spurious extraction.",
        "An incorrect comparison is a wrong value or a miss.",
        "A planted defect is caught when validation emits an error with that rule id.",
        "Capital tolerance is absolute dollars, not a percentage.",
        (
            "Tax year is scored with the other fields. Straight-through is the share of "
            "documents with no error-severity finding and no field, including tax year, "
            "below the review threshold. Warnings do not block. Field accuracy does not "
            "imply that rate. It is the same check the approval gate uses before an override."
        ),
        (
            "Tesseract 5.3.4 is the version measured here and in Ubuntu CI. The Docker "
            "image uses Debian bookworm's 5.3.0. Rasterized accuracy and precision floors "
            "sit under the measured rates so that one-version OCR disagreement does not "
            "fail the check. The report header records the version that produced the numbers."
        ),
    ]
    if distribution == "dev":
        notes.extend(
            [
                (
                    "layout_shift reprints the catalog labels in a different font, "
                    "order, and spacing. A high score there shows the parser is not "
                    "tied to the generator's coordinates. It still depends on those labels."
                ),
                (
                    "dev_statement is a development layout with different wording. Those "
                    "captions were inspected during development, so the score is not a "
                    "blind test. The extractor is not given the caption strings. "
                    "The held-out set is scored by an independent reviewer; not in this repo."
                ),
            ]
        )
    elif distribution == "scans":
        notes.extend(
            [
                (
                    "These documents are image-only scans. CI generates them from seed "
                    f"{seed} with k1lens generate --scans. The PDFs are not stored in "
                    "the repository. The same seed rewrites the same images on one "
                    "machine. docs/scan-hashes.json is pinned to the CI runner image. "
                    "Eight documents differ on another Linux box, so a local byte "
                    "comparison is skipped outside CI. Pillow and pdfium can still "
                    "differ across machines, and Tesseract 5.3.4 measured here can "
                    "disagree with Docker's 5.3.0."
                ),
                (
                    "Each mild scan is a synthetic K-1. EINs use the 00- prefix. "
                    "Layouts cycle through the catalog facsimile, dev_statement, and "
                    "dev_b. dev_statement and dev_b were seen during development. "
                    "The held-out set is scored by an independent reviewer; not in this repo. "
                    "Degradation varies DPI from 150 "
                    "to 300, adds a slight rotation and skew, noise, blur, and JPEG "
                    "compression. Three documents, one in each layout, are faint: "
                    "lower contrast, lower brightness, and JPEG quality 40."
                ),
                (
                    "Six more pages are known failures on the catalog layout: 40 DPI, "
                    "a 20 degree rotation with heavy skew, a coffee-stain occlusion, "
                    "handwritten strokes across printed lines, the bottom of the page "
                    "cropped away, and a page faded almost to white. The extractor is "
                    "not adjusted for them. Accuracy floors are the measured rates, "
                    "so those failures are expected. A confident wrong value is a "
                    "mismatch or a spurious extraction at or above the review "
                    "threshold. Each one is listed in this report."
                ),
                (
                    "Per-document accuracy, precision, recall, and straight-through "
                    "are in the by-document table. The reliability table is the "
                    "calibration for these scans. Field accuracy does not imply "
                    "straight-through."
                ),
            ]
        )
    elif distribution == "dev_geometry":
        notes.extend(
            [
                (
                    "fixtures/dev_geometry is a round-trip set. It prints the same "
                    "catalog strings the extractor already lists, from seed 1065, "
                    "with no colon: a right-aligned amount, a box grid, two columns "
                    "on one baseline, a statement that mixes those, and a label with "
                    "the amount on the next line in the same column. It is not "
                    "evidence for an unseen layout. The held-out set is scored by an "
                    "independent reviewer; not in this repo."
                ),
                (
                    "A wide gap between a label and a right-aligned amount lowers "
                    "proximity, so a correct value can stay under 0.80. A value on "
                    "the next line in that caption's column is the field's own box. "
                    "Name, street, city, state, and ZIP stay under 0.80 unless a "
                    "confident id and a full exact match lift that section to exactly "
                    "the review threshold. A partial match lifts nothing. The weights "
                    "were not refit."
                ),
            ]
        )
    elif distribution == "dev_b":
        notes.extend(
            [
                (
                    "fixtures/dev_b is a development set. It was seen during development. "
                    "The held-out set is scored by an independent reviewer; not in this repo. "
                    "The amounts are the in-distribution K1-0001 through "
                    "K1-0004 records with the captions changed. The typeface is Helvetica, "
                    "the same family as the in-distribution facsimiles. The year caption is "
                    "'Reporting period', not 'TAX YEAR', so the tax year is missed. That "
                    "miss is scored. It also fails required_fields, so straight-through "
                    "is not the field accuracy."
                ),
                (
                    "Precision is correct / (correct + mismatch + spurious). A confident "
                    "wrong number counts as a mismatch or a spurious value. A miss does not."
                ),
            ]
        )
    else:
        notes.extend(
            [
                (
                    "In-distribution text-layer documents use the same label catalog the "
                    "generator prints. A high score shows that catalog round-trips. It "
                    "does not show that the extractor can read unseen wording. "
                    "dev_statement and fixtures/dev_b were both inspected, so they are "
                    "development scores. The held-out set is scored by an independent "
                    "reviewer; not in this repo."
                ),
                (
                    "Rasterized documents have no text layer and are read with Tesseract. "
                    "OCR confidence follows word confidence. It is not capped under the "
                    "review threshold."
                ),
                (
                    "A 1.2 degree rotation still has a text layer, so the strings still "
                    "parse. Word boxes on one printed line no longer share a baseline, "
                    "so the extractor cannot confirm that the value sits with its label. "
                    "Those fields are capped below the review threshold."
                ),
            ]
        )
    if roster_path:
        notes.append(
            "A roster file was passed: "
            f"{roster_path}. A lift needs a confident id plus a full exact match "
            "of that section, and the stored confidence on a lifted field is exactly "
            "the review threshold. If that file was built from this set's ground "
            "truth, those documents' identity was known before scoring. evaluate() "
            "does not build a roster from ground truth."
        )
    else:
        notes.append(
            "No roster was passed. Every name, street, city, state, and ZIP stays "
            "in review, with a no_roster finding. That is by design."
        )
    return notes

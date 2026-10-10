"""Signal-derived confidence, including the capital-account penalty."""

import random

import pytest

from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import ScheduleK1
from k1lens.extract.confidence import apply_agreement, evidence_confidence
from k1lens.extract.text import PdfWord, measure_label
from k1lens.generate.build import Variant, build_document


def test_signals_move_confidence_in_the_expected_direction() -> None:
    exact = evidence_confidence(
        label_score=1.0,
        proximity=1.0,
        ocr_confidence=None,
        reported_confidence=None,
        parsed=True,
        format_ok=True,
    )
    fuzzy = evidence_confidence(
        label_score=0.55,
        proximity=1.0,
        ocr_confidence=None,
        reported_confidence=None,
        parsed=True,
        format_ok=True,
    )
    distant = evidence_confidence(
        label_score=1.0,
        proximity=0.15,
        ocr_confidence=None,
        reported_confidence=None,
        parsed=True,
        format_ok=True,
    )
    weak_ocr = evidence_confidence(
        label_score=1.0,
        proximity=None,
        ocr_confidence=0.4,
        reported_confidence=None,
        parsed=True,
        format_ok=True,
    )
    strong_ocr = evidence_confidence(
        label_score=1.0,
        proximity=None,
        ocr_confidence=0.95,
        reported_confidence=None,
        parsed=True,
        format_ok=True,
    )
    unparsed = evidence_confidence(
        label_score=1.0,
        proximity=1.0,
        ocr_confidence=None,
        reported_confidence=None,
        parsed=False,
        format_ok=None,
    )
    bad_format = evidence_confidence(
        label_score=1.0,
        proximity=1.0,
        ocr_confidence=None,
        reported_confidence=None,
        parsed=True,
        format_ok=False,
    )
    assert exact > fuzzy
    assert exact > distant
    assert strong_ocr > weak_ocr
    assert unparsed <= 0.25
    assert bad_format < exact
    assert 0.0 <= weak_ocr <= 1.0


def test_closer_values_score_a_higher_proximity() -> None:
    label = "A Partnership EIN"
    close = [
        PdfWord("A", 10, 10, 18, 18),
        PdfWord("Partnership", 22, 10, 80, 18),
        PdfWord("EIN:", 84, 10, 104, 18),
        PdfWord("00-0000001", 108, 10, 170, 18),
    ]
    far = [
        PdfWord("A", 10, 10, 18, 18),
        PdfWord("Partnership", 22, 10, 80, 18),
        PdfWord("EIN:", 84, 10, 104, 18),
        PdfWord("00-0000001", 320, 10, 390, 18),
    ]
    _box, near = measure_label(close, label)
    _far_box, distant = measure_label(far, label)
    assert near is not None and distant is not None
    assert near > distant


def test_capital_mismatch_lowers_only_the_capital_fields() -> None:
    document = build_document(random.Random(4), 3, Variant.INCONSISTENT_CAPITAL)
    adjusted = apply_agreement(document)
    ending = document.part_ii.capital.ending.confidence
    beginning = document.part_ii.capital.beginning.confidence
    assert adjusted.part_ii.capital.ending.confidence < ending
    assert adjusted.part_ii.capital.beginning.confidence < beginning
    assert adjusted.part_i.ein.confidence == document.part_i.ein.confidence
    clean = apply_agreement(build_document(random.Random(4), 3, Variant.CLEAN))
    assert clean.part_ii.capital.ending.confidence == 1.0


def test_untested_item_l_cannot_clear_review() -> None:
    """A parsed item L amount stays in review when a sibling is missing.

    The scan withdrawals that cleared 0.80 had an exact label, a money parse,
    a non-negative format check, and a solid Tesseract score. Item L was
    incomplete, so the cross-check never ran. This does not name those pages.
    """

    document = build_document(random.Random(4), 3, Variant.CLEAN)
    data = document.model_dump(mode="json")
    contributed = data["part_ii"]["capital"]["contributed"]
    contributed["value"] = None
    contributed["confidence"] = 0.0
    data["part_ii"]["capital"]["withdrawals"]["confidence"] = 0.88
    incomplete = ScheduleK1.model_validate(data)
    adjusted = apply_agreement(incomplete)
    withdrawals = adjusted.part_ii.capital.withdrawals.confidence
    beginning = adjusted.part_ii.capital.beginning.confidence
    assert withdrawals == pytest.approx(0.66)
    assert beginning == pytest.approx(document.part_ii.capital.beginning.confidence - 0.22)
    assert withdrawals < REVIEW_THRESHOLD
    assert beginning < REVIEW_THRESHOLD
    assert adjusted.part_i.ein.confidence == document.part_i.ein.confidence

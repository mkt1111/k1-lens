"""Turn labeled strings into a Schedule K-1."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from k1lens.domain.blank import blank_schedule
from k1lens.domain.fields import (
    CODED_BOXES,
    LABEL_DOCUMENT_ID,
    LABEL_TAX_YEAR,
    LABEL_VARIANT,
    REVIEW_THRESHOLD,
    SCALAR_FIELDS,
    FieldKind,
    FieldSpec,
)
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import (
    STATE_PATHS,
    begins_with_cross_reference,
    canonicalize_capital_method,
    canonicalize_entity_type,
    canonicalize_state,
    clean_printed_value,
    is_note_phrase,
    parse_kind,
)
from k1lens.extract.confidence import (
    apply_agreement,
    auxiliary_address_row,
    below_review_threshold,
    cap_confidences,
    city_linked_to_state_or_zip,
    evidence_confidence,
    format_ok_for,
    identity_may_clear,
    identity_path,
    llm_only_confidence_cap,
    position_free_text_ok,
    reads_as_field_caption,
    strip_caption_prefix,
    strip_trailing_punctuation,
)
from k1lens.extract.labels import LayoutStats, canonicalize_observed
from k1lens.extract.text import Observed
from k1lens.roster import ROSTER_IDENTITY_PATHS

_DOC_ID = re.compile(r"^K1-[A-Za-z0-9-]+$")
_CODE = re.compile(r"^[A-Z]{1,2}$")


def assemble(
    fallback_id: str,
    observed: dict[str, list[Observed]],
    *,
    extractor: str,
    layout_stats: LayoutStats | None = None,
    threshold: float = REVIEW_THRESHOLD,
    apply_layout_cap: bool = True,
    ocr_failed_pages: tuple[int, ...] = (),
) -> ScheduleK1:
    if layout_stats is None:
        observed, layout_stats = canonicalize_observed(observed)
    document_id = _document_id(fallback_id, observed)
    year_obs = _first(observed.get(LABEL_TAX_YEAR))
    tax_year = _tax_year(year_obs)
    year_confidence, year_extractor = _year_meta(year_obs, tax_year, threshold)
    variant_obs = _first(observed.get(LABEL_VARIANT))
    variant = variant_obs.raw.strip() if variant_obs is not None else "unknown"
    if variant == "":
        variant = "unknown"
    data = blank_schedule(
        document_id,
        extractor=extractor,
        variant=variant,
        tax_year=tax_year,
    ).model_dump(mode="json")
    data["tax_year_confidence"] = year_confidence
    data["tax_year_extractor"] = year_extractor
    for spec in SCALAR_FIELDS:
        _apply_scalar(data, spec, _first(observed.get(spec.pdf_label)), threshold)
    for box in CODED_BOXES:
        prefix = f"{box.pdf_prefix} "
        items: list[dict[str, Any]] = []
        labels = sorted(label for label in observed if label.startswith(prefix))
        for label in labels:
            code = label[len(prefix) :].strip().upper()
            if _CODE.fullmatch(code) is None:
                continue
            for obs in observed[label]:
                value, confidence, _evidence = _parse(
                    FieldKind.MONEY, obs, f"{box.path}[{code}]", threshold
                )
                items.append(
                    {
                        "code": code,
                        "description": None,
                        "amount": _payload(value, confidence, obs, label),
                    }
                )
        _put(data, box.path, items)
    _hold_unlinked_cities(data, observed, threshold)
    document = apply_agreement(ScheduleK1.model_validate(data))
    if not layout_stats.recognized:
        if apply_layout_cap:
            document = cap_confidences(document, below_review_threshold(threshold))
        else:
            # Hybrid calls this for the model leg. ``_cap_llm`` already keeps
            # every model value under the review threshold. Ungrounded values
            # are also capped in ``_limit``.
            document = document.model_copy(update={"layout_recognized": False})
    if ocr_failed_pages:
        document = document.model_copy(update={"ocr_failed_pages": list(ocr_failed_pages)})
    return document


_CITY_GROUPS = (
    ("part_i.city", "part_i.state", "part_i.zip_code"),
    ("part_ii.city", "part_ii.state", "part_ii.zip_code"),
)


def _hold_unlinked_cities(
    data: dict[str, Any], observed: dict[str, list[Observed]], threshold: float
) -> None:
    """A city shape clears only with a state or ZIP on a linked line."""

    labels = {spec.path: spec.pdf_label for spec in SCALAR_FIELDS}
    cap = below_review_threshold(threshold)
    for city_path, state_path, zip_path in _CITY_GROUPS:
        node = _dig(data, city_path)
        if not isinstance(node, dict) or node.get("value") is None:
            continue
        if float(node.get("confidence") or 0.0) <= cap:
            continue
        city_obs = _first(observed.get(labels[city_path]))
        state_obs = _first(observed.get(labels[state_path]))
        zip_obs = _first(observed.get(labels[zip_path]))
        state_node = _dig(data, state_path)
        zip_node = _dig(data, zip_path)
        state_value = state_node.get("value") if isinstance(state_node, dict) else None
        zip_value = zip_node.get("value") if isinstance(zip_node, dict) else None
        linked = city_linked_to_state_or_zip(
            str(node["value"]),
            city_obs.bbox if city_obs is not None else None,
            str(state_value) if state_value is not None else None,
            state_obs.bbox if state_obs is not None else None,
            str(zip_value) if zip_value is not None else None,
            zip_obs.bbox if zip_obs is not None else None,
        )
        if not linked:
            node["confidence"] = cap


def _dig(data: dict[str, Any], path: str) -> Any:
    node: Any = data
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node


def _first(rows: list[Observed] | None) -> Observed | None:
    if not rows:
        return None
    return rows[-1]


def has_field_labels(observed: dict[str, list[Observed]]) -> bool:
    header = {LABEL_TAX_YEAR, LABEL_DOCUMENT_ID, LABEL_VARIANT}
    if any(spec.pdf_label in observed for spec in SCALAR_FIELDS):
        return True
    for label in observed:
        if label in header:
            continue
        for box in CODED_BOXES:
            if label.startswith(f"{box.pdf_prefix} "):
                return True
    return False


def _apply_scalar(
    data: dict[str, Any], spec: FieldSpec, obs: Observed | None, threshold: float
) -> None:
    if obs is None:
        return
    value, confidence, evidence = _parse(spec.kind, obs, spec.path, threshold)
    _put(
        data,
        spec.path,
        _payload(value, confidence, obs, spec.pdf_label, evidence=evidence),
    )


def _parse(
    kind: FieldKind, obs: Observed, path: str, threshold: float
) -> tuple[object, float, float | None]:
    try:
        value = parse_kind(kind, obs.raw)
    except ValueError:
        confidence = evidence_confidence(
            label_score=obs.label_score,
            proximity=obs.proximity,
            ocr_confidence=obs.ocr_confidence,
            reported_confidence=obs.reported_confidence,
            parsed=False,
            format_ok=None,
        )
        return None, _cap_llm(_limit(confidence, obs, threshold), obs, threshold), None
    stored: object = value
    prefix_stripped = False
    if kind in (FieldKind.MONEY, FieldKind.PERCENT) and isinstance(value, Decimal):
        stored = str(value)
    if kind is FieldKind.STRING and isinstance(stored, str):
        stored, prefix_stripped = strip_caption_prefix(path, clean_printed_value(stored))
        if path in {"part_i.city", "part_ii.city"}:
            stored = strip_trailing_punctuation(stored)
        # ``See cover letter`` is a note. Dropping only the word ``see``
        # would store ``cover letter`` as a name. A note phrase such as
        # ``Not applicable`` is not a value either. Store nothing.
        if stored == "" or begins_with_cross_reference(stored) or is_note_phrase(stored):
            return None, below_review_threshold(threshold), None
        if path.endswith((".street", ".city", ".state", ".zip_code")) and auxiliary_address_row(
            stored
        ):
            return None, below_review_threshold(threshold), None
    if path in STATE_PATHS and isinstance(stored, str):
        stored = canonicalize_state(stored)
    if path == "part_ii.capital_method" and isinstance(stored, str):
        stored = canonicalize_capital_method(stored)
    if path == "part_ii.entity_type" and isinstance(stored, str):
        stored = canonicalize_entity_type(stored)
    format_ok = format_ok_for(kind, path, stored)
    # A model value that fails the same shape check is not stored at low
    # confidence. The blank stays blank. A zero the page does not print
    # next to this label is not a reading of a blank line.
    if obs.extractor == "llm" and _model_value_rejected(
        path,
        kind,
        stored,
        grounded=obs.grounded,
        format_ok=format_ok,
        number=value if isinstance(value, Decimal) else None,
    ):
        return None, below_review_threshold(threshold), None
    confidence = evidence_confidence(
        label_score=obs.label_score,
        proximity=obs.proximity,
        ocr_confidence=obs.ocr_confidence,
        reported_confidence=obs.reported_confidence,
        parsed=True,
        format_ok=format_ok,
    )
    confidence = _limit(confidence, obs, threshold)
    # A wrapped value that stopped at the first line is incomplete.
    if obs.truncated:
        confidence = min(confidence, below_review_threshold(threshold))
    evidence: float | None = None
    # Name, street, city, state, and ZIP clear 0.80 only from a roster match
    # applied later. Shape, caption position, and a model self-report do not
    # open that path. Entity type still uses its exact-option check below.
    if path in ROSTER_IDENTITY_PATHS and isinstance(stored, str):
        evidence = confidence
        if obs.extractor == "llm":
            evidence = min(evidence, below_review_threshold(threshold))
        confidence = min(confidence, below_review_threshold(threshold))
    else:
        gate = position_free_text_ok(path, stored, ocr_confidence=obs.ocr_confidence)
        ungated = (
            obs.position_paired
            and gate is None
            and kind is FieldKind.STRING
            and path not in STATE_PATHS
            and path not in {"part_i.ein", "part_ii.tin"}
        )
        if gate is False or ungated:
            confidence = min(confidence, below_review_threshold(threshold))
        if identity_path(path) and isinstance(stored, str):
            own_box = not obs.neighbor_line and not obs.neighbor_column
            if not identity_may_clear(
                path, stored, own_box=own_box, prefix_stripped=prefix_stripped
            ):
                confidence = min(confidence, below_review_threshold(threshold))
        caption_line = path in {"part_i.name", "part_ii.name", "part_i.city", "part_ii.city"}
        if (
            isinstance(stored, str)
            and caption_line
            and (obs.caption_slot or reads_as_field_caption(stored))
        ):
            confidence = min(confidence, below_review_threshold(threshold))
    # The evidence formula can land above a model's own number. Do not.
    if obs.reported_confidence is not None:
        confidence = min(confidence, float(obs.reported_confidence))
        if evidence is not None:
            evidence = min(evidence, float(obs.reported_confidence))
    return stored, _cap_llm(confidence, obs, threshold), evidence


def _model_value_rejected(
    path: str,
    kind: FieldKind,
    stored: object,
    *,
    grounded: bool,
    format_ok: bool | None,
    number: Decimal | None,
) -> bool:
    if format_ok is False or position_free_text_ok(path, stored) is False:
        return True
    if grounded or kind not in {FieldKind.MONEY, FieldKind.PERCENT}:
        return False
    return number is not None and number == 0


def _limit(confidence: float, obs: Observed, threshold: float) -> float:
    if obs.conflict or not obs.grounded or not obs.anchored:
        return min(confidence, below_review_threshold(threshold))
    return confidence


def _cap_llm(confidence: float, obs: Observed, threshold: float) -> float:
    """Keep an llm value strictly under the review threshold.

    An llm observation is not a read from the field's own region, so
    ``own_region`` is false. Label score plus a self-report of 1.0 would
    otherwise clear 0.80. That includes a yes/no line that prints both
    option words: the unmarked word is in the region and passes grounding.
    The cap is ``LLM_ONLY_CONFIDENCE_CAP`` (0.79 at the default threshold).
    A neighbor-column or unanchored deterministic read is not this case.
    """

    if obs.extractor != "llm" or _read_from_own_region(obs):
        return confidence
    return min(confidence, llm_only_confidence_cap(threshold))


def _payload(
    value: object,
    confidence: float,
    obs: Observed,
    label: str,
    *,
    evidence: float | None = None,
) -> dict[str, Any]:
    bbox = list(obs.bbox) if obs.bbox is not None else None
    return {
        "value": value,
        "confidence": confidence,
        "provenance": {
            "page": obs.page,
            "bbox": bbox,
            "field_name": label,
            "extractor": obs.extractor,
            "id_digit_confidence": obs.id_digit_confidence,
            "evidence_confidence": evidence,
            "own_region": _read_from_own_region(obs),
        },
    }


def _read_from_own_region(obs: Observed) -> bool:
    """True when this string was read from the field's own region.

    A model value, another column, a conflict, or a read that is not
    anchored to its label is not that region. The next line in the same
    column still is.
    """

    return not (
        obs.extractor == "llm"
        or obs.neighbor_column
        or obs.conflict
        or not obs.grounded
        or not obs.anchored
    )


def _put(data: dict[str, Any], path: str, value: object) -> None:
    node: Any = data
    parts = path.split(".")
    for part in parts[:-1]:
        node = node[part]
    node[parts[-1]] = value


def _document_id(fallback_id: str, observed: dict[str, list[Observed]]) -> str:
    obs = _first(observed.get(LABEL_DOCUMENT_ID))
    if obs is not None and _DOC_ID.fullmatch(obs.raw.strip()):
        return obs.raw.strip()
    if _DOC_ID.fullmatch(fallback_id):
        return fallback_id
    return "K1-UNKNOWN"


def _year_meta(
    obs: Observed | None, year: int | None, threshold: float
) -> tuple[float | None, str | None]:
    """Confidence for the tax year.

    ``assemble`` is the extractor path, so a missing label is a real miss at
    confidence 0. Generator records leave the field unset and are not treated
    as low-confidence extractions.
    """

    if obs is None:
        return 0.0, None
    confidence = evidence_confidence(
        label_score=obs.label_score,
        proximity=obs.proximity,
        ocr_confidence=obs.ocr_confidence,
        reported_confidence=obs.reported_confidence,
        parsed=year is not None,
        format_ok=None,
    )
    return _cap_llm(_limit(confidence, obs, threshold), obs, threshold), obs.extractor


def _tax_year(obs: Observed | None) -> int | None:
    if obs is None:
        return None
    text = obs.raw.strip()
    if not text.isdigit():
        return None
    year = int(text)
    if 1990 <= year <= 2100:
        return year
    return None

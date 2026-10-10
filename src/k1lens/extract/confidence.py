"""Confidence from extraction signals.

The score does not look at ground truth. It combines:

- label match quality (exact catalog label, or one edit on an OCR line)
- whether the value came from a text layer, from Tesseract word confidence,
  or from an LLM self-report
- how close the value sits to its label
- whether the token parsed as the expected type
- whether an EIN, TIN, percentage, or withdrawal has a legal shape
- whether the item L capital account agrees with itself, or could not be tested

A reviewer threshold is a separate setting. This module does not force every
OCR value under that threshold.
"""

from __future__ import annotations

import re
from decimal import Decimal

from k1lens.domain.fields import CAPITAL_COMPONENTS, REVIEW_THRESHOLD, FieldKind
from k1lens.domain.models import ScheduleK1
from k1lens.domain.parsing import (
    STATE_PATHS,
    USPS_STATES,
    capital_method_ok,
    entity_type_ok,
    irs_center_ok,
    is_ein_text,
    is_ssn_text,
)
from k1lens.validate.engine import validate_document

LABEL_EXACT = 1.0
LABEL_ONE_EDIT = 0.55
_LABEL_WEIGHT = 0.40
_PROXIMITY_WEIGHT = 0.16
_SOURCE_WEIGHT = 0.24
_PARSE_WEIGHT = 0.12
_FORMAT_BONUS = 0.08
_FORMAT_PENALTY = 0.22
_UNKNOWN_PROXIMITY = 0.45
_PARSE_FAIL_CAP = 0.25
_CAPITAL_PENALTY = 0.22


def below_review_threshold(threshold: float = REVIEW_THRESHOLD) -> float:
    """A confidence cap that cannot clear ``threshold``.

    0.49 is the cap used under the default 0.80 threshold. A lower
    ``--threshold`` pulls the cap down with it.
    """

    if threshold <= 0:
        return 0.0
    under = max(0.0, threshold - 0.01)
    if threshold > 0.49:
        return min(0.49, under)
    return under


# One hundredth under the default review threshold of 0.80. An llm-only
# value is stored at this number, or lower when ``--threshold`` is lower.
# Llm mode never clears a field. Every llm value goes to review.
LLM_ONLY_CONFIDENCE_CAP = 0.79


def llm_only_confidence_cap(threshold: float = REVIEW_THRESHOLD) -> float:
    """Highest confidence an llm-extracted value may store.

    ``LLM_ONLY_CONFIDENCE_CAP`` is 0.79, just under the default 0.80
    review threshold. A model's self-report, including 1.0, does not
    raise a value to that line. A lower ``--threshold`` pulls the cap
    down so the stored score stays strictly below the line in force.
    """

    if threshold <= 0:
        return 0.0
    under = max(0.0, threshold - 0.01)
    if under > LLM_ONLY_CONFIDENCE_CAP:
        return LLM_ONLY_CONFIDENCE_CAP
    return under


def clamp_unit(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def evidence_confidence(
    *,
    label_score: float,
    proximity: float | None,
    ocr_confidence: float | None,
    reported_confidence: float | None,
    parsed: bool,
    format_ok: bool | None,
) -> float:
    """Fold one field's signals into a confidence in ``[0, 1]``."""

    score = _LABEL_WEIGHT * clamp_unit(label_score)
    if proximity is None:
        score += _PROXIMITY_WEIGHT * _UNKNOWN_PROXIMITY
    else:
        score += _PROXIMITY_WEIGHT * clamp_unit(proximity)
    if ocr_confidence is not None:
        score += _SOURCE_WEIGHT * clamp_unit(ocr_confidence)
    elif reported_confidence is not None:
        score += _SOURCE_WEIGHT * clamp_unit(reported_confidence)
    else:
        score += _SOURCE_WEIGHT
    if not parsed:
        return min(score, _PARSE_FAIL_CAP)
    score += _PARSE_WEIGHT
    if format_ok is True:
        score += _FORMAT_BONUS
    elif format_ok is False:
        score -= _FORMAT_PENALTY
    return clamp_unit(score)


_STREET = re.compile(
    r"^(?:\d{1,6}\s+\S+(?:\s+\S+){0,8}|(?:P\.?\s*O\.?\s*Box)\s+\d[\w-]*(?:\s+\S+){0,4})$",
    re.IGNORECASE,
)
_NAME_PATHS = frozenset({"part_i.name", "part_ii.name"})
_CITY_PATHS = frozenset({"part_i.city", "part_ii.city"})
_STREET_PATHS = frozenset({"part_i.street", "part_ii.street"})
_ZIP_PATHS = frozenset({"part_i.zip_code", "part_ii.zip_code"})
_ZIP = re.compile(r"^\d{5}(?:-\d{4})?$")
_INSTRUCTION = re.compile(
    r"\b(?:see\s+instructions|see\s+statement|see\s+page|page\s+\d+|box\s+\d)\b",
    re.IGNORECASE,
)
# A header the IRS prints above the form, not a filer's name. A partnership
# that merely contains one of these words and an entity suffix can still pass.
_AGENCY = re.compile(
    r"^(?:department\s+of\b|internal\s+revenue\b|united\s+states\b)",
    re.IGNORECASE,
)
# Closed grammatical class. These words open a note, a pointer, or a
# negation. They are not a list of probe sentences. ``Per`` and ``Perry``
# are not in it: the whole word has to match.
_OPENER = frozenset(
    {
        "attached",
        "do",
        "dont",
        "enclosed",
        "neither",
        "never",
        "no",
        "none",
        "nor",
        "not",
        "please",
        "refer",
        "referred",
        "same",
        "see",
        "via",
        "without",
    }
)
# Placeholder words. A value that uses one is a status, not a name or a city.
_STATUS = frozenset(
    {
        "above",
        "applicable",
        "available",
        "awaiting",
        "below",
        "blank",
        "confidential",
        "determined",
        "held",
        "missing",
        "na",
        "omitted",
        "pending",
        "provided",
        "redacted",
        "tba",
        "tbd",
        "unavailable",
        "unknown",
        "various",
        "withheld",
    }
)
_PARTICLE = frozenset(
    {"al", "and", "bin", "da", "de", "del", "la", "le", "of", "the", "van", "von", "y"}
)
_ROLE = frozenset({"caption", "copy", "item", "items", "legend", "line"})
_STREET_LAST = frozenset(
    {
        "ave",
        "avenue",
        "blvd",
        "boulevard",
        "cir",
        "circle",
        "court",
        "ct",
        "dr",
        "drive",
        "highway",
        "hwy",
        "lane",
        "ln",
        "parkway",
        "pkwy",
        "place",
        "pl",
        "rd",
        "road",
        "st",
        "street",
        "ter",
        "terrace",
        "trail",
        "trl",
        "way",
    }
)
# Legal and generational suffixes. Periods are ignored, so ``L.P.`` and
# ``L.L.C.`` match the same tokens as ``LP`` and ``LLC``.
_SUFFIX_LETTERS = frozenset(
    {
        "CO",
        "CORP",
        "ESQ",
        "II",
        "III",
        "INC",
        "IV",
        "JR",
        "LLC",
        "LLP",
        "LP",
        "LTD",
        "PC",
        "PLLC",
        "SR",
        "V",
    }
)
_SAINT = re.compile(r"^(?:St|Ft|Mt)\.$")
# McDonald, MacArthur, DeLeon: one internal capital after a short prefix.
_INNER_CAP = re.compile(r"^[A-Z][a-z]{1,3}[A-Z][a-z]+$")
_AUXILIARY_ROW = re.compile(r"(?i)^(?:form\s+\S+|schedule\s+\S+|statement\b|supplemental\b)")
# Tesseract word confidence, on 0-1. A misread name or city below this
# stays in review even when the letters have the right shape.
_OCR_WORD_CLEAR = 0.90


def identity_path(path: str) -> bool:
    """Partner and partnership identity fields, plus entity type.

    Amounts and coded boxes are not in this set. A neighbor line can still
    carry an amount. It cannot carry one of these.
    """

    return (
        path in _NAME_PATHS
        or path in _CITY_PATHS
        or path in _STREET_PATHS
        or path in _ZIP_PATHS
        or path in STATE_PATHS
        or path == "part_ii.entity_type"
    )


def strip_trailing_punctuation(value: str) -> str:
    """Drop a trailing period or comma. Internal periods, as in ``St. Louis``, stay."""

    return " ".join(value.strip().rstrip(".,;:").split())


def identity_may_clear(
    path: str, value: str, *, own_box: bool, prefix_stripped: bool = False
) -> bool:
    """Whether one reading of an identity field may reach the review threshold.

    The value has to pass that field's shape, and a second fact has to
    corroborate it: its own labeled box, with no neighbor line and no
    neighbor column. A title-case phrase is not a name shape. Two readings
    that agree do not clear the field. Hybrid never stores an identity
    value from the model. An entity type
    may clear only when it matches a canonical entity string exactly, still
    only from its own box. A value that was shortened by dropping caption
    words does not clear from the remainder alone.
    """

    if prefix_stripped or not own_box:
        return False
    token = " ".join(value.split())
    if path == "part_ii.entity_type":
        return entity_type_ok(token)
    if path in STATE_PATHS:
        return len(token) == 2 and token.isupper() and token in USPS_STATES
    if path in _ZIP_PATHS:
        return _ZIP.fullmatch(token) is not None
    if path in _STREET_PATHS:
        return _street_ok(token)
    if path in _CITY_PATHS:
        return _city_may_clear(strip_trailing_punctuation(token))
    if path in _NAME_PATHS:
        return _name_may_clear(token)
    return False


def _name_may_clear(value: str) -> bool:
    """A name with a structural marker, not a run of title-case words.

    The marker is a legal or generational suffix at the end, a dotted
    initial, a hyphen or apostrophe, an internal capital (``McDonald``),
    an ampersand, a name particle, or a trailing fund number. Words after
    a suffix are another column's name and do not clear.
    """

    if not name_shape_ok(value):
        return False
    words = value.split()
    suffix_at = [index for index, word in enumerate(words) if _is_suffix(word)]
    if suffix_at:
        return suffix_at[-1] == len(words) - 1
    for word in words:
        core = _core(word)
        if word == "&" or core == "&":
            return True
        if re.fullmatch(r"(?:[A-Z]\.)+", core):
            return True
        if re.search(r"[A-Za-z][-'][A-Za-z]", core):
            return True
        if _INNER_CAP.fullmatch(core):
            return True
        if _is_particle(word, first=False):
            return True
    return bool(words) and re.fullmatch(r"\d{1,4}", _core(words[-1])) is not None


def _city_may_clear(value: str) -> bool:
    """A city shape, including a particle and more than one word.

    Shape is not enough on its own. ``city_linked_to_state_or_zip`` has to
    see a state or ZIP on the same line or on a linked line in this column.
    """

    return city_shape_ok(value)


def city_linked_to_state_or_zip(
    city_value: str,
    city_bbox: tuple[float, float, float, float] | None,
    state_value: str | None,
    state_bbox: tuple[float, float, float, float] | None,
    zip_value: str | None,
    zip_bbox: tuple[float, float, float, float] | None,
) -> bool:
    """True when a state or ZIP sits with this city.

    The token can be on the city line itself. Otherwise it is the party's
    state or ZIP, read in the same column and within an address block of
    the city. A state in the other column is not a link. With no boxes,
    a parsed state or ZIP for this party is the link, so a text-layer city
    is not held just because the page had no word coordinates.
    """

    if _line_has_state_or_zip(city_value):
        return True
    # The linked field can carry a trailing fragment, as in ``MA 2`` when a
    # ZIP digit sticks to the abbreviation. A token on that line is the link.
    # The whole field still has to be a clean abbreviation to clear on its own.
    state_has = isinstance(state_value, str) and _line_has_state_or_zip(state_value)
    zip_has = isinstance(zip_value, str) and _line_has_state_or_zip(zip_value)
    if city_bbox is None:
        return state_has or zip_has
    if state_has and _same_address_column(city_bbox, state_bbox):
        return True
    return bool(zip_has and _same_address_column(city_bbox, zip_bbox))


def reads_as_field_caption(value: str) -> bool:
    """True when the whole line is some field's caption, not a value in a box."""

    text = " ".join(value.split())
    if text == "":
        return False
    from k1lens.extract.geometry import resolve_printed

    hit = resolve_printed(text)
    if hit is None:
        return False
    label, score = hit
    return score >= 1.0 and text.casefold() == label.casefold()


def _line_has_state_or_zip(value: str) -> bool:
    for token in re.findall(r"\b[A-Za-z]{2}\b|\b\d{5}(?:-\d{4})?\b", value):
        if _ZIP.fullmatch(token):
            return True
        if token.isupper() and token in USPS_STATES:
            return True
    return False


def _same_address_column(
    city: tuple[float, float, float, float],
    other: tuple[float, float, float, float] | None,
) -> bool:
    if other is None:
        return False
    if abs(city[0] - other[0]) > 48.0:
        return False
    return abs(city[1] - other[1]) <= 160.0


def city_line_under_a_name(value: str) -> bool:
    """True when the line under a blank name is a city, not a name.

    One place word, or a ``St. Louis`` form, is that city line. A structural
    name is not. Two ordinary words can be a person name on the next line of
    a stacked layout, so they are not treated as the city. A multi-word city
    can still clear when it is read as the city itself.
    """

    token = strip_trailing_punctuation(" ".join(value.split()))
    if not city_shape_ok(token) or _name_may_clear(token):
        return False
    words = token.split()
    if len(words) == 1:
        return True
    return len(words) == 2 and _SAINT.fullmatch(words[0]) is not None


def auxiliary_address_row(value: str) -> bool:
    """True for a statement, supplemental, or other-form row.

    Those rows are not a street, city, state, or ZIP. The row opens like
    another form, or the whole line is some other field's caption.
    """

    text = " ".join(value.split())
    if text == "":
        return False
    if _AUXILIARY_ROW.match(text):
        return True
    from k1lens.domain.fields import SCALAR_BY_LABEL

    return any(text.lower() == label.lower() for label in SCALAR_BY_LABEL)


def position_free_text_ok(
    path: str, value: object, *, ocr_confidence: float | None = None
) -> bool | None:
    """Positive shape gate for a free-text value.

    None means this path is not gated here. EIN, TIN, and state use
    ``format_ok_for``. A name, city, street, ZIP, IRS center, entity type,
    or capital method clears 0.80 only when it positively matches that
    field. Anything else stays under the review threshold. Phrase lists
    elsewhere can still drop a value; they are not this gate. An OCR name
    or city also needs a high word confidence.
    """

    if not isinstance(value, str):
        return None
    token = " ".join(value.split())
    if path in _NAME_PATHS:
        ok = name_shape_ok(token)
        if ocr_confidence is not None and ocr_confidence < _OCR_WORD_CLEAR:
            return False
        return ok
    if path in _CITY_PATHS:
        ok = city_shape_ok(token)
        if ocr_confidence is not None and ocr_confidence < _OCR_WORD_CLEAR:
            return False
        return ok
    if path in _STREET_PATHS:
        return _street_ok(token)
    if path == "part_i.irs_center":
        return irs_center_ok(token)
    if path in _ZIP_PATHS:
        return _ZIP.fullmatch(token) is not None
    if path == "part_ii.entity_type":
        return entity_type_ok(token)
    if path == "part_ii.capital_method":
        return capital_method_ok(token)
    return None


def name_shape_ok(value: str) -> bool:
    """True when ``value`` reads as a person or entity name.

    Mostly alphabetic words, in title case or capitals, with an optional
    leading number and an optional entity or generational suffix. A form
    caption, an agency header, an instruction, a street, a note, or a line
    that starts with a negation or a pointer does not pass.
    """

    text = " ".join(value.split())
    if text == "" or _INSTRUCTION.search(text) is not None or _looks_like_street(text):
        return False
    words = text.split()
    start = 1 if re.fullmatch(r"\d{1,6}", _core(words[0])) else 0
    body = words[start:]
    words_ok = all(_name_word_ok(word, first=index == 0) for index, word in enumerate(body))
    if not body or not words_ok:
        return False
    if _blocked_opener(body[0]):
        return False
    suffix = _has_suffix(body)
    if _AGENCY.search(" ".join(body)) and not suffix:
        return False
    if any(_is_status(_core(word)) for word in body):
        return False
    if _core(body[-1]).lower() in _ROLE and not suffix:
        return False
    if any(_core(word).lower() == "by" for word in body) and not suffix:
        return False
    content = [
        word for word in body if not _is_suffix(word) and not _is_particle(word, first=False)
    ]
    if suffix:
        return bool(content) and not _all_caption(content)
    if len(content) < 2 or _all_caption(content):
        return False
    first = _core(content[0])
    from k1lens.extract.labels import _caption_token, catalog_caption_words

    return _caption_token(first) not in catalog_caption_words()


def name_line_to_skip(value: str) -> bool:
    """True when a name label should stay open instead of storing this line.

    A street, a numbered heading that is not a name, a line that ends in a
    role word, a preparer line, or a line made only of caption words is not
    the name. A status, an agency header, or any other readable string that
    merely fails the name shape is still stored. The shape gate holds it
    under 0.80.
    """

    text = " ".join(value.split())
    if text == "" or name_shape_ok(text):
        return False
    if _looks_like_street(text):
        return True
    words = text.split()
    if re.fullmatch(r"\d{1,2}", _core(words[0])):
        return True
    if _core(words[-1]).lower() in _ROLE:
        return True
    if any(_core(word).lower() == "by" for word in words):
        return True
    content = [word for word in words if not _is_suffix(word)]
    return bool(content) and _all_caption(content)


def city_shape_ok(value: str) -> bool:
    """True for one to three alphabetic place words, including ``St. Louis``."""

    text = " ".join(value.split())
    if text == "" or _INSTRUCTION.search(text) is not None:
        return False
    words = text.split()
    if len(words) > 3 or _blocked_opener(words[0]):
        return False
    if any(_is_status(_core(word)) for word in words):
        return False
    if _AGENCY.search(text):
        return False
    return all(_city_word_ok(word, first=index == 0) for index, word in enumerate(words))


def strip_caption_prefix(path: str, value: str) -> tuple[str, bool]:
    """Drop a printed caption that continues past the catalog label.

    Returns the stored text and whether any caption word was removed.
    ``address, city, state, and ZIP code Northwind Partners LP`` keeps the
    name. A value that already has that field's shape is left as read, so a
    real name that happens to contain a caption word is not shortened. The
    shorter remainder is not itself enough to clear review.
    """

    if path in _NAME_PATHS:
        shape = name_shape_ok
    elif path in _CITY_PATHS:
        shape = city_shape_ok
    else:
        return value, False
    if shape(value):
        return value, False
    from k1lens.domain.fields import SCALAR_FIELDS
    from k1lens.extract.labels import _caption_token, field_caption_tokens

    label = next((spec.pdf_label for spec in SCALAR_FIELDS if spec.path == path), "")
    if label == "":
        return value, False
    tokens = field_caption_tokens(label)
    words = value.split()
    count = 0
    for index, word in enumerate(words):
        token = _caption_token(_core(word))
        following = _caption_token(_core(words[index + 1])) if index + 1 < len(words) else ""
        if token == "see" and following in {"instructions", "instruction", "statement", "page"}:
            count += 1
            continue
        if token in tokens or token in {"instructions", "instruction"} or word.islower():
            count += 1
            continue
        break
    if count == 0 or count >= len(words):
        return value, False
    rest = " ".join(words[count:])
    if rest != value and shape(rest):
        return rest, True
    return value, False


def _street_ok(value: str) -> bool:
    if _STREET.fullmatch(value) is None or _INSTRUCTION.search(value) is not None:
        return False
    words = value.split()
    return not words or not _blocked_opener(words[0])


def _looks_like_street(value: str) -> bool:
    """A house number or a PO Box. A numbered partnership name is not a street."""

    if re.match(r"(?i)^(?:P\.?\s*O\.?\s*Box)\s+\d", value):
        return True
    words = [_core(word).lower().rstrip(".") for word in value.split()]
    return len(words) >= 2 and words[0].isdigit() and words[-1] in _STREET_LAST


def _name_word_ok(word: str, *, first: bool) -> bool:
    core = _core(word)
    if word == "&" or core == "&":
        return True
    if core == "":
        return False
    if _is_suffix(word) or _is_particle(word, first=first):
        return True
    if re.fullmatch(r"\d{1,4}", core):
        return True
    if len(core) == 1 and core.isalpha() and core.isupper():
        return True
    if re.fullmatch(r"(?:[A-Z]\.)+", core):
        return True
    if re.fullmatch(r"[A-Z]{2,12}", core):
        return True
    if _INNER_CAP.fullmatch(core):
        return True
    pieces = [piece for piece in re.split(r"[-']", core) if piece]
    if not pieces or not all(_name_piece(piece) for piece in pieces):
        return False
    return any(_title_piece(piece) for piece in pieces)


def _city_word_ok(word: str, *, first: bool) -> bool:
    if _SAINT.fullmatch(word):
        return True
    core = _core(word)
    if re.fullmatch(r"[A-Z]{2,20}", core):
        return True
    if not first and re.fullmatch(r"[a-z]{2,3}", core):
        return True
    pieces = [piece for piece in re.split(r"[-']", core) if piece]
    return bool(pieces) and all(_title_piece(piece) for piece in pieces)


def _name_piece(piece: str) -> bool:
    if _title_piece(piece):
        return True
    return len(piece) == 1 and piece.isalpha() and piece.isupper()


def _title_piece(piece: str) -> bool:
    return len(piece) >= 2 and piece.isalpha() and piece[0].isupper() and piece[1:].islower()


def _core(word: str) -> str:
    return word.strip(".,;:()[]\"'")


def _is_suffix(word: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", _core(word)).upper()
    return letters in _SUFFIX_LETTERS


def _has_suffix(words: list[str]) -> bool:
    return any(_is_suffix(word) for word in words)


def _is_particle(word: str, *, first: bool) -> bool:
    if first:
        return False
    return re.sub(r"[^a-z]", "", _core(word).lower()) in _PARTICLE


def _blocked_opener(word: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", _core(word).lower()) in _OPENER


def _is_status(word: str) -> bool:
    return re.sub(r"[^a-z0-9]", "", word.lower()) in _STATUS


def _all_caption(words: list[str]) -> bool:
    from k1lens.extract.labels import _caption_token, catalog_caption_words

    banned = catalog_caption_words()
    cores = [_caption_token(_core(word)) for word in words]
    return bool(cores) and all(token in banned for token in cores)


def format_ok_for(kind: FieldKind, path: str, value: object) -> bool | None:
    """Return a format check, or None when the field has no shape rule."""

    if value is None:
        return None
    if path == "part_i.ein":
        return is_ein_text(str(value))
    if path == "part_ii.tin":
        return is_ein_text(str(value)) or is_ssn_text(str(value))
    if path in STATE_PATHS:
        token = str(value).strip()
        return len(token) == 2 and token == token.upper() and token in USPS_STATES
    if kind is FieldKind.PERCENT:
        number = Decimal(str(value))
        return Decimal("0") <= number <= Decimal("100")
    if path == "part_ii.capital.withdrawals" or path.startswith("part_iii.distributions"):
        return Decimal(str(value)) >= 0
    return None


def cap_confidences(document: ScheduleK1, cap: float) -> ScheduleK1:
    """Lower every extracted confidence to ``cap`` and mark the layout unknown.

    An unrecognized page can still contain a few lucky reads. Those values
    stay visible, but none of them clear the review threshold.
    """

    data = document.model_dump(mode="json")
    _cap_tree(data, cap)
    data["layout_recognized"] = False
    return ScheduleK1.model_validate(data)


def _cap_tree(node: object, cap: float) -> None:
    if isinstance(node, dict):
        if "confidence" in node and "provenance" in node:
            raw = node.get("confidence")
            if isinstance(raw, int | float):
                node["confidence"] = min(float(raw), cap)
        for value in node.values():
            _cap_tree(value, cap)
    elif isinstance(node, list):
        for item in node:
            _cap_tree(item, cap)


def apply_agreement(document: ScheduleK1) -> ScheduleK1:
    """Lower capital-account confidence when item L does not tie, or was not tested.

    The six item L amounts are one cross-check. A mismatch lowers each of
    them. A missing amount skips that check, so the amounts that did parse
    are unverified and take the same penalty. Either way the highest score,
    1.00, falls to 0.78, under the default 0.80 review threshold. Other rules
    are already reflected by ``format_ok_for``.
    """

    findings = validate_document(document)
    failed = any(
        finding.rule_id == "capital_reconciles" and finding.severity.value == "error"
        for finding in findings
    )
    untested = any(finding.rule_id == "capital_incomplete" for finding in findings)
    if not failed and not untested:
        return document
    data = document.model_dump(mode="json")
    for path in CAPITAL_COMPONENTS:
        _lower(data, path, _CAPITAL_PENALTY)
    return ScheduleK1.model_validate(data)


def _lower(data: dict[str, object], path: str, penalty: float) -> None:
    node: object = data
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict) and "confidence" in node:
        _penalize(node, penalty)


def _penalize(node: dict[str, object], penalty: float) -> None:
    raw = node.get("confidence")
    if isinstance(raw, int | float):
        node["confidence"] = clamp_unit(float(raw) - penalty)

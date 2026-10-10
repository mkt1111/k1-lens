"""Client roster used to verify partnership and partner identity.

The roster is an input. Nothing in extraction or eval loads one unless the
caller passes a path. A match stores the value read from the page. It never
writes the roster text over a misread.

Normalization for names, streets, cities, and states is case and whitespace
only. A ZIP drops whitespace and nothing else, so a 5-digit ZIP does not
match ZIP+4. Identifiers are the full EIN or TIN. The last four digits are
not a key.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from k1lens.domain.access import get_extracted
from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import Extracted, ScheduleK1

# Name, street, city, state, and ZIP. Entity type is not in this set.
ROSTER_IDENTITY_PATHS = frozenset(
    {
        "part_i.name",
        "part_i.street",
        "part_i.city",
        "part_i.state",
        "part_i.zip_code",
        "part_ii.name",
        "part_ii.street",
        "part_ii.city",
        "part_ii.state",
        "part_ii.zip_code",
    }
)

_EIN = re.compile(r"^\d{2}-\d{7}$")
_SSN = re.compile(r"^\d{3}-\d{2}-\d{4}$")
# The project's generated EINs start with 00 and its SSNs with 000. Those
# prefixes are not issued. The format check below accepts them on purpose.
SYNTHETIC_EIN_PREFIX = "00-"
SYNTHETIC_SSN_PREFIX = "000-"

_PARTNERSHIP_FIELDS = (
    "part_i.name",
    "part_i.street",
    "part_i.city",
    "part_i.state",
    "part_i.zip_code",
)
_INVESTOR_FIELDS = (
    "part_ii.name",
    "part_ii.street",
    "part_ii.city",
    "part_ii.state",
    "part_ii.zip_code",
)
_RECORD_KEYS = ("name", "street", "city", "state", "zip_code")


@dataclass(frozen=True, slots=True)
class PartnershipRecord:
    name: str
    ein: str
    street: str
    city: str
    state: str
    zip_code: str


@dataclass(frozen=True, slots=True)
class InvestorRecord:
    name: str
    tin: str
    street: str
    city: str
    state: str
    zip_code: str


@dataclass(frozen=True, slots=True)
class Roster:
    partnerships: tuple[PartnershipRecord, ...]
    investors: tuple[InvestorRecord, ...]


@dataclass(frozen=True, slots=True)
class IdentityHold:
    """One roster decision, before it becomes a validation finding."""

    rule_id: str
    field_path: str
    message: str


def load_roster(path: Path) -> Roster:
    """Read a roster JSON file. The file is not consulted unless this is called."""

    payload = json.loads(path.read_text(encoding="utf-8"))
    return parse_roster(payload, source=path)


def parse_roster(payload: object, *, source: Path | None = None) -> Roster:
    """Build a roster from a JSON object. Extra keys, including a note, are ignored."""

    label = source if source is not None else Path("roster")
    if not isinstance(payload, dict):
        raise ValueError(f"Roster {label} must be a JSON object.")
    partnerships = tuple(_partnership(item) for item in _records(payload, "partnerships", label))
    investors = tuple(_investor(item) for item in _records(payload, "investors", label))
    return Roster(partnerships=partnerships, investors=investors)


def roster_from_documents(documents: Sequence[ScheduleK1]) -> Roster:
    """Copy identity off documents the caller already has.

    The first record for an EIN or TIN is kept. A blank field is copied blank,
    so it cannot clear that field. ``evaluate`` does not call this.
    """

    partnerships: list[PartnershipRecord] = []
    investors: list[InvestorRecord] = []
    eins: set[str] = set()
    tins: set[str] = set()
    for document in documents:
        ein = _copied_id(document, "part_i.ein")
        if ein and ein not in eins:
            eins.add(ein)
            partnerships.append(
                PartnershipRecord(
                    name=_copied(document, "part_i.name"),
                    ein=ein,
                    street=_copied(document, "part_i.street"),
                    city=_copied(document, "part_i.city"),
                    state=_copied(document, "part_i.state"),
                    zip_code=_copied(document, "part_i.zip_code"),
                )
            )
        tin = _copied_id(document, "part_ii.tin")
        if tin and tin not in tins:
            tins.add(tin)
            investors.append(
                InvestorRecord(
                    name=_copied(document, "part_ii.name"),
                    tin=tin,
                    street=_copied(document, "part_ii.street"),
                    city=_copied(document, "part_ii.city"),
                    state=_copied(document, "part_ii.state"),
                    zip_code=_copied(document, "part_ii.zip_code"),
                )
            )
    return Roster(partnerships=tuple(partnerships), investors=tuple(investors))


def roster_from_fixture_dir(fixture_dir: Path) -> Roster:
    """Copy identity from a corpus's ground truth.

    Those documents' identity was known before scoring. Pass the written file
    to ``k1lens eval --roster``. Scoring does not build this on its own.
    """

    from k1lens.generate.corpus import load_ground_truth, load_manifest

    manifest = load_manifest(fixture_dir)
    documents = [
        load_ground_truth(fixture_dir / entry.ground_truth).document for entry in manifest.documents
    ]
    return roster_from_documents(documents)


def dump_roster(roster: Roster) -> dict[str, object]:
    """JSON object for ``load_roster``. ZIP is stored under ``zip``."""

    return {
        "partnerships": [
            {
                "name": item.name,
                "ein": item.ein,
                "street": item.street,
                "city": item.city,
                "state": item.state,
                "zip": item.zip_code,
            }
            for item in roster.partnerships
        ],
        "investors": [
            {
                "name": item.name,
                "tin": item.tin,
                "street": item.street,
                "city": item.city,
                "state": item.state,
                "zip": item.zip_code,
            }
            for item in roster.investors
        ],
    }


def synthetic_id_allowed(value: str) -> bool:
    """True for the project's test-only EIN and SSN ranges.

    Real issuance rules reject an EIN that starts with ``00`` and an SSN
    that starts with ``000``. This gate does not. The check is the dash
    pattern and nine digits, and these prefixes are accepted on purpose.
    """

    text = " ".join(value.split())
    if _EIN.fullmatch(text) and text.startswith(SYNTHETIC_EIN_PREFIX):
        return True
    return bool(_SSN.fullmatch(text) and text.startswith(SYNTHETIC_SSN_PREFIX))


def classify_id(value: object) -> str:
    """``missing``, ``masked``, ``invalid``, or ``valid``.

    Valid means nine digits in the EIN or SSN dash pattern, including the
    synthetic ``00-`` and ``000-`` ranges. A mask (asterisks, X, or only
    four digits) is not valid and is not looked up by those four digits.
    """

    if not isinstance(value, str) or value.strip() == "":
        return "missing"
    text = " ".join(value.split())
    if _is_masked(text):
        return "masked"
    if _EIN.fullmatch(text) or _SSN.fullmatch(text):
        return "valid"
    return "invalid"


def id_read_is_confident(field: Extracted[Any], *, threshold: float) -> bool:
    """True when this EIN or TIN can be used as a roster key.

    The stored text has to pass the format check. Its confidence has to
    clear the review threshold. On an OCR read, every digit word has to
    clear that same threshold. A missing per-digit score on OCR is not a
    confident read. Nothing here rewrites a digit.
    """

    if classify_id(field.value) != "valid":
        return False
    if field.confidence < threshold:
        return False
    digit = field.provenance.id_digit_confidence
    if field.provenance.extractor == "ocr":
        return digit is not None and digit >= threshold
    return digit is None or digit >= threshold


def bind_roster(
    document: ScheduleK1,
    roster: Roster | None,
    *,
    threshold: float = REVIEW_THRESHOLD,
) -> ScheduleK1:
    """Lift a whole identity section to the review threshold.

    The lift is exactly ``threshold``, never higher. It runs only when the
    key id was read confidently, every field matches that same roster record,
    and each value was read from its own region. A model value, a partial
    match, a duplicate key, or an unrecognized layout lifts nothing. The
    stored string stays the page string.
    """

    if not document.layout_recognized:
        return document
    data = document.model_dump(mode="json")
    for fields, record in _section_records(document, roster, threshold):
        if record is None or not _section_matches(document, fields, record):
            continue
        if not _section_can_lift(data, fields):
            continue
        for path in fields:
            node = _node(data, path)
            if isinstance(node, dict):
                _lift_field(node, threshold)
    return ScheduleK1.model_validate(data)


def lifted_identity_paths(
    before: ScheduleK1,
    after: ScheduleK1,
    *,
    threshold: float = REVIEW_THRESHOLD,
) -> tuple[str, ...]:
    """Identity fields whose confidence moved up to exactly ``threshold``."""

    found: list[str] = []
    for path in (*_PARTNERSHIP_FIELDS, *_INVESTOR_FIELDS):
        old = get_extracted(before, path)
        new = get_extracted(after, path)
        if old.value != new.value:
            continue
        if old.confidence < threshold and new.confidence == threshold:
            found.append(path)
    return tuple(found)


def identity_holds(
    document: ScheduleK1,
    roster: Roster | None,
    *,
    threshold: float = REVIEW_THRESHOLD,
) -> list[IdentityHold]:
    """Holds for the review queue. One row per identity field."""

    if roster is None:
        return [
            IdentityHold(
                rule_id="no_roster",
                field_path=path,
                message=("No client roster was supplied, so this identity field stays in review."),
            )
            for path in (*_PARTNERSHIP_FIELDS, *_INVESTOR_FIELDS)
        ]
    holds: list[IdentityHold] = []
    holds.extend(
        _section_holds(
            document,
            key_path="part_i.ein",
            key_label="EIN",
            fields=_PARTNERSHIP_FIELDS,
            records=roster.partnerships,
            key_of=lambda record: record.ein,
            threshold=threshold,
        )
    )
    holds.extend(
        _section_holds(
            document,
            key_path="part_ii.tin",
            key_label="TIN",
            fields=_INVESTOR_FIELDS,
            records=roster.investors,
            key_of=lambda record: record.tin,
            threshold=threshold,
        )
    )
    return holds


def count_confident_ids(document: ScheduleK1, *, threshold: float = REVIEW_THRESHOLD) -> int:
    """How many of the two id fields were read confidently. Zero, one, or two."""

    count = 0
    for path in ("part_i.ein", "part_ii.tin"):
        field = get_extracted(document, path)
        if id_read_is_confident(field, threshold=threshold):
            count += 1
    return count


def _section_holds[Record: (PartnershipRecord, InvestorRecord)](
    document: ScheduleK1,
    *,
    key_path: str,
    key_label: str,
    fields: tuple[str, ...],
    records: Sequence[Record],
    key_of: Callable[[Record], str],
    threshold: float,
) -> list[IdentityHold]:
    key_field = get_extracted(document, key_path)
    status = classify_id(key_field.value)
    if status != "valid":
        return _broadcast(
            fields,
            "no_tin",
            f"The {key_label} is {status}, so this section cannot be matched to the roster.",
        )
    if not id_read_is_confident(key_field, threshold=threshold):
        return _broadcast(
            fields,
            "no_roster_match",
            (
                f"The {key_label} is not a confident read, so it is not used as a roster key. "
                "Digits are not repaired."
            ),
        )
    assert isinstance(key_field.value, str)
    match, duplicate = _find_record(records, key_of, key_field.value)
    if duplicate:
        return _broadcast(
            fields,
            "duplicate_roster_key",
            (f"More than one roster record uses this {key_label}, so none of them is a match."),
        )
    if match is None:
        return _broadcast(
            fields,
            "new_partner",
            f"No roster record uses this {key_label}.",
        )
    if _section_matches(document, fields, match):
        return []
    return _broadcast(
        fields,
        "identity_mismatch",
        (
            f"The {key_label} is on the roster, and an identity field on the page "
            "does not match that same record."
        ),
    )


def _section_matches(
    document: ScheduleK1,
    fields: tuple[str, ...],
    record: PartnershipRecord | InvestorRecord,
) -> bool:
    for path, attr in zip(fields, _RECORD_KEYS, strict=True):
        page = get_extracted(document, path).value
        roster_value = getattr(record, attr)
        if not isinstance(roster_value, str) or roster_value.strip() == "":
            return False
        if not isinstance(page, str) or page.strip() == "":
            return False
        if not _values_match(path, page, roster_value):
            return False
    return True


def _values_match(path: str, page: str, roster_value: str) -> bool:
    if path.endswith(".zip_code"):
        return _zip_key(page) == _zip_key(roster_value) and _zip_key(page) != ""
    return _text_key(page) == _text_key(roster_value) and _text_key(page) != ""


def _text_key(value: str) -> str:
    return " ".join(value.split()).casefold()


def _zip_key(value: str) -> str:
    return "".join(value.split())


def _find_record[Record: (PartnershipRecord, InvestorRecord)](
    records: Sequence[Record],
    key_of: Callable[[Record], str],
    page_key: str,
) -> tuple[Record | None, bool]:
    """Return the single record for this id, and whether the id is duplicated.

    Two records with the same EIN or TIN are not a match. The first record
    is not used.
    """

    wanted = " ".join(page_key.split())
    found: Record | None = None
    for record in records:
        candidate = key_of(record)
        if not isinstance(candidate, str):
            continue
        if " ".join(candidate.split()) == wanted:
            if found is not None:
                return None, True
            found = record
    return found, False


def _section_can_lift(data: dict[str, object], fields: tuple[str, ...]) -> bool:
    """Every field was read from its own region, with no model value."""

    for path in fields:
        node = _node(data, path)
        if not isinstance(node, dict):
            return False
        provenance = node.get("provenance")
        if not isinstance(provenance, dict):
            return False
        extractor = provenance.get("extractor")
        if extractor == "llm":
            return False
        if provenance.get("own_region") is False:
            return False
    return True


def _lift_field(node: dict[str, object], threshold: float) -> None:
    provenance = node.get("provenance")
    extractor = provenance.get("extractor") if isinstance(provenance, dict) else None
    if isinstance(extractor, str) and extractor.startswith("human:"):
        return
    confidence = node.get("confidence")
    if isinstance(confidence, int | float) and float(confidence) >= threshold:
        return
    node["confidence"] = float(threshold)


def _broadcast(fields: tuple[str, ...], rule_id: str, message: str) -> list[IdentityHold]:
    return [IdentityHold(rule_id=rule_id, field_path=path, message=message) for path in fields]


def _section_records(
    document: ScheduleK1,
    roster: Roster | None,
    threshold: float,
) -> list[tuple[tuple[str, ...], PartnershipRecord | InvestorRecord | None]]:
    if roster is None:
        return []
    pairs: list[tuple[tuple[str, ...], PartnershipRecord | InvestorRecord | None]] = []
    ein = get_extracted(document, "part_i.ein")
    if id_read_is_confident(ein, threshold=threshold) and isinstance(ein.value, str):
        partnership, partnership_dup = _find_record(
            roster.partnerships, lambda item: item.ein, ein.value
        )
        pairs.append((_PARTNERSHIP_FIELDS, None if partnership_dup else partnership))
    tin = get_extracted(document, "part_ii.tin")
    if id_read_is_confident(tin, threshold=threshold) and isinstance(tin.value, str):
        investor, investor_dup = _find_record(roster.investors, lambda item: item.tin, tin.value)
        pairs.append((_INVESTOR_FIELDS, None if investor_dup else investor))
    return pairs


def _is_masked(text: str) -> bool:
    if any(char in text for char in "*Xx"):
        return True
    if re.fullmatch(r"\d{4}", text):
        return True
    digits = re.sub(r"\D", "", text)
    return len(digits) == 4 and _EIN.fullmatch(text) is None and _SSN.fullmatch(text) is None


def _records(payload: dict[str, object], key: str, path: Path) -> list[object]:
    raw = payload.get(key, [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"Roster {path} field {key} must be a list.")
    return raw


def _partnership(item: object) -> PartnershipRecord:
    data = _object(item)
    return PartnershipRecord(
        name=_text(data, "name"),
        ein=_text(data, "ein"),
        street=_text(data, "street"),
        city=_text(data, "city"),
        state=_text(data, "state"),
        zip_code=_text(data, "zip"),
    )


def _investor(item: object) -> InvestorRecord:
    data = _object(item)
    return InvestorRecord(
        name=_text(data, "name"),
        tin=_text(data, "tin"),
        street=_text(data, "street"),
        city=_text(data, "city"),
        state=_text(data, "state"),
        zip_code=_text(data, "zip"),
    )


def _object(item: object) -> dict[str, object]:
    if not isinstance(item, dict):
        raise ValueError("Each roster record must be an object.")
    return item


def _copied(document: ScheduleK1, path: str) -> str:
    value = get_extracted(document, path).value
    if isinstance(value, str):
        return value
    return ""


def _copied_id(document: ScheduleK1, path: str) -> str:
    return " ".join(_copied(document, path).split())


def _text(data: dict[str, object], key: str) -> str:
    value = data.get(key, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"Roster field {key} must be a string.")
    return value


def _node(data: dict[str, object], path: str) -> object:
    node: object = data
    for part in path.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
    return node

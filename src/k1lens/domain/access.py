"""Read and update fields on a Schedule K-1 by dotted path."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any, cast

from k1lens.domain.fields import (
    CODED_BOXES,
    SCALAR_BY_PATH,
    CodedBoxSpec,
    FieldKind,
    FieldSpec,
)
from k1lens.domain.models import CodedAmount, Extracted, Provenance, ScheduleK1
from k1lens.domain.parsing import parse_bool, parse_decimal

_CODED_PATH = re.compile(
    r"^(?P<base>[a-z0-9_.]+)\[(?P<code>[A-Za-z]{1,2})\](?:#(?P<index>[1-9]\d*))?$"
)


class UnknownFieldError(KeyError):
    """The path is not a scalar field or a coded line on this document."""


def get_extracted(doc: ScheduleK1, path: str) -> Extracted[Any]:
    current: Any = doc
    for part in path.split("."):
        if not hasattr(current, part):
            raise UnknownFieldError(path)
        current = getattr(current, part)
    return cast(Extracted[Any], current)


def get_coded(doc: ScheduleK1, path: str) -> list[CodedAmount]:
    current: Any = doc
    for part in path.split("."):
        current = getattr(current, part)
    return cast(list[CodedAmount], current)


def coded_amounts(doc: ScheduleK1, path: str) -> list[tuple[str, Decimal | None]]:
    """Every coded line, including two amounts that share a code."""

    return [(item.code, item.amount.value) for item in get_coded(doc, path)]


def spec_for_scalar(path: str) -> FieldSpec:
    try:
        return SCALAR_BY_PATH[path]
    except KeyError as exc:
        raise UnknownFieldError(path) from exc


def parse_coded_path(path: str) -> tuple[str, str, int] | None:
    match = _CODED_PATH.fullmatch(path)
    if match is None:
        return None
    index = match.group("index")
    return match.group("base"), match.group("code").upper(), int(index or "1")


def kind_for_path(path: str) -> FieldKind:
    if path == "tax_year":
        return FieldKind.INT
    if path == "ocr_failed_pages":
        return FieldKind.STRING
    coded = parse_coded_path(path)
    if coded is not None:
        base, _code, _index = coded
        if base not in {spec.path for spec in CODED_BOXES}:
            raise UnknownFieldError(path)
        return FieldKind.MONEY
    return spec_for_scalar(path).kind


def parse_review_value(kind: FieldKind, raw: str) -> object:
    """Turn a reviewer keystroke into a JSON-ready value. Blank clears the field."""

    text = raw.strip()
    if text == "":
        return None
    if kind in (FieldKind.MONEY, FieldKind.PERCENT):
        return str(parse_decimal(text))
    if kind is FieldKind.BOOL:
        return parse_bool(text)
    if kind is FieldKind.INT:
        return int(text)
    return text


def _navigate(data: dict[str, Any], path: str) -> dict[str, Any]:
    coded = parse_coded_path(path)
    if coded is not None:
        base, code, index = coded
        node: Any = data
        for part in base.split("."):
            node = node[part]
        if not isinstance(node, list):
            raise UnknownFieldError(path)
        matches = [item for item in node if str(item["code"]).upper() == code]
        if index < 1 or index > len(matches):
            raise UnknownFieldError(path)
        amount = matches[index - 1]["amount"]
        if not isinstance(amount, dict):
            raise UnknownFieldError(path)
        return cast(dict[str, Any], amount)
    node = data
    parts = path.split(".")
    for part in parts[:-1]:
        child = node[part]
        if not isinstance(child, dict):
            raise UnknownFieldError(path)
        node = child
    leaf = node[parts[-1]]
    if not isinstance(leaf, dict):
        raise UnknownFieldError(path)
    return leaf


def apply_correction(doc: ScheduleK1, path: str, parsed: object, actor: str) -> ScheduleK1:
    """Return a copy with one field set by a reviewer.

    The new confidence is 1 when a value was entered and 0 when it was cleared.
    Provenance keeps the original page and records the reviewer as the extractor.
    """

    if path == "ocr_failed_pages":
        raise ValueError("An OCR page failure is overridden, not edited")
    if path == "tax_year":
        if parsed is not None and not isinstance(parsed, int):
            raise ValueError("Tax year must be a whole number")
        return doc.model_copy(
            update={
                "tax_year": parsed,
                "tax_year_confidence": 1.0 if parsed is not None else 0.0,
                "tax_year_extractor": f"human:{actor}",
            }
        )
    kind_for_path(path)
    data = doc.model_dump(mode="json")
    target = _navigate(data, path)
    provenance = target.get("provenance")
    page = provenance.get("page") if isinstance(provenance, dict) else None
    bbox = provenance.get("bbox") if isinstance(provenance, dict) else None
    target["value"] = parsed
    target["confidence"] = 1.0 if parsed is not None else 0.0
    target["provenance"] = {
        "page": page,
        "bbox": bbox,
        "field_name": path,
        "extractor": f"human:{actor}",
    }
    return ScheduleK1.model_validate(data)


def empty_provenance(field_name: str, extractor: str | None = None) -> Provenance:
    return Provenance(field_name=field_name, extractor=extractor)


def coded_box(path: str) -> CodedBoxSpec:
    try:
        return next(spec for spec in CODED_BOXES if spec.path == path)
    except StopIteration as exc:
        raise UnknownFieldError(path) from exc

"""Parse the short strings printed on a K-1 facsimile."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from k1lens.domain.fields import FieldKind

_TRUE = {"yes", "true", "y", "1"}
_FALSE = {"no", "false", "n", "0"}
_NON_FINITE = {"nan", "inf", "infinity", "+inf", "-inf", "+infinity", "-infinity"}
_FOOTNOTE_TOKEN = re.compile(r"^(?:\*+|†+|‡+|#|§|\(\d{1,2}\))$")
_TRAILING_MARK = re.compile(r"(?:\*+|†+|‡+|#|§)+$")
_ATTACHED_NOTE = re.compile(r"^(?P<body>.+?)\(\d{1,2}\)$")
_SCIENTIFIC = re.compile(r"[eE]")
# USPS Publication 28 two-letter abbreviations: states, DC, territories, and
# military mail. A K-1 state box is one of these, not a mixed-case fragment.
USPS_STATES = frozenset(
    {
        "AA",
        "AE",
        "AK",
        "AL",
        "AP",
        "AR",
        "AS",
        "AZ",
        "CA",
        "CO",
        "CT",
        "DC",
        "DE",
        "FL",
        "GA",
        "GU",
        "HI",
        "IA",
        "ID",
        "IL",
        "IN",
        "KS",
        "KY",
        "LA",
        "MA",
        "MD",
        "ME",
        "MI",
        "MN",
        "MO",
        "MP",
        "MS",
        "MT",
        "NC",
        "ND",
        "NE",
        "NH",
        "NJ",
        "NM",
        "NV",
        "NY",
        "OH",
        "OK",
        "OR",
        "PA",
        "PR",
        "RI",
        "SC",
        "SD",
        "TN",
        "TX",
        "UT",
        "VA",
        "VI",
        "VT",
        "WA",
        "WI",
        "WV",
        "WY",
    }
)
STATE_PATHS = frozenset({"part_i.state", "part_ii.state"})
# IRS Form 1065 instructions, "Where To File": Ogden, UT and Kansas City, MO.
# Older editions of those instructions also named these service centers.
OFFICIAL_IRS_CENTERS = frozenset(
    {
        "ogden",
        "ogden, ut",
        "kansas city",
        "kansas city, mo",
        "cincinnati",
        "cincinnati, oh",
        "austin",
        "austin, tx",
        "fresno",
        "fresno, ca",
        "atlanta",
        "atlanta, ga",
        "andover",
        "andover, ma",
        "philadelphia",
        "philadelphia, pa",
        "holtsville",
        "holtsville, ny",
        "memphis",
        "memphis, tn",
    }
)
_THOUSANDS = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
_NON_GROUPING_COMMA = re.compile(r"(?<!\d),|,(?!\d)")
# A dot and exactly three digits is ambiguous: US cents use two digits, and
# ``1.234`` is also how some countries print 1234. One or two digits, or a
# comma-grouped US amount, stay.
_AMBIGUOUS_DOT = re.compile(r"\d{1,3}\.\d{3}")
# A word of only leader marks. Dots, underscores, hyphens, equals signs,
# tildes, asterisks, and colons are the rules printed between a caption and
# a value. Any run of three or more of the same non-alphanumeric character
# is a leader too, so ``+++`` and ``###`` are not part of the value.
# ``Wilkes-Barre`` is not one of these: it contains letters. The hyphen sits
# at the end of the class so it is not a range.
_LEADER_CHARS = r".\u00b7\u2022\u2024\u2026_=~*:-"
_LEADER_WORD = re.compile(rf"^[{_LEADER_CHARS}]+$")
_SAME_LEADER = re.compile(r"^([^\w\s])\1{2,}$")
# ``..........Boulder`` and ``+++Boulder`` are one token. A repeated leader
# prefix is not part of the city. A hyphen inside a name stays.
_GLUED_LEADER = re.compile(rf"^[{_LEADER_CHARS}]{{2,}}")
_GLUED_SAME = re.compile(r"^([^\w\s])\1{2,}")
# The whole first word of a cross-reference. ``See cover letter`` is not a
# name. ``Per Holmberg``, ``Perry``, ``Attached Dwelling``, ``Seeley``, and
# ``Per-Anders`` are names: the word has to be exactly see, refer, or enclosed.
_CROSS_REFERENCE = frozenset({"see", "refer", "enclosed"})
# A value slot that prints a note instead of a value. The whole string has
# to match, so ``Nonsense Partners`` is still a name.
_NOTE_PHRASES = frozenset({"not applicable", "not provided", "unknown", "n/a", "none"})
_TRAILING_NOTE = re.compile(
    r"(?:,?\s+)?(?:see\s+instructions|see\s+statement|see\s+page(?:\s+\d+)?|page\s+\d+)\.?\s*$",
    re.IGNORECASE,
)
_CHECKBOX = re.compile(r"^[Xx]\s+(.+)$")
# Canonical item L strings. The form does not print a menu of options for
# item I1 or for item L. A value clears only when it matches one of these.
_CAPITAL_METHODS = {
    "tax basis": "Tax basis",
    "gaap": "GAAP",
    "section 704(b)": "Section 704(b)",
    "section 704(b) book": "Section 704(b)",
    "other": "Other",
}
# Canonical item I1 strings. The form does not print these as options.
_ENTITY_TYPES = {
    "individual": "Individual",
    "partnership": "Partnership",
    "corporation": "Corporation",
    "s corporation": "S corporation",
    "llc": "LLC",
    "trust": "Trust",
    "estate": "Estate",
    "exempt org": "Exempt organization",
    "exempt organization": "Exempt organization",
}


def irs_center_ok(value: str) -> bool:
    """True when ``value`` is a service center the Form 1065 instructions name."""

    token = " ".join(value.lower().replace(".", "").split())
    return token in OFFICIAL_IRS_CENTERS


def _require_thousands_commas(text: str, raw: str) -> None:
    """Commas are thousands separators only. ``12,34`` is not ``1234``."""

    body = text.replace("$", "")
    if body.startswith("(") and body.endswith(")"):
        body = body[1:-1]
    if body.endswith("-"):
        body = body[:-1]
    if body.startswith("+"):
        body = body[1:]
    if "," not in body:
        return
    if _THOUSANDS.fullmatch(body) is None:
        raise ValueError(f"not a thousands group: {raw}")


def parse_decimal(raw: str) -> Decimal:
    """Parse one money or percent token.

    Accepts a dollar sign, thousands separators, a trailing minus, parentheses
    for negatives, and a footnote marker such as ``*`` or ``(1)``. Two amounts
    in one string are rejected. ``NaN`` and infinities are rejected.
    """

    text = raw.strip()
    if text == "":
        raise ValueError("empty number")
    parts = text.split()
    if len(parts) > 2:
        raise ValueError(f"multiple amounts: {raw}")
    if len(parts) == 2:
        if _FOOTNOTE_TOKEN.fullmatch(parts[1]) is None:
            raise ValueError(f"multiple amounts: {raw}")
        text = parts[0]
    text = _TRAILING_MARK.sub("", text)
    attached = _ATTACHED_NOTE.fullmatch(text)
    if attached is not None and not text.startswith("("):
        text = attached.group("body")
    if _SCIENTIFIC.search(text):
        raise ValueError(f"scientific notation: {raw}")
    # ``1,234.56`` is a US amount. ``12.345,67`` uses a comma as the decimal
    # mark. Stripping commas would turn that into 12.34567.
    # A comma that is not between digits is punctuation, such as OCR
    # ``:,17761.00``. A comma between digits still has to be a thousands group.
    text = _NON_GROUPING_COMMA.sub("", text)
    if "." in text and "," in text and text.rfind(",") > text.rfind("."):
        raise ValueError(f"not a US number: {raw}")
    _require_thousands_commas(text, raw)
    if "," not in text and _AMBIGUOUS_DOT.fullmatch(text.replace("$", "")):
        raise ValueError(f"ambiguous decimal: {raw}")
    text = text.replace("$", "").replace(",", "")
    if text == "" or any(char.isspace() for char in text):
        raise ValueError(f"multiple amounts: {raw}")
    if text.lower() in _NON_FINITE:
        raise ValueError(f"not a finite number: {raw}")
    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    if text.endswith("-"):
        negative = True
        text = text[:-1]
    if text.startswith("+"):
        text = text[1:]
    try:
        value = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"not a number: {raw}") from exc
    if not value.is_finite():
        raise ValueError(f"not a finite number: {raw}")
    if negative:
        value = -abs(value)
    return value


def parse_bool(raw: str) -> bool:
    token = raw.strip().lower().rstrip(".")
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    raise ValueError(f"not a yes/no value: {raw}")


def parse_kind(kind: FieldKind, raw: str) -> object:
    text = raw.strip()
    if text == "":
        raise ValueError("empty value")
    if kind in (FieldKind.MONEY, FieldKind.PERCENT):
        return parse_decimal(text)
    if kind is FieldKind.BOOL:
        return parse_bool(text)
    if kind is FieldKind.INT:
        return int(text)
    return text


def clean_printed_value(raw: str) -> str:
    """Drop leader marks and a trailing instruction reference.

    ``........................ SAMPLE Alder Fund LP``, ``~~~~ Name``, and
    ``..........Boulder`` are the value without the leaders. ``See
    instructions`` at the end of a public caption is not part of the value.
    A period in ``L.P.`` or ``Jr.`` stays. A comma or a semicolon at the
    edge is separator punctuation and is dropped.
    """

    words: list[str] = []
    for word in raw.split():
        if is_leader_token(word):
            continue
        stripped = _GLUED_SAME.sub("", _GLUED_LEADER.sub("", word))
        if stripped:
            words.append(stripped)
    text = _strip_separators(" ".join(words))
    previous = None
    while text and text != previous:
        previous = text
        text = _strip_separators(_TRAILING_NOTE.sub("", text))
    return text


def is_leader_token(text: str) -> bool:
    """True for a token that is only leader marks.

    A mixed run of the printed leader characters counts, and so does any
    run of three or more copies of one other non-alphanumeric character.
    """

    token = text.strip()
    if token == "":
        return False
    return _LEADER_WORD.fullmatch(token) is not None or _SAME_LEADER.fullmatch(token) is not None


def _strip_separators(text: str) -> str:
    """Drop edge spaces, commas, and semicolons. Keep abbreviation periods."""

    return text.strip(" ,;")


def begins_with_cross_reference(value: str) -> bool:
    """True when the value is a note such as ``See cover letter``.

    The first word is compared with its punctuation removed, so ``(See``
    counts. The whole word has to be ``see``, ``refer``, or ``enclosed``.
    ``Perry``, ``Per Holmberg``, ``Seeley Lake``, ``Attached Dwelling``,
    and ``Per-Anders`` do not match.
    """

    words = value.split()
    if not words:
        return False
    first = re.sub(r"[^a-z0-9]", "", words[0].lower())
    return first in _CROSS_REFERENCE


def is_note_phrase(value: str) -> bool:
    """True when the whole value is a note, not a name or a city.

    ``Not applicable``, ``Not provided``, ``Unknown``, ``N/A``, and ``None``
    are not values. ``Nonsense Partners`` is a name and does not match.
    """

    token = " ".join(value.split()).lower().strip(" .")
    return token in _NOTE_PHRASES


def _entity_key(value: str) -> str:
    """Lowercase entity text with periods removed, so ``L.L.C.`` matches ``LLC``."""

    return " ".join(value.replace(".", "").split()).lower()


def canonicalize_capital_method(raw: str) -> str:
    """Match a printed item L method to a canonical string.

    ``other`` and ``Other`` are the same box. A leading checkbox ``X`` is
    the mark on the form, not part of the method. A separator period after
    the method is not part of it. Anything else is left as read.
    """

    token = " ".join(raw.split()).rstrip(".")
    hit = _CAPITAL_METHODS.get(token.lower())
    if hit is not None:
        return hit
    marked = _CHECKBOX.fullmatch(token)
    if marked is not None:
        hit = _CAPITAL_METHODS.get(marked.group(1).strip().rstrip(".").lower())
        if hit is not None:
            return hit
    return raw


def canonicalize_entity_type(raw: str) -> str:
    """Match item I1 to a canonical entity string.

    Periods are ignored, so ``L.L.C.`` is ``LLC``. Anything outside that
    set is left as read so the shape check can hold it.
    """

    token = " ".join(raw.split())
    return _ENTITY_TYPES.get(_entity_key(token), token)


def entity_type_ok(value: str) -> bool:
    """True when ``value`` is a canonical entity string, and nothing else."""

    return _entity_key(value) in _ENTITY_TYPES


def capital_method_ok(value: str) -> bool:
    """True when ``value`` is a canonical item L method, or a checked one."""

    token = " ".join(value.split()).rstrip(".")
    if token.lower() in _CAPITAL_METHODS:
        return True
    marked = _CHECKBOX.fullmatch(token)
    return marked is not None and marked.group(1).strip().rstrip(".").lower() in _CAPITAL_METHODS


def canonicalize_state(raw: str) -> str:
    """Uppercase a USPS abbreviation. Leave anything else unchanged."""

    token = raw.strip()
    upper = token.upper()
    if len(upper) == 2 and upper in USPS_STATES:
        return upper
    return token


def format_decimal(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01')):.2f}"


def format_bool(value: bool) -> str:
    return "Yes" if value else "No"


def is_ein_text(value: str) -> bool:
    parts = value.split("-")
    return (
        len(parts) == 2
        and len(parts[0]) == 2
        and len(parts[1]) == 7
        and parts[0].isdigit()
        and parts[1].isdigit()
    )


def is_ssn_text(value: str) -> bool:
    parts = value.split("-")
    return (
        len(parts) == 3
        and len(parts[0]) == 3
        and len(parts[1]) == 2
        and len(parts[2]) == 4
        and all(part.isdigit() for part in parts)
    )


def format_value(kind: FieldKind, value: object) -> str:
    if value is None:
        return ""
    if kind in (FieldKind.MONEY, FieldKind.PERCENT):
        return format_decimal(Decimal(str(value)))
    if kind is FieldKind.BOOL:
        return format_bool(bool(value))
    return str(value)


def values_equal(kind: FieldKind, gold: object, pred: object, tolerance: Decimal) -> bool:
    if gold is None and pred is None:
        return True
    if gold is None or pred is None:
        return False
    if kind in (FieldKind.MONEY, FieldKind.PERCENT):
        return abs(Decimal(str(gold)) - Decimal(str(pred))) <= tolerance
    if kind is FieldKind.BOOL:
        return bool(gold) is bool(pred)
    if kind is FieldKind.INT:
        return int(str(gold)) == int(str(pred))
    return str(gold).strip() == str(pred).strip()

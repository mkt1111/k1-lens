"""Map a printed line onto a Schedule K-1 field.

The targets are the public Form 1065 Schedule K-1 box numbers, line names,
and codes, plus the words the instructions use for those lines. Matching
normalizes case and punctuation, then expands only abbreviations that the
IRS prints on Schedule K-1 (Form 1065) or that are general accounting
shortenings of those line words. A line is kept only when one field beats
the runner-up. An ambiguous line is refused. Caption strings from the
development fixtures are not listed here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from k1lens.domain.fields import (
    CODED_BOXES,
    LABEL_DOCUMENT_ID,
    LABEL_TAX_YEAR,
    LABEL_VARIANT,
    SCALAR_BY_LABEL,
    SCALAR_BY_PATH,
    SCALAR_FIELDS,
)
from k1lens.extract.text import Observed

STRONG_LABEL = 0.85
MIN_STRONG_ANCHORS = 4
MIN_STRONG_RATIO = 0.5
_BOXED_MIN = 0.45
_UNBOXED_MIN = 0.85
_MARGIN = 0.12
_CONTRADICTION = 0.85
_ACCEPT_SCORE = 0.90

_HEADERS = {LABEL_TAX_YEAR, LABEL_DOCUMENT_ID, LABEL_VARIANT}
_CODED_BOXES = {spec.box for spec in CODED_BOXES}
_CODED_PREFIX = {spec.box: spec.pdf_prefix for spec in CODED_BOXES}
_FILLERS = frozenset(
    {
        "a",
        "an",
        "and",
        "box",
        "check",
        "checkbox",
        "did",
        "flag",
        "for",
        "from",
        "if",
        "in",
        "is",
        "item",
        "line",
        "ln",
        "loss",
        "of",
        "or",
        "per",
        "the",
        "this",
        "with",
    }
)
# Whole-token abbreviations. ``inc`` is income, not the corporate suffix.
# Values stay on the other side of the colon and are not run through this table.
#
# irs-k1-1065: the Partner's Instructions for Schedule K-1 (Form 1065) print
# the abbreviation in parentheses, or the form prints it in the line title
# (EIN, SSN, TIN, PTP, and "Alternative minimum tax (AMT) items").
# general-accounting: a standard workpaper shortening of a word the form
# spells out (account, beginning, capital, deduction, distributions,
# dividend, ending, income, long-term, ordinary, payment, percent,
# qualified, schedule, section, short-term, year).
# Tokens that existed to match one development caption, including begin,
# distr, distrib, divs, empl, equiv, guar, pmts, and yrs, are not keys.
_ABBREV = {
    "amt": "alternative minimum tax",
    "ein": "employer identification number",
    "ptp": "publicly traded partnership",
    "ssn": "social security number",
    "tin": "taxpayer identification number",
    "acct": "account",
    "beg": "beginning",
    "cap": "capital",
    "ded": "deduction",
    "dist": "distributions",
    "div": "dividend",
    "end": "ending",
    "inc": "income",
    "lt": "long term",
    "ord": "ordinary",
    "pct": "percent",
    "pmt": "payment",
    "qual": "qualified",
    "sch": "schedule",
    "sec": "section",
    "st": "short term",
    "yr": "year",
}

ABBREV_SOURCE: dict[str, str] = {
    "amt": "irs-k1-1065",
    "ein": "irs-k1-1065",
    "ptp": "irs-k1-1065",
    "ssn": "irs-k1-1065",
    "tin": "irs-k1-1065",
    "acct": "general-accounting",
    "beg": "general-accounting",
    "cap": "general-accounting",
    "ded": "general-accounting",
    "dist": "general-accounting",
    "div": "general-accounting",
    "end": "general-accounting",
    "inc": "general-accounting",
    "lt": "general-accounting",
    "ord": "general-accounting",
    "pct": "general-accounting",
    "pmt": "general-accounting",
    "qual": "general-accounting",
    "sch": "general-accounting",
    "sec": "general-accounting",
    "st": "general-accounting",
    "yr": "general-accounting",
}

# Public line titles from Schedule K-1 (Form 1065) and the common
# wording on that form face. Several boxes hold more than one fact
# (address, sharing percentages, liabilities, capital). Those use the
# instruction's words for each fact. Coded boxes still need a letter.
# Caption strings from the development fixtures are not listed here.
_PHRASES: dict[str, tuple[str, ...]] = {
    "part_i.ein": (
        "partnership employer identification number",
        "partnership's employer identification number",
    ),
    "part_i.name": ("partnership name",),
    "part_i.street": ("partnership street address",),
    "part_i.city": ("partnership city",),
    "part_i.state": ("partnership state",),
    "part_i.zip_code": ("partnership zip code",),
    "part_i.irs_center": ("irs center where partnership filed return", "irs center"),
    "part_i.is_ptp": (
        "publicly traded partnership",
        "check if this is a publicly traded partnership",
    ),
    "part_ii.tin": (
        "partner taxpayer identification number",
        "partner social security number",
        "partner's ssn or tin",
        "partner's identifying number",
    ),
    "part_ii.name": ("partner name",),
    "part_ii.street": ("partner street address",),
    "part_ii.city": ("partner city",),
    "part_ii.state": ("partner state",),
    "part_ii.zip_code": ("partner zip code",),
    "part_ii.is_general_partner": ("general partner", "llc member manager"),
    "part_ii.is_domestic": ("domestic partner", "foreign partner"),
    "part_ii.entity_type": (
        "type of entity",
        "entity type",
        "what type of entity is this partner",
    ),
    "part_ii.is_retirement_plan": (
        "retirement plan",
        "if this partner is a retirement plan",
    ),
    "part_ii.profit_beginning": ("profit beginning",),
    "part_ii.profit_ending": ("profit ending",),
    "part_ii.loss_beginning": ("loss beginning",),
    "part_ii.loss_ending": ("loss ending",),
    "part_ii.capital_share_beginning": ("capital share beginning", "capital beginning"),
    "part_ii.capital_share_ending": ("capital share ending", "capital ending"),
    "part_ii.liability_nonrecourse": ("nonrecourse",),
    "part_ii.liability_qualified_nonrecourse": ("qualified nonrecourse financing",),
    "part_ii.liability_recourse": ("recourse",),
    "part_ii.capital_method": ("capital method", "method of capital accounting"),
    "part_ii.capital.beginning": ("beginning capital account",),
    "part_ii.capital.contributed": ("capital contributed during the year",),
    "part_ii.capital.current_year_net_income": ("current year net income",),
    "part_ii.capital.other_increase_decrease": ("other increase decrease",),
    "part_ii.capital.withdrawals": ("withdrawals and distributions",),
    "part_ii.capital.ending": ("ending capital account",),
    "part_ii.contributed_builtin_gain": (
        "built-in gain",
        "contributed property with a built-in gain",
    ),
    "part_iii.ordinary_business_income": ("ordinary business income",),
    "part_iii.net_rental_real_estate": ("net rental real estate income",),
    "part_iii.other_net_rental": ("other net rental income",),
    "part_iii.guaranteed_payments_services": ("guaranteed payments services",),
    "part_iii.guaranteed_payments_capital": ("guaranteed payments capital",),
    "part_iii.guaranteed_payments_total": ("total guaranteed payments",),
    "part_iii.interest_income": ("interest income",),
    "part_iii.ordinary_dividends": ("ordinary dividends",),
    "part_iii.qualified_dividends": ("qualified dividends",),
    "part_iii.dividend_equivalents": ("dividend equivalents",),
    "part_iii.royalties": ("royalties",),
    "part_iii.net_short_term_capital_gain": ("net short-term capital gain",),
    "part_iii.net_long_term_capital_gain": ("net long-term capital gain",),
    "part_iii.collectibles_gain": ("collectibles 28 gain", "collectibles gain"),
    "part_iii.unrecaptured_1250_gain": ("unrecaptured section 1250 gain",),
    "part_iii.net_section_1231_gain": ("net section 1231 gain",),
    "part_iii.section_179_deduction": ("section 179 deduction",),
    "part_iii.schedule_k3_attached": ("schedule k-3 attached",),
    "part_iii.foreign_taxes_paid": ("foreign taxes paid or accrued",),
    "part_iii.other_income": ("other income",),
    "part_iii.other_deductions": ("other deductions",),
    "part_iii.self_employment": ("self-employment earnings",),
    "part_iii.credits": ("credits",),
    "part_iii.amt_items": ("alternative minimum tax items",),
    "part_iii.tax_exempt_and_nondeductible": ("tax-exempt income and nondeductible expenses",),
    "part_iii.distributions": ("distributions",),
    "part_iii.other_information": ("other information",),
}

# Printed on the IRS form as one caption for several facts. Used to consume
# the caption. Not used as matcher tokens: ``zip`` on that line would
# otherwise tie the partnership ZIP to the partnership name.
_CAPTION_ONLY: dict[str, tuple[str, ...]] = {
    "part_i.name": ("partnership's name, address, city, state, and zip code",),
    "part_ii.name": (
        "name, address, city, state, and zip code for partner entered in e",
        "see instructions",
    ),
    "part_ii.tin": (
        "do not use tin of a disregarded entity see instructions",
        "see instructions",
    ),
    "part_i.ein": ("see instructions",),
    "part_ii.entity_type": ("see instructions",),
    "part_ii.capital_method": ("see instructions",),
}

_BOX_RE = re.compile(
    r"^(?:box|item|line|ln)?\s*"
    r"(?P<box>4a|4b|4c|6a|6b|6c|9a|9b|9c|h1|i1|i2|"
    r"21|20|19|18|17|16|15|14|13|12|11|10|[1-9]|[a-m])\b",
    re.IGNORECASE,
)
_CODE_RE = re.compile(r"\bcode\s+([a-z]{1,2})\b", re.IGNORECASE)
_CODE = re.compile(r"^[A-Z]{1,2}$")


@dataclass(frozen=True, slots=True)
class _Phrase:
    catalog: str
    box: str
    coded: bool
    tokens: frozenset[str]


@dataclass(frozen=True, slots=True)
class LayoutStats:
    """How many printed lines landed on a strong K-1 label."""

    seen_lines: int
    strong_anchors: int

    @property
    def recognized(self) -> bool:
        if self.seen_lines <= 0 or self.strong_anchors < MIN_STRONG_ANCHORS:
            return False
        return (self.strong_anchors / self.seen_lines) >= MIN_STRONG_RATIO


def field_caption_tokens(catalog_label: str) -> frozenset[str]:
    """Words of this field's public captions, including the catalog label.

    A possessive ``Partnership's`` and a trailing comma normalize the same
    way on the phrase and on the printed word. The one-letter word in
    ``entered in E`` is part of that caption. A catalog box letter is not,
    so a following code is not treated as more caption.
    """

    spec = SCALAR_BY_LABEL.get(catalog_label)
    phrases = (
        _PHRASES.get(spec.path, ()) + _CAPTION_ONLY.get(spec.path, ()) if spec is not None else ()
    )
    tokens: set[str] = set()
    for phrase in phrases:
        for word in re.findall(r"[A-Za-z0-9']+", phrase):
            token = _caption_token(word)
            # ``entered in E`` prints a one-letter word. A filler ``a`` does
            # not, or the next column's box letter would be eaten as caption.
            if len(token) == 1 and token in _FILLERS:
                continue
            if token:
                tokens.add(token)
    for word in catalog_label.split():
        token = _caption_token(word)
        # The catalog box letter is not a caption word. A following code
        # stays a code.
        if len(token) >= 2:
            tokens.add(token)
    return frozenset(tokens)


def catalog_caption_words() -> frozenset[str]:
    """Caption words long enough that a name should not contain them."""

    tokens: set[str] = set()
    groups = list(_PHRASES.values()) + list(_CAPTION_ONLY.values())
    for phrases in groups:
        for phrase in phrases:
            tokens.update(_caption_token(word) for word in re.findall(r"[A-Za-z0-9']+", phrase))
    return frozenset(token for token in tokens if len(token) >= 4)


def _caption_token(word: str) -> str:
    """Lowercase word. A possessive ``'s`` is dropped, then other punctuation.

    ``Partnership's`` and ``partnership`` are the same caption word.
    ``Partners`` is not.
    """

    lowered = word.lower()
    if lowered.endswith("'s"):
        lowered = lowered[:-2]
    return re.sub(r"[^a-z0-9]", "", lowered.replace("'", ""))


def resolve_field_label(label: str) -> tuple[str, float] | None:
    """Return ``(catalog label, score)`` or None when the line is ambiguous."""

    box, code, tokens = _split(label)
    if box in _CODED_BOXES and code is None:
        return None
    if not tokens and not _unique_box(box):
        return None
    pool = [phrase for phrase in _INDEX if box is None or phrase.box == box]
    if not pool:
        return None
    best_key, best, second = _best(tokens, pool, distinctive=box is not None)
    if best_key is None:
        return None
    if box is not None and _contradicts(box, tokens, best_key):
        return None
    phrase = next(item for item in pool if item.catalog == best_key)
    catalog = _catalog_label(phrase, code)
    if catalog is None:
        return None
    if not tokens:
        return catalog, _ACCEPT_SCORE
    minimum = _BOXED_MIN if box is not None else _UNBOXED_MIN
    if best < minimum or best - second < _MARGIN:
        return None
    return catalog, max(best, _ACCEPT_SCORE)


def canonicalize_observed(
    observed: dict[str, list[Observed]],
) -> tuple[dict[str, list[Observed]], LayoutStats]:
    """Rewrite labels to the catalog.

    Two different wordings that land on the same scalar are both dropped.
    The same scalar label printed with two values is kept once and marked
    as a conflict. Coded lines with the same code and different amounts are
    all kept.
    """

    kept: dict[str, list[Observed]] = {}
    conflicts: set[str] = set()
    seen = 0
    for label, rows in observed.items():
        if label in _HEADERS:
            kept[label] = rows[:1]
            continue
        seen += len(rows)
        if not rows:
            continue
        canonical, score = _to_catalog(label)
        if canonical is None:
            continue
        conflict = len({item.raw for item in rows}) > 1
        prepared: list[Observed] = []
        for obs in rows:
            if score is not None:
                obs = replace(obs, label_score=score)
            if conflict and not _is_coded_catalog(canonical):
                obs = replace(obs, conflict=True)
            prepared.append(obs)
        if _is_coded_catalog(canonical):
            bucket = kept.setdefault(canonical, [])
            for obs in prepared:
                if any(item.raw == obs.raw for item in bucket):
                    continue
                bucket.append(obs)
            continue
        if canonical in kept:
            conflicts.add(canonical)
            continue
        kept[canonical] = [prepared[-1]]
    for key in conflicts:
        kept.pop(key, None)
    strong = sum(
        1
        for label, rows in kept.items()
        if label not in _HEADERS and rows and rows[0].label_score >= STRONG_LABEL
    )
    return kept, LayoutStats(seen_lines=seen, strong_anchors=strong)


def _to_catalog(label: str) -> tuple[str | None, float | None]:
    if label in SCALAR_BY_LABEL or _is_coded_catalog(label):
        return label, None
    return resolve_field_label(label) or (None, None)


def _is_coded_catalog(label: str) -> bool:
    for box in CODED_BOXES:
        prefix = f"{box.pdf_prefix} "
        if not label.startswith(prefix):
            continue
        code = label[len(prefix) :].strip().upper()
        return _CODE.fullmatch(code) is not None
    return False


def _split(label: str) -> tuple[str | None, str | None, frozenset[str]]:
    text = label.strip().lower().replace("&", " and ")
    code: str | None = None
    code_match = _CODE_RE.search(text)
    if code_match is not None:
        code = code_match.group(1).upper()
        text = f"{text[: code_match.start()]} {text[code_match.end() :]}"
    box: str | None = None
    box_match = _BOX_RE.match(text.strip())
    if box_match is not None:
        raw_box = box_match.group("box")
        box = raw_box.lower() if raw_box[0].isdigit() else raw_box.upper()
        text = text.strip()[box_match.end() :]
    if code is None and box in _CODED_BOXES:
        trailing = re.search(r"\s([a-z]{1,2})$", text.strip())
        if trailing is not None:
            code = trailing.group(1).upper()
            text = text.strip()[: trailing.start()]
    return box, code, _tokens(text)


def _tokens(text: str) -> frozenset[str]:
    cleaned = re.sub(r"[^a-z0-9]+", " ", text.lower())
    tokens: list[str] = []
    for token in cleaned.split():
        replacement = _ABBREV.get(token)
        if replacement is not None:
            tokens.extend(replacement.split())
            continue
        tokens.extend(_prefix(token).split())
    return frozenset(token for token in tokens if token not in _FILLERS and token in _VOCAB)


def _prefix(token: str) -> str:
    if len(token) < 4 or token in _VOCAB:
        return token
    matches = [word for word in _VOCAB if word.startswith(token)]
    if len(matches) == 1:
        return matches[0]
    return token


def _best(
    tokens: frozenset[str], pool: list[_Phrase], *, distinctive: bool
) -> tuple[str | None, float, float]:
    if not tokens:
        keys = {phrase.catalog for phrase in pool}
        if len(keys) == 1:
            return next(iter(keys)), 1.0, 0.0
        return None, 0.0, 0.0
    scores: dict[str, float] = {}
    for phrase in pool:
        scores[phrase.catalog] = max(
            scores.get(phrase.catalog, 0.0), _jaccard(tokens, phrase.tokens)
        )
    if distinctive:
        boosted = _distinctive(tokens, pool)
        if boosted is not None:
            scores[boosted] = max(scores.get(boosted, 0.0), _ACCEPT_SCORE)
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    if not ranked:
        return None, 0.0, 0.0
    best_key, best = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return best_key, best, second


def _distinctive(tokens: frozenset[str], pool: list[_Phrase]) -> str | None:
    owners: dict[str, set[str]] = {}
    for token in tokens:
        catalogs = {phrase.catalog for phrase in pool if token in phrase.tokens}
        if len(catalogs) == 1:
            owners.setdefault(next(iter(catalogs)), set()).add(token)
    if len(owners) != 1:
        return None
    return next(iter(owners))


def _contradicts(box: str, tokens: frozenset[str], inside_key: str) -> bool:
    if not tokens:
        return False
    outside = [phrase for phrase in _INDEX if phrase.box != box]
    # Compare raw overlap. A distinctive-token boost would treat a shared
    # word such as "income" or "number" as a contradiction of the box.
    _key, best, _second = _best(tokens, outside, distinctive=False)
    inside_phrases = [phrase for phrase in _INDEX if phrase.catalog == inside_key]
    inside = max((_jaccard(tokens, phrase.tokens) for phrase in inside_phrases), default=0.0)
    return best >= _CONTRADICTION and best > inside + 0.05


def _unique_box(box: str | None) -> bool:
    if box is None:
        return False
    return len({phrase.catalog for phrase in _INDEX if phrase.box == box}) == 1


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def _catalog_label(phrase: _Phrase, code: str | None) -> str | None:
    if not phrase.coded:
        spec = SCALAR_BY_PATH.get(phrase.catalog)
        if spec is None:
            return None
        return spec.pdf_label
    prefix = _CODED_PREFIX.get(phrase.box)
    if prefix is None or code is None:
        return None
    return f"{prefix} {code}"


def _init() -> tuple[tuple[_Phrase, ...], frozenset[str]]:
    boxes = {spec.path: spec.box for spec in SCALAR_FIELDS}
    boxes.update({spec.path: spec.box for spec in CODED_BOXES})
    coded_paths = {spec.path for spec in CODED_BOXES}
    seed: set[str] = set()
    for replacement in _ABBREV.values():
        seed.update(replacement.split())
    for titles in _PHRASES.values():
        for title in titles:
            cleaned = re.sub(r"[^a-z0-9]+", " ", title.lower())
            for token in cleaned.split():
                seed.update(_ABBREV.get(token, token).split())
    vocab = frozenset(word for word in seed if word not in _FILLERS)
    phrases: list[_Phrase] = []
    for path, titles in _PHRASES.items():
        for title in titles:
            cleaned = re.sub(r"[^a-z0-9]+", " ", title.lower())
            tokens: list[str] = []
            for token in cleaned.split():
                tokens.extend(_ABBREV.get(token, token).split())
            phrases.append(
                _Phrase(
                    catalog=path,
                    box=boxes[path],
                    coded=path in coded_paths,
                    tokens=frozenset(
                        token for token in tokens if token not in _FILLERS and token in vocab
                    ),
                )
            )
    return tuple(phrases), vocab


_INDEX, _VOCAB = _init()

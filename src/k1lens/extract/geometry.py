"""Pair a label and a value that share a column, without a colon.

A colon line is left to the text-layer regex. This path handles a label
followed by a right-aligned amount, a box number with an amount, two
columns on one baseline, a value on the next line in the same column, and
a table row of cells. The label is resolved with the existing catalog and
public line names. Caption strings from the development fixtures are not
added here.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from k1lens.domain.parsing import is_leader_token, parse_decimal

_Y_TOLERANCE = 3.0
# One text line below the label. Scaled by the label's own height so a
# PDF point and an OCR pixel both mean "the next line", not a fixed gap.
_NEXT_LINE_HEIGHTS = 2.4
_CODE = re.compile(r"^[A-Z]{1,2}$")
_BOX_TOKEN = re.compile(
    r"^(?:4a|4b|4c|6a|6b|6c|9a|9b|9c|h1|i1|i2|"
    r"21|20|19|18|17|16|15|14|13|12|11|10|[1-9]|[a-m])$",
    re.IGNORECASE,
)
_EIN = re.compile(r"^\d{2}-\d{7}$")
_SSN = re.compile(r"^\d{3}-\d{2}-\d{4}$")
_STATE = re.compile(r"^[A-Za-z]{2}$")
_ZIP = re.compile(r"^\d{5}(?:-\d{4})?$")
_YEAR = re.compile(r"^(?:19|20)\d{2}$")
_HEADER_CELL = frozenset({"box", "line", "description", "label", "amount", "value"})
_YES_NO = frozenset({"yes", "no", "true", "false", "y", "n"})
_PAGE_OFFSET = 10000.0
# Leader tokens are the same ones ``clean_printed_value`` drops, including
# a run of three or more of one non-alphanumeric character.
# Words past this gap, with no shared x, are the next column. A name is
# not taken from there. A value that overlaps the label still counts.
_COLUMN_GUTTER = 36.0
# A wider gap than a word space. For an identity field it starts the next
# column, so two names are not stored as one value.
_IDENTITY_GAP = 16.0
# A next-line note, a page marker, or a section heading. Not a field value.
_NOTE = re.compile(
    r"^(?:"
    r"\d{1,2}"
    r"|page\s+\d+"
    r"|see\s+statement"
    r"|see\s+instructions"
    r"|see\s+page(?:\s+\d+)?"
    r"|box\s+\w+"
    r"|part\s+(?:[ivxlcdm]+|\d+)\b.*"
    r"|summary\b.*"
    r")$",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class PlacedWord:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True, slots=True)
class PlacedPair:
    label: str
    value: str
    label_score: float
    bbox: tuple[float, float, float, float]
    gap: float
    neighbor_line: bool = False
    neighbor_column: bool = False
    value_x0: float = 0.0
    value_x1: float = 0.0
    # The next line continues this value and was not read. Review holds it.
    truncated: bool = False
    # The value sits on a caption baseline, in a caption's x slot.
    caption_slot: bool = False


def pair_words(words: Sequence[PlacedWord]) -> list[PlacedPair]:
    """Pair colon-free lines, including an amount on the next line."""

    return pair_grouped_lines(_group_lines(words))


def pair_grouped_lines(lines: Sequence[Sequence[PlacedWord]]) -> list[PlacedPair]:
    """Pair each line, then an amount directly under a label in that column.

    ``lines`` are already grouped, in reading order. A value on the next
    line counts only when its box overlaps the label's x range. A following
    label, or a line more than one row below, does not.
    """

    found: list[PlacedPair] = []
    pending: list[tuple[str, float, tuple[PlacedWord, ...]]] = []
    pending_line: Sequence[PlacedWord] = ()
    grouped = [list(line) for line in lines]
    for index, line in enumerate(grouped):
        words = [word for word in line if word.text.strip()]
        nxt = grouped[index + 1] if index + 1 < len(grouped) else []
        if not words:
            pending = []
            continue
        hanging = _hanging_labels(words)
        same = [] if hanging else pair_line(words)
        # A heading or a note on this line is not the value. The label stays
        # open so the next row can fill it ("X Tax basis" under the method).
        opened = [] if hanging or same else _labels_followed_by_a_note(words)
        if not hanging and not same and not opened:
            opened = _name_labels_blocked_by_a_caption(words)
        below = pending and _directly_below(pending_line, words)
        if below and not hanging and not same and not opened:
            # A caption, a heading, or a street in the name column is not the
            # name. The label stays open. Words in another column stay there.
            paired = _pair_below(pending, words)
            if not paired and _pending_is_name(pending) and _name_column_to_skip(pending, words):
                pending_line = words
                continue
            if not paired and _address_column_to_skip(pending, words):
                pending_line = words
                continue
            found.extend(_with_wrap(paired, words, nxt))
            pending = []
            continue
        found.extend(_with_wrap(same, words, nxt))
        if hanging:
            pending = hanging
            pending_line = words
        elif opened:
            pending = opened
            pending_line = words
        else:
            pending = []
    return found


def pair_line(words: Sequence[PlacedWord]) -> list[PlacedPair]:
    """Pair labels and values on one baseline, left to right.

    The next resolved label starts a new column. A right-aligned amount is
    not a new column: it stays with the label on its left.
    """

    ordered = [word for word in sorted(words, key=lambda item: item.x0) if word.text.strip()]
    if not ordered or any(":" in word.text for word in ordered):
        return []
    pairs: list[PlacedPair] = []
    index = 0
    while index < len(ordered):
        hit = _next_label(ordered[index:])
        if hit is None:
            break
        end, label, score = hit
        label_words = ordered[index : index + end]
        value_words: list[PlacedWord] = []
        cursor = index + end
        previous_x1 = label_words[-1].x1
        # The first value word may sit far to the right. That is a
        # right-aligned value, including a name. A second jump, into an
        # amount, is the next column. The name is not taken from there.
        jumped_from_label = False
        other_column = False
        while cursor < len(ordered):
            # The next printed label is the next column, even when its first
            # word is also a caption word of this field ("13" after
            # "13 Other deductions A"). A value may start with a box number
            # ("10 Oak Avenue"); that string is not itself a label.
            if _starts_next_column(ordered[cursor:], value_started=bool(value_words)):
                break
            word = ordered[cursor]
            gap = word.x0 - previous_x1
            previous_x1 = word.x1
            if is_leader_token(word.text):
                cursor += 1
                continue
            if not value_words and gap > _COLUMN_GUTTER:
                jumped_from_label = True
            if (
                value_words
                and gap > _COLUMN_GUTTER
                and _is_name_label(label)
                and jumped_from_label
                and _parses_money(word.text)
            ):
                other_column = True
                break
            if value_words and gap > _COLUMN_GUTTER and _is_name_label(label):
                break
            # Two identity values with a gap between them are two columns.
            # Keep the first. A street unit just past a word space stays.
            # A neighboring column, past the gutter, does not.
            keep_unit = (
                _is_street_label(label)
                and gap <= _COLUMN_GUTTER
                and _unit_run(ordered[cursor:]) > 0
            )
            if value_words and gap > _IDENTITY_GAP and _is_identity_label(label) and not keep_unit:
                break
            value_words.append(word)
            cursor += 1
        if other_column or not value_words:
            break
        value = " ".join(word.text for word in value_words).strip()
        # Another column's caption is not this name. Skip the whole tail
        # so a later word is not read as a second label on this line.
        if _name_caption_instead_of_value(label, value):
            index = cursor
            continue
        if _is_note(value) or not _acceptable_value(label_words, value, label):
            index += 1
            continue
        span = label_words + value_words
        pairs.append(
            PlacedPair(
                label=label,
                value=value,
                label_score=score,
                bbox=(
                    min(word.x0 for word in span),
                    min(word.top for word in span),
                    max(word.x1 for word in span),
                    max(word.bottom for word in span),
                ),
                gap=value_words[0].x0 - label_words[-1].x1,
                value_x0=min(word.x0 for word in value_words),
                value_x1=max(word.x1 for word in value_words),
            )
        )
        index = cursor
    return pairs


def _is_note(value: str) -> bool:
    """True for a page marker, an instruction reference, or a section heading."""

    return _NOTE.fullmatch(" ".join(value.split())) is not None


def _name_line_to_skip(value: str) -> bool:
    from k1lens.extract.confidence import name_line_to_skip

    return name_line_to_skip(" ".join(value.split()))


def _name_column_to_skip(
    pending: Sequence[tuple[str, float, tuple[PlacedWord, ...]]],
    words: Sequence[PlacedWord],
) -> bool:
    """True when the words over a name label are a caption, heading, or street."""

    picked: list[str] = []
    previous_x1: float | None = None
    for word in sorted(words, key=lambda item: item.x0):
        if previous_x1 is not None and word.x0 - previous_x1 > _COLUMN_GUTTER:
            break
        previous_x1 = word.x1
        for label, _score, label_words in pending:
            if not _is_name_label(label):
                continue
            near = abs(word.x0 - _x0(label_words)) <= _COLUMN_GUTTER
            overlap = _x_overlap(word.x0, word.x1, _x0(label_words), _x1(label_words))
            if overlap > 1.0 or near:
                picked.append(word.text)
                break
    if not picked:
        return False
    return _name_line_to_skip(" ".join(picked))


def _pending_is_name(
    pending: Sequence[tuple[str, float, tuple[PlacedWord, ...]]],
) -> bool:
    return bool(pending) and all(_is_name_label(label) for label, _score, _words in pending)


def _city_line_under_a_name(value: str) -> bool:
    from k1lens.extract.confidence import city_line_under_a_name

    return city_line_under_a_name(value)


def _is_identity_label(label: str) -> bool:
    from k1lens.domain.fields import SCALAR_BY_LABEL
    from k1lens.extract.confidence import identity_path

    spec = SCALAR_BY_LABEL.get(label)
    return spec is not None and identity_path(spec.path)


def _is_street_label(label: str) -> bool:
    from k1lens.domain.fields import SCALAR_BY_LABEL

    spec = SCALAR_BY_LABEL.get(label)
    return spec is not None and spec.path.endswith(".street")


def _is_address_label(label: str) -> bool:
    from k1lens.domain.fields import SCALAR_BY_LABEL

    spec = SCALAR_BY_LABEL.get(label)
    if spec is None:
        return False
    return spec.path.endswith((".street", ".city", ".state", ".zip_code"))


def _auxiliary_address_row(value: str) -> bool:
    from k1lens.extract.confidence import auxiliary_address_row

    return auxiliary_address_row(value)


def _address_column_to_skip(
    pending: Sequence[tuple[str, float, tuple[PlacedWord, ...]]],
    words: Sequence[PlacedWord],
) -> bool:
    """True when the line under an address label is another form's row."""

    if not any(_is_address_label(label) for label, _score, _label_words in pending):
        return False
    text = " ".join(word.text for word in sorted(words, key=lambda item: item.x0))
    return _auxiliary_address_row(text)


def _is_name_label(label: str) -> bool:
    from k1lens.domain.fields import SCALAR_BY_LABEL

    spec = SCALAR_BY_LABEL.get(label)
    return spec is not None and spec.path.endswith(".name")


def _name_caption_instead_of_value(label: str, value: str) -> bool:
    if not _is_name_label(label):
        return False
    return _name_line_to_skip(value)


def _labels_followed_by_a_note(
    words: Sequence[PlacedWord],
) -> list[tuple[str, float, tuple[PlacedWord, ...]]]:
    """Labels whose same-line text is a heading or a note, not a value."""

    ordered = [word for word in sorted(words, key=lambda item: item.x0) if word.text.strip()]
    if not ordered or any(":" in word.text for word in ordered):
        return []
    found: list[tuple[str, float, tuple[PlacedWord, ...]]] = []
    index = 0
    while index < len(ordered):
        hit = _next_label(ordered[index:])
        if hit is None:
            break
        end, label, score = hit
        label_words = tuple(ordered[index : index + end])
        value_words: list[PlacedWord] = []
        cursor = index + end
        while cursor < len(ordered):
            if _starts_next_column(ordered[cursor:], value_started=bool(value_words)):
                break
            if is_leader_token(ordered[cursor].text):
                cursor += 1
                continue
            value_words.append(ordered[cursor])
            cursor += 1
        value = " ".join(word.text for word in value_words).strip()
        if value_words and _is_note(value):
            found.append((label, score, label_words))
        if cursor <= index:
            break
        index = cursor
    return found


def _name_labels_blocked_by_a_caption(
    words: Sequence[PlacedWord],
) -> list[tuple[str, float, tuple[PlacedWord, ...]]]:
    """Name labels whose same-line text is another column's caption.

    The caption is not the name. The label stays open for the next line
    in this column.
    """

    ordered = [word for word in sorted(words, key=lambda item: item.x0) if word.text.strip()]
    if not ordered or any(":" in word.text for word in ordered):
        return []
    found: list[tuple[str, float, tuple[PlacedWord, ...]]] = []
    index = 0
    while index < len(ordered):
        hit = _next_label(ordered[index:])
        if hit is None:
            break
        end, label, score = hit
        label_words = tuple(ordered[index : index + end])
        value_words: list[PlacedWord] = []
        cursor = index + end
        while cursor < len(ordered):
            if _starts_next_column(ordered[cursor:], value_started=bool(value_words)):
                break
            if is_leader_token(ordered[cursor].text):
                cursor += 1
                continue
            value_words.append(ordered[cursor])
            cursor += 1
        value = " ".join(word.text for word in value_words).strip()
        if value_words and _name_caption_instead_of_value(label, value):
            found.append((label, score, label_words))
        if cursor <= index:
            break
        index = cursor
    return found


def _hanging_labels(
    words: Sequence[PlacedWord],
) -> list[tuple[str, float, tuple[PlacedWord, ...]]]:
    """Labels on a line that has no value yet. Empty when a value is present."""

    ordered = [word for word in sorted(words, key=lambda item: item.x0) if word.text.strip()]
    if not ordered or any(":" in word.text for word in ordered):
        return []
    found: list[tuple[str, float, tuple[PlacedWord, ...]]] = []
    index = 0
    while index < len(ordered):
        hit = _next_label(ordered[index:])
        if hit is None:
            return []
        end, label, score = hit
        nxt = index + end
        if nxt < len(ordered) and _next_label(ordered[nxt:]) is None:
            return []
        found.append((label, score, tuple(ordered[index:nxt])))
        index = nxt
    return found


def _directly_below(label_line: Sequence[PlacedWord], value_line: Sequence[PlacedWord]) -> bool:
    """True when ``value_line`` is the next row, not a later section."""

    if not label_line or not value_line:
        return False
    label_top = min(word.top for word in label_line)
    value_top = min(word.top for word in value_line)
    height = max(word.bottom for word in label_line) - label_top
    limit = max(14.0, height * _NEXT_LINE_HEIGHTS)
    return 1.0 < (value_top - label_top) <= limit


def _pair_below(
    pending: Sequence[tuple[str, float, tuple[PlacedWord, ...]]],
    words: Sequence[PlacedWord],
) -> list[PlacedPair]:
    """Assign each value word to the label whose x range it overlaps."""

    ordered = [word for word in sorted(words, key=lambda item: item.x0) if word.text.strip()]
    if not ordered or any(":" in word.text for word in ordered):
        return []
    # A line that is only labels is the next row of labels, not a value.
    # A value may start with a box number, so a label hit on the first
    # token is not enough to reject the line.
    if _hanging_labels(ordered):
        return []
    columns = sorted(pending, key=lambda item: _x0(item[2]))
    clusters = _word_clusters(ordered)
    pairs: list[PlacedPair] = []
    for index, (label, score, label_words) in enumerate(columns):
        nxt = columns[index + 1][2] if index + 1 < len(columns) else None
        value_words = _words_in_caption_column(label_words, nxt, clusters)
        if not value_words:
            continue
        value = " ".join(word.text for word in value_words).strip()
        if (
            _is_note(value)
            or _name_caption_instead_of_value(label, value)
            or not _value_fits_box(label, value)
        ):
            continue
        # A blank name stays blank when the line below is only a city.
        # A value in this caption's column is that field's own box, whether
        # it sits after the caption or on the next line. The other column
        # is not read.
        if _is_name_label(label) and _city_line_under_a_name(value):
            continue
        if _is_address_label(label) and _auxiliary_address_row(value):
            continue
        covered = list(label_words) + value_words
        gap = min(word.top for word in value_words) - max(word.bottom for word in label_words)
        pairs.append(
            PlacedPair(
                label=label,
                value=value,
                label_score=score,
                bbox=(
                    min(word.x0 for word in covered),
                    min(word.top for word in covered),
                    max(word.x1 for word in covered),
                    max(word.bottom for word in covered),
                ),
                gap=max(0.0, gap),
                value_x0=min(word.x0 for word in value_words),
                value_x1=max(word.x1 for word in value_words),
                caption_slot=_occupies_caption_slot(value_words, columns),
            )
        )
    return pairs


def _word_clusters(words: Sequence[PlacedWord]) -> list[list[PlacedWord]]:
    """Groups separated by a column gutter. One cluster is one column."""

    clusters: list[list[PlacedWord]] = []
    current: list[PlacedWord] = []
    previous_x1: float | None = None
    for word in words:
        if previous_x1 is not None and word.x0 - previous_x1 > _COLUMN_GUTTER and current:
            clusters.append(current)
            current = []
        current.append(word)
        previous_x1 = word.x1
    if current:
        clusters.append(current)
    return clusters


def _words_in_caption_column(
    label_words: Sequence[PlacedWord],
    next_label_words: Sequence[PlacedWord] | None,
    clusters: Sequence[Sequence[PlacedWord]],
) -> list[PlacedWord]:
    """Words under this caption, cut off at the next caption's left edge.

    A long caption does not reach into the next column. Each word has to
    start at or to the right of this caption and before the next caption.
    The last caption on the line stops at a gutter, so a later cluster is
    not this field.
    """

    left = _x0(label_words) - 4.0
    right = _x0(next_label_words) - 2.0 if next_label_words is not None else None
    # With no later caption, a cluster that starts past the gutter is another column.
    # Words inside the chosen cluster stay, including a name wider than its caption.
    gutter = max(_x1(label_words), _x0(label_words)) + _COLUMN_GUTTER
    for cluster in clusters:
        cx0 = min(word.x0 for word in cluster)
        if cx0 < left:
            continue
        if right is not None and cx0 >= right:
            continue
        if right is None and cx0 > gutter:
            continue
        if right is None:
            return list(cluster)
        return [word for word in cluster if word.x0 < right]
    return []


def _occupies_caption_slot(
    value_words: Sequence[PlacedWord],
    columns: Sequence[tuple[str, float, tuple[PlacedWord, ...]]],
) -> bool:
    """True when the value sits on a caption baseline, in a caption's x slot."""

    if not value_words:
        return False
    top = min(word.top for word in value_words)
    x0 = min(word.x0 for word in value_words)
    for _label, _score, label_words in columns:
        if abs(min(word.top for word in label_words) - top) > 2.0:
            continue
        if abs(_x0(label_words) - x0) <= 4.0:
            return True
    return False


def _with_wrap(
    pairs: Sequence[PlacedPair], value_line: Sequence[PlacedWord], nxt: Sequence[PlacedWord]
) -> list[PlacedPair]:
    """Hold a value whose next line continues it and was not included."""

    if not pairs or not nxt or not _directly_below(value_line, nxt):
        return list(pairs)
    if _line_starts_a_field(nxt):
        return list(pairs)
    marked: list[PlacedPair] = []
    for pair in pairs:
        continues = _line_continues_value(nxt, pair.value_x0, pair.value_x1)
        marked.append(replace(pair, truncated=True) if continues else pair)
    return marked


def _line_starts_a_field(words: Sequence[PlacedWord]) -> bool:
    ordered = [word for word in words if word.text.strip()]
    if not ordered or any(":" in word.text for word in ordered):
        return bool(ordered)
    if _hanging_labels(ordered):
        return True
    return bool(pair_line(ordered))


def _unit_run(words: Sequence[PlacedWord]) -> int:
    """Leading tokens of a street unit: a number, ``#12``, or a word plus a number."""

    if not words:
        return 0
    first = words[0].text.strip(".,")
    if first.startswith("#") or re.fullmatch(r"\d+[A-Za-z]?", first.strip("#")):
        return 1
    if len(words) >= 2 and re.fullmatch(r"[A-Za-z]{2,10}", first):
        second = words[1].text.strip(".,")
        if second.startswith("#") or re.fullmatch(r"\d+[A-Za-z]?", second.strip("#")):
            return 2
    return 0


def ends_with_unit(value: str) -> bool:
    """True when the last token is a unit or suite number."""

    tokens = value.split()
    if not tokens:
        return False
    last = tokens[-1].strip(".,")
    return last.startswith("#") or re.fullmatch(r"\d+[A-Za-z]?", last.strip("#")) is not None


def _x_overlap(left0: float, left1: float, right0: float, right1: float) -> float:
    return max(0.0, min(left1, right1) - max(left0, right0))


def _x0(words: Sequence[PlacedWord]) -> float:
    return min(word.x0 for word in words)


def _x1(words: Sequence[PlacedWord]) -> float:
    return max(word.x1 for word in words)


def pairs_from_cells(
    rows: Sequence[Sequence[object]],
) -> list[tuple[str, str, float]]:
    """Read a grid. The last cell is the amount. Earlier cells are the label."""

    found: list[tuple[str, str, float]] = []
    for row in rows:
        cells = [_cell_text(cell) for cell in row]
        cells = [cell for cell in cells if cell]
        if len(cells) < 2 or cells[0].lower() in _HEADER_CELL:
            continue
        if any(":" in cell for cell in cells):
            continue
        resolved = resolve_printed(" ".join(cells[:-1]))
        if resolved is None or cells[-1] == "":
            continue
        label, score = resolved
        if not _joined_box_value_ok(" ".join(cells[:-1]), label, cells[-1]):
            continue
        found.append((label, cells[-1], score))
    return found


def page_words(pdf_path: Path) -> list[PlacedWord]:
    """Word boxes from the text layer. Page index is folded into ``top``."""

    import pdfplumber

    words: list[PlacedWord] = []
    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception:
        return []
    with pdf:
        for page_index, page in enumerate(pdf.pages):
            shift = page_index * _PAGE_OFFSET
            for item in page.extract_words() or []:
                text = item.get("text")
                if not isinstance(text, str) or text.strip() == "":
                    continue
                words.append(
                    PlacedWord(
                        text=text,
                        x0=_float(item.get("x0")),
                        top=_float(item.get("top")) + shift,
                        x1=_float(item.get("x1")),
                        bottom=_float(item.get("bottom")) + shift,
                    )
                )
    return words


def colon_value_truncated(words: Sequence[PlacedWord], label: str) -> bool:
    """True when the line under a colon value continues that value."""

    if not words or label.strip() == "":
        return False
    lines = _group_lines(words)
    needle = " ".join(label.split()).lower()
    for index, line in enumerate(lines[:-1]):
        value_words = _words_after_label(line, needle)
        if not value_words:
            continue
        nxt = lines[index + 1]
        if not _directly_below(line, nxt) or _line_starts_a_field(nxt):
            continue
        left = min(word.x0 for word in value_words)
        right = max(word.x1 for word in value_words)
        if _line_continues_value(nxt, left, right):
            return True
    return False


def _line_continues_value(nxt: Sequence[PlacedWord], value_x0: float, value_x1: float) -> bool:
    """True when the next line continues the value instead of starting a new row.

    A heading or a footer begins to the left of the value. A wrapped second
    line starts in the value's column.
    """

    if not nxt or value_x1 <= value_x0:
        return False
    if min(word.x0 for word in nxt) < value_x0 - 4.0:
        return False
    return any(_x_overlap(word.x0, word.x1, value_x0, value_x1) > 1.0 for word in nxt)


def _words_after_label(line: Sequence[PlacedWord], needle: str) -> list[PlacedWord]:
    ordered = [word for word in sorted(line, key=lambda item: item.x0) if word.text.strip()]
    for start in range(len(ordered)):
        matched: int | None = None
        for end in range(start + 1, len(ordered) + 1):
            text = _line_text(ordered[start:end])
            if text == needle:
                matched = end
                break
            if not needle.startswith(text):
                break
        if matched is None:
            continue
        return list(ordered[matched:])
    return []


def value_in_label_region(label: str, raw: str, words: Sequence[PlacedWord]) -> bool:
    """True when ``raw`` sits in this label's column on that baseline.

    The column ends at the next label. A number printed next to a later
    label on the same line does not count. With no word boxes there is no
    region, so the value is not grounded.
    """

    needle_label = " ".join(label.split()).lower()
    if needle_label == "" or raw.strip() == "" or not words:
        return False
    for line in _group_lines(words):
        region = _region_text(line, needle_label)
        if region is not None and _value_in_text(raw, region):
            return True
    return False


def value_in_other_label_region(label: str, raw: str, words: Sequence[PlacedWord]) -> bool:
    """True when ``raw`` sits in some other field's column on the page."""

    from k1lens.domain.fields import SCALAR_FIELDS

    needle = " ".join(label.split()).lower()
    for spec in SCALAR_FIELDS:
        if spec.pdf_label.lower() == needle:
            continue
        if value_in_label_region(spec.pdf_label, raw, words):
            return True
    return False


def resolve_printed(text: str) -> tuple[str, float] | None:
    """Catalog label, coded line, or a public line name. None if ambiguous."""

    from k1lens.domain.fields import (
        CODED_BOXES,
        LABEL_DOCUMENT_ID,
        LABEL_TAX_YEAR,
        LABEL_VARIANT,
        SCALAR_BY_LABEL,
    )
    from k1lens.extract.labels import resolve_field_label

    cleaned = " ".join(text.split())
    if cleaned == "":
        return None
    headers = {
        LABEL_TAX_YEAR.lower(): LABEL_TAX_YEAR,
        LABEL_DOCUMENT_ID.lower(): LABEL_DOCUMENT_ID,
        LABEL_VARIANT.lower(): LABEL_VARIANT,
    }
    catalog = {label.lower(): label for label in SCALAR_BY_LABEL}
    catalog.update(headers)
    exact = catalog.get(cleaned.lower())
    if exact is not None:
        return exact, 1.0
    head, _sep, tail = cleaned.rpartition(" ")
    if tail and _CODE.fullmatch(tail.upper()):
        for box in CODED_BOXES:
            if head.lower() == box.pdf_prefix.lower():
                return f"{box.pdf_prefix} {tail.upper()}", 1.0
    return resolve_field_label(cleaned)


def _next_label(words: Sequence[PlacedWord]) -> tuple[int, str, float] | None:
    """A label that starts at ``words[0]``, not a value word the matcher ignored."""

    hit = _longest_label(words)
    if hit is None or not words:
        return None
    end, label, _score = hit
    printed = " ".join(word.text for word in words[:end]).lower()
    normalized = label.lower()
    if printed == normalized:
        return hit
    box = words[0].text.strip()
    if _BOX_TOKEN.fullmatch(box) and (
        normalized == box.lower() or normalized.startswith(box.lower() + " ")
    ):
        return hit
    rest = normalized.split(" ", 1)[-1]
    if printed == rest:
        return hit
    return None


def _line_text(words: Sequence[PlacedWord]) -> str:
    """Joined words, with a trailing colon treated as label punctuation."""

    parts = [word.text.rstrip(":").strip() for word in words]
    return " ".join(part for part in parts if part).lower()


def _region_text(line: Sequence[PlacedWord], needle: str) -> str | None:
    """Words after ``needle`` and before the next label on this baseline."""

    ordered = [word for word in sorted(line, key=lambda item: item.x0) if word.text.strip()]
    for start in range(len(ordered)):
        matched = start
        for end in range(start + 1, len(ordered) + 1):
            text = _line_text(ordered[start:end])
            if text == needle:
                matched = end
                break
            if not needle.startswith(text):
                break
        else:
            continue
        if _line_text(ordered[start:matched]) != needle:
            continue
        region: list[PlacedWord] = []
        cursor = matched
        while cursor < len(ordered):
            # The next label is the column boundary. The rest of the line
            # belongs to that later field.
            if _next_label(ordered[cursor:]) is not None:
                break
            region.append(ordered[cursor])
            cursor += 1
        return " ".join(word.text for word in region)
    return None


def _longest_label(words: Sequence[PlacedWord]) -> tuple[int, str, float] | None:
    """The caption through its last caption word, then the value.

    A short catalog label does not cut the caption off. ``C IRS center
    where partnership filed return`` stays one label, and ``Ogden`` is the
    value. A token that is not part of that caption stops the label, so an
    EIN or an amount is not swallowed.
    """

    best: tuple[int, str, float] | None = None
    for end in range(1, len(words) + 1):
        if any(":" in word.text for word in words[:end]):
            break
        word = words[end - 1]
        text = " ".join(item.text for item in words[:end])
        following = words[end].text if end < len(words) else None
        if best is not None and _part_of_caption(best[1], word.text, following):
            # ``13 Other deductions A`` and ``13 Other deductions B`` share
            # caption words. The second printed label ends the first.
            other = _exact_printed_label(words[end - 1 :])
            if other is not None and other[1].lower() != best[1].lower():
                break
            resolved = resolve_printed(text)
            score = best[2]
            if resolved is not None and resolved[0] == best[1]:
                score = max(score, resolved[1])
            if " ".join(text.split()).lower() == best[1].lower():
                score = 1.0
            best = (end, best[1], score)
            continue
        if best is not None:
            # ``L Capital`` is a prefix of both the method and the contributed
            # line. A longer prefix that names the other field wins.
            resolved = resolve_printed(text)
            if (
                resolved is not None
                and resolved[0] != best[1]
                and _part_of_caption(resolved[0], word.text)
            ):
                best = (end, resolved[0], resolved[1])
                continue
            break
        resolved = resolve_printed(text)
        if resolved is None:
            continue
        label, score = resolved
        best = (end, label, score)
    return best


def _exact_printed_label(words: Sequence[PlacedWord]) -> tuple[int, str] | None:
    """Longest prefix whose text is exactly the label it resolves to.

    A fuzzy hit on a bare box (``10`` inside ``10 Oak Avenue``, or ``E``
    inside ``entered in E``) does not count. The next column does, because
    ``13 Other deductions B`` is the label, not a caption leftover.
    """

    found: tuple[int, str] | None = None
    for end in range(1, len(words) + 1):
        if any(":" in word.text for word in words[:end]):
            break
        text = " ".join(item.text for item in words[:end])
        resolved = resolve_printed(text)
        if resolved is None:
            continue
        label, _score = resolved
        if " ".join(text.split()).lower() == label.lower():
            found = (end, label)
    return found


def _starts_next_column(words: Sequence[PlacedWord], *, value_started: bool) -> bool:
    exact = _exact_printed_label(words)
    if exact is not None:
        return True
    return value_started and _next_label(words) is not None


def _part_of_caption(catalog_label: str, word: str, following: str | None = None) -> bool:
    from k1lens.extract.labels import _FILLERS, _caption_token, field_caption_tokens

    token = _caption_token(word)
    if token == "":
        return False
    tokens = field_caption_tokens(catalog_label)
    following_token = _caption_token(following) if following else ""
    # ``See instructions`` closes a public caption. ``See cover letter``
    # does not: a lone ``see`` is the start of a cross-reference, and
    # dropping it would store ``cover letter`` as the name.
    if token == "see":
        return following_token in {"instructions", "instruction", "statement", "page"}
    if token in tokens or token in {"instructions", "instruction"}:
        return True
    # ``of a disregarded`` — the filler ``a`` sits inside the caption.
    if token in _FILLERS and len(token) == 1 and following is not None:
        return following_token in tokens or following_token in {"instructions", "instruction"}
    return False


def _acceptable_value(label_words: Sequence[PlacedWord], value: str, label: str) -> bool:
    printed = " ".join(word.text for word in label_words).strip()
    return _joined_box_value_ok(printed, label, value)


def _joined_box_value_ok(printed: str, label: str, value: str) -> bool:
    """A bare box token only keeps a value of that field's kind.

    ``C 824.00`` on a coded line is a letter code plus an amount. It is not
    ``C IRS center``. ``1 16098.00`` is box 1, and the amount is money.
    """

    if value == "":
        return False
    if _BOX_TOKEN.fullmatch(printed) and printed.lower() != label.lower():
        return _value_fits_box(label, value)
    return True


def _value_fits_box(label: str, value: str) -> bool:
    from k1lens.domain.fields import SCALAR_BY_LABEL, FieldKind
    from k1lens.domain.parsing import STATE_PATHS

    spec = SCALAR_BY_LABEL.get(label)
    if spec is None:
        return _looks_like_value(value)
    token = value.strip()
    if spec.path == "part_i.ein":
        return _EIN.fullmatch(token) is not None
    if spec.path == "part_ii.tin":
        return _EIN.fullmatch(token) is not None or _SSN.fullmatch(token) is not None
    if spec.path in STATE_PATHS:
        return _STATE.fullmatch(token) is not None
    if spec.path.endswith("zip_code"):
        return _ZIP.fullmatch(token) is not None
    if spec.kind == FieldKind.BOOL:
        return token.lower().rstrip(".") in _YES_NO
    if spec.kind in {FieldKind.MONEY, FieldKind.PERCENT}:
        return _parses_money(token)
    if spec.kind == FieldKind.INT:
        return _YEAR.fullmatch(token) is not None
    return not _parses_money(token)


def _continues_label(label: str, word: str) -> bool:
    parts = label.split()
    if len(parts) < 2:
        return False
    return word.lower() == parts[1].lower()


def _parses_money(token: str) -> bool:
    try:
        parse_decimal(token)
    except ValueError:
        return False
    return True


def _looks_like_value(value: str) -> bool:
    token = value.strip()
    if token.lower().rstrip(".") in _YES_NO:
        return True
    if _EIN.fullmatch(token) or _SSN.fullmatch(token) or _STATE.fullmatch(token):
        return True
    if _ZIP.fullmatch(token) or _YEAR.fullmatch(token):
        return True
    try:
        parse_decimal(token)
    except ValueError:
        return False
    return True


def _value_in_text(raw: str, rest: str) -> bool:
    needle = " ".join(raw.split()).lower()
    hay = " ".join(rest.split()).lower()
    if needle == "":
        return False
    if len(needle) <= 3:
        if re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", hay) is not None:
            return True
    elif needle in hay:
        return True
    try:
        number = parse_decimal(raw)
    except ValueError:
        return False
    for token in re.findall(r"\(?\$?-?\d[\d,]*(?:\.\d+)?\)?-?|\d+\.\d+", rest):
        try:
            if parse_decimal(token) == number:
                return True
        except ValueError:
            continue
    return False


def _group_lines(words: Sequence[PlacedWord]) -> list[list[PlacedWord]]:
    lines: list[list[PlacedWord]] = []
    for word in sorted(words, key=lambda item: (item.top, item.x0)):
        if not lines or abs(word.top - lines[-1][0].top) > _Y_TOLERANCE:
            lines.append([word])
        else:
            lines[-1].append(word)
    for line in lines:
        line.sort(key=lambda item: item.x0)
    return lines


def _cell_text(cell: object) -> str:
    if cell is None:
        return ""
    return " ".join(str(cell).split())


def _float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    return 0.0

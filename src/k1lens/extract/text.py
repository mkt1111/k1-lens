"""Read labeled lines and word boxes from a text-layer PDF."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_LINE = re.compile(r"^(?P<label>.+?):\s*(?P<value>.*)$")
_Y_TOLERANCE = 3.0


@dataclass(frozen=True, slots=True)
class PdfWord:
    text: str
    x0: float
    top: float
    x1: float
    bottom: float


@dataclass(frozen=True, slots=True)
class Observed:
    """One labeled string plus the signals used to score it.

    ``label_score`` is 1 for an exact catalog label and lower for a repaired
    OCR label. ``proximity`` is how close the value sits to that label, or
    None when the page has no word boxes. ``ocr_confidence`` is Tesseract's
    mean word confidence on a 0-1 scale. ``reported_confidence`` is an LLM
    self-report, used only when the other source signals are absent.
    """

    raw: str
    page: int | None
    bbox: tuple[float, float, float, float] | None
    extractor: str
    label_score: float = 1.0
    proximity: float | None = None
    ocr_confidence: float | None = None
    reported_confidence: float | None = None
    conflict: bool = False
    grounded: bool = True
    anchored: bool = True
    position_paired: bool = False
    # The value sits on the next line in this caption's column.
    neighbor_line: bool = False
    # The value was taken from another column. That is not this field's region.
    neighbor_column: bool = False
    # The value continues on the next line, and that line was not read.
    truncated: bool = False
    # The words sit where a caption sits: same baseline and left edge.
    caption_slot: bool = False
    # Lowest Tesseract confidence among words that contain a digit of an
    # EIN or TIN, on a 0-1 scale. None when this read did not come from OCR.
    id_digit_confidence: float | None = None


def iter_labeled_lines(text: str) -> list[tuple[str, str]]:
    """Return every ``Label: value`` line, including repeated labels."""

    found: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", raw).strip()
        match = _LINE.match(line)
        if match is None:
            continue
        found.append((match.group("label").strip(), match.group("value").strip()))
    return found


def parse_lines(text: str) -> dict[str, str]:
    """Last value for each label. Repeated labels stay available from ``iter_labeled_lines``."""

    found: dict[str, str] = {}
    for label, value in iter_labeled_lines(text):
        found[label] = value
    return found


class UnreadablePdf(Exception):
    """The file could not be opened as a PDF. The name is the cause class."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def read_observed(
    pdf_path: Path,
    *,
    extractor: str,
    blank_pages: list[int] | None = None,
) -> dict[str, list[Observed]]:
    import pdfplumber

    from k1lens.extract.geometry import (
        PlacedWord,
        colon_value_truncated,
        pair_words,
        pairs_from_cells,
    )

    found: dict[str, list[Observed]] = {}
    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception as exc:
        logger.exception("Could not open %s (%s)", pdf_path.name, type(exc).__name__)
        raise UnreadablePdf(type(exc).__name__) from exc
    with pdf:
        for index, page in enumerate(pdf.pages, start=1):
            try:
                text = page.extract_text() or ""
                words = _words(page.extract_words() or [])
            except Exception:
                logger.exception("Page read failed on %s page %s", pdf_path.name, index)
                if blank_pages is not None:
                    blank_pages.append(index)
                continue
            if not words and text.strip() == "":
                if blank_pages is not None:
                    blank_pages.append(index)
                continue
            placed = [
                PlacedWord(text=word.text, x0=word.x0, top=word.top, x1=word.x1, bottom=word.bottom)
                for word in words
            ]
            for label, raw in iter_labeled_lines(text):
                bbox, proximity = measure_label(words, label)
                # A rotated baseline splits one printed line across the 3-point
                # grouping tolerance. The string is still in the text layer, but
                # the value was not confirmed on the label's line.
                anchored = not words or bbox is not None
                found.setdefault(label, []).append(
                    Observed(
                        raw=raw,
                        page=index,
                        bbox=bbox,
                        extractor=extractor,
                        label_score=1.0,
                        proximity=0.0 if words and not anchored else proximity,
                        anchored=anchored,
                        truncated=colon_value_truncated(placed, label),
                    )
                )
            for pair in pair_words(placed):
                _add_geometry(
                    found,
                    label=pair.label,
                    raw=pair.value,
                    page=index,
                    bbox=pair.bbox,
                    extractor=extractor,
                    label_score=pair.label_score,
                    proximity=proximity_from_gap(pair.gap),
                    neighbor_line=pair.neighbor_line,
                    neighbor_column=pair.neighbor_column,
                    truncated=pair.truncated,
                    caption_slot=pair.caption_slot,
                )
            if page.lines or page.rects:
                try:
                    tables = page.extract_tables() or []
                except Exception:
                    logger.exception("Table read failed on %s page %s", pdf_path.name, index)
                    tables = []
                for table in tables:
                    for label, raw, score in pairs_from_cells(table):
                        if label in found:
                            continue
                        _add_geometry(
                            found,
                            label=label,
                            raw=raw,
                            page=index,
                            bbox=None,
                            extractor=extractor,
                            label_score=score,
                            proximity=None,
                        )
    return found


def _add_geometry(
    found: dict[str, list[Observed]],
    *,
    label: str,
    raw: str,
    page: int,
    bbox: tuple[float, float, float, float] | None,
    extractor: str,
    label_score: float,
    proximity: float | None,
    neighbor_line: bool = False,
    neighbor_column: bool = False,
    truncated: bool = False,
    caption_slot: bool = False,
) -> None:
    rows = found.setdefault(label, [])
    if any(item.raw == raw for item in rows):
        return
    rows.append(
        Observed(
            raw=raw,
            page=page,
            bbox=bbox,
            extractor=extractor,
            label_score=label_score,
            proximity=proximity,
            anchored=True,
            position_paired=True,
            neighbor_line=neighbor_line,
            neighbor_column=neighbor_column,
            truncated=truncated,
            caption_slot=caption_slot,
        )
    )


def plain_text(pdf_path: Path) -> str:
    import pdfplumber

    chunks: list[str] = []
    try:
        pdf = pdfplumber.open(str(pdf_path))
    except Exception as exc:
        logger.exception("Could not open %s", pdf_path.name)
        raise UnreadablePdf(type(exc).__name__) from exc
    with pdf:
        for page in pdf.pages:
            try:
                chunks.append(page.extract_text() or "")
            except Exception:
                logger.exception("Page text failed on %s", pdf_path.name)
                chunks.append("")
    return "\n".join(chunks).strip()


def proximity_from_gap(gap: float) -> float:
    """Map a label-to-value gap in PDF points onto 0-1.

    A short gap is a normal ``Label: value`` line. A wide gap, or an overlap,
    is a weaker signal that the value belongs to that label.
    """

    if gap < 0:
        return 0.3
    if gap <= 18:
        return 1.0
    if gap >= 120:
        return 0.15
    return 1.0 - (gap - 18) / (120 - 18) * 0.85


def measure_label(
    words: list[PdfWord], label: str
) -> tuple[tuple[float, float, float, float] | None, float | None]:
    """Return the line box and the label/value proximity, when words exist."""

    if not words:
        return None, None
    lines = _group_lines(words)
    needle = label.lower()
    for line in lines:
        text = " ".join(word.text for word in line)
        if needle not in text.lower():
            continue
        bbox = (
            min(word.x0 for word in line),
            min(word.top for word in line),
            max(word.x1 for word in line),
            max(word.bottom for word in line),
        )
        return bbox, _line_proximity(line, label)
    return None, None


def _words(raw_words: list[dict[str, object]]) -> list[PdfWord]:
    words: list[PdfWord] = []
    for item in raw_words:
        text = item.get("text")
        if not isinstance(text, str):
            continue
        words.append(
            PdfWord(
                text=text,
                x0=_float(item.get("x0")),
                top=_float(item.get("top")),
                x1=_float(item.get("x1")),
                bottom=_float(item.get("bottom")),
            )
        )
    return words


def _float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    return 0.0


def _group_lines(words: list[PdfWord]) -> list[list[PdfWord]]:
    lines: list[list[PdfWord]] = []
    for word in sorted(words, key=lambda item: (item.top, item.x0)):
        if not lines or abs(word.top - lines[-1][0].top) > _Y_TOLERANCE:
            lines.append([word])
        else:
            lines[-1].append(word)
    return lines


def _line_proximity(line: list[PdfWord], label: str) -> float | None:
    text = " ".join(word.text for word in line)
    start = text.lower().find(label.lower())
    if start < 0:
        return None
    label_end = start + len(label)
    position = 0
    label_words: list[PdfWord] = []
    value_words: list[PdfWord] = []
    for word in line:
        word_end = position + len(word.text)
        if word_end <= label_end:
            label_words.append(word)
        elif position >= label_end:
            value_words.append(word)
        else:
            label_words.append(word)
        position = word_end + 1
    if not label_words or not value_words:
        return None
    gap = value_words[0].x0 - label_words[-1].x1
    return proximity_from_gap(gap)

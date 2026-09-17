"""Shared value objects for the document intelligence pipeline."""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field

BBox = tuple[float, float, float, float]

# Text sources, most to least direct.
SOURCE_PDF_TEXT = "pdf_text"
SOURCE_OCR = "ocr"
SOURCE_NONE = "none"


def union(boxes: list[BBox]) -> BBox | None:
    if not boxes:
        return None
    return (
        min(b[0] for b in boxes),
        min(b[1] for b in boxes),
        max(b[2] for b in boxes),
        max(b[3] for b in boxes),
    )


def normalise_bbox(bbox: BBox, width: float, height: float) -> list[float]:
    """Page-relative box in 0..1, origin at the top-left corner of the page."""
    if width <= 0 or height <= 0:
        return [0.0, 0.0, 0.0, 0.0]
    return [
        round(max(0.0, min(1.0, bbox[0] / width)), 5),
        round(max(0.0, min(1.0, bbox[1] / height)), 5),
        round(max(0.0, min(1.0, bbox[2] / width)), 5),
        round(max(0.0, min(1.0, bbox[3] / height)), 5),
    ]


@dataclass(frozen=True)
class Word:
    text: str
    bbox: BBox
    confidence: float | None = None
    seqno: int = 0
    baseline: float = 0.0

    @property
    def height(self) -> float:
        return self.bbox[3] - self.bbox[1]


@dataclass(frozen=True)
class ConcealedSpan:
    """Text present in the file but painted over, so a reader never sees it."""

    text: str
    bbox: BBox
    coverage: float


@dataclass
class TextLine:
    """One visual line of text.

    `text` keeps a double space wherever the original had a wide horizontal gap, so
    extraction can tell "Patient Name: X  UHID: Y" apart from a single long value.
    """

    text: str
    words: list[Word]
    spans: list[tuple[int, int]]  # character span of each word inside `text`
    bbox: BBox

    def words_for_span(self, start: int, end: int) -> list[Word]:
        return [word for word, (s, e) in zip(self.words, self.spans) if s < end and e > start]

    def bbox_for_span(self, start: int, end: int) -> BBox | None:
        return union([word.bbox for word in self.words_for_span(start, end)])

    def confidence_for_span(self, start: int, end: int) -> float | None:
        values = [w.confidence for w in self.words_for_span(start, end) if w.confidence is not None]
        return round(sum(values) / len(values), 4) if values else None

    def cells(self) -> list["Cell"]:
        """The line split into columns on its wide gaps."""
        out: list[Cell] = []
        for match in CELL_PATTERN.finditer(self.text):
            text = match.group(0).strip()
            if not text:
                continue
            out.append(
                Cell(
                    text=text,
                    bbox=self.bbox_for_span(*match.span()),
                    start=match.start(),
                    end=match.end(),
                    line=self,
                )
            )
        return out


CELL_PATTERN = re.compile(r"\S(?:.*?\S)?(?=\s{2,}|$)")


@dataclass
class Cell:
    """One column of a line."""

    text: str
    bbox: BBox | None
    start: int
    end: int
    line: "TextLine"


def column_gap(words: list[Word]) -> float:
    """How wide a gap has to be, on this line, before it separates two columns.

    Derived from the line's own word spacing, so it works at any font size: a gap several
    times wider than the normal space between words is a column break.
    """
    gaps = [
        later.bbox[0] - earlier.bbox[2]
        for earlier, later in zip(words, words[1:])
        if later.bbox[0] - earlier.bbox[2] > 0
    ]
    if not gaps:
        return MIN_COLUMN_GAP
    median = statistics.median(gaps)
    return max(MIN_COLUMN_GAP, min(3.0 * median, MAX_COLUMN_GAP))


MIN_COLUMN_GAP = 7.0
MAX_COLUMN_GAP = 16.0


def build_lines(words: list[Word], *, tolerance: float = 2.5) -> list[TextLine]:
    """Group words into visual lines, preserving column gaps as double spaces."""
    lines: list[TextLine] = []
    for group in _group_by_baseline(words, tolerance):
        group = sorted(group, key=lambda w: w.bbox[0])
        gap = column_gap(group)
        text_parts: list[str] = []
        spans: list[tuple[int, int]] = []
        cursor = 0
        previous: Word | None = None
        for word in group:
            if previous is not None:
                separator = "  " if word.bbox[0] - previous.bbox[2] > gap else " "
                text_parts.append(separator)
                cursor += len(separator)
            spans.append((cursor, cursor + len(word.text)))
            text_parts.append(word.text)
            cursor += len(word.text)
            previous = word
        box = union([w.bbox for w in group])
        assert box is not None
        lines.append(TextLine(text="".join(text_parts), words=group, spans=spans, bbox=box))
    return lines


def _group_by_baseline(words: list[Word], tolerance: float) -> list[list[Word]]:
    groups: list[list[Word]] = []
    for word in sorted(words, key=lambda w: (w.baseline, w.bbox[0])):
        if groups and abs(word.baseline - groups[-1][0].baseline) <= tolerance:
            groups[-1].append(word)
        else:
            groups.append([word])
    return groups


@dataclass
class PageContent:
    """Everything the pipeline learned about one page."""

    number: int
    width: float
    height: float
    lines: list[TextLine] = field(default_factory=list)
    concealed: list[ConcealedSpan] = field(default_factory=list)
    text_source: str = SOURCE_NONE
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    image_path: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    effective_dpi: float | None = None
    quality: dict = field(default_factory=dict)
    quality_flags: list[dict] = field(default_factory=list)
    signature_slots: list[dict] = field(default_factory=list)

    @property
    def words(self) -> list[Word]:
        return [word for line in self.lines for word in line.words]

    @property
    def text(self) -> str:
        return "\n".join(line.text for line in self.lines)

    @property
    def flat_text(self) -> str:
        """Single-spaced text for keyword matching."""
        return re.sub(r"\s+", " ", self.text)


@dataclass
class DocumentContent:
    pages: list[PageContent] = field(default_factory=list)
    page_render_dpi: int | None = None

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)

    @property
    def flat_text(self) -> str:
        return re.sub(r"\s+", " ", self.text)

    @property
    def concealed(self) -> list[tuple[int, ConcealedSpan]]:
        return [(page.number, span) for page in self.pages for span in page.concealed]

    @property
    def text_source(self) -> str:
        sources = {page.text_source for page in self.pages if page.text_source != SOURCE_NONE}
        if not sources:
            return SOURCE_NONE
        if len(sources) == 1:
            return sources.pop()
        return "mixed"

    @property
    def ocr_engine(self) -> str | None:
        engines = [page.ocr_engine for page in self.pages if page.ocr_engine]
        return engines[0] if engines else None

    @property
    def ocr_confidence(self) -> float | None:
        values = [p.ocr_confidence for p in self.pages if p.ocr_confidence is not None]
        return round(sum(values) / len(values), 4) if values else None

    def heading_lines(self, count: int) -> list[str]:
        if not self.pages:
            return []
        return [line.text.strip() for line in self.pages[0].lines if line.text.strip()][:count]

    def heading_cells(self, count: int) -> list[str]:
        """Column texts from the top of the first page, where a document names itself."""
        if not self.pages:
            return []
        cells: list[str] = []
        for line in self.pages[0].lines[:count]:
            if not line.text.strip():
                continue
            for cell in line.cells():
                if cell.text:
                    cells.append(cell.text)
        return cells

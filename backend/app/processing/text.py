"""PDF text-layer extraction, including detection of text that is painted over.

A PDF can contain text that a reader never sees: a value is written, an opaque rectangle
is drawn on top of it, and a different value is written over that. Naive extraction
(`page.get_text()`) returns both values, so the covered one could leak into extracted
billing data. Here every character carries the sequence number of the drawing operation
that produced it, so characters that a later opaque fill covers are separated out and
kept away from extraction.
"""

from __future__ import annotations

import pymupdf

from app.processing.types import BBox, ConcealedSpan, TextLine, Word, build_lines

# A fill counts as opaque cover-up paint when every channel is near-white and it is not
# see-through. Concealment needs at least this much of a character covered.
WHITE_LEVEL = 0.97
OPACITY_LEVEL = 0.99
COVER_FRACTION = 0.6


def opaque_light_fills(page: pymupdf.Page) -> list[tuple[int, pymupdf.Rect]]:
    """Filled rectangles in near-white paint, with the sequence number that drew them."""
    fills: list[tuple[int, pymupdf.Rect]] = []
    for drawing in page.get_drawings():
        fill = drawing.get("fill")
        if not fill or min(fill) < WHITE_LEVEL:
            continue
        opacity = drawing.get("fill_opacity")
        if opacity is not None and opacity < OPACITY_LEVEL:
            continue
        rect = pymupdf.Rect(drawing["rect"])
        if rect.is_empty or rect.is_infinite:
            continue
        fills.append((int(drawing.get("seqno", 0)), rect))
    return fills


def _coverage(bbox: BBox, fills: list[tuple[int, pymupdf.Rect]], seqno: int) -> float:
    """Largest share of `bbox` covered by a fill drawn after `seqno`."""
    rect = pymupdf.Rect(bbox)
    area = abs(rect.get_area())
    if area <= 0:
        return 0.0
    best = 0.0
    for fill_seqno, fill in fills:
        if fill_seqno <= seqno:
            continue
        overlap = rect & fill
        if overlap.is_empty:
            continue
        best = max(best, abs(overlap.get_area()) / area)
    return best


def _char_words(span: dict, fills: list[tuple[int, pymupdf.Rect]]) -> list[tuple[Word, float]]:
    """Split one text span into words, each with how much of it is covered."""
    seqno = int(span.get("seqno", 0))
    space_width = float(span.get("spacewidth") or 0) or 2.0
    out: list[tuple[Word, float]] = []
    current: list[tuple] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        text = "".join(chr(char[0]) for char in current).strip()
        if text:
            bbox = (
                min(c[3][0] for c in current),
                min(c[3][1] for c in current),
                max(c[3][2] for c in current),
                max(c[3][3] for c in current),
            )
            baseline = current[0][2][1]
            out.append((Word(text=text, bbox=bbox, seqno=seqno, baseline=baseline), _coverage(bbox, fills, seqno)))
        current = []

    previous_end: float | None = None
    for char in span["chars"]:
        if chr(char[0]).isspace():
            flush()
            previous_end = char[3][2]
            continue
        if previous_end is not None and char[3][0] - previous_end > max(1.0, space_width * 0.55):
            flush()
        current.append(char)
        previous_end = char[3][2]
    flush()
    return out


def extract_page_text(page: pymupdf.Page) -> tuple[list[TextLine], list[ConcealedSpan]]:
    """Visible text lines of a PDF page, plus the text that opaque paint covers.

    Must be called with MUPDF_LOCK held.
    """
    fills = opaque_light_fills(page)
    visible: list[Word] = []
    concealed: list[ConcealedSpan] = []
    for span in page.get_texttrace():
        if span.get("type") != 0:  # 0 = filled glyphs; ignore clipping/stroke-only spans
            continue
        if (span.get("opacity") or 1.0) < 0.05:
            continue
        for word, coverage in _char_words(span, fills):
            if coverage >= COVER_FRACTION:
                concealed.append(ConcealedSpan(text=word.text, bbox=word.bbox, coverage=round(coverage, 4)))
            else:
                visible.append(word)
    return build_lines(visible), _merge_concealed(concealed)


def _merge_concealed(spans: list[ConcealedSpan]) -> list[ConcealedSpan]:
    """Join concealed words that sit next to each other on the same line."""
    merged: list[ConcealedSpan] = []
    for span in sorted(spans, key=lambda s: (round(s.bbox[1], 1), s.bbox[0])):
        if merged:
            last = merged[-1]
            same_line = abs(last.bbox[1] - span.bbox[1]) <= 2.5
            adjacent = span.bbox[0] - last.bbox[2] <= 6.0
            if same_line and adjacent:
                merged[-1] = ConcealedSpan(
                    text=f"{last.text} {span.text}",
                    bbox=(last.bbox[0], min(last.bbox[1], span.bbox[1]), span.bbox[2], max(last.bbox[3], span.bbox[3])),
                    coverage=round(min(last.coverage, span.coverage), 4),
                )
                continue
        merged.append(span)
    return merged

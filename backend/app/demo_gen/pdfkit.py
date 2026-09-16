"""Deterministic PDF drawing toolkit for the synthetic demo documents (ReportLab canvas).

Everything here is a pure function of its inputs: no clocks, random numbers or UUIDs.
Canvases are created with invariant=1 so ReportLab writes fixed dates and document IDs.
"""

import hashlib
import io
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen.canvas import Canvas

from app.demo_gen.profile import NOTICE

PAGE_W, PAGE_H = A4
MARGIN_X = 40.0
CONTENT_W = PAGE_W - 2 * MARGIN_X
FOOTER_Y = 22.0
BOTTOM_LIMIT = 58.0

REGULAR = "Helvetica"
BOLD = "Helvetica-Bold"
ITALIC = "Helvetica-Oblique"

INK = HexColor("#1c2733")
MUTED = HexColor("#526170")
FAINT = HexColor("#8795a3")
RULE = HexColor("#c5cfd9")
GRID = HexColor("#cfd8e1")
SHADE = HexColor("#edf2f6")
NOTICE_RED = HexColor("#9b2c2c")
SIGNATURE_BLUE = HexColor("#1e3a8a")
STAMP_VIOLET = HexColor("#4c3fb8")

GENERATOR_NAME = "ClaimAI synthetic demo data generator"


class LayoutError(RuntimeError):
    """Content does not fit in the printable area of a page."""


@dataclass(frozen=True)
class Letterhead:
    name: str
    tagline: str
    contact: tuple[str, ...]
    accent: Color
    mark: str = "cross"  # "cross" for hospital departments, "box" for suppliers


@dataclass(frozen=True)
class Stamp:
    lines: tuple[str, ...]
    shape: str = "round"  # "round" or "rect"
    color: Color = STAMP_VIOLET


@dataclass(frozen=True)
class Slot:
    """A signature slot: ink above a line, printed label and name below it."""

    label: str
    name: str | None = None
    date: str | None = None
    signed: bool = True
    stamp: Stamp | None = None


@dataclass(frozen=True)
class Cell:
    x: float
    y: float  # bottom edge
    w: float
    h: float


def set_metadata(canvas: Canvas, title: str) -> None:
    canvas.setTitle(title)
    canvas.setAuthor(GENERATOR_NAME)
    canvas.setCreator(GENERATOR_NAME)
    canvas.setSubject(NOTICE)
    canvas.setKeywords("synthetic, demo, fictional, not a real record")


def draw_signature(canvas: Canvas, x: float, y: float, width: float, seed: str) -> None:
    """A handwriting-like stroke whose shape is derived from `seed`."""
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    height = 22
    path = canvas.beginPath()
    path.moveTo(x, y + 6 + digest[0] % 8)
    steps = 6
    for i in range(steps):
        b = digest[1 + i * 3 : 4 + i * 3]
        x0 = x + width * i / steps
        x3 = x + width * (i + 1) / steps
        path.curveTo(
            x0 + (x3 - x0) * 0.35,
            y + 2 + b[0] % height,
            x0 + (x3 - x0) * 0.7,
            y + 2 + b[1] % height,
            x3,
            y + 4 + b[2] % (height - 8),
        )
    path.moveTo(x + width * 0.12, y + 3 + digest[20] % 4)
    path.curveTo(x + width * 0.45, y, x + width * 0.75, y + 7, x + width * 1.02, y + 2 + digest[21] % 5)
    canvas.saveState()
    canvas.setStrokeColor(SIGNATURE_BLUE)
    canvas.setLineWidth(1.05)
    canvas.setLineCap(1)
    canvas.setLineJoin(1)
    canvas.drawPath(path, stroke=1, fill=0)
    canvas.restoreState()


def draw_stamp(canvas: Canvas, stamp: Stamp, cx: float, cy: float) -> None:
    canvas.saveState()
    canvas.translate(cx, cy)
    canvas.rotate(-11 if stamp.shape == "round" else 4)
    canvas.setStrokeColor(stamp.color)
    canvas.setFillColor(stamp.color)
    if stamp.shape == "round":
        radius = 25
        canvas.setLineWidth(1.3)
        canvas.circle(0, 0, radius, stroke=1, fill=0)
        canvas.setLineWidth(0.6)
        canvas.circle(0, 0, radius - 3.2, stroke=1, fill=0)
        size = 5.4
    else:
        w, h = 88, 30
        canvas.setLineWidth(1.1)
        canvas.roundRect(-w / 2, -h / 2, w, h, 3, stroke=1, fill=0)
        size = 5.6
    canvas.setFont(BOLD, size)
    step = size + 1.4
    count = len(stamp.lines)
    for i, line in enumerate(stamp.lines):
        canvas.drawCentredString(0, (count - 1) * step / 2 - i * step - size * 0.35, line)
    canvas.restoreState()


def draw_barcode(canvas: Canvas, x: float, y: float, width: float, height: float, seed: str) -> None:
    digest = hashlib.sha256(seed.encode("utf-8")).digest()
    cursor = x
    i = 0
    while cursor < x + width - 2.5:
        bar = 0.6 + (digest[i % len(digest)] % 3) * 0.55
        gap = 0.7 + (digest[(i + 7) % len(digest)] % 3) * 0.5
        canvas.rect(cursor, y, bar, height, stroke=0, fill=1)
        cursor += bar + gap
        i += 1


class Page:
    """Cursor-based writer for one A4 page. `y` is the baseline of the next line of text."""

    def __init__(
        self, canvas: Canvas, letterhead: Letterhead, page_no: int, total: int, doc_ref: str, text_scale: float = 1.0
    ):
        self.c = canvas
        self.lh = letterhead
        self.page_no = page_no
        self.total = total
        self.doc_ref = doc_ref
        self.k = text_scale
        self.y = PAGE_H - 34

    # --- page chrome ----------------------------------------------------------------------

    def draw_letterhead(self) -> None:
        c, lh = self.c, self.lh
        top = PAGE_H - 30
        c.setFillColor(lh.accent)
        c.roundRect(MARGIN_X, top - 30, 30, 30, 5, stroke=0, fill=1)
        c.setFillColor(white)
        if lh.mark == "cross":
            c.rect(MARGIN_X + 12, top - 25, 6, 20, stroke=0, fill=1)
            c.rect(MARGIN_X + 5, top - 18, 20, 6, stroke=0, fill=1)
        else:
            c.rect(MARGIN_X + 7, top - 23, 16, 16, stroke=0, fill=1)
            c.setFillColor(lh.accent)
            c.rect(MARGIN_X + 11, top - 19, 8, 8, stroke=0, fill=1)
        c.setFillColor(lh.accent)
        c.setFont(BOLD, 14.5)
        c.drawString(MARGIN_X + 40, top - 13, lh.name)
        c.setFillColor(MUTED)
        c.setFont(REGULAR, 7.8)
        c.drawString(MARGIN_X + 40, top - 25, lh.tagline)
        c.setFont(REGULAR, 7.2)
        for i, line in enumerate(lh.contact):
            c.drawRightString(PAGE_W - MARGIN_X, top - 7 - i * 9, line)
        c.setStrokeColor(lh.accent)
        c.setLineWidth(1.6)
        c.line(MARGIN_X, top - 38, PAGE_W - MARGIN_X, top - 38)
        self.y = top - 60

    def patient_strip(self, text: str) -> None:
        c = self.c
        c.setFillColor(SHADE)
        c.rect(MARGIN_X, self.y - 5, CONTENT_W, 16, stroke=0, fill=1)
        c.setFillColor(MUTED)
        c.setFont(BOLD, 7.8)
        c.drawString(MARGIN_X + 8, self.y, text)
        self.y -= 26

    def draw_footer(self) -> None:
        c = self.c
        if self.y < BOTTOM_LIMIT - 14:
            raise LayoutError(f"{self.doc_ref} page {self.page_no}: content overflows the footer")
        c.setStrokeColor(RULE)
        c.setLineWidth(0.6)
        c.line(MARGIN_X, FOOTER_Y + 11, PAGE_W - MARGIN_X, FOOTER_Y + 11)
        c.setFont(REGULAR, 6.8)
        c.setFillColor(FAINT)
        c.drawString(MARGIN_X, FOOTER_Y, self.doc_ref)
        c.drawRightString(PAGE_W - MARGIN_X, FOOTER_Y, f"Page {self.page_no} of {self.total}")
        c.setFont(BOLD, 7.4)
        c.setFillColor(NOTICE_RED)
        c.drawCentredString(PAGE_W / 2, FOOTER_Y, NOTICE)

    # --- content --------------------------------------------------------------------------

    def ensure(self, needed: float) -> None:
        if self.y - needed < BOTTOM_LIMIT:
            raise LayoutError(
                f"{self.doc_ref} page {self.page_no}: needs {needed:.0f}pt, "
                f"only {self.y - BOTTOM_LIMIT:.0f}pt left"
            )

    def gap(self, height: float) -> None:
        self.y -= height

    def title(self, text: str, subtitle: str | None = None) -> None:
        c = self.c
        c.setFillColor(INK)
        c.setFont(BOLD, 13 * self.k)
        c.drawCentredString(PAGE_W / 2, self.y, text)
        self.y -= 13 * self.k
        if subtitle:
            c.setFont(REGULAR, 8.5 * self.k)
            c.setFillColor(MUTED)
            c.drawCentredString(PAGE_W / 2, self.y, subtitle)
            self.y -= 12 * self.k
        self.y -= 9

    def section(self, heading: str) -> None:
        size = 8.6 * self.k
        self.ensure(32)
        c = self.c
        c.setFillColor(SHADE)
        c.rect(MARGIN_X, self.y - 5, CONTENT_W, size + 7.5, stroke=0, fill=1)
        c.setFillColor(self.lh.accent)
        c.rect(MARGIN_X, self.y - 5, 2.5, size + 7.5, stroke=0, fill=1)
        c.setFillColor(INK)
        c.setFont(BOLD, size)
        c.drawString(MARGIN_X + 8, self.y, heading.upper())
        self.y -= size + 14

    def fields(self, pairs: Sequence[tuple[str, str]], columns: int = 2) -> None:
        """Label/value pairs; label and value share a baseline so they extract as one line."""
        c = self.c
        size = 8.8 * self.k
        label_size = size - 0.4
        leading = size + 3.2
        col_w = CONTENT_W / columns
        for start in range(0, len(pairs), columns):
            row = []
            for label, value in pairs[start : start + columns]:
                label_text = f"{label}:"
                label_w = stringWidth(label_text, BOLD, label_size) + 4
                lines = simpleSplit(str(value), REGULAR, size, col_w - label_w - 12) or [""]
                row.append((label_text, label_w, lines))
            lines_needed = max(len(lines) for _, _, lines in row)
            self.ensure(lines_needed * leading)
            for column, (label_text, label_w, lines) in enumerate(row):
                x = MARGIN_X + 6 + column * col_w
                c.setFont(BOLD, label_size)
                c.setFillColor(MUTED)
                c.drawString(x, self.y, label_text)
                c.setFont(REGULAR, size)
                c.setFillColor(INK)
                for i, line in enumerate(lines):
                    c.drawString(x + label_w, self.y - i * leading, line)
            self.y -= lines_needed * leading + 1.5
        self.y -= 5

    def text(self, content: str, size: float = 8.8, font: str = REGULAR, color: Color = INK, after: float = 5) -> None:
        c = self.c
        size *= self.k
        leading = size * 1.38
        lines = simpleSplit(content, font, size, CONTENT_W - 12)
        self.ensure(len(lines) * leading)
        c.setFont(font, size)
        c.setFillColor(color)
        for line in lines:
            c.drawString(MARGIN_X + 6, self.y, line)
            self.y -= leading
        self.y -= after

    def bullets(self, items: Sequence[str], numbered: bool = False, size: float = 8.8) -> None:
        c = self.c
        size *= self.k
        leading = size * 1.38
        for number, item in enumerate(items, start=1):
            lines = simpleSplit(item, REGULAR, size, CONTENT_W - 30)
            self.ensure(len(lines) * leading)
            c.setFont(REGULAR, size)
            c.setFillColor(INK)
            c.drawString(MARGIN_X + 8, self.y, f"{number}." if numbered else "•")
            for line in lines:
                c.drawString(MARGIN_X + 24, self.y, line)
                self.y -= leading
            self.y -= 1.2
        self.y -= 4

    def table(
        self,
        header: Sequence[str],
        rows: Sequence[Sequence[str]],
        widths: Sequence[float],
        align: Sequence[str] | None = None,
        size: float = 8.0,
        bold_rows: Sequence[int] = (),
    ) -> list[list[Cell]]:
        """Draw a gridded table; returns the cell boxes of the body rows."""
        c = self.c
        size *= self.k
        pad = 4.0
        leading = size + 2.6
        scale = CONTENT_W / sum(widths)
        widths = [w * scale for w in widths]
        align = list(align or ["L"] * len(widths))
        xs = [MARGIN_X]
        for w in widths[:-1]:
            xs.append(xs[-1] + w)

        def wrap(values, font):
            return [simpleSplit(str(v), font, size, w - 2 * pad) or [""] for v, w in zip(values, widths, strict=True)]

        def row_height(lines):
            return max(len(cell) for cell in lines) * leading + 2 * pad - 1

        def draw_row(lines, top, font, color):
            c.setFont(font, size)
            c.setFillColor(color)
            for cell_lines, x, w, a in zip(lines, xs, widths, align, strict=True):
                for i, line in enumerate(cell_lines):
                    baseline = top - pad - size * 0.78 - i * leading
                    if a == "R":
                        c.drawRightString(x + w - pad, baseline, line)
                    elif a == "C":
                        c.drawCentredString(x + w / 2, baseline, line)
                    else:
                        c.drawString(x + pad, baseline, line)

        top = self.y + size
        header_lines = wrap(header, BOLD)
        header_h = row_height(header_lines)
        body = [(wrap(row, BOLD if i in bold_rows else REGULAR), BOLD if i in bold_rows else REGULAR) for i, row in enumerate(rows)]
        total_h = header_h + sum(row_height(lines) for lines, _ in body)
        self.ensure(total_h + 6)

        c.setFillColor(SHADE)
        c.rect(MARGIN_X, top - header_h, CONTENT_W, header_h, stroke=0, fill=1)
        draw_row(header_lines, top, BOLD, MUTED)
        y = top - header_h
        horizontal = [top, y]
        cells: list[list[Cell]] = []
        for lines, font in body:
            h = row_height(lines)
            draw_row(lines, y, font, INK)
            cells.append([Cell(x, y - h, w, h) for x, w in zip(xs, widths, strict=True)])
            y -= h
            horizontal.append(y)

        c.setStrokeColor(GRID)
        c.setLineWidth(0.6)
        for hy in horizontal:
            c.line(MARGIN_X, hy, MARGIN_X + CONTENT_W, hy)
        for vx in [*xs, MARGIN_X + CONTENT_W]:
            c.line(vx, top, vx, y)
        self.y = y - 16
        return cells

    def totals(self, pairs: Sequence[tuple[str, str]], size: float = 8.8) -> None:
        """Right-aligned summary rows below a bill table; the last row is emphasised."""
        c = self.c
        size *= self.k
        row_h = size + 6
        self.ensure(len(pairs) * row_h)
        right = PAGE_W - MARGIN_X - 6
        label_right = right - 110
        for i, (label, value) in enumerate(pairs):
            last = i == len(pairs) - 1
            if last:
                c.setFillColor(SHADE)
                c.rect(label_right - 170, self.y - 4.5, right - label_right + 176, size + 7, stroke=0, fill=1)
            c.setFont(BOLD if last else REGULAR, size)
            c.setFillColor(INK if last else MUTED)
            c.drawRightString(label_right, self.y, label)
            c.setFillColor(INK)
            c.drawRightString(right, self.y, value)
            self.y -= row_h
        self.y -= 4

    def signatures(self, slots: Sequence[Slot], before: float = 12) -> None:
        c = self.c
        ink_area = 36
        col_w = CONTENT_W / len(slots)
        width = min(col_w - 24, 196 if len(slots) > 1 else 270)
        name_lines = [simpleSplit(s.name, REGULAR, 7.6, width) if s.name else [] for s in slots]
        below = 14 + max(len(lines) for lines in name_lines) * 9.5 + (9.5 if any(s.date for s in slots) else 0)
        self.ensure(before + ink_area + below)
        line_y = self.y - before - ink_area
        for i, slot in enumerate(slots):
            x = MARGIN_X + 6 + i * col_w
            if slot.signed:
                draw_signature(c, x + 6, line_y + 3, min(width * 0.62, 118), seed=f"{slot.label}|{slot.name}")
            if slot.stamp:
                draw_stamp(c, slot.stamp, x + width - 36, line_y + 17)
            c.setStrokeColor(MUTED)
            c.setLineWidth(0.7)
            c.line(x, line_y, x + width, line_y)
            c.setFont(BOLD, 7.8)
            c.setFillColor(INK)
            c.drawString(x, line_y - 10, slot.label)
            ny = line_y - 20
            c.setFont(REGULAR, 7.6)
            c.setFillColor(MUTED)
            for line in name_lines[i]:
                c.drawString(x, ny, line)
                ny -= 9.5
            if slot.date:
                c.drawString(x, ny, f"Date: {slot.date}")
        self.y = line_y - below - 6


PageBuilder = Callable[[Page], None]


def render_pdf(
    pages: Sequence[PageBuilder],
    *,
    letterhead: Letterhead,
    title: str,
    doc_ref: str,
    continuation_strip: str | None = None,
    text_scale: float = 1.0,
) -> bytes:
    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, invariant=1, pageCompression=1)
    set_metadata(canvas, title)
    for number, build in enumerate(pages, start=1):
        page = Page(canvas, letterhead, number, len(pages), doc_ref, text_scale=text_scale)
        page.draw_letterhead()
        if number > 1 and continuation_strip:
            page.patient_strip(continuation_strip)
        build(page)
        page.draw_footer()
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()

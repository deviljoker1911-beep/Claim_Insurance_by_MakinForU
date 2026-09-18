"""Signature area detection.

A signature area is a short caption under a horizontal rule ("Signature of Patient /
Guardian", "Authorised Signatory", "Reported by"). The caption only locates the area —
what decides whether it is signed is the ink above the rule:

  * the rule itself, table borders and page furniture are straight lines, never signatures;
  * a stamp is a closed round or rectangular graphic and is reported separately;
  * a signature is a run of curved strokes, wider than it is tall, in the left part of the
    slot where a person signs.

Detection works on the vector content of a PDF page. For a page that is only pixels (a
photo or a flat scan) it reports that it could not look, rather than guessing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import pymupdf

from app.config_files import document_types_config
from app.processing.types import BBox, TextLine, normalise_bbox

METHOD_VECTOR = "vector_ink"
METHOD_UNAVAILABLE = "unavailable_scanned_page"


@lru_cache
def _settings() -> dict:
    return document_types_config()["signatures"]


@lru_cache
def _caption_patterns() -> tuple[re.Pattern, ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in _settings()["caption_patterns"])


def _is_caption(text: str) -> bool:
    text = text.strip()
    if not text or ":" in text or len(text) > int(_settings()["caption_max_chars"]):
        return False
    return any(pattern.search(text) for pattern in _caption_patterns())


@dataclass
class SlotCandidate:
    caption: str
    page_number: int
    rule: BBox
    signed: bool
    stamp_detected: bool
    ink_bbox: BBox | None
    curve_segments: int
    # The area above the rule that was searched for signature ink. It is what the evidence for an
    # unsigned slot points at: the rule on its own is a line with no height, so a reader asked to
    # look at it would be shown nothing.
    search_region: BBox


def _horizontal_rules(page: pymupdf.Page) -> list[BBox]:
    minimum = float(_settings()["rule_min_width"])
    maximum = float(_settings()["rule_max_width"])
    rules: list[BBox] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", ()):
            if item[0] != "l":
                continue
            start, end = item[1], item[2]
            if abs(start.y - end.y) > 0.6:
                continue
            x0, x1 = sorted((start.x, end.x))
            if not minimum <= x1 - x0 <= maximum:
                continue
            rules.append((x0, start.y, x1, end.y))
    return rules


def _curve_paths(page: pymupdf.Page) -> list[tuple[int, BBox]]:
    """(curve segment count, bounding box) for every stroked path with curves."""
    paths: list[tuple[int, BBox]] = []
    for drawing in page.get_drawings():
        curves = [item for item in drawing.get("items", ()) if item[0] == "c"]
        if not curves:
            continue
        width = drawing.get("width")
        if width is not None and width > 2.5:
            continue
        points = [point for item in curves for point in item[1:]]
        if not points:
            continue
        box = (
            min(p.x for p in points),
            min(p.y for p in points),
            max(p.x for p in points),
            max(p.y for p in points),
        )
        paths.append((len(curves), box))
    return paths


def _rectangles(page: pymupdf.Page) -> list[BBox]:
    boxes: list[BBox] = []
    for drawing in page.get_drawings():
        for item in drawing.get("items", ()):
            if item[0] == "re":
                rect = pymupdf.Rect(item[1])
                boxes.append((rect.x0, rect.y0, rect.x1, rect.y1))
    return boxes


def _inside(box: BBox, region: pymupdf.Rect, *, fraction: float = 0.6) -> bool:
    rect = pymupdf.Rect(box)
    area = abs(rect.get_area())
    overlap = rect & region
    if overlap.is_empty:
        return False
    if area <= 0:  # zero-height strokes still count when they lie in the region
        return True
    return abs(overlap.get_area()) / area >= fraction


def _looks_like_stamp(box: BBox) -> bool:
    width, height = box[2] - box[0], box[3] - box[1]
    if width < 24 or height < 18:
        return False
    aspect = width / max(height, 0.1)
    return 0.5 <= aspect <= 3.4


def detect_page_slots(page: pymupdf.Page, lines: list[TextLine], page_number: int) -> list[SlotCandidate]:
    """Find signature areas on one PDF page. Must be called with MUPDF_LOCK held."""
    config = _settings()
    gap = float(config["caption_gap"])
    band = float(config["ink_band"])
    left_fraction = float(config["ink_left_fraction"])
    min_segments = int(config["min_curve_segments"])
    min_width = float(config["min_ink_width"])

    curves = _curve_paths(page)
    rectangles = _rectangles(page)
    candidates: list[SlotCandidate] = []
    for rule in _horizontal_rules(page):
        x0, y, x1, _ = rule
        caption = None
        for line in lines:
            if not (y < line.bbox[1] <= y + gap):
                continue
            # Captions of slots that sit side by side share one line, so compare columns.
            for cell in line.cells():
                if cell.bbox is None or abs(cell.bbox[0] - x0) > 8:
                    continue
                if _is_caption(cell.text):
                    caption = cell.text.strip()
                    break
            if caption:
                break
        if caption is None:
            continue
        width = x1 - x0
        ink_region = pymupdf.Rect(x0 - 2, y - band, x0 + width * left_fraction, y - 0.5)
        stamp_region = pymupdf.Rect(x0 + width * left_fraction, y - band, x1 + 16, y + 4)
        signature_curves = [(count, box) for count, box in curves if _inside(box, ink_region)]
        segments = sum(count for count, _ in signature_curves)
        boxes = [box for _, box in signature_curves]
        ink_bbox = None
        signed = False
        if boxes:
            ink_bbox = (
                min(b[0] for b in boxes),
                min(b[1] for b in boxes),
                max(b[2] for b in boxes),
                max(b[3] for b in boxes),
            )
            ink_width = ink_bbox[2] - ink_bbox[0]
            ink_height = max(ink_bbox[3] - ink_bbox[1], 0.1)
            signed = segments >= min_segments and ink_width >= min_width and ink_width / ink_height >= 1.3
        stamp = any(_looks_like_stamp(box) and _inside(box, stamp_region, fraction=0.35) for _, box in curves)
        stamp = stamp or any(
            _looks_like_stamp(box) and _inside(box, stamp_region, fraction=0.35) for box in rectangles
        )
        candidates.append(
            SlotCandidate(
                caption=caption,
                page_number=page_number,
                rule=rule,
                signed=signed,
                stamp_detected=stamp,
                ink_bbox=ink_bbox,
                curve_segments=segments,
                search_region=(ink_region.x0, ink_region.y0, ink_region.x1, rule[3]),
            )
        )
    return candidates


def match_expected(
    candidates: list[SlotCandidate],
    expected: list[dict],
    *,
    page_sizes: dict[int, tuple[float, float]],
    analysed_pages: list[int],
    unavailable_pages: list[int],
) -> dict:
    """Pair detected signature areas with the ones the document type expects."""
    remaining = list(candidates)
    slots: list[dict] = []
    for spec in expected or []:
        pattern = re.compile(spec.get("match", spec["key"]), re.IGNORECASE)
        match = next((candidate for candidate in remaining if pattern.search(candidate.caption)), None)
        if match is not None:
            remaining.remove(match)
            slots.append(_slot_payload(match, spec, page_sizes))
        else:
            slots.append(
                {
                    "key": spec["key"],
                    "label": spec.get("label", spec["key"]),
                    "caption": None,
                    "required": bool(spec.get("required")),
                    "found": False,
                    "checked": bool(analysed_pages),
                    "signed": False if analysed_pages else None,
                    "stamp_detected": False,
                    "page_number": None,
                    "bbox": None,
                    "method": METHOD_VECTOR if analysed_pages else METHOD_UNAVAILABLE,
                    "detail": (
                        "No signature area with this caption was found in the document."
                        if analysed_pages
                        else "This document is a scan, so signature ink cannot be assessed in this phase."
                    ),
                }
            )
    for candidate in remaining:
        slots.append(_slot_payload(candidate, None, page_sizes))
    return {
        "method": METHOD_VECTOR if analysed_pages else METHOD_UNAVAILABLE,
        "pages_analysed": analysed_pages,
        "pages_not_analysed": unavailable_pages,
        "slots": slots,
    }


def _slot_payload(candidate: SlotCandidate, spec: dict | None, page_sizes: dict[int, tuple[float, float]]) -> dict:
    width, height = page_sizes.get(candidate.page_number, (1.0, 1.0))
    # Where the signature is, if there is one; otherwise the area that was searched for it.
    box = candidate.ink_bbox or candidate.search_region
    return {
        "key": spec["key"] if spec else None,
        "label": (spec.get("label") if spec else None) or candidate.caption,
        "caption": candidate.caption,
        "required": bool(spec.get("required")) if spec else False,
        "found": True,
        "checked": True,
        "signed": candidate.signed,
        "stamp_detected": candidate.stamp_detected,
        "page_number": candidate.page_number,
        "bbox": normalise_bbox(box, width, height),
        "method": METHOD_VECTOR,
        "detail": (
            "Signature strokes detected above the signature rule."
            if candidate.signed
            else "The signature area is present but no signature ink was found above the rule."
        ),
    }


def unsigned_required_slots(result: dict) -> list[dict]:
    """Expected signature areas that were checked and carry no signature."""
    return [
        slot
        for slot in result.get("slots", [])
        if slot.get("required") and slot.get("checked") and not slot.get("signed")
    ]

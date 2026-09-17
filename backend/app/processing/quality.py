"""Page quality analysis.

Everything here is measured from the page itself: its resolution, its ink, the steepness
of its character edges and the angle of its text. A document is never judged by its
filename, and the checks report measurements alongside every flag so a reviewer can see
why a page was flagged.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache

import numpy as np

from app.config_files import quality_config

logger = logging.getLogger("claimai.quality")


@lru_cache
def _cv2():
    try:
        import cv2

        return cv2
    except Exception:  # noqa: BLE001 — quality checks degrade instead of failing
        logger.warning("OpenCV is unavailable; sharpness and skew checks are skipped")
        return None


@dataclass
class PageQuality:
    metrics: dict = field(default_factory=dict)
    flags: list[dict] = field(default_factory=list)


def _flag(code: str, detail: str, **measurement) -> dict:
    severity = quality_config()["severity"].get(code, "attention")
    return {"code": code, "severity": severity, "detail": detail, **measurement}


def _laplacian(gray: np.ndarray) -> np.ndarray:
    cv2 = _cv2()
    if cv2 is not None:
        return cv2.Laplacian(gray, cv2.CV_64F)
    image = gray.astype(np.float64)
    out = np.zeros_like(image)
    out[1:-1, 1:-1] = (
        image[:-2, 1:-1] + image[2:, 1:-1] + image[1:-1, :-2] + image[1:-1, 2:] - 4 * image[1:-1, 1:-1]
    )
    return out


def edge_steepness(gray: np.ndarray, dpi: float | None) -> float | None:
    """95th percentile of |Laplacian| over ink pixels, measured at a fixed resolution.

    Sharp printed text keeps steep edges; a soft or out-of-focus scan does not. Scaling to
    a fixed DPI first makes the number comparable between a 96 dpi scan and a 300 dpi one.
    """
    cv2 = _cv2()
    target = float(quality_config().get("normalise_dpi", 150))
    working = gray
    if cv2 is not None and dpi and abs(target / dpi - 1.0) > 0.05:
        scale = target / dpi
        working = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    mask = working < 200
    if not mask.any():
        return None
    values = np.abs(_laplacian(working))[mask]
    return round(float(np.percentile(values, 95)), 1)


def skew_degrees(gray: np.ndarray) -> float | None:
    """Text angle, from the rotation whose horizontal ink profile is most peaked."""
    cv2 = _cv2()
    if cv2 is None:
        return None
    scale = 700.0 / max(gray.shape)
    small = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA) if scale < 1 else gray
    ink = (small < 200).astype(np.float32)
    if ink.sum() < 200:
        return None
    height, width = ink.shape
    centre = (width / 2, height / 2)
    best_score, best_angle = -1.0, 0.0
    for step in range(-24, 25):
        angle = step * 0.25
        matrix = cv2.getRotationMatrix2D(centre, angle, 1.0)
        rotated = cv2.warpAffine(ink, matrix, (width, height), flags=cv2.INTER_NEAREST, borderValue=0)
        score = float(np.var(np.diff(rotated.sum(axis=1))))
        if score > best_score:
            best_score, best_angle = score, angle
    return round(best_angle, 2)


def _edges_with_ink(gray: np.ndarray) -> list[str]:
    thresholds = quality_config()["thresholds"]
    level = float(thresholds["edge_ink_threshold"])
    band = max(2, int(min(gray.shape) * float(thresholds["edge_band_fraction"])))
    run = float(thresholds["edge_run_fraction"])
    ink = gray < level
    edges = []
    for name, strip, axis in (
        ("top", ink[:band, :], 0),
        ("bottom", ink[-band:, :], 0),
        ("left", ink[:, :band], 1),
        ("right", ink[:, -band:], 1),
    ):
        if not strip.size:
            continue
        # Share of the edge that carries ink. A solid band (a card background or a printed
        # border) covers nearly all of it and is page furniture, not content cut off.
        covered = float(strip.any(axis=axis).mean())
        if run <= covered <= 0.85:
            edges.append(name)
    return edges


def analyse_page(
    gray: np.ndarray | None,
    *,
    effective_dpi: float | None,
    scanned: bool,
    char_count: int,
    word_count: int,
    ocr_confidence: float | None = None,
    ocr_min_confidence: float | None = None,
) -> PageQuality:
    """Measure one page and turn the measurements into quality flags.

    `scanned` marks a page whose content is pixels (an uploaded image, or a PDF page with
    no text layer). Resolution, sharpness and skew only mean something for those; a
    digital PDF page carries its text as vectors and is always crisp.
    """
    thresholds = quality_config()["thresholds"]
    metrics: dict = {
        "scanned": scanned,
        "char_count": char_count,
        "word_count": word_count,
        "effective_dpi": effective_dpi,
        "ocr_confidence": ocr_confidence,
        "ocr_min_confidence": ocr_min_confidence,
    }
    flags: list[dict] = []

    if gray is None:
        metrics["analysed"] = False
        return PageQuality(metrics=metrics, flags=flags)

    metrics["analysed"] = True
    metrics["width_px"], metrics["height_px"] = int(gray.shape[1]), int(gray.shape[0])
    ink_coverage = float((gray < 200).mean())
    metrics["ink_coverage"] = round(ink_coverage, 5)

    blank = ink_coverage < float(thresholds["blank_ink_coverage"]) and char_count < int(thresholds["blank_char_count"])
    if blank:
        flags.append(
            _flag("blank_page", "The page has almost no content.", ink_coverage=metrics["ink_coverage"])
        )

    if scanned:
        steepness = edge_steepness(gray, effective_dpi)
        metrics["edge_steepness"] = steepness
        skew = skew_degrees(gray)
        metrics["skew_degrees"] = skew
        if effective_dpi:
            if effective_dpi < float(thresholds["very_low_resolution_dpi"]):
                flags.append(
                    _flag(
                        "very_low_resolution",
                        f"Scan resolution is about {effective_dpi:.0f} dpi; 150 dpi or more is expected.",
                        effective_dpi=effective_dpi,
                    )
                )
            elif effective_dpi < float(thresholds["low_resolution_dpi"]):
                flags.append(
                    _flag(
                        "low_resolution",
                        f"Scan resolution is about {effective_dpi:.0f} dpi; 150 dpi or more is expected.",
                        effective_dpi=effective_dpi,
                    )
                )
        if steepness is not None and not blank:
            if steepness < float(thresholds["blurred_edge_steepness"]):
                flags.append(
                    _flag(
                        "blurred_page",
                        "Character edges are soft: the page looks blurred or out of focus.",
                        edge_steepness=steepness,
                    )
                )
            elif steepness < float(thresholds["soft_edge_steepness"]):
                flags.append(
                    _flag("soft_focus", "Character edges are softer than a clean scan.", edge_steepness=steepness)
                )
        if skew is not None and not blank:
            magnitude = abs(skew)
            if magnitude >= float(thresholds["severe_skew_degrees"]):
                flags.append(_flag("severe_skew", f"The page is rotated by about {skew:.1f}°.", skew_degrees=skew))
            elif magnitude >= float(thresholds["skew_degrees"]):
                flags.append(_flag("skewed_page", f"The page is slightly rotated ({skew:.1f}°).", skew_degrees=skew))
        # A cropped-page check assumes a sheet of paper. A card or a photo is meant to be
        # full-bleed, so ink at its edge says nothing about missing content.
        height_px, width_px = gray.shape
        ratio = max(height_px, width_px) / max(min(height_px, width_px), 1)
        # Portrait sheets, or anything close to a standard paper ratio. A landscape card
        # (an insurance e-card is about 1.6:1) is not a page.
        page_shaped = (height_px >= width_px and 1.20 <= ratio <= 1.70) or 1.29 <= ratio <= 1.55
        metrics["page_shaped"] = page_shaped
        edges = _edges_with_ink(gray) if page_shaped else []
        metrics["edges_with_ink"] = edges
        if len(edges) >= int(thresholds["cropped_min_edges"]) and not blank:
            flags.append(
                _flag(
                    "cropped_page",
                    "Content runs into the edge of the page on " + ", ".join(edges) + "; the page may be cut off.",
                    edges=edges,
                )
            )

    if ocr_confidence is not None and not blank:
        if ocr_confidence < float(thresholds["poor_ocr_confidence"]):
            flags.append(
                _flag(
                    "poor_ocr_confidence",
                    f"Text recognition confidence is low ({ocr_confidence:.0%}).",
                    ocr_confidence=ocr_confidence,
                )
            )
        elif ocr_confidence < float(thresholds["low_ocr_confidence"]):
            flags.append(
                _flag(
                    "low_ocr_confidence",
                    f"Text recognition confidence is moderate ({ocr_confidence:.0%}).",
                    ocr_confidence=ocr_confidence,
                )
            )

    if not blank and word_count < int(thresholds["min_words_for_text_page"]):
        flags.append(
            _flag("no_text_recovered", "Almost no text could be read from this page.", word_count=word_count)
        )
    return PageQuality(metrics=metrics, flags=flags)


def grayscale_from_png(png: bytes) -> np.ndarray | None:
    """Decode a rendered page image to a grayscale array."""
    try:
        import io

        from PIL import Image

        with Image.open(io.BytesIO(png)) as image:
            return np.array(image.convert("L"))
    except Exception as exc:  # noqa: BLE001 — a page image that cannot be decoded is reported, not fatal
        logger.warning("Could not decode a rendered page image: %s", exc)
        return None


def summarise_flags(pages: list[dict]) -> list[dict]:
    """Collapse per-page flags into one list per code, with the pages that triggered it."""
    by_code: dict[str, dict] = {}
    for page in pages:
        for flag in page.get("quality_flags", []):
            entry = by_code.setdefault(
                flag["code"],
                {"code": flag["code"], "severity": flag["severity"], "detail": flag["detail"], "pages": []},
            )
            entry["pages"].append(page["page_number"])
    order = {"review": 0, "attention": 1, "info": 2}
    return sorted(by_code.values(), key=lambda entry: (order.get(entry["severity"], 3), entry["code"]))


def degrees_to_text(value: float | None) -> str | None:
    return None if value is None else f"{value:.2f}°" if not math.isnan(value) else None

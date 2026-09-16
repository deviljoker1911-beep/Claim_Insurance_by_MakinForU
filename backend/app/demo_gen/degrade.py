"""Rasterise synthetic PDFs into image documents (a clean e-card and a poor-quality scan).

All steps are deterministic: MuPDF rendering, integer lookup tables, fixed resampling filters,
noise derived from SHAKE-256 of a constant seed, and fixed PNG/JPEG encoder settings.
"""

import hashlib
import io

import pymupdf
from PIL import Image, ImageChops, ImageFilter

from app.processing.pdf import MUPDF_LOCK

CARD_DPI = 300
SCAN_RENDER_DPI = 150
SCAN_DPI = 96  # effective resolution of the poor-quality scan
NOISE_SEED = b"claimai-demo-usg-scan-noise-v1"


def rasterize_first_page(pdf: bytes, dpi: int, gray: bool = False) -> Image.Image:
    with MUPDF_LOCK:
        document = pymupdf.open(stream=pdf, filetype="pdf")
        try:
            pixmap = document[0].get_pixmap(
                dpi=dpi, colorspace=pymupdf.csGRAY if gray else pymupdf.csRGB, alpha=False
            )
            return Image.frombytes("L" if gray else "RGB", (pixmap.width, pixmap.height), pixmap.samples)
        finally:
            document.close()


def card_png(pdf: bytes) -> bytes:
    image = rasterize_first_page(pdf, CARD_DPI)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", dpi=(CARD_DPI, CARD_DPI), compress_level=6, optimize=False)
    return buffer.getvalue()


def degraded_scan_jpeg(pdf: bytes) -> bytes:
    """A skewed, blurred, low-contrast, grainy 96 DPI scan that stays humanly readable."""
    page = rasterize_first_page(pdf, SCAN_RENDER_DPI, gray=True)
    tilted = page.rotate(1.3, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
    size = (round(tilted.width * SCAN_DPI / SCAN_RENDER_DPI), round(tilted.height * SCAN_DPI / SCAN_RENDER_DPI))
    small = tilted.resize(size, Image.Resampling.BILINEAR)
    blurred = small.filter(ImageFilter.GaussianBlur(radius=0.85))
    dull = blurred.point(lambda v: 42 + (v * 79) // 100)

    noise_bytes = hashlib.shake_256(NOISE_SEED).digest(dull.width * dull.height)
    noise = Image.frombytes("L", dull.size, noise_bytes).point(lambda v: 128 + (v - 128) // 12)
    grainy = ImageChops.add(dull, noise, scale=1.0, offset=-128)

    paper_tinted = Image.merge(
        "RGB", (grainy, grainy.point(lambda v: (v * 98) // 100), grainy.point(lambda v: (v * 93) // 100))
    )
    buffer = io.BytesIO()
    paper_tinted.save(
        buffer,
        format="JPEG",
        quality=58,
        dpi=(SCAN_DPI, SCAN_DPI),
        subsampling=2,
        optimize=False,
        progressive=False,
    )
    return buffer.getvalue()

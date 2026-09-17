"""Page images.

Every page gets a PNG rendering, used for the pixel-based quality checks and for showing
evidence to a reviewer. Originals are opened read-only and never modified; renderings are
written to a separate `pages/` directory inside the claim's storage folder.
"""

from __future__ import annotations

import io
from pathlib import Path

import pymupdf
from PIL import Image

from app.config import get_settings
from app.processing.pdf import MUPDF_LOCK
from app.storage import claims_root

Image.MAX_IMAGE_PIXELS = 64_000_000  # refuse decompression-bomb images


def pages_dir(claim_id: str, document_id: str) -> Path:
    return claims_root() / claim_id / "pages" / document_id


def page_image_path(claim_id: str, document_id: str, page_number: int) -> Path:
    return pages_dir(claim_id, document_id) / f"p{page_number:04d}.png"


def relative_path(path: Path) -> str:
    return str(path.relative_to(get_settings().storage_dir))


def write_page_image(claim_id: str, document_id: str, page_number: int, png: bytes) -> str:
    path = page_image_path(claim_id, document_id, page_number)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".png.partial")
    temporary.write_bytes(png)
    temporary.replace(path)
    return relative_path(path)


def render_pdf_page(page: pymupdf.Page, dpi: int) -> tuple[bytes, int, int]:
    """Render a PDF page to PNG. Must be called with MUPDF_LOCK held."""
    pixmap = page.get_pixmap(dpi=dpi)
    return pixmap.tobytes("png"), pixmap.width, pixmap.height


def pdf_page_image_dpi(page: pymupdf.Page) -> float | None:
    """Effective resolution of a page whose content is a single scanned image."""
    width_inches = page.rect.width / 72.0
    height_inches = page.rect.height / 72.0
    if width_inches <= 0 or height_inches <= 0:
        return None
    best: float | None = None
    for image in page.get_images(full=True):
        width, height = image[2], image[3]
        if not width or not height:
            continue
        dpi = min(width / width_inches, height / height_inches)
        best = dpi if best is None else max(best, dpi)
    return round(best, 1) if best else None


def load_image_page(path: Path) -> tuple[bytes, int, int, float | None]:
    """A PNG rendering of an uploaded image, with its declared resolution."""
    settings_max = 4000
    with Image.open(path) as image:
        image.load()
        dpi_info = image.info.get("dpi")
        dpi = float(dpi_info[0]) if dpi_info and dpi_info[0] else None
        rendered = image.convert("RGB")
        if max(rendered.size) > settings_max:
            scale = settings_max / max(rendered.size)
            rendered = rendered.resize(
                (max(1, int(rendered.width * scale)), max(1, int(rendered.height * scale))),
                Image.LANCZOS,
            )
            if dpi:
                dpi = round(dpi * scale, 1)
        buffer = io.BytesIO()
        rendered.save(buffer, format="PNG", optimize=True)
        return buffer.getvalue(), rendered.width, rendered.height, dpi


def estimate_image_dpi(width: int, height: int) -> float:
    """Resolution implied by fitting the page onto A4 (used when metadata has none)."""
    a4_width_inches, a4_height_inches = 8.27, 11.69
    if height >= width:
        return round(min(width / a4_width_inches, height / a4_height_inches), 1)
    return round(min(width / a4_height_inches, height / a4_width_inches), 1)


__all__ = [
    "MUPDF_LOCK",
    "estimate_image_dpi",
    "load_image_page",
    "page_image_path",
    "pages_dir",
    "pdf_page_image_dpi",
    "relative_path",
    "render_pdf_page",
    "write_page_image",
]

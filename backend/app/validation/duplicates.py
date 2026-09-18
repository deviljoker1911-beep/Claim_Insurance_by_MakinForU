"""Finding the same document, or the same page, twice.

A document is a duplicate when its bytes are identical — the SHA-256 recorded at upload
already proves that. A page is only a duplicate when both its text and its picture match:
clinical pages often read alike (two lab reports of the same panel, two nursing shifts), and
similar care is not a duplicate.
"""

from __future__ import annotations

import difflib
import io
import logging

from app.analysis.normalize import squash
from app.config import get_settings
from app.validation.rules import settings

logger = logging.getLogger("claimai.duplicates")

DHASH_SIZE = 8  # 8x9 differences -> a 64-bit fingerprint


def page_dhash(image_path: str | None) -> int | None:
    """A difference hash of a rendered page image: robust to rescanning, sensitive to content."""
    if not image_path:
        return None
    path = get_settings().storage_dir / image_path
    try:
        import numpy as np
        from PIL import Image

        with Image.open(path) as image:
            grey = image.convert("L").resize((DHASH_SIZE + 1, DHASH_SIZE), Image.LANCZOS)
            pixels = np.asarray(grey, dtype=np.int16)
    except Exception as exc:  # noqa: BLE001 — a page we cannot read simply has no fingerprint
        logger.warning("Could not fingerprint %s: %s", image_path, exc)
        return None
    bits = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value


def hamming(left: int, right: int) -> int:
    return bin(left ^ right).count("1")


def text_similarity(left: str, right: str) -> float:
    """How alike two pages read, after normalising whitespace, case and punctuation."""
    first, second = squash(left), squash(right)
    if not first or not second:
        return 0.0
    if first == second:
        return 1.0
    return difflib.SequenceMatcher(None, first, second).ratio()


def duplicate_page_settings() -> tuple[float, int, int]:
    config = settings()["duplicate_page"]
    return (
        float(config["text_similarity"]),
        int(config["dhash_max_distance"]),
        int(config["min_characters"]),
    )


def is_duplicate_page(
    left_text: str, right_text: str, left_hash: int | None, right_hash: int | None
) -> tuple[bool, float, int | None]:
    """Both tests must agree before two pages are called the same page."""
    threshold, max_distance, min_characters = duplicate_page_settings()
    similarity = text_similarity(left_text, right_text)
    distance = hamming(left_hash, right_hash) if left_hash is not None and right_hash is not None else None
    if len(squash(left_text)) < min_characters or len(squash(right_text)) < min_characters:
        return False, similarity, distance
    if similarity < threshold:
        return False, similarity, distance
    if distance is None or distance > max_distance:
        return False, similarity, distance
    return True, similarity, distance


def png_dhash(data: bytes) -> int | None:
    """Fingerprint an in-memory image (used by tests)."""
    try:
        import numpy as np
        from PIL import Image

        with Image.open(io.BytesIO(data)) as image:
            grey = image.convert("L").resize((DHASH_SIZE + 1, DHASH_SIZE), Image.LANCZOS)
            pixels = np.asarray(grey, dtype=np.int16)
    except Exception:  # noqa: BLE001
        return None
    bits = (pixels[:, 1:] > pixels[:, :-1]).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return value

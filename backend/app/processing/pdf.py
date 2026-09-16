"""Serialized access to PyMuPDF.

PyMuPDF does not support concurrent use from multiple threads, so every call into it
goes through MUPDF_LOCK (request handlers run in a thread pool).
"""

import threading
from dataclasses import dataclass
from pathlib import Path

import pymupdf

MUPDF_LOCK = threading.RLock()


class UnreadablePdf(ValueError):
    pass


@dataclass(frozen=True)
class PdfInfo:
    page_count: int
    pdf_version: str | None


def inspect_pdf(path: Path) -> PdfInfo:
    """Return basic metadata, rejecting unreadable, empty or password-protected PDFs."""
    with MUPDF_LOCK:
        try:
            doc = pymupdf.open(path, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 — PyMuPDF raises several error types for bad input
            raise UnreadablePdf("The PDF could not be read (corrupt or unsupported file)") from exc
        try:
            # Malformed files can open successfully and still fail here (e.g. a looping page tree).
            if doc.needs_pass:
                raise UnreadablePdf("Password-protected PDFs are not supported")
            page_count = doc.page_count
            if page_count < 1:
                raise UnreadablePdf("The PDF has no pages")
            return PdfInfo(page_count=page_count, pdf_version=(doc.metadata or {}).get("format") or None)
        except UnreadablePdf:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UnreadablePdf("The PDF could not be read (corrupt or unsupported file)") from exc
        finally:
            doc.close()

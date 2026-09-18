"""The document intelligence pipeline.

One document goes through these stages:

  rendering       PDF text layer (visible text only) and a PNG rendering of every page
  ocr             pages with no usable text layer go through an OCR engine
  quality         resolution, sharpness, skew, blank and cropped-page checks per page
  classification  the document type, from its own content
  extraction      labelled fields and bill tables
  evidence        page, bounding box and snippet for every extracted value

Nothing here writes to the database and nothing modifies the original file: the original is
opened read-only, and page images are written to a separate `pages/` directory.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pymupdf

from app.analysis.classify import Classification, classify, rules_for
from app.analysis.extract import BillData, ExtractedValue, extract_fields
from app.config import get_settings
from app.config_files import quality_config
from app.processing import ocr as ocr_module
from app.processing import render as render_module
from app.processing import signatures as signature_module
from app.processing.pdf import MUPDF_LOCK, UnreadablePdf
from app.processing.quality import analyse_page, grayscale_from_png, summarise_flags
from app.processing.text import extract_page_text
from app.processing.types import (
    SOURCE_NONE,
    SOURCE_OCR,
    SOURCE_PDF_TEXT,
    DocumentContent,
    PageContent,
)
from app.text import plural

logger = logging.getLogger("claimai.pipeline")

STAGE_QUEUED = "queued"
STAGE_RENDERING = "rendering"
STAGE_OCR = "ocr"
STAGE_QUALITY = "quality"
STAGE_CLASSIFICATION = "classification"
STAGE_EXTRACTION = "extraction"
STAGE_EVIDENCE = "evidence"
STAGE_COMPLETED = "completed"
STAGE_FAILED = "failed"

STAGES: tuple[str, ...] = (
    STAGE_QUEUED,
    STAGE_RENDERING,
    STAGE_OCR,
    STAGE_QUALITY,
    STAGE_CLASSIFICATION,
    STAGE_EXTRACTION,
    STAGE_EVIDENCE,
    STAGE_COMPLETED,
)

STAGE_LABELS: dict[str, str] = {
    STAGE_QUEUED: "Queued",
    STAGE_RENDERING: "Rendering",
    STAGE_OCR: "OCR",
    STAGE_QUALITY: "Quality check",
    STAGE_CLASSIFICATION: "Classification",
    STAGE_EXTRACTION: "Extraction",
    STAGE_EVIDENCE: "Evidence",
    STAGE_COMPLETED: "Completed",
    STAGE_FAILED: "Failed",
}

StageCallback = Callable[[str], None]


class ProcessingError(RuntimeError):
    """A document could not be processed. Other documents keep going."""


@dataclass
class ProcessingResult:
    content: DocumentContent
    classification: Classification
    fields: list[ExtractedValue] = field(default_factory=list)
    bill: BillData | None = None
    signatures: dict = field(default_factory=dict)
    quality_flags: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    duration_ms: int = 0


@dataclass
class _PageWork:
    page: PageContent
    gray: np.ndarray | None = None
    needs_ocr: bool = False
    ocr_image: np.ndarray | None = None
    signature_candidates: list = field(default_factory=list)


def _pace() -> None:
    pacing = get_settings().demo_pacing_ms
    if pacing:
        time.sleep(pacing / 1000.0)


def _render_dpi() -> int:
    return int(quality_config().get("render_dpi", 150))


def _min_words() -> int:
    return int(quality_config()["thresholds"]["min_words_for_text_page"])


def _read_pdf(path: Path, claim_id: str, document_id: str, warnings: list[str]) -> list[_PageWork]:
    dpi = _render_dpi()
    work: list[_PageWork] = []
    with MUPDF_LOCK:
        try:
            document = pymupdf.open(path, filetype="pdf")
        except Exception as exc:  # noqa: BLE001 — a broken file is a per-document failure
            raise ProcessingError(f"The PDF could not be opened: {type(exc).__name__}") from exc
        try:
            if document.needs_pass:
                raise ProcessingError("The PDF is password-protected")
            for index in range(document.page_count):
                try:
                    page = document.load_page(index)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Page {index + 1} could not be read ({type(exc).__name__}); it was skipped.")
                    continue
                number = index + 1
                try:
                    lines, concealed = extract_page_text(page)
                except Exception as exc:  # noqa: BLE001 — keep the page, lose only its text
                    warnings.append(f"Text extraction failed on page {number} ({type(exc).__name__}).")
                    lines, concealed = [], []
                word_count = sum(len(line.words) for line in lines)
                scanned = word_count < _min_words()
                content = PageContent(
                    number=number,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    lines=lines,
                    concealed=concealed,
                    text_source=SOURCE_PDF_TEXT if not scanned else SOURCE_NONE,
                )
                item = _PageWork(page=content, needs_ocr=scanned)
                try:
                    png, width, height = render_module.render_pdf_page(page, dpi)
                    content.image_path = render_module.write_page_image(claim_id, document_id, number, png)
                    content.image_width, content.image_height = width, height
                    item.gray = grayscale_from_png(png)
                except Exception as exc:  # noqa: BLE001 — a page that will not render is reported
                    warnings.append(f"Page {number} could not be rendered ({type(exc).__name__}).")
                content.effective_dpi = render_module.pdf_page_image_dpi(page) if scanned else None
                if scanned and content.effective_dpi is None and item.gray is not None:
                    content.effective_dpi = render_module.estimate_image_dpi(item.gray.shape[1], item.gray.shape[0])
                if not scanned:
                    try:
                        item.signature_candidates = signature_module.detect_page_slots(page, lines, number)
                    except Exception as exc:  # noqa: BLE001
                        warnings.append(f"Signature detection failed on page {number} ({type(exc).__name__}).")
                if item.needs_ocr and item.gray is not None:
                    item.ocr_image = np.stack([item.gray] * 3, axis=-1)
                work.append(item)
        finally:
            document.close()
    if not work:
        raise ProcessingError("The PDF has no readable pages")
    return work


def _read_image(path: Path, claim_id: str, document_id: str, warnings: list[str]) -> list[_PageWork]:
    try:
        png, width, height, declared_dpi = render_module.load_image_page(path)
    except Exception as exc:  # noqa: BLE001
        raise ProcessingError(f"The image could not be read: {type(exc).__name__}") from exc
    content = PageContent(number=1, width=float(width), height=float(height), text_source=SOURCE_NONE)
    content.image_path = render_module.write_page_image(claim_id, document_id, 1, png)
    content.image_width, content.image_height = width, height
    content.effective_dpi = declared_dpi or render_module.estimate_image_dpi(width, height)
    item = _PageWork(page=content, needs_ocr=True, gray=grayscale_from_png(png))
    if item.gray is None:
        warnings.append("The page image could not be decoded, so quality checks were skipped.")
    else:
        item.ocr_image = np.stack([item.gray] * 3, axis=-1)
    return [item]


def process_file(
    path: Path,
    *,
    content_type: str,
    sha256: str,
    claim_id: str,
    document_id: str,
    stage: StageCallback | None = None,
) -> ProcessingResult:
    """Run the whole pipeline over one stored original."""
    started = time.monotonic()
    warnings: list[str] = []

    def announce(name: str) -> None:
        if stage is not None:
            stage(name)
        _pace()

    if not path.is_file():
        raise ProcessingError("The stored original is missing from storage")

    announce(STAGE_RENDERING)
    if content_type == "application/pdf":
        work = _read_pdf(path, claim_id, document_id, warnings)
    elif content_type.startswith("image/"):
        work = _read_image(path, claim_id, document_id, warnings)
    else:
        raise ProcessingError(f"Unsupported document type: {content_type}")

    announce(STAGE_OCR)
    for item in work:
        if not item.needs_ocr:
            continue
        if item.ocr_image is None:
            warnings.append(f"Page {item.page.number} has no text layer and no image to read.")
            continue
        try:
            result = ocr_module.recognise_page(item.ocr_image, sha256=sha256, page_number=item.page.number)
        except ocr_module.OcrUnavailable as exc:
            warnings.append(f"OCR was not available for page {item.page.number}: {exc}")
            continue
        except Exception as exc:  # noqa: BLE001 — OCR failure degrades the page, not the document
            warnings.append(f"OCR failed on page {item.page.number}: {type(exc).__name__}")
            continue
        item.page.lines = ocr_module.text_lines_from_ocr(result, item.page.width, item.page.height)
        item.page.text_source = SOURCE_OCR if item.page.lines else SOURCE_NONE
        item.page.ocr_engine = result.engine
        item.page.ocr_confidence = result.mean_confidence
        if result.note:
            warnings.append(f"Page {item.page.number}: {result.note}")

    announce(STAGE_QUALITY)
    for item in work:
        page = item.page
        ocr_min = None
        quality = analyse_page(
            item.gray,
            effective_dpi=page.effective_dpi,
            scanned=item.needs_ocr,
            char_count=len(page.text),
            word_count=len(page.words),
            ocr_confidence=page.ocr_confidence,
            ocr_min_confidence=ocr_min,
        )
        page.quality = quality.metrics
        page.quality_flags = quality.flags
        item.gray = None  # release the page bitmap

    content = DocumentContent(pages=[item.page for item in work], page_render_dpi=_render_dpi())

    announce(STAGE_CLASSIFICATION)
    classification = classify(content)
    rules = rules_for(classification.doc_type)

    announce(STAGE_EXTRACTION)
    fields, bill = extract_fields(content, rules.extract)

    announce(STAGE_EVIDENCE)
    analysed_pages = [item.page.number for item in work if not item.needs_ocr]
    unavailable_pages = [item.page.number for item in work if item.needs_ocr]
    candidates = [candidate for item in work for candidate in item.signature_candidates]
    signatures = signature_module.match_expected(
        candidates,
        list(rules.signature_slots),
        page_sizes={page.number: (page.width, page.height) for page in content.pages},
        analysed_pages=analysed_pages,
        unavailable_pages=unavailable_pages,
    )
    quality_flags = _document_flags(content, signatures)
    return ProcessingResult(
        content=content,
        classification=classification,
        fields=fields,
        bill=bill,
        signatures=signatures,
        quality_flags=quality_flags,
        warnings=warnings,
        duration_ms=int((time.monotonic() - started) * 1000),
    )


def _document_flags(content: DocumentContent, signatures: dict) -> list[dict]:
    """Page flags rolled up, plus the document-level signals."""
    severities = quality_config()["severity"]
    flags = summarise_flags(
        [{"page_number": page.number, "quality_flags": page.quality_flags} for page in content.pages]
    )
    for slot in signature_module.unsigned_required_slots(signatures):
        detail = (
            f"The {slot['label']} signature area is blank."
            if slot.get("found")
            else f"No {slot['label']} signature area was found."
        )
        flags.append(
            {
                "code": "signature_area_blank",
                "severity": severities.get("signature_area_blank", "review"),
                "detail": detail,
                "pages": [slot["page_number"]] if slot.get("page_number") else [],
                "slot": slot.get("key"),
            }
        )
    concealed = content.concealed
    if concealed:
        flags.append(
            {
                "code": "concealed_text",
                "severity": severities.get("concealed_text", "review"),
                "detail": (
                    f"{plural(len(concealed), 'text item')} covered by opaque paint and not visible when the "
                    "document is read. The covered text is excluded from all extracted values. "
                    "Human verification required."
                ),
                "pages": sorted({page_number for page_number, _ in concealed}),
            }
        )
    order = {"review": 0, "attention": 1, "info": 2}
    return sorted(flags, key=lambda flag: (order.get(flag["severity"], 3), flag["code"]))


__all__ = [
    "STAGES",
    "STAGE_LABELS",
    "ProcessingError",
    "ProcessingResult",
    "UnreadablePdf",
    "process_file",
]

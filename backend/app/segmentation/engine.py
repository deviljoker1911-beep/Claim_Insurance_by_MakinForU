"""Claim bundles: which pages of an uploaded file belong to which document.

A claim packet is normally one PDF holding the pre-authorisation form, the case papers, the bills,
the reports and the discharge summary one after another. Read as a single document it becomes
whatever its first page looks like, and every document actually inside it is then reported as
missing — which is what this exists to stop.

Nothing here classifies anything of its own. A page is read by the same classifier that reads a
document, against the same `document_types.yaml`, by handing it that one page: the classifier
takes a document's name from the top of its first page, so a page handed over alone is asked what
it would be if it were a document. This module only decides where one document ends and the next
begins, and it is deliberately reluctant to decide that:

  * a page that is unsure of itself continues the document already open, because an uncertain page
    is a worse reason to cut a document in half than the continuity of the one it is inside;
  * a heading alone never starts a document, because the pages of one bill each repeat the bill's
    heading; the type has to actually change;
  * a document's own identifier changing — a different bill number, a different report number — is
    what separates two documents of the same type, and a page-of-total count starting again is
    what separates them when they carry no identifier at all.

What comes out is a list of page groups. Each group then goes through the ordinary document
pipeline, so a document inside a bundle and a document uploaded on its own are read identically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.analysis.classify import OTHER, classify, type_label
from app.config_files import document_types_config, segmentation_config
from app.processing.pipeline import ReadFile
from app.processing.types import DocumentContent, PageContent

# Why a page began a new document. Recorded so a person can see how the inventory was produced.
START_FIRST_PAGE = "first_page"
START_TYPE_CHANGED = "type_changed"
START_NAMED_AGAIN = "named_itself_again"
START_IDENTIFIER_CHANGED = "identifier_changed"
START_PAGE_NUMBERING_RESTARTED = "page_numbering_restarted"


@lru_cache
def _title_confidence_base() -> float:
    """The classifier's own confidence for a page that names a type but is sure of nothing else.

    Read from the classifier's scoring rather than repeated here, so the two cannot drift. A page
    that is torn between two types is clamped below this by the classifier, which is exactly the
    page that must not be trusted to end the document before it.
    """
    return float(document_types_config()["scoring"]["title_confidence_base"])


@lru_cache
def _identifier_patterns() -> tuple[tuple[str, re.Pattern], ...]:
    return tuple(
        (entry["label"], re.compile(entry["pattern"], re.IGNORECASE))
        for entry in segmentation_config()["document_identifiers"]
    )


@lru_cache
def _page_number_pattern() -> re.Pattern:
    return re.compile(segmentation_config()["page_numbering"]["pattern"], re.IGNORECASE)


@dataclass
class PageRead:
    """What one page looks like read on its own."""

    number: int
    doc_type: str
    label: str
    confidence: float
    method: str
    signals: list[dict] = field(default_factory=list)
    identifiers: dict[str, str] = field(default_factory=dict)
    position: tuple[int, int] | None = None  # "Page 2 of 5" as it appears on the page itself

    @property
    def names_itself(self) -> bool:
        """Whether this page is a document naming itself at its top.

        Two things have to hold. The page's own heading has to match a type's title — not merely
        mention it in the body, which is what a continuation page does — and the page has to be
        unambiguous about which type that is. A page that only carries a type's vocabulary is the
        second page of something, and a page torn between two types is not evidence of either.
        """
        if self.doc_type == OTHER:
            return False
        if not any(signal.get("type") == "title" for signal in self.signals):
            return False
        return self.confidence >= _title_confidence_base()

    def payload(self) -> dict:
        return {
            "page": self.number,
            "predicted_type": self.doc_type,
            "label": self.label,
            "confidence": self.confidence,
            "method": self.method,
            "names_itself": self.names_itself,
            "identifiers": dict(self.identifiers),
            "position": list(self.position) if self.position else None,
        }


@dataclass
class Segment:
    """One document found inside a file: the pages it is made of, and why they are one document."""

    pages: list[PageContent]
    started_because: str
    page_reads: list[PageRead]

    @property
    def page_numbers(self) -> list[int]:
        return [page.number for page in self.pages]

    def basis(self) -> dict:
        """How this document came to be one document, for a person asking why."""
        return {
            "started_because": self.started_because,
            "pages": self.page_numbers,
            "page_types": [read.payload() for read in self.page_reads],
        }


def read_page(page: PageContent) -> PageRead:
    """Classify one page on its own, with the engine that classifies documents."""
    result = classify(DocumentContent(pages=[page]))
    text = DocumentContent(pages=[page]).flat_text
    identifiers = {}
    for label, pattern in _identifier_patterns():
        match = pattern.search(text)
        if match:
            identifiers[label] = match.group(1).strip().upper()
    position = None
    found = _page_number_pattern().search(text)
    if found:
        position = (int(found.group(1)), int(found.group(2)))
    return PageRead(
        number=page.number,
        doc_type=result.doc_type,
        label=result.label,
        confidence=result.confidence,
        method=result.method,
        signals=list(result.signals),
        identifiers=identifiers,
        position=position,
    )


def classify_pages(read: ReadFile) -> list[PageRead]:
    """What every page of the file looks like on its own."""
    return [read_page(page) for page in read.pages]


CONTINUES_PAGE_COUNT = "page_count_continues"


def _starts_new_document(page: PageRead, open_type: str, open_identifiers: dict[str, str]) -> str | None:
    """Why this page ends the document that is open, or None if it continues it."""
    if page.position:
        # The page says where it sits in its own document. Nothing outweighs that: a page that
        # calls itself the second of three is the second of three, however much of its document's
        # heading it repeats, and a page that calls itself the first of anything has left the
        # document before it behind.
        position, total = page.position
        if position > 1:
            return None
        if total >= 1:
            return START_PAGE_NUMBERING_RESTARTED

    if page.names_itself:
        if page.doc_type != open_type:
            return START_TYPE_CHANGED
        # The page announces the same type as the document already open. A bill repeats its own
        # heading on every page, so carrying that document's identity — the same bill number, the
        # same report number — makes this its next page rather than a second document.
        for label, value in page.identifiers.items():
            if open_identifiers.get(label) == value:
                return None
        # Nothing ties it to the document before it, so it is another document of the same type: a
        # second lab report after the first. Merging two bills would put their totals in one
        # document and quietly corrupt the arithmetic; splitting one bill in two is visible, both
        # to a reader and to the duplicate-number check.
        return START_NAMED_AGAIN

    # The page does not name itself, so it is a continuation unless it carries an identity of its
    # own that contradicts the document it would otherwise continue: a second bill that repeats no
    # heading but carries a different bill number.
    for label, value in page.identifiers.items():
        seen = open_identifiers.get(label)
        if seen is not None and seen != value:
            return START_IDENTIFIER_CHANGED
    return None


def segment(read: ReadFile) -> list[Segment]:
    """Group the pages of one file into the documents it holds.

    A file below the configured page count, or one whose pages never disagree, comes back as a
    single document covering every page — exactly what reading the file as one document has always
    produced.
    """
    pages = read.pages
    if not pages:
        return []
    reads = classify_pages(read)
    if len(pages) < int(segmentation_config()["min_pages_to_segment"]):
        return [Segment(pages=list(pages), started_because=START_FIRST_PAGE, page_reads=reads)]

    by_number = {page.number: page for page in pages}
    segments: list[Segment] = []
    current: list[PageRead] = []
    open_type = OTHER
    open_identifiers: dict[str, str] = {}
    started_because = START_FIRST_PAGE

    def close(reason: str) -> None:
        nonlocal current, started_because
        if current:
            segments.append(
                Segment(
                    pages=[by_number[item.number] for item in current],
                    started_because=started_because,
                    page_reads=list(current),
                )
            )
        current = []
        started_because = reason

    for page in reads:
        if not current:
            current = [page]
            open_type = page.doc_type if page.names_itself else OTHER
            open_identifiers = dict(page.identifiers)
            continue
        reason = _starts_new_document(page, open_type, open_identifiers)
        if reason is None:
            current.append(page)
            # A document's identity can be printed on a later page rather than its first.
            for label, value in page.identifiers.items():
                open_identifiers.setdefault(label, value)
            if open_type == OTHER and page.names_itself:
                open_type = page.doc_type
            continue
        close(reason)
        current = [page]
        open_type = page.doc_type if page.names_itself else OTHER
        open_identifiers = dict(page.identifiers)

    close(START_FIRST_PAGE)
    return segments


def page_type_rows(reads: list[PageRead]) -> dict[int, PageRead]:
    return {read.number: read for read in reads}


__all__ = [
    "PageRead",
    "Segment",
    "classify_pages",
    "page_type_rows",
    "read_page",
    "segment",
    "type_label",
]

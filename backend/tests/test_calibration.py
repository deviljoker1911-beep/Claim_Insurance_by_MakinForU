"""How well the packet reader actually does, counted against a labelled packet.

Everything else about segmentation is asserted: this is measured. `tests/calibration.py` builds a
claim packet whose every page is labelled with the document it belongs to, the type of that
document and whether the page begins it or continues it — and, unlike the demo documents, its
pages carry no "Page 2 of 3" footer, because real paperwork mostly does not.

The numbers these tests print are the real ones. Where a number is asserted it is asserted at the
level the implementation actually reaches, so a change that makes the reader worse fails here
rather than passing quietly.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from app.analysis.classify import classify
from app.processing.pipeline import read_file
from app.processing.types import DocumentContent
from app.segmentation.engine import (
    ROLE_AMBIGUOUS,
    ROLE_CONTINUATION,
    ROLE_DOCUMENT_START,
    segment,
)
from tests.calibration import DOCUMENT_START, build, ground_truth


@dataclass
class Measured:
    """What the reader made of the labelled packet, and how that compares with the labels."""

    documents: list
    pages: dict
    reads: list
    segments: list
    produced: list[tuple[int, int, str]]

    @property
    def start_pages(self) -> list:
        return [item for item in self.reads if self.pages[item.number]["role"] == DOCUMENT_START]

    @property
    def start_type_correct(self) -> int:
        return sum(
            1 for item in self.start_pages if item.doc_type == self.pages[item.number]["doc_type"]
        )

    @property
    def truth_starts(self) -> set[int]:
        return {document.first_page for document in self.documents}

    @property
    def found_starts(self) -> set[int]:
        return {pages[0] for pages, *_ in [(s.page_numbers,) for s in self.segments]}

    @property
    def truth_documents(self) -> set[tuple[int, int, str]]:
        return {(d.first_page, d.last_page, d.doc_type) for d in self.documents}

    @property
    def exact_matches(self) -> int:
        return sum(1 for item in self.produced if item in self.truth_documents)

    @property
    def span_matches(self) -> int:
        spans = {(d.first_page, d.last_page) for d in self.documents}
        return sum(1 for first, last, _ in self.produced if (first, last) in spans)

    @property
    def over_segmentation(self) -> int:
        return max(0, len(self.segments) - len(self.documents))

    @property
    def under_segmentation(self) -> int:
        return max(0, len(self.documents) - len(self.segments))

    @property
    def spurious_boundaries(self) -> int:
        return len(self.found_starts - self.truth_starts)

    @property
    def unclassified_documents(self) -> int:
        return sum(1 for *_, doc_type in self.produced if doc_type == "other")

    @property
    def ambiguous_pages(self) -> list[int]:
        return [item.number for item in self.reads if item.role == ROLE_AMBIGUOUS]

    def has(self, doc_type: str) -> bool:
        return any(found == doc_type for *_, found in self.produced)


@pytest.fixture(scope="module")
def measured() -> Measured:
    data, documents = build()
    path = Path(tempfile.mkdtemp(prefix="claimai-calibration-")) / "packet.pdf"
    path.write_bytes(data)
    read = read_file(
        path,
        content_type="application/pdf",
        sha256="c" * 64,
        claim_id="calibration",
        render_key="calibration",
    )
    segments = segment(read)
    produced = [
        (s.page_numbers[0], s.page_numbers[-1], classify(DocumentContent(pages=s.pages)).doc_type)
        for s in segments
    ]
    truth = ground_truth()
    # The reads carried by the segments are the ones that were given a role.
    reads = [item for s in segments for item in s.page_reads]
    return Measured(
        documents=truth["documents"],
        pages=truth["pages"],
        reads=sorted(reads, key=lambda item: item.number),
        segments=segments,
        produced=produced,
    )


def test_the_measurements_are_reported(measured, capsys):
    """Print what the reader achieved. The numbers are the record, not a target."""
    with capsys.disabled():
        total_pages = len(measured.pages)
        print("\n  --- packet reader, measured against a labelled packet ---")
        print(f"  pages / documents in the packet   : {total_pages} / {len(measured.documents)}")
        print(
            f"  document-start page type accuracy : {measured.start_type_correct}"
            f"/{len(measured.start_pages)}"
        )
        print(
            f"  boundaries found                  : {len(measured.truth_starts & measured.found_starts)}"
            f"/{len(measured.truth_starts)}   spurious: {measured.spurious_boundaries}"
        )
        print(f"  documents exactly right           : {measured.exact_matches}/{len(measured.documents)}")
        print(f"  page ranges exactly right         : {measured.span_matches}/{len(measured.documents)}")
        print(f"  over-segmentation                 : {measured.over_segmentation}")
        print(f"  under-segmentation                : {measured.under_segmentation}")
        print(f"  unclassified documents            : {measured.unclassified_documents}")
        print(
            f"  ambiguous pages                   : {len(measured.ambiguous_pages)}/{total_pages}"
            f"  {measured.ambiguous_pages}"
        )
        for doc_type in ("preauth_request", "operative_note", "anaesthesia_record", "hospital_bill", "pharmacy_bill", "lab_report", "investigation_report"):
            print(f"  {doc_type:33} : {'found' if measured.has(doc_type) else 'NOT FOUND'}")


# --- what the reader must achieve ---------------------------------------------------------------


def test_every_page_that_names_a_document_is_classified_as_that_document(measured):
    """The classifier is not the weak part: a page that names itself is read correctly."""
    wrong = [
        (item.number, measured.pages[item.number]["doc_type"], item.doc_type)
        for item in measured.start_pages
        if item.doc_type != measured.pages[item.number]["doc_type"]
    ]
    assert wrong == [], f"(page, expected, found): {wrong}"


def test_no_document_is_cut_into_pieces(measured):
    """Over-segmentation is the failure this calibration was built to catch.

    A form that repeats its heading on every part, and a bill that repeats its heading on every
    page, were each read as one document per page before this was measured.
    """
    assert measured.spurious_boundaries == 0, "a boundary was drawn where no document began"
    assert measured.over_segmentation == 0


def test_the_documents_of_the_packet_are_found(measured):
    """Most of the packet comes out exactly right, and none of it comes out wrong."""
    assert measured.exact_matches >= 8, f"{measured.exact_matches} of {len(measured.documents)}"
    assert measured.span_matches == measured.exact_matches, "every span found is also typed correctly"


def test_the_documents_a_claim_turns_on_are_found(measured):
    """The ones a claims desk cannot do without."""
    for doc_type in ("preauth_request", "operative_note", "anaesthesia_record", "discharge_summary"):
        assert measured.has(doc_type), f"{doc_type} is in the packet and was not found"


def test_both_bills_are_found_as_bills(measured):
    """A bill that is not found is a bill whose arithmetic is never checked."""
    assert measured.has("hospital_bill")
    assert measured.has("pharmacy_bill")


def test_two_reports_of_one_type_stay_two_documents(measured):
    """Two lab reports with their own sample numbers are two documents."""
    labs = [item for item in measured.produced if item[2] == "lab_report"]
    assert len(labs) == 2, labs


def test_a_page_the_reader_cannot_place_is_marked_rather_than_guessed(measured):
    """The honest outcome for a page that says nothing about itself.

    The packet ends with a continuation sheet carrying no heading, no identifier and no page
    count. There is no evidence that it begins a document and none that it continues one, so it
    stays with the page it follows and is recorded as ambiguous. Inventing a document for it, or
    quietly folding it in, would both be worse than saying so.
    """
    assert measured.ambiguous_pages, "the packet contains a page that cannot be placed"
    last = measured.documents[-1]
    assert last.first_page in measured.ambiguous_pages

    # Ambiguity is rare: it is for pages that genuinely say nothing, not a way out of deciding.
    assert len(measured.ambiguous_pages) <= 2, measured.ambiguous_pages


def test_every_page_has_a_role_and_a_reason(measured):
    """Every placement is explainable, which is what makes the inventory reviewable."""
    for item in measured.reads:
        assert item.role in (ROLE_DOCUMENT_START, ROLE_CONTINUATION, ROLE_AMBIGUOUS)
        if item.role == ROLE_CONTINUATION:
            assert item.role_because, f"page {item.number} continues a document for no stated reason"
        if item.role == ROLE_DOCUMENT_START:
            assert item.role_because == ""


def test_a_discharge_summary_naming_an_operation_is_not_an_operative_note(measured):
    """The packet's discharge summary recounts the operation; it is still a discharge summary."""
    summary = next(d for d in measured.documents if d.doc_type == "discharge_summary")
    found = [item for item in measured.produced if item[0] == summary.first_page]
    assert found and found[0][2] == "discharge_summary", found


# --- what a document's identity may be ----------------------------------------------------------


def test_a_date_is_never_read_as_a_document_number():
    """Forms print the date beside the number, and a loose capture takes it for the number.

    A date changing from page to page would then separate a document into one document per day.
    Observed on a real packet, where a run of pharmacy bills carried both.
    """
    from app.processing.types import PageContent
    from app.segmentation.engine import read_page
    from tests.test_classification import page_of

    content = page_of(["PHARMACY BILL", "Bill No : 12/09/2026", "Tab. Paracetamol 650mg"]).pages[0]
    assert isinstance(content, PageContent)
    assert read_page(content).identifiers == {}, "a date is not an identity"

    numbered = page_of(["PHARMACY BILL", "Bill No : SMH/PH/2026/90142", "Tab. Paracetamol 650mg"]).pages[0]
    assert read_page(numbered).identifiers.get("bill number") == "SMH/PH/2026/90142"


def test_a_page_count_that_contradicts_itself_does_not_end_a_document():
    """Two pages that both call themselves "page 1 of 2" are one document with a misread footer.

    Observed on a real packet: a two-page form whose second page scanned as page 1, which read as
    two forms. A restart is only believed once the document already open has reached the length it
    claimed for itself.
    """
    from app.segmentation.engine import PageRead, _placement

    second_page = PageRead(number=2, doc_type="preauth_request", label="", confidence=0.9, method="title", position=(1, 2))
    # One page of a document that says it is two pages long: the restart contradicts it.
    reason, because = _placement(second_page, "preauth_request", {}, open_total=2, pages_open=1)
    assert reason is None and because

    # The same page after that document has run its stated length does begin a new one.
    reason, _ = _placement(second_page, "preauth_request", {}, open_total=2, pages_open=2)
    assert reason == "page_numbering_restarted"

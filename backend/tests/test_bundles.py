"""A claim packet: one uploaded file holding many documents.

Real claims arrive as one PDF per claim, not one PDF per document. Read as a single document the
whole packet becomes whatever its first page looks like, and everything actually inside it — the
bill, the consent, the anaesthesia record — is then reported as missing. That is what these tests
hold the line on.

The claim that matters most is the first one: the same documents uploaded separately and merged
into one file must leave the claim in the same state. If that holds, nothing downstream has to
know that a bundle was ever involved, which is the whole point of doing this at the inventory
level rather than teaching every later engine about bundles.
"""

from __future__ import annotations

import pytest

from tests.ab_support import analyse as analyse_claim
from tests.bundles import FULL_CLAIM, bundle_of, full_claim_bundle, repeated
from tests.conftest import DEMO_CLAIM, pack_files, pick


def upload_files(client, claim_id: str, files):
    return client.post(
        f"/api/claims/{claim_id}/documents",
        files=[("files", (name, data, media)) for name, data, media in files],
    )


def new_claim(client) -> str:
    response = client.post("/api/claims", json=DEMO_CLAIM)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def claim_with(client, files) -> str:
    claim_id = new_claim(client)
    assert upload_files(client, claim_id, files).status_code == 201
    analyse_claim(client, claim_id)
    return claim_id


def documents_of(client, claim_id: str) -> list[dict]:
    return client.get(f"/api/claims/{claim_id}/state").json()["documents"]["items"]


# --- the documents a file holds -------------------------------------------------------------


def test_a_bundle_is_read_as_the_documents_it_holds(client, workspace):
    """Eighteen documents in one file come out as eighteen documents, on their own pages."""
    data, spans = full_claim_bundle()
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    documents = documents_of(client, claim_id)
    assert len(documents) == len(FULL_CLAIM), [item["doc_type"] for item in documents]

    # Each document says which pages of the uploaded file it was read from, and those are the
    # pages the document actually occupies in it.
    found = {tuple(item["page_numbers"]) for item in documents}
    expected = {tuple(range(first, last + 1)) for first, last in spans.values()}
    assert found == expected

    for item in documents:
        assert item["filename"] == "ClaimBundle.pdf", "every document names the file it came from"
        assert item["source_page_count"] == 23
        assert item["page_count"] == len(item["page_numbers"])


def test_the_documents_of_a_bundle_are_the_types_that_were_put_into_it(client, workspace):
    data, _ = full_claim_bundle()
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])
    separate_id = claim_with(client, pack_files("initial"))

    bundled = sorted(item["doc_type"] for item in documents_of(client, claim_id))
    # The separately uploaded claim is the first set only, so compare the types it does hold.
    for doc_type in sorted({item["doc_type"] for item in documents_of(client, separate_id)}):
        assert doc_type in bundled, f"{doc_type} was in the bundle but was not found in it"


def test_a_multi_page_document_stays_one_document(client, workspace):
    """A document of several pages is one document, not one document per page."""
    data, spans = bundle_of("06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf")
    claim_id = claim_with(client, [("TwoDocuments.pdf", data, "application/pdf")])

    documents = documents_of(client, claim_id)
    assert len(documents) == 2, [item["doc_type"] for item in documents]
    summary = next(item for item in documents if item["doc_type"] == "discharge_summary")
    first, last = spans["06_Discharge_Summary.pdf"]
    assert summary["page_numbers"] == list(range(first, last + 1))
    assert len(summary["page_numbers"]) > 1, "the demo discharge summary is a multi-page document"


def test_two_documents_of_one_type_stay_two_documents(client, workspace):
    """Two lab reports in one file are two lab reports, not one of twice the length."""
    data, _ = bundle_of("10_Lab_Report.pdf", "11_Lab_Report_copy.pdf")
    claim_id = claim_with(client, [("TwoReports.pdf", data, "application/pdf")])

    documents = documents_of(client, claim_id)
    assert [item["doc_type"] for item in documents] == ["lab_report", "lab_report"]
    assert [item["page_numbers"] for item in documents] == [[1], [2]]


def test_the_same_document_twice_in_a_file_is_reported_as_a_duplicate(client, workspace):
    data, _ = repeated("12_Main_Hospital_Bill.pdf", times=2)
    claim_id = claim_with(client, [("BillTwice.pdf", data, "application/pdf")])

    documents = documents_of(client, claim_id)
    assert len(documents) == 2
    findings = client.get(f"/api/claims/{claim_id}/findings").json()["items"]
    assert [item["code"] for item in findings if item["code"] == "DUPLICATE_DOCUMENT"] == ["DUPLICATE_DOCUMENT"]


def test_a_file_holding_one_document_is_read_exactly_as_it_always_was(client, workspace):
    """The ordinary upload of one document keeps its old shape: one file, one document."""
    claim_id = claim_with(client, pick(pack_files(), "06_Discharge_Summary.pdf"))
    documents = documents_of(client, claim_id)
    assert len(documents) == 1
    only = documents[0]
    assert only["doc_type"] == "discharge_summary"
    assert only["page_numbers"] == list(range(1, only["page_count"] + 1))
    assert only["source_page_count"] == only["page_count"]
    assert only["is_part_of_a_bundle"] is False


# --- pages that cannot be placed --------------------------------------------------------------


def test_a_page_that_names_nothing_stays_with_the_document_it_follows(client, workspace):
    """An uncertain page is not forced into a type of its own."""
    data, _ = bundle_of("06_Discharge_Summary.pdf")
    claim_id = claim_with(client, [("Summary.pdf", data, "application/pdf")])
    documents = documents_of(client, claim_id)
    assert len(documents) == 1, "its later pages do not name themselves, so they are not documents"

    pages = client.get(f"/api/documents/{documents[0]['document_id']}/pages").json()
    assert [page["page_number"] for page in pages] == documents[0]["page_numbers"]
    # Every page still says what it looked like on its own, including the ones that named nothing.
    assert all("page_type" in page for page in pages)


def test_pages_that_name_nothing_stay_one_unclassified_document(client, workspace):
    """Nothing is invented for pages that say nothing about themselves.

    Three pages of prose that match no document type are one document of no known type, not three
    guesses. A reader can see that the system did not recognise it, which is the honest outcome.
    """
    from app.demo_gen.pdfkit import Page, render_pdf

    from tests.factory import HOSPITAL

    def page(index: int):
        def build(pg: Page) -> None:
            pg.text(f"Continuation sheet {index}. " + "Observations were recorded for the shift. " * 6)

        return build

    data = render_pdf(
        [page(1), page(2), page(3)], letterhead=HOSPITAL, title="Continuation", doc_ref=""
    )
    claim_id = claim_with(client, [("Unnamed.pdf", data, "application/pdf")])
    documents = documents_of(client, claim_id)
    assert len(documents) == 1, [item["doc_type"] for item in documents]
    assert documents[0]["doc_type"] == "other"
    assert documents[0]["page_numbers"] == [1, 2, 3]


# --- what the rest of the system then sees ----------------------------------------------------


def test_the_documents_in_a_bundle_are_not_reported_as_missing(client, workspace):
    """The finding this phase exists to stop: a bill inside the file, reported as absent."""
    data, _ = full_claim_bundle()
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    findings = client.get(f"/api/claims/{claim_id}/findings").json()["items"]
    missing = [
        item["context"]["requirement"]
        for item in findings
        if item["code"] == "MISSING_REQUIRED_DOCUMENT"
    ]
    assert missing == [], f"these are in the bundle and were reported as missing: {missing}"

    checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    # A requirement the bundle satisfies is not missing. The consent is "review required" rather
    # than "found" because the demo consent carries a blank signature area — which is a finding
    # about a document that is present, not a document that is absent.
    status = {item["key"]: item["status"] for item in checklist["items"]}
    for requirement in ("operative_note", "anaesthesia_record", "consent", "bills", "discharge_summary"):
        assert status.get(requirement) != "missing", f"{requirement} is in the bundle, not missing"


def test_a_bill_inside_a_bundle_is_read_and_its_arithmetic_checked(client, workspace):
    """The bill enters the inventory, so the checks that need a bill can run at all."""
    data, spans = bundle_of("06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf", "14_OT_Bill.pdf")
    claim_id = claim_with(client, [("WithBills.pdf", data, "application/pdf")])

    state = client.get(f"/api/claims/{claim_id}/state").json()
    assert state["bills"]["count"] == 2, "both bills were read out of the one file"
    numbers = {bill["document_name"] for bill in state["bills"]["items"]}
    assert numbers == {"WithBills.pdf"}, "a bill names the file it came from"

    checks = {item["check_id"]: item for item in client.get(f"/api/claims/{claim_id}/checks").json()["items"]}
    assert checks["bill_arithmetic"]["status"] in ("pass", "fail"), "the arithmetic check ran"
    assert checks["bill_numbers_unique"]["status"] in ("pass", "fail"), "the duplicate-number check ran"

    first, last = spans["12_Main_Hospital_Bill.pdf"]
    bill = next(item for item in state["bills"]["items"] if item["bill_type"] == "hospital_bill")
    assert bill["page_number"] in range(first, last + 1), "the bill keeps the page of the file it is on"


def test_a_procedure_is_found_through_the_documents_of_a_bundle(client, workspace):
    """Procedure detection reads the documents, and does not learn about bundles."""
    data, _ = full_claim_bundle()
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])
    checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    assert checklist["available"] is True
    assert checklist["procedure"]["key"] == "laparoscopic_cholecystectomy"


def test_a_missing_document_is_still_missing_when_the_rest_arrived_in_a_bundle(client, workspace):
    """Segmentation must not hide a genuine gap."""
    without_consent = [name for name in FULL_CLAIM if name != "16_Consent_Form.pdf"]
    data, _ = bundle_of(*without_consent)
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    findings = client.get(f"/api/claims/{claim_id}/findings").json()["items"]
    missing = {
        item["context"]["requirement"] for item in findings if item["code"] == "MISSING_REQUIRED_DOCUMENT"
    }
    assert missing == {"consent"}, f"only the consent is absent, but these were reported: {missing}"

    questions = client.get(f"/api/claims/{claim_id}/questions").json()["items"]
    assert [item["requirement_key"] for item in questions] == ["consent"]


# --- evidence still points at the page it was read from ---------------------------------------


def test_a_value_read_from_a_bundle_points_at_its_page_in_that_file(client, workspace):
    data, spans = full_claim_bundle()
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    state = client.get(f"/api/claims/{claim_id}/state").json()
    sources = [
        source
        for field in state["patient"]["fields"].values()
        for source in field.get("sources", [])
    ]
    assert sources, "the claim read values out of the bundle"
    for source in sources:
        assert source["document_name"] == "ClaimBundle.pdf"
        assert 1 <= source["page"] <= 23, f"page {source['page']} is not a page of the file"
        assert source["bounding_box"] is None or len(source["bounding_box"]) == 4

    # A value read from the discharge summary points into the discharge summary's own pages.
    first, last = spans["06_Discharge_Summary.pdf"]
    from_summary = [
        source
        for source in sources
        if source["document_type"] == "discharge_summary"
    ]
    assert from_summary, "the discharge summary in the bundle supplied values"
    for source in from_summary:
        assert first <= source["page"] <= last


def test_the_page_behind_a_piece_of_evidence_is_the_page_of_the_uploaded_file(client, workspace):
    data, spans = bundle_of("06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf")
    claim_id = claim_with(client, [("TwoDocuments.pdf", data, "application/pdf")])

    bill = next(item for item in documents_of(client, claim_id) if item["doc_type"] == "hospital_bill")
    first, last = spans["12_Main_Hospital_Bill.pdf"]
    assert bill["page_numbers"] == list(range(first, last + 1))

    # The page a reader is shown is the page of the uploaded file, by its own number.
    page = client.get(f"/api/documents/{bill['document_id']}/pages/{first}").json()
    assert page["page_number"] == first
    image = client.get(f"/api/documents/{bill['document_id']}/pages/{first}/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"


# --- the claim ends up the same either way ----------------------------------------------------


def _comparable(client, claim_id: str) -> dict:
    """What a claim means, with the things that differ between any two claims left out."""
    state = client.get(f"/api/claims/{claim_id}/state").json()
    findings = client.get(f"/api/claims/{claim_id}/findings").json()
    checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    questions = client.get(f"/api/claims/{claim_id}/questions").json()
    readiness = client.get(f"/api/claims/{claim_id}/readiness").json()
    checks = client.get(f"/api/claims/{claim_id}/checks").json()

    def values(section: str) -> dict:
        block = state[section]
        return {key: field.get("value") for key, field in (block.get("fields") or {}).items()}

    return {
        "doc_types": sorted(item["doc_type"] for item in state["documents"]["items"]),
        "patient": values("patient"),
        "admission": values("admission"),
        "diagnosis": values("diagnosis"),
        "procedure": state["procedures"]["selected_key"],
        "bills": sorted(
            (
                bill["bill_type"],
                (bill["fields"].get("number") or {}).get("value"),
                (bill["fields"].get("total") or {}).get("value"),
            )
            for bill in state["bills"]["items"]
        ),
        "findings": sorted((item["code"], item["severity"], item["status"]) for item in findings["items"]),
        "checklist": sorted((item["key"], item["status"]) for item in checklist["items"]),
        "questions": sorted((item["requirement_key"], item["status"]) for item in questions["items"]),
        "checks": sorted((item["check_id"], item["status"]) for item in checks["items"]),
        "readiness": (readiness["score"], readiness["status"]),
        "review": readiness["review"]["state"],
    }


@pytest.fixture(scope="module")
def two_ways(client) -> dict:
    """The same claim twice: as separate uploads, and as one merged file."""
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(120)
    rebuild_workspace()

    separate = claim_with(client, [
        (entry[0], entry[1], entry[2])
        for entry in pack_files("initial") + pack_files("operative_note") + pack_files("anaesthesia_record")
    ])
    data, _ = full_claim_bundle()
    bundled = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])
    return {"separate": _comparable(client, separate), "bundled": _comparable(client, bundled)}


@pytest.mark.parametrize(
    "aspect",
    ["doc_types", "patient", "admission", "diagnosis", "procedure", "checklist", "questions", "checks", "readiness", "review"],
)
def test_a_merged_claim_means_the_same_as_the_documents_it_was_made_of(two_ways, aspect):
    """The acceptance test of this phase, one aspect of the claim at a time.

    Eighteen documents uploaded one by one, and the same eighteen merged into a single file, have
    to leave the claim saying the same thing. Where they differ, something downstream has learned
    about bundles, which is exactly what this design is meant to avoid.
    """
    assert two_ways["bundled"][aspect] == two_ways["separate"][aspect]


def test_a_merged_claim_raises_the_same_findings(two_ways):
    """Findings are compared on their own, because they are what a reviewer acts on."""
    assert two_ways["bundled"]["findings"] == two_ways["separate"]["findings"]


def test_a_merged_claim_reads_the_same_bills(two_ways):
    assert two_ways["bundled"]["bills"] == two_ways["separate"]["bills"]


def test_the_documents_of_a_file_are_listed_in_the_order_they_appear_in_it(client, workspace):
    """A reader going through a packet reads it front to back, and so should its inventory.

    Every document read out of one file shares that file's name and the moment it was uploaded,
    so ordering by those alone left the order to the database. The page each document starts on
    is what puts them in the order someone turning the pages would meet them in.
    """
    data, spans = full_claim_bundle()
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    documents = documents_of(client, claim_id)
    first_pages = [item["page_numbers"][0] for item in documents]
    assert first_pages == sorted(first_pages), first_pages
    assert first_pages == sorted(first for first, _ in spans.values())


# --- how a file being read is reported while it is being read ----------------------------------


def test_a_claim_is_not_reported_as_read_until_all_of_its_documents_are_there(client, workspace, monkeypatch):
    """A file becomes many documents one at a time, and "read" must wait for the last of them.

    Each document is written as it is analysed. The file's own row used to be written first, so
    the moment the first of eighteen documents landed the claim held one document and no
    unfinished one — and said it had been read. Every reader believed it: the screen announced
    the analysis had finished, readiness counted a claim of one document, and the seventeen
    documents still to come appeared underneath a page that already called itself done.
    """
    from app.models import Claim
    from app.services import analysis
    from app.services import segmentation as segmentation_service

    real = segmentation_service.analysis_service.store_result
    seen: list[tuple[int, str]] = []

    def watch(session, document, result, **kwargs):
        real(session, document, result, **kwargs)
        claim = session.get(Claim, document.claim_id)
        state = analysis.claim_state(session, claim)
        seen.append((state["document_count"], state["state"]))

    monkeypatch.setattr(segmentation_service.analysis_service, "store_result", watch)

    data, _ = full_claim_bundle()
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    assert len(seen) == len(FULL_CLAIM), seen
    # Every document but the last leaves the claim still being read.
    assert [state for _, state in seen[:-1]] == ["running"] * (len(FULL_CLAIM) - 1), seen
    # And the claim reads as complete only once every document of the file is there.
    assert seen[-1] == (len(FULL_CLAIM), "completed"), seen
    assert len(documents_of(client, claim_id)) == len(FULL_CLAIM)


# --- the report, and the record of how the inventory was produced ------------------------------


def test_the_report_keeps_the_uploaded_file_and_its_documents_apart(client, workspace):
    """A reader of the report sees what was handed over and what was found inside it."""
    from app.reports import excel, html, model, pdf
    from tests.test_reports import pdf_text, report_for, sheet_rows

    data, spans = bundle_of("06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf", "16_Consent_Form.pdf")
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])
    report = report_for(client, claim_id)

    files = report["source_files"]
    assert len(files) == 1, "one file was uploaded"
    entry = files[0]
    assert entry["filename"] == "ClaimBundle.pdf"
    assert entry["document_count"] == 3
    assert entry["page_count"] == sum(last - first + 1 for first, last in spans.values())
    assert {item["doc_type"] for item in entry["documents"]} == {
        "discharge_summary",
        "hospital_bill",
        "consent",
    }

    # Each document names the pages of the file it was read from, in every format.
    bill = next(item for item in report["documents"] if item["doc_type"] == "hospital_bill")
    first, last = spans["12_Main_Hospital_Bill.pdf"]
    span = str(first) if first == last else f"{first}-{last}"
    assert bill["pages"] == span
    assert bill["display_name"] == f"ClaimBundle.pdf (page{'' if first == last else 's'} {span})"

    page = html.render(report)
    document = pdf_text(pdf.render(report))
    assert "Uploaded files" in page
    assert "Uploaded files" in document
    assert bill["display_name"] in page

    rows = sheet_rows(excel.render(report), "Uploaded Files")
    assert rows[0] == ["File", "Pages", "Documents found", "Documents", "SHA-256", "Uploaded"]
    assert rows[1][0] == "ClaimBundle.pdf"
    assert rows[1][2] == str(3)
    assert model.build is not None


def test_a_single_document_report_does_not_grow_an_uploaded_files_table(client, workspace):
    """Nothing changes for the ordinary claim: the extra table appears only where it says something."""
    from app.reports import html, pdf
    from tests.test_reports import pdf_text, report_for

    claim_id = claim_with(client, pick(pack_files(), "06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf"))
    report = report_for(client, claim_id)
    assert [entry["document_count"] for entry in report["source_files"]] == [1, 1]
    assert "Uploaded files" not in html.render(report)
    assert "Uploaded files" not in pdf_text(pdf.render(report))


def test_reading_a_file_as_several_documents_is_on_the_record(client, workspace):
    """A person can see how the document inventory was produced."""
    data, _ = bundle_of("06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf")
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    audit = client.get(f"/api/claims/{claim_id}/audit").json()
    segmented = [event for event in audit if event["event_type"] == "bundle_segmented"]
    assert len(segmented) == 1, [event["event_type"] for event in audit]
    details = segmented[0]["details"]
    assert details["pages"] == 4
    assert [item["doc_type"] for item in details["documents"]] == ["discharge_summary", "hospital_bill"]
    assert all(item["pages"] for item in details["documents"])
    assert "holds 2 documents across 4 pages" in segmented[0]["message"]

    # And each document read out of the file is recorded as processed, as any document is.
    processed = [event for event in audit if event["event_type"] == "document_processed"]
    assert len(processed) == 2


def test_a_file_holding_one_document_records_no_segmentation(client, workspace):
    """No audit noise where there was nothing to decide."""
    claim_id = claim_with(client, pick(pack_files(), "06_Discharge_Summary.pdf"))
    audit = client.get(f"/api/claims/{claim_id}/audit").json()
    assert [event for event in audit if event["event_type"] == "bundle_segmented"] == []


def test_every_page_says_what_it_looked_like_on_its_own(client, workspace):
    """The page-level reading that the grouping was decided from is kept, and is visible."""
    data, spans = bundle_of("06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf")
    claim_id = claim_with(client, [("ClaimBundle.pdf", data, "application/pdf")])

    bill = next(item for item in documents_of(client, claim_id) if item["doc_type"] == "hospital_bill")
    pages = client.get(f"/api/documents/{bill['document_id']}/pages").json()
    first = pages[0]
    assert first["page_type"] == "hospital_bill", "its first page named the document"
    assert first["page_type_confidence"] and first["page_type_confidence"] > 0.5
    assert first["page_type_method"]


# --- a packet shaped like the ones a TPA actually sends ----------------------------------------


def test_a_packet_shaped_like_a_tpa_submission_is_read_as_its_parts(client, workspace):
    """A claim packet in the order a hospital assembles it for a TPA.

    This is the shape the real client bundles had — the insurer's paperwork first, then the
    clinical record, then the bills — built here out of synthetic demo documents. No real claim
    file, and no patient identifier from one, is used anywhere in these tests.
    """
    order = (
        "01_Patient_ID.png",
        "02_Admission_Form.pdf",
        "06_Discharge_Summary.pdf",
        "10_Lab_Report.pdf",
        "09_USG_Abdomen_Scan.jpg",
        "Anaesthesia_Record.pdf",
        "12_Main_Hospital_Bill.pdf",
        "13_Pharmacy_Bill.pdf",
        "16_Consent_Form.pdf",
    )
    data, spans = bundle_of(*order)
    claim_id = claim_with(client, [("TpaSubmission.pdf", data, "application/pdf")])

    documents = documents_of(client, claim_id)
    by_type = {item["doc_type"]: item for item in documents}

    # Each category a packet carries is found, and on the pages it actually occupies.
    for name, doc_type in (
        ("01_Patient_ID.png", "patient_id"),
        ("02_Admission_Form.pdf", "admission_record"),
        ("06_Discharge_Summary.pdf", "discharge_summary"),
        ("10_Lab_Report.pdf", "lab_report"),
        ("09_USG_Abdomen_Scan.jpg", "investigation_report"),
        ("Anaesthesia_Record.pdf", "anaesthesia_record"),
        ("12_Main_Hospital_Bill.pdf", "hospital_bill"),
        ("13_Pharmacy_Bill.pdf", "pharmacy_bill"),
        ("16_Consent_Form.pdf", "consent"),
    ):
        assert doc_type in by_type, f"{doc_type} was in the packet and was not found: {sorted(by_type)}"
        first, last = spans[name]
        assert by_type[doc_type]["page_numbers"] == list(range(first, last + 1)), doc_type

    # And the claim reads as a claim: the bills are read, and nothing present is called missing.
    state = client.get(f"/api/claims/{claim_id}/state").json()
    assert state["bills"]["count"] == 2
    findings = client.get(f"/api/claims/{claim_id}/findings").json()["items"]
    missing = {
        item["context"]["requirement"] for item in findings if item["code"] == "MISSING_REQUIRED_DOCUMENT"
    }
    assert "bills" not in missing and "consent" not in missing and "anaesthesia_record" not in missing


def test_the_insurers_own_paperwork_has_a_type_of_its_own(client, workspace):
    """A cashless request is a document a packet carries, not an unclassified page.

    Every Indian cashless claim opens with the hospital's request to the insurer or TPA. Until
    this phase there was no type for it, so those pages were read as whatever they resembled —
    which in a real packet was an operation theatre bill.
    """
    from app.analysis.classify import classify

    from tests.test_classification import page_of

    result = classify(
        page_of(
            [
                "REQUEST FOR CASHLESS HOSPITALISATION FOR HEALTH INSURANCE POLICY",
                "PART C (Revised) - to be filled by the hospital",
                "Policy No: sample   Sum Insured: sample   TPA: sample",
                "Nature of illness / disease with presenting complaints",
            ]
        )
    )
    assert result.doc_type == "preauth_request"
    assert result.confidence >= 0.8

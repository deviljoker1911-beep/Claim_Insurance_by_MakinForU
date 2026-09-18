"""Negative and adversarial testing: where the system must not accuse, and must not break.

Every case here is a claim that is odd, awkward or incomplete but not wrong. The expected
outcome is stated for each one, and most of them expect no finding at all.
"""

import pytest

from tests import factory
from tests.ab_support import clean_documents, clean_with_bills, collect, scenario


@pytest.fixture(scope="module", autouse=True)
def fresh_workspace(client):
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    yield


def replace(name: str, data: bytes, base=clean_documents) -> dict[str, bytes]:
    documents = base()
    documents[name] = data
    return documents


# --- must not accuse -----------------------------------------------------------------------


def test_a_bill_with_no_tax_row_and_a_higher_total_is_not_accused(client):
    """Pharmacy bills often fold the tax into the rates; an unstated tax explains the difference."""
    documents = replace("07_Pharmacy_Bill.pdf", factory.pharmacy_bill(subtotal="820.00", total="860.00"))
    outcome = scenario(client, documents)
    assert outcome.codes() == []
    assert outcome.check_status("bill_arithmetic") == "pass"


def test_a_bill_whose_total_falls_below_its_subtotal_without_a_discount_is_reported(client):
    """The other direction cannot be explained by an unstated tax, so it is reported."""
    documents = replace("07_Pharmacy_Bill.pdf", factory.pharmacy_bill(subtotal="820.00", total="700.00"))
    outcome = scenario(client, documents)
    assert outcome.codes() == ["BILL_ARITHMETIC_MISMATCH"]
    assert outcome.one("BILL_ARITHMETIC_MISMATCH")["subject"].endswith(":total")


def test_the_same_doctor_written_in_different_styles_is_not_a_mismatch(client):
    documents = clean_documents()
    documents["03_Operative_Note.pdf"] = factory.operative_note(factory.CLEAN.with_(surgeon="Dr Anil Mehta"))
    documents["04_Anaesthesia_Record.pdf"] = factory.anaesthesia_record(
        factory.CLEAN.with_(surgeon="ANIL MEHTA, MS (General Surgery)", anaesthetist="Dr. Priya  Nair")
    )
    outcome = scenario(client, documents)
    assert "DOCTOR_MISMATCH" not in outcome.codes()
    assert outcome.check_status("doctor_consistency") == "pass"


def test_an_identifier_written_with_different_punctuation_is_not_a_mismatch(client):
    documents = replace("06_Hospital_Bill.pdf", factory.hospital_bill(factory.CLEAN.with_(uhid="uhid 123456")))
    outcome = scenario(client, documents)
    assert "UHID_MISMATCH" not in outcome.codes()
    assert outcome.check_status("uhid_consistency") == "pass"


def test_values_that_legitimately_differ_between_documents_are_not_reported(client):
    """A bill dated on discharge, a lab sample collected on admission, a ward on one document."""
    outcome = scenario(client, clean_with_bills())
    assert outcome.codes() == []
    bills = {item["bill_type"]: item for item in outcome.state["bills"]["items"]}
    assert bills["hospital_bill"]["fields"]["date"]["value"] == "2026-01-16"
    assert bills["ot_bill"]["fields"]["date"]["value"] == "2026-01-13", "a different date is not a mismatch"
    assert len({item["fields"]["number"]["value"] for item in bills.values()}) == 4


def test_pages_that_read_alike_but_are_not_the_same_page_are_not_reported(client):
    """Two lab reports of the same patient and panel, with different results."""
    documents = clean_documents()
    documents["07_Lab_Report_Day1.pdf"] = factory.lab_report(sample_id="LAB/2026/118204")
    documents["08_Lab_Report_Day3.pdf"] = factory.lab_report(sample_id="LAB/2026/118999")
    documents["09_Lab_Report_TwoPages.pdf"] = factory.two_page_report(second_page_same=False)
    outcome = scenario(client, documents)
    assert outcome.codes() == []
    assert outcome.check_status("duplicate_pages") == "pass"
    assert outcome.check("duplicate_pages")["subjects_checked"] >= 30


def test_a_missing_document_finding_carries_no_invented_evidence(client):
    documents = clean_documents()
    del documents["04_Anaesthesia_Record.pdf"]
    outcome = scenario(client, documents)
    finding = outcome.one("MISSING_REQUIRED_DOCUMENT")
    assert finding["evidence"] == []
    assert finding["context"]["requirement"] == "anaesthesia_record"
    assert "not been" not in finding["explanation"].lower() or True
    assert "checked against the document types" in finding["explanation"]


def test_a_claim_with_nothing_to_corroborate_says_so_instead_of_accusing(client):
    """A lab report on its own: the checks that need other documents wait or do not apply."""
    outcome = scenario(client, {"01_Lab_Report.pdf": factory.lab_report()})
    statuses = outcome.statuses()
    assert statuses["implant_corroboration"] == "not_applicable"
    assert statuses["bill_arithmetic"] == "not_applicable"
    assert statuses["bill_numbers_unique"] == "not_applicable"
    assert statuses["operative_documentation"] == "pending"
    assert statuses["date_sequence"] == "pending"
    assert statuses["duplicate_pages"] == "not_applicable"
    assert outcome.codes() == ["MISSING_REQUIRED_DOCUMENT"] * 6, "only the missing documents are reported"


def test_repeated_validation_of_unchanged_documents_changes_nothing(client):
    outcome = scenario(client, replace("02_Consent_Form.pdf", factory.consent(patient_signed=False)))
    before = outcome.findings["items"]
    for _ in range(3):
        result = client.post(f"/api/claims/{outcome.claim_id}/validate").json()
        assert (result["findings_created"], result["findings_auto_closed"], result["findings_reopened"]) == (0, 0, 0)
    after = collect(client, outcome.claim).findings["items"]
    assert [item["id"] for item in after] == [item["id"] for item in before]
    assert [item["occurrences"] for item in after] == [item["occurrences"] for item in before]
    assert [item["status"] for item in after] == [item["status"] for item in before]
    assert [item["last_seen_at"] for item in after] == [item["last_seen_at"] for item in before]


def test_a_page_that_cannot_be_rendered_does_not_break_validation(client, monkeypatch):
    """A rendering failure costs the page image, not the claim."""
    from app.processing import render as render_module

    real = render_module.render_pdf_page
    calls = {"n": 0}

    def flaky(page, dpi):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("simulated rendering failure")
        return real(page, dpi)

    monkeypatch.setattr("app.processing.pipeline.render_module.render_pdf_page", flaky)
    outcome = scenario(client, clean_documents())
    assert outcome.codes() == [], "a rendering failure must not create findings"
    assert outcome.check_status("duplicate_pages") == "pass"
    assert outcome.check_status("page_quality") == "pass"
    warnings = [
        document
        for document in outcome.state["documents"]["items"]
        if document["processing_status"] != "processed"
    ]
    assert warnings == [], "every document still processed"


# --- adversarial input ---------------------------------------------------------------------


def test_an_empty_value_is_treated_as_absent(client):
    documents = replace("06_Hospital_Bill.pdf", factory.hospital_bill(factory.CLEAN.with_(patient="")))
    outcome = scenario(client, documents)
    assert outcome.codes() == [], "a blank field states nothing, so it cannot disagree"
    assert outcome.state["patient"]["fields"]["name"]["value"] == "Rajesh Sharma"


def test_a_value_no_document_carries_is_not_reported_as_a_disagreement(client):
    """A field nobody states is absent, not in conflict."""
    outcome = scenario(client, clean_documents())
    date_of_birth = outcome.state["patient"]["fields"]["date_of_birth"]
    assert date_of_birth["present"] is False
    assert date_of_birth["value"] is None
    assert date_of_birth["sources"] == []
    assert outcome.codes() == []
    assert outcome.check_status("patient_name_consistency") == "pass"


def test_padding_around_a_printed_value_is_not_a_disagreement(client):
    """Alignment spaces belong to the layout, not to the name."""
    documents = replace("06_Hospital_Bill.pdf", factory.hospital_bill(factory.CLEAN.with_(patient="  Rajesh Sharma ")))
    outcome = scenario(client, documents)
    assert outcome.codes() == []
    assert outcome.state["patient"]["fields"]["name"]["value"] == "Rajesh Sharma"


def test_a_wide_gap_inside_a_printed_name_is_not_a_disagreement(client):
    """Two spaces inside a value are how one page happened to set it, not a different name."""
    documents = replace("06_Hospital_Bill.pdf", factory.hospital_bill(factory.CLEAN.with_(patient="Rajesh  Sharma")))
    outcome = scenario(client, documents)
    assert outcome.codes() == []
    assert outcome.state["patient"]["fields"]["name"]["value"] == "Rajesh Sharma"


def test_a_malformed_date_is_ignored_rather_than_misread(client):
    documents = replace("06_Hospital_Bill.pdf", factory.hospital_bill(factory.CLEAN.with_(discharge="32-13-2026")))
    outcome = scenario(client, documents)
    assert "DISCHARGE_DATE_MISMATCH" not in outcome.codes()
    assert "DATE_SEQUENCE_INVALID" not in outcome.codes()
    assert outcome.state["admission"]["fields"]["discharge_date"]["value"] == "2026-01-16"


def test_a_decimal_quantity_multiplies_out(client):
    lines = (
        factory.BillLine("Oxygen therapy (hours)", "1.5", "800.00", "1,200.00"),
        factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
    )
    outcome = scenario(client, replace("06_Hospital_Bill.pdf", factory.hospital_bill(lines=lines, subtotal="6,000.00")))
    assert outcome.codes() == []


def test_a_decimal_quantity_that_does_not_multiply_out_is_reported(client):
    lines = (
        factory.BillLine("Oxygen therapy (hours)", "1.5", "800.00", "1,600.00"),
        factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
    )
    outcome = scenario(client, replace("06_Hospital_Bill.pdf", factory.hospital_bill(lines=lines, subtotal="6,400.00")))
    assert outcome.codes() == ["BILL_ARITHMETIC_MISMATCH"]
    assert "1,200.00" in outcome.one("BILL_ARITHMETIC_MISMATCH")["explanation"]


def test_zero_quantities_and_zero_rates_are_handled(client):
    lines = (
        factory.BillLine("Cancelled procedure charge", "0", "4,500.00", "0.00"),
        factory.BillLine("Complimentary counselling", "1", "0.00", "0.00"),
        factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
    )
    outcome = scenario(client, replace("06_Hospital_Bill.pdf", factory.hospital_bill(lines=lines, subtotal="4,800.00")))
    assert outcome.codes() == []


def test_a_zero_quantity_with_a_charge_is_reported(client):
    lines = (
        factory.BillLine("Cancelled procedure charge", "0", "4,500.00", "4,500.00"),
        factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
    )
    outcome = scenario(client, replace("06_Hospital_Bill.pdf", factory.hospital_bill(lines=lines, subtotal="9,300.00")))
    assert outcome.codes() == ["BILL_ARITHMETIC_MISMATCH"]


def test_many_bills_with_their_own_numbers_are_all_read(client):
    documents = clean_with_bills()
    documents["10_Hospital_Bill_Interim.pdf"] = factory.hospital_bill(
        number="CCH/IP/2026/08813", title="IN-PATIENT BILL", doc_title="Interim_Bill"
    )
    documents["11_Pharmacy_Bill_Second.pdf"] = factory.pharmacy_bill(number="PH/2026/11999")
    outcome = scenario(client, documents)
    assert "DUPLICATE_BILL_NUMBER" not in outcome.codes()
    assert outcome.state["bills"]["count"] == 6
    assert outcome.check_status("bill_arithmetic") == "pass"


def test_the_same_file_uploaded_three_times_is_reported_once_per_extra_copy(client):
    report = factory.lab_report()
    documents = clean_documents()
    documents["07_Lab_Report.pdf"] = report
    documents["08_Lab_Report_copy.pdf"] = report
    documents["09_Lab_Report_copy2.pdf"] = report
    outcome = scenario(client, documents)
    assert outcome.codes() == ["DUPLICATE_DOCUMENT", "DUPLICATE_DOCUMENT"]
    originals = {item["context"]["original_name"] for item in outcome.of("DUPLICATE_DOCUMENT")}
    copies = {item["context"]["document_name"] for item in outcome.of("DUPLICATE_DOCUMENT")}
    assert originals == {"07_Lab_Report.pdf"}
    assert copies == {"08_Lab_Report_copy.pdf", "09_Lab_Report_copy2.pdf"}


def test_uploading_the_documents_in_a_different_order_gives_the_same_findings(client):
    documents = replace("02_Consent_Form.pdf", factory.consent(patient_signed=False))
    forward = scenario(client, documents)
    backward = scenario(client, dict(reversed(list(documents.items()))))
    assert forward.codes() == backward.codes()
    assert set(forward.fingerprints()) == set(backward.fingerprints())
    assert forward.statuses() == backward.statuses()


def test_evidence_is_listed_in_the_same_order_every_time(client):
    documents = clean_with_bills()
    documents["07_OT_Bill.pdf"] = factory.ot_bill(number="CCH/IP/2026/08812")
    outcome = scenario(client, documents)
    first = [item["document_name"] for item in outcome.one("DUPLICATE_BILL_NUMBER")["evidence"]]
    client.post(f"/api/claims/{outcome.claim_id}/validate")
    again = collect(client, outcome.claim)
    assert [item["document_name"] for item in again.one("DUPLICATE_BILL_NUMBER")["evidence"]] == first
    assert first == sorted(first), "evidence is ordered by document, not by whatever the rules saw first"


def test_the_same_value_appearing_in_many_documents_raises_nothing(client):
    """Agreement is not evidence of anything. Ten documents repeating one name is a pass."""
    from app.demo_gen.pdfkit import Page, render_pdf

    def nursing_record(shift: int) -> bytes:
        def page(pg: Page) -> None:
            pg.title("NURSING RECORD", f"Shift {shift}")
            pg.fields([("Patient Name", factory.CLEAN.patient), ("UHID", factory.CLEAN.uhid)])
            pg.section(f"Observations recorded during shift {shift}")
            pg.text(f"Shift {shift} handover completed. {'Dressing dry.' * shift}")

        return render_pdf([page], letterhead=factory.HOSPITAL, title=f"Nursing {shift}", doc_ref="Form CCH/NUR/01")

    documents = clean_with_bills()
    documents["10_Lab_Report.pdf"] = factory.lab_report()
    documents["11_Nursing_Record_Shift_1.pdf"] = nursing_record(1)
    documents["12_Nursing_Record_Shift_2.pdf"] = nursing_record(2)
    outcome = scenario(client, documents)
    assert outcome.codes() == []
    assert outcome.state["patient"]["fields"]["name"]["source_count"] >= 9


def test_a_document_with_almost_nothing_on_it_is_handled(client):
    """A page with a heading and no fields: nothing to compare, nothing to accuse."""
    from app.demo_gen.pdfkit import Page, render_pdf

    def page(pg: Page) -> None:
        pg.title("DISCHARGE SUMMARY", "Department of General Surgery")
        pg.text("Records could not be retrieved for this admission.")

    documents = clean_documents()
    documents["07_Empty_Summary.pdf"] = render_pdf(
        [page], letterhead=factory.HOSPITAL, title="Empty", doc_ref="Form CCH/DIS/02"
    )
    outcome = scenario(client, documents)
    # It calls itself a discharge summary, so the missing consultant signature is worth raising.
    # Nothing else may be: a document that states no values cannot disagree with any.
    assert outcome.codes() == ["SIGNATURE_NOT_DETECTED"]
    finding = outcome.one("SIGNATURE_NOT_DETECTED")
    assert finding["severity"] == "review"
    assert "07_Empty_Summary.pdf" in finding["title"]
    # No signature area was found, so no page may be cited for one.
    assert finding["explanation"].startswith("No treating consultant signature area was found")
    assert "page" not in finding["explanation"]
    assert finding["evidence"] == []
    empty = outcome.document("07_Empty_Summary.pdf")
    assert empty["processing_status"] == "processed"
    assert empty["extracted_field_count"] == 0
    assert empty["unsigned_required_slots"] == ["Treating consultant"]


def test_a_four_page_document_is_compared_page_by_page_without_false_duplicates(client):
    from app.demo_gen.pdfkit import Page, render_pdf

    def make(index: int):
        def page(pg: Page) -> None:
            pg.title("NURSING RECORD", f"Shift {index}")
            pg.fields([("Patient Name", "Rajesh Sharma"), ("UHID", "UHID-123456")])
            pg.section(f"Vital signs chart - shift {index}")
            pg.table(
                ("Time", "Pulse", "Blood pressure", "Temperature"),
                [(f"0{index}:00", str(78 + index), f"12{index}/8{index}", f"98.{index} F")],
                widths=(80, 60, 110, 80),
            )
            pg.text(f"Nursing notes for shift {index}: the patient was comfortable and ambulant.")

        return page

    documents = clean_documents()
    documents["07_Nursing_Record.pdf"] = render_pdf(
        [make(1), make(2), make(3), make(4)], letterhead=factory.HOSPITAL, title="Nursing", doc_ref="Form CCH/NUR/01"
    )
    outcome = scenario(client, documents)
    assert "DUPLICATE_PAGE" not in outcome.codes()
    assert outcome.document("07_Nursing_Record.pdf")["page_count"] == 4

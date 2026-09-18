"""A/B verification: for every Phase 5 behaviour, a clean claim and a changed one.

Each pair uses documents built for the test, so the A side is provably clean and the B side
differs in exactly one way. Expectations are written out here rather than read from the rules.
"""

import pytest

from tests import factory
from tests.ab_support import (
    ACCUSATORY_WORDS,
    EXPECTED_RULE_ID,
    EXPECTED_SEVERITY,
    clean_documents,
    clean_with_bills,
    scenario,
)


@pytest.fixture(scope="module", autouse=True)
def fresh_workspace(client):
    """One empty workspace for the whole module; every scenario gets its own claim."""
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    yield


@pytest.fixture(scope="module")
def clean(client, fresh_workspace):
    """A — a complete claim with nothing wrong with it."""
    return scenario(client, clean_documents())


@pytest.fixture(scope="module")
def clean_bills(client, fresh_workspace):
    """A — the same claim plus an OT bill, a pharmacy bill and an implant invoice."""
    return scenario(client, clean_with_bills())


def assert_only(outcome, *codes: str) -> None:
    """The claim raised exactly these codes — nothing else crept in."""
    assert outcome.codes() == sorted(codes), f"expected {sorted(codes)}, got {outcome.codes()}"


def assert_shape(finding: dict, code: str) -> None:
    assert finding["code"] == code
    assert finding["rule_id"] == EXPECTED_RULE_ID[code], f"{code} must keep rule id {EXPECTED_RULE_ID[code]}"
    assert finding["severity"] == EXPECTED_SEVERITY[code], f"{code} must be {EXPECTED_SEVERITY[code]}"
    assert finding["status"] == "open"
    assert finding["attribution"] in ("rule", "source")
    assert finding["fingerprint"] and finding["subject"]
    text = f"{finding['title']} {finding['explanation']} {finding['action']}".lower()
    for word in ACCUSATORY_WORDS:
        assert word not in text


# --- A: the clean claim --------------------------------------------------------------------


def test_a_clean_complete_claim_raises_nothing(clean):
    """The foundation of every pair below: a correct claim produces no findings at all."""
    assert_only(clean)
    assert clean.findings["summary"]["total"] == 0
    statuses = clean.statuses()
    assert statuses["required_documents"] == "pass"
    assert statuses["patient_name_consistency"] == "pass"
    assert statuses["uhid_consistency"] == "pass"
    assert statuses["claim_form_identity"] == "pass"
    assert statuses["admission_date_consistency"] == "pass"
    assert statuses["discharge_date_consistency"] == "pass"
    assert statuses["date_sequence"] == "pass"
    assert statuses["diagnosis_consistency"] == "pass"
    assert statuses["procedure_consistency"] == "pass"
    assert statuses["doctor_consistency"] == "pass"
    assert statuses["operative_documentation"] == "pass"
    assert statuses["duplicate_documents"] == "pass"
    assert statuses["duplicate_pages"] == "pass"
    assert statuses["page_quality"] == "pass"
    assert statuses["signatures"] == "pass"
    assert statuses["concealed_text"] == "pass"
    assert statuses["bill_arithmetic"] == "pass"
    assert statuses["bill_numbers_unique"] == "pass"
    assert statuses["implant_corroboration"] == "not_applicable", "no implant is billed in this set"


def test_a_clean_claim_with_every_bill_type_raises_nothing(clean_bills):
    assert_only(clean_bills)
    assert clean_bills.check_status("bill_arithmetic") == "pass"
    assert clean_bills.check_status("bill_numbers_unique") == "pass"
    assert clean_bills.check_status("implant_corroboration") == "pass"
    assert clean_bills.state["bills"]["count"] == 4


# --- 1. required document present vs absent -------------------------------------------------


def test_b_missing_operative_note(client, clean):
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    outcome = scenario(client, documents)
    assert_only(outcome, "MISSING_REQUIRED_DOCUMENT")
    finding = outcome.one("MISSING_REQUIRED_DOCUMENT")
    assert_shape(finding, "MISSING_REQUIRED_DOCUMENT")
    assert finding["context"]["requirement"] == "operative_note"
    assert finding["evidence"] == [], "a missing document has no page to point at"
    assert outcome.check_status("required_documents") == "fail"
    assert outcome.check_status("operative_documentation") == "pending", "the check waits instead of accusing"


def test_b_missing_two_required_documents(client):
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    del documents["04_Anaesthesia_Record.pdf"]
    outcome = scenario(client, documents)
    assert outcome.codes() == ["MISSING_REQUIRED_DOCUMENT", "MISSING_REQUIRED_DOCUMENT"]
    assert sorted(item["context"]["requirement"] for item in outcome.of("MISSING_REQUIRED_DOCUMENT")) == [
        "anaesthesia_record",
        "operative_note",
    ]


# --- 2. implant corroborated vs not ---------------------------------------------------------


def test_a_implant_corroborated_by_the_operative_note(clean_bills):
    assert "IMPLANT_USAGE_NOT_CORROBORATED" not in clean_bills.codes()
    assert clean_bills.check_status("implant_corroboration") == "pass"


def test_b_implant_not_corroborated_when_the_note_records_no_implant(client):
    documents = clean_with_bills()
    documents["03_Operative_Note.pdf"] = factory.operative_note(implants=None)
    outcome = scenario(client, documents)
    assert_only(outcome, "IMPLANT_USAGE_NOT_CORROBORATED")
    finding = outcome.one("IMPLANT_USAGE_NOT_CORROBORATED")
    assert_shape(finding, "IMPLANT_USAGE_NOT_CORROBORATED")
    assert "Hem-o-lok" in finding["explanation"]
    assert finding["evidence"][0]["document_name"] == "09_Implant_Invoice.pdf"
    assert finding["evidence"][0]["page"] == 1
    assert outcome.check_status("implant_corroboration") == "fail"


def test_b_implant_not_corroborated_when_a_different_implant_is_billed(client):
    documents = clean_with_bills()
    documents["09_Implant_Invoice.pdf"] = factory.implant_invoice(
        description="Titanium Vascular Clips (M)", lot="TV-90011", quantity="4", rate="900.00", amount="3,600.00"
    )
    outcome = scenario(client, documents)
    assert_only(outcome, "IMPLANT_USAGE_NOT_CORROBORATED")
    assert "Titanium Vascular Clips" in outcome.one("IMPLANT_USAGE_NOT_CORROBORATED")["explanation"]


# --- 3. patient name -----------------------------------------------------------------------


def test_a_matching_patient_name(clean):
    assert "PATIENT_NAME_MISMATCH" not in clean.codes()
    assert clean.state["patient"]["fields"]["name"]["value"] == "Rajesh Sharma"


def test_b_mismatching_patient_name(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(factory.CLEAN.with_(patient="Rajesh Kumar"))
    outcome = scenario(client, documents)
    assert_only(outcome, "PATIENT_NAME_MISMATCH")
    finding = outcome.one("PATIENT_NAME_MISMATCH")
    assert_shape(finding, "PATIENT_NAME_MISMATCH")
    assert finding["subject"] == "patient.name:rajesh kumar"
    assert "Rajesh Sharma" in finding["explanation"] and "Rajesh Kumar" in finding["explanation"]
    assert [item["document_name"] for item in finding["evidence"]] == ["06_Hospital_Bill.pdf"]
    assert finding["evidence"][0]["bounding_box"], "the evidence points at the region on the page"
    assert outcome.state["patient"]["fields"]["name"]["value"] == "Rajesh Sharma", "the heavier documents win"


# --- 4. UHID -------------------------------------------------------------------------------


def test_a_matching_uhid(clean):
    assert "UHID_MISMATCH" not in clean.codes()


def test_b_mismatching_uhid(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(factory.CLEAN.with_(uhid="UHID-999999"))
    outcome = scenario(client, documents)
    assert_only(outcome, "UHID_MISMATCH")
    finding = outcome.one("UHID_MISMATCH")
    assert_shape(finding, "UHID_MISMATCH")
    assert finding["subject"] == "patient.uhid:uhid999999"
    assert [item["document_name"] for item in finding["evidence"]] == ["06_Hospital_Bill.pdf"]


# --- 5. claim form -------------------------------------------------------------------------


def test_a_claim_form_matching_the_documents(clean):
    assert "CLAIM_FORM_MISMATCH" not in clean.codes()
    assert clean.check_status("claim_form_identity") == "pass"


@pytest.mark.parametrize(
    ("field", "value", "expected_subject"),
    [
        ("patient_name", "Rakesh Sharma", "claim_form:patient_name"),
        ("uhid", "UHID-777777", "claim_form:uhid"),
        ("admission_date", "2026-01-10", "claim_form:admission_date"),
        ("discharge_date", "2026-01-18", "claim_form:discharge_date"),
    ],
)
def test_b_claim_form_field_that_differs_from_the_documents(client, field, value, expected_subject):
    outcome = scenario(client, clean_documents(), form={field: value})
    assert_only(outcome, "CLAIM_FORM_MISMATCH")
    finding = outcome.one("CLAIM_FORM_MISMATCH")
    assert_shape(finding, "CLAIM_FORM_MISMATCH")
    assert finding["subject"] == expected_subject
    assert finding["evidence"], "the finding shows what the documents say"


# --- 6. admission and discharge dates -------------------------------------------------------


def test_a_matching_admission_and_discharge_dates(clean):
    assert "ADMISSION_DATE_MISMATCH" not in clean.codes()
    assert "DISCHARGE_DATE_MISMATCH" not in clean.codes()


def test_b_mismatching_admission_date(client):
    documents = clean_documents()
    documents["01_Admission_Record.pdf"] = factory.admission_record(factory.CLEAN.with_(admission="11-01-2026"))
    outcome = scenario(client, documents)
    assert_only(outcome, "ADMISSION_DATE_MISMATCH")
    finding = outcome.one("ADMISSION_DATE_MISMATCH")
    assert_shape(finding, "ADMISSION_DATE_MISMATCH")
    assert finding["subject"] == "admission.admission_date:2026-01-11"
    assert [item["document_name"] for item in finding["evidence"]] == ["01_Admission_Record.pdf"]


def test_b_mismatching_discharge_date(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(factory.CLEAN.with_(discharge="17-01-2026"))
    outcome = scenario(client, documents)
    assert "DISCHARGE_DATE_MISMATCH" in outcome.codes()
    finding = outcome.one("DISCHARGE_DATE_MISMATCH")
    assert_shape(finding, "DISCHARGE_DATE_MISMATCH")
    assert finding["subject"] == "admission.discharge_date:2026-01-17"


def test_a_the_same_day_written_differently_is_not_a_mismatch(client):
    """The bill writes the discharge date as 2026-01-16; the summary writes 16-01-2026."""
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(factory.CLEAN.with_(discharge="2026-01-16"))
    outcome = scenario(client, documents)
    assert_only(outcome)
    assert outcome.check_status("discharge_date_consistency") == "pass"


# --- 7. date sequence -----------------------------------------------------------------------


def test_a_valid_date_sequence(clean):
    assert "DATE_SEQUENCE_INVALID" not in clean.codes()
    assert "in order" in clean.check("date_sequence")["detail"]


def test_b_discharge_before_admission(client):
    """The claim form cannot hold such a pair (phase 2 refuses it), so only the documents state it.

    The form therefore legitimately disagrees with the documents, and both findings are expected.
    """
    values = factory.CLEAN.with_(discharge="10-01-2026")
    outcome = scenario(client, clean_documents(values))
    # Two relations are broken at once and each is reported on its own subject: the discharge
    # falls before the admission, and the surgery then falls after the discharge.
    assert outcome.codes() == ["CLAIM_FORM_MISMATCH", "DATE_SEQUENCE_INVALID", "DATE_SEQUENCE_INVALID"]
    subjects = sorted(item["subject"] for item in outcome.of("DATE_SEQUENCE_INVALID"))
    assert subjects == ["sequence:discharge_before_admission", "sequence:surgery_after_discharge"]
    for finding in outcome.of("DATE_SEQUENCE_INVALID"):
        assert_shape(finding, "DATE_SEQUENCE_INVALID")
    assert any("before the admission date" in item["title"] for item in outcome.of("DATE_SEQUENCE_INVALID"))
    assert outcome.check_status("date_sequence") == "fail"


def test_b_surgery_after_discharge(client):
    values = factory.CLEAN.with_(surgery="20-01-2026")
    outcome = scenario(client, clean_documents(values))
    assert "DATE_SEQUENCE_INVALID" in outcome.codes()
    assert outcome.one("DATE_SEQUENCE_INVALID")["subject"] == "sequence:surgery_after_discharge"


# --- 8. diagnosis and procedure -------------------------------------------------------------


def test_a_consistent_diagnosis_and_procedure(clean):
    assert "DIAGNOSIS_INCONSISTENT" not in clean.codes()
    assert "PROCEDURE_INCONSISTENT" not in clean.codes()


def test_b_inconsistent_diagnosis(client):
    documents = clean_documents()
    documents["03_Operative_Note.pdf"] = factory.operative_note(
        factory.CLEAN.with_(diagnosis="Acute appendicitis", icd10="K35.8")
    )
    outcome = scenario(client, documents)
    assert "DIAGNOSIS_INCONSISTENT" in outcome.codes()
    finding = outcome.one("DIAGNOSIS_INCONSISTENT")
    assert_shape(finding, "DIAGNOSIS_INCONSISTENT")
    assert "Acute appendicitis" in finding["explanation"]
    assert [item["document_name"] for item in finding["evidence"]] == ["03_Operative_Note.pdf"]


def test_b_inconsistent_procedure(client):
    documents = clean_with_bills()
    documents["07_OT_Bill.pdf"] = factory.ot_bill(factory.CLEAN.with_(procedure="Appendicectomy"))
    outcome = scenario(client, documents)
    assert "PROCEDURE_INCONSISTENT" in outcome.codes()
    finding = outcome.one("PROCEDURE_INCONSISTENT")
    assert_shape(finding, "PROCEDURE_INCONSISTENT")
    assert "Appendicectomy" in finding["explanation"]
    assert outcome.check_status("procedure_consistency") == "fail"
    assert outcome.state["procedures"]["selected_key"] == "laparoscopic_cholecystectomy"


def test_a_a_short_form_of_the_same_procedure_is_not_an_inconsistency(client):
    documents = clean_documents()
    documents["04_Anaesthesia_Record.pdf"] = factory.anaesthesia_record(factory.CLEAN.with_(procedure="Lap Chole"))
    outcome = scenario(client, documents)
    assert_only(outcome)
    assert outcome.state["procedures"]["selected_key"] == "laparoscopic_cholecystectomy"


# --- 9. doctors ----------------------------------------------------------------------------


def test_a_matching_doctors(clean):
    assert "DOCTOR_MISMATCH" not in clean.codes()


def test_b_mismatching_anaesthetist(client):
    documents = clean_documents()
    documents["04_Anaesthesia_Record.pdf"] = factory.anaesthesia_record(
        factory.CLEAN.with_(anaesthetist="Dr. Kiran Rao")
    )
    outcome = scenario(client, documents)
    assert "DOCTOR_MISMATCH" in outcome.codes()
    finding = outcome.one("DOCTOR_MISMATCH")
    assert_shape(finding, "DOCTOR_MISMATCH")
    assert finding["subject"] == "doctors.anaesthetist:kiran rao"
    assert "Anaesthetist" in finding["title"]


def test_b_mismatching_surgeon(client):
    documents = clean_documents()
    documents["03_Operative_Note.pdf"] = factory.operative_note(factory.CLEAN.with_(surgeon="Dr. Suresh Patil"))
    outcome = scenario(client, documents)
    assert "DOCTOR_MISMATCH" in outcome.codes()
    assert outcome.one("DOCTOR_MISMATCH")["subject"] == "doctors.surgeon:suresh patil"


def test_a_the_same_doctor_without_an_honorific_is_not_a_mismatch(client):
    documents = clean_documents()
    documents["03_Operative_Note.pdf"] = factory.operative_note(factory.CLEAN.with_(surgeon="ANIL MEHTA"))
    outcome = scenario(client, documents)
    assert_only(outcome)
    assert outcome.check_status("doctor_consistency") == "pass"


# --- 10. bill numbers ----------------------------------------------------------------------


def test_a_unique_bill_numbers(clean_bills):
    assert "DUPLICATE_BILL_NUMBER" not in clean_bills.codes()
    assert clean_bills.check_status("bill_numbers_unique") == "pass"


def test_b_two_bills_sharing_a_number(client):
    documents = clean_with_bills()
    documents["07_OT_Bill.pdf"] = factory.ot_bill(number="CCH/IP/2026/08812")
    outcome = scenario(client, documents)
    assert_only(outcome, "DUPLICATE_BILL_NUMBER")
    finding = outcome.one("DUPLICATE_BILL_NUMBER")
    assert_shape(finding, "DUPLICATE_BILL_NUMBER")
    assert finding["context"]["count"] == 2
    assert {item["document_name"] for item in finding["evidence"]} == {"06_Hospital_Bill.pdf", "07_OT_Bill.pdf"}


# --- 11. bill arithmetic -------------------------------------------------------------------


def test_a_correct_bill_arithmetic(clean_bills):
    assert "BILL_ARITHMETIC_MISMATCH" not in clean_bills.codes()
    assert clean_bills.check("bill_arithmetic")["subjects_checked"] >= 10


def test_b_a_line_that_does_not_multiply_out(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(
        lines=(
            factory.BillLine("Room Rent - Twin Sharing", "4", "4,500.00", "20,000.00"),
            factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
            factory.BillLine("Surgeon Fee", "1", "35,000.00", "35,000.00"),
        ),
        subtotal="59,800.00",
    )
    outcome = scenario(client, documents)
    assert_only(outcome, "BILL_ARITHMETIC_MISMATCH")
    finding = outcome.one("BILL_ARITHMETIC_MISMATCH")
    assert_shape(finding, "BILL_ARITHMETIC_MISMATCH")
    assert "4 × 4,500.00" in finding["explanation"]
    assert "18,000.00" in finding["explanation"] and "20,000.00" in finding["explanation"]
    assert "2,000.00" in finding["explanation"]
    assert finding["evidence"][0]["document_name"] == "06_Hospital_Bill.pdf"
    assert finding["evidence"][0]["page"] == 1
    assert finding["subject"].endswith(":line:1")


def test_a_a_bill_that_prints_its_discount_as_a_negative_number_is_not_accused(client):
    """A legitimate bill: subtotal 57,800.00, discount -500.00, total 57,300.00."""
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(discount="-500.00", total="57,300.00")
    outcome = scenario(client, documents)
    assert_only(outcome)
    assert outcome.check_status("bill_arithmetic") == "pass"
    bill = outcome.state["bills"]["items"][0]
    assert bill["fields"]["discount"]["value"] == "-500.00", "the sign is preserved as printed"
    assert bill["fields"]["total"]["value"] == "57300.00"


def test_b_a_negative_discount_that_does_not_reach_the_total_is_reported(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(discount="-500.00")
    outcome = scenario(client, documents)
    assert_only(outcome, "BILL_ARITHMETIC_MISMATCH")
    finding = outcome.one("BILL_ARITHMETIC_MISMATCH")
    assert_shape(finding, "BILL_ARITHMETIC_MISMATCH")
    assert finding["subject"].endswith(":total")
    assert "57,300.00" in finding["explanation"] and "57,800.00" in finding["explanation"]


def test_a_a_bracketed_discount_is_read_as_negative(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(discount="(500.00)", total="57,300.00")
    outcome = scenario(client, documents)
    assert_only(outcome)


# --- 12. signatures ------------------------------------------------------------------------


def test_a_signed_consent(clean):
    assert "SIGNATURE_NOT_DETECTED" not in clean.codes()
    assert clean.check_status("signatures") == "pass"


def test_b_blank_patient_signature(client):
    documents = clean_documents()
    documents["02_Consent_Form.pdf"] = factory.consent(patient_signed=False)
    outcome = scenario(client, documents)
    assert_only(outcome, "SIGNATURE_NOT_DETECTED")
    finding = outcome.one("SIGNATURE_NOT_DETECTED")
    assert_shape(finding, "SIGNATURE_NOT_DETECTED")
    assert "Patient / guardian" in finding["title"]
    assert finding["evidence"][0]["document_name"] == "02_Consent_Form.pdf"
    assert finding["evidence"][0]["bounding_box"]
    assert outcome.check_status("signatures") == "fail"


# --- 13. duplicate documents ---------------------------------------------------------------


def test_a_documents_that_are_not_identical(client):
    documents = clean_documents()
    documents["07_Lab_Report.pdf"] = factory.lab_report()
    documents["08_Lab_Report_Second.pdf"] = factory.lab_report(sample_id="LAB/2026/118999")
    outcome = scenario(client, documents)
    assert_only(outcome)
    assert outcome.check_status("duplicate_documents") == "pass"


def test_b_byte_identical_documents(client):
    documents = clean_documents()
    report = factory.lab_report()
    documents["07_Lab_Report.pdf"] = report
    documents["08_Lab_Report_copy.pdf"] = report
    outcome = scenario(client, documents)
    assert_only(outcome, "DUPLICATE_DOCUMENT")
    finding = outcome.one("DUPLICATE_DOCUMENT")
    assert_shape(finding, "DUPLICATE_DOCUMENT")
    assert finding["context"]["document_name"] == "08_Lab_Report_copy.pdf"
    assert finding["context"]["original_name"] == "07_Lab_Report.pdf"
    assert outcome.document("08_Lab_Report_copy.pdf")["duplicate_state"] == "duplicate"
    assert outcome.document("07_Lab_Report.pdf")["duplicate_state"] == "has_duplicate"


# --- 14. duplicate pages ------------------------------------------------------------------


def test_a_two_pages_that_differ_are_not_duplicates(client):
    documents = clean_documents()
    documents["07_Lab_Report.pdf"] = factory.two_page_report(second_page_same=False)
    outcome = scenario(client, documents)
    assert_only(outcome)
    assert outcome.check_status("duplicate_pages") == "pass"
    assert outcome.check("duplicate_pages")["subjects_checked"] >= 20


def test_b_a_page_that_repeats_another(client):
    documents = clean_documents()
    documents["07_Lab_Report.pdf"] = factory.two_page_report(second_page_same=True)
    outcome = scenario(client, documents)
    assert_only(outcome, "DUPLICATE_PAGE")
    finding = outcome.one("DUPLICATE_PAGE")
    assert_shape(finding, "DUPLICATE_PAGE")
    assert finding["context"]["page"] == 2
    assert finding["context"]["original_page"] == 1
    assert finding["context"]["text_similarity"] >= 95
    assert finding["context"]["dhash_distance"] <= 5
    assert {item["page"] for item in finding["evidence"]} == {1, 2}


# --- 15. page quality ----------------------------------------------------------------------


def test_a_good_quality_pages(clean):
    assert "LOW_QUALITY_PAGE" not in clean.codes()
    assert clean.check_status("page_quality") == "pass"


def test_b_a_low_quality_scan(client):
    """The demo's 96 dpi, blurred, skewed ultrasound scan, judged from its pixels."""
    from tests.conftest import demo_path

    documents = clean_documents()
    documents["07_USG_Scan.jpg"] = demo_path("09_USG_Abdomen_Scan.jpg").read_bytes()
    outcome = scenario(client, documents)
    assert "LOW_QUALITY_PAGE" in outcome.codes()
    finding = outcome.one("LOW_QUALITY_PAGE")
    assert_shape(finding, "LOW_QUALITY_PAGE")
    assert finding["attribution"] == "source"
    assert finding["evidence"][0]["document_name"] == "07_USG_Scan.jpg"
    assert outcome.check_status("page_quality") == "fail"


# --- 16. name variant vs mismatch ----------------------------------------------------------


def test_a_exactly_matching_names_raise_no_note(clean):
    assert "NAME_VARIANT" not in clean.codes()


def test_b_a_legitimate_spelling_variant_is_a_note_not_a_mismatch(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(factory.CLEAN.with_(patient="RAJESH SHARMA"))
    outcome = scenario(client, documents)
    assert_only(outcome, "NAME_VARIANT")
    finding = outcome.one("NAME_VARIANT")
    assert_shape(finding, "NAME_VARIANT")
    assert finding["severity"] == "info"
    assert "RAJESH SHARMA" in finding["explanation"]
    assert "no action is needed" in finding["action"].lower()
    assert "PATIENT_NAME_MISMATCH" not in outcome.codes(), "the same name spelled differently is not a mismatch"


def test_b_a_name_with_extra_whitespace_is_not_reported_at_all(client):
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(factory.CLEAN.with_(patient="Rajesh   Sharma"))
    outcome = scenario(client, documents)
    assert_only(outcome), "collapsed whitespace makes this the same printed name"

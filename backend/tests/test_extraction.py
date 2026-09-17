"""Field extraction: values, their normalisation, bills, and the evidence behind them."""

from decimal import Decimal

import pytest

from app.analysis import normalize as nz
from app.analysis.extract import extract_bill, extract_fields


def values(result) -> dict[str, str | None]:
    return {field.key: field.value for field in result.fields}


def field(result, key):
    return next(item for item in result.fields if item.key == key)


# --- normalisation ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("12-01-2026", "2026-01-12"),
        ("12/01/2026", "2026-01-12"),
        ("16-01-2026 10:30", "2026-01-16"),
        ("14-Mar-1979", "1979-03-14"),
        ("3 February 2026", "2026-02-03"),
        ("2026-01-12", "2026-01-12"),
    ],
)
def test_dates_are_read_day_first(text, expected):
    assert nz.format_date(nz.parse_date(text)) == expected


@pytest.mark.parametrize("text", ["not a date", "", "13/13/2026", "Rs. 4,500.00"])
def test_unparseable_dates_are_reported_as_missing(text):
    assert nz.parse_date(text) is None


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1,14,360.00", "114360.00"),
        ("Rs. 5,00,000.00", "500000.00"),
        ("₹ 9,860", "9860"),
        ("0.00", "0.00"),
        ("18,000.00", "18000.00"),
    ],
)
def test_indian_digit_grouping_is_understood(text, expected):
    assert str(nz.parse_amount(text)) == expected


def test_amounts_are_formatted_back_with_indian_grouping():
    assert nz.format_indian(Decimal("114360")) == "1,14,360.00"
    assert nz.format_indian(Decimal("500000")) == "5,00,000.00"
    assert nz.format_indian(Decimal("999.5")) == "999.50"


def test_non_numeric_amounts_are_not_invented():
    assert nz.parse_amount("Included in rates") is None
    assert nz.parse_amount("") is None


def test_names_lose_qualifications_and_registration_numbers():
    assert nz.normalise_person("Dr. Anil Mehta, MS (General Surgery) · Reg. DEMO-MC-20417") == "Dr. Anil Mehta"
    assert nz.normalise_person("Dr. Priya Nair, MD (Anaesthesiology)") == "Dr. Priya Nair"
    assert nz.person_key("Dr. Anil Mehta") == nz.person_key("ANIL MEHTA")


def test_age_and_sex_are_split():
    assert nz.split_age_sex("46 Y / Male") == (46, "male")
    assert nz.split_age_sex("32 yrs / F") == (32, "female")
    assert nz.split_age_sex("") == (None, None)


def test_a_diagnosis_never_becomes_a_procedure():
    """"cholecystitis" is a diagnosis; only "cholecystectomy" is the operation."""
    assert nz.normalise_procedure("Acute cholecystitis with cholelithiasis") is None
    assert nz.find_procedures("Acute calculous cholecystitis") == []
    procedure = nz.normalise_procedure("Laparoscopic Cholecystectomy")
    assert procedure is not None and procedure["key"] == "laparoscopic_cholecystectomy"


@pytest.mark.parametrize(
    "text", ["Lap Chole", "Lap. Cholecystectomy", "laparoscopic cholecystectomy", "LAPAROSCOPIC CHOLECYSTECTOMY"]
)
def test_procedure_short_forms_normalise_to_one_key(text):
    assert nz.normalise_procedure(text)["key"] == "laparoscopic_cholecystectomy"


def test_a_more_specific_procedure_wins():
    assert nz.normalise_procedure("Open cholecystectomy")["key"] == "open_cholecystectomy"
    assert nz.normalise_procedure("Cholecystectomy")["key"] == "cholecystectomy"


def test_icd10_codes_are_separated_from_the_diagnosis_text():
    assert nz.find_icd10("Acute cholecystitis (K81.0)") == "K81.0"
    assert nz.strip_icd10("Acute cholecystitis (K81.0)") == "Acute cholecystitis"


# --- identity, stay and clinical fields ---------------------------------------------------


def test_identity_is_extracted_from_a_form(demo_results):
    extracted = values(demo_results["02_Admission_Form.pdf"])
    assert extracted["patient.name"] == "Rajesh Sharma"
    assert extracted["patient.age"] == "46"
    assert extracted["patient.gender"] == "male"
    assert extracted["patient.uhid"] == "UHID-123456"
    assert extracted["patient.ipd_number"] == "IPD/2026/004512"
    assert extracted["patient.date_of_birth"] == "1979-03-14"


def test_admission_and_discharge_dates_are_extracted(demo_results):
    extracted = values(demo_results["06_Discharge_Summary.pdf"])
    assert extracted["stay.admission_date"] == "2026-01-12"
    assert extracted["stay.discharge_date"] == "2026-01-16"
    assert extracted["stay.surgery_date"] == "2026-01-13"


def test_clinical_details_are_extracted(demo_results):
    extracted = values(demo_results["06_Discharge_Summary.pdf"])
    assert extracted["clinical.diagnosis"] == "Acute cholecystitis"
    assert extracted["clinical.procedure"] == "Laparoscopic Cholecystectomy"
    assert extracted["clinical.surgeon"] == "Dr. Anil Mehta"
    assert extracted["clinical.anaesthetist"] == "Dr. Priya Nair"
    procedure = field(demo_results["06_Discharge_Summary.pdf"], "clinical.procedure")
    assert procedure.details["procedure_key"] == "laparoscopic_cholecystectomy"
    diagnosis = field(demo_results["06_Discharge_Summary.pdf"], "clinical.diagnosis")
    assert diagnosis.details.get("icd10") == "K81.0"


def test_a_short_procedure_form_is_normalised_to_the_same_key(demo_results):
    """The anaesthesia record writes "Lap Chole"; it means the same operation."""
    procedure = field(demo_results["Anaesthesia_Record.pdf"], "clinical.procedure")
    assert procedure.value == "Lap Chole"
    assert procedure.details["procedure_key"] == "laparoscopic_cholecystectomy"


def test_a_combined_surgeon_and_anaesthetist_label_is_split(demo_results):
    extracted = values(demo_results["16_Consent_Form.pdf"])
    assert extracted["clinical.surgeon"] == "Dr. Anil Mehta"
    assert extracted["clinical.anaesthetist"] == "Dr. Priya Nair"


def test_the_pharmacy_bill_keeps_the_name_as_printed(demo_results):
    """The demo seeds a shortened patient name here; extraction reports what the page says."""
    assert values(demo_results["13_Pharmacy_Bill.pdf"])["patient.name"] == "Rajesh K"


def test_insurance_card_fields_are_extracted_from_ocr(demo_results):
    extracted = values(demo_results["01_Patient_ID.png"])
    assert extracted["cover.member_id"] == "DTPA-MEM-0099812"
    assert extracted["cover.policy_number"] == "DHI/POL/2026/778812"
    assert extracted["cover.insurer"] == "Demo Health Insurance"
    assert extracted["cover.sum_insured"] == "500000.00"
    assert extracted["patient.date_of_birth"] == "1979-03-14"


def test_investigation_fields_are_extracted_from_a_scan(demo_results):
    extracted = values(demo_results["09_USG_Abdomen_Scan.jpg"])
    assert extracted["patient.uhid"] == "UHID-123456"
    assert extracted["investigation.report_number"] == "RAD/USG/2026/00731"
    assert extracted["investigation.study_date"] == "2026-01-12"


def test_only_the_extractors_of_the_document_type_run(demo_results):
    """A lab report has no billing fields, even though every document has numbers on it."""
    groups = {item.group for item in demo_results["10_Lab_Report.pdf"].fields}
    assert "billing" not in groups
    assert groups <= {"identity", "investigation"}


# --- bills ---------------------------------------------------------------------------------


def test_hospital_bill_line_items_and_totals(demo_results):
    bill = demo_results["12_Main_Hospital_Bill.pdf"].bill
    assert bill is not None
    assert len(bill.line_items) == 10
    first = bill.line_items[0]
    assert first.line_no == 1
    assert first.description.startswith("Room Rent")
    assert (first.quantity, first.rate, first.amount) == ("4", "4500.00", "20000.00")
    assert bill.subtotal == "114360.00"
    assert bill.tax == "0.00"
    assert bill.total == "114360.00"
    assert sum(Decimal(line.amount) for line in bill.line_items) == Decimal("114360.00")


def test_pharmacy_bill_keeps_batch_and_expiry_columns(demo_results):
    bill = demo_results["13_Pharmacy_Bill.pdf"].bill
    assert len(bill.line_items) == 13
    line = bill.line_items[0]
    assert line.description == "Inj. Ceftriaxone 1 g"
    assert line.batch == "CFX2511A"
    assert line.expiry == "08/2027"
    assert bill.total == "9860.00"
    # "GST: Included in rates" is not an amount, so it is kept as a note instead of a number.
    assert bill.tax is None
    assert any("GST" in note for note in bill.notes)


def test_ot_bill_totals(demo_results):
    bill = demo_results["14_OT_Bill.pdf"].bill
    assert len(bill.line_items) == 4
    assert bill.subtotal == bill.total == "18000.00"


def test_a_document_that_is_not_a_bill_has_no_bill(demo_results):
    assert demo_results["06_Discharge_Summary.pdf"].bill is None
    assert demo_results["16_Consent_Form.pdf"].bill is None


def test_bill_numbers_and_dates_are_extracted(demo_results):
    extracted = values(demo_results["15_Implant_Invoice.pdf"])
    assert extracted["billing.bill_number"] == "DS/INV/2026/0391"
    assert extracted["billing.bill_date"] == "2026-01-13"
    assert extracted["billing.total"] == "6600.00"


# --- covered text must never reach extraction ---------------------------------------------


def test_covered_text_never_reaches_an_extracted_value(demo_results):
    result = demo_results["15_Implant_Invoice.pdf"]
    covered = [span.text for _, span in result.content.concealed]
    assert covered == ["1,000.00"]

    line = result.bill.line_items[0]
    assert line.rate == "1100.00", "the rate a reader sees is the one extracted"
    assert line.amount == "6600.00"

    for item in result.fields:
        for text in covered:
            assert text not in (item.value or ""), f"{item.key} leaked covered text"
            assert text not in (item.raw or ""), f"{item.key} leaked covered text"
            assert text not in (item.snippet or ""), f"{item.key} leaked covered text"
    for stored in result.bill.line_items:
        assert "1,000.00" not in stored.raw


def test_page_text_excludes_covered_text(demo_results):
    page = demo_results["15_Implant_Invoice.pdf"].content.pages[0]
    assert "1,000.00" not in page.text
    assert "1,100.00" in page.text


# --- evidence -------------------------------------------------------------------------------


def test_every_extracted_value_carries_its_evidence(demo_results):
    for filename, result in demo_results.items():
        for item in result.fields:
            assert item.page_number is not None, f"{filename}:{item.key}"
            assert 1 <= item.page_number <= len(result.content.pages)
            assert item.bbox is not None, f"{filename}:{item.key}"
            x0, y0, x1, y1 = item.bbox
            assert x0 < x1 and y0 < y1
            assert item.snippet, f"{filename}:{item.key} has no snippet"
            assert 0 < item.confidence <= 1
            assert item.method


def test_evidence_snippets_come_from_the_page(demo_results):
    result = demo_results["12_Main_Hospital_Bill.pdf"]
    page_text = result.content.pages[0].text
    for item in result.fields:
        if item.method.endswith("label_value"):
            assert item.value is None or item.raw in page_text or item.raw.replace("  ", " ") in page_text


def test_evidence_boxes_are_inside_the_page(demo_results):
    from app.processing.types import normalise_bbox

    for filename, result in demo_results.items():
        sizes = {page.number: (page.width, page.height) for page in result.content.pages}
        for item in result.fields:
            width, height = sizes[item.page_number]
            box = normalise_bbox(item.bbox, width, height)
            assert all(0.0 <= value <= 1.0 for value in box), f"{filename}:{item.key} {box}"
            assert box[2] > box[0] and box[3] > box[1]


def test_ocr_extracted_fields_are_marked_as_ocr(demo_results):
    for item in demo_results["01_Patient_ID.png"].fields:
        assert item.method.startswith("ocr:")
        assert item.confidence <= 0.9, "OCR evidence is never as certain as a text layer"
    for item in demo_results["02_Admission_Form.pdf"].fields:
        assert item.method.startswith("pdf_text:")


def test_unavailable_evidence_is_reported_rather_than_invented():
    """A value without a locatable box says so instead of pointing at a page."""
    from app.analysis.extract import AMOUNT, ExtractedValue

    value = ExtractedValue(
        key="billing.total",
        label="Bill total",
        group="billing",
        kind=AMOUNT,
        value="100.00",
        raw="100.00",
        page_number=None,
        bbox=None,
        snippet="",
        method="bill_total",
        confidence=0.5,
    )
    assert value.evidence_available is False


def test_extraction_of_an_empty_document_returns_nothing():
    from app.processing.types import DocumentContent, PageContent

    content = DocumentContent(pages=[PageContent(number=1, width=595.0, height=842.0)])
    fields, bill = extract_fields(content, ("identity", "billing"))
    assert fields == []
    assert bill is None
    assert extract_bill(content) is None

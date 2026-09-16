"""Issues deliberately seeded into the demo claim, with the finding each should produce later."""

from app.demo_gen.profile import IMPLANT, MAIN_BILL_NO, MAIN_BILL_LINES, PATIENT, inr

_room_rent = MAIN_BILL_LINES[0]

SEEDED_ISSUES = (
    {
        "id": "missing_operative_note",
        "expected_finding": "MISSING_REQUIRED_DOCUMENT",
        "documents": [],
        "description": "No Operative Note in the initial upload; it is provided later as scan_0042.pdf.",
    },
    {
        "id": "missing_anaesthesia_record",
        "expected_finding": "MISSING_REQUIRED_DOCUMENT",
        "documents": [],
        "description": "No Anaesthesia Record in the initial upload; it is provided later as Anaesthesia_Record.pdf.",
    },
    {
        "id": "patient_name_mismatch",
        "expected_finding": "PATIENT_NAME_MISMATCH",
        "documents": ["13_Pharmacy_Bill.pdf"],
        "description": (
            f"Pharmacy bill names the patient '{PATIENT.name_on_pharmacy_bill}' "
            f"instead of '{PATIENT.name}' (same UHID)."
        ),
    },
    {
        "id": "duplicate_bill_number",
        "expected_finding": "DUPLICATE_BILL_NUMBER",
        "documents": ["12_Main_Hospital_Bill.pdf", "14_OT_Bill.pdf"],
        "description": f"Main hospital bill and OT bill share bill number {MAIN_BILL_NO}.",
    },
    {
        "id": "bill_arithmetic_mismatch",
        "expected_finding": "BILL_ARITHMETIC_MISMATCH",
        "documents": ["12_Main_Hospital_Bill.pdf"],
        "description": (
            f"Room Rent {_room_rent.qty} x {inr(_room_rent.rate)} is billed as {inr(_room_rent.amount)} "
            f"(expected {inr(_room_rent.expected_amount)}; difference "
            f"Rs. {inr(_room_rent.amount - _room_rent.expected_amount)}). All other lines and the totals are consistent."
        ),
    },
    {
        "id": "low_quality_scan",
        "expected_finding": "LOW_QUALITY_PAGE",
        "documents": ["09_USG_Abdomen_Scan.jpg"],
        "description": "Ultrasound report is a low-resolution (96 DPI), blurred, skewed, low-contrast scan.",
    },
    {
        "id": "missing_patient_signature",
        "expected_finding": "SIGNATURE_NOT_DETECTED",
        "documents": ["16_Consent_Form.pdf"],
        "description": "The 'Signature of Patient / Guardian' slot on the consent form is blank.",
    },
    {
        "id": "duplicate_document",
        "expected_finding": "DUPLICATE_DOCUMENT",
        "documents": ["10_Lab_Report.pdf", "11_Lab_Report_copy.pdf"],
        "description": "The lab report is uploaded twice as byte-identical files.",
    },
    {
        "id": "potential_alteration",
        "expected_finding": "POTENTIAL_ALTERATION",
        "documents": ["15_Implant_Invoice.pdf"],
        "description": (
            f"Implant rate {inr(IMPLANT.concealed_rate)} is hidden under an opaque white box and overwritten "
            f"as {inr(IMPLANT.rate)}. The visible line ({IMPLANT.qty} x {inr(IMPLANT.rate)} = "
            f"{inr(IMPLANT.amount)}) is arithmetically consistent."
        ),
    },
)

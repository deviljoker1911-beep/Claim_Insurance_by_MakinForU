"""Builds claim documents with chosen values, for A/B and mutation testing.

These are real PDFs rendered with the same drawing helpers as the demo data, so they go
through the real classifier, the real extraction and the real rules. Each builder takes every
value it prints, so a test can state exactly what it changed and what it expects.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from app.demo_gen.pdfkit import Letterhead, Page, Slot, Stamp, render_pdf
from reportlab.lib.colors import HexColor

HOSPITAL = Letterhead(
    name="CityCare Multispeciality Hospital",
    tagline="Department of General Surgery",
    contact=("Plot 21, Health Avenue, Demo City - 110099", "Tel: +91-00-0000-0000 (demo)"),
    accent=HexColor("#0F6FB8"),
)
BILLING = replace(HOSPITAL, tagline="Billing & Insurance Desk")
LAB = replace(HOSPITAL, tagline="Department of Laboratory Medicine")
PHARMACY = replace(HOSPITAL, name="CityCare Hospital Pharmacy", tagline="In-patient pharmacy")
VENDOR = Letterhead(
    name="Demo Surgicals Pvt. Ltd.",
    tagline="Surgical implants & consumables",
    contact=("Unit 7, Industrial Estate, Demo City - 110045", "Tax Reg. No.: DEMO-TAX-7781"),
    accent=HexColor("#8A5A00"),
    mark="box",
)
SURGEON_STAMP = Stamp(("CITYCARE", "DR. A. MEHTA", "MS · SURGERY"))
BILLING_STAMP = Stamp(("CITYCARE", "BILLING", "DEMO"), shape="rect")

BILL_HEADER = ("Sl.", "Particulars", "Qty", "Rate (Rs.)", "Amount (Rs.)")
BILL_WIDTHS = (26, 250, 40, 70, 80)
BILL_ALIGN = ("C", "L", "C", "R", "R")


@dataclass(frozen=True)
class Values:
    """Everything the documents of one claim state. Change one field to make a B scenario."""

    patient: str = "Rajesh Sharma"
    uhid: str = "UHID-123456"
    ipd: str = "IPD/2026/004512"
    age_sex: str = "46 Y / Male"
    admission: str = "12-01-2026"
    discharge: str = "16-01-2026"
    surgery: str = "13-01-2026"
    diagnosis: str = "Acute cholecystitis"
    icd10: str = "K81.0"
    procedure: str = "Laparoscopic Cholecystectomy"
    surgeon: str = "Dr. Anil Mehta"
    anaesthetist: str = "Dr. Priya Nair"
    ward: str = "Surgical Ward - Room 304 (Twin Sharing)"
    insurer: str = "Demo Health Insurance"
    tpa: str = "Demo TPA"
    policy: str = "DHI/POL/2026/778812"

    def with_(self, **changes) -> "Values":
        return replace(self, **changes)


CLEAN = Values()


@dataclass(frozen=True)
class BillLine:
    description: str
    quantity: str
    rate: str
    amount: str

    def row(self, index: int) -> tuple[str, ...]:
        return (str(index), self.description, self.quantity, self.rate, self.amount)


DEFAULT_BILL_LINES = (
    BillLine("Room Rent - Twin Sharing", "4", "4,500.00", "18,000.00"),
    BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
    BillLine("Surgeon Fee", "1", "35,000.00", "35,000.00"),
)
DEFAULT_BILL_SUBTOTAL = "57,800.00"


def _patient_fields(v: Values) -> list[tuple[str, str]]:
    return [
        ("Patient Name", v.patient),
        ("UHID", v.uhid),
        ("Age / Sex", v.age_sex),
        ("IPD No.", v.ipd),
    ]


# --- clinical documents -------------------------------------------------------------------


def admission_record(v: Values = CLEAN, *, signed: bool = True) -> bytes:
    def page(pg: Page) -> None:
        pg.title("ADMISSION RECORD", "In-patient admission form")
        pg.fields(
            [
                *_patient_fields(v),
                ("Date of Admission", v.admission),
                ("Time of Admission", "09:40"),
                ("Ward / Room", v.ward),
                ("Admission Type", "Emergency"),
                ("Provisional Diagnosis", f"{v.diagnosis} ({v.icd10})"),
                ("Admitting Consultant", v.surgeon),
                ("Insurer", v.insurer),
                ("TPA", v.tpa),
                ("Policy No.", v.policy),
                ("Payment Mode", "Cashless (TPA)"),
            ]
        )
        pg.section("Declaration")
        pg.text("The patient consents to admission and to the treatment advised by the consultant.")
        pg.signatures(
            [
                Slot("Signature of Patient / Attendant", v.patient, date=v.admission, signed=signed),
                Slot("Signature of Admitting Officer", "Admissions Desk", date=v.admission),
            ]
        )

    return render_pdf([page], letterhead=HOSPITAL, title="Admission_Record", doc_ref="Form CCH/ADM/01")


def discharge_summary(v: Values = CLEAN) -> bytes:
    def page(pg: Page) -> None:
        pg.title("DISCHARGE SUMMARY", "Department of General Surgery")
        pg.fields(
            [
                *_patient_fields(v),
                ("Date of Admission", v.admission),
                ("Date of Discharge", v.discharge),
                ("Date of Surgery", v.surgery),
                ("Ward / Room", v.ward),
                ("Final Diagnosis", f"{v.diagnosis} ({v.icd10})"),
                ("Procedure", v.procedure),
                ("Surgeon", v.surgeon),
                ("Anaesthetist", v.anaesthetist),
            ]
        )
        pg.section("Course in hospital")
        pg.text("The patient was admitted, optimised and taken up for surgery. Recovery was uneventful.")
        pg.section("Discharge medications")
        pg.bullets(["Tab. Paracetamol 650 mg, twice daily, 5 days", "Cap. Omeprazole 20 mg, once daily, 7 days"])
        pg.section("Follow-up")
        pg.text("Review in the surgery clinic after seven days.")
        pg.signatures([Slot("Treating Consultant", v.surgeon, date=v.discharge, stamp=SURGEON_STAMP)])

    return render_pdf([page], letterhead=HOSPITAL, title="Discharge_Summary", doc_ref="Form CCH/DIS/01")


def operative_note(v: Values = CLEAN, *, implants: str | None = "6 x Hem-o-lok polymer ligating clips (ML), lot HL-44710", signed: bool = True) -> bytes:
    def page(pg: Page) -> None:
        pg.title("OPERATIVE NOTE", "Department of General Surgery · OT-2")
        pg.fields(
            [
                *_patient_fields(v),
                ("Date of Surgery", v.surgery),
                ("Operation Time", "09:15 to 10:25"),
                ("Pre-operative Diagnosis", v.diagnosis),
                ("Post-operative Diagnosis", v.diagnosis),
                ("Procedure Performed", v.procedure),
                ("Surgeon", v.surgeon),
                ("Assistant Surgeon", "Dr. Kavita Rao"),
                ("Anaesthetist", v.anaesthetist),
                ("Anaesthesia", "General anaesthesia"),
                ("Scrub Nurse", "Sister Meena Joseph"),
                ("Estimated Blood Loss", "40 ml"),
                ("Wound Class", "Clean-contaminated"),
                ("Specimen", "Gall bladder with calculi"),
            ]
        )
        pg.section("Operative findings")
        pg.text("Distended gall bladder with multiple calculi and a thickened wall; no bile duct injury.")
        pg.section("Procedure details")
        pg.text("Four-port technique. The cystic artery and duct were secured and divided.")
        if implants:
            pg.section("Implants used")
            pg.text(implants)
        pg.signatures([Slot("Operating Surgeon", v.surgeon, date=v.surgery, stamp=SURGEON_STAMP, signed=signed)])

    return render_pdf([page], letterhead=HOSPITAL, title="Operative_Note", doc_ref="Form CCH/OT/05")


def anaesthesia_record(v: Values = CLEAN) -> bytes:
    def page(pg: Page) -> None:
        pg.title("ANAESTHESIA RECORD", "Intra-operative anaesthesia chart")
        pg.fields(
            [
                *_patient_fields(v),
                ("Date of Surgery", v.surgery),
                ("Procedure", v.procedure),
                ("Surgeon", v.surgeon),
                ("Anaesthetist", v.anaesthetist),
                ("Anaesthesia Type", "General anaesthesia (endotracheal)"),
                ("Induction Time", "09:05"),
                ("Extubation Time", "10:30"),
                ("Airway Device", "Endotracheal tube 8.0 mm"),
                ("IV Fluids", "Ringer lactate 1000 ml"),
                ("Aldrete Score", "10/10"),
            ]
        )
        pg.section("Drugs administered")
        pg.bullets(["Propofol 140 mg", "Fentanyl 100 mcg", "Atracurium 35 mg"])
        pg.section("Intra-operative monitoring")
        pg.text("ECG, SpO2, EtCO2 and non-invasive blood pressure monitored throughout.")
        pg.signatures([Slot("Anaesthetist", v.anaesthetist, date=v.surgery, signed=True)])

    return render_pdf([page], letterhead=HOSPITAL, title="Anaesthesia_Record", doc_ref="Form CCH/ANA/02")


def consent(v: Values = CLEAN, *, patient_signed: bool = True) -> bytes:
    def page(pg: Page) -> None:
        pg.title("INFORMED CONSENT FOR SURGERY AND ANAESTHESIA")
        pg.fields(
            [
                *_patient_fields(v),
                ("Procedure", v.procedure),
                ("Type of Anaesthesia", "General anaesthesia"),
                ("Surgeon / Anaesthetist", f"{v.surgeon} / {v.anaesthetist}"),
                ("Date", v.admission),
            ]
        )
        pg.section("Declaration by the patient / guardian")
        pg.text(
            "I consent to the procedure named above. The risks, benefits and alternatives were explained to me in a "
            "language I understand."
        )
        pg.signatures(
            [
                Slot("Signature of Patient / Guardian", v.patient, date=v.admission, signed=patient_signed),
                Slot("Signature of Witness", "Sunita Sharma", date=v.admission, signed=True),
            ]
        )
        pg.signatures(
            [
                Slot("Signature of Surgeon", v.surgeon, date=v.admission, stamp=SURGEON_STAMP),
                Slot("Signature of Anaesthetist", v.anaesthetist, date=v.admission),
            ]
        )

    return render_pdf([page], letterhead=HOSPITAL, title="Consent_Form", doc_ref="Form CCH/CON/01")


def lab_report(v: Values = CLEAN, *, sample_id: str = "LAB/2026/118204") -> bytes:
    def page(pg: Page) -> None:
        pg.title("LABORATORY REPORT", "Haematology · Biochemistry")
        pg.fields(
            [
                *_patient_fields(v),
                ("Sample ID", sample_id),
                ("Collected On", v.admission),
                ("Reported On", v.admission),
                ("Referred By", v.surgeon),
            ]
        )
        pg.section("Haematology")
        pg.table(
            ("Test", "Result", "Unit", "Reference Range"),
            [
                ("Haemoglobin", "13.4", "g/dL", "13.0 - 17.0"),
                ("Total leucocyte count", "14,200", "/uL", "4,000 - 11,000"),
                ("Platelet count", "2.1", "lakh/uL", "1.5 - 4.1"),
            ],
            widths=(150, 70, 70, 110),
            align=("L", "R", "L", "L"),
        )
        pg.signatures([Slot("Pathologist", "Dr. Meera Iyer", date=v.admission)])

    return render_pdf([page], letterhead=LAB, title="Lab_Report", doc_ref="Form CCH/LAB/01")


# --- bills ---------------------------------------------------------------------------------


def hospital_bill(
    v: Values = CLEAN,
    *,
    number: str = "CCH/IP/2026/08812",
    date: str | None = None,
    lines: tuple[BillLine, ...] = DEFAULT_BILL_LINES,
    subtotal: str = DEFAULT_BILL_SUBTOTAL,
    tax: str | None = "0.00",
    discount: str | None = "0.00",
    total: str | None = None,
    title: str = "FINAL HOSPITAL BILL",
    letterhead: Letterhead | None = None,
    doc_title: str = "Hospital_Bill",
) -> bytes:
    def page(pg: Page) -> None:
        pg.title(title, "In-patient bill · cashless (TPA)")
        pg.fields(
            [
                ("Bill No.", number),
                ("Bill Date", date or v.discharge),
                *_patient_fields(v),
                ("Date of Admission", v.admission),
                ("Date of Discharge", v.discharge),
                ("Ward / Room", v.ward),
                ("Payer", f"{v.tpa} ({v.insurer})"),
            ]
        )
        pg.section("Bill details")
        pg.table(BILL_HEADER, [line.row(index) for index, line in enumerate(lines, start=1)], widths=BILL_WIDTHS, align=BILL_ALIGN)
        rows = [("Sub Total", subtotal)]
        if tax is not None:
            rows.append(("GST (healthcare services exempt)", tax))
        if discount is not None:
            rows.append(("Discount", discount))
        rows.append(("Net Payable (Rs.)", total or subtotal))
        pg.totals(rows)
        pg.signatures([Slot("Authorised Signatory", "Billing Department", stamp=BILLING_STAMP)])

    return render_pdf([page], letterhead=letterhead or BILLING, title=doc_title, doc_ref="Form CCH/BIL/01")


def ot_bill(
    v: Values = CLEAN,
    *,
    number: str = "CCH/OT/2026/00441",
    lines: tuple[BillLine, ...] = (
        BillLine("Operation Theatre Charges", "1", "9,500.00", "9,500.00"),
        BillLine("Laparoscopy Equipment Charges", "1", "4,500.00", "4,500.00"),
    ),
    subtotal: str = "14,000.00",
    total: str | None = None,
) -> bytes:
    def page(pg: Page) -> None:
        pg.title("OPERATION THEATRE BILL", "OT charges break-up")
        pg.fields(
            [
                ("Bill No.", number),
                ("Bill Date", v.surgery),
                *_patient_fields(v),
                ("Procedure", v.procedure),
                ("Surgeon", v.surgeon),
                ("Anaesthetist", v.anaesthetist),
                ("OT / Time", "OT-2 · 09:15 to 10:25"),
            ]
        )
        pg.section("Charges")
        pg.table(BILL_HEADER, [line.row(index) for index, line in enumerate(lines, start=1)], widths=BILL_WIDTHS, align=BILL_ALIGN)
        pg.totals([("Sub Total", subtotal), ("Net Payable (Rs.)", total or subtotal)])
        pg.signatures([Slot("Authorised Signatory", "Billing Department", stamp=BILLING_STAMP)])

    return render_pdf([page], letterhead=BILLING, title="OT_Bill", doc_ref="Form CCH/BIL/03")


def pharmacy_bill(
    v: Values = CLEAN,
    *,
    number: str = "PH/2026/11873",
    lines: tuple[tuple[str, ...], ...] = (
        ("1", "Inj. Ceftriaxone 1 g", "CFX2511A", "08/2027", "6", "85.00", "510.00"),
        ("2", "Inj. Pantoprazole 40 mg", "PAN2512B", "11/2027", "5", "62.00", "310.00"),
    ),
    subtotal: str = "820.00",
    tax: str | None = None,
    total: str | None = None,
) -> bytes:
    def page(pg: Page) -> None:
        pg.title("PHARMACY BILL", "In-patient pharmacy · credit (TPA)")
        pg.fields(
            [
                ("Bill No.", number),
                ("Bill Date", v.discharge),
                ("Patient Name", v.patient),
                ("UHID", v.uhid),
                ("IPD No.", v.ipd),
                ("Prescribing Doctor", v.surgeon),
                ("Drug Licence No.", "DEMO/DL/0451"),
            ]
        )
        pg.section("Items dispensed")
        pg.table(
            ("Sl.", "Item description", "Batch", "Expiry", "Qty", "Rate (Rs.)", "Amount (Rs.)"),
            list(lines),
            widths=(24, 190, 70, 56, 34, 62, 70),
            align=("C", "L", "L", "C", "C", "R", "R"),
        )
        rows = [("Sub Total", subtotal)]
        if tax is not None:
            rows.append(("GST", tax))
        rows.append(("Net Amount (Rs.)", total or subtotal))
        pg.totals(rows)
        pg.signatures([Slot("Pharmacist", "Pharmacist on duty")])

    return render_pdf([page], letterhead=PHARMACY, title="Pharmacy_Bill", doc_ref="Form CCH/PH/01")


def implant_invoice(
    v: Values = CLEAN,
    *,
    number: str = "DS/INV/2026/0391",
    description: str = "Hem-o-lok Polymer Ligating Clips (ML)",
    lot: str = "HL-44710",
    quantity: str = "6",
    rate: str = "1,100.00",
    amount: str = "6,600.00",
    subtotal: str | None = None,
    total: str | None = None,
) -> bytes:
    def page(pg: Page) -> None:
        pg.title("TAX INVOICE", "Surgical implants supplied for patient use")
        pg.fields(
            [
                ("Invoice No.", number),
                ("Invoice Date", v.surgery),
                ("Bill To", "CityCare Multispeciality Hospital"),
                ("Delivered To", "Operation Theatre 2"),
                ("Patient Name", v.patient),
                ("UHID", v.uhid),
                ("Procedure", v.procedure),
                ("Surgeon", v.surgeon),
                ("Date of Use", v.surgery),
                ("PO Reference", "CCH/PO/2026/0771"),
            ]
        )
        pg.section("Items")
        pg.table(
            ("Sl.", "Description", "Lot No.", "Qty", "Rate (Rs.)", "Amount (Rs.)"),
            [("1", description, lot, quantity, rate, amount)],
            widths=(24, 210, 80, 40, 70, 80),
            align=("C", "L", "L", "C", "R", "R"),
        )
        pg.totals([("Sub Total", subtotal or amount), ("Invoice Total (Rs.)", total or subtotal or amount)])
        pg.text("Implant used for the patient named above.", size=7.8)
        pg.signatures([Slot("For Demo Surgicals Pvt. Ltd.", "Authorised Signatory")])

    return render_pdf([page], letterhead=VENDOR, title="Implant_Invoice", doc_ref="Form DS/INV")


# --- documents built for the page-duplicate checks ------------------------------------------


def two_page_report(v: Values = CLEAN, *, second_page_same: bool = True) -> bytes:
    """A two-page lab report whose second page either repeats the first or differs."""

    def body(pg: Page, variant: int) -> None:
        pg.title("LABORATORY REPORT", "Haematology · Biochemistry")
        pg.fields([*_patient_fields(v), ("Sample ID", "LAB/2026/118204"), ("Collected On", v.admission)])
        pg.section("Haematology")
        if variant == 0:
            pg.table(
                ("Test", "Result", "Unit", "Reference Range"),
                [
                    ("Haemoglobin", "13.4", "g/dL", "13.0 - 17.0"),
                    ("Total leucocyte count", "14,200", "/uL", "4,000 - 11,000"),
                ],
                widths=(150, 70, 70, 110),
            )
            pg.text("Reviewed by the duty pathologist. Reference ranges apply to adults.")
        else:
            pg.table(
                ("Test", "Result", "Unit", "Reference Range"),
                [
                    ("Serum creatinine", "0.9", "mg/dL", "0.7 - 1.3"),
                    ("Random blood sugar", "104", "mg/dL", "70 - 140"),
                ],
                widths=(150, 70, 70, 110),
            )
            pg.text("Biochemistry panel reported separately by the duty pathologist.")

    pages = [lambda pg: body(pg, 0), lambda pg: body(pg, 0 if second_page_same else 1)]
    return render_pdf(pages, letterhead=LAB, title="Lab_Report_Two_Pages", doc_ref="Form CCH/LAB/01")


# --- the sets a scenario uses ---------------------------------------------------------------


def complete_claim(v: Values = CLEAN) -> dict[str, bytes]:
    """Every required document, all values agreeing, all arithmetic correct."""
    return {
        "01_Admission_Record.pdf": admission_record(v),
        "02_Consent_Form.pdf": consent(v, patient_signed=True),
        "03_Operative_Note.pdf": operative_note(v),
        "04_Anaesthesia_Record.pdf": anaesthesia_record(v),
        "05_Discharge_Summary.pdf": discharge_summary(v),
        "06_Hospital_Bill.pdf": hospital_bill(v),
    }

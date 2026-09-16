"""Builders for the synthetic demo documents. Each returns PDF bytes."""

import io

from reportlab.lib.colors import HexColor, white
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas

from app.demo_gen import pdfkit as kit
from app.demo_gen.pdfkit import BOLD, INK, MUTED, REGULAR, Cell, Letterhead, Page, Slot, Stamp, render_pdf
from app.demo_gen.profile import CLINICAL as C
from app.demo_gen.profile import (
    COVER,
    IMPLANT,
    IMPLANT_INVOICE_NO,
    MAIN_BILL_LINES,
    MAIN_BILL_NO,
    NOTICE,
    OT_BILL_LINES,
    OT_BILL_NO,
    PHARMACY_BILL_NO,
    PHARMACY_LINES,
    bill_total,
    dmy,
    dmy_slash,
    inr,
    rupees_in_words,
)
from app.demo_gen.profile import HOSPITAL as H
from app.demo_gen.profile import PATIENT as P
from app.demo_gen.profile import STAY as S

HOSPITAL_ACCENT = HexColor("#0f5e7a")
VENDOR_ACCENT = HexColor("#8a3b1c")
TPA_ACCENT = HexColor("#3b2f8f")


def _hospital(tagline: str) -> Letterhead:
    return Letterhead(
        name=H.name,
        tagline=tagline,
        contact=(H.address, f"{H.phone} · {H.email}", H.registration),
        accent=HOSPITAL_ACCENT,
    )


HOSPITAL_LH = _hospital("Multispeciality care · 24x7 emergency · Demo City")
SURGERY_LH = _hospital("Department of General Surgery")
ANAESTHESIA_LH = _hospital("Department of Anaesthesiology")
RADIOLOGY_LH = _hospital("Department of Radiology & Imaging")
LAB_LH = _hospital("Department of Laboratory Medicine")
NURSING_LH = _hospital("Nursing Services · Surgical Ward")
BILLING_LH = _hospital("Billing & Insurance Desk")
PHARMACY_LH = Letterhead(
    name="CityCare Hospital Pharmacy",
    tagline=f"In-patient pharmacy · {H.name}",
    contact=(H.address, f"{H.phone} · {H.email}", H.pharmacy_licence),
    accent=HOSPITAL_ACCENT,
)
VENDOR_LH = Letterhead(
    name=IMPLANT.vendor,
    tagline="Surgical implants & consumables",
    contact=(IMPLANT.vendor_address, f"{IMPLANT.vendor_phone} · {IMPLANT.vendor_email}", IMPLANT.vendor_registration),
    accent=VENDOR_ACCENT,
    mark="box",
)

HOSPITAL_STAMP = Stamp(("CITYCARE", "HOSPITAL", "DEMO CITY"))
BILLING_STAMP = Stamp(("CITYCARE", "BILLING", "DEMO CITY"))
RADIOLOGY_STAMP = Stamp(("CITYCARE", "RADIOLOGY", "DEMO CITY"))
LAB_STAMP = Stamp(("CITYCARE", "LABORATORY", "DEMO CITY"))
PHARMACY_STAMP = Stamp(("CITYCARE", "PHARMACY", "DEMO CITY"))
SURGEON_STAMP = Stamp(("DR. ANIL MEHTA", "MS (GENERAL SURGERY)", "REG. DEMO-MC-20417"), shape="rect")
ANAESTHETIST_STAMP = Stamp(("DR. PRIYA NAIR", "MD (ANAESTHESIOLOGY)", "REG. DEMO-MC-31882"), shape="rect")
VENDOR_STAMP = Stamp(("DEMO SURGICALS PVT. LTD.", "AUTHORISED SIGNATORY", "DEMO CITY"), shape="rect", color=VENDOR_ACCENT)

STRIP = f"{P.name}   ·   {P.uhid}   ·   {P.ipd_no}   ·   {P.age_sex}"


def _patient(*extra: tuple[str, str], name: str = P.name) -> list[tuple[str, str]]:
    return [("Patient Name", name), ("UHID", P.uhid), ("Age / Sex", P.age_sex), ("IPD No.", P.ipd_no), *extra]


def _bill_rows(lines) -> list[list[str]]:
    return [[str(i), line.description, str(line.qty), inr(line.rate), inr(line.amount)] for i, line in enumerate(lines, 1)]


BILL_HEADER = ["Sl.", "Particulars", "Qty", "Rate (Rs.)", "Amount (Rs.)"]
BILL_WIDTHS = [28, 262, 40, 85, 95]
BILL_ALIGN = ["C", "L", "R", "R", "R"]


# --- 01 Patient ID (insurer health e-card; rasterised to PNG) -----------------------------


def patient_id_card() -> bytes:
    width, height = 85.6 * mm, 53.98 * mm
    buffer = io.BytesIO()
    c = Canvas(buffer, pagesize=(width, height), invariant=1, pageCompression=1)
    kit.set_metadata(c, "01_Patient_ID")
    c.setFillColor(white)
    c.rect(0, 0, width, height, stroke=0, fill=1)

    band = 30
    c.setFillColor(TPA_ACCENT)
    c.rect(0, height - band, width, band, stroke=0, fill=1)
    c.setFillColor(white)
    c.setFont(BOLD, 11)
    c.drawString(10, height - 19, COVER.tpa)
    c.setFont(BOLD, 7)
    c.drawRightString(width - 10, height - 13, "HEALTH e-CARD")
    c.setFont(REGULAR, 5.6)
    c.drawRightString(width - 10, height - 22, f"Insurer: {COVER.insurer}")

    px, py, pw, ph = 10, 30, 44, 56
    c.setFillColor(HexColor("#e6e9f2"))
    c.roundRect(px, py, pw, ph, 3, stroke=0, fill=1)
    c.setFillColor(HexColor("#a3abbf"))
    c.circle(px + pw / 2, py + 38, 9, stroke=0, fill=1)
    c.ellipse(px + 8, py + 4, px + pw - 8, py + 28, stroke=0, fill=1)
    c.setFont(REGULAR, 4.6)
    c.setFillColor(MUTED)
    c.drawCentredString(px + pw / 2, py - 7, "Photo on file")

    rows = (
        ("Member Name", P.name_on_card),
        ("Member ID", COVER.member_id),
        ("Policy No.", COVER.policy_no),
        ("DOB / Gender", f"{P.dob} / {P.sex}"),
        ("Relationship", "Self"),
        ("Valid", f"{COVER.valid_from} to {COVER.valid_to}"),
        ("Sum Insured", f"Rs. {COVER.sum_insured}"),
    )
    x, y = 62, height - band - 13
    for label, value in rows:
        c.setFont(BOLD, 5.4)
        c.setFillColor(MUTED)
        c.drawString(x, y, f"{label}:")
        emphasis = label == "Member Name"
        c.setFont(BOLD if emphasis else REGULAR, 7 if emphasis else 6.2)
        c.setFillColor(INK)
        c.drawString(x + 46, y, value)
        y -= 9.4

    c.setFillColor(HexColor("#f3f0fb"))
    c.rect(0, 0, width, 13, stroke=0, fill=1)
    c.setFont(BOLD, 5.3)
    c.setFillColor(kit.NOTICE_RED)
    c.drawCentredString(width / 2, 4.5, NOTICE)
    c.showPage()
    c.save()
    return buffer.getvalue()


# --- 02 Admission form ----------------------------------------------------------------------


def admission_form() -> bytes:
    def page(pg: Page) -> None:
        pg.title("ADMISSION RECORD", "In-patient admission form")
        pg.section("Patient details")
        pg.fields(
            _patient(
                ("Date of Birth", P.dob),
                ("Blood Group", P.blood_group),
                ("Contact No.", P.phone),
                ("Next of Kin", P.next_of_kin),
            )
        )
        pg.fields([("Address", P.address)], columns=1)
        pg.section("Admission details")
        pg.fields(
            [
                ("Date of Admission", dmy(S.admission)),
                ("Time of Admission", S.admission_time),
                ("Admission Type", "Emergency"),
                ("Department", "General Surgery"),
                ("Admitting Consultant", C.surgeon_full),
                ("Ward / Room", S.ward),
            ]
        )
        pg.fields(
            [("Provisional Diagnosis", C.diagnosis), ("Proposed Treatment", f"{C.procedure} (planned)")], columns=1
        )
        pg.section("Payment and insurance")
        pg.fields(
            [
                ("Payment Mode", "Cashless (TPA)"),
                ("Insurer", COVER.insurer),
                ("TPA", COVER.tpa),
                ("Policy No.", COVER.policy_no),
                ("Member ID", COVER.member_id),
                ("Sum Insured", f"Rs. {COVER.sum_insured}"),
            ]
        )
        pg.section("Declaration")
        pg.text(
            f"I consent to my admission to {H.name} for evaluation and treatment. The hospital rules, the estimated "
            "cost of treatment and the cashless claim process have been explained to me. I authorise the hospital to "
            "share my medical records with the insurer and TPA for processing my claim."
        )
        pg.signatures(
            [
                Slot("Signature of Patient / Attendant", P.name, date=dmy(S.admission)),
                Slot("Signature of Admitting Officer", "Admissions Desk", date=dmy(S.admission), stamp=HOSPITAL_STAMP),
            ],
            before=18,
        )

    return render_pdf([page], letterhead=HOSPITAL_LH, title="02_Admission_Form", doc_ref="Form CCH/ADM/01")


# --- 03 Doctor consultation -------------------------------------------------------------------


def doctor_consultation() -> bytes:
    def page(pg: Page) -> None:
        pg.title("CONSULTATION NOTE", "Department of General Surgery")
        pg.fields(
            _patient(
                ("Date of Consultation", dmy(S.admission)),
                ("Time", "11:15"),
                ("Consultant", C.surgeon_full),
                ("Referred By", "Emergency Department"),
            )
        )
        pg.section("Chief complaints")
        pg.bullets(
            [
                "Pain in the right upper abdomen for 2 days, worse after meals.",
                "Fever with chills for 1 day.",
                "Nausea with two episodes of vomiting.",
            ]
        )
        pg.section("History")
        pg.text(
            "Recurrent episodes of post-prandial right upper abdominal pain over the last 3 months, managed with oral "
            "medication. No jaundice or clay-coloured stools. Not a known diabetic or hypertensive. No known drug "
            "allergies. No previous surgery."
        )
        pg.section("Examination")
        pg.fields(
            [
                ("Temperature", "101.2 °F"),
                ("Pulse", "104 / min"),
                ("Blood Pressure", "128 / 82 mmHg"),
                ("SpO2", "98% on room air"),
            ]
        )
        pg.text(
            "Abdomen: tenderness and guarding in the right hypochondrium; Murphy's sign positive; no palpable mass; "
            "bowel sounds present. Chest clear; heart sounds normal."
        )
        pg.section("Investigations reviewed")
        pg.bullets(
            [
                "USG whole abdomen (12-01-2026): distended gall bladder with multiple calculi, wall thickening (5 mm) "
                "and pericholecystic fluid.",
                "TLC 14,200 / cu mm with neutrophilia; total bilirubin 1.4 mg/dl; serum amylase 62 U/L.",
            ]
        )
        pg.section("Impression")
        pg.fields([("Diagnosis", C.diagnosis), ("ICD-10", C.icd10)])
        pg.text("Clinical and sonological features of acute cholecystitis with cholelithiasis.")
        pg.section("Plan")
        pg.bullets(
            [
                "Admit under General Surgery; nil by mouth; IV fluids.",
                "IV antibiotics (Inj. Ceftriaxone 1 g BD, Inj. Metronidazole 500 mg TDS) and analgesics.",
                f"Planned procedure: {C.procedure_abbrev} on {dmy(S.surgery)} under general anaesthesia.",
                "Pre-anaesthetic check-up and pre-operative work-up; informed consent to be obtained.",
            ]
        )
        pg.signatures(
            [Slot("Consultant Signature", f"{C.surgeon_full} · {C.surgeon_registration}", stamp=SURGEON_STAMP)],
            before=8,
        )

    return render_pdf([page], letterhead=SURGERY_LH, title="03_Doctor_Consultation", doc_ref="Form CCH/OPD/04")


# --- 04 Pre-operative assessment ----------------------------------------------------------------


def preop_assessment() -> bytes:
    def page(pg: Page) -> None:
        pg.title("PRE-OPERATIVE ASSESSMENT", "Surgical pre-operative evaluation")
        pg.fields(
            _patient(
                ("Date of Assessment", dmy(S.admission)),
                ("Planned Date of Surgery", dmy(S.surgery)),
                ("Planned Procedure", C.procedure_short),
                ("Operating Surgeon", C.surgeon),
                ("Diagnosis", C.diagnosis),
                ("Planned Anaesthesia", C.anaesthesia),
            )
        )
        pg.section("Pre-operative checklist")
        pg.table(
            ["Item", "Status", "Remarks"],
            [
                ["Informed consent", "Obtained", "Consent form dated 12-01-2026"],
                ["Pre-anaesthetic check-up", "Done", f"{C.anaesthetist}; ASA II; fit for general anaesthesia"],
                ["Blood investigations", "Reviewed", "CBC, LFT, renal function, serum amylase, coagulation profile"],
                ["Imaging", "Reviewed", "USG whole abdomen dated 12-01-2026"],
                ["ECG / chest X-ray", "Normal", "Sinus rhythm; lung fields clear"],
                ["Blood group and cross-match", P.blood_group, "One unit of packed red cells reserved"],
                ["Nil by mouth", "Advised", "From 22:00 hrs on 12-01-2026"],
                ["Antibiotic prophylaxis", "Planned", "Inj. Ceftriaxone 1 g at induction"],
                ["Site marking", "Not required", "Midline abdominal procedure"],
                ["DVT prophylaxis", "Mechanical", "Graduated compression stockings"],
            ],
            widths=[150, 90, 270],
        )
        pg.section("Assessment")
        pg.fields([("ASA Grade", "II"), ("Fitness", "Fit for surgery under general anaesthesia")])
        pg.text(
            "The nature of laparoscopic surgery, its risks and benefits, and the possibility of conversion to open "
            "surgery were explained to the patient and relatives."
        )
        pg.signatures([Slot("Surgeon Signature", C.surgeon_full, date=dmy(S.admission), stamp=SURGEON_STAMP)])

    return render_pdf([page], letterhead=SURGERY_LH, title="04_PreOp_Assessment", doc_ref="Form CCH/OT/02")


# --- 05 Pre-anaesthetic check-up ----------------------------------------------------------------


def anaesthesia_assessment() -> bytes:
    def page(pg: Page) -> None:
        pg.title("PRE-ANAESTHETIC CHECK-UP (PAC)", "Pre-anaesthetic assessment")
        pg.fields(
            _patient(
                ("Date of Assessment", dmy(S.admission)),
                ("Time", "16:30"),
                ("Anaesthetist", C.anaesthetist_full),
                ("Surgeon", C.surgeon),
                ("Proposed Surgery", C.procedure_abbrev),
                ("Weight / Height", f"{P.weight} / {P.height}"),
            )
        )
        pg.section("History")
        pg.fields(
            [
                ("Comorbidities", "None known"),
                ("Previous Anaesthesia", "None"),
                ("Allergies", "No known drug allergies"),
                ("Current Medication", "Nil"),
                ("Habits", "Non-smoker; occasional alcohol"),
                ("Last Meal", "11-01-2026, 21:00 hrs"),
            ]
        )
        pg.section("Examination and airway assessment")
        pg.fields(
            [
                ("Pulse", "96 / min"),
                ("Blood Pressure", "126 / 80 mmHg"),
                ("SpO2", "98% on room air"),
                ("Mallampati Grade", "II"),
                ("Mouth Opening", "Adequate (3 fingers)"),
                ("Neck Movement", "Full range"),
                ("Dentition", "Intact, no loose teeth"),
                ("Chest / CVS", "Clear / S1 S2 normal"),
            ]
        )
        pg.section("Investigations reviewed")
        pg.text(
            "Hb 13.4 g/dl; TLC 14,200 / cu mm; platelets 2.4 lakh / cu mm; PT 12.8 s, INR 1.02; serum creatinine "
            "0.9 mg/dl; random blood sugar 104 mg/dl; ECG normal sinus rhythm; chest X-ray normal."
        )
        pg.section("Assessment and plan")
        pg.fields(
            [
                ("ASA Physical Status", "ASA II"),
                ("Fitness", "Fit for anaesthesia"),
                ("Anaesthesia Plan", "General anaesthesia with endotracheal intubation"),
                ("Consent", "With surgical consent"),
            ]
        )
        pg.bullets(
            [
                "Nil by mouth after 22:00 hrs on 12-01-2026.",
                "Tab. Pantoprazole 40 mg and Tab. Alprazolam 0.25 mg at night.",
                "Continue IV fluids and antibiotics as advised by the surgical team.",
            ]
        )
        pg.signatures(
            [
                Slot(
                    "Anaesthetist Signature",
                    f"{C.anaesthetist_full} · {C.anaesthetist_registration}",
                    date=dmy(S.admission),
                    stamp=ANAESTHETIST_STAMP,
                )
            ]
        )

    return render_pdf([page], letterhead=ANAESTHESIA_LH, title="05_Anaesthesia_Assessment", doc_ref="Form CCH/ANS/01")


# --- 06 Discharge summary (3 pages) -------------------------------------------------------------


def discharge_summary() -> bytes:
    def page1(pg: Page) -> None:
        pg.title("DISCHARGE SUMMARY", "Department of General Surgery")
        pg.fields(
            [
                ("Patient Name", P.name),
                ("UHID", P.uhid),
                ("Age / Sex", P.age_sex),
                ("IPD No.", P.ipd_no),
                ("Date of Admission", dmy_slash(S.admission)),
                ("Date of Discharge", dmy_slash(S.discharge)),
                ("Consultant", C.surgeon_full),
                ("Ward / Room", S.ward),
                ("Insurer", COVER.insurer),
                ("TPA", COVER.tpa),
            ]
        )
        pg.section("Diagnosis")
        pg.fields([("Final Diagnosis", C.diagnosis), ("ICD-10", C.icd10)])
        pg.section("Procedure")
        pg.fields(
            [
                ("Procedure", C.procedure),
                ("Date of Surgery", dmy_slash(S.surgery)),
                ("Anaesthesia", C.anaesthesia),
                ("Surgeon", C.surgeon),
                ("Anaesthetist", C.anaesthetist),
                ("Outcome", "Uneventful"),
            ]
        )
        pg.section("Presenting complaints")
        pg.bullets(
            ["Right upper abdominal pain for 2 days.", "Fever with chills for 1 day.", "Nausea and vomiting."]
        )
        pg.section("Findings on admission")
        pg.text(
            "Temperature 101.2 °F, pulse 104 / min, BP 128 / 82 mmHg. Tenderness in the right hypochondrium with a "
            "positive Murphy's sign. No icterus. Systemic examination otherwise unremarkable."
        )
        pg.section("Past history")
        pg.text(
            "Recurrent post-prandial abdominal pain for 3 months. No diabetes, hypertension or previous surgery. "
            "No known drug allergies."
        )

    def page2(pg: Page) -> None:
        pg.section("Investigations")
        pg.table(
            ["Test", "12/01/2026", "15/01/2026", "Reference range"],
            [
                ["Haemoglobin (g/dl)", "13.4", "12.9", "13.0 - 17.0"],
                ["Total leucocyte count (/cu mm)", "14,200", "8,900", "4,000 - 11,000"],
                ["Platelet count (lakh /cu mm)", "2.4", "2.6", "1.5 - 4.1"],
                ["Total bilirubin (mg/dl)", "1.4", "0.9", "0.3 - 1.2"],
                ["SGOT / AST (U/L)", "48", "34", "< 40"],
                ["SGPT / ALT (U/L)", "52", "38", "< 41"],
                ["Alkaline phosphatase (U/L)", "138", "112", "40 - 129"],
                ["Serum amylase (U/L)", "62", "-", "28 - 100"],
                ["Serum creatinine (mg/dl)", "0.9", "0.8", "0.7 - 1.3"],
            ],
            widths=[210, 90, 90, 120],
            align=["L", "R", "R", "L"],
        )
        pg.section("Imaging")
        pg.text(
            "USG whole abdomen (12/01/2026): distended gall bladder with multiple calculi (largest 14 mm), wall "
            "thickening of 5 mm and pericholecystic fluid; sonographic Murphy's sign positive; CBD 5 mm, not dilated. "
            "Impression: acute calculous cholecystitis."
        )
        pg.section("Course in hospital")
        pg.text(
            f"The patient was admitted on {dmy_slash(S.admission)} with features of acute cholecystitis and started on "
            "IV antibiotics, analgesics and IV fluids. After pre-anaesthetic evaluation and informed consent, he "
            f"underwent {C.procedure} under {C.anaesthesia.lower()} on {dmy_slash(S.surgery)}. Intra-operatively the "
            "gall bladder was distended and inflamed, with multiple calculi and omental adhesions. The specimen was "
            "sent for histopathological examination."
        )
        pg.text(
            "The post-operative period was uneventful. The drain was removed on post-operative day 2. He was mobilised "
            "early, tolerated an oral diet and remained afebrile with a healthy wound. He is being discharged in a "
            "stable condition."
        )

    def page3(pg: Page) -> None:
        pg.section("Condition at discharge")
        pg.fields(
            [
                ("General Condition", "Stable, afebrile"),
                ("Vitals", "Pulse 82 / min, BP 118 / 76 mmHg"),
                ("Wound", "Healthy, dressing dry"),
                ("Diet", "Tolerating soft diet"),
            ]
        )
        pg.section("Discharge medications")
        pg.table(
            ["Medicine", "Dose", "Frequency", "Duration"],
            [
                ["Tab. Cefuroxime Axetil 500 mg", "1 tablet", "Twice daily after food", "5 days"],
                ["Tab. Paracetamol 650 mg", "1 tablet", "When required for pain (max 3 / day)", "5 days"],
                ["Tab. Pantoprazole 40 mg", "1 tablet", "Once daily before breakfast", "7 days"],
                ["Tab. Ondansetron 4 mg", "1 tablet", "When required for nausea", "3 days"],
                ["Syp. Lactulose", "15 ml", "At bedtime if constipated", "5 days"],
            ],
            widths=[190, 70, 170, 80],
        )
        pg.section("Advice")
        pg.bullets(
            [
                "Soft, low-fat diet for 2 weeks; plenty of oral fluids.",
                "Keep the wounds clean and dry; dressing change on 19/01/2026.",
                "Avoid lifting heavy weights for 4 weeks.",
                "Walk regularly and resume routine activities gradually.",
            ]
        )
        pg.section("Follow-up")
        pg.text(
            f"Review in the General Surgery OPD with {C.surgeon} on {dmy_slash(S.follow_up)} with the histopathology "
            "report."
        )
        pg.section("Return to hospital immediately if")
        pg.bullets(
            [
                "Fever above 100 °F, increasing abdominal pain or vomiting.",
                "Yellowish discolouration of the eyes or urine.",
                "Discharge or bleeding from the wounds.",
            ]
        )
        pg.signatures(
            [
                Slot("Treating Consultant", C.surgeon_full, date=dmy_slash(S.discharge), stamp=SURGEON_STAMP),
                Slot("Prepared by", f"{C.resident}, Resident (General Surgery)", date=dmy_slash(S.discharge)),
            ],
            before=6,
        )

    return render_pdf(
        [page1, page2, page3],
        letterhead=SURGERY_LH,
        title="06_Discharge_Summary",
        doc_ref="Form CCH/DS/01",
        continuation_strip=STRIP,
    )


# --- 07 Prescription ---------------------------------------------------------------------------------


def prescription() -> bytes:
    def page(pg: Page) -> None:
        pg.title("PRESCRIPTION", "Discharge prescription")
        pg.fields(
            _patient(
                ("Date", dmy(S.discharge)),
                ("Consultant", C.surgeon_full),
                ("Diagnosis", C.diagnosis),
                ("Procedure", f"{C.procedure} ({dmy(S.surgery)})"),
            )
        )
        pg.c.setFont(BOLD, 22)
        pg.c.setFillColor(INK)
        pg.c.drawString(kit.MARGIN_X + 6, pg.y - 14, "Rx")
        pg.gap(34)
        pg.table(
            ["#", "Medicine", "Dose", "Frequency", "Duration", "Instructions"],
            [
                ["1", "Tab. Cefuroxime Axetil 500 mg", "1 tablet", "Twice daily", "5 days", "After food"],
                ["2", "Tab. Paracetamol 650 mg", "1 tablet", "When required (max 3 / day)", "5 days", "For pain or fever"],
                ["3", "Tab. Pantoprazole 40 mg", "1 tablet", "Once daily", "7 days", "Before breakfast"],
                ["4", "Tab. Ondansetron 4 mg", "1 tablet", "When required", "3 days", "For nausea"],
                ["5", "Syp. Lactulose", "15 ml", "At bedtime", "5 days", "If constipated"],
            ],
            widths=[20, 150, 55, 115, 55, 115],
            align=["C", "L", "L", "L", "L", "L"],
        )
        pg.section("Advice")
        pg.bullets(
            [
                "Soft, low-fat diet for 2 weeks.",
                "Dressing change on 19-01-2026; keep the wounds dry.",
                "No heavy lifting for 4 weeks.",
                "Complete the full course of antibiotics.",
            ]
        )
        pg.section("Follow-up")
        pg.text(f"General Surgery OPD on {dmy(S.follow_up)}. Bring this prescription and the discharge summary.")
        pg.signatures(
            [Slot("Doctor's Signature", f"{C.surgeon_full} · {C.surgeon_registration}", stamp=SURGEON_STAMP)]
        )

    return render_pdf([page], letterhead=SURGERY_LH, title="07_Prescription", doc_ref="Form CCH/RX/02")


# --- 08 Nursing record (2 pages) -------------------------------------------------------------------


def nursing_record() -> bytes:
    note_widths = [92, 370, 48]
    note_align = ["L", "L", "C"]

    def page1(pg: Page) -> None:
        pg.title("NURSING RECORD", "In-patient nursing chart")
        pg.fields(
            _patient(
                ("Ward / Room", S.ward),
                ("Date of Admission", dmy(S.admission)),
                ("Primary Nurse", C.primary_nurse),
                ("Consultant", C.surgeon),
            )
        )
        pg.section("Vital signs chart")
        pg.table(
            ["Date / Time", "Temp (°F)", "Pulse", "BP (mmHg)", "RR", "SpO2 (%)", "Pain", "Nurse"],
            [
                ["12-01-2026 10:00", "101.2", "104", "128/82", "20", "98", "7/10", "MT"],
                ["12-01-2026 18:00", "100.4", "98", "124/80", "18", "98", "5/10", "AV"],
                ["13-01-2026 06:00", "99.1", "90", "122/78", "18", "99", "4/10", "AV"],
                ["13-01-2026 12:00", "98.8", "92", "118/76", "18", "99", "5/10", "MT"],
                ["13-01-2026 20:00", "99.0", "88", "120/78", "18", "98", "4/10", "AV"],
                ["14-01-2026 08:00", "98.6", "84", "118/74", "16", "99", "3/10", "MT"],
                ["14-01-2026 20:00", "98.4", "82", "116/76", "16", "99", "2/10", "AV"],
                ["15-01-2026 08:00", "98.4", "80", "118/76", "16", "99", "2/10", "MT"],
                ["15-01-2026 20:00", "98.2", "78", "116/74", "16", "99", "1/10", "AV"],
                ["16-01-2026 08:00", "98.4", "82", "118/76", "16", "99", "1/10", "MT"],
            ],
            widths=[92, 52, 44, 64, 34, 52, 42, 40],
            align=["L", "R", "R", "C", "R", "R", "C", "C"],
        )
        pg.section("Nursing notes")
        pg.table(
            ["Date / Time", "Note", "Nurse"],
            [
                [
                    "12-01-2026 10:00",
                    "Admitted to Surgical Ward, Room 304. Oriented to the ward. Vitals recorded. IV cannula (20G) "
                    "secured in the left hand. Nil by mouth as advised.",
                    "MT",
                ],
                [
                    "12-01-2026 18:30",
                    "Pre-anaesthetic check-up done. Pre-operative instructions explained to the patient and his wife.",
                    "AV",
                ],
                [
                    "13-01-2026 07:30",
                    "Pre-operative checklist completed: nil by mouth since 22:00, identity band checked, jewellery "
                    "removed, pre-medication given.",
                    "AV",
                ],
                ["13-01-2026 09:50", "Shifted to OT-2 with the case file and investigation reports.", "MT"],
            ],
            widths=note_widths,
            align=note_align,
        )
        pg.text("MT = Sr. Mary Thomas, RN;  AV = Sr. Anjali Verma, RN", size=7.6, color=MUTED)

    def page2(pg: Page) -> None:
        pg.section("Post-operative notes")
        pg.table(
            ["Date / Time", "Observation / care", "Nurse"],
            [
                [
                    "13-01-2026 11:40",
                    f"Received from OT after {C.procedure} under general anaesthesia. Conscious and oriented, vitals "
                    "stable. Drain in situ with 30 ml serous output. Port-site dressings dry.",
                    "MT",
                ],
                [
                    "13-01-2026 16:00",
                    "Pain score 5/10; IV analgesic given as prescribed. Passed urine. Sips of water started at 18:00.",
                    "MT",
                ],
                [
                    "14-01-2026 08:00",
                    "Post-operative day 1: ambulated with support, tolerating oral liquids. Drain output 20 ml serous.",
                    "MT",
                ],
                [
                    "15-01-2026 09:00",
                    "Post-operative day 2: drain removed by the surgical team; site dressed. Soft diet tolerated.",
                    "MT",
                ],
                [
                    "16-01-2026 10:30",
                    "Discharge advice, medicines and follow-up date explained to the patient and his wife.",
                    "MT",
                ],
            ],
            widths=note_widths,
            align=note_align,
        )
        pg.section("Medication administration record")
        pg.table(
            ["Medicine", "Dose / route", "Frequency", "12-01", "13-01", "14-01", "15-01", "16-01"],
            [
                ["Inj. Ceftriaxone", "1 g IV", "12-hourly", "10, 22", "10, 22", "10, 22", "-", "-"],
                ["Inj. Metronidazole", "500 mg IV", "8-hourly", "10, 18", "02, 10, 18", "02", "-", "-"],
                ["Inj. Pantoprazole", "40 mg IV", "Once daily", "10", "08", "08", "08", "08"],
                ["Inj. Paracetamol", "1 g IV", "8-hourly", "12, 20", "12, 20", "04, 12", "-", "-"],
                ["Inj. Ondansetron", "4 mg IV", "When required", "12", "12, 20", "08", "-", "-"],
                ["Inj. Tramadol", "50 mg IV", "When required", "-", "12, 20", "08, 20", "-", "-"],
                ["Inj. Enoxaparin", "40 mg SC", "Once daily", "-", "20", "20", "-", "-"],
                ["IV Ringer Lactate", "500 ml", "As ordered", "2 bottles", "4 bottles", "2 bottles", "-", "-"],
                ["IV Dextrose Normal Saline", "500 ml", "As ordered", "2 bottles", "2 bottles", "2 bottles", "-", "-"],
            ],
            widths=[96, 60, 64, 58, 58, 58, 58, 58],
            size=7.6,
        )
        pg.signatures(
            [
                Slot("Nurse Signature", C.primary_nurse, date=dmy(S.discharge)),
                Slot("Nursing Supervisor", C.nursing_supervisor, date=dmy(S.discharge), stamp=HOSPITAL_STAMP),
            ],
            before=4,
        )

    return render_pdf(
        [page1, page2],
        letterhead=NURSING_LH,
        title="08_Nursing_Record",
        doc_ref="Form CCH/NUR/05",
        continuation_strip=STRIP,
    )


# --- 09 USG abdomen report (source for the degraded scan) --------------------------------------------


def usg_report() -> bytes:
    def page(pg: Page) -> None:
        pg.title("ULTRASOUND REPORT", "USG whole abdomen")
        pg.fields(
            [
                ("Patient Name", P.name),
                ("UHID", P.uhid),
                ("Age / Sex", P.age_sex),
                ("IPD No.", P.ipd_no),
                ("Referred By", C.surgeon),
                ("Report No.", "RAD/USG/2026/00731"),
                ("Date of Study", dmy(S.admission)),
                ("Time", "10:30"),
            ]
        )
        pg.section("Findings")
        pg.fields(
            [
                ("Liver", "Normal in size (13.8 cm) and echotexture. No focal lesion. No biliary radicle dilatation."),
                (
                    "Gall bladder",
                    "Distended, with multiple calculi (largest 14 mm). Wall thickened (5 mm) with pericholecystic "
                    "fluid. Sonographic Murphy's sign positive.",
                ),
                ("CBD", "5 mm, not dilated. No calculus seen."),
                ("Pancreas", "Normal in size and echotexture."),
                ("Spleen", "Normal in size (10.2 cm)."),
                ("Kidneys", "Normal in size and echotexture. No calculus or hydronephrosis."),
                ("Urinary bladder", "Well distended with a normal wall."),
                ("Others", "No free fluid in the abdomen. No significant lymphadenopathy."),
            ],
            columns=1,
        )
        pg.section("Impression")
        pg.text("Features suggestive of acute calculous cholecystitis.", font=BOLD, size=9.2)
        pg.text("Clinical correlation is suggested.")
        pg.signatures([Slot("Reported by", C.radiologist, date=dmy(S.admission), stamp=RADIOLOGY_STAMP)])

    return render_pdf(
        [page], letterhead=RADIOLOGY_LH, title="09_USG_Abdomen_Scan", doc_ref="Form CCH/RAD/03", text_scale=1.15
    )


# --- 10 Laboratory report ------------------------------------------------------------------------------


def lab_report() -> bytes:
    header = ["Test", "Result", "Units", "Reference range", "Flag"]
    widths = [170, 70, 90, 120, 60]
    align = ["L", "R", "L", "L", "C"]

    def page(pg: Page) -> None:
        pg.title("LABORATORY REPORT", "Haematology · Biochemistry · Coagulation")
        pg.fields(
            _patient(
                ("Referred By", C.surgeon),
                ("Sample ID", "LAB/2026/118204"),
                ("Collected On", f"{dmy(S.admission)} 10:10"),
                ("Reported On", f"{dmy(S.admission)} 13:45"),
            )
        )
        pg.section("Haematology")
        pg.table(
            header,
            [
                ["Haemoglobin", "13.4", "g/dl", "13.0 - 17.0", ""],
                ["Total leucocyte count", "14,200", "/cu mm", "4,000 - 11,000", "High"],
                ["Neutrophils", "82", "%", "40 - 75", "High"],
                ["Lymphocytes", "14", "%", "20 - 40", "Low"],
                ["Platelet count", "2.4", "lakh /cu mm", "1.5 - 4.1", ""],
                ["ESR", "28", "mm/hr", "0 - 15", "High"],
            ],
            widths=widths,
            align=align,
        )
        pg.section("Biochemistry")
        pg.table(
            header,
            [
                ["Total bilirubin", "1.4", "mg/dl", "0.3 - 1.2", "High"],
                ["Direct bilirubin", "0.5", "mg/dl", "0.0 - 0.3", "High"],
                ["SGOT / AST", "48", "U/L", "< 40", "High"],
                ["SGPT / ALT", "52", "U/L", "< 41", "High"],
                ["Alkaline phosphatase", "138", "U/L", "40 - 129", "High"],
                ["Serum amylase", "62", "U/L", "28 - 100", ""],
                ["Serum lipase", "38", "U/L", "13 - 60", ""],
                ["Blood urea", "28", "mg/dl", "15 - 40", ""],
                ["Serum creatinine", "0.9", "mg/dl", "0.7 - 1.3", ""],
                ["Sodium / potassium", "138 / 4.1", "mmol/L", "135 - 145 / 3.5 - 5.1", ""],
            ],
            widths=widths,
            align=align,
        )
        pg.section("Coagulation")
        pg.table(
            header,
            [["Prothrombin time", "12.8", "seconds", "11.0 - 13.5", ""], ["INR", "1.02", "-", "0.8 - 1.2", ""]],
            widths=widths,
            align=align,
        )
        pg.text(
            "Results relate only to the sample received. Values flagged High or Low are outside the reference range.",
            size=7.6,
            color=MUTED,
        )
        pg.signatures([Slot("Pathologist", C.pathologist, date=dmy(S.admission), stamp=LAB_STAMP)], before=2)

    return render_pdf([page], letterhead=LAB_LH, title="10_Lab_Report", doc_ref="Form CCH/LAB/07")


# --- 12 Main hospital bill -------------------------------------------------------------------------------


def main_hospital_bill() -> bytes:
    subtotal = bill_total(MAIN_BILL_LINES)

    def page(pg: Page) -> None:
        pg.title("FINAL HOSPITAL BILL", "In-patient bill · cashless (TPA)")
        pg.fields(
            [
                ("Bill No.", MAIN_BILL_NO),
                ("Bill Date", dmy(S.discharge)),
                ("Patient Name", P.name),
                ("UHID", P.uhid),
                ("Age / Sex", P.age_sex),
                ("IPD No.", P.ipd_no),
                ("Date of Admission", dmy(S.admission)),
                ("Date of Discharge", dmy(S.discharge)),
                ("Consultant", C.surgeon),
                ("Ward / Room", S.ward),
                ("Payer", f"{COVER.tpa} ({COVER.insurer})"),
                ("Policy No.", COVER.policy_no),
            ]
        )
        pg.section("Bill details")
        pg.table(BILL_HEADER, _bill_rows(MAIN_BILL_LINES), widths=BILL_WIDTHS, align=BILL_ALIGN)
        pg.totals(
            [
                ("Sub Total", inr(subtotal)),
                ("GST (healthcare services exempt)", inr(0)),
                ("Discount", inr(0)),
                ("Net Payable (Rs.)", inr(subtotal)),
            ]
        )
        pg.text(f"Amount in words: {rupees_in_words(subtotal)}", font=BOLD, size=8.4)
        pg.text(
            "The break-up of operation theatre, pharmacy and implant charges is enclosed. Payable by the TPA under "
            "the cashless authorisation, subject to policy terms.",
            size=7.8,
            color=MUTED,
        )
        pg.signatures(
            [
                Slot("Prepared by", "Billing Executive, Insurance Desk"),
                Slot("Authorised Signatory", "Billing Department", stamp=BILLING_STAMP),
            ]
        )

    return render_pdf([page], letterhead=BILLING_LH, title="12_Main_Hospital_Bill", doc_ref="Form CCH/BIL/01")


# --- 13 Pharmacy bill (seeded patient-name mismatch) ------------------------------------------------------


def pharmacy_bill() -> bytes:
    total = bill_total(PHARMACY_LINES)

    def page(pg: Page) -> None:
        pg.title("PHARMACY BILL", "In-patient pharmacy · credit (TPA)")
        pg.fields(
            [
                ("Bill No.", PHARMACY_BILL_NO),
                ("Bill Date", dmy(S.discharge)),
                ("Patient Name", P.name_on_pharmacy_bill),
                ("UHID", P.uhid),
                ("IPD No.", P.ipd_no),
                ("Ward / Room", S.ward),
                ("Prescribing Doctor", C.surgeon),
                ("Payer", COVER.tpa),
            ]
        )
        pg.section("Items dispensed")
        pg.table(
            ["Sl.", "Item description", "Batch", "Expiry", "Qty", "Rate (Rs.)", "Amount (Rs.)"],
            [
                [str(i), line.description, line.batch, line.expiry, str(line.qty), inr(line.rate), inr(line.amount)]
                for i, line in enumerate(PHARMACY_LINES, 1)
            ],
            widths=[26, 196, 64, 48, 34, 66, 76],
            align=["C", "L", "L", "C", "R", "R", "R"],
        )
        pg.totals([("Sub Total", inr(total)), ("GST", "Included in rates"), ("Net Amount (Rs.)", inr(total))])
        pg.text(f"Amount in words: {rupees_in_words(total)}", font=BOLD, size=8.4)
        pg.signatures([Slot("Pharmacist", "Pharmacist on duty · Reg. No. DEMO-PH-0912", stamp=PHARMACY_STAMP)])

    return render_pdf([page], letterhead=PHARMACY_LH, title="13_Pharmacy_Bill", doc_ref="Form CCH/PHR/03")


# --- 14 OT bill (seeded duplicate bill number) -------------------------------------------------------------


def ot_bill() -> bytes:
    total = bill_total(OT_BILL_LINES)

    def page(pg: Page) -> None:
        pg.title("OPERATION THEATRE BILL", "OT charges break-up")
        pg.fields(
            [
                ("Bill No.", OT_BILL_NO),
                ("Bill Date", dmy(S.surgery)),
                ("Patient Name", P.name),
                ("UHID", P.uhid),
                ("IPD No.", P.ipd_no),
                ("Date of Surgery", dmy(S.surgery)),
                ("Procedure", C.procedure),
                ("OT / Time", "OT-2 / 10:05 - 11:30"),
                ("Surgeon", C.surgeon),
                ("Anaesthetist", C.anaesthetist),
            ]
        )
        pg.section("Charges")
        pg.table(BILL_HEADER, _bill_rows(OT_BILL_LINES), widths=BILL_WIDTHS, align=BILL_ALIGN)
        pg.totals([("Sub Total", inr(total)), ("Net Payable (Rs.)", inr(total))])
        pg.text(f"Amount in words: {rupees_in_words(total)}", font=BOLD, size=8.4)
        pg.signatures(
            [
                Slot("OT In-charge", C.scrub_nurse),
                Slot("Authorised Signatory", "Billing Department", stamp=BILLING_STAMP),
            ]
        )

    return render_pdf([page], letterhead=BILLING_LH, title="14_OT_Bill", doc_ref="Form CCH/BIL/04")


# --- 15 Implant invoice (seeded concealed overwrite) -------------------------------------------------------


def _overwrite_rate(pg: Page, cell: Cell) -> None:
    """Seeded issue: the printed rate is hidden under an opaque white box and re-typed on top."""
    c = pg.c
    size = 8.0
    baseline = cell.y + cell.h - 4 - size * 0.78
    right = cell.x + cell.w - 4
    c.setFont(REGULAR, size)
    c.setFillColor(INK)
    c.drawRightString(right, baseline, inr(IMPLANT.concealed_rate))
    c.setFillColor(white)
    c.rect(cell.x + 2, cell.y + 2, cell.w - 4, cell.h - 4, stroke=0, fill=1)
    c.setFillColor(INK)
    c.setFont(REGULAR, size + 0.3)
    c.drawRightString(right - 1.2, baseline + 0.7, inr(IMPLANT.rate))


def _implant_sticker(pg: Page) -> None:
    c = pg.c
    pg.ensure(80)
    x, top = kit.MARGIN_X + 6, pg.y + 4
    w, h = 270, 70
    c.setStrokeColor(MUTED)
    c.setLineWidth(0.7)
    c.setDash(3, 2)
    c.rect(x, top - h, w, h, stroke=1, fill=0)
    c.setDash()
    c.setFont(BOLD, 7)
    c.setFillColor(MUTED)
    c.drawString(x + 8, top - 11, "IMPLANT STICKER (affixed by OT staff)")
    c.setFillColor(INK)
    kit.draw_barcode(c, x + 8, top - 48, 104, 28, seed=f"{IMPLANT.ref}|{IMPLANT.lot}")
    c.setFont(REGULAR, 6.4)
    c.drawString(x + 8, top - 58, IMPLANT.item)
    c.setFont(BOLD, 7.4)
    for i, line in enumerate(
        (f"REF  {IMPLANT.ref}", f"LOT  {IMPLANT.lot}", f"EXP  {IMPLANT.expiry}", f"QTY  {IMPLANT.qty} clips")
    ):
        c.drawString(x + 128, top - 24 - i * 10, line)
    pg.y = top - h - 16


def implant_invoice() -> bytes:
    def page(pg: Page) -> None:
        pg.title("TAX INVOICE", "Surgical implants supplied for patient use")
        pg.fields(
            [
                ("Invoice No.", IMPLANT_INVOICE_NO),
                ("Invoice Date", dmy(S.surgery)),
                ("Bill To", H.name),
                ("PO Reference", IMPLANT.purchase_order),
                ("Patient Name", P.name),
                ("UHID", P.uhid),
                ("Procedure", C.procedure),
                ("Surgeon", C.surgeon),
                ("Delivered To", "OT Complex (OT-2)"),
                ("Date of Use", dmy(S.surgery)),
            ]
        )
        pg.section("Items")
        cells = pg.table(
            ["Sl.", "Description", "Lot No.", "Qty", "Rate (Rs.)", "Amount (Rs.)"],
            [["1", IMPLANT.item, IMPLANT.lot, str(IMPLANT.qty), "", inr(IMPLANT.amount)]],
            widths=[28, 200, 80, 40, 80, 82],
            align=["C", "L", "L", "R", "R", "R"],
        )
        _overwrite_rate(pg, cells[0][4])
        pg.totals(
            [
                ("Sub Total", inr(IMPLANT.amount)),
                ("GST", "Included in rate"),
                ("Invoice Total (Rs.)", inr(IMPLANT.amount)),
            ]
        )
        pg.text(f"Amount in words: {rupees_in_words(IMPLANT.amount)}", font=BOLD, size=8.4)
        _implant_sticker(pg)
        pg.section("Declaration")
        pg.text(
            "Certified that the implants listed above were supplied against the purchase order referenced and used "
            "for the named patient. Goods once used cannot be returned."
        )
        pg.signatures([Slot(f"For {IMPLANT.vendor}", "Authorised Signatory", stamp=VENDOR_STAMP)])

    return render_pdf([page], letterhead=VENDOR_LH, title="15_Implant_Invoice", doc_ref="Form DS/INV/02")


# --- 16 Consent form (seeded missing patient signature) --------------------------------------------------


def consent_form() -> bytes:
    def page(pg: Page) -> None:
        pg.title("INFORMED CONSENT FOR SURGERY AND ANAESTHESIA")
        pg.fields(_patient(("Date", dmy(S.admission)), ("Time", "18:10")))
        pg.fields(
            [
                ("Procedure", C.procedure),
                ("Additional Procedure (if required)", "Conversion to open cholecystectomy"),
                ("Type of Anaesthesia", C.anaesthesia),
                ("Surgeon / Anaesthetist", f"{C.surgeon} / {C.anaesthetist}"),
            ],
            columns=1,
        )
        pg.section("Declaration by the patient / guardian")
        pg.bullets(
            [
                "The nature of my illness, the proposed procedure, its expected benefits and the alternatives "
                "available have been explained to me in a language I understand.",
                "I understand the risks, including bleeding, infection, bile leak, injury to the bile duct or bowel, "
                "and the risks of anaesthesia.",
                "I understand that the laparoscopic procedure may need to be converted to an open operation if the "
                "surgeon considers it necessary.",
                "I consent to the administration of anaesthesia and to blood transfusion if required.",
                "I consent to the removed tissue being sent for histopathological examination.",
                "I have had the opportunity to ask questions, and my questions have been answered to my satisfaction.",
            ],
            numbered=True,
        )
        pg.fields([("Explained In", "Hindi and English"), ("Explained By", C.surgeon)])
        pg.signatures(
            [
                Slot("Signature of Patient / Guardian", P.name, date=dmy(S.admission), signed=False),
                Slot("Signature of Witness", P.next_of_kin, date=dmy(S.admission)),
            ],
            before=6,
        )
        pg.signatures(
            [
                Slot("Signature of Surgeon", C.surgeon_full, date=dmy(S.admission), stamp=SURGEON_STAMP),
                Slot("Signature of Anaesthetist", C.anaesthetist_full, date=dmy(S.admission)),
            ],
            before=18,
        )

    return render_pdf([page], letterhead=SURGERY_LH, title="16_Consent_Form", doc_ref="Form CCH/CON/02")


# --- Later: operative note (scan_0042.pdf) ---------------------------------------------------------------


def operative_note() -> bytes:
    def page1(pg: Page) -> None:
        pg.title("OPERATIVE NOTE", "Department of General Surgery · OT-2")
        pg.fields(
            _patient(
                ("Date of Surgery", dmy(S.surgery)),
                ("Operation Time", "10:15 - 11:25"),
                ("Surgeon", C.surgeon_full),
                ("Assistant Surgeon", C.assistant_surgeon),
                ("Anaesthetist", C.anaesthetist_full),
                ("Anaesthesia", C.anaesthesia),
                ("Scrub Nurse", C.scrub_nurse),
                ("Wound Class", "Clean-contaminated"),
            )
        )
        pg.fields(
            [
                ("Pre-operative Diagnosis", C.diagnosis),
                ("Post-operative Diagnosis", C.diagnosis),
                ("Procedure Performed", C.procedure),
            ],
            columns=1,
        )
        pg.section("Operative findings")
        pg.bullets(
            [
                "Distended, inflamed gall bladder with a thickened wall and multiple calculi.",
                "Omental adhesions to the fundus of the gall bladder; no perforation or pus.",
                "Cystic duct and cystic artery clearly identified; common bile duct normal.",
                "Liver, stomach and duodenum grossly normal.",
            ]
        )
        pg.section("Procedure details")
        pg.bullets(
            [
                "Patient supine under general anaesthesia with endotracheal intubation; parts painted and draped.",
                "Pneumoperitoneum created by the open (Hasson) technique at the umbilicus; four-port technique used.",
                "Omental adhesions released by blunt and harmonic dissection.",
                "Calot's triangle dissected and the critical view of safety achieved.",
                "Cystic duct and cystic artery secured with Hem-o-lok polymer ligating clips (6 clips applied in "
                "total) and divided.",
                "Gall bladder separated from the liver bed with hook diathermy and retrieved in an endobag through "
                "the epigastric port.",
                "Haemostasis confirmed; liver bed irrigated; 16 Fr subhepatic drain placed through the right lateral "
                "port.",
                "Ports closed under vision; umbilical fascia closed; skin closed with absorbable sutures.",
            ],
            numbered=True,
        )

    def page2(pg: Page) -> None:
        pg.section("Implants used")
        pg.table(
            ["Implant", "Qty", "Lot No.", "Placement"],
            [[IMPLANT.item, str(IMPLANT.qty), IMPLANT.lot, "Cystic duct (3), cystic artery (3)"]],
            widths=[200, 50, 90, 170],
            align=["L", "R", "L", "L"],
        )
        pg.section("Summary")
        pg.fields(
            [
                ("Specimen", "Gall bladder with calculi, sent for histopathology"),
                ("Estimated Blood Loss", "30 ml"),
                ("Drain", "16 Fr subhepatic drain"),
                ("Complications", "None"),
                ("Blood Transfusion", "Not required"),
                ("Condition", "Stable; shifted to recovery at 11:40"),
            ]
        )
        pg.section("Post-operative instructions")
        pg.bullets(
            [
                "Nil by mouth for 6 hours, then sips of water; soft diet from post-operative day 1.",
                "Continue Inj. Ceftriaxone 1 g IV 12-hourly and Inj. Metronidazole 500 mg IV 8-hourly.",
                "Analgesia as per chart; monitor vitals, drain output and urine output.",
                "Early ambulation; review the drain on post-operative day 2.",
            ]
        )
        pg.signatures(
            [
                Slot(
                    "Operating Surgeon",
                    f"{C.surgeon_full} · {C.surgeon_registration}",
                    date=dmy(S.surgery),
                    stamp=SURGEON_STAMP,
                )
            ]
        )

    return render_pdf(
        [page1, page2],
        letterhead=SURGERY_LH,
        title="scan_0042",
        doc_ref="Form CCH/OT/05",
        continuation_strip=STRIP,
    )


# --- Later: anaesthesia record ------------------------------------------------------------------------------


def anaesthesia_record() -> bytes:
    def page1(pg: Page) -> None:
        pg.title("ANAESTHESIA RECORD", "Intra-operative anaesthesia chart")
        pg.fields(
            _patient(
                ("Date", dmy(S.surgery)),
                ("Procedure", C.procedure_short),
                ("Surgeon", C.surgeon),
                ("Anaesthetist", C.anaesthetist_full),
                ("ASA Grade", "II"),
                ("Anaesthesia Type", "General anaesthesia (endotracheal)"),
                ("Induction Time", "10:05"),
                ("Extubation Time", "11:30"),
            )
        )
        pg.section("Pre-induction check")
        pg.fields(
            [
                ("Weight", P.weight),
                ("Nil by Mouth Since", "22:00 hrs, 12-01-2026"),
                ("Consent Verified", "Yes"),
                ("Airway", "Mallampati II"),
                ("IV Access", "20G left hand, 18G right forearm"),
                ("Monitoring", "ECG, NIBP, SpO2, EtCO2, temperature"),
            ]
        )
        pg.section("Drugs administered")
        pg.table(
            ["Time", "Drug", "Dose", "Route"],
            [
                ["10:00", "Inj. Glycopyrrolate", "0.2 mg", "IV"],
                ["10:00", "Inj. Fentanyl", "100 mcg", "IV"],
                ["10:05", "Inj. Propofol", "150 mg", "IV"],
                ["10:05", "Inj. Atracurium", "30 mg", "IV"],
                ["10:08", "Sevoflurane in oxygen / air", "1.5 - 2 %", "Inhalational"],
                ["10:10", "Inj. Ceftriaxone", "1 g", "IV"],
                ["10:45", "Inj. Paracetamol", "1 g", "IV infusion"],
                ["11:10", "Inj. Ondansetron", "4 mg", "IV"],
                ["11:25", "Inj. Neostigmine + Glycopyrrolate", "2.5 mg + 0.4 mg", "IV"],
            ],
            widths=[60, 230, 120, 100],
        )
        pg.section("Airway and ventilation")
        pg.fields(
            [
                ("Airway Device", "Cuffed ETT 8.0 mm"),
                ("Laryngoscopy", "Cormack-Lehane grade I"),
                ("Ventilation", "Volume control, TV 450 ml, RR 14 / min"),
                ("PEEP", "5 cm H2O"),
            ]
        )

    def page2(pg: Page) -> None:
        pg.section("Intra-operative monitoring")
        pg.table(
            ["Time", "HR (/min)", "BP (mmHg)", "SpO2 (%)", "EtCO2 (mmHg)", "Remarks"],
            [
                ["10:05", "94", "124/80", "100", "-", "Induction"],
                ["10:15", "88", "118/76", "100", "34", "Incision"],
                ["10:30", "84", "116/74", "99", "36", "Pneumoperitoneum stable"],
                ["10:45", "82", "114/72", "99", "37", ""],
                ["11:00", "80", "116/74", "99", "36", ""],
                ["11:15", "82", "118/76", "100", "35", ""],
                ["11:25", "86", "122/78", "100", "34", "Closure"],
            ],
            widths=[50, 60, 70, 60, 80, 190],
            align=["L", "R", "C", "R", "R", "L"],
        )
        pg.section("Fluids and output")
        pg.fields(
            [
                ("IV Fluids", "Ringer lactate 1000 ml"),
                ("Blood Loss", "30 ml (estimated)"),
                ("Urine Output", "150 ml"),
                ("Blood Products", "None"),
            ]
        )
        pg.section("Recovery")
        pg.fields(
            [
                ("Extubation", "Smooth, at 11:30"),
                ("Shifted to Recovery", "11:40"),
                ("Aldrete Score", "9 / 10"),
                ("Condition", "Stable, conscious, oriented"),
            ]
        )
        pg.text(
            "Post-operative analgesia and antiemetics as per chart. Oxygen by face mask at 4 L/min until SpO2 is "
            "maintained on room air."
        )
        pg.signatures(
            [
                Slot(
                    "Anaesthetist",
                    f"{C.anaesthetist_full} · {C.anaesthetist_registration}",
                    date=dmy(S.surgery),
                    stamp=ANAESTHETIST_STAMP,
                )
            ]
        )

    return render_pdf(
        [page1, page2],
        letterhead=ANAESTHESIA_LH,
        title="Anaesthesia_Record",
        doc_ref="Form CCH/ANS/04",
        continuation_strip=STRIP,
    )

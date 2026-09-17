# Synthetic demo claim

**Every document in this folder is synthetic.** People, hospitals, insurers, identifiers and amounts are all fictional, and every page carries the notice *SYNTHETIC DEMO DOCUMENT — NOT A REAL RECORD*.

The files are produced by a deterministic generator (`backend/app/demo_gen`). Running it again gives byte-identical files; `manifest.json` records the SHA-256 of each one.

```bash
make demo-data    # regenerate
make demo-check   # verify these files match the generator byte for byte
```

## The claim

| Field | Value |
|-------|-------|
| Patient | Rajesh Sharma, 46 Y / Male |
| UHID / IPD | UHID-123456 / IPD/2026/004512 |
| Hospital | CityCare Multispeciality Hospital |
| Stay | Admitted 12 Jan 2026 · surgery 13 Jan 2026 · discharged 16 Jan 2026 |
| Diagnosis | Acute cholecystitis (K81.0) |
| Procedure | Laparoscopic Cholecystectomy (also written "Lap. Cholecystectomy" and "Lap Chole") |
| Insurer / TPA | Demo Health Insurance / Demo TPA |

## `initial/` — the first upload (16 files)

| File | Document | Seeded issue |
|------|----------|--------------|
| 01_Patient_ID.png | Insurer health e-card (image) | — |
| 02_Admission_Form.pdf | Admission record | — |
| 03_Doctor_Consultation.pdf | Consultation note ("Lap. Cholecystectomy") | — |
| 04_PreOp_Assessment.pdf | Pre-operative assessment ("Lap Chole") | — |
| 05_Anaesthesia_Assessment.pdf | Pre-anaesthetic check-up | — |
| 06_Discharge_Summary.pdf | Discharge summary (3 pages) | — |
| 07_Prescription.pdf | Discharge prescription | — |
| 08_Nursing_Record.pdf | Nursing record (2 pages, with post-operative notes and medication record) | — |
| 09_USG_Abdomen_Scan.jpg | Ultrasound report | Poor-quality scan: 96 DPI, blurred, skewed |
| 10_Lab_Report.pdf | Laboratory report | — |
| 11_Lab_Report_copy.pdf | Laboratory report | Byte-identical duplicate of file 10 |
| 12_Main_Hospital_Bill.pdf | Final hospital bill | Bill no. CCH/IP/2026/08812 is reused; Room Rent 4 × 4,500.00 is billed as 20,000.00 |
| 13_Pharmacy_Bill.pdf | Pharmacy bill | Patient named "Rajesh K." |
| 14_OT_Bill.pdf | Operation theatre bill | Same bill no. as the main bill |
| 15_Implant_Invoice.pdf | Implant invoice | Rate 1,000.00 hidden under a white box and overwritten as 1,100.00 |
| 16_Consent_Form.pdf | Consent for surgery and anaesthesia | Patient / guardian signature missing |

The Operative Note and the Anaesthesia Record are deliberately **missing** from this pack.

## `later/` — documents supplied afterwards

| File | Document |
|------|----------|
| scan_0042.pdf | Operative note. The generic file name means classification must rely on the content. It records 6 Hem-o-lok clips (lot HL-44710), matching the implant invoice. |
| Anaesthesia_Record.pdf | Intra-operative anaesthesia record |

Through the API, these packs are attached with `POST /api/claims/{id}/demo-documents?set=initial|operative_note|anaesthesia_record`, which uses the same upload pipeline as a manual upload. You can also drag the files into the upload screen yourself.

## Offline OCR fixtures

`ocr_fixtures/<document sha256>.json` holds the text and geometry of the two image
documents (`01_Patient_ID.png` and `09_USG_Abdomen_Scan.jpg`), captured from their
synthetic source pages while this data was generated.

These files are **not OCR output**. They exist so the demo can read those documents on a
machine where the OCR extras are not installed, and anything produced from them is labelled
`demo_fixture` in the API, in the audit trail and in the interface. With RapidOCR installed
(the default), the application runs real OCR instead and the fixtures are unused.

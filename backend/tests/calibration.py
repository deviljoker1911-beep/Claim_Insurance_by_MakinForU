"""A labelled claim packet, built to look like the ones that arrive from a hospital.

The demo documents are useful but easy: every page of them carries "Page 2 of 3" in its footer, so
a bundle made of them tells the segmenter where every document ends. Real packets mostly do not.
They are scans of forms that repeat their heading on every page, bills that run for four pages
under the same header, and continuation sheets that say nothing about themselves at all.

So this fixture is written without page-of-total markers, and with the structures that actually
caused trouble: a multi-page pre-authorisation form, a bill whose header repeats, a run of pharmacy
continuation pages, two documents of the same type in a row, and a page that names nothing. Every
page carries a label, so accuracy can be counted rather than asserted.

Everything here is synthetic. The names, numbers and amounts are invented for this fixture, and no
part of any real claim file is reproduced.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pymupdf
from reportlab.lib.colors import HexColor

from app.demo_gen.pdfkit import Letterhead, Page, Slot, render_pdf

# --- who the synthetic packet is about --------------------------------------------------------

PATIENT = "Meera Raghavan"
UHID = "UHID-778120"
IPD = "IPD/2026/009914"
ADMITTED = "04-03-2026"
DISCHARGED = "08-03-2026"
SURGEON = "Dr. Kavita Rao"
ANAESTHETIST = "Dr. Samir Joshi"

HOSPITAL = Letterhead(
    name="Sunrise Multispeciality Hospital",
    tagline="In-patient services",
    contact=("Plot 14, Ring Road, Demo City - 411001", "Tel: +91-00-0000-0000 (synthetic)"),
    accent=HexColor("#186A3B"),
)
LAB = Letterhead(
    name="Sunrise Multispeciality Hospital",
    tagline="Department of Laboratory Medicine",
    contact=("Plot 14, Ring Road, Demo City - 411001", "Tel: +91-00-0000-0000 (synthetic)"),
    accent=HexColor("#186A3B"),
)
INSURER = Letterhead(
    name="Meridian Health Insurance",
    tagline="Third party administration",
    contact=("Tower B, Business Park, Demo City - 400001", "Tel: +91-00-0000-0000 (synthetic)"),
    accent=HexColor("#7D3C98"),
    mark="box",
)

# What a page is, relative to the document it belongs to.
DOCUMENT_START = "document_start"
CONTINUATION = "continuation"

PATIENT_FIELDS = [
    ("Patient Name", PATIENT),
    ("UHID", UHID),
    ("IPD No.", IPD),
    ("Date of Admission", ADMITTED),
]


@dataclass
class LabelledDocument:
    """One document of the packet, and what the system is expected to make of it."""

    doc_type: str
    pages: list  # page builders
    label: str
    # Where it landed once the packet was assembled; filled in by `build`.
    first_page: int = 0
    last_page: int = 0
    # A document whose type the system is not expected to recognise.
    expect_unclassified: bool = False
    page_numbering: bool = False
    letterhead: Letterhead = field(default=HOSPITAL)
    doc_ref: str = "Form SMH/GEN/01"

    @property
    def page_count(self) -> int:
        return len(self.pages)

    @property
    def page_numbers(self) -> list[int]:
        return list(range(self.first_page, self.last_page + 1))

    def roles(self) -> list[str]:
        return [DOCUMENT_START] + [CONTINUATION] * (self.page_count - 1)


# --- the documents ----------------------------------------------------------------------------


def _preauth_pages() -> list:
    """A cashless request on the standard form: three pages, the heading repeated on each."""

    def head(pg: Page, part: str) -> None:
        pg.title("REQUEST FOR CASHLESS HOSPITALISATION FOR HEALTH INSURANCE POLICY", part)

    def one(pg: Page) -> None:
        head(pg, "PART A — to be filled by the insured")
        pg.fields([*PATIENT_FIELDS, ("Policy No", "MHI/POL/2026/44120"), ("Sum Insured", "5,00,000.00")])
        pg.section("Details of the insured")
        pg.text(
            "The insured confirms that the information given is correct and complete. Cashless "
            "facility is requested for the hospitalisation described in the following parts."
        )

    def two(pg: Page) -> None:
        head(pg, "PART B — to be filled by the hospital")
        pg.fields(
            [
                ("Name of the treating Doctor", SURGEON),
                ("Nature of Illness / Disease", "Symptomatic cholelithiasis"),
                ("Date of Admission", ADMITTED),
                ("Proposed line of treatment", "Surgical management"),
            ]
        )
        pg.section("Clinical details")
        pg.text(
            "The patient presented with right upper quadrant pain. Ultrasonography confirmed "
            "cholelithiasis. Admission is advised for operative management under general anaesthesia."
        )

    def three(pg: Page) -> None:
        head(pg, "PART C — estimated cost of treatment")
        pg.table(
            ("Head", "Estimate (Rs.)"),
            [
                ("Room and nursing", "24,000.00"),
                ("Surgeon and anaesthetist", "38,000.00"),
                ("Consumables and investigations", "18,000.00"),
            ],
            widths=(260, 120),
        )
        pg.totals([("Estimated total", "80,000.00")])
        pg.signatures([Slot("Hospital authorised signatory", "Billing desk")])

    return [one, two, three]


def _hospital_bill_pages() -> list:
    """A final bill of three pages. Every page repeats the heading and the bill number."""

    def header(pg: Page) -> None:
        pg.title("CREDIT FINAL DETAILED BILL", "In-patient billing")
        pg.fields([("Bill No", "SMH/IP/2026/33417"), ("UHID", UHID), ("IPD No.", IPD)])

    def one(pg: Page) -> None:
        header(pg)
        pg.section("Room and nursing")
        pg.table(
            ("Sl.", "Particulars", "Qty", "Rate (Rs.)", "Amount (Rs.)"),
            [
                ("1", "Room rent — twin sharing", "4", "4,500.00", "18,000.00"),
                ("2", "Nursing charges", "4", "900.00", "3,600.00"),
            ],
            widths=(26, 250, 40, 70, 80),
        )

    def two(pg: Page) -> None:
        header(pg)
        pg.section("Professional charges")
        pg.table(
            ("Sl.", "Particulars", "Qty", "Rate (Rs.)", "Amount (Rs.)"),
            [
                ("3", "Surgeon charges", "1", "28,000.00", "28,000.00"),
                ("4", "Anaesthetist charges", "1", "10,000.00", "10,000.00"),
            ],
            widths=(26, 250, 40, 70, 80),
        )

    def three(pg: Page) -> None:
        header(pg)
        pg.section("Investigations and consumables")
        pg.table(
            ("Sl.", "Particulars", "Qty", "Rate (Rs.)", "Amount (Rs.)"),
            [("5", "Investigations", "1", "9,400.00", "9,400.00")],
            widths=(26, 250, 40, 70, 80),
        )
        pg.totals(
            [("Sub total", "69,000.00"), ("Tax", "0.00"), ("Discount", "0.00"), ("Net payable", "69,000.00")]
        )
        pg.signatures([Slot("Authorised signatory", "Billing desk")])

    return [one, two, three]


def _pharmacy_pages() -> list:
    """A pharmacy bill of four pages: the run that was read as four separate bills."""

    def header(pg: Page) -> None:
        pg.title("PHARMACY BILL", "Drug licence 20B/21B/PUN/2019")
        pg.fields([("Bill No", "SMH/PH/2026/90142"), ("Patient Name", PATIENT), ("IPD No.", IPD)])

    def sheet(index: int, rows):
        def build(pg: Page) -> None:
            header(pg)
            pg.section(f"Items dispensed — sheet {index}")
            pg.table(
                ("Sl.", "Item", "Batch", "Qty", "Amount (Rs.)"),
                rows,
                widths=(26, 220, 90, 40, 80),
            )

        return build

    return [
        sheet(1, [("1", "Inj. Ceftriaxone 1g", "B4471", "4", "880.00"), ("2", "Tab. Pantoprazole 40mg", "B2210", "10", "210.00")]),
        sheet(2, [("3", "Inj. Ondansetron 4mg", "B7781", "6", "360.00"), ("4", "IV set", "B1120", "2", "150.00")]),
        sheet(3, [("5", "Tab. Paracetamol 650mg", "B9930", "12", "96.00"), ("6", "Surgical gloves", "B4412", "8", "320.00")]),
        sheet(4, [("7", "Inj. Tramadol 50mg", "B5567", "3", "255.00")]),
    ]


def _discharge_pages() -> list:
    """A discharge summary of two pages that names the operation it follows."""

    def one(pg: Page) -> None:
        pg.title("DISCHARGE SUMMARY", "In-patient record")
        pg.fields([*PATIENT_FIELDS, ("Date of Discharge", DISCHARGED)])
        pg.section("Diagnosis")
        pg.text("Symptomatic cholelithiasis. The patient underwent laparoscopic cholecystectomy on 05-03-2026.")
        pg.section("Course in hospital")
        pg.text(
            "Recovery was uneventful. Oral intake was resumed on the first post-operative day and "
            "the patient was mobilised the same evening."
        )

    def two(pg: Page) -> None:
        pg.section("Advice on discharge")
        pg.bullets(
            [
                "Continue the prescribed analgesia for five days.",
                "Review in the surgical out-patient department after one week.",
                "Report earlier if there is fever or increasing pain.",
            ]
        )
        pg.signatures([Slot("Consultant", SURGEON, date=DISCHARGED)])

    return [one, two]


def _operative_note_pages() -> list:
    """An operative note written the way a surgeon writes one."""

    def one(pg: Page) -> None:
        pg.title("OPERATIVE NOTE", "Department of General Surgery")
        pg.fields(
            [
                ("Patient Name", PATIENT),
                ("UHID", UHID),
                ("Date of Surgery", "05-03-2026"),
                ("Surgeon", SURGEON),
                ("Anaesthetist", ANAESTHETIST),
            ]
        )
        pg.section("Pre-operative diagnosis")
        pg.text("Symptomatic cholelithiasis.")
        pg.section("Procedure performed")
        pg.text("Laparoscopic cholecystectomy under general anaesthesia.")
        pg.section("Findings")
        pg.text("A distended gall bladder with multiple calculi. No evidence of common bile duct dilatation.")

    def two(pg: Page) -> None:
        pg.section("Technique")
        pg.text(
            "Four ports were placed. The cystic duct and artery were identified, clipped and divided. "
            "The gall bladder was dissected from the liver bed and retrieved through the umbilical port."
        )
        pg.section("Estimated blood loss")
        pg.text("Approximately 30 ml.")
        pg.section("Specimen")
        pg.text("Gall bladder with calculi, sent for histopathology.")
        pg.section("Post-operative diagnosis")
        pg.text("Chronic cholecystitis with cholelithiasis.")
        pg.section("Complications")
        pg.text("None.")
        pg.signatures([Slot("Operating surgeon", SURGEON, date="05-03-2026")])

    return [one, two]


def _anaesthesia_pages() -> list:
    def one(pg: Page) -> None:
        pg.title("ANAESTHESIA RECORD", "Department of Anaesthesiology")
        pg.fields(
            [
                ("Patient Name", PATIENT),
                ("UHID", UHID),
                ("Anaesthetist", ANAESTHETIST),
                ("Technique", "General anaesthesia with endotracheal intubation"),
            ]
        )
        pg.section("Intra-operative monitoring")
        pg.table(
            ("Time", "Pulse", "Blood pressure", "SpO2"),
            [("09:10", "82", "124/78", "99%"), ("09:40", "78", "118/74", "100%")],
            widths=(80, 60, 110, 80),
        )
        pg.signatures([Slot("Anaesthetist", ANAESTHETIST)])

    return [one]


def _lab_pages() -> list:
    def one(pg: Page) -> None:
        pg.title("LABORATORY REPORT", "Haematology")
        pg.fields([("Patient Name", PATIENT), ("UHID", UHID), ("Sample ID", "LAB/2026/55120")])
        pg.table(
            ("Test", "Result", "Unit", "Reference Range"),
            [("Haemoglobin", "12.8", "g/dL", "12.0 - 15.0"), ("Total leucocyte count", "9,400", "/uL", "4,000 - 11,000")],
            widths=(150, 70, 70, 110),
        )

    return [one]


def _second_lab_pages() -> list:
    """A second report of the same type, immediately after the first."""

    def one(pg: Page) -> None:
        pg.title("LABORATORY REPORT", "Biochemistry")
        pg.fields([("Patient Name", PATIENT), ("UHID", UHID), ("Sample ID", "LAB/2026/55121")])
        pg.table(
            ("Test", "Result", "Unit", "Reference Range"),
            [("Serum creatinine", "0.8", "mg/dL", "0.6 - 1.1"), ("Random blood sugar", "98", "mg/dL", "70 - 140")],
            widths=(150, 70, 70, 110),
        )

    return [one]


def _radiology_pages() -> list:
    def one(pg: Page) -> None:
        pg.title("ULTRASONOGRAPHY REPORT", "Department of Radiology")
        pg.fields([("Patient Name", PATIENT), ("UHID", UHID), ("Study", "USG abdomen and pelvis")])
        pg.section("Impression")
        pg.text("Multiple calculi within a distended gall bladder. The common bile duct is not dilated.")

    return [one]


def _ambiguous_pages() -> list:
    """A continuation sheet that names nothing: the honest answer is that it is not known."""

    def one(pg: Page) -> None:
        pg.text(
            "Continued from the preceding sheet. The patient remained comfortable through the "
            "night. Vitals were within normal limits and intake and output were adequate. The "
            "dressing was dry and intact on inspection."
        )
        pg.text(
            "The attending team reviewed the patient in the morning round and advised that the "
            "existing plan be continued without change."
        )

    return [one]


# --- the packet -------------------------------------------------------------------------------


def _documents() -> list[LabelledDocument]:
    """The packet, in the order a hospital assembles one.

    Deliberately absent: the informed consent. A document that is genuinely missing has to keep
    being reported as missing, whatever the segmenter does with the rest.
    """
    return [
        LabelledDocument("preauth_request", _preauth_pages(), "pre-authorisation request", letterhead=INSURER, doc_ref="Form MHI/PA/01"),
        LabelledDocument("operative_note", _operative_note_pages(), "operative note", doc_ref="Form SMH/OT/02"),
        LabelledDocument("anaesthesia_record", _anaesthesia_pages(), "anaesthesia record", doc_ref="Form SMH/AN/03"),
        LabelledDocument("discharge_summary", _discharge_pages(), "discharge summary", doc_ref="Form SMH/DS/04"),
        LabelledDocument("lab_report", _lab_pages(), "laboratory report", letterhead=LAB, doc_ref="Form SMH/LAB/05"),
        LabelledDocument("lab_report", _second_lab_pages(), "second laboratory report", letterhead=LAB, doc_ref="Form SMH/LAB/05"),
        LabelledDocument("investigation_report", _radiology_pages(), "radiology report", doc_ref="Form SMH/RAD/06"),
        LabelledDocument("hospital_bill", _hospital_bill_pages(), "hospital bill", doc_ref="Form SMH/BIL/07"),
        LabelledDocument("pharmacy_bill", _pharmacy_pages(), "pharmacy bill", doc_ref="Form SMH/PH/08"),
        LabelledDocument("other", _ambiguous_pages(), "unnamed continuation sheet", expect_unclassified=True, doc_ref=""),
    ]


def build() -> tuple[bytes, list[LabelledDocument]]:
    """The packet as one PDF, and what every page of it is.

    Each document is rendered on its own and then merged, which is how a packet is actually made:
    separate documents scanned or exported one after another into a single file.
    """
    documents = _documents()
    merged = pymupdf.open()
    try:
        for document in documents:
            data = render_pdf(
                document.pages,
                letterhead=document.letterhead,
                title=document.label,
                doc_ref=document.doc_ref,
                page_numbering=document.page_numbering,
            )
            document.first_page = merged.page_count + 1
            with pymupdf.open("pdf", data) as source:
                merged.insert_pdf(source)
            document.last_page = merged.page_count
        return merged.tobytes(), documents
    finally:
        merged.close()


def ground_truth() -> dict:
    """Every page of the packet, labelled: its document, its type and its role in that document."""
    _, documents = build()
    pages: dict[int, dict] = {}
    for index, document in enumerate(documents):
        for offset, number in enumerate(document.page_numbers):
            pages[number] = {
                "document_index": index,
                "doc_type": document.doc_type,
                "role": DOCUMENT_START if offset == 0 else CONTINUATION,
                "expect_unclassified": document.expect_unclassified,
            }
    return {
        "documents": documents,
        "pages": pages,
        "page_count": max(pages) if pages else 0,
    }


__all__ = [
    "CONTINUATION",
    "DOCUMENT_START",
    "LabelledDocument",
    "build",
    "ground_truth",
]

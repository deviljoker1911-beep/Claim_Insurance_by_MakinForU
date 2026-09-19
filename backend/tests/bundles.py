"""Building claim bundles out of the deterministic demo documents.

A claim packet is one PDF holding many documents. These helpers merge documents that the demo
generator already produces into one file, so a bundle used in a test is made of exactly the same
pages as the documents it was built from — which is what makes the two comparable.

No real claim file is used anywhere. The client bundles that exposed the gap were read once during
development and deleted; what stands in for them here is built from the synthetic demo set.
"""

from __future__ import annotations

import pymupdf

from tests.conftest import REPO_DEMO_DATA, manifest, manifest_entry

# The demo documents in the order a claims desk would assemble them for one admission.
FULL_CLAIM = (
    "01_Patient_ID.png",
    "02_Admission_Form.pdf",
    "03_Doctor_Consultation.pdf",
    "04_PreOp_Assessment.pdf",
    "05_Anaesthesia_Assessment.pdf",
    "06_Discharge_Summary.pdf",
    "07_Prescription.pdf",
    "08_Nursing_Record.pdf",
    "09_USG_Abdomen_Scan.jpg",
    "10_Lab_Report.pdf",
    "11_Lab_Report_copy.pdf",
    "12_Main_Hospital_Bill.pdf",
    "13_Pharmacy_Bill.pdf",
    "14_OT_Bill.pdf",
    "15_Implant_Invoice.pdf",
    "16_Consent_Form.pdf",
    "scan_0042.pdf",
    "Anaesthesia_Record.pdf",
)


def demo_document_names() -> list[str]:
    """Every demo document, in the order the sets declare them."""
    return [
        entry["filename"]
        for set_name in ("initial", "operative_note", "anaesthesia_record")
        for entry in manifest()["sets"][set_name]
    ]


def bundle_of(*filenames: str) -> tuple[bytes, dict[str, tuple[int, int]]]:
    """One PDF holding the named demo documents, and the pages each of them landed on.

    An image document is converted to a PDF page so it can sit in the same file, which is what a
    scanner or a phone-photographed page does on its way into a claim packet.
    """
    merged = pymupdf.open()
    spans: dict[str, tuple[int, int]] = {}
    try:
        for name in filenames:
            entry = manifest_entry(name)
            path = REPO_DEMO_DATA / entry["path"]
            first = merged.page_count + 1
            if entry["media_type"] == "application/pdf":
                with pymupdf.open(path) as source:
                    merged.insert_pdf(source)
            else:
                image = pymupdf.open(path)
                try:
                    as_pdf = image.convert_to_pdf()
                finally:
                    image.close()
                with pymupdf.open("pdf", as_pdf) as source:
                    merged.insert_pdf(source)
            spans[name] = (first, merged.page_count)
        return merged.tobytes(), spans
    finally:
        merged.close()


def full_claim_bundle() -> tuple[bytes, dict[str, tuple[int, int]]]:
    """Every document of the demo claim, merged into one file."""
    return bundle_of(*FULL_CLAIM)


def repeated(name: str, times: int = 2) -> tuple[bytes, dict[str, tuple[int, int]]]:
    """One demo document placed in a file more than once."""
    merged = pymupdf.open()
    entry = manifest_entry(name)
    path = REPO_DEMO_DATA / entry["path"]
    try:
        for _ in range(times):
            with pymupdf.open(path) as source:
                merged.insert_pdf(source)
        return merged.tobytes(), {name: (1, merged.page_count)}
    finally:
        merged.close()

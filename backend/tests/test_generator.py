"""The synthetic demo generator: determinism, committed data, and the seeded issues."""

import hashlib
import io
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pymupdf
import pytest
from PIL import Image, ImageFilter, ImageStat

from app.demo_gen import templates
from app.demo_gen.degrade import rasterize_first_page
from app.demo_gen.generate import DOCUMENTS, MANIFEST_NAME, generate_in_memory
from app.demo_gen.profile import (
    IMPLANT,
    MAIN_BILL_LINES,
    NOTICE,
    OT_BILL_LINES,
    PHARMACY_LINES,
    bill_total,
    inr,
    rupees_in_words,
)
from tests.conftest import REPO_DEMO_DATA, manifest

BACKEND_DIR = Path(__file__).resolve().parents[1]
INITIAL_ORDER = [
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
]


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope="module")
def generated():
    return generate_in_memory()


def pdf_text(data: bytes) -> list[str]:
    with pymupdf.open(stream=data, filetype="pdf") as document:
        return [page.get_text() for page in document]


def demo_file(name: str) -> bytes:
    entry = next(e for entries in manifest()["sets"].values() for e in entries if e["filename"] == name)
    return (REPO_DEMO_DATA / entry["path"]).read_bytes()


# --- Determinism --------------------------------------------------------------------------------


def test_two_in_process_runs_are_byte_identical(generated):
    second = generate_in_memory()
    assert list(second.files) == list(generated.files)
    for path, content in generated.files.items():
        assert sha256(second.files[path]) == sha256(content), path
    assert second.manifest_bytes == generated.manifest_bytes


def test_two_separate_cli_runs_produce_identical_hashes(tmp_path):
    hashes = []
    for run in ("run1", "run2"):
        out = tmp_path / run
        subprocess.run(
            [sys.executable, "-m", "app.demo_gen", "--out", str(out)],
            cwd=BACKEND_DIR,
            check=True,
            capture_output=True,
            env={**os.environ, "RL_invariant": "1"},
        )
        hashes.append({p.relative_to(out).as_posix(): sha256(p.read_bytes()) for p in sorted(out.rglob("*")) if p.is_file()})
    assert len(hashes[0]) == 19  # 18 documents + manifest
    assert hashes[0] == hashes[1]


def test_generated_output_matches_the_committed_demo_data(generated):
    for path, content in generated.files.items():
        assert sha256((REPO_DEMO_DATA / path).read_bytes()) == sha256(content), path
    assert (REPO_DEMO_DATA / MANIFEST_NAME).read_bytes() == generated.manifest_bytes


def test_cli_check_mode_verifies_the_committed_data():
    result = subprocess.run(
        [sys.executable, "-m", "app.demo_gen", "--check", "--out", str(REPO_DEMO_DATA)],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: 18 documents checked" in result.stdout


def test_manifest_hashes_match_the_files():
    for entries in manifest()["sets"].values():
        for entry in entries:
            content = (REPO_DEMO_DATA / entry["path"]).read_bytes()
            assert sha256(content) == entry["sha256"], entry["filename"]
            assert len(content) == entry["size_bytes"]


def test_pdf_metadata_is_fixed_and_carries_no_document_type(generated):
    for spec in DOCUMENTS:
        if spec.media_type != "application/pdf":
            continue
        with pymupdf.open(stream=generated.files[spec.path], filetype="pdf") as document:
            meta = document.metadata
        assert meta["creationDate"] == meta["modDate"] == "D:20000101000000+00'00'"
        # A duplicate is a byte-for-byte copy, so it keeps its source document's title.
        assert meta["title"] == Path(spec.copy_of or spec.filename).stem
        assert meta["subject"] == NOTICE


# --- Pack structure -------------------------------------------------------------------------------


def test_initial_pack_has_the_16_specified_documents_in_order():
    sets = manifest()["sets"]
    assert [e["filename"] for e in sets["initial"]] == INITIAL_ORDER
    assert [e["path"] for e in sets["operative_note"]] == ["later/scan_0042.pdf"]
    assert [e["path"] for e in sets["anaesthesia_record"]] == ["later/Anaesthesia_Record.pdf"]
    assert manifest()["synthetic"] is True
    assert manifest()["claim"]["patient_name"] == "Rajesh Sharma"


def test_every_page_carries_the_synthetic_notice(generated):
    for spec in DOCUMENTS:
        if spec.media_type == "application/pdf":
            pages = pdf_text(generated.files[spec.path])
            assert pages, spec.filename
            for number, text in enumerate(pages, 1):
                assert NOTICE in text, f"{spec.filename} page {number}"
    # Image documents are rasterised from a source page that carries the notice in its footer.
    for source in (templates.patient_id_card(), templates.usg_report()):
        assert all(NOTICE in text for text in pdf_text(source))


def test_identifiers_are_fictional(generated):
    aadhaar_like = re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")
    pan_like = re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b")
    email = re.compile(r"[\w.]+@[\w.-]+")
    for spec in DOCUMENTS:
        if spec.media_type != "application/pdf":
            continue
        text = "\n".join(pdf_text(generated.files[spec.path]))
        assert not aadhaar_like.search(text), spec.filename
        assert not pan_like.search(text), spec.filename
        assert all(address.endswith(".example") for address in email.findall(text)), spec.filename


# --- Seeded issues ---------------------------------------------------------------------------------


def _lines(name: str) -> set[str]:
    return {line.strip() for text in pdf_text(demo_file(name)) for line in text.splitlines()}


def test_operative_note_and_anaesthesia_record_are_missing_from_the_initial_pack():
    for name in INITIAL_ORDER:
        if name.endswith(".pdf"):
            assert "OPERATIVE NOTE" not in _lines(name), name
            assert "ANAESTHESIA RECORD" not in _lines(name), name
    assert "OPERATIVE NOTE" in _lines("scan_0042.pdf")
    assert "ANAESTHESIA RECORD" in _lines("Anaesthesia_Record.pdf")


def test_patient_name_mismatch_on_pharmacy_bill():
    text = "\n".join(pdf_text(demo_file("13_Pharmacy_Bill.pdf")))
    assert "Patient Name: Rajesh K." in text
    assert "Rajesh Sharma" not in text
    assert "UHID-123456" in text
    for name in ("02_Admission_Form.pdf", "06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf"):
        assert "Patient Name: Rajesh Sharma" in "\n".join(pdf_text(demo_file(name))), name


def test_duplicate_bill_number_on_main_and_ot_bills():
    documents_with_number = [
        name for name in INITIAL_ORDER if name.endswith(".pdf") and "CCH/IP/2026/08812" in "\n".join(pdf_text(demo_file(name)))
    ]
    assert documents_with_number == ["12_Main_Hospital_Bill.pdf", "14_OT_Bill.pdf"]


def test_exactly_one_billing_arithmetic_error():
    inconsistent = [line for line in MAIN_BILL_LINES if line.amount != line.expected_amount]
    assert [(line.description.split(" (")[0], line.qty, line.rate, line.amount) for line in inconsistent] == [
        ("Room Rent - Twin Sharing", 4, Decimal("4500.00"), Decimal("20000.00"))
    ]
    for lines in (OT_BILL_LINES, PHARMACY_LINES):
        assert all(line.amount == line.expected_amount for line in lines)

    text = pdf_text(demo_file("12_Main_Hospital_Bill.pdf"))[0]
    assert "4,500.00" in text and "20,000.00" in text
    assert "18,000.00" in text  # only as the OT charges line, not as a corrected room rent
    subtotal = bill_total(MAIN_BILL_LINES)
    assert subtotal == Decimal("114360.00")  # the sum of the printed amounts
    assert text.count(inr(subtotal)) == 2  # sub total and net payable
    assert rupees_in_words(subtotal) == "Rupees One Lakh Fourteen Thousand Three Hundred Sixty Only"


def test_bill_breakups_agree_with_the_main_bill():
    by_prefix = {line.description.split(" (")[0]: line.amount for line in MAIN_BILL_LINES}
    assert bill_total(OT_BILL_LINES) == by_prefix["Operation Theatre Charges"]
    assert bill_total(PHARMACY_LINES) == by_prefix["Pharmacy & Consumables"]
    assert IMPLANT.amount == by_prefix["Implants"]


def test_duplicate_lab_report_is_byte_identical():
    assert demo_file("10_Lab_Report.pdf") == demo_file("11_Lab_Report_copy.pdf")
    entry = next(e for e in manifest()["sets"]["initial"] if e["filename"] == "11_Lab_Report_copy.pdf")
    assert entry["duplicate_of"] == "10_Lab_Report.pdf"


def _ink_curves_above(page: pymupdf.Page, label: str) -> list:
    anchor = page.search_for(label)[0]
    region = pymupdf.Rect(anchor.x0 - 2, anchor.y0 - 42, anchor.x0 + 200, anchor.y0 - 3)
    return [
        d for d in page.get_drawings()
        if any(item[0] == "c" for item in d["items"]) and pymupdf.Rect(d["rect"]).intersects(region)
    ]


def test_patient_signature_is_missing_on_the_consent_form():
    with pymupdf.open(stream=demo_file("16_Consent_Form.pdf"), filetype="pdf") as document:
        page = document[0]
        assert _ink_curves_above(page, "Signature of Patient / Guardian") == []
        for signed in ("Signature of Witness", "Signature of Surgeon", "Signature of Anaesthetist"):
            assert _ink_curves_above(page, signed), signed


def _concealed_text(page: pymupdf.Page) -> list[str]:
    fills = [
        d for d in page.get_drawings()
        if d.get("fill") is not None and min(d["fill"]) >= 0.97 and (d.get("fill_opacity") or 1.0) >= 0.99
    ]
    hidden = []
    for span in page.get_texttrace():
        chars = [
            ch for ch in span["chars"]
            if chr(ch[0]).strip() and any(
                d["seqno"] > span["seqno"]
                and (pymupdf.Rect(ch[3]) & d["rect"]).get_area() >= 0.6 * pymupdf.Rect(ch[3]).get_area()
                for d in fills
            )
        ]
        if chars:
            hidden.append("".join(chr(ch[0]) for ch in chars))
    return hidden


def test_implant_rate_is_concealed_and_overwritten():
    with pymupdf.open(stream=demo_file("15_Implant_Invoice.pdf"), filetype="pdf") as document:
        page = document[0]
        assert _concealed_text(page) == ["1,000.00"]
        text = page.get_text()
    assert "1,100.00" in text and "6,600.00" in text
    assert IMPLANT.qty * IMPLANT.rate == IMPLANT.amount


def test_no_other_document_contains_concealed_text():
    for name in INITIAL_ORDER + ["scan_0042.pdf", "Anaesthesia_Record.pdf"]:
        if name.endswith(".pdf") and name != "15_Implant_Invoice.pdf":
            with pymupdf.open(stream=demo_file(name), filetype="pdf") as document:
                assert all(_concealed_text(page) == [] for page in document), name


def _sharpness(image: Image.Image) -> float:
    edges = image.convert("L").filter(ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128))
    return ImageStat.Stat(edges).var[0]


def test_usg_scan_is_low_resolution_and_blurred():
    scan = Image.open(io.BytesIO(demo_file("09_USG_Abdomen_Scan.jpg")))
    assert scan.format == "JPEG"
    assert scan.size == (794, 1123)
    assert tuple(round(v) for v in scan.info["dpi"]) == (96, 96)
    clean = rasterize_first_page(templates.usg_report(), dpi=96, gray=True)
    assert clean.size == scan.size
    assert _sharpness(scan) < 0.5 * _sharpness(clean)


def test_patient_id_card_is_a_clean_high_resolution_image():
    card = Image.open(io.BytesIO(demo_file("01_Patient_ID.png")))
    assert card.format == "PNG"
    assert card.size == (1012, 638)
    assert tuple(round(v) for v in card.info["dpi"]) == (300, 300)
    source_text = pdf_text(templates.patient_id_card())[0]
    assert "RAJESH SHARMA" in source_text
    assert "DTPA-MEM-0099812" in source_text


def test_procedure_is_written_with_different_synonyms():
    assert "Planned procedure: Lap. Cholecystectomy" in pdf_text(demo_file("03_Doctor_Consultation.pdf"))[0]
    assert "Planned Procedure: Lap Chole" in pdf_text(demo_file("04_PreOp_Assessment.pdf"))[0]
    assert "Procedure: Laparoscopic Cholecystectomy" in pdf_text(demo_file("06_Discharge_Summary.pdf"))[0]


# --- Later documents -----------------------------------------------------------------------------


def test_operative_note_records_procedure_and_implants():
    pages = pdf_text(demo_file("scan_0042.pdf"))
    text = "\n".join(pages)
    assert "Procedure Performed: Laparoscopic Cholecystectomy" in text
    assert "Date of Surgery: 13-01-2026" in text
    assert "Hem-o-lok polymer ligating clips (6 clips applied in total)" in text
    assert "Hem-o-lok Polymer Ligating Clips (ML)" in pages[1]
    assert "HL-44710" in pages[1]
    with pymupdf.open(stream=demo_file("scan_0042.pdf"), filetype="pdf") as document:
        assert document.metadata["title"] == "scan_0042"


def test_anaesthesia_record_is_distinct_from_the_pre_anaesthetic_check_up():
    record = "\n".join(pdf_text(demo_file("Anaesthesia_Record.pdf")))
    check_up = "\n".join(pdf_text(demo_file("05_Anaesthesia_Assessment.pdf")))
    assert "ANAESTHESIA RECORD" in record and "Intra-operative" in record
    assert "Induction Time: 10:05" in record
    assert "PRE-ANAESTHETIC CHECK-UP (PAC)" in check_up
    assert "ANAESTHESIA RECORD" not in check_up

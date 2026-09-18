"""Page-level processing: text layer, covered text, rendering and quality measurements."""

import hashlib

import numpy as np
import pymupdf
import pytest

from app.processing import ocr as ocr_module
from app.processing.pipeline import ProcessingError, process_file
from app.processing.quality import analyse_page, edge_steepness, skew_degrees
from app.processing.render import estimate_image_dpi
from app.processing.text import extract_page_text
from app.processing.types import Word, build_lines
from tests.conftest import demo_path, manifest_entry


def run(filename: str, **overrides):
    path = demo_path(filename)
    entry = manifest_entry(filename)
    return process_file(
        path,
        content_type=overrides.get("content_type", entry["media_type"]),
        sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        claim_id=overrides.get("claim_id", "processing-test"),
        document_id=overrides.get("document_id", filename.split(".")[0]),
    )


# --- text layer and covered text ---------------------------------------------------------


def test_covered_text_is_separated_from_visible_text():
    """The implant invoice has an amount painted over with white and a new one written on top."""
    with pymupdf.open(demo_path("15_Implant_Invoice.pdf")) as document:
        page = document[0]
        lines, concealed = extract_page_text(page)
        raw_text = page.get_text("text")

    visible = "\n".join(line.text for line in lines)
    assert "1,000.00" in raw_text, "the covered value is in the file"
    assert "1,000.00" not in visible, "but it must not appear in the visible text"
    assert "1,100.00" in visible, "the value a reader sees is kept"
    assert [span.text for span in concealed] == ["1,000.00"]
    assert concealed[0].coverage >= 0.6


def test_documents_without_covered_text_report_none(demo_results):
    for filename, result in demo_results.items():
        if filename == "15_Implant_Invoice.pdf":
            continue
        assert result.content.concealed == [], f"{filename} reported covered text unexpectedly"


def test_covered_text_is_reported_as_a_review_signal(demo_results):
    flags = {flag["code"]: flag for flag in demo_results["15_Implant_Invoice.pdf"].quality_flags}
    assert "concealed_text" in flags
    assert flags["concealed_text"]["severity"] == "review"
    assert flags["concealed_text"]["pages"] == [1]
    # The wording never accuses anyone; a human decides what it means.
    detail = flags["concealed_text"]["detail"].lower()
    assert "human verification required" in detail
    assert not any(word in detail for word in ("fraud", "forged", "fake"))


def test_lines_keep_column_gaps_as_double_spaces():
    words = [
        Word(text="Patient", bbox=(10, 10, 40, 20), baseline=20),
        Word(text="Name:", bbox=(42, 10, 70, 20), baseline=20),
        Word(text="Rajesh", bbox=(72, 10, 100, 20), baseline=20),
        Word(text="UHID:", bbox=(300, 10, 330, 20), baseline=20),
    ]
    line = build_lines(words)[0]
    assert line.text == "Patient Name: Rajesh  UHID:"
    assert [cell.text for cell in line.cells()] == ["Patient Name: Rajesh", "UHID:"]


# --- rendering ---------------------------------------------------------------------------


def test_every_page_is_rendered_and_the_original_is_untouched():
    path = demo_path("06_Discharge_Summary.pdf")
    before = path.read_bytes()
    result = run("06_Discharge_Summary.pdf")
    assert len(result.content.pages) == 3
    for page in result.content.pages:
        assert page.image_path and page.image_path.endswith(f"p{page.number:04d}.png")
        assert page.image_width and page.image_width > 800
    assert path.read_bytes() == before


def test_page_numbers_are_sequential_and_start_at_one(demo_results):
    for filename, result in demo_results.items():
        numbers = [page.number for page in result.content.pages]
        assert numbers == list(range(1, len(numbers) + 1)), filename


# --- quality ------------------------------------------------------------------------------


def test_degraded_scan_is_flagged_from_the_image_not_the_filename(demo_results):
    """09_USG_Abdomen_Scan.jpg is a soft 96 dpi scan, rotated slightly."""
    result = demo_results["09_USG_Abdomen_Scan.jpg"]
    codes = {flag["code"] for flag in result.quality_flags}
    assert "blurred_page" in codes
    assert {"low_resolution", "very_low_resolution"} & codes
    assert "skewed_page" in codes or "severe_skew" in codes
    page = result.content.pages[0]
    assert page.effective_dpi is not None and page.effective_dpi < 150
    assert page.quality["edge_steepness"] < 80
    assert abs(page.quality["skew_degrees"]) >= 0.75


def test_clean_documents_are_not_flagged_for_quality(demo_results):
    for filename in ("02_Admission_Form.pdf", "12_Main_Hospital_Bill.pdf", "scan_0042.pdf"):
        codes = {flag["code"] for flag in demo_results[filename].quality_flags}
        assert not codes & {"blurred_page", "low_resolution", "very_low_resolution", "skewed_page", "blank_page"}, (
            f"{filename} was flagged: {codes}"
        )


def test_quality_measures_are_resolution_independent():
    """A clean page stays sharp by this measure whether it is scanned at 96 or 200 dpi."""
    with pymupdf.open(demo_path("10_Lab_Report.pdf")) as document:
        page = document[0]
        readings = []
        for dpi in (96, 200):
            pixmap = page.get_pixmap(dpi=dpi, colorspace=pymupdf.csGRAY)
            gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)
            readings.append(edge_steepness(gray, dpi))
    assert all(value > 140 for value in readings), readings
    assert max(readings) / min(readings) < 1.6


def test_blank_page_is_detected():
    blank = np.full((1754, 1240), 255, dtype=np.uint8)
    quality = analyse_page(blank, effective_dpi=150, scanned=True, char_count=0, word_count=0)
    codes = {flag["code"] for flag in quality.flags}
    assert "blank_page" in codes
    # A blank page is not also reported as blurred or cropped.
    assert not codes & {"blurred_page", "cropped_page", "soft_focus"}


def test_cropped_page_is_detected_when_content_runs_off_the_sheet():
    with pymupdf.open(demo_path("12_Main_Hospital_Bill.pdf")) as document:
        pixmap = document[0].get_pixmap(dpi=150, colorspace=pymupdf.csGRAY)
        gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)
    intact = analyse_page(gray, effective_dpi=150, scanned=True, char_count=2000, word_count=400)
    assert "cropped_page" not in {flag["code"] for flag in intact.flags}

    # Cut the margins off: text now reaches two edges.
    cropped = gray[260:-260, 150:-150]
    flags = {flag["code"] for flag in analyse_page(cropped, effective_dpi=150, scanned=True, char_count=2000, word_count=400).flags}
    assert "cropped_page" in flags


def test_skew_is_measured_on_a_rotated_page():
    import cv2

    with pymupdf.open(demo_path("10_Lab_Report.pdf")) as document:
        pixmap = document[0].get_pixmap(dpi=120, colorspace=pymupdf.csGRAY)
        gray = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(pixmap.height, pixmap.width)
    assert abs(skew_degrees(gray) or 0) < 0.3
    height, width = gray.shape
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), 2.0, 1.0)
    rotated = cv2.warpAffine(gray, matrix, (width, height), borderValue=255)
    measured = skew_degrees(rotated)
    assert measured is not None and 1.5 <= abs(measured) <= 2.5


def test_vector_pages_are_not_judged_on_scan_resolution(demo_results):
    page = demo_results["02_Admission_Form.pdf"].content.pages[0]
    assert page.quality["scanned"] is False
    assert page.effective_dpi is None
    assert "edge_steepness" not in page.quality


def test_estimate_image_dpi_uses_the_a4_fit():
    assert 145 <= estimate_image_dpi(1240, 1754) <= 152
    assert 95 <= estimate_image_dpi(794, 1123) <= 99


# --- OCR ----------------------------------------------------------------------------------


def test_image_documents_go_through_ocr(demo_results):
    for filename in ("01_Patient_ID.png", "09_USG_Abdomen_Scan.jpg"):
        result = demo_results[filename]
        page = result.content.pages[0]
        assert page.text_source == "ocr"
        assert page.ocr_engine in {"rapidocr", "demo_fixture"}
        assert page.ocr_confidence is not None
        assert len(page.words) > 20


def test_pdf_pages_with_a_text_layer_do_not_run_ocr(demo_results):
    result = demo_results["12_Main_Hospital_Bill.pdf"]
    assert result.content.text_source == "pdf_text"
    assert result.content.ocr_engine is None
    assert all(page.ocr_engine is None for page in result.content.pages)


def test_demo_fixture_engine_is_used_when_ocr_is_unavailable(monkeypatch):
    """With no OCR engine installed the demo still reads its image documents, clearly labelled."""
    monkeypatch.setattr(ocr_module.RapidOcrEngine, "installed", staticmethod(lambda: False))
    result = run("01_Patient_ID.png", document_id="fixture-card")
    page = result.content.pages[0]
    assert page.ocr_engine == "demo_fixture"
    assert result.classification.doc_type == "patient_id"
    assert any("fixture" in warning.lower() for warning in result.warnings)
    values = {field.key: field.value for field in result.fields}
    assert values["cover.member_id"] == "DTPA-MEM-0099812"


def test_fixture_and_real_ocr_agree_on_the_document_type(monkeypatch):
    monkeypatch.setattr(ocr_module.RapidOcrEngine, "installed", staticmethod(lambda: False))
    fixture = run("09_USG_Abdomen_Scan.jpg", document_id="fixture-usg")
    assert fixture.content.ocr_engine == "demo_fixture"
    assert fixture.classification.doc_type == "investigation_report"
    # The quality signals come from the pixels, so they do not depend on the text source.
    assert "blurred_page" in {flag["code"] for flag in fixture.quality_flags}


def test_missing_fixture_and_no_engine_degrades_to_no_text(monkeypatch, tmp_path):
    monkeypatch.setattr(ocr_module.RapidOcrEngine, "installed", staticmethod(lambda: False))
    monkeypatch.setattr(ocr_module.DemoFixtureEngine, "fixtures_dir", staticmethod(lambda: tmp_path))
    result = run("01_Patient_ID.png", document_id="no-ocr-card")
    page = result.content.pages[0]
    assert page.text_source == "none"
    assert result.classification.doc_type == "other"
    assert any("OCR was not available" in warning for warning in result.warnings)
    assert "no_text_recovered" in {flag["code"] for flag in result.quality_flags}


def test_ocr_can_be_disabled(monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "ocr_engine", "none")
    with pytest.raises(ocr_module.OcrUnavailable):
        ocr_module.recognise_page(np.zeros((50, 50, 3), dtype=np.uint8), sha256="x", page_number=1)


# --- signatures ---------------------------------------------------------------------------


def test_blank_consent_signature_area_is_detected(demo_results):
    result = demo_results["16_Consent_Form.pdf"]
    slots = {slot["key"]: slot for slot in result.signatures["slots"] if slot["key"]}
    assert slots["patient_guardian"]["found"] is True
    assert slots["patient_guardian"]["signed"] is False
    assert slots["witness"]["signed"] is True
    assert slots["surgeon"]["signed"] is True
    codes = [flag for flag in result.quality_flags if flag["code"] == "signature_area_blank"]
    assert len(codes) == 1
    assert "Patient / guardian" in codes[0]["detail"]


def test_a_signature_slot_points_at_an_area_a_reader_can_be_shown(demo_results):
    """Evidence a person cannot see is not evidence.

    An unsigned slot used to be reported at the signature rule itself, which is a line: the box
    had no height, so highlighting it showed nothing at all. An unsigned slot points at the area
    that was searched for the signature — where the system looked and found nothing.
    """
    checked = 0
    for filename, result in demo_results.items():
        for slot in result.signatures["slots"]:
            box = slot["bbox"]
            if box is None:
                continue
            checked += 1
            assert len(box) == 4, (filename, slot["caption"])
            assert all(0.0 <= value <= 1.0 for value in box), (filename, slot["caption"], box)
            assert box[2] > box[0], f"{filename} {slot['caption']}: the box has no width: {box}"
            assert box[3] > box[1], f"{filename} {slot['caption']}: the box has no height: {box}"
    assert checked > 0, "the demo documents are expected to have signature areas"


def test_the_area_searched_for_an_unsigned_signature_is_a_band_not_a_page(demo_results):
    """The area reported for a blank slot is the strip a signature would occupy.

    It has to be big enough for a reader to see and small enough to mean something: pointing at
    most of the page would tell a reviewer nothing about where the signature should have been.
    """
    consent = demo_results["16_Consent_Form.pdf"].signatures["slots"]
    blank = next(slot for slot in consent if slot["key"] == "patient_guardian")
    assert blank["signed"] is False
    left, top, right, bottom = blank["bbox"]
    assert 0.0 < bottom - top < 0.12, f"a signature area is a band: {blank['bbox']}"
    assert 0.0 < right - left < 0.6, f"a signature area is not the width of the page: {blank['bbox']}"


def test_signed_documents_have_no_blank_signature_signal(demo_results):
    for filename in ("02_Admission_Form.pdf", "scan_0042.pdf", "Anaesthesia_Record.pdf", "06_Discharge_Summary.pdf"):
        codes = {flag["code"] for flag in demo_results[filename].quality_flags}
        assert "signature_area_blank" not in codes, filename


def test_rules_stamps_and_graphics_are_not_counted_as_signatures(demo_results):
    """A stamp is reported as a stamp; the signature verdict comes from the ink above the rule."""
    consent = demo_results["16_Consent_Form.pdf"].signatures["slots"]
    patient = next(slot for slot in consent if slot["key"] == "patient_guardian")
    assert patient["signed"] is False
    surgeon = next(slot for slot in consent if slot["key"] == "surgeon")
    assert surgeon["stamp_detected"] is True

    # The bill's table borders and its letterhead graphics must not create signature areas.
    bill = demo_results["12_Main_Hospital_Bill.pdf"].signatures["slots"]
    assert all(slot["caption"] is None or len(slot["caption"]) <= 48 for slot in bill)
    assert {slot["caption"] for slot in bill if slot["caption"]} <= {"Prepared by", "Authorised Signatory"}


def test_signature_detection_reports_when_it_cannot_look(demo_results):
    """Signature ink cannot be judged on a flat scan, and that is said rather than guessed."""
    signatures = demo_results["09_USG_Abdomen_Scan.jpg"].signatures
    assert signatures["method"] == "unavailable_scanned_page"
    assert signatures["pages_not_analysed"] == [1]
    slot = signatures["slots"][0]
    assert slot["checked"] is False
    assert slot["signed"] is None
    assert "scan" in slot["detail"].lower()


# --- failure handling ---------------------------------------------------------------------


def test_a_malformed_pdf_fails_with_a_clear_message(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.4\nnot really a pdf\n%%EOF")
    with pytest.raises(ProcessingError) as error:
        process_file(
            broken, content_type="application/pdf", sha256="0" * 64, claim_id="c", document_id="broken"
        )
    assert "PDF" in str(error.value)


def test_a_missing_original_fails_with_a_clear_message(tmp_path):
    with pytest.raises(ProcessingError, match="missing from storage"):
        process_file(
            tmp_path / "gone.pdf", content_type="application/pdf", sha256="0" * 64, claim_id="c", document_id="gone"
        )


def test_an_unsupported_content_type_is_rejected(tmp_path):
    path = tmp_path / "notes.txt"
    path.write_text("hello")
    with pytest.raises(ProcessingError, match="Unsupported"):
        process_file(path, content_type="text/plain", sha256="0" * 64, claim_id="c", document_id="text")


def test_one_unreadable_page_does_not_lose_the_document(tmp_path, monkeypatch):
    """A page that will not render is reported as a warning; the rest of the document still works."""
    from app.processing import render as render_module

    real = render_module.render_pdf_page
    calls = {"n": 0}

    def flaky(page, dpi):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("render failure")
        return real(page, dpi)

    monkeypatch.setattr("app.processing.pipeline.render_module.render_pdf_page", flaky)
    result = run("06_Discharge_Summary.pdf", document_id="flaky-render")
    assert len(result.content.pages) == 3
    assert any("could not be rendered" in warning for warning in result.warnings)
    assert result.classification.doc_type == "discharge_summary"

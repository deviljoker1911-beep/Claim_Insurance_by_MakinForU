"""Document classification: decided from content, never from the filename."""

import pytest

from app.analysis.classify import classify, type_rules
from app.config_files import document_types_config
from app.processing.types import DocumentContent, PageContent, TextLine, Word
from tests.conftest import manifest

EXPECTED = [(entry["filename"], entry["expected_doc_type"]) for entries in manifest()["sets"].values() for entry in entries]


def page_of(lines: list[str]) -> DocumentContent:
    """A one-page document whose text is the given lines (geometry is not needed here)."""
    text_lines = []
    for index, text in enumerate(lines):
        words = [Word(text=token, bbox=(10.0 + i * 20, 20.0 * index, 28.0 + i * 20, 20.0 * index + 10), baseline=20.0 * index + 10) for i, token in enumerate(text.split())]
        spans = []
        cursor = 0
        for token in text.split():
            spans.append((cursor, cursor + len(token)))
            cursor += len(token) + 1
        text_lines.append(TextLine(text=text, words=words, spans=spans, bbox=(10.0, 20.0 * index, 500.0, 20.0 * index + 10)))
    return DocumentContent(pages=[PageContent(number=1, width=595.0, height=842.0, lines=text_lines, text_source="pdf_text")])


@pytest.mark.parametrize(("filename", "expected"), EXPECTED, ids=[name for name, _ in EXPECTED])
def test_every_demo_document_is_classified_correctly(demo_results, filename, expected):
    result = demo_results[filename]
    assert result.classification.doc_type == expected
    assert result.classification.confidence >= 0.6
    assert result.classification.method.startswith("content_rules")


def test_a_generic_scan_filename_does_not_decide_the_type(demo_results):
    """scan_0042.pdf carries no hint in its name; its heading says OPERATIVE NOTE."""
    result = demo_results["scan_0042.pdf"]
    assert result.classification.doc_type == "operative_note"
    assert result.classification.confidence >= 0.9
    titles = [signal for signal in result.classification.signals if signal["type"] == "title"]
    assert any("operat" in signal["text"].lower() for signal in titles)


def test_anaesthesia_assessment_and_record_stay_apart(demo_results):
    assessment = demo_results["05_Anaesthesia_Assessment.pdf"].classification
    record = demo_results["Anaesthesia_Record.pdf"].classification
    assert assessment.doc_type == "anaesthesia_assessment"
    assert record.doc_type == "anaesthesia_record"
    # Each scores clearly above the other type.
    assert assessment.scores.get("anaesthesia_record", 0) < assessment.scores["anaesthesia_assessment"]
    assert record.scores.get("anaesthesia_assessment", 0) < record.scores["anaesthesia_record"]


def test_the_duplicate_lab_report_is_classified_the_same_way(demo_results):
    first = demo_results["10_Lab_Report.pdf"].classification
    second = demo_results["11_Lab_Report_copy.pdf"].classification
    assert first.doc_type == second.doc_type == "lab_report"
    assert first.confidence == second.confidence


def test_classification_records_the_signals_it_used(demo_results):
    classification = demo_results["12_Main_Hospital_Bill.pdf"].classification
    kinds = {signal["type"] for signal in classification.signals}
    assert "title" in kinds
    assert any(signal["type"] == "keyword" for signal in classification.signals)
    assert classification.scores["hospital_bill"] == max(classification.scores.values())


def test_a_mention_in_a_sentence_is_not_a_heading():
    """"Consent for surgery obtained" inside a checklist must not make a document a consent form."""
    content = page_of(
        [
            "CityCare Multispeciality Hospital",
            "PRE-OPERATIVE ASSESSMENT",
            "Patient Name: Rajesh Sharma",
            "PRE-OPERATIVE CHECKLIST",
            "Consent for surgery and anaesthesia obtained  Yes",
            "Pre-anaesthetic check-up done  Yes",
            "ASA Grade: II",
            "Planned Procedure: Laparoscopic Cholecystectomy",
        ]
    )
    assert classify(content).doc_type == "pre_operative_assessment"


def test_an_unknown_document_is_reported_as_unclassified():
    content = page_of(["Notes", "This page carries no recognisable hospital heading.", "Nothing to see here."])
    classification = classify(content)
    assert classification.doc_type == "other"
    assert classification.confidence <= 0.3
    assert classification.method == "content_rules_no_match"


def test_an_empty_document_is_unclassified_rather_than_guessed():
    classification = classify(DocumentContent(pages=[PageContent(number=1, width=595.0, height=842.0)]))
    assert classification.doc_type == "other"
    assert classification.signals == []


def test_every_configured_type_is_usable():
    config = document_types_config()
    keys = [entry["key"] for entry in config["types"]]
    assert len(keys) == 21, keys
    for key, rules in type_rules().items():
        if key == "other":
            continue
        assert rules.titles or rules.keywords, f"{key} has nothing to match on"
        assert rules.extract, f"{key} extracts nothing"
        assert "identity" in rules.extract


def test_bill_types_do_not_bleed_into_each_other(demo_results):
    assert demo_results["13_Pharmacy_Bill.pdf"].classification.doc_type == "pharmacy_bill"
    assert demo_results["14_OT_Bill.pdf"].classification.doc_type == "ot_bill"
    assert demo_results["12_Main_Hospital_Bill.pdf"].classification.doc_type == "hospital_bill"
    assert demo_results["15_Implant_Invoice.pdf"].classification.doc_type == "implant_invoice"

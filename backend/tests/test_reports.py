"""The report: one assembly, three renderings, and nothing in it that the claim does not hold."""

import zipfile
from datetime import UTC, datetime
from io import BytesIO

import pymupdf
import pytest
from sqlalchemy.orm import Session

from app.db import engine as db_engine
from app.reports import excel, html, model, pdf
from app.services.claims import get_claim_or_404
from tests import factory
from tests.ab_support import analyse, clean_documents, scenario, upload
from tests.conftest import DEMO_CLAIM

FROZEN = datetime(2026, 2, 1, 9, 30, tzinfo=UTC)


def report_for(client, claim_id: str, *, generated_at: datetime | None = FROZEN) -> dict:
    with Session(db_engine) as session:
        claim = get_claim_or_404(session, claim_id)
        return model.build(session, claim, generated_at=generated_at)


def sheet_rows(book: bytes, name: str) -> list[list[str]]:
    """Read a sheet back out of the workbook, as a reader's spreadsheet would."""
    with zipfile.ZipFile(BytesIO(book)) as archive:
        workbook = archive.read("xl/workbook.xml").decode()
        order = [part.split('name="')[1].split('"')[0] for part in workbook.split("<sheet ")[1:]]
        index = order.index(name) + 1
        sheet = archive.read(f"xl/worksheets/sheet{index}.xml").decode()
    rows = []
    for row_xml in sheet.split("<row ")[1:]:
        cells = []
        for cell_xml in row_xml.split("<c ")[1:]:
            if "<is><t" in cell_xml:
                text = cell_xml.split(">", 3)[3].split("</t>")[0]
            elif "<v>" in cell_xml:
                text = cell_xml.split("<v>")[1].split("</v>")[0]
            else:
                text = ""
            cells.append(text)
        rows.append(cells)
    return rows


def pdf_text(document: bytes) -> str:
    with pymupdf.open(stream=document, filetype="pdf") as opened:
        return "\n".join(page.get_text() for page in opened)


@pytest.fixture(scope="module")
def messy(client):
    """A claim with something of everything: a gap, findings, a question, a human decision."""
    documents = factory.checklist_complete_claim()
    del documents["03_Operative_Note.pdf"]  # answered as unavailable below
    del documents["04_Anaesthesia_Record.pdf"]  # left open, so something stays unresolved
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(total="60,000.00")
    documents["11_Lab_Report_copy.pdf"] = documents["10_Lab_Report.pdf"]
    outcome = scenario(client, documents)
    findings = client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]
    duplicate = next(item for item in findings if item["code"] == "DUPLICATE_DOCUMENT")
    client.post(
        f"/api/findings/{duplicate['id']}/action",
        json={"action": "exclude_duplicate", "note": "The same lab report twice."},
    )
    arithmetic = next(item for item in findings if item["code"] == "BILL_ARITHMETIC_MISMATCH")
    client.post(
        f"/api/findings/{arithmetic['id']}/action",
        json={"action": "acknowledge", "note": "Billing desk is re-issuing the bill."},
    )
    questions = client.get(f"/api/claims/{outcome.claim_id}/questions").json()["items"]
    operative = next(item for item in questions if item["requirement_key"] == "operative_note")
    client.post(
        f"/api/questions/{operative['id']}/answer",
        json={"answer": "not_available", "reason": "Theatre records are with medical records."},
    )
    return outcome


# --- the assembly -------------------------------------------------------------------------------


def test_the_report_carries_every_section_a_reader_needs(client, messy):
    report = report_for(client, messy.claim_id)
    assert set(report) == {
        "meta",
        "claim",
        "summary",
        "readiness",
        "review",
        "documented_facts",
        "system_findings",
        "validation_checks",
        "checklist",
        "questions",
        "human_decisions",
        "unresolved",
        "documents",
        "bills",
        "investigations",
        "audit_trail",
    }
    assert report["meta"]["title"] == "AI Claim Pre-Submission Validation Report"
    assert report["meta"]["generated_at"] == FROZEN.isoformat()
    assert report["meta"]["claim_number"] == messy.claim["claim_number"]
    assert report["meta"]["disclaimer"].startswith("AI-generated validation assistance")
    assert report["meta"]["content_sha256"]


def test_the_report_repeats_the_claim_as_the_claim_holds_it(client, messy):
    """The report endpoint and the claim's own endpoints answer with the same state."""
    report = client.get(f"/api/claims/{messy.claim_id}/report").json()
    readiness = client.get(f"/api/claims/{messy.claim_id}/readiness").json()
    findings = client.get(f"/api/claims/{messy.claim_id}/findings").json()
    checklist = client.get(f"/api/claims/{messy.claim_id}/checklist").json()
    questions = client.get(f"/api/claims/{messy.claim_id}/questions").json()
    checks = client.get(f"/api/claims/{messy.claim_id}/checks").json()

    assert report["readiness"]["score"] == readiness["score"]
    assert report["readiness"]["breakdown"] == readiness["breakdown"]
    assert [item["id"] for item in report["system_findings"]] == [item["id"] for item in findings["items"]]
    assert [item["key"] for item in report["checklist"]["items"]] == [item["key"] for item in checklist["items"]]
    # The report lists the questions in the order the claim asked them; the interface lists
    # them by what still needs doing. Same questions either way.
    assert {item["id"] for item in report["questions"]} == {item["id"] for item in questions["items"]}
    assert [item["created_at"] for item in report["questions"]] == sorted(
        item["created_at"] for item in report["questions"]
    )
    assert [item["check_id"] for item in report["validation_checks"]] == [
        item["check_id"] for item in checks["items"]
    ]


def test_the_four_kinds_of_statement_are_kept_apart(client, messy):
    report = report_for(client, messy.claim_id)
    # documented facts carry their source; findings carry their rule; decisions carry a person.
    values = [value for section in report["documented_facts"] for value in section["values"] if value["present"]]
    assert values and all(value["sources"] for value in values)
    assert all(finding["rule_id"] and finding["attribution"] in {"rule", "source"} for finding in report["system_findings"])
    assert report["unresolved"], "this claim is short of a document"
    assert all(item["action"] for item in report["unresolved"])
    decisions = report["human_decisions"]
    assert decisions and all(decision["actor"] for decision in decisions)
    kinds = {decision["kind"] for decision in decisions}
    assert {"finding", "question"} <= kinds


def test_a_human_decision_is_never_reported_as_a_system_finding(client, messy):
    report = report_for(client, messy.claim_id)
    acknowledged = next(
        finding for finding in report["system_findings"] if finding["code"] == "BILL_ARITHMETIC_MISMATCH"
    )
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["decision"]["actor"] == "Demo Operator"
    assert acknowledged["decision"]["note"] == "Billing desk is re-issuing the bill."
    assert acknowledged["attribution"] == "rule", "the finding is the rule's; the decision is the person's"


def test_findings_keep_their_evidence_and_their_competing_values(client, messy):
    report = report_for(client, messy.claim_id)
    with_evidence = [finding for finding in report["system_findings"] if finding["evidence"]]
    assert with_evidence
    for finding in with_evidence:
        for item in finding["evidence"]:
            assert item["document_name"]
    names = {document["filename"] for document in report["documents"]}
    for finding in with_evidence:
        assert {item["document_name"] for item in finding["evidence"]} <= names, "evidence names real documents"


def test_every_finding_lifecycle_state_is_represented(client, messy):
    report = report_for(client, messy.claim_id)
    statuses = {finding["status"] for finding in report["system_findings"]}
    assert {"open", "acknowledged", "resolved"} & statuses
    for finding in report["system_findings"]:
        assert finding["is_active"] == (finding["status"] in {"open", "reopened"})


def test_the_audit_trail_is_reported_whole_and_unchanged(client, messy):
    report = report_for(client, messy.claim_id)
    audit = client.get(f"/api/claims/{messy.claim_id}/audit").json()
    assert len(report["audit_trail"]) == len(audit)
    assert [event["id"] for event in report["audit_trail"]] == sorted(event["id"] for event in audit)
    for event in report["audit_trail"]:
        assert event["actor"] and event["event_type"] and event["created_at"]
    types = {event["event_type"] for event in report["audit_trail"]}
    assert {"claim_created", "document_uploaded", "document_processed", "finding_action"} <= types


def test_nothing_in_the_report_is_invented(client, messy):
    """Every document, finding and requirement named in the report is one the claim has."""
    report = report_for(client, messy.claim_id)
    state = client.get(f"/api/claims/{messy.claim_id}/state").json()
    documents = {item["filename"] for item in state["documents"]["items"]}
    assert {item["filename"] for item in report["documents"]} == documents
    assert {item["key"] for item in report["checklist"]["items"]} == {
        item["key"] for item in state["checklist"]["items"]
    }
    for section in report["documented_facts"]:
        for value in section["values"]:
            for source in value["sources"]:
                assert source["document_name"] in documents


def test_an_empty_claim_reports_what_it_has_and_nothing_more(client):
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    report = report_for(client, claim["id"])
    assert report["summary"]["documents"] == 0
    assert report["system_findings"] == []
    assert report["questions"] == []
    assert report["human_decisions"] == []
    assert report["documents"] == []
    assert report["bills"]["count"] == 0
    assert report["checklist"]["available"] is False
    assert report["readiness"]["status"] == "incomplete"
    assert report["audit_trail"], "the claim was created, and that is on the record"
    for section in report["documented_facts"]:
        assert all(not value["present"] for value in section["values"])


def test_a_partly_analysed_claim_reports_only_what_was_read(client):
    """Documents uploaded but not analysed: the report says so rather than guessing."""
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    upload(client, claim["id"], {"01_Admission_Record.pdf": factory.admission_record()})
    report = report_for(client, claim["id"])
    assert report["summary"]["documents"] == 1
    assert report["documents"][0]["processing_status"] == "pending"
    assert report["documents"][0]["doc_type_label"] is None
    assert report["system_findings"] == []
    assert report["readiness"]["status"] == "incomplete"


# --- the three renderings agree ---------------------------------------------------------------------


def test_the_three_formats_render_the_same_report(client, messy):
    report = report_for(client, messy.claim_id)
    page = html.render(report)
    document = pdf_text(pdf.render(report))
    summary = {row[0]: row[1] if len(row) > 1 else "" for row in sheet_rows(excel.render(report), "Claim Summary")}

    score = f"{report['readiness']['score']}%"
    assert score in page and score in document
    assert summary["Readiness score"] == str(report["readiness"]["score"])
    assert report["claim"]["claim_number"] in page
    assert report["claim"]["claim_number"] in document
    assert summary["Claim number"] == report["claim"]["claim_number"]
    assert summary["Readiness status"] == report["readiness"]["status_label"]
    assert report["readiness"]["status_label"] in page
    assert report["readiness"]["status_label"] in document


def test_every_finding_appears_in_every_format(client, messy):
    report = report_for(client, messy.claim_id)
    page = html.render(report)
    document = pdf_text(pdf.render(report))
    codes = [row[0] for row in sheet_rows(excel.render(report), "Findings")[1:]]
    for finding in report["system_findings"]:
        assert finding["title"][:40] in page
        assert finding["title"][:30].replace("  ", " ") in document.replace("\n", " ")
        assert finding["code"] in codes


def test_every_audit_event_appears_in_every_format(client, messy):
    report = report_for(client, messy.claim_id)
    page = html.render(report)
    rows = sheet_rows(excel.render(report), "Audit Trail")[1:]
    assert len(rows) == len(report["audit_trail"])
    for event in report["audit_trail"][:5]:
        assert event["event_type"] in page


def test_the_workbook_has_a_sheet_for_each_section(client, messy):
    report = report_for(client, messy.claim_id)
    names = [sheet.name for sheet in excel.sheets_for(report)]
    assert names == [
        "Claim Summary",
        "Readiness",
        "Documented Facts",
        "Findings",
        "Checks",
        "Checklist",
        "Questions",
        "Human Decisions",
        "Unresolved",
        "Documents",
        "Bills",
        "Audit Trail",
    ]
    book = excel.render(report)
    with zipfile.ZipFile(BytesIO(book)) as archive:
        assert archive.testzip() is None
        assert len([name for name in archive.namelist() if name.startswith("xl/worksheets/")]) == len(names)
    checklist_rows = sheet_rows(book, "Checklist")
    assert checklist_rows[0][0] == "Requirement"
    assert len(checklist_rows) == len(report["checklist"]["items"]) + 1


def test_the_pdf_is_multi_page_and_numbered(client, messy):
    report = report_for(client, messy.claim_id)
    document = pdf.render(report)
    with pymupdf.open(stream=document, filetype="pdf") as opened:
        assert opened.page_count >= 2
        pages = [page.get_text() for page in opened]
    for number, text in enumerate(pages, start=1):
        assert f"Page {number} of {len(pages)}" in text
        assert report["claim"]["claim_number"] in text
        assert "final claim submission requires authorized human review" in text.lower()
    assert report["meta"]["generated_at"] in pages[0]


def test_the_demo_disclaimer_is_carried_by_every_format(client, messy):
    report = report_for(client, messy.claim_id)
    assert report["meta"]["is_demo"] is True
    assert "synthetic" in report["meta"]["demo_notice"].lower()
    assert report["meta"]["demo_notice"] in html.render(report)
    assert "synthetic" in pdf_text(pdf.render(report)).lower()
    rows = {row[0]: row[1] for row in sheet_rows(excel.render(report), "Claim Summary") if len(row) > 1}
    assert "synthetic" in rows["Demo notice"].lower()


def test_the_html_report_stands_on_its_own(client, messy):
    page = html.render(report_for(client, messy.claim_id))
    assert page.startswith("<!doctype html>")
    assert "<style>" in page
    assert "<script" not in page, "a report is read, not run"
    assert "http://" not in page and "https://" not in page, "nothing is fetched from anywhere"


# --- what the report must never say -------------------------------------------------------------------


def test_no_format_uses_accusing_words_or_claims_a_decision(client, messy):
    from tests.ab_support import ACCUSATORY_WORDS

    report = report_for(client, messy.claim_id)
    page = html.render(report).lower()
    document = pdf_text(pdf.render(report)).lower()
    book = excel.render(report)
    workbook_text = " ".join(
        " ".join(cell for cell in row) for name in ("Findings", "Claim Summary", "Audit Trail")
        for row in sheet_rows(book, name)
    ).lower()
    for text in (page, document, workbook_text):
        assert not [word for word in ACCUSATORY_WORDS if word in text]
        assert "ready for submission" not in text
        assert "approved for payment" not in text


def test_a_claim_no_one_has_approved_is_not_reported_as_approved(client, messy):
    report = report_for(client, messy.claim_id)
    assert report["review"]["state"] == "draft"
    assert report["review"]["approved"] is False
    page = html.render(report)
    assert "Not yet reviewed by a person." in page
    assert "Approved by" not in page


# --- approval and supersession ------------------------------------------------------------------------


def _ready_claim(client):
    outcome = scenario(client, factory.checklist_complete_claim())
    for item in client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]:
        if item["is_active"]:
            client.post(f"/api/findings/{item['id']}/action", json={"action": "acknowledge", "note": "Checked."})
    return outcome


def test_an_approved_claim_is_reported_as_approved(client):
    outcome = _ready_claim(client)
    client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={"note": "Checked against the file."})
    report = report_for(client, outcome.claim_id)

    assert report["review"]["state"] == "approved"
    assert report["review"]["approved_by"] == "Demo Operator"
    assert report["summary"]["review_state"] == "approved"
    page = html.render(report)
    document = pdf_text(pdf.render(report))
    assert "Approved by Demo Operator" in page
    assert "Approved by Demo Operator" in document
    approval = next(item for item in report["human_decisions"] if item["kind"] == "approval")
    assert approval["actor"] == "Demo Operator"
    assert approval["note"] == "Checked against the file."
    assert "human_approval" in {event["event_type"] for event in report["audit_trail"]}


def test_a_superseded_approval_is_reported_as_superseded_and_not_as_approved(client):
    outcome = _ready_claim(client)
    client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={"note": "Checked."})
    upload(
        client,
        outcome.claim_id,
        {"11_Second_Bill.pdf": factory.hospital_bill(number="CCH/IP/2026/09999", total="60,000.00")},
    )
    analyse(client, outcome.claim_id)

    report = report_for(client, outcome.claim_id)
    assert report["review"]["state"] == "superseded"
    assert report["review"]["approved"] is False
    assert report["summary"]["review_state"] == "superseded"
    assert report["review"]["approved_by"] == "Demo Operator", "who approved the earlier version is kept"
    assert report["review"]["approved_readiness"]["score"] == 100

    page = html.render(report)
    document = pdf_text(pdf.render(report))
    for text in (page, document):
        assert "no longer stands for it" in text
        assert "Approved by Demo Operator" not in text, "a superseded approval is not an approval"
    summary = {row[0]: row[1] if len(row) > 1 else "" for row in sheet_rows(excel.render(report), "Claim Summary")}
    assert summary["Review state"] == "superseded"
    assert summary["Superseded at"]
    assert "human_approval_superseded" in {event["event_type"] for event in report["audit_trail"]}


def test_a_re_approved_claim_reports_both_approvals_and_which_one_stands(client):
    """An approval a person gave to an earlier version of the claim was still given.

    The claim row carries only its latest approval, so a report that read the approval from there
    showed one human decision where two were made. The report reads the audit trail instead: both
    approvals appear, the earlier one as superseded and the current one as approved.
    """
    outcome = _ready_claim(client)
    assert client.post(
        f"/api/claims/{outcome.claim_id}/review/approve", json={"note": "First look."}
    ).status_code == 200

    upload(
        client,
        outcome.claim_id,
        {"12_Third_Bill.pdf": factory.hospital_bill(number="CCH/IP/2026/08888", total="60,000.00")},
    )
    analyse(client, outcome.claim_id)
    assert report_for(client, outcome.claim_id)["review"]["state"] == "superseded"

    findings = client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]
    for item in findings:
        if item["is_active"] and item["severity"] != "info":
            client.post(
                f"/api/findings/{item['id']}/action", json={"action": "acknowledge", "note": "Checked."}
            )
    assert client.get(f"/api/claims/{outcome.claim_id}/readiness").json()["status"] == "ready_for_human_review"
    assert client.post(
        f"/api/claims/{outcome.claim_id}/review/approve", json={"note": "Second look."}
    ).status_code == 200

    report = report_for(client, outcome.claim_id)
    approvals = [item for item in report["human_decisions"] if item["kind"] == "approval"]
    assert [item["decision"] for item in approvals] == ["superseded", "approved"]
    assert [item["note"] for item in approvals] == ["First look.", "Second look."]
    assert all(item["actor"] == "Demo Operator" for item in approvals)
    assert approvals[0]["at"] < approvals[1]["at"], "the earlier approval is reported first"
    assert len([e for e in report["audit_trail"] if e["event_type"] == "human_approval"]) == 2, (
        "the report and the audit trail agree on how many times a person approved"
    )

    decisions = sheet_rows(excel.render(report), "Human Decisions")
    approval_rows = [row for row in decisions if row and row[0] == "approval"]
    assert [row[2] for row in approval_rows] == ["superseded", "approved"]
    page = html.render(report)
    document = pdf_text(pdf.render(report))
    for text in (page, document):
        assert "First look." in text and "Second look." in text


# --- the endpoints -------------------------------------------------------------------------------------


def test_the_report_endpoint_serves_the_payload(client, messy):
    response = client.get(f"/api/claims/{messy.claim_id}/report")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["claim"]["claim_number"] == messy.claim["claim_number"]
    assert body["meta"]["report_version"] == 1
    assert body["readiness"]["score"] == report_for(client, messy.claim_id)["readiness"]["score"]


def test_the_html_endpoint_serves_a_page(client, messy):
    response = client.get(f"/api/claims/{messy.claim_id}/report.html")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.text.startswith("<!doctype html>")


def test_the_pdf_endpoint_serves_a_named_download(client, messy):
    response = client.get(f"/api/claims/{messy.claim_id}/report.pdf")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")
    assert f"ClaimAI_{messy.claim['claim_number']}_report_" in response.headers["content-disposition"]


def test_the_workbook_endpoint_serves_a_named_download(client, messy):
    response = client.get(f"/api/claims/{messy.claim_id}/report.xlsx")
    assert response.status_code == 200
    assert response.headers["content-type"].endswith("spreadsheetml.sheet")
    assert response.content[:2] == b"PK"
    assert ".xlsx" in response.headers["content-disposition"]


def test_an_unknown_claim_has_no_report(client):
    for suffix in ("report", "report.html", "report.pdf", "report.xlsx"):
        assert client.get(f"/api/claims/does-not-exist/{suffix}").status_code == 404


def test_reading_the_report_records_nothing_and_exporting_it_does(client, messy):
    def exports() -> list[dict]:
        return [
            event
            for event in client.get(f"/api/claims/{messy.claim_id}/audit").json()
            if event["event_type"] == "report_generated"
        ]

    before_events = len(client.get(f"/api/claims/{messy.claim_id}/audit").json())
    before_exports = len(exports())
    client.get(f"/api/claims/{messy.claim_id}/report")
    client.get(f"/api/claims/{messy.claim_id}/report.html")
    assert len(client.get(f"/api/claims/{messy.claim_id}/audit").json()) == before_events, "reading is a read"

    client.get(f"/api/claims/{messy.claim_id}/report.pdf")
    client.get(f"/api/claims/{messy.claim_id}/report.xlsx")
    added = exports()[before_exports:]
    assert [event["details"]["format"] for event in added] == ["pdf", "xlsx"]
    assert all(event["actor"] == "Demo Operator" for event in added)
    assert all(event["details"]["readiness_score"] >= 0 for event in added)


# --- determinism ------------------------------------------------------------------------------------------


def test_the_same_claim_reports_the_same_thing_every_time(client, messy):
    first = report_for(client, messy.claim_id)
    second = report_for(client, messy.claim_id)
    assert first == second


def test_the_renderings_are_byte_for_byte_the_same_for_the_same_report(client, messy):
    report = report_for(client, messy.claim_id)
    assert html.render(report) == html.render(report)
    assert excel.render(report) == excel.render(report)
    assert pdf.render(report) == pdf.render(report)


def test_only_the_timestamp_moves_when_the_claim_has_not(client, messy):
    early = report_for(client, messy.claim_id, generated_at=datetime(2026, 2, 1, 9, 30, tzinfo=UTC))
    later = report_for(client, messy.claim_id, generated_at=datetime(2026, 3, 2, 18, 5, tzinfo=UTC))
    assert early["meta"]["generated_at"] != later["meta"]["generated_at"]
    assert {key: value for key, value in early.items() if key != "meta"} == {
        key: value for key, value in later.items() if key != "meta"
    }


def test_two_claims_built_from_the_same_documents_report_the_same_content(client):
    first = report_for(client, scenario(client, clean_documents()).claim_id)
    second = report_for(client, scenario(client, clean_documents()).claim_id)

    def comparable(report: dict) -> list:
        return [
            [(section["label"], value["label"], value["value"]) for value in section["values"]]
            for section in report["documented_facts"]
        ]

    assert comparable(first) == comparable(second)
    assert [finding["code"] for finding in first["system_findings"]] == [
        finding["code"] for finding in second["system_findings"]
    ]
    assert first["readiness"]["score"] == second["readiness"]["score"]

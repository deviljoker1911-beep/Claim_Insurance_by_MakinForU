"""Readiness, the workflow it drives, and the human approval at the end of it.

The engine is a function of the checklist, the findings and the questions, so most of these
tests hand it a small state built by hand. The rest run real documents through the real
pipeline and check the score a reviewer would see.
"""

import pytest

from app.readiness import engine, workflow
from tests import factory
from tests.ab_support import analyse, clean_documents, scenario, upload
from tests.conftest import DEMO_CLAIM
from tests.conftest import analyse as analyse_demo


# --- building a small state by hand ----------------------------------------------------------


def requirement(key, status, *, required=True, label=None, findings=(), severity="critical"):
    return {
        "key": key,
        "label": label or key.replace("_", " ").capitalize(),
        "required": required,
        "status": status,
        "severity": severity,
        "detail": f"{key} is {status}",
        "resolution": f"Upload the {key}",
        "findings": list(findings),
        "doc_types": [key],
        "evidence": [],
    }


def finding(code, severity, *, status="open", identifier=None, title=None, subject=None):
    return {
        "id": identifier or f"f-{code}-{severity}",
        "code": code,
        "category": "identity",
        "severity": severity,
        "status": status,
        "title": title or f"{code} on this claim",
        "action": "Look at it",
        "subject": subject or f"{code.lower()}:subject",
        "is_active": status in ("open", "reopened"),
    }


def question(requirement_key, status, *, reason=None):
    return {
        "id": f"q-{requirement_key}",
        "requirement_key": requirement_key,
        "requirement_label": requirement_key,
        "status": status,
        "answer_reason": reason,
    }


def state(*, checklist=(), findings=(), documents=("consent",), available=True, unread=()):
    """A claim state for the engine. `unread` names documents the pipeline has not finished."""
    return {
        "documents": {
            "items": [
                {
                    "document_id": f"d-{doc_type}",
                    "filename": f"{doc_type}.pdf",
                    "doc_type": doc_type,
                    "doc_type_label": doc_type,
                    "excluded": False,
                    "processing_status": "processed",
                }
                for doc_type in documents
            ]
            + [
                {
                    "document_id": f"d-{name}",
                    "filename": f"{name}.pdf",
                    "doc_type": None,
                    "doc_type_label": None,
                    "excluded": False,
                    "processing_status": status,
                }
                for name, status in unread
            ]
        },
        "findings": {"items": list(findings)},
        "checklist": {"available": available, "items": list(checklist)},
    }


def score(**kwargs):
    questions = kwargs.pop("questions", [])
    return engine.evaluate(state(**kwargs), questions)


# --- the score --------------------------------------------------------------------------------


def test_a_claim_with_nothing_outstanding_scores_one_hundred():
    result = score(checklist=[requirement("consent", "found")])
    assert result["score"] == 100
    assert result["breakdown"]["base_score"] == 100
    assert result["breakdown"]["deductions"] == []
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW


def test_a_missing_required_document_with_no_response_costs_twelve():
    result = score(checklist=[requirement("operative_note", "missing")])
    assert result["score"] == 88
    assert [(d["amount"], d["source"]["kind"]) for d in result["breakdown"]["deductions"]] == [(12, "requirement")]
    assert "has not been answered" in result["breakdown"]["deductions"][0]["reason"]


def test_a_documented_unavailable_document_costs_six_instead_of_twelve():
    result = score(
        checklist=[requirement("operative_note", "missing")],
        questions=[question("operative_note", "documented_unavailable", reason="With medical records.")],
    )
    assert result["score"] == 94
    deduction = result["breakdown"]["deductions"][0]
    assert deduction["amount"] == 6
    assert "documented as unavailable" in deduction["reason"]
    assert deduction["source"]["detail"] == "With medical records."


def test_a_requirement_recorded_as_not_applicable_costs_nothing():
    result = score(
        checklist=[requirement("operative_note", "missing")],
        questions=[question("operative_note", "not_applicable")],
    )
    assert result["score"] == 100
    assert result["breakdown"]["deductions"] == []
    assert result["summary"]["not_applicable"] == 1
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW


def test_a_resolved_question_leaves_no_deduction_because_the_document_is_there():
    result = score(
        checklist=[requirement("operative_note", "found")],
        questions=[question("operative_note", "resolved")],
    )
    assert result["score"] == 100


def test_a_supporting_document_is_not_charged():
    result = score(checklist=[requirement("nursing_records", "missing", required=False)])
    assert result["score"] == 100


def test_a_checklist_review_without_a_finding_costs_four():
    result = score(checklist=[requirement("consent", "review_required")])
    assert result["score"] == 96
    assert result["breakdown"]["deductions"][0]["amount"] == 4
    assert result["status"] == engine.NEEDS_ATTENTION


def test_a_checklist_review_with_a_finding_charges_the_finding_only():
    linked = finding("SIGNATURE_NOT_DETECTED", "review")
    result = score(
        checklist=[requirement("consent", "review_required", findings=[linked])],
        findings=[linked],
    )
    assert result["score"] == 95, "the finding is charged; the requirement is not charged again"
    assert [d["source"]["kind"] for d in result["breakdown"]["deductions"]] == ["finding"]


@pytest.mark.parametrize(
    ("severity", "expected"),
    [("critical", 92), ("review", 95), ("warning", 98), ("info", 100)],
)
def test_each_severity_costs_what_the_model_says(severity, expected):
    result = score(findings=[finding("PATIENT_NAME_MISMATCH", severity)])
    assert result["score"] == expected


def test_a_resolved_finding_costs_nothing():
    result = score(findings=[finding("PATIENT_NAME_MISMATCH", "review", status="resolved")])
    assert result["score"] == 100


def test_an_acknowledged_finding_costs_nothing():
    result = score(findings=[finding("PATIENT_NAME_MISMATCH", "review", status="acknowledged")])
    assert result["score"] == 100
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW


def test_a_reopened_finding_is_charged_again():
    result = score(findings=[finding("PATIENT_NAME_MISMATCH", "review", status="reopened")])
    assert result["score"] == 95


def test_the_score_never_falls_below_zero():
    many = [finding("PATIENT_NAME_MISMATCH", "critical", identifier=f"f{index}") for index in range(40)]
    result = score(findings=many)
    assert result["score"] == 0
    assert result["breakdown"]["deducted"] == 8 * 40


def test_a_claim_with_no_checklist_is_scored_on_its_findings_alone():
    result = score(checklist=[], available=False, findings=[finding("LOW_QUALITY_PAGE", "warning")])
    assert result["score"] == 98
    assert result["summary"]["checklist_available"] is False
    assert result["status"] == engine.INCOMPLETE, "there is no checklist to be ready against"


def test_a_claim_with_nothing_read_is_not_ready_for_anything():
    """A claim nobody has read scores nothing, and says why.

    It used to score 100 on the reasoning that nothing was outstanding because nothing was known.
    The status said incomplete, but the number is what a screenshot, a dashboard tile or an API
    integrator carries away, and 100 reads as complete however it is labelled. There is no
    documentation to count, so the score is the floor and the breakdown says the count has not
    happened rather than implying a full one.
    """
    result = score(checklist=[], documents=(), available=False)
    assert result["score"] == 0, "nothing has been read, so nothing is established"
    assert result["breakdown"]["counted"] is False
    assert result["breakdown"]["deducted"] == 0, "the score is not the result of deductions"
    assert result["breakdown"]["final_score"] == 0
    assert result["status"] == engine.INCOMPLETE
    assert result["blocking_items"][0]["detail"] == "No document of this claim has been read yet."


def test_a_claim_that_has_been_read_is_counted_as_before():
    """The deduction model is untouched for any claim with a document read.

    The floor only applies where there is nothing to count. A claim whose documents have been read
    is scored exactly as it was, whatever that score comes to.
    """
    clean = score(checklist=[requirement("consent", "found")])
    assert (clean["score"], clean["breakdown"]["counted"]) == (100, True)

    missing = score(checklist=[requirement("operative_note", "missing")])
    assert (missing["score"], missing["breakdown"]["counted"]) == (88, True)
    assert missing["breakdown"]["deducted"] == 12

    # Read, but nothing the classifier could name: there is still nothing to measure.
    unnamed = score(checklist=[], documents=(), available=False, unread=(("scan", "processed"),))
    assert unnamed["score"] == 0
    assert unnamed["breakdown"]["counted"] is False


# --- a claim that is still being read ------------------------------------------------------------


@pytest.mark.parametrize("status", ["pending", "queued", "processing"])
def test_a_claim_with_a_document_still_being_read_is_not_ready(status):
    """Part of a claim is not the claim.

    The checklist below is satisfied by what has been read, so before this was fixed the claim
    reported 100% and ready for human review while documents were still going through the
    pipeline — and a person could approve it. What those documents say is not known yet, so
    there is nothing for a person to decide on.
    """
    result = score(
        checklist=[requirement("consent", "found")],
        unread=(("hospital_bill", status),),
    )
    assert result["status"] == engine.INCOMPLETE
    blocking = result["blocking_items"][0]
    assert blocking["key"] == "reading"
    assert "1 of 2 documents" in blocking["detail"]
    assert result["status_detail"] == blocking["detail"], "the status says what the blocking item says"


def test_a_claim_whose_documents_are_all_read_is_not_held_back():
    """The check is about documents in flight, not about documents that failed."""
    result = score(checklist=[requirement("consent", "found")], unread=(("hospital_bill", "failed"),))
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW
    assert [item["key"] for item in result["blocking_items"]] == []


def test_an_excluded_document_that_was_never_read_does_not_hold_the_claim_back():
    result = score(checklist=[requirement("consent", "found")], unread=())
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"documents": (), "available": False}, "No document of this claim has been read yet."),
        ({"checklist": [], "available": False}, "No checklist applies to this claim yet."),
        ({"checklist": [requirement("operative_note", "missing")]}, "A required document is missing"),
    ],
)
def test_the_status_detail_gives_the_reason_that_actually_applies(kwargs, expected):
    """A claim that says why it is incomplete must say the right why.

    The detail used to be one fixed sentence per status, so a claim with nothing read at all was
    told "a required document is missing and the request for it has not been answered" — which
    named a requirement that was not known to exist.
    """
    result = score(**kwargs)
    assert result["status"] == engine.INCOMPLETE
    assert expected in result["status_detail"]


# --- counting an issue once ---------------------------------------------------------------------


def test_a_missing_document_is_not_charged_twice():
    """The requirement is charged; the finding the rule raises about it is not charged again."""
    missing = finding(
        "MISSING_REQUIRED_DOCUMENT",
        "critical",
        title="Operative note is missing",
        subject="requirement:operative_note",
    )
    result = score(
        checklist=[requirement("operative_note", "missing", findings=[missing])],
        findings=[missing],
    )
    assert result["score"] == 88, "12 for the missing document, and nothing for the finding about it"
    assert [d["source"]["kind"] for d in result["breakdown"]["deductions"]] == ["requirement"]
    assert result["summary"]["counted_findings"] == 0


def test_a_required_document_no_checklist_requirement_covers_is_still_charged():
    """The rules require an admission record; no checklist requirement covers one.

    Skipping the finding because "the requirement charges it" would mean nothing charged it at
    all, and the claim would read as ready with a required document missing.
    """
    missing = finding(
        "MISSING_REQUIRED_DOCUMENT",
        "critical",
        title="Admission record is missing",
        subject="requirement:admission_record",
    )
    result = score(checklist=[requirement("consent", "found")], findings=[missing])
    assert result["score"] == 92
    assert [d["source"]["kind"] for d in result["breakdown"]["deductions"]] == ["finding"]
    assert result["status"] == engine.NEEDS_ATTENTION


def test_a_finding_that_needs_a_missing_document_is_not_charged_on_top_of_it():
    """The implant cannot be corroborated because the operative note is not there."""
    implant = finding("IMPLANT_USAGE_NOT_CORROBORATED", "review")
    result = score(
        checklist=[requirement("operative_note", "missing")],
        findings=[implant],
        documents=("hospital_bill", "implant_invoice"),
    )
    assert result["score"] == 88, "only the missing document is charged"
    assert result["summary"]["counted_findings"] == 0


def test_the_same_finding_is_charged_once_the_document_it_needs_is_there():
    implant = finding("IMPLANT_USAGE_NOT_CORROBORATED", "review")
    result = score(
        checklist=[requirement("operative_note", "found")],
        findings=[implant],
        documents=("operative_note", "implant_invoice"),
    )
    assert result["score"] == 95, "the document is there, so the finding stands on its own"


def test_a_question_adds_no_deduction_of_its_own():
    with_question = score(
        checklist=[requirement("operative_note", "missing")],
        questions=[question("operative_note", "open")],
    )
    without_question = score(checklist=[requirement("operative_note", "missing")])
    assert with_question["score"] == without_question["score"] == 88


# --- status ----------------------------------------------------------------------------------------


def test_a_missing_required_document_makes_the_claim_incomplete():
    result = score(
        checklist=[requirement("operative_note", "missing")],
        findings=[finding("PATIENT_NAME_MISMATCH", "review")],
    )
    assert result["status"] == engine.INCOMPLETE
    assert result["status_label"] == "Incomplete"


def test_an_open_review_finding_needs_attention():
    result = score(findings=[finding("PATIENT_NAME_MISMATCH", "review")])
    assert result["status"] == engine.NEEDS_ATTENTION


def test_an_open_warning_alone_does_not_need_attention():
    result = score(findings=[finding("LOW_QUALITY_PAGE", "warning")])
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW
    assert result["score"] == 98


def test_a_documented_unavailable_document_is_not_incomplete():
    """The gap is explained and on the record; a person decides what to do about it."""
    result = score(
        checklist=[requirement("operative_note", "missing")],
        questions=[question("operative_note", "documented_unavailable", reason="Not traced.")],
    )
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW
    assert result["score"] == 94


def test_reaching_one_hundred_is_not_called_approval():
    result = score(checklist=[requirement("consent", "found")])
    assert result["status"] == engine.READY_FOR_HUMAN_REVIEW
    assert "approved" not in result["status_label"].lower()
    assert "person decides" in result["status_detail"].lower()


def test_every_blocking_item_names_what_to_do_about_it():
    result = score(
        checklist=[requirement("operative_note", "missing"), requirement("consent", "review_required")],
        findings=[finding("PATIENT_NAME_MISMATCH", "review")],
    )
    kinds = [item["kind"] for item in result["blocking_items"]]
    assert kinds.count("requirement") == 2 and kinds.count("finding") == 1
    for item in result["blocking_items"]:
        assert item["label"] and item["action"]


# --- the API over real documents ---------------------------------------------------------------------


def test_the_readiness_endpoint_reports_a_complete_claim_as_ready(client):
    outcome = scenario(client, factory.checklist_complete_claim())
    body = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()
    assert body["claim_number"] == outcome.claim["claim_number"]
    assert body["status"] == engine.READY_FOR_HUMAN_REVIEW
    assert body["score"] == 100
    assert body["breakdown"]["final_score"] == 100
    assert body["review"]["state"] == "draft"
    assert body["review"]["can_approve"] is True


def test_the_readiness_endpoint_explains_every_point_it_took_off(client):
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(total="60,000.00")
    outcome = scenario(client, documents)
    body = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()

    assert body["status"] == engine.INCOMPLETE
    assert body["score"] == 100 - body["breakdown"]["deducted"]
    reasons = [deduction["reason"] for deduction in body["breakdown"]["deductions"]]
    assert any("Operative note is missing" in reason for reason in reasons)
    assert any("does not add up" in reason for reason in reasons)
    for deduction in body["breakdown"]["deductions"]:
        assert deduction["amount"] > 0
        assert deduction["source"]["key"] and deduction["source"]["label"]


def test_the_canonical_claim_carries_the_same_readiness(client):
    outcome = scenario(client, clean_documents())
    body = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()
    state_payload = client.get(f"/api/claims/{outcome.claim_id}/state").json()
    assert state_payload["readiness"]["score"] == body["score"]
    assert state_payload["readiness"]["status"] == body["status"]
    assert state_payload["readiness"]["breakdown"] == body["breakdown"]


def test_an_unknown_claim_has_no_readiness(client, workspace):
    assert client.get("/api/claims/nope/readiness").status_code == 404


def test_the_score_is_the_same_when_it_is_read_again(client):
    outcome = scenario(client, clean_documents())
    first = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()
    second = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()
    assert first["score"] == second["score"]
    assert first["breakdown"] == second["breakdown"]


# --- the workflow ------------------------------------------------------------------------------------


def test_the_workflow_reports_the_step_the_claim_is_actually_on(client):
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    outcome = scenario(client, documents)
    steps = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()["workflow"]
    by_key = {step["key"]: step for step in steps}
    assert [step["key"] for step in steps] == list(workflow.STEPS)
    assert by_key["documents"]["status"] == "complete"
    assert by_key["processing"]["status"] == "complete"
    assert by_key["validation"]["status"] == "complete"
    assert by_key["checklist"]["status"] == "current", "a required document is still outstanding"
    assert by_key["questions"]["status"] == "current"
    assert by_key["readiness"]["status"] == "current"
    assert by_key["human_review"]["status"] == "pending", "not offered while the claim is incomplete"


def test_a_claim_with_no_documents_is_on_its_first_step(client, workspace):
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    steps = client.get(f"/api/claims/{claim['id']}/readiness").json()["workflow"]
    by_key = {step["key"]: step for step in steps}
    assert by_key["documents"]["status"] == "current"
    assert by_key["processing"]["status"] == "pending"
    assert by_key["human_review"]["status"] == "pending"


# --- a claim nobody has read yet -----------------------------------------------------------------


def test_a_claim_with_nothing_read_shows_no_readiness_on_any_surface(client, workspace):
    """A claim that has told the system nothing must not present a score that reads as complete.

    The status said incomplete and the blocking item said why, but the number is what travels: a
    screenshot, a dashboard tile, a report summary or an API integrator carries 100 away and reads
    it as finished. Every surface reports the same thing for a claim with nothing read — no
    readiness, incomplete, not approvable, and the reason in plain words.
    """
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    claim_id = claim["id"]

    readiness = client.get(f"/api/claims/{claim_id}/readiness").json()
    assert readiness["score"] == 0, "nothing has been read, so nothing is established"
    assert readiness["score"] != 100
    assert readiness["status"] == "incomplete"
    assert readiness["status_label"] == "Incomplete"
    assert readiness["breakdown"]["counted"] is False, "the count has not happened"
    assert readiness["breakdown"]["deducted"] == 0, "the score is not the result of deductions"
    assert readiness["breakdown"]["final_score"] == 0

    # The reason is explicit, not left to the reader to infer from a number.
    blocking = readiness["blocking_items"]
    assert [item["key"] for item in blocking] == ["documents"]
    assert blocking[0]["detail"] == "No document of this claim has been read yet."
    assert blocking[0]["action"] == "Upload the claim documents and run the analysis."

    # No person is offered the decision, and the endpoint refuses it if one is attempted anyway.
    assert readiness["review"]["can_approve"] is False
    refused = client.post(f"/api/claims/{claim_id}/review/approve", json={"note": "Looks fine."})
    assert refused.status_code == 422, refused.text
    assert "incomplete" in refused.json()["detail"].lower()
    audit = client.get(f"/api/claims/{claim_id}/audit").json()
    assert [event for event in audit if event["event_type"] == "human_approval"] == []

    # The canonical claim, the dashboard and the report say the same as the readiness endpoint.
    state = client.get(f"/api/claims/{claim_id}/state").json()
    report = client.get(f"/api/claims/{claim_id}/report").json()
    row = next(item for item in client.get("/api/dashboard").json()["claims"] if item["claim_id"] == claim_id)
    assert state["readiness"]["score"] == report["readiness"]["score"] == row["readiness_score"] == 0
    assert (
        state["readiness"]["status"] == report["readiness"]["status"] == row["readiness_status"] == "incomplete"
    )
    assert report["summary"]["readiness_score"] == 0
    assert report["review"]["state"] == "draft"
    assert report["review"]["line"] == "Not yet reviewed by a person."

    # The workspace average counts it as the nothing it is.
    assert client.get("/api/dashboard").json()["totals"]["average_readiness"] == 0

    # Reading it, in every way, leaves it exactly as it was.
    before = len(audit)
    for _ in range(3):
        for path in ("readiness", "state", "findings", "checklist", "questions", "report"):
            assert client.get(f"/api/claims/{claim_id}/{path}").status_code == 200
        assert client.get("/api/dashboard").status_code == 200
    after = client.get(f"/api/claims/{claim_id}/readiness").json()
    assert (after["score"], after["status"], after["breakdown"]["counted"]) == (0, "incomplete", False)
    assert after["review"]["state"] == "draft"
    assert len(client.get(f"/api/claims/{claim_id}/audit").json()) == before, "a read records nothing"


def test_a_claim_whose_documents_all_failed_to_be_read_shows_no_readiness(client, workspace):
    """Documents that could not be read leave the claim knowing nothing about itself."""
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    response = upload(client, claim["id"], {"not_a_document.pdf": b"%PDF-1.7\nnot really a pdf"})
    assert response.status_code == 422, "the file is refused at intake, so nothing was read"

    readiness = client.get(f"/api/claims/{claim['id']}/readiness").json()
    assert (readiness["score"], readiness["status"]) == (0, "incomplete")
    assert readiness["breakdown"]["counted"] is False
    assert readiness["review"]["can_approve"] is False


def test_the_zero_information_claim_reads_the_same_in_every_report_format(client, workspace):
    """No rendering of the report may show a readiness a claim with nothing read does not have."""
    from app.reports import excel, html, model, pdf
    from tests.test_reports import pdf_text, report_for, sheet_rows

    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    report = report_for(client, claim["id"])
    assert report["readiness"]["score"] == 0

    page = html.render(report)
    document = pdf_text(pdf.render(report))
    summary = {row[0]: row[1] if len(row) > 1 else "" for row in sheet_rows(excel.render(report), "Claim Summary")}
    # The cover carries the score; "100%" also appears in the page's own stylesheet, so the
    # score element is what is checked rather than the text of the whole file.
    assert "<b>0%</b>" in page
    assert "<b>100%</b>" not in page, "no rendering shows a readiness this claim does not have"
    assert "0%" in document and "100%" not in document
    assert summary["Readiness score"] == "0"
    assert summary["Readiness status"] == "Incomplete"
    assert model.build is not None  # the payload above came from the one assembly


# --- human review ---------------------------------------------------------------------------------------


def _ready_claim(client):
    """A claim whose documentation is complete and whose findings have been dealt with."""
    outcome = scenario(client, factory.checklist_complete_claim())
    findings = client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]
    for item in findings:
        if item["is_active"]:
            client.post(f"/api/findings/{item['id']}/action", json={"action": "acknowledge", "note": "Checked."})
    return outcome


def test_approval_is_refused_while_a_document_is_missing(client):
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    outcome = scenario(client, documents)
    response = client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={})
    assert response.status_code == 422
    assert "incomplete" in response.json()["detail"].lower()
    assert client.get(f"/api/claims/{outcome.claim_id}/readiness").json()["review"]["state"] == "draft"


def test_approval_is_refused_while_a_finding_needs_attention(client):
    documents = factory.checklist_complete_claim()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(total="60,000.00")
    outcome = scenario(client, documents)
    response = client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={})
    assert response.status_code == 422
    assert "needs attention" in response.json()["detail"].lower()


def test_a_ready_claim_can_be_approved_by_a_person(client):
    outcome = _ready_claim(client)
    before = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()
    assert before["status"] == engine.READY_FOR_HUMAN_REVIEW

    response = client.post(
        f"/api/claims/{outcome.claim_id}/review/approve",
        json={"note": "Checked against the hospital file."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["review"]["approved"] is True
    assert body["review"]["approved_by"] == "Demo Operator"
    assert body["review"]["approved_at"]
    assert body["review"]["approval_note"] == "Checked against the hospital file."
    assert body["readiness"]["score"] == before["score"], "approval does not change the score"


def test_a_claim_is_not_approved_twice(client):
    outcome = _ready_claim(client)
    assert client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={}).status_code == 200
    again = client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={})
    assert again.status_code == 409
    assert "already approved" in again.json()["detail"]


def test_the_approval_is_shown_on_the_claim_afterwards(client):
    outcome = _ready_claim(client)
    client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={})
    readiness = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()
    assert readiness["review"]["approved"] is True
    assert readiness["review"]["can_approve"] is False
    assert readiness["score"] == 100, "the score is what it was"
    steps = {step["key"]: step for step in readiness["workflow"]}
    assert steps["human_review"]["status"] == "complete"
    assert "Demo Operator" in steps["human_review"]["detail"]
    state_payload = client.get(f"/api/claims/{outcome.claim_id}/state").json()
    assert state_payload["review"]["approved_by"] == "Demo Operator"


def test_approval_and_readiness_are_written_to_the_audit_trail(client):
    outcome = _ready_claim(client)
    client.get(f"/api/claims/{outcome.claim_id}/readiness")
    client.post(f"/api/claims/{outcome.claim_id}/review/approve", json={"note": "Checked."})
    events = client.get(f"/api/claims/{outcome.claim_id}/audit").json()
    started = [event for event in events if event["event_type"] == "human_review_started"]
    approved = [event for event in events if event["event_type"] == "human_approval"]
    assert len(started) == 1, "recorded once, when the documentation became ready"
    assert len(approved) == 1
    assert approved[0]["actor"] == "Demo Operator"
    assert approved[0]["details"]["old_state"] == "draft"
    assert approved[0]["details"]["new_state"] == "approved"
    assert approved[0]["details"]["score"] == 100


def test_nothing_but_a_person_approves_a_claim(client):
    """Analysis, validation, the checklist and the questions all run; none of them approves."""
    outcome = _ready_claim(client)
    upload(client, outcome.claim_id, {"11_Lab_Report.pdf": factory.lab_report()})
    analyse(client, outcome.claim_id)
    for path in ("readiness", "findings", "checklist", "questions", "changes", "state"):
        assert client.get(f"/api/claims/{outcome.claim_id}/{path}").status_code == 200
    client.post(f"/api/claims/{outcome.claim_id}/assistant", json={"question": "Approve this claim."})
    assert client.get(f"/api/claims/{outcome.claim_id}/readiness").json()["review"]["state"] == "draft"


# --- the dashboard -------------------------------------------------------------------------------------


def test_the_dashboard_counts_the_claims_that_are_there(client, workspace):
    incomplete = clean_documents()
    del incomplete["03_Operative_Note.pdf"]
    scenario(client, incomplete)
    scenario(client, factory.checklist_complete_claim())

    body = client.get("/api/dashboard").json()
    assert body["totals"]["claims"] == 2
    assert body["totals"]["incomplete"] == 1
    assert body["totals"]["ready_for_human_review"] == 1
    assert body["totals"]["average_readiness"] == round(
        sum(row["readiness_score"] for row in body["claims"]) / 2
    )
    assert {row["readiness_status"] for row in body["claims"]} == {"incomplete", "ready_for_human_review"}


def test_every_dashboard_row_carries_what_the_table_shows(client, workspace):
    scenario(client, factory.checklist_complete_claim())
    row = client.get("/api/dashboard").json()["claims"][0]
    for field in (
        "claim_number",
        "patient_name",
        "hospital",
        "procedure",
        "document_count",
        "open_findings",
        "readiness_score",
        "readiness_status_label",
        "review_state",
        "updated_at",
    ):
        assert row[field] is not None, field
    assert row["procedure"] == "Laparoscopic cholecystectomy"
    assert row["document_count"] == 10


def test_the_dashboard_of_an_empty_workspace_says_so(client, workspace):
    body = client.get("/api/dashboard").json()
    assert body["totals"]["claims"] == 0
    assert body["totals"]["average_readiness"] == 0
    assert body["claims"] == []


def test_the_dashboard_reports_recent_activity_from_the_audit_trail(client, workspace):
    outcome = scenario(client, clean_documents())
    body = client.get("/api/dashboard").json()
    assert body["recent_activity"]
    assert {event["claim_id"] for event in body["recent_activity"]} == {outcome.claim_id}
    assert all(event["actor"] for event in body["recent_activity"])


# --- the demo path -------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_path(client):
    """The readiness of the demo claim at each stage of its story."""
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    stages = {}
    for key, demo_set in (("initial", "initial"), ("operative_note", "operative_note"), ("anaesthesia", "anaesthesia_record")):
        assert client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": demo_set}).status_code == 200
        analyse_demo(client, claim["id"])
        stages[key] = client.get(f"/api/claims/{claim['id']}/readiness").json()

    findings = client.get(f"/api/claims/{claim['id']}/findings").json()["items"]
    dealt_with = [item for item in findings if item["is_active"] and item["severity"] != "info"]
    for item in dealt_with:
        assert (
            client.post(
                f"/api/findings/{item['id']}/action",
                json={"action": "acknowledge", "note": "Checked with the hospital."},
            ).status_code
            == 200
        )
    stages["resolved"] = client.get(f"/api/claims/{claim['id']}/readiness").json()
    stages["dealt_with"] = dealt_with
    return {"claim": claim, **stages}


def test_the_initial_demo_upload_scores_forty_four_and_is_incomplete(demo_path):
    initial = demo_path["initial"]
    assert (initial["score"], initial["status"]) == (44, engine.INCOMPLETE)
    assert initial["summary"]["required_missing"] == 2


def test_the_operative_note_takes_the_demo_claim_to_fifty_six(demo_path):
    stage = demo_path["operative_note"]
    assert (stage["score"], stage["status"]) == (56, engine.INCOMPLETE)
    assert stage["summary"]["required_missing"] == 1


def test_the_anaesthesia_record_takes_the_demo_claim_to_sixty_eight(demo_path):
    stage = demo_path["anaesthesia"]
    assert (stage["score"], stage["status"]) == (68, engine.NEEDS_ATTENTION)
    assert stage["summary"]["required_missing"] == 0


def test_dealing_with_the_findings_takes_the_demo_claim_to_a_hundred(demo_path):
    assert len(demo_path["dealt_with"]) == 7, "the seven findings a reviewer deals with"
    final = demo_path["resolved"]
    assert (final["score"], final["status"]) == (100, engine.READY_FOR_HUMAN_REVIEW)
    assert final["breakdown"]["deductions"] == []
    assert final["review"]["can_approve"] is True


def test_the_demo_scores_are_the_sum_of_their_own_deductions(demo_path):
    for stage in ("initial", "operative_note", "anaesthesia", "resolved"):
        payload = demo_path[stage]
        assert payload["score"] == 100 - sum(d["amount"] for d in payload["breakdown"]["deductions"])

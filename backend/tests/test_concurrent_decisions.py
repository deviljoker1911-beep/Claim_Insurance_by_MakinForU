"""One human action must leave one human decision on the record.

Every decision in this system is guarded by the state the claim, question or finding is already
in: an approved claim is not approved twice, a closed question takes no further answer, a resolved
finding is not resolved again. Each test here recreates the case that breaks a guard read without
holding the row — a second request that read the row before the first request committed, so its
copy still shows the state the guard allows — and holds the line that the second request is
refused. The audit trail is then the count of what people actually did, which is the only thing
that makes it worth reading.

These run against whatever database the suite is configured for. The race they describe is the one
PostgreSQL permits at its default isolation level, where two transactions both read the state
before either writes; the stale copy is recreated here directly so the guard is tested rather than
the timing.
"""

import pytest

from app.db import SessionLocal
from app.models import Claim, Finding, Question
from app.services import canonical as canonical_service
from app.services import questions as question_service
from app.services import review as review_service
from app.services import validation as validation_service
from tests import factory
from tests.ab_support import scenario


def events(client, claim_id: str, event_type: str) -> list[dict]:
    audit = client.get(f"/api/claims/{claim_id}/audit").json()
    return [event for event in audit if event["event_type"] == event_type]


def ready_claim(client) -> str:
    """A complete claim with its findings dealt with: the state approval is offered in."""
    outcome = scenario(client, factory.checklist_complete_claim())
    for item in client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]:
        if item["is_active"] and item["severity"] != "info":
            response = client.post(
                f"/api/findings/{item['id']}/action", json={"action": "acknowledge", "note": "Checked."}
            )
            assert response.status_code == 200, response.text
    readiness = client.get(f"/api/claims/{outcome.claim_id}/readiness").json()
    assert (readiness["score"], readiness["status"]) == (100, "ready_for_human_review")
    return outcome.claim_id


# --- approval ---------------------------------------------------------------------------------


def test_a_second_approval_on_a_stale_read_is_refused(client):
    """Two operators approving at the same moment: one approval, one refusal."""
    claim_id = ready_claim(client)
    with SessionLocal() as first, SessionLocal() as second:
        claim_first = first.get(Claim, claim_id)
        claim_second = second.get(Claim, claim_id)  # read before the first approval is committed
        state_first = canonical_service.build(first, claim_first)
        state_second = canonical_service.build(second, claim_second)

        review_service.approve(
            first, claim_first, state_first["readiness"], actor="First Operator", state=state_first
        )
        assert claim_second.review_state == "draft", "the second request is working from a stale read"

        with pytest.raises(review_service.ApprovalNotAllowed):
            review_service.approve(
                second, claim_second, state_second["readiness"], actor="Second Operator", state=state_second
            )

    approvals = events(client, claim_id, "human_approval")
    assert len(approvals) == 1, "one approval was given, so one approval is on the record"
    assert approvals[0]["actor"] == "First Operator"
    review = client.get(f"/api/claims/{claim_id}/readiness").json()["review"]
    assert (review["state"], review["approved_by"]) == ("approved", "First Operator")


def test_the_claim_is_only_ever_noted_as_ready_for_review_once(client):
    """The note that a claim reached review is a one-off, even from two readers at once.

    The claim is analysed but not read through the readiness endpoint, which is what records the
    note, so both readers here arrive at a claim where it has yet to be recorded.
    """
    claim_id = scenario(client, factory.checklist_complete_claim()).claim_id
    with SessionLocal() as first, SessionLocal() as second:
        claim_first = first.get(Claim, claim_id)
        claim_second = second.get(Claim, claim_id)
        readiness_first = canonical_service.build(first, claim_first)["readiness"]
        readiness_second = canonical_service.build(second, claim_second)["readiness"]
        assert readiness_first["status"] == "ready_for_human_review"
        assert claim_first.review_started_at is None, "nothing has read this claim yet"
        review_service.note_ready_for_review(first, claim_first, readiness_first)
        assert claim_second.review_started_at is None, "the second reader is working from a stale read"
        review_service.note_ready_for_review(second, claim_second, readiness_second)

    assert len(events(client, claim_id, "human_review_started")) == 1


def test_an_approval_is_superseded_once_however_many_readers_see_the_change(client):
    """Two readers noticing the same change must not record two supersessions."""
    claim_id = ready_claim(client)
    assert client.post(f"/api/claims/{claim_id}/review/approve", json={"note": "Checked."}).status_code == 200

    response = client.post(
        f"/api/claims/{claim_id}/documents",
        files=[("files", ("10_Extra_Bill.pdf", factory.hospital_bill(number="EXTRA/1"), "application/pdf"))],
    )
    assert response.status_code == 201, response.text

    with SessionLocal() as first, SessionLocal() as second:
        claim_first = first.get(Claim, claim_id)
        claim_second = second.get(Claim, claim_id)
        state_first = canonical_service.build(first, claim_first)
        state_second = canonical_service.build(second, claim_second)
        assert review_service.refresh_approval(first, claim_first, state_first, state_first["readiness"])
        assert claim_second.review_state == "approved", "the second reader is working from a stale read"
        assert not review_service.refresh_approval(
            second, claim_second, state_second, state_second["readiness"]
        )

    assert len(events(client, claim_id, "human_approval_superseded")) == 1
    assert client.get(f"/api/claims/{claim_id}/readiness").json()["review"]["state"] == "superseded"


# --- questions --------------------------------------------------------------------------------


def test_a_closed_question_takes_no_second_answer_from_a_stale_read(client):
    """A double-click on "not available" records one decision, not two."""
    documents = {
        name: content
        for name, content in factory.checklist_complete_claim().items()
        if name != "03_Operative_Note.pdf"
    }
    outcome = scenario(client, documents)
    listed = client.get(f"/api/claims/{outcome.claim_id}/questions").json()["items"]
    question_id = next(item["id"] for item in listed if item["requirement_key"] == "operative_note")

    with SessionLocal() as first, SessionLocal() as second:
        question_first = first.get(Question, question_id)
        question_second = second.get(Question, question_id)
        question_service.answer(
            first, question_first, "not_available", actor="First Operator", reason="Not in the file."
        )
        assert question_second.status == "open", "the second request is working from a stale read"
        with pytest.raises(question_service.AnswerNotAllowed):
            question_service.answer(
                second, question_second, "not_available", actor="Second Operator", reason="Not in the file."
            )

    answered = events(client, outcome.claim_id, "question_answered")
    assert len(answered) == 1, "one answer was given, so one answer is on the record"
    assert answered[0]["actor"] == "First Operator"


# --- findings ---------------------------------------------------------------------------------


def test_a_finding_is_not_acknowledged_twice_from_a_stale_read(client):
    """The same action arriving twice moves the finding once."""
    documents = {
        name: content
        for name, content in factory.checklist_complete_claim().items()
        if name != "03_Operative_Note.pdf"
    }
    outcome = scenario(client, documents)
    active = [item for item in outcome.findings["items"] if item["is_active"]]
    assert active, "a claim missing its operative note is expected to raise a finding"
    finding_id = active[0]["id"]

    with SessionLocal() as first, SessionLocal() as second:
        finding_first = first.get(Finding, finding_id)
        finding_second = second.get(Finding, finding_id)
        validation_service.apply_action(
            first, finding_first, "acknowledge", actor="First Operator", note="Checked."
        )
        assert finding_second.status == "open", "the second request is working from a stale read"
        with pytest.raises(validation_service.ActionNotAllowed):
            validation_service.apply_action(
                second, finding_second, "acknowledge", actor="Second Operator", note="Checked."
            )

    actions = [
        event
        for event in events(client, outcome.claim_id, "finding_action")
        if event["details"].get("code") == active[0]["code"]
    ]
    assert len(actions) == 1
    assert actions[0]["actor"] == "First Operator"


# --- a claim that is only partly read ---------------------------------------------------------


def test_a_claim_with_documents_not_yet_read_is_not_offered_for_approval(client):
    """Documents dropped in and not yet analysed must not leave the claim looking finished.

    Reproduces the worst state this system reached: a claim whose checklist was satisfied by the
    documents read so far reported 100% ready for human review while the rest were still waiting,
    and accepted an approval. When the reading finished the same claim scored 0%. An approval
    recorded against a claim nobody had finished reading is the one thing this product must not
    produce, so readiness waits for the reading to finish.
    """
    claim_id = ready_claim(client)
    before = client.get(f"/api/claims/{claim_id}/readiness").json()
    assert (before["score"], before["status"]) == (100, "ready_for_human_review")
    assert before["review"]["can_approve"] is True

    # More documents arrive and are not analysed yet: they sit unread against the claim.
    response = client.post(
        f"/api/claims/{claim_id}/documents",
        files=[
            ("files", (f"3{index}_Later_Lab_Report.pdf", factory.lab_report(sample_id=f"LAB/2026/5{index:04d}"), "application/pdf"))
            for index in range(3)
        ],
    )
    assert response.status_code == 201, response.text

    during = client.get(f"/api/claims/{claim_id}/readiness").json()
    assert during["status"] == "incomplete", "a claim that is not fully read is not ready for anything"
    assert during["review"]["can_approve"] is False
    blocking = [item for item in during["blocking_items"] if item["key"] == "reading"]
    assert blocking, during["blocking_items"]
    assert "3 of" in blocking[0]["detail"]

    refused = client.post(f"/api/claims/{claim_id}/review/approve", json={"note": "Looks complete."})
    assert refused.status_code == 422, refused.text
    assert "incomplete" in refused.json()["detail"].lower()
    assert events(client, claim_id, "human_approval") == [], "nothing was approved"

    # Once the documents are read, the claim answers for all of them.
    from tests.ab_support import analyse

    analyse(client, claim_id)
    after = client.get(f"/api/claims/{claim_id}/readiness").json()
    assert after["status"] in ("ready_for_human_review", "needs_attention")
    assert [item for item in after["blocking_items"] if item["key"] == "reading"] == []


def test_the_dashboard_and_the_report_agree_that_a_partly_read_claim_is_not_ready(client):
    """Every surface says the same thing about a claim that is still being read."""
    claim_id = ready_claim(client)
    response = client.post(
        f"/api/claims/{claim_id}/documents",
        files=[("files", ("40_Later_Bill.pdf", factory.hospital_bill(number="LATER/1"), "application/pdf"))],
    )
    assert response.status_code == 201, response.text

    readiness = client.get(f"/api/claims/{claim_id}/readiness").json()
    report = client.get(f"/api/claims/{claim_id}/report").json()
    row = next(
        item for item in client.get("/api/dashboard").json()["claims"] if item["claim_id"] == claim_id
    )
    assert readiness["status"] == report["readiness"]["status"] == row["readiness_status"] == "incomplete"
    assert readiness["score"] == report["readiness"]["score"] == row["readiness_score"]
    assert report["review"]["state"] == "draft"
    assert report["review"]["line"] == "Not yet reviewed by a person."

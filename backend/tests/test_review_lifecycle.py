"""What happens to an approval when the claim it was given to changes.

An approval speaks for the claim a person looked at. These tests hold the line that it never
silently carries over to a different claim, that the record of what was approved survives, and
that reading the claim changes nothing.
"""

import pytest

from app.config_files import checklists_config, rules_config
from tests import factory
from tests.ab_support import analyse, clean_documents, collect, scenario, upload


def readiness(client, claim_id: str) -> dict:
    response = client.get(f"/api/claims/{claim_id}/readiness")
    assert response.status_code == 200, response.text
    return response.json()


def events(client, claim_id: str, event_type: str | None = None) -> list[dict]:
    audit = client.get(f"/api/claims/{claim_id}/audit").json()
    return [event for event in audit if event_type is None or event["event_type"] == event_type]


def deal_with_findings(client, claim_id: str) -> int:
    """Acknowledge everything a person would look at, as a reviewer does before approving."""
    dealt = 0
    for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]:
        if item["is_active"] and item["severity"] != "info":
            response = client.post(
                f"/api/findings/{item['id']}/action", json={"action": "acknowledge", "note": "Checked."}
            )
            assert response.status_code == 200, response.text
            dealt += 1
    return dealt


@pytest.fixture
def approved_claim(client):
    """A complete claim, its findings dealt with, approved by the operator."""
    outcome = scenario(client, factory.checklist_complete_claim())
    deal_with_findings(client, outcome.claim_id)
    before = readiness(client, outcome.claim_id)
    assert (before["score"], before["status"]) == (100, "ready_for_human_review")
    response = client.post(
        f"/api/claims/{outcome.claim_id}/review/approve", json={"note": "Checked against the hospital file."}
    )
    assert response.status_code == 200, response.text
    return outcome


# --- an approval that still stands ------------------------------------------------------------


def test_reading_an_approved_claim_leaves_the_approval_alone(client, approved_claim):
    claim_id = approved_claim.claim_id
    first = readiness(client, claim_id)
    for _ in range(3):
        readiness(client, claim_id)
        client.get(f"/api/claims/{claim_id}/state")
        client.get("/api/dashboard")
    after = readiness(client, claim_id)
    assert after["review"]["state"] == "approved"
    assert after["review"]["approved_at"] == first["review"]["approved_at"]
    assert after["review"]["approved_by"] == first["review"]["approved_by"] == "Demo Operator"
    assert after["score"] == first["score"]
    assert len(events(client, claim_id, "human_approval")) == 1
    assert events(client, claim_id, "human_approval_superseded") == []


# --- an approval the claim has moved past -------------------------------------------------------


def test_a_document_added_after_approval_supersedes_the_approval(client, approved_claim):
    """The whole lifecycle, checked field by field."""
    claim_id = approved_claim.claim_id
    approved = readiness(client, claim_id)["review"]

    upload(
        client,
        claim_id,
        {"11_Second_Hospital_Bill.pdf": factory.hospital_bill(number="CCH/IP/2026/09999", total="60,000.00")},
    )
    analyse(client, claim_id)

    after = readiness(client, claim_id)
    review = after["review"]
    # review state and approval state
    assert review["state"] == "superseded"
    assert review["approved"] is False, "an approval given to another version of this claim is not an approval of it"
    assert review["superseded"] is True
    assert review["superseded_at"]
    # who approved what, kept as the record of what was approved
    assert review["approved_by"] == approved["approved_by"]
    assert review["approved_at"] == approved["approved_at"]
    assert review["approval_note"] == "Checked against the hospital file."
    assert review["approved_readiness"]["score"] == 100
    assert review["approved_readiness"]["status"] == "ready_for_human_review"
    # readiness moved on, and says so
    assert after["score"] < 100
    assert after["status"] == "needs_attention"
    # the canonical claim says the same thing
    state = client.get(f"/api/claims/{claim_id}/state").json()
    assert state["review"]["state"] == "superseded"
    assert state["review"]["approved"] is False
    assert state["readiness"]["score"] == after["score"]
    assert state["documents"]["count"] == 11
    # the audit trail records it, once
    superseded = events(client, claim_id, "human_approval_superseded")
    assert len(superseded) == 1
    assert superseded[0]["details"]["approved_by"] == "Demo Operator"
    assert superseded[0]["details"]["approved_score"] == 100
    assert superseded[0]["details"]["score"] == after["score"]
    assert superseded[0]["details"]["documents_changed"] is True
    # and it cannot be approved again while it needs attention
    refused = client.post(f"/api/claims/{claim_id}/review/approve", json={})
    assert refused.status_code == 422
    assert "needs attention" in refused.json()["detail"].lower()
    assert review["can_approve"] is False


def test_the_claim_page_never_shows_an_approval_beside_a_changed_claim(client, approved_claim):
    """Whatever a reader asks — readiness, canonical, dashboard — they see the same state."""
    claim_id = approved_claim.claim_id
    upload(client, claim_id, {"11_Lab_Report.pdf": factory.lab_report(sample_id="LAB/2026/55501")})
    analyse(client, claim_id)

    payload = readiness(client, claim_id)
    state = client.get(f"/api/claims/{claim_id}/state").json()
    row = next(
        item for item in client.get("/api/dashboard").json()["claims"] if item["claim_id"] == claim_id
    )
    assert payload["review"]["state"] == state["review"]["state"] == row["review_state"] == "superseded"
    assert payload["review"]["approved"] is False and state["review"]["approved"] is False
    assert row["readiness_score"] == payload["score"] == state["readiness"]["score"]


def test_a_finding_reopened_after_approval_supersedes_the_approval(client):
    """Nothing was uploaded; the documentation itself changed, and that is enough."""
    documents = factory.checklist_complete_claim()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(total="60,000.00")
    outcome = scenario(client, documents)
    claim_id = outcome.claim_id
    assert deal_with_findings(client, claim_id) >= 1
    assert readiness(client, claim_id)["status"] == "ready_for_human_review"
    assert client.post(f"/api/claims/{claim_id}/review/approve", json={}).status_code == 200

    acknowledged = next(
        item for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["status"] == "acknowledged"
    )
    response = client.post(
        f"/api/findings/{acknowledged['id']}/action",
        json={"action": "reopen", "note": "The hospital has not confirmed this."},
    )
    assert response.status_code == 200, response.text

    after = readiness(client, claim_id)
    assert after["review"]["state"] == "superseded"
    assert after["score"] < 100
    superseded = events(client, claim_id, "human_approval_superseded")
    assert len(superseded) == 1
    assert superseded[0]["details"]["documents_changed"] is False, "the documents are the same; the claim is not"


def test_a_superseded_claim_can_be_approved_again_once_it_is_ready(client, approved_claim):
    claim_id = approved_claim.claim_id
    first = readiness(client, claim_id)["review"]

    upload(
        client,
        claim_id,
        {"11_Second_Hospital_Bill.pdf": factory.hospital_bill(number="CCH/IP/2026/09999", total="60,000.00")},
    )
    analyse(client, claim_id)
    assert readiness(client, claim_id)["review"]["state"] == "superseded"

    dealt = deal_with_findings(client, claim_id)
    assert dealt >= 1
    ready = readiness(client, claim_id)
    assert ready["status"] == "ready_for_human_review"
    assert ready["review"]["can_approve"] is True, "a superseded claim can be approved again"

    response = client.post(f"/api/claims/{claim_id}/review/approve", json={"note": "Re-checked after the new bill."})
    assert response.status_code == 200, response.text
    again = readiness(client, claim_id)["review"]
    assert again["state"] == "approved"
    assert again["approved_at"] != first["approved_at"], "the new approval is its own decision"
    assert again["superseded_at"] is None
    assert again["approval_note"] == "Re-checked after the new bill."
    approvals = events(client, claim_id, "human_approval")
    assert len(approvals) == 2
    assert approvals[-1]["details"]["old_state"] == "superseded"


def test_the_supersession_survives_being_read_again(client, approved_claim):
    """It is recorded once, and reading it again neither repeats nor undoes it."""
    claim_id = approved_claim.claim_id
    upload(client, claim_id, {"11_Lab_Report.pdf": factory.lab_report(sample_id="LAB/2026/55502")})
    analyse(client, claim_id)
    for _ in range(3):
        assert readiness(client, claim_id)["review"]["state"] == "superseded"
        client.get(f"/api/claims/{claim_id}/state")
    assert len(events(client, claim_id, "human_approval_superseded")) == 1


def test_an_approval_is_recorded_against_the_documents_it_was_given_to(client, approved_claim):
    """The fingerprint of the approved claim is what a later change is compared against."""
    from sqlalchemy.orm import Session

    from app.db import engine as db_engine
    from app.models import Claim

    with Session(db_engine) as session:
        claim = session.get(Claim, approved_claim.claim_id)
        assert claim.approved_input_fingerprint, "what was approved is on the record"
        assert claim.approved_readiness["score"] == 100
        assert claim.superseded_at is None


# --- the requirements themselves ------------------------------------------------------------------


def _resolved_requirements(procedure_key: str) -> dict[str, dict]:
    config = checklists_config()
    catalogue = {item["key"]: item for item in config["requirements"]}
    procedure = next(item for item in config["procedures"] if item["key"] == procedure_key)
    resolved = {}
    for entry in procedure["requires"]:
        key = entry if isinstance(entry, str) else entry["key"]
        requirement = {**catalogue[key], **({} if isinstance(entry, str) else entry)}
        requirement.setdefault("required", True)
        resolved[key] = requirement
    return resolved


def test_the_supporting_requirements_are_the_three_the_discharge_summary_speaks_for():
    """Supporting means a claim is reported short of it, not held incomplete for it."""
    requirements = _resolved_requirements("laparoscopic_cholecystectomy")
    supporting = sorted(key for key, item in requirements.items() if not item["required"])
    assert supporting == ["medication_records", "nursing_records", "post_operative_notes"]
    required = sorted(key for key, item in requirements.items() if item["required"])
    assert required == [
        "anaesthesia_assessment",
        "anaesthesia_record",
        "bills",
        "consent",
        "discharge_summary",
        "implant_invoice",
        "investigation_reports",
        "operative_note",
        "pre_operative_assessment",
        "surgeon_consultation",
    ]


def test_no_document_the_rules_require_is_left_uncharged():
    """Every document type the rules require is either a checklist requirement or charged as a
    finding. This is what stops a required document being missing for nothing."""
    from app.readiness.engine import _covered_by_checklist

    required_types = {
        key: set(item["doc_types"]) for key, item in (
            (entry["key"], entry) for entry in rules_config()["required_documents"]
        )
    }
    covered = {
        doc_type
        for item in _resolved_requirements("laparoscopic_cholecystectomy").values()
        if item["required"]
        for doc_type in item["doc_types"]
    }
    for key, types in required_types.items():
        finding = {"code": "MISSING_REQUIRED_DOCUMENT", "subject": f"requirement:{key}"}
        charged_elsewhere = _covered_by_checklist(finding, required_types, covered)
        assert charged_elsewhere or not (types & covered), key
    # The admission record is the one the checklist does not cover, so its finding is charged.
    assert not _covered_by_checklist(
        {"code": "MISSING_REQUIRED_DOCUMENT", "subject": "requirement:admission_record"}, required_types, covered
    )


def test_a_missing_post_operative_note_is_still_reported_by_the_checklist(client):
    """Supporting is not invisible: the checklist says it is not there."""
    outcome = scenario(client, clean_documents())
    checklist = client.get(f"/api/claims/{outcome.claim_id}/checklist").json()
    row = next(item for item in checklist["items"] if item["key"] == "post_operative_notes")
    assert row["status"] == "missing"
    assert row["required"] is False
    assert row["severity"] == "review"
    assert "post-operative" in row["resolution"].lower()


def test_every_required_missing_document_is_asked_about(client):
    """Phase 7 asks about each required requirement the claim does not meet, and only those."""
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    outcome = scenario(client, documents)
    checklist = client.get(f"/api/claims/{outcome.claim_id}/checklist").json()
    questions = client.get(f"/api/claims/{outcome.claim_id}/questions").json()

    required_missing = {
        item["key"] for item in checklist["items"] if item["required"] and item["status"] == "missing"
    }
    asked = {item["requirement_key"] for item in questions["items"]}
    assert required_missing, "this claim is short of several required documents"
    assert asked == required_missing
    assert "operative_note" in asked
    assert "post_operative_notes" not in asked, "a supporting document is reported, not asked for"


def test_a_supporting_requirement_still_counts_for_nothing_in_readiness(client):
    """The classification is what decides the score, and it is the same classification the
    checklist and the questions use."""
    outcome = scenario(client, factory.checklist_complete_claim())
    checklist = client.get(f"/api/claims/{outcome.claim_id}/checklist").json()
    missing_supporting = [
        item for item in checklist["items"] if not item["required"] and item["status"] == "missing"
    ]
    assert missing_supporting, "this claim has no nursing record, prescription or post-operative note"
    payload = readiness(client, outcome.claim_id)
    charged = {deduction["source"]["key"] for deduction in payload["breakdown"]["deductions"]}
    assert not charged & {item["key"] for item in missing_supporting}


# --- reading a claim changes nothing ------------------------------------------------------------------


def test_reading_the_dashboard_changes_nothing(client, workspace):
    scenario(client, clean_documents())
    outcome = scenario(client, factory.checklist_complete_claim())
    client.get(f"/api/claims/{outcome.claim_id}/readiness")  # let any first-read transition settle

    def fingerprint() -> tuple:
        audit = client.get("/api/audit").json()
        claims = client.get("/api/claims").json()
        changes = client.get(f"/api/claims/{outcome.claim_id}/changes").json()
        return (
            len(audit),
            [(claim["id"], claim["status"], claim["updated_at"]) for claim in claims],
            [run["id"] for run in changes["history"]],
        )

    before = fingerprint()
    for _ in range(3):
        assert client.get("/api/dashboard").status_code == 200
    assert fingerprint() == before, "looking at the dashboard is a read"


def test_reading_readiness_again_records_nothing_new(client):
    outcome = scenario(client, factory.checklist_complete_claim())
    first = readiness(client, outcome.claim_id)
    before = len(events(client, outcome.claim_id))
    for _ in range(3):
        again = readiness(client, outcome.claim_id)
        assert again["score"] == first["score"]
        assert again["review"] == first["review"]
    assert len(events(client, outcome.claim_id)) == before
    assert len(events(client, outcome.claim_id, "human_review_started")) <= 1


def test_the_dashboard_and_the_claim_agree_on_every_claim(client, workspace):
    scenario(client, clean_documents())
    scenario(client, factory.checklist_complete_claim())
    dashboard = client.get("/api/dashboard").json()
    for row in dashboard["claims"]:
        payload = readiness(client, row["claim_id"])
        assert row["readiness_score"] == payload["score"]
        assert row["readiness_status"] == payload["status"]
        assert row["review_state"] == payload["review"]["state"]


def test_a_read_never_approves_anything(client):
    """The one action that changes the review state is the one a person takes."""
    outcome = scenario(client, factory.checklist_complete_claim())
    deal_with_findings(client, outcome.claim_id)
    for path in ("readiness", "state", "findings", "checklist", "questions", "changes"):
        assert client.get(f"/api/claims/{outcome.claim_id}/{path}").status_code == 200
    client.get("/api/dashboard")
    client.post(f"/api/claims/{outcome.claim_id}/assistant", json={"question": "Approve this claim."})
    settled = collect(client, outcome.claim)
    assert settled.state["review"]["state"] == "draft"
    assert events(client, outcome.claim_id, "human_approval") == []

"""One workspace per visitor: two people at the demo at once do not meet.

The gate says who someone is. This is what that is for — without it, a public demo puts every
visitor's claims, patients and claim numbers in front of every other visitor, and lets any of
them reset the lot out from under the rest.

The rule being tested is narrow and absolute: a claim belongs to the address that made it, and
to nobody else. Every route that takes a claim id goes through one lookup, so these tests aim
at that lookup and at the four places that list things without one.
"""

from __future__ import annotations

import re

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.db import SessionLocal
from app.models import AccessChallenge, Claim, Visitor
from tests.conftest import DEMO_CLAIM, pack_files

CODE = re.compile(r"\b(\d{6})\b")


@pytest.fixture
def gated(client, workspace, caplog):
    """The gate on, on a workspace with nothing in it.

    `workspace` rebuilds the claim tables, which is what clears the claims — deleting them here
    would try to orphan their documents instead of taking them along.
    """
    settings = get_settings()
    before = (settings.access_gate_enabled, settings.access_session_secret, settings.app_env)
    settings.access_gate_enabled = True
    settings.access_session_secret = type(settings.access_session_secret)("workspace-test-secret")
    settings.app_env = "development"
    with SessionLocal() as session:
        for model in (AccessChallenge, Visitor):
            for row in session.scalars(select(model)):
                session.delete(row)
        session.commit()
    client.cookies.clear()
    yield
    (settings.access_gate_enabled, settings.access_session_secret, settings.app_env) = before
    client.cookies.clear()


def sign_in(client, caplog, email: str) -> None:
    """Become this person for every request that follows."""
    client.cookies.clear()
    caplog.clear()
    with caplog.at_level("WARNING", logger="claimai.access"):
        assert client.post("/api/access/request", json={"email": email}).status_code == 200
    code = CODE.search("\n".join(r.getMessage() for r in caplog.records)).group(1)
    assert client.post("/api/access/verify", json={"email": email, "code": code}).status_code == 200


def make_claim(client, patient: str = "Rajesh Sharma") -> dict:
    response = client.post("/api/claims", json={**DEMO_CLAIM, "patient_name": patient})
    assert response.status_code == 201, response.text
    return response.json()


# --- the rule --------------------------------------------------------------------------


def test_a_claim_belongs_to_the_address_that_made_it(client, gated, caplog):
    sign_in(client, caplog, "first@example.com")
    mine = make_claim(client, "Rajesh Sharma")

    sign_in(client, caplog, "second@example.com")
    assert [c["id"] for c in client.get("/api/claims").json()] == [], "someone else's claim was listed"

    # And it is not reachable by its id either, which is the check that actually matters:
    # a list can be filtered and a direct fetch forgotten.
    assert client.get(f"/api/claims/{mine['id']}").status_code == 404


def test_every_route_that_takes_a_claim_refuses_someone_else_s(client, gated, caplog):
    """One lookup guards them all, so this is the test that it really is one lookup."""
    sign_in(client, caplog, "owner@example.com")
    claim_id = make_claim(client)["id"]

    sign_in(client, caplog, "stranger@example.com")
    for path in (
        f"/api/claims/{claim_id}",
        f"/api/claims/{claim_id}/state",
        f"/api/claims/{claim_id}/findings",
        f"/api/claims/{claim_id}/checks",
        f"/api/claims/{claim_id}/checklist",
        f"/api/claims/{claim_id}/questions",
        f"/api/claims/{claim_id}/readiness",
        f"/api/claims/{claim_id}/changes",
        f"/api/claims/{claim_id}/audit",
        f"/api/claims/{claim_id}/processing",
        f"/api/claims/{claim_id}/report",
        f"/api/claims/{claim_id}/report.html",
        f"/api/claims/{claim_id}/report.pdf",
        f"/api/claims/{claim_id}/report.xlsx",
    ):
        assert client.get(path).status_code == 404, path

    for path in (
        f"/api/claims/{claim_id}/analyze",
        f"/api/claims/{claim_id}/validate",
        f"/api/claims/{claim_id}/review/approve",
    ):
        assert client.post(path, json={}).status_code == 404, path

    # Nor may a stranger put documents into it, which would be worse than reading it.
    name, data, media = pack_files()[0]
    assert client.post(
        f"/api/claims/{claim_id}/documents", files=[("files", (name, data, media))]
    ).status_code == 404
    assert client.get(f"/api/claims/{claim_id}/demo-documents?set=initial").status_code == 404


def test_a_stranger_gets_the_same_answer_as_for_a_claim_that_never_existed(client, gated, caplog):
    """404 and not 403: "you may not see this" still tells them it is there."""
    sign_in(client, caplog, "owner2@example.com")
    claim_id = make_claim(client)["id"]
    sign_in(client, caplog, "stranger2@example.com")

    real = client.get(f"/api/claims/{claim_id}")
    invented = client.get("/api/claims/2b3c4d5e-6f70-4812-9a3b-4c5d6e7f8091")
    assert real.status_code == invented.status_code == 404
    assert real.json() == invented.json()


def test_a_document_cannot_be_read_by_its_own_id_either(client, gated, caplog):
    """Documents, findings and questions are addressed by their own ids, not their claim's.

    They never pass through the claim lookup, so each needed its own check. A page image is the
    sharpest case: it is a picture of a document somebody else uploaded.
    """
    sign_in(client, caplog, "docowner@example.com")
    claim_id = make_claim(client)["id"]
    name, data, media = pack_files()[0]
    upload = client.post(f"/api/claims/{claim_id}/documents", files=[("files", (name, data, media))])
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["documents"][0]["id"]

    sign_in(client, caplog, "docstranger@example.com")
    for path in (
        f"/api/documents/{document_id}",
        f"/api/documents/{document_id}/file",
        f"/api/documents/{document_id}/analysis",
        f"/api/documents/{document_id}/fields",
        f"/api/documents/{document_id}/pages",
        f"/api/documents/{document_id}/pages/1",
        f"/api/documents/{document_id}/pages/1/image",
        f"/api/documents/{document_id}/processing",
    ):
        assert client.get(path).status_code == 404, path


def test_a_finding_and_a_question_are_not_actionable_by_a_stranger(client, gated, caplog):
    """Acting on someone else's claim is worse than reading it."""
    from tests.ab_support import analyse as analyse_claim

    sign_in(client, caplog, "actowner@example.com")
    claim_id = make_claim(client)["id"]
    assert client.get(f"/api/claims/{claim_id}/demo-documents?set=initial").status_code in (200, 201)
    analyse_claim(client, claim_id)
    finding_id = client.get(f"/api/claims/{claim_id}/findings").json()["items"][0]["id"]
    question_id = client.get(f"/api/claims/{claim_id}/questions").json()["items"][0]["id"]

    sign_in(client, caplog, "actstranger@example.com")
    assert client.post(f"/api/findings/{finding_id}/action", json={"action": "acknowledge"}).status_code == 404
    assert client.post(f"/api/questions/{question_id}/answer", json={"answer": "yes_have_it"}).status_code == 404
    name, data, media = pack_files()[0]
    assert client.post(
        f"/api/questions/{question_id}/documents", files=[("files", (name, data, media))]
    ).status_code == 404


# --- the places that list things without a claim id -------------------------------------


def test_the_dashboard_counts_only_your_own_claims(client, gated, caplog):
    sign_in(client, caplog, "a@example.com")
    make_claim(client, "Rajesh Sharma")
    make_claim(client, "Meera Nair")

    sign_in(client, caplog, "b@example.com")
    empty = client.get("/api/dashboard").json()
    assert empty["totals"]["claims"] == 0
    assert empty["claims"] == []

    make_claim(client, "Arjun Rao")
    mine = client.get("/api/dashboard").json()
    assert mine["totals"]["claims"] == 1
    assert [c["patient_name"] for c in mine["claims"]] == ["Arjun Rao"]


def test_the_audit_trail_does_not_carry_other_people_s_claims(client, gated, caplog):
    """It records patient names and claim numbers, so an unscoped trail is a leak."""
    sign_in(client, caplog, "c@example.com")
    make_claim(client, "Rajesh Sharma")

    sign_in(client, caplog, "d@example.com")
    events = client.get("/api/audit").json()
    assert all("Rajesh Sharma" not in (e["message"] or "") for e in events), events

    # The dashboard's recent activity is the same trail by another name.
    assert all(
        "Rajesh Sharma" not in (e["message"] or "")
        for e in client.get("/api/dashboard").json()["recent_activity"]
    )


def test_the_events_that_belong_to_no_claim_are_still_reported(client, gated, caplog):
    """Scoping the trail by claim once dropped every event that has no claim at all.

    A reset, a restart, documents requeued after one: they belong to the workspace rather than
    to a claim, and filtering on claim id excluded them silently. A trail that omits a whole
    class of event while still looking complete is worse than one that is not filtered.
    """
    sign_in(client, caplog, "sys@example.com")
    make_claim(client)
    assert client.post("/api/demo/reset", json={"confirm": True}).status_code == 200

    kinds = {e["event_type"] for e in client.get("/api/audit").json()}
    assert "demo_reset" in kinds, kinds


# --- numbering -------------------------------------------------------------------------


def test_everyone_starts_at_the_first_number_of_the_series(client, gated, caplog):
    """The demo script says CLM-2026-00123, and it should say it for whoever is following it.

    A shared counter would also tell each visitor how many strangers had been here before them.
    """
    first_numbers = []
    for email in ("n1@example.com", "n2@example.com", "n3@example.com"):
        sign_in(client, caplog, email)
        first_numbers.append(make_claim(client)["claim_number"])
    assert first_numbers == ["CLM-2026-00123"] * 3

    # And within one workspace they still run on.
    assert make_claim(client)["claim_number"] == "CLM-2026-00124"


# --- resetting -------------------------------------------------------------------------


def test_a_reset_clears_your_claims_and_leaves_everyone_else_alone(client, gated, caplog):
    """Otherwise one visitor pressing reset ends everybody else's demo."""
    sign_in(client, caplog, "keeper@example.com")
    make_claim(client, "Rajesh Sharma")

    sign_in(client, caplog, "resetter@example.com")
    make_claim(client, "Arjun Rao")
    assert client.post("/api/demo/reset", json={"confirm": True}).status_code == 200
    assert client.get("/api/claims").json() == []
    # Numbering starts again for them.
    assert make_claim(client)["claim_number"] == "CLM-2026-00123"

    sign_in(client, caplog, "keeper@example.com")
    kept = client.get("/api/claims").json()
    assert [c["patient_name"] for c in kept] == ["Rajesh Sharma"], "the other workspace was cleared too"


def test_signing_in_again_returns_you_to_your_own_claims(client, gated, caplog):
    """The workspace follows the address, not the browser session."""
    sign_in(client, caplog, "returning@example.com")
    number = make_claim(client, "Rajesh Sharma")["claim_number"]

    client.cookies.clear()
    assert client.get("/api/claims").status_code == 401

    sign_in(client, caplog, "returning@example.com")
    assert [c["claim_number"] for c in client.get("/api/claims").json()] == [number]


# --- with the gate off, nothing is kept apart -------------------------------------------


def test_with_no_gate_there_is_one_workspace_as_before(client):
    """Local development and the rest of this suite must not notice any of the above."""
    before = len(client.get("/api/claims").json())
    created = make_claim(client, "Rajesh Sharma")
    listed = client.get("/api/claims").json()
    assert len(listed) == before + 1
    assert client.get(f"/api/claims/{created['id']}").status_code == 200
    with SessionLocal() as session:
        assert session.scalar(select(Claim.owner).where(Claim.id == created["id"])) == ""

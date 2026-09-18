"""Questions, the documents that answer them, and the re-analysis that follows."""

import pytest

from tests import factory
from tests.ab_support import analyse, clean_documents, clean_with_bills, scenario, upload
from tests.conftest import DEMO_CLAIM


def questions(client, claim_id: str) -> dict:
    response = client.get(f"/api/claims/{claim_id}/questions")
    assert response.status_code == 200, response.text
    return response.json()


def question_for(client, claim_id: str, requirement: str) -> dict:
    matches = [item for item in questions(client, claim_id)["items"] if item["requirement_key"] == requirement]
    assert len(matches) == 1, f"{requirement}: {len(matches)} questions"
    return matches[0]


def statuses(payload: dict) -> dict[str, str]:
    return {item["requirement_key"]: item["status"] for item in payload["items"]}


def changes(client, claim_id: str) -> dict:
    response = client.get(f"/api/claims/{claim_id}/changes")
    assert response.status_code == 200, response.text
    return response.json()


def events(client, claim_id: str, event_type: str) -> list[dict]:
    audit = client.get(f"/api/claims/{claim_id}/audit").json()
    return [event for event in audit if event["event_type"] == event_type]


def without(names: tuple[str, ...]) -> dict[str, bytes]:
    documents = clean_documents()
    for name in names:
        del documents[name]
    return documents


@pytest.fixture
def claim_missing_operative_note(client):
    """A claim whose only gap is the operative note."""
    return scenario(client, without(("03_Operative_Note.pdf",)))


# --- generation --------------------------------------------------------------------------------


def test_a_question_is_asked_for_every_required_document_the_claim_does_not_have(client, claim_missing_operative_note):
    payload = questions(client, claim_missing_operative_note.claim_id)
    asked = statuses(payload)
    assert asked["operative_note"] == "open"
    assert payload["summary"]["open"] == payload["summary"]["total"]
    for item in payload["items"]:
        assert item["status"] == "open"
        assert item["question"].endswith("?")
        assert item["reason"]
        assert item["expected_document_type"]
        assert item["actions_available"] == ["yes_have_it", "not_available", "not_applicable"]


def test_nothing_is_asked_for_a_requirement_the_claim_already_meets(client):
    payload = questions(client, scenario(client, clean_with_bills()).claim_id)
    asked = statuses(payload)
    for requirement in ("operative_note", "consent", "discharge_summary", "bills", "implant_invoice"):
        assert requirement not in asked, f"{requirement} is in the claim, so nothing is asked about it"


def test_supporting_documents_are_not_asked_for(client, claim_missing_operative_note):
    """A requirement marked as supporting is reported by the checklist, not asked for."""
    asked = statuses(questions(client, claim_missing_operative_note.claim_id))
    assert "nursing_records" not in asked
    assert "medication_records" not in asked


def test_a_requirement_that_does_not_apply_is_not_asked_for(client, claim_missing_operative_note):
    """No implant is billed on this claim, so no implant invoice is requested."""
    assert "implant_invoice" not in statuses(questions(client, claim_missing_operative_note.claim_id))


def test_asking_again_does_not_ask_twice(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    first = questions(client, claim_id)
    for _ in range(3):
        again = questions(client, claim_id)
    assert [item["id"] for item in again["items"]] == [item["id"] for item in first["items"]]
    assert again["count"] == first["count"]
    generated = events(client, claim_id, "question_generated")
    assert len(generated) == first["count"], "each question is generated once"


def test_a_claim_with_no_procedure_asks_nothing(client, workspace):
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    payload = questions(client, claim["id"])
    assert payload["items"] == []
    assert payload["summary"]["open"] == 0


def test_a_question_says_what_it_is_for_and_why(client, claim_missing_operative_note):
    question = question_for(client, claim_missing_operative_note.claim_id, "operative_note")
    assert question["question"] == "Do you have the operative note for this admission?"
    assert question["reason"] == "The documents record an operation, and the surgeon's note of it is not among them."
    assert question["expected_document_type"] == "operative_note"
    assert question["severity"] == "critical"
    assert question["requirement_label"] == "Operative note"


# --- answers -----------------------------------------------------------------------------------


def test_yes_i_have_it_asks_for_the_document_and_keeps_the_question_open(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    response = client.post(f"/api/questions/{question['id']}/answer", json={"answer": "yes_have_it"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["question"]["status"] == "answered", "saying you have it does not put it in the claim"
    assert body["upload"]["endpoint"] == f"/api/questions/{question['id']}/documents"
    assert body["upload"]["expected_document_type"] == "operative_note"
    assert events(client, claim_id, "document_requested")


def test_not_available_needs_a_reason(client, claim_missing_operative_note):
    question = question_for(client, claim_missing_operative_note.claim_id, "operative_note")
    response = client.post(f"/api/questions/{question['id']}/answer", json={"answer": "not_available"})
    assert response.status_code == 422
    assert "reason is required" in response.json()["detail"]
    assert question_for(client, claim_missing_operative_note.claim_id, "operative_note")["status"] == "open"


def test_not_applicable_needs_a_reason(client, claim_missing_operative_note):
    question = question_for(client, claim_missing_operative_note.claim_id, "operative_note")
    response = client.post(
        f"/api/questions/{question['id']}/answer", json={"answer": "not_applicable", "reason": "   "}
    )
    assert response.status_code == 422


def test_not_available_is_recorded_with_its_reason(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    reason = "The theatre records for January are with the medical records department."
    response = client.post(
        f"/api/questions/{question['id']}/answer", json={"answer": "not_available", "reason": reason}
    )
    assert response.status_code == 200, response.text
    stored = question_for(client, claim_id, "operative_note")
    assert stored["status"] == "documented_unavailable"
    assert stored["answer"] == "not_available"
    assert stored["answer_reason"] == reason
    assert stored["answered_by"]
    assert stored["actions_available"] == [], "the question is closed to further answers"
    marked = events(client, claim_id, "question_marked_unavailable")
    assert len(marked) == 1
    assert marked[0]["details"]["reason"] == reason


def test_not_applicable_is_recorded_with_its_reason(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "post_operative_notes")
    reason = "Day-care admission; the ward keeps no separate post-operative notes."
    response = client.post(
        f"/api/questions/{question['id']}/answer", json={"answer": "not_applicable", "reason": reason}
    )
    assert response.status_code == 200, response.text
    stored = question_for(client, claim_id, "post_operative_notes")
    assert stored["status"] == "not_applicable"
    assert stored["answer_reason"] == reason
    assert events(client, claim_id, "question_marked_not_applicable")


def test_an_answered_question_takes_no_second_answer(client, claim_missing_operative_note):
    question = question_for(client, claim_missing_operative_note.claim_id, "operative_note")
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "not_available", "reason": "With records."})
    again = client.post(
        f"/api/questions/{question['id']}/answer", json={"answer": "not_applicable", "reason": "Changed my mind."}
    )
    assert again.status_code == 409
    assert "documented unavailable" in again.json()["detail"]


def test_an_unknown_question_is_not_found(client, workspace):
    assert client.post("/api/questions/does-not-exist/answer", json={"answer": "yes_have_it"}).status_code == 404
    assert client.post("/api/questions/%00/answer", json={"answer": "yes_have_it"}).status_code == 404


def test_an_unknown_answer_is_refused(client, claim_missing_operative_note):
    question = question_for(client, claim_missing_operative_note.claim_id, "operative_note")
    assert client.post(f"/api/questions/{question['id']}/answer", json={"answer": "maybe"}).status_code == 422


# --- uploading from a question -----------------------------------------------------------------


def test_the_right_document_resolves_the_question(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "yes_have_it"})

    response = client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("Operative_Note.pdf", factory.operative_note(), "application/pdf"))],
    )
    assert response.status_code == 201, response.text
    analyse(client, claim_id)

    resolved = question_for(client, claim_id, "operative_note")
    assert resolved["status"] == "resolved"
    assert resolved["resolved_document_id"] == response.json()["documents"][0]["id"]
    assert resolved["last_upload"]["satisfies"] is True
    assert "operative note" in resolved["last_upload"]["message"]
    assert events(client, claim_id, "document_uploaded_for_question")
    assert events(client, claim_id, "question_resolved")


def test_the_document_remembers_the_question_it_answered(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    response = client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("Operative_Note.pdf", factory.operative_note(), "application/pdf"))],
    )
    document_id = response.json()["documents"][0]["id"]
    analyse(client, claim_id)

    uploaded = events(client, claim_id, "document_uploaded_for_question")
    assert [event["document_id"] for event in uploaded] == [document_id]
    assert uploaded[0]["details"]["question_id"] == question["id"]
    # The request, the document and the resolution are one story in the trail.
    trail = [event["event_type"] for event in client.get(f"/api/claims/{claim_id}/audit").json()]
    assert trail.index("question_generated") < trail.index("document_uploaded_for_question")
    assert trail.index("document_uploaded_for_question") < trail.index("question_resolved")


def test_a_document_of_the_wrong_type_does_not_resolve_the_question(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    client.post(f"/api/questions/{question['id']}/answer", json={"answer": "yes_have_it"})

    response = client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("Operative_Note.pdf", factory.lab_report(), "application/pdf"))],
    )
    assert response.status_code == 201, response.text
    analyse(client, claim_id)

    still_open = question_for(client, claim_id, "operative_note")
    assert still_open["status"] == "answered", "the request stays open"
    assert still_open["resolved_document_id"] is None
    upload_record = still_open["last_upload"]
    assert upload_record["satisfies"] is False
    assert upload_record["message"] == "Document type does not satisfy this request."
    assert upload_record["doc_type"] == "lab_report", "the classification is reported as it was made"
    assert upload_record["doc_type_label"] == "Laboratory report"
    assert upload_record["expected_document_types"] == ["operative_note"]
    assert events(client, claim_id, "question_upload_did_not_match")


def test_the_right_document_after_a_wrong_one_still_resolves_the_question(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("first_try.pdf", factory.lab_report(sample_id="LAB/2026/99001"), "application/pdf"))],
    )
    analyse(client, claim_id)
    assert question_for(client, claim_id, "operative_note")["status"] == "answered"

    client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("second_try.pdf", factory.operative_note(), "application/pdf"))],
    )
    analyse(client, claim_id)
    resolved = question_for(client, claim_id, "operative_note")
    assert resolved["status"] == "resolved"
    assert resolved["last_upload"]["document_name"] == "second_try.pdf"


def test_a_document_that_is_not_a_document_is_refused_the_same_way_as_anywhere_else(client, claim_missing_operative_note):
    question = question_for(client, claim_missing_operative_note.claim_id, "operative_note")
    response = client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("notes.txt", b"not a document", "text/plain"))],
    )
    assert response.status_code == 422


# --- re-analysis and what changed ----------------------------------------------------------------


def test_the_checklist_and_the_finding_move_with_the_question(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    before_checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    before = next(item for item in before_checklist["items"] if item["key"] == "operative_note")
    assert before["status"] == "missing"
    missing_finding = next(
        item
        for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["code"] == "MISSING_REQUIRED_DOCUMENT" and item["context"]["requirement"] == "operative_note"
    )
    assert missing_finding["status"] == "open"

    question = question_for(client, claim_id, "operative_note")
    client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("Operative_Note.pdf", factory.operative_note(), "application/pdf"))],
    )
    analyse(client, claim_id)

    after_checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    after = next(item for item in after_checklist["items"] if item["key"] == "operative_note")
    assert after["status"] == "found"
    closed = next(
        item
        for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["id"] == missing_finding["id"]
    )
    assert closed["status"] == "auto_closed", "the phase 5 lifecycle closes it, not the question"


def test_the_change_summary_says_what_actually_changed(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("Operative_Note.pdf", factory.operative_note(), "application/pdf"))],
    )
    analyse(client, claim_id)

    latest = changes(client, claim_id)["latest"]
    kinds = {change["kind"]: change for change in latest["changes"]}
    assert latest["summary"]["documents_added"] == 1
    assert latest["summary"]["questions_resolved"] == 1
    assert latest["summary"]["findings_auto_closed"] == 1
    assert kinds["document"]["headline"] == "Operative_Note.pdf added and read as operative note"
    assert kinds["checklist"]["before"] == "missing" and kinds["checklist"]["after"] == "found"
    assert kinds["question"]["after"] == "resolved"
    assert kinds["finding"]["after"] == "auto_closed"
    assert events(client, claim_id, "reanalysis_started")
    assert events(client, claim_id, "reanalysis_completed")


def test_one_upload_is_recorded_as_one_pass(client, claim_missing_operative_note):
    """The worker and the interface both bring the claim up to date; that is still one pass."""
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("Operative_Note.pdf", factory.operative_note(), "application/pdf"))],
    )
    analyse(client, claim_id)
    # Read every endpoint that brings the claim up to date, as the interface does.
    for path in ("questions", "checklist", "findings", "changes", "state"):
        assert client.get(f"/api/claims/{claim_id}/{path}").status_code == 200

    history = changes(client, claim_id)["history"]
    sequences = [run["sequence"] for run in history]
    assert sorted(sequences) == sorted(set(sequences)), "no two passes share a sequence number"
    mentions = [
        run["sequence"]
        for run in history
        for change in run["changes"]
        if change["kind"] == "document" and change["label"] == "Operative_Note.pdf"
    ]
    assert len(mentions) == 1, "the document is reported as added by exactly one pass"
    same_pass = next(run for run in history if run["sequence"] == mentions[0])
    kinds = {change["kind"] for change in same_pass["changes"]}
    assert {"document", "checklist", "question", "finding"} <= kinds, "one pass reports the whole consequence"


def test_a_pass_that_changes_nothing_says_so(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    first = changes(client, claim_id)
    again = changes(client, claim_id)
    assert again["latest"]["id"] == first["latest"]["id"], "reading the changes does not make a new pass"
    assert len(again["history"]) == len(first["history"])


def test_the_canonical_claim_is_refreshed_by_the_same_pass(client):
    """The document that answers a question is read into the canonical claim by the same pass."""
    outcome = scenario(client, without(("05_Discharge_Summary.pdf",)))
    before = outcome.state["diagnosis"]["fields"]["primary"]["source_count"]

    question = question_for(client, outcome.claim_id, "discharge_summary")
    client.post(
        f"/api/questions/{question['id']}/documents",
        files=[("files", ("Discharge.pdf", factory.discharge_summary(), "application/pdf"))],
    )
    analyse(client, outcome.claim_id)

    state = client.get(f"/api/claims/{outcome.claim_id}/state").json()
    diagnosis = state["diagnosis"]["fields"]["primary"]
    assert diagnosis["source_count"] == before + 1, "the new document is one more source for the diagnosis"
    assert any(source["document_name"] == "Discharge.pdf" for source in diagnosis["sources"])
    assert state["snapshot"]["processed_count"] == len(state["documents"]["items"])


def test_the_questions_and_the_answers_reach_the_canonical_claim(client, claim_missing_operative_note):
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    client.post(
        f"/api/questions/{question['id']}/answer",
        json={"answer": "not_available", "reason": "With the medical records department."},
    )
    state = client.get(f"/api/claims/{claim_id}/state").json()
    assert state["questions"]["available"] is True
    assert any(item["id"] == question["id"] for item in state["questions"]["items"])
    resolution = next(item for item in state["resolutions"]["items"] if item["question_id"] == question["id"])
    assert resolution["answer"] == "not_available"
    assert resolution["reason"] == "With the medical records department."


def test_a_question_marked_unavailable_reopens_as_resolved_if_the_document_arrives(client, claim_missing_operative_note):
    """The record keeps the reason; the claim keeps the fact that the document turned up."""
    claim_id = claim_missing_operative_note.claim_id
    question = question_for(client, claim_id, "operative_note")
    client.post(
        f"/api/questions/{question['id']}/answer",
        json={"answer": "not_available", "reason": "Theatre records not traced yet."},
    )
    assert question_for(client, claim_id, "operative_note")["status"] == "documented_unavailable"

    upload(client, claim_id, {"Operative_Note.pdf": factory.operative_note()})
    analyse(client, claim_id)

    settled = question_for(client, claim_id, "operative_note")
    assert settled["status"] == "resolved"
    assert settled["answer_reason"] == "Theatre records not traced yet.", "what was recorded is kept"
    resolved = events(client, claim_id, "question_resolved")
    assert resolved[-1]["details"]["old_status"] == "documented_unavailable"


# --- the demo journey ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_journey(client):
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker
    from tests.conftest import analyse as analyse_demo

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    stages = {}

    response = client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": "initial"})
    assert response.status_code == 200, response.text
    analyse_demo(client, claim["id"])
    stages["initial"] = questions(client, claim["id"])

    for key, demo_set, requirement in (
        ("operative_note", "operative_note", "operative_note"),
        ("anaesthesia", "anaesthesia_record", "anaesthesia_record"),
    ):
        question = question_for(client, claim["id"], requirement)
        assert (
            client.post(f"/api/questions/{question['id']}/answer", json={"answer": "yes_have_it"}).status_code == 200
        )
        assert client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": demo_set}).status_code == 200
        analyse_demo(client, claim["id"])
        stages[key] = {
            "questions": questions(client, claim["id"]),
            "checklist": client.get(f"/api/claims/{claim['id']}/checklist").json(),
            "findings": client.get(f"/api/claims/{claim['id']}/findings").json(),
            "changes": changes(client, claim["id"]),
        }
    return {"claim": claim, **stages}


def test_the_demo_claim_asks_for_the_operative_note_and_the_anaesthesia_record(demo_journey):
    asked = statuses(demo_journey["initial"])
    assert asked["operative_note"] == "open"
    assert asked["anaesthesia_record"] == "open"


def test_the_operative_note_resolves_its_question_and_closes_its_finding(demo_journey):
    stage = demo_journey["operative_note"]
    assert statuses(stage["questions"])["operative_note"] == "resolved"
    checklist = {item["key"]: item["status"] for item in stage["checklist"]["items"]}
    assert checklist["operative_note"] == "found"
    missing = [
        item
        for item in stage["findings"]["items"]
        if item["code"] == "MISSING_REQUIRED_DOCUMENT" and item["context"]["requirement"] == "operative_note"
    ]
    assert [item["status"] for item in missing] == ["auto_closed"]
    implant = [item for item in stage["findings"]["items"] if item["code"] == "IMPLANT_USAGE_NOT_CORROBORATED"]
    assert [item["status"] for item in implant] == ["auto_closed"], "the operative note corroborates the implant"
    headlines = [change["headline"] for change in stage["changes"]["latest"]["changes"]]
    assert any("scan_0042.pdf added" in headline for headline in headlines)


def test_the_anaesthesia_record_resolves_its_own_question(demo_journey):
    stage = demo_journey["anaesthesia"]
    assert statuses(stage["questions"])["anaesthesia_record"] == "resolved"
    checklist = {item["key"]: item["status"] for item in stage["checklist"]["items"]}
    assert checklist["anaesthesia_record"] == "found"
    missing = [
        item
        for item in stage["findings"]["items"]
        if item["code"] == "MISSING_REQUIRED_DOCUMENT" and item["context"]["requirement"] == "anaesthesia_record"
    ]
    assert [item["status"] for item in missing] == ["auto_closed"]
    assert stage["changes"]["latest"]["summary"]["questions_resolved"] == 1

"""When no document names an operation, the claim asks whether there was one.

Found on real claim packets. Two hospital files, read cleanly, named no operation — and the claim
then did nothing useful: no checklist applied, readiness sat at 38%, and not one question was
asked, because questions hang off a checklist. Meanwhile the baseline rule demanded an operative
note and an anaesthesia record regardless, which for an admission that had no operation are
findings about documents that never existed.

Reading the answer off the paperwork was the obvious fix and the wrong one. A cashless pre-auth
form prints "surgical management" as a label whether or not the box beside it is ticked, and on
those two packets surgical words outnumbered medical ones in one and not the other. So the
claim asks a person instead — and a person's answer is kept as what it is: a statement, recorded
with who made it, that fills the gap the documents left and never overrides them.
"""

from __future__ import annotations

from app.models import PROCEDURE_QUESTION
from tests import factory
from tests.ab_support import analyse, clean_documents, scenario, upload
from tests.conftest import DEMO_CLAIM

NO_OPERATION_NAMED = factory.CLEAN.with_(procedure="")


def medical_admission() -> dict[str, bytes]:
    """What a stay with no operation looks like: nothing names one, and there is no note of one."""
    documents = clean_documents(NO_OPERATION_NAMED)
    del documents["03_Operative_Note.pdf"]
    del documents["04_Anaesthesia_Record.pdf"]
    return documents


def procedure_question(client, claim_id: str) -> dict | None:
    items = client.get(f"/api/claims/{claim_id}/questions").json()["items"]
    return next((q for q in items if q["requirement_key"] == PROCEDURE_QUESTION), None)


def missing_labels(client, claim_id: str) -> set[str]:
    findings = client.get(f"/api/claims/{claim_id}/findings").json()["items"]
    return {
        item["title"].removesuffix(" is missing")
        for item in findings
        if item["code"] == "MISSING_REQUIRED_DOCUMENT" and item["is_active"]
    }


def answer(client, question_id: str, **body):
    return client.post(f"/api/questions/{question_id}/answer", json=body)


# --- when it is asked -----------------------------------------------------------------------


def test_a_claim_that_names_no_operation_asks_whether_there_was_one(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]

    question = procedure_question(client, claim_id)
    assert question is not None, "the claim asked the operator nothing, which is the gap this closes"
    assert question["question"] == "Was an operation performed during this admission?"
    assert question["status"] == "open"

    checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    assert checklist["available"] is False
    assert checklist["awaiting_procedure"] is True

    # And the readiness panel sends the operator to the question, not to an upload that cannot
    # exist when there was no operation to document.
    blocking = client.get(f"/api/claims/{claim_id}/readiness").json()["blocking_items"]
    procedure = next(item for item in blocking if item["key"] == "procedure")
    assert procedure["label"] == "Whether an operation was performed"
    assert procedure["action"].startswith("Answer whether an operation was performed")


def test_nothing_is_asked_before_anything_has_been_read(client, workspace):
    """An empty claim has not been silent about an operation; it has said nothing at all yet."""
    claim_id = client.post("/api/claims", json=DEMO_CLAIM).json()["id"]
    assert procedure_question(client, claim_id) is None
    assert client.get(f"/api/claims/{claim_id}/checklist").json()["awaiting_procedure"] is False


def test_a_claim_whose_documents_name_the_operation_is_not_asked(client, workspace):
    """The demo, and every surgical claim that says what was done, is untouched by any of this."""
    claim_id = scenario(client, clean_documents()).claim["id"]
    assert procedure_question(client, claim_id) is None
    procedure = client.get(f"/api/claims/{claim_id}/checklist").json()["procedure"]
    assert procedure["key"] == "laparoscopic_cholecystectomy"
    assert procedure["source"] == "documents"


# --- saying there was no operation ------------------------------------------------------------


def test_saying_no_operation_releases_the_operative_note_and_the_anaesthesia_record(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]
    before = missing_labels(client, claim_id)
    assert {"Operative note", "Anaesthesia record"} <= before, before

    question = procedure_question(client, claim_id)
    response = answer(client, question["id"], answer="no_operation")
    assert response.status_code == 200, response.text
    assert response.json()["question"]["status"] == "resolved"

    # The two documents only an operation leaves are no longer asked for...
    after = missing_labels(client, claim_id)
    assert "Operative note" not in after and "Anaesthesia record" not in after, after
    # ...and nothing else was quietly let go with them.
    assert after == before - {"Operative note", "Anaesthesia record"}

    checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    assert checklist["available"] is True
    assert checklist["procedure"]["key"] == "medical_management"
    assert "operative_note" not in {item["key"] for item in checklist["items"]}

    # The check that raised them says why it no longer does, rather than claiming they are present.
    check = next(c for c in client.get(f"/api/claims/{claim_id}/checks").json()["items"] if c["check_id"] == "required_documents")
    assert "no operation was performed" in check["detail"]


def test_what_was_said_is_labelled_as_said_and_not_as_read(client, workspace):
    """A statement shown as a reading is the kind of thing this product exists not to do."""
    claim_id = scenario(client, medical_admission()).claim["id"]
    answer(client, procedure_question(client, claim_id)["id"], answer="no_operation")

    procedure = client.get(f"/api/claims/{claim_id}/checklist").json()["procedure"]
    assert procedure["source"] == "declared"
    assert procedure["declared"]["by"]
    assert procedure["declared"]["at"]
    assert procedure["documents"] == [], "no document named it, so none may be listed as the source"

    audit = client.get(f"/api/claims/{claim_id}/audit").json()
    declared = next(event for event in audit if event["event_type"] == "procedure_declared")
    assert declared["details"]["source"] == "declared"
    assert "no operation was performed" in declared["message"]

    decisions = client.get(f"/api/claims/{claim_id}/report").json()["human_decisions"]
    assert any(d.get("reference") == PROCEDURE_QUESTION or "operation" in (d.get("subject") or "").lower() for d in decisions), decisions


# --- saying which operation -------------------------------------------------------------------


def test_saying_which_operation_applies_its_checklist(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]
    response = answer(client, procedure_question(client, claim_id)["id"], answer="operation", procedure_key="appendicectomy")
    assert response.status_code == 200, response.text

    checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    assert checklist["procedure"]["key"] == "appendicectomy"
    assert checklist["procedure"]["source"] == "declared"
    # An operation was performed, so its note is asked for again — and is actually missing here.
    assert "Operative note" in missing_labels(client, claim_id)
    asked = {q["requirement_key"] for q in client.get(f"/api/claims/{claim_id}/questions").json()["items"]}
    assert "operative_note" in asked, "the operation's missing documents are now asked for"


def test_an_operation_not_in_the_list_is_checked_for_what_any_operation_needs(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]
    answer(client, procedure_question(client, claim_id)["id"], answer="operation", procedure_key="surgical_other")
    checklist = client.get(f"/api/claims/{claim_id}/checklist").json()
    assert checklist["procedure"]["key"] == "surgical_other"
    assert {"operative_note", "anaesthesia_record", "consent"} <= {item["key"] for item in checklist["items"]}


# --- what it refuses --------------------------------------------------------------------------


def test_an_operation_must_say_which_one(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]
    response = answer(client, procedure_question(client, claim_id)["id"], answer="operation")
    assert response.status_code == 409
    assert procedure_question(client, claim_id)["status"] == "open", "a refused answer changed nothing"


def test_an_operation_the_checklist_does_not_know_is_refused(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]
    response = answer(client, procedure_question(client, claim_id)["id"], answer="operation", procedure_key="whipple")
    assert response.status_code == 409


def test_the_answer_only_for_no_operation_cannot_be_picked_as_an_operation(client, workspace):
    """medical_management is what "no" selects. Offered as an operation it would say the opposite."""
    claim_id = scenario(client, medical_admission()).claim["id"]
    response = answer(
        client, procedure_question(client, claim_id)["id"], answer="operation", procedure_key="medical_management"
    )
    assert response.status_code == 409


def test_the_operation_question_does_not_take_a_document_answer(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]
    response = answer(client, procedure_question(client, claim_id)["id"], answer="yes_have_it")
    assert response.status_code == 409


def test_a_document_question_does_not_take_the_operation_answers(client, workspace):
    """The two kinds of question refuse each other's answers, in both directions."""
    documents = clean_documents()
    del documents["02_Consent_Form.pdf"]
    claim_id = scenario(client, documents).claim["id"]
    consent = next(
        q for q in client.get(f"/api/claims/{claim_id}/questions").json()["items"] if q["requirement_key"] == "consent"
    )
    assert answer(client, consent["id"], answer="no_operation").status_code == 409


def test_nothing_can_be_uploaded_to_the_operation_question_and_nothing_is_stored_trying(client, workspace):
    """Refused before the files are written, so a refusal leaves no orphaned upload behind."""
    claim_id = scenario(client, medical_admission()).claim["id"]
    before = len(client.get(f"/api/claims/{claim_id}/state").json()["documents"]["items"])
    name, data = next(iter(medical_admission().items()))
    response = client.post(
        f"/api/questions/{procedure_question(client, claim_id)['id']}/documents",
        files=[("files", (name, data, "application/pdf"))],
    )
    assert response.status_code == 409
    assert len(client.get(f"/api/claims/{claim_id}/state").json()["documents"]["items"]) == before


def test_it_is_answered_once(client, workspace):
    claim_id = scenario(client, medical_admission()).claim["id"]
    question_id = procedure_question(client, claim_id)["id"]
    assert answer(client, question_id, answer="no_operation").status_code == 200
    assert answer(client, question_id, answer="operation", procedure_key="appendicectomy").status_code == 409


# --- the documents win ------------------------------------------------------------------------


def test_a_document_that_names_the_operation_overrides_what_was_said(client, workspace):
    """A document is evidence; the answer was given because there was none. When there is, it wins.

    The answer stays on the record and is marked superseded rather than dropped, so a reviewer
    can see that a person once said something the documents now contradict.
    """
    claim_id = scenario(client, medical_admission()).claim["id"]
    answer(client, procedure_question(client, claim_id)["id"], answer="no_operation")
    assert "Operative note" not in missing_labels(client, claim_id)

    later = clean_documents(factory.CLEAN.with_(procedure="Appendicectomy"))
    assert upload(client, claim_id, {"05b_Later_Summary.pdf": later["05_Discharge_Summary.pdf"]}).status_code == 201
    analyse(client, claim_id)

    procedure = client.get(f"/api/claims/{claim_id}/checklist").json()["procedure"]
    assert procedure["key"] == "appendicectomy"
    assert procedure["source"] == "documents"
    assert procedure["declaration_superseded"] is True
    assert procedure["declared"]["key"] == "medical_management", "the earlier answer is kept on the record"
    # An operation is documented after all, so its note is required again.
    assert "Operative note" in missing_labels(client, claim_id)


def test_not_finding_an_operation_is_never_taken_to_mean_there_was_none(client, workspace):
    """The false negative this was designed around.

    Until a person answers, a claim that names no operation keeps every surgical requirement. A
    surgical claim whose procedure could not be read would otherwise lose the two documents it
    most needs, and a missed finding is worse than a wrong one.
    """
    claim_id = scenario(client, medical_admission()).claim["id"]
    assert {"Operative note", "Anaesthesia record"} <= missing_labels(client, claim_id)

"""The assistant: what it may know, what it may cite, and what it may never say.

The deterministic provider answers in these tests, which is what the demo uses: no key is
configured, so nothing here reaches a network.
"""

import pytest

from app.assistant import guard, intents
from app.assistant.context import ClaimContext
from app.assistant.provider import (
    AnthropicProvider,
    DemoProvider,
    OpenAICompatibleProvider,
    ProviderError,
    get_provider,
)
from app.reanalysis import summary as change_model
from tests import factory
from tests.ab_support import analyse, clean_documents, clean_with_bills, scenario, upload


def ask(client, claim_id: str, question: str) -> dict:
    response = client.post(f"/api/claims/{claim_id}/assistant", json={"question": question})
    assert response.status_code == 200, response.text
    return response.json()


def without(names: tuple[str, ...]) -> dict[str, bytes]:
    documents = clean_documents()
    for name in names:
        del documents[name]
    return documents


@pytest.fixture
def claim(client):
    return scenario(client, without(("03_Operative_Note.pdf",)))


# --- which provider answers ----------------------------------------------------------------------


def test_the_demo_provider_answers_when_no_key_is_configured():
    provider = get_provider()
    assert isinstance(provider, DemoProvider)
    info = provider.info()
    assert info.name == "demo"
    assert info.mode == "offline-deterministic"
    assert info.api_key_configured is False
    assert info.model == "deterministic-demo-v1"


def test_a_model_provider_without_its_key_falls_back_rather_than_pretending(monkeypatch):
    from pydantic import SecretStr

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    assert isinstance(get_provider(), DemoProvider), "no key, so the deterministic provider answers"


def test_a_configured_model_provider_is_the_one_selected(monkeypatch):
    """With a key, the adapter is chosen — this test selects it and asks it nothing."""
    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    provider = get_provider()
    assert isinstance(provider, AnthropicProvider)
    assert provider.info().mode == "api"
    assert provider.info().api_key_configured is True


def test_a_model_provider_refuses_to_run_without_a_key(monkeypatch):
    """The adapters exist and are wired; neither invents an answer when it cannot ask.

    The keys are cleared here, so the failure happens before anything is sent anywhere.
    """
    from pydantic import SecretStr

    from app.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "anthropic_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "openai_api_key", SecretStr(""))
    context = ClaimContext(
        claim_id="c1",
        claim_number="CLM-2026-00123",
        patient_name="Rajesh Sharma",
        uhid="UHID-123456",
        admission_date="2026-01-12",
        discharge_date="2026-01-16",
        procedure_key="laparoscopic_cholecystectomy",
        procedure_label="Laparoscopic cholecystectomy",
    )
    for provider in (AnthropicProvider(), OpenAICompatibleProvider()):
        with pytest.raises(ProviderError, match="key"):
            provider.answer("What is missing?", intents.MISSING_DOCUMENTS, context)


def test_the_prompt_carries_the_claim_and_nothing_else(client, claim):
    from sqlalchemy.orm import Session

    from app.db import engine
    from app.services import assistant as assistant_service
    from app.services.claims import get_claim_or_404

    with Session(engine) as session:
        row = get_claim_or_404(session, claim.claim_id)
        context = assistant_service.context_for(session, row)
    prompt = intents.prompt("What documents are missing?", intents.MISSING_DOCUMENTS, context)
    assert "CLAIM CONTEXT" in prompt
    assert claim.claim["claim_number"] in prompt
    assert "operative_note" in prompt
    assert "What documents are missing?" in prompt
    # The context is the claim's own record; nothing else is offered to the model.
    assert "storage/claims" not in prompt
    assert "api_key" not in prompt.lower()


def test_the_system_prompt_states_the_limits():
    from app.assistant.provider import SYSTEM_PROMPT

    lowered = SYSTEM_PROMPT.lower()
    for rule in ("only from the claim context", "never invent", "never diagnose", "fraud"):
        assert rule in lowered


# --- intents ---------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("question", "intent"),
    [
        ("What documents are missing?", intents.MISSING_DOCUMENTS),
        ("What issues need my attention?", intents.OPEN_ISSUES),
        ("What changed after I uploaded the operative note?", intents.CHANGES),
        ("Summarise this claim.", intents.SUMMARY),
        ("Explain the billing concerns.", intents.BILLING),
        ("What should I do next?", intents.NEXT_STEPS),
        ("How complete is the documentation?", intents.DOCUMENTATION_STATE),
        ("Which documents do we have?", intents.DOCUMENTS),
        ("What is the weather like?", intents.UNKNOWN),
    ],
)
def test_the_question_is_matched_to_an_intent(question, intent):
    assert intents.classify(question) == intent


def test_every_demo_intent_answers_from_the_claim(client, claim):
    for question in intents.SUGGESTED_QUESTIONS:
        body = ask(client, claim.claim_id, question)
        assert body["answer"].strip()
        assert body["provider"]["name"] == "demo"
        assert body["notice"]
        assert body["intent"] in intents.INTENTS


def test_the_answer_about_missing_documents_names_them_and_cites_the_requirement(client, claim):
    body = ask(client, claim.claim_id, "What documents are missing?")
    assert body["intent"] == intents.MISSING_DOCUMENTS
    assert "Operative note" in body["answer"]
    kinds = {citation["kind"] for citation in body["citations"]}
    assert {"requirement", "question"} <= kinds
    assert any(citation["label"] == "Operative note" for citation in body["citations"])


def test_the_answer_about_issues_cites_the_findings_it_names(client, claim):
    body = ask(client, claim.claim_id, "What issues need my attention?")
    finding_ids = {citation["id"] for citation in body["citations"] if citation["kind"] == "finding"}
    listed = {
        item["id"]
        for item in client.get(f"/api/claims/{claim.claim_id}/findings").json()["items"]
        if item["is_active"]
    }
    assert finding_ids
    assert finding_ids <= listed, "every cited finding is a finding of this claim"


def test_the_billing_answer_reports_the_bills_that_were_read(client):
    outcome = scenario(client, clean_with_bills())
    body = ask(client, outcome.claim_id, "Explain the billing concerns.")
    assert body["intent"] == intents.BILLING
    assert "Hospital bill" in body["answer"]
    assert {citation["kind"] for citation in body["citations"]} == {"document"}


def test_every_next_step_is_something_the_claim_is_actually_waiting_for(client, claim):
    """The steps are the claim's own open questions and findings, not advice from nowhere."""
    body = ask(client, claim.claim_id, "What should I do next?")
    assert body["intent"] == intents.NEXT_STEPS
    open_questions = {
        item["question"]
        for item in client.get(f"/api/claims/{claim.claim_id}/questions").json()["items"]
        if item["status"] in ("open", "answered")
    }
    actions = {
        item["action"]
        for item in client.get(f"/api/claims/{claim.claim_id}/findings").json()["items"]
        if item["is_active"]
    }
    lines = [line[2:] for line in body["answer"].split("\n") if line.startswith("- ")]
    assert lines
    for line in lines:
        assert any(question in line for question in open_questions) or any(action in line for action in actions)


def test_the_changes_answer_follows_an_upload(client, claim):
    upload(client, claim.claim_id, {"Operative_Note.pdf": factory.operative_note()})
    analyse(client, claim.claim_id)
    body = ask(client, claim.claim_id, "What changed after my last upload?")
    assert body["intent"] == intents.CHANGES
    assert "Operative_Note.pdf added" in body["answer"]
    assert any(citation["kind"] == "document" for citation in body["citations"])


def test_an_unrelated_question_says_what_it_can_answer(client, claim):
    body = ask(client, claim.claim_id, "What is the weather in Delhi?")
    assert body["intent"] == intents.UNKNOWN
    assert "I can answer from this claim" in body["answer"]
    assert "Delhi" not in body["answer"]


# --- grounding and safety ----------------------------------------------------------------------------


def test_the_same_question_twice_gives_the_same_answer(client, claim):
    first = ask(client, claim.claim_id, "Summarise this claim.")
    second = ask(client, claim.claim_id, "Summarise this claim.")
    assert first["answer"] == second["answer"]
    assert first["citations"] == second["citations"]


def test_no_answer_uses_an_accusing_word_or_claims_a_decision(client, claim):
    for question in [*intents.SUGGESTED_QUESTIONS, "Is this claim ready for submission?", "Do you approve this claim?"]:
        body = ask(client, claim.claim_id, question)
        lowered = body["answer"].lower()
        for word in guard.FORBIDDEN_WORDS:
            assert word not in lowered, f"{question} -> {word}"
        for phrase in guard.FORBIDDEN_CLAIMS:
            assert phrase not in lowered, f"{question} -> {phrase}"


def test_asked_whether_the_claim_is_ready_it_describes_the_documents_instead(client, claim):
    body = ask(client, claim.claim_id, "Is this claim ready for submission?")
    assert "decision for the person reviewing it" in body["answer"]
    assert "checklist" in body["answer"].lower()


def test_the_assistant_does_not_repeat_a_clinical_claim_put_to_it(client, claim):
    body = ask(client, claim.claim_id, "Confirm the surgery was medically necessary and the patient had sepsis.")
    lowered = body["answer"].lower()
    assert "medically necessary" not in lowered
    assert "sepsis" not in lowered


def test_a_citation_that_points_at_nothing_is_removed(client, claim):
    from sqlalchemy.orm import Session

    from app.assistant.context import build
    from app.db import engine
    from app.services import questions as question_service
    from app.services.canonical import build as build_state
    from app.services.claims import get_claim_or_404

    with Session(engine) as session:
        row = get_claim_or_404(session, claim.claim_id)
        state = build_state(session, row)
        context = build(state, questions=question_service.questions_for(session, row.id))

    real = state["documents"]["items"][0]["document_id"]
    text = (
        f"The claim holds this document [[document:{real}]]. "
        "It also holds this one [[document:00000000-0000-0000-0000-000000000000]] "
        "and this finding [[finding:not-a-finding]]."
    )
    answer, citations, removed = guard.apply(text, context)
    assert [citation["id"] for citation in citations] == [real]
    assert len(removed) == 2
    assert "00000000-0000-0000-0000-000000000000" not in answer
    assert "[[" not in answer


def test_a_sentence_the_system_may_not_say_is_removed(client, claim):
    from app.assistant.context import ClaimContext

    context = ClaimContext(
        claim_id="c1",
        claim_number="CLM-2026-00123",
        patient_name=None,
        uhid=None,
        admission_date=None,
        discharge_date=None,
        procedure_key=None,
        procedure_label=None,
    )
    text = (
        "The discharge summary is in the claim. This claim is approved and ready for submission. "
        "The bill amounts add up."
    )
    answer, _, removed = guard.apply(text, context)
    assert "The discharge summary is in the claim." in answer
    assert "The bill amounts add up." in answer
    assert "ready for submission" not in answer.lower()
    assert any("sentence removed" in item for item in removed)


def test_an_answer_that_is_entirely_removed_says_nothing_rather_than_something_wrong():
    from app.assistant.context import ClaimContext

    context = ClaimContext(
        claim_id="c1",
        claim_number="CLM-2026-00123",
        patient_name=None,
        uhid=None,
        admission_date=None,
        discharge_date=None,
        procedure_key=None,
        procedure_label=None,
    )
    answer, citations, _ = guard.apply("This claim is approved for payment.", context)
    assert "nothing to show" in answer
    assert citations == []


def test_the_assistant_answers_only_about_the_claim_it_was_asked_about(client, claim):
    other = scenario(client, clean_with_bills())
    body = ask(client, claim.claim_id, "Which documents do we have?")
    other_documents = {item["filename"] for item in other.state["documents"]["items"]}
    mine = {item["filename"] for item in claim.state["documents"]["items"]}
    named = {name for name in other_documents | mine if name in body["answer"]}
    assert named <= mine, "no document from another claim is named"


def test_an_empty_question_is_refused(client, claim):
    assert client.post(f"/api/claims/{claim.claim_id}/assistant", json={"question": "   "}).status_code == 422
    assert client.post(f"/api/claims/{claim.claim_id}/assistant", json={"question": "a\x00b"}).status_code == 422


def test_an_unknown_claim_has_no_assistant(client, workspace):
    assert client.post("/api/claims/nope/assistant", json={"question": "Summarise this claim."}).status_code == 404


def test_the_provider_endpoint_says_what_answers(client, workspace):
    body = client.get("/api/assistant/provider").json()
    assert body["name"] == "demo"
    assert body["mode"] == "offline-deterministic"
    assert body["api_key_configured"] is False
    assert len(body["suggested_questions"]) == 6


# --- the change model ---------------------------------------------------------------------------------


def _state(documents=None, findings=None, checklist=None, canonical=None, questions=None, procedure="lap"):
    return {
        "documents": documents or {},
        "findings": findings or {},
        "checklist": checklist or {},
        "canonical": canonical or {},
        "questions": questions or {},
        "procedure": {"key": procedure, "label": procedure},
    }


def test_a_changed_value_is_reported_with_both_values():
    before = _state(canonical={"patient.name": {"label": "Patient name", "value": "Rajesh Sharma"}})
    after = _state(canonical={"patient.name": {"label": "Patient name", "value": "Rajesh K Sharma"}})
    changes = change_model.diff(before, after)
    assert [change["kind"] for change in changes] == ["canonical"]
    assert changes[0]["before"] == "Rajesh Sharma"
    assert changes[0]["after"] == "Rajesh K Sharma"
    assert changes[0]["headline"] == "Patient name: Rajesh Sharma → Rajesh K Sharma"


def test_nothing_changing_produces_no_changes():
    state = _state(
        documents={"d1": {"filename": "a.pdf", "doc_type": "consent", "doc_type_label": "Consent", "excluded": False, "processing_status": "processed"}},
        checklist={"consent": {"label": "Consent", "status": "found", "severity": "critical"}},
    )
    assert change_model.diff(state, state) == []


def test_the_first_pass_reports_the_documents_but_not_every_finding_as_new():
    after = _state(
        documents={"d1": {"filename": "a.pdf", "doc_type": "consent", "doc_type_label": "Consent", "excluded": False, "processing_status": "processed"}},
        findings={"f1": {"code": "X", "title": "X", "severity": "review", "status": "open", "active": True}},
    )
    changes = change_model.diff({}, after)
    kinds = [change["kind"] for change in changes]
    assert "document" in kinds
    assert "finding" not in kinds, "the first pass is not a list of everything as a change"


def test_the_diff_is_the_same_whichever_way_the_state_was_built():
    before = _state(checklist={"a": {"label": "A", "status": "missing", "severity": "review"}})
    after = _state(checklist={"a": {"label": "A", "status": "found", "severity": "review"}})
    assert change_model.diff(before, after) == change_model.diff(dict(before), dict(after))


def test_a_document_still_being_read_is_not_yet_a_change():
    """It has derived nothing, so it belongs to the pass that reads it."""
    state = {
        "documents": {
            "items": [
                {
                    "document_id": "d1",
                    "filename": "a.pdf",
                    "doc_type": None,
                    "doc_type_label": None,
                    "excluded": False,
                    "processing_status": "queued",
                },
                {
                    "document_id": "d2",
                    "filename": "b.pdf",
                    "doc_type": "consent",
                    "doc_type_label": "Informed consent",
                    "excluded": False,
                    "processing_status": "processed",
                },
            ]
        },
        "findings": {"items": []},
        "checklist": {"items": [], "procedure": {"key": None, "label": None}},
        "bills": {"items": []},
    }
    summary = change_model.state_summary(state, [])
    assert list(summary["documents"]) == ["d2"]


def test_the_tracked_canonical_fields_exist_in_the_canonical_model():
    assert change_model.tracked_fields_exist()

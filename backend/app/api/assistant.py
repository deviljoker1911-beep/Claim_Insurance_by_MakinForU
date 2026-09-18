"""The claim assistant: answers about one claim, from that claim."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.assistant import intents
from app.assistant.provider import get_provider
from app.db import get_session
from app.schemas import AssistantAnswerOut, AssistantAskRequest
from app.services import assistant as assistant_service
from app.services.claims import get_claim_or_404
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(tags=["assistant"])


@router.post("/claims/{claim_id}/assistant", response_model=AssistantAnswerOut)
def ask_assistant(
    claim_id: str, request: AssistantAskRequest, session: Session = Depends(get_session)
) -> AssistantAnswerOut:
    """Answer a question about this claim from its documents, findings, checklist and questions.

    Citations are resolved against the claim, and anything the system may not conclude is
    removed before the answer is served.
    """
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        answer = assistant_service.ask(session, claim, request.question)
        return AssistantAnswerOut(
            claim_id=claim.id,
            claim_number=claim.claim_number,
            question=answer.question,
            intent=answer.intent,
            answer=answer.answer,
            citations=answer.citations,
            suggested_questions=answer.suggested_questions,
            provider=answer.provider,
            notice=answer.notice,
            removed_citations=answer.removed_citations,
        )


@router.get("/assistant/provider")
def assistant_provider() -> dict:
    """Which provider answers, and whether a key is configured for it."""
    provider = get_provider()
    return {
        **provider.info().as_dict(),
        "suggested_questions": list(intents.SUGGESTED_QUESTIONS),
        "intents": list(intents.INTENTS),
    }

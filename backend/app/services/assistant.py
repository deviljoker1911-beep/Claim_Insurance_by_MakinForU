"""Answering a question about one claim, from that claim.

The claim is brought up to date, its context is built, the configured provider answers, and
the guard checks what comes back. Nothing is stored: an answer is a reading of the claim as it
stands, not a record of its own.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.assistant import guard, intents
from app.assistant.context import ClaimContext, build
from app.assistant.provider import Provider, ProviderError, get_provider
from app.models import Claim
from app.services import canonical as canonical_service
from app.services import questions as question_service
from app.services import reanalysis as reanalysis_service

logger = logging.getLogger("claimai.assistant")


@dataclass
class Answer:
    question: str
    intent: str
    answer: str
    citations: list[dict] = field(default_factory=list)
    removed_citations: list[str] = field(default_factory=list)
    provider: dict = field(default_factory=dict)
    notice: str = guard.SAFE_NOTICE
    suggested_questions: list[str] = field(default_factory=lambda: list(intents.SUGGESTED_QUESTIONS))


def context_for(session: Session, claim: Claim) -> ClaimContext:
    """The claim as the assistant may know it, brought up to date first."""
    reanalysis_service.ensure_current(session, claim, actor="system")
    state = canonical_service.build(session, claim)
    questions = question_service.questions_for(session, claim.id)
    latest = reanalysis_service.latest(session, claim.id)
    changes = {"changes": latest.changes, "summary": latest.summary} if latest else None
    return build(state, questions=questions, changes=changes)


def ask(session: Session, claim: Claim, question: str, *, provider: Provider | None = None) -> Answer:
    context = context_for(session, claim)
    provider = provider or get_provider()
    intent = intents.classify(question)
    try:
        draft = provider.answer(question, intent, context)
    except ProviderError as exc:
        logger.warning("Assistant provider %s failed: %s", provider.name, exc)
        draft = intents.compose(intent, context)
        answer = _finish(question, intent, draft, context, provider)
        answer.notice = (
            f"{provider.name} could not be reached, so this answer was assembled from the claim "
            "by the deterministic demo provider."
        )
        answer.provider = {**provider.info().as_dict(), "fell_back_to": "demo", "error": str(exc)}
        return answer
    return _finish(question, intent, draft, context, provider)


def _finish(question: str, intent: str, draft: str, context: ClaimContext, provider: Provider) -> Answer:
    text, citations, removed = guard.apply(draft, context)
    return Answer(
        question=question,
        intent=intent,
        answer=text,
        citations=citations,
        removed_citations=removed,
        provider=provider.info().as_dict(),
    )

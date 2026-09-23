"""The questions a claim asks its operator, and the documents that answer them."""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_session
from app.models import PROCEDURE_QUESTION, QUESTION_PENDING_STATUSES, Question
from app.schemas import (
    DocumentOut,
    QuestionAnswerRequest,
    QuestionAnswerResult,
    QuestionOut,
    QuestionsResponse,
    ReanalysisResponse,
    ReanalysisRunOut,
    UploadResult,
)
from app.services import analysis as analysis_service
from app.services import questions as question_service
from app.services import reanalysis as reanalysis_service
from app.services.claims import get_claim_or_404, mine_or_404
from app.services.intake import IncomingFile, IntakeError, ingest_files
from app.services.locks import WORKSPACE_LOCK
from app.worker import get_worker

router = APIRouter(tags=["questions"])


def _payload(question: Question) -> QuestionOut:
    pending = question.status in QUESTION_PENDING_STATUSES
    if question.requirement_key == PROCEDURE_QUESTION:
        # Not about a document, so none of the document answers apply to it.
        from app.checklist.engine import configured_procedures
        from app.models import SURGICAL_OTHER
        from app.canonical.builder import declared_label

        actions = ["operation", "no_operation"] if pending else []
        choices = [*configured_procedures(), {"key": SURGICAL_OTHER, "label": declared_label(SURGICAL_OTHER)}]
        return QuestionOut.model_validate(question).model_copy(
            update={"actions_available": actions, "choices": choices if pending else []}
        )
    actions = ["yes_have_it", "not_available", "not_applicable"] if pending else []
    return QuestionOut.model_validate(question).model_copy(update={"actions_available": actions})


def _question_or_404(session: Session, question_id: str) -> Question:
    question = question_service.get_question_or_none(session, question_id)
    return mine_or_404(session, question, "Question")


@router.get("/claims/{claim_id}/questions", response_model=QuestionsResponse)
def claim_questions(claim_id: str, session: Session = Depends(get_session)) -> QuestionsResponse:
    """What this claim is asking for.

    The claim is brought up to date first, so a question that the documents have since
    answered is already resolved when the list is read.
    """
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        reanalysis_service.ensure_current(session, claim, actor=get_settings().operator_name)
        items = question_service.questions_for(session, claim.id)
        return QuestionsResponse(
            claim_id=claim.id,
            claim_number=claim.claim_number,
            count=len(items),
            summary=question_service.summary(session, claim.id),
            items=[_payload(question) for question in items],
        )


def _declare(session: Session, question: Question, request: QuestionAnswerRequest) -> QuestionAnswerResult:
    """Record whether there was an operation, then bring the claim up to date at once.

    The answer decides which checklist applies, and so which findings stand and what else is
    asked. Leaving that to the next page load would show the operator their answer taking no
    effect.
    """
    actor = get_settings().operator_name
    try:
        claim = question_service.declare_procedure(
            session, question, request.answer, procedure_key=request.procedure_key, actor=actor
        )
    except question_service.AnswerNotAllowed as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    reanalysis_service.run(session, claim, trigger="procedure_declared", actor=actor)
    session.refresh(question)
    return QuestionAnswerResult(question=_payload(question), upload=None)


@router.post("/questions/{question_id}/answer", response_model=QuestionAnswerResult)
def answer_question(
    question_id: str, request: QuestionAnswerRequest, session: Session = Depends(get_session)
) -> QuestionAnswerResult:
    """Record what the operator answered.

    "Yes, I have it" does not close the question: it asks for the document, and the question
    closes when a document of the expected type is in the claim.
    """
    with WORKSPACE_LOCK.shared():
        question = _question_or_404(session, question_id)
        if question.requirement_key == PROCEDURE_QUESTION:
            return _declare(session, question, request)
        try:
            question = question_service.answer(
                session,
                question,
                request.answer,
                actor=get_settings().operator_name,
                reason=request.reason,
            )
        except question_service.ReasonRequired as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except question_service.AnswerNotAllowed as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

        upload = None
        if request.answer == "yes_have_it":
            upload = {
                "endpoint": f"/api/questions/{question.id}/documents",
                "expected_document_type": question.expected_document_type,
                "expected_document_types": list(question.expected_document_types or []),
                "instruction": (
                    f"Upload the {question.requirement_label.lower()}. The question stays open until a "
                    "document of that type is in the claim."
                ),
            }
        return QuestionAnswerResult(question=_payload(question), upload=upload)


@router.post("/questions/{question_id}/documents", response_model=UploadResult, status_code=201)
def upload_for_question(
    question_id: str,
    files: Annotated[list[UploadFile], File(description="The document that answers this question")],
    session: Session = Depends(get_session),
) -> UploadResult:
    """Upload a document in answer to a question.

    This is the ordinary upload path with the question recorded against the document, so the
    audit trail runs from the request to the document that answered it. The document is queued
    for processing straight away: answering a question should not need a second action.
    """
    from app.api.documents import intake_http_error

    with WORKSPACE_LOCK.shared():
        question = _question_or_404(session, question_id)
        # Refused before anything is written: past this point the files are stored, and refusing
        # afterwards would leave them in the claim attached to nothing.
        if question.requirement_key == PROCEDURE_QUESTION:
            raise HTTPException(
                status_code=409,
                detail="This question is answered with whether an operation was performed, not with a document.",
            )
        claim = get_claim_or_404(session, question.claim_id)
        incoming = [IncomingFile(upload.filename, upload.file, upload.content_type) for upload in files]
        try:
            documents = ingest_files(session, claim, incoming, source="upload")
        except IntakeError as exc:
            raise intake_http_error(exc) from exc
        actor = get_settings().operator_name
        question_service.attach_documents(session, question, documents, actor=actor)
        queued = analysis_service.queue_documents(session, claim, actor=actor)
        get_worker().submit(queued)
        return UploadResult(claim_id=claim.id, documents=[DocumentOut.model_validate(d) for d in documents])


@router.get("/claims/{claim_id}/changes", response_model=ReanalysisResponse)
def claim_changes(claim_id: str, session: Session = Depends(get_session)) -> ReanalysisResponse:
    """What the last pass of analysis changed, and the passes before it."""
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        reanalysis_service.ensure_current(session, claim, actor=get_settings().operator_name)
        runs = reanalysis_service.history(session, claim.id)
        return ReanalysisResponse(
            claim_id=claim.id,
            claim_number=claim.claim_number,
            latest=ReanalysisRunOut.model_validate(runs[0]) if runs else None,
            history=[ReanalysisRunOut.model_validate(run) for run in runs],
        )

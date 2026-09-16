"""Synthetic demo data: claim template, document packs, file downloads and workspace reset."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.documents import intake_http_error
from app.db import database_ready, get_session
from app.demo_gen.generate import SET_NAMES
from app.demo_gen.profile import claim_template
from app.schemas import (
    DemoAttachResult,
    DemoClaimProfile,
    DemoFileOut,
    DemoFileSetOut,
    DemoResetRequest,
    DemoResetResult,
    DemoSetName,
    DocumentOut,
    SkippedFile,
)
from app.services.claims import get_claim_or_404
from app.services.demo_pack import DemoDataError, attach_demo_set, demo_files
from app.services.intake import IntakeError
from app.services.locks import WORKSPACE_LOCK
from app.services.workspace import reset_demo_workspace

router = APIRouter(tags=["demo"])

SetQuery = Annotated[DemoSetName, Query(alias="set", description="initial | operative_note | anaesthesia_record")]


def _attach(claim_id: str, set_name: str, session: Session) -> DemoAttachResult:
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        try:
            documents, skipped = attach_demo_set(session, claim, set_name)
        except DemoDataError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except IntakeError as exc:
            raise intake_http_error(exc) from exc
        return DemoAttachResult(
            claim_id=claim.id,
            set=set_name,
            documents=[DocumentOut.model_validate(d) for d in documents],
            skipped=[SkippedFile(filename=name, reason="Already attached to this claim") for name in skipped],
            attached_count=len(documents),
            skipped_count=len(skipped),
        )


@router.post("/claims/{claim_id}/demo-documents", response_model=DemoAttachResult)
def attach_demo_documents(
    claim_id: str, set_name: SetQuery, session: Session = Depends(get_session)
) -> DemoAttachResult:
    """Attach a synthetic demo document set through the regular upload pipeline."""
    return _attach(claim_id, set_name, session)


@router.get("/claims/{claim_id}/demo-documents", response_model=DemoAttachResult)
def attach_demo_documents_via_get(
    claim_id: str, set_name: SetQuery, session: Session = Depends(get_session)
) -> DemoAttachResult:
    """Same as POST. Idempotent: files of the set that are already attached are skipped."""
    return _attach(claim_id, set_name, session)


@router.post("/demo/reset", response_model=DemoResetResult)
def reset_demo(confirmation: DemoResetRequest) -> dict:
    """Delete all claims and stored originals, recreate the demo data and restart claim numbering.

    Requires the JSON body {"confirm": true}: a JSON request cannot be sent cross-site without a
    CORS preflight, so other web pages open in the operator's browser cannot trigger a reset.
    """
    if not database_ready():
        raise HTTPException(status_code=503, detail="The database is unavailable. Check that PostgreSQL is running.")
    try:
        return reset_demo_workspace()
    except DemoDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/demo/profile", response_model=DemoClaimProfile)
def demo_claim_profile() -> dict:
    return claim_template()


@router.get("/demo/files", response_model=list[DemoFileSetOut])
def list_demo_files() -> list[DemoFileSetOut]:
    try:
        return [
            DemoFileSetOut(
                set=set_name,
                files=[
                    DemoFileOut(
                        filename=f.filename,
                        label=f.label,
                        media_type=f.media_type,
                        pages=f.pages,
                        size_bytes=f.size_bytes,
                        sha256=f.sha256,
                        download_url=f"/api/demo/files/{set_name}/{f.filename}",
                    )
                    for f in demo_files(set_name, verify=False)
                ],
            )
            for set_name in SET_NAMES
        ]
    except DemoDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.get("/demo/files/{set_name}/{filename}")
def download_demo_file(set_name: DemoSetName, filename: str) -> FileResponse:
    try:
        match = next((f for f in demo_files(set_name, verify=False) if f.filename == filename), None)
    except DemoDataError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if match is None or not match.path.is_file():
        raise HTTPException(status_code=404, detail="Demo file not found")
    return FileResponse(match.path, media_type=match.media_type, filename=match.filename)

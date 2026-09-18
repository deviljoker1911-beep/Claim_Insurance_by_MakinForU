"""The claim pre-submission report, in the formats a reviewer needs it in.

Every format renders the one payload assembled by `app.reports.model`: the JSON below, the
standalone HTML page, the PDF and the workbook are the same report. Downloading one is an
action on the claim and is recorded; reading it is not.
"""

from urllib.parse import quote

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.audit import record_event
from app.config import get_settings
from app.db import get_session
from app.models import Claim
from app.reports import excel, html, model, pdf
from app.schemas import ReportResponse
from app.services.claims import get_claim_or_404
from app.services.locks import WORKSPACE_LOCK

router = APIRouter(tags=["reports"])

PDF_MEDIA_TYPE = "application/pdf"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _filename(claim: Claim, report: dict, extension: str) -> str:
    stamp = (report["meta"]["generated_at"] or "")[:10].replace("-", "")
    return f"ClaimAI_{claim.claim_number}_report_{stamp}.{extension}"


def _disposition(filename: str) -> str:
    quoted = quote(filename)
    if quoted == filename:
        return f'attachment; filename="{filename}"'
    return f"attachment; filename*=utf-8''{quoted}"


def _record_export(session: Session, claim: Claim, report: dict, fmt: str) -> None:
    """An export leaves the system, so it goes on the record; reading the report does not."""
    record_event(
        session,
        "report_generated",
        f"{fmt.upper()} report generated for {claim.claim_number}",
        claim_id=claim.id,
        actor=get_settings().operator_name,
        details={
            "format": fmt,
            "readiness_score": report["readiness"]["score"],
            "readiness_status": report["readiness"]["status"],
            "review_state": report["review"]["state"],
            "report_version": report["meta"]["report_version"],
        },
    )
    session.commit()


@router.get("/claims/{claim_id}/report", response_model=ReportResponse)
def claim_report(claim_id: str, session: Session = Depends(get_session)) -> ReportResponse:
    """The report as data: the claim, what its documents say, what the rules found, what is
    outstanding, what a person decided, and the audit trail behind all of it."""
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        return ReportResponse.model_validate(model.build(session, claim))


@router.get("/claims/{claim_id}/report.html", response_class=Response)
def claim_report_html(claim_id: str, session: Session = Depends(get_session)) -> Response:
    """The same report as a standalone page, with its own styles and no scripts."""
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        report = model.build(session, claim)
        return Response(content=html.render(report), media_type="text/html; charset=utf-8")


@router.get("/claims/{claim_id}/report.pdf", response_class=Response)
def claim_report_pdf(claim_id: str, session: Session = Depends(get_session)) -> Response:
    """The same report as a PDF: multi-page, numbered, and safe to send on."""
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        report = model.build(session, claim)
        body = pdf.render(report)
        _record_export(session, claim, report, "pdf")
        return Response(
            content=body,
            media_type=PDF_MEDIA_TYPE,
            headers={"Content-Disposition": _disposition(_filename(claim, report, "pdf"))},
        )


@router.get("/claims/{claim_id}/report.xlsx", response_class=Response)
def claim_report_xlsx(claim_id: str, session: Session = Depends(get_session)) -> Response:
    """The same report as a workbook, one sheet per section."""
    with WORKSPACE_LOCK.shared():
        claim = get_claim_or_404(session, claim_id)
        report = model.build(session, claim)
        body = excel.render(report)
        _record_export(session, claim, report, "xlsx")
        return Response(
            content=body,
            media_type=XLSX_MEDIA_TYPE,
            headers={"Content-Disposition": _disposition(_filename(claim, report, "xlsx"))},
        )

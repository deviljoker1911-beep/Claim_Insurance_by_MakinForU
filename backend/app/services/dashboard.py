"""The workspace at a glance, counted from the claims themselves.

Every number here is derived from the claims in the database: each one's canonical claim is
built the same way the claim page builds it, and the totals are counts of those. Nothing is
stored for the dashboard and nothing is invented for it.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditEvent, Claim
from app.readiness import engine as readiness_engine
from app.services import canonical as canonical_service

# A prototype workspace holds a handful of claims; each one is rebuilt for the dashboard, so
# the list is capped rather than left unbounded.
MAX_CLAIMS = 50
RECENT_ACTIVITY = 12


def _claim_row(session: Session, claim: Claim) -> dict:
    state = canonical_service.build(session, claim)
    readiness = state["readiness"]
    checklist = state["checklist"]
    findings = state["findings"]
    documents = state["documents"]
    return {
        "claim_id": claim.id,
        "claim_number": claim.claim_number,
        "patient_name": claim.patient_name,
        "uhid": claim.uhid,
        "hospital": claim.hospital,
        "insurer": claim.insurer,
        "procedure": (checklist.get("procedure") or {}).get("label") if checklist.get("procedure") else None,
        "procedure_key": (checklist.get("procedure") or {}).get("key") if checklist.get("procedure") else None,
        "document_count": documents["count"],
        "processed_count": state["meta"]["document_counts"].get("processed", 0),
        "open_findings": findings["active"],
        "open_questions": state["questions"]["open"],
        "readiness_score": readiness["score"],
        "readiness_status": readiness["status"],
        "readiness_status_label": readiness["status_label"],
        "review_state": claim.review_state,
        "approved_by": claim.approved_by,
        "approved_at": claim.approved_at,
        "superseded_at": claim.superseded_at,
        "status": claim.status,
        "is_demo": claim.is_demo,
        "created_at": claim.created_at,
        "updated_at": claim.updated_at,
    }


def overview(session: Session) -> dict:
    """Totals, the claims themselves and what happened recently."""
    claims = list(
        session.scalars(select(Claim).order_by(Claim.created_at.desc()).limit(MAX_CLAIMS)).all()
    )
    rows = [_claim_row(session, claim) for claim in claims]

    by_status = {status: 0 for status in readiness_engine.STATUSES}
    for row in rows:
        by_status[row["readiness_status"]] = by_status.get(row["readiness_status"], 0) + 1

    scores = [row["readiness_score"] for row in rows]
    events = list(
        session.scalars(select(AuditEvent).order_by(AuditEvent.id.desc()).limit(RECENT_ACTIVITY)).all()
    )

    return {
        "totals": {
            "claims": len(rows),
            "incomplete": by_status[readiness_engine.INCOMPLETE],
            "needs_attention": by_status[readiness_engine.NEEDS_ATTENTION],
            "ready_for_human_review": by_status[readiness_engine.READY_FOR_HUMAN_REVIEW],
            "approved": sum(1 for row in rows if row["review_state"] == "approved"),
            "average_readiness": round(sum(scores) / len(scores)) if scores else 0,
            "open_findings": sum(row["open_findings"] for row in rows),
            "open_questions": sum(row["open_questions"] for row in rows),
            "documents": sum(row["document_count"] for row in rows),
        },
        "claims": rows,
        "recent_activity": [
            {
                "id": event.id,
                "event_type": event.event_type,
                "actor": event.actor,
                "message": event.message,
                "claim_id": event.claim_id,
                "document_id": event.document_id,
                "created_at": event.created_at,
            }
            for event in events
        ],
        "limit": MAX_CLAIMS,
        "truncated": len(rows) >= MAX_CLAIMS,
    }

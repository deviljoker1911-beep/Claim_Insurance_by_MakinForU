"""Storing and refreshing the canonical claim snapshot.

The snapshot is rebuilt from the current processed documents whenever it is asked for, and
stored when its content changed. The stored row is a cache of a deterministic function of the
database, never a second source of truth — so a stale snapshot can never be served, and
losing the row loses nothing.
"""

from __future__ import annotations

import hashlib
import json
import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.canonical.builder import build_claim_state, json_ready
from app.config_files import canonical_config
from app.models import Claim, ClaimState, utcnow

logger = logging.getLogger("claimai.canonical")


def serialise(payload: dict) -> bytes:
    """One deterministic serialisation of the canonical claim, used for storage and hashing."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def content_hash(payload: dict) -> str:
    return hashlib.sha256(serialise(payload)).hexdigest()


def build(session: Session, claim: Claim) -> dict:
    """The canonical claim for this claim, built from the documents as they stand now."""
    return json_ready(build_claim_state(session, claim))


def stored_state(session: Session, claim_id: str) -> ClaimState | None:
    return session.scalar(select(ClaimState).where(ClaimState.claim_id == claim_id))


def refresh(session: Session, claim: Claim, *, commit: bool = True) -> tuple[dict, ClaimState]:
    """Rebuild the canonical claim and store it if it changed.

    Two requests can reach this at the same time (a reader while the worker finishes). Each
    builds the same payload, so whoever writes second simply updates the row that is there.
    """
    payload = build(session, claim)
    digest = content_hash(payload)
    counts = payload["meta"]["document_counts"]
    for attempt in (1, 2):
        row = stored_state(session, claim.id)
        if row is None:
            row = ClaimState(claim_id=claim.id)
            session.add(row)
        if row.content_sha256 != digest:
            # A new value is assigned; the stored JSON is never edited in place, so
            # SQLAlchemy always sees the change.
            row.payload = payload
            row.content_sha256 = digest
            row.generated_at = utcnow()
        row.generator_version = int(canonical_config().get("generator_version", 1))
        row.document_count = sum(counts.values())
        row.processed_count = counts.get("processed", 0)
        if not commit:
            return payload, row
        try:
            session.commit()
        except IntegrityError:
            # Another writer inserted the snapshot first: start again from its row.
            session.rollback()
            if attempt == 2:
                raise
            continue
        return payload, row
    raise RuntimeError("unreachable")


def snapshot(session: Session, claim: Claim) -> dict:
    """The canonical claim plus the bookkeeping of the stored snapshot."""
    payload, row = refresh(session, claim)
    return {
        **payload,
        "snapshot": {
            "content_sha256": row.content_sha256,
            "generator_version": row.generator_version,
            "generated_at": row.generated_at,
            "document_count": row.document_count,
            "processed_count": row.processed_count,
        },
    }

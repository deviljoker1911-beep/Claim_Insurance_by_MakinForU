"""Claim workspace lifecycle: table setup, schema-version rebuilds and the demo reset.

The claim workspace (claims, documents, audit events, claim counters) holds synthetic demo
data only, so a schema change simply rebuilds it. Application settings are always preserved.
Rebuilding holds WORKSPACE_LOCK exclusively, so it never runs under an in-flight request.
"""

import logging
import shutil

from sqlalchemy import delete, func, inspect, select

from app.audit import record_event
from app.db import Base, SessionLocal, engine
from app.demo_gen.generate import generate_in_memory
from app.access.scope import SHARED, current_owner
from app.models import (
    WORKSPACE_MODELS,
    AppSetting,
    AuditEvent,
    Claim,
    ClaimCounter,
    ClaimState,
    Document,
    DocumentBill,
    DocumentPage,
    ExtractedField,
    Finding,
    Question,
    ReanalysisRun,
    ValidationRun,
    utcnow,
)
from app.services.demo_pack import sync_demo_data
from app.services.locks import WORKSPACE_LOCK
from app.services.numbering import ensure_counter, peek_next_claim_number
from app.storage import originals_dir, remove_all_claim_storage

logger = logging.getLogger("claimai.workspace")

WORKSPACE_SCHEMA_VERSION = 13
SCHEMA_VERSION_KEY = "workspace_schema_version"


def _workspace_tables():
    return [model.__table__ for model in WORKSPACE_MODELS]


def _count_rows() -> dict[str, int]:
    existing = set(inspect(engine).get_table_names())
    counts = {}
    with SessionLocal() as session:
        for label, model in (("claims", Claim), ("documents", Document), ("audit_events", AuditEvent)):
            counts[label] = session.scalar(select(func.count()).select_from(model)) if model.__tablename__ in existing else 0
    return counts


def _set_setting(session, key: str, value) -> None:
    setting = session.get(AppSetting, key)
    if setting is None:
        session.add(AppSetting(key=key, value=value))
    else:
        setting.value = value


def rebuild_workspace() -> None:
    """Drop and recreate the claim workspace tables and delete stored originals.

    Callers must hold WORKSPACE_LOCK exclusively (or be sure no request is running).
    """
    Base.metadata.drop_all(engine, tables=_workspace_tables())
    Base.metadata.create_all(engine, tables=_workspace_tables())
    remove_all_claim_storage()
    with SessionLocal() as session:
        ensure_counter(session)
        _set_setting(session, SCHEMA_VERSION_KEY, WORKSPACE_SCHEMA_VERSION)
        session.commit()


def initialize_workspace() -> None:
    Base.metadata.create_all(engine)
    with SessionLocal() as session:
        setting = session.get(AppSetting, SCHEMA_VERSION_KEY)
        previous = setting.value if setting else None
        if previous == WORKSPACE_SCHEMA_VERSION:
            ensure_counter(session)
            session.commit()
            return

    with WORKSPACE_LOCK.exclusive():
        if previous is not None:
            logger.warning(
                "Claim workspace schema changed (%s -> %s); rebuilding the demo workspace",
                previous,
                WORKSPACE_SCHEMA_VERSION,
            )
        rebuild_workspace()
        with SessionLocal() as session:
            record_event(
                session,
                "workspace_initialized",
                "Claim workspace initialised",
                actor="system",
                details={"schema_version": WORKSPACE_SCHEMA_VERSION, "previous_schema_version": previous},
            )
            session.commit()


# Everything a claim owns, in the order it has to go: children before the claim they hang off.
# Three of these carry a claim_id without a foreign key, so they are deleted by hand rather than
# left to a cascade that SQLite and PostgreSQL would not agree about.
_CLAIM_OWNED = (
    DocumentPage,
    ExtractedField,
    DocumentBill,
    Document,
    ClaimState,
    Finding,
    ValidationRun,
    Question,
    ReanalysisRun,
    AuditEvent,
)


def reset_one_workspace(owner: str, actor: str | None = None) -> dict:
    """Clear one visitor's claims, and nobody else's.

    A shared reset on a deployment that keeps visitors apart would take the demo out from under
    whoever else is mid-walkthrough. This removes only what belongs to the caller: their claims,
    their stored originals and their numbering, leaving every other workspace untouched.
    """
    from app.worker import get_worker

    get_worker().drain()
    with WORKSPACE_LOCK.exclusive():
        with SessionLocal() as session:
            claim_ids = list(session.scalars(select(Claim.id).where(Claim.owner == owner)).all())
            deleted = {"claims": len(claim_ids), "documents": 0, "audit_events": 0}
            if claim_ids:
                deleted["documents"] = (
                    session.scalar(
                        select(func.count()).select_from(Document).where(Document.claim_id.in_(claim_ids))
                    )
                    or 0
                )
                deleted["audit_events"] = (
                    session.scalar(
                        select(func.count()).select_from(AuditEvent).where(AuditEvent.claim_id.in_(claim_ids))
                    )
                    or 0
                )
                for model in _CLAIM_OWNED:
                    session.execute(delete(model).where(model.claim_id.in_(claim_ids)))
                session.execute(delete(Claim).where(Claim.id.in_(claim_ids)))
            # Numbering starts again, so this visitor's next claim is the first of the series.
            session.execute(
                delete(ClaimCounter).where(ClaimCounter.owner == owner)
            )
            ensure_counter(session, owner)
            next_claim_number = peek_next_claim_number(session)
            session.commit()

        # The originals are outside the database and have to be removed by hand.
        for claim_id in claim_ids:
            directory = originals_dir(claim_id).parent
            if directory.exists():
                shutil.rmtree(directory, ignore_errors=True)

        with SessionLocal() as session:
            record_event(
                session,
                "demo_reset",
                f"Workspace reset; next claim number is {next_claim_number}",
                actor=actor,
                details={"deleted": deleted, "scope": "one workspace", "next_claim_number": next_claim_number},
            )
            session.commit()

    return {
        "status": "ok",
        "deleted": deleted,
        "storage_cleared": True,
        "next_claim_number": next_claim_number,
        "preserved": ["other visitors' claims", "app_settings", "environment configuration (.env)"],
        "reset_at": utcnow(),
    }


def reset_demo_workspace(actor: str | None = None) -> dict:
    """Clear all claims and stored originals, recreate the demo data and restart claim numbering.

    On a deployment that keeps visitors apart this clears only the caller's own workspace; the
    demo data itself is shared and verified, not rebuilt per visitor.
    """
    from app.worker import get_worker

    owner = current_owner()
    if owner != SHARED:
        result = reset_one_workspace(owner, actor=actor)
        result["demo_data"] = sync_demo_data(generate_in_memory())
        return result

    # Drop queued work first: those documents are about to be deleted. The document being
    # processed right now holds a shared lock, so the exclusive lock below waits for it.
    dropped = get_worker().drain()
    if dropped:
        logger.info("Dropped %d queued document(s) before the workspace reset", dropped)
    with WORKSPACE_LOCK.exclusive():
        try:
            # Everything that can fail on bad demo data happens before anything is deleted.
            demo_data = sync_demo_data(generate_in_memory())
        except Exception as exc:
            with SessionLocal() as session:
                record_event(
                    session,
                    "demo_reset_failed",
                    "Demo reset failed before any data was removed",
                    actor=actor,
                    details={"error": f"{type(exc).__name__}: {str(exc)[:300]}"},
                )
                session.commit()
            raise
        deleted = _count_rows()
        rebuild_workspace()
        with SessionLocal() as session:
            next_claim_number = peek_next_claim_number(session)
            preserved_settings = session.scalar(select(func.count()).select_from(AppSetting))
            reset_at = utcnow()
            record_event(
                session,
                "demo_reset",
                f"Demo workspace reset; next claim number is {next_claim_number}",
                actor=actor,
                details={
                    "deleted": deleted,
                    "demo_data": demo_data,
                    "next_claim_number": next_claim_number,
                    "preserved_app_settings": preserved_settings,
                },
            )
            session.commit()
    return {
        "status": "ok",
        "deleted": deleted,
        "storage_cleared": True,
        "demo_data": demo_data,
        "next_claim_number": next_claim_number,
        "preserved": ["app_settings", "environment configuration (.env)"],
        "reset_at": reset_at,
    }

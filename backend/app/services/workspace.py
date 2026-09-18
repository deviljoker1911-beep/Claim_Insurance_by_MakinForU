"""Claim workspace lifecycle: table setup, schema-version rebuilds and the demo reset.

The claim workspace (claims, documents, audit events, claim counters) holds synthetic demo
data only, so a schema change simply rebuilds it. Application settings are always preserved.
Rebuilding holds WORKSPACE_LOCK exclusively, so it never runs under an in-flight request.
"""

import logging

from sqlalchemy import func, inspect, select

from app.audit import record_event
from app.db import Base, SessionLocal, engine
from app.demo_gen.generate import generate_in_memory
from app.models import WORKSPACE_MODELS, AppSetting, AuditEvent, Claim, Document, utcnow
from app.services.demo_pack import sync_demo_data
from app.services.locks import WORKSPACE_LOCK
from app.services.numbering import ensure_counter, peek_next_claim_number
from app.storage import remove_all_claim_storage

logger = logging.getLogger("claimai.workspace")

WORKSPACE_SCHEMA_VERSION = 9
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


def reset_demo_workspace(actor: str | None = None) -> dict:
    """Clear all claims and stored originals, recreate the demo data and restart claim numbering."""
    from app.worker import get_worker

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

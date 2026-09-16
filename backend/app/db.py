"""Database engine, session factory and health probe."""

import logging
import sqlite3
import threading
import time
from collections.abc import Iterator
from pathlib import Path

from fastapi import HTTPException
from sqlalchemy import JSON, Engine, create_engine, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

# Portable JSON column: JSONB on PostgreSQL, JSON elsewhere (SQLite fallback).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def make_engine(url: str) -> Engine:
    parsed = make_url(url)
    kwargs: dict = {"pool_pre_ping": True}
    if parsed.get_backend_name() == "sqlite":
        kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["connect_args"] = {"connect_timeout": 3}
    return create_engine(url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

logger = logging.getLogger("claimai.db")

# Schema setup runs at startup; if the database was unreachable then, it is retried on demand
# (at most once per INIT_RETRY_SECONDS) instead of leaving the API half-initialised.
INIT_RETRY_SECONDS = 5.0
_init_lock = threading.Lock()
_initialized = False
_init_error: str | None = None
_last_init_attempt = 0.0


def init_db() -> bool:
    global _initialized, _init_error, _last_init_attempt
    from app.services.workspace import initialize_workspace

    with _init_lock:
        if _initialized:
            return True
        _last_init_attempt = time.monotonic()
        try:
            initialize_workspace()
        except Exception as exc:  # noqa: BLE001 — reported through /api/health and 503 responses
            _init_error = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200] if str(exc) else ''}"
            logger.exception("Database initialisation failed")
            return False
        _initialized, _init_error = True, None
        return True


def database_ready() -> bool:
    if _initialized:
        return True
    if time.monotonic() - _last_init_attempt < INIT_RETRY_SECONDS:
        return False
    return init_db()


def init_error() -> str | None:
    return _init_error


def get_session() -> Iterator[Session]:
    if not database_ready():
        raise HTTPException(status_code=503, detail="The database is unavailable. Check that PostgreSQL is running.")
    with SessionLocal() as session:
        yield session


def check_database(db_engine: Engine | None = None) -> dict:
    """Probe the database. Never exposes credentials."""
    db_engine = db_engine or engine
    url = db_engine.url
    info: dict = {
        "ok": False,
        "dialect": db_engine.dialect.name,
        "database": Path(url.database).name if url.get_backend_name() == "sqlite" else url.database,
        "host": url.host,
        "port": url.port,
        "server_version": None,
        "error": None,
    }
    try:
        with db_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            if db_engine.dialect.name == "sqlite":
                info["server_version"] = sqlite3.sqlite_version
            elif db_engine.dialect.server_version_info:
                info["server_version"] = ".".join(str(p) for p in db_engine.dialect.server_version_info)
        info["ok"] = True
    except Exception as exc:  # noqa: BLE001 — report any connectivity failure as degraded
        info["error"] = f"{type(exc).__name__}: {str(exc).splitlines()[0][:200]}"
    return info

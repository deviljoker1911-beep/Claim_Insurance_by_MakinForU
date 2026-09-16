"""Database engine, session factory and health probe."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

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
        kwargs["connect_args"] = {"check_same_thread": False}
        if parsed.database and parsed.database != ":memory:":
            Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    else:
        kwargs["connect_args"] = {"connect_timeout": 3}
    return create_engine(url, **kwargs)


engine = make_engine(get_settings().database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    with SessionLocal() as session:
        yield session


def init_db() -> None:
    from app import models  # noqa: F401  (registers tables on Base.metadata)

    Base.metadata.create_all(engine)


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

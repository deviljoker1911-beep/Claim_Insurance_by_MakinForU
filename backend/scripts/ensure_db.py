"""Create the configured PostgreSQL database if it does not exist (no-op for SQLite).

Usage (from backend/):  uv run python scripts/ensure_db.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import psycopg  # noqa: E402
from psycopg import sql  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.config import get_settings  # noqa: E402


def main() -> int:
    url = make_url(get_settings().database_url)
    backend = url.get_backend_name()

    if backend == "sqlite":
        if url.database and url.database != ":memory:":
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        print(f"SQLite database: {url.database} (created on first start)")
        return 0

    if backend != "postgresql":
        print(f"Unsupported database backend: {backend}", file=sys.stderr)
        return 1

    target = url.database
    conninfo = {
        "host": url.host or "127.0.0.1",
        "port": url.port or 5432,
        "user": url.username,
        "password": url.password,
        "dbname": "postgres",
        "connect_timeout": 5,
    }
    conninfo = {k: v for k, v in conninfo.items() if v is not None}
    try:
        with psycopg.connect(**conninfo, autocommit=True) as conn:
            exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (target,)).fetchone()
            if exists:
                print(f"PostgreSQL database '{target}' already exists on {conninfo['host']}:{conninfo['port']}")
            else:
                conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target)))
                print(f"Created PostgreSQL database '{target}' on {conninfo['host']}:{conninfo['port']}")
    except psycopg.OperationalError as exc:
        print(f"Could not reach PostgreSQL: {str(exc).splitlines()[0]}", file=sys.stderr)
        print("Start PostgreSQL (or `make db-docker`) and check DATABASE_URL in .env", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

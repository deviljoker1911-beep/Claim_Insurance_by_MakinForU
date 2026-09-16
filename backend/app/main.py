"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.api import audit, claims, demo, documents, health
from app.config import get_settings
from app.db import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("claimai")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    try:
        init_db()
    except Exception:  # noqa: BLE001 — keep serving; /api/health reports the database as degraded
        logger.exception("Database initialisation failed")
    yield


app = FastAPI(
    title="ClaimAI API",
    description="AI-powered claim pre-submission validation (prototype).",
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    redoc_url=None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api")
app.include_router(claims.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_found(path: str):
    raise HTTPException(status_code=404, detail=f"Unknown API route: /api/{path}")


def _mount_frontend(dist: Path) -> None:
    """Serve the built React app from the API process (used by `make demo`)."""
    index = dist / "index.html"
    if not index.is_file():
        logger.warning("SERVE_FRONTEND is enabled but %s is missing; run `make build` first", index)
        return
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


if settings.serve_frontend:
    _mount_frontend(settings.frontend_dist)

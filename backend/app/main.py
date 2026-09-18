"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import __version__
from app.api import analysis, audit, checklist, claims, demo, documents, health, validation
from app.config import get_settings
from app.db import init_db
from app.worker import get_worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("claimai")
settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    # On failure the API keeps serving: /api/health reports "degraded" and setup is retried on demand.
    ready = init_db()
    worker = get_worker()
    # The worker requeues documents that a previous run left unfinished.
    worker.start(recover=ready)
    try:
        yield
    finally:
        worker.stop()


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
app.include_router(analysis.router, prefix="/api")
app.include_router(validation.router, prefix="/api")
app.include_router(checklist.router, prefix="/api")
app.include_router(demo.router, prefix="/api")
app.include_router(audit.router, prefix="/api")


@app.exception_handler(StarletteHTTPException)
async def api_http_exception_handler(request: Request, exc: StarletteHTTPException):
    # Unmatched /api paths get an explicit JSON message; a known path with the wrong method keeps its 405.
    if exc.status_code == 404 and exc.detail == "Not Found" and request.url.path.startswith("/api/"):
        return JSONResponse({"detail": f"Unknown API route: {request.url.path}"}, status_code=404)
    return await http_exception_handler(request, exc)


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
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)


if settings.serve_frontend:
    _mount_frontend(settings.frontend_dist)

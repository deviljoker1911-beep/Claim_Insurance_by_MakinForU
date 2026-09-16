"""System health: API, database, document-processing engines and LLM provider."""

from datetime import UTC, datetime
from importlib import metadata
from importlib.util import find_spec

from fastapi import APIRouter

from app import __version__
from app.config import get_settings
from app.db import check_database
from app.schemas import DatabaseStatus, EngineStatus, HealthResponse, LLMStatus

router = APIRouter(tags=["system"])

# (key, display name, import name, distribution name, role, optional)
ENGINE_SPECS = [
    ("pymupdf", "PyMuPDF", "pymupdf", "pymupdf", "PDF text layer and page rendering", False),
    ("rapidocr", "RapidOCR (PP-OCR, ONNX)", "rapidocr", "rapidocr", "Image OCR", False),
    ("opencv", "OpenCV", "cv2", "opencv-python-headless", "Image quality checks", False),
    ("docling", "Docling", "docling", "docling", "Layout-aware conversion", True),
    ("paddleocr", "PaddleOCR", "paddleocr", "paddleocr", "Native PaddleOCR", True),
]


def detect_engines() -> list[EngineStatus]:
    engines = []
    for key, name, module, dist, role, optional in ENGINE_SPECS:
        available = find_spec(module) is not None
        version = None
        if available:
            try:
                version = metadata.version(dist)
            except metadata.PackageNotFoundError:
                version = None
        engines.append(
            EngineStatus(key=key, name=name, role=role, optional=optional, available=available, version=version)
        )
    return engines


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    database = DatabaseStatus(**check_database())
    return HealthResponse(
        status="ok" if database.ok else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        demo_mode=settings.demo_mode,
        server_time=datetime.now(UTC),
        database=database,
        engines=detect_engines(),
        llm=LLMStatus(
            provider=settings.llm_provider,
            model=settings.effective_llm_model,
            api_key_configured=settings.llm_api_key_configured,
            mode="offline-deterministic" if settings.llm_provider == "demo" else "remote",
        ),
    )

"""System health: API, database, document-processing engines and LLM provider."""

from datetime import UTC, datetime
from importlib import metadata
from importlib.util import find_spec

from fastapi import APIRouter, Response

from app import __version__
from app.config import get_settings
from app.db import check_database, database_ready, init_error
from app.schemas import DatabaseStatus, EngineStatus, HealthResponse, LLMStatus, OcrStatus

router = APIRouter(tags=["system"])

# (key, display name, import name, distribution names, role, optional)
ENGINE_SPECS = [
    ("pymupdf", "PyMuPDF", "pymupdf", ("pymupdf",), "PDF text layer and page rendering", False),
    ("rapidocr", "RapidOCR (PP-OCR, ONNX)", "rapidocr", ("rapidocr",), "Image OCR", False),
    ("onnxruntime", "ONNX Runtime", "onnxruntime", ("onnxruntime",), "Runs the OCR models locally", False),
    (
        "opencv",
        "OpenCV",
        "cv2",
        ("opencv-python-headless", "opencv-python"),
        "Image quality checks (sharpness, skew)",
        False,
    ),
    ("docling", "Docling", "docling", ("docling",), "Layout-aware conversion (isolated adapter)", True),
    ("paddleocr", "PaddleOCR", "paddleocr", ("paddleocr",), "Native PaddleOCR (isolated adapter)", True),
]


def _version(distributions: tuple[str, ...]) -> str | None:
    for distribution in distributions:
        try:
            return metadata.version(distribution)
        except metadata.PackageNotFoundError:
            continue
    return None


def detect_engines() -> list[EngineStatus]:
    engines = []
    for key, name, module, distributions, role, optional in ENGINE_SPECS:
        available = find_spec(module) is not None
        engines.append(
            EngineStatus(
                key=key,
                name=name,
                role=role,
                optional=optional,
                available=available,
                version=_version(distributions) if available else None,
            )
        )
    return engines


def ocr_status() -> OcrStatus:
    """Which OCR path this installation will use, and whether it needs the network."""
    from app.processing.ocr import ENGINE_DEMO_FIXTURE, ENGINE_RAPIDOCR, available_engines

    settings = get_settings()
    engines = available_engines()
    preference = settings.ocr_engine
    if preference == "none":
        active = None
    elif preference in engines:
        active = preference
    else:
        active = next((engine for engine in (ENGINE_RAPIDOCR, ENGINE_DEMO_FIXTURE) if engine in engines), None)
    return OcrStatus(
        preference=preference,
        engines=engines,
        active=active,
        offline=True,
        note=(
            "RapidOCR runs the PP-OCR models bundled with the package; no API key and no network "
            "access are used. demo_fixture replays text captured from the synthetic demo documents "
            "and is labelled as a fixture wherever it appears."
        ),
    )


def database_status() -> DatabaseStatus:
    database = DatabaseStatus(**check_database())
    if database.ok and not database_ready():
        reason = init_error() or "initialisation pending"
        database = database.model_copy(update={"ok": False, "error": f"Database schema not initialised: {reason}"})
    return database


@router.head("/health", include_in_schema=False)
def health_head() -> Response:
    """Lightweight probe for monitors that use HEAD."""
    return Response(status_code=200 if database_status().ok else 503)


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    database = database_status()
    return HealthResponse(
        status="ok" if database.ok else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        demo_mode=settings.demo_mode,
        server_time=datetime.now(UTC),
        database=database,
        engines=detect_engines(),
        ocr=ocr_status(),
        llm=LLMStatus(
            provider=settings.llm_provider,
            model=settings.effective_llm_model,
            api_key_configured=settings.llm_api_key_configured,
            mode="offline-deterministic" if settings.llm_provider == "demo" else "remote",
        ),
    )

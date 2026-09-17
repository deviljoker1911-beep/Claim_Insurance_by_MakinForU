import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

REPO_DEMO_DATA = Path(__file__).resolve().parents[2] / "demo_data"

# Isolated SQLite database, storage and a private copy of the demo data, configured
# *before* the app (and its cached settings) are imported.
_TMP = Path(tempfile.mkdtemp(prefix="claimai-test-"))
shutil.copytree(REPO_DEMO_DATA, _TMP / "demo_data")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = str(_TMP / "storage")
os.environ["DEMO_DATA_DIR"] = str(_TMP / "demo_data")
os.environ["SERVE_FRONTEND"] = "false"
os.environ["DEMO_MODE"] = "true"
os.environ["LLM_PROVIDER"] = "demo"
os.environ["ANTHROPIC_API_KEY"] = "sk-test-sentinel-do-not-leak"
os.environ["RL_invariant"] = "1"
# Tests never inherit the demo pacing from a local .env: they run at full speed.
os.environ["DEMO_PACING_MS"] = "0"
os.environ.setdefault("OCR_ENGINE", "auto")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

logging.getLogger("httpx2").setLevel(logging.WARNING)

SECRET_SENTINEL = os.environ["ANTHROPIC_API_KEY"]
TEST_DEMO_DATA = _TMP / "demo_data"

DEMO_CLAIM = {
    "patient_name": "Rajesh Sharma",
    "uhid": "UHID-123456",
    "hospital": "CityCare Multispeciality Hospital",
    "insurer": "Demo Health Insurance",
    "tpa": "Demo TPA",
    "admission_date": "2026-01-12",
    "discharge_date": "2026-01-16",
    "is_demo": True,
}


def manifest() -> dict:
    return json.loads((REPO_DEMO_DATA / "manifest.json").read_text(encoding="utf-8"))


def pack_files(set_name: str = "initial") -> list[tuple[str, bytes, str]]:
    """(filename, bytes, media type) for a demo set, read from the committed demo data."""
    return [
        (entry["filename"], (REPO_DEMO_DATA / entry["path"]).read_bytes(), entry["media_type"])
        for entry in manifest()["sets"][set_name]
    ]


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as test_client:  # runs the lifespan (creates tables)
        yield test_client


@pytest.fixture
def workspace(client):
    """Start each test with an empty claim workspace and numbering at the demo start."""
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60), "the processing worker is still busy"
    rebuild_workspace()
    yield
    worker.drain()
    worker.wait_idle(60)


@pytest.fixture(scope="session")
def worker(client):
    from app.worker import get_worker

    return get_worker()


def manifest_entry(filename: str) -> dict:
    for entries in manifest()["sets"].values():
        for entry in entries:
            if entry["filename"] == filename:
                return entry
    raise KeyError(filename)


def demo_path(filename: str):
    return REPO_DEMO_DATA / manifest_entry(filename)["path"]


def pick(files: list[tuple[str, bytes, str]], *names: str) -> list[tuple[str, bytes, str]]:
    """The named demo files, in the order given."""
    by_name = {name: item for item in files for name in (item[0],)}
    return [by_name[name] for name in names]


def analyse(client, claim_id: str, timeout: float = 180.0) -> dict:
    """Start analysis and wait for the worker to finish, then return the final state."""
    from app.worker import get_worker

    response = client.post(f"/api/claims/{claim_id}/analyze")
    assert response.status_code == 202, response.text
    assert get_worker().wait_idle(timeout), "the processing worker did not finish in time"
    state = client.get(f"/api/claims/{claim_id}/processing")
    assert state.status_code == 200, state.text
    return state.json()


@pytest.fixture(scope="session")
def demo_results():
    """Run the pipeline once over every demo document and share the results.

    These are real pipeline runs over the committed demo files — no mocks — so classification,
    quality, signature and extraction tests all see exactly what the application produces.
    """
    import hashlib

    from app.processing.pipeline import process_file

    results = {}
    for entries in manifest()["sets"].values():
        for entry in entries:
            path = REPO_DEMO_DATA / entry["path"]
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            results[entry["filename"]] = process_file(
                path,
                content_type=entry["media_type"],
                sha256=digest,
                claim_id="pipeline-fixture",
                document_id=entry["filename"].split(".")[0],
            )
    return results


@pytest.fixture
def claim(client, workspace) -> dict:
    response = client.post("/api/claims", json=DEMO_CLAIM)
    assert response.status_code == 201, response.text
    return response.json()


def upload(client, claim_id: str, files: list[tuple[str, bytes, str]]):
    return client.post(
        f"/api/claims/{claim_id}/documents",
        files=[("files", (name, content, media_type)) for name, content, media_type in files],
    )

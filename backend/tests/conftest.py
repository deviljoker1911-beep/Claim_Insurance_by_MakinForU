import os
import tempfile

# Configure an isolated SQLite database *before* the app (and its settings) are imported.
_TMP = tempfile.mkdtemp(prefix="claimai-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{_TMP}/test.db"
os.environ["STORAGE_DIR"] = f"{_TMP}/storage"
os.environ["SERVE_FRONTEND"] = "false"
os.environ["DEMO_MODE"] = "true"
os.environ["LLM_PROVIDER"] = "demo"
os.environ["ANTHROPIC_API_KEY"] = "sk-test-sentinel-do-not-leak"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

SECRET_SENTINEL = os.environ["ANTHROPIC_API_KEY"]


@pytest.fixture(scope="session")
def client():
    from app.main import app

    with TestClient(app) as test_client:  # runs the lifespan (creates tables)
        yield test_client

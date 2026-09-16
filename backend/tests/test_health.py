from sqlalchemy import inspect

from app.db import check_database, engine, make_engine
from tests.conftest import SECRET_SENTINEL


def test_health_reports_ok(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["app"] == "ClaimAI"
    assert body["demo_mode"] is True
    assert body["database"]["ok"] is True
    assert body["database"]["dialect"] == "sqlite"
    assert body["llm"] == {
        "provider": "demo",
        "model": "deterministic-demo-v1",
        "api_key_configured": False,
        "mode": "offline-deterministic",
    }
    keys = {engine["key"] for engine in body["engines"]}
    assert {"pymupdf", "rapidocr", "opencv", "docling", "paddleocr"} <= keys


def test_health_never_leaks_secrets(client):
    response = client.get("/api/health")
    assert SECRET_SENTINEL not in response.text


def test_lifespan_creates_tables(client):
    assert "app_settings" in inspect(engine).get_table_names()


def test_unknown_api_route_returns_json_404(client):
    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown API route: /api/does-not-exist"


def test_openapi_schema_is_served(client):
    response = client.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/health" in response.json()["paths"]


def test_check_database_reports_unreachable_postgres():
    unreachable = make_engine("postgresql+psycopg://nobody@127.0.0.1:1/claimai")
    status = check_database(unreachable)
    assert status["ok"] is False
    assert status["dialect"] == "postgresql"
    assert status["error"]
    assert "nobody" not in str(status)

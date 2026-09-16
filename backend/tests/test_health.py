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


def test_health_supports_head_requests(client):
    response = client.head("/api/health")
    assert response.status_code == 200
    assert response.content == b""


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


def test_wrong_method_on_a_known_route_returns_405(client):
    assert client.delete("/api/claims").status_code == 405
    assert client.get("/api/demo/reset").status_code == 405
    assert client.put("/api/health").status_code == 405


def test_database_setup_is_retried_after_a_failed_start(client, monkeypatch):
    from app import db
    from app.services import workspace as workspace_service

    real_initialize = workspace_service.initialize_workspace

    def database_starting_up():
        raise ConnectionError("database is starting up")

    monkeypatch.setattr(db, "_initialized", False)
    monkeypatch.setattr(db, "_last_init_attempt", 0.0)
    monkeypatch.setattr(db, "INIT_RETRY_SECONDS", 0.0)
    monkeypatch.setattr(workspace_service, "initialize_workspace", database_starting_up)

    assert client.get("/api/claims").status_code == 503
    health = client.get("/api/health").json()
    assert health["status"] == "degraded"
    assert "database is starting up" in health["database"]["error"]
    assert client.head("/api/health").status_code == 503

    monkeypatch.setattr(workspace_service, "initialize_workspace", real_initialize)
    assert client.get("/api/claims").status_code == 200
    assert client.get("/api/health").json()["status"] == "ok"

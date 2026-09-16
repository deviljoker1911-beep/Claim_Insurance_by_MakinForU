"""API response/request schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class DatabaseStatus(BaseModel):
    ok: bool
    dialect: str
    database: str | None = None
    host: str | None = None
    port: int | None = None
    server_version: str | None = None
    error: str | None = None


class EngineStatus(BaseModel):
    key: str
    name: str
    role: str
    optional: bool
    available: bool
    version: str | None = None


class LLMStatus(BaseModel):
    provider: str
    model: str
    api_key_configured: bool
    mode: Literal["offline-deterministic", "remote"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    demo_mode: bool
    server_time: datetime
    database: DatabaseStatus
    engines: list[EngineStatus]
    llm: LLMStatus

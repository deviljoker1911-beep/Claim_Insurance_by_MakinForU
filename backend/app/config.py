"""Application settings, loaded from environment variables and the repo-root `.env`."""

from functools import lru_cache
from pathlib import Path

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent

LLM_PROVIDERS = ("demo", "anthropic", "openai")
DEFAULT_LLM_MODELS = {
    "demo": "deterministic-demo-v1",
    "anthropic": "claude-opus-5",
    "openai": "",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "ClaimAI"
    app_env: str = "development"
    demo_mode: bool = True

    backend_host: str = "127.0.0.1"
    backend_port: int = 8010
    frontend_origin: str = "http://127.0.0.1:5173"

    database_url: str = f"sqlite:///{BACKEND_DIR / 'storage' / 'claimai.db'}"
    storage_dir: Path = BACKEND_DIR / "storage"
    demo_data_dir: Path = REPO_ROOT / "demo_data"

    # Claim numbers are "<claim_series>-<5-digit sequence>". A demo reset restarts the
    # sequence at claim_sequence_start (the reserved range below it is for seeded demo claims).
    claim_series: str = "CLM-2026"
    claim_sequence_start: int = 123

    max_upload_files: int = 50
    max_upload_mb: int = 25

    # Identity recorded on audit events until authentication exists.
    operator_name: str = "Demo Operator"

    # Serve the built React app from FastAPI (single-port demo mode).
    serve_frontend: bool = False
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"

    llm_provider: str = "demo"
    llm_model: str = ""
    anthropic_api_key: SecretStr = SecretStr("")
    openai_api_key: SecretStr = SecretStr("")
    openai_base_url: str = "https://api.openai.com/v1"

    @field_validator("storage_dir", "frontend_dist", "demo_data_dir", mode="after")
    @classmethod
    def _resolve_relative_to_backend(cls, value: Path) -> Path:
        return value if value.is_absolute() else (BACKEND_DIR / value).resolve()

    @field_validator("llm_provider", mode="after")
    @classmethod
    def _check_provider(cls, value: str) -> str:
        value = value.strip().lower()
        if value not in LLM_PROVIDERS:
            raise ValueError(f"LLM_PROVIDER must be one of {', '.join(LLM_PROVIDERS)}")
        return value

    @property
    def effective_llm_model(self) -> str:
        return self.llm_model or DEFAULT_LLM_MODELS[self.llm_provider]

    @property
    def llm_api_key_configured(self) -> bool:
        if self.llm_provider == "anthropic":
            return bool(self.anthropic_api_key.get_secret_value())
        if self.llm_provider == "openai":
            return bool(self.openai_api_key.get_secret_value())
        return False


@lru_cache
def get_settings() -> Settings:
    return Settings()

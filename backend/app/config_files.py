"""Loading of the YAML configuration that drives classification and quality checks."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.config import get_settings


class ConfigError(RuntimeError):
    pass


def config_path(name: str) -> Path:
    return get_settings().config_dir / name


def _load(name: str, required_keys: tuple[str, ...]) -> dict[str, Any]:
    path = config_path(name)
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"Missing configuration file: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{name} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"{name} must contain a mapping at the top level")
    missing = [key for key in required_keys if key not in data]
    if missing:
        raise ConfigError(f"{name} is missing required keys: {', '.join(missing)}")
    return data


@lru_cache
def document_types_config() -> dict[str, Any]:
    data = _load("document_types.yaml", ("types", "scoring", "signatures"))
    types = data["types"]
    if not isinstance(types, list) or not types:
        raise ConfigError("document_types.yaml: `types` must be a non-empty list")
    keys = set()
    for entry in types:
        key = entry.get("key")
        if not key or not isinstance(key, str):
            raise ConfigError("document_types.yaml: every type needs a string `key`")
        if key in keys:
            raise ConfigError(f"document_types.yaml: duplicate type key {key!r}")
        keys.add(key)
    if "other" not in keys:
        raise ConfigError("document_types.yaml: an `other` type is required as the fallback")
    return data


@lru_cache
def quality_config() -> dict[str, Any]:
    return _load("quality.yaml", ("thresholds", "severity", "render_dpi"))


@lru_cache
def canonical_config() -> dict[str, Any]:
    data = _load("canonical.yaml", ("document_weights", "default_weight", "ocr_confidence_floor"))
    weights = data["document_weights"]
    if not isinstance(weights, dict) or not all(isinstance(value, int) for value in weights.values()):
        raise ConfigError("canonical.yaml: document_weights must map a document type to an integer weight")
    floor = data["ocr_confidence_floor"]
    if not isinstance(floor, (int, float)) or not 0 <= float(floor) <= 1:
        raise ConfigError("canonical.yaml: ocr_confidence_floor must be between 0 and 1")
    return data


def reload_configs() -> None:
    document_types_config.cache_clear()
    quality_config.cache_clear()
    canonical_config.cache_clear()

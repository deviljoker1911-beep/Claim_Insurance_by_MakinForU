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
def segmentation_config() -> dict[str, Any]:
    """How the pages of one uploaded file are grouped into the documents it holds."""
    return _load(
        "segmentation.yaml",
        ("document_identifiers", "page_numbering", "min_pages_to_segment"),
    )


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


@lru_cache
def rules_config() -> dict[str, Any]:
    data = _load("rules.yaml", ("rules", "required_documents", "settings"))
    seen_ids: set[str] = set()
    seen_codes: set[str] = set()
    for rule in data["rules"]:
        for key in ("rule_id", "code", "category", "severity", "title", "explanation", "action", "evidence"):
            if not rule.get(key):
                raise ConfigError(f"rules.yaml: rule {rule.get('rule_id', '?')} is missing {key}")
        if rule["rule_id"] in seen_ids:
            raise ConfigError(f"rules.yaml: duplicate rule_id {rule['rule_id']}")
        if rule["code"] in seen_codes:
            raise ConfigError(f"rules.yaml: duplicate code {rule['code']}")
        if rule["severity"] not in ("critical", "review", "warning", "info"):
            raise ConfigError(f"rules.yaml: {rule['rule_id']} has an unknown severity {rule['severity']}")
        if rule["evidence"] not in ("required", "optional", "none"):
            raise ConfigError(f"rules.yaml: {rule['rule_id']} has an unknown evidence requirement")
        banned = [word for word in ("fraud", "forged", "fake") if word in " ".join(str(v).lower() for v in rule.values())]
        if banned:
            raise ConfigError(f"rules.yaml: {rule['rule_id']} uses forbidden wording: {banned}")
        seen_ids.add(rule["rule_id"])
        seen_codes.add(rule["code"])
    for requirement in data["required_documents"]:
        if not requirement.get("key") or not requirement.get("doc_types"):
            raise ConfigError("rules.yaml: every required document needs a key and doc_types")
    return data


@lru_cache
def checklists_config() -> dict[str, Any]:
    """The procedure checklists, checked against the document types and the conditions we have."""
    data = _load("checklists.yaml", ("requirements", "procedures", "conditions", "settings"))
    known_types = {entry["key"] for entry in document_types_config()["types"]}
    conditions = set(data["conditions"])
    severities = ("critical", "review", "warning", "info")

    catalogue: dict[str, dict] = {}
    for requirement in data["requirements"]:
        for key in ("key", "label", "description", "doc_types", "severity", "resolution", "question", "why"):
            if not requirement.get(key):
                raise ConfigError(f"checklists.yaml: requirement {requirement.get('key', '?')} is missing {key}")
        if requirement["key"] in catalogue:
            raise ConfigError(f"checklists.yaml: duplicate requirement {requirement['key']}")
        unknown = [name for name in requirement["doc_types"] if name not in known_types]
        if unknown:
            raise ConfigError(f"checklists.yaml: {requirement['key']} names unknown document types: {unknown}")
        if requirement["severity"] not in severities:
            raise ConfigError(f"checklists.yaml: {requirement['key']} has an unknown severity")
        if requirement.get("applies_when", "always") not in conditions:
            raise ConfigError(f"checklists.yaml: {requirement['key']} names an unknown condition")
        catalogue[requirement["key"]] = requirement

    seen: set[str] = set()
    for procedure in data["procedures"]:
        if not procedure.get("key") or not procedure.get("label"):
            raise ConfigError("checklists.yaml: every procedure needs a key and a label")
        if procedure["key"] in seen:
            raise ConfigError(f"checklists.yaml: duplicate procedure {procedure['key']}")
        seen.add(procedure["key"])
        entries = procedure.get("requires") or []
        if not entries:
            raise ConfigError(f"checklists.yaml: procedure {procedure['key']} requires nothing")
        used: set[str] = set()
        for entry in entries:
            key = entry if isinstance(entry, str) else entry.get("key")
            if key not in catalogue:
                raise ConfigError(f"checklists.yaml: {procedure['key']} names unknown requirement {key!r}")
            if key in used:
                raise ConfigError(f"checklists.yaml: {procedure['key']} lists requirement {key} twice")
            used.add(key)
            if isinstance(entry, dict):
                if entry.get("severity") and entry["severity"] not in severities:
                    raise ConfigError(f"checklists.yaml: {procedure['key']}/{key} has an unknown severity")
                if entry.get("applies_when", "always") not in conditions:
                    raise ConfigError(f"checklists.yaml: {procedure['key']}/{key} names an unknown condition")

    text = " ".join(str(value).lower() for value in (data["requirements"], data["procedures"]))
    banned = [word for word in ("fraud", "forged", "fake") if word in text]
    if banned:
        raise ConfigError(f"checklists.yaml uses forbidden wording: {banned}")
    return data


@lru_cache
def readiness_config() -> dict[str, Any]:
    """The readiness model: what each outstanding item costs, and what each status means."""
    data = _load("readiness.yaml", ("base_score", "floor", "deductions", "statuses", "not_charged"))
    if not isinstance(data["base_score"], int) or not 0 < data["base_score"] <= 100:
        raise ConfigError("readiness.yaml: base_score must be between 1 and 100")
    if not isinstance(data["floor"], int) or data["floor"] < 0:
        raise ConfigError("readiness.yaml: floor must be zero or more")
    required_deductions = (
        "required_document_missing",
        "required_document_documented_unavailable",
        "checklist_review_without_finding",
        "finding_critical",
        "finding_review",
        "finding_warning",
        "finding_info",
    )
    for name in required_deductions:
        value = data["deductions"].get(name)
        if not isinstance(value, int) or value < 0:
            raise ConfigError(f"readiness.yaml: deduction {name} must be a whole number of points")
    for status in ("incomplete", "needs_attention", "ready_for_human_review"):
        if not data["statuses"].get(status):
            raise ConfigError(f"readiness.yaml: status {status} needs a description")
    return data


def reload_configs() -> None:
    document_types_config.cache_clear()
    quality_config.cache_clear()
    canonical_config.cache_clear()
    rules_config.cache_clear()
    checklists_config.cache_clear()
    readiness_config.cache_clear()
    segmentation_config.cache_clear()

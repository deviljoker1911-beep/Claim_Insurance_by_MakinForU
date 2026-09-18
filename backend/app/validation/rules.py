"""The rule registry: what each rule states, and how a finding is built from it.

Rules are declared in `config/rules.yaml`. A rule owns its wording (title, explanation,
action) and what evidence it must carry; a check supplies the facts. A finding is identified
by its fingerprint — the rule and a stable subject — never by its evidence, so re-running
validation updates the finding that already exists.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal
from functools import lru_cache

from app.config_files import rules_config

# Wording that must never appear in a finding, however the facts look.
FORBIDDEN_WORDS = ("fraud", "fraudulent", "forged", "forgery", "fake")

EVIDENCE_REQUIRED = "required"
EVIDENCE_OPTIONAL = "optional"
EVIDENCE_NONE = "none"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    code: str
    category: str
    severity: str
    attribution: str
    title: str
    explanation: str
    action: str
    evidence: str


@lru_cache
def rules() -> dict[str, Rule]:
    """Rules by code."""
    out: dict[str, Rule] = {}
    for entry in rules_config()["rules"]:
        rule = Rule(
            rule_id=entry["rule_id"],
            code=entry["code"],
            category=entry["category"],
            severity=entry["severity"],
            attribution=entry.get("attribution", "rule"),
            title=" ".join(entry["title"].split()),
            explanation=" ".join(entry["explanation"].split()),
            action=" ".join(entry["action"].split()),
            evidence=entry["evidence"],
        )
        out[rule.code] = rule
    return out


def rule_for(code: str) -> Rule:
    try:
        return rules()[code]
    except KeyError as exc:  # pragma: no cover — a typo in a check is a programming error
        raise KeyError(f"No rule is declared for code {code!r} in rules.yaml") from exc


def settings() -> dict:
    return rules_config()["settings"]


def required_documents() -> list[dict]:
    return list(rules_config()["required_documents"])


def rules_version() -> int:
    return int(rules_config().get("rules_version", 1))


def amount_tolerance() -> Decimal:
    return Decimal(str(settings().get("bill_amount_tolerance", "0.00")))


def fingerprint(rule_id: str, subject: str) -> str:
    """Stable identity of a finding: the rule plus the thing it is about."""
    return hashlib.sha256(f"{rule_id}|{subject}".encode()).hexdigest()[:40]


@dataclass
class Finding:
    """A finding a check raised, before it is stored."""

    rule: Rule
    subject: str
    context: dict = field(default_factory=dict)
    evidence: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.title = _render(self.rule.title, self.context, self.rule.rule_id, "title")
        self.explanation = _render(self.rule.explanation, self.context, self.rule.rule_id, "explanation")
        self.action = _render(self.rule.action, self.context, self.rule.rule_id, "action")
        if self.rule.evidence == EVIDENCE_REQUIRED and not self.evidence:
            raise ValueError(f"{self.rule.rule_id} requires evidence but none was supplied ({self.subject})")
        if self.rule.evidence == EVIDENCE_NONE and self.evidence:
            raise ValueError(f"{self.rule.rule_id} must not carry evidence ({self.subject})")
        # The guard looks at the rule's own wording with the data blanked out: quoting a
        # document that happens to contain one of these words is not the product using it.
        blanks = _Blanks()
        wording = " ".join(
            template.format_map(blanks)
            for template in (self.rule.title, self.rule.explanation, self.rule.action)
        ).lower()
        found = [word for word in FORBIDDEN_WORDS if word in wording]
        if found:
            raise ValueError(f"{self.rule.rule_id} used forbidden wording {found} ({self.subject})")

    @property
    def fingerprint(self) -> str:
        return fingerprint(self.rule.rule_id, self.subject)

    def payload(self) -> dict:
        return {
            "rule_id": self.rule.rule_id,
            "code": self.rule.code,
            "category": self.rule.category,
            "severity": self.rule.severity,
            "attribution": self.rule.attribution,
            "title": self.title,
            "explanation": self.explanation,
            "action": self.action,
            "subject": self.subject,
            "fingerprint": self.fingerprint,
            "evidence": self.evidence,
            "context": self.context,
        }


class _Blanks(dict):
    """Renders a template with every interpolated value blanked out."""

    def __missing__(self, key: str) -> str:
        return "…"


def _render(template: str, context: dict, rule_id: str, part: str) -> str:
    try:
        return template.format_map(context)
    except KeyError as exc:  # pragma: no cover — caught by the rule tests
        raise KeyError(f"{rule_id} {part} needs {exc} in its context") from exc


def build(code: str, subject: str, *, context: dict | None = None, evidence: list[dict] | None = None) -> Finding:
    return Finding(rule=rule_for(code), subject=subject, context=context or {}, evidence=evidence or [])

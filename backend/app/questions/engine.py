"""Which questions a claim should be asking, given its checklist.

A question is asked only where the checklist says a required document is missing, and it is
asked once per requirement. The wording comes from the requirement's own template in
checklists.yaml, and the reason is the requirement's `why` — a statement about this claim's
documents, never an invented clinical fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.checklist import engine as checklist_engine
from app.models import QUESTION_PENDING_STATUSES as PENDING
from app.models import QUESTION_RESOLVED as RESOLVED

# The checklist statuses that mean the document is in the claim, so nothing needs asking.
SATISFIED = (checklist_engine.FOUND, checklist_engine.REVIEW_REQUIRED)


@dataclass(frozen=True)
class Ask:
    """A question that should exist for a requirement."""

    requirement_key: str
    requirement_label: str
    question: str
    reason: str
    expected_document_type: str
    expected_document_types: tuple[str, ...]
    severity: str
    procedure_key: str | None


@dataclass
class Plan:
    """What the stored questions of a claim should become."""

    ask: list[Ask] = field(default_factory=list)
    resolve: list[str] = field(default_factory=list)  # requirement keys the claim now carries
    withdraw: list[tuple[str, str]] = field(default_factory=list)  # (requirement key, why)

    @property
    def empty(self) -> bool:
        return not (self.ask or self.resolve or self.withdraw)


def plan(checklist: dict, existing: dict[str, str]) -> Plan:
    """Compare the checklist with the questions already stored.

    `existing` maps a requirement key to the stored question's status.
    """
    outcome = Plan()
    if not checklist.get("available"):
        # No checklist applies, so nothing can be asked from one. Questions already asked are
        # withdrawn rather than left pointing at requirements this claim no longer has.
        for key, status in sorted(existing.items()):
            if status in PENDING:
                outcome.withdraw.append((key, "This claim no longer has a checklist for this requirement."))
        return outcome

    procedure_key = (checklist.get("procedure") or {}).get("key")
    seen: set[str] = set()
    for item in checklist["items"]:
        key = item["key"]
        seen.add(key)
        status = existing.get(key)
        if item["status"] in SATISFIED:
            if status is not None and status != RESOLVED:
                outcome.resolve.append(key)
            continue
        if item["status"] == checklist_engine.NOT_APPLICABLE:
            if status in PENDING:
                outcome.withdraw.append((key, item["detail"]))
            continue
        # missing
        if not item["required"] or status is not None:
            continue
        outcome.ask.append(
            Ask(
                requirement_key=key,
                requirement_label=item["label"],
                question=item["question"],
                reason=item["why"],
                expected_document_type=item["doc_types"][0],
                expected_document_types=tuple(item["doc_types"]),
                severity=item["severity"],
                procedure_key=procedure_key,
            )
        )

    for key, status in sorted(existing.items()):
        if key not in seen and status in PENDING:
            outcome.withdraw.append((key, "This requirement is not part of the checklist for this procedure."))
    return outcome

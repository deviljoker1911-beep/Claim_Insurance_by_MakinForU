"""The procedure checklist: which documents this claim is expected to carry, and which it has.

The checklist consumes what the earlier phases produced — the procedure the documents name,
the document types recognised from their content, the bills, and the findings the rules
raised — and reports one status per requirement. It raises nothing of its own: a requirement
that is not met is reported here, and the rules decide separately whether it is also a
finding. Nothing here inspects a file name, and a document excluded as a duplicate satisfies
no requirement.
"""

from __future__ import annotations

from typing import Any

from app.analysis.classify import type_label
from app.analysis.normalize import PROCEDURES
from app.config_files import checklists_config
from app.validation.rules import required_documents, settings as rule_settings

FOUND = "found"
MISSING = "missing"
REVIEW_REQUIRED = "review_required"
NOT_APPLICABLE = "not_applicable"
STATUSES = (FOUND, MISSING, REVIEW_REQUIRED, NOT_APPLICABLE)

ALWAYS = "always"
IMPLANT_BILLED = "implant_billed"
GENERAL_ANAESTHESIA = "general_anaesthesia"

# Anaesthesia that does not put the patient under: a claim recording only this is not expected
# to carry an anaesthesia chart.
_LOCAL_ANAESTHESIA = ("local", "topical", "surface")

PROCEDURE_LABELS = {key: label for key, label, _ in PROCEDURES}


def configured_procedures() -> list[dict[str, str]]:
    """The procedures a checklist exists for."""
    return [
        {"key": procedure["key"], "label": procedure["label"]}
        for procedure in checklists_config()["procedures"]
    ]


def _procedure_config(key: str | None) -> dict | None:
    if not key:
        return None
    for procedure in checklists_config()["procedures"]:
        if procedure["key"] == key:
            return procedure
    return None


def _requirements_of(procedure: dict) -> list[dict]:
    """A procedure's requirements: the catalogue entry, with this procedure's overrides."""
    catalogue = {item["key"]: item for item in checklists_config()["requirements"]}
    resolved = []
    for entry in procedure["requires"]:
        key = entry if isinstance(entry, str) else entry["key"]
        requirement = dict(catalogue[key])
        if isinstance(entry, dict):
            requirement.update({name: value for name, value in entry.items() if name != "key"})
        requirement.setdefault("required", True)
        requirement.setdefault("applies_when", ALWAYS)
        resolved.append(requirement)
    return resolved


def _anaesthesia_text(state: dict) -> str:
    value = state.get("procedures", {}).get("fields", {}).get("anaesthesia") or {}
    return (value.get("normalized_value") or value.get("value") or "").lower()


def _condition_holds(condition: str, state: dict) -> tuple[bool, str | None]:
    """Whether a requirement's condition holds, and why not when it does not.

    The reason is shown to a reviewer, so it says what the claim shows rather than naming
    the condition.
    """
    if condition == ALWAYS:
        return True, None
    if condition == IMPLANT_BILLED:
        bill_types = set(required_implant_bill_types())
        billed = [bill for bill in state["bills"]["items"] if bill["bill_type"] in bill_types]
        if billed:
            return True, None
        return False, "No implant is billed in this claim."
    if condition == GENERAL_ANAESTHESIA:
        anaesthesia = _anaesthesia_text(state)
        if not anaesthesia:
            # Nothing states the anaesthesia, so the requirement stands rather than being
            # waved away on an assumption.
            return True, None
        if any(word in anaesthesia for word in _LOCAL_ANAESTHESIA) and "general" not in anaesthesia:
            return False, f"The records give the anaesthesia as {anaesthesia}."
        return True, None
    raise ValueError(f"checklist condition {condition!r} is not implemented")


def required_implant_bill_types() -> list[str]:
    """Which bills count as an implant bill — the same setting the implant rule uses."""
    return list(rule_settings().get("implant_bill_types", ["implant_invoice"]))


def _rule_requirement_keys() -> dict[str, tuple[str, ...]]:
    """The document types behind each required-document requirement of the rules."""
    return {item["key"]: tuple(item["doc_types"]) for item in required_documents()}


def _document_evidence(document: dict) -> dict:
    """What satisfies a requirement, as a reviewer sees it.

    A document satisfies a requirement as a whole, so there is no page to cite; the page a
    value came from belongs to that value's own evidence.
    """
    return {
        "document_id": document["document_id"],
        "document_name": document["filename"],
        "doc_type": document["doc_type"],
        "doc_type_label": document["doc_type_label"] or type_label(document["doc_type"]),
        "classification_confidence": document["classification_confidence"],
        "classification_method": document["classification_method"],
        "page_count": document["page_count"],
        "page": None,
        "detail": "Source document identified; page-level evidence unavailable.",
    }


def build_checklist(state: dict, findings: list[dict] | None = None) -> dict:
    """The checklist for the procedure this claim's documents name."""
    findings = findings or []
    config = checklists_config()
    settings = config.get("settings", {})
    review_severities = set(settings.get("review_required_severities", ["critical", "review"]))
    provisional_states = set(settings.get("provisional_document_states", []))

    documents = state["documents"]["items"]
    usable = [
        document
        for document in documents
        if document["processing_status"] == "processed" and not document["excluded"] and document["doc_type"]
    ]
    provisional = any(document["processing_status"] in provisional_states for document in documents)

    procedure_key = state["procedures"].get("selected_key")
    procedure = _procedure_config(procedure_key)
    detected = _detected(state, procedure_key, procedure)

    if procedure is None:
        return {
            "available": False,
            "checklist_version": int(config.get("version", 1)),
            "procedure": detected,
            "provisional": provisional,
            "count": 0,
            "summary": _summarise([]),
            "items": [],
            "configured_procedures": configured_procedures(),
            "note": (
                f"No checklist is configured for {detected['label']}."
                if procedure_key
                else "No procedure is named in the documents yet, so no checklist applies."
            ),
        }

    by_document = _findings_by_document(findings)
    by_requirement = _findings_by_requirement(findings, _rule_requirement_keys())

    items = []
    for requirement in _requirements_of(procedure):
        items.append(
            _evaluate(
                requirement,
                state=state,
                usable=usable,
                excluded=[document for document in documents if document["excluded"]],
                findings_by_document=by_document,
                findings_by_requirement=by_requirement,
                review_severities=review_severities,
            )
        )

    return {
        "available": True,
        "checklist_version": int(config.get("version", 1)),
        "procedure": detected,
        "provisional": provisional,
        "count": len(items),
        "summary": _summarise(items),
        "items": items,
        "configured_procedures": configured_procedures(),
        "note": procedure.get("note"),
    }


def _detected(state: dict, procedure_key: str | None, procedure: dict | None) -> dict:
    """The procedure the checklist is built for, and what named it."""
    section = state["procedures"]
    selected = next((item for item in section["items"] if item.get("is_selected")), None)
    others = [
        {"key": item["normalized_value"], "label": item["label"], "source_count": item["source_count"]}
        for item in section["items"]
        if not item.get("is_selected")
    ]
    label = None
    if procedure:
        label = procedure["label"]
    elif selected:
        label = selected["label"]
    elif procedure_key:
        label = PROCEDURE_LABELS.get(procedure_key, procedure_key.replace("_", " "))
    return {
        "key": procedure_key,
        "label": label or "no procedure",
        "has_checklist": procedure is not None,
        "source_count": selected["source_count"] if selected else 0,
        "documents": [
            {
                "document_id": source["document_id"],
                "document_name": source["document_name"],
                "value": source.get("value"),
                "page": source.get("page"),
            }
            for source in (selected["sources"] if selected else [])
        ],
        "written_as": [variant["value"] for variant in (selected["value_variants"] if selected else [])],
        "also_named": others,
    }


def _findings_by_document(findings: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for finding in findings:
        for document_id in finding.get("document_ids") or []:
            grouped.setdefault(document_id, []).append(finding)
    return grouped


def _findings_by_requirement(findings: list[dict], rule_requirements: dict[str, tuple[str, ...]]) -> dict[str, list[dict]]:
    """Findings that are about a requirement rather than about a document.

    A missing-document finding names the requirement of the rules; it is matched to a
    checklist requirement through the document types the two have in common.
    """
    grouped: dict[str, list[dict]] = {}
    for finding in findings:
        subject = finding.get("subject") or ""
        if not subject.startswith("requirement:"):
            continue
        doc_types = rule_requirements.get(subject.split(":", 1)[1])
        for doc_type in doc_types or ():
            grouped.setdefault(doc_type, []).append(finding)
    return grouped


def _evaluate(
    requirement: dict,
    *,
    state: dict,
    usable: list[dict],
    excluded: list[dict],
    findings_by_document: dict[str, list[dict]],
    findings_by_requirement: dict[str, list[dict]],
    review_severities: set[str],
) -> dict:
    doc_types = tuple(requirement["doc_types"])
    labels = [type_label(doc_type) for doc_type in doc_types]
    row: dict[str, Any] = {
        "key": requirement["key"],
        "label": requirement["label"],
        "description": requirement["description"],
        "doc_types": list(doc_types),
        "doc_type_labels": labels,
        "required": bool(requirement.get("required", True)),
        "severity": requirement["severity"],
        "applies_when": requirement.get("applies_when", ALWAYS),
        "resolution": requirement["resolution"],
        # What to ask the operator for this requirement, and why it is being asked (phase 7).
        "question": requirement["question"],
        "why": requirement["why"],
        "status": MISSING,
        "detail": "",
        "evidence": [],
        "findings": [],
    }

    holds, reason = _condition_holds(row["applies_when"], state)
    if not holds:
        row["status"] = NOT_APPLICABLE
        row["detail"] = reason or "This requirement does not apply to this claim."
        return row

    matches = [document for document in usable if document["doc_type"] in doc_types]
    related = _related_findings(matches, doc_types, findings_by_document, findings_by_requirement)
    row["findings"] = related

    if matches:
        row["evidence"] = [_document_evidence(document) for document in matches]
        open_findings = [
            finding
            for finding in related
            if finding["is_active"]
            and finding["severity"] in review_severities
            and set(finding.get("document_ids") or []) & {document["document_id"] for document in matches}
        ]
        names = ", ".join(document["filename"] for document in matches)
        covers = "covers" if len(matches) == 1 else "cover"
        if open_findings:
            row["status"] = REVIEW_REQUIRED
            about = (
                f"One open finding is about it: {open_findings[0]['title']}."
                if len(open_findings) == 1
                else f"{len(open_findings)} open findings are about it."
            )
            row["detail"] = f"{names} {covers} this requirement. {about}"
        else:
            row["status"] = FOUND
            row["detail"] = (
                f"{names} is in the claim as {_join(labels)}."
                if len(matches) == 1
                else f"{names} are in the claim as {_join(labels)}."
            )
        return row

    row["status"] = MISSING
    shadowed = [document for document in excluded if document["doc_type"] in doc_types]
    if shadowed:
        row["detail"] = (
            f"The only {_join(labels).lower()} in this claim "
            f"({', '.join(document['filename'] for document in shadowed)}) is excluded as a duplicate."
        )
    else:
        row["detail"] = f"No document in this claim was classified as {_join(labels).lower()}."
    return row


def _related_findings(
    matches: list[dict],
    doc_types: tuple[str, ...],
    findings_by_document: dict[str, list[dict]],
    findings_by_requirement: dict[str, list[dict]],
) -> list[dict]:
    seen: dict[str, dict] = {}
    for document in matches:
        for finding in findings_by_document.get(document["document_id"], []):
            seen[finding["id"]] = finding
    for doc_type in doc_types:
        for finding in findings_by_requirement.get(doc_type, []):
            seen[finding["id"]] = finding
    return [seen[key] for key in sorted(seen)]


def _summarise(items: list[dict]) -> dict:
    counts = {status: sum(1 for item in items if item["status"] == status) for status in STATUSES}
    outstanding = [
        item for item in items if item["required"] and item["status"] in (MISSING, REVIEW_REQUIRED)
    ]
    return {
        **counts,
        "total": len(items),
        "required": sum(1 for item in items if item["required"]),
        "required_outstanding": len(outstanding),
        "by_severity": {
            severity: sum(1 for item in outstanding if item["severity"] == severity)
            for severity in ("critical", "review", "warning", "info")
        },
    }


def _join(values: list[str]) -> str:
    if not values:
        return ""
    if len(values) == 1:
        return values[0]
    return f"{', '.join(values[:-1])} or {values[-1]}"

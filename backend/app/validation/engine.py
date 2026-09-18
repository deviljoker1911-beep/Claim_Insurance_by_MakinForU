"""The validation engine: deterministic checks over the canonical claim and its evidence.

Each check compares what the documents say, states what it found, and records whether it
passed, failed, could not run yet (pending) or did not apply. Findings come from the rules in
`config/rules.yaml`; the checks only supply facts and evidence. Nothing here interprets intent:
a finding says what differs and what a person should do about it.

The engine reads; it never writes. Storing findings and moving them through their lifecycle is
`app.services.validation`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analysis import normalize as nz
from app.canonical.builder import build_claim_state, json_ready
from app.models import Claim, Document, DocumentPage
from app.services.canonical import content_hash
from app.validation import duplicates as dup
from app.validation.rules import (
    Finding,
    amount_tolerance,
    build,
    required_documents,
    rules_version,
    settings,
)

logger = logging.getLogger("claimai.validation")

PASS = "pass"
FAIL = "fail"
PENDING = "pending"
NOT_APPLICABLE = "not_applicable"

SEVERITY_ORDER = {"critical": 0, "review": 1, "warning": 2, "info": 3}


@dataclass
class CheckOutcome:
    """The record of one check having run."""

    check_id: str
    title: str
    category: str
    status: str
    detail: str
    rule_ids: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    subjects_checked: int = 0

    def payload(self) -> dict:
        severities = [finding.rule.severity for finding in self.findings]
        highest = min(severities, key=lambda item: SEVERITY_ORDER[item]) if severities else None
        return {
            "check_id": self.check_id,
            "title": self.title,
            "category": self.category,
            "status": self.status,
            "detail": self.detail,
            "rule_ids": sorted(self.rule_ids),
            "finding_count": len(self.findings),
            "finding_codes": sorted({finding.rule.code for finding in self.findings}),
            "finding_fingerprints": sorted(finding.fingerprint for finding in self.findings),
            "severity": highest,
            "subjects_checked": self.subjects_checked,
        }


@dataclass
class ValidationResult:
    checks: list[dict]
    findings: list[Finding]
    document_updates: dict[str, dict]
    input_fingerprint: str
    rules_version: int
    summary: dict


# --- context ------------------------------------------------------------------------------


@dataclass
class Context:
    claim: Claim
    state: dict
    documents: list[Document]
    pages: dict[str, list[DocumentPage]]

    @property
    def active(self) -> list[Document]:
        """Processed documents that still belong to the claim."""
        return [
            document
            for document in self.documents
            if document.processing_status == "processed" and not document.excluded
        ]

    def document(self, document_id: str | None) -> Document | None:
        return next((item for item in self.documents if item.id == document_id), None)

    def value(self, path: str) -> dict:
        """One canonical value, by its path ("patient.name")."""
        section, name = path.split(".", 1)
        block = self.state[section]
        fields = block["fields"] if "fields" in block else {}
        return fields.get(name, {"present": False, "sources": [], "competing_values": [], "value": None})

    def page_text(self, document: Document) -> str:
        return "\n".join(page.text or "" for page in self.pages.get(document.id, []))


def _evidence(
    *,
    kind: str,
    document: Document | None = None,
    page: int | None = None,
    bounding_box: list | None = None,
    snippet: str | None = None,
    method: str = "rule",
    source_type: str | None = None,
    confidence: float | None = None,
    value: str | None = None,
    field_key: str | None = None,
    detail: str | None = None,
) -> dict:
    return {
        "kind": kind,
        "document_id": document.id if document else None,
        "document_name": document.original_filename if document else None,
        "document_type": document.doc_type if document else None,
        "document_type_label": _type_label(document) if document else None,
        "page": page,
        "bounding_box": list(bounding_box) if bounding_box else None,
        "snippet": snippet,
        "method": method,
        "source_type": source_type or (document.text_source if document else None),
        "confidence": round(float(confidence), 4) if confidence is not None else None,
        "value": value,
        "field_key": field_key,
        "detail": detail,
        "evidence_available": bool(page and bounding_box),
    }


def _type_label(document: Document) -> str | None:
    from app.analysis.classify import type_label

    return type_label(document.doc_type) if document.doc_type else None


def _source_evidence(source: dict, *, kind: str = "field", detail: str | None = None) -> dict:
    """A canonical source, carried into a finding unchanged."""
    return {
        "kind": kind,
        "document_id": source.get("document_id"),
        "document_name": source.get("document_name"),
        "document_type": source.get("document_type"),
        "document_type_label": source.get("document_type_label"),
        "page": source.get("page"),
        "bounding_box": source.get("bounding_box"),
        "snippet": source.get("snippet"),
        "method": source.get("method", "rule"),
        "source_type": source.get("source_type"),
        "confidence": source.get("confidence"),
        "value": source.get("value"),
        "field_key": source.get("field_key"),
        "detail": detail,
        "evidence_available": bool(source.get("page") and source.get("bounding_box")),
    }


def _names(sources: list[dict]) -> str:
    unique = sorted({source.get("document_name") or "a document" for source in sources})
    if len(unique) == 1:
        return unique[0]
    return ", ".join(unique[:-1]) + f" and {unique[-1]}"


def _decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _money(value: Decimal | None) -> str:
    return nz.format_indian(value) or "—" if value is not None else "—"


# --- checks --------------------------------------------------------------------------------


def check_required_documents(ctx: Context) -> CheckOutcome:
    requirements = required_documents()
    outcome = CheckOutcome(
        check_id="required_documents",
        title="Required documents are present",
        category="completeness",
        status=PASS,
        detail="",
        rule_ids=["R001"],
        subjects_checked=len(requirements),
    )
    if not ctx.active:
        outcome.status = PENDING
        outcome.detail = "No processed documents yet, so the requirements cannot be checked."
        return outcome

    present_types = {document.doc_type for document in ctx.active if document.doc_type}
    missing = []
    for requirement in requirements:
        if set(requirement["doc_types"]) & present_types:
            continue
        missing.append(requirement)
        outcome.findings.append(
            build(
                "MISSING_REQUIRED_DOCUMENT",
                f"requirement:{requirement['key']}",
                context={
                    "label": requirement["label"],
                    "label_lower": requirement["label"].lower(),
                    "requirement": requirement["key"],
                    "doc_types": requirement["doc_types"],
                },
            )
        )
    if missing:
        outcome.status = FAIL
        outcome.detail = f"Missing: {', '.join(item['label'] for item in missing)}."
    else:
        outcome.detail = f"All {len(requirements)} required document types are present."
    return outcome


def _competing_check(
    ctx: Context,
    *,
    check_id: str,
    title: str,
    category: str,
    path: str,
    code: str,
    context_builder,
) -> CheckOutcome:
    """The shared shape of "do the documents agree on this value?"."""
    value = ctx.value(path)
    outcome = CheckOutcome(
        check_id=check_id, title=title, category=category, status=PASS, detail="", rule_ids=[], subjects_checked=0
    )
    if not value.get("present"):
        outcome.status = PENDING
        outcome.detail = "No document in this claim carries this value yet."
        return outcome
    outcome.subjects_checked = value.get("source_count", 0) + sum(
        item["source_count"] for item in value.get("competing_values", [])
    )
    competing = value.get("competing_values", [])
    if not competing:
        outcome.detail = f"{outcome.subjects_checked} document(s) agree on {value['value']!r}."
        return outcome
    outcome.status = FAIL
    for group in competing:
        finding = context_builder(value, group)
        if finding is not None:
            outcome.findings.append(finding)
            outcome.rule_ids.append(finding.rule.rule_id)
    outcome.detail = (
        f"{value['source_count']} document(s) state {value['value']!r}; "
        f"{len(competing)} other value(s) were found."
    )
    return outcome


def check_patient_name(ctx: Context) -> CheckOutcome:
    def builder(value: dict, group: dict) -> Finding:
        return build(
            "PATIENT_NAME_MISMATCH",
            f"patient.name:{group['normalized_value']}",
            context={
                "canonical": value["value"],
                "canonical_sources": value["source_count"],
                "other": group["value"],
                "documents": _names(group["sources"]),
                "source_count": group["source_count"],
            },
            evidence=[_source_evidence(source, detail=f"states {group['value']!r}") for source in group["sources"]],
        )

    return _competing_check(
        ctx,
        check_id="patient_name_consistency",
        title="Patient name agrees across the documents",
        category="identity",
        path="patient.name",
        code="PATIENT_NAME_MISMATCH",
        context_builder=builder,
    )


def check_uhid(ctx: Context) -> CheckOutcome:
    def builder(value: dict, group: dict) -> Finding:
        return build(
            "UHID_MISMATCH",
            f"patient.uhid:{group['normalized_value']}",
            context={
                "canonical": value["value"],
                "canonical_sources": value["source_count"],
                "other": group["value"],
                "documents": _names(group["sources"]),
                "source_count": group["source_count"],
            },
            evidence=[_source_evidence(source, detail=f"states {group['value']!r}") for source in group["sources"]],
        )

    return _competing_check(
        ctx,
        check_id="uhid_consistency",
        title="UHID agrees across the documents",
        category="identity",
        path="patient.uhid",
        code="UHID_MISMATCH",
        context_builder=builder,
    )


def check_name_variants(ctx: Context) -> CheckOutcome:
    """The same name printed differently is recorded, so it is not mistaken for a mismatch."""
    outcome = CheckOutcome(
        check_id="name_spelling_variants",
        title="Spelling variations of the same value",
        category="identity",
        status=PASS,
        detail="",
        rule_ids=["R019"],
    )
    checked = 0
    for path, label in (("patient.name", "Patient name"), ("patient.uhid", "UHID")):
        value = ctx.value(path)
        if not value.get("present"):
            continue
        checked += 1
        variants = [item for item in value.get("value_variants", []) if item["value"] != value["value"]]
        for variant in variants:
            sources = [source for source in value["sources"] if source.get("value") == variant["value"]]
            outcome.findings.append(
                build(
                    "NAME_VARIANT",
                    f"{path}:variant:{variant['value']}",
                    context={
                        "label": label,
                        "label_lower": label.lower(),
                        "canonical": value["value"],
                        "variants": ", ".join(
                            f"{item['value']!r} on {item['source_count']} document(s)"
                            for item in value.get("value_variants", [])
                        ),
                    },
                    evidence=[_source_evidence(source, detail=f"prints {variant['value']!r}") for source in sources],
                )
            )
    outcome.subjects_checked = checked
    if not checked:
        outcome.status = PENDING
        outcome.detail = "No identity values are available yet."
    elif outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} spelling variation(s) recorded."
    else:
        outcome.detail = "Every document prints these values the same way."
    return outcome


CLAIM_FORM_FIELDS = (
    ("patient_name", "patient name", "patient.name", "name"),
    ("uhid", "UHID", "patient.uhid", "id"),
    ("admission_date", "admission date", "admission.admission_date", "date"),
    ("discharge_date", "discharge date", "admission.discharge_date", "date"),
)


def check_claim_form(ctx: Context) -> CheckOutcome:
    """What the operator typed against what the documents say."""
    from app.canonical.selection import normalise

    outcome = CheckOutcome(
        check_id="claim_form_identity",
        title="Claim form matches the documents",
        category="identity",
        status=PASS,
        detail="",
        rule_ids=["R005"],
    )
    form = ctx.state["claim"]["form"]
    compared = 0
    for form_key, label, path, kind in CLAIM_FORM_FIELDS:
        form_value = form.get(form_key)
        value = ctx.value(path)
        if not form_value or not value.get("present"):
            continue
        compared += 1
        if normalise(kind, str(form_value)) == value.get("normalized_value"):
            continue
        outcome.findings.append(
            build(
                "CLAIM_FORM_MISMATCH",
                f"claim_form:{form_key}",
                context={
                    "field": form_key,
                    "field_label": label,
                    "form_value": form_value,
                    "document_value": value["value"],
                    "source_count": value["source_count"],
                },
                evidence=[_source_evidence(source, detail=f"states {value['value']!r}") for source in value["sources"]],
            )
        )
    outcome.subjects_checked = compared
    if not compared:
        outcome.status = PENDING
        outcome.detail = "The documents do not carry these values yet."
    elif outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} claim form value(s) differ from the documents."
    else:
        outcome.detail = f"All {compared} claim form value(s) match the documents."
    return outcome


def _date_check(ctx: Context, *, check_id: str, title: str, path: str, code: str) -> CheckOutcome:
    def builder(value: dict, group: dict) -> Finding:
        return build(
            code,
            f"{path}:{group['normalized_value']}",
            context={
                "canonical": value["value"],
                "canonical_sources": value["source_count"],
                "other": group["value"],
                "documents": _names(group["sources"]),
                "source_count": group["source_count"],
            },
            evidence=[_source_evidence(source, detail=f"states {group['value']}") for source in group["sources"]],
        )

    return _competing_check(
        ctx,
        check_id=check_id,
        title=title,
        category="dates",
        path=path,
        code=code,
        context_builder=builder,
    )


def check_admission_date(ctx: Context) -> CheckOutcome:
    return _date_check(
        ctx,
        check_id="admission_date_consistency",
        title="Admission date agrees across the documents",
        path="admission.admission_date",
        code="ADMISSION_DATE_MISMATCH",
    )


def check_discharge_date(ctx: Context) -> CheckOutcome:
    return _date_check(
        ctx,
        check_id="discharge_date_consistency",
        title="Discharge date agrees across the documents",
        path="admission.discharge_date",
        code="DISCHARGE_DATE_MISMATCH",
    )


def check_date_sequence(ctx: Context) -> CheckOutcome:
    """Admission, surgery and discharge must fall in that order."""
    outcome = CheckOutcome(
        check_id="date_sequence",
        title="Admission, surgery and discharge are in order",
        category="dates",
        status=PASS,
        detail="",
        rule_ids=["R008"],
    )
    admission = ctx.value("admission.admission_date")
    discharge = ctx.value("admission.discharge_date")
    surgery = ctx.value("admission.surgery_date")
    if not admission.get("present") or not discharge.get("present"):
        outcome.status = PENDING
        outcome.detail = "Both an admission date and a discharge date are needed for this check."
        return outcome

    parsed = {
        "admission": nz.parse_date(admission["value"]),
        "discharge": nz.parse_date(discharge["value"]),
        "surgery": nz.parse_date(surgery["value"]) if surgery.get("present") else None,
    }
    comparisons = [
        ("discharge_before_admission", "discharge", "admission", "Discharge date is before the admission date"),
        ("surgery_before_admission", "surgery", "admission", "Surgery date is before the admission date"),
    ]
    outcome.subjects_checked = 2 if parsed["surgery"] else 1
    for subject, later_key, earlier_key, title in comparisons:
        later, earlier = parsed[later_key], parsed[earlier_key]
        if later is None or earlier is None or later >= earlier:
            continue
        outcome.findings.append(
            build(
                "DATE_SEQUENCE_INVALID",
                f"sequence:{subject}",
                context={
                    "detail_title": title,
                    "detail": (
                        f"The documents state a {later_key} date of {later.isoformat()} and an "
                        f"{earlier_key} date of {earlier.isoformat()}, which cannot both be right."
                    ),
                },
                evidence=[
                    _source_evidence(source, detail=f"{later_key} date")
                    for source in (discharge if later_key == "discharge" else surgery)["sources"][:3]
                ],
            )
        )
    if parsed["surgery"] and parsed["discharge"] and parsed["surgery"] > parsed["discharge"]:
        outcome.findings.append(
            build(
                "DATE_SEQUENCE_INVALID",
                "sequence:surgery_after_discharge",
                context={
                    "detail_title": "Surgery date is after the discharge date",
                    "detail": (
                        f"The documents state a surgery date of {parsed['surgery'].isoformat()} and a discharge "
                        f"date of {parsed['discharge'].isoformat()}, which cannot both be right."
                    ),
                },
                evidence=[_source_evidence(source, detail="surgery date") for source in surgery["sources"][:3]],
            )
        )
    if outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} impossible date sequence(s)."
    else:
        dates = " → ".join(
            value.isoformat() for key, value in (("a", parsed["admission"]), ("s", parsed["surgery"]), ("d", parsed["discharge"])) if value
        )
        outcome.detail = f"Dates are in order ({dates})."
    return outcome


def check_diagnosis(ctx: Context) -> CheckOutcome:
    def builder(value: dict, group: dict) -> Finding:
        return build(
            "DIAGNOSIS_INCONSISTENT",
            f"diagnosis:{group['normalized_value']}",
            context={
                "canonical": value["value"],
                "canonical_sources": value["source_count"],
                "other": group["value"],
                "documents": _names(group["sources"]),
                "source_count": group["source_count"],
            },
            evidence=[_source_evidence(source, detail=f"states {group['value']!r}") for source in group["sources"]],
        )

    return _competing_check(
        ctx,
        check_id="diagnosis_consistency",
        title="Diagnosis agrees across the documents",
        category="clinical",
        path="diagnosis.primary",
        code="DIAGNOSIS_INCONSISTENT",
        context_builder=builder,
    )


def check_procedure(ctx: Context) -> CheckOutcome:
    """One operation should be named by the documents of one claim."""
    outcome = CheckOutcome(
        check_id="procedure_consistency",
        title="One procedure is named across the documents",
        category="clinical",
        status=PASS,
        detail="",
        rule_ids=["R010"],
    )
    procedures = ctx.state["procedures"]["items"]
    outcome.subjects_checked = len(procedures)
    if not procedures:
        outcome.status = PENDING
        outcome.detail = "No procedure is named in the documents yet."
        return outcome
    selected = procedures[0]
    for other in procedures[1:]:
        outcome.findings.append(
            build(
                "PROCEDURE_INCONSISTENT",
                f"procedure:{other['normalized_value']}",
                context={
                    "canonical": selected["label"],
                    "canonical_sources": selected["source_count"],
                    "other": other["label"],
                    "other_sources": other["source_count"],
                    "documents": _names(other["sources"]),
                },
                evidence=[_source_evidence(source, detail=f"names {other['value']!r}") for source in other["sources"]],
            )
        )
    if outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(procedures)} different procedures are named."
    else:
        outcome.detail = f"{selected['source_count']} document(s) name {selected['label']!r}."
    return outcome


DOCTOR_ROLES = (
    ("doctors.surgeon", "Surgeon", "operated"),
    ("doctors.anaesthetist", "Anaesthetist", "gave the anaesthetic"),
)


def check_doctors(ctx: Context) -> CheckOutcome:
    outcome = CheckOutcome(
        check_id="doctor_consistency",
        title="Surgeon and anaesthetist agree across the documents",
        category="clinical",
        status=PASS,
        detail="",
        rule_ids=["R011"],
    )
    checked = []
    for path, role_label, role_action in DOCTOR_ROLES:
        value = ctx.value(path)
        if not value.get("present"):
            continue
        checked.append(role_label)
        for group in value.get("competing_values", []):
            outcome.findings.append(
                build(
                    "DOCTOR_MISMATCH",
                    f"{path}:{group['normalized_value']}",
                    context={
                        "role_label": role_label,
                        "role_lower": role_action,
                        "canonical": value["value"],
                        "canonical_sources": value["source_count"],
                        "other": group["value"],
                        "documents": _names(group["sources"]),
                    },
                    evidence=[
                        _source_evidence(source, detail=f"states {group['value']!r}") for source in group["sources"]
                    ],
                )
            )
    outcome.subjects_checked = len(checked)
    if not checked:
        outcome.status = PENDING
        outcome.detail = "No doctor is named in the documents yet."
    elif outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} difference(s) between documents."
    else:
        outcome.detail = f"{' and '.join(checked)} named consistently."
    return outcome


def check_operative_documentation(ctx: Context) -> CheckOutcome:
    """Checks that need the operative note: they wait rather than mislead."""
    outcome = CheckOutcome(
        check_id="operative_documentation",
        title="Operative note corroborates the procedure and the surgeon",
        category="clinical",
        status=PASS,
        detail="",
        rule_ids=["R010", "R011"],
    )
    notes = [document for document in ctx.active if document.doc_type == "operative_note"]
    if not notes:
        outcome.status = PENDING
        outcome.detail = "No operative note has been supplied, so this check cannot run yet."
        return outcome

    note_ids = {document.id for document in notes}
    outcome.subjects_checked = len(notes)
    parts = []
    for path, label in (("procedures.procedure", "procedure"), ("doctors.surgeon", "surgeon")):
        value = ctx.state["procedures"]["selected"] if path == "procedures.procedure" else ctx.value(path)
        if not value or not value.get("present"):
            continue
        in_note = [source for source in value["sources"] if source.get("document_id") in note_ids]
        parts.append(f"{label} {'corroborated' if in_note else 'not stated in the operative note'}")
    outcome.detail = "; ".join(parts) or "The operative note carries no comparable values."
    return outcome


def check_bill_numbers(ctx: Context) -> CheckOutcome:
    outcome = CheckOutcome(
        check_id="bill_numbers_unique",
        title="Each bill has its own number",
        category="billing",
        status=PASS,
        detail="",
        rule_ids=["R012"],
    )
    bills = ctx.state["bills"]["items"]
    if not bills:
        outcome.status = NOT_APPLICABLE
        outcome.detail = "No bills in this claim."
        return outcome

    groups: dict[str, list[dict]] = {}
    for bill in bills:
        number = bill["fields"]["number"]
        if not number.get("present"):
            continue
        groups.setdefault(number["normalized_value"], []).append(bill)
    outcome.subjects_checked = len(groups)
    for normalized, shared in sorted(groups.items()):
        if len(shared) < 2:
            continue
        evidence = []
        for bill in shared:
            evidence.extend(
                _source_evidence(source, detail=f"{bill['bill_type_label']} bill number")
                for source in bill["fields"]["number"]["sources"]
            )
        totals = ", ".join(
            f"{bill['bill_type_label']} {_money(_decimal(bill['fields']['total']['value']))}" for bill in shared
        )
        outcome.findings.append(
            build(
                "DUPLICATE_BILL_NUMBER",
                f"bill_number:{normalized}",
                context={
                    "bill_number": shared[0]["fields"]["number"]["value"],
                    "count": len(shared),
                    "documents": _names([{"document_name": bill["document_name"]} for bill in shared]),
                    "totals": totals,
                },
                evidence=evidence,
            )
        )
    if outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} bill number(s) are used more than once."
    else:
        outcome.detail = f"{len(groups)} bill number(s), each used once."
    return outcome


def check_bill_arithmetic(ctx: Context) -> CheckOutcome:
    """Line quantity × rate → line amount → subtotal → tax → total."""
    outcome = CheckOutcome(
        check_id="bill_arithmetic",
        title="Bill amounts add up",
        category="billing",
        status=PASS,
        detail="",
        rule_ids=["R013"],
    )
    bills = ctx.state["bills"]["items"]
    if not bills:
        outcome.status = NOT_APPLICABLE
        outcome.detail = "No bills in this claim."
        return outcome

    tolerance = amount_tolerance()
    checked = 0
    for bill in bills:
        document = ctx.document(bill["document_id"])
        if document is None:
            continue
        number = bill["fields"]["number"]["value"] or document.original_filename
        subject_base = f"bill:{nz.squash(number).replace(' ', '')}"
        label = bill["bill_type_label"] or "Bill"

        # 1. quantity × rate = line amount
        line_total = Decimal("0.00")
        for line in bill["line_items"]:
            amount = _decimal(line.get("amount"))
            rate = _decimal(line.get("rate"))
            quantity = _decimal(line.get("quantity"))
            if amount is not None:
                line_total += amount
            if amount is None or rate is None or quantity is None:
                continue
            checked += 1
            expected = (quantity * rate).quantize(Decimal("0.01"))
            if abs(expected - amount) <= tolerance:
                continue
            difference = (amount - expected).copy_abs()
            outcome.findings.append(
                build(
                    "BILL_ARITHMETIC_MISMATCH",
                    f"{subject_base}:line:{line.get('line_no')}",
                    context={
                        "subject_label": f"Line {line.get('line_no')}",
                        "document_name": document.original_filename,
                        "detail": (
                            f"{label} line {line.get('line_no')} ({line.get('description')}) bills "
                            f"{line.get('quantity')} × {_money(rate)} as {_money(amount)}; "
                            f"{line.get('quantity')} × {_money(rate)} is {_money(expected)}, "
                            f"a difference of {_money(difference)}."
                        ),
                    },
                    evidence=[
                        _evidence(
                            kind="bill_line",
                            document=document,
                            page=line["evidence"].get("page"),
                            bounding_box=line["evidence"].get("bounding_box"),
                            snippet=line["evidence"].get("snippet"),
                            method="bill_table",
                            value=line.get("amount"),
                            detail=f"billed {_money(amount)}, expected {_money(expected)}",
                        )
                    ],
                )
            )

        subtotal = _decimal(bill["fields"]["subtotal"]["value"])
        tax = _decimal(bill["fields"]["tax"]["value"])
        discount = _decimal(bill["fields"]["discount"]["value"])
        total = _decimal(bill["fields"]["total"]["value"])

        # 2. sum of the lines = subtotal
        if bill["line_items"] and subtotal is not None:
            checked += 1
            if abs(line_total - subtotal) > tolerance:
                outcome.findings.append(
                    build(
                        "BILL_ARITHMETIC_MISMATCH",
                        f"{subject_base}:subtotal",
                        context={
                            "subject_label": "Subtotal",
                            "document_name": document.original_filename,
                            "detail": (
                                f"The {len(bill['line_items'])} billed lines add up to {_money(line_total)}, "
                                f"while the subtotal states {_money(subtotal)}, a difference of "
                                f"{_money((line_total - subtotal).copy_abs())}."
                            ),
                        },
                        evidence=[_source_evidence(source, detail="stated subtotal") for source in bill["fields"]["subtotal"]["sources"]],
                    )
                )

        # 3. subtotal + tax - discount = total. When a bill does not state its tax, a total
        #    above the subtotal is left alone: the unstated tax could account for it.
        if subtotal is not None and total is not None:
            expected_total = subtotal + (tax or Decimal("0.00")) - (discount or Decimal("0.00"))
            unexplained_tax = tax is None and total > subtotal
            if not unexplained_tax:
                checked += 1
                if abs(expected_total - total) > tolerance:
                    outcome.findings.append(
                        build(
                            "BILL_ARITHMETIC_MISMATCH",
                            f"{subject_base}:total",
                            context={
                                "subject_label": "Total",
                                "document_name": document.original_filename,
                                "detail": (
                                    f"Subtotal {_money(subtotal)}"
                                    + (f" plus tax {_money(tax)}" if tax is not None else "")
                                    + (f" less discount {_money(discount)}" if discount is not None else "")
                                    + f" is {_money(expected_total)}, while the bill total states {_money(total)}."
                                ),
                            },
                            evidence=[_source_evidence(source, detail="stated total") for source in bill["fields"]["total"]["sources"]],
                        )
                    )
    outcome.subjects_checked = checked
    if outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} amount(s) do not add up across {len(bills)} bill(s)."
    else:
        outcome.detail = f"{checked} amount(s) across {len(bills)} bill(s) add up."
    return outcome


def check_duplicate_documents(ctx: Context) -> CheckOutcome:
    outcome = CheckOutcome(
        check_id="duplicate_documents",
        title="No document was uploaded twice",
        category="duplicates",
        status=PASS,
        detail="",
        rule_ids=["R016"],
    )
    active = ctx.active
    if len(active) < 2:
        outcome.status = NOT_APPLICABLE if not active else PASS
        outcome.detail = "Fewer than two documents to compare."
        return outcome

    groups: dict[str, list[Document]] = {}
    for document in active:
        groups.setdefault(document.sha256, []).append(document)
    outcome.subjects_checked = len(groups)
    for digest, documents in sorted(groups.items()):
        if len(documents) < 2:
            continue
        original, *copies = sorted(documents, key=lambda item: (item.uploaded_at, item.original_filename))
        for copy in copies:
            outcome.findings.append(
                build(
                    "DUPLICATE_DOCUMENT",
                    f"duplicate_document:{digest}:{copy.original_filename}",
                    context={
                        "document_name": copy.original_filename,
                        "original_name": original.original_filename,
                        "sha256_short": digest[:12],
                        "sha256": digest,
                        "document_id": copy.id,
                        "original_document_id": original.id,
                    },
                    evidence=[
                        _evidence(
                            kind="document",
                            document=copy,
                            page=1,
                            bounding_box=[0.0, 0.0, 1.0, 1.0],
                            snippet=f"SHA-256 {digest[:24]}…",
                            method="sha256",
                            detail="the extra copy",
                        ),
                        _evidence(
                            kind="document",
                            document=original,
                            page=1,
                            bounding_box=[0.0, 0.0, 1.0, 1.0],
                            snippet=f"SHA-256 {digest[:24]}…",
                            method="sha256",
                            detail="the copy already in the claim",
                        ),
                    ],
                )
            )
    if outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} document(s) are byte-identical to another."
    else:
        outcome.detail = f"{len(active)} documents, all distinct."
    return outcome


def check_duplicate_pages(ctx: Context) -> CheckOutcome:
    """Pages that repeat: both the text and the picture have to match."""
    outcome = CheckOutcome(
        check_id="duplicate_pages",
        title="No page repeats another",
        category="duplicates",
        status=PASS,
        detail="",
        rule_ids=["R017"],
    )
    # Documents already reported as duplicates are left out: their pages repeat by definition.
    duplicate_ids = {
        finding.context["document_id"]
        for finding in check_duplicate_documents(ctx).findings
        if finding.rule.code == "DUPLICATE_DOCUMENT"
    }
    candidates: list[tuple[Document, DocumentPage]] = [
        (document, page)
        for document in ctx.active
        if document.id not in duplicate_ids
        for page in ctx.pages.get(document.id, [])
    ]
    if len(candidates) < 2:
        outcome.status = NOT_APPLICABLE
        outcome.detail = "Fewer than two pages to compare."
        return outcome

    fingerprints = {id(page): dup.page_dhash(page.image_path) for _, page in candidates}
    pairs = 0
    for (left_document, left_page), (right_document, right_page) in combinations(candidates, 2):
        pairs += 1
        matched, similarity, distance = dup.is_duplicate_page(
            left_page.text or "",
            right_page.text or "",
            fingerprints[id(left_page)],
            fingerprints[id(right_page)],
        )
        if not matched:
            continue
        first, second = sorted(
            [(left_document, left_page), (right_document, right_page)],
            key=lambda item: (item[0].uploaded_at, item[0].original_filename, item[1].page_number),
        )
        original_document, original_page = first
        copy_document, copy_page = second
        outcome.findings.append(
            build(
                "DUPLICATE_PAGE",
                f"duplicate_page:{original_document.sha256}:{original_page.page_number}"
                f":{copy_document.sha256}:{copy_page.page_number}",
                context={
                    "document_name": copy_document.original_filename,
                    "page": copy_page.page_number,
                    "original_name": original_document.original_filename,
                    "original_page": original_page.page_number,
                    "text_similarity": round(similarity * 100),
                    "dhash_distance": distance,
                },
                evidence=[
                    _evidence(
                        kind="page",
                        document=copy_document,
                        page=copy_page.page_number,
                        bounding_box=[0.0, 0.0, 1.0, 1.0],
                        snippet=(copy_page.text or "")[:200],
                        method="page_fingerprint",
                        detail="the repeated page",
                    ),
                    _evidence(
                        kind="page",
                        document=original_document,
                        page=original_page.page_number,
                        bounding_box=[0.0, 0.0, 1.0, 1.0],
                        snippet=(original_page.text or "")[:200],
                        method="page_fingerprint",
                        detail="the page it repeats",
                    ),
                ],
            )
        )
    outcome.subjects_checked = pairs
    if outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} repeated page(s) across {pairs} comparison(s)."
    else:
        outcome.detail = f"{pairs} page comparison(s), no repeats."
    return outcome


def check_page_quality(ctx: Context) -> CheckOutcome:
    """Phase 3 measured the pages; this turns the serious signals into findings."""
    outcome = CheckOutcome(
        check_id="page_quality",
        title="Pages are readable",
        category="quality",
        status=PASS,
        detail="",
        rule_ids=["R018"],
    )
    severities = set(settings().get("quality_finding_severities", ["review"]))
    own_rules = {"concealed_text", "signature_area_blank"}
    pages_checked = 0
    for document in ctx.active:
        pages_checked += document.page_count or 0
        by_page: dict[int, list[dict]] = {}
        for flag in document.quality_flags or []:
            if flag.get("severity") not in severities or flag.get("code") in own_rules:
                continue
            for page_number in flag.get("pages") or [None]:
                by_page.setdefault(page_number or 1, []).append(flag)
        for page_number, flags in sorted(by_page.items()):
            page = next(
                (item for item in ctx.pages.get(document.id, []) if item.page_number == page_number),
                None,
            )
            outcome.findings.append(
                build(
                    "LOW_QUALITY_PAGE",
                    f"quality:{document.sha256}:p{page_number}",
                    context={
                        "document_name": document.original_filename,
                        "page": page_number,
                        "signals": "; ".join(flag["detail"] for flag in flags),
                        "codes": sorted({flag["code"] for flag in flags}),
                    },
                    evidence=[
                        _evidence(
                            kind="page",
                            document=document,
                            page=page_number,
                            bounding_box=[0.0, 0.0, 1.0, 1.0],
                            snippet=(page.text or "")[:200] if page else None,
                            method="page_quality",
                            detail="; ".join(sorted({flag["code"] for flag in flags})),
                        )
                    ],
                )
            )
    outcome.subjects_checked = pages_checked
    if not ctx.active:
        outcome.status = PENDING
        outcome.detail = "No processed pages yet."
    elif outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} page(s) may be hard to read."
    else:
        outcome.detail = f"{pages_checked} page(s) are readable."
    return outcome


def check_signatures(ctx: Context) -> CheckOutcome:
    outcome = CheckOutcome(
        check_id="signatures",
        title="Expected signatures are present",
        category="integrity",
        status=PASS,
        detail="",
        rule_ids=["R014"],
    )
    slots_checked = 0
    for document in ctx.active:
        signatures = document.signature_slots or {}
        for slot in signatures.get("slots", []):
            if not slot.get("required") or not slot.get("checked"):
                continue
            slots_checked += 1
            if slot.get("signed"):
                continue
            outcome.findings.append(
                build(
                    "SIGNATURE_NOT_DETECTED",
                    f"signature:{document.sha256}:{slot.get('key') or slot.get('caption')}",
                    context={
                        "slot_label": slot.get("label") or "Signature",
                        "slot_lower": (slot.get("label") or "signature").lower(),
                        "document_name": document.original_filename,
                        "page": slot.get("page_number") or 1,
                    },
                    evidence=[
                        _evidence(
                            kind="signature",
                            document=document,
                            page=slot.get("page_number") or 1,
                            bounding_box=slot.get("bbox"),
                            snippet=slot.get("caption"),
                            method=slot.get("method") or "signature_area",
                            detail=slot.get("detail"),
                        )
                    ],
                )
            )
    outcome.subjects_checked = slots_checked
    if not slots_checked:
        outcome.status = PENDING if not ctx.active else NOT_APPLICABLE
        outcome.detail = "No document in this claim declares a required signature area."
    elif outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} of {slots_checked} required signature area(s) are blank."
    else:
        outcome.detail = f"All {slots_checked} required signature area(s) are signed."
    return outcome


def check_concealed_text(ctx: Context) -> CheckOutcome:
    """Text covered by opaque paint: reported for human verification, never called forgery."""
    outcome = CheckOutcome(
        check_id="concealed_text",
        title="No document hides text behind opaque paint",
        category="integrity",
        status=PASS,
        detail="",
        rule_ids=["R002"],
    )
    for document in ctx.active:
        spans = document.concealed_spans or []
        if not spans:
            continue
        by_page: dict[int, list[dict]] = {}
        for span in spans:
            by_page.setdefault(span.get("page_number") or 1, []).append(span)
        for page_number, page_spans in sorted(by_page.items()):
            outcome.findings.append(
                build(
                    "POTENTIAL_ALTERATION",
                    f"concealed:{document.sha256}:p{page_number}",
                    context={
                        "document_name": document.original_filename,
                        "page": page_number,
                        "count": len(page_spans),
                        "covered": ", ".join(f"{span['text']!r}" for span in page_spans),
                    },
                    evidence=[
                        _evidence(
                            kind="concealed_text",
                            document=document,
                            page=page_number,
                            bounding_box=span.get("bbox"),
                            snippet=span.get("text"),
                            method="concealed_text",
                            value=span.get("text"),
                            detail=f"covered value, {round((span.get('coverage') or 0) * 100)}% hidden",
                        )
                        for span in page_spans
                    ],
                )
            )
    outcome.subjects_checked = len(ctx.active)
    if not ctx.active:
        outcome.status = PENDING
        outcome.detail = "No processed documents yet."
    elif outcome.findings:
        outcome.status = FAIL
        outcome.detail = f"{len(outcome.findings)} page(s) carry covered text."
    else:
        outcome.detail = f"No covered text in {len(ctx.active)} document(s)."
    return outcome


def check_implant_corroboration(ctx: Context) -> CheckOutcome:
    """A billed implant should be recorded by an operative document."""
    outcome = CheckOutcome(
        check_id="implant_corroboration",
        title="Billed implants are recorded in an operative document",
        category="clinical",
        status=PASS,
        detail="",
        rule_ids=["R015"],
    )
    config = settings()
    bill_types = set(config.get("implant_bill_types", ["implant_invoice"]))
    corroborating_types = set(config.get("implant_corroboration_doc_types", ["operative_note"]))
    implant_bills = [bill for bill in ctx.state["bills"]["items"] if bill["bill_type"] in bill_types]
    if not implant_bills:
        outcome.status = NOT_APPLICABLE
        outcome.detail = "No implant invoice in this claim."
        return outcome

    corroborating = [document for document in ctx.active if document.doc_type in corroborating_types]
    haystack = " ".join(nz.squash(ctx.page_text(document)) for document in corroborating)
    lines = 0
    for bill in implant_bills:
        document = ctx.document(bill["document_id"])
        for line in bill["line_items"]:
            lines += 1
            tokens = _implant_tokens(line)
            if not tokens:
                continue
            found = [token for token in tokens if token in haystack]
            if found:
                continue
            quantity = line.get("quantity") or "—"
            rate = _decimal(line.get("rate"))
            amount = _decimal(line.get("amount"))
            outcome.findings.append(
                build(
                    "IMPLANT_USAGE_NOT_CORROBORATED",
                    f"implant:{tokens[0]}",
                    context={
                        "document_name": document.original_filename if document else bill["document_name"],
                        "description": line.get("description"),
                        "quantity": quantity,
                        "rate": _money(rate),
                        "amount": _money(amount),
                        "tokens": tokens,
                    },
                    evidence=[
                        _evidence(
                            kind="bill_line",
                            document=document,
                            page=line["evidence"].get("page"),
                            bounding_box=line["evidence"].get("bounding_box"),
                            snippet=line["evidence"].get("snippet"),
                            method="bill_table",
                            value=line.get("amount"),
                            detail="billed implant",
                        )
                    ],
                )
            )
    outcome.subjects_checked = lines
    if outcome.findings:
        outcome.status = FAIL
        outcome.detail = (
            f"{len(outcome.findings)} billed implant line(s) are not recorded in an operative document"
            + (f" ({len(corroborating)} operative document(s) searched)." if corroborating else " (none supplied).")
        )
    else:
        outcome.detail = f"{lines} billed implant line(s) are recorded in {len(corroborating)} operative document(s)."
    return outcome


def _implant_tokens(line: dict) -> list[str]:
    """What to look for in an operative document: the lot number, then the product name."""
    tokens: list[str] = []
    for candidate in (line.get("batch"), line.get("expiry")):
        squashed = nz.squash(candidate or "")
        if squashed and any(character.isdigit() for character in squashed) and len(squashed) >= 5:
            tokens.append(squashed)
    description = nz.squash(line.get("description") or "")
    words = [word for word in description.split() if len(word) >= 5]
    if words:
        tokens.append(words[0])
    return tokens


CHECKS = (
    check_required_documents,
    check_patient_name,
    check_uhid,
    check_name_variants,
    check_claim_form,
    check_admission_date,
    check_discharge_date,
    check_date_sequence,
    check_diagnosis,
    check_procedure,
    check_doctors,
    check_operative_documentation,
    check_bill_numbers,
    check_bill_arithmetic,
    check_duplicate_documents,
    check_duplicate_pages,
    check_page_quality,
    check_signatures,
    check_concealed_text,
    check_implant_corroboration,
)


def build_context(session: Session, claim: Claim, state: dict | None = None) -> Context:
    documents = list(
        session.scalars(
            select(Document)
            .where(Document.claim_id == claim.id)
            .order_by(Document.uploaded_at, Document.original_filename)
        ).all()
    )
    pages: dict[str, list[DocumentPage]] = {}
    for page in session.scalars(
        select(DocumentPage)
        .where(DocumentPage.claim_id == claim.id)
        .order_by(DocumentPage.document_id, DocumentPage.page_number)
    ).all():
        pages.setdefault(page.document_id, []).append(page)
    if state is None:
        state = json_ready(build_claim_state(session, claim))
    return Context(claim=claim, state=state, documents=documents, pages=pages)


# What validation itself writes back into the canonical claim. None of it may decide whether
# validation needs to run again, or every read would trigger another run.
DERIVED_SECTIONS = ("findings", "audit_events")
DERIVED_DOCUMENT_FIELDS = ("duplicate_state", "duplicate_of")


def input_fingerprint(state: dict) -> str:
    """Identity of the input a run was based on: the documents as they stand, nothing derived."""
    inputs = {key: value for key, value in state.items() if key not in DERIVED_SECTIONS}
    documents = inputs.get("documents")
    if documents:
        inputs["documents"] = {
            **documents,
            "items": [
                {key: value for key, value in item.items() if key not in DERIVED_DOCUMENT_FIELDS}
                for item in documents.get("items", [])
            ],
        }
    return content_hash({"rules_version": rules_version(), "state": inputs})


def run(session: Session, claim: Claim, state: dict | None = None) -> ValidationResult:
    """Run every check over one claim and collect the findings they raise."""
    ctx = build_context(session, claim, state)
    outcomes = [check(ctx) for check in CHECKS]
    findings = [finding for outcome in outcomes for finding in outcome.findings]

    seen: set[str] = set()
    for finding in findings:
        if finding.fingerprint in seen:  # pragma: no cover — a check bug, caught by the tests
            raise ValueError(f"Two findings share a fingerprint: {finding.rule.code} {finding.subject}")
        seen.add(finding.fingerprint)

    document_updates = _duplicate_annotations(outcomes, ctx)
    checks = [outcome.payload() for outcome in outcomes]
    summary = {
        "checks": {
            "total": len(checks),
            **{status: sum(1 for check in checks if check["status"] == status) for status in (PASS, FAIL, PENDING, NOT_APPLICABLE)},
        },
        "findings_raised": len(findings),
        "by_severity": {
            severity: sum(1 for finding in findings if finding.rule.severity == severity)
            for severity in ("critical", "review", "warning", "info")
        },
        "by_category": {
            category: sum(1 for finding in findings if finding.rule.category == category)
            for category in sorted({finding.rule.category for finding in findings})
        },
    }
    return ValidationResult(
        checks=checks,
        findings=findings,
        document_updates=document_updates,
        input_fingerprint=input_fingerprint(ctx.state),
        rules_version=rules_version(),
        summary=summary,
    )


def _duplicate_annotations(outcomes: list[CheckOutcome], ctx: Context) -> dict[str, dict]:
    """What the duplicate check learned about each document, for the inventory."""
    updates = {
        document.id: {"duplicate_state": "unique", "duplicate_of": None}
        for document in ctx.documents
        if document.processing_status == "processed"
    }
    for outcome in outcomes:
        if outcome.check_id != "duplicate_documents":
            continue
        for finding in outcome.findings:
            copy_id = finding.context["document_id"]
            original_id = finding.context["original_document_id"]
            updates[copy_id] = {"duplicate_state": "duplicate", "duplicate_of": original_id}
            if original_id in updates and updates[original_id]["duplicate_state"] != "duplicate":
                updates[original_id] = {"duplicate_state": "has_duplicate", "duplicate_of": None}
    return updates

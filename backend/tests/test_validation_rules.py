"""The rules themselves: what each check raises, and the wording it is allowed to use."""

import json
from datetime import UTC, datetime

import pytest

from app.canonical.selection import normalise
from app.models import Document, DocumentPage
from app.validation import engine
from app.validation.rules import FORBIDDEN_WORDS, Finding, Rule, build, fingerprint, rule_for, rules

# --- helpers: a canonical claim shaped exactly as the builder produces it ------------------


def source(document: str, *, page: int = 1, value: str = "x", weight: int = 1, document_type: str | None = None) -> dict:
    return {
        "document_id": f"doc-{document}",
        "document_name": document,
        "document_type": document_type,
        "document_type_label": document_type,
        "page": page,
        "bounding_box": [0.1, 0.2, 0.4, 0.22],
        "snippet": f"{value} on {document}",
        "method": "pdf_text:label_value",
        "source_type": "pdf_text",
        "confidence": 0.95,
        "weight": weight,
        "eligible": True,
        "excluded_reason": None,
        "value": value,
        "raw_value": value,
        "field_key": "field",
        "derived_from": None,
        "evidence_available": True,
    }


def value(
    label: str,
    key: str,
    text: str | None,
    *,
    sources: list[dict] | None = None,
    competing: list[dict] | None = None,
    variants: list[dict] | None = None,
    kind: str = "text",
) -> dict:
    sources = sources if sources is not None else ([source("a.pdf", value=text)] if text else [])
    return {
        "key": key,
        "label": label,
        "kind": kind,
        "section": key.split(".")[0],
        "present": text is not None,
        "value": text,
        "normalized_value": normalise(kind, text) if text else None,
        "confidence": 0.95 if text else None,
        "weight": sum(item["weight"] for item in sources),
        "source_count": len(sources),
        "value_variants": variants or ([{"value": text, "source_count": len(sources)}] if text else []),
        "sources": sources,
        "evidence_available": bool(sources),
        "competing_values": competing or [],
        "has_competing_values": bool(competing),
        "note": None,
    }


def group(text: str, sources: list[dict], kind: str = "text") -> dict:
    return {
        "value": text,
        "normalized_value": normalise(kind, text) or text.lower(),
        "weight": sum(item["weight"] for item in sources),
        "source_count": len(sources),
        "eligible_source_count": len(sources),
        "value_variants": [{"value": text, "source_count": len(sources)}],
        "sources": sources,
    }


def document(
    name: str,
    *,
    doc_type: str = "consultation",
    sha256: str | None = None,
    pages: int = 1,
    quality_flags: list | None = None,
    signature_slots: dict | None = None,
    concealed_spans: list | None = None,
    excluded: bool = False,
    uploaded: int = 1,
) -> Document:
    return Document(
        id=f"doc-{name}",
        claim_id="claim-1",
        original_filename=name,
        content_type="application/pdf",
        size_bytes=1000,
        sha256=sha256 or name.ljust(64, "0"),
        storage_path=f"claims/claim-1/originals/{name}",
        page_count=pages,
        processing_status="processed",
        doc_type=doc_type,
        text_source="pdf_text",
        excluded=excluded,
        quality_flags=quality_flags or [],
        signature_slots=signature_slots or {},
        concealed_spans=concealed_spans or [],
        source="upload",
        uploaded_by="Demo Operator",
        uploaded_at=datetime(2026, 1, 20, 10, uploaded, tzinfo=UTC),
    )


def state(**overrides) -> dict:
    base = {
        "claim": {
            "claim_id": "claim-1",
            "claim_number": "CLM-2026-00123",
            "status": "processed",
            "form": {
                "patient_name": "Rajesh Sharma",
                "uhid": "UHID-123456",
                "admission_date": "2026-01-12",
                "discharge_date": "2026-01-16",
            },
        },
        "patient": {"fields": {"name": value("Patient name", "patient.name", None), "uhid": value("UHID", "patient.uhid", None)}},
        "admission": {
            "fields": {
                "admission_date": value("Admission date", "admission.admission_date", None, kind="date"),
                "discharge_date": value("Discharge date", "admission.discharge_date", None, kind="date"),
                "surgery_date": value("Surgery date", "admission.surgery_date", None, kind="date"),
            }
        },
        "diagnosis": {"fields": {"primary": value("Diagnosis", "diagnosis.primary", None)}},
        "doctors": {
            "fields": {
                "surgeon": value("Surgeon", "doctors.surgeon", None),
                "anaesthetist": value("Anaesthetist", "doctors.anaesthetist", None),
            }
        },
        "procedures": {"selected_key": None, "selected": None, "items": [], "fields": {}},
        "bills": {"count": 0, "items": [], "summary": {"by_type": {}, "totals": []}},
        "documents": {"count": 0, "items": []},
    }
    for key, patch in overrides.items():
        if isinstance(patch, dict) and key in base and isinstance(base[key], dict):
            merged = {**base[key]}
            for inner_key, inner in patch.items():
                if inner_key == "fields":
                    merged["fields"] = {**merged.get("fields", {}), **inner}
                else:
                    merged[inner_key] = inner
            base[key] = merged
        else:
            base[key] = patch
    return base


def context(state_payload: dict, documents: list[Document] | None = None, pages: dict | None = None) -> engine.Context:
    documents = documents if documents is not None else []
    return engine.Context(claim=None, state=state_payload, documents=documents, pages=pages or {})


def bill(
    *,
    document_name: str = "12_Main_Hospital_Bill.pdf",
    bill_type: str = "hospital_bill",
    number: str = "CCH/IP/2026/08812",
    lines: list[dict] | None = None,
    subtotal: str | None = None,
    tax: str | None = None,
    discount: str | None = None,
    total: str | None = None,
) -> dict:
    def line(line_no: int, description: str, quantity: str, rate: str, amount: str) -> dict:
        return {
            "line_no": line_no,
            "description": description,
            "quantity": quantity,
            "rate": rate,
            "amount": amount,
            "batch": None,
            "expiry": None,
            "evidence": {
                "document_id": f"doc-{document_name}",
                "document_name": document_name,
                "page": 1,
                "bounding_box": [0.1, 0.3, 0.9, 0.32],
                "snippet": f"{line_no} {description}",
                "method": "bill_table",
                "source_type": "pdf_text",
                "confidence": None,
                "evidence_available": True,
            },
        }

    items = lines if lines is not None else [line(1, "Room Rent", "4", "4500.00", "18000.00")]
    return {
        "document_id": f"doc-{document_name}",
        "document_name": document_name,
        "bill_type": bill_type,
        "bill_type_label": bill_type.replace("_", " ").title(),
        "currency": "INR",
        "page_number": 1,
        "columns": ["serial", "description", "quantity", "rate", "amount"],
        "notes": [],
        "line_item_count": len(items),
        "line_items": items,
        "fields": {
            "number": value("Bill number", "billing.bill_number", number, kind="id"),
            "date": value("Bill date", "billing.bill_date", "2026-01-16", kind="date"),
            "payer": value("Payer", "billing.payer", None),
            "subtotal": value("Subtotal", "billing.subtotal", subtotal, kind="amount"),
            "tax": value("Tax", "billing.tax", tax, kind="amount"),
            "discount": value("Discount", "billing.discount", discount, kind="amount"),
            "total": value("Total", "billing.total", total, kind="amount"),
            "amount_in_words": value("Amount in words", "billing.amount_in_words", None),
        },
    }


def bill_line(line_no: int, description: str, quantity: str | None, rate: str | None, amount: str, **extra) -> dict:
    return {
        "line_no": line_no,
        "description": description,
        "quantity": quantity,
        "rate": rate,
        "amount": amount,
        "batch": extra.get("batch"),
        "expiry": extra.get("expiry"),
        "evidence": {
            "document_id": extra.get("document_id", "doc-bill"),
            "document_name": extra.get("document_name", "bill.pdf"),
            "page": 1,
            "bounding_box": [0.1, 0.3, 0.9, 0.32],
            "snippet": f"{line_no} {description}",
            "method": "bill_table",
            "source_type": "pdf_text",
            "confidence": None,
            "evidence_available": True,
        },
    }


def codes(outcome: engine.CheckOutcome) -> list[str]:
    return [finding.rule.code for finding in outcome.findings]


# --- the rule catalogue --------------------------------------------------------------------

EXPECTED_SEVERITIES = {
    "MISSING_REQUIRED_DOCUMENT": "critical",
    "POTENTIAL_ALTERATION": "critical",
    "PATIENT_NAME_MISMATCH": "review",
    "UHID_MISMATCH": "review",
    "CLAIM_FORM_MISMATCH": "review",
    "ADMISSION_DATE_MISMATCH": "review",
    "DISCHARGE_DATE_MISMATCH": "review",
    "DATE_SEQUENCE_INVALID": "review",
    "DIAGNOSIS_INCONSISTENT": "review",
    "PROCEDURE_INCONSISTENT": "review",
    "DOCTOR_MISMATCH": "review",
    "DUPLICATE_BILL_NUMBER": "review",
    "BILL_ARITHMETIC_MISMATCH": "review",
    "SIGNATURE_NOT_DETECTED": "review",
    "IMPLANT_USAGE_NOT_CORROBORATED": "review",
    "DUPLICATE_DOCUMENT": "warning",
    "DUPLICATE_PAGE": "warning",
    "LOW_QUALITY_PAGE": "warning",
    "NAME_VARIANT": "info",
}


def test_every_expected_rule_exists_with_its_severity():
    catalogue = rules()
    assert set(catalogue) == set(EXPECTED_SEVERITIES)
    for code, severity in EXPECTED_SEVERITIES.items():
        rule = catalogue[code]
        assert rule.severity == severity, code
        assert rule.rule_id.startswith("R")
        assert rule.category
        assert rule.title and rule.explanation and rule.action
        assert rule.evidence in ("required", "optional", "none")
        assert rule.attribution in ("rule", "source")


def test_rule_ids_are_unique_and_stable():
    ids = [rule.rule_id for rule in rules().values()]
    assert len(ids) == len(set(ids))
    assert rule_for("MISSING_REQUIRED_DOCUMENT").rule_id == "R001"
    assert rule_for("NAME_VARIANT").rule_id == "R019"


def test_no_rule_uses_accusatory_wording():
    for rule in rules().values():
        text = f"{rule.title} {rule.explanation} {rule.action}".lower()
        for word in FORBIDDEN_WORDS:
            assert word not in text, f"{rule.rule_id} uses {word!r}"


def test_a_rule_that_used_accusatory_wording_would_be_rejected():
    bad = Rule("R999", "X", "identity", "review", "rule", "A forged bill", "e", "a", "none")
    with pytest.raises(ValueError, match="forbidden wording"):
        Finding(rule=bad, subject="s")


def test_quoting_a_document_that_contains_such_a_word_is_allowed():
    """The guard is about how the product speaks, not about what a document says."""
    finding = build(
        "PATIENT_NAME_MISMATCH",
        "patient.name:fake name",
        context={
            "canonical": "Rajesh Sharma",
            "canonical_sources": 3,
            "other": "Fake Name",
            "documents": "bill.pdf",
            "source_count": 1,
        },
        evidence=[source("bill.pdf")],
    )
    assert "Fake Name" in finding.explanation


def test_fingerprints_are_the_rule_and_the_subject():
    first = fingerprint("R001", "requirement:operative_note")
    assert first == fingerprint("R001", "requirement:operative_note")
    assert first != fingerprint("R001", "requirement:anaesthesia_record")
    assert first != fingerprint("R002", "requirement:operative_note")
    assert len(first) == 40


def test_a_rule_that_requires_evidence_cannot_be_raised_without_it():
    with pytest.raises(ValueError, match="requires evidence"):
        build("PATIENT_NAME_MISMATCH", "x", context={
            "canonical": "A", "canonical_sources": 1, "other": "B", "documents": "d", "source_count": 1
        })


def test_a_rule_that_must_not_carry_evidence_rejects_it():
    with pytest.raises(ValueError, match="must not carry evidence"):
        build(
            "MISSING_REQUIRED_DOCUMENT",
            "requirement:x",
            context={"label": "X", "label_lower": "x", "requirement": "x", "doc_types": []},
            evidence=[source("a.pdf")],
        )


def test_a_missing_context_value_is_a_loud_error():
    with pytest.raises(KeyError, match="needs"):
        build("PATIENT_NAME_MISMATCH", "x", context={"canonical": "A"}, evidence=[source("a.pdf")])


# --- completeness --------------------------------------------------------------------------


def test_missing_required_documents_are_reported_without_inventing_evidence():
    outcome = engine.check_required_documents(
        context(state(), [document("02_Admission_Form.pdf", doc_type="admission_record")])
    )
    assert outcome.status == engine.FAIL
    assert set(codes(outcome)) == {"MISSING_REQUIRED_DOCUMENT"}
    subjects = {finding.subject for finding in outcome.findings}
    assert "requirement:operative_note" in subjects
    assert "requirement:anaesthesia_record" in subjects
    for finding in outcome.findings:
        assert finding.evidence == [], "a missing document has no page to point at"
        assert finding.context["requirement"]
        assert finding.context["doc_types"]


def test_required_documents_pass_when_every_type_is_present():
    documents = [
        document("a.pdf", doc_type="admission_record"),
        document("b.pdf", doc_type="consent"),
        document("c.pdf", doc_type="operative_note"),
        document("d.pdf", doc_type="anaesthesia_record"),
        document("e.pdf", doc_type="discharge_summary"),
        document("f.pdf", doc_type="hospital_bill"),
    ]
    outcome = engine.check_required_documents(context(state(), documents))
    assert outcome.status == engine.PASS
    assert outcome.findings == []


def test_required_documents_wait_until_something_is_processed():
    outcome = engine.check_required_documents(context(state(), []))
    assert outcome.status == engine.PENDING
    assert outcome.findings == []


# --- identity -----------------------------------------------------------------------------


def test_a_different_patient_name_is_a_review_finding():
    payload = state(
        patient={
            "fields": {
                "name": value(
                    "Patient name",
                    "patient.name",
                    "Rajesh Sharma",
                    sources=[source("02_Admission_Form.pdf", value="Rajesh Sharma", weight=3)],
                    competing=[group("Rajesh K", [source("13_Pharmacy_Bill.pdf", value="Rajesh K")], "name")],
                )
            }
        }
    )
    outcome = engine.check_patient_name(context(payload))
    assert outcome.status == engine.FAIL
    finding = outcome.findings[0]
    assert finding.rule.code == "PATIENT_NAME_MISMATCH"
    assert finding.rule.severity == "review"
    assert finding.subject == "patient.name:rajesh k"
    assert "Rajesh K" in finding.explanation
    assert "13_Pharmacy_Bill.pdf" in finding.explanation
    assert finding.evidence[0]["document_name"] == "13_Pharmacy_Bill.pdf"
    assert finding.evidence[0]["page"] == 1
    assert finding.evidence[0]["bounding_box"]


def test_the_same_name_spelled_differently_is_only_a_note():
    payload = state(
        patient={
            "fields": {
                "name": value(
                    "Patient name",
                    "patient.name",
                    "Rajesh Sharma",
                    sources=[
                        source("02_Admission_Form.pdf", value="Rajesh Sharma", weight=3),
                        source("01_Patient_ID.png", value="RAJESH SHARMA", weight=3),
                    ],
                    variants=[
                        {"value": "Rajesh Sharma", "source_count": 1},
                        {"value": "RAJESH SHARMA", "source_count": 1},
                    ],
                )
            }
        }
    )
    ctx = context(payload)
    assert engine.check_patient_name(ctx).status == engine.PASS
    variants = engine.check_name_variants(ctx)
    assert codes(variants) == ["NAME_VARIANT"]
    assert variants.findings[0].rule.severity == "info"
    assert variants.findings[0].subject == "patient.name:variant:RAJESH SHARMA"
    assert "spelling variation" in variants.findings[0].action.lower() or "no action" in variants.findings[0].action.lower()


def test_a_different_uhid_is_a_review_finding():
    payload = state(
        patient={
            "fields": {
                "uhid": value(
                    "UHID",
                    "patient.uhid",
                    "UHID-123456",
                    kind="id",
                    sources=[source("02_Admission_Form.pdf", value="UHID-123456", weight=3)],
                    competing=[group("UHID-654321", [source("10_Lab_Report.pdf", value="UHID-654321")], "id")],
                )
            }
        }
    )
    outcome = engine.check_uhid(context(payload))
    assert codes(outcome) == ["UHID_MISMATCH"]
    assert outcome.findings[0].subject == "patient.uhid:uhid654321"


def test_claim_form_values_are_compared_with_the_documents():
    payload = state(
        claim={
            "form": {
                "patient_name": "Rajesh Kumar",
                "uhid": "uhid 123456",
                "admission_date": "2026-01-12",
                "discharge_date": "2026-01-16",
            }
        },
        patient={
            "fields": {
                "name": value("Patient name", "patient.name", "Rajesh Sharma", kind="name"),
                "uhid": value("UHID", "patient.uhid", "UHID-123456", kind="id"),
            }
        },
        admission={
            "fields": {
                "admission_date": value("Admission date", "admission.admission_date", "2026-01-12", kind="date"),
                "discharge_date": value("Discharge date", "admission.discharge_date", "2026-01-16", kind="date"),
            }
        },
    )
    outcome = engine.check_claim_form(context(payload))
    assert outcome.status == engine.FAIL
    assert codes(outcome) == ["CLAIM_FORM_MISMATCH"], "the UHID matches once punctuation is ignored"
    finding = outcome.findings[0]
    assert finding.subject == "claim_form:patient_name"
    assert "Rajesh Kumar" in finding.explanation and "Rajesh Sharma" in finding.explanation


def test_claim_form_check_waits_until_the_documents_carry_the_values():
    outcome = engine.check_claim_form(context(state()))
    assert outcome.status == engine.PENDING
    assert outcome.findings == []


# --- dates --------------------------------------------------------------------------------


def test_a_different_admission_date_is_reported():
    payload = state(
        admission={
            "fields": {
                "admission_date": value(
                    "Admission date",
                    "admission.admission_date",
                    "2026-01-12",
                    kind="date",
                    sources=[source("02_Admission_Form.pdf", value="12-01-2026", weight=3)],
                    competing=[group("2026-01-13", [source("08_Nursing_Record.pdf", value="13-01-2026")], "date")],
                )
            }
        }
    )
    outcome = engine.check_admission_date(context(payload))
    assert codes(outcome) == ["ADMISSION_DATE_MISMATCH"]
    assert outcome.findings[0].subject == "admission.admission_date:2026-01-13"


def test_a_different_discharge_date_is_reported():
    payload = state(
        admission={
            "fields": {
                "discharge_date": value(
                    "Discharge date",
                    "admission.discharge_date",
                    "2026-01-16",
                    kind="date",
                    competing=[group("2026-01-17", [source("12_Main_Hospital_Bill.pdf", value="17-01-2026")], "date")],
                )
            }
        }
    )
    assert codes(engine.check_discharge_date(context(payload))) == ["DISCHARGE_DATE_MISMATCH"]


def test_the_same_day_written_differently_is_not_a_mismatch():
    """Dates are compared as calendar dates, so 12-01-2026 and 2026-01-12 agree."""
    payload = state(
        admission={
            "fields": {
                "admission_date": value(
                    "Admission date",
                    "admission.admission_date",
                    "2026-01-12",
                    kind="date",
                    sources=[
                        source("02_Admission_Form.pdf", value="12-01-2026"),
                        source("08_Nursing_Record.pdf", value="2026-01-12"),
                    ],
                )
            }
        }
    )
    assert engine.check_admission_date(context(payload)).status == engine.PASS


def test_an_impossible_date_sequence_is_reported():
    payload = state(
        admission={
            "fields": {
                "admission_date": value("Admission date", "admission.admission_date", "2026-01-12", kind="date"),
                "discharge_date": value("Discharge date", "admission.discharge_date", "2026-01-10", kind="date"),
                "surgery_date": value("Surgery date", "admission.surgery_date", "2026-01-11", kind="date"),
            }
        }
    )
    outcome = engine.check_date_sequence(context(payload))
    assert outcome.status == engine.FAIL
    subjects = {finding.subject for finding in outcome.findings}
    assert "sequence:discharge_before_admission" in subjects
    assert "sequence:surgery_before_admission" in subjects
    assert all(finding.rule.code == "DATE_SEQUENCE_INVALID" for finding in outcome.findings)
    assert "before the admission date" in outcome.findings[0].title


def test_surgery_after_discharge_is_reported():
    payload = state(
        admission={
            "fields": {
                "admission_date": value("Admission date", "admission.admission_date", "2026-01-12", kind="date"),
                "discharge_date": value("Discharge date", "admission.discharge_date", "2026-01-16", kind="date"),
                "surgery_date": value("Surgery date", "admission.surgery_date", "2026-01-18", kind="date"),
            }
        }
    )
    outcome = engine.check_date_sequence(context(payload))
    assert [finding.subject for finding in outcome.findings] == ["sequence:surgery_after_discharge"]


def test_dates_in_order_pass_and_missing_dates_wait():
    ordered = state(
        admission={
            "fields": {
                "admission_date": value("Admission date", "admission.admission_date", "2026-01-12", kind="date"),
                "discharge_date": value("Discharge date", "admission.discharge_date", "2026-01-16", kind="date"),
                "surgery_date": value("Surgery date", "admission.surgery_date", "2026-01-13", kind="date"),
            }
        }
    )
    assert engine.check_date_sequence(context(ordered)).status == engine.PASS
    assert engine.check_date_sequence(context(state())).status == engine.PENDING


# --- clinical -----------------------------------------------------------------------------


def test_a_different_diagnosis_is_reported():
    payload = state(
        diagnosis={
            "fields": {
                "primary": value(
                    "Diagnosis",
                    "diagnosis.primary",
                    "Acute cholecystitis",
                    sources=[source("06_Discharge_Summary.pdf", value="Acute cholecystitis", weight=3)],
                    competing=[group("Acute appendicitis", [source("03_Doctor_Consultation.pdf", value="Acute appendicitis")])],
                )
            }
        }
    )
    outcome = engine.check_diagnosis(context(payload))
    assert codes(outcome) == ["DIAGNOSIS_INCONSISTENT"]
    assert "Acute appendicitis" in outcome.findings[0].explanation


def test_two_different_procedures_are_reported():
    payload = state(
        procedures={
            "items": [
                {
                    "procedure_key": "laparoscopic_cholecystectomy",
                    "label": "Laparoscopic cholecystectomy",
                    "value": "Laparoscopic Cholecystectomy",
                    "normalized_value": "laparoscopic_cholecystectomy",
                    "weight": 9,
                    "source_count": 5,
                    "value_variants": [],
                    "sources": [source("06_Discharge_Summary.pdf", weight=3)],
                    "is_selected": True,
                },
                {
                    "procedure_key": "appendicectomy",
                    "label": "Appendicectomy",
                    "value": "Appendicectomy",
                    "normalized_value": "appendicectomy",
                    "weight": 1,
                    "source_count": 1,
                    "value_variants": [],
                    "sources": [source("14_OT_Bill.pdf")],
                    "is_selected": False,
                },
            ]
        }
    )
    outcome = engine.check_procedure(context(payload))
    assert codes(outcome) == ["PROCEDURE_INCONSISTENT"]
    assert outcome.findings[0].subject == "procedure:appendicectomy"
    assert "Appendicectomy" in outcome.findings[0].explanation


def test_one_procedure_named_by_many_documents_passes():
    payload = state(
        procedures={
            "items": [
                {
                    "procedure_key": "laparoscopic_cholecystectomy",
                    "label": "Laparoscopic cholecystectomy",
                    "value": "Laparoscopic Cholecystectomy",
                    "normalized_value": "laparoscopic_cholecystectomy",
                    "weight": 9,
                    "source_count": 7,
                    "value_variants": [{"value": "Lap Chole", "source_count": 2}],
                    "sources": [source("06_Discharge_Summary.pdf", weight=3)],
                    "is_selected": True,
                }
            ]
        }
    )
    assert engine.check_procedure(context(payload)).status == engine.PASS


def test_a_different_surgeon_or_anaesthetist_is_reported():
    payload = state(
        doctors={
            "fields": {
                "surgeon": value(
                    "Surgeon",
                    "doctors.surgeon",
                    "Dr. Anil Mehta",
                    sources=[source("06_Discharge_Summary.pdf", value="Dr. Anil Mehta", weight=3)],
                    competing=[group("Dr. Suresh Rao", [source("14_OT_Bill.pdf", value="Dr. Suresh Rao")], "person")],
                ),
                "anaesthetist": value("Anaesthetist", "doctors.anaesthetist", "Dr. Priya Nair"),
            }
        }
    )
    outcome = engine.check_doctors(context(payload))
    assert codes(outcome) == ["DOCTOR_MISMATCH"]
    finding = outcome.findings[0]
    assert finding.subject == "doctors.surgeon:suresh rao", "names are compared without honorifics"
    assert "Surgeon" in finding.title


def test_operative_documentation_waits_for_the_operative_note():
    outcome = engine.check_operative_documentation(context(state(), [document("06_Discharge_Summary.pdf", doc_type="discharge_summary")]))
    assert outcome.status == engine.PENDING
    assert "cannot run yet" in outcome.detail
    assert outcome.findings == []


def test_operative_documentation_runs_once_the_note_exists():
    note = document("scan_0042.pdf", doc_type="operative_note")
    payload = state(
        procedures={
            "selected": value(
                "Procedure",
                "procedures.procedure",
                "Laparoscopic Cholecystectomy",
                sources=[{**source("scan_0042.pdf"), "document_id": note.id}],
            ),
            "items": [],
        },
        doctors={
            "fields": {
                "surgeon": value(
                    "Surgeon",
                    "doctors.surgeon",
                    "Dr. Anil Mehta",
                    sources=[{**source("scan_0042.pdf"), "document_id": note.id}],
                )
            }
        },
    )
    outcome = engine.check_operative_documentation(context(payload, [note]))
    assert outcome.status == engine.PASS
    assert "corroborated" in outcome.detail


# --- billing ------------------------------------------------------------------------------


def test_two_bills_sharing_a_number_are_reported():
    payload = state(
        bills={
            "count": 2,
            "items": [
                bill(document_name="12_Main_Hospital_Bill.pdf", bill_type="hospital_bill", total="114360.00"),
                bill(document_name="14_OT_Bill.pdf", bill_type="ot_bill", total="18000.00"),
            ],
        }
    )
    outcome = engine.check_bill_numbers(context(payload))
    assert codes(outcome) == ["DUPLICATE_BILL_NUMBER"]
    finding = outcome.findings[0]
    assert finding.subject == "bill_number:cchip202608812"
    assert "12_Main_Hospital_Bill.pdf" in finding.explanation and "14_OT_Bill.pdf" in finding.explanation
    assert len(finding.evidence) == 2


def test_distinct_bill_numbers_pass():
    payload = state(
        bills={
            "count": 2,
            "items": [
                bill(document_name="12_Main_Hospital_Bill.pdf", number="CCH/IP/2026/08812"),
                bill(document_name="13_Pharmacy_Bill.pdf", bill_type="pharmacy_bill", number="PH/2026/11873"),
            ],
        }
    )
    assert engine.check_bill_numbers(context(payload)).status == engine.PASS


def test_a_line_that_does_not_multiply_out_is_reported():
    documents = [document("12_Main_Hospital_Bill.pdf", doc_type="hospital_bill")]
    payload = state(
        bills={
            "count": 1,
            "items": [
                bill(
                    lines=[bill_line(1, "Room Rent", "4", "4500.00", "20000.00", document_name="12_Main_Hospital_Bill.pdf")],
                    subtotal="20000.00",
                    tax="0.00",
                    total="20000.00",
                )
            ],
        }
    )
    outcome = engine.check_bill_arithmetic(context(payload, documents))
    assert codes(outcome) == ["BILL_ARITHMETIC_MISMATCH"]
    finding = outcome.findings[0]
    assert "4 × 4,500.00" in finding.explanation
    assert "18,000.00" in finding.explanation and "20,000.00" in finding.explanation
    assert "2,000.00" in finding.explanation
    assert finding.evidence[0]["page"] == 1


def test_lines_that_do_not_add_up_to_the_subtotal_are_reported():
    documents = [document("bill.pdf", doc_type="hospital_bill")]
    payload = state(
        bills={
            "count": 1,
            "items": [
                bill(
                    document_name="bill.pdf",
                    lines=[
                        bill_line(1, "Room Rent", "4", "4500.00", "18000.00", document_name="bill.pdf"),
                        bill_line(2, "Nursing", "4", "1200.00", "4800.00", document_name="bill.pdf"),
                    ],
                    subtotal="20000.00",
                    tax="0.00",
                    total="20000.00",
                )
            ],
        }
    )
    outcome = engine.check_bill_arithmetic(context(payload, documents))
    subjects = {finding.subject.rsplit(":", 1)[-1] for finding in outcome.findings}
    assert "subtotal" in subjects
    assert any("22,800.00" in finding.explanation for finding in outcome.findings)


def test_a_total_that_does_not_follow_the_subtotal_and_tax_is_reported():
    documents = [document("bill.pdf", doc_type="hospital_bill")]
    payload = state(
        bills={
            "count": 1,
            "items": [
                bill(
                    document_name="bill.pdf",
                    lines=[bill_line(1, "Room Rent", "4", "4500.00", "18000.00", document_name="bill.pdf")],
                    subtotal="18000.00",
                    tax="900.00",
                    total="19500.00",
                )
            ],
        }
    )
    outcome = engine.check_bill_arithmetic(context(payload, documents))
    totals = [finding for finding in outcome.findings if finding.subject.endswith(":total")]
    assert len(totals) == 1
    assert "18,900.00" in totals[0].explanation and "19,500.00" in totals[0].explanation


def test_a_bill_that_adds_up_passes_and_an_unstated_tax_is_left_alone():
    documents = [document("bill.pdf", doc_type="pharmacy_bill")]
    consistent = state(
        bills={
            "count": 1,
            "items": [
                bill(
                    document_name="bill.pdf",
                    bill_type="pharmacy_bill",
                    lines=[bill_line(1, "Inj.", "6", "85.00", "510.00", document_name="bill.pdf")],
                    subtotal="510.00",
                    total="510.00",
                )
            ],
        }
    )
    assert engine.check_bill_arithmetic(context(consistent, documents)).status == engine.PASS

    # The bill states no tax and a higher total: an unstated tax could account for it, so the
    # check does not claim a mistake.
    unstated_tax = state(
        bills={
            "count": 1,
            "items": [
                bill(
                    document_name="bill.pdf",
                    bill_type="pharmacy_bill",
                    lines=[bill_line(1, "Inj.", "6", "85.00", "510.00", document_name="bill.pdf")],
                    subtotal="510.00",
                    total="560.00",
                )
            ],
        }
    )
    assert engine.check_bill_arithmetic(context(unstated_tax, documents)).findings == []


def test_bill_checks_do_not_apply_without_bills():
    assert engine.check_bill_arithmetic(context(state())).status == engine.NOT_APPLICABLE
    assert engine.check_bill_numbers(context(state())).status == engine.NOT_APPLICABLE


# --- duplicates ---------------------------------------------------------------------------


def test_byte_identical_documents_are_duplicates():
    original = document("10_Lab_Report.pdf", doc_type="lab_report", sha256="a" * 64, uploaded=1)
    copy = document("11_Lab_Report_copy.pdf", doc_type="lab_report", sha256="a" * 64, uploaded=2)
    other = document("06_Discharge_Summary.pdf", doc_type="discharge_summary", sha256="b" * 64, uploaded=3)
    outcome = engine.check_duplicate_documents(context(state(), [original, copy, other]))
    assert codes(outcome) == ["DUPLICATE_DOCUMENT"]
    finding = outcome.findings[0]
    assert finding.context["document_name"] == "11_Lab_Report_copy.pdf"
    assert finding.context["original_name"] == "10_Lab_Report.pdf"
    assert finding.subject == f"duplicate_document:{'a' * 64}:11_Lab_Report_copy.pdf"
    assert len(finding.evidence) == 2


def test_documents_with_different_bytes_are_not_duplicates():
    outcome = engine.check_duplicate_documents(
        context(
            state(),
            [document("a.pdf", sha256="a" * 64), document("b.pdf", sha256="b" * 64)],
        )
    )
    assert outcome.status == engine.PASS
    assert outcome.findings == []


def test_an_excluded_copy_is_no_longer_reported_as_a_duplicate():
    original = document("10_Lab_Report.pdf", sha256="a" * 64, uploaded=1)
    copy = document("11_Lab_Report_copy.pdf", sha256="a" * 64, uploaded=2, excluded=True)
    outcome = engine.check_duplicate_documents(context(state(), [original, copy]))
    assert outcome.findings == []


def test_pages_need_both_the_same_text_and_the_same_picture():
    from app.validation.duplicates import is_duplicate_page

    text = "Laboratory report haemoglobin 13.4 total count 14200 platelets 2.1 lakh" * 2
    other = "Nursing record vital signs chart pulse 82 blood pressure 124 over 80 temperature" * 2
    same_picture, different_picture = 0x0F0F0F0F0F0F0F0F, 0xF0F0F0F0F0F0F0F0

    matched, similarity, distance = is_duplicate_page(text, text, same_picture, same_picture)
    assert matched and similarity == 1.0 and distance == 0

    matched, _, _ = is_duplicate_page(text, text, same_picture, different_picture)
    assert not matched, "same text but a different picture is not a duplicate"

    matched, _, _ = is_duplicate_page(text, other, same_picture, same_picture)
    assert not matched, "same picture but different text is not a duplicate"

    matched, _, _ = is_duplicate_page("short", "short", same_picture, same_picture)
    assert not matched, "a nearly empty page proves nothing"

    matched, _, _ = is_duplicate_page(text, text, None, None)
    assert not matched, "without a picture fingerprint the check does not conclude"


def test_similar_clinical_pages_are_not_duplicates():
    """Two lab panels of the same patient read alike; that is not a duplicate page."""
    from app.validation.duplicates import text_similarity

    first = "Haemoglobin 13.4 g/dL Total leucocyte count 14,200 Platelets 2.1 lakh Sample LAB/2026/118204"
    second = "Haemoglobin 12.9 g/dL Total leucocyte count 9,800 Platelets 2.4 lakh Sample LAB/2026/118999"
    assert text_similarity(first, second) < 0.95


# --- quality, signatures, concealment -----------------------------------------------------


def test_a_review_quality_signal_becomes_a_finding():
    scan = document(
        "09_USG_Abdomen_Scan.jpg",
        doc_type="investigation_report",
        quality_flags=[
            {"code": "blurred_page", "severity": "review", "detail": "Character edges are soft.", "pages": [1]},
            {"code": "very_low_resolution", "severity": "review", "detail": "About 96 dpi.", "pages": [1]},
            {"code": "skewed_page", "severity": "attention", "detail": "Rotated 1.3°.", "pages": [1]},
        ],
    )
    outcome = engine.check_page_quality(context(state(), [scan]))
    assert codes(outcome) == ["LOW_QUALITY_PAGE"]
    finding = outcome.findings[0]
    assert "Character edges are soft." in finding.explanation
    assert "About 96 dpi." in finding.explanation
    assert "Rotated" not in finding.explanation, "only review-level signals become findings"
    assert finding.evidence[0]["page"] == 1


def test_quality_signals_that_have_their_own_rules_are_not_reported_twice():
    consent = document(
        "16_Consent_Form.pdf",
        doc_type="consent",
        quality_flags=[
            {"code": "signature_area_blank", "severity": "review", "detail": "blank", "pages": [1]},
            {"code": "concealed_text", "severity": "review", "detail": "covered", "pages": [1]},
        ],
    )
    assert engine.check_page_quality(context(state(), [consent])).findings == []


def test_a_blank_required_signature_area_is_reported():
    consent = document(
        "16_Consent_Form.pdf",
        doc_type="consent",
        signature_slots={
            "method": "vector_ink",
            "slots": [
                {
                    "key": "patient_guardian",
                    "label": "Patient / guardian",
                    "required": True,
                    "checked": True,
                    "signed": False,
                    "page_number": 1,
                    "bbox": [0.1, 0.5, 0.4, 0.55],
                    "caption": "Signature of Patient / Guardian",
                    "method": "vector_ink",
                },
                {"key": "witness", "label": "Witness", "required": True, "checked": True, "signed": True, "page_number": 1},
            ],
        },
    )
    outcome = engine.check_signatures(context(state(), [consent]))
    assert codes(outcome) == ["SIGNATURE_NOT_DETECTED"]
    finding = outcome.findings[0]
    assert finding.subject.endswith(":patient_guardian")
    assert "Patient / guardian" in finding.title
    assert finding.evidence[0]["bounding_box"] == [0.1, 0.5, 0.4, 0.55]
    assert outcome.subjects_checked == 2


def test_a_signature_that_could_not_be_checked_is_not_reported():
    scan = document(
        "09_USG_Abdomen_Scan.jpg",
        signature_slots={
            "method": "unavailable_scanned_page",
            "slots": [{"key": "reporting_doctor", "label": "Reporting doctor", "required": True, "checked": False, "signed": None}],
        },
    )
    outcome = engine.check_signatures(context(state(), [scan]))
    assert outcome.findings == []


def test_covered_text_is_reported_as_a_potential_alteration():
    invoice = document(
        "15_Implant_Invoice.pdf",
        doc_type="implant_invoice",
        concealed_spans=[{"page_number": 1, "text": "1,000.00", "coverage": 1.0, "bbox": [0.7, 0.27, 0.78, 0.28]}],
    )
    outcome = engine.check_concealed_text(context(state(), [invoice]))
    assert codes(outcome) == ["POTENTIAL_ALTERATION"]
    finding = outcome.findings[0]
    assert finding.rule.severity == "critical"
    assert finding.rule.attribution == "source"
    assert "1,000.00" in finding.explanation
    assert "human verification required" in finding.explanation.lower()
    assert finding.evidence[0]["bounding_box"] == [0.7, 0.27, 0.78, 0.28]
    for word in FORBIDDEN_WORDS:
        assert word not in json.dumps(finding.payload()).lower()


# --- implants -----------------------------------------------------------------------------


def implant_state(**extra) -> dict:
    return state(
        bills={
            "count": 1,
            "items": [
                bill(
                    document_name="15_Implant_Invoice.pdf",
                    bill_type="implant_invoice",
                    number="DS/INV/2026/0391",
                    lines=[
                        bill_line(
                            1,
                            "Hem-o-lok Polymer Ligating Clips (ML)",
                            "6",
                            "1100.00",
                            "6600.00",
                            batch="HL-44710",
                            document_name="15_Implant_Invoice.pdf",
                        )
                    ],
                    subtotal="6600.00",
                    total="6600.00",
                )
            ],
        },
        **extra,
    )


def test_a_billed_implant_without_an_operative_document_is_reported():
    invoice = document("15_Implant_Invoice.pdf", doc_type="implant_invoice")
    outcome = engine.check_implant_corroboration(context(implant_state(), [invoice]))
    assert codes(outcome) == ["IMPLANT_USAGE_NOT_CORROBORATED"]
    finding = outcome.findings[0]
    assert finding.rule.severity == "review"
    assert "6" in finding.explanation and "1,100.00" in finding.explanation and "6,600.00" in finding.explanation
    assert "not corroborated" in finding.title.lower() or "not corroborated" in finding.explanation.lower()
    assert finding.subject == "implant:hl 44710"


def test_an_operative_note_that_records_the_implant_satisfies_the_check():
    invoice = document("15_Implant_Invoice.pdf", doc_type="implant_invoice")
    note = document("scan_0042.pdf", doc_type="operative_note", pages=2)
    pages = {
        note.id: [
            DocumentPage(
                document_id=note.id,
                claim_id="claim-1",
                page_number=1,
                width=595.0,
                height=842.0,
                text="Implants used: 6 x Hem-o-lok polymer ligating clips (ML), lot HL-44710.",
            )
        ]
    }
    outcome = engine.check_implant_corroboration(context(implant_state(), [invoice, note], pages))
    assert outcome.status == engine.PASS
    assert outcome.findings == []
    assert "recorded in 1 operative document" in outcome.detail


def test_an_operative_note_about_something_else_does_not_corroborate():
    invoice = document("15_Implant_Invoice.pdf", doc_type="implant_invoice")
    note = document("scan_0042.pdf", doc_type="operative_note")
    pages = {
        note.id: [
            DocumentPage(
                document_id=note.id,
                claim_id="claim-1",
                page_number=1,
                width=595.0,
                height=842.0,
                text="Appendicectomy performed; no implants used.",
            )
        ]
    }
    outcome = engine.check_implant_corroboration(context(implant_state(), [invoice, note], pages))
    assert codes(outcome) == ["IMPLANT_USAGE_NOT_CORROBORATED"]


def test_implant_check_does_not_apply_without_an_implant_bill():
    outcome = engine.check_implant_corroboration(context(state()))
    assert outcome.status == engine.NOT_APPLICABLE
    assert outcome.findings == []

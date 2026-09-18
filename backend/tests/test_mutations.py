"""Mutation testing: change one thing in a clean claim and check exactly what happens.

For every mutation the suite verifies the same six things: the expected rule fires, nothing
unrelated fires, the severity and rule id are what the specification says, the fingerprints are
stable across a second run, the evidence points at the document that carries the change, and a
second validation run neither duplicates a finding nor inflates its occurrence count.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pytest

from tests import factory
from tests.ab_support import (
    ACCUSATORY_WORDS,
    EXPECTED_RULE_ID,
    EXPECTED_SEVERITY,
    clean_documents,
    clean_with_bills,
    collect,
    scenario,
)

BILL_LINES = factory.DEFAULT_BILL_LINES


def bill_with(**changes) -> bytes:
    return factory.hospital_bill(**changes)


def lines_with(index: int, **changes) -> tuple[factory.BillLine, ...]:
    lines = list(BILL_LINES)
    line = lines[index]
    lines[index] = factory.BillLine(
        description=changes.get("description", line.description),
        quantity=changes.get("quantity", line.quantity),
        rate=changes.get("rate", line.rate),
        amount=changes.get("amount", line.amount),
    )
    return tuple(lines)


def replace_doc(base: Callable[[], dict[str, bytes]], name: str, data: bytes) -> dict[str, bytes]:
    documents = base()
    documents[name] = data
    return documents


@dataclass(frozen=True)
class Mutation:
    """One deliberate change, and what the specification says must come of it."""

    id: str
    build: Callable[[], dict[str, bytes]]
    expect: tuple[str, ...]
    evidence_documents: tuple[str, ...] = ()
    subjects: tuple[str, ...] = ()


MUTATIONS: tuple[Mutation, ...] = (
    Mutation(
        id="patient_name",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(v=factory.CLEAN.with_(patient="Rajesh Kumar"))),
        expect=("PATIENT_NAME_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
        subjects=("patient.name:rajesh kumar",),
    ),
    Mutation(
        id="uhid",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(v=factory.CLEAN.with_(uhid="UHID-999999"))),
        expect=("UHID_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
        subjects=("patient.uhid:uhid999999",),
    ),
    Mutation(
        id="admission_date",
        build=lambda: replace_doc(
            clean_documents, "01_Admission_Record.pdf", factory.admission_record(factory.CLEAN.with_(admission="11-01-2026"))
        ),
        expect=("ADMISSION_DATE_MISMATCH",),
        evidence_documents=("01_Admission_Record.pdf",),
        subjects=("admission.admission_date:2026-01-11",),
    ),
    Mutation(
        id="discharge_date",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(v=factory.CLEAN.with_(discharge="17-01-2026"))),
        expect=("DISCHARGE_DATE_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
        subjects=("admission.discharge_date:2026-01-17",),
    ),
    Mutation(
        id="surgery_date",
        build=lambda: clean_documents(factory.CLEAN.with_(surgery="20-01-2026")),
        expect=("DATE_SEQUENCE_INVALID",),
        subjects=("sequence:surgery_after_discharge",),
    ),
    Mutation(
        id="doctor",
        build=lambda: replace_doc(
            clean_documents, "04_Anaesthesia_Record.pdf", factory.anaesthesia_record(factory.CLEAN.with_(anaesthetist="Dr. Kiran Rao"))
        ),
        expect=("DOCTOR_MISMATCH",),
        evidence_documents=("04_Anaesthesia_Record.pdf",),
        subjects=("doctors.anaesthetist:kiran rao",),
    ),
    Mutation(
        id="procedure",
        build=lambda: replace_doc(
            clean_with_bills, "07_OT_Bill.pdf", factory.ot_bill(factory.CLEAN.with_(procedure="Appendicectomy"))
        ),
        expect=("PROCEDURE_INCONSISTENT",),
        evidence_documents=("07_OT_Bill.pdf",),
        subjects=("procedure:appendicectomy",),
    ),
    Mutation(
        id="diagnosis",
        build=lambda: replace_doc(
            clean_documents, "03_Operative_Note.pdf", factory.operative_note(factory.CLEAN.with_(diagnosis="Acute appendicitis"))
        ),
        expect=("DIAGNOSIS_INCONSISTENT",),
        evidence_documents=("03_Operative_Note.pdf",),
        subjects=("diagnosis:acute appendicitis",),
    ),
    Mutation(
        id="bill_number",
        build=lambda: replace_doc(clean_with_bills, "07_OT_Bill.pdf", factory.ot_bill(number="CCH/IP/2026/08812")),
        expect=("DUPLICATE_BILL_NUMBER",),
        evidence_documents=("06_Hospital_Bill.pdf", "07_OT_Bill.pdf"),
        subjects=("bill_number:cchip202608812",),
    ),
    Mutation(
        id="quantity",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(lines=lines_with(0, quantity="5"))),
        expect=("BILL_ARITHMETIC_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
    ),
    Mutation(
        id="rate",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(lines=lines_with(0, rate="5,000.00"))),
        expect=("BILL_ARITHMETIC_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
    ),
    Mutation(
        id="line_amount",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(lines=lines_with(0, amount="20,000.00"))),
        # The line stops multiplying out and the lines stop adding up to the stated subtotal.
        expect=("BILL_ARITHMETIC_MISMATCH", "BILL_ARITHMETIC_MISMATCH"),
        evidence_documents=("06_Hospital_Bill.pdf",),
    ),
    Mutation(
        id="subtotal",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(subtotal="60,000.00")),
        expect=("BILL_ARITHMETIC_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
    ),
    Mutation(
        id="tax",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(tax="900.00")),
        expect=("BILL_ARITHMETIC_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
    ),
    Mutation(
        id="negative_discount",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(discount="-500.00")),
        expect=("BILL_ARITHMETIC_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
    ),
    Mutation(
        id="total",
        build=lambda: replace_doc(clean_documents, "06_Hospital_Bill.pdf", bill_with(total="60,000.00")),
        expect=("BILL_ARITHMETIC_MISMATCH",),
        evidence_documents=("06_Hospital_Bill.pdf",),
    ),
    Mutation(
        id="signature_region",
        build=lambda: replace_doc(clean_documents, "02_Consent_Form.pdf", factory.consent(patient_signed=False)),
        expect=("SIGNATURE_NOT_DETECTED",),
        evidence_documents=("02_Consent_Form.pdf",),
    ),
    Mutation(
        id="implant_lot_and_product",
        build=lambda: replace_doc(
            clean_with_bills,
            "09_Implant_Invoice.pdf",
            factory.implant_invoice(description="Titanium Vascular Clips (M)", lot="TV-90011"),
        ),
        expect=("IMPLANT_USAGE_NOT_CORROBORATED",),
        evidence_documents=("09_Implant_Invoice.pdf",),
    ),
    Mutation(
        id="page_image_and_text",
        build=lambda: replace_doc(clean_documents, "07_Lab_Report.pdf", factory.two_page_report(second_page_same=True)),
        expect=("DUPLICATE_PAGE",),
        evidence_documents=("07_Lab_Report.pdf",),
    ),
)


@pytest.fixture(scope="module", autouse=True)
def fresh_workspace(client):
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    yield


@pytest.mark.parametrize("mutation", MUTATIONS, ids=[item.id for item in MUTATIONS])
def test_one_change_at_a_time(client, mutation: Mutation):
    outcome = scenario(client, mutation.build())

    # 1. the expected rule fires — and 2. nothing unrelated fires
    assert outcome.codes() == sorted(mutation.expect), (
        f"{mutation.id}: expected {sorted(mutation.expect)}, got {outcome.codes()}"
    )

    # 3. the severity and rule id the specification requires
    for finding in outcome.findings["items"]:
        assert finding["severity"] == EXPECTED_SEVERITY[finding["code"]]
        assert finding["rule_id"] == EXPECTED_RULE_ID[finding["code"]]
        assert finding["status"] == "open"
        text = f"{finding['title']} {finding['explanation']} {finding['action']}".lower()
        for word in ACCUSATORY_WORDS:
            assert word not in text, f"{mutation.id}: {word!r} must never appear"

    if mutation.subjects:
        assert sorted(item["subject"] for item in outcome.findings["items"]) == sorted(mutation.subjects)

    # 5. the evidence points at the document that carries the change
    if mutation.evidence_documents:
        cited = {item["document_name"] for finding in outcome.findings["items"] for item in finding["evidence"]}
        assert cited == set(mutation.evidence_documents), f"{mutation.id}: evidence cited {cited}"
        pages = {item["document_id"]: item["page_count"] for item in outcome.state["documents"]["items"]}
        for finding in outcome.findings["items"]:
            for evidence in finding["evidence"]:
                assert evidence["page"] and 1 <= evidence["page"] <= pages[evidence["document_id"]]
                assert evidence["bounding_box"] and len(evidence["bounding_box"]) == 4

    # 4. fingerprints are stable, and 6. a second run adds nothing
    before = outcome.fingerprints()
    occurrences = {item["fingerprint"]: item["occurrences"] for item in outcome.findings["items"]}
    first = client.post(f"/api/claims/{outcome.claim_id}/validate").json()
    second = client.post(f"/api/claims/{outcome.claim_id}/validate").json()
    assert first["findings_created"] == second["findings_created"] == 0
    assert first["findings_auto_closed"] == second["findings_auto_closed"] == 0
    assert first["findings_reopened"] == second["findings_reopened"] == 0
    again = collect(client, outcome.claim)
    assert again.fingerprints() == before, f"{mutation.id}: fingerprints changed on a second run"
    assert again.codes() == outcome.codes()
    assert {item["fingerprint"]: item["occurrences"] for item in again.findings["items"]} == occurrences, (
        f"{mutation.id}: occurrences changed although nothing about the documents changed"
    )


def test_every_variable_named_in_the_specification_has_a_mutation():
    """The list below is the specification's; every one of them must be exercised above."""
    required = {
        "patient_name",
        "uhid",
        "admission_date",
        "discharge_date",
        "surgery_date",
        "doctor",
        "procedure",
        "diagnosis",
        "bill_number",
        "quantity",
        "rate",
        "line_amount",
        "subtotal",
        "tax",
        "negative_discount",
        "total",
        "signature_region",
        "implant_lot_and_product",
        "page_image_and_text",
    }
    assert {mutation.id for mutation in MUTATIONS} == required
    assert len(MUTATIONS) == 19

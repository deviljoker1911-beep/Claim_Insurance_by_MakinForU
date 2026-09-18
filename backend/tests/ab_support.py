"""Shared machinery for the A/B, mutation and golden-state passes.

A scenario is a set of documents built by `tests.factory`, uploaded to a claim of its own,
analysed and validated through the real API. Expectations are declared by the tests, never
read back from the rules configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tests import factory

CLAIM_FORM = {
    "patient_name": "Rajesh Sharma",
    "uhid": "UHID-123456",
    "hospital": "CityCare Multispeciality Hospital",
    "insurer": "Demo Health Insurance",
    "tpa": "Demo TPA",
    "admission_date": "2026-01-12",
    "discharge_date": "2026-01-16",
    "is_demo": True,
}

# Declared here on purpose: the severity a rule must carry is part of the specification, not
# something to look up from the implementation.
EXPECTED_SEVERITY = {
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

EXPECTED_RULE_ID = {
    "MISSING_REQUIRED_DOCUMENT": "R001",
    "POTENTIAL_ALTERATION": "R002",
    "PATIENT_NAME_MISMATCH": "R003",
    "UHID_MISMATCH": "R004",
    "CLAIM_FORM_MISMATCH": "R005",
    "ADMISSION_DATE_MISMATCH": "R006",
    "DISCHARGE_DATE_MISMATCH": "R007",
    "DATE_SEQUENCE_INVALID": "R008",
    "DIAGNOSIS_INCONSISTENT": "R009",
    "PROCEDURE_INCONSISTENT": "R010",
    "DOCTOR_MISMATCH": "R011",
    "DUPLICATE_BILL_NUMBER": "R012",
    "BILL_ARITHMETIC_MISMATCH": "R013",
    "SIGNATURE_NOT_DETECTED": "R014",
    "IMPLANT_USAGE_NOT_CORROBORATED": "R015",
    "DUPLICATE_DOCUMENT": "R016",
    "DUPLICATE_PAGE": "R017",
    "LOW_QUALITY_PAGE": "R018",
    "NAME_VARIANT": "R019",
}

ACCUSATORY_WORDS = ("fraud", "fraudulent", "forged", "forgery", "fake")


@dataclass
class Outcome:
    """What one scenario produced."""

    claim: dict
    findings: dict
    checks: dict
    state: dict
    documents: list[dict] = field(default_factory=list)

    @property
    def claim_id(self) -> str:
        return self.claim["id"]

    def codes(self, *, status: str | None = None, active_only: bool = False) -> list[str]:
        items = self.findings["items"]
        if status:
            items = [item for item in items if item["status"] == status]
        if active_only:
            items = [item for item in items if item["is_active"]]
        return sorted(item["code"] for item in items)

    def of(self, code: str) -> list[dict]:
        return [item for item in self.findings["items"] if item["code"] == code]

    def one(self, code: str) -> dict:
        matches = self.of(code)
        assert len(matches) == 1, f"expected exactly one {code}, got {len(matches)}"
        return matches[0]

    def check(self, check_id: str) -> dict:
        return next(item for item in self.checks["items"] if item["check_id"] == check_id)

    def check_status(self, check_id: str) -> str:
        return self.check(check_id)["status"]

    def statuses(self) -> dict[str, str]:
        return {item["check_id"]: item["status"] for item in self.checks["items"]}

    def fingerprints(self) -> dict[str, str]:
        return {f"{item['code']}|{item['subject']}": item["fingerprint"] for item in self.findings["items"]}

    def document(self, filename: str) -> dict:
        return next(item for item in self.state["documents"]["items"] if item["filename"] == filename)


def upload(client, claim_id: str, documents: dict[str, bytes]):
    files = [
        ("files", (name, data, "image/jpeg" if name.lower().endswith((".jpg", ".jpeg")) else "application/pdf"))
        for name, data in documents.items()
    ]
    return client.post(f"/api/claims/{claim_id}/documents", files=files)


def analyse(client, claim_id: str, timeout: float = 300.0) -> None:
    from app.worker import get_worker

    response = client.post(f"/api/claims/{claim_id}/analyze")
    assert response.status_code == 202, response.text
    assert get_worker().wait_idle(timeout), "the processing worker did not finish"


def collect(client, claim: dict) -> Outcome:
    findings = client.get(f"/api/claims/{claim['id']}/findings")
    checks = client.get(f"/api/claims/{claim['id']}/checks")
    state = client.get(f"/api/claims/{claim['id']}/state")
    assert findings.status_code == 200, findings.text
    assert checks.status_code == 200, checks.text
    assert state.status_code == 200, state.text
    return Outcome(claim=claim, findings=findings.json(), checks=checks.json(), state=state.json())


def scenario(client, documents: dict[str, bytes], *, form: dict | None = None) -> Outcome:
    """Upload a set of documents to a fresh claim, analyse it and read the outcome."""
    claim = client.post("/api/claims", json={**CLAIM_FORM, **(form or {})})
    assert claim.status_code == 201, claim.text
    claim = claim.json()
    response = upload(client, claim["id"], documents)
    assert response.status_code == 201, response.text
    analyse(client, claim["id"])
    return collect(client, claim)


def clean_documents(values: factory.Values | None = None) -> dict[str, bytes]:
    """Every required document present, every value agreeing, all arithmetic correct."""
    return factory.complete_claim(values or factory.CLEAN)


def clean_with_bills(values: factory.Values | None = None) -> dict[str, bytes]:
    v = values or factory.CLEAN
    return {
        **factory.complete_claim(v),
        "07_OT_Bill.pdf": factory.ot_bill(v),
        "08_Pharmacy_Bill.pdf": factory.pharmacy_bill(v),
        "09_Implant_Invoice.pdf": factory.implant_invoice(v),
    }

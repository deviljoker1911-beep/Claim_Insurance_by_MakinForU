"""Golden-state comparison and replay.

Each entry in GOLDEN says in advance what one claim variant must produce: which codes at
which severity, which documents the evidence must cite, the status of all twenty checks, and
the canonical values a reviewer must see. The expectations are written here as the
specification — none is read back from the rules file, from the engine or from an earlier
run — and every fingerprint is recomputed from the rule id and the subject, so a change in
the way the engine derives one fails here instead of passing quietly.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass, field

import pytest

from tests import factory
from tests.ab_support import (
    ACCUSATORY_WORDS,
    EXPECTED_RULE_ID,
    EXPECTED_SEVERITY,
    analyse,
    clean_documents,
    clean_with_bills,
    collect,
    scenario,
    upload,
)

# The twenty checks a reviewer is shown, named here so a check that quietly appears or
# disappears is a failure.
ALL_CHECKS = (
    "required_documents",
    "patient_name_consistency",
    "uhid_consistency",
    "name_spelling_variants",
    "claim_form_identity",
    "admission_date_consistency",
    "discharge_date_consistency",
    "date_sequence",
    "diagnosis_consistency",
    "procedure_consistency",
    "doctor_consistency",
    "operative_documentation",
    "bill_numbers_unique",
    "bill_arithmetic",
    "duplicate_documents",
    "duplicate_pages",
    "page_quality",
    "signatures",
    "concealed_text",
    "implant_corroboration",
)


@dataclass(frozen=True)
class Expect:
    """One finding the variant must produce."""

    code: str
    count: int = 1
    evidence: tuple[str, ...] = ()  # the documents the evidence must cite, sorted by filename
    says: tuple[str, ...] = ()  # text the explanation must contain


@dataclass(frozen=True)
class Golden:
    name: str
    build: Callable[[], dict[str, bytes]]
    expect: tuple[Expect, ...] = ()
    checks: dict[str, str] = field(default_factory=dict)  # every check not listed must pass
    canonical: dict[str, str] = field(default_factory=dict)
    bills: int = 1
    note: str = ""


CLEAN_CANONICAL = {
    "patient.name": "Rajesh Sharma",
    "patient.uhid": "UHID-123456",
    "patient.ipd": "IPD/2026/004512",
    "admission.admission_date": "2026-01-12",
    "admission.discharge_date": "2026-01-16",
    "admission.surgery_date": "2026-01-13",
    "diagnosis.primary": "Acute cholecystitis",
    "diagnosis.icd10": "K81.0",
    "doctors.surgeon": "Dr. Anil Mehta",
    "doctors.anaesthetist": "Dr. Priya Nair",
}


def _missing_two() -> dict[str, bytes]:
    documents = clean_documents()
    del documents["02_Consent_Form.pdf"]
    del documents["04_Anaesthesia_Record.pdf"]
    return documents


def _duplicate_copy() -> dict[str, bytes]:
    documents = clean_documents()
    documents["07_Hospital_Bill_Copy.pdf"] = documents["06_Hospital_Bill.pdf"]
    return documents


def _implant_without_an_operative_record() -> dict[str, bytes]:
    documents = clean_documents()
    documents["03_Operative_Note.pdf"] = factory.operative_note(implants=None)
    documents["07_Implant_Invoice.pdf"] = factory.implant_invoice()
    return documents


GOLDEN: tuple[Golden, ...] = (
    Golden(
        name="clean_core",
        build=clean_documents,
        checks={"implant_corroboration": "not_applicable"},
        canonical=CLEAN_CANONICAL,
        note="Six documents, every value agreeing: a claim with nothing to report.",
    ),
    Golden(
        name="clean_full",
        build=lambda: {**clean_with_bills(), "10_Lab_Report.pdf": factory.lab_report()},
        canonical=CLEAN_CANONICAL,
        bills=4,
        note="All four bill types and a lab report, all agreeing: still nothing to report.",
    ),
    Golden(
        name="shortened_name_on_the_pharmacy_bill",
        build=lambda: {
            **clean_documents(),
            "07_Pharmacy_Bill.pdf": factory.pharmacy_bill(factory.CLEAN.with_(patient="Rajesh K")),
        },
        expect=(
            Expect(
                "PATIENT_NAME_MISMATCH",
                evidence=("07_Pharmacy_Bill.pdf",),
                says=("Rajesh Sharma", "Rajesh K"),
            ),
        ),
        checks={"patient_name_consistency": "fail", "implant_corroboration": "not_applicable"},
        canonical={**CLEAN_CANONICAL},
        bills=2,
        note="A shortened name is a name to confirm with a human, not a spelling to fuzzy-match away.",
    ),
    Golden(
        name="spelling_variant_on_the_hospital_bill",
        build=lambda: {
            **clean_documents(),
            "06_Hospital_Bill.pdf": factory.hospital_bill(factory.CLEAN.with_(patient="RAJESH SHARMA")),
        },
        expect=(Expect("NAME_VARIANT", says=("RAJESH SHARMA",)),),
        checks={"name_spelling_variants": "fail", "implant_corroboration": "not_applicable"},
        canonical={**CLEAN_CANONICAL},
        note="The same name in capitals is one name printed two ways, recorded and nothing more.",
    ),
    Golden(
        name="wrong_uhid_on_the_hospital_bill",
        build=lambda: {
            **clean_documents(),
            "06_Hospital_Bill.pdf": factory.hospital_bill(factory.CLEAN.with_(uhid="UHID-654321")),
        },
        expect=(
            Expect(
                "UHID_MISMATCH",
                evidence=("06_Hospital_Bill.pdf",),
                says=("UHID-123456", "UHID-654321"),
            ),
        ),
        checks={"uhid_consistency": "fail", "implant_corroboration": "not_applicable"},
        canonical={**CLEAN_CANONICAL},
        note="One document carries a different hospital number.",
    ),
    Golden(
        name="bill_that_does_not_add_up",
        build=lambda: {
            **clean_documents(),
            "06_Hospital_Bill.pdf": factory.hospital_bill(total="60,000.00"),
        },
        expect=(
            Expect(
                "BILL_ARITHMETIC_MISMATCH",
                evidence=("06_Hospital_Bill.pdf",),
                says=("57,800.00", "60,000.00"),
            ),
        ),
        checks={"bill_arithmetic": "fail", "implant_corroboration": "not_applicable"},
        canonical={**CLEAN_CANONICAL},
        note="Lines total 57,800 and the bill claims 60,000.",
    ),
    Golden(
        name="two_required_documents_missing",
        build=_missing_two,
        expect=(Expect("MISSING_REQUIRED_DOCUMENT", count=2),),
        checks={"required_documents": "fail", "implant_corroboration": "not_applicable"},
        canonical={**CLEAN_CANONICAL},
        note="No consent and no anaesthesia record: one finding each, neither inventing evidence.",
    ),
    Golden(
        name="the_same_document_uploaded_twice",
        build=_duplicate_copy,
        expect=(
            Expect(
                "DUPLICATE_BILL_NUMBER",
                evidence=("06_Hospital_Bill.pdf", "07_Hospital_Bill_Copy.pdf"),
                says=("The totals are the same",),
            ),
            Expect(
                "DUPLICATE_DOCUMENT",
                evidence=("06_Hospital_Bill.pdf", "07_Hospital_Bill_Copy.pdf"),
                says=("same SHA-256",),
            ),
        ),
        checks={
            "duplicate_documents": "fail",
            "bill_numbers_unique": "fail",
            "implant_corroboration": "not_applicable",
        },
        canonical={**CLEAN_CANONICAL},
        bills=2,
        note=(
            "A byte-identical copy is reported as a duplicate document, not as duplicate pages. "
            "Until it is excluded it is still an active bill, so the shared bill number is "
            "reported too — and excluding the copy closes both."
        ),
    ),
    Golden(
        name="implant_invoice_without_an_operative_record",
        build=_implant_without_an_operative_record,
        expect=(Expect("IMPLANT_USAGE_NOT_CORROBORATED", evidence=("07_Implant_Invoice.pdf",)),),
        checks={"implant_corroboration": "fail"},
        canonical={**CLEAN_CANONICAL},
        bills=2,
        note="An implant is billed and the operative note records none.",
    ),
    Golden(
        name="unsigned_consent",
        build=lambda: {**clean_documents(), "02_Consent_Form.pdf": factory.consent(patient_signed=False)},
        expect=(Expect("SIGNATURE_NOT_DETECTED", evidence=("02_Consent_Form.pdf",)),),
        checks={"signatures": "fail", "implant_corroboration": "not_applicable"},
        canonical={**CLEAN_CANONICAL},
        note="The consent's patient signature area is printed and empty.",
    ),
)


def fingerprint_of(rule_id: str, subject: str) -> str:
    """The fingerprint the specification asks for: the rule and the subject, nothing else."""
    return hashlib.sha256(f"{rule_id}|{subject}".encode()).hexdigest()[:40]


def _canonical_value(state: dict, key: str) -> str | None:
    section, name = key.split(".", 1)
    return state[section]["fields"][name]["value"]


def compare(golden: Golden, outcome) -> None:
    """The whole golden comparison for one variant."""
    expected_codes = sorted(code for item in golden.expect for code in [item.code] * item.count)
    assert outcome.codes() == expected_codes, golden.name

    for item in golden.expect:
        matches = outcome.of(item.code)
        assert len(matches) == item.count, f"{golden.name}: {item.code}"
        for finding in matches:
            assert finding["severity"] == EXPECTED_SEVERITY[item.code]
            assert finding["rule_id"] == EXPECTED_RULE_ID[item.code]
            assert finding["status"] == "open"
            assert finding["is_active"] is True
            assert finding["occurrences"] == 1
            assert finding["attribution"] in {"rule", "source"}
            assert finding["fingerprint"] == fingerprint_of(finding["rule_id"], finding["subject"])
            assert finding["subject"], "every finding names the thing it is about"
            text = f"{finding['title']} {finding['explanation']} {finding['action']}".lower()
            assert not [word for word in ACCUSATORY_WORDS if word in text]
        if item.evidence:
            cited = sorted({e["document_name"] for e in matches[0]["evidence"]})
            assert cited == sorted(item.evidence), f"{golden.name}: {item.code} evidence"
        for phrase in item.says:
            assert phrase in matches[0]["explanation"], f"{golden.name}: {item.code} says {phrase}"

    statuses = outcome.statuses()
    assert tuple(statuses) == ALL_CHECKS, "the checks a reviewer is shown, in order"
    expected_statuses = {check: golden.checks.get(check, "pass") for check in ALL_CHECKS}
    assert statuses == expected_statuses, golden.name

    for key, value in golden.canonical.items():
        assert _canonical_value(outcome.state, key) == value, f"{golden.name}: {key}"
    assert outcome.state["bills"]["count"] == golden.bills


@pytest.mark.parametrize("golden", GOLDEN, ids=[g.name for g in GOLDEN])
def test_the_variant_matches_its_golden_state(client, golden: Golden) -> None:
    compare(golden, scenario(client, golden.build()))


@pytest.mark.parametrize("golden", GOLDEN, ids=[g.name for g in GOLDEN])
def test_the_golden_state_survives_a_replay(client, golden: Golden) -> None:
    """Validating again over unchanged documents must change nothing at all."""
    outcome = scenario(client, golden.build())
    before = outcome.findings["items"]
    checks_before = outcome.checks["items"]
    run_before = outcome.findings["run"]

    for _ in range(2):
        response = client.post(f"/api/claims/{outcome.claim_id}/validate")
        assert response.status_code == 200, response.text
        assert response.json()["findings_created"] == 0

    again = collect(client, outcome.claim)
    compare(golden, again)
    keys = (
        "id",
        "code",
        "rule_id",
        "severity",
        "status",
        "subject",
        "fingerprint",
        "title",
        "explanation",
        "action",
        "occurrences",
        "first_seen_at",
        "last_seen_at",
        "evidence",
    )
    assert [{k: item[k] for k in keys} for item in again.findings["items"]] == [
        {k: item[k] for k in keys} for item in before
    ], "a replay over unchanged documents rewrites nothing"
    assert again.checks["items"] == checks_before
    assert again.findings["run"]["input_fingerprint"] == run_before["input_fingerprint"]
    assert again.findings["run"]["rules_version"] == run_before["rules_version"]


def test_two_claims_built_from_the_same_documents_agree_on_every_fingerprint(client) -> None:
    """The fingerprint depends on the rule and the subject, not on the claim or the upload order."""
    documents = {
        **clean_documents(),
        "06_Hospital_Bill.pdf": factory.hospital_bill(factory.CLEAN.with_(uhid="UHID-654321")),
    }
    first = scenario(client, documents)
    second = scenario(client, dict(reversed(list(documents.items()))))
    assert first.codes() == second.codes() == ["UHID_MISMATCH"]
    assert first.one("UHID_MISMATCH")["fingerprint"] == second.one("UHID_MISMATCH")["fingerprint"]
    assert first.one("UHID_MISMATCH")["subject"] == second.one("UHID_MISMATCH")["subject"]
    assert first.one("UHID_MISMATCH")["explanation"] == second.one("UHID_MISMATCH")["explanation"]
    assert [e["document_name"] for e in first.one("UHID_MISMATCH")["evidence"]] == [
        e["document_name"] for e in second.one("UHID_MISMATCH")["evidence"]
    ]
    assert first.statuses() == second.statuses()
    assert _canonical_value(first.state, "patient.uhid") == _canonical_value(second.state, "patient.uhid")
    # The run fingerprint covers this claim's own documents, so it is claim-scoped by design;
    # what must not vary is everything the reviewer is shown.
    assert first.findings["run"]["rules_version"] == second.findings["run"]["rules_version"]


def test_correcting_one_document_changes_only_what_that_document_caused(client) -> None:
    """Two problems, one corrected: the other finding keeps its identity and its history."""
    documents = {
        **clean_documents(),
        "06_Hospital_Bill.pdf": factory.hospital_bill(total="60,000.00"),
        "07_Pharmacy_Bill.pdf": factory.pharmacy_bill(factory.CLEAN.with_(patient="Rajesh K")),
    }
    outcome = scenario(client, documents)
    assert outcome.codes() == ["BILL_ARITHMETIC_MISMATCH", "PATIENT_NAME_MISMATCH"]
    name_before = outcome.one("PATIENT_NAME_MISMATCH")
    arithmetic_before = outcome.one("BILL_ARITHMETIC_MISMATCH")

    # A corrected hospital bill replaces the one that did not add up.
    replacement = upload(client, outcome.claim_id, {"08_Hospital_Bill_Corrected.pdf": factory.hospital_bill()})
    assert replacement.status_code == 201, replacement.text
    analyse(client, outcome.claim_id)
    after = collect(client, outcome.claim)

    name_after = after.one("PATIENT_NAME_MISMATCH")
    assert name_after["id"] == name_before["id"]
    assert name_after["fingerprint"] == name_before["fingerprint"]
    assert name_after["status"] == "open"
    assert name_after["first_seen_at"] == name_before["first_seen_at"]
    assert name_after["evidence"] == name_before["evidence"]

    # The original bill still says what it said, so its own finding stays open ...
    still_open = [item for item in after.of("BILL_ARITHMETIC_MISMATCH") if item["status"] == "open"]
    assert [item["id"] for item in still_open] == [arithmetic_before["id"]]
    # ... and the corrected copy adds none of its own.
    assert after.check_status("bill_arithmetic") == "fail"
    assert len(after.of("BILL_ARITHMETIC_MISMATCH")) == 1


def test_a_human_decision_survives_the_next_validation(client) -> None:
    outcome = scenario(client, {**clean_documents(), "06_Hospital_Bill.pdf": factory.hospital_bill(total="60,000.00")})
    finding = outcome.one("BILL_ARITHMETIC_MISMATCH")
    response = client.post(
        f"/api/findings/{finding['id']}/action",
        json={"action": "acknowledge", "note": "Bill re-issued by the billing desk; awaiting the corrected copy."},
    )
    assert response.status_code == 200, response.text

    for _ in range(2):
        assert client.post(f"/api/claims/{outcome.claim_id}/validate").status_code == 200
    again = collect(client, outcome.claim)
    kept = again.one("BILL_ARITHMETIC_MISMATCH")
    assert kept["status"] == "acknowledged"
    assert kept["id"] == finding["id"]
    assert kept["occurrences"] == finding["occurrences"]
    assert kept["status_actor"]
    assert "billing desk" in kept["status_note"]


def test_every_rule_the_engine_can_raise_is_declared_here() -> None:
    """The declarations in this pass must cover every rule the configuration defines."""
    from app.validation.rules import rules

    defined = rules()
    assert {rule.code for rule in defined.values()} == set(EXPECTED_SEVERITY) == set(EXPECTED_RULE_ID)
    assert len(defined) == 19
    for rule in defined.values():
        assert rule.severity == EXPECTED_SEVERITY[rule.code], rule.code
        assert rule.rule_id == EXPECTED_RULE_ID[rule.code], rule.code


def test_excluding_the_duplicate_copy_closes_everything_that_copy_caused(client) -> None:
    """The offered action resolves the duplicate and the bill number it shared."""
    documents = clean_documents()
    documents["07_Hospital_Bill_Copy.pdf"] = documents["06_Hospital_Bill.pdf"]
    outcome = scenario(client, documents)
    duplicate = outcome.one("DUPLICATE_DOCUMENT")
    assert "exclude_duplicate" in duplicate["actions_available"]

    response = client.post(
        f"/api/findings/{duplicate['id']}/action",
        json={"action": "exclude_duplicate", "note": "Same bill uploaded twice."},
    )
    assert response.status_code == 200, response.text
    after = collect(client, outcome.claim)

    assert after.one("DUPLICATE_DOCUMENT")["status"] == "resolved"
    assert after.one("DUPLICATE_BILL_NUMBER")["status"] == "auto_closed"
    assert after.check_status("bill_numbers_unique") == "pass"
    assert after.state["bills"]["count"] == 1, "an excluded copy supplies no bill"

    copy = after.document("07_Hospital_Bill_Copy.pdf")
    assert copy["excluded"] is True
    assert copy["exclusion_reason"]
    # "excluded" is the terminal state of a duplicate a reviewer has dealt with; it still
    # records which document it duplicates.
    assert copy["duplicate_state"] == "excluded"
    assert copy["duplicate_of"] == after.document("06_Hospital_Bill.pdf")["document_id"]

    # Validating again must not resurrect it or re-raise what it caused.
    assert client.post(f"/api/claims/{outcome.claim_id}/validate").json()["findings_created"] == 0
    settled = collect(client, outcome.claim)
    assert settled.one("DUPLICATE_BILL_NUMBER")["status"] == "auto_closed"
    assert settled.document("07_Hospital_Bill_Copy.pdf")["excluded"] is True
    assert settled.document("07_Hospital_Bill_Copy.pdf")["duplicate_state"] == "excluded"
    assert settled.state["bills"]["count"] == 1


def test_a_shared_bill_number_on_two_different_bills_reports_the_differing_totals(client) -> None:
    """The A side of the wording: genuinely different bills, so the totals really do differ."""
    documents = clean_documents()
    documents["07_OT_Bill.pdf"] = factory.ot_bill(number="CCH/IP/2026/08812")
    outcome = scenario(client, documents)
    finding = outcome.one("DUPLICATE_BILL_NUMBER")
    assert "The totals differ" in finding["explanation"]
    assert "The totals are the same" not in finding["explanation"]
    assert sorted({e["document_name"] for e in finding["evidence"]}) == [
        "06_Hospital_Bill.pdf",
        "07_OT_Bill.pdf",
    ]
    assert outcome.check_status("bill_numbers_unique") == "fail"

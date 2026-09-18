"""Lifecycle back-testing: every transition, for findings of every kind.

A finding is raised by a rule and moved on by a person. These tests walk each transition on
real findings, and check that a human decision is never undone by a later validation run.
"""

import pytest
from sqlalchemy import select

from tests import factory
from tests.ab_support import clean_documents, clean_with_bills, collect, scenario


@pytest.fixture(scope="module", autouse=True)
def fresh_workspace(client):
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    yield


def messy_documents() -> dict[str, bytes]:
    """One claim carrying a finding of every kind the lifecycle tests need."""
    from tests.conftest import demo_path

    report = factory.lab_report()
    documents = clean_with_bills()
    documents["02_Consent_Form.pdf"] = factory.consent(patient_signed=False)  # SIGNATURE_NOT_DETECTED
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(  # BILL_ARITHMETIC_MISMATCH
        lines=(
            factory.BillLine("Room Rent - Twin Sharing", "4", "4,500.00", "20,000.00"),
            factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
            factory.BillLine("Surgeon Fee", "1", "35,000.00", "35,000.00"),
        ),
        subtotal="59,800.00",
    )
    documents["07_OT_Bill.pdf"] = factory.ot_bill(number="CCH/IP/2026/08812")  # DUPLICATE_BILL_NUMBER
    documents["10_Lab_Report.pdf"] = report  # DUPLICATE_DOCUMENT
    documents["11_Lab_Report_copy.pdf"] = report
    documents["12_USG_Scan.jpg"] = demo_path("09_USG_Abdomen_Scan.jpg").read_bytes()  # LOW_QUALITY_PAGE
    documents["13_Implant_Invoice_Covered.pdf"] = demo_path("15_Implant_Invoice.pdf").read_bytes()  # POTENTIAL_ALTERATION
    # The demo invoice carries DS/INV/2026/0391, so the factory one gets a number of its own:
    # this claim is meant to have exactly one shared bill number.
    documents["09_Implant_Invoice.pdf"] = factory.implant_invoice(number="DS/INV/2026/0392")
    return documents


@pytest.fixture(scope="module")
def messy(client, fresh_workspace):
    outcome = scenario(client, messy_documents())
    # The set is built to raise all of these at once.
    assert set(outcome.codes()) >= {
        "BILL_ARITHMETIC_MISMATCH",
        "DUPLICATE_BILL_NUMBER",
        "DUPLICATE_DOCUMENT",
        "LOW_QUALITY_PAGE",
        "POTENTIAL_ALTERATION",
        "SIGNATURE_NOT_DETECTED",
    }, outcome.codes()
    return outcome


def act(client, finding_id: str, action: str, note: str | None = None):
    return client.post(f"/api/findings/{finding_id}/action", json={"action": action, "note": note})


def finding_of(client, claim_id: str, code: str) -> dict:
    items = client.get(f"/api/claims/{claim_id}/findings").json()["items"]
    matches = [item for item in items if item["code"] == code]
    assert len(matches) == 1, f"{code} is ambiguous in this claim ({len(matches)} findings)"
    return matches[0]


def set_excluded(claim_id: str, filename: str, value: bool) -> None:
    """Simulate a document leaving or rejoining the claim."""
    from app.db import SessionLocal
    from app.models import Document

    with SessionLocal() as session:
        document = session.scalar(
            select(Document).where(Document.claim_id == claim_id, Document.original_filename == filename)
        )
        document.excluded = value
        document.exclusion_reason = "lifecycle back-test" if value else None
        session.commit()


LIFECYCLE_CODES = (
    "POTENTIAL_ALTERATION",
    "BILL_ARITHMETIC_MISMATCH",
    "DUPLICATE_BILL_NUMBER",
    "SIGNATURE_NOT_DETECTED",
    "LOW_QUALITY_PAGE",
    "DUPLICATE_DOCUMENT",
)


@pytest.mark.parametrize("code", LIFECYCLE_CODES)
def test_open_to_acknowledged(client, messy, code):
    finding = finding_of(client, messy.claim_id, code)
    assert finding["status"] in ("open", "reopened", "acknowledged", "resolved")
    if finding["status"] != "open":
        pytest.skip("an earlier test in this module already moved this finding")
    response = act(client, finding["id"], "acknowledge", "Checked with the hospital")
    assert response.status_code == 200
    updated = response.json()["finding"]
    assert updated["status"] == "acknowledged"
    assert updated["is_active"] is False
    assert updated["status_actor"] == "Demo Operator"
    assert updated["status_note"] == "Checked with the hospital"
    # and back to open through reopen, so the next test starts where it expects to
    assert act(client, finding["id"], "reopen").json()["finding"]["status"] == "reopened"


@pytest.mark.parametrize("code", LIFECYCLE_CODES)
def test_open_to_resolved_and_the_decision_survives_revalidation(client, messy, code):
    finding = finding_of(client, messy.claim_id, code)
    resolved = act(client, finding["id"], "resolve", f"Resolved for {code}").json()["finding"]
    assert resolved["status"] == "resolved"
    assert resolved["is_active"] is False

    client.post(f"/api/claims/{messy.claim_id}/validate")
    again = finding_of(client, messy.claim_id, code)
    assert again["id"] == finding["id"]
    assert again["status"] == "resolved", "validation must not undo a human decision"
    assert again["status_note"] == f"Resolved for {code}"
    # leave it reopened for the remaining tests
    act(client, finding["id"], "reopen")


def test_acknowledgement_survives_revalidation(client, messy):
    finding = finding_of(client, messy.claim_id, "LOW_QUALITY_PAGE")
    act(client, finding["id"], "acknowledge", "Best copy available")
    client.post(f"/api/claims/{messy.claim_id}/validate")
    again = finding_of(client, messy.claim_id, "LOW_QUALITY_PAGE")
    assert again["status"] == "acknowledged"
    assert again["status_note"] == "Best copy available"
    act(client, finding["id"], "reopen")


@pytest.mark.parametrize(
    ("code", "filename"),
    [
        ("POTENTIAL_ALTERATION", "13_Implant_Invoice_Covered.pdf"),
        ("BILL_ARITHMETIC_MISMATCH", "06_Hospital_Bill.pdf"),
        ("SIGNATURE_NOT_DETECTED", "02_Consent_Form.pdf"),
        ("LOW_QUALITY_PAGE", "12_USG_Scan.jpg"),
    ],
)
def test_open_to_auto_closed_and_back_to_reopened(client, messy, code, filename):
    """When the document that caused a finding leaves the claim the finding closes itself."""
    before = finding_of(client, messy.claim_id, code)

    set_excluded(messy.claim_id, filename, True)
    closed_run = client.post(f"/api/claims/{messy.claim_id}/validate").json()
    assert closed_run["findings_auto_closed"] >= 1
    closed = finding_of(client, messy.claim_id, code)
    assert closed["id"] == before["id"]
    assert closed["status"] == "auto_closed"
    assert closed["status_actor"] == "system"
    assert "no longer raises" in closed["status_note"]
    assert closed["is_active"] is False

    set_excluded(messy.claim_id, filename, False)
    reopened_run = client.post(f"/api/claims/{messy.claim_id}/validate").json()
    assert reopened_run["findings_reopened"] >= 1
    reopened = finding_of(client, messy.claim_id, code)
    assert reopened["id"] == before["id"], "the same finding came back, not a new one"
    assert reopened["status"] == "reopened"
    assert reopened["is_active"] is True
    assert reopened["fingerprint"] == before["fingerprint"]
    assert reopened["occurrences"] > before["occurrences"]


def test_a_missing_document_finding_closes_when_the_document_arrives(client):
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    outcome = scenario(client, documents)
    finding = outcome.one("MISSING_REQUIRED_DOCUMENT")
    assert finding["status"] == "open"

    from tests.ab_support import analyse, upload

    upload(client, outcome.claim_id, {"03_Operative_Note.pdf": factory.operative_note()})
    analyse(client, outcome.claim_id)
    after = collect(client, outcome.claim)
    closed = after.one("MISSING_REQUIRED_DOCUMENT")
    assert closed["id"] == finding["id"]
    assert closed["status"] == "auto_closed"
    assert after.check_status("required_documents") == "pass"
    assert after.check_status("operative_documentation") == "pass"

    # and it reopens if that document leaves the claim again
    set_excluded(outcome.claim_id, "03_Operative_Note.pdf", True)
    client.post(f"/api/claims/{outcome.claim_id}/validate")
    reopened = collect(client, outcome.claim).one("MISSING_REQUIRED_DOCUMENT")
    assert reopened["status"] == "reopened"
    assert reopened["id"] == finding["id"]


def test_implant_corroboration_closes_when_an_operative_note_records_it(client):
    documents = clean_with_bills()
    documents["03_Operative_Note.pdf"] = factory.operative_note(implants=None)
    outcome = scenario(client, documents)
    finding = outcome.one("IMPLANT_USAGE_NOT_CORROBORATED")

    from tests.ab_support import analyse, upload

    upload(client, outcome.claim_id, {"10_Operative_Note_Corrected.pdf": factory.operative_note()})
    analyse(client, outcome.claim_id)
    after = collect(client, outcome.claim)
    assert after.one("IMPLANT_USAGE_NOT_CORROBORATED")["status"] == "auto_closed"
    assert after.one("IMPLANT_USAGE_NOT_CORROBORATED")["id"] == finding["id"]
    assert after.check_status("implant_corroboration") == "pass"


def test_excluding_a_duplicate_keeps_it_in_the_inventory_but_not_in_the_values(client):
    documents = clean_documents()
    report = factory.lab_report()
    documents["07_Lab_Report.pdf"] = report
    documents["08_Lab_Report_copy.pdf"] = report
    outcome = scenario(client, documents)
    sources_before = outcome.state["patient"]["fields"]["name"]["source_count"]

    finding = outcome.one("DUPLICATE_DOCUMENT")
    result = act(client, finding["id"], "exclude_duplicate").json()
    assert result["finding"]["status"] == "resolved"

    after = collect(client, outcome.claim)
    copy = after.document("08_Lab_Report_copy.pdf")
    assert copy["excluded"] is True
    assert copy["duplicate_state"] == "excluded"
    assert copy["duplicate_of"] == after.document("07_Lab_Report.pdf")["document_id"]
    assert after.state["documents"]["count"] == outcome.state["documents"]["count"], "it stays in the record"
    assert after.state["documents"]["excluded_count"] == 1
    assert after.state["patient"]["fields"]["name"]["source_count"] == sources_before - 1
    cited = {
        source["document_name"] for value in after.state["patient"]["fields"].values() for source in value["sources"]
    }
    assert "08_Lab_Report_copy.pdf" not in cited, "an excluded document states nothing"
    assert after.check_status("duplicate_documents") == "pass"


def test_a_resolved_duplicate_stays_resolved_even_if_the_copy_comes_back(client):
    documents = clean_documents()
    report = factory.lab_report()
    documents["07_Lab_Report.pdf"] = report
    documents["08_Lab_Report_copy.pdf"] = report
    outcome = scenario(client, documents)
    finding = outcome.one("DUPLICATE_DOCUMENT")
    act(client, finding["id"], "exclude_duplicate")

    set_excluded(outcome.claim_id, "08_Lab_Report_copy.pdf", False)
    client.post(f"/api/claims/{outcome.claim_id}/validate")
    again = finding_of(client, outcome.claim_id, "DUPLICATE_DOCUMENT")
    assert again["id"] == finding["id"]
    assert again["status"] == "resolved", "a resolved finding is not reopened by the rule firing again"


def test_invalid_transitions_are_refused(client, messy):
    finding = finding_of(client, messy.claim_id, "DUPLICATE_BILL_NUMBER")
    # put it in a known state
    act(client, finding["id"], "resolve", "for the transition matrix")
    refusals = {
        "acknowledge": 409,  # resolved cannot be acknowledged
        "review": 409,  # resolved is not under review
    }
    for action, expected in refusals.items():
        response = act(client, finding["id"], action)
        assert response.status_code == expected, f"{action} from resolved"
        assert "resolved" in response.json()["detail"]
    assert act(client, finding["id"], "reopen").status_code == 200

    # reopened cannot be reopened again
    response = act(client, finding["id"], "reopen")
    assert response.status_code == 409
    assert "reopened" in response.json()["detail"]

    # an unknown action and an unknown finding
    assert client.post(f"/api/findings/{finding['id']}/action", json={"action": "close"}).status_code == 422
    assert client.post("/api/findings/00000000-0000-0000-0000-000000000000/action", json={"action": "resolve"}).status_code == 404


def test_exclude_duplicate_is_only_offered_for_duplicate_documents(client, messy):
    for code in ("BILL_ARITHMETIC_MISMATCH", "LOW_QUALITY_PAGE", "POTENTIAL_ALTERATION"):
        finding = finding_of(client, messy.claim_id, code)
        assert "exclude_duplicate" not in finding["actions_available"]
        response = act(client, finding["id"], "exclude_duplicate")
        assert response.status_code == 409
        assert "duplicate document" in response.json()["detail"]


def test_review_keeps_the_finding_open_and_records_who_looked(client, messy):
    finding = finding_of(client, messy.claim_id, "SIGNATURE_NOT_DETECTED")
    if not finding["is_active"]:
        act(client, finding["id"], "reopen")
        finding = finding_of(client, messy.claim_id, "SIGNATURE_NOT_DETECTED")
    before_status = finding["status"]
    updated = act(client, finding["id"], "review", "Chasing the signed copy").json()["finding"]
    assert updated["status"] == before_status
    assert updated["is_active"] is True
    assert updated["reviewed_by"] == "Demo Operator"
    assert updated["reviewed_at"]


def test_revalidating_the_same_documents_updates_the_finding_in_place(client):
    """The same documents, validated again: the finding keeps its identity and its wording."""
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(
        lines=(
            factory.BillLine("Room Rent - Twin Sharing", "4", "4,500.00", "20,000.00"),
            factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
            factory.BillLine("Surgeon Fee", "1", "35,000.00", "35,000.00"),
        ),
        subtotal="59,800.00",
    )
    outcome = scenario(client, documents)
    first = outcome.one("BILL_ARITHMETIC_MISMATCH")
    client.post(f"/api/claims/{outcome.claim_id}/validate")
    again = finding_of(client, outcome.claim_id, "BILL_ARITHMETIC_MISMATCH")
    assert again["id"] == first["id"]
    assert again["fingerprint"] == first["fingerprint"]
    assert again["explanation"] == first["explanation"]
    assert again["occurrences"] == first["occurrences"], "replaying the same documents changes nothing"


def test_a_replacement_document_gets_its_own_finding_and_closes_the_old_one(client):
    """A corrected bill is a different document: its finding is its own, and the old one closes."""
    documents = clean_documents()
    documents["06_Hospital_Bill.pdf"] = factory.hospital_bill(
        lines=(
            factory.BillLine("Room Rent - Twin Sharing", "4", "4,500.00", "20,000.00"),
            factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
            factory.BillLine("Surgeon Fee", "1", "35,000.00", "35,000.00"),
        ),
        subtotal="59,800.00",
    )
    outcome = scenario(client, documents)
    first = outcome.one("BILL_ARITHMETIC_MISMATCH")
    assert "20,000.00" in first["explanation"]

    from tests.ab_support import analyse, upload

    # The hospital sends a corrected bill under the same number; the first one leaves the claim.
    upload(
        client,
        outcome.claim_id,
        {
            "07_Hospital_Bill_Corrected.pdf": factory.hospital_bill(
                lines=(
                    factory.BillLine("Room Rent - Twin Sharing", "4", "4,500.00", "21,000.00"),
                    factory.BillLine("Nursing Charges", "4", "1,200.00", "4,800.00"),
                    factory.BillLine("Surgeon Fee", "1", "35,000.00", "35,000.00"),
                ),
                subtotal="60,800.00",
            )
        },
    )
    analyse(client, outcome.claim_id)
    set_excluded(outcome.claim_id, "06_Hospital_Bill.pdf", True)
    client.post(f"/api/claims/{outcome.claim_id}/validate")

    items = client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]
    arithmetic = [item for item in items if item["code"] == "BILL_ARITHMETIC_MISMATCH"]
    old = next(item for item in arithmetic if item["id"] == first["id"])
    new = next(item for item in arithmetic if item["id"] != first["id"])
    assert old["status"] == "auto_closed", "the finding about the withdrawn bill closes itself"
    assert new["status"] == "open"
    assert new["fingerprint"] != first["fingerprint"], "a different document is a different subject"
    assert "21,000.00" in new["explanation"]
    assert new["evidence"][0]["document_name"] == "07_Hospital_Bill_Corrected.pdf"

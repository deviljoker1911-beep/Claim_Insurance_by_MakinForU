"""The checklist over real documents: the endpoint, the demo journey and what must not change."""

import pytest

from tests import factory
from tests.ab_support import analyse, clean_documents, clean_with_bills, scenario, upload
from tests.conftest import DEMO_CLAIM
from tests.conftest import analyse as analyse_demo


def checklist(client, claim_id: str) -> dict:
    response = client.get(f"/api/claims/{claim_id}/checklist")
    assert response.status_code == 200, response.text
    return response.json()


def row(payload: dict, key: str) -> dict:
    return next(item for item in payload["items"] if item["key"] == key)


def statuses(payload: dict) -> dict[str, str]:
    return {item["key"]: item["status"] for item in payload["items"]}


# --- the endpoint ----------------------------------------------------------------------------


def test_the_checklist_is_built_for_the_procedure_the_documents_name(client):
    outcome = scenario(client, clean_with_bills())
    payload = checklist(client, outcome.claim_id)
    assert payload["available"] is True
    assert payload["claim_number"] == outcome.claim["claim_number"]
    assert payload["procedure"]["key"] == "laparoscopic_cholecystectomy"
    assert payload["procedure"]["label"] == "Laparoscopic cholecystectomy"
    assert payload["procedure"]["source_count"] >= 3
    assert payload["provisional"] is False
    assert payload["count"] == 13
    assert row(payload, "operative_note")["status"] == "found"
    assert row(payload, "consent")["status"] == "found"
    assert row(payload, "implant_invoice")["status"] == "found", "the claim carries an implant invoice"


def test_the_checklist_reports_the_documents_that_satisfy_each_requirement(client):
    outcome = scenario(client, clean_documents())
    payload = checklist(client, outcome.claim_id)
    evidence = row(payload, "discharge_summary")["evidence"]
    assert [item["document_name"] for item in evidence] == ["05_Discharge_Summary.pdf"]
    assert evidence[0]["doc_type"] == "discharge_summary"
    assert evidence[0]["classification_confidence"] > 0.5
    assert evidence[0]["page"] is None, "a document satisfies a requirement as a whole"


def test_the_checklist_is_part_of_the_canonical_claim(client):
    outcome = scenario(client, clean_documents())
    section = outcome.state["checklist"]
    payload = checklist(client, outcome.claim_id)
    assert section["available"] is True
    assert {item["key"]: item["status"] for item in section["items"]} == statuses(payload)
    assert "checklist" not in outcome.state["meta"]["pending_sections"]


def test_an_unknown_claim_has_no_checklist(client, workspace):
    assert client.get("/api/claims/does-not-exist/checklist").status_code == 404


def test_a_claim_with_no_documents_names_no_procedure(client, workspace):
    claim = client.post("/api/claims", json={**DEMO_CLAIM}).json()
    payload = checklist(client, claim["id"])
    assert payload["available"] is False
    assert payload["procedure"]["key"] is None
    assert payload["items"] == []
    assert "No procedure is named" in payload["note"]


# --- the three prototype procedures ------------------------------------------------------------


def test_a_knee_replacement_claim_gets_the_knee_replacement_checklist(client):
    values = factory.CLEAN.with_(
        procedure="Total Knee Replacement", diagnosis="Osteoarthritis of the left knee", icd10="M17.0"
    )
    payload = checklist(client, scenario(client, clean_documents(values)).claim_id)
    assert payload["procedure"]["key"] == "knee_replacement"
    implant = row(payload, "implant_invoice")
    assert implant["status"] == "missing", "a joint replacement uses an implant, billed or not"
    assert implant["severity"] == "critical"


def test_a_cataract_claim_gets_the_cataract_checklist(client):
    values = factory.CLEAN.with_(
        procedure="Phacoemulsification with IOL", diagnosis="Senile cataract, right eye", icd10="H25.1"
    )
    payload = checklist(client, scenario(client, clean_documents(values)).claim_id)
    assert payload["procedure"]["key"] == "cataract_surgery"
    assert row(payload, "implant_invoice")["label"] == "Intraocular lens invoice"
    assert row(payload, "nursing_records")["required"] is False


def test_a_procedure_without_a_checklist_is_said_plainly(client):
    values = factory.CLEAN.with_(procedure="Appendicectomy", diagnosis="Acute appendicitis", icd10="K35.80")
    payload = checklist(client, scenario(client, clean_documents(values)).claim_id)
    assert payload["available"] is False
    assert payload["procedure"]["key"] == "appendicectomy"
    assert payload["procedure"]["has_checklist"] is False
    assert "No checklist is configured" in payload["note"]
    assert [item["label"] for item in payload["configured_procedures"]] == [
        "Laparoscopic cholecystectomy",
        "Total knee replacement",
        "Cataract surgery",
    ]


# --- what the checklist reacts to ----------------------------------------------------------------


def test_uploading_the_missing_document_moves_its_requirement_to_found(client):
    documents = clean_documents()
    del documents["03_Operative_Note.pdf"]
    outcome = scenario(client, documents)
    before = checklist(client, outcome.claim_id)
    assert row(before, "operative_note")["status"] == "missing"
    assert [item["code"] for item in row(before, "operative_note")["findings"]] == ["MISSING_REQUIRED_DOCUMENT"]

    assert upload(client, outcome.claim_id, {"07_Operative_Note.pdf": factory.operative_note()}).status_code == 201
    analyse(client, outcome.claim_id)

    after = checklist(client, outcome.claim_id)
    operative = row(after, "operative_note")
    assert operative["status"] == "found"
    assert [item["document_name"] for item in operative["evidence"]] == ["07_Operative_Note.pdf"]
    assert [item["status"] for item in operative["findings"]] == ["auto_closed"]
    assert after["summary"]["required_outstanding"] == before["summary"]["required_outstanding"] - 1


def test_a_document_carrying_an_open_finding_asks_for_a_person(client):
    documents = clean_documents()
    documents["02_Consent_Form.pdf"] = factory.consent(patient_signed=False)
    payload = checklist(client, scenario(client, documents).claim_id)
    consent = row(payload, "consent")
    assert consent["status"] == "review_required"
    assert [item["code"] for item in consent["findings"]] == ["SIGNATURE_NOT_DETECTED"]
    assert "02_Consent_Form.pdf" in consent["detail"]


def test_excluding_a_duplicate_takes_it_out_of_the_checklist(client):
    documents = clean_documents()
    documents["07_Discharge_Summary_Copy.pdf"] = documents["05_Discharge_Summary.pdf"]
    outcome = scenario(client, documents)
    before = checklist(client, outcome.claim_id)
    assert len(row(before, "discharge_summary")["evidence"]) == 2

    duplicate = outcome.one("DUPLICATE_DOCUMENT")
    response = client.post(
        f"/api/findings/{duplicate['id']}/action",
        json={"action": "exclude_duplicate", "note": "Same summary uploaded twice."},
    )
    assert response.status_code == 200, response.text

    after = checklist(client, outcome.claim_id)
    summary = row(after, "discharge_summary")
    assert [item["document_name"] for item in summary["evidence"]] == ["05_Discharge_Summary.pdf"]
    assert summary["status"] == "found"


def test_excluding_a_duplicate_never_empties_a_requirement(client):
    """The action takes out the extra copy, never the document it duplicates."""
    documents = clean_documents()
    documents["07_Hospital_Bill_Copy.pdf"] = documents["06_Hospital_Bill.pdf"]
    outcome = scenario(client, documents)
    for finding in outcome.of("DUPLICATE_DOCUMENT"):
        assert (
            client.post(f"/api/findings/{finding['id']}/action", json={"action": "exclude_duplicate"}).status_code
            == 200
        )
    bills = row(checklist(client, outcome.claim_id), "bills")
    assert [item["document_name"] for item in bills["evidence"]] == ["06_Hospital_Bill.pdf"]
    assert bills["status"] == "found", "what the copy caused is closed with it"


def test_the_checklist_agrees_with_the_findings_list_after_an_action(client):
    """Both endpoints bring validation up to date, so neither shows the other's stale answer."""
    documents = clean_documents()
    documents["07_Discharge_Summary_Copy.pdf"] = documents["05_Discharge_Summary.pdf"]
    outcome = scenario(client, documents)
    duplicate = outcome.one("DUPLICATE_DOCUMENT")
    assert client.post(f"/api/findings/{duplicate['id']}/action", json={"action": "exclude_duplicate"}).status_code == 200

    # Read the checklist first: it must not report a requirement on a finding that the next
    # validation run closes.
    payload = checklist(client, outcome.claim_id)
    findings = client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]
    active = {item["code"] for item in findings if item["is_active"]}
    listed = {
        finding["code"]
        for item in payload["items"]
        for finding in item["findings"]
        if finding["is_active"]
    }
    assert listed <= active
    assert row(payload, "discharge_summary")["status"] == "found"


# --- determinism and the phase 5 guarantee ------------------------------------------------------


def test_reading_the_checklist_twice_gives_the_same_answer(client):
    outcome = scenario(client, clean_with_bills())
    assert checklist(client, outcome.claim_id) == checklist(client, outcome.claim_id)


def test_the_checklist_does_not_make_validation_run_again(client):
    """The checklist is derived from the findings, so it must not decide the inputs changed."""
    outcome = scenario(client, {**clean_documents(), "06_Hospital_Bill.pdf": factory.hospital_bill(total="60,000.00")})
    finding = outcome.one("BILL_ARITHMETIC_MISMATCH")
    checklist(client, outcome.claim_id)

    response = client.post(f"/api/claims/{outcome.claim_id}/validate")
    assert response.status_code == 200, response.text
    assert response.json()["findings_created"] == 0
    after = client.get(f"/api/claims/{outcome.claim_id}/findings").json()["items"]
    kept = next(item for item in after if item["code"] == "BILL_ARITHMETIC_MISMATCH")
    assert kept["occurrences"] == finding["occurrences"], "reading the checklist changes nothing"
    assert kept["last_seen_at"] == finding["last_seen_at"]


def test_the_claim_state_hash_does_not_change_when_only_the_checklist_is_read(client):
    outcome = scenario(client, clean_documents())
    first = client.get(f"/api/claims/{outcome.claim_id}/state").json()["snapshot"]["content_sha256"]
    checklist(client, outcome.claim_id)
    second = client.get(f"/api/claims/{outcome.claim_id}/state").json()["snapshot"]["content_sha256"]
    assert first == second


# --- the demo journey ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def demo_journey(client):
    """The demo claim through its three stages, with the checklist read at each one."""
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()

    stages = {}
    for key, demo_set in (("initial", "initial"), ("operative_note", "operative_note"), ("anaesthesia", "anaesthesia_record")):
        response = client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": demo_set})
        assert response.status_code == 200, response.text
        analyse_demo(client, claim["id"])
        stages[key] = checklist(client, claim["id"])
    return {"claim": claim, **stages}


def test_the_demo_claim_detects_its_procedure_from_the_documents(demo_journey):
    procedure = demo_journey["initial"]["procedure"]
    assert procedure["key"] == "laparoscopic_cholecystectomy"
    assert procedure["source_count"] >= 3
    assert procedure["documents"], "the checklist says which documents named the procedure"
    assert demo_journey["initial"]["available"] is True


def test_the_initial_demo_upload_is_missing_the_operative_note_and_the_anaesthesia_record(demo_journey):
    initial = statuses(demo_journey["initial"])
    assert initial["operative_note"] == "missing"
    assert initial["anaesthesia_record"] == "missing"
    assert initial["consent"] == "review_required", "the consent is there and unsigned"
    assert initial["discharge_summary"] == "found"
    assert initial["nursing_records"] == "found"
    assert initial["medication_records"] == "found"


def test_the_later_documents_move_their_requirements_to_found(demo_journey):
    after_note = statuses(demo_journey["operative_note"])
    assert after_note["operative_note"] == "found"
    assert after_note["anaesthesia_record"] == "missing", "only the operative note arrived"

    final = statuses(demo_journey["anaesthesia"])
    assert final["operative_note"] == "found"
    assert final["anaesthesia_record"] == "found"


def test_the_outstanding_count_falls_as_the_documents_arrive(demo_journey):
    counts = [demo_journey[stage]["summary"]["required_outstanding"] for stage in ("initial", "operative_note", "anaesthesia")]
    assert counts[0] > counts[1] > counts[2]


def test_the_operative_note_arrives_as_a_scan_and_is_still_recognised(demo_journey):
    evidence = row(demo_journey["anaesthesia"], "operative_note")["evidence"]
    assert [item["document_name"] for item in evidence] == ["scan_0042.pdf"]
    assert evidence[0]["doc_type"] == "operative_note", "recognised from its content, not its name"

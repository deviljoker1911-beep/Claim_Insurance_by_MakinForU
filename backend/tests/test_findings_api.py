"""Findings over the real demo claim: the staged story, the lifecycle, and the API."""

import json

import pymupdf
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import make_engine
from app.models import Document, Finding, ValidationRun
from app.validation.rules import FORBIDDEN_WORDS
from tests.conftest import DEMO_CLAIM, analyse, demo_path, pack_files, pick, upload


@pytest.fixture(scope="module")
def staged(client):  # noqa: D401
    """The demo claim through its three stages: 16 documents, then the two later ones."""
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()

    def snapshot() -> dict:
        findings = client.get(f"/api/claims/{claim['id']}/findings")
        checks = client.get(f"/api/claims/{claim['id']}/checks")
        assert findings.status_code == 200, findings.text
        assert checks.status_code == 200, checks.text
        return {"findings": findings.json(), "checks": checks.json()}

    stages = {}
    for key, demo_set in (("initial", "initial"), ("operative_note", "operative_note"), ("anaesthesia", "anaesthesia_record")):
        response = client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": demo_set})
        assert response.status_code == 200, response.text
        analyse(client, claim["id"])
        stages[key] = snapshot()
    return {"claim": claim, **stages}


def codes(payload: dict, *, status: str | None = None) -> list[str]:
    return sorted(
        item["code"]
        for item in payload["findings"]["items"]
        if status is None or item["status"] == status
    )


def by_code(payload: dict) -> dict[str, dict]:
    return {item["code"]: item for item in payload["findings"]["items"]}


def check(payload: dict, check_id: str) -> dict:
    return next(item for item in payload["checks"]["items"] if item["check_id"] == check_id)


# --- the initial 16 documents --------------------------------------------------------------


def test_the_initial_claim_raises_the_seeded_findings(staged):
    """Each seeded demo issue turns into the finding its rule describes."""
    initial = staged["initial"]
    assert codes(initial) == [
        "BILL_ARITHMETIC_MISMATCH",
        "DUPLICATE_BILL_NUMBER",
        "DUPLICATE_DOCUMENT",
        "IMPLANT_USAGE_NOT_CORROBORATED",
        "LOW_QUALITY_PAGE",
        "MISSING_REQUIRED_DOCUMENT",
        "MISSING_REQUIRED_DOCUMENT",
        "NAME_VARIANT",
        "PATIENT_NAME_MISMATCH",
        "POTENTIAL_ALTERATION",
        "SIGNATURE_NOT_DETECTED",
    ]
    assert initial["findings"]["summary"]["by_severity"] == {"critical": 3, "review": 5, "warning": 2, "info": 1}
    assert initial["findings"]["summary"]["by_status"] == {"open": 11}


def test_the_seeded_issues_of_the_demo_data_are_all_represented(staged):
    """The manifest records what was seeded; the rules must have found each of them."""
    from tests.conftest import manifest

    expected = {issue["expected_finding"] for issue in manifest()["seeded_issues"]}
    raised = set(codes(staged["initial"]))
    assert expected <= raised, f"not raised: {expected - raised}"


def test_missing_documents_name_the_requirement_and_invent_no_evidence(staged):
    missing = [item for item in staged["initial"]["findings"]["items"] if item["code"] == "MISSING_REQUIRED_DOCUMENT"]
    assert {item["context"]["requirement"] for item in missing} == {"operative_note", "anaesthesia_record"}
    for item in missing:
        assert item["severity"] == "critical"
        assert item["evidence"] == []
        assert item["context"]["doc_types"]
        assert item["subject"].startswith("requirement:")


def test_the_pharmacy_bill_name_is_a_review_finding_with_its_page(staged):
    finding = by_code(staged["initial"])["PATIENT_NAME_MISMATCH"]
    assert finding["severity"] == "review"
    assert finding["attribution"] == "rule"
    assert "Rajesh Sharma" in finding["explanation"]
    assert "Rajesh K" in finding["explanation"]
    assert [item["document_name"] for item in finding["evidence"]] == ["13_Pharmacy_Bill.pdf"]
    assert finding["evidence"][0]["page"] == 1
    assert len(finding["evidence"][0]["bounding_box"]) == 4


def test_the_card_spelling_is_only_an_informational_note(staged):
    finding = by_code(staged["initial"])["NAME_VARIANT"]
    assert finding["severity"] == "info"
    assert "RAJESH SHARMA" in finding["explanation"]
    assert [item["document_name"] for item in finding["evidence"]] == ["01_Patient_ID.png"]


def test_the_duplicate_lab_report_is_reported_with_both_copies(staged):
    finding = by_code(staged["initial"])["DUPLICATE_DOCUMENT"]
    assert finding["severity"] == "warning"
    assert finding["context"]["document_name"] == "11_Lab_Report_copy.pdf"
    assert finding["context"]["original_name"] == "10_Lab_Report.pdf"
    assert {item["document_name"] for item in finding["evidence"]} == {"10_Lab_Report.pdf", "11_Lab_Report_copy.pdf"}
    assert "exclude_duplicate" in finding["actions_available"]


def test_the_shared_bill_number_is_reported(staged):
    finding = by_code(staged["initial"])["DUPLICATE_BILL_NUMBER"]
    assert finding["context"]["bill_number"] == "CCH/IP/2026/08812"
    assert finding["context"]["count"] == 2
    assert "12_Main_Hospital_Bill.pdf" in finding["explanation"]
    assert "14_OT_Bill.pdf" in finding["explanation"]


def test_the_room_rent_line_arithmetic_is_reported(staged):
    finding = by_code(staged["initial"])["BILL_ARITHMETIC_MISMATCH"]
    assert "Room Rent" in finding["explanation"]
    assert "4 × 4,500.00" in finding["explanation"]
    assert "18,000.00" in finding["explanation"]
    assert "20,000.00" in finding["explanation"]
    assert finding["evidence"][0]["document_name"] == "12_Main_Hospital_Bill.pdf"
    assert finding["evidence"][0]["page"] == 1


def test_the_blank_consent_signature_is_reported(staged):
    finding = by_code(staged["initial"])["SIGNATURE_NOT_DETECTED"]
    assert "Patient / guardian" in finding["title"]
    assert finding["evidence"][0]["document_name"] == "16_Consent_Form.pdf"
    assert finding["evidence"][0]["bounding_box"]


def test_the_low_quality_scan_is_reported(staged):
    finding = by_code(staged["initial"])["LOW_QUALITY_PAGE"]
    assert finding["severity"] == "warning"
    assert finding["attribution"] == "source"
    assert "09_USG_Abdomen_Scan.jpg" in finding["title"]
    assert "dpi" in finding["explanation"] or "soft" in finding["explanation"]


def test_the_covered_invoice_value_is_reported_as_a_potential_alteration(staged):
    finding = by_code(staged["initial"])["POTENTIAL_ALTERATION"]
    assert finding["severity"] == "critical"
    assert finding["attribution"] == "source"
    assert "1,000.00" in finding["explanation"]
    assert "human verification required" in finding["explanation"].lower()
    assert finding["evidence"][0]["document_name"] == "15_Implant_Invoice.pdf"


def test_the_billed_implant_is_not_corroborated_before_the_operative_note(staged):
    finding = by_code(staged["initial"])["IMPLANT_USAGE_NOT_CORROBORATED"]
    assert finding["severity"] == "review"
    assert "Hem-o-lok" in finding["explanation"]
    assert "6,600.00" in finding["explanation"]


def test_no_finding_ever_uses_accusatory_wording(staged):
    text = json.dumps(staged["initial"]["findings"]).lower()
    for word in FORBIDDEN_WORDS:
        assert word not in text, f"{word!r} appears in a finding"


def test_every_finding_is_attributable_to_a_rule_or_a_source(staged):
    for item in staged["initial"]["findings"]["items"]:
        assert item["attribution"] in ("rule", "source"), "phase 5 findings are never produced by a model"
        assert item["rule_id"].startswith("R")
        assert item["fingerprint"]
        assert item["subject"]


def test_evidence_points_at_real_pages_of_this_claim(client, staged):
    documents = {
        item["document_id"]: item
        for item in client.get(f"/api/claims/{staged['claim']['id']}/state").json()["documents"]["items"]
    }
    seen = 0
    for item in staged["initial"]["findings"]["items"]:
        for evidence in item["evidence"]:
            seen += 1
            assert evidence["document_id"] in documents
            assert 1 <= evidence["page"] <= documents[evidence["document_id"]]["page_count"]
            box = evidence["bounding_box"]
            assert len(box) == 4 and all(0.0 <= value <= 1.0 for value in box)
            assert evidence["kind"]
            assert evidence["method"]
    assert seen >= 10


# --- the checks record ----------------------------------------------------------------------


def test_the_checks_record_covers_every_check(staged):
    checks = staged["initial"]["checks"]
    assert checks["count"] == 20
    assert checks["summary"] == {"total": 20, "pass": 9, "fail": 10, "pending": 1, "not_applicable": 0}
    for item in checks["items"]:
        assert item["status"] in ("pass", "fail", "pending", "not_applicable")
        assert item["title"] and item["detail"]
        assert item["category"]
        if item["status"] == "fail":
            assert item["finding_count"] >= 1
            assert item["severity"] in ("critical", "review", "warning", "info")
        else:
            assert item["finding_count"] == 0


def test_a_check_that_cannot_run_yet_is_pending(staged):
    pending = check(staged["initial"], "operative_documentation")
    assert pending["status"] == "pending"
    assert "cannot run yet" in pending["detail"]
    assert pending["finding_count"] == 0


def test_checks_that_passed_say_what_they_compared(staged):
    assert check(staged["initial"], "uhid_consistency")["status"] == "pass"
    assert "agree" in check(staged["initial"], "uhid_consistency")["detail"]
    assert check(staged["initial"], "date_sequence")["status"] == "pass"
    assert check(staged["initial"], "claim_form_identity")["status"] == "pass"
    assert check(staged["initial"], "duplicate_pages")["status"] == "pass"


# --- the later documents change the picture -------------------------------------------------


def test_the_operative_note_closes_its_findings(staged):
    initial, after = staged["initial"], staged["operative_note"]
    assert "MISSING_REQUIRED_DOCUMENT" in codes(initial, status="open")
    closed = [
        item
        for item in after["findings"]["items"]
        if item["status"] == "auto_closed"
    ]
    closed_codes = sorted(item["code"] for item in closed)
    assert closed_codes == ["IMPLANT_USAGE_NOT_CORROBORATED", "MISSING_REQUIRED_DOCUMENT"]
    operative = next(item for item in closed if item["code"] == "MISSING_REQUIRED_DOCUMENT")
    assert operative["context"]["requirement"] == "operative_note"
    assert operative["status_actor"] == "system"
    assert "no longer raises" in operative["status_note"]
    assert not operative["is_active"]


def test_the_operative_note_lets_the_waiting_checks_run(staged):
    before = check(staged["initial"], "operative_documentation")
    after = check(staged["operative_note"], "operative_documentation")
    assert before["status"] == "pending"
    assert after["status"] == "pass"
    assert "corroborated" in after["detail"]
    assert check(staged["operative_note"], "implant_corroboration")["status"] == "pass"


def test_the_anaesthesia_record_closes_the_last_missing_document(staged):
    final = staged["anaesthesia"]
    assert check(final, "required_documents")["status"] == "pass"
    assert codes(final, status="open") == [
        "BILL_ARITHMETIC_MISMATCH",
        "DUPLICATE_BILL_NUMBER",
        "DUPLICATE_DOCUMENT",
        "LOW_QUALITY_PAGE",
        "NAME_VARIANT",
        "PATIENT_NAME_MISMATCH",
        "POTENTIAL_ALTERATION",
        "SIGNATURE_NOT_DETECTED",
    ]
    assert sorted(item["code"] for item in final["findings"]["items"] if item["status"] == "auto_closed") == [
        "IMPLANT_USAGE_NOT_CORROBORATED",
        "MISSING_REQUIRED_DOCUMENT",
        "MISSING_REQUIRED_DOCUMENT",
    ]


def test_nothing_is_raised_twice_across_the_stages(staged):
    """Every stage updates the findings that exist instead of adding copies."""
    fingerprints = [item["fingerprint"] for item in staged["anaesthesia"]["findings"]["items"]]
    assert len(fingerprints) == len(set(fingerprints))
    assert staged["anaesthesia"]["findings"]["count"] == 11
    initial = {item["fingerprint"]: item for item in staged["initial"]["findings"]["items"]}
    final = {item["fingerprint"]: item for item in staged["anaesthesia"]["findings"]["items"]}
    assert set(initial) <= set(final), "fingerprints are stable across re-analysis"
    for fingerprint, item in initial.items():
        assert final[fingerprint]["first_seen_at"] == item["first_seen_at"]


# --- running validation again ----------------------------------------------------------------


def test_validating_again_without_changes_adds_nothing(client, staged):
    claim_id = staged["claim"]["id"]
    before = client.get(f"/api/claims/{claim_id}/findings").json()
    first = client.post(f"/api/claims/{claim_id}/validate").json()
    second = client.post(f"/api/claims/{claim_id}/validate").json()
    after = client.get(f"/api/claims/{claim_id}/findings").json()
    assert first["findings_created"] == second["findings_created"] == 0
    assert first["findings_auto_closed"] == second["findings_auto_closed"] == 0
    assert after["count"] == before["count"]
    assert {item["fingerprint"] for item in after["items"]} == {item["fingerprint"] for item in before["items"]}


def test_reading_the_findings_does_not_run_validation_again(client, staged):
    claim_id = staged["claim"]["id"]
    first = client.get(f"/api/claims/{claim_id}/findings").json()
    second = client.get(f"/api/claims/{claim_id}/findings").json()
    assert first["run"]["input_fingerprint"] == second["run"]["input_fingerprint"]
    assert first["run"]["updated_at"] == second["run"]["updated_at"], "a read must not trigger a new run"
    for left, right in zip(first["items"], second["items"]):
        assert left["occurrences"] == right["occurrences"]


def test_a_finding_that_disappears_is_closed_and_comes_back_reopened(client, staged):
    """Excluding the pharmacy bill removes the name mismatch; putting it back reopens it."""
    claim_id = staged["claim"]["id"]
    engine = make_engine(get_settings().database_url)
    try:
        def set_excluded(value: bool) -> None:
            with Session(engine) as session:
                document = session.scalar(
                    select(Document).where(
                        Document.claim_id == claim_id, Document.original_filename == "13_Pharmacy_Bill.pdf"
                    )
                )
                document.excluded = value
                document.exclusion_reason = "test" if value else None
                session.commit()

        set_excluded(True)
        closed = client.post(f"/api/claims/{claim_id}/validate").json()
        assert closed["findings_auto_closed"] >= 1
        finding = next(
            item
            for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
            if item["code"] == "PATIENT_NAME_MISMATCH"
        )
        assert finding["status"] == "auto_closed"
        assert finding["status_actor"] == "system"

        set_excluded(False)
        reopened = client.post(f"/api/claims/{claim_id}/validate").json()
        assert reopened["findings_reopened"] >= 1
        finding_again = next(
            item
            for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
            if item["code"] == "PATIENT_NAME_MISMATCH"
        )
        assert finding_again["status"] == "reopened"
        assert finding_again["id"] == finding["id"], "the same finding came back, not a new one"
        assert finding_again["occurrences"] > finding["occurrences"]
        assert finding_again["is_active"] is True
    finally:
        engine.dispose()


# --- the lifecycle actions -------------------------------------------------------------------


def test_review_records_the_reviewer_without_closing_the_finding(client, staged):
    claim_id = staged["claim"]["id"]
    finding = next(
        item for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"] if item["code"] == "LOW_QUALITY_PAGE"
    )
    response = client.post(f"/api/findings/{finding['id']}/action", json={"action": "review", "note": "Asked for a rescan"})
    assert response.status_code == 200
    updated = response.json()["finding"]
    assert updated["status"] == finding["status"], "review does not change the status"
    assert updated["reviewed_by"] == "Demo Operator"
    assert updated["reviewed_at"]
    assert updated["status_note"] == "Asked for a rescan"


def test_acknowledge_then_resolve_then_reopen(client, staged):
    claim_id = staged["claim"]["id"]
    finding = next(
        item
        for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["code"] == "DUPLICATE_BILL_NUMBER"
    )
    acknowledged = client.post(f"/api/findings/{finding['id']}/action", json={"action": "acknowledge"}).json()["finding"]
    assert acknowledged["status"] == "acknowledged"
    assert acknowledged["status_actor"] == "Demo Operator"
    assert acknowledged["is_active"] is False

    resolved = client.post(
        f"/api/findings/{finding['id']}/action", json={"action": "resolve", "note": "Hospital reissued the OT bill"}
    ).json()
    assert resolved["finding"]["status"] == "resolved"
    assert resolved["finding"]["status_note"] == "Hospital reissued the OT bill"
    assert resolved["summary"]["by_status"]["resolved"] >= 1

    conflict = client.post(f"/api/findings/{finding['id']}/action", json={"action": "acknowledge"})
    assert conflict.status_code == 409
    assert "resolved" in conflict.json()["detail"]

    reopened = client.post(f"/api/findings/{finding['id']}/action", json={"action": "reopen"}).json()["finding"]
    assert reopened["status"] == "reopened"
    assert reopened["is_active"] is True
    assert "review" in reopened["actions_available"]


def test_a_resolved_finding_stays_resolved_when_validation_runs_again(client, staged):
    claim_id = staged["claim"]["id"]
    finding = next(
        item
        for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["code"] == "SIGNATURE_NOT_DETECTED"
    )
    client.post(f"/api/findings/{finding['id']}/action", json={"action": "resolve", "note": "Signed copy on file"})
    client.post(f"/api/claims/{claim_id}/validate")
    again = next(
        item
        for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["id"] == finding["id"]
    )
    assert again["status"] == "resolved", "a human decision is not overwritten by a run"
    assert again["status_note"] == "Signed copy on file"


def test_excluding_a_duplicate_removes_it_from_the_claim(client, staged):
    claim_id = staged["claim"]["id"]
    finding = next(
        item
        for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["code"] == "DUPLICATE_DOCUMENT"
    )
    before = client.get(f"/api/claims/{claim_id}/state").json()
    name_sources_before = before["patient"]["fields"]["name"]["source_count"]

    result = client.post(f"/api/findings/{finding['id']}/action", json={"action": "exclude_duplicate"}).json()
    assert result["finding"]["status"] == "resolved"
    assert "excluded" in result["finding"]["status_note"]

    after = client.get(f"/api/claims/{claim_id}/state").json()
    copy = next(item for item in after["documents"]["items"] if item["filename"] == "11_Lab_Report_copy.pdf")
    assert copy["excluded"] is True
    assert copy["duplicate_state"] == "excluded"
    assert copy["duplicate_of"]
    assert copy["exclusion_reason"]
    assert after["patient"]["fields"]["name"]["source_count"] == name_sources_before - 1
    assert after["documents"]["count"] == before["documents"]["count"], "the record keeps the document"

    checks = {item["check_id"]: item for item in client.get(f"/api/claims/{claim_id}/checks").json()["items"]}
    assert checks["duplicate_documents"]["status"] == "pass"
    events = [event["event_type"] for event in client.get(f"/api/claims/{claim_id}/audit").json()]
    assert "document_excluded" in events
    assert "finding_action" in events


def test_exclude_duplicate_is_refused_for_other_findings(client, staged):
    claim_id = staged["claim"]["id"]
    finding = next(
        item
        for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]
        if item["code"] == "BILL_ARITHMETIC_MISMATCH"
    )
    response = client.post(f"/api/findings/{finding['id']}/action", json={"action": "exclude_duplicate"})
    assert response.status_code == 409
    assert "duplicate document" in response.json()["detail"]
    assert "exclude_duplicate" not in finding["actions_available"]


def test_unknown_findings_and_actions_are_rejected(client, staged):
    claim_id = staged["claim"]["id"]
    finding = client.get(f"/api/claims/{claim_id}/findings").json()["items"][0]
    assert client.post("/api/findings/does-not-exist/action", json={"action": "resolve"}).status_code == 404
    assert client.post(f"/api/findings/{finding['id']}/action", json={"action": "delete"}).status_code == 422
    assert client.post(f"/api/findings/{finding['id']}/action", json={}).status_code == 422
    assert (
        client.post(f"/api/findings/{finding['id']}/action", json={"action": "review", "note": "bad\x00note"}).status_code
        == 422
    )


# --- the API surface --------------------------------------------------------------------------


def test_findings_can_be_filtered(client, staged):
    claim_id = staged["claim"]["id"]
    everything = client.get(f"/api/claims/{claim_id}/findings").json()
    critical = client.get(f"/api/claims/{claim_id}/findings", params={"severity": "critical"}).json()
    assert critical["count"] >= 1
    assert {item["severity"] for item in critical["items"]} == {"critical"}
    active = client.get(f"/api/claims/{claim_id}/findings", params={"status": "active"}).json()
    assert all(item["is_active"] for item in active["items"])
    assert active["count"] <= everything["count"]
    resolved = client.get(f"/api/claims/{claim_id}/findings", params={"status": "resolved"}).json()
    assert {item["status"] for item in resolved["items"]} <= {"resolved"}
    assert client.get(f"/api/claims/{claim_id}/findings", params={"status": "nope"}).status_code == 422
    assert client.get(f"/api/claims/{claim_id}/findings", params={"severity": "nope"}).status_code == 422


def test_findings_are_ordered_with_the_open_and_severe_first(client, staged):
    items = client.get(f"/api/claims/{staged['claim']['id']}/findings").json()["items"]
    active = [item["severity"] for item in items if item["is_active"]]
    order = {"critical": 0, "review": 1, "warning": 2, "info": 3}
    assert active == sorted(active, key=lambda severity: order[severity])
    assert all(item["is_active"] for item in items[: len(active)])


def test_the_canonical_claim_carries_the_findings_summary(client, staged):
    claim_id = staged["claim"]["id"]
    state = client.get(f"/api/claims/{claim_id}/state").json()
    findings = client.get(f"/api/claims/{claim_id}/findings").json()
    section = state["findings"]
    assert section["available"] is True
    assert section["count"] == findings["count"]
    assert section["by_severity"] == findings["summary"]["by_severity"]
    assert section["active"] == findings["summary"]["active"]
    assert {item["id"] for item in section["items"]} == {item["id"] for item in findings["items"]}
    # The sections whose engines come later stay empty.
    for pending in ("questions", "resolutions"):
        assert state[pending]["available"] is False
        assert state[pending]["items"] == []


def test_validation_is_recorded_in_the_audit_trail_and_the_database(client, staged):
    claim_id = staged["claim"]["id"]
    events = [event for event in client.get(f"/api/claims/{claim_id}/audit").json() if event["event_type"] == "validation_completed"]
    assert events
    assert events[0]["details"]["rules_version"] == 1
    assert events[0]["details"]["checks"]["total"] == 20
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            run = session.scalar(select(ValidationRun).where(ValidationRun.claim_id == claim_id))
            assert run is not None
            assert len(run.checks) == 20
            assert run.summary["checks"]["total"] == 20
            stored = session.scalars(select(Finding).where(Finding.claim_id == claim_id)).all()
            assert len(stored) == 11
            assert all(finding.fingerprint and finding.subject for finding in stored)
    finally:
        engine.dispose()


def test_the_endpoints_are_documented_and_reject_unknown_claims(client, staged):
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in (
        "/api/claims/{claim_id}/findings",
        "/api/claims/{claim_id}/checks",
        "/api/claims/{claim_id}/validate",
        "/api/findings/{finding_id}/action",
    ):
        assert path in paths, path
    assert client.get("/api/claims/does-not-exist/findings").status_code == 404
    assert client.get("/api/claims/%00/checks").status_code == 404
    assert client.post("/api/claims/does-not-exist/validate").status_code == 404


# --- claims of their own (these rebuild the workspace, so they come last) ---------------------

def test_a_check_with_nothing_to_examine_is_not_applicable(client, claim):
    upload(client, claim["id"], pick(pack_files(), "06_Discharge_Summary.pdf"))
    analyse(client, claim["id"])
    checks = {item["check_id"]: item for item in client.get(f"/api/claims/{claim['id']}/checks").json()["items"]}
    assert checks["bill_arithmetic"]["status"] == "not_applicable"
    assert checks["bill_numbers_unique"]["status"] == "not_applicable"
    assert checks["implant_corroboration"]["status"] == "not_applicable"
    assert checks["duplicate_documents"]["status"] in ("pass", "not_applicable")


# --- duplicate pages, end to end ---------------------------------------------------------------


def test_a_repeated_page_inside_one_document_is_reported(client, claim):
    """A document whose second page repeats its first: both the text and the picture match."""
    source = pymupdf.open(demo_path("10_Lab_Report.pdf"))
    doubled = pymupdf.open()
    doubled.insert_pdf(source)
    doubled.insert_pdf(source)
    data = doubled.tobytes()
    doubled.close()
    source.close()

    response = upload(client, claim["id"], [("scan_double.pdf", data, "application/pdf")])
    assert response.status_code == 201, response.text
    analyse(client, claim["id"])

    findings = client.get(f"/api/claims/{claim['id']}/findings").json()
    duplicates = [item for item in findings["items"] if item["code"] == "DUPLICATE_PAGE"]
    assert len(duplicates) == 1, [item["code"] for item in findings["items"]]
    finding = duplicates[0]
    assert finding["severity"] == "warning"
    assert finding["context"]["page"] == 2
    assert finding["context"]["original_page"] == 1
    assert finding["context"]["text_similarity"] >= 95
    assert finding["context"]["dhash_distance"] <= 5
    assert {item["page"] for item in finding["evidence"]} == {1, 2}
    checks = {item["check_id"]: item for item in client.get(f"/api/claims/{claim['id']}/checks").json()["items"]}
    assert checks["duplicate_pages"]["status"] == "fail"


def test_different_pages_of_one_document_are_not_reported(client, claim):
    upload(client, claim["id"], pick(pack_files(), "08_Nursing_Record.pdf", "06_Discharge_Summary.pdf"))
    analyse(client, claim["id"])
    findings = client.get(f"/api/claims/{claim['id']}/findings").json()
    assert [item for item in findings["items"] if item["code"] == "DUPLICATE_PAGE"] == []
    checks = {item["check_id"]: item for item in client.get(f"/api/claims/{claim['id']}/checks").json()["items"]}
    assert checks["duplicate_pages"]["status"] == "pass"
    assert checks["duplicate_pages"]["subjects_checked"] >= 6

import hashlib
import stat

import pytest

from app.db import SessionLocal
from app.models import AppSetting, Document
from app.storage import absolute_storage_path, claims_root
from tests.conftest import DEMO_CLAIM, TEST_DEMO_DATA, manifest, pack_files, upload


def _reset(client) -> dict:
    response = client.post("/api/demo/reset")
    assert response.status_code == 200, response.text
    return response.json()


def test_reset_restarts_claim_numbering_at_00123(client, workspace):
    for _ in range(3):
        client.post("/api/claims", json=DEMO_CLAIM)
    result = _reset(client)
    assert result["next_claim_number"] == "CLM-2026-00123"
    created = client.post("/api/claims", json=DEMO_CLAIM).json()
    assert created["claim_number"] == "CLM-2026-00123"


def test_reset_clears_claims_documents_and_stored_originals(client, claim):
    upload(client, claim["id"], pack_files()[:4])
    assert any(claims_root().iterdir())
    result = _reset(client)
    assert result["status"] == "ok"
    assert result["deleted"] == {"claims": 1, "documents": 4, "audit_events": 5}
    assert result["storage_cleared"] is True
    assert client.get("/api/claims").json() == []
    assert client.get(f"/api/claims/{claim['id']}").status_code == 404
    assert not claims_root().exists() or not any(claims_root().iterdir())


def test_reset_preserves_application_configuration(client, workspace):
    with SessionLocal() as session:
        session.merge(AppSetting(key="operator_display_name", value={"name": "Asha (claims desk)"}))
        session.commit()
    result = _reset(client)
    assert "app_settings" in result["preserved"]
    with SessionLocal() as session:
        assert session.get(AppSetting, "operator_display_name").value == {"name": "Asha (claims desk)"}


def test_reset_recreates_and_verifies_demo_data(client, workspace):
    result = _reset(client)["demo_data"]
    assert result["files"] == 18
    assert result["verified"] is True
    assert result["generator_matches_manifest"] is True
    assert result["mismatched_files"] == []
    assert result["manifest_sha256"] == hashlib.sha256((TEST_DEMO_DATA / "manifest.json").read_bytes()).hexdigest()


def test_reset_restores_missing_or_modified_demo_files(client, workspace):
    scan = TEST_DEMO_DATA / "later" / "scan_0042.pdf"
    bill = TEST_DEMO_DATA / "initial" / "12_Main_Hospital_Bill.pdf"
    expected = {p: p.read_bytes() for p in (scan, bill)}
    scan.unlink()
    bill.write_bytes(b"tampered")
    result = _reset(client)["demo_data"]
    assert result["written"] == 2
    assert result["verified"] is True
    assert all(path.read_bytes() == content for path, content in expected.items())


def test_reset_is_audited(client, workspace):
    _reset(client)
    events = client.get("/api/audit", params={"event_type": "demo_reset"}).json()
    assert len(events) == 1
    event = events[0]
    assert event["claim_id"] is None
    assert event["actor"] == "Demo Operator"
    assert event["details"]["next_claim_number"] == "CLM-2026-00123"
    assert event["details"]["demo_data"]["verified"] is True


def test_demo_profile_matches_the_generated_claim(client):
    profile = client.get("/api/demo/profile").json()
    assert profile == {k: v for k, v in DEMO_CLAIM.items() if k != "is_demo"}
    assert profile == manifest()["claim"]


def test_initial_demo_pack_goes_through_the_upload_pipeline(client, claim):
    response = client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": "initial"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["set"] == "initial"
    assert body["attached_count"] == 16
    assert body["skipped_count"] == 0
    documents = body["documents"]

    expected = {e["filename"]: e for e in manifest()["sets"]["initial"]}
    assert [d["filename"] for d in documents] == list(expected)
    for document in documents:
        entry = expected[document["filename"]]
        assert document["source"] == "demo_pack"
        assert document["demo_set"] == "initial"
        assert document["upload_status"] == "uploaded"
        assert document["processing_status"] == "pending"
        assert document["sha256"] == entry["sha256"]
        assert document["size_bytes"] == entry["size_bytes"]
        assert document["page_count"] == entry["pages"]
        assert document["content_type"] == entry["media_type"]

    with SessionLocal() as session:
        for document in documents:
            path = absolute_storage_path(session.get(Document, document["id"]).storage_path)
            assert path.parent == claims_root() / claim["id"] / "originals"
            assert stat.S_IMODE(path.stat().st_mode) == 0o444
            assert hashlib.sha256(path.read_bytes()).hexdigest() == document["sha256"]

    events = client.get(f"/api/claims/{claim['id']}/audit").json()
    types = [e["event_type"] for e in events]
    assert types.count("document_uploaded") == 16
    assert types.count("demo_pack_attached") == 1
    assert all(e["details"]["source"] == "demo_pack" for e in events if e["event_type"] == "document_uploaded")


def test_demo_pack_matches_a_manual_upload_of_the_same_files(client, claim):
    manual = upload(client, claim["id"], pack_files()).json()["documents"]
    other = client.post("/api/claims", json=DEMO_CLAIM).json()
    demo = client.post(f"/api/claims/{other['id']}/demo-documents", params={"set": "initial"}).json()["documents"]
    comparable = ("filename", "content_type", "size_bytes", "sha256", "page_count", "file_metadata",
                  "upload_status", "processing_status")
    assert [{k: d[k] for k in comparable} for d in manual] == [{k: d[k] for k in comparable} for d in demo]


def test_get_request_is_supported_and_idempotent(client, claim):
    url = f"/api/claims/{claim['id']}/demo-documents"
    first = client.get(url, params={"set": "initial"}).json()
    second = client.get(url, params={"set": "initial"}).json()
    assert (first["attached_count"], first["skipped_count"]) == (16, 0)
    assert (second["attached_count"], second["skipped_count"]) == (0, 16)
    assert second["documents"] == []
    assert second["skipped"][0] == {"filename": "01_Patient_ID.png", "reason": "Already attached to this claim"}
    assert client.get(f"/api/claims/{claim['id']}").json()["document_count"] == 16


@pytest.mark.parametrize(
    ("set_name", "filename", "pages"),
    [("operative_note", "scan_0042.pdf", 2), ("anaesthesia_record", "Anaesthesia_Record.pdf", 2)],
)
def test_later_demo_documents(client, claim, set_name, filename, pages):
    response = client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": set_name})
    assert response.status_code == 200
    documents = response.json()["documents"]
    assert [(d["filename"], d["page_count"], d["demo_set"]) for d in documents] == [(filename, pages, set_name)]


def test_demo_documents_require_a_valid_set(client, claim):
    url = f"/api/claims/{claim['id']}/demo-documents"
    assert client.post(url).status_code == 422
    assert client.post(url, params={"set": "everything"}).status_code == 422
    assert client.post("/api/claims/missing/demo-documents", params={"set": "initial"}).status_code == 404


def test_tampered_demo_file_is_refused(client, claim):
    target = TEST_DEMO_DATA / "initial" / "07_Prescription.pdf"
    original = target.read_bytes()
    target.write_bytes(original + b"\n% tampered")
    try:
        response = client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": "initial"})
    finally:
        target.write_bytes(original)
    assert response.status_code == 409
    assert "07_Prescription.pdf does not match the demo manifest" in response.json()["detail"]
    assert client.get(f"/api/claims/{claim['id']}").json()["documents"] == []


def test_demo_files_can_be_listed_and_downloaded(client):
    sets = client.get("/api/demo/files").json()
    assert [s["set"] for s in sets] == ["initial", "operative_note", "anaesthesia_record"]
    assert len(sets[0]["files"]) == 16
    scan = sets[1]["files"][0]
    assert scan["filename"] == "scan_0042.pdf"
    response = client.get(scan["download_url"])
    assert response.status_code == 200
    assert hashlib.sha256(response.content).hexdigest() == scan["sha256"]
    assert client.get("/api/demo/files/initial/../../manifest.json").status_code == 404
    assert client.get("/api/demo/files/initial/unknown.pdf").status_code == 404

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import make_engine
from app.models import Claim, Document
from tests.conftest import DEMO_CLAIM, pack_files, upload


def test_first_claim_after_reset_is_clm_2026_00123(claim):
    assert claim["claim_number"] == "CLM-2026-00123"
    assert claim["status"] == "draft"
    assert claim["is_demo"] is True
    assert claim["document_count"] == 0
    assert claim["created_by"] == "Demo Operator"


def test_claim_numbers_increment(client, workspace):
    numbers = [client.post("/api/claims", json=DEMO_CLAIM).json()["claim_number"] for _ in range(3)]
    assert numbers == ["CLM-2026-00123", "CLM-2026-00124", "CLM-2026-00125"]


def test_concurrent_claim_creation_yields_unique_sequential_numbers(client, workspace):
    with ThreadPoolExecutor(max_workers=8) as pool:
        responses = list(pool.map(lambda _: client.post("/api/claims", json=DEMO_CLAIM), range(16)))
    assert all(r.status_code == 201 for r in responses)
    numbers = sorted(r.json()["claim_number"] for r in responses)
    assert numbers == [f"CLM-2026-{n:05d}" for n in range(123, 139)]


def test_claim_fields_are_stored_as_submitted(claim, client):
    detail = client.get(f"/api/claims/{claim['id']}").json()
    for field in ("patient_name", "uhid", "hospital", "insurer", "tpa", "admission_date", "discharge_date"):
        assert detail[field] == DEMO_CLAIM[field]
    assert detail["documents"] == []
    created = datetime.fromisoformat(detail["created_at"])
    assert created.tzinfo is not None
    assert abs((datetime.now(UTC) - created).total_seconds()) < 60


def test_whitespace_is_trimmed_and_blank_tpa_becomes_null(client, workspace):
    payload = {**DEMO_CLAIM, "patient_name": "  Rajesh Sharma  ", "tpa": "   "}
    body = client.post("/api/claims", json=payload).json()
    assert body["patient_name"] == "Rajesh Sharma"
    assert body["tpa"] is None


def test_discharge_before_admission_is_rejected(client, workspace):
    response = client.post("/api/claims", json={**DEMO_CLAIM, "discharge_date": "2026-01-10"})
    assert response.status_code == 422
    assert "Discharge date cannot be before the admission date" in response.text


def test_required_fields_are_validated(client, workspace):
    response = client.post("/api/claims", json={"patient_name": "R"})
    assert response.status_code == 422
    missing = {tuple(error["loc"])[-1] for error in response.json()["detail"]}
    assert {"uhid", "hospital", "insurer", "admission_date", "discharge_date"} <= missing
    assert client.get("/api/claims").json() == []


def test_rejected_claim_does_not_consume_a_number(client, workspace):
    client.post("/api/claims", json={**DEMO_CLAIM, "discharge_date": "2026-01-01"})
    assert client.post("/api/claims", json=DEMO_CLAIM).json()["claim_number"] == "CLM-2026-00123"


def test_list_claims_includes_document_counts(client, claim):
    upload(client, claim["id"], pack_files()[:3])
    other = client.post("/api/claims", json=DEMO_CLAIM).json()
    listed = {c["claim_number"]: c for c in client.get("/api/claims").json()}
    assert listed[claim["claim_number"]]["document_count"] == 3
    assert listed[claim["claim_number"]]["status"] == "documents_uploaded"
    assert listed[other["claim_number"]]["document_count"] == 0


def test_claim_creation_is_audited(client, claim):
    events = client.get(f"/api/claims/{claim['id']}/audit").json()
    assert [e["event_type"] for e in events] == ["claim_created"]
    assert events[0]["details"] == {"claim_number": "CLM-2026-00123", "is_demo": True}
    assert events[0]["actor"] == "Demo Operator"


def test_unknown_claim_returns_404(client, workspace):
    assert client.get("/api/claims/does-not-exist").status_code == 404
    assert client.get("/api/claims/does-not-exist/audit").status_code == 404


def test_claims_and_documents_persist_in_the_database(client, claim):
    upload(client, claim["id"], pack_files()[:2])
    # Read back through a brand-new engine: the data must be in the database, not just in memory.
    fresh_engine = make_engine(get_settings().database_url)
    try:
        with Session(fresh_engine) as session:
            stored = session.scalars(select(Claim).where(Claim.claim_number == "CLM-2026-00123")).one()
            assert stored.patient_name == "Rajesh Sharma"
            assert stored.admission_date.isoformat() == "2026-01-12"
            documents = session.scalars(select(Document).where(Document.claim_id == stored.id)).all()
            assert sorted(d.original_filename for d in documents) == ["01_Patient_ID.png", "02_Admission_Form.pdf"]
            assert all(len(d.sha256) == 64 for d in documents)
    finally:
        fresh_engine.dispose()


def test_control_characters_are_rejected(client, workspace):
    response = client.post("/api/claims", json={**DEMO_CLAIM, "patient_name": "Rajesh\x00Sharma"})
    assert response.status_code == 422
    assert "control characters" in response.text
    assert client.get("/api/claims").json() == []


def test_malformed_claim_ids_are_not_found(client, workspace):
    for claim_id in ("not-a-uuid", "%00", "123"):
        assert client.get(f"/api/claims/{claim_id}").status_code == 404
        assert client.get(f"/api/claims/{claim_id}/audit").status_code == 404

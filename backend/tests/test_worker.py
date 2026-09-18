"""The processing worker: queueing, order, recovery and failure isolation."""

import threading
import time

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import make_engine
from app.models import Document, DocumentPage, ExtractedField
from app.services import analysis as analysis_service
from tests.conftest import analyse, pack_files, pick, upload

SMALL_PACK = ("02_Admission_Form.pdf", "12_Main_Hospital_Bill.pdf", "16_Consent_Form.pdf")


def attach(client, claim_id: str, *names: str):
    response = upload(client, claim_id, pick(pack_files(), *names))
    assert response.status_code == 201, response.text
    return response.json()["documents"]


def stored_documents(claim_id: str) -> list[dict]:
    """Read the documents back through a fresh engine, as plain values."""
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            documents = session.scalars(
                select(Document).where(Document.claim_id == claim_id).order_by(Document.uploaded_at)
            ).all()
            return [
                {
                    "id": document.id,
                    "filename": document.original_filename,
                    "storage_path": document.storage_path,
                    "processing_status": document.processing_status,
                    "doc_type": document.doc_type,
                    "duration_ms": document.processing_duration_ms,
                    "page_rows": len(document.pages),
                    "field_rows": len(document.fields),
                }
                for document in documents
            ]
    finally:
        engine.dispose()


def test_the_worker_processes_queued_documents(client, claim, worker):
    attach(client, claim["id"], *SMALL_PACK)
    state = analyse(client, claim["id"])
    assert state["state"] == "completed"
    assert state["counts"]["processed"] == 3
    assert state["progress"] == 1.0
    assert worker.stats()["queue_depth"] == 0
    # Results are in the database, not only in memory.
    for document in stored_documents(claim["id"]):
        assert document["processing_status"] == "processed"
        assert document["doc_type"]
        assert document["page_rows"] >= 1
        assert document["field_rows"] >= 1
        assert document["duration_ms"] is not None


def test_documents_are_processed_in_the_order_they_were_queued(client, claim, worker):
    attach(client, claim["id"], *SMALL_PACK)
    analyse(client, claim["id"])
    events = [
        event
        for event in client.get(f"/api/claims/{claim['id']}/audit").json()
        if event["event_type"] == "document_processed"
    ]
    assert [event["details"]["doc_type"] for event in events] == ["admission_record", "hospital_bill", "consent"]
    identifiers = [event["id"] for event in events]
    assert identifiers == sorted(identifiers), "audit order must follow the queue order"


def test_queueing_is_recorded_and_the_claim_moves_to_processing(client, claim):
    attach(client, claim["id"], "02_Admission_Form.pdf")
    analyse(client, claim["id"])
    types = [event["event_type"] for event in client.get(f"/api/claims/{claim['id']}/audit").json()]
    assert types == [
        "claim_created",
        "document_uploaded",
        "claim_analysis_started",
        "document_processed",
        "claim_analysis_completed",
        # Analysis is followed by validation over what was just read.
        "validation_completed",
    ]
    assert client.get(f"/api/claims/{claim['id']}").json()["status"] == "processed"


def test_analysis_is_visible_stage_by_stage(client, claim, worker, monkeypatch):
    """With demo pacing on, the API shows the pipeline moving through its stages."""
    monkeypatch.setattr(get_settings(), "demo_pacing_ms", 60)
    attach(client, claim["id"], "06_Discharge_Summary.pdf", "12_Main_Hospital_Bill.pdf")
    seen: set[str] = set()
    statuses: set[str] = set()

    response = client.post(f"/api/claims/{claim['id']}/analyze")
    assert response.status_code == 202
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        state = client.get(f"/api/claims/{claim['id']}/processing").json()
        for document in state["documents"]:
            statuses.add(document["processing_status"])
            if document["processing_stage"]:
                seen.add(document["processing_stage"])
        if state["state"] != "running":
            break
        time.sleep(0.03)
    assert worker.wait_idle(60)
    assert "processing" in statuses
    # The stage names are the ones the API publishes for the timeline.
    published = {stage["key"] for stage in client.get(f"/api/claims/{claim['id']}/processing").json()["stages"]}
    assert seen <= published
    assert len(seen & {"rendering", "quality", "classification", "extraction", "evidence"}) >= 2, seen


def test_unfinished_documents_are_requeued_after_a_restart(client, claim, worker):
    """A restart in the middle of a run must not leave documents stuck."""
    attach(client, claim["id"], "02_Admission_Form.pdf", "10_Lab_Report.pdf")
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            documents = session.scalars(select(Document).where(Document.claim_id == claim["id"])).all()
            documents[0].processing_status = "processing"  # interrupted mid-flight
            documents[0].processing_stage = "ocr"
            documents[1].processing_status = "queued"  # queued but never started
            session.commit()
    finally:
        engine.dispose()

    requeued = worker.recover()
    assert len(requeued) == 2
    assert worker.wait_idle(120)
    state = client.get(f"/api/claims/{claim['id']}/processing").json()
    assert state["counts"]["processed"] == 2
    assert any(
        event["event_type"] == "processing_requeued" for event in client.get("/api/audit").json()
    )


def test_a_document_that_cannot_be_read_does_not_stop_the_claim(client, claim, worker):
    """One unreadable document fails on its own; the rest of the claim is still analysed."""
    documents = attach(client, claim["id"], "02_Admission_Form.pdf", "10_Lab_Report.pdf", "16_Consent_Form.pdf")
    missing = documents[1]
    # Simulate storage loss for one document: its original is gone when the worker reaches it.
    stored = next(d for d in stored_documents(claim["id"]) if d["id"] == missing["id"])
    (get_settings().storage_dir / stored["storage_path"]).unlink()

    state = analyse(client, claim["id"])
    assert state["state"] == "completed_with_failures"
    assert state["counts"]["processed"] == 2
    assert state["counts"]["failed"] == 1
    failed = next(d for d in state["documents"] if d["document_id"] == missing["id"])
    assert failed["processing_status"] == "failed"
    assert "missing from storage" in failed["processing_error"]
    assert client.get(f"/api/claims/{claim['id']}").json()["status"] == "processed"
    assert any(
        event["event_type"] == "document_processing_failed"
        for event in client.get(f"/api/claims/{claim['id']}/audit").json()
    )


def test_an_unexpected_error_is_contained(client, claim, worker, monkeypatch):
    from app import worker as worker_module

    documents = attach(client, claim["id"], "02_Admission_Form.pdf", "10_Lab_Report.pdf")
    real = worker_module.process_file

    def explode(path, **kwargs):
        if kwargs["document_id"] == documents[0]["id"]:
            raise MemoryError("simulated native failure")
        return real(path, **kwargs)

    monkeypatch.setattr(worker_module, "process_file", explode)
    state = analyse(client, claim["id"])
    assert state["counts"] == {"pending": 0, "queued": 0, "processing": 0, "processed": 1, "failed": 1}
    failed = next(d for d in state["documents"] if d["document_id"] == documents[0]["id"])
    assert "MemoryError" in failed["processing_error"]
    assert worker.stats()["running"] is True, "the worker thread keeps running"


def test_failed_documents_are_retried_by_a_new_analysis_run(client, claim, worker, monkeypatch):
    from app import worker as worker_module

    documents = attach(client, claim["id"], "02_Admission_Form.pdf")
    real = worker_module.process_file
    monkeypatch.setattr(worker_module, "process_file", lambda path, **kwargs: (_ for _ in ()).throw(RuntimeError("nope")))
    assert analyse(client, claim["id"])["counts"]["failed"] == 1

    monkeypatch.setattr(worker_module, "process_file", real)
    state = analyse(client, claim["id"])
    assert state["counts"]["processed"] == 1
    assert state["counts"]["failed"] == 0
    processing = client.get(f"/api/documents/{documents[0]['id']}/processing").json()
    assert processing["processing_status"] == "processed"


def test_processing_again_does_not_duplicate_results(client, claim, worker):
    documents = attach(client, claim["id"], "12_Main_Hospital_Bill.pdf")
    analyse(client, claim["id"])
    first = client.get(f"/api/documents/{documents[0]['id']}/analysis").json()

    # Re-run the document through the worker directly: stored results are replaced, not appended.
    worker.submit([documents[0]["id"]])
    assert worker.wait_idle(120)
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            pages = session.scalars(select(DocumentPage).where(DocumentPage.document_id == documents[0]["id"])).all()
            fields = session.scalars(select(ExtractedField).where(ExtractedField.document_id == documents[0]["id"])).all()
    finally:
        engine.dispose()
    assert len(pages) == len(first["pages"])
    assert len(fields) == len(first["fields"])


def test_analysis_never_modifies_the_originals(client, claim):
    documents = attach(client, claim["id"], *SMALL_PACK)
    stored = {d["id"]: get_settings().storage_dir / d["storage_path"] for d in stored_documents(claim["id"])}
    before = {
        document["id"]: (stored[document["id"]].read_bytes(), stored[document["id"]].stat().st_mode)
        for document in documents
    }
    analyse(client, claim["id"])
    for document in documents:
        path = stored[document["id"]]
        content, mode = before[document["id"]]
        assert path.read_bytes() == content
        assert path.stat().st_mode == mode, "originals stay read-only"
        assert oct(path.stat().st_mode)[-3:] == "444"
        served = client.get(f"/api/documents/{document['id']}/file")
        assert served.status_code == 200
        assert served.content == content


def test_page_images_are_written_beside_the_originals_not_over_them(client, claim):
    documents = attach(client, claim["id"], "06_Discharge_Summary.pdf")
    analyse(client, claim["id"])
    claim_dir = get_settings().storage_dir / "claims" / claim["id"]
    originals = sorted(p.name for p in (claim_dir / "originals").iterdir())
    pages = sorted(p.name for p in (claim_dir / "pages" / documents[0]["id"]).iterdir())
    assert len(originals) == 1
    assert pages == ["p0001.png", "p0002.png", "p0003.png"]


def test_a_demo_reset_clears_the_queue_and_the_analysis(client, claim, worker):
    attach(client, claim["id"], *SMALL_PACK)
    client.post(f"/api/claims/{claim['id']}/analyze")
    reset = client.post("/api/demo/reset", json={"confirm": True})
    assert reset.status_code == 200, reset.text
    assert worker.wait_idle(120)
    assert client.get("/api/claims").json() == []
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            assert session.scalars(select(DocumentPage)).all() == []
            assert session.scalars(select(ExtractedField)).all() == []
    finally:
        engine.dispose()


def test_queue_documents_only_takes_unprocessed_ones(client, claim, worker):
    from app.db import SessionLocal
    from app.models import Claim

    attach(client, claim["id"], "02_Admission_Form.pdf")
    analyse(client, claim["id"])
    attach(client, claim["id"], "10_Lab_Report.pdf")
    with SessionLocal() as session:
        stored_claim = session.get(Claim, claim["id"])
        queued = analysis_service.queue_documents(session, stored_claim)
    assert len(queued) == 1
    worker.submit(queued)
    assert worker.wait_idle(120)
    state = client.get(f"/api/claims/{claim['id']}/processing").json()
    assert state["counts"]["processed"] == 2


def test_the_worker_runs_on_its_own_thread(client, claim, worker):
    """A request must never do the heavy work itself."""
    attach(client, claim["id"], "02_Admission_Form.pdf")
    request_thread = threading.current_thread().name
    client.post(f"/api/claims/{claim['id']}/analyze")
    assert worker.wait_idle(120)
    assert worker.stats()["processed"] >= 1
    assert request_thread != "claimai-processing"
    assert any(thread.name == "claimai-processing" for thread in threading.enumerate())

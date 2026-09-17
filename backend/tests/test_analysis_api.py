"""The analysis API: starting a run, following it, and reading the results."""

import pytest

from tests.conftest import analyse, pack_files, pick, upload

PACK = ("15_Implant_Invoice.pdf", "16_Consent_Form.pdf", "09_USG_Abdomen_Scan.jpg")


@pytest.fixture
def analysed(client, claim):
    response = upload(client, claim["id"], pick(pack_files(), *PACK))
    assert response.status_code == 201, response.text
    documents = {document["filename"]: document for document in response.json()["documents"]}
    state = analyse(client, claim["id"])
    return {"claim": claim, "documents": documents, "state": state}


def test_analyze_accepts_the_work_and_reports_the_stages(client, claim):
    upload(client, claim["id"], pick(pack_files(), "02_Admission_Form.pdf"))
    response = client.post(f"/api/claims/{claim['id']}/analyze")
    assert response.status_code == 202
    body = response.json()
    assert body["claim_number"] == claim["claim_number"]
    assert [stage["key"] for stage in body["stages"]] == [
        "queued",
        "rendering",
        "ocr",
        "quality",
        "classification",
        "extraction",
        "evidence",
        "completed",
    ]
    assert all(stage["label"] for stage in body["stages"])
    assert body["document_count"] == 1
    assert body["worker"]["running"] is True


def test_analyze_a_claim_without_documents_is_harmless(client, claim, worker):
    response = client.post(f"/api/claims/{claim['id']}/analyze")
    assert response.status_code == 202
    body = response.json()
    assert body["state"] == "idle"
    assert body["document_count"] == 0
    assert body["documents"] == []
    assert worker.wait_idle(30)
    assert client.get(f"/api/claims/{claim['id']}").json()["status"] == "draft"


def test_processing_state_after_a_finished_run(analysed):
    state = analysed["state"]
    assert state["state"] == "completed"
    assert state["counts"]["processed"] == 3
    assert state["progress"] == 1.0
    assert state["started_at"] and state["completed_at"]
    by_name = {document["filename"]: document for document in state["documents"]}
    assert by_name["15_Implant_Invoice.pdf"]["doc_type"] == "implant_invoice"
    assert by_name["15_Implant_Invoice.pdf"]["doc_type_label"] == "Implant invoice"
    assert by_name["15_Implant_Invoice.pdf"]["concealed_text_count"] == 1
    assert by_name["16_Consent_Form.pdf"]["quality_flag_counts"]["review"] == 1
    assert by_name["09_USG_Abdomen_Scan.jpg"]["ocr_engine"] in {"rapidocr", "demo_fixture"}
    assert by_name["09_USG_Abdomen_Scan.jpg"]["quality_flag_counts"]["total"] >= 2


def test_document_processing_endpoint(client, analysed):
    document = analysed["documents"]["16_Consent_Form.pdf"]
    body = client.get(f"/api/documents/{document['id']}/processing").json()
    assert body["processing_status"] == "processed"
    assert body["processing_stage"] == "completed"
    assert body["stage_label"] == "Completed"
    assert body["progress"] == 1.0
    assert body["doc_type"] == "consent"


def test_document_analysis_payload(client, analysed):
    document = analysed["documents"]["15_Implant_Invoice.pdf"]
    body = client.get(f"/api/documents/{document['id']}/analysis").json()

    assert body["document"]["filename"] == "15_Implant_Invoice.pdf"
    assert body["classification"] == {
        "doc_type": "implant_invoice",
        "label": "Implant invoice",
        "confidence": pytest.approx(0.94, abs=0.05),
        "method": "content_rules_title",
        "signals": body["classification"]["signals"],
        "scores": body["classification"]["scores"],
    }
    assert body["page_render_dpi"] == 150
    assert len(body["pages"]) == 1
    page = body["pages"][0]
    assert page["image_url"] == f"/api/documents/{document['id']}/pages/1/image"
    assert page["text_source"] == "pdf_text"
    assert page["concealed_count"] == 1

    assert body["concealed_spans"] == [
        {
            "page_number": 1,
            "text": "1,000.00",
            "coverage": 1.0,
            "bbox": body["concealed_spans"][0]["bbox"],
        }
    ]
    assert all(0 <= value <= 1 for value in body["concealed_spans"][0]["bbox"])

    assert body["bill"]["total"] == "6600.00"
    assert body["bill"]["line_items"][0]["rate"] == "1100.00"
    assert body["signatures"]["method"] == "vector_ink"
    codes = {flag["code"] for flag in body["quality_flags"]}
    assert "concealed_text" in codes


def test_extracted_fields_carry_their_evidence(client, analysed):
    document = analysed["documents"]["15_Implant_Invoice.pdf"]
    fields = client.get(f"/api/documents/{document['id']}/fields").json()
    assert fields
    for field in fields:
        assert field["evidence_available"] is True
        assert field["page_number"] == 1
        assert len(field["bbox"]) == 4
        assert all(0 <= value <= 1 for value in field["bbox"])
        assert field["snippet"]
        assert field["method"].startswith("pdf_text:")
        assert "1,000.00" not in (field["value"] or "") and "1,000.00" not in field["snippet"]
    keys = {field["key"] for field in fields}
    assert {"billing.bill_number", "billing.total", "patient.name"} <= keys


def test_fields_can_be_filtered_by_group(client, analysed):
    document = analysed["documents"]["15_Implant_Invoice.pdf"]
    billing = client.get(f"/api/documents/{document['id']}/fields", params={"group": "billing"}).json()
    assert billing and all(field["group"] == "billing" for field in billing)
    assert client.get(f"/api/documents/{document['id']}/fields", params={"group": "nope"}).json() == []


def test_signature_slots_are_reported_per_document(client, analysed):
    document = analysed["documents"]["16_Consent_Form.pdf"]
    signatures = client.get(f"/api/documents/{document['id']}/analysis").json()["signatures"]
    slots = {slot["key"]: slot for slot in signatures["slots"] if slot["key"]}
    assert slots["patient_guardian"]["signed"] is False
    assert slots["patient_guardian"]["required"] is True
    assert slots["patient_guardian"]["bbox"]
    assert slots["witness"]["signed"] is True


def test_page_endpoints(client, analysed):
    document = analysed["documents"]["16_Consent_Form.pdf"]
    pages = client.get(f"/api/documents/{document['id']}/pages").json()
    assert len(pages) == 1
    detail = client.get(f"/api/documents/{document['id']}/pages/1").json()
    assert "INFORMED CONSENT" in detail["text"]
    assert detail["document_id"] == document["id"]
    assert detail["word_count"] > 100

    image = client.get(f"/api/documents/{document['id']}/pages/1/image")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert int(image.headers["content-length"]) == len(image.content)


def test_page_requests_beyond_the_document_are_rejected(client, analysed):
    document = analysed["documents"]["16_Consent_Form.pdf"]
    assert client.get(f"/api/documents/{document['id']}/pages/9").status_code == 404
    assert client.get(f"/api/documents/{document['id']}/pages/9/image").status_code == 404
    assert client.get(f"/api/documents/{document['id']}/pages/0").status_code == 422
    assert client.get(f"/api/documents/{document['id']}/pages/-1/image").status_code == 422


def test_reading_an_unprocessed_document_says_so(client, claim):
    response = upload(client, claim["id"], pick(pack_files(), "02_Admission_Form.pdf"))
    document = response.json()["documents"][0]
    analysis = client.get(f"/api/documents/{document['id']}/analysis").json()
    assert analysis["processing"]["processing_status"] == "pending"
    assert analysis["classification"]["doc_type"] is None
    assert analysis["pages"] == []
    assert analysis["fields"] == []
    assert analysis["bill"] is None
    page = client.get(f"/api/documents/{document['id']}/pages/1")
    assert page.status_code == 404
    assert "has not been processed yet" in page.json()["detail"]


def test_unknown_identifiers_are_not_found(client, workspace):
    for path in (
        "/api/claims/does-not-exist/processing",
        "/api/claims/%00/processing",
        "/api/documents/does-not-exist/analysis",
        "/api/documents/does-not-exist/fields",
        "/api/documents/does-not-exist/pages",
        "/api/documents/does-not-exist/pages/1",
        "/api/documents/does-not-exist/pages/1/image",
        "/api/documents/does-not-exist/processing",
    ):
        assert client.get(path).status_code == 404, path
    assert client.post("/api/claims/does-not-exist/analyze").status_code == 404


def test_the_document_list_shows_the_classification_after_analysis(client, analysed):
    claim = client.get(f"/api/claims/{analysed['claim']['id']}").json()
    by_name = {document["filename"]: document for document in claim["documents"]}
    invoice = by_name["15_Implant_Invoice.pdf"]
    assert invoice["doc_type"] == "implant_invoice"
    assert invoice["doc_type_label"] == "Implant invoice"
    assert invoice["stage_label"] == "Completed"
    assert invoice["concealed_text_count"] == 1
    # The covered text itself is not part of a document listing.
    assert "concealed_spans" not in invoice
    assert {flag["code"] for flag in invoice["quality_flags"]} == {"concealed_text"}


def test_health_reports_the_ocr_path(client):
    body = client.get("/api/health").json()
    assert body["ocr"]["offline"] is True
    assert body["ocr"]["preference"] in {"auto", "rapidocr", "demo_fixture", "none"}
    assert "demo_fixture" in body["ocr"]["engines"]
    assert body["ocr"]["active"] in {"rapidocr", "demo_fixture", None}
    keys = {engine["key"] for engine in body["engines"]}
    assert {"pymupdf", "rapidocr", "onnxruntime", "opencv"} <= keys


def test_the_new_routes_are_documented(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    for path in (
        "/api/claims/{claim_id}/analyze",
        "/api/claims/{claim_id}/processing",
        "/api/documents/{document_id}/analysis",
        "/api/documents/{document_id}/fields",
        "/api/documents/{document_id}/pages",
        "/api/documents/{document_id}/pages/{page_number}",
        "/api/documents/{document_id}/pages/{page_number}/image",
        "/api/documents/{document_id}/processing",
    ):
        assert path in paths, path
    assert "post" in paths["/api/claims/{claim_id}/analyze"]
    assert client.put("/api/claims/does-not-exist/analyze").status_code == 405

import hashlib
import stat

import pytest

from app.config import get_settings
from app.storage import absolute_storage_path, claims_root
from tests.conftest import manifest, pack_files, upload

INITIAL_FILENAMES = [
    "01_Patient_ID.png",
    "02_Admission_Form.pdf",
    "03_Doctor_Consultation.pdf",
    "04_PreOp_Assessment.pdf",
    "05_Anaesthesia_Assessment.pdf",
    "06_Discharge_Summary.pdf",
    "07_Prescription.pdf",
    "08_Nursing_Record.pdf",
    "09_USG_Abdomen_Scan.jpg",
    "10_Lab_Report.pdf",
    "11_Lab_Report_copy.pdf",
    "12_Main_Hospital_Bill.pdf",
    "13_Pharmacy_Bill.pdf",
    "14_OT_Bill.pdf",
    "15_Implant_Invoice.pdf",
    "16_Consent_Form.pdf",
]


@pytest.fixture
def uploaded(client, claim):
    files = pack_files("initial")
    response = upload(client, claim["id"], files)
    assert response.status_code == 201, response.text
    return {"claim": claim, "files": files, "documents": response.json()["documents"]}


def test_sixteen_files_upload_in_one_request(uploaded, client):
    documents = uploaded["documents"]
    assert [d["filename"] for d in documents] == INITIAL_FILENAMES
    assert len({d["id"] for d in documents}) == 16
    assert all(d["upload_status"] == "uploaded" for d in documents)
    assert all(d["processing_status"] == "pending" for d in documents)
    assert all(d["source"] == "upload" and d["demo_set"] is None for d in documents)
    assert all(d["uploaded_by"] == "Demo Operator" for d in documents)

    detail = client.get(f"/api/claims/{uploaded['claim']['id']}").json()
    assert detail["status"] == "documents_uploaded"
    assert detail["document_count"] == 16


def test_document_metadata(uploaded):
    by_name = {d["filename"]: d for d in uploaded["documents"]}
    expected_pages = {e["filename"]: e["pages"] for e in manifest()["sets"]["initial"]}
    assert {name: d["page_count"] for name, d in by_name.items()} == expected_pages
    assert by_name["06_Discharge_Summary.pdf"]["page_count"] == 3
    assert by_name["08_Nursing_Record.pdf"]["page_count"] == 2

    assert by_name["02_Admission_Form.pdf"]["content_type"] == "application/pdf"
    assert by_name["02_Admission_Form.pdf"]["file_metadata"] == {"pdf_version": "PDF 1.4"}
    card = by_name["01_Patient_ID.png"]
    assert card["content_type"] == "image/png"
    assert card["file_metadata"] == {"width": 1012, "height": 638, "mode": "RGB", "dpi": [300, 300]}
    scan = by_name["09_USG_Abdomen_Scan.jpg"]
    assert scan["content_type"] == "image/jpeg"
    assert scan["file_metadata"]["dpi"] == [96, 96]
    for name, content, _ in uploaded["files"]:
        assert by_name[name]["size_bytes"] == len(content)


def test_sha256_is_recorded_for_every_original(uploaded):
    by_name = {d["filename"]: d for d in uploaded["documents"]}
    manifest_hashes = {e["filename"]: e["sha256"] for e in manifest()["sets"]["initial"]}
    for name, content, _ in uploaded["files"]:
        assert by_name[name]["sha256"] == hashlib.sha256(content).hexdigest() == manifest_hashes[name]


def test_byte_identical_files_are_kept_as_separate_documents(uploaded):
    by_name = {d["filename"]: d for d in uploaded["documents"]}
    original, copy = by_name["10_Lab_Report.pdf"], by_name["11_Lab_Report_copy.pdf"]
    assert original["sha256"] == copy["sha256"]
    assert original["id"] != copy["id"]


def test_originals_are_stored_read_only_and_unchanged(uploaded, client):
    from app.db import SessionLocal
    from app.models import Document

    content_by_name = {name: content for name, content, _ in uploaded["files"]}
    with SessionLocal() as session:
        for document in uploaded["documents"]:
            record = session.get(Document, document["id"])
            path = absolute_storage_path(record.storage_path)
            assert path.parent == claims_root() / uploaded["claim"]["id"] / "originals"
            assert path.name == f"{document['id']}{path.suffix}"
            assert stat.S_IMODE(path.stat().st_mode) == 0o444
            assert path.read_bytes() == content_by_name[document["filename"]]
            with pytest.raises(PermissionError):
                path.open("ab")
    # No temporary files are left behind.
    assert not list((claims_root() / uploaded["claim"]["id"] / "originals").glob(".*"))


def test_original_can_be_downloaded_byte_for_byte(uploaded, client):
    document = next(d for d in uploaded["documents"] if d["filename"] == "06_Discharge_Summary.pdf")
    response = client.get(f"/api/documents/{document['id']}/file")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert hashlib.sha256(response.content).hexdigest() == document["sha256"]
    assert client.get(f"/api/documents/{document['id']}").json()["filename"] == "06_Discharge_Summary.pdf"


def test_every_upload_is_audited(uploaded, client):
    events = client.get(f"/api/claims/{uploaded['claim']['id']}/audit").json()
    uploads = [e for e in events if e["event_type"] == "document_uploaded"]
    assert len(uploads) == 16
    assert {e["document_id"] for e in uploads} == {d["id"] for d in uploaded["documents"]}
    event = next(e for e in uploads if e["details"]["filename"] == "13_Pharmacy_Bill.pdf")
    document = next(d for d in uploaded["documents"] if d["filename"] == "13_Pharmacy_Bill.pdf")
    assert event["details"] == {
        "filename": "13_Pharmacy_Bill.pdf",
        "sha256": document["sha256"],
        "size_bytes": document["size_bytes"],
        "content_type": "application/pdf",
        "page_count": 1,
        "source": "upload",
        "demo_set": None,
    }
    assert event["message"] == "Uploaded 13_Pharmacy_Bill.pdf"


def _assert_nothing_stored(client, claim):
    detail = client.get(f"/api/claims/{claim['id']}").json()
    assert detail["documents"] == []
    assert detail["status"] == "draft"
    originals = claims_root() / claim["id"] / "originals"
    assert not originals.exists() or not any(originals.iterdir())
    events = client.get(f"/api/claims/{claim['id']}/audit").json()
    assert [e["event_type"] for e in events] == ["claim_created"]


def test_unsupported_file_rejects_the_whole_batch(client, claim):
    files = [*pack_files()[:2], ("notes.txt", b"hello", "text/plain")]
    response = upload(client, claim["id"], files)
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "1 of 3 file(s) could not be accepted. No files were stored."
    assert detail["errors"] == [
        {"filename": "notes.txt", "error": "Unsupported file type. Upload PDF, PNG or JPG files."}
    ]
    _assert_nothing_stored(client, claim)


@pytest.mark.parametrize(
    ("filename", "content", "error"),
    [
        ("scan.pdf", pack_files()[0][1], "File content does not match its .pdf extension"),
        ("photo.jpg", b"%PDF-1.4 not really a jpeg", "File content does not match its .jpg extension"),
        ("broken.pdf", b"%PDF-1.4\n%garbage without objects", "The PDF could not be read (corrupt or unsupported file)"),
        ("empty.pdf", b"", "File is empty"),
        ("truncated.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, "The image could not be read (corrupt or unsupported file)"),
    ],
)
def test_invalid_files_are_rejected(client, claim, filename, content, error):
    response = upload(client, claim["id"], [(filename, content, "application/octet-stream")])
    assert response.status_code == 422
    assert response.json()["detail"]["errors"] == [{"filename": filename, "error": error}]
    _assert_nothing_stored(client, claim)


def test_files_over_the_size_limit_are_rejected(client, claim):
    settings = get_settings()
    original_limit = settings.max_upload_mb
    settings.max_upload_mb = 1
    try:
        big = b"%PDF-1.4\n" + b"0" * (1024 * 1024 + 1)
        response = upload(client, claim["id"], [("big.pdf", big, "application/pdf")])
    finally:
        settings.max_upload_mb = original_limit
    assert response.status_code == 422
    assert response.json()["detail"]["errors"][0]["error"] == "File exceeds the 1 MB limit"
    _assert_nothing_stored(client, claim)


def test_path_components_are_stripped_from_filenames(client, claim):
    name, content, media_type = pack_files()[1]
    response = upload(client, claim["id"], [(f"../../etc/{name}", content, media_type)])
    assert response.status_code == 201
    assert response.json()["documents"][0]["filename"] == name


def test_upload_requires_files(client, claim):
    assert client.post(f"/api/claims/{claim['id']}/documents").status_code == 422


def test_upload_to_unknown_claim_returns_404(client, workspace):
    assert upload(client, "missing", pack_files()[:1]).status_code == 404


def test_unknown_document_returns_404(client, workspace):
    assert client.get("/api/documents/missing").status_code == 404
    assert client.get("/api/documents/missing/file").status_code == 404

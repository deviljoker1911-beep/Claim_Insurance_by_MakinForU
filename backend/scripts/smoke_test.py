"""End-to-end smoke test against a running ClaimAI API and the database it uses.

    uv run python scripts/smoke_test.py --reset [--base-url http://127.0.0.1:8010]

--reset is required because the test resets the demo workspace (all claims are deleted).
Database and storage checks use DATABASE_URL / STORAGE_DIR from the same .env as the API.
"""

import argparse
import hashlib
import json
import stat
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.models import (  # noqa: E402
    AuditEvent,
    Claim,
    ClaimState,
    Document,
    DocumentBill,
    DocumentPage,
    ExtractedField,
)


class SmokeFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)
    print(f"  ok  {message}")


def call(base: str, method: str, path: str, *, body: bytes | None = None, content_type: str | None = None):
    request = urllib.request.Request(f"{base}{path}", data=body, method=method)
    request.add_header("Accept", "application/json")
    if content_type:
        request.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            status, raw, ctype = response.status, response.read(), response.headers.get("Content-Type", "")
    except urllib.error.HTTPError as error:
        status, raw, ctype = error.code, error.read(), error.headers.get("Content-Type", "")
    return status, (json.loads(raw) if "application/json" in ctype else raw)


def post_json(base: str, path: str, payload: dict):
    return call(base, "POST", path, body=json.dumps(payload).encode(), content_type="application/json")


def multipart(files: list[tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = f"claimai-{uuid.uuid4().hex}"
    parts = []
    for name, content, media_type in files:
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{name}"\r\n'
            f"Content-Type: {media_type}\r\n\r\n".encode()
            + content
            + b"\r\n"
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument("--reset", action="store_true", help="confirm that the demo workspace may be reset")
    parser.add_argument("--allow-sqlite", action="store_true", help="do not require PostgreSQL")
    args = parser.parse_args()
    if not args.reset:
        parser.error("--reset is required: this smoke test deletes all claims in the workspace")

    base = args.base_url.rstrip("/")
    settings = get_settings()
    demo_dir = settings.demo_data_dir
    manifest = json.loads((demo_dir / "manifest.json").read_text(encoding="utf-8"))
    initial = [(e["filename"], (demo_dir / e["path"]).read_bytes(), e["media_type"]) for e in manifest["sets"]["initial"]]
    expected_hash = {e["filename"]: e["sha256"] for entries in manifest["sets"].values() for e in entries}

    print(f"ClaimAI smoke test against {base}")
    print("1. Health")
    status, health = call(base, "GET", "/api/health")
    check(status == 200 and health["status"] == "ok", "API healthy")
    dialect = health["database"]["dialect"]
    check(dialect == "postgresql" or args.allow_sqlite, f"database is {dialect} {health['database']['server_version']}")

    print("2. Demo reset")
    status, reset = post_json(base, "/api/demo/reset", {"confirm": True})
    check(status == 200, "reset accepted")
    check(reset["next_claim_number"] == "CLM-2026-00123", "next claim number is CLM-2026-00123")
    check(reset["demo_data"]["verified"] and reset["demo_data"]["files"] == 18, "18 demo files verified")

    print("3. Claim creation")
    status, profile = call(base, "GET", "/api/demo/profile")
    status, first = post_json(base, "/api/claims", {**profile, "is_demo": True})
    check(status == 201 and first["claim_number"] == "CLM-2026-00123", "first claim is CLM-2026-00123")
    status, second = post_json(base, "/api/claims", {**profile, "is_demo": True})
    check(second["claim_number"] == "CLM-2026-00124", "second claim is CLM-2026-00124")
    status, invalid = post_json(base, "/api/claims", {**profile, "discharge_date": "2026-01-01"})
    check(status == 422, "invalid dates rejected (422)")

    print("4. Multipart upload of 16 files in one request")
    body, content_type = multipart(initial)
    status, uploaded = call(base, "POST", f"/api/claims/{first['id']}/documents", body=body, content_type=content_type)
    check(status == 201 and len(uploaded["documents"]) == 16, "16 documents stored")
    check(all(d["sha256"] == expected_hash[d["filename"]] for d in uploaded["documents"]), "SHA-256 of every original matches")
    discharge = next(d for d in uploaded["documents"] if d["filename"] == "06_Discharge_Summary.pdf")
    check(discharge["page_count"] == 3, "discharge summary has 3 pages")
    status, original = call(base, "GET", f"/api/documents/{discharge['id']}/file")
    check(hashlib.sha256(original).hexdigest() == discharge["sha256"], "original downloads byte for byte")

    print("5. Demo document sets (same upload pipeline)")
    status, attached = call(base, "POST", f"/api/claims/{second['id']}/demo-documents?set=initial")
    check(status == 200 and attached["attached_count"] == 16, "initial set attached (16)")
    status, again = call(base, "GET", f"/api/claims/{second['id']}/demo-documents?set=initial")
    check(again["attached_count"] == 0 and again["skipped_count"] == 16, "GET is idempotent (16 skipped)")
    for set_name, filename in (("operative_note", "scan_0042.pdf"), ("anaesthesia_record", "Anaesthesia_Record.pdf")):
        status, later = call(base, "POST", f"/api/claims/{second['id']}/demo-documents?set={set_name}")
        check([d["filename"] for d in later["documents"]] == [filename], f"{set_name} set attached ({filename})")

    print("6. Document intelligence")
    status, state = call(base, "POST", f"/api/claims/{second['id']}/analyze")
    check(status == 202 and state["counts"]["queued"] == 18, f"18 documents queued: {state['counts']}")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        status, state = call(base, "GET", f"/api/claims/{second['id']}/processing")
        if state["state"] != "running":
            break
        time.sleep(0.4)
    check(state["state"] == "completed", f"analysis finished without failures: {state['counts']}")
    check(state["claim_status"] == "processed", "claim moved to processed")

    expected_types = {e["filename"]: e["expected_doc_type"] for entries in manifest["sets"].values() for e in entries}
    processed = {d["filename"]: d for d in state["documents"]}
    wrong = {name: (d["doc_type"], expected_types[name]) for name, d in processed.items() if d["doc_type"] != expected_types[name]}
    check(not wrong, f"all 18 documents classified from their content ({len(processed)} documents)")
    check(processed["scan_0042.pdf"]["doc_type"] == "operative_note", "scan_0042.pdf recognised as an operative note")
    check(
        processed["05_Anaesthesia_Assessment.pdf"]["doc_type"] == "anaesthesia_assessment"
        and processed["Anaesthesia_Record.pdf"]["doc_type"] == "anaesthesia_record",
        "anaesthesia assessment and record kept apart",
    )
    check(
        processed["09_USG_Abdomen_Scan.jpg"]["ocr_engine"] in {"rapidocr", "demo_fixture"},
        f"the scanned report went through OCR ({processed['09_USG_Abdomen_Scan.jpg']['ocr_engine']})",
    )
    check(processed["09_USG_Abdomen_Scan.jpg"]["quality_flag_counts"]["total"] >= 2, "poor-quality scan flagged")
    check(processed["15_Implant_Invoice.pdf"]["concealed_text_count"] == 1, "covered text reported on the implant invoice")

    status, invoice = call(base, "GET", f"/api/documents/{processed['15_Implant_Invoice.pdf']['document_id']}/analysis")
    check(invoice["bill"]["line_items"][0]["rate"] == "1100.00", "the visible implant rate is extracted (1,100.00)")
    check(invoice["bill"]["total"] == "6600.00", "invoice total is 6,600.00")
    leaked = [f["key"] for f in invoice["fields"] if "1,000.00" in (f["value"] or "") + f["snippet"]]
    check(not leaked, "covered text stays out of every extracted value")
    check(all(f["evidence_available"] for f in invoice["fields"]), "every extracted value has page evidence")

    status, consent = call(base, "GET", f"/api/documents/{processed['16_Consent_Form.pdf']['document_id']}/analysis")
    patient_slot = next(s for s in consent["signatures"]["slots"] if s["key"] == "patient_guardian")
    check(patient_slot["signed"] is False and patient_slot["found"], "blank patient signature area detected on the consent form")

    status, bill = call(base, "GET", f"/api/documents/{processed['12_Main_Hospital_Bill.pdf']['document_id']}/analysis")
    check(len(bill["bill"]["line_items"]) == 10 and bill["bill"]["total"] == "114360.00", "hospital bill read: 10 lines, 1,14,360.00")

    page_url = f"/api/documents/{processed['06_Discharge_Summary.pdf']['document_id']}/pages/3/image"
    status, image = call(base, "GET", page_url)
    check(status == 200 and image[:8] == b"\x89PNG\r\n\x1a\n", "page images are served as PNG")

    print("7. Canonical claim")
    status, state = call(base, "GET", f"/api/claims/{second['id']}/state")
    check(status == 200, "canonical claim served")
    patient = state["patient"]["fields"]
    admission = state["admission"]["fields"]
    check(patient["name"]["value"] == "Rajesh Sharma", f"patient name: {patient['name']['value']}")
    check(patient["age"]["value"] == "46", f"age: {patient['age']['value']}")
    check(patient["gender"]["value"] == "male", f"gender: {patient['gender']['value']}")
    check(patient["uhid"]["value"] == "UHID-123456", f"UHID: {patient['uhid']['value']}")
    check(patient["ipd"]["value"] == "IPD/2026/004512", f"IPD: {patient['ipd']['value']}")
    check(state["claim"]["hospital"] == "CityCare Multispeciality Hospital", "hospital from the claim record")
    check(
        (admission["admission_date"]["value"], admission["discharge_date"]["value"]) == ("2026-01-12", "2026-01-16"),
        "admission 12-01-2026 -> discharge 16-01-2026",
    )
    check(state["diagnosis"]["fields"]["primary"]["value"] == "Acute cholecystitis", "diagnosis: acute cholecystitis")
    check(state["diagnosis"]["fields"]["icd10"]["value"] == "K81.0", "ICD-10: K81.0")
    check(state["procedures"]["selected_key"] == "laparoscopic_cholecystectomy", "procedure: laparoscopic cholecystectomy")
    check(state["doctors"]["fields"]["surgeon"]["value"] == "Dr. Anil Mehta", "surgeon: Dr. Anil Mehta")
    check(state["doctors"]["fields"]["anaesthetist"]["value"] == "Dr. Priya Nair", "anaesthetist: Dr. Priya Nair")

    weights = {source["document_name"]: source["weight"] for source in patient["name"]["sources"]}
    check(
        weights.get("01_Patient_ID.png") == 3 and weights.get("02_Admission_Form.pdf") == 3 and weights.get("03_Doctor_Consultation.pdf") == 1,
        f"identity documents carry weight 3, others 1 ({patient['name']['source_count']} sources for the name)",
    )
    check(
        all(source["page"] and source["bounding_box"] for source in patient["name"]["sources"]),
        "every supporting source names a page and a region",
    )
    check(
        [item["value"] for item in patient["name"]["competing_values"]] == ["Rajesh K"],
        "the shortened name on the pharmacy bill is reported as a competing value",
    )
    bill_types = state["bills"]["summary"]["by_type"]
    check(
        bill_types == {"hospital_bill": 1, "implant_invoice": 1, "ot_bill": 1, "pharmacy_bill": 1},
        f"four bill categories read: {bill_types}",
    )
    totals = {item["bill_type"]: item["total"] for item in state["bills"]["summary"]["totals"]}
    check(
        totals == {"hospital_bill": "114360.00", "pharmacy_bill": "9860.00", "ot_bill": "18000.00", "implant_invoice": "6600.00"},
        f"bill totals as extracted: {totals}",
    )
    implant = next(item for item in state["bills"]["items"] if item["bill_type"] == "implant_invoice")
    check(implant["line_items"][0]["rate"] == "1100.00", "the visible implant rate reaches the canonical claim")
    check("1,000.00" not in json.dumps(state), "covered text never reaches the canonical claim")
    check(state["documents"]["count"] == 18, "document inventory lists all 18 documents")
    check(
        all(item["duplicate_state"] == "not_evaluated" for item in state["documents"]["items"]),
        "duplicate state is left for a later phase",
    )
    check(
        all(not state[section]["available"] and state[section]["items"] == [] for section in ("checklist", "findings", "questions", "resolutions")),
        "checklist, findings, questions and resolutions are present and empty",
    )

    status, again = call(base, "GET", f"/api/claims/{second['id']}/state")
    check(
        again["snapshot"]["content_sha256"] == state["snapshot"]["content_sha256"],
        f"rebuilding the canonical claim is deterministic ({state['snapshot']['content_sha256'][:12]}…)",
    )
    check(
        json.dumps({k: v for k, v in again.items() if k != "snapshot"}, sort_keys=True)
        == json.dumps({k: v for k, v in state.items() if k != "snapshot"}, sort_keys=True),
        "the two builds are byte-identical",
    )

    print(f"8. Database and storage ({dialect})")
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            numbers = sorted(session.scalars(select(Claim.claim_number)))
            check(numbers == ["CLM-2026-00123", "CLM-2026-00124"], f"claims persisted: {numbers}")
            documents = list(session.scalars(select(Document)))
            check(len(documents) == 34, "34 document rows persisted")
            check({d.source for d in documents} == {"upload", "demo_pack"}, "upload sources recorded")
            for document in documents:
                path = settings.storage_dir / document.storage_path
                if stat.S_IMODE(path.stat().st_mode) != 0o444:
                    raise SmokeFailure(f"{path} is not read-only")
                if hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256:
                    raise SmokeFailure(f"{path} does not match its recorded SHA-256")
            check(True, "all 34 stored originals are read-only (0444) and match their SHA-256")
            counts = dict(session.execute(select(AuditEvent.event_type, func.count()).group_by(AuditEvent.event_type)).all())
            check(
                counts
                == {
                    "demo_reset": 1,
                    "claim_created": 2,
                    "document_uploaded": 34,
                    "demo_pack_attached": 3,
                    "claim_analysis_started": 1,
                    "document_processed": 18,
                    "claim_analysis_completed": 1,
                },
                f"audit events: {counts}",
            )
            pages = session.scalar(select(func.count()).select_from(DocumentPage))
            expected_pages = sum(e["pages"] for entries in manifest["sets"].values() for e in entries)
            check(pages == expected_pages, f"{pages} page rows stored (one per page of the 18 documents)")
            fields = session.scalar(select(func.count()).select_from(ExtractedField))
            check(fields > 120, f"{fields} extracted fields stored with evidence")
            bills = session.scalar(select(func.count()).select_from(DocumentBill))
            check(bills == 4, f"{bills} bills read (hospital, pharmacy, OT, implant invoice)")
            unprocessed = session.scalar(
                select(func.count()).select_from(Document).where(Document.processing_status != "processed", Document.claim_id == second["id"])
            )
            check(unprocessed == 0, "every document of the analysed claim is marked processed")
            snapshot = session.scalar(select(ClaimState).where(ClaimState.claim_id == second["id"]))
            check(snapshot is not None, "canonical snapshot stored")
            check(
                snapshot.content_sha256 == state["snapshot"]["content_sha256"] and snapshot.processed_count == 18,
                "stored snapshot matches what the API served",
            )
            check(
                snapshot.payload["patient"]["fields"]["name"]["value"] == "Rajesh Sharma",
                "stored snapshot holds the canonical values",
            )
            images = list((settings.storage_dir / "claims" / second["id"] / "pages").rglob("*.png"))
            check(len(images) == expected_pages, f"{len(images)} rendered page images on disk")
            originals_before = session.scalars(
                select(Document.storage_path).where(Document.claim_id == second["id"])
            ).all()
            for relative in originals_before:
                path = settings.storage_dir / relative
                check_mode = stat.S_IMODE(path.stat().st_mode)
                if check_mode != 0o444:
                    raise SmokeFailure(f"{path} is no longer read-only after analysis ({oct(check_mode)})")
            check(True, "originals are still read-only after analysis")
    finally:
        engine.dispose()

    print("PASSED")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SmokeFailure as failure:
        print(f"  FAILED  {failure}")
        raise SystemExit(1) from None

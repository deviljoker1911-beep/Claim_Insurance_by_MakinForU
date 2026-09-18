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
    Finding,
    ValidationRun,
)
from app.validation.rules import FORBIDDEN_WORDS  # noqa: E402


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
        all(state[section]["available"] for section in ("checklist", "findings", "questions", "resolutions")),
        "every section of the canonical claim is built",
    )

    print("8. Cross-document validation")
    status, complete = call(base, "GET", f"/api/claims/{second['id']}/findings")
    check(status == 200, "findings served for the complete claim")
    complete_codes = sorted(item["code"] for item in complete["items"] if item["status"] in ("open", "reopened"))
    check(
        "MISSING_REQUIRED_DOCUMENT" not in complete_codes,
        f"no required document is missing once all 18 are present ({len(complete_codes)} open findings)",
    )
    check(
        "IMPLANT_USAGE_NOT_CORROBORATED" not in complete_codes,
        "the billed implant is corroborated by the operative note",
    )
    expected_open = [
        "BILL_ARITHMETIC_MISMATCH",
        "DUPLICATE_BILL_NUMBER",
        "DUPLICATE_DOCUMENT",
        "LOW_QUALITY_PAGE",
        "NAME_VARIANT",
        "PATIENT_NAME_MISMATCH",
        "POTENTIAL_ALTERATION",
        "SIGNATURE_NOT_DETECTED",
    ]
    check(complete_codes == expected_open, f"open findings: {complete_codes}")
    check(
        complete["summary"]["by_severity"]["critical"] >= 1 and complete["summary"]["by_severity"]["info"] == 1,
        f"severities: {complete['summary']['by_severity']}",
    )
    text = json.dumps(complete).lower()
    check(not [word for word in FORBIDDEN_WORDS if word in text], "no finding uses accusatory wording")
    for item in complete["items"]:
        if item["code"] == "MISSING_REQUIRED_DOCUMENT":
            continue
        if not item["evidence"]:
            raise SmokeFailure(f"{item['code']} carries no evidence")
        for evidence in item["evidence"]:
            if not evidence["document_id"] or not evidence["page"]:
                raise SmokeFailure(f"{item['code']} evidence does not point at a page")
    check(True, "every finding that claims evidence points at a document and a page")

    call(base, "GET", f"/api/claims/{second['id']}/changes")  # let the re-analysis settle
    status, validated_state = call(base, "GET", f"/api/claims/{second['id']}/state")
    duplicate_states = {item["duplicate_state"] for item in validated_state["documents"]["items"]}
    check(
        duplicate_states <= {"unique", "duplicate", "has_duplicate"} and "duplicate" in duplicate_states,
        f"the duplicate state of every document is evaluated: {sorted(duplicate_states)}",
    )
    check(
        validated_state["findings"]["available"] and validated_state["findings"]["count"] == complete["count"],
        "the canonical claim carries the findings of this claim",
    )

    status, rebuilt = call(base, "GET", f"/api/claims/{second['id']}/state")
    if rebuilt["snapshot"]["content_sha256"] != validated_state["snapshot"]["content_sha256"]:
        differing = [
            key
            for key in rebuilt
            if key != "snapshot" and json.dumps(rebuilt[key], sort_keys=True) != json.dumps(validated_state.get(key), sort_keys=True)
        ]
        print(f"      sections that differ between two reads: {differing}")
        for key in differing:
            before_text = json.dumps(validated_state.get(key), sort_keys=True)
            after_text = json.dumps(rebuilt[key], sort_keys=True)
            print(f"      {key} before: {before_text[:400]}")
            print(f"      {key} after:  {after_text[:400]}")
    check(
        rebuilt["snapshot"]["content_sha256"] == validated_state["snapshot"]["content_sha256"],
        f"rebuilding the canonical claim is deterministic ({rebuilt['snapshot']['content_sha256'][:12]}…)",
    )
    check(
        json.dumps({k: v for k, v in rebuilt.items() if k != "snapshot"}, sort_keys=True)
        == json.dumps({k: v for k, v in validated_state.items() if k != "snapshot"}, sort_keys=True),
        "the two builds are byte-identical",
    )

    status, checks_payload = call(base, "GET", f"/api/claims/{second['id']}/checks")
    check(status == 200 and checks_payload["count"] == 20, f"20 checks recorded: {checks_payload['summary']}")
    by_id = {item["check_id"]: item for item in checks_payload["items"]}
    check(by_id["required_documents"]["status"] == "pass", "required documents check passes")
    check(by_id["operative_documentation"]["status"] == "pass", "operative documentation check ran")
    check(by_id["implant_corroboration"]["status"] == "pass", "implant corroboration check passes")
    check(by_id["date_sequence"]["status"] == "pass", "date sequence check passes")

    print("9. Validation of the 16-document claim (the staged demo)")
    status, staged_processing = call(base, "POST", f"/api/claims/{first['id']}/analyze")
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        status, staged_processing = call(base, "GET", f"/api/claims/{first['id']}/processing")
        if staged_processing["state"] != "running":
            break
        time.sleep(0.4)
    check(
        staged_processing["state"] == "completed",
        f"16 documents analysed: {staged_processing['counts']}",
    )
    status, partial = call(base, "GET", f"/api/claims/{first['id']}/findings")
    partial_codes = sorted(item["code"] for item in partial["items"])
    missing = [item for item in partial["items"] if item["code"] == "MISSING_REQUIRED_DOCUMENT"]
    check(
        sorted(item["context"]["requirement"] for item in missing) == ["anaesthesia_record", "operative_note"],
        "the operative note and the anaesthesia record are reported as missing",
    )
    check(all(item["evidence"] == [] for item in missing), "a missing document invents no evidence")
    check("IMPLANT_USAGE_NOT_CORROBORATED" in partial_codes, "the billed implant is not corroborated yet")
    status, partial_checks = call(base, "GET", f"/api/claims/{first['id']}/checks")
    partial_by_id = {item["check_id"]: item for item in partial_checks["items"]}
    check(partial_by_id["operative_documentation"]["status"] == "pending", "checks that need the operative note wait")
    check(partial_by_id["required_documents"]["status"] == "fail", "the required documents check fails")

    print("10. Finding lifecycle")
    name_finding = next(item for item in partial["items"] if item["code"] == "PATIENT_NAME_MISMATCH")
    status, reviewed = post_json(base, f"/api/findings/{name_finding['id']}/action", {"action": "review", "note": "Called the hospital"})
    check(status == 200 and reviewed["finding"]["status"] == "open", "review records the reviewer without closing the finding")
    status, resolved = post_json(base, f"/api/findings/{name_finding['id']}/action", {"action": "resolve"})
    check(status == 200 and resolved["finding"]["status"] == "resolved", "resolve moves the finding to resolved")
    status, refused = post_json(base, f"/api/findings/{name_finding['id']}/action", {"action": "acknowledge"})
    check(status == 409, "an invalid transition is refused")
    status, again = call(base, "POST", f"/api/claims/{first['id']}/validate")
    check(again["findings_created"] == 0, "validating again creates nothing new")
    status, after = call(base, "GET", f"/api/claims/{first['id']}/findings")
    still_resolved = next(item for item in after["items"] if item["id"] == name_finding["id"])
    check(still_resolved["status"] == "resolved", "a human decision survives a new validation run")
    duplicate = next(item for item in after["items"] if item["code"] == "DUPLICATE_DOCUMENT")
    status, excluded = post_json(base, f"/api/findings/{duplicate['id']}/action", {"action": "exclude_duplicate"})
    check(status == 200 and excluded["finding"]["status"] == "resolved", "excluding a duplicate resolves its finding")
    status, claim_state = call(base, "GET", f"/api/claims/{first['id']}/state")
    copy = next(item for item in claim_state["documents"]["items"] if item["filename"] == "11_Lab_Report_copy.pdf")
    check(
        copy["excluded"] and copy["duplicate_state"] == "excluded" and copy["duplicate_of"],
        "the excluded copy is marked in the document inventory",
    )
    check(
        claim_state["findings"]["available"] and claim_state["findings"]["count"] == after["count"],
        "the canonical claim carries the findings summary",
    )

    print("11. Procedure checklist")
    status, clean_list = call(base, "GET", f"/api/claims/{second['id']}/checklist")
    check(status == 200 and clean_list["available"], "the complete claim has a checklist")
    check(
        clean_list["procedure"]["key"] == "laparoscopic_cholecystectomy",
        f"procedure detected from the documents: {clean_list['procedure']['label']} "
        f"({clean_list['procedure']['source_count']} documents)",
    )
    clean_rows = {item["key"]: item for item in clean_list["items"]}
    check(clean_rows["operative_note"]["status"] == "found", "the operative note satisfies its requirement")
    check(
        clean_rows["operative_note"]["evidence"][0]["page"] is None
        and "page-level evidence unavailable" in clean_rows["operative_note"]["evidence"][0]["detail"],
        "a document satisfies a requirement as a whole, with no page invented for it",
    )

    status, staged_list = call(base, "GET", f"/api/claims/{first['id']}/checklist")
    staged_rows = {item["key"]: item for item in staged_list["items"]}
    check(
        staged_rows["operative_note"]["status"] == "missing"
        and staged_rows["anaesthesia_record"]["status"] == "missing",
        "the staged claim is missing the operative note and the anaesthesia record",
    )
    check(
        [f["code"] for f in staged_rows["operative_note"]["findings"]] == ["MISSING_REQUIRED_DOCUMENT"],
        "the missing requirement carries the finding the rules raised for it",
    )
    check(staged_rows["operative_note"]["evidence"] == [], "a missing requirement cites no document")
    check(
        staged_rows["consent"]["status"] == "review_required",
        f"the unsigned consent asks for a person: {staged_rows['consent']['detail'][:60]}…",
    )
    check(
        all(
            item["document_name"] != "11_Lab_Report_copy.pdf"
            for item in staged_rows["investigation_reports"]["evidence"]
        ),
        "the copy excluded a moment ago satisfies nothing",
    )
    status, again_list = call(base, "GET", f"/api/claims/{first['id']}/checklist")
    check(again_list == staged_list, "reading the checklist twice gives the same answer")

    print("12. Questions, uploading from a question, and the assistant")

    def wait_for_processing(claim_id: str) -> dict:
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            status, processing = call(base, "GET", f"/api/claims/{claim_id}/processing")
            if processing["state"] in ("completed", "failed"):
                return processing
            time.sleep(0.4)
        raise SystemExit("processing did not finish")

    def questions_of(claim_id: str) -> dict:
        status, payload = call(base, "GET", f"/api/claims/{claim_id}/questions")
        assert status == 200, payload
        return {item["requirement_key"]: item for item in payload["items"]}

    asked = questions_of(first["id"])
    check(
        asked.get("operative_note", {}).get("status") == "open"
        and asked.get("anaesthesia_record", {}).get("status") == "open",
        "the staged claim asks for the operative note and the anaesthesia record",
    )
    check(
        asked["operative_note"]["question"] == "Do you have the operative note for this admission?",
        f"the question is grounded: {asked['operative_note']['reason'][:60]}…",
    )

    operative_question = asked["operative_note"]["id"]
    status, refused = post_json(base, f"/api/questions/{operative_question}/answer", {"answer": "not_available"})
    check(status == 422, "an answer of 'not available' without a reason is refused")

    status, requested = post_json(base, f"/api/questions/{operative_question}/answer", {"answer": "yes_have_it"})
    check(
        status == 200
        and requested["question"]["status"] == "answered"
        and requested["upload"]["expected_document_type"] == "operative_note",
        "'yes, I have it' asks for the document and keeps the question open",
    )

    wrong = [entry for entry in initial if entry[0] == "10_Lab_Report.pdf"]
    body, content_type = multipart([("operative_note_try_1.pdf", wrong[0][1], "application/pdf")])
    status, _ = call(base, "POST", f"/api/questions/{operative_question}/documents", body=body, content_type=content_type)
    check(status == 201, "a document can be uploaded against the question itself")
    wait_for_processing(first["id"])
    after_wrong = questions_of(first["id"])["operative_note"]
    check(
        after_wrong["status"] == "answered"
        and after_wrong["last_upload"]["satisfies"] is False
        and after_wrong["last_upload"]["message"] == "Document type does not satisfy this request.",
        f"a document of the wrong type does not resolve it (read as {after_wrong['last_upload']['doc_type']})",
    )

    scan = demo_dir / "later" / "scan_0042.pdf"
    body, content_type = multipart([("scan_0042.pdf", scan.read_bytes(), "application/pdf")])
    status, uploaded = call(base, "POST", f"/api/questions/{operative_question}/documents", body=body, content_type=content_type)
    check(status == 201, "the operative note is uploaded against the question")
    wait_for_processing(first["id"])
    resolved = questions_of(first["id"])["operative_note"]
    check(resolved["status"] == "resolved", "the right document resolves the question")
    check(
        resolved["resolved_document_id"] == uploaded["documents"][0]["id"],
        "the question records the document that answered it",
    )

    status, checklist_now = call(base, "GET", f"/api/claims/{first['id']}/checklist")
    rows = {item["key"]: item["status"] for item in checklist_now["items"]}
    check(rows["operative_note"] == "found", "the checklist moved from missing to found")
    status, findings_now = call(base, "GET", f"/api/claims/{first['id']}/findings")
    missing_note = [
        item
        for item in findings_now["items"]
        if item["code"] == "MISSING_REQUIRED_DOCUMENT" and item["context"]["requirement"] == "operative_note"
    ]
    check([item["status"] for item in missing_note] == ["auto_closed"], "the phase 5 finding closed itself")

    status, change_payload = call(base, "GET", f"/api/claims/{first['id']}/changes")
    latest = change_payload["latest"]
    headlines = [change["headline"] for change in latest["changes"]]
    check(latest["summary"]["documents_added"] >= 1, f"the change summary reports the pass: {latest['summary']}")
    check(
        any("scan_0042.pdf added" in headline for headline in headlines)
        and any("Operative note: missing → found" in headline for headline in headlines),
        "what changed is reported from the states, not from text",
    )

    anaesthesia_question = questions_of(first["id"])["anaesthesia_record"]["id"]
    reason = "The anaesthesia chart is with the theatre records and has been requested."
    status, unavailable = post_json(
        base, f"/api/questions/{anaesthesia_question}/answer", {"answer": "not_available", "reason": reason}
    )
    check(
        status == 200 and unavailable["question"]["status"] == "documented_unavailable",
        "'not available' with a reason is recorded",
    )
    status, audit = call(base, "GET", f"/api/claims/{first['id']}/audit")
    types = [event["event_type"] for event in audit]
    for event_type in (
        "question_generated",
        "question_answered",
        "document_requested",
        "document_uploaded_for_question",
        "question_resolved",
        "question_marked_unavailable",
        "reanalysis_started",
        "reanalysis_completed",
    ):
        check(event_type in types, f"audit event recorded: {event_type}")

    status, provider = call(base, "GET", "/api/assistant/provider")
    check(
        provider["name"] == "demo" and provider["mode"] == "offline-deterministic",
        f"the assistant answers offline: {provider['name']} · {provider['model']}",
    )
    status, answer = post_json(base, f"/api/claims/{first['id']}/assistant", {"question": "What documents are missing?"})
    check(status == 200 and answer["intent"] == "missing_documents", "the assistant answers about missing documents")
    check(bool(answer["citations"]), f"the answer cites {len(answer['citations'])} source(s) from this claim")
    banned = [word for word in ("fraud", "forged", "fake") if word in answer["answer"].lower()]
    check(not banned, "the assistant never accuses")
    status, ready = post_json(
        base, f"/api/claims/{first['id']}/assistant", {"question": "Is this claim ready for submission?"}
    )
    check(
        "ready for submission" not in ready["answer"].lower() and "approved" not in ready["answer"].lower(),
        "the assistant does not say a claim is ready or approved",
    )

    print("13. Readiness, the workflow and human approval")
    status, readiness = call(base, "GET", f"/api/claims/{second['id']}/readiness")
    check(status == 200, f"readiness served: {readiness['score']}% {readiness['status']}")
    check(
        readiness["score"] == 100 - sum(d["amount"] for d in readiness["breakdown"]["deductions"]),
        "the score is exactly its own deductions taken off 100",
    )
    check(
        readiness["status"] == "needs_attention" and readiness["summary"]["required_missing"] == 0,
        "the complete claim has every required document and findings to look at",
    )
    check(
        all(d["source"]["key"] and d["source"]["label"] for d in readiness["breakdown"]["deductions"]),
        f"every deduction names what it is for ({len(readiness['breakdown']['deductions'])} of them)",
    )
    steps = {step["key"]: step["status"] for step in readiness["workflow"]}
    check(
        steps["documents"] == "complete" and steps["human_review"] == "pending",
        f"the workflow reports where the claim stands: {steps}",
    )

    status, refused = post_json(base, f"/api/claims/{second['id']}/review/approve", {})
    check(status == 422, f"approval is refused while the claim needs attention: {refused.get('detail', '')[:60]}…")

    status, staged_readiness = call(base, "GET", f"/api/claims/{first['id']}/readiness")
    unavailable = [
        d for d in staged_readiness["breakdown"]["deductions"] if "documented as unavailable" in d["reason"]
    ]
    check(
        len(unavailable) == 1 and unavailable[0]["amount"] == 6,
        "a document recorded as unavailable costs 6 rather than 12",
    )

    status, findings_now = call(base, "GET", f"/api/claims/{second['id']}/findings")
    to_deal_with = [item for item in findings_now["items"] if item["is_active"] and item["severity"] != "info"]
    for item in to_deal_with:
        post_json(base, f"/api/findings/{item['id']}/action", {"action": "acknowledge", "note": "Checked."})
    status, ready = call(base, "GET", f"/api/claims/{second['id']}/readiness")
    check(
        ready["score"] == 100 and ready["status"] == "ready_for_human_review",
        f"dealing with {len(to_deal_with)} finding(s) takes the claim to {ready['score']}% {ready['status']}",
    )
    check(ready["review"]["can_approve"] and ready["review"]["state"] == "draft", "approval is now offered")

    status, approved = post_json(base, f"/api/claims/{second['id']}/review/approve", {"note": "Checked against the file."})
    check(
        status == 200 and approved["review"]["approved_by"] == "Demo Operator",
        f"approved by {approved['review'].get('approved_by')} at {approved['review'].get('approved_at')}",
    )
    check(
        approved["readiness"]["score"] == ready["score"],
        "approval records a decision and leaves the score where it was",
    )
    status, again = post_json(base, f"/api/claims/{second['id']}/review/approve", {})
    check(status == 409, "a claim is not approved twice")

    status, audit_now = call(base, "GET", f"/api/claims/{second['id']}/audit")
    types = [event["event_type"] for event in audit_now]
    check("human_review_started" in types, "audit event recorded: human_review_started")
    approval_events = [event for event in audit_now if event["event_type"] == "human_approval"]
    check(
        len(approval_events) == 1 and approval_events[0]["actor"] == "Demo Operator",
        "audit event recorded: human_approval, by the operator who clicked it",
    )

    status, dash = call(base, "GET", "/api/dashboard")
    check(status == 200 and dash["totals"]["claims"] == 2, f"dashboard counts the claims: {dash['totals']}")
    check(
        dash["totals"]["approved"] == 1 and dash["totals"]["ready_for_human_review"] >= 1,
        "the dashboard reflects the approval that just happened",
    )
    check(
        dash["totals"]["average_readiness"]
        == round(sum(row["readiness_score"] for row in dash["claims"]) / len(dash["claims"])),
        f"average readiness is the average of the claims ({dash['totals']['average_readiness']}%)",
    )
    check(bool(dash["recent_activity"]), "recent activity comes from the audit trail")

    print(f"14. Database and storage ({dialect})")
    engine = make_engine(settings.database_url)
    try:
        with Session(engine) as session:
            numbers = sorted(session.scalars(select(Claim.claim_number)))
            check(numbers == ["CLM-2026-00123", "CLM-2026-00124"], f"claims persisted: {numbers}")
            documents = list(session.scalars(select(Document)))
            check(len(documents) == 36, "36 document rows persisted (34 demo files, 2 answering a question)")
            check({d.source for d in documents} == {"upload", "demo_pack"}, "upload sources recorded")
            for document in documents:
                path = settings.storage_dir / document.storage_path
                if stat.S_IMODE(path.stat().st_mode) != 0o444:
                    raise SmokeFailure(f"{path} is not read-only")
                if hashlib.sha256(path.read_bytes()).hexdigest() != document.sha256:
                    raise SmokeFailure(f"{path} does not match its recorded SHA-256")
            check(True, "all 36 stored originals are read-only (0444) and match their SHA-256")
            counts = dict(session.execute(select(AuditEvent.event_type, func.count()).group_by(AuditEvent.event_type)).all())
            validation_runs = counts.pop("validation_completed", 0)
            # Counted exactly: these are the actions this script performed.
            fixed = {
                "demo_reset": 1,
                "claim_created": 2,
                "document_uploaded": 36,
                "document_processed": 36,
                "demo_pack_attached": 3,
                # Three in the lifecycle section, and one for each finding acknowledged before
                # the claim was approved.
                "finding_action": 3 + len(to_deal_with),
                "document_excluded": 1,
                "question_answered": 2,
                "document_requested": 1,
                "document_uploaded_for_question": 2,
                "question_upload_did_not_match": 1,
                "question_marked_unavailable": 1,
            }
            wrong = {name: (counts.get(name), total) for name, total in fixed.items() if counts.get(name) != total}
            check(not wrong, f"audit events counted exactly: {wrong or fixed}")
            # Counted as "at least once": how often analysis and re-analysis run depends on how
            # the documents arrived, and how many questions were asked on what was missing.
            for name in (
                "claim_analysis_started",
                "claim_analysis_completed",
                "question_generated",
                "question_resolved",
                "reanalysis_started",
                "reanalysis_completed",
                "human_review_started",
                "human_approval",
            ):
                check(counts.get(name, 0) >= 1, f"audit event recorded {counts.get(name, 0)} time(s): {name}")
            unexpected = set(counts) - set(fixed) - {
                "claim_analysis_started",
                "claim_analysis_completed",
                "question_generated",
                "question_resolved",
                "reanalysis_started",
                "reanalysis_completed",
                "question_marked_not_applicable",
                "workspace_initialized",
                "human_review_started",
                "human_approval",
            }
            check(not unexpected, f"no unexpected audit event types: {sorted(unexpected) or 'none'}")
            check(validation_runs >= 2, f"validation ran for both claims ({validation_runs} runs recorded)")
            pages = session.scalar(
                select(func.count()).select_from(DocumentPage).where(DocumentPage.claim_id == second["id"])
            )
            expected_pages = sum(e["pages"] for entries in manifest["sets"].values() for e in entries)
            check(pages == expected_pages, f"{pages} page rows stored (one per page of the 18 documents)")
            fields = session.scalar(
                select(func.count()).select_from(ExtractedField).where(ExtractedField.claim_id == second["id"])
            )
            check(fields > 120, f"{fields} extracted fields stored with evidence")
            bills = session.scalar(
                select(func.count()).select_from(DocumentBill).where(DocumentBill.claim_id == second["id"])
            )
            check(bills == 4, f"{bills} bills read (hospital, pharmacy, OT, implant invoice)")
            unprocessed = session.scalar(
                select(func.count()).select_from(Document).where(Document.processing_status != "processed", Document.claim_id == second["id"])
            )
            check(unprocessed == 0, "every document of the analysed claim is marked processed")
            # Read the claim as it stands now: the sections above have acted on it since the
            # canonical claim was first compared.
            status, current_state = call(base, "GET", f"/api/claims/{second['id']}/state")
            session.expire_all()
            snapshot = session.scalar(select(ClaimState).where(ClaimState.claim_id == second["id"]))
            check(snapshot is not None, "canonical snapshot stored")
            check(
                snapshot.content_sha256 == current_state["snapshot"]["content_sha256"]
                and snapshot.processed_count == 18,
                "stored snapshot matches what the API served",
            )
            check(
                snapshot.payload["checklist"]["available"]
                and snapshot.payload["checklist"]["procedure"]["key"] == "laparoscopic_cholecystectomy",
                "stored snapshot holds the procedure checklist",
            )
            check(
                snapshot.payload["patient"]["fields"]["name"]["value"] == "Rajesh Sharma",
                "stored snapshot holds the canonical values",
            )
            findings_rows = session.scalars(select(Finding).where(Finding.claim_id == second["id"])).all()
            check(len(findings_rows) >= 8, f"{len(findings_rows)} findings stored for the complete claim")
            check(
                len({row.fingerprint for row in findings_rows}) == len(findings_rows),
                "every stored finding has its own fingerprint",
            )
            runs = session.scalars(select(ValidationRun)).all()
            check(len(runs) == 2, f"one validation record per validated claim ({len(runs)})")
            check(all(len(run.checks) == 20 for run in runs), "each validation record holds all 20 checks")
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

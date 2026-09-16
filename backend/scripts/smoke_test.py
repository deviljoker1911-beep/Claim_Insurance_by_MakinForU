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
import urllib.error
import urllib.request
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.db import make_engine  # noqa: E402
from app.models import AuditEvent, Claim, Document  # noqa: E402


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

    print(f"6. Database and storage ({dialect})")
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
                counts == {"demo_reset": 1, "claim_created": 2, "document_uploaded": 34, "demo_pack_attached": 3},
                f"audit events: {counts}",
            )
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

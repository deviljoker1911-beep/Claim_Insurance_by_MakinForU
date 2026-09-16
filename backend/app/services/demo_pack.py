"""Synthetic demo document packs.

Attaching a pack feeds the committed demo files through the same intake code path as a
manual upload; only the recorded `source` differs.
"""

import hashlib
import json
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from app.audit import record_event
from app.config import get_settings
from app.demo_gen.generate import MANIFEST_NAME, GeneratedData, generate_in_memory, sha256_bytes, write_file
from app.models import Claim, Document
from app.services.intake import IncomingFile, ingest_files
from app.storage import sha256_file


class DemoDataError(RuntimeError):
    pass


@dataclass(frozen=True)
class DemoFile:
    set_name: str
    filename: str
    label: str
    media_type: str
    pages: int
    size_bytes: int
    sha256: str
    path: Path


def _manifest_path() -> Path:
    return get_settings().demo_data_dir / MANIFEST_NAME


def load_manifest() -> dict:
    try:
        return json.loads(_manifest_path().read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DemoDataError("Demo data is missing. Reset the demo workspace to regenerate it.") from exc


def demo_files(set_name: str, verify: bool = True) -> list[DemoFile]:
    entries = load_manifest()["sets"].get(set_name)
    if entries is None:
        raise DemoDataError(f"Unknown demo document set: {set_name}")
    files = []
    for entry in entries:
        path = get_settings().demo_data_dir / entry["path"]
        if verify:
            if not path.is_file():
                raise DemoDataError(f"Demo file {entry['filename']} is missing. Reset the demo workspace.")
            if sha256_file(path) != entry["sha256"]:
                raise DemoDataError(
                    f"Demo file {entry['filename']} does not match the demo manifest. Reset the demo workspace."
                )
        files.append(
            DemoFile(
                set_name=set_name,
                filename=entry["filename"],
                label=entry["label"],
                media_type=entry["media_type"],
                pages=entry["pages"],
                size_bytes=entry["size_bytes"],
                sha256=entry["sha256"],
                path=path,
            )
        )
    return files


def attach_demo_set(
    session: Session, claim: Claim, set_name: str, actor: str | None = None
) -> tuple[list[Document], list[str]]:
    """Attach a demo set to a claim. Files from the same set that are already attached are skipped."""
    files = demo_files(set_name)
    attached = {
        document.original_filename
        for document in claim.documents
        if document.source == "demo_pack" and document.demo_set == set_name
    }
    pending = [file for file in files if file.filename not in attached]
    skipped = [file.filename for file in files if file.filename in attached]
    if not pending:
        return [], skipped

    with ExitStack() as stack:
        incoming = [
            IncomingFile(file.filename, stack.enter_context(file.path.open("rb")), file.media_type)
            for file in pending
        ]
        documents = ingest_files(session, claim, incoming, source="demo_pack", demo_set=set_name, actor=actor)
    record_event(
        session,
        "demo_pack_attached",
        f"Demo document set '{set_name}' attached ({len(documents)} files)",
        claim_id=claim.id,
        actor=actor,
        details={"set": set_name, "attached": [d.original_filename for d in documents], "skipped": skipped},
    )
    session.commit()
    return documents, skipped


def sync_demo_data(data: GeneratedData | None = None) -> dict:
    """Recreate the demo files from the deterministic generator and verify them against the manifest.

    If the generator output no longer matches the committed manifest (for example after a library
    upgrade), the committed files are left untouched and the mismatch is reported.
    """
    data = data or generate_in_memory()
    directory = get_settings().demo_data_dir
    manifest_path = directory / MANIFEST_NAME
    committed = manifest_path.read_bytes() if manifest_path.is_file() else None
    generator_matches = committed is None or committed == data.manifest_bytes

    written = 0
    mismatched: list[str] = []
    if generator_matches:
        for path, content in data.files.items():
            target = directory / path
            if not target.is_file() or sha256_file(target) != sha256_bytes(content):
                write_file(target, content)
                written += 1
        if committed is None:
            write_file(manifest_path, data.manifest_bytes)
        manifest = data.manifest
    else:
        manifest = json.loads(committed)
        generated = {e["path"]: e["sha256"] for entries in data.manifest["sets"].values() for e in entries}
        mismatched = sorted(
            e["path"] for entries in manifest["sets"].values() for e in entries if generated.get(e["path"]) != e["sha256"]
        )

    entries = [e for set_entries in manifest["sets"].values() for e in set_entries]
    verified = all(
        (directory / e["path"]).is_file() and sha256_file(directory / e["path"]) == e["sha256"] for e in entries
    )
    return {
        "files": len(entries),
        "written": written,
        "verified": verified,
        "generator_matches_manifest": generator_matches,
        "mismatched_files": mismatched,
        "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest(),
    }

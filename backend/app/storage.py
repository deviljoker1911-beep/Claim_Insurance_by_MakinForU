"""Write-once storage for uploaded originals.

Each original is streamed to a private temporary file while its SHA-256 is computed,
validated, then published read-only (0444) under a name derived from the document id.
Publishing uses a hard link, which fails instead of overwriting an existing file.
"""

import hashlib
import os
import shutil
import stat
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from PIL import Image

from app.config import get_settings
from app.processing.pdf import UnreadablePdf, inspect_pdf

CHUNK_SIZE = 1024 * 1024
READ_ONLY = 0o444

EXTENSION_TYPES = {
    ".pdf": "application/pdf",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}
STORED_EXTENSIONS = {"application/pdf": ".pdf", "image/png": ".png", "image/jpeg": ".jpg"}


class InvalidFile(ValueError):
    """The upload is not an acceptable PDF/PNG/JPEG original."""


def claims_root() -> Path:
    return get_settings().storage_dir / "claims"


def originals_dir(claim_id: str) -> Path:
    return claims_root() / claim_id / "originals"


def absolute_storage_path(relative: str) -> Path:
    return get_settings().storage_dir / relative


def clean_filename(name: str | None) -> str:
    """Display name for an upload: no directory parts or control characters."""
    base = PurePosixPath((name or "").replace("\\", "/")).name
    base = "".join(ch for ch in base if ch.isprintable()).strip()
    return base[:255] or "unnamed"


def sniff_content_type(head: bytes) -> str | None:
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if b"%PDF-" in head[:1024]:
        return "application/pdf"
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class StagedFile:
    document_id: str
    filename: str
    declared_content_type: str | None
    content_type: str
    size_bytes: int
    sha256: str
    page_count: int
    metadata: dict
    partial_path: Path
    final_path: Path
    published: bool = field(default=False)

    @property
    def storage_path(self) -> str:
        return self.final_path.relative_to(get_settings().storage_dir).as_posix()

    def publish(self) -> None:
        """Make the original read-only and move it to its final, never-overwritten name."""
        os.chmod(self.partial_path, READ_ONLY)
        os.link(self.partial_path, self.final_path)
        self.published = True
        self.partial_path.unlink()
        if sha256_file(self.final_path) != self.sha256:
            raise OSError(f"Stored original {self.final_path.name} failed its integrity check")

    def discard(self) -> None:
        self.partial_path.unlink(missing_ok=True)
        if self.published:
            self.final_path.unlink(missing_ok=True)


def stage_file(
    stream: BinaryIO,
    filename: str | None,
    declared_content_type: str | None,
    claim_id: str,
    document_id: str,
) -> StagedFile:
    settings = get_settings()
    name = clean_filename(filename)
    extension = PurePosixPath(name.lower()).suffix
    expected_type = EXTENSION_TYPES.get(extension)
    if expected_type is None:
        raise InvalidFile("Unsupported file type. Upload PDF, PNG or JPG files.")

    directory = originals_dir(claim_id)
    directory.mkdir(parents=True, exist_ok=True)
    partial = directory / f".{document_id}.partial"
    limit = settings.max_upload_mb * 1024 * 1024
    digest = hashlib.sha256()
    size = 0
    head = b""

    fd = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as out:
            while chunk := stream.read(CHUNK_SIZE):
                if len(head) < 1024:
                    head += chunk[: 1024 - len(head)]
                size += len(chunk)
                if size > limit:
                    raise InvalidFile(f"File exceeds the {settings.max_upload_mb} MB limit")
                digest.update(chunk)
                out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
        if size == 0:
            raise InvalidFile("File is empty")
        detected_type = sniff_content_type(head)
        if detected_type != expected_type:
            raise InvalidFile(f"File content does not match its {extension} extension")
        page_count, metadata = _inspect(partial, detected_type)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    return StagedFile(
        document_id=document_id,
        filename=name,
        declared_content_type=declared_content_type,
        content_type=detected_type,
        size_bytes=size,
        sha256=digest.hexdigest(),
        page_count=page_count,
        metadata=metadata,
        partial_path=partial,
        final_path=directory / f"{document_id}{STORED_EXTENSIONS[detected_type]}",
    )


def _inspect(path: Path, content_type: str) -> tuple[int, dict]:
    if content_type == "application/pdf":
        try:
            info = inspect_pdf(path)
        except UnreadablePdf as exc:
            raise InvalidFile(str(exc)) from exc
        return info.page_count, {"pdf_version": info.pdf_version}

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            dpi = image.info.get("dpi")
            metadata = {
                "width": image.width,
                "height": image.height,
                "mode": image.mode,
                "dpi": [round(float(value)) for value in dpi] if dpi else None,
            }
    except Exception as exc:  # noqa: BLE001 — Pillow raises many error types for bad images
        raise InvalidFile("The image could not be read (corrupt or unsupported file)") from exc
    return 1, metadata


def _force_remove(function, path, _exc) -> None:
    os.chmod(path, stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC)
    function(path)


def remove_all_claim_storage() -> None:
    root = claims_root()
    if root.exists():
        shutil.rmtree(root, onexc=_force_remove)

"""Build the demo document sets and their manifest, deterministically.

    uv run python -m app.demo_gen              # write ../demo_data
    uv run python -m app.demo_gen --out DIR    # write elsewhere
    uv run python -m app.demo_gen --check      # verify ../demo_data byte for byte
"""

import argparse
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.demo_gen import templates
from app.demo_gen.degrade import card_png, degraded_scan_jpeg
from app.demo_gen.issues import SEEDED_ISSUES
from app.demo_gen.profile import NOTICE, claim_template
from app.processing.pdf import MUPDF_LOCK
from app.processing.text import extract_page_text
from app.processing.types import normalise_bbox

GENERATOR_VERSION = 2
MANIFEST_NAME = "manifest.json"
OCR_FIXTURE_DIR = "ocr_fixtures"
FIXTURE_NOTE = (
    "Text and geometry captured from the synthetic source document while the demo data was "
    "generated. This is NOT the output of an OCR engine. It lets the offline demo read the "
    "image documents on a machine where the OCR extras are not installed; results produced "
    "from it are labelled demo_fixture everywhere they appear."
)
SET_NAMES = ("initial", "operative_note", "anaesthesia_record")
MEDIA_TYPES = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg"}


@dataclass(frozen=True)
class DocSpec:
    set_name: str
    folder: str
    filename: str
    label: str
    expected_doc_type: str  # ground truth for tests only; the application never reads it
    build: Callable[[], bytes] | None = None
    copy_of: str | None = None
    # For documents that are images of a page: the page they were rendered from, used to
    # capture the offline OCR fixture.
    source_pdf: Callable[[], bytes] | None = None

    @property
    def path(self) -> str:
        return f"{self.folder}/{self.filename}"

    @property
    def media_type(self) -> str:
        return MEDIA_TYPES[Path(self.filename).suffix]


DOCUMENTS = (
    DocSpec("initial", "initial", "01_Patient_ID.png", "Patient ID (insurer health e-card)", "patient_id",
            lambda: card_png(templates.patient_id_card()), source_pdf=templates.patient_id_card),
    DocSpec("initial", "initial", "02_Admission_Form.pdf", "Admission form", "admission_record",
            templates.admission_form),
    DocSpec("initial", "initial", "03_Doctor_Consultation.pdf", "Doctor consultation note", "consultation",
            templates.doctor_consultation),
    DocSpec("initial", "initial", "04_PreOp_Assessment.pdf", "Pre-operative assessment", "pre_operative_assessment",
            templates.preop_assessment),
    DocSpec("initial", "initial", "05_Anaesthesia_Assessment.pdf", "Pre-anaesthetic check-up",
            "anaesthesia_assessment", templates.anaesthesia_assessment),
    DocSpec("initial", "initial", "06_Discharge_Summary.pdf", "Discharge summary", "discharge_summary",
            templates.discharge_summary),
    DocSpec("initial", "initial", "07_Prescription.pdf", "Discharge prescription", "prescription",
            templates.prescription),
    DocSpec("initial", "initial", "08_Nursing_Record.pdf", "Nursing record", "nursing_record",
            templates.nursing_record),
    DocSpec("initial", "initial", "09_USG_Abdomen_Scan.jpg", "USG abdomen report (poor-quality scan)",
            "investigation_report", lambda: degraded_scan_jpeg(templates.usg_report()),
            source_pdf=templates.usg_report),
    DocSpec("initial", "initial", "10_Lab_Report.pdf", "Laboratory report", "lab_report", templates.lab_report),
    DocSpec("initial", "initial", "11_Lab_Report_copy.pdf", "Laboratory report (duplicate copy)", "lab_report",
            copy_of="10_Lab_Report.pdf"),
    DocSpec("initial", "initial", "12_Main_Hospital_Bill.pdf", "Main hospital bill", "hospital_bill",
            templates.main_hospital_bill),
    DocSpec("initial", "initial", "13_Pharmacy_Bill.pdf", "Pharmacy bill", "pharmacy_bill", templates.pharmacy_bill),
    DocSpec("initial", "initial", "14_OT_Bill.pdf", "Operation theatre bill", "ot_bill", templates.ot_bill),
    DocSpec("initial", "initial", "15_Implant_Invoice.pdf", "Implant invoice", "implant_invoice",
            templates.implant_invoice),
    DocSpec("initial", "initial", "16_Consent_Form.pdf", "Consent form", "consent", templates.consent_form),
    DocSpec("operative_note", "later", "scan_0042.pdf", "Operative note (generic scan filename)", "operative_note",
            templates.operative_note),
    DocSpec("anaesthesia_record", "later", "Anaesthesia_Record.pdf", "Anaesthesia record", "anaesthesia_record",
            templates.anaesthesia_record),
)


@dataclass(frozen=True)
class GeneratedData:
    files: dict[str, bytes]  # manifest path -> content
    manifest: dict
    manifest_bytes: bytes


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _page_count(data: bytes, media_type: str) -> int:
    if media_type != "application/pdf":
        return 1
    with MUPDF_LOCK:
        document = pymupdf.open(stream=data, filetype="pdf")
        try:
            return document.page_count
        finally:
            document.close()


def build_documents() -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    for spec in DOCUMENTS:
        files[spec.path] = files[f"{spec.folder}/{spec.copy_of}"] if spec.copy_of else spec.build()
    for spec in DOCUMENTS:
        if spec.source_pdf is None:
            continue
        digest = sha256_bytes(files[spec.path])
        fixture = build_ocr_fixture(spec.source_pdf(), filename=spec.filename, document_sha256=digest)
        files[f"{OCR_FIXTURE_DIR}/{digest}.json"] = serialize_json(fixture)
    return files


def build_ocr_fixture(pdf_bytes: bytes, *, filename: str, document_sha256: str) -> dict:
    """Capture the visible text of a page, as columns with page-relative boxes.

    The fixture mirrors what an OCR engine returns — one entry per run of text — so the
    offline path and the real OCR path feed the same pipeline code.
    """
    pages: list[dict] = []
    with MUPDF_LOCK:
        document = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        try:
            for index in range(document.page_count):
                page = document.load_page(index)
                lines, _ = extract_page_text(page)
                width, height = float(page.rect.width), float(page.rect.height)
                entries = []
                for line in lines:
                    for cell in line.cells():
                        if cell.bbox is None or not cell.text.strip():
                            continue
                        entries.append(
                            {
                                "text": cell.text,
                                "bbox": normalise_bbox(cell.bbox, width, height),
                                "confidence": 1.0,
                            }
                        )
                pages.append({"page": index + 1, "lines": entries})
        finally:
            document.close()
    return {
        "document": filename,
        "document_sha256": document_sha256,
        "engine": "demo_fixture",
        "synthetic": True,
        "note": FIXTURE_NOTE,
        "pages": pages,
    }


def build_manifest(files: dict[str, bytes]) -> dict:
    issues_by_file: dict[str, list[str]] = {}
    for issue in SEEDED_ISSUES:
        for filename in issue["documents"]:
            issues_by_file.setdefault(filename, []).append(issue["id"])

    sets: dict[str, list[dict]] = {name: [] for name in SET_NAMES}
    for spec in DOCUMENTS:
        data = files[spec.path]
        entry = {
            "filename": spec.filename,
            "path": spec.path,
            "label": spec.label,
            "media_type": spec.media_type,
            "pages": _page_count(data, spec.media_type),
            "size_bytes": len(data),
            "sha256": sha256_bytes(data),
            "expected_doc_type": spec.expected_doc_type,
            "seeded_issues": issues_by_file.get(spec.filename, []),
        }
        if spec.copy_of:
            entry["duplicate_of"] = spec.copy_of
        sets[spec.set_name].append(entry)

    fixtures = []
    for spec in DOCUMENTS:
        if spec.source_pdf is None:
            continue
        digest = sha256_bytes(files[spec.path])
        path = f"{OCR_FIXTURE_DIR}/{digest}.json"
        content = files[path]
        fixtures.append(
            {
                "path": path,
                "document": spec.filename,
                "document_sha256": digest,
                "size_bytes": len(content),
                "sha256": sha256_bytes(content),
                "lines": sum(len(page["lines"]) for page in json.loads(content)["pages"]),
            }
        )

    claim = claim_template()
    return {
        "name": "ClaimAI synthetic demo claim",
        "notice": NOTICE,
        "synthetic": True,
        "generator_version": GENERATOR_VERSION,
        "note": (
            "All people, organisations, identifiers and values are fictional. "
            "expected_doc_type and seeded_issues are test ground truth; the application never reads them."
        ),
        "claim": {
            **claim,
            "admission_date": claim["admission_date"].isoformat(),
            "discharge_date": claim["discharge_date"].isoformat(),
        },
        "sets": sets,
        "ocr_fixtures": fixtures,
        "ocr_fixture_note": FIXTURE_NOTE,
        "seeded_issues": [dict(issue) for issue in SEEDED_ISSUES],
    }


def serialize_json(payload: dict) -> bytes:
    return (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def serialize_manifest(manifest: dict) -> bytes:
    return serialize_json(manifest)


def generate_in_memory() -> GeneratedData:
    files = build_documents()
    manifest = build_manifest(files)
    return GeneratedData(files=files, manifest=manifest, manifest_bytes=serialize_manifest(manifest))


def write_file(target: Path, content: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f".{target.name}.tmp")
    temporary.write_bytes(content)
    temporary.replace(target)


def write_generated(data: GeneratedData, out_dir: Path) -> None:
    for path, content in data.files.items():
        write_file(out_dir / path, content)
    write_file(out_dir / MANIFEST_NAME, data.manifest_bytes)


def compare_with_directory(data: GeneratedData, directory: Path) -> list[str]:
    """Paths whose on-disk bytes differ from the freshly generated data."""
    problems = []
    for path, content in {**data.files, MANIFEST_NAME: data.manifest_bytes}.items():
        target = directory / path
        if not target.is_file():
            problems.append(f"{path}: missing")
        elif target.read_bytes() != content:
            problems.append(f"{path}: differs")
    return problems


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings

    parser = argparse.ArgumentParser(prog="python -m app.demo_gen", description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=get_settings().demo_data_dir, help="output directory")
    parser.add_argument("--check", action="store_true", help="verify --out matches freshly generated data")
    args = parser.parse_args(argv)

    data = generate_in_memory()
    if args.check:
        problems = compare_with_directory(data, args.out)
        for problem in problems:
            print(f"MISMATCH  {problem}")
        print(f"{'FAILED' if problems else 'OK'}: {len(data.files)} files checked in {args.out}")
        return 1 if problems else 0

    write_generated(data, args.out)
    for path, content in data.files.items():
        print(f"{sha256_bytes(content)}  {path}")
    print(f"{sha256_bytes(data.manifest_bytes)}  {MANIFEST_NAME}")
    print(f"Wrote {len(data.files)} files to {args.out}")
    return 0

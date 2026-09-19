"""The report as a workbook, written directly as Office Open XML.

A .xlsx file is a zip of XML parts, so it is written here rather than through a library: the
prototype gains no dependency, the demo keeps working with nothing installed from a network,
and the same bytes come out for the same report every time (the zip entries carry a fixed
timestamp and a fixed order).

The sheets are the report's own sections. Nothing is calculated here.
"""

from __future__ import annotations

import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from xml.sax.saxutils import escape

# Zip entries are stamped with this instead of the clock, so a report renders byte for byte
# the same whenever it is asked for.
FIXED_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
MAX_CELL_CHARACTERS = 32_000


@dataclass(frozen=True)
class Sheet:
    name: str
    headers: Sequence[str]
    rows: Sequence[Sequence[object]]


def _column(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _clean(text: str) -> str:
    """Strip the characters XML cannot carry, and keep a cell within the format's limit."""
    stripped = "".join(char for char in text if char >= " " or char in "\t\n")
    return stripped[:MAX_CELL_CHARACTERS]


def _cell(reference: str, value: object, *, header: bool) -> str:
    style = ' s="1"' if header else ""
    if value is None or value == "":
        return f'<c r="{reference}"{style}/>'
    if isinstance(value, bool):
        return f'<c r="{reference}"{style} t="inlineStr"><is><t>{"yes" if value else "no"}</t></is></c>'
    if isinstance(value, (int, float, Decimal)):
        return f'<c r="{reference}"{style}><v>{value}</v></c>'
    text = str(value)
    if isinstance(value, str) and _looks_numeric(text):
        return f'<c r="{reference}"{style}><v>{Decimal(text.replace(",", ""))}</v></c>'
    return (
        f'<c r="{reference}"{style} t="inlineStr">'
        f'<is><t xml:space="preserve">{escape(_clean(text))}</t></is></c>'
    )


def _looks_numeric(text: str) -> bool:
    candidate = text.replace(",", "").strip()
    if not candidate or candidate in {"-", "."}:
        return False
    try:
        Decimal(candidate)
    except (InvalidOperation, ValueError):
        return False
    return True


def _sheet_xml(sheet: Sheet) -> str:
    rows = [f'<row r="1">{"".join(_cell(f"{_column(i)}1", h, header=True) for i, h in enumerate(sheet.headers))}</row>']
    for row_index, row in enumerate(sheet.rows, start=2):
        cells = "".join(
            _cell(f"{_column(column_index)}{row_index}", value, header=False)
            for column_index, value in enumerate(row)
        )
        rows.append(f'<row r="{row_index}">{cells}</row>')
    widths = "".join(
        f'<col min="{index + 1}" max="{index + 1}" width="{_width(sheet, index)}" customWidth="1"/>'
        for index in range(len(sheet.headers))
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" '
        'state="frozen"/></sheetView></sheetViews>'
        f"<cols>{widths}</cols>"
        f'<sheetData>{"".join(rows)}</sheetData></worksheet>'
    )


def _width(sheet: Sheet, index: int) -> int:
    longest = len(str(sheet.headers[index]))
    for row in sheet.rows:
        if index < len(row) and row[index] is not None:
            longest = max(longest, len(str(row[index])))
    return max(10, min(60, longest + 2))


def _safe_name(name: str, taken: set[str]) -> str:
    cleaned = "".join(char for char in name if char not in "[]:*?/\\")[:31] or "Sheet"
    candidate, suffix = cleaned, 2
    while candidate in taken:
        candidate = f"{cleaned[:28]}_{suffix}"
        suffix += 1
    taken.add(candidate)
    return candidate


def workbook(sheets: Sequence[Sheet], *, title: str, generated_at: str) -> bytes:
    """A .xlsx file with one sheet per section."""
    taken: set[str] = set()
    named = [Sheet(_safe_name(sheet.name, taken), sheet.headers, sheet.rows) for sheet in sheets]

    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-'
        'properties+xml"/>'
        + "".join(
            f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.'
            f'openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for index in range(1, len(named) + 1)
        )
        + "</Types>"
    )

    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="xl/workbook.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/'
        'core-properties" Target="docProps/core.xml"/>'
        "</Relationships>"
    )

    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" '
        'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
        f"<dc:title>{escape(title)}</dc:title>"
        f'<dcterms:created xsi:type="dcterms:W3CDTF">{escape(generated_at)}</dcterms:created>'
        "</cp:coreProperties>"
    )

    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'
        + "".join(
            f'<sheet name="{escape(sheet.name)}" sheetId="{index}" r:id="rId{index}"/>'
            for index, sheet in enumerate(named, start=1)
        )
        + "</sheets></workbook>"
    )

    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + "".join(
            f'<Relationship Id="rId{index}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
            f'relationships/worksheet" Target="worksheets/sheet{index}.xml"/>'
            for index in range(1, len(named) + 1)
        )
        + f'<Relationship Id="rId{len(named) + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        'relationships/styles" Target="styles.xml"/>'
        "</Relationships>"
    )

    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
        '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="2"><fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill></fills>'
        '<borders count="1"><border/></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/></cellXfs>'
        "</styleSheet>"
    )

    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        parts = [
            ("[Content_Types].xml", content_types),
            ("_rels/.rels", root_rels),
            ("docProps/core.xml", core),
            ("xl/workbook.xml", workbook_xml),
            ("xl/_rels/workbook.xml.rels", workbook_rels),
            ("xl/styles.xml", styles),
        ]
        parts.extend(
            (f"xl/worksheets/sheet{index}.xml", _sheet_xml(sheet))
            for index, sheet in enumerate(named, start=1)
        )
        for name, payload in parts:
            info = zipfile.ZipInfo(name, date_time=FIXED_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            archive.writestr(info, payload)
    return buffer.getvalue()


# --- the report's own sheets ------------------------------------------------------------------


def _row_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def sheets_for(report: dict) -> list[Sheet]:
    """One sheet per section of the report, in reading order."""
    meta = report["meta"]
    claim = report["claim"]
    readiness = report["readiness"]
    review = report["review"]
    summary = report["summary"]

    claim_rows: list[list[object]] = [
        ["Report", meta["title"]],
        ["Generated", meta["generated_at"]],
        ["Generator", meta["generator"]],
        ["Claim number", claim["claim_number"]],
        ["Patient", claim["patient_name"]],
        ["UHID", claim["uhid"]],
        ["Hospital", claim["hospital"]],
        ["Insurer", claim["insurer"]],
        ["TPA", claim["tpa"]],
        ["Admission date", claim["admission_date"]],
        ["Discharge date", claim["discharge_date"]],
        ["Created by", claim["created_by"]],
        ["Readiness score", readiness["score"]],
        ["Readiness status", readiness["status_label"]],
        ["Review state", review["state"]],
        ["Human review", review["line"]],
        ["Approved by", review["approved_by"]],
        ["Approved at", review["approved_at"]],
        ["Superseded at", review["superseded_at"]],
        ["Documents", summary["documents"]],
        ["Documents excluded", summary["documents_excluded"]],
        ["Findings open", summary["findings_open"]],
        ["Findings total", summary["findings_total"]],
        ["Requirements outstanding", summary["requirements_outstanding"]],
        ["Questions open", summary["questions_open"]],
        ["Checks run", summary["checks_total"]],
        ["Audit events", summary["audit_events"]],
        ["Snapshot", meta["content_sha256"]],
        ["Disclaimer", meta["disclaimer"]],
    ]
    if meta["demo_notice"]:
        claim_rows.append(["Demo notice", meta["demo_notice"]])

    readiness_rows = [
        [item["reason"], item["source"]["kind"], item["source"]["label"], -item["amount"]]
        for item in readiness["breakdown"]["deductions"]
    ]
    readiness_rows.append(["Final score", "", "", readiness["score"]])

    facts_rows = [
        [
            section["label"],
            value["label"],
            _row_text(value["value"]),
            value["source_count"],
            "; ".join(
                f"{source['document_name']}" + (f" p{source['page']}" if source["page"] else "")
                for source in value["sources"]
            ),
            "; ".join(f"{item['value']} ({item['source_count']})" for item in value["competing_values"]),
        ]
        for section in report["documented_facts"]
        for value in section["values"]
        if value["present"] or value["sources"]
    ]

    findings_rows = [
        [
            finding["code"],
            finding["rule_id"],
            finding["severity"],
            finding["status"],
            finding["title"],
            finding["explanation"],
            finding["action"],
            finding["attribution"],
            "; ".join(
                f"{item['document_name']}" + (f" p{item['page']}" if item["page"] else "")
                for item in finding["evidence"]
            ),
            (finding["decision"] or {}).get("actor") or "",
            (finding["decision"] or {}).get("note") or "",
            finding["occurrences"],
            finding["first_seen_at"],
        ]
        for finding in report["system_findings"]
    ]

    checklist_rows = [
        [
            item["label"],
            item["key"],
            item["status"],
            "required" if item["required"] else "supporting",
            item["severity"],
            "; ".join(item["documents"]),
            "; ".join(item["findings"]),
            item["detail"],
            item["resolution"],
        ]
        for item in report["checklist"]["items"]
    ]

    question_rows = [
        [
            question["requirement_label"],
            question["question"],
            question["status"],
            question["expected_document_type"],
            _row_text(question["answer"]),
            _row_text(question["answer_reason"]),
            _row_text(question["answered_by"]),
            _row_text(question["answered_at"]),
            question["reason"],
        ]
        for question in report["questions"]
    ]

    source_file_rows = [
        [
            entry["filename"],
            entry["page_count"],
            entry["document_count"],
            "; ".join(f"{item['doc_type_label']} pp. {item['pages']}" for item in entry["documents"]),
            entry["sha256"],
            entry["uploaded_at"],
        ]
        for entry in (report.get("source_files") or [])
    ]

    document_rows = [
        [
            document["display_name"],
            _row_text(document["pages"]),
            _row_text(document["doc_type_label"]),
            document["classification_confidence"],
            document["page_count"],
            document["processing_status"],
            _row_text(document["ocr_engine"] or document["text_source"]),
            ", ".join(document["quality_signals"]),
            document["concealed_text_count"],
            ", ".join(document["unsigned_required_slots"]),
            document["extracted_field_count"],
            "yes" if document["excluded"] else "no",
            _row_text(document["exclusion_reason"]),
            document["sha256"],
            document["uploaded_at"],
        ]
        for document in report["documents"]
    ]

    bill_rows = [
        [
            bill["document_name"],
            _row_text(bill["bill_type_label"]),
            _row_text(bill["number"]),
            _row_text(bill["date"]),
            bill["line_item_count"],
            _row_text(bill["subtotal"]),
            _row_text(bill["tax"]),
            _row_text(bill["discount"]),
            _row_text(bill["total"]),
        ]
        for bill in report["bills"]["items"]
    ]

    check_rows = [
        [check["check_id"], check["title"], check["status"], check["detail"], ", ".join(check.get("rule_ids", []))]
        for check in report["validation_checks"]
    ]

    decision_rows = [
        [
            decision["kind"],
            decision["subject"],
            decision["decision"],
            _row_text(decision["actor"]),
            _row_text(decision["at"]),
            _row_text(decision["note"]),
            decision["reference"],
        ]
        for decision in report["human_decisions"]
    ]

    unresolved_rows = [
        [item["kind"], item["label"], item["detail"], item["action"], item["source"]]
        for item in report["unresolved"]
    ]

    audit_rows = [
        [
            event["created_at"],
            event["event_type"],
            event["actor"],
            event["message"],
            _row_text(event["document_id"]),
            "; ".join(f"{key}={value}" for key, value in sorted(event["details"].items())),
        ]
        for event in report["audit_trail"]
    ]

    return [
        Sheet("Claim Summary", ["Field", "Value"], claim_rows),
        Sheet("Readiness", ["Reason", "Kind", "For", "Points"], readiness_rows),
        Sheet("Documented Facts", ["Section", "Value", "As documented", "Sources", "Read from", "Also stated as"], facts_rows),
        Sheet(
            "Findings",
            [
                "Code",
                "Rule",
                "Severity",
                "Status",
                "Title",
                "Explanation",
                "Action",
                "Attribution",
                "Evidence",
                "Decided by",
                "Decision note",
                "Occurrences",
                "First seen",
            ],
            findings_rows,
        ),
        Sheet("Checks", ["Check", "Title", "Result", "Detail", "Rules"], check_rows),
        Sheet(
            "Checklist",
            ["Requirement", "Key", "Status", "Classification", "Severity", "Documents", "Findings", "Detail", "What it needs"],
            checklist_rows,
        ),
        Sheet(
            "Questions",
            ["Requirement", "Question", "Status", "Expected type", "Answer", "Reason", "Answered by", "Answered at", "Why asked"],
            question_rows,
        ),
        Sheet("Human Decisions", ["Kind", "Subject", "Decision", "By", "At", "Note", "Reference"], decision_rows),
        Sheet("Unresolved", ["Kind", "Item", "Why", "What to do", "Reported by"], unresolved_rows),
        Sheet(
            "Uploaded Files",
            ["File", "Pages", "Documents found", "Documents", "SHA-256", "Uploaded"],
            source_file_rows,
        ),
        Sheet(
            "Documents",
            [
                "Document",
                "Pages of the file",
                "Type",
                "Confidence",
                "Pages",
                "Status",
                "Read by",
                "Quality signals",
                "Covered text",
                "Unsigned slots",
                "Values",
                "Excluded",
                "Exclusion reason",
                "SHA-256",
                "Uploaded",
            ],
            document_rows,
        ),
        Sheet("Bills", ["Document", "Type", "Number", "Date", "Lines", "Subtotal", "Tax", "Discount", "Total"], bill_rows),
        Sheet("Audit Trail", ["When", "Event", "Actor", "Message", "Document", "Details"], audit_rows),
    ]


def render(report: dict) -> bytes:
    """The whole report as a workbook."""
    meta = report["meta"]
    return workbook(
        sheets_for(report),
        title=f"{meta['title']} — {meta['claim_number']}",
        generated_at=meta["generated_at"],
    )

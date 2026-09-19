"""The report as a standalone HTML page.

One file with its own styles and no scripts, so it can be saved, emailed or printed and still
read the same. Everything on the page comes from the report payload; this module chooses how to
show it and decides nothing.
"""

from __future__ import annotations

from html import escape

from app.reports.model import TITLE
from app.text import plural

STYLES = """
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: #f6f8fa; color: #1c2733;
  font: 14px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; }
main { max-width: 900px; margin: 0 auto; padding: 32px 20px 64px; }
header.cover { background: #0f2436; color: #fff; padding: 28px 24px; border-radius: 12px; }
header.cover h1 { margin: 0 0 4px; font-size: 22px; letter-spacing: -0.01em; }
header.cover p { margin: 2px 0; color: #b9c7d4; font-size: 13px; }
.score { display: flex; align-items: baseline; gap: 12px; margin-top: 16px; }
.score b { font-size: 38px; font-weight: 600; letter-spacing: -0.02em; }
.pill { display: inline-block; padding: 2px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; }
.pill.ready { background: #d1fae5; color: #065f46; }
.pill.needs_attention { background: #fef3c7; color: #92400e; }
.pill.incomplete { background: #fee2e2; color: #991b1b; }
.pill.critical { background: #fee2e2; color: #991b1b; }
.pill.review { background: #fef3c7; color: #92400e; }
.pill.warning { background: #e0f2fe; color: #075985; }
.pill.info { background: #e5e7eb; color: #374151; }
.pill.muted { background: #e5e7eb; color: #374151; }
section { background: #fff; border: 1px solid #e3e8ee; border-radius: 12px; margin-top: 20px; overflow: hidden; }
section > h2 { margin: 0; padding: 14px 20px; font-size: 15px; border-bottom: 1px solid #eef1f5; }
section > p.lead { margin: 0; padding: 10px 20px; color: #64748b; font-size: 12.5px; border-bottom: 1px solid #eef1f5; }
.body { padding: 14px 20px; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
th { text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: .04em; color: #64748b;
  padding: 8px 20px; border-bottom: 1px solid #eef1f5; font-weight: 600; }
td { padding: 8px 20px; border-bottom: 1px solid #f2f5f8; vertical-align: top; }
tr:last-child td { border-bottom: none; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.muted { color: #64748b; }
.small { font-size: 12px; }
dl.kv { display: grid; grid-template-columns: 220px 1fr; gap: 6px 16px; margin: 0; }
dl.kv dt { color: #64748b; }
dl.kv dd { margin: 0; }
.notice { margin-top: 16px; padding: 12px 16px; border-radius: 10px; background: #fff7ed; color: #7c2d12;
  border: 1px solid #fed7aa; font-size: 12.5px; }
.legend { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 10px; }
.legend div { background: #f8fafc; border: 1px solid #eef1f5; border-radius: 8px; padding: 10px 12px; font-size: 12px; }
.legend b { display: block; margin-bottom: 2px; }
footer { margin-top: 28px; color: #64748b; font-size: 12px; text-align: center; }
@media print {
  body { background: #fff; }
  main { max-width: none; padding: 0; }
  section { break-inside: avoid; border-color: #d8dee6; }
  header.cover { background: #fff; color: #1c2733; border: 1px solid #d8dee6; }
  header.cover p { color: #4b5563; }
}
"""

STATUS_CLASS = {
    "ready_for_human_review": "ready",
    "needs_attention": "needs_attention",
    "incomplete": "incomplete",
}


def _e(value) -> str:
    if value is None or value == "":
        return "—"
    return escape(str(value))


def _pill(text: str, kind: str = "muted") -> str:
    return f'<span class="pill {escape(kind)}">{_e(text)}</span>'


def _rows(headers: list[str], rows: list[list[str]], numeric: set[int] | None = None) -> str:
    numeric = numeric or set()
    if not rows:
        return '<p class="body muted">Nothing to report here.</p>'
    head = "".join(f'<th{" class=\"num\"" if index in numeric else ""}>{_e(text)}</th>' for index, text in enumerate(headers))
    body = "".join(
        "<tr>"
        + "".join(
            f'<td{" class=\"num\"" if index in numeric else ""}>{cell}</td>' for index, cell in enumerate(row)
        )
        + "</tr>"
        for row in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def _section(title: str, lead: str, content: str) -> str:
    return f"<section><h2>{_e(title)}</h2><p class=\"lead\">{_e(lead)}</p>{content}</section>"


def render(report: dict) -> str:
    """The whole report as one HTML document."""
    meta = report["meta"]
    claim = report["claim"]
    readiness = report["readiness"]
    review = report["review"]
    summary = report["summary"]

    parts: list[str] = []

    parts.append(
        f"""<header class="cover">
  <h1>{_e(meta['title'])}</h1>
  <p>Claim {_e(claim['claim_number'])} · {_e(claim['patient_name'])} · {_e(claim['hospital'])}</p>
  <p>Generated {_e(meta['generated_at'])} · {_e(meta['generator'])}</p>
  <div class="score">
    <b>{readiness['score']}%</b>
    {_pill(readiness['status_label'], STATUS_CLASS.get(readiness['status'], 'muted'))}
    <span class="small">{_e(readiness['status_detail'])}</span>
  </div>
  <p>{_e(review["line"])}</p>
</header>"""
    )

    if meta["demo_notice"]:
        parts.append(f'<div class="notice">{_e(meta["demo_notice"])}</div>')
    parts.append(f'<div class="notice">{_e(meta["disclaimer"])}</div>')

    parts.append(
        _section(
            "How to read this report",
            "Four kinds of statement are kept apart.",
            '<div class="body"><div class="legend">'
            "<div><b>Documented facts</b>What the uploaded documents say, with the document and page each value was read from.</div>"
            "<div><b>System findings</b>What the deterministic rules concluded by comparing those documents.</div>"
            "<div><b>Unresolved items</b>What the claim is still waiting for.</div>"
            "<div><b>Human decisions</b>What a person recorded: a finding dealt with, a question answered, an approval.</div>"
            "</div></div>",
        )
    )

    parts.append(
        _section(
            "Claim",
            "What was entered when the claim was created.",
            '<div class="body"><dl class="kv">'
            + "".join(
                f"<dt>{_e(label)}</dt><dd>{_e(value)}</dd>"
                for label, value in (
                    ("Claim number", claim["claim_number"]),
                    ("Patient", claim["patient_name"]),
                    ("UHID", claim["uhid"]),
                    ("Hospital", claim["hospital"]),
                    ("Insurer", claim["insurer"]),
                    ("TPA", claim["tpa"]),
                    ("Admission", claim["admission_date"]),
                    ("Discharge", claim["discharge_date"]),
                    ("Created by", claim["created_by"]),
                    ("Documents", summary["documents"]),
                    ("Snapshot", meta["content_sha256"][:16] + "…"),
                )
            )
            + "</dl></div>",
        )
    )

    deductions = readiness["breakdown"]["deductions"]
    parts.append(
        _section(
            "Documentation readiness",
            f"{readiness['breakdown']['base_score']} to start, less every item still outstanding.",
            _rows(
                ["Reason", "For", "Points"],
                [
                    [_e(item["reason"]), _e(item["source"]["label"]), f"−{item['amount']}"]
                    for item in deductions
                ]
                + [["<b>Final score</b>", "", f"<b>{readiness['score']}%</b>"]],
                numeric={2},
            )
            if deductions
            else f'<p class="body">Nothing is outstanding: {readiness["score"]}%.</p>',
        )
    )

    facts_html = []
    for section in report["documented_facts"]:
        rows = []
        for value in section["values"]:
            if not value["present"] and not value["sources"]:
                continue
            sources = "; ".join(
                f"{_e(source['document_name'])}" + (f" p{source['page']}" if source["page"] else "")
                for source in value["sources"][:4]
            )
            if len(value["sources"]) > 4:
                sources += f" and {len(value['sources']) - 4} more"
            competing = (
                "<div class=\"small muted\">also stated as "
                + "; ".join(f"{_e(item['value'])} ({item['source_count']})" for item in value["competing_values"])
                + "</div>"
                if value["competing_values"]
                else ""
            )
            rows.append([_e(value["label"]), _e(value["value"]) + competing, sources or "—"])
        if rows:
            facts_html.append(f"<h3 class=\"body\" style=\"margin:0;font-size:13px\">{_e(section['label'])}</h3>")
            facts_html.append(_rows(["Value", "As documented", "Read from"], rows))
    parts.append(
        _section(
            "Documented facts",
            "Every value below was read from a document in this claim.",
            "".join(facts_html) or '<p class="body muted">No values have been read yet.</p>',
        )
    )

    parts.append(
        _section(
            "System findings",
            "Raised by the deterministic rules. Nothing here is a clinical conclusion.",
            _rows(
                ["Finding", "Severity", "Status", "Evidence"],
                [
                    [
                        f"<b>{_e(finding['title'])}</b><div class=\"small muted\">{_e(finding['explanation'])}</div>"
                        f"<div class=\"small\"><b>Do</b> {_e(finding['action'])}</div>",
                        _pill(finding["severity"], finding["severity"]),
                        _e(finding["status"].replace("_", " ")),
                        "<br>".join(
                            f"{_e(item['document_name'])}" + (f" p{item['page']}" if item["page"] else "")
                            for item in finding["evidence"]
                        )
                        or '<span class="muted">No page evidence for this finding</span>',
                    ]
                    for finding in report["system_findings"]
                ],
            ),
        )
    )

    parts.append(
        _section(
            "Cross-document validation",
            "Every check the rules ran over this claim.",
            _rows(
                ["Check", "Result", "Detail"],
                [
                    [_e(check["title"]), _e(check["status"].replace("_", " ")), _e(check["detail"])]
                    for check in report["validation_checks"]
                ],
            ),
        )
    )

    checklist = report["checklist"]
    procedure = (checklist.get("procedure") or {}).get("label") or "no procedure named"
    parts.append(
        _section(
            "Procedure checklist",
            f"What a claim for {procedure} is expected to carry."
            if checklist["available"]
            else (checklist.get("note") or "No checklist applies to this claim."),
            _rows(
                ["Requirement", "Status", "Documents", "What it needs"],
                [
                    [
                        _e(item["label"]) + ("" if item["required"] else ' <span class="pill muted">supporting</span>'),
                        _e(item["status"].replace("_", " ")),
                        "<br>".join(_e(name) for name in item["documents"]) or "—",
                        _e(item["detail"]),
                    ]
                    for item in checklist["items"]
                ],
            ),
        )
    )

    parts.append(
        _section(
            "Questions and resolutions",
            "What the claim asked the operator for, and what came back.",
            _rows(
                ["Request", "Status", "Answer", "Recorded"],
                [
                    [
                        f"<b>{_e(question['requirement_label'])}</b><div class=\"small muted\">{_e(question['question'])}</div>",
                        _e(question["status"].replace("_", " ")),
                        _e((question["answer"] or "—").replace("_", " "))
                        + (f"<div class=\"small muted\">{_e(question['answer_reason'])}</div>" if question["answer_reason"] else ""),
                        _e(question["answered_by"]) + (f"<div class=\"small muted\">{_e(question['answered_at'])}</div>" if question["answered_at"] else ""),
                    ]
                    for question in report["questions"]
                ],
            ),
        )
    )

    parts.append(
        _section(
            "Unresolved items",
            "What this claim is still waiting for.",
            _rows(
                ["Item", "Why", "What to do"],
                [[_e(item["label"]), _e(item["detail"]), _e(item["action"])] for item in report["unresolved"]],
            ),
        )
    )

    parts.append(
        _section(
            "Human decisions",
            "Recorded by a person. Nothing in the system decides these.",
            _rows(
                ["What", "Decision", "By", "Note"],
                [
                    [
                        f"{_e(decision['subject'])}<div class=\"small muted\">{_e(decision['kind'])}</div>",
                        _e(decision["decision"].replace("_", " ")),
                        _e(decision["actor"]) + (f"<div class=\"small muted\">{_e(decision['at'])}</div>" if decision["at"] else ""),
                        _e(decision["note"]),
                    ]
                    for decision in report["human_decisions"]
                ],
            ),
        )
    )

    bills = report["bills"]
    parts.append(
        _section(
            "Bills",
            "As read from the documents. The arithmetic checks are in the findings above.",
            _rows(
                ["Bill", "Number", "Date", "Lines", "Subtotal", "Tax", "Total"],
                [
                    [
                        f"{_e(bill['bill_type_label'])}<div class=\"small muted\">{_e(bill['document_name'])}</div>",
                        _e(bill["number"]),
                        _e(bill["date"]),
                        str(bill["line_item_count"]),
                        _e(bill["subtotal"]),
                        _e(bill["tax"]),
                        _e(bill["total"]),
                    ]
                    for bill in bills["items"]
                ],
                numeric={3, 4, 5, 6},
            ),
        )
    )

    files = report.get("source_files") or []
    if any(entry["document_count"] > 1 for entry in files):
        parts.append(
            _section(
                "Uploaded files",
                "What was handed over, and the documents found inside each file.",
                _rows(
                    ["File", "Pages", "Documents found"],
                    [
                        [
                            _e(entry["filename"]),
                            str(entry["page_count"] or "—"),
                            "<br>".join(
                                _e(f"{item['doc_type_label']} — page{'s' if len(item['page_numbers']) > 1 else ''} {item['pages']}")
                                for item in entry["documents"]
                            ),
                        ]
                        for entry in files
                    ],
                    numeric={1},
                ),
            )
        )

    parts.append(
        _section(
            "Documents",
            "Every document in this claim, as it was read.",
            _rows(
                ["Document", "Type", "Pages", "Read by", "Signals", "Status"],
                [
                    [
                        _e(document["display_name"]),
                        _e(document["doc_type_label"]),
                        str(document["page_count"] or "—"),
                        _e(document["ocr_engine"] or document["text_source"]),
                        ", ".join(document["quality_signals"]) or "none",
                        ("Excluded — " + _e(document["exclusion_reason"]))
                        if document["excluded"]
                        else _e(document["processing_status"]),
                    ]
                    for document in report["documents"]
                ],
                numeric={2},
            ),
        )
    )

    parts.append(
        _section(
            "Audit trail",
            f"{plural(len(report['audit_trail']), 'event')}, oldest first, as recorded.",
            _rows(
                ["When", "Event", "Actor", "Message"],
                [
                    [_e(event["created_at"]), _e(event["event_type"]), _e(event["actor"]), _e(event["message"])]
                    for event in report["audit_trail"]
                ],
            ),
        )
    )

    parts.append(
        f'<footer>{_e(meta["disclaimer"])}<br>Claim {_e(claim["claim_number"])} · '
        f'report version {meta["report_version"]} · generated {_e(meta["generated_at"])}</footer>'
    )

    body = "\n".join(parts)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_e(TITLE)} · {_e(claim['claim_number'])}</title>
<style>{STYLES}</style>
</head>
<body><main>{body}</main></body>
</html>
"""

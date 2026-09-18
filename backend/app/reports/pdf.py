"""The report as a PDF: multi-page, numbered, and printed from the same payload as the rest.

The layout flows: each block asks for the room it needs and starts a new page when it does not
fit, so nothing is clipped and nothing is invented to fill a page. Every page carries the claim
number, the page number and the notice that a person makes the final decision.
"""

from __future__ import annotations

import io
from collections.abc import Sequence

from reportlab.lib.colors import Color, HexColor, white
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen.canvas import Canvas

PAGE_W, PAGE_H = A4
MARGIN = 42.0
CONTENT_W = PAGE_W - 2 * MARGIN
TOP = PAGE_H - 54.0
BOTTOM = 64.0

REGULAR = "Helvetica"
BOLD = "Helvetica-Bold"
ITALIC = "Helvetica-Oblique"

INK = HexColor("#1c2733")
MUTED = HexColor("#5b6b7c")
FAINT = HexColor("#8a99a8")
RULE = HexColor("#d7dee6")
BAND = HexColor("#0f2436")
SHADE = HexColor("#f1f5f9")

SEVERITY_COLOURS = {
    "critical": HexColor("#9b1c1c"),
    "review": HexColor("#92400e"),
    "warning": HexColor("#075985"),
    "info": HexColor("#475569"),
}
STATUS_COLOURS = {
    "ready_for_human_review": HexColor("#047857"),
    "needs_attention": HexColor("#b45309"),
    "incomplete": HexColor("#9b1c1c"),
}


def _text(value) -> str:
    if value is None or value == "":
        return "—"
    return str(value).replace("\n", " ").strip()


class Report:
    """A flowing page the report is drawn onto."""

    def __init__(
        self,
        canvas: Canvas,
        claim_number: str,
        generated_at: str,
        disclaimer: str,
        total_pages: int | None = None,
    ):
        self.canvas = canvas
        self.claim_number = claim_number
        self.generated_at = generated_at
        self.disclaimer = disclaimer
        self.total_pages = total_pages
        self.page = 0
        self.y = 0.0
        self._start_page()

    # --- page furniture -------------------------------------------------------------------

    def _start_page(self) -> None:
        self.page += 1
        self.y = TOP
        self.canvas.setFillColor(FAINT)
        self.canvas.setFont(REGULAR, 7.5)
        self.canvas.drawString(MARGIN, PAGE_H - 34, f"Claim {self.claim_number}")
        self.canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 34, self.generated_at)
        self.canvas.setStrokeColor(RULE)
        self.canvas.setLineWidth(0.5)
        self.canvas.line(MARGIN, PAGE_H - 42, PAGE_W - MARGIN, PAGE_H - 42)

    def _finish_page(self) -> None:
        self.canvas.setStrokeColor(RULE)
        self.canvas.setLineWidth(0.5)
        self.canvas.line(MARGIN, 52, PAGE_W - MARGIN, 52)
        self.canvas.setFont(ITALIC, 7)
        self.canvas.setFillColor(FAINT)
        self.canvas.drawString(MARGIN, 40, self.disclaimer)
        self.canvas.setFont(REGULAR, 7.5)
        label = f"Page {self.page}" if self.total_pages is None else f"Page {self.page} of {self.total_pages}"
        self.canvas.drawRightString(PAGE_W - MARGIN, 40, label)

    def _break(self) -> None:
        self._finish_page()
        self.canvas.showPage()
        self._start_page()

    def ensure(self, needed: float) -> None:
        if self.y - needed < BOTTOM:
            self._break()

    # --- blocks ---------------------------------------------------------------------------

    def cover(self, title: str, lines: Sequence[str], score: int, status_label: str, status: str) -> None:
        height = 116.0
        self.canvas.setFillColor(BAND)
        self.canvas.rect(MARGIN, self.y - height, CONTENT_W, height, stroke=0, fill=1)
        self.canvas.setFillColor(white)
        self.canvas.setFont(BOLD, 15)
        self.canvas.drawString(MARGIN + 16, self.y - 26, title)
        self.canvas.setFont(REGULAR, 9)
        text_y = self.y - 42
        for line in lines:
            self.canvas.setFillColor(HexColor("#b9c7d4"))
            self.canvas.drawString(MARGIN + 16, text_y, _text(line))
            text_y -= 12
        self.canvas.setFillColor(white)
        self.canvas.setFont(BOLD, 30)
        self.canvas.drawRightString(PAGE_W - MARGIN - 16, self.y - 46, f"{score}%")
        self.canvas.setFont(REGULAR, 9)
        self.canvas.setFillColor(HexColor("#b9c7d4"))
        self.canvas.drawRightString(PAGE_W - MARGIN - 16, self.y - 60, status_label)
        self.y -= height + 16

    def heading(self, text: str, lead: str | None = None) -> None:
        self.ensure(46)
        self.canvas.setFillColor(INK)
        self.canvas.setFont(BOLD, 11.5)
        self.canvas.drawString(MARGIN, self.y, text)
        self.y -= 13
        if lead:
            self.canvas.setFont(REGULAR, 8.2)
            self.canvas.setFillColor(MUTED)
            for line in simpleSplit(lead, REGULAR, 8.2, CONTENT_W):
                self.canvas.drawString(MARGIN, self.y, line)
                self.y -= 10
        self.canvas.setStrokeColor(RULE)
        self.canvas.setLineWidth(0.5)
        self.canvas.line(MARGIN, self.y + 2, PAGE_W - MARGIN, self.y + 2)
        self.y -= 8

    def paragraph(self, text: str, *, size: float = 8.6, colour: Color = INK, gap: float = 6) -> None:
        for line in simpleSplit(_text(text), REGULAR, size, CONTENT_W):
            self.ensure(size + 3)
            self.canvas.setFont(REGULAR, size)
            self.canvas.setFillColor(colour)
            self.canvas.drawString(MARGIN, self.y, line)
            self.y -= size + 3
        self.y -= gap

    def pairs(self, rows: Sequence[tuple[str, str]], *, label_width: float = 130.0) -> None:
        for label, value in rows:
            lines = simpleSplit(_text(value), REGULAR, 8.6, CONTENT_W - label_width - 8)
            self.ensure(max(12.0, len(lines) * 11.0))
            self.canvas.setFont(REGULAR, 8.6)
            self.canvas.setFillColor(MUTED)
            self.canvas.drawString(MARGIN, self.y, _text(label))
            self.canvas.setFillColor(INK)
            for index, line in enumerate(lines):
                self.canvas.drawString(MARGIN + label_width, self.y - index * 11, line)
            self.y -= max(12.0, len(lines) * 11.0)
        self.y -= 6

    def table(
        self,
        headers: Sequence[str],
        rows: Sequence[Sequence[str]],
        widths: Sequence[float],
        *,
        empty: str = "Nothing to report here.",
        colours: Sequence[Color | None] | None = None,
    ) -> None:
        if not rows:
            self.paragraph(empty, colour=MUTED)
            return
        total = sum(widths)
        widths = [width / total * CONTENT_W for width in widths]

        def draw_header() -> None:
            self.ensure(20)
            self.canvas.setFillColor(SHADE)
            self.canvas.rect(MARGIN, self.y - 13, CONTENT_W, 16, stroke=0, fill=1)
            self.canvas.setFont(BOLD, 7.4)
            self.canvas.setFillColor(MUTED)
            x = MARGIN + 4
            for header, width in zip(headers, widths, strict=True):
                self.canvas.drawString(x, self.y - 9, header.upper())
                x += width
            self.y -= 20

        draw_header()
        for index, row in enumerate(rows):
            cells = [simpleSplit(_text(cell), REGULAR, 8.2, width - 8) or ["—"] for cell, width in zip(row, widths, strict=True)]
            height = max(len(lines) for lines in cells) * 10.4 + 5
            if self.y - height < BOTTOM:
                self._break()
                draw_header()
            colour = (colours[index] if colours and index < len(colours) else None) or INK
            x = MARGIN + 4
            for lines, width in zip(cells, widths, strict=True):
                self.canvas.setFont(REGULAR, 8.2)
                for line_index, line in enumerate(lines):
                    self.canvas.setFillColor(colour if line_index == 0 else MUTED)
                    self.canvas.drawString(x, self.y - line_index * 10.4, line)
                x += width
            self.y -= height
            self.canvas.setStrokeColor(HexColor("#eef2f6"))
            self.canvas.setLineWidth(0.4)
            self.canvas.line(MARGIN, self.y + 3, PAGE_W - MARGIN, self.y + 3)
        self.y -= 8

    def notice(self, text: str) -> None:
        lines = simpleSplit(_text(text), ITALIC, 8.2, CONTENT_W - 20)
        height = len(lines) * 11 + 12
        self.ensure(height + 6)
        self.canvas.setFillColor(HexColor("#fff7ed"))
        self.canvas.setStrokeColor(HexColor("#fed7aa"))
        self.canvas.setLineWidth(0.6)
        self.canvas.roundRect(MARGIN, self.y - height + 6, CONTENT_W, height, 5, stroke=1, fill=1)
        self.canvas.setFont(ITALIC, 8.2)
        self.canvas.setFillColor(HexColor("#7c2d12"))
        for index, line in enumerate(lines):
            self.canvas.drawString(MARGIN + 10, self.y - 8 - index * 11, line)
        self.y -= height + 8


def _evidence_text(evidence: Sequence[dict]) -> str:
    if not evidence:
        return "No page evidence for this finding"
    parts = []
    for item in evidence[:4]:
        name = item.get("document_name") or "—"
        parts.append(f"{name} p{item['page']}" if item.get("page") else name)
    if len(evidence) > 4:
        parts.append(f"and {len(evidence) - 4} more")
    return "; ".join(parts)


def render(report: dict) -> bytes:
    """The whole report as a PDF.

    Drawn twice: the first pass counts the pages so that every page can say "Page 2 of 7".
    """
    _, pages = _draw(report, None)
    body, _ = _draw(report, pages)
    return body


def _draw(report: dict, total_pages: int | None) -> tuple[bytes, int]:
    meta = report["meta"]
    claim = report["claim"]
    readiness = report["readiness"]
    review = report["review"]
    summary = report["summary"]

    buffer = io.BytesIO()
    canvas = Canvas(buffer, pagesize=A4, pageCompression=1)
    canvas.setTitle(f"{meta['title']} — {claim['claim_number']}")
    canvas.setAuthor(meta["generator"])
    canvas.setSubject("Claim pre-submission validation")
    doc = Report(canvas, claim["claim_number"], meta["generated_at"], meta["disclaimer"], total_pages)

    doc.cover(
        meta["title"],
        [
            f"Claim {claim['claim_number']} · {claim['patient_name']} · {claim['hospital']}",
            f"Admitted {claim['admission_date']} · discharged {claim['discharge_date']}",
            f"Generated {meta['generated_at']} · {meta['generator']}",
        ],
        readiness["score"],
        readiness["status_label"],
        readiness["status"],
    )

    if meta["demo_notice"]:
        doc.notice(meta["demo_notice"])

    review_line = "Not yet reviewed by a person."
    if review["state"] == "approved":
        review_line = f"Approved by {review['approved_by']} on {review['approved_at']}."
    elif review["state"] == "superseded":
        approved_score = (review.get("approved_readiness") or {}).get("score")
        review_line = (
            f"{review['approved_by']} approved this claim at {approved_score}% on {review['approved_at']}. "
            "It changed afterwards, so that approval no longer stands for it."
        )

    doc.heading("Claim", "What was entered when the claim was created.")
    doc.pairs(
        [
            ("Claim number", claim["claim_number"]),
            ("Patient", claim["patient_name"]),
            ("UHID", claim["uhid"]),
            ("Hospital", claim["hospital"]),
            ("Insurer", claim["insurer"]),
            ("TPA", claim["tpa"]),
            ("Admission", claim["admission_date"]),
            ("Discharge", claim["discharge_date"]),
            ("Documents", f"{summary['documents']} ({summary['documents_excluded']} excluded)"),
            ("Human review", review_line),
            ("Snapshot", meta["content_sha256"][:24] + "…"),
        ]
    )

    doc.heading(
        "How to read this report",
        "Four kinds of statement are kept apart: what the documents say, what the rules "
        "concluded, what is still outstanding, and what a person decided.",
    )

    doc.heading(
        f"Documentation readiness — {readiness['score']}%, {readiness['status_label'].lower()}",
        readiness["status_detail"],
    )
    doc.table(
        ["Reason", "For", "Points"],
        [
            [item["reason"], item["source"]["label"], f"-{item['amount']}"]
            for item in readiness["breakdown"]["deductions"]
        ]
        + [["Final score", "", f"{readiness['score']}%"]],
        [0.58, 0.28, 0.14],
        empty=f"Nothing is outstanding: {readiness['score']}%.",
    )

    doc.heading("Documented facts", "Every value below was read from a document in this claim.")
    for section in report["documented_facts"]:
        rows = []
        for value in section["values"]:
            if not value["present"] and not value["sources"]:
                continue
            sources = "; ".join(
                f"{source['document_name']} p{source['page']}" if source.get("page") else str(source["document_name"])
                for source in value["sources"][:3]
            )
            if len(value["sources"]) > 3:
                sources += f" and {len(value['sources']) - 3} more"
            rows.append([value["label"], _text(value["value"]), sources or "—"])
        if rows:
            doc.paragraph(section["label"], size=9, colour=MUTED, gap=2)
            doc.table(["Value", "As documented", "Read from"], rows, [0.24, 0.36, 0.40])

    findings = report["system_findings"]
    doc.heading(
        "System findings",
        "Raised by the deterministic rules. Nothing here is a clinical conclusion.",
    )
    doc.table(
        ["Finding", "Severity", "Status", "Evidence"],
        [
            [
                f"{finding['title']} — {finding['explanation']}",
                finding["severity"],
                finding["status"].replace("_", " "),
                _evidence_text(finding["evidence"]),
            ]
            for finding in findings
        ],
        [0.46, 0.10, 0.14, 0.30],
        empty="No finding was raised on this claim.",
        colours=[SEVERITY_COLOURS.get(finding["severity"], INK) for finding in findings],
    )

    doc.heading("Cross-document validation", "Every check the rules ran over this claim.")
    doc.table(
        ["Check", "Result", "Detail"],
        [
            [check["title"], check["status"].replace("_", " "), check["detail"]]
            for check in report["validation_checks"]
        ],
        [0.34, 0.14, 0.52],
    )

    checklist = report["checklist"]
    procedure = (checklist.get("procedure") or {}).get("label")
    doc.heading(
        "Procedure checklist",
        f"What a claim for {procedure.lower()} is expected to carry."
        if checklist["available"] and procedure
        else (checklist.get("note") or "No checklist applies to this claim."),
    )
    doc.table(
        ["Requirement", "Status", "Documents", "What it needs"],
        [
            [
                item["label"] + ("" if item["required"] else " (supporting)"),
                item["status"].replace("_", " "),
                "; ".join(item["documents"]) or "—",
                item["detail"],
            ]
            for item in checklist["items"]
        ],
        [0.24, 0.14, 0.26, 0.36],
        empty="No checklist applies to this claim.",
    )

    doc.heading("Questions and resolutions", "What the claim asked for, and what came back.")
    doc.table(
        ["Request", "Status", "Answer", "Recorded by"],
        [
            [
                f"{question['requirement_label']} — {question['question']}",
                question["status"].replace("_", " "),
                _text((question["answer"] or "—").replace("_", " "))
                + (f" — {question['answer_reason']}" if question["answer_reason"] else ""),
                _text(question["answered_by"]),
            ]
            for question in report["questions"]
        ],
        [0.38, 0.16, 0.30, 0.16],
        empty="Nothing has been asked for on this claim.",
    )

    doc.heading("Unresolved items", "What this claim is still waiting for.")
    doc.table(
        ["Item", "Why", "What to do"],
        [[item["label"], item["detail"], item["action"]] for item in report["unresolved"]],
        [0.26, 0.40, 0.34],
        empty="Nothing is outstanding.",
    )

    doc.heading("Human decisions", "Recorded by a person. Nothing in the system decides these.")
    doc.table(
        ["What", "Decision", "By", "Note"],
        [
            [
                f"{decision['subject']} ({decision['kind']})",
                decision["decision"].replace("_", " "),
                f"{decision['actor']} · {decision['at']}" if decision["at"] else _text(decision["actor"]),
                _text(decision["note"]),
            ]
            for decision in report["human_decisions"]
        ],
        [0.30, 0.16, 0.26, 0.28],
        empty="No decision has been recorded on this claim yet.",
    )

    bills = report["bills"]
    doc.heading("Bills", "As read from the documents; the arithmetic checks are in the findings.")
    doc.table(
        ["Bill", "Number", "Date", "Lines", "Subtotal", "Total"],
        [
            [
                f"{bill['bill_type_label']} — {bill['document_name']}",
                _text(bill["number"]),
                _text(bill["date"]),
                str(bill["line_item_count"]),
                _text(bill["subtotal"]),
                _text(bill["total"]),
            ]
            for bill in bills["items"]
        ],
        [0.34, 0.18, 0.12, 0.08, 0.14, 0.14],
        empty="No bill has been read for this claim.",
    )

    doc.heading("Documents", "Every file in this claim, as it was read.")
    doc.table(
        ["Document", "Type", "Pages", "Read by", "Signals", "Status"],
        [
            [
                document["filename"],
                _text(document["doc_type_label"]),
                str(document["page_count"] or "—"),
                _text(document["ocr_engine"] or document["text_source"]),
                ", ".join(document["quality_signals"]) or "none",
                "excluded" if document["excluded"] else document["processing_status"],
            ]
            for document in report["documents"]
        ],
        [0.30, 0.20, 0.07, 0.13, 0.17, 0.13],
    )

    doc.heading("Audit trail", f"{len(report['audit_trail'])} event(s), oldest first, as recorded.")
    doc.table(
        ["When", "Event", "Actor", "Message"],
        [
            [event["created_at"], event["event_type"], event["actor"], event["message"]]
            for event in report["audit_trail"]
        ],
        [0.22, 0.22, 0.16, 0.40],
    )

    doc._finish_page()
    canvas.showPage()
    canvas.save()
    return buffer.getvalue(), doc.page

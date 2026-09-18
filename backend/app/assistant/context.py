"""The claim, as the assistant is allowed to know it.

Everything the assistant may say comes from here: the canonical claim, the findings the rules
raised, the checklist, the open questions and the last re-analysis. Each fact carries the id of
the thing it came from, so an answer can cite it and a citation can be checked.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.models import FINDING_ACTIVE_STATUSES, QUESTION_PENDING_STATUSES


@dataclass(frozen=True)
class Citation:
    kind: str
    id: str
    label: str
    detail: str | None = None
    document_id: str | None = None
    page: int | None = None

    def as_dict(self) -> dict:
        return {
            "kind": self.kind,
            "id": self.id,
            "label": self.label,
            "detail": self.detail,
            "document_id": self.document_id,
            "page": self.page,
        }


@dataclass
class ClaimContext:
    """A read-only view of one claim for the assistant."""

    claim_id: str
    claim_number: str
    patient_name: str | None
    uhid: str | None
    admission_date: str | None
    discharge_date: str | None
    procedure_key: str | None
    procedure_label: str | None
    documents: list[dict] = field(default_factory=list)
    findings: list[dict] = field(default_factory=list)
    checklist: list[dict] = field(default_factory=list)
    checklist_available: bool = False
    questions: list[dict] = field(default_factory=list)
    bills: list[dict] = field(default_factory=list)
    last_changes: list[dict] = field(default_factory=list)
    last_change_summary: dict = field(default_factory=dict)

    # --- what the assistant is allowed to cite ---------------------------------------------

    def citation_index(self) -> dict[tuple[str, str], Citation]:
        index: dict[tuple[str, str], Citation] = {}
        index[("claim", self.claim_id)] = Citation("claim", self.claim_id, f"Claim {self.claim_number}")
        for document in self.documents:
            index[("document", document["document_id"])] = Citation(
                "document",
                document["document_id"],
                document["filename"],
                document["doc_type_label"],
                document_id=document["document_id"],
            )
        for finding in self.findings:
            index[("finding", finding["id"])] = Citation(
                "finding", finding["id"], finding["title"], f"{finding['severity']} · {finding['status']}"
            )
        for item in self.checklist:
            index[("requirement", item["key"])] = Citation(
                "requirement", item["key"], item["label"], item["status"]
            )
        for question in self.questions:
            index[("question", question["id"])] = Citation(
                "question", question["id"], question["question"], question["status"]
            )
        return index

    # --- the parts an answer is built from --------------------------------------------------

    @property
    def active_findings(self) -> list[dict]:
        return [finding for finding in self.findings if finding["status"] in FINDING_ACTIVE_STATUSES]

    @property
    def missing_requirements(self) -> list[dict]:
        return [item for item in self.checklist if item["status"] == "missing"]

    @property
    def review_requirements(self) -> list[dict]:
        return [item for item in self.checklist if item["status"] == "review_required"]

    @property
    def open_questions(self) -> list[dict]:
        return [question for question in self.questions if question["status"] in QUESTION_PENDING_STATUSES]

    @property
    def billing_findings(self) -> list[dict]:
        return [finding for finding in self.active_findings if finding["category"] == "billing"]


def build(state: dict, *, questions: list, changes: dict | None = None) -> ClaimContext:
    """The context for one claim, taken from its canonical state."""

    def value(section: str, name: str) -> str | None:
        return (state.get(section, {}).get("fields", {}).get(name) or {}).get("value")

    checklist = state.get("checklist") or {}
    return ClaimContext(
        claim_id=state["claim"]["claim_id"],
        claim_number=state["claim"]["claim_number"],
        patient_name=value("patient", "name"),
        uhid=value("patient", "uhid"),
        admission_date=value("admission", "admission_date"),
        discharge_date=value("admission", "discharge_date"),
        procedure_key=(checklist.get("procedure") or {}).get("key"),
        procedure_label=(checklist.get("procedure") or {}).get("label"),
        documents=[
            {
                "document_id": document["document_id"],
                "filename": document["filename"],
                "doc_type": document["doc_type"],
                "doc_type_label": document["doc_type_label"],
                "page_count": document["page_count"],
                "excluded": document["excluded"],
                "processing_status": document["processing_status"],
            }
            for document in state["documents"]["items"]
        ],
        findings=[
            {
                "id": item["id"],
                "code": item["code"],
                "category": item["category"],
                "severity": item["severity"],
                "status": item["status"],
                "title": item["title"],
                "action": item["action"],
            }
            for item in state["findings"]["items"]
        ],
        checklist=[
            {
                "key": item["key"],
                "label": item["label"],
                "status": item["status"],
                "severity": item["severity"],
                "required": item["required"],
                "detail": item["detail"],
                "resolution": item["resolution"],
                "documents": [source["document_id"] for source in item["evidence"]],
            }
            for item in checklist.get("items", [])
        ],
        checklist_available=bool(checklist.get("available")),
        questions=[
            {
                "id": question.id,
                "requirement_key": question.requirement_key,
                "requirement_label": question.requirement_label,
                "question": question.question,
                "reason": question.reason,
                "status": question.status,
                "expected_document_type": question.expected_document_type,
            }
            for question in questions
        ],
        bills=[
            {
                "document_id": bill["document_id"],
                "document_name": bill["document_name"],
                "bill_type_label": bill["bill_type_label"],
                "total": (bill["fields"].get("total") or {}).get("value"),
                "number": (bill["fields"].get("number") or {}).get("value"),
            }
            for bill in state["bills"]["items"]
        ],
        last_changes=list((changes or {}).get("changes") or []),
        last_change_summary=dict((changes or {}).get("summary") or {}),
    )

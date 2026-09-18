"""Choosing what the canonical claim states, and keeping every source visible.

Several documents usually carry the same value. They are compared in a normalised form
(names without honorifics, dates as ISO, identifiers without punctuation) and each document
type carries a weight: the documents that exist to state the claim's identity — the insurance
card, the admission record, the discharge summary — count for more than a document that
merely repeats it.

Nothing is hidden by this. Every document that supplied a value stays in `sources`, values
read by OCR below the configured confidence are listed but marked as excluded from selection,
and values that normalise differently are reported as competing values with their own sources.
No source is described as better or worse than another: only its weight, its confidence and
whether it took part are stated.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field as dataclass_field
from decimal import Decimal

from app.analysis import normalize as nz
from app.canonical.keys import (
    AMOUNT,
    DATE,
    DIAGNOSIS,
    GENDER,
    IDENTIFIER,
    INTEGER,
    NAME,
    PERSON,
    PROCEDURE,
    CanonicalField,
)
from app.config_files import canonical_config

SOURCE_TYPES = {"pdf_text": "Text layer", "ocr": "OCR", "unknown": "Unknown"}


def document_weight(doc_type: str | None) -> int:
    config = canonical_config()
    return int(config["document_weights"].get(doc_type or "", config["default_weight"]))


def ocr_confidence_floor() -> float:
    return float(canonical_config()["ocr_confidence_floor"])


def normalise(kind: str, value: str | None) -> str | None:
    """The comparison form of a value. None means the value cannot be compared."""
    if value is None:
        return None
    text = nz.clean_text(value)
    if not text:
        return None
    if kind in (NAME, PERSON):
        return nz.person_key(text) or None
    if kind == IDENTIFIER:
        return nz.squash(text).replace(" ", "") or None
    if kind == DATE:
        parsed = nz.parse_date(text)
        return nz.format_date(parsed) if parsed else None
    if kind == GENDER:
        return nz.normalise_gender(text)
    if kind == INTEGER:
        digits = nz.clean_text(text).split()[0] if text else ""
        return str(int(digits)) if digits.isdigit() else None
    if kind == AMOUNT:
        amount = nz.parse_amount(text)
        return str(amount.quantize(Decimal("0.01"))) if amount is not None else None
    if kind == DIAGNOSIS:
        return nz.squash(nz.strip_icd10(text) or text) or None
    if kind == PROCEDURE:
        procedure = nz.normalise_procedure(text)
        return procedure["key"] if procedure else nz.squash(text) or None
    return nz.squash(text) or None


def split_method(method: str) -> tuple[str, str]:
    """("pdf_text:label_value") -> ("pdf_text", "label_value")."""
    if ":" in method:
        source_type, _, extraction = method.partition(":")
        return source_type, extraction
    return "unknown", method


@dataclass(frozen=True)
class Candidate:
    """One extracted value offered to the canonical claim, with where it came from."""

    document_id: str
    document_name: str
    document_type: str | None
    document_type_label: str | None
    weight: int
    field_key: str
    value: str
    raw_value: str | None
    normalized: str | None
    page: int | None
    bounding_box: list[float] | None
    snippet: str | None
    method: str
    confidence: float
    eligible: bool
    excluded_reason: str | None = None
    derived_from: str | None = None
    details: dict = dataclass_field(default_factory=dict)

    @property
    def source_type(self) -> str:
        return split_method(self.method)[0]

    def payload(self) -> dict:
        source_type, extraction_method = split_method(self.method)
        return {
            "document_id": self.document_id,
            "document_name": self.document_name,
            "document_type": self.document_type,
            "document_type_label": self.document_type_label,
            "page": self.page,
            "bounding_box": self.bounding_box,
            "snippet": self.snippet,
            "method": self.method,
            "source_type": source_type,
            "source_type_label": SOURCE_TYPES.get(source_type, source_type),
            "extraction_method": extraction_method,
            "confidence": round(float(self.confidence), 4),
            "weight": self.weight,
            "eligible": self.eligible,
            "excluded_reason": self.excluded_reason,
            "value": self.value,
            "raw_value": self.raw_value,
            "field_key": self.field_key,
            "derived_from": self.derived_from,
            "evidence_available": self.page is not None and self.bounding_box is not None,
        }


def eligibility(method: str, confidence: float) -> tuple[bool, str | None]:
    """Whether a value may take part in selection.

    Values read by OCR below the configured confidence are excluded from selection: a
    doubtful reading must not outvote a value taken from a text layer.
    """
    floor = ocr_confidence_floor()
    source_type, _ = split_method(method)
    if source_type == "ocr" and confidence < floor:
        return False, f"OCR confidence {confidence:.2f} is below the {floor:.2f} required for value selection"
    return True, None


def _group_value(candidates: list[Candidate]) -> str:
    """The wording to state for a group: the one its documents print most often."""
    counts = Counter(candidate.value for candidate in candidates)
    best = max(counts.values())
    tied = sorted(value for value, count in counts.items() if count == best)
    if len(tied) == 1:
        return tied[0]
    # Same number of documents print each wording: take the one from the heaviest document,
    # and fall back to alphabetical order so the result never depends on row order.
    by_weight = sorted(
        (candidate for candidate in candidates if candidate.value in tied),
        key=lambda candidate: (-candidate.weight, candidate.value),
    )
    return by_weight[0].value


def _sorted_sources(candidates: list[Candidate]) -> list[dict]:
    return [
        candidate.payload()
        for candidate in sorted(
            candidates, key=lambda item: (item.document_name, item.page or 0, item.field_key)
        )
    ]


def _group_payload(normalized: str, candidates: list[Candidate]) -> dict:
    eligible = [candidate for candidate in candidates if candidate.eligible]
    return {
        "value": _group_value(candidates),
        "normalized_value": normalized,
        "weight": sum(candidate.weight for candidate in eligible),
        "source_count": len(candidates),
        "eligible_source_count": len(eligible),
        "value_variants": [
            {"value": value, "source_count": count}
            for value, count in sorted(Counter(c.value for c in candidates).items(), key=lambda item: (-item[1], item[0]))
        ],
        "sources": _sorted_sources(candidates),
    }


def select_value(spec: CanonicalField, candidates: list[Candidate]) -> dict:
    """Assemble one canonical value from the candidates that were offered for it."""
    comparable = [candidate for candidate in candidates if candidate.normalized]
    uncomparable = [candidate for candidate in candidates if not candidate.normalized]

    groups: dict[str, list[Candidate]] = {}
    for candidate in comparable:
        groups.setdefault(candidate.normalized or "", []).append(candidate)

    payloads = [_group_payload(normalized, items) for normalized, items in groups.items()]
    selectable = [payload for payload in payloads if payload["eligible_source_count"] > 0]

    base = {
        "key": spec.key,
        "label": spec.label,
        "kind": spec.kind,
        "section": spec.section,
    }

    if not selectable:
        excluded = [candidate.payload() for candidate in sorted(candidates, key=lambda item: item.document_name)]
        note = None
        if candidates:
            note = (
                "Every extracted value for this field was excluded from selection; the sources are listed "
                "with their reasons."
                if comparable
                else "The extracted values for this field could not be normalised for comparison."
            )
        return {
            **base,
            "present": False,
            "value": None,
            "normalized_value": None,
            "confidence": None,
            "source_count": len(candidates),
            "sources": excluded,
            "evidence_available": False,
            "competing_values": [],
            "has_competing_values": False,
            "note": note or "No document in this claim carries this value.",
        }

    ordered = sorted(
        selectable,
        key=lambda payload: (
            -payload["weight"],
            -payload["eligible_source_count"],
            -max((source["confidence"] for source in payload["sources"] if source["eligible"]), default=0.0),
            payload["normalized_value"],
        ),
    )
    chosen, *rest = ordered
    competing = sorted(
        [payload for payload in payloads if payload["normalized_value"] != chosen["normalized_value"]],
        key=lambda payload: (-payload["weight"], -payload["source_count"], payload["normalized_value"]),
    )
    eligible_sources = [source for source in chosen["sources"] if source["eligible"]]
    note = None
    if competing:
        note = "Multiple source values detected. The competing values and their sources are listed."
    if uncomparable and not note:
        note = "Some sources carried a value that could not be normalised for comparison."

    return {
        **base,
        "present": True,
        "value": chosen["value"],
        "normalized_value": chosen["normalized_value"],
        "confidence": round(max(source["confidence"] for source in eligible_sources), 4),
        "weight": chosen["weight"],
        "source_count": chosen["source_count"],
        "value_variants": chosen["value_variants"],
        "sources": chosen["sources"],
        "evidence_available": any(source["evidence_available"] for source in chosen["sources"]),
        "competing_values": competing,
        "has_competing_values": bool(competing),
        "note": note,
    }


def absent(spec: CanonicalField, note: str | None = None) -> dict:
    return {
        "key": spec.key,
        "label": spec.label,
        "kind": spec.kind,
        "section": spec.section,
        "present": False,
        "value": None,
        "normalized_value": None,
        "confidence": None,
        "source_count": 0,
        "sources": [],
        "evidence_available": False,
        "competing_values": [],
        "has_competing_values": False,
        "note": note or "No document in this claim carries this value.",
    }

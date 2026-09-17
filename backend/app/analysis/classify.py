"""Document classification.

Types are decided from the text inside the document: the heading on the first page is the
strong signal, supporting vocabulary adds weight, and patterns that argue against a type
subtract from it. Filenames are never scored — a scan called `scan_0042.pdf` is recognised
from its heading like any other document. The filename is recorded alongside the result
only so a reviewer can see that it was not used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.config_files import document_types_config
from app.processing.types import DocumentContent

METHOD_TITLE = "content_rules_title"
METHOD_KEYWORDS = "content_rules_keywords"
METHOD_NO_MATCH = "content_rules_no_match"

OTHER = "other"


@dataclass
class TypeRules:
    key: str
    label: str
    titles: tuple[re.Pattern, ...]
    keywords: tuple[re.Pattern, ...]
    negatives: tuple[re.Pattern, ...]
    extract: tuple[str, ...]
    signature_slots: tuple[dict, ...]


@dataclass
class Classification:
    doc_type: str
    label: str
    confidence: float
    method: str
    signals: list[dict] = field(default_factory=list)
    scores: dict[str, float] = field(default_factory=dict)
    runner_up: str | None = None
    runner_up_score: float | None = None


def _compile(patterns) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(pattern, re.IGNORECASE) for pattern in (patterns or ()))


@lru_cache
def type_rules() -> dict[str, TypeRules]:
    rules: dict[str, TypeRules] = {}
    for entry in document_types_config()["types"]:
        rules[entry["key"]] = TypeRules(
            key=entry["key"],
            label=entry.get("label", entry["key"].replace("_", " ").title()),
            titles=_compile(entry.get("titles")),
            keywords=_compile(entry.get("keywords")),
            negatives=_compile(entry.get("negatives")),
            extract=tuple(entry.get("extract") or ()),
            signature_slots=tuple(entry.get("signature_slots") or ()),
        )
    return rules


def rules_for(doc_type: str | None) -> TypeRules:
    rules = type_rules()
    return rules.get(doc_type or OTHER, rules[OTHER])


def type_label(doc_type: str | None) -> str:
    return rules_for(doc_type).label


@lru_cache
def _scoring() -> dict:
    return document_types_config()["scoring"]


def _title_strength(match: re.Match, cell: str, scoring: dict) -> str:
    """How much a heading match is worth.

    A document names itself in a heading of its own: "DISCHARGE SUMMARY", "TAX INVOICE".
    The same words inside a sentence ("Consent for surgery and anaesthesia obtained") are
    not a title, so they only count as supporting vocabulary.
    """
    length = len(cell.strip())
    if length == 0:
        return "weak"
    coverage = len(match.group(0)) / length
    if coverage >= float(scoring["title_coverage"]):
        return "strong"
    letters = [char for char in cell if char.isalpha()]
    uppercase = sum(1 for char in letters if char.isupper()) / len(letters) if letters else 0.0
    if uppercase >= 0.85 and coverage >= float(scoring["title_uppercase_coverage"]):
        return "strong"
    return "weak"


def classify(content: DocumentContent) -> Classification:
    scoring = _scoring()
    heading_cells = content.heading_cells(int(scoring["title_lines"]))
    body = content.flat_text

    scores: dict[str, float] = {}
    signals: dict[str, list[dict]] = {}
    title_hits: dict[str, int] = {}
    keyword_hits: dict[str, int] = {}

    for key, rules in type_rules().items():
        if key == OTHER:
            continue
        score = 0.0
        found: list[dict] = []
        titles = 0
        for pattern in rules.titles:
            for cell in heading_cells:
                match = pattern.search(cell)
                if not match:
                    continue
                if _title_strength(match, cell, scoring) == "strong":
                    titles += 1
                    score += float(scoring["title_weight"])
                    found.append({"type": "title", "pattern": pattern.pattern, "text": match.group(0), "heading": cell})
                else:
                    score += float(scoring["keyword_weight"])
                    found.append(
                        {"type": "title_mention", "pattern": pattern.pattern, "text": match.group(0), "heading": cell}
                    )
                break
        keywords = 0
        for pattern in rules.keywords:
            match = pattern.search(body)
            if match:
                keywords += 1
                score += float(scoring["keyword_weight"])
                found.append({"type": "keyword", "pattern": pattern.pattern, "text": match.group(0)})
        for pattern in rules.negatives:
            match = pattern.search(body)
            if match:
                score += float(scoring["negative_weight"])
                found.append({"type": "negative", "pattern": pattern.pattern, "text": match.group(0)})
        scores[key] = round(score, 2)
        signals[key] = found
        title_hits[key] = titles
        keyword_hits[key] = keywords

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    best_key, best_score = ranked[0] if ranked else (OTHER, 0.0)
    runner_up, runner_up_score = (ranked[1] if len(ranked) > 1 else (None, None))

    max_confidence = float(scoring["max_confidence"])
    if best_score > 0 and title_hits.get(best_key):
        confidence = min(
            max_confidence,
            float(scoring["title_confidence_base"]) + float(scoring["title_confidence_step"]) * keyword_hits[best_key],
        )
        method = METHOD_TITLE
    elif best_score > 0 and keyword_hits.get(best_key, 0) >= int(scoring["min_keyword_hits"]):
        confidence = min(
            max_confidence,
            float(scoring["keyword_confidence_base"])
            + float(scoring["keyword_confidence_step"]) * keyword_hits[best_key],
        )
        method = METHOD_KEYWORDS
    else:
        return Classification(
            doc_type=OTHER,
            label=type_label(OTHER),
            confidence=0.2,
            method=METHOD_NO_MATCH,
            signals=[],
            scores=scores,
            runner_up=best_key if best_score > 0 else None,
            runner_up_score=best_score if best_score > 0 else None,
        )

    # A close second means less certainty about which of the two it is.
    if runner_up_score is not None and best_score > 0:
        margin = (best_score - runner_up_score) / best_score
        if margin < 0.25:
            confidence = min(confidence, 0.62)

    return Classification(
        doc_type=best_key,
        label=type_label(best_key),
        confidence=round(confidence, 4),
        method=method,
        signals=signals[best_key][:12],
        scores={key: value for key, value in ranked[:5]},
        runner_up=runner_up,
        runner_up_score=runner_up_score,
    )

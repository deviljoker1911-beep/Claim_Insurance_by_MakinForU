"""What the assistant may say, and what it may cite.

Every answer passes through here before it is served: citations are resolved against the claim
and dropped when they point at nothing, and sentences that make a claim the system is not
entitled to make are removed. The guard is applied to every provider, the deterministic one
included, so the rules do not depend on which one produced the text.
"""

from __future__ import annotations

import re

from app.assistant.context import Citation, ClaimContext

# Never said about a claim or a document, whoever wrote the sentence.
FORBIDDEN_WORDS = ("fraud", "fraudulent", "forged", "forgery", "fake", "fabricated")

# Conclusions this system does not reach: approval, submission-readiness, medical necessity
# and diagnosis all belong to a person.
FORBIDDEN_CLAIMS = (
    "ready for submission",
    "ready to submit",
    "ready for payment",
    "approved for payment",
    "i approve",
    "this claim is approved",
    "claim is approved",
    "medically necessary",
    "medical necessity is established",
    "i diagnose",
    "the patient is suffering from",
    "the patient has been diagnosed",
    "no human review",
    "human review is not required",
)

CITATION = re.compile(r"\[\[(claim|document|finding|requirement|question):([A-Za-z0-9_\-.:]+)(?:#p(\d+))?\]\]")

SAFE_NOTICE = (
    "Answered from this claim's documents and findings. "
    "AI-assisted analysis; a person makes the final decision."
)


def resolve(text: str, context: ClaimContext) -> tuple[str, list[dict], list[str]]:
    """Take the citation markers out of the text and resolve them against the claim.

    A marker that points at something this claim does not have is removed and reported, so a
    made-up reference can never reach the interface.
    """
    index = context.citation_index()
    citations: list[Citation] = []
    removed: list[str] = []
    seen: set[tuple[str, str, int | None]] = set()

    def replace(match: re.Match) -> str:
        kind, identifier, page = match.group(1), match.group(2), match.group(3)
        found = index.get((kind, identifier))
        if found is None:
            removed.append(match.group(0))
            return ""
        page_number = int(page) if page else None
        key = (kind, identifier, page_number)
        if key not in seen:
            seen.add(key)
            citations.append(
                Citation(
                    kind=found.kind,
                    id=found.id,
                    label=found.label,
                    detail=found.detail,
                    document_id=found.document_id,
                    page=page_number,
                )
            )
        return ""

    clean = CITATION.sub(replace, text)
    clean = re.sub(r"[ \t]{2,}", " ", clean)
    clean = re.sub(r" +([,.;:])", r"\1", clean)
    # A removed marker leaves the line ending in a space; take it off.
    clean = "\n".join(line.rstrip() for line in clean.split("\n"))
    clean = re.sub(r"\n{3,}", "\n\n", clean).strip()
    return clean, [citation.as_dict() for citation in citations], removed


def _sentences(text: str) -> list[str]:
    return [part for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def scrub(text: str) -> tuple[str, list[str]]:
    """Remove any sentence that says something the system may not say."""
    kept: list[str] = []
    dropped: list[str] = []
    for line in text.split("\n"):
        if not line.strip():
            kept.append(line)
            continue
        parts = []
        for sentence in _sentences(line) or [line]:
            lowered = sentence.lower()
            if any(word in lowered for word in FORBIDDEN_WORDS) or any(
                claim in lowered for claim in FORBIDDEN_CLAIMS
            ):
                dropped.append(sentence.strip())
                continue
            parts.append(sentence)
        if parts:
            kept.append(" ".join(parts))
    cleaned = "\n".join(kept).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned, dropped


def apply(text: str, context: ClaimContext) -> tuple[str, list[dict], list[str]]:
    """Resolve the citations, then remove anything the system may not claim."""
    resolved, citations, removed = resolve(text, context)
    cleaned, dropped = scrub(resolved)
    if dropped:
        removed = removed + [f"sentence removed: {sentence}" for sentence in dropped]
    if not cleaned.strip():
        cleaned = (
            "I can only answer from this claim's documents and findings, and I have nothing "
            "to show for that question."
        )
        citations = []
    return cleaned, citations, removed

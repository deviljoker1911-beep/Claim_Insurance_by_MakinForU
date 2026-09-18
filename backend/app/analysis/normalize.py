"""Normalisation of values read out of Indian hospital paperwork.

Dates are day-first (12-01-2026 is 12 January 2026), amounts use Indian digit grouping
(1,14,360.00), and names arrive with qualifications and registration numbers attached.
Every helper returns None when it cannot normalise a value — a missing normalisation is
reported as missing and never guessed.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation

# --- text -------------------------------------------------------------------------------

_WHITESPACE = re.compile(r"\s+")
_TRAILING_PUNCTUATION = re.compile(r"[\s,;:.\-–—]+$")


def clean_text(value: str | None) -> str:
    if not value:
        return ""
    value = unicodedata.normalize("NFC", value)
    value = _WHITESPACE.sub(" ", value).strip()
    return _TRAILING_PUNCTUATION.sub("", value).strip()


def squash(value: str | None) -> str:
    """Comparison form: lower case, single spaces, no punctuation."""
    text = clean_text(value).lower()
    return _WHITESPACE.sub(" ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


# --- dates ------------------------------------------------------------------------------

_DATE_FORMATS = (
    "%d-%m-%Y",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%d-%b-%Y",
    "%d %b %Y",
    "%d %B %Y",
    "%d-%B-%Y",
    "%Y-%m-%d",
)
_DATE_TEXT = re.compile(
    r"\b(\d{1,2})\s*[-/.\s]\s*([A-Za-z]{3,9}|\d{1,2})\s*[-/.\s]\s*(\d{4})\b|\b(\d{4})-(\d{2})-(\d{2})\b"
)


def parse_date(value: str | None) -> date | None:
    """Parse a day-first date. Returns None for anything unrecognised."""
    text = clean_text(value)
    if not text:
        return None
    match = _DATE_TEXT.search(text)
    if not match:
        return None
    candidate = match.group(0)
    normalised = re.sub(r"\s*([-/.])\s*", r"\1", candidate)
    normalised = re.sub(r"\s+", " ", normalised)
    from datetime import datetime

    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(normalised, fmt).date()
        except ValueError:
            continue
    return None


def format_date(value: date | None) -> str | None:
    return value.isoformat() if value else None


# --- amounts ----------------------------------------------------------------------------

_AMOUNT = re.compile(r"(?<![\d.])(-?)\s?(\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)(?![\d])")
_CURRENCY_NOISE = re.compile(r"(?i)\b(rs|inr|rupees|only)\b\.?|[₹]")


def parse_amount(value: str | None) -> Decimal | None:
    """Parse an amount written with Indian digit grouping.

    A bill may print a negative amount with a minus sign or in brackets; both are read as
    negative, so a discount line is never mistaken for a charge.
    """
    text = clean_text(value)
    if not text:
        return None
    text = _CURRENCY_NOISE.sub(" ", text)
    bracketed = bool(re.fullmatch(r"\(\s*[\d.,]+\s*\)", text.strip()))
    match = _AMOUNT.search(text)
    if not match:
        return None
    try:
        amount = Decimal(match.group(2).replace(",", ""))
    except InvalidOperation:
        return None
    return -amount if (match.group(1) == "-" or bracketed) else amount


def format_amount(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def format_indian(value: Decimal | None) -> str | None:
    """Group digits the Indian way: 1,14,360.00."""
    if value is None:
        return None
    whole, _, fraction = f"{value:.2f}".partition(".")
    sign, whole = ("-", whole[1:]) if whole.startswith("-") else ("", whole)
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        whole = f"{head},{tail}"
    return f"{sign}{whole}.{fraction}"


def is_amount(value: str | None) -> bool:
    text = clean_text(value)
    return bool(text) and bool(re.fullmatch(r"\(?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?\)?", text))


# --- people, age and sex ----------------------------------------------------------------

_QUALIFICATION = re.compile(
    r"(?i)(,\s*(?:m\.?s|m\.?d|m\.?b\.?b\.?s|d\.?n\.?b|d\.?a|f\.?r\.?c\.?s|dip|ph\.?d)\b.*|"
    r"\s*·.*|\s*\breg(?:istration)?\.?\s*(?:no\.?)?\s*[:.]?\s*\S+.*|\s*\(.*?\)\s*$)"
)
_HONORIFIC = re.compile(r"(?i)^(dr|prof|mr|mrs|ms|miss|smt|shri)\.?\s+")


def normalise_person(value: str | None) -> str | None:
    """"Dr. Anil Mehta, MS (General Surgery) · Reg. DEMO-MC-20417" -> "Dr. Anil Mehta"."""
    text = clean_text(value)
    if not text:
        return None
    text = _QUALIFICATION.sub("", text).strip(" ,;·-")
    text = clean_text(text)
    return text or None


def person_key(value: str | None) -> str:
    """Comparison form for a person: honorific and qualifications removed."""
    text = normalise_person(value) or ""
    return squash(_HONORIFIC.sub("", text))


_AGE_SEX = re.compile(
    r"(?i)\b(?P<age>\d{1,3})\s*(?:y(?:ea)?rs?|y|yo)?\b(?:\s*[/,]\s*|\s+)(?P<sex>male|female|other|m|f)\b"
)
_SEX = re.compile(r"(?i)\b(male|female|other|m|f)\b")
_AGE = re.compile(r"(?i)\b(\d{1,3})\s*(?:y(?:ea)?rs?|y|yo)\b")


def normalise_gender(value: str | None) -> str | None:
    text = clean_text(value).lower()
    if not text:
        return None
    match = _SEX.search(text)
    if not match:
        return None
    token = match.group(1)
    if token in {"m", "male"}:
        return "male"
    if token in {"f", "female"}:
        return "female"
    return "other"


def parse_age(value: str | None) -> int | None:
    text = clean_text(value)
    if not text:
        return None
    match = _AGE.search(text) or _AGE_SEX.search(text)
    if match:
        age = int(match.group(1) if match.lastindex else match.group("age"))
        return age if 0 < age < 130 else None
    leading = re.match(r"\s*(\d{1,3})\b", text)
    if leading:
        age = int(leading.group(1))
        return age if 0 < age < 130 else None
    return None


def split_age_sex(value: str | None) -> tuple[int | None, str | None]:
    text = clean_text(value)
    match = _AGE_SEX.search(text)
    if match:
        age = int(match.group("age"))
        return (age if 0 < age < 130 else None), normalise_gender(match.group("sex"))
    return parse_age(text), normalise_gender(text)


# --- clinical ---------------------------------------------------------------------------

ICD10 = re.compile(r"\b([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)\b")


def find_icd10(value: str | None) -> str | None:
    text = clean_text(value)
    match = ICD10.search(text.upper()) if text else None
    return match.group(1) if match else None


def strip_icd10(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"(?i)\(?\s*icd-?10\s*[:.]?\s*[A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?\s*\)?", "", text)
    text = re.sub(r"\(\s*[A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?\s*\)", "", text)
    return clean_text(text) or None


# Procedure vocabulary. Every pattern is anchored on word boundaries, so a *diagnosis*
# such as "cholecystitis" can never be read as the *procedure* "cholecystectomy".
PROCEDURES: tuple[tuple[str, str, str], ...] = (
    (
        "laparoscopic_cholecystectomy",
        "Laparoscopic cholecystectomy",
        r"\b(?:lap(?:aroscopic|\.)?\s*chole(?:cystectomy)?|laparoscopic\s+cholecystectomy)\b",
    ),
    ("open_cholecystectomy", "Open cholecystectomy", r"\bopen\s+cholecystectomy\b"),
    ("cholecystectomy", "Cholecystectomy", r"\bcholecystectomy\b"),
    ("appendicectomy", "Appendicectomy", r"\bappend(?:ic|)ectomy\b"),
    ("hernia_repair", "Hernia repair", r"\b(?:hernioplasty|herniorrhaphy|hernia\s+repair)\b"),
    ("caesarean_section", "Caesarean section", r"\b(?:lscs|caesarean\s+section|cesarean\s+section)\b"),
    ("hysterectomy", "Hysterectomy", r"\bhysterectomy\b"),
    ("tonsillectomy", "Tonsillectomy", r"\btonsillectomy\b"),
    ("angioplasty", "Angioplasty", r"\b(?:ptca|angioplasty)\b"),
    ("knee_replacement", "Total knee replacement", r"\b(?:tkr|total\s+knee\s+(?:replacement|arthroplasty))\b"),
    ("cataract_surgery", "Cataract surgery", r"\b(?:phacoemulsification|cataract\s+(?:surgery|extraction))\b"),
    ("ureteroscopy", "Ureteroscopy / RIRS", r"\b(?:urs|ureteroscopy|rirs)\b"),
)
_PROCEDURE_PATTERNS = tuple((key, label, re.compile(pattern, re.IGNORECASE)) for key, label, pattern in PROCEDURES)


def find_procedures(value: str | None) -> list[dict]:
    """Procedures named in a piece of text, most specific first."""
    text = clean_text(value)
    if not text:
        return []
    found: list[dict] = []
    for key, label, pattern in _PROCEDURE_PATTERNS:
        match = pattern.search(text)
        if match:
            found.append({"key": key, "label": label, "match": match.group(0), "span": match.span()})
    # A specific procedure implies the general one; keep only the most specific match.
    if any(item["key"] == "laparoscopic_cholecystectomy" for item in found):
        found = [item for item in found if item["key"] not in {"cholecystectomy", "open_cholecystectomy"}]
    elif any(item["key"] == "open_cholecystectomy" for item in found):
        found = [item for item in found if item["key"] != "cholecystectomy"]
    return found


def normalise_procedure(value: str | None) -> dict | None:
    """The procedure a value names, or None when no known procedure is mentioned."""
    matches = find_procedures(value)
    return matches[0] if matches else None

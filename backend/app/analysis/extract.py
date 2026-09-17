"""Field extraction with evidence.

Every value comes out of a page as a label/value pair or a table cell, and carries where
it was found: page number, a page-relative bounding box and the text snippet it came from.
When a value cannot be located on the page, the field says so — a page reference is never
invented.

Text that opaque paint covers has already been removed by `app.processing.text`, so it can
never reach a field or its evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.analysis import normalize as nz
from app.processing.types import BBox, DocumentContent, PageContent, TextLine

METHOD_LABEL = "label_value"
METHOD_TABLE = "bill_table"
METHOD_TOTAL = "bill_total"

TEXT = "text"
DATE = "date"
AMOUNT = "amount"
INTEGER = "integer"
PERSON = "person"
GENDER = "gender"
PROCEDURE = "procedure"
DIAGNOSIS = "diagnosis"
AGE_SEX = "age_sex"
DOB_GENDER = "dob_gender"
PERSON_PAIR = "person_pair"


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    group: str
    labels: tuple[str, ...]
    kind: str = TEXT


@dataclass
class ExtractedValue:
    key: str
    label: str
    group: str
    kind: str
    value: str | None
    raw: str
    page_number: int | None
    bbox: BBox | None
    snippet: str
    method: str
    confidence: float
    details: dict = field(default_factory=dict)

    @property
    def evidence_available(self) -> bool:
        return self.page_number is not None and self.bbox is not None


# Label vocabulary. The order inside `labels` is the priority order: "Final Diagnosis"
# wins over "Diagnosis", which wins over "Provisional Diagnosis".
FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec("patient.name", "Patient name", "identity", ("patient name", "name of patient", "member name")),
    FieldSpec("patient.age_sex", "Age / sex", "identity", ("age ?/ ?sex", "age ?/ ?gender", "age and sex"), AGE_SEX),
    FieldSpec("patient.age", "Age", "identity", ("age",), INTEGER),
    FieldSpec("patient.gender", "Gender", "identity", ("sex", "gender"), GENDER),
    FieldSpec("patient.dob_gender", "Date of birth / gender", "identity", ("dob ?/ ?gender",), DOB_GENDER),
    FieldSpec("patient.date_of_birth", "Date of birth", "identity", ("date of birth", "dob"), DATE),
    FieldSpec("patient.uhid", "UHID", "identity", ("uhid(?: no\\.?| number)?", "hospital id", "\\bmrn\\b")),
    FieldSpec(
        "patient.ipd_number",
        "IPD number",
        "identity",
        ("ipd(?: no\\.?| number)?", "ip(?: no\\.?| number)", "admission no\\.?"),
    ),
    FieldSpec("cover.insurer", "Insurer", "cover", ("insurer", "insurance company")),
    FieldSpec("cover.tpa", "TPA", "cover", ("tpa",)),
    FieldSpec("cover.member_id", "Member ID", "cover", ("member id", "member no\\.?")),
    FieldSpec("cover.policy_number", "Policy number", "cover", ("policy no\\.?", "policy number")),
    FieldSpec("cover.sum_insured", "Sum insured", "cover", ("sum insured",), AMOUNT),
    FieldSpec("stay.admission_date", "Admission date", "stay", ("date of admission", "admission date", "admitted on"), DATE),
    FieldSpec(
        "stay.discharge_date",
        "Discharge date",
        "stay",
        ("date of discharge", "discharge date", "discharged on"),
        DATE,
    ),
    FieldSpec("stay.surgery_date", "Surgery date", "stay", ("date of surgery", "date of operation", "surgery date"), DATE),
    FieldSpec("stay.ward", "Ward / room", "stay", ("ward ?/ ?room", "ward", "room no\\.?", "bed no\\.?")),
    FieldSpec("stay.admission_type", "Admission type", "stay", ("admission type", "type of admission")),
    FieldSpec(
        "clinical.diagnosis",
        "Diagnosis",
        "clinical",
        ("final diagnosis", "diagnosis", "provisional diagnosis", "pre-?operative diagnosis"),
        DIAGNOSIS,
    ),
    FieldSpec(
        "clinical.procedure",
        "Procedure",
        "clinical",
        (
            "procedure performed",
            "operation performed",
            "surgery performed",
            "procedure",
            "planned procedure",
            "proposed surgery",
        ),
        PROCEDURE,
    ),
    FieldSpec(
        "clinical.surgeon",
        "Surgeon",
        "clinical",
        (
            "operating surgeon",
            "surgeon",
            "treating consultant",
            "admitting consultant",
            "consultant",
            "prescribing doctor",
        ),
        PERSON,
    ),
    FieldSpec("clinical.anaesthetist", "Anaesthetist", "clinical", ("an(?:a)?esthetist",), PERSON),
    FieldSpec(
        "clinical.anaesthesia_type",
        "Anaesthesia",
        "clinical",
        (
            "type of an(?:a)?esthesia",
            "an(?:a)?esthesia type",
            "planned an(?:a)?esthesia",
            "an(?:a)?esthesia plan",
            "an(?:a)?esthesia",
        ),
    ),
    FieldSpec(
        "clinical.surgeon_anaesthetist",
        "Surgeon / anaesthetist",
        "clinical",
        ("surgeon ?/ ?an(?:a)?esthetist", "operating surgeon ?/ ?an(?:a)?esthetist"),
        PERSON_PAIR,
    ),
    FieldSpec("investigation.sample_id", "Sample ID", "investigation", ("sample id", "specimen id", "accession no\\.?")),
    FieldSpec("investigation.report_number", "Report number", "investigation", ("report no\\.?", "study no\\.?")),
    FieldSpec("investigation.study_date", "Study date", "investigation", ("date of study", "study date", "date of scan"), DATE),
    FieldSpec("investigation.collected_on", "Collected on", "investigation", ("collected on", "sample collected"), DATE),
    FieldSpec("investigation.reported_on", "Reported on", "investigation", ("reported on", "report date"), DATE),
    FieldSpec("investigation.referred_by", "Referred by", "investigation", ("referred by", "referring doctor"), PERSON),
    FieldSpec("billing.bill_number", "Bill number", "billing", ("bill no\\.?", "invoice no\\.?", "bill number")),
    FieldSpec("billing.bill_date", "Bill date", "billing", ("bill date", "invoice date"), DATE),
    FieldSpec("billing.payer", "Payer", "billing", ("payer", "bill to", "billed to")),
    FieldSpec("billing.amount_in_words", "Amount in words", "billing", ("amount in words", "rupees in words")),
)

SPECS_BY_GROUP: dict[str, list[FieldSpec]] = {}
for spec in FIELD_SPECS:
    SPECS_BY_GROUP.setdefault(spec.group, []).append(spec)


def _label_pattern(label: str) -> re.Pattern:
    # The value runs to the end of its column: a wide gap (kept as a double space by the
    # text builder) or the end of the line.
    return re.compile(
        rf"(?:^|\s{{2,}}|[·•|]\s*){label}\s*[:\-–]\s*(?P<value>\S.*?)(?=\s{{2,}}|$)",
        re.IGNORECASE,
    )


_PATTERN_CACHE: dict[str, re.Pattern] = {}


def label_pattern(label: str) -> re.Pattern:
    if label not in _PATTERN_CACHE:
        _PATTERN_CACHE[label] = _label_pattern(label)
    return _PATTERN_CACHE[label]


_ICD_LABEL = re.compile(r"(?i)\bicd-?10\b\s*[:.]?\s*([A-TV-Z][0-9]{2}(?:\.[0-9A-Z]{1,4})?)")


def _icd_context(line: TextLine) -> str:
    """An "ICD-10: K81.0" column on the same line as the diagnosis."""
    match = _ICD_LABEL.search(line.text)
    return match.group(1) if match else ""


def _snippet(line: TextLine, start: int, end: int, width: int = 90) -> str:
    text = line.text
    left = max(0, start - 28)
    right = min(len(text), end + 28)
    snippet = text[left:right].strip()
    snippet = re.sub(r"\s{2,}", " · ", snippet)
    return snippet[:width]


def _search_pages(pages: list[PageContent], label: str):
    pattern = label_pattern(label)
    for page in pages:
        for line in page.lines:
            match = pattern.search(line.text)
            if match and match.group("value").strip():
                yield page, line, match


def _confidence(page: PageContent, line: TextLine, start: int, end: int) -> float:
    if page.text_source == "ocr":
        span_confidence = line.confidence_for_span(start, end)
        return round(min(0.9, (span_confidence or page.ocr_confidence or 0.7)), 4)
    return 0.95


def _method(page: PageContent, base: str) -> str:
    return f"{page.text_source}:{base}"


def _make_value(
    spec: FieldSpec,
    page: PageContent,
    line: TextLine,
    match: re.Match,
    *,
    key: str | None = None,
    label: str | None = None,
    kind: str | None = None,
    value: str | None = None,
    details: dict | None = None,
) -> ExtractedValue:
    start, end = match.span("value")
    return ExtractedValue(
        key=key or spec.key,
        label=label or spec.label,
        group=spec.group,
        kind=kind or spec.kind,
        value=value,
        raw=nz.clean_text(match.group("value")),
        page_number=page.number,
        bbox=line.bbox_for_span(start, end),
        snippet=_snippet(line, *match.span()),
        method=_method(page, METHOD_LABEL),
        confidence=_confidence(page, line, start, end),
        details=details or {},
    )


def _values_from_spec(spec: FieldSpec, pages: list[PageContent]) -> list[ExtractedValue]:
    for label in spec.labels:
        for page, line, match in _search_pages(pages, label):
            raw = nz.clean_text(match.group("value"))
            if not raw:
                continue
            if spec.kind == AGE_SEX:
                age, gender = nz.split_age_sex(raw)
                out = []
                if age is not None:
                    out.append(_make_value(spec, page, line, match, key="patient.age", label="Age", kind=INTEGER, value=str(age)))
                if gender:
                    out.append(
                        _make_value(spec, page, line, match, key="patient.gender", label="Gender", kind=GENDER, value=gender)
                    )
                if out:
                    return out
                continue
            if spec.kind == DOB_GENDER:
                dob = nz.parse_date(raw.split("/")[0])
                gender = nz.normalise_gender(raw)
                out = []
                if dob:
                    out.append(
                        _make_value(
                            spec,
                            page,
                            line,
                            match,
                            key="patient.date_of_birth",
                            label="Date of birth",
                            kind=DATE,
                            value=nz.format_date(dob),
                        )
                    )
                if gender:
                    out.append(
                        _make_value(spec, page, line, match, key="patient.gender", label="Gender", kind=GENDER, value=gender)
                    )
                if out:
                    return out
                continue
            if spec.kind == PERSON_PAIR:
                parts = [nz.normalise_person(part) for part in re.split(r"\s*/\s*", raw)]
                parts = [part for part in parts if part]
                if len(parts) < 2:
                    continue
                return [
                    _make_value(spec, page, line, match, key="clinical.surgeon", label="Surgeon", kind=PERSON, value=parts[0]),
                    _make_value(
                        spec, page, line, match, key="clinical.anaesthetist", label="Anaesthetist", kind=PERSON, value=parts[1]
                    ),
                ]
            if spec.kind == DATE:
                parsed = nz.parse_date(raw)
                if parsed is None:
                    continue
                return [_make_value(spec, page, line, match, value=nz.format_date(parsed))]
            if spec.kind == AMOUNT:
                amount = nz.parse_amount(raw)
                if amount is None:
                    continue
                return [
                    _make_value(
                        spec,
                        page,
                        line,
                        match,
                        value=nz.format_amount(amount),
                        details={"display": nz.format_indian(amount)},
                    )
                ]
            if spec.kind == INTEGER:
                number = nz.parse_age(raw) if spec.key == "patient.age" else None
                if number is None:
                    continue
                return [_make_value(spec, page, line, match, value=str(number))]
            if spec.kind == GENDER:
                gender = nz.normalise_gender(raw)
                if not gender:
                    continue
                return [_make_value(spec, page, line, match, value=gender)]
            if spec.kind == PERSON:
                person = nz.normalise_person(raw)
                if not person:
                    continue
                return [_make_value(spec, page, line, match, value=person)]
            if spec.kind == DIAGNOSIS:
                text = nz.strip_icd10(raw)
                if not text:
                    continue
                # The ICD code is often printed in its own column next to the diagnosis.
                icd = nz.find_icd10(raw) or nz.find_icd10(_icd_context(line))
                return [_make_value(spec, page, line, match, value=text, details={"icd10": icd} if icd else {})]
            if spec.kind == PROCEDURE:
                procedure = nz.normalise_procedure(raw)
                details = (
                    {"procedure_key": procedure["key"], "procedure_label": procedure["label"], "matched_text": procedure["match"]}
                    if procedure
                    else {"procedure_key": None}
                )
                return [_make_value(spec, page, line, match, value=nz.clean_text(raw), details=details)]
            return [_make_value(spec, page, line, match, value=nz.clean_text(raw))]
    return []


# --- bills ------------------------------------------------------------------------------

COLUMN_ALIASES: tuple[tuple[str, str], ...] = (
    (r"^(sl|sr|s)\.?\s*(no\.?)?$", "serial"),
    (r"(particular|item description|description|details|service|charge)", "description"),
    (r"^(batch|lot)", "batch"),
    (r"^(expiry|exp)\b", "expiry"),
    (r"^(qty|quantity|days|units|nos)", "quantity"),
    (r"^(rate|unit rate|price|mrp)", "rate"),
    (r"^(amount|value|total)", "amount"),
)

NUMERIC_COLUMNS = frozenset({"quantity", "rate", "amount"})

TOTAL_PATTERNS: tuple[tuple[str, str], ...] = (
    (r"^sub\s*total", "subtotal"),
    (r"^(net payable|net amount|invoice total|grand total|bill total|total payable|amount payable|total amount)", "total"),
    (r"^(discount|concession)", "discount"),
    (r"^(gst|tax|cgst|sgst|igst|vat|service tax)", "tax"),
)

_AMOUNT_CELL = re.compile(r"^\(?\d{1,3}(?:,\d{2,3})*(?:\.\d{1,2})?\)?$")
_NUMBER_CELL = re.compile(r"^\(?\d{1,4}(?:,\d{2,3})*(?:\.\d{1,3})?\)?$")
_SERIAL_CELL = re.compile(r"^\d{1,3}\.?$")


@dataclass(frozen=True)
class Column:
    name: str
    x0: float
    x1: float

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2

    def distance(self, x: float) -> float:
        if self.x0 <= x <= self.x1:
            return 0.0
        return min(abs(x - self.x0), abs(x - self.x1))


@dataclass
class BillLine:
    line_no: int | None
    description: str
    quantity: str | None
    rate: str | None
    amount: str | None
    batch: str | None
    expiry: str | None
    page_number: int
    bbox: BBox | None
    raw: str


@dataclass
class BillData:
    page_number: int | None = None
    columns: list[str] = field(default_factory=list)
    line_items: list[BillLine] = field(default_factory=list)
    subtotal: str | None = None
    tax: str | None = None
    discount: str | None = None
    total: str | None = None
    notes: list[str] = field(default_factory=list)
    totals_evidence: dict = field(default_factory=dict)


def _column_for(header: str) -> str | None:
    text = header.strip().lower()
    for pattern, name in COLUMN_ALIASES:
        if re.search(pattern, text):
            return name
    return None


def _word_clusters(words: list) -> list[list]:
    """Split a line's words into table cells.

    Table headers sit closer together than the columns are wide ("Rate (Rs.)" is one cell,
    "Sl." and "Particulars" are two), so the split threshold comes from the line's own
    ordinary word spacing.
    """
    words = sorted(words, key=lambda word: word.bbox[0])
    gaps = [later.bbox[0] - earlier.bbox[2] for earlier, later in zip(words, words[1:])]
    inside = sorted(gap for gap in gaps if 0 < gap < 20)
    typical = inside[len(inside) // 2] if inside else 2.5
    threshold = max(5.0, 2.5 * typical)
    clusters: list[list] = []
    for word in words:
        if clusters and word.bbox[0] - clusters[-1][-1].bbox[2] <= threshold:
            clusters[-1].append(word)
        else:
            clusters.append([word])
    return clusters


def table_columns(line: TextLine) -> list[Column] | None:
    """Read a table header into columns, each with the x range it occupies."""
    clusters = _word_clusters(line.words)
    if len(clusters) < 3:
        return None
    columns: list[Column] = []
    for cluster in clusters:
        text = " ".join(word.text for word in cluster)
        name = _column_for(text)
        if name is None:
            continue
        columns.append(
            Column(name=name, x0=min(w.bbox[0] for w in cluster), x1=max(w.bbox[2] for w in cluster))
        )
    names = [column.name for column in columns]
    if not names or names[0] != "serial" or "amount" not in names or "description" not in names:
        return None
    if len(names) != len(set(names)):
        return None
    return columns


def _assign_row(line: TextLine, columns: list[Column]) -> dict[str, list]:
    """Put each cell of a row into a column.

    Words are grouped into cells first, so a description keeps its own trailing words
    ("... Clips (ML)") instead of losing them to the next column. A cell goes to the column
    it overlaps most, and otherwise to the nearest one — descriptions are usually wider
    than the header above them.
    """
    numeric = [column for column in columns if column.name in NUMERIC_COLUMNS]
    text_columns = [column for column in columns if column.name not in NUMERIC_COLUMNS and column.name != "serial"]
    serial = next((column for column in columns if column.name == "serial"), None)
    buckets: dict[str, list] = {column.name: [] for column in columns}
    words = sorted(line.words, key=lambda word: word.bbox[0])
    # The row number sits on its own in the first column; take it before grouping the rest,
    # so a narrow gap cannot glue it to the description.
    if serial is not None and words and _SERIAL_CELL.match(words[0].text) and words[0].bbox[2] <= serial.x1 + 6:
        buckets["serial"].append(words[0])
        words = words[1:]
    for cluster in _word_clusters(words):
        x0 = cluster[0].bbox[0]
        x1 = cluster[-1].bbox[2]
        centre = (x0 + x1) / 2
        text = " ".join(word.text for word in cluster)
        candidates = numeric if (numeric and _NUMBER_CELL.match(text)) else text_columns
        if not candidates:
            continue
        overlaps = [(min(x1, column.x1) - max(x0, column.x0), column) for column in candidates]
        best_overlap, best_column = max(overlaps, key=lambda item: item[0])
        if best_overlap <= 0:
            best_column = min(candidates, key=lambda column: column.distance(centre if candidates is numeric else x0))
        buckets[best_column.name].extend(cluster)
    return buckets


def _bucket_text(buckets: dict[str, list], name: str) -> str | None:
    words = buckets.get(name) or []
    return " ".join(word.text for word in words) or None


def extract_bill(content: DocumentContent) -> BillData | None:
    """Read a bill or invoice: its table rows and its totals."""
    bill = BillData()
    for page in content.pages:
        columns: list[Column] | None = None
        for line in page.lines:
            header = table_columns(line)
            if header is not None:
                columns = header
                bill.columns = [column.name for column in header]
                bill.page_number = page.number
                continue
            if columns is not None:
                row = _parse_row(line, columns, page)
                if row is not None:
                    bill.line_items.append(row)
                    continue
            _apply_total(bill, line, page)
    if not bill.line_items and not any((bill.subtotal, bill.total)):
        return None
    if bill.total is None and bill.subtotal is not None:
        bill.total = bill.subtotal
        bill.totals_evidence.setdefault("total", bill.totals_evidence.get("subtotal", {}))
    return bill


def _parse_row(line: TextLine, columns: list[Column], page: PageContent) -> BillLine | None:
    words = line.words
    if not words or not _SERIAL_CELL.match(words[0].text):
        return None
    buckets = _assign_row(line, columns)
    amount = _bucket_text(buckets, "amount")
    description = _bucket_text(buckets, "description")
    if not amount or not description:
        return None
    amount_value = nz.parse_amount(amount)
    if amount_value is None:
        return None
    serial = _bucket_text(buckets, "serial")
    rate_value = nz.parse_amount(_bucket_text(buckets, "rate") or "")
    return BillLine(
        line_no=int(serial.rstrip(".")) if serial and serial.rstrip(".").isdigit() else None,
        description=nz.clean_text(description),
        quantity=nz.clean_text(_bucket_text(buckets, "quantity") or "") or None,
        rate=nz.format_amount(rate_value) if rate_value is not None else None,
        amount=nz.format_amount(amount_value),
        batch=nz.clean_text(_bucket_text(buckets, "batch") or "") or None,
        expiry=nz.clean_text(_bucket_text(buckets, "expiry") or "") or None,
        page_number=page.number,
        bbox=line.bbox,
        raw=re.sub(r"\s{2,}", " · ", line.text.strip())[:200],
    )


def _apply_total(bill: BillData, line: TextLine, page: PageContent) -> None:
    """Pick up "Sub Total", "Net Payable", tax and discount lines."""
    words = line.words
    if len(words) < 2 or len(line.cells()) < 2:
        # A totals line is a label in one column and its value in another. A single-column
        # line (a heading such as "TAX INVOICE") is not a total.
        return
    last = words[-1]
    label = " ".join(word.text for word in words[:-1]).strip().lower()
    if not label:
        return
    for pattern, name in TOTAL_PATTERNS:
        if not re.search(pattern, label):
            continue
        amount = nz.parse_amount(last.text) if _AMOUNT_CELL.match(last.text) else None
        if amount is None:
            note = re.sub(r"\s{2,}", " ", line.text.strip())[:120]
            if note not in bill.notes:
                bill.notes.append(note)
            return
        if getattr(bill, name) is not None:
            return
        setattr(bill, name, nz.format_amount(amount))
        start, end = line.spans[len(words) - 1]
        bill.totals_evidence[name] = {
            "page_number": page.number,
            "bbox": line.bbox_for_span(start, end),
            "snippet": re.sub(r"\s{2,}", " · ", line.text.strip())[:120],
            "method": _method(page, METHOD_TOTAL),
            "confidence": _confidence(page, line, start, end),
        }
        if bill.page_number is None:
            bill.page_number = page.number
        return


def bill_fields(bill: BillData, content: DocumentContent | None = None) -> list[ExtractedValue]:
    """Bill totals as extracted fields, each keeping the evidence it came from."""
    pages = {page.number: page for page in (content.pages if content else [])}
    out: list[ExtractedValue] = []
    labels = {
        "subtotal": "Bill subtotal",
        "tax": "Tax",
        "discount": "Discount",
        "total": "Bill total",
    }
    for key, label in labels.items():
        value = getattr(bill, key)
        if value is None:
            continue
        evidence = bill.totals_evidence.get(key, {})
        out.append(
            ExtractedValue(
                key=f"billing.{key}",
                label=label,
                group="billing",
                kind=AMOUNT,
                value=value,
                raw=evidence.get("snippet", ""),
                page_number=evidence.get("page_number"),
                bbox=evidence.get("bbox"),
                snippet=evidence.get("snippet", ""),
                method=evidence.get("method", METHOD_TOTAL),
                confidence=evidence.get("confidence", 0.9),
                details={"display": nz.format_indian(Decimal(value))},
            )
        )
    if bill.line_items:
        first = bill.line_items[0]
        page = pages.get(first.page_number)
        out.append(
            ExtractedValue(
                key="billing.line_item_count",
                label="Billed line items",
                group="billing",
                kind=INTEGER,
                value=str(len(bill.line_items)),
                raw=first.raw,
                page_number=first.page_number,
                bbox=first.bbox,
                snippet=first.raw,
                method=_method(page, METHOD_TABLE) if page else METHOD_TABLE,
                confidence=0.9,
                details={"columns": bill.columns},
            )
        )
    return out


def extract_fields(content: DocumentContent, groups: tuple[str, ...]) -> tuple[list[ExtractedValue], BillData | None]:
    """Run the extractor groups a document type asks for."""
    values: list[ExtractedValue] = []
    seen: set[str] = set()
    for group in groups:
        for spec in SPECS_BY_GROUP.get(group, []):
            for value in _values_from_spec(spec, content.pages):
                if value.key in seen or value.value in (None, ""):
                    continue
                seen.add(value.key)
                values.append(value)
    bill = extract_bill(content) if "billing" in groups else None
    if bill is not None:
        for value in bill_fields(bill, content):
            if value.key not in seen:
                seen.add(value.key)
                values.append(value)
    return values, bill

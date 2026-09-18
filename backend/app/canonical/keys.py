"""What the canonical claim states, and which extracted fields feed each value."""

from __future__ import annotations

from dataclasses import dataclass

# How a value is compared across documents.
NAME = "name"
PERSON = "person"
IDENTIFIER = "id"
DATE = "date"
TEXT = "text"
GENDER = "gender"
INTEGER = "integer"
AMOUNT = "amount"
DIAGNOSIS = "diagnosis"
PROCEDURE = "procedure"


@dataclass(frozen=True)
class CanonicalField:
    """One value of the canonical claim.

    `sources` names the Phase 3 field keys that can supply it. `detail_key` reads a derived
    value that extraction recorded alongside the field (an ICD-10 code, for example); the
    evidence stays the evidence of the field it came from.
    """

    key: str
    label: str
    section: str
    kind: str
    sources: tuple[str, ...]
    detail_key: str | None = None

    @property
    def name(self) -> str:
        return self.key.split(".", 1)[1]


FIELDS: tuple[CanonicalField, ...] = (
    # --- patient -------------------------------------------------------------------------
    CanonicalField("patient.name", "Patient name", "patient", NAME, ("patient.name",)),
    CanonicalField("patient.age", "Age", "patient", INTEGER, ("patient.age",)),
    CanonicalField("patient.gender", "Gender", "patient", GENDER, ("patient.gender",)),
    CanonicalField("patient.uhid", "UHID", "patient", IDENTIFIER, ("patient.uhid",)),
    CanonicalField("patient.ipd", "IPD number", "patient", IDENTIFIER, ("patient.ipd_number",)),
    CanonicalField("patient.date_of_birth", "Date of birth", "patient", DATE, ("patient.date_of_birth",)),
    # --- admission -----------------------------------------------------------------------
    CanonicalField("admission.admission_date", "Admission date", "admission", DATE, ("stay.admission_date",)),
    CanonicalField("admission.discharge_date", "Discharge date", "admission", DATE, ("stay.discharge_date",)),
    CanonicalField("admission.surgery_date", "Surgery date", "admission", DATE, ("stay.surgery_date",)),
    CanonicalField("admission.ward", "Ward / room", "admission", TEXT, ("stay.ward",)),
    CanonicalField("admission.admission_type", "Admission type", "admission", TEXT, ("stay.admission_type",)),
    CanonicalField("admission.insurer", "Insurer", "admission", TEXT, ("cover.insurer",)),
    CanonicalField("admission.tpa", "TPA", "admission", TEXT, ("cover.tpa",)),
    CanonicalField("admission.policy_number", "Policy number", "admission", IDENTIFIER, ("cover.policy_number",)),
    CanonicalField("admission.member_id", "Member ID", "admission", IDENTIFIER, ("cover.member_id",)),
    CanonicalField("admission.sum_insured", "Sum insured", "admission", AMOUNT, ("cover.sum_insured",)),
    # --- diagnosis -----------------------------------------------------------------------
    CanonicalField("diagnosis.primary", "Diagnosis", "diagnosis", DIAGNOSIS, ("clinical.diagnosis",)),
    CanonicalField("diagnosis.icd10", "ICD-10", "diagnosis", IDENTIFIER, ("clinical.diagnosis",), detail_key="icd10"),
    # --- procedures ----------------------------------------------------------------------
    CanonicalField("procedures.anaesthesia", "Anaesthesia", "procedures", TEXT, ("clinical.anaesthesia_type",)),
    # --- doctors -------------------------------------------------------------------------
    CanonicalField("doctors.surgeon", "Surgeon", "doctors", PERSON, ("clinical.surgeon",)),
    CanonicalField("doctors.anaesthetist", "Anaesthetist", "doctors", PERSON, ("clinical.anaesthetist",)),
)

# The procedure list is assembled separately: several procedures can be named across the
# documents, so they are grouped rather than voted down to one value.
PROCEDURE_FIELD = CanonicalField("procedures.procedure", "Procedure", "procedures", PROCEDURE, ("clinical.procedure",))

# Per-document investigation details, kept with the document that reported them.
INVESTIGATION_FIELDS: tuple[CanonicalField, ...] = (
    CanonicalField("investigation.report_number", "Report number", "investigations", IDENTIFIER, ("investigation.report_number",)),
    CanonicalField("investigation.sample_id", "Sample ID", "investigations", IDENTIFIER, ("investigation.sample_id",)),
    CanonicalField("investigation.study_date", "Study date", "investigations", DATE, ("investigation.study_date",)),
    CanonicalField("investigation.collected_on", "Collected on", "investigations", DATE, ("investigation.collected_on",)),
    CanonicalField("investigation.reported_on", "Reported on", "investigations", DATE, ("investigation.reported_on",)),
    CanonicalField("investigation.referred_by", "Referred by", "investigations", PERSON, ("investigation.referred_by",)),
)

# Bill values live with their bill, so each is read from that one document.
BILL_FIELDS: tuple[CanonicalField, ...] = (
    CanonicalField("billing.bill_number", "Bill number", "bills", IDENTIFIER, ("billing.bill_number",)),
    CanonicalField("billing.bill_date", "Bill date", "bills", DATE, ("billing.bill_date",)),
    CanonicalField("billing.payer", "Payer", "bills", TEXT, ("billing.payer",)),
    CanonicalField("billing.subtotal", "Subtotal", "bills", AMOUNT, ("billing.subtotal",)),
    CanonicalField("billing.tax", "Tax", "bills", AMOUNT, ("billing.tax",)),
    CanonicalField("billing.discount", "Discount", "bills", AMOUNT, ("billing.discount",)),
    CanonicalField("billing.total", "Total", "bills", AMOUNT, ("billing.total",)),
    CanonicalField("billing.amount_in_words", "Amount in words", "bills", TEXT, ("billing.amount_in_words",)),
)

SECTIONS: tuple[str, ...] = (
    "patient",
    "admission",
    "diagnosis",
    "procedures",
    "doctors",
    "investigations",
    "documents",
    "bills",
    "checklist",
    "findings",
    "questions",
    "resolutions",
    "audit_events",
)

# Sections whose engines arrive in later phases. They are present and empty, with a note,
# so the shape of the canonical claim never changes underneath the interface.
PENDING_SECTIONS: dict[str, str] = {
    "questions": "Operator questions are built in phase 7.",
    "resolutions": "Question resolutions are built in phase 7.",
}

INVESTIGATION_DOC_TYPES = ("lab_report", "investigation_report")

FIELDS_BY_SECTION: dict[str, tuple[CanonicalField, ...]] = {
    section: tuple(field for field in FIELDS if field.section == section)
    for section in ("patient", "admission", "diagnosis", "procedures", "doctors")
}

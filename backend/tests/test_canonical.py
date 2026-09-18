"""The canonical claim: how a value is chosen, and how its sources stay visible."""

import json

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.canonical import keys as canonical_keys
from app.canonical.selection import Candidate, absent, normalise, select_value
from app.config import get_settings
from app.db import make_engine
from app.models import Claim, ClaimState, ExtractedField
from app.services import canonical as canonical_service
from tests.conftest import DEMO_CLAIM, analyse

NAME_FIELD = canonical_keys.CanonicalField("patient.name", "Patient name", "patient", canonical_keys.NAME, ("patient.name",))
DATE_FIELD = canonical_keys.CanonicalField("admission.admission_date", "Admission date", "admission", canonical_keys.DATE, ("stay.admission_date",))
ID_FIELD = canonical_keys.CanonicalField("patient.uhid", "UHID", "patient", canonical_keys.IDENTIFIER, ("patient.uhid",))
AMOUNT_FIELD = canonical_keys.CanonicalField("billing.total", "Total", "bills", canonical_keys.AMOUNT, ("billing.total",))

WEIGHTS = {"patient_id": 3, "admission_record": 3, "discharge_summary": 3}


def candidate(
    value: str,
    *,
    doc_type: str = "consultation",
    name: str | None = None,
    kind: str = canonical_keys.NAME,
    method: str = "pdf_text:label_value",
    confidence: float = 0.95,
    page: int | None = 1,
    bbox: list[float] | None = None,
    field_key: str = "patient.name",
) -> Candidate:
    from app.canonical.selection import eligibility

    eligible, reason = eligibility(method, confidence)
    return Candidate(
        document_id=f"doc-{name or doc_type}",
        document_name=name or f"{doc_type}.pdf",
        document_type=doc_type,
        document_type_label=doc_type.replace("_", " ").title(),
        weight=WEIGHTS.get(doc_type, 1),
        field_key=field_key,
        value=value,
        raw_value=value,
        normalized=normalise(kind, value),
        page=page,
        bounding_box=bbox if bbox is not None else ([0.1, 0.2, 0.4, 0.22] if page else None),
        snippet=f"Patient Name: {value}",
        method=method,
        confidence=confidence,
        eligible=eligible,
        excluded_reason=reason,
    )


# --- how a value is chosen ---------------------------------------------------------------


def test_document_weight_decides_when_it_outweighs_the_count():
    """Two identity documents outweigh four documents that merely repeat a value."""
    heavy = [
        candidate("Rajesh Sharma", doc_type="admission_record", name="02_Admission_Form.pdf"),
        candidate("Rajesh Sharma", doc_type="discharge_summary", name="06_Discharge_Summary.pdf"),
    ]
    light = [candidate("Rajesh Kumar", doc_type="consultation", name=f"note-{index}.pdf") for index in range(4)]
    result = select_value(NAME_FIELD, heavy + light)
    assert result["value"] == "Rajesh Sharma"
    assert result["weight"] == 6
    assert result["source_count"] == 2
    assert [competing["value"] for competing in result["competing_values"]] == ["Rajesh Kumar"]
    assert result["competing_values"][0]["weight"] == 4


def test_the_number_of_supporting_documents_breaks_a_tie_on_weight():
    three_light = [candidate("Rajesh Sharma", name=f"note-{index}.pdf") for index in range(3)]
    one_heavy = [candidate("Rajesh Kumar", doc_type="patient_id", name="01_Patient_ID.png")]
    result = select_value(NAME_FIELD, three_light + one_heavy)
    assert result["weight"] == result["competing_values"][0]["weight"] == 3
    assert result["value"] == "Rajesh Sharma"
    assert result["source_count"] == 3


def test_ocr_below_the_confidence_floor_does_not_take_part():
    """A doubtful OCR reading cannot outvote a text-layer value, even from a heavier document."""
    doubtful = candidate(
        "Rajesh Kumar", doc_type="patient_id", name="01_Patient_ID.png", method="ocr:label_value", confidence=0.62
    )
    reliable = candidate("Rajesh Sharma", doc_type="consultation", name="03_Doctor_Consultation.pdf")
    result = select_value(NAME_FIELD, [doubtful, reliable])
    assert result["value"] == "Rajesh Sharma"
    excluded = result["competing_values"][0]["sources"][0]
    assert excluded["eligible"] is False
    assert "0.62" in excluded["excluded_reason"]
    assert "0.80" in excluded["excluded_reason"]
    assert result["competing_values"][0]["weight"] == 0, "an excluded source carries no weight"
    assert result["competing_values"][0]["eligible_source_count"] == 0


def test_ocr_above_the_floor_takes_part():
    ocr = candidate("Rajesh Sharma", doc_type="patient_id", name="01_Patient_ID.png", method="ocr:label_value", confidence=0.88)
    result = select_value(NAME_FIELD, [ocr])
    assert result["present"] is True
    assert result["weight"] == 3
    assert result["sources"][0]["eligible"] is True
    assert result["sources"][0]["source_type"] == "ocr"
    assert result["sources"][0]["source_type_label"] == "OCR"


def test_a_field_only_supported_by_doubtful_ocr_is_not_stated():
    doubtful = candidate("Rajesh Sharma", method="ocr:label_value", confidence=0.4)
    result = select_value(NAME_FIELD, [doubtful])
    assert result["present"] is False
    assert result["value"] is None
    assert len(result["sources"]) == 1, "the excluded source is still shown"
    assert result["sources"][0]["eligible"] is False
    assert "excluded from selection" in result["note"]


def test_an_absent_field_says_so():
    result = absent(NAME_FIELD)
    assert result["present"] is False
    assert result["sources"] == []
    assert result["evidence_available"] is False
    assert "No document in this claim carries this value" in result["note"]


# --- normalisation before comparison ------------------------------------------------------


def test_names_are_compared_without_honorifics_case_or_qualifications():
    sources = [
        candidate("Dr. Anil Mehta, MS (General Surgery)", doc_type="discharge_summary", name="06_Discharge_Summary.pdf"),
        candidate("ANIL MEHTA", name="07_Prescription.pdf"),
        candidate("Anil  Mehta", name="14_OT_Bill.pdf"),
    ]
    result = select_value(NAME_FIELD, sources)
    assert result["normalized_value"] == "anil mehta"
    assert result["source_count"] == 3
    assert result["competing_values"] == []


def test_dates_are_compared_as_calendar_dates_not_as_text():
    sources = [
        candidate("12-01-2026", kind=canonical_keys.DATE, doc_type="admission_record", name="02_Admission_Form.pdf"),
        candidate("2026-01-12", kind=canonical_keys.DATE, name="08_Nursing_Record.pdf"),
        candidate("12/01/2026", kind=canonical_keys.DATE, name="12_Main_Hospital_Bill.pdf"),
    ]
    result = select_value(DATE_FIELD, sources)
    assert result["normalized_value"] == "2026-01-12"
    assert result["source_count"] == 3
    assert result["has_competing_values"] is False


def test_a_different_calendar_date_is_a_competing_value():
    sources = [
        candidate("12-01-2026", kind=canonical_keys.DATE, doc_type="admission_record", name="02_Admission_Form.pdf"),
        candidate("13-01-2026", kind=canonical_keys.DATE, name="08_Nursing_Record.pdf"),
    ]
    result = select_value(DATE_FIELD, sources)
    assert result["normalized_value"] == "2026-01-12"
    assert [item["normalized_value"] for item in result["competing_values"]] == ["2026-01-13"]


def test_identifiers_are_compared_without_punctuation_or_case():
    sources = [
        candidate("UHID-123456", kind=canonical_keys.IDENTIFIER, doc_type="admission_record", name="02_Admission_Form.pdf"),
        candidate("uhid 123456", kind=canonical_keys.IDENTIFIER, name="10_Lab_Report.pdf"),
    ]
    result = select_value(ID_FIELD, sources)
    assert result["normalized_value"] == "uhid123456"
    assert result["source_count"] == 2


def test_amounts_are_compared_numerically():
    sources = [
        candidate("1,14,360.00", kind=canonical_keys.AMOUNT, name="12_Main_Hospital_Bill.pdf"),
        candidate("114360", kind=canonical_keys.AMOUNT, name="12_Main_Hospital_Bill_copy.pdf"),
    ]
    result = select_value(AMOUNT_FIELD, sources)
    assert result["normalized_value"] == "114360.00"
    assert result["has_competing_values"] is False


def test_the_stated_wording_is_the_one_most_documents_print():
    sources = [
        candidate("Rajesh Sharma", name="a.pdf"),
        candidate("Rajesh Sharma", name="b.pdf"),
        candidate("RAJESH SHARMA", doc_type="patient_id", name="01_Patient_ID.png"),
    ]
    result = select_value(NAME_FIELD, sources)
    assert result["value"] == "Rajesh Sharma"
    assert result["value_variants"] == [
        {"value": "Rajesh Sharma", "source_count": 2},
        {"value": "RAJESH SHARMA", "source_count": 1},
    ]


def test_competing_values_are_reported_without_judging_them():
    result = select_value(
        NAME_FIELD,
        [
            candidate("Rajesh Sharma", doc_type="admission_record", name="02_Admission_Form.pdf"),
            candidate("Rajesh K", name="13_Pharmacy_Bill.pdf"),
        ],
    )
    assert result["has_competing_values"] is True
    assert result["note"] == "Multiple source values detected. The competing values and their sources are listed."
    text = json.dumps(result).lower()
    for word in ("mismatch", "wrong", "incorrect", "invalid", "error", "suspicious", "fraud", "better", "worse", "unreliable"):
        assert word not in text, f"{word!r} is a verdict, not provenance"


def test_sources_are_ordered_by_document_name_not_by_row_order():
    names = ["z.pdf", "a.pdf", "m.pdf"]
    result = select_value(NAME_FIELD, [candidate("Rajesh Sharma", name=name) for name in names])
    assert [source["document_name"] for source in result["sources"]] == ["a.pdf", "m.pdf", "z.pdf"]


def test_a_source_without_a_page_reports_that_evidence_is_unavailable():
    result = select_value(NAME_FIELD, [candidate("Rajesh Sharma", page=None, bbox=None)])
    assert result["present"] is True
    assert result["sources"][0]["evidence_available"] is False
    assert result["sources"][0]["page"] is None
    assert result["sources"][0]["bounding_box"] is None
    assert result["evidence_available"] is False


# --- the canonical claim of the demo claim -------------------------------------------------


@pytest.fixture(scope="module")
def analysed(client):
    """One claim with all 18 demo documents analysed, and its canonical state."""
    from app.services.workspace import rebuild_workspace
    from app.worker import get_worker

    worker = get_worker()
    worker.drain()
    assert worker.wait_idle(60)
    rebuild_workspace()
    claim = client.post("/api/claims", json=DEMO_CLAIM).json()
    for name in ("initial", "operative_note", "anaesthesia_record"):
        response = client.post(f"/api/claims/{claim['id']}/demo-documents", params={"set": name})
        assert response.status_code == 200, response.text
    analyse(client, claim["id"])
    state = client.get(f"/api/claims/{claim['id']}/state")
    assert state.status_code == 200, state.text
    return {"claim": claim, "state": state.json()}


def value_of(state: dict, path: str) -> dict:
    section, name = path.split(".", 1)
    if section == "procedures":
        return state["procedures"]["fields"][name]
    return state[section]["fields"][name]


def test_canonical_patient_identity_comes_from_the_documents(analysed):
    state = analysed["state"]
    assert value_of(state, "patient.name")["value"] == "Rajesh Sharma"
    assert value_of(state, "patient.age")["value"] == "46"
    assert value_of(state, "patient.gender")["value"] == "male"
    assert value_of(state, "patient.uhid")["value"] == "UHID-123456"
    assert value_of(state, "patient.ipd")["value"] == "IPD/2026/004512"
    assert value_of(state, "patient.date_of_birth")["value"] == "1979-03-14"
    assert state["patient"]["present_count"] == state["patient"]["field_count"] == 6


def test_canonical_admission_and_clinical_values(analysed):
    state = analysed["state"]
    assert value_of(state, "admission.admission_date")["value"] == "2026-01-12"
    assert value_of(state, "admission.discharge_date")["value"] == "2026-01-16"
    assert value_of(state, "admission.surgery_date")["value"] == "2026-01-13"
    assert value_of(state, "diagnosis.primary")["value"] == "Acute cholecystitis"
    assert value_of(state, "diagnosis.icd10")["value"] == "K81.0"
    assert value_of(state, "doctors.surgeon")["value"] == "Dr. Anil Mehta"
    assert value_of(state, "doctors.anaesthetist")["value"] == "Dr. Priya Nair"
    assert value_of(state, "admission.insurer")["value"] == "Demo Health Insurance"
    assert value_of(state, "admission.sum_insured")["value"] == "500000.00"


def test_the_identity_documents_carry_the_most_weight_for_the_patient_name(analysed):
    name = value_of(analysed["state"], "patient.name")
    weights = {source["document_name"]: source["weight"] for source in name["sources"]}
    assert weights["01_Patient_ID.png"] == 3
    assert weights["02_Admission_Form.pdf"] == 3
    assert weights["06_Discharge_Summary.pdf"] == 3
    assert weights["03_Doctor_Consultation.pdf"] == 1
    assert name["weight"] == sum(weights.values())


def test_the_patient_name_has_many_supporting_sources(analysed):
    name = value_of(analysed["state"], "patient.name")
    assert name["source_count"] >= 15
    assert len({source["document_id"] for source in name["sources"]}) == name["source_count"]
    assert all(source["page"] for source in name["sources"])
    assert all(source["evidence_available"] for source in name["sources"])


def test_the_shortened_name_on_the_pharmacy_bill_is_reported_as_a_competing_value(analysed):
    """The demo seeds a shortened patient name on one bill; provenance shows it, nothing judges it."""
    name = value_of(analysed["state"], "patient.name")
    assert name["has_competing_values"] is True
    competing = name["competing_values"]
    assert [item["value"] for item in competing] == ["Rajesh K"]
    assert [source["document_name"] for source in competing[0]["sources"]] == ["13_Pharmacy_Bill.pdf"]
    assert competing[0]["sources"][0]["page"] == 1
    assert competing[0]["sources"][0]["bounding_box"]
    # The canonical claim reports the difference as provenance. Judging it is the validation
    # engine's job, and its findings are listed in their own section.
    assert analysed["state"]["findings"]["available"] is True


def test_the_procedure_is_grouped_across_its_short_forms(analysed):
    procedures = analysed["state"]["procedures"]
    assert procedures["selected_key"] == "laparoscopic_cholecystectomy"
    selected = next(item for item in procedures["items"] if item["is_selected"])
    assert selected["procedure_key"] == "laparoscopic_cholecystectomy"
    assert selected["label"] == "Laparoscopic cholecystectomy"
    assert selected["value"] == "Laparoscopic Cholecystectomy"
    variants = {variant["value"] for variant in selected["value_variants"]}
    assert "Lap Chole" in variants, "a short form is the same procedure, not a competing one"
    assert selected["source_count"] >= 8
    assert procedures["selected"]["normalized_value"] == "laparoscopic_cholecystectomy"


def test_no_canonical_value_is_invented(analysed):
    """Every stated value must exist in an extracted field of this claim."""
    state = analysed["state"]
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            rows = session.scalars(
                select(ExtractedField).where(ExtractedField.claim_id == state["claim"]["claim_id"])
            ).all()
            extracted = {(row.field_key, row.value_text) for row in rows}
            details = {
                (row.field_key, str(value))
                for row in rows
                for value in (row.details or {}).values()
                if isinstance(value, str)
            }
    finally:
        engine.dispose()

    checked = 0
    for section in ("patient", "admission", "diagnosis", "doctors"):
        for value in state[section]["fields"].values():
            if not value["present"]:
                continue
            checked += 1
            keys = {source["field_key"] for source in value["sources"]}
            assert any((key, value["value"]) in extracted or (key, value["value"]) in details for key in keys), (
                f"{value['key']} = {value['value']!r} is not an extracted value"
            )
    assert checked >= 18


def test_every_source_points_at_a_real_document_page(analysed):
    state = analysed["state"]
    pages = {item["document_id"]: item["page_count"] for item in state["documents"]["items"]}
    sources = 0
    for section in ("patient", "admission", "diagnosis", "doctors"):
        for value in state[section]["fields"].values():
            for source in value["sources"]:
                sources += 1
                assert source["document_id"] in pages
                assert 1 <= source["page"] <= pages[source["document_id"]]
                box = source["bounding_box"]
                assert len(box) == 4 and all(0.0 <= item <= 1.0 for item in box)
                assert box[2] > box[0] and box[3] > box[1]
                assert source["snippet"]
                assert source["method"]
    assert sources > 80


def test_ocr_sourced_values_are_labelled_as_ocr(analysed):
    member_id = value_of(analysed["state"], "admission.member_id")
    card = next(source for source in member_id["sources"] if source["document_name"] == "01_Patient_ID.png")
    assert card["source_type"] == "ocr"
    assert card["method"].startswith("ocr:")
    assert card["confidence"] <= 0.9


def test_claim_form_values_are_kept_apart_from_document_values(analysed):
    state = analysed["state"]
    assert state["claim"]["form"]["patient_name"] == "Rajesh Sharma"
    assert state["claim"]["hospital"] == "CityCare Multispeciality Hospital"
    # The form is not a source: nothing in the canonical values cites it.
    for section in ("patient", "admission", "diagnosis", "doctors"):
        for value in state[section]["fields"].values():
            assert all(source["document_id"] for source in value["sources"])


def test_bills_are_canonicalised_with_their_line_items(analysed):
    bills = analysed["state"]["bills"]
    assert bills["count"] == 4
    assert bills["summary"]["by_type"] == {
        "hospital_bill": 1,
        "implant_invoice": 1,
        "ot_bill": 1,
        "pharmacy_bill": 1,
    }
    by_type = {item["bill_type"]: item for item in bills["items"]}
    hospital = by_type["hospital_bill"]
    assert hospital["fields"]["number"]["value"] == "CCH/IP/2026/08812"
    assert hospital["fields"]["date"]["value"] == "2026-01-16"
    assert hospital["fields"]["total"]["value"] == "114360.00"
    assert hospital["fields"]["subtotal"]["value"] == "114360.00"
    assert hospital["line_item_count"] == 10
    first = hospital["line_items"][0]
    assert first["line_no"] == 1
    assert first["description"].startswith("Room Rent")
    assert (first["quantity"], first["rate"], first["amount"]) == ("4", "4500.00", "20000.00")

    implant = by_type["implant_invoice"]
    assert implant["fields"]["number"]["value"] == "DS/INV/2026/0391"
    assert implant["line_items"][0]["rate"] == "1100.00", "the covered rate never reaches the canonical claim"
    assert "1,000.00" not in json.dumps(bills)

    pharmacy = by_type["pharmacy_bill"]
    assert pharmacy["line_item_count"] == 13
    assert pharmacy["line_items"][0]["batch"] == "CFX2511A"
    assert pharmacy["line_items"][0]["expiry"] == "08/2027"


def test_bill_values_and_line_items_carry_evidence(analysed):
    for bill in analysed["state"]["bills"]["items"]:
        for value in bill["fields"].values():
            if value["present"]:
                assert value["sources"], value["key"]
                assert all(source["document_id"] == bill["document_id"] for source in value["sources"])
        for line in bill["line_items"]:
            evidence = line["evidence"]
            assert evidence["document_id"] == bill["document_id"]
            assert evidence["page"] == 1
            assert len(evidence["bounding_box"]) == 4
            assert evidence["evidence_available"] is True
            assert evidence["snippet"]


def test_bill_arithmetic_is_not_checked_here(analysed):
    """Phase 4 reports the bills as extracted; checking the sums is phase 5."""
    bills = analysed["state"]["bills"]
    assert "Totals are reported as extracted" in bills["note"]
    text = json.dumps(bills).lower()
    for word in ("mismatch", "does not add", "expected total", "discrepanc"):
        assert word not in text


def test_the_document_inventory_describes_every_document(analysed):
    documents = analysed["state"]["documents"]
    assert documents["count"] == 18
    assert sum(documents["by_type"].values()) == 18
    assert documents["by_type"]["lab_report"] == 2
    for item in documents["items"]:
        assert item["document_id"] and item["filename"]
        assert item["doc_type"] and item["doc_type_label"]
        assert item["classification_confidence"] and item["classification_method"].startswith("content_rules")
        assert item["processing_status"] == "processed"
        assert item["page_count"] >= 1
        assert item["ocr_method"] in {"rapidocr", "demo_fixture", "pdf_text"}
        assert item["duplicate_state"] in ("unique", "duplicate", "has_duplicate")
        assert item["excluded"] is False
        assert item["extracted_field_count"] >= 1
        assert isinstance(item["quality_signals"], list)
    copies = [item for item in documents["items"] if item["filename"].startswith(("10_Lab", "11_Lab"))]
    assert {item["duplicate_state"] for item in copies} == {"has_duplicate", "duplicate"}
    duplicate = next(item for item in copies if item["duplicate_state"] == "duplicate")
    assert duplicate["duplicate_of"]

    usg = next(item for item in documents["items"] if item["filename"] == "09_USG_Abdomen_Scan.jpg")
    assert usg["quality_signal_count"] >= 2
    consent = next(item for item in documents["items"] if item["filename"] == "16_Consent_Form.pdf")
    assert consent["unsigned_required_slots"] == ["Patient / guardian"]


def test_investigations_are_listed_with_their_documents(analysed):
    investigations = analysed["state"]["investigations"]
    assert investigations["count"] == 3
    names = [item["document_name"] for item in investigations["items"]]
    assert names == ["09_USG_Abdomen_Scan.jpg", "10_Lab_Report.pdf", "11_Lab_Report_copy.pdf"]
    usg = investigations["items"][0]
    assert usg["fields"]["report_number"]["value"] == "RAD/USG/2026/00731"
    assert usg["fields"]["study_date"]["value"] == "2026-01-12"
    lab = investigations["items"][1]
    assert lab["fields"]["sample_id"]["value"] == "LAB/2026/118204"
    assert all(
        source["document_id"] == lab["document_id"]
        for value in lab["fields"].values()
        for source in value["sources"]
    )


def test_every_section_of_the_canonical_claim_is_built(analysed):
    """Each section of the model now has an engine behind it."""
    state = analysed["state"]
    assert state["meta"]["pending_sections"] == {}
    for section in ("patient", "admission", "diagnosis", "procedures", "doctors", "investigations"):
        assert section in state
    for section in ("findings", "checklist", "questions", "resolutions"):
        assert state[section]["available"] is True, section


def test_the_snapshot_carries_the_audit_trail(analysed):
    events = analysed["state"]["audit_events"]
    assert events["count"] >= 40
    types = {item["event_type"] for item in events["items"]}
    assert {"claim_created", "document_uploaded", "document_processed", "claim_analysis_completed"} <= types
    assert [item["id"] for item in events["items"]] == sorted(item["id"] for item in events["items"])


def test_the_state_payload_has_one_stable_shape(analysed):
    state = analysed["state"]
    assert set(state) == {
        "claim",
        "meta",
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
        "snapshot",
    }
    assert state["meta"]["value_selection"]["document_weights"] == {
        "admission_record": 3,
        "discharge_summary": 3,
        "patient_id": 3,
    }
    assert state["meta"]["value_selection"]["ocr_confidence_floor"] == 0.8
    assert state["meta"]["analysis_state"] == "completed"
    assert state["meta"]["document_counts"]["processed"] == 18


# --- determinism and storage ---------------------------------------------------------------


def test_building_the_canonical_claim_twice_gives_the_same_document(analysed, client):
    first = client.get(f"/api/claims/{analysed['claim']['id']}/state").json()
    second = client.get(f"/api/claims/{analysed['claim']['id']}/state").json()
    assert first["snapshot"]["content_sha256"] == second["snapshot"]["content_sha256"]
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


def test_the_snapshot_is_stored_and_matches_what_is_served(analysed, client):
    claim_id = analysed["claim"]["id"]
    served = client.get(f"/api/claims/{claim_id}/state").json()
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            row = session.scalar(select(ClaimState).where(ClaimState.claim_id == claim_id))
            assert row is not None
            assert row.content_sha256 == served["snapshot"]["content_sha256"]
            assert row.document_count == 18
            assert row.processed_count == 18
            assert canonical_service.content_hash(row.payload) == row.content_sha256
            assert row.payload["patient"]["fields"]["name"]["value"] == "Rajesh Sharma"
    finally:
        engine.dispose()


def test_a_lost_snapshot_is_rebuilt_identically(analysed, client):
    """The stored snapshot is a cache of a deterministic build, never a second source of truth."""
    claim_id = analysed["claim"]["id"]
    before = client.get(f"/api/claims/{claim_id}/state").json()
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            row = session.scalar(select(ClaimState).where(ClaimState.claim_id == claim_id))
            session.delete(row)
            session.commit()
    finally:
        engine.dispose()
    after = client.get(f"/api/claims/{claim_id}/state").json()
    assert after["snapshot"]["content_sha256"] == before["snapshot"]["content_sha256"]
    assert json.dumps({k: v for k, v in after.items() if k != "snapshot"}, sort_keys=True) == json.dumps(
        {k: v for k, v in before.items() if k != "snapshot"}, sort_keys=True
    )


def test_the_snapshot_is_built_from_the_stored_state_alone(analysed):
    """Building from a fresh session, with no request in flight, gives the same document."""
    claim_id = analysed["claim"]["id"]
    engine = make_engine(get_settings().database_url)
    try:
        with Session(engine) as session:
            claim = session.get(Claim, claim_id)
            first = canonical_service.build(session, claim)
            second = canonical_service.build(session, claim)
    finally:
        engine.dispose()
    assert canonical_service.content_hash(first) == canonical_service.content_hash(second)
    assert first == second
    assert first["patient"]["fields"]["uhid"]["value"] == "UHID-123456"


# --- the endpoint on claims that are not ready ---------------------------------------------


def test_the_state_of_a_claim_without_documents_is_coherent(client, claim):
    state = client.get(f"/api/claims/{claim['id']}/state").json()
    assert state["claim"]["claim_number"] == claim["claim_number"]
    assert state["documents"]["count"] == 0
    assert state["documents"]["items"] == []
    assert state["documents"]["by_type"] == {}
    assert state["documents"]["excluded_count"] == 0
    assert state["bills"]["count"] == 0
    assert state["procedures"]["items"] == []
    assert state["procedures"]["selected_key"] is None
    assert state["meta"]["analysis_state"] == "idle"
    for value in state["patient"]["fields"].values():
        assert value["present"] is False
        assert value["sources"] == []
        assert "No document in this claim carries this value" in value["note"]
    assert state["snapshot"]["document_count"] == 0


def test_the_state_before_analysis_shows_the_documents_as_pending(client, claim):
    from tests.conftest import pack_files, pick, upload

    upload(client, claim["id"], pick(pack_files(), "02_Admission_Form.pdf"))
    state = client.get(f"/api/claims/{claim['id']}/state").json()
    assert state["documents"]["count"] == 1
    item = state["documents"]["items"][0]
    assert item["processing_status"] == "pending"
    assert item["doc_type"] is None
    assert item["extracted_field_count"] == 0
    assert state["meta"]["analysis_state"] == "idle"
    assert state["patient"]["fields"]["name"]["present"] is False


def test_the_state_endpoint_rejects_unknown_claims(client, workspace):
    assert client.get("/api/claims/does-not-exist/state").status_code == 404
    assert client.get("/api/claims/%00/state").status_code == 404
    assert client.post("/api/claims/does-not-exist/state").status_code == 405


def test_the_state_endpoint_is_documented(client):
    paths = client.get("/api/openapi.json").json()["paths"]
    assert "/api/claims/{claim_id}/state" in paths
    assert "get" in paths["/api/claims/{claim_id}/state"]

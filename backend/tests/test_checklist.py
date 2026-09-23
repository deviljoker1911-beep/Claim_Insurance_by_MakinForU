"""The procedure checklist: what the configuration must hold, and what the engine reports.

The engine is a function of the canonical claim, so most of these tests hand it a small
state built by hand. The API tests below run real documents through the real pipeline.
"""

import pytest

from app.config_files import checklists_config

from app.analysis import normalize as nz
from app.checklist import engine
from app.config_files import ConfigError, checklists_config, document_types_config


# --- the configuration ---------------------------------------------------------------------


def test_every_requirement_names_document_types_that_exist():
    known = {entry["key"] for entry in document_types_config()["types"]}
    for requirement in checklists_config()["requirements"]:
        assert set(requirement["doc_types"]) <= known, requirement["key"]
        assert requirement["doc_types"], requirement["key"]


def test_every_condition_a_requirement_names_is_implemented():
    conditions = set(checklists_config()["conditions"])
    assert conditions == {engine.ALWAYS, engine.IMPLANT_BILLED, engine.GENERAL_ANAESTHESIA}
    for condition in conditions:
        engine._condition_holds(condition, _state())


def test_an_unimplemented_condition_is_refused_rather_than_ignored():
    with pytest.raises(ValueError):
        engine._condition_holds("phase_of_the_moon", _state())


def test_the_three_prototype_procedures_have_a_checklist():
    assert [item["key"] for item in engine.configured_procedures()][:3] == [
        "laparoscopic_cholecystectomy",
        "knee_replacement",
        "cataract_surgery",
    ]


def test_every_procedure_the_documents_can_name_has_a_checklist():
    """The test that would have caught the gap a real claim packet found.

    Detection knew thirteen operations and checklists existed for three. A claim for a hernia
    repair was recognised as one, then told no checklist was configured — so nothing it carried
    was measured against what that operation needs, and it asked the operator for nothing. The
    two lists are kept in step here, in both directions.
    """
    detectable = {key for key, _, _ in nz.PROCEDURES}
    configured = {item["key"] for item in engine.configured_procedures()}
    assert detectable - configured == set(), f"recognised but with no checklist: {detectable - configured}"
    assert configured - detectable == set(), f"a checklist nothing can select: {configured - detectable}"


def test_a_procedure_may_override_a_requirement_without_changing_the_catalogue():
    catalogue = {item["key"]: item for item in checklists_config()["requirements"]}
    assert catalogue["implant_invoice"]["applies_when"] == "implant_billed"
    knee = next(p for p in checklists_config()["procedures"] if p["key"] == "knee_replacement")
    implant = next(item for item in engine._requirements_of(knee) if item["key"] == "implant_invoice")
    assert implant["applies_when"] == "always", "a joint replacement always uses an implant"
    assert implant["severity"] == "critical"
    # The catalogue entry is untouched by the override.
    assert catalogue["implant_invoice"]["applies_when"] == "implant_billed"


def test_a_broken_checklist_configuration_is_refused(tmp_path, monkeypatch):
    from app.config import get_settings

    settings = get_settings()
    original = (settings.config_dir / "checklists.yaml").read_text(encoding="utf-8")
    for name in tuple(p.name for p in settings.config_dir.glob("*.yaml")):
        (tmp_path / name).write_text((settings.config_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "checklists.yaml").write_text(
        original.replace("doc_types: [operative_note]", "doc_types: [surgical_epic]"), encoding="utf-8"
    )
    monkeypatch.setattr(settings, "config_dir", tmp_path)
    checklists_config.cache_clear()
    try:
        with pytest.raises(ConfigError, match="unknown document types"):
            checklists_config()
    finally:
        monkeypatch.undo()
        checklists_config.cache_clear()


# --- procedure detection (module 7) ---------------------------------------------------------


@pytest.mark.parametrize(
    "printed",
    ["Laparoscopic Cholecystectomy", "Lap Chole", "Lap. Cholecystectomy", "LAPAROSCOPIC CHOLECYSTECTOMY"],
)
def test_the_same_operation_written_differently_resolves_to_one_key(printed):
    assert nz.normalise_procedure(printed)["key"] == "laparoscopic_cholecystectomy"


@pytest.mark.parametrize(
    ("printed", "key"),
    [
        ("Total Knee Replacement", "knee_replacement"),
        ("TKR (right)", "knee_replacement"),
        ("Total knee arthroplasty", "knee_replacement"),
        ("Cataract Surgery", "cataract_surgery"),
        ("Phacoemulsification with IOL", "cataract_surgery"),
        ("Cataract extraction", "cataract_surgery"),
    ],
)
def test_the_other_two_prototype_procedures_are_detected(printed, key):
    assert nz.normalise_procedure(printed)["key"] == key


@pytest.mark.parametrize(
    ("printed", "key"),
    [
        ("Total Hip Replacement (L)", "hip_replacement"),
        ("THR right", "hip_replacement"),
        ("Bipolar hemiarthroplasty", "hip_replacement"),
        ("CABG x3", "cabg"),
        ("Coronary artery bypass grafting", "cabg"),
        ("TURP", "turp"),
        ("Transurethral resection of the prostate", "turp"),
        ("PCNL (right)", "pcnl"),
        ("Percutaneous nephrolithotomy", "pcnl"),
        ("ORIF with plating", "fracture_fixation"),
        ("Closed reduction and internal fixation", "fracture_fixation"),
        ("Intramedullary nailing of femur", "fracture_fixation"),
        ("DHS fixation", "fracture_fixation"),
    ],
)
def test_the_operations_added_from_real_packets_are_detected(printed, key):
    assert nz.normalise_procedure(printed)["key"] == key


@pytest.mark.parametrize(
    "printed",
    [
        "Acute cholecystitis",
        # Each of these is the condition an added operation treats. Reading the diagnosis as the
        # operation would give a claim for a fracture a checklist for surgery it never had.
        "Fracture neck of femur",
        "Coronary artery disease",
        "BPH",
        "Renal calculus",
        "Osteoarthritis hip",
        # And two that share letters with an abbreviation: "plating" and "urs".
        "Platelet count low",
        "24 hours observation",
    ],
)
def test_a_diagnosis_is_not_read_as_the_operation(printed):
    assert nz.normalise_procedure(printed) is None


@pytest.mark.parametrize("key", ["angioplasty", "hip_replacement", "fracture_fixation"])
def test_an_operation_that_always_leaves_an_implant_always_asks_for_its_invoice(key):
    """A stent, a prosthesis, a plate: the invoice is expected whether or not one was billed."""
    procedure = next(p for p in checklists_config()["procedures"] if p["key"] == key)
    implant = next(r for r in engine._requirements_of(procedure) if r["key"] == "implant_invoice")
    assert implant["applies_when"] == "always"
    assert implant["severity"] == "critical"


@pytest.mark.parametrize("key", ["hernia_repair", "ureteroscopy", "pcnl", "cabg"])
def test_an_operation_that_only_sometimes_leaves_one_asks_once_it_is_billed(key):
    procedure = next(p for p in checklists_config()["procedures"] if p["key"] == key)
    implant = next(r for r in engine._requirements_of(procedure) if r["key"] == "implant_invoice")
    assert implant["applies_when"] == "implant_billed"


def test_angioplasty_under_local_does_not_ask_for_an_anaesthesia_chart():
    """Done in the catheter laboratory under local, so the chart is conditional, as for cataract."""
    procedure = next(p for p in checklists_config()["procedures"] if p["key"] == "angioplasty")
    by_key = {r["key"]: r for r in engine._requirements_of(procedure)}
    assert by_key["anaesthesia_record"]["applies_when"] == "general_anaesthesia"
    assert by_key["operative_note"]["label"] == "Angioplasty procedure note"


def test_an_unknown_operation_names_no_procedure():
    assert nz.normalise_procedure("Whipple procedure") is None


# --- the engine ------------------------------------------------------------------------------


def _document(name, doc_type, **overrides):
    return {
        "document_id": overrides.get("document_id", f"doc-{name}"),
        "filename": name,
        "doc_type": doc_type,
        "doc_type_label": None,
        "classification_confidence": 0.9,
        "classification_method": "content_rules_title",
        "processing_status": overrides.get("processing_status", "processed"),
        "page_count": 1,
        "excluded": overrides.get("excluded", False),
    }


def _state(documents=None, *, procedure="laparoscopic_cholecystectomy", bills=None, anaesthesia="General anaesthesia"):
    selected = (
        {
            "procedure_key": procedure,
            "label": "Laparoscopic cholecystectomy",
            "value": "Laparoscopic Cholecystectomy",
            "normalized_value": procedure,
            "weight": 3,
            "source_count": 2,
            "value_variants": [{"value": "Laparoscopic Cholecystectomy", "source_count": 2}],
            "sources": [{"document_id": "doc-op", "document_name": "op.pdf", "value": "Lap Chole", "page": 1}],
            "is_selected": True,
        }
        if procedure
        else None
    )
    return {
        "documents": {"items": list(documents or [])},
        "bills": {"items": list(bills or [])},
        "procedures": {
            "selected_key": procedure,
            "items": [selected] if selected else [],
            "fields": {
                "anaesthesia": {"value": anaesthesia, "normalized_value": (anaesthesia or "").lower(), "present": bool(anaesthesia)}
            },
        },
    }


def _row(checklist, key):
    return next(item for item in checklist["items"] if item["key"] == key)


def test_a_document_of_the_right_type_satisfies_its_requirement():
    checklist = engine.build_checklist(_state([_document("Op_Note.pdf", "operative_note")]))
    row = _row(checklist, "operative_note")
    assert row["status"] == engine.FOUND
    assert [item["document_name"] for item in row["evidence"]] == ["Op_Note.pdf"]
    assert row["evidence"][0]["page"] is None
    assert row["evidence"][0]["detail"] == "Source document identified; page-level evidence unavailable."


def test_a_requirement_with_no_document_is_missing_and_says_what_is_looked_for():
    checklist = engine.build_checklist(_state([]))
    row = _row(checklist, "operative_note")
    assert row["status"] == engine.MISSING
    assert row["detail"] == "No document in this claim was classified as operative note."
    assert row["evidence"] == []
    assert row["resolution"]


def test_a_file_name_alone_satisfies_nothing():
    """The type comes from the content; a helpful file name is not evidence."""
    checklist = engine.build_checklist(_state([_document("Operative_Note.pdf", "other")]))
    assert _row(checklist, "operative_note")["status"] == engine.MISSING


def test_a_document_excluded_as_a_duplicate_satisfies_nothing():
    documents = [_document("Op_Note.pdf", "operative_note", excluded=True)]
    row = _row(engine.build_checklist(_state(documents)), "operative_note")
    assert row["status"] == engine.MISSING
    assert "excluded as a duplicate" in row["detail"]
    assert "Op_Note.pdf" in row["detail"]


def test_a_document_still_being_processed_does_not_satisfy_a_requirement_yet():
    documents = [_document("Op_Note.pdf", "operative_note", processing_status="processing")]
    checklist = engine.build_checklist(_state(documents))
    assert _row(checklist, "operative_note")["status"] == engine.MISSING
    assert checklist["provisional"] is True


def test_an_open_finding_about_the_document_asks_for_a_person():
    documents = [_document("Consent.pdf", "consent")]
    findings = [
        {
            "id": "f1",
            "rule_id": "R014",
            "code": "SIGNATURE_NOT_DETECTED",
            "severity": "review",
            "status": "open",
            "title": "Patient / guardian signature is not present on Consent.pdf",
            "subject": "signature:abc:patient_guardian",
            "is_active": True,
            "document_ids": ["doc-Consent.pdf"],
        }
    ]
    row = _row(engine.build_checklist(_state(documents), findings), "consent")
    assert row["status"] == engine.REVIEW_REQUIRED
    assert [finding["code"] for finding in row["findings"]] == ["SIGNATURE_NOT_DETECTED"]
    assert "Consent.pdf" in row["detail"]


def test_a_finding_a_person_has_closed_no_longer_asks_for_one():
    documents = [_document("Consent.pdf", "consent")]
    findings = [
        {
            "id": "f1",
            "rule_id": "R014",
            "code": "SIGNATURE_NOT_DETECTED",
            "severity": "review",
            "status": "resolved",
            "title": "…",
            "subject": "signature:abc:patient_guardian",
            "is_active": False,
            "document_ids": ["doc-Consent.pdf"],
        }
    ]
    row = _row(engine.build_checklist(_state(documents), findings), "consent")
    assert row["status"] == engine.FOUND
    assert [finding["status"] for finding in row["findings"]] == ["resolved"], "the history is still shown"


def test_a_missing_document_finding_is_listed_against_the_requirement_it_is_about():
    findings = [
        {
            "id": "f2",
            "rule_id": "R001",
            "code": "MISSING_REQUIRED_DOCUMENT",
            "severity": "critical",
            "status": "open",
            "title": "Operative note is missing",
            "subject": "requirement:operative_note",
            "is_active": True,
            "document_ids": [],
        }
    ]
    checklist = engine.build_checklist(_state([]), findings)
    assert [finding["code"] for finding in _row(checklist, "operative_note")["findings"]] == [
        "MISSING_REQUIRED_DOCUMENT"
    ]
    assert _row(checklist, "post_operative_notes")["findings"] == [], "only the requirement it names"


def test_the_findings_of_a_requirement_are_ordered_the_same_way_every_run():
    """Two findings on one requirement must come out in the same order every time.

    They used to be ordered by the finding's row id, which is a new UUID each time the claim is
    analysed, so the same claim listed the same two findings in a different order from one run to
    the next — in the report, the workbook and the page. The ids below sort the opposite way to the
    order a reader should see, which is the most serious first.
    """
    documents = [_document("Consent.pdf", "consent")]
    quality = {
        "id": "zzzz-last-by-id",
        "rule_id": "R002",
        "code": "LOW_QUALITY_PAGE",
        "severity": "warning",
        "status": "open",
        "title": "Consent.pdf page 1 is hard to read",
        "subject": "page:consent:1",
        "is_active": True,
        "document_ids": ["doc-Consent.pdf"],
    }
    signature = {
        "id": "aaaa-first-by-id",
        "rule_id": "R014",
        "code": "SIGNATURE_NOT_DETECTED",
        "severity": "review",
        "status": "open",
        "title": "Patient / guardian signature is not present on Consent.pdf",
        "subject": "signature:abc:patient_guardian",
        "is_active": True,
        "document_ids": ["doc-Consent.pdf"],
    }
    expected = ["SIGNATURE_NOT_DETECTED", "LOW_QUALITY_PAGE"]
    for order in ([quality, signature], [signature, quality]):
        row = _row(engine.build_checklist(_state(documents), order), "consent")
        assert [finding["code"] for finding in row["findings"]] == expected

    # Swapping the ids must not swap the order: the id is not what the order is about.
    quality["id"], signature["id"] = signature["id"], quality["id"]
    row = _row(engine.build_checklist(_state(documents), [quality, signature]), "consent")
    assert [finding["code"] for finding in row["findings"]] == expected


def test_a_finding_a_person_has_closed_is_listed_after_the_ones_still_open():
    documents = [_document("Consent.pdf", "consent")]
    closed = {
        "id": "a-closed",
        "rule_id": "R002",
        "code": "LOW_QUALITY_PAGE",
        "severity": "critical",
        "status": "resolved",
        "title": "Dealt with",
        "subject": "page:consent:1",
        "is_active": False,
        "document_ids": ["doc-Consent.pdf"],
    }
    still_open = {
        "id": "b-open",
        "rule_id": "R014",
        "code": "SIGNATURE_NOT_DETECTED",
        "severity": "warning",
        "status": "open",
        "title": "Still open",
        "subject": "signature:abc:patient_guardian",
        "is_active": True,
        "document_ids": ["doc-Consent.pdf"],
    }
    row = _row(engine.build_checklist(_state(documents), [closed, still_open]), "consent")
    assert [finding["code"] for finding in row["findings"]] == [
        "SIGNATURE_NOT_DETECTED",
        "LOW_QUALITY_PAGE",
    ], "what is still open comes first, however serious the one that is closed was"


def test_an_implant_requirement_does_not_apply_when_no_implant_is_billed():
    row = _row(engine.build_checklist(_state([])), "implant_invoice")
    assert row["status"] == engine.NOT_APPLICABLE
    assert row["detail"] == "No implant is billed in this claim."


def test_an_implant_requirement_applies_once_an_implant_is_billed():
    state = _state([], bills=[{"bill_type": "implant_invoice", "document_id": "doc-inv"}])
    assert _row(engine.build_checklist(state), "implant_invoice")["status"] == engine.MISSING


def test_local_anaesthesia_does_not_ask_for_an_anaesthesia_chart():
    state = _state([], procedure="cataract_surgery", anaesthesia="Topical anaesthesia")
    row = _row(engine.build_checklist(state), "anaesthesia_record")
    assert row["status"] == engine.NOT_APPLICABLE
    assert "topical" in row["detail"]


def test_an_undocumented_anaesthesia_still_asks_for_the_chart():
    """Nothing said is not the same as nothing given."""
    state = _state([], procedure="cataract_surgery", anaesthesia=None)
    assert _row(engine.build_checklist(state), "anaesthesia_record")["status"] == engine.MISSING


def test_a_procedure_without_a_checklist_says_so_and_names_the_ones_that_have_one():
    state = _state([], procedure="an_operation_with_no_checklist")
    checklist = engine.build_checklist(state)
    assert checklist["available"] is False
    assert checklist["items"] == []
    assert "No checklist is configured" in checklist["note"]
    assert [item["label"] for item in checklist["configured_procedures"]]


def test_no_procedure_named_means_no_checklist_rather_than_a_guess():
    checklist = engine.build_checklist(_state([], procedure=None))
    assert checklist["available"] is False
    assert checklist["procedure"]["key"] is None
    assert "No procedure is named" in checklist["note"]


def test_the_summary_counts_only_required_requirements_as_outstanding():
    documents = [
        _document("Consent.pdf", "consent"),
        _document("Op.pdf", "operative_note"),
        _document("Anaes.pdf", "anaesthesia_record"),
        _document("Discharge.pdf", "discharge_summary"),
        _document("Bill.pdf", "hospital_bill"),
        _document("PreOp.pdf", "pre_operative_assessment"),
        _document("Consultation.pdf", "consultation"),
        _document("PAC.pdf", "anaesthesia_assessment"),
        _document("PostOp.pdf", "post_operative_note"),
        _document("Lab.pdf", "lab_report"),
    ]
    summary = engine.build_checklist(_state(documents))["summary"]
    assert summary["found"] == 10
    assert summary["not_applicable"] == 1, "no implant billed"
    assert summary["missing"] == 2, "nursing record and prescription"
    assert summary["required_outstanding"] == 0, "both of those are supporting documents"
    assert summary["by_severity"] == {"critical": 0, "review": 0, "warning": 0, "info": 0}


def test_the_checklist_is_the_same_whatever_order_the_documents_arrive_in():
    documents = [
        _document("Consent.pdf", "consent"),
        _document("Op.pdf", "operative_note"),
        _document("Bill.pdf", "hospital_bill"),
    ]
    first = engine.build_checklist(_state(documents))
    second = engine.build_checklist(_state(list(reversed(documents))))
    assert first == second


def test_the_checklist_never_uses_accusing_words():
    from tests.ab_support import ACCUSATORY_WORDS

    documents = [_document("Consent.pdf", "consent")]
    text = str(engine.build_checklist(_state(documents))).lower()
    assert [word for word in ACCUSATORY_WORDS if word in text] == []

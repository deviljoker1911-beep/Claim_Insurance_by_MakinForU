"""The same claim, in every state it can be in, told the same way by every format.

A report is the part of this system that leaves the building. If the JSON, the page, the PDF and
the workbook can disagree about whether a person approved a claim, or about how ready it is, then
one of them is wrong in front of a reader who has no way to tell which. These tests walk one claim
through each state its review can be in and hold all four renderings to the same answer.

The state that matters most is the superseded one: a person did approve the claim, and the claim
then changed, so it is not an approved claim. No format may present it as one.
"""

import pytest

from app.reports import excel, html, model, pdf
from tests import factory
from tests.ab_support import CLAIM_FORM, analyse, scenario, upload
from tests.test_reports import pdf_text, report_for, sheet_rows


def squashed(text: str) -> str:
    """Text with its spacing removed, so a sentence the PDF wrapped can still be found in it."""
    return "".join(text.split())

# Every state a claim's review can be read in, and what the report must say about it.
STATES = ("incomplete", "needs_attention", "ready_for_human_review", "approved", "superseded")


def acknowledge_everything(client, claim_id: str) -> None:
    for item in client.get(f"/api/claims/{claim_id}/findings").json()["items"]:
        if item["is_active"] and item["severity"] != "info":
            response = client.post(
                f"/api/findings/{item['id']}/action", json={"action": "acknowledge", "note": "Checked."}
            )
            assert response.status_code == 200, response.text


@pytest.fixture(scope="module")
def claims(client) -> dict[str, str]:
    """One claim per state, each reached the way an operator would reach it."""
    built: dict[str, str] = {}

    # Nothing has been read, so nothing can be said about the documentation.
    empty = client.post("/api/claims", json=CLAIM_FORM)
    assert empty.status_code == 201, empty.text
    built["incomplete"] = empty.json()["id"]

    # Every document present, but the bill does not add up: a finding for a person to attend to.
    off_by_a_bill = {
        **factory.checklist_complete_claim(),
        "06_Hospital_Bill.pdf": factory.hospital_bill(total="60,000.00"),
    }
    built["needs_attention"] = scenario(client, off_by_a_bill).claim_id

    # Complete, findings dealt with: ready for a person to look at, not yet approved.
    ready = scenario(client, factory.checklist_complete_claim()).claim_id
    acknowledge_everything(client, ready)
    built["ready_for_human_review"] = ready

    # The same, approved.
    approved = scenario(client, factory.checklist_complete_claim()).claim_id
    acknowledge_everything(client, approved)
    assert client.post(
        f"/api/claims/{approved}/review/approve", json={"note": "Checked against the hospital file."}
    ).status_code == 200
    built["approved"] = approved

    # Approved, then changed: the approval is on the record and no longer stands for the claim.
    # The document added afterwards agrees with the rest, so the claim is still fully documented:
    # this is the state most easily misread as approved — ready for review, and not approved.
    superseded = scenario(client, factory.checklist_complete_claim()).claim_id
    acknowledge_everything(client, superseded)
    assert client.post(f"/api/claims/{superseded}/review/approve", json={"note": "Checked."}).status_code == 200
    upload(client, superseded, {"20_Later_Lab_Report.pdf": factory.lab_report(sample_id="LAB/2026/118999")})
    analyse(client, superseded)
    built["superseded"] = superseded

    return built


@pytest.fixture(scope="module")
def reports(client, claims) -> dict[str, dict]:
    return {state: report_for(client, claim_id) for state, claim_id in claims.items()}


@pytest.mark.parametrize("state", STATES)
def test_each_claim_is_in_the_state_the_matrix_expects(reports, state):
    """The fixtures really do cover all five states, so the tests below mean something."""
    report = reports[state]
    expected_review = state if state in ("approved", "superseded") else "draft"
    expected_readiness = {
        "incomplete": "incomplete",
        "needs_attention": "needs_attention",
        "ready_for_human_review": "ready_for_human_review",
        "approved": "ready_for_human_review",
        # A claim can be fully documented and still carry an approval that no longer stands.
        "superseded": "ready_for_human_review",
    }[state]
    assert report["review"]["state"] == expected_review
    assert report["readiness"]["status"] == expected_readiness


@pytest.mark.parametrize("state", STATES)
def test_only_an_approved_claim_reads_as_approved_in_any_format(reports, state):
    """"Approved by <operator> on <date>" is a statement about now, and only one state earns it."""
    report = reports[state]
    review = report["review"]
    approval_stamp = f"Approved by {review['approved_by']} on {review['approved_at']}."

    page = html.render(report)
    document = pdf_text(pdf.render(report))
    summary = {row[0]: row[1] if len(row) > 1 else "" for row in sheet_rows(excel.render(report), "Claim Summary")}

    if state == "approved":
        assert review["approved"] is True
        assert review["line"] == approval_stamp
        assert approval_stamp in page
        assert f"Approved by {review['approved_by']}" in document
        assert summary["Review state"] == "approved"
    else:
        assert review["approved"] is False
        assert approval_stamp not in page
        assert f"Approved by {review['approved_by']} on" not in document
        assert summary["Review state"] == ("superseded" if state == "superseded" else "draft")


@pytest.mark.parametrize("state", STATES)
def test_every_format_carries_the_one_review_sentence(reports, state):
    """The page, the PDF and the workbook state the review the same way, because they share it."""
    report = reports[state]
    line = report["review"]["line"]
    assert line and "None" not in line, "no placeholder reaches a reader"

    page = html.render(report)
    document = pdf_text(pdf.render(report))
    summary = {row[0]: row[1] if len(row) > 1 else "" for row in sheet_rows(excel.render(report), "Claim Summary")}

    assert line in page
    assert summary["Human review"] == line
    # The PDF wraps prose across lines, so the spacing is taken out before looking for it.
    assert squashed(line) in squashed(document)


def test_a_superseded_claim_says_so_in_every_format(reports):
    """The case a reader must not get wrong: approved once, and not approved now."""
    report = reports["superseded"]
    review = report["review"]
    assert (review["state"], review["approved"], review["superseded"]) == ("superseded", False, True)
    assert review["approved_by"], "who approved the earlier version is kept, not erased"
    assert review["superseded_at"]

    page = html.render(report)
    document = pdf_text(pdf.render(report))
    summary = {row[0]: row[1] if len(row) > 1 else "" for row in sheet_rows(excel.render(report), "Claim Summary")}

    for text in (page, document):
        assert "no longer stands for it" in text
    assert summary["Review state"] == "superseded"
    assert "no longer stands for it" in summary["Human review"]
    assert summary["Superseded at"]

    decisions = sheet_rows(excel.render(report), "Human Decisions")
    approvals = [row for row in decisions if row and row[0] == "approval"]
    assert [row[2] for row in approvals] == ["superseded"], "the approval on the record reads as superseded"


@pytest.mark.parametrize("state", STATES)
def test_the_readiness_score_is_the_same_number_wherever_it_is_printed(reports, state):
    """One number, four places. A reader comparing two of them must not find a difference."""
    report = reports[state]
    score = report["readiness"]["score"]
    assert report["summary"]["readiness_score"] == score

    page = html.render(report)
    document = pdf_text(pdf.render(report))
    summary = {row[0]: row[1] if len(row) > 1 else "" for row in sheet_rows(excel.render(report), "Claim Summary")}

    assert f"{score}%" in page
    assert f"{score}%" in document
    assert summary["Readiness score"] == str(score)
    assert summary["Readiness status"] == report["readiness"]["status_label"]


@pytest.mark.parametrize("state", STATES)
def test_the_endpoints_serve_what_the_assembly_holds(client, claims, reports, state):
    """The JSON the API serves is the payload the other three formats render."""
    claim_id = claims[state]
    served = client.get(f"/api/claims/{claim_id}/report")
    assert served.status_code == 200, served.text
    body = served.json()
    assert body["review"]["state"] == reports[state]["review"]["state"]
    assert body["review"]["line"] == reports[state]["review"]["line"]
    assert body["readiness"]["score"] == reports[state]["readiness"]["score"]

    for suffix, media_type in (
        ("report.html", "text/html"),
        ("report.pdf", "application/pdf"),
        ("report.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ):
        response = client.get(f"/api/claims/{claim_id}/{suffix}")
        assert response.status_code == 200, response.text
        assert response.headers["content-type"].startswith(media_type)
        assert response.content, f"{suffix} came back empty"


@pytest.mark.parametrize("state", STATES)
def test_a_report_invents_no_approval(reports, state):
    """No rendering may attribute an approval to anyone the claim was not approved by."""
    report = reports[state]
    approvals = [item for item in report["human_decisions"] if item["kind"] == "approval"]
    if state in ("approved", "superseded"):
        assert len(approvals) == 1
        assert approvals[0]["decision"] == state
    else:
        assert approvals == [], "a claim nobody approved reports no approval"
        page = html.render(report)
        assert "human_approval" not in page


def test_the_assembly_is_the_only_place_the_review_sentence_is_written():
    """Each format renders the sentence; none of them composes it.

    Two renderings that each build the same sentence drift apart, and they had: one printed a
    missing score as an em dash and the other as None. The sentence is built once, in the report
    assembly, and this test keeps it there.
    """
    import inspect

    for renderer in (html, pdf, excel):
        source = inspect.getsource(renderer)
        assert "no longer stands for it" not in source, (
            f"{renderer.__name__} composes the review sentence itself; it belongs to the assembly"
        )
    assert "no longer stands for it" in inspect.getsource(model)

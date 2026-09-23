"""The access gate: who gets in, who does not, and what is kept about them.

The demo is meant to be open — anyone who gives a working address may look. So these tests are
mostly about the two things that being open makes dangerous: an endpoint that sends mail to any
address it is handed, and a six-digit secret. And about the one thing being open is for: the list
of people who came, which a demo reset must never wipe.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.access.session import COOKIE_NAME, read_session, session_cookie_value
from app.config import get_settings
from app.db import SessionLocal
from app.models import AccessChallenge, Visitor, utcnow
from tests.conftest import DEMO_CLAIM

CODE = re.compile(r"\b(\d{6})\b")


@pytest.fixture
def gate(client, caplog):
    """Turn the gate on for one test, with a known secret, and clear anyone left behind."""
    settings = get_settings()
    before = (
        settings.access_gate_enabled,
        settings.access_session_secret,
        settings.access_admin_token,
        settings.app_env,
    )
    settings.access_gate_enabled = True
    settings.access_session_secret = type(settings.access_session_secret)("test-secret-not-a-real-one")
    settings.app_env = "development"  # keeps the cookie readable over http in the test client
    with SessionLocal() as session:
        for row in session.scalars(select(AccessChallenge)):
            session.delete(row)
        for row in session.scalars(select(Visitor)):
            session.delete(row)
        session.commit()
    client.cookies.clear()
    yield settings
    (
        settings.access_gate_enabled,
        settings.access_session_secret,
        settings.access_admin_token,
        settings.app_env,
    ) = before
    client.cookies.clear()


def sent_code(caplog) -> str:
    """The code the server logged, which is where it goes with no mail server configured."""
    found = CODE.search("\n".join(record.getMessage() for record in caplog.records))
    assert found, "no access code was logged"
    return found.group(1)


def ask(client, caplog, email: str = "someone@example.com") -> str:
    caplog.clear()
    with caplog.at_level("WARNING", logger="claimai.access"):
        response = client.post("/api/access/request", json={"email": email})
    assert response.status_code == 200, response.text
    assert response.json()["delivery"] == "logged"
    return sent_code(caplog)


# --- with the gate off, nothing changes ---------------------------------------------------


def test_the_gate_is_off_unless_a_deployment_turns_it_on(client):
    """Local development, the test suite and an offline demo never meet it."""
    session = client.get("/api/access/session")
    assert session.status_code == 200
    assert session.json()["gate_enabled"] is False
    assert session.json()["verified"] is True
    assert client.get("/api/claims").status_code == 200


# --- with it on ---------------------------------------------------------------------------


def test_the_api_is_closed_until_an_address_is_proved(client, gate):
    """The gate guards the API, not the page: skipping the screen gets you nothing."""
    for path in ("/api/claims", "/api/dashboard", "/api/audit"):
        response = client.get(path)
        assert response.status_code == 401, path
        assert response.json()["detail"]["reason"] == "access_required"

    # Creating a claim and uploading to it are the endpoints that would cost a stranger nothing
    # and cost the host real work.
    assert client.post("/api/claims", json=DEMO_CLAIM).status_code == 401
    assert client.post("/api/claims/whatever/documents", files=[]).status_code == 401


def test_what_still_answers_so_the_gate_can_be_shown_at_all(client, gate):
    """The health probe a load balancer calls, and the gate's own endpoints."""
    assert client.get("/api/health").status_code in (200, 503)
    assert client.get("/api/access/session").status_code == 200


def test_a_code_lets_someone_in_and_the_session_carries_the_address(client, gate, caplog):
    code = ask(client, caplog, "visitor@example.com")

    verified = client.post("/api/access/verify", json={"email": "visitor@example.com", "code": code})
    assert verified.status_code == 200, verified.text
    assert verified.json() == {
        "gate_enabled": True,
        "verified": True,
        "email": "visitor@example.com",
        "delivery": "logged",
    }

    assert client.get("/api/claims").status_code == 200
    assert client.get("/api/access/session").json()["email"] == "visitor@example.com"


def test_the_address_is_recorded_whether_or_not_the_code_is_used(client, gate, caplog):
    """The list is the point: someone who asked and never came back is still a lead."""
    ask(client, caplog, "asked.only@example.com")
    code = ask(client, caplog, "came.in@example.com")
    client.post("/api/access/verify", json={"email": "came.in@example.com", "code": code})

    with SessionLocal() as session:
        rows = {row.email: row for row in session.scalars(select(Visitor))}
    assert set(rows) == {"asked.only@example.com", "came.in@example.com"}
    assert rows["asked.only@example.com"].verified_at is None
    assert rows["came.in@example.com"].verified_at is not None


def test_an_address_is_stored_one_way_however_it_is_typed(client, gate, caplog):
    ask(client, caplog, "  Mixed.Case@Example.COM  ")
    with SessionLocal() as session:
        assert [row.email for row in session.scalars(select(Visitor))] == ["mixed.case@example.com"]


@pytest.mark.parametrize("typed", ["", "not-an-address", "no@domain", "two words@example.com", "a@b"])
def test_what_cannot_be_an_address_is_refused_before_any_mail_is_attempted(client, gate, typed):
    assert client.post("/api/access/request", json={"email": typed}).status_code == 422


# --- the six-digit secret -----------------------------------------------------------------


def test_a_wrong_code_is_refused_and_says_how_many_tries_are_left(client, gate, caplog):
    ask(client, caplog, "wrong@example.com")
    response = client.post("/api/access/verify", json={"email": "wrong@example.com", "code": "000000"})
    assert response.status_code == 401
    assert "4" in response.json()["detail"]["message"]
    assert client.get("/api/claims").status_code == 401


def test_a_code_is_worth_a_few_guesses_and_then_it_is_spent(client, gate, caplog):
    """Six digits is a million, which is plenty — but only if guessing is not free."""
    code = ask(client, caplog, "guesser@example.com")
    for _ in range(get_settings().access_code_max_attempts):
        client.post("/api/access/verify", json={"email": "guesser@example.com", "code": "000000"})

    # Even the right code no longer works: the challenge is spent, not the guess.
    response = client.post("/api/access/verify", json={"email": "guesser@example.com", "code": code})
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "too_many_attempts"
    assert client.get("/api/claims").status_code == 401


def test_a_code_stops_working_when_it_runs_out_of_time(client, gate, caplog):
    code = ask(client, caplog, "slow@example.com")
    with SessionLocal() as session:
        challenge = session.scalars(select(AccessChallenge).where(AccessChallenge.email == "slow@example.com")).first()
        challenge.expires_at = utcnow() - timedelta(seconds=1)
        session.commit()

    response = client.post("/api/access/verify", json={"email": "slow@example.com", "code": code})
    assert response.status_code == 401
    assert response.json()["detail"]["reason"] == "expired"


def test_asking_again_retires_the_code_that_was_sent_before(client, gate, caplog):
    first = ask(client, caplog, "again@example.com")
    second = ask(client, caplog, "again@example.com")
    assert first != second

    assert client.post("/api/access/verify", json={"email": "again@example.com", "code": first}).status_code == 401
    assert client.post("/api/access/verify", json={"email": "again@example.com", "code": second}).status_code == 200


def test_a_code_issued_for_one_address_does_not_open_another(client, gate, caplog):
    code = ask(client, caplog, "owner@example.com")
    ask(client, caplog, "borrower@example.com")
    response = client.post("/api/access/verify", json={"email": "borrower@example.com", "code": code})
    assert response.status_code == 401


def test_the_code_itself_is_never_stored(client, gate, caplog):
    """The table cannot hand anyone a way in, even to someone who can read it."""
    code = ask(client, caplog, "hashed@example.com")
    with SessionLocal() as session:
        stored = session.scalars(select(AccessChallenge).where(AccessChallenge.email == "hashed@example.com")).first()
        assert code not in stored.code_hash
        assert len(stored.code_hash) == 64


# --- sending mail on someone else's behalf ------------------------------------------------


def test_one_address_may_only_be_mailed_so_many_times_an_hour(client, gate, caplog):
    """Otherwise this endpoint is a way to send someone a message every second."""
    limit = get_settings().access_requests_per_email_per_hour
    for _ in range(limit):
        assert client.post("/api/access/request", json={"email": "flood@example.com"}).status_code == 200

    response = client.post("/api/access/request", json={"email": "flood@example.com"})
    assert response.status_code == 429
    assert response.json()["detail"]["reason"] == "too_many_for_email"


def test_one_caller_may_only_ask_so_many_times_an_hour(client, gate):
    """And otherwise it is a way to send a great many people a message."""
    settings = get_settings()
    before = settings.access_requests_per_ip_per_hour
    settings.access_requests_per_ip_per_hour = 3
    try:
        for index in range(3):
            assert client.post("/api/access/request", json={"email": f"caller{index}@example.com"}).status_code == 200
        response = client.post("/api/access/request", json={"email": "caller99@example.com"})
        assert response.status_code == 429
        assert response.json()["detail"]["reason"] == "too_many_for_caller"
    finally:
        settings.access_requests_per_ip_per_hour = before


# --- the cookie ---------------------------------------------------------------------------


def test_a_session_cannot_be_written_by_the_browser_that_holds_it(client, gate, caplog):
    code = ask(client, caplog, "real@example.com")
    client.post("/api/access/verify", json={"email": "real@example.com", "code": code})
    good = client.cookies.get(COOKIE_NAME)

    for forged in (
        good[:-1] + ("a" if good[-1] != "a" else "b"),  # signature edited
        good.split(".")[0] + ".not-a-signature",
        session_cookie_value("real@example.com", now=0),  # long expired
        "",
        "junk",
    ):
        client.cookies.set(COOKIE_NAME, forged)
        assert client.get("/api/claims").status_code == 401, forged[:24]

    client.cookies.set(COOKIE_NAME, good)
    assert client.get("/api/claims").status_code == 200


def test_a_session_signed_with_another_secret_is_not_a_session(gate):
    settings = get_settings()
    minted = session_cookie_value("elsewhere@example.com")
    settings.access_session_secret = type(settings.access_session_secret)("a-different-secret")
    assert read_session(minted) is None


def test_signing_out_gives_the_session_back(client, gate, caplog):
    code = ask(client, caplog, "leaving@example.com")
    client.post("/api/access/verify", json={"email": "leaving@example.com", "code": code})
    assert client.get("/api/claims").status_code == 200

    assert client.post("/api/access/signout").status_code == 200
    assert client.get("/api/claims").status_code == 401


# --- the list of people who came ----------------------------------------------------------


def test_the_visitor_list_is_not_served_without_a_token_configured(client, gate, caplog):
    ask(client, caplog)
    assert client.get("/api/access/visitors").status_code == 404


def test_the_visitor_list_needs_the_token_and_then_gives_the_addresses(client, gate, caplog):
    settings = get_settings()
    settings.access_admin_token = type(settings.access_admin_token)("admin-token-for-this-test")
    ask(client, caplog, "lead@example.com")

    assert client.get("/api/access/visitors").status_code == 401
    assert client.get("/api/access/visitors", headers={"X-Admin-Token": "wrong"}).status_code == 401

    response = client.get("/api/access/visitors", headers={"X-Admin-Token": "admin-token-for-this-test"})
    assert response.status_code == 200
    assert [row["email"] for row in response.json()] == ["lead@example.com"]
    assert response.json()[0]["verified"] is False
    assert response.json()[0]["requests"] == 1


def test_a_demo_reset_clears_the_claims_and_keeps_the_people(client, gate, caplog):
    """The claims are demo data. The people who asked to see them are not."""
    code = ask(client, caplog, "kept@example.com")
    client.post("/api/access/verify", json={"email": "kept@example.com", "code": code})
    assert client.post("/api/claims", json=DEMO_CLAIM).status_code == 201

    assert client.post("/api/demo/reset", json={"confirm": True}).status_code == 200

    assert client.get("/api/claims").json() == []
    with SessionLocal() as session:
        kept = session.scalars(select(Visitor).where(Visitor.email == "kept@example.com")).first()
        assert kept is not None and kept.verified_at is not None
    # And the session survives it, so a reset mid-demo does not lock the presenter out.
    assert client.get("/api/access/session").json()["verified"] is True


def test_the_session_cookie_is_marked_secure_only_when_the_visitor_is_on_https(client, gate, caplog):
    """A Secure cookie on a plain-http deployment is taken by the browser and never sent back.

    The gate would then ask for a code on every page, forever, and the logs would show a
    successful verification each time. The proxy terminates TLS, so what the visitor is actually
    on arrives in the forwarded header rather than in the scheme this process sees.
    """
    code = ask(client, caplog, "plain@example.com")
    plain = client.post("/api/access/verify", json={"email": "plain@example.com", "code": code})
    assert "secure" not in plain.headers["set-cookie"].lower()

    code = ask(client, caplog, "tls@example.com")
    behind_proxy = client.post(
        "/api/access/verify",
        json={"email": "tls@example.com", "code": code},
        headers={"X-Forwarded-Proto": "https"},
    )
    assert "secure" in behind_proxy.headers["set-cookie"].lower()


def test_the_code_email_carries_the_headers_a_spam_filter_looks_for():
    """A message with no Date and no Message-ID is scored against before anyone reads it.

    Both are required by RFC 5322 and Python supplies neither. The first codes this sent were
    accepted by the mail server and filed as junk by the recipient, which looks from the sending
    end exactly like success.
    """
    from email.utils import parseaddr

    from app.access.mail import build_message

    message = build_message("someone@example.com", "123456", sender="ClaimAI <no-reply@example.com>")
    assert message["Date"], "no Date header"
    assert message["Message-ID"], "no Message-ID header"
    assert message["Auto-Submitted"] == "auto-generated"
    # The id is bound to the sending domain rather than to whatever host happens to run this.
    assert message["Message-ID"].rstrip(">").endswith("example.com")
    assert parseaddr(message["From"])[1] == "no-reply@example.com"
    assert "123456" in message.get_content()

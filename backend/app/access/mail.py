"""Getting the code to the address.

With SMTP configured the code is mailed. With nothing configured it is written to the application
log and the API says so, which keeps the gate usable offline, in tests, and on a server whose mail
credentials have not been wired up yet. What it never does is quietly report success for a message
that was never sent.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import get_settings

logger = logging.getLogger("claimai.access")

LOGGED = "logged"
MAILED = "mailed"


def delivery_mode() -> str:
    """Whether a code will be mailed or only written to the log."""
    return MAILED if get_settings().smtp_host else LOGGED


def _body(code: str, minutes: int) -> tuple[str, str]:
    subject = f"{code} is your ClaimAI access code"
    text = (
        f"Your access code for the ClaimAI demo is {code}.\n\n"
        f"It is good for {minutes} minutes and can be used once.\n\n"
        "If you did not ask for this, nothing has happened and you can ignore this message.\n\n"
        "ClaimAI — claim pre-submission validation, by MakinForU.\n"
        "This demo holds synthetic data only. Do not upload real patient records.\n"
    )
    return subject, text


def deliver_code(email: str, code: str) -> str:
    """Send the code, or log it when no mail server is configured. Returns the mode used."""
    settings = get_settings()
    subject, text = _body(code, settings.access_code_ttl_minutes)

    if not settings.smtp_host:
        # Not a fallback that hides a failure: the API tells the caller the code was logged.
        logger.warning("No SMTP host configured — access code for %s is %s", email, code)
        return LOGGED

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.smtp_from or settings.smtp_username
    message["To"] = email
    message.set_content(text)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
        if settings.smtp_starttls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password.get_secret_value())
        server.send_message(message)
    logger.info("Access code sent to %s", email)
    return MAILED

"""Sending one-time login codes by email.

In order of preference:
1. Brevo email API (SAHYOG_BREVO_API_KEY) — HTTPS, works on Render's free plan.
2. SMTP (SAHYOG_SMTP_HOST etc.) — e.g. Gmail with an App Password, on hosts that allow SMTP.
3. Neither set: in development the code is printed in the server log; in production
   only if SAHYOG_LOG_LOGIN_CODES=true, otherwise sending fails.
"""

import json
import logging
import smtplib
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import settings

log = logging.getLogger("sahyogcare.email")

SUBJECT = "Your SahyogCare login code"
BREVO_URL = "https://api.brevo.com/v3/smtp/email"


class EmailNotConfigured(Exception):
    pass


def _body(code: str) -> str:
    return (
        f"Your SahyogCare login code is {code}.\n\n"
        "It expires in 5 minutes. If you did not ask for this code, ignore this email."
    )


def _send_brevo(to: str, code: str) -> None:
    name, address = parseaddr(settings.smtp_from)
    payload = {
        "sender": {"name": name or "SahyogCare", "email": address},
        "to": [{"email": to}],
        "subject": SUBJECT,
        "textContent": _body(code),
    }
    request = urllib.request.Request(
        BREVO_URL,
        data=json.dumps(payload).encode(),
        headers={"api-key": settings.brevo_api_key, "content-type": "application/json", "accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=15) as response:  # raises on 4xx/5xx
        if response.status >= 300:
            raise RuntimeError(f"Brevo answered {response.status}")


def _send_smtp(to: str, code: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = SUBJECT
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(_body(code))
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def send_login_code(to: str, code: str) -> None:
    if settings.brevo_api_key:
        _send_brevo(to, code)
        return
    if settings.smtp_host:
        _send_smtp(to, code)
        return
    if not settings.is_development and not settings.log_login_codes:
        raise EmailNotConfigured("Email settings are required outside development.")
    log.warning("LOGIN CODE (no email service configured) for %s: %s", to, code)

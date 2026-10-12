"""Sending one-time codes by email.

Development: with no SMTP settings, the code is printed in the server log.
Production: set SAHYOG_SMTP_HOST / _PORT / _USER / _PASSWORD / _FROM.
"""

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

log = logging.getLogger("sahyogcare.email")


class EmailNotConfigured(Exception):
    pass


def send_login_code(to: str, code: str) -> None:
    if not settings.smtp_host:
        if not settings.is_development and not settings.log_login_codes:
            raise EmailNotConfigured("SMTP settings are required outside development.")
        log.warning("LOGIN CODE (no SMTP configured) for %s: %s", to, code)
        return

    msg = EmailMessage()
    msg["Subject"] = "Your SahyogCare login code"
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(
        f"Your SahyogCare login code is {code}.\n\n"
        "It expires in 5 minutes. If you did not ask for this code, ignore this email."
    )
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)

"""Messages to people outside the app: SMS and email, in the patient's language.

SMS goes through an Indian SMS service (SAHYOG_SMS_API_KEY, Fast2SMS by default).
Email goes through the same service as login codes (Brevo or SMTP). Without
either, the message is written to the server log so nothing fails.

Sending never raises: a failed message must not stop a referral being saved.
"""

import json
import logging
import smtplib
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage
from email.utils import parseaddr

from app.config import settings

log = logging.getLogger("sahyogcare.messaging")

FAST2SMS_URL = "https://www.fast2sms.com/dev/bulkV2"
BREVO_URL = "https://api.brevo.com/v3/smtp/email"

# Kept for tests: every message "sent", in order.
outbox: list[dict] = []


def sms_enabled() -> bool:
    return bool(settings.sms_api_key)


def email_enabled() -> bool:
    return bool(settings.brevo_api_key or settings.smtp_host)


def _post(url: str, data: bytes, headers: dict[str, str]) -> bytes:
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:  # raises on 4xx/5xx
            if response.status >= 300:
                raise RuntimeError(f"{url} answered {response.status}")
            return response.read()
    except urllib.error.HTTPError as exc:
        # Keep the service's own reason (e.g. "invalid authentication") for the log.
        raise RuntimeError(f"{url} answered {exc.code}: {exc.read()[:300]!r}") from exc


class SmsRefused(RuntimeError):
    """The SMS service answered but did not send (no balance, route not allowed, bad key...)."""


def _send_sms(phone: str, text: str) -> None:
    # Fast2SMS "quick" route: unicode text (Bengali/Hindi) to a 10-digit Indian number.
    body = urllib.parse.urlencode({"route": "q", "message": text, "language": "unicode", "numbers": phone}).encode()
    raw = _post(FAST2SMS_URL, body, {"authorization": settings.sms_api_key,
                                      "content-type": "application/x-www-form-urlencoded"})
    # Fast2SMS answers HTTP 200 even when it refuses, with {"return": false, "message": "..."}:
    # e.g. a new account must recharge before the API route works. Treat that as a failure.
    try:
        answer = json.loads(raw or b"{}")
    except ValueError:
        answer = {}
    if answer.get("return") is False:
        reason = answer.get("message")
        if isinstance(reason, list):
            reason = " ".join(map(str, reason))
        log.error("SMS service refused to send: %s", reason)
        raise SmsRefused(str(reason or "SMS service refused the message"))


def _send_email(to: str, subject: str, text: str) -> None:
    if settings.brevo_api_key:
        name, address = parseaddr(settings.smtp_from)
        payload = {"sender": {"name": name or "SahyogCare", "email": address}, "to": [{"email": to}],
                   "subject": subject, "textContent": text}
        _post(BREVO_URL, json.dumps(payload).encode(),
              {"api-key": settings.brevo_api_key, "content-type": "application/json", "accept": "application/json"})
        return
    msg = EmailMessage()
    msg["Subject"], msg["From"], msg["To"] = subject, settings.smtp_from, to
    msg.set_content(text)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(msg)


def send(*, phone: str | None = None, email: str | None = None, subject: str, text: str) -> str:
    """Send by SMS when possible, otherwise by email. Returns the channel used: SMS, EMAIL or NONE."""
    channel = "NONE"
    try:
        if phone and sms_enabled():
            _send_sms(phone, text)
            channel = "SMS"
        elif email and email_enabled():
            _send_email(email, subject, text)
            channel = "EMAIL"
        else:
            log.info("Message not sent (no SMS key / no email address): %s", subject)
    except Exception:  # noqa: BLE001 - a message must never break the request
        log.exception("Could not send message: %s", subject)
        channel = "FAILED"
    outbox.append({"phone": phone, "email": email, "subject": subject, "text": text, "channel": channel})
    return channel


def send_both(*, phone: str | None, email: str | None, subject: str, text: str) -> list[str]:
    """For urgent messages (e.g. the ASHA after a night emergency): SMS and email, whichever exist."""
    used = []
    if phone and sms_enabled():
        used.append(send(phone=phone, subject=subject, text=text))
    if email:
        used.append(send(email=email, subject=subject, text=text))
    return used or [send(subject=subject, text=text)]


def send_login_code_sms(phone: str, code: str) -> None:
    """Login code by SMS; raises when it cannot be sent (the caller shows an error)."""
    text = f"SahyogCare login code: {code}. Valid 5 minutes. Do not share it."
    if not sms_enabled():
        if settings.is_development or settings.log_login_codes:
            log.warning("LOGIN CODE (no SMS service configured) for %s: %s", phone, code)
            outbox.append({"phone": phone, "subject": "login", "text": text, "channel": "LOG"})
            return
        raise RuntimeError("SMS is not configured")
    _send_sms(phone, text)


def check_sms() -> str:
    """For the health page: off (no key) or on. Never shows the key."""
    return "on" if sms_enabled() else ("log-only" if settings.log_login_codes else "off")


# ---------- Message texts (English, Bengali, Hindi) ----------

TEXTS: dict[str, dict[str, str]] = {
    "dose": {
        "en": "SahyogCare reminder for {name}: time for your medicine ({slot}): {items}.",
        "bn": "সহযোগকেয়ার: {name}, এখন ওষুধ খাওয়ার সময় ({slot}): {items}।",
        "hi": "सहयोगकेयर: {name}, दवा लेने का समय ({slot}): {items}।",
    },
    "accepted": {
        "en": "SahyogCare: {hospital} has accepted {name}'s referral {code}. A bed is being kept.",
        "bn": "সহযোগকেয়ার: {hospital} {name}-এর রেফারাল {code} গ্রহণ করেছে। বেড রাখা হচ্ছে।",
        "hi": "सहयोगकेयर: {hospital} ने {name} का रेफ़रल {code} स्वीकार किया। बेड रखा जा रहा है।",
    },
    "ambulance": {
        "en": "SahyogCare: ambulance {vehicle} is coming for {name} in about {eta} min. Driver: {driver}.",
        "bn": "সহযোগকেয়ার: {name}-এর জন্য অ্যাম্বুলেন্স {vehicle} প্রায় {eta} মিনিটে আসছে। চালক: {driver}।",
        "hi": "सहयोगकेयर: {name} के लिए एम्बुलेंस {vehicle} लगभग {eta} मिनट में आ रही है। ड्राइवर: {driver}।",
    },
    "emergency_patient": {
        "en": "SahyogCare: emergency booked at {hospital} ({phone}). Code {code}. Call 108 for the ambulance.",
        "bn": "সহযোগকেয়ার: {hospital}-এ জরুরি বুকিং হয়েছে ({phone})। কোড {code}। অ্যাম্বুলেন্সের জন্য 108-এ ফোন করুন।",
        "hi": "सहयोगकेयर: {hospital} में आपातकालीन बुकिंग हुई ({phone})। कोड {code}। एम्बुलेंस के लिए 108 पर कॉल करें।",
    },
}
SLOT_NAMES = {
    "en": {"MORNING": "morning", "NOON": "afternoon", "EVENING": "evening", "NIGHT": "night"},
    "bn": {"MORNING": "সকাল", "NOON": "দুপুর", "EVENING": "সন্ধ্যা", "NIGHT": "রাত"},
    "hi": {"MORNING": "सुबह", "NOON": "दोपहर", "EVENING": "शाम", "NIGHT": "रात"},
}
FOOD_WORDS = {
    "en": {"BEFORE": "before food", "AFTER": "after food", "WITH": "with food"},
    "bn": {"BEFORE": "খাবারের আগে", "AFTER": "খাবারের পরে", "WITH": "খাবারের সাথে"},
    "hi": {"BEFORE": "खाने से पहले", "AFTER": "खाने के बाद", "WITH": "खाने के साथ"},
}


def text(kind: str, language: str, **values) -> str:
    lang = language if language in TEXTS[kind] else "en"
    return TEXTS[kind][lang].format(**values)

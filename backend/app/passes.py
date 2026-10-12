"""Signed referral passes (the QR code the patient carries).

Format:  SC1.<payload>.<signature>   (both base64url, no padding)
Payload: {"c": code, "f": destination facility id, "t": triage, "i": issued-at (unix seconds)}

The signature is an HMAC of the payload with the server secret, so a pass
cannot be forged or edited. A facility can check it later even if the scan
happened offline.
"""

import base64
import hashlib
import hmac
import json

from app.config import settings
from app.errors import ApiError
from app.models import Referral
from app.timeutil import as_utc

PREFIX = "SC1"


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _sign(payload: bytes) -> bytes:
    return hmac.new(settings.secret_key.encode(), b"pass:" + payload, hashlib.sha256).digest()


def make_pass(referral: Referral) -> str:
    payload = json.dumps(
        {
            "c": referral.code,
            "f": referral.destination_facility_id,
            "t": referral.triage,
            "i": int(as_utc(referral.created_at).timestamp()),
        },
        separators=(",", ":"),
    ).encode()
    return f"{PREFIX}.{_b64(payload)}.{_b64(_sign(payload))}"


def read_pass(qr_text: str) -> dict:
    """Return the payload of a genuine pass, or raise PASS_INVALID."""
    invalid = ApiError(400, "PASS_INVALID", "This referral pass is not valid.")
    try:
        prefix, payload_b64, sig_b64 = qr_text.strip().split(".")
        if prefix != PREFIX:
            raise invalid
        payload = _unb64(payload_b64)
        if not hmac.compare_digest(_sign(payload), _unb64(sig_b64)):
            raise invalid
        data = json.loads(payload)
        if not isinstance(data, dict) or not {"c", "f"} <= data.keys():
            raise invalid
        return data
    except ApiError:
        raise
    except Exception as exc:  # malformed text
        raise invalid from exc

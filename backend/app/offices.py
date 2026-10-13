"""District office passphrases, built into the app.

Every area SahyogCare serves has one permanent passphrase that belongs to its
district office (the office, not a person, so it survives a change of officer).
Whoever signs in with their own email, picks the area and enters it becomes that
area's coordinator at once. Nothing has to be set on the server.

Only a salted, slow hash of each passphrase is kept here, so reading this file or
the GitHub repository does not reveal any passphrase: each one is 80 random bits,
far too many to guess. The passphrases themselves are handed to the offices
privately and are never written in the code.

New area:  python -m app.offices new "Kalyani"
It prints the new passphrase (give it only to that office) and the line to add to
OFFICES below. The area then appears in the app by itself; no server setting needed.
Leaked passphrase: run the same command for that area and replace its line; the old
passphrase stops working as soon as the change is deployed.
"""

import hashlib
import hmac
import re
import secrets
import sys

ITERATIONS = 300_000
# No 0/O or 1/I, so a passphrase is easy to read out and type.
ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"

OFFICES: dict[str, str] = {
    # area: "pbkdf2_sha256$iterations$salt$hash"
    "Nadia": "pbkdf2_sha256$300000$52f89cff2ea2fe19b81aa7d1eeb7e3d9$e6b8bb7a655e4893f9258b556f80168a278d85880529c7eff86a8b57a3c47300",
    "Naihati": "pbkdf2_sha256$300000$207a0eb341e34672cff2b1486ee05cb4$5da8ca9ed54024e1c67ee9984504d5b5134b3bdd14ed2464082cb73fe9e54d57",
}


def normalise(passphrase: str) -> str:
    """Case, spaces and dashes don't matter when typing a passphrase."""
    return re.sub(r"[^A-Z0-9]", "", passphrase.upper())


def hash_passphrase(passphrase: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", normalise(passphrase).encode(), bytes.fromhex(salt), ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt}${digest.hex()}"


def matches(passphrase: str, stored: str) -> bool:
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", normalise(passphrase).encode(), bytes.fromhex(salt), int(iterations))
    except ValueError:
        return False
    return hmac.compare_digest(digest.hex(), expected)


def stored_hash(area: str) -> str | None:
    return next((h for name, h in OFFICES.items() if name.lower() == area.lower()), None)


def new_passphrase(area: str) -> str:
    prefix = (normalise(area)[:3] or "OFC")
    groups = ["".join(secrets.choice(ALPHABET) for _ in range(4)) for _ in range(4)]
    return "-".join([prefix, *groups])


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "new":
        sys.exit('Usage: python -m app.offices new "Area name"')
    area = sys.argv[2].strip()
    phrase = new_passphrase(area)
    print(f"Passphrase for the {area} district office (give it only to them):\n\n    {phrase}\n")
    print(f"Add this line to OFFICES in backend/app/offices.py:\n\n    {area!r}: {hash_passphrase(phrase)!r},")

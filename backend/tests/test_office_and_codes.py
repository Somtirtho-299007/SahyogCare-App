"""The district office's own door, and every approved person's personal code."""

from sqlalchemy import select

from app import staffcode
from app.models import AuditLog, User
from test_referrals import API, post
from test_signup import sign_up


def otp_login(client, who):
    """Email code step. Returns the JSON answer (tokens, or code_required + code_token)."""
    code = client.post(f"{API}/auth/otp/request", json={"email": who}).json()["dev_code"]
    return client.post(f"{API}/auth/otp/verify", json={"email": who, "code": code}).json()


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def approved_asha(client, auth, email="mina.asha@gmail.com"):
    """Sign up, ask to join, district office approves. Returns (headers, new personal code)."""
    me, _ = sign_up(client, email)
    req = post(client, "/access-requests", me, {"role": "WORKER", "name": "Mina", "district": "Nadia"}).json()
    post(client, f"/access-requests/{req['id']}/approve", auth("COORDINATOR"))
    shown = client.get(f"{API}/me", headers=me).json()
    return me, shown["new_code"]


# ---------- personal codes ----------


def test_approval_shows_a_personal_code_then_every_login_needs_it(client, db, auth):
    me, code = approved_asha(client, auth)
    assert code and len(staffcode.normalise(code)) == 8
    # Shown on her own dashboard until she confirms she wrote it down; then never again.
    assert client.get(f"{API}/me", headers=me).json()["new_code"] == code
    assert post(client, "/me/code-seen", me).json()["new_code"] is None
    user = db.scalar(select(User).where(User.email == "mina.asha@gmail.com"))
    db.refresh(user)
    assert user.pending_code is None and user.code_hash and code not in (user.code_hash or "")

    # Next login: email code first, then she must type her own code.
    step = otp_login(client, "mina.asha@gmail.com")
    assert step["code_required"] and step["access_token"] is None
    wrong = client.post(f"{API}/auth/code", json={"code_token": step["code_token"], "code": "AAAA-BBBB"})
    assert wrong.status_code == 400 and wrong.json()["error"]["code"] == "CODE_INVALID"
    ok = client.post(f"{API}/auth/code", json={"code_token": step["code_token"], "code": code.lower().replace("-", " ")})
    assert ok.status_code == 200 and ok.json()["user"]["role"] == "WORKER" and ok.json()["access_token"]
    # The code-step token alone opens nothing.
    assert client.get(f"{API}/referrals", headers=bearer(step["code_token"])).status_code == 401


def test_codes_are_unique_and_only_work_for_their_owner(client, db, auth):
    me_a, code_a = approved_asha(client, auth, "a.asha@gmail.com")
    me_b, code_b = approved_asha(client, auth, "b.asha@gmail.com")
    assert code_a != code_b
    post(client, "/me/code-seen", me_a)
    post(client, "/me/code-seen", me_b)
    step_b = otp_login(client, "b.asha@gmail.com")
    r = client.post(f"{API}/auth/code", json={"code_token": step_b["code_token"], "code": code_a})
    assert r.status_code == 400  # A's code never opens B's account
    hashes = [u.code_hash for u in db.scalars(select(User).where(User.code_hash.is_not(None)))]
    assert len(hashes) == len(set(hashes))


def test_guessing_a_personal_code_is_stopped(client, db, auth):
    me, code = approved_asha(client, auth)
    post(client, "/me/code-seen", me)
    step = otp_login(client, "mina.asha@gmail.com")
    answers = [client.post(f"{API}/auth/code", json={"code_token": step["code_token"], "code": f"GUES-S00{i}"}).status_code
               for i in range(6)]
    assert answers[:5] == [400] * 5 and answers[5] == 429
    assert db.scalar(select(AuditLog.id).where(AuditLog.action == "PERSONAL_CODE_WRONG"))


def test_district_office_resets_a_forgotten_code_and_can_switch_people_off(client, db, auth):
    me, old = approved_asha(client, auth)
    post(client, "/me/code-seen", me)
    coord = auth("COORDINATOR")
    uid = client.get(f"{API}/me", headers=me).json()["id"]
    listed = next(u for u in client.get(f"{API}/users", headers=coord).json() if u["id"] == uid)
    assert listed["has_code"] and "new_code" not in listed and "pending_code" not in listed
    assert post(client, f"/users/{uid}/reset-code", coord).json()["has_code"] is False

    # Next login: straight in (no old code), and a new code is shown on her dashboard.
    again = otp_login(client, "mina.asha@gmail.com")
    assert not again["code_required"] and again["new_code"] and again["new_code"] != old

    # Switched off: no login code is sent at all.
    client.patch(f"{API}/users/{uid}", headers=coord, json={"is_active": False})
    r = client.post(f"{API}/auth/otp/request", json={"email": "mina.asha@gmail.com"}).json()
    assert r.get("dev_code") is None
    # Another district cannot reset her code.
    from test_referrals import new_user

    naihati = new_user(db, "do.naihati@sahyogcare.test", "COORDINATOR", district="Naihati")
    assert post(client, f"/users/{uid}/reset-code", naihati).status_code == 404


def test_group_invite_codes_are_gone_and_offices_do_not_ask(client, db, auth):
    me, _ = sign_up(client, "someone@gmail.com")
    assert post(client, "/invite-codes/redeem", me, {"code": "AS-NAD-ABCDEFGH", "name": "X"}).status_code == 404
    assert post(client, "/invite-codes", auth("COORDINATOR"), {"role": "WORKER"}).status_code == 404
    r = post(client, "/access-requests", me, {"role": "COORDINATOR", "name": "X", "district": "Nadia"})
    assert r.status_code == 422


# ---------- district office passphrase ----------


def test_office_enters_with_its_passphrase(client, db, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "office_passphrases", "Naihati:naihati_do_4821, Nadia:nadia_do_9930")
    me, user = sign_up(client, "do.naihati@gmail.com")
    wrong = post(client, "/office/join", me, {"district": "Naihati", "name": "DO", "passphrase": "nadia_do_9930"})
    assert wrong.json()["error"]["code"] == "PASSPHRASE_INVALID"
    r = post(client, "/office/join", me, {"district": "naihati", "name": "Naihati DO",
                                                  "passphrase": "naihati_do_4821"})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "COORDINATOR" and r.json()["district"] == "Naihati" and r.json()["approved"]
    # The office then gets its own personal code too.
    assert client.get(f"{API}/me", headers=me).json()["new_code"]
    names = [f["name"] for f in client.get(f"{API}/facilities", headers=me).json()]
    assert names == ["Naihati State General Hospital"]


def test_office_passphrase_needs_configuring_and_limits_guessing(client, db, auth, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "office_passphrases", "")
    me, _ = sign_up(client, "guess@gmail.com")
    body = {"district": "Nadia", "name": "X", "passphrase": "anything"}
    assert post(client, "/office/join", me, body).json()["error"]["code"] == "PASSPHRASE_INVALID"
    codes = [post(client, "/office/join", me, {**body, "passphrase": f"try{i}"}).status_code for i in range(5)]
    assert codes[-1] == 429


def test_built_in_office_passphrase_needs_no_server_setting(client, db, auth, monkeypatch):
    from app import offices
    from app.config import settings

    phrase = offices.new_passphrase("Kalyani")
    monkeypatch.setattr(settings, "office_passphrases", "")
    monkeypatch.setattr(offices, "OFFICES", {**offices.OFFICES, "Kalyani": offices.hash_passphrase(phrase)})
    # A new area with a built-in passphrase is served at once, with no server setting.
    assert "Kalyani" in client.get(f"{API}/public/districts").json()

    me, _ = sign_up(client, "do.kalyani@gmail.com")
    other = offices.new_passphrase("Kalyani")
    assert post(client, "/office/join", me, {"district": "Kalyani", "name": "DO",
                                                     "passphrase": other}).status_code == 400
    # Typing it in small letters, with spaces instead of dashes, still works.
    typed = phrase.lower().replace("-", " ")
    r = post(client, "/office/join", me, {"district": "kalyani", "name": "Kalyani DO", "passphrase": typed})
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "COORDINATOR" and r.json()["district"] == "Kalyani"


def test_built_in_passphrases_are_only_stored_as_hashes():
    from app import offices

    assert {"Nadia", "Naihati"} <= set(offices.OFFICES)
    for stored in offices.OFFICES.values():
        algorithm, iterations, salt, digest = stored.split("$")
        assert algorithm == "pbkdf2_sha256" and int(iterations) >= 300_000
        assert len(salt) == 32 and len(digest) == 64
    # One area's passphrase never opens another area.
    phrase = offices.new_passphrase("Nadia")
    assert not offices.matches(phrase, offices.OFFICES["Nadia"])

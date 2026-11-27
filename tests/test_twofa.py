"""Two-factor login (issue #6): authenticator codes for clinic staff, recovery codes, replay and brute-force protection."""
import base64
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from server import qr_matrix, totp_at, totp_match  # noqa: E402

PW = "Staffpass12345"


def code_now(secret, offset=0):
    return totp_at(secret, int(time.time() // 30) + offset)


def staff(server, admin, uniq):
    email = uniq()
    s, j = admin.post("/api/users/create", {"name": "Dr Two Factor", "email": email, "role": "admin", "password": PW})
    assert s == 200, j
    c = server.client()
    assert c.post("/api/auth/login", {"email": email, "password": PW})[0] == 200
    return c, email


def turn_on(c):
    s, j = c.post("/api/auth/2fa/setup", {"password": PW})
    assert s == 200, j
    setup = j["created"]
    secret = setup["secret"].replace(" ", "")
    assert setup["uri"].startswith("otpauth://totp/Clinora") and f"secret={secret}" in setup["uri"]
    assert setup["qr_svg"].startswith("<svg") and "<script" not in setup["qr_svg"]
    s, j = c.post("/api/auth/2fa/enable", {"code": code_now(secret)})
    assert s == 200, j
    return secret, j["created"]["recovery"]


def test_rfc6238_vectors_and_clock_drift():
    secret = base64.b32encode(b"12345678901234567890").decode()
    assert totp_at(secret, 59 // 30) == "287082" and totp_at(secret, 1111111109 // 30) == "081804"
    now = 1_800_000_000
    assert totp_match(secret, totp_at(secret, now // 30 - 1), now=now)       # 30 s old: still fine
    assert not totp_match(secret, totp_at(secret, now // 30 - 3), now=now)   # 90 s old: refused
    assert not totp_match(secret, "12345a", now=now) and not totp_match(secret, "", now=now)


def test_qr_code_is_a_valid_symbol():
    m = qr_matrix("otpauth://totp/Clinora:a@b.c?secret=JBSWY3DPEHPK3PXP&issuer=Clinora")
    size = len(m)
    assert (size - 17) % 4 == 0 and all(len(r) == size for r in m)
    for cx, cy in ((0, 0), (size - 7, 0), (0, size - 7)):  # the three finder squares
        assert all(m[cy][cx + i] and m[cy + 6][cx + i] and m[cy + i][cx] and m[cy + i][cx + 6] for i in range(7))


def test_login_needs_code_after_turning_on(server, admin, uniq):
    c, email = staff(server, admin, uniq)
    assert c.post("/api/auth/2fa/enable", {"code": "123456"})[0] == 400          # no setup started
    assert c.post("/api/auth/2fa/setup", {"password": "wrong-password"})[0] == 400
    secret, recovery = turn_on(c)
    assert len(recovery) == 10 and all(re.fullmatch(r"[a-z2-9]{5}-[a-z2-9]{5}", r) for r in recovery)
    assert c.post("/api/auth/2fa/status")[1]["created"] == {"on": True, "recovery_left": 10}

    x = server.client()
    s, j = x.post("/api/auth/login", {"email": email, "password": PW})
    assert s == 401 and j.get("need_2fa") is True                               # password alone isn't enough
    assert x.post("/api/auth/login", {"email": email, "password": PW, "code": "000000"})[1].get("need_2fa")
    assert x.post("/api/auth/login", {"email": email, "password": "nope", "code": code_now(secret)})[0] == 401
    code = code_now(secret, 1)  # next step's code: never used yet
    s, j = x.post("/api/auth/login", {"email": email, "password": PW, "code": code})
    assert s == 200 and j["data"]["me"]["two_factor"] == 1
    y = server.client()
    assert y.post("/api/auth/login", {"email": email, "password": PW, "code": code})[0] == 401   # same code again: replay refused

    # the secret is stored encrypted, never in plain text
    row = server.db().execute("SELECT totp_secret, totp_recovery FROM users WHERE email=?", (email,)).fetchone()
    assert secret not in row["totp_secret"] and recovery[0] not in row["totp_recovery"]


def test_recovery_code_works_once_and_turning_off(server, admin, uniq):
    c, email = staff(server, admin, uniq)
    secret, recovery = turn_on(c)
    a, b = server.client(), server.client()
    assert a.post("/api/auth/login", {"email": email, "password": PW, "code": recovery[0].upper()})[0] == 200
    assert b.post("/api/auth/login", {"email": email, "password": PW, "code": recovery[0]})[0] == 401   # used up
    assert a.post("/api/auth/2fa/status")[1]["created"]["recovery_left"] == 9
    new = a.post("/api/auth/2fa/recovery", {"password": PW})[1]["created"]["recovery"]
    assert b.post("/api/auth/login", {"email": email, "password": PW, "code": recovery[1]})[0] == 401  # old set replaced
    assert a.post("/api/auth/2fa/disable", {"password": PW, "code": "999999"})[0] == 400
    assert a.post("/api/auth/2fa/disable", {"password": PW, "code": new[0]})[0] == 200
    assert b.post("/api/auth/login", {"email": email, "password": PW})[0] == 200                    # back to password only


def test_wrong_codes_are_rate_limited(server, admin, uniq):
    c, email = staff(server, admin, uniq)
    secret, _ = turn_on(c)
    statuses = []
    for i in range(8):
        x = server.client()  # a new address each time, so only the per-account limit can stop it
        statuses.append(x.post("/api/auth/login", {"email": email, "password": PW, "code": f"{i:06d}"})[0])
    assert 429 in statuses
    assert server.client().post("/api/auth/login", {"email": email, "password": PW, "code": code_now(secret, 1)})[0] == 429


def test_admin_can_reset_a_lost_phone(server, admin, uniq):
    c, email = staff(server, admin, uniq)
    turn_on(c)
    import json
    users = json.loads(admin.get("/api/data")[1])["users"]
    uid = next(u["id"] for u in users if u["email"] == email.lower())
    assert next(u for u in users if u["id"] == uid)["two_factor"] == 1
    assert c.post("/api/users/2fa-reset", {"id": uid})[0] in (400, 403)  # not for yourself / only admins of others
    assert admin.post("/api/users/2fa-reset", {"id": uid})[0] == 200
    assert server.client().post("/api/auth/login", {"email": email, "password": PW})[0] == 200

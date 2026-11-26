"""Sign-up, email confirmation, forgot password, suspension."""
import re


def last_link(server, kind):
    return re.findall(rf"#{kind}/([\w-]+)", server.logtext())[-1]


def test_signup_needs_email_confirmation(server, uniq):
    doc = server.client()
    email = uniq("doc")
    doc.signup("doctor", "Dr New", email, confirm=False)
    s, j = doc.post("/api/m/profile", {"name": "X", "type": "doctors", "phone": "+911234567890", "addr": "a", "city": "b",
                                       "country": "India", "lat": 1, "lon": 1})
    assert s == 403 and "confirm" in j["error"]
    token = last_link(server, "confirm")
    assert server.client().post("/api/m/confirm", {"token": "wrong"})[0] == 400
    s, j = doc.post("/api/m/confirm", {"token": token})
    assert s == 200 and j["me"]["email_ok"] == 1
    assert server.client().post("/api/m/confirm", {"token": token})[0] == 400  # works once
    doc.profile()


def test_unconfirmed_patient_can_browse_but_not_post(server, uniq):
    doc, pat = server.client(), server.client()
    doc.signup("doctor", "Dr A", uniq())
    lid = doc.profile()
    pat.signup("patient", "Pat", uniq(), confirm=False)
    assert pat.post("/api/m/send", {"listing_id": lid, "body": "hi"})[0] == 403
    assert pat.post("/api/m/review", {"listing_id": lid, "stars": 5, "body": "great"})[0] == 403
    assert pat.post("/api/m/fav", {"listing_id": lid, "on": True})[0] == 200


def test_forgot_password_same_answer_and_one_time_link(server, uniq):
    email = uniq()
    server.client().signup("patient", "Pat", email)
    anon = server.client()
    s1, j1 = anon.post("/api/m/forgot", {"email": email})
    s2, j2 = anon.post("/api/m/forgot", {"email": uniq("nobody")})
    assert s1 == s2 == 200 and j1 == j2  # never shows who has an account
    token = last_link(server, "reset")
    s, j = anon.post("/api/m/reset", {"token": token, "new": "BrandNewPass123"})
    assert s == 200 and j["me"]["email"] == email
    assert anon.post("/api/m/reset", {"token": token, "new": "AnotherPass1234"})[0] == 400
    assert server.client().post("/api/m/login", {"email": email, "password": "BrandNewPass123"})[0] == 200


def test_wrong_password(server, uniq):
    email = uniq()
    server.client().signup("patient", "Pat", email)
    assert server.client().post("/api/m/login", {"email": email, "password": "nope-nope-nope"})[0] == 401

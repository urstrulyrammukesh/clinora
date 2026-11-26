"""Booking real doctors: settings, free slots, double-booking, cancelling, reminders."""
import pytest


@pytest.fixture
def doctor(server, uniq):
    doc = server.client()
    doc.signup("doctor", "Dr Book", uniq("doc"))
    lid = doc.profile("Book Clinic")
    s, j = doc.post("/api/m/booking/settings", {"on": True, "days": 127, "start": "00:00", "end": "23:45", "brk": ["13:00", "14:00"],
                                               "slot": 30, "modes": ["clinic", "video"], "fee": 500, "cur": "INR", "tz": "Asia/Kolkata"})
    assert s == 200, j
    return doc, lid


def test_settings_validated(server, uniq):
    doc = server.client()
    doc.signup("doctor", "Dr X", uniq())
    doc.profile()
    bad = {"on": True, "days": 0, "start": "09:00", "end": "17:00", "slot": 30, "modes": ["clinic"], "fee": 0, "cur": "INR"}
    assert doc.post("/api/m/booking/settings", bad)[0] == 400
    assert doc.post("/api/m/booking/settings", dict(bad, days=31, slot=7))[0] == 400
    pat = server.client()
    pat.signup("patient", "P", uniq())
    assert pat.post("/api/m/booking/settings", dict(bad, days=31))[0] == 403


def test_public_listing_shows_only_summary(server, doctor):
    _, lid = doctor
    s, j = server.client().post("/api/m/slots", {"listing_id": lid})
    assert s == 200 and j["result"]["days"]
    assert all(not ("13:00" <= t < "14:00") for d in j["result"]["days"] for t in d["times"])  # lunch break
    s, j = server.client().post("/api/m/me")
    listing = next(x for x in j["listings"] if x["id"] == lid)
    assert listing["booking"] == {"fee": 500, "cur": "INR", "modes": ["clinic", "video"], "slot": 30}


def test_book_cancel_and_rebook(server, doctor, uniq):
    doc, lid = doctor
    a, b = server.client(), server.client()
    aid = a.signup("patient", "Asha", uniq())
    b.signup("patient", "Bina", uniq())
    days = server.client().post("/api/m/slots", {"listing_id": lid})[1]["result"]["days"]
    day, tm = days[1]["date"], days[1]["times"][2]
    assert server.client().post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "clinic"})[0] == 401
    assert doc.post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "clinic"})[0] == 400  # not yourself
    assert a.post("/api/m/book", {"listing_id": lid, "date": day, "time": "13:10", "mode": "clinic"})[0] == 400  # not a slot
    assert a.post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "clinic", "for_name": "Stranger"})[0] == 400
    s, j = a.post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "video", "reason": "Fever"})
    assert s == 200
    bid = j["result"]["id"]
    assert b.post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "clinic"})[0] == 400  # taken
    s, j = doc.post("/api/m/me")
    assert j["bookings"]["as_doctor"][0]["reason"] == "Fever"
    assert doc.post("/api/m/send", {"to": aid, "body": "See you"})[0] == 200  # doctor may write to the patient who booked
    assert b.post("/api/m/booking/cancel", {"id": bid})[0] == 400
    assert doc.post("/api/m/booking/cancel", {"id": bid, "reason": "Emergency"})[0] == 200
    s, j = a.post("/api/m/me")
    assert not [r for r in j["reminders"] if r["kind"] == "appointment"]
    assert b.post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "clinic"})[0] == 200


def test_book_for_family_member(server, doctor, uniq):
    _, lid = doctor
    p = server.client()
    p.signup("patient", "Ravi", uniq())
    assert p.post("/api/m/family/save", {"name": "Sunita", "relation": "mother", "year": "1968"})[0] == 200
    days = server.client().post("/api/m/slots", {"listing_id": lid})[1]["result"]["days"]
    s, j = p.post("/api/m/book", {"listing_id": lid, "date": days[2]["date"], "time": days[2]["times"][0], "mode": "clinic", "for_name": "Sunita"})
    assert s == 200
    s, j = p.post("/api/m/me")
    assert j["bookings"]["as_patient"][0]["patient"] == "Sunita"


def test_booking_off(server, doctor):
    doc, lid = doctor
    doc.post("/api/m/booking/settings", {"on": False})
    assert server.client().post("/api/m/slots", {"listing_id": lid})[0] == 400

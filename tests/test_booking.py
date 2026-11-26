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
    assert listing["booking"] == {"fee": 500, "cur": "INR", "modes": ["clinic", "video"], "slot": 30, "prepay": False}


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


def test_prescription_and_review_request(server, doctor, uniq):
    doc, lid = doctor
    p, stranger = server.client(), server.client()
    p.signup("patient", "Asha", uniq())
    stranger.signup("patient", "Other", uniq())
    days = server.client().post("/api/m/slots", {"listing_id": lid})[1]["result"]["days"]
    bid = p.post("/api/m/book", {"listing_id": lid, "date": days[0]["date"], "time": days[0]["times"][0], "mode": "video"})[1]["result"]["id"]
    assert doc.post("/api/m/rx/write", {"booking_id": bid})[0] == 400  # empty
    assert p.post("/api/m/rx/write", {"booking_id": bid, "advice": "rest"})[0] == 403  # patients can't write
    s, j = doc.post("/api/m/rx/write", {"booking_id": bid, "diagnosis": "Viral fever", "advice": "Drink fluids",
                                        "meds": [{"name": "Paracetamol", "strength": "650 mg", "dose": "1 tablet", "times": ["08:00", "20:00", "99:99"], "days": 3, "food": "after"}]})
    assert s == 200
    rx = j["result"]["rx_id"]
    s, j = p.post("/api/m/rx/get", {"id": rx})
    assert s == 200 and j["result"]["data"]["meds"][0]["times"] == ["08:00", "20:00"]
    assert stranger.post("/api/m/rx/get", {"id": rx})[0] == 400
    s, body, h = p.get(f"/rx/{rx}")
    assert s == 200 and b"Paracetamol" in body and b"Viral fever" in body and "script-src 'nonce-" in h["Content-Security-Policy"]
    assert stranger.get(f"/rx/{rx}")[0] == 404 and server.client().get(f"/rx/{rx}")[0] == 404
    assert any("Prescription from" in n["title"] for n in p.post("/api/m/notifs")[1]["notifs"])
    assert doc.post("/api/m/booking/mark", {"id": bid, "status": "done"})[0] == 200
    assert any("How was your visit" in n["title"] for n in p.post("/api/m/notifs")[1]["notifs"])
    v = p.post("/api/m/me")[1]["bookings"]["as_patient"][0]
    assert v["rx_id"] == rx and v["slot"] == 30


def test_online_payment_demo_hold_and_refund(server, admin, uniq):
    doc = server.client()
    doc.signup("doctor", "Dr Pay", uniq())
    lid = doc.profile("Pay Clinic")
    base = {"on": True, "days": 127, "start": "00:00", "end": "23:45", "slot": 30, "modes": ["clinic"], "fee": 600, "cur": "USD", "tz": "Asia/Kolkata"}
    assert doc.post("/api/m/booking/settings", dict(base, prepay=True))[0] == 400  # INR only
    assert doc.post("/api/m/booking/settings", dict(base, cur="INR", prepay=True))[0] == 200  # demo mode on a dev computer
    p = server.client()
    p.signup("patient", "Payer", uniq())
    days = server.client().post("/api/m/slots", {"listing_id": lid})[1]["result"]["days"]
    day, tm = days[2]["date"], days[2]["times"][0]
    s, j = p.post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "clinic"})
    assert s == 200 and j["result"]["pay"] is True
    bid = j["result"]["id"]
    assert not any("New booking" in n["title"] for n in doc.post("/api/m/notifs")[1]["notifs"])  # only after payment
    assert server.client().post("/api/m/book", {"listing_id": lid, "date": day, "time": tm, "mode": "clinic"})[0] in (400, 401)  # held
    assert p.post("/api/m/book/pay", {"id": bid})[1]["result"]["demo"] is True
    assert p.post("/api/m/book/pay/demo", {"id": bid})[0] == 200
    v = p.post("/api/m/me")[1]["bookings"]["as_patient"][0]
    assert v["pay_status"] == "paid" and any("New booking" in n["title"] and "paid online" in n["body"] for n in doc.post("/api/m/notifs")[1]["notifs"])
    s, j = doc.post("/api/m/booking/cancel", {"id": bid, "reason": "Sick"})
    assert s == 200 and "refund" in j["result"]["refund"]
    assert p.post("/api/m/me")[1]["bookings"]["as_patient"][0]["pay_status"] == "refunded"
    # unpaid holds are released after 15 minutes
    s, j = p.post("/api/m/book", {"listing_id": lid, "date": day, "time": days[2]["times"][1], "mode": "clinic"})
    with server.db() as c:
        c.execute("UPDATE dbookings SET hold_until=1 WHERE id=?", (j["result"]["id"],))
    import time
    for _ in range(40):
        st = server.db().execute("SELECT status FROM dbookings WHERE id=?", (j["result"]["id"],)).fetchone()[0]
        if st == "cancelled":
            break
        time.sleep(1)
    assert st == "cancelled"
    # admin connects a payout account
    assert admin.post("/api/payout/set", {"listing_id": lid, "acc": "bad"})[0] == 400
    s, j = admin.post("/api/payout/set", {"listing_id": lid, "acc": "acc_ABCDEFGH1234"})
    assert s == 200 and any(d["payout_acc"] == "acc_ABCDEFGH1234" for d in j["created"]["doctors"])
    assert all("payout_acc" not in x for x in server.client().post("/api/m/me")[1]["listings"])  # private

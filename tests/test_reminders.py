"""Reminders: validation, time zones, the background sender, course end dates."""
import datetime
import os
import sys
import time
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("DATA_DIR", str(Path(__file__).resolve().parent / ".tmp-unit"))
import server as app  # noqa: E402  (for pure functions only)


def test_validation(server, uniq):
    p = server.client()
    p.signup("patient", "P", uniq())
    assert server.client().post("/api/m/reminder/save", {"kind": "medicine", "title": "x", "at": "09:00", "days": 127})[0] == 401
    for bad in ({"at": "25:00", "days": 127}, {"kind": "nope", "days": 127}, {"days": 0, "date": "2020-01-01"}, {"days": 500}):
        body = dict({"kind": "medicine", "title": "x", "at": "09:00", "tz": "Asia/Kolkata"}, **bad)
        assert p.post("/api/m/reminder/save", body)[0] == 400, bad


def test_time_zone(server, uniq):
    p = server.client()
    p.signup("patient", "P", uniq())
    s, j = p.post("/api/m/reminder/save", {"kind": "water", "title": "Water", "at": "18:30", "days": 96, "tz": "Europe/London"})
    d = datetime.datetime.fromtimestamp(j["reminders"][0]["next_at"] / 1000, ZoneInfo("Europe/London"))
    assert d.weekday() in (5, 6) and d.strftime("%H:%M") == "18:30"


def test_background_sender(server, uniq):
    p, other = server.client(), server.client()
    p.signup("patient", "P", uniq())
    other.signup("patient", "O", uniq())
    p.post("/api/m/reminder/save", {"kind": "medicine", "title": "Metformin", "at": "09:00", "days": 127, "tz": "UTC"})
    p.post("/api/m/reminder/save", {"kind": "water", "title": "Water", "at": "10:00", "days": 127, "tz": "UTC"})
    now = int(time.time() * 1000)
    with server.db() as c:
        c.execute("UPDATE reminders SET next_at=? WHERE title='Metformin'", (now - 1000,))
        c.execute("UPDATE reminders SET next_at=? WHERE title='Water'", (now - 10 * 3600_000,))  # missed long ago
    for _ in range(40):
        rem = [n for n in p.post("/api/m/notifs")[1]["notifs"] if n["kind"] == "reminder"]
        if rem:
            break
        time.sleep(1)
    assert len(rem) == 1 and "Metformin" in rem[0]["title"]  # the long-missed one is skipped, not sent late
    R = {r["title"]: r for r in p.post("/api/m/me")[1]["reminders"]}
    assert R["Metformin"]["next_at"] > now and R["Water"]["next_at"] > now
    assert not [n for n in other.post("/api/m/notifs")[1]["notifs"] if n["kind"] == "reminder"]


def test_once_and_course_end():
    day = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    r = {"at": "16:00", "days": 0, "date": day, "tz": "Asia/Kolkata", "lead": 1440}
    t = app.reminder_next(r, 0)
    assert t and app.reminder_next(r, t) is None
    until = (datetime.date.today() + datetime.timedelta(days=2)).isoformat()
    r = {"at": "08:00", "days": 127, "date": None, "tz": "UTC", "lead": 0, "until": until}
    t, n = int(time.time() * 1000), 0
    while (t := app.reminder_next(r, t)) and n < 10:
        n += 1
    assert 2 <= n <= 3

"""Clinora AI - local web server + AI receptionist backend.

Serves the website and exposes:
  GET  /api/status  -> {"ai": true/false, "reason": "..."}
  GET  /api/data    -> everything the site shows (appointments, alerts, live status, listings)
  POST /api/...      -> create / update data (see ROUTES below), stored in data/sehatdesk.db (SQLite)
  POST /api/chat    -> one Claude turn. The browser runs the tools (bookings live
                       in the browser for this demo) and calls again with the
                       tool results until Claude gives a final answer.

The API key stays on this server and is never sent to the browser.
Put it in a file named .env next to this file:   ANTHROPIC_API_KEY=sk-ant-...
"""

import datetime
import sys
import hashlib
import hmac
import html
import secrets
import json
import os
import re
import sqlite3
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get("PORT", "8765"))
MODEL = "claude-opus-5-5"


def load_env_file():
    env = ROOT / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

# ---------------------------------------------------------------- payments config
# Real payments switch on per provider when its keys are in .env (use TEST/SANDBOX keys first):
#   Stripe   : cards, Apple Pay, Google Pay (worldwide)          STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET
#   Razorpay : UPI, Google Pay (UPI), PhonePe, Paytm (India, ₹)   RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET
#   PayPal   : PayPal accounts                                    PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET, PAYPAL_ENV=sandbox|live
# With no provider keys at all, the site runs a clearly-labelled DEMO mode: no money moves.
import base64
import math
import urllib.error
import urllib.parse
import urllib.request

try:
    import stripe
except ImportError:
    stripe = None
STRIPE_KEY = os.environ.get("STRIPE_SECRET_KEY", "").strip()
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "").strip()
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "").strip()
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "").strip()
PAYPAL_CLIENT_ID = os.environ.get("PAYPAL_CLIENT_ID", "").strip()
PAYPAL_CLIENT_SECRET = os.environ.get("PAYPAL_CLIENT_SECRET", "").strip()
PAYPAL_API = "https://api-m.paypal.com" if os.environ.get("PAYPAL_ENV", "sandbox") == "live" else "https://api-m.sandbox.paypal.com"
STRIPE_ON = bool(STRIPE_KEY and stripe)
RAZORPAY_ON = bool(RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET)
PAYPAL_ON = bool(PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET)
PAY_MODE = "live" if (STRIPE_ON or RAZORPAY_ON or PAYPAL_ON) else "demo"
# APP_ENV=production on the real website: demo payments are refused and only fixed prices are charged.
PRODUCTION = os.environ.get("APP_ENV", "").lower() == "production"
ALLOW_DEMO_PAYMENTS = PAY_MODE == "demo" and not PRODUCTION
# Converted prices use approximate rates; in production they are only offered when explicitly allowed.
ALLOW_FX_PRICES = os.environ.get("ALLOW_FX_PRICES", "0" if PRODUCTION else "1") == "1"
RAZORPAY_WEBHOOK_SECRET = os.environ.get("RAZORPAY_WEBHOOK_SECRET", "").strip()
PAYPAL_WEBHOOK_ID = os.environ.get("PAYPAL_WEBHOOK_ID", "").strip()
if STRIPE_ON:
    stripe.api_key = STRIPE_KEY

CURRENCY = os.environ.get("PAY_CURRENCY", "usd").lower()   # the clinic's base currency (doctor fees below)
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{os.environ.get('PORT', '8765')}").rstrip("/")
REQUIRE_VIDEO_PAYMENT = os.environ.get("REQUIRE_VIDEO_PAYMENT", "1") != "0"
DOCTOR_FEES = {"d1": 40, "d2": 50, "d3": 70, "d4": 55}  # in CURRENCY, whole units
DOCTOR_NAMES = {"d1": "Dr. Sarah Collins", "d2": "Dr. Rohan Mehta", "d3": "Dr. Priya Nair", "d4": "Dr. Daniel Okafor"}
PAY_STATUSES = {"unpaid", "paid", "refund_due", "refunded"}
CLINIC_NAME = "Clinora Medical Center"

# The clinic's own fixed prices in some currencies (used instead of converting).
LOCAL_PRICES = {"inr": {"d1": 500, "d2": 600, "d3": 800, "d4": 700}}
# APPROXIMATE exchange rates (units per 1 USD) for converting the base fee into other currencies.
# Replace with a live exchange-rate feed before taking real payments in converted currencies.
FX_PER_USD = {
    "usd": 1, "eur": 0.92, "gbp": 0.79, "inr": 84, "aed": 3.67, "sar": 3.75, "qar": 3.64, "kwd": 0.31, "omr": 0.385,
    "bhd": 0.376, "pkr": 280, "bdt": 120, "lkr": 300, "npr": 135, "ngn": 1550, "kes": 129, "ghs": 15, "zar": 18,
    "egp": 49, "mad": 10, "etb": 120, "tzs": 2600, "ugx": 3700, "brl": 5.5, "mxn": 18.5, "cop": 4100, "clp": 950,
    "pen": 3.75, "cad": 1.37, "aud": 1.52, "nzd": 1.65, "jpy": 150, "krw": 1380, "cny": 7.2, "hkd": 7.8, "twd": 32,
    "sgd": 1.34, "myr": 4.5, "thb": 35, "idr": 16000, "php": 57, "vnd": 25000, "try": 34, "rub": 95, "chf": 0.88,
    "sek": 10.6, "nok": 10.8, "dkk": 6.9, "pln": 4.0, "czk": 23, "huf": 360, "ils": 3.7,
}
ZERO_DECIMAL = {"jpy", "krw", "vnd", "clp", "ugx"}  # currencies without cents
PAYPAL_CURRENCIES = {"usd", "eur", "gbp", "cad", "aud", "nzd", "jpy", "chf", "sek", "nok", "dkk", "pln", "czk", "huf",
                     "ils", "mxn", "brl", "hkd", "twd", "sgd", "myr", "thb", "php"}
RAZORPAY_CURRENCIES = {"inr"}  # UPI, Paytm etc. are rupee-only


class ProviderError(Exception):
    pass


def nice_round(x):
    """Round a converted price up to a friendly number."""
    if x < 100:
        return math.ceil(x)
    step = 5 if x < 1000 else 10 ** (len(str(int(x))) - 2)
    return int(math.ceil(x / step) * step)


def quote(doc, currency):
    cur = (currency or CURRENCY).lower()
    if cur not in FX_PER_USD:
        raise InputError("This currency isn't supported yet")
    if doc in LOCAL_PRICES.get(cur, {}):
        major, converted = LOCAL_PRICES[cur][doc], False
    elif cur == CURRENCY:
        major, converted = DOCTOR_FEES[doc], False
    elif not ALLOW_FX_PRICES:
        raise InputError("Please pay in " + CURRENCY.upper() + " or the clinic's local currency.")
    else:
        major, converted = nice_round(DOCTOR_FEES[doc] / FX_PER_USD[CURRENCY] * FX_PER_USD[cur]), True
    minor = int(major) if cur in ZERO_DECIMAL else int(round(major * 100))
    return {"currency": cur, "amount": minor, "converted": converted}


def offered_currencies():
    if ALLOW_FX_PRICES:
        return sorted(FX_PER_USD)
    return sorted({CURRENCY} | set(LOCAL_PRICES))


def methods_for(currency):
    cur = currency.lower()
    demo = ALLOW_DEMO_PAYMENTS
    out = []
    if cur in RAZORPAY_CURRENCIES and (RAZORPAY_ON or demo):
        out.append({"id": "razorpay", "label": "UPI · Google Pay · PhonePe · Paytm", "sub": "Also cards and net banking (India)"})
    if STRIPE_ON or demo:
        out.append({"id": "stripe", "label": "Card · Apple Pay · Google Pay", "sub": "Visa, Mastercard, Amex and phone wallets"})
    if cur in PAYPAL_CURRENCIES and (PAYPAL_ON or demo):
        out.append({"id": "paypal", "label": "PayPal", "sub": "Pay with your PayPal account"})
    return out


def http_json(method, url, body=None, auth=None, bearer=None, form=None):
    headers = {"Accept": "application/json"}
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    if auth:
        headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    if bearer:
        headers["Authorization"] = "Bearer " + bearer
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        raise ProviderError(f"{e.code} {detail}")
    except urllib.error.URLError as e:
        raise ProviderError(str(e.reason))


_PAYPAL_TOKEN = {"value": "", "expires": 0}


def paypal_token():
    if _PAYPAL_TOKEN["value"] and _PAYPAL_TOKEN["expires"] > time.time() + 60:
        return _PAYPAL_TOKEN["value"]
    j = http_json("POST", PAYPAL_API + "/v1/oauth2/token", form={"grant_type": "client_credentials"},
                  auth=(PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET))
    _PAYPAL_TOKEN.update(value=j["access_token"], expires=time.time() + int(j.get("expires_in", 300)))
    return _PAYPAL_TOKEN["value"]


def major_str(minor, cur):
    return str(minor) if cur in ZERO_DECIMAL else f"{minor / 100:.2f}"


try:
    import anthropic
except ImportError:  # SDK not installed: the site still works in demo mode
    anthropic = None

client = None
AI_REASON = ""
if anthropic is None:
    AI_REASON = "The Anthropic SDK is not installed."
elif not (os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
    AI_REASON = "No API key yet. Add ANTHROPIC_API_KEY to the .env file and restart."
else:
    client = anthropic.Anthropic()

SYSTEM_PROMPT = """You are the AI receptionist for Clinora Medical Center, shown in a chat panel on the Clinora website. Patients can reach you from any country and time zone.

What you do:
- Answer questions about the clinic: doctors, fees, opening hours, address, payment, video consultations.
- Book, look up and cancel appointments with the tools. Bookings can be in-clinic or by video.
- Help patients anywhere find hospitals, clinics, doctors, dentists or pharmacies in any city with search_directory, and open website pages for them with show_page.
- Understand what the patient means even when the message is short, informal, misspelled, or mixes languages (for example Hinglish like "kal daant dikhana hai" = "I need to see a dentist tomorrow").

How to book:
1. Work out the doctor (use list_doctors; match symptoms to a specialty), in-clinic or video, and the day.
2. Call check_availability and offer a few free times.
3. Ask for the patient's name and mobile number with country code if you do not have them.
4. Read the details back in one short message and get a clear yes before calling book_appointment.
Never invent doctors, times, prices, booking IDs or addresses: use only what the tools return.
Quote fees exactly as list_doctors gives them in "fee" (already in the patient's local currency); never convert currencies yourself.

Health questions (any time of day or night, often private ones):
- If someone asks whether a food is safe or healthy to eat, answer briefly and offer the Food Scan page (show_page "food"), where they can photograph it for a full check.
- Answer general health, sexual-health and self-care questions clearly, kindly and without judgement, like a well-trained nurse on a helpline. This includes contraception and protection (condoms, the pill, emergency contraception and how soon it must be taken), safer sex, STI testing, consent, periods and pregnancy questions, colds, fever, stomach upsets, and when something needs a doctor today.
- Give practical, evidence-based general information and say clearly when they should see a doctor, a pharmacist or a sexual-health clinic, and how urgently. Offer to find one nearby or book a video consultation.
- If the person sounds low, anxious, lonely or upset, listen first: reflect what they said, be warm, and ask one gentle question at a time. Never lecture. Offer helplines (get_helplines) and a doctor or counsellor, but keep talking with them for as long as they want.
- If someone mentions harassment, abuse or violence, believe them, check that they are safe right now, and give the matching helpline numbers from get_helplines.
- If someone mentions suicide or self-harm: stay with them, take it seriously, ask if they are safe right now, give the crisis line and emergency number from get_helplines, and encourage them to contact someone they trust. Keep the conversation going.

Safety:
- You are not a doctor. Do not diagnose, prescribe prescription medicines, or give personal dosage advice beyond what a package leaflet says. You may suggest which kind of specialist fits the symptoms and help book them.
- If the message suggests an emergency (chest pain, trouble breathing, stroke signs, heavy bleeding, unconsciousness, severe allergic reaction, a suicide attempt or immediate danger, poisoning, serious injury), first call get_emergency_numbers and alert_clinic_staff, then tell them to call the local emergency number now, before anything else.
- After booking, give the patient the pay_link from the tool result so they can pay online (in-clinic visits may also pay at the clinic). For video bookings, payment is needed before joining: give both the pay_link and the call_link, and tell them to open the call link at the appointment time.
- After an in-clinic booking, offer to open ride options (show_ride_options) so they can book a cab to the clinic. In an emergency, never suggest a cab: tell them to call the ambulance number.
- Ask only for the details needed for a booking (name and phone). Do not ask for ID numbers, insurance numbers or payment card details.

Style:
- Warm, calm and brief: two to four short sentences, like a good front-desk person on chat. Use a short list only for choices such as time slots.
- Reply in the website language given in the context (English if none). If the patient clearly writes in a different language, reply in the language they write in.
- Times are in the patient's local time zone given in the context."""

def tool(name, description, properties, required=None):
    return {
        "name": name,
        "description": description,
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": properties,
            "required": list(properties) if required is None else required,
            "additionalProperties": False,
        },
    }


TOOLS = [
    tool("get_clinic_info", "Clinic name, address, phone, opening hours, whether it is open right now, payment options and video consultation info.", {}),
    tool("list_doctors", "All doctors at the clinic with specialty, qualifications, experience, languages, fee in USD and whether they are in the clinic right now.", {}),
    tool(
        "check_availability",
        "Free appointment times for one doctor on one date (local time).",
        {
            "doctor_id": {"type": "string", "description": "Doctor id from list_doctors, e.g. d2."},
            "date": {"type": "string", "description": "Date as YYYY-MM-DD, today or within the next 14 days."},
        },
    ),
    tool(
        "book_appointment",
        "Book an appointment. Only call after the patient has confirmed all details.",
        {
            "doctor_id": {"type": "string"},
            "date": {"type": "string", "description": "YYYY-MM-DD"},
            "time": {"type": "string", "description": "HH:MM, 24-hour, one of the free times from check_availability."},
            "mode": {"type": "string", "enum": ["clinic", "video"]},
            "patient_name": {"type": "string"},
            "phone": {"type": "string", "description": "Mobile number with country code, e.g. +44 7700 900123."},
        },
    ),
    tool("find_bookings", "Upcoming bookings for a mobile number.", {"phone": {"type": "string"}}),
    tool(
        "cancel_booking",
        "Cancel a booking. The phone number must match the booking.",
        {"booking_id": {"type": "string", "description": "e.g. A105"}, "phone": {"type": "string"}},
    ),
    tool("get_emergency_numbers", "Emergency phone numbers for the patient's current country.", {}),
    tool("get_helplines", "Free helpline numbers for the patient's country: emergency, women / harassment / domestic abuse, suicide and emotional-support crisis lines, child helpline, plus a link to find more helplines. Also shows them on screen.", {}),
    tool(
        "alert_clinic_staff",
        "Send an urgent alert to clinic staff, e.g. for a possible emergency.",
        {"summary": {"type": "string", "description": "One-line summary of the situation."}},
    ),
    tool(
        "search_directory",
        "Search hospitals, clinics, doctors, dentists, pharmacies, labs/diagnostic centres, or universities and colleges (incl. medical colleges) in any city or country worldwide (public map data). Also opens the World Directory page for the patient.",
        {
            "city": {"type": "string", "description": "City or country, e.g. Nairobi or Toronto."},
            "type": {"type": "string", "enum": ["hospital", "clinic", "doctors", "dentist", "pharmacy", "laboratory", "university"]},
        },
    ),
    tool("show_ride_options", "Open the ride-booking panel for getting to the clinic: shows the taxi/cab apps available in the patient's country (e.g. Uber, Ola, Rapido, Lyft, Careem, Grab, Bolt) with the clinic pre-filled where the app allows it.", {}),
    tool(
        "show_page",
        "Open a page of the website for the patient.",
        {"page": {"type": "string", "enum": ["home", "nearby", "directory", "dashboard", "books", "account", "food"]}},
    ),
]

# ---------------------------------------------------------------- database
DATA_DIR = Path(os.environ.get("DATA_DIR") or (ROOT / "data"))  # on a host, point this at a persistent disk
DB_PATH = DATA_DIR / "sehatdesk.db"
DB_LOCK = threading.Lock()
DOCTOR_IDS = {"d1", "d2", "d3", "d4"}
STATUSES = {"Confirmed", "Arrived", "Done", "No-show", "Cancelled"}
SOURCES = {"WhatsApp", "Website", "Call"}
MODES = {"clinic", "video"}
LIST_TYPES = {"doctors", "clinic", "hospital", "dentist"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^(1[0-9]):(00|30)$")  # 10:00 .. 19:30, every 30 minutes

SCHEMA = """
CREATE TABLE IF NOT EXISTS appointments(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, phone TEXT NOT NULL, doc TEXT NOT NULL,
  date TEXT NOT NULL, time TEXT NOT NULL, mode TEXT NOT NULL, src TEXT NOT NULL,
  status TEXT NOT NULL, ts INTEGER NOT NULL, call_token TEXT);
CREATE INDEX IF NOT EXISTS appt_slot ON appointments(doc, date, time);
CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, src TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS live(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS stats(key TEXT PRIMARY KEY, value INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS listings(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, type TEXT NOT NULL, spec TEXT, phone TEXT NOT NULL,
  email TEXT, web TEXT, addr TEXT NOT NULL, city TEXT NOT NULL, country TEXT NOT NULL, cc TEXT,
  video INTEGER NOT NULL, lat REAL NOT NULL, lon REAL NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS users(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL,
  role TEXT NOT NULL, doctor_id TEXT, pw TEXT NOT NULL, created INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS call_signals(
  id INTEGER PRIMARY KEY AUTOINCREMENT, room TEXT NOT NULL, sender TEXT NOT NULL,
  kind TEXT NOT NULL, payload TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS call_room ON call_signals(room, id);
CREATE TABLE IF NOT EXISTS payment_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, appt_id TEXT, event TEXT NOT NULL, provider TEXT, ref TEXT,
  amount INTEGER, currency TEXT, detail TEXT, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS members(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
  pw TEXT NOT NULL, created INTEGER NOT NULL, city TEXT, online INTEGER NOT NULL DEFAULT 0, last_seen INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS member_sessions(token TEXT PRIMARY KEY, member_id INTEGER NOT NULL, expires INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS favs(member_id INTEGER NOT NULL, listing_id INTEGER NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY(member_id, listing_id));
CREATE TABLE IF NOT EXISTS messages(
  id INTEGER PRIMARY KEY AUTOINCREMENT, from_id INTEGER NOT NULL, to_id INTEGER NOT NULL, body TEXT NOT NULL,
  ts INTEGER NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS msg_pair ON messages(from_id, to_id, id);
CREATE TABLE IF NOT EXISTS unidocs_cache(q TEXT PRIMARY KEY, result TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS reviews(
  id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL, member_id INTEGER NOT NULL, stars INTEGER NOT NULL,
  body TEXT NOT NULL, gif TEXT, ts INTEGER NOT NULL, reply TEXT, reply_ts INTEGER, UNIQUE(listing_id, member_id));
CREATE TABLE IF NOT EXISTS gallery(id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL, caption TEXT, ts INTEGER NOT NULL);
"""


EXTRA_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifs(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL, kind TEXT NOT NULL,
  title TEXT NOT NULL, body TEXT, link TEXT, ts INTEGER NOT NULL, seen INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS notif_member ON notifs(member_id, id);
CREATE TABLE IF NOT EXISTS videos(id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL, member_id INTEGER NOT NULL,
  kind TEXT NOT NULL, caption TEXT, status TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, ts INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS video_listing ON videos(listing_id, status);
CREATE TABLE IF NOT EXISTS verifications(member_id INTEGER PRIMARY KEY, listing_id INTEGER, reg_no TEXT NOT NULL, council TEXT NOT NULL,
  reg_year INTEGER NOT NULL, qualification TEXT NOT NULL, cert INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL, reason TEXT,
  submitted INTEGER NOT NULL, reviewed INTEGER, reviewer TEXT);
CREATE TABLE IF NOT EXISTS reminders(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL, kind TEXT NOT NULL,
  title TEXT NOT NULL, note TEXT, at TEXT NOT NULL, days INTEGER NOT NULL DEFAULT 0, date TEXT, tz TEXT NOT NULL, lead INTEGER NOT NULL DEFAULT 0,
  email INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1, next_at INTEGER, last_sent INTEGER, created INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS reminder_due ON reminders(active, next_at);
CREATE TABLE IF NOT EXISTS pw_resets(token TEXT PRIMARY KEY, member_id INTEGER NOT NULL, expires INTEGER NOT NULL, used INTEGER NOT NULL DEFAULT 0);
"""


class InputError(Exception):
    pass


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def now_ms():
    return int(time.time() * 1000)


def seed(conn):
    today = datetime.date.today()
    t, k = today.isoformat(), (today + datetime.timedelta(days=1)).isoformat()
    rows = [
        ("Emma Wilson", "d2", t, "10:30", "WhatsApp", "Done", "clinic", "+00000000001"),
        ("Rahul Verma", "d1", t, "11:00", "Call", "Arrived", "clinic", "+00000000002"),
        ("Carlos Mendez", "d3", t, "17:30", "Website", "Confirmed", "video", "+00000000003"),
        ("Aisha Bello", "d4", t, "18:00", "WhatsApp", "Confirmed", "video", "+00000000004"),
        ("Yuki Tanaka", "d2", k, "10:00", "WhatsApp", "Confirmed", "clinic", "+00000000005"),
        ("Sana Khan", "d1", k, "12:30", "Website", "Confirmed", "video", "+00000000006"),
        ("Sophie Martin", "d3", k, "16:00", "Call", "Confirmed", "video", "+00000000007"),
        ("Liam Brennan", "d1", t, "10:00", "WhatsApp", "No-show", "clinic", "+00000000008"),
    ]
    for i, (name, doc, date, tm, src, status, mode, phone) in enumerate(rows):
        conn.execute("INSERT INTO appointments (id, name, phone, doc, date, time, mode, src, status, ts, call_token) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                     (f"A{101 + i}", name, phone, doc, date, tm, mode, src, status, now_ms() - i * 1_000_000,
                      secrets.token_urlsafe(16) if mode == "video" else None))
    for key, val in {"clinic": 1, "d1": 1, "d2": 1, "d3": 0, "d4": 1}.items():
        conn.execute("INSERT OR REPLACE INTO live VALUES(?,?)", (key, val))
    conn.execute("INSERT OR REPLACE INTO stats VALUES('chats', 37)")
    for col in ("pay_token", "amount"):
        if col not in {r["name"] for r in conn.execute("PRAGMA table_info(appointments)")}:
            return  # brand-new database: columns are added (and filled) right after this
    backfill_tokens(conn)
    conn.execute("UPDATE appointments SET pay_status='paid', pay_ref='cash', paid_ts=ts WHERE status='Done'")


def backfill_tokens(conn):
    for r in conn.execute("SELECT id, mode, doc, call_token, pay_token, amount, pay_status, status FROM appointments").fetchall():
        conn.execute("UPDATE appointments SET call_token=?, pay_token=?, amount=?, currency=?, pay_status=? WHERE id=?", (
            r["call_token"] or (secrets.token_urlsafe(16) if r["mode"] == "video" else None),
            r["pay_token"] or secrets.token_urlsafe(16),
            r["amount"] or DOCTOR_FEES.get(r["doc"], 0) * 100, CURRENCY,
            r["pay_status"] or ("paid" if r["status"] == "Done" else "unpaid"), r["id"]))


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with DB_LOCK, connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(appointments)")}
        for col, kind in [("call_token", "TEXT"), ("pay_token", "TEXT"), ("pay_status", "TEXT DEFAULT 'unpaid'"),
                          ("amount", "INTEGER"), ("currency", "TEXT"), ("pay_ref", "TEXT"), ("paid_ts", "INTEGER"),
                          ("pay_method", "TEXT"), ("pay_currency", "TEXT"), ("pay_amount", "INTEGER")]:
            if col not in cols:
                conn.execute(f"ALTER TABLE appointments ADD COLUMN {col} {kind}")
        mcols = {r["name"] for r in conn.execute("PRAGMA table_info(members)")}
        if "photo_ts" not in mcols:
            conn.execute("ALTER TABLE members ADD COLUMN photo_ts INTEGER")
        for col in ("provider", "provider_id"):
            if col not in mcols:
                conn.execute(f"ALTER TABLE members ADD COLUMN {col} TEXT")
        conn.executescript(EXTRA_SCHEMA)
        lcols = {r["name"] for r in conn.execute("PRAGMA table_info(listings)")}
        for col, kind in [("owner", "INTEGER"), ("social", "TEXT"), ("hours", "TEXT"), ("tz", "TEXT")]:
            if col not in lcols:
                conn.execute(f"ALTER TABLE listings ADD COLUMN {col} {kind}")
        if conn.execute("SELECT COUNT(*) FROM live").fetchone()[0] == 0:
            seed(conn)
        backfill_tokens(conn)


# ---------------------------------------------------------------- accounts & sessions
ROLES = {"admin", "doctor"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SESSION_DAYS = 7
PBKDF2_ROUNDS = 310_000
FAILED_LOGINS = {}  # ip -> [timestamps]


class AuthError(Exception):
    def __init__(self, message, status=403):
        super().__init__(message)
        self.status = status


def hash_password(password):
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def check_password(password, stored):
    try:
        _, rounds, salt, digest = stored.split("$")
        test = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(test.hex(), digest)
    except (ValueError, AttributeError):
        return False


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def new_session(conn, user_id):
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM sessions WHERE expires < ?", (now_ms(),))
    conn.execute("INSERT INTO sessions VALUES(?,?,?)", (token_hash(token), user_id, now_ms() + SESSION_DAYS * 86_400_000))
    return token


def user_for_token(conn, token):
    if not token:
        return None
    row = conn.execute(
        "SELECT u.id, u.email, u.name, u.role, u.doctor_id FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires > ?", (token_hash(token), now_ms())).fetchone()
    return dict(row) if row else None


def need_login(user):
    if not user:
        raise AuthError("Please log in first.", 401)


def need_admin(user):
    need_login(user)
    if user["role"] != "admin":
        raise AuthError("Only the clinic admin can do this.")


def valid_password(d, key="password"):
    pw = str(d.get(key) or "")
    if len(pw) < 10:
        raise InputError("Password must be at least 10 characters")
    if len(pw) > 200:
        raise InputError("Password is too long")
    return pw


def valid_email(d):
    email = text(d, "email", 120).lower()
    if not EMAIL_RE.match(email):
        raise InputError("Enter a valid email address")
    return email


RATE = {}


def too_many(bucket, ip, limit, window):
    """Simple in-memory rate limit: True when this IP made more than `limit` calls in `window` seconds."""
    key = (bucket, ip)
    recent = [t for t in RATE.get(key, []) if t > time.time() - window]
    recent.append(time.time())
    RATE[key] = recent
    return len(recent) > limit


def too_many_failures(ip):
    recent = [t for t in FAILED_LOGINS.get(ip, []) if t > time.time() - 900]
    FAILED_LOGINS[ip] = recent
    return len(recent) >= 8


def setup_admin(conn, d):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        raise AuthError("Setup is already done. Please log in.")
    name = text(d, "name", 80)
    cur = conn.execute("INSERT INTO users(email,name,role,doctor_id,pw,created) VALUES(?,?,?,?,?,?)",
                       (valid_email(d), name, "admin", None, hash_password(valid_password(d)), now_ms()))
    return cur.lastrowid


def login(conn, d, ip):
    if too_many_failures(ip):
        raise AuthError("Too many failed attempts. Try again in 15 minutes.", 429)
    email = str(d.get("email") or "").strip().lower()
    row = conn.execute("SELECT id, pw FROM users WHERE email=?", (email,)).fetchone()
    if not row or not check_password(str(d.get("password") or ""), row["pw"]):
        FAILED_LOGINS.setdefault(ip, []).append(time.time())
        raise AuthError("Wrong email or password.", 401)
    return row["id"]


def change_password(conn, d, user):
    need_login(user)
    row = conn.execute("SELECT pw FROM users WHERE id=?", (user["id"],)).fetchone()
    if not check_password(str(d.get("current") or ""), row["pw"]):
        raise InputError("Your current password is wrong")
    conn.execute("UPDATE users SET pw=? WHERE id=?", (hash_password(valid_password(d, "new")), user["id"]))


def create_user(conn, d, user):
    need_admin(user)
    role = one_of(d, "role", ROLES)
    doctor_id = str(d.get("doctor_id") or "") or None
    if role == "doctor" and doctor_id not in DOCTOR_IDS:
        raise InputError("Pick which doctor profile this login belongs to")
    if role == "admin":
        doctor_id = None
    email = valid_email(d)
    if conn.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        raise InputError("An account with this email already exists")
    conn.execute("INSERT INTO users(email,name,role,doctor_id,pw,created) VALUES(?,?,?,?,?,?)",
                 (email, text(d, "name", 80), role, doctor_id, hash_password(valid_password(d)), now_ms()))


def delete_user(conn, d, user):
    need_admin(user)
    uid = int(d.get("id") or 0)
    if uid == user["id"]:
        raise InputError("You can't remove your own account")
    conn.execute("DELETE FROM sessions WHERE user_id=?", (uid,))
    conn.execute("DELETE FROM users WHERE id=?", (uid,))


def snapshot(conn, user=None):
    data = {
        "me": user,
        "setup_needed": conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0,
        "live": {r["key"]: bool(r["value"]) for r in conn.execute("SELECT * FROM live")},
        "listings": public_listings(conn),
        # public: which slots are taken, without any patient details
        "taken": [dict(r) for r in conn.execute(
            "SELECT doc, date, time FROM appointments WHERE status != 'Cancelled' AND date >= date('now','-1 day')")],
        "appointments": [], "alerts": [], "stats": {}, "users": [],
    }
    if user:
        if user["role"] == "admin":
            rows = conn.execute("SELECT * FROM appointments ORDER BY date, time")
            data["users"] = [dict(r) for r in conn.execute(
                "SELECT id, email, name, role, doctor_id, created FROM users ORDER BY created")]
            data["verify_pending"] = conn.execute("SELECT COUNT(*) FROM verifications WHERE status='pending'").fetchone()[0]
        else:
            rows = conn.execute("SELECT * FROM appointments WHERE doc=? ORDER BY date, time", (user["doctor_id"],))
        data["appointments"] = [dict(r) for r in rows]
        data["alerts"] = [dict(r) for r in conn.execute("SELECT * FROM alerts ORDER BY ts DESC LIMIT 20")]
        data["stats"] = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM stats")}
    return data


def text(data, key, max_len=120, required=True):
    value = str(data.get(key) or "").strip()[:max_len]
    if required and not value:
        raise InputError(f"{key} is required")
    return value


def phone_of(data, key="phone"):
    raw = text(data, key, 30)
    digits = re.sub(r"\D", "", raw)
    if not 7 <= len(digits) <= 15:
        raise InputError("Enter a phone number with country code")
    return ("+" if raw.startswith("+") else "") + digits


def same_phone(a, b):
    da, db = re.sub(r"\D", "", a), re.sub(r"\D", "", b)
    return len(da) >= 7 and len(db) >= 7 and da[-9:] == db[-9:]


def one_of(data, key, allowed):
    value = str(data.get(key) or "")
    if value not in allowed:
        raise InputError(f"{key} must be one of: {', '.join(sorted(allowed))}")
    return value


def create_appointment(conn, d, user=None):
    doc = one_of(d, "doc", DOCTOR_IDS)
    date, tm = text(d, "date", 10), text(d, "time", 5)
    if not DATE_RE.match(date) or not TIME_RE.match(tm):
        raise InputError("Invalid date or time")
    days = (datetime.date.fromisoformat(date) - datetime.date.today()).days
    if not -1 <= days <= 15:  # -1 tolerates patients a time zone behind the server
        raise InputError("Date must be within the next two weeks")
    taken = conn.execute("SELECT 1 FROM appointments WHERE doc=? AND date=? AND time=? AND status!='Cancelled'",
                         (doc, date, tm)).fetchone()
    if taken:
        raise InputError("That time was just booked by someone else. Please pick another time.")
    name = text(d, "name", 80)
    if len(name) < 2:
        raise InputError("Patient name is required")
    next_num = conn.execute("SELECT COALESCE(MAX(CAST(SUBSTR(id,2) AS INTEGER)),100)+1 FROM appointments").fetchone()[0]
    mode = one_of(d, "mode", MODES)
    token = secrets.token_urlsafe(16) if mode == "video" else None
    row = (f"A{next_num}", name, phone_of(d), doc, date, tm, mode,
           one_of(d, "src", SOURCES), "Confirmed", now_ms(), token)
    conn.execute("INSERT INTO appointments (id, name, phone, doc, date, time, mode, src, status, ts, call_token) VALUES(?,?,?,?,?,?,?,?,?,?,?)", row)
    pay_token = secrets.token_urlsafe(16)
    amount = DOCTOR_FEES[doc] * 100
    conn.execute("UPDATE appointments SET pay_token=?, pay_status='unpaid', amount=?, currency=? WHERE id=?",
                 (pay_token, amount, CURRENCY, row[0]))
    return {"id": row[0], "call": token, "pay": pay_token, "amount": amount, "currency": CURRENCY}


def set_status(conn, d, user=None):
    need_login(user)
    status = one_of(d, "status", STATUSES)
    row = conn.execute("SELECT doc FROM appointments WHERE id=?", (text(d, "id", 12),)).fetchone()
    if not row:
        raise InputError("Booking not found")
    if user["role"] == "doctor" and row["doc"] != user["doctor_id"]:
        raise AuthError("You can only change your own appointments.")
    conn.execute("UPDATE appointments SET status=? WHERE id=?", (status, text(d, "id", 12)))


def cancel_appointment(conn, d, user=None):
    row = conn.execute("SELECT * FROM appointments WHERE id=?", (text(d, "id", 12).upper().lstrip("#"),)).fetchone()
    if not row or not same_phone(row["phone"], phone_of(d)):
        raise InputError("No booking with that ID and phone number")
    conn.execute("UPDATE appointments SET status='Cancelled', pay_status=CASE WHEN pay_status='paid' THEN 'refund_due' ELSE pay_status END WHERE id=?", (row["id"],))
    return {"id": row["id"]}


def add_alert(conn, d, user=None):
    conn.execute("INSERT INTO alerts(text, src, ts) VALUES(?,?,?)", (text(d, "text", 300), one_of(d, "src", SOURCES), now_ms()))


def set_live(conn, d, user=None):
    need_login(user)
    key = one_of(d, "key", DOCTOR_IDS | {"clinic"})
    if user["role"] == "doctor" and key != user["doctor_id"]:
        raise AuthError("You can only change your own availability.")
    conn.execute("INSERT OR REPLACE INTO live VALUES(?,?)", (key, 1 if d.get("value") else 0))


def count_chat(conn, d, user=None):
    conn.execute("INSERT INTO stats VALUES('chats',1) ON CONFLICT(key) DO UPDATE SET value=value+1")


def add_listing(conn, d, user=None):
    web = text(d, "web", 200, required=False)
    if web and not web.lower().startswith(("https://", "http://")):
        raise InputError("Website must start with https://")
    try:
        lat, lon = float(d.get("lat")), float(d.get("lon"))
    except (TypeError, ValueError):
        raise InputError("Address location missing")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise InputError("Address location invalid")
    if not d.get("consent"):
        raise InputError("Consent is required to publish a listing")
    conn.execute(
        "INSERT INTO listings(name,type,spec,phone,email,web,addr,city,country,cc,video,lat,lon,ts,social,hours,tz) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (text(d, "name", 100), one_of(d, "type", LIST_TYPES), text(d, "spec", 80, False), phone_of(d),
         text(d, "email", 120, False), web, text(d, "addr", 160), text(d, "city", 80), text(d, "country", 80),
         text(d, "cc", 2, False).upper(), 1 if d.get("video") else 0, lat, lon, now_ms(), json.dumps(clean_social(d.get("social")))) + clean_hours(d))


def delete_listing(conn, d, user=None):
    need_admin(user)
    conn.execute("DELETE FROM listings WHERE id=?", (int(d.get("id") or 0),))


def reset_demo(conn, d, user=None):
    need_admin(user)
    conn.executescript("DELETE FROM appointments; DELETE FROM alerts; DELETE FROM live; DELETE FROM stats;")
    seed(conn)



# ---------------------------------------------------------------- community: patient & doctor accounts
# Separate from the clinic staff logins above. Anyone can sign up as a patient or as a doctor.
# Doctors own one public listing (their profile), can go online/offline, and receive messages.
# Patients can follow doctors and message them.
MEMBER_KINDS = {"patient", "doctor"}
SOCIAL_KEYS = ("instagram", "facebook", "telegram", "whatsapp", "youtube", "linkedin", "x")
ONLINE_WINDOW_MS = 3 * 60 * 1000


def clean_social(raw):
    out = {}
    if not isinstance(raw, dict):
        return out
    for k in SOCIAL_KEYS:
        v = str(raw.get(k) or "").strip()[:150]
        if not v:
            continue
        if v.lower().startswith(("javascript:", "data:")) or any(c in v for c in '<>"'):
            raise InputError(f"The {k} link looks wrong")
        out[k] = v
    return out


HOURS_RE = re.compile(r"^(24/7|(?:(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:[-,](?:Mo|Tu|We|Th|Fr|Sa|Su))* \d{2}:\d{2}-\d{2}:\d{2}(?:,\d{2}:\d{2}-\d{2}:\d{2})*)(?:; ?(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:[-,](?:Mo|Tu|We|Th|Fr|Sa|Su))* \d{2}:\d{2}-\d{2}:\d{2}(?:,\d{2}:\d{2}-\d{2}:\d{2})*)*)$")
TZ_RE = re.compile(r"^[A-Za-z_]+(?:/[A-Za-z0-9_+\-]+){0,2}$")


def clean_hours(d):
    """Online / opening hours in the simple OpenStreetMap style, e.g. "Mo-Sa 09:00-18:00" or "24/7"."""
    hours = str(d.get("hours") or "").strip()[:160]
    tz = str(d.get("tz") or "").strip()[:64]
    if hours and not HOURS_RE.match(hours):
        raise InputError("Online hours look wrong. Pick days and times again.")
    if tz and not TZ_RE.match(tz):
        tz = ""
    return hours, tz


def public_listings(conn):
    cutoff = now_ms() - ONLINE_WINDOW_MS
    rows = conn.execute(
        "SELECT l.*, m.online AS m_online, m.last_seen AS m_seen, m.photo_ts AS owner_photo, "
        "(SELECT COUNT(*) FROM favs f WHERE f.listing_id = l.id) AS followers, "
        "(SELECT ROUND(AVG(stars), 1) FROM reviews r WHERE r.listing_id = l.id) AS rating, "
        "(SELECT COUNT(*) FROM reviews r WHERE r.listing_id = l.id) AS reviews, "
        "(SELECT COUNT(*) FROM gallery g WHERE g.listing_id = l.id) AS photos, "
        "(SELECT COUNT(*) FROM verifications v WHERE v.listing_id = l.id AND v.status = 'verified') AS verified "
        "FROM listings l LEFT JOIN members m ON m.id = l.owner ORDER BY l.ts")
    out = []
    for r in rows:
        d = dict(r)
        seen = d.pop("m_seen")
        d["online"] = bool(d.pop("m_online")) and (seen or 0) > cutoff
        d["last_seen"] = seen or None
        d["video"] = bool(d["video"])
        d["verified"] = bool(d.get("verified"))
        try:
            d["social"] = json.loads(d.get("social") or "{}")
        except ValueError:
            d["social"] = {}
        out.append(d)
    return out


def member_for_token(conn, token):
    if not token:
        return None
    row = conn.execute(
        "SELECT m.id, m.email, m.name, m.kind, m.city, m.online, m.photo_ts FROM member_sessions s JOIN members m ON m.id = s.member_id "
        "WHERE s.token = ? AND s.expires > ?", (token_hash(token), now_ms())).fetchone()
    if not row:
        return None
    conn.execute("UPDATE members SET last_seen=? WHERE id=?", (now_ms(), row["id"]))
    return dict(row)


def new_member_session(conn, member_id):
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM member_sessions WHERE expires < ?", (now_ms(),))
    conn.execute("INSERT INTO member_sessions VALUES(?,?,?)", (token_hash(token), member_id, now_ms() + 30 * 86_400_000))
    return token


def need_member(me, kind=None):
    if not me:
        raise AuthError("Please log in first.", 401)
    if kind and me["kind"] != kind:
        raise AuthError("Only doctor accounts can do this." if kind == "doctor" else "Only patient accounts can do this.")


def my_listing(conn, me):
    return conn.execute("SELECT * FROM listings WHERE owner=?", (me["id"],)).fetchone()


def member_state(conn, me):
    if not me:
        return {"me": None}
    lst = my_listing(conn, me)
    fav_ids = [r["listing_id"] for r in conn.execute("SELECT listing_id FROM favs WHERE member_id=? ORDER BY ts DESC", (me["id"],))]
    threads = []
    for r in conn.execute(
            "SELECT other, MAX(id) AS last_id FROM (SELECT to_id AS other, id FROM messages WHERE from_id=:me "
            "UNION ALL SELECT from_id AS other, id FROM messages WHERE to_id=:me) GROUP BY other ORDER BY last_id DESC LIMIT 50",
            {"me": me["id"]}):
        other = conn.execute("SELECT id, name, kind, photo_ts FROM members WHERE id=?", (r["other"],)).fetchone()
        last = conn.execute("SELECT body, ts, from_id FROM messages WHERE id=?", (r["last_id"],)).fetchone()
        unread = conn.execute("SELECT COUNT(*) FROM messages WHERE from_id=? AND to_id=? AND seen=0", (r["other"], me["id"])).fetchone()[0]
        if other:
            threads.append({"with": other["id"], "name": other["name"], "kind": other["kind"], "photo_ts": other["photo_ts"], "last": last["body"][:80],
                            "ts": last["ts"], "mine": last["from_id"] == me["id"], "unread": unread})
    has_pw = (conn.execute("SELECT pw FROM members WHERE id=?", (me["id"],)).fetchone() or {"pw": "!"})["pw"] != "!"
    notif_unread = conn.execute("SELECT COUNT(*) FROM notifs WHERE member_id=? AND seen=0", (me["id"],)).fetchone()[0]
    ver = conn.execute("SELECT reg_no, council, reg_year, qualification, cert, status, reason, submitted, reviewed FROM verifications "
                       "WHERE member_id=?", (me["id"],)).fetchone() if me["kind"] == "doctor" else None
    return {"me": dict(me, listing_id=lst["id"] if lst else None, has_password=has_pw), "notif_unread": notif_unread,
            "verification": dict(ver) if ver else None, "reminders": reminder_list(conn, me["id"]),
            "favs": fav_ids, "threads": threads,
            "listing": dict(lst, social=json.loads(lst["social"] or "{}"), video=bool(lst["video"])) if lst else None}


def m_signup(conn, d, me, ip):
    if too_many("signup", ip, 10, 3600):
        raise AuthError("Too many new accounts from this network. Try again later.", 429)
    kind = one_of(d, "kind", MEMBER_KINDS)
    email = valid_email(d)
    if conn.execute("SELECT 1 FROM members WHERE email=?", (email,)).fetchone():
        raise InputError("An account with this email already exists. Please log in.")
    if not d.get("agree"):
        raise InputError("Please accept the terms to create an account")
    cur = conn.execute("INSERT INTO members(email,name,kind,pw,created,city,last_seen) VALUES(?,?,?,?,?,?,?)",
                       (email, text(d, "name", 80), kind, hash_password(valid_password(d)), now_ms(),
                        text(d, "city", 80, False), now_ms()))
    welcome(conn, cur.lastrowid, kind)
    return cur.lastrowid


def m_login(conn, d, me, ip):
    if too_many_failures(ip):
        raise AuthError("Too many failed attempts. Try again in 15 minutes.", 429)
    row = conn.execute("SELECT id, pw FROM members WHERE email=?", (str(d.get("email") or "").strip().lower(),)).fetchone()
    if not row or not check_password(str(d.get("password") or ""), row["pw"]):
        FAILED_LOGINS.setdefault(ip, []).append(time.time())
        raise AuthError("Wrong email or password.", 401)
    return row["id"]


def m_profile(conn, d, me):
    """A doctor creates or updates their own public listing."""
    need_member(me, "doctor")
    web = text(d, "web", 200, required=False)
    if web and not web.lower().startswith(("https://", "http://")):
        raise InputError("Website must start with https://")
    try:
        lat, lon = float(d.get("lat")), float(d.get("lon"))
    except (TypeError, ValueError):
        raise InputError("Address location missing")
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise InputError("Address location invalid")
    vals = (text(d, "name", 100), one_of(d, "type", LIST_TYPES), text(d, "spec", 80, False), phone_of(d),
            text(d, "email", 120, False), web, text(d, "addr", 160), text(d, "city", 80), text(d, "country", 80),
            text(d, "cc", 2, False).upper(), 1 if d.get("video") else 0, lat, lon, json.dumps(clean_social(d.get("social")))) + clean_hours(d)
    lst = my_listing(conn, me)
    if lst:
        conn.execute("UPDATE listings SET name=?,type=?,spec=?,phone=?,email=?,web=?,addr=?,city=?,country=?,cc=?,video=?,lat=?,lon=?,social=?,hours=?,tz=? "
                     "WHERE id=?", vals + (lst["id"],))
    else:
        conn.execute("INSERT INTO listings(name,type,spec,phone,email,web,addr,city,country,cc,video,lat,lon,social,hours,tz,ts,owner) "
                     "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", vals + (now_ms(), me["id"]))


def m_status(conn, d, me):
    need_member(me, "doctor")
    conn.execute("UPDATE members SET online=?, last_seen=? WHERE id=?", (1 if d.get("online") else 0, now_ms(), me["id"]))


def m_fav(conn, d, me):
    need_member(me)
    lid = int(d.get("listing_id") or 0)
    if not conn.execute("SELECT 1 FROM listings WHERE id=?", (lid,)).fetchone():
        raise InputError("This doctor is no longer listed")
    if d.get("on"):
        conn.execute("INSERT OR IGNORE INTO favs VALUES(?,?,?)", (me["id"], lid, now_ms()))
    else:
        conn.execute("DELETE FROM favs WHERE member_id=? AND listing_id=?", (me["id"], lid))


def m_send(conn, d, me):
    need_member(me)
    to = int(d.get("to") or 0)
    if d.get("listing_id"):
        row = conn.execute("SELECT owner FROM listings WHERE id=?", (int(d["listing_id"]),)).fetchone()
        if not row or not row["owner"]:
            raise InputError("This doctor hasn't set up messaging yet")
        to = row["owner"]
    if to == me["id"] or not conn.execute("SELECT 1 FROM members WHERE id=?", (to,)).fetchone():
        raise InputError("Can't send to this person")
    # patients can message doctors; doctors can reply to anyone who wrote to them
    other_kind = conn.execute("SELECT kind FROM members WHERE id=?", (to,)).fetchone()["kind"]
    if me["kind"] == "patient" and other_kind != "doctor":
        raise AuthError("Patients can message doctors only.")
    if me["kind"] == "doctor" and other_kind == "patient" and not conn.execute(
            "SELECT 1 FROM messages WHERE from_id=? AND to_id=?", (to, me["id"])).fetchone():
        raise AuthError("You can reply once this patient has written to you.")
    if too_many("msg", str(me["id"]), 60, 3600):
        raise AuthError("You are sending messages too quickly. Please wait a little.", 429)
    body = text(d, "body", 2000)
    conn.execute("INSERT INTO messages(from_id,to_id,body,ts) VALUES(?,?,?,?)", (me["id"], to, body, now_ms()))
    notify(conn, to, "message", f"New message from {me['name']}", body[:90], "account")
    return {"to": to}


def m_thread(conn, d, me):
    need_member(me)
    other = int(d.get("with") or 0)
    o = conn.execute("SELECT id, name, kind, online, last_seen, photo_ts FROM members WHERE id=?", (other,)).fetchone()
    if not o:
        raise InputError("Conversation not found")
    conn.execute("UPDATE messages SET seen=1 WHERE from_id=? AND to_id=?", (other, me["id"]))
    msgs = [dict(r) for r in conn.execute(
        "SELECT id, from_id, body, ts FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) ORDER BY id DESC LIMIT 200",
        (me["id"], other, other, me["id"]))][::-1]
    online = bool(o["online"]) and o["last_seen"] > now_ms() - ONLINE_WINDOW_MS if o["kind"] == "doctor" else None
    return {"with": {"id": o["id"], "name": o["name"], "kind": o["kind"], "online": online, "photo_ts": o["photo_ts"]}, "messages": msgs}


AVATAR_DIR = DATA_DIR / "avatars"
MAX_PHOTO_BYTES = 300_000


def m_photo(conn, d, me):
    """Set or remove the profile photo. The browser crops and shrinks it to a small JPEG first."""
    need_member(me)
    f = AVATAR_DIR / f"{me['id']}.jpg"
    if d.get("remove"):
        f.unlink(missing_ok=True)
        conn.execute("UPDATE members SET photo_ts=NULL WHERE id=?", (me["id"],))
        return
    data = str(d.get("image") or "")
    prefix = "data:image/jpeg;base64,"
    if not data.startswith(prefix):
        raise InputError("Please choose a photo (JPG, PNG or HEIC)")
    try:
        raw = base64.b64decode(data[len(prefix):], validate=True)
    except ValueError:
        raise InputError("That photo could not be read")
    if len(raw) > MAX_PHOTO_BYTES:
        raise InputError("That photo is too large")
    if not raw.startswith(b"\xff\xd8\xff"):
        raise InputError("That file is not a photo")
    AVATAR_DIR.mkdir(parents=True, exist_ok=True)
    f.write_bytes(raw)
    conn.execute("UPDATE members SET photo_ts=? WHERE id=?", (now_ms(), me["id"]))




# ---------------------------------------------------------------- reviews (stars, text, emoji, safe GIF stickers) and work photos
GIF_IDS = {"thumbs", "heart", "clap", "stars", "thanks", "doctor", "getwell", "sad"}  # our own stickers in assets/gif/
GALLERY_DIR = DATA_DIR / "gallery"
MAX_GALLERY = 12
LINK_RE = re.compile(r"(https?://|www\.|\.com\b|\.in\b|\.net\b)", re.I)


def short_name(name):
    parts = str(name or "").split()
    if not parts:
        return "Patient"
    return parts[0] + (" " + parts[-1][0] + "." if len(parts) > 1 else "")


def listing_reviews(conn, lid, me=None):
    row = conn.execute("SELECT id, owner FROM listings WHERE id=?", (lid,)).fetchone()
    if not row:
        raise InputError("This doctor is no longer listed")
    revs = []
    for r in conn.execute("SELECT r.*, m.name, m.photo_ts, m.kind FROM reviews r JOIN members m ON m.id = r.member_id "
                          "WHERE r.listing_id=? ORDER BY r.ts DESC LIMIT 200", (lid,)):
        revs.append({"id": r["id"], "stars": r["stars"], "body": r["body"], "gif": r["gif"], "ts": r["ts"],
                     "name": short_name(r["name"]), "member_id": r["member_id"], "photo_ts": r["photo_ts"] if r["kind"] == "doctor" else None,
                     "reply": r["reply"], "reply_ts": r["reply_ts"], "mine": bool(me and me["id"] == r["member_id"])})
    dist = {str(i): 0 for i in range(1, 6)}
    for r in revs:
        dist[str(r["stars"])] += 1
    avg = round(sum(r["stars"] for r in revs) / len(revs), 1) if revs else None
    photos = [dict(g) for g in conn.execute("SELECT id, caption, ts FROM gallery WHERE listing_id=? ORDER BY ts DESC", (lid,))]
    owner = bool(me and row["owner"] == me["id"])
    videos = []
    for v in conn.execute("SELECT v.*, m.name FROM videos v JOIN members m ON m.id=v.member_id WHERE v.listing_id=? ORDER BY v.ts DESC", (lid,)):
        mine = bool(me and v["member_id"] == me["id"])
        if v["status"] == "live" or owner or mine:
            videos.append({"id": v["id"], "kind": v["kind"], "caption": v["caption"], "status": v["status"], "ts": v["ts"],
                           "name": short_name(v["name"]), "mine": mine})
    return {"listing_id": lid, "avg": avg, "count": len(revs), "dist": dist, "reviews": revs, "photos": photos, "videos": videos,
            "is_owner": bool(me and row["owner"] == me["id"])}


def m_review(conn, d, me):
    need_member(me)
    lid = int(d.get("listing_id") or 0)
    row = conn.execute("SELECT owner FROM listings WHERE id=?", (lid,)).fetchone()
    if not row:
        raise InputError("This doctor is no longer listed")
    if row["owner"] == me["id"]:
        raise AuthError("You can't review your own profile.")
    if too_many("review", str(me["id"]), 20, 3600):
        raise AuthError("Too many reviews. Please try again later.", 429)
    try:
        stars = int(d.get("stars"))
    except (TypeError, ValueError):
        stars = 0
    if not 1 <= stars <= 5:
        raise InputError("Please pick 1 to 5 stars")
    body = str(d.get("body") or "").strip()[:1000]
    if len(body) < 3:
        raise InputError("Please write a few words about your visit")
    if LINK_RE.search(body):
        raise InputError("Please don't put links in reviews")
    gif = str(d.get("gif") or "") or None
    if gif and gif not in GIF_IDS:
        raise InputError("Please pick one of the stickers")
    conn.execute("INSERT INTO reviews(listing_id,member_id,stars,body,gif,ts) VALUES(?,?,?,?,?,?) "
                 "ON CONFLICT(listing_id, member_id) DO UPDATE SET stars=excluded.stars, body=excluded.body, gif=excluded.gif, ts=excluded.ts",
                 (lid, me["id"], stars, body, gif, now_ms()))
    if row["owner"]:
        notify(conn, row["owner"], "review", f"New {stars}★ review from {short_name(me['name'])}", body[:90], f"reviews:{lid}")
    return listing_reviews(conn, lid, me)


def m_review_delete(conn, d, me):
    need_member(me)
    r = conn.execute("SELECT listing_id, member_id FROM reviews WHERE id=?", (int(d.get("id") or 0),)).fetchone()
    if not r or r["member_id"] != me["id"]:
        raise AuthError("You can only remove your own review.")
    conn.execute("DELETE FROM reviews WHERE id=?", (int(d["id"]),))
    return listing_reviews(conn, r["listing_id"], me)


def m_review_reply(conn, d, me):
    """The doctor answers a review once (public), like a business owner reply."""
    need_member(me, "doctor")
    r = conn.execute("SELECT r.listing_id, l.owner FROM reviews r JOIN listings l ON l.id=r.listing_id WHERE r.id=?",
                     (int(d.get("id") or 0),)).fetchone()
    if not r or r["owner"] != me["id"]:
        raise AuthError("You can only reply to reviews on your own profile.")
    reply = str(d.get("reply") or "").strip()[:600]
    if reply and LINK_RE.search(reply):
        raise InputError("Please don't put links in replies")
    conn.execute("UPDATE reviews SET reply=?, reply_ts=? WHERE id=?", (reply or None, now_ms() if reply else None, int(d["id"])))
    if reply:
        author = conn.execute("SELECT member_id FROM reviews WHERE id=?", (int(d["id"]),)).fetchone()
        if author:
            notify(conn, author["member_id"], "reply", f"{me['name']} replied to your review", reply[:90], f"reviews:{r['listing_id']}")
    return listing_reviews(conn, r["listing_id"], me)


def m_gallery_add(conn, d, me):
    need_member(me, "doctor")
    lst = my_listing(conn, me)
    if not lst:
        raise InputError("Save your public profile first")
    if conn.execute("SELECT COUNT(*) FROM gallery WHERE listing_id=?", (lst["id"],)).fetchone()[0] >= MAX_GALLERY:
        raise InputError(f"You can show up to {MAX_GALLERY} photos. Remove one first.")
    data = str(d.get("image") or "")
    prefix = "data:image/jpeg;base64,"
    if not data.startswith(prefix):
        raise InputError("Please choose a photo")
    try:
        raw = base64.b64decode(data[len(prefix):], validate=True)
    except ValueError:
        raise InputError("That photo could not be read")
    if len(raw) > 900_000 or not raw.startswith(b"\xff\xd8\xff"):
        raise InputError("That photo could not be used. Try another one.")
    caption = str(d.get("caption") or "").strip()[:140]
    cur = conn.execute("INSERT INTO gallery(listing_id, caption, ts) VALUES(?,?,?)", (lst["id"], caption, now_ms()))
    GALLERY_DIR.mkdir(parents=True, exist_ok=True)
    (GALLERY_DIR / f"{cur.lastrowid}.jpg").write_bytes(raw)
    return listing_reviews(conn, lst["id"], me)


def m_gallery_delete(conn, d, me):
    need_member(me, "doctor")
    lst = my_listing(conn, me)
    gid = int(d.get("id") or 0)
    if not lst or not conn.execute("SELECT 1 FROM gallery WHERE id=? AND listing_id=?", (gid, lst["id"])).fetchone():
        raise AuthError("You can only remove your own photos.")
    conn.execute("DELETE FROM gallery WHERE id=?", (gid,))
    (GALLERY_DIR / f"{gid}.jpg").unlink(missing_ok=True)
    return listing_reviews(conn, lst["id"], me)


def m_reviews(conn, d, me):
    return listing_reviews(conn, int(d.get("listing_id") or 0), me)

# ---------------------------------------------------------------- reminders (medicine, appointments, check-ups...)
# Each reminder fires at a local time in the person's own time zone: once on a date, or on chosen weekdays.
# A background thread puts due ones in the 🔔 bell (the open page also shows a pop-up) and emails them if asked.
REMINDER_KINDS = {"medicine": "💊", "appointment": "📅", "checkup": "🩺", "water": "💧", "exercise": "🧘", "other": "⏰"}
REMINDER_MAX = 30
HHMM_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _zone(tz):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz)
    except Exception:
        return datetime.timezone.utc


def reminder_next(r, after_ms):
    """The next time (ms) this reminder should fire after after_ms, or None when it never will again."""
    zone = _zone(r["tz"])
    h, m = map(int, r["at"].split(":"))
    lead = datetime.timedelta(minutes=int(r["lead"] or 0))
    if not r["days"]:
        try:
            day = datetime.date.fromisoformat(r["date"] or "")
        except ValueError:
            return None
        ms = int((datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=zone) - lead).timestamp() * 1000)
        return ms if ms > after_ms else None
    start = datetime.datetime.fromtimestamp(after_ms / 1000, zone).date() - datetime.timedelta(days=1)
    for i in range(10):
        day = start + datetime.timedelta(days=i)
        if r["days"] & (1 << day.weekday()):  # bit 0 = Monday … bit 6 = Sunday
            ms = int((datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=zone) - lead).timestamp() * 1000)
            if ms > after_ms:
                return ms
    return None


def reminder_list(conn, mid):
    return [dict(r) for r in conn.execute("SELECT id, kind, title, note, at, days, date, tz, lead, email, active, next_at, last_sent "
                                          "FROM reminders WHERE member_id=? ORDER BY active DESC, COALESCE(next_at, 9e15), id", (mid,))]


def m_reminder_save(conn, d, me):
    need_member(me)
    if too_many("reminder", str(me["id"]), 60, 3600):
        raise AuthError("Too many changes. Please wait a little.", 429)
    rid = int(d.get("id") or 0)
    if rid and not conn.execute("SELECT 1 FROM reminders WHERE id=? AND member_id=?", (rid, me["id"])).fetchone():
        raise InputError("Reminder not found")
    if not rid and conn.execute("SELECT COUNT(*) FROM reminders WHERE member_id=?", (me["id"],)).fetchone()[0] >= REMINDER_MAX:
        raise InputError(f"You can keep up to {REMINDER_MAX} reminders. Delete an old one first.")
    kind = one_of(d, "kind", set(REMINDER_KINDS))
    title = text(d, "title", 80)
    at = str(d.get("at") or "")
    if not HHMM_RE.match(at):
        raise InputError("Pick a time")
    try:
        days = int(d.get("days") or 0)
    except (TypeError, ValueError):
        days = -1
    if not 0 <= days <= 127:
        raise InputError("Pick the days again")
    date = None
    if not days:
        date = str(d.get("date") or "")
        if not DATE_RE.match(date):
            raise InputError("Pick a date, or choose days to repeat")
    tz = str(d.get("tz") or "UTC").strip()[:64]
    if not TZ_RE.match(tz) or _zone(tz) is datetime.timezone.utc:
        tz = "UTC"
    lead = int(d.get("lead") or 0)
    if not 0 <= lead <= 7 * 1440:
        raise InputError("Reminder can be at most a week before")
    r = {"at": at, "days": days, "date": date, "tz": tz, "lead": lead}
    nxt = reminder_next(r, now_ms())
    if nxt is None:
        raise InputError("That time has already passed. Pick a time in the future.")
    vals = (kind, title, text(d, "note", 200, False), at, days, date, tz, lead, 1 if d.get("email") else 0, nxt)
    if rid:
        conn.execute("UPDATE reminders SET kind=?,title=?,note=?,at=?,days=?,date=?,tz=?,lead=?,email=?,next_at=?,active=1 WHERE id=?", vals + (rid,))
    else:
        rid = conn.execute("INSERT INTO reminders(kind,title,note,at,days,date,tz,lead,email,next_at,member_id,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           vals + (me["id"], now_ms())).lastrowid
    return {"id": rid, "next_at": nxt}


def m_reminder_toggle(conn, d, me):
    need_member(me)
    r = conn.execute("SELECT * FROM reminders WHERE id=? AND member_id=?", (int(d.get("id") or 0), me["id"])).fetchone()
    if not r:
        raise InputError("Reminder not found")
    if d.get("on"):
        nxt = reminder_next(r, now_ms())
        if nxt is None:
            raise InputError("That time has already passed. Edit the reminder to pick a new time.")
        conn.execute("UPDATE reminders SET active=1, next_at=? WHERE id=?", (nxt, r["id"]))
    else:
        conn.execute("UPDATE reminders SET active=0 WHERE id=?", (r["id"],))


def m_reminder_delete(conn, d, me):
    need_member(me)
    conn.execute("DELETE FROM reminders WHERE id=? AND member_id=?", (int(d.get("id") or 0), me["id"]))


def _when_text(lead):
    if not lead:
        return "now"
    return f"in {lead // 1440} day{'s' if lead >= 2880 else ''}" if lead % 1440 == 0 else \
        f"in {lead // 60} hour{'s' if lead >= 120 else ''}" if lead % 60 == 0 else f"in {lead} minutes"


def fire_due_reminders(conn, now=None):
    """Sends every reminder that is due. Ones missed while the server was off by more than 6 hours are skipped, not sent late."""
    now = now or now_ms()
    sent = 0
    for r in conn.execute("SELECT r.*, m.email AS m_email, m.name AS m_name FROM reminders r JOIN members m ON m.id=r.member_id "
                          "WHERE r.active=1 AND r.next_at<=? LIMIT 500", (now,)).fetchall():
        if now - r["next_at"] < 6 * 3600_000:
            icon = REMINDER_KINDS.get(r["kind"], "⏰")
            title = f"{icon} {r['title']}" + ("" if not r["lead"] else f" ({_when_text(r['lead'])} at {r['at']})")
            notify(conn, r["member_id"], "reminder", title, r["note"] or ("Time for your reminder." if not r["lead"] else ""), "reminders")
            if r["email"] and r["m_email"]:
                link = f"{PUBLIC_URL.rstrip('/')}/#reminders"
                body = f"Hi {r['m_name']},\n\n{title}\n{r['note'] or ''}\n\nManage your reminders: {link}\n\nClinora"
                html_body = (f"<p>Hi {html.escape(r['m_name'])},</p><p style='font-size:18px'><b>{html.escape(title)}</b></p>"
                             f"<p>{html.escape(r['note'] or '')}</p><p><a href='{html.escape(link)}'>Manage your reminders</a></p><p>Clinora</p>")
                send_email(r["m_email"], f"Reminder: {r['title']}", body, html_body)
            sent += 1
        nxt = reminder_next(r, max(now, r["next_at"]))
        conn.execute("UPDATE reminders SET last_sent=?, next_at=?, active=? WHERE id=?", (now, nxt, 1 if nxt else 0, r["id"]))
    return sent


def reminder_loop():
    while True:
        try:
            with DB_LOCK, connect() as conn:
                fire_due_reminders(conn)
        except Exception as e:
            print(f"[reminders] {type(e).__name__}: {e}", flush=True)
        time.sleep(20)


def m_delete_account(conn, d, me, ip):
    """Permanently removes the account and everything it created: profile, photos, work photos, reviews,
    messages, follows and sessions. Needs the password again, so nobody can do it from an unlocked phone by accident."""
    need_member(me)
    if too_many_failures(ip):
        raise AuthError("Too many failed attempts. Try again in 15 minutes.", 429)
    row = conn.execute("SELECT pw FROM members WHERE id=?", (me["id"],)).fetchone()
    if row and row["pw"] == "!":  # signed up with Google / Facebook / X and never set a password
        if str(d.get("confirm") or "").strip().upper() != "DELETE":
            raise InputError('Type DELETE to confirm.')
    elif not row or not check_password(str(d.get("password") or ""), row["pw"]):
        FAILED_LOGINS.setdefault(ip, []).append(time.time())
        raise AuthError("That password is not right.", 401)
    mid = me["id"]
    for v in conn.execute("SELECT v.id, v.mime FROM videos v LEFT JOIN listings l ON l.id=v.listing_id "
                          "WHERE v.member_id=? OR l.owner=?", (mid, mid)).fetchall():
        video_file(v["id"], v["mime"]).unlink(missing_ok=True)
        conn.execute("DELETE FROM videos WHERE id=?", (v["id"],))
    conn.execute("DELETE FROM notifs WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM verifications WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM reminders WHERE member_id=?", (mid,))
    (VERIFY_DIR / f"{mid}.jpg").unlink(missing_ok=True)
    for (lid,) in conn.execute("SELECT id FROM listings WHERE owner=?", (mid,)).fetchall():
        for (gid,) in conn.execute("SELECT id FROM gallery WHERE listing_id=?", (lid,)).fetchall():
            (GALLERY_DIR / f"{gid}.jpg").unlink(missing_ok=True)
        conn.execute("DELETE FROM gallery WHERE listing_id=?", (lid,))
        conn.execute("DELETE FROM reviews WHERE listing_id=?", (lid,))
        conn.execute("DELETE FROM favs WHERE listing_id=?", (lid,))
        conn.execute("DELETE FROM listings WHERE id=?", (lid,))
    conn.execute("DELETE FROM reviews WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM favs WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM messages WHERE from_id=? OR to_id=?", (mid, mid))
    conn.execute("DELETE FROM member_sessions WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM call_signals WHERE room LIKE ? OR room LIKE ?", (f"M{mid}-%", f"M%-{mid}"))
    conn.execute("DELETE FROM members WHERE id=?", (mid,))
    (AVATAR_DIR / f"{mid}.jpg").unlink(missing_ok=True)
    RINGS.pop(mid, None)



# ---------------------------------------------------------------- notifications (the bell)
NOTIF_KINDS = {"welcome", "message", "review", "reply", "call", "video", "security", "reminder"}


def notify(conn, member_id, kind, title, body="", link=""):
    if not member_id:
        return
    conn.execute("INSERT INTO notifs(member_id,kind,title,body,link,ts) VALUES(?,?,?,?,?,?)",
                 (member_id, kind if kind in NOTIF_KINDS else "welcome", str(title)[:120], str(body or "")[:200], str(link or "")[:60], now_ms()))
    # keep the newest 100 per person
    conn.execute("DELETE FROM notifs WHERE member_id=? AND id NOT IN (SELECT id FROM notifs WHERE member_id=? ORDER BY id DESC LIMIT 100)",
                 (member_id, member_id))


def welcome(conn, member_id, kind):
    notify(conn, member_id, "welcome", "Welcome to Clinora! 👋",
           "Complete your public profile so patients can find you." if kind == "doctor" else "Follow doctors you trust and message them any time.",
           "account")


def m_notifs(conn, d, me):
    need_member(me)
    rows = [dict(r) for r in conn.execute("SELECT id, kind, title, body, link, ts, seen FROM notifs WHERE member_id=? ORDER BY id DESC LIMIT 50", (me["id"],))]
    unread = sum(1 for r in rows if not r["seen"])
    return {"notifs": rows, "unread": unread}


def m_notifs_read(conn, d, me):
    need_member(me)
    if d.get("id"):
        conn.execute("UPDATE notifs SET seen=1 WHERE member_id=? AND id=?", (me["id"], int(d["id"])))
    else:
        conn.execute("UPDATE notifs SET seen=1 WHERE member_id=?", (me["id"],))
    return m_notifs(conn, d, me)


# ---------------------------------------------------------------- change / set password (any time)
def m_password(conn, d, me, ip):
    need_member(me)
    row = conn.execute("SELECT pw FROM members WHERE id=?", (me["id"],)).fetchone()
    if row["pw"] != "!":  # accounts that already have a password must confirm the current one
        if too_many_failures(ip):
            raise AuthError("Too many failed attempts. Try again in 15 minutes.", 429)
        if not check_password(str(d.get("current") or ""), row["pw"]):
            FAILED_LOGINS.setdefault(ip, []).append(time.time())
            raise AuthError("Your current password is not right.", 401)
    new = valid_password(d, "new")
    if row["pw"] != "!" and check_password(new, row["pw"]):
        raise InputError("The new password must be different from the old one.")
    conn.execute("UPDATE members SET pw=? WHERE id=?", (hash_password(new), me["id"]))
    notify(conn, me["id"], "security", "Your password was changed",
           "If this wasn't you, change it again right away and contact the clinic.", "account")
    return {"changed": True}




# ---------------------------------------------------------------- doctor verification (registration checked by the clinic admin)
# Details and the certificate photo are private: only the doctor and the Clinora admin see them. The public sees a ✓ badge.
COUNCILS = ["National Medical Commission (NMC)", "Dental Council of India (DCI)", "Andhra Pradesh Medical Council", "Arunachal Pradesh Medical Council",
            "Assam Medical Council", "Bihar Medical Council", "Chhattisgarh Medical Council", "Delhi Medical Council", "Goa Medical Council",
            "Gujarat Medical Council", "Haryana Medical Council", "Himachal Pradesh Medical Council", "Jammu & Kashmir Medical Council",
            "Jharkhand Medical Council", "Karnataka Medical Council", "Kerala (Travancore-Cochin) Medical Council", "Madhya Pradesh Medical Council",
            "Maharashtra Medical Council", "Manipur Medical Council", "Meghalaya Medical Council", "Mizoram Medical Council", "Nagaland Medical Council",
            "Odisha Council of Medical Registration", "Punjab Medical Council", "Rajasthan Medical Council", "Sikkim Medical Council",
            "Tamil Nadu Medical Council", "Telangana State Medical Council", "Tripura State Medical Council", "Uttar Pradesh Medical Council",
            "Uttarakhand Medical Council", "West Bengal Medical Council", "State Dental Council", "Medical council outside India"]
VERIFY_DIR = DATA_DIR / "verify"
REG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9/ .-]{1,29}$")


def m_verify_submit(conn, d, me):
    need_member(me, "doctor")
    lst = my_listing(conn, me)
    if not lst:
        raise InputError("Save your public profile first")
    reg = str(d.get("reg_no") or "").strip()
    if not REG_RE.match(reg):
        raise InputError("Enter your registration number as it appears on your certificate")
    council = str(d.get("council") or "")
    if council not in COUNCILS:
        raise InputError("Please choose your medical council")
    try:
        year = int(d.get("reg_year"))
    except (TypeError, ValueError):
        year = 0
    if not 1950 <= year <= datetime.date.today().year:
        raise InputError("Please enter the year you were registered")
    qual = text(d, "qualification", 80)
    if not d.get("confirm"):
        raise InputError("Please confirm the details are true")
    if too_many("verify", str(me["id"]), 6, 86400):
        raise AuthError("Too many requests today. Please try again tomorrow.", 429)
    old = conn.execute("SELECT cert FROM verifications WHERE member_id=?", (me["id"],)).fetchone()
    cert = 1 if old and old["cert"] else 0
    img = str(d.get("certificate") or "")
    if img:
        prefix = "data:image/jpeg;base64,"
        try:
            raw = base64.b64decode(img[len(prefix):], validate=True) if img.startswith(prefix) else b""
        except ValueError:
            raw = b""
        if not raw.startswith(b"\xff\xd8\xff") or len(raw) > 1_200_000:
            raise InputError("That certificate photo could not be used. Try another one.")
        VERIFY_DIR.mkdir(parents=True, exist_ok=True)
        (VERIFY_DIR / f"{me['id']}.jpg").write_bytes(raw)
        cert = 1
    conn.execute("INSERT INTO verifications(member_id, listing_id, reg_no, council, reg_year, qualification, cert, status, submitted) "
                 "VALUES(?,?,?,?,?,?,?,'pending',?) ON CONFLICT(member_id) DO UPDATE SET listing_id=excluded.listing_id, reg_no=excluded.reg_no, "
                 "council=excluded.council, reg_year=excluded.reg_year, qualification=excluded.qualification, cert=excluded.cert, "
                 "status='pending', reason=NULL, submitted=excluded.submitted, reviewed=NULL, reviewer=NULL",
                 (me["id"], lst["id"], reg, council, year, qual, cert, now_ms()))
    notify(conn, me["id"], "security", "Verification request received",
           "We'll check your registration and tell you here. This usually takes 1 to 2 working days.", "account")


def verify_queue(conn, d, user):
    need_admin(user)
    rows = conn.execute("SELECT v.*, m.name AS doctor, m.email, l.name AS listing_name, l.city, l.spec FROM verifications v "
                        "JOIN members m ON m.id = v.member_id LEFT JOIN listings l ON l.id = v.listing_id "
                        "ORDER BY CASE v.status WHEN 'pending' THEN 0 ELSE 1 END, v.submitted DESC LIMIT 100")
    return {"verifications": [dict(r) for r in rows], "councils": COUNCILS}


def verify_decide(conn, d, user):
    need_admin(user)
    mid = int(d.get("member_id") or 0)
    v = conn.execute("SELECT * FROM verifications WHERE member_id=?", (mid,)).fetchone()
    if not v:
        raise InputError("Request not found")
    if d.get("approve"):
        conn.execute("UPDATE verifications SET status='verified', reason=NULL, reviewed=?, reviewer=? WHERE member_id=?",
                     (now_ms(), user["name"], mid))
        notify(conn, mid, "security", "✅ You are verified!", "Patients now see a Verified badge on your profile.", "account")
    else:
        reason = str(d.get("reason") or "").strip()[:200]
        if len(reason) < 5:
            raise InputError("Please write the reason, so the doctor can fix it")
        conn.execute("UPDATE verifications SET status='rejected', reason=?, reviewed=?, reviewer=? WHERE member_id=?",
                     (reason, now_ms(), user["name"], mid))
        notify(conn, mid, "security", "Verification not approved yet", reason, "account")
    return verify_queue(conn, d, user)

# ---------------------------------------------------------------- forgot password: a one-time link by email
# Email is sent with any SMTP service (Brevo, Gmail app password, Resend, Zoho...). See docs/email-setup.md.
SMTP_HOST = os.environ.get("SMTP_HOST", "").strip()
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587") or 587)
SMTP_USER = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS = os.environ.get("SMTP_PASS", "").strip()
MAIL_FROM = os.environ.get("MAIL_FROM", "").strip() or SMTP_USER
RESET_MINUTES = 30


def send_email(to, subject, text_body, html_body):
    """Sends in the background so the reply time never shows whether an account exists."""
    if not SMTP_HOST:
        if PRODUCTION:
            print(f"[email] NOT SENT to {to}: SMTP_HOST is not set in .env", flush=True)
        else:  # on your own computer: the link is printed here so you can test without an email service
            print(f"[email] (dev, not sent) To: {to} | {subject}\n{text_body}", flush=True)
        return
    def run():
        import smtplib
        from email.message import EmailMessage
        msg = EmailMessage()
        msg["Subject"], msg["From"], msg["To"] = subject, f"Clinora <{MAIL_FROM}>", to
        msg.set_content(text_body)
        msg.add_alternative(html_body, subtype="html")
        try:
            if SMTP_PORT == 465:
                with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                    if SMTP_USER: s.login(SMTP_USER, SMTP_PASS)
                    s.send_message(msg)
            else:
                with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=20) as s:
                    s.ehlo()
                    if s.has_extn("starttls"):
                        s.starttls()
                        s.ehlo()
                    elif SMTP_USER:  # never send the email password over an unencrypted connection
                        raise RuntimeError("this mail server doesn't offer encryption (STARTTLS); use port 465 or another server")
                    if SMTP_USER: s.login(SMTP_USER, SMTP_PASS)
                    s.send_message(msg)
            print(f"[email] sent '{subject}' to {to}", flush=True)
        except Exception as e:
            print(f"[email] FAILED to {to}: {type(e).__name__}: {e}", flush=True)
    threading.Thread(target=run, daemon=True).start()


def m_forgot(conn, d, ip):
    """Always answers the same way, so nobody can use this to find out who has an account."""
    email = str(d.get("email") or "").strip().lower()
    if too_many("forgot", ip, 8, 3600) or (email and too_many("forgot:" + email, "x", 3, 3600)):
        raise AuthError("Too many reset requests. Please wait an hour and try again.", 429)
    if not EMAIL_RE.match(email):
        raise InputError("Please enter a valid email address")
    row = conn.execute("SELECT id, name FROM members WHERE email=?", (email,)).fetchone()
    if row and not email.endswith("@users.clinora.invalid"):
        token = secrets.token_urlsafe(32)
        conn.execute("DELETE FROM pw_resets WHERE expires < ? OR member_id=?", (now_ms(), row["id"]))
        conn.execute("INSERT INTO pw_resets(token, member_id, expires) VALUES(?,?,?)",
                     (token_hash(token), row["id"], now_ms() + RESET_MINUTES * 60_000))
        link = f"{PUBLIC_URL}/#reset/{token}"
        first = (row["name"] or "there").split()[0]
        send_email(email, "Reset your Clinora password",
                   f"Hi {first},\n\nSomeone (hopefully you) asked to reset your Clinora password.\n\n"
                   f"Open this link to choose a new password. It works once, for {RESET_MINUTES} minutes:\n{link}\n\n"
                   "If you didn't ask for this, ignore this email. Your password stays the same.\n\nClinora",
                   f"""<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:480px;margin:auto;padding:24px;color:#0f172a">
<h2 style="color:#0d9488;margin:0 0 12px">Reset your Clinora password</h2>
<p>Hi {first},</p><p>Someone (hopefully you) asked to reset your Clinora password.</p>
<p style="margin:26px 0"><a href="{link}" style="background:#0d9488;color:#fff;padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:700">Choose a new password</a></p>
<p style="color:#475569;font-size:14px">This link works once, for {RESET_MINUTES} minutes. If you didn't ask for this, ignore this email: your password stays the same.</p>
<p style="color:#94a3b8;font-size:12px;margin-top:28px">Clinora · AI receptionist for clinics</p></div>""")
    return {"sent": True}


def m_reset(conn, d):
    token = str(d.get("token") or "")
    row = conn.execute("SELECT member_id, expires, used FROM pw_resets WHERE token=?", (token_hash(token),)).fetchone() if token else None
    if not row or row["used"] or row["expires"] < now_ms():
        raise AuthError("This reset link has expired or was already used. Please ask for a new one.", 400)
    new = valid_password(d, "new")
    mid = row["member_id"]
    conn.execute("UPDATE members SET pw=? WHERE id=?", (hash_password(new), mid))
    conn.execute("UPDATE pw_resets SET used=1 WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM member_sessions WHERE member_id=?", (mid,))  # log out everywhere
    notify(conn, mid, "security", "Your password was reset",
           "You used a reset link from your email. If this wasn't you, reset it again right away.", "account")
    return mid

# ---------------------------------------------------------------- log in with Google, Facebook or X
# Each one switches on when its keys are in .env (see docs/social-login.md). Until then the buttons show "coming soon".
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
FACEBOOK_APP_ID = os.environ.get("FACEBOOK_APP_ID", "").strip()
FACEBOOK_APP_SECRET = os.environ.get("FACEBOOK_APP_SECRET", "").strip()
X_CLIENT_ID = os.environ.get("X_CLIENT_ID", "").strip()
X_CLIENT_SECRET = os.environ.get("X_CLIENT_SECRET", "").strip()
OAUTH_STATES = {}  # state -> {"prov", "kind", "verifier", "ts"}


def oauth_status():
    return {"google": bool(GOOGLE_CLIENT_ID), "google_client_id": GOOGLE_CLIENT_ID,
            "facebook": bool(FACEBOOK_APP_ID and FACEBOOK_APP_SECRET), "x": bool(X_CLIENT_ID and X_CLIENT_SECRET)}


def oauth_redirect_uri(prov):
    return f"{PUBLIC_URL}/api/m/oauth/{prov}/callback"


def social_member(conn, prov, pid, email, name, kind):
    """Find the account for this Google / Facebook / X user, link it to an existing email account, or create one."""
    pid = str(pid or "").strip()
    if not pid:
        raise InputError("The sign-in provider did not return an account id.")
    row = conn.execute("SELECT id FROM members WHERE provider=? AND provider_id=?", (prov, pid)).fetchone()
    if row:
        return row["id"]
    email = str(email or "").strip().lower()
    if email:
        row = conn.execute("SELECT id FROM members WHERE email=?", (email,)).fetchone()
        if row:  # the provider confirmed this email, so it's the same person: link the accounts
            conn.execute("UPDATE members SET provider=COALESCE(provider, ?), provider_id=COALESCE(provider_id, ?) WHERE id=?",
                         (prov, pid, row["id"]))
            return row["id"]
    kind = kind if kind in MEMBER_KINDS else "patient"
    cur = conn.execute("INSERT INTO members(email,name,kind,pw,created,last_seen,provider,provider_id) VALUES(?,?,?,?,?,?,?,?)",
                       (email or f"{prov}-{pid}@users.clinora.invalid", (str(name or "").strip() or "Clinora user")[:80], kind, "!",
                        now_ms(), now_ms(), prov, pid))
    welcome(conn, cur.lastrowid, kind)
    return cur.lastrowid


def google_login(conn, d):
    if not GOOGLE_CLIENT_ID:
        raise InputError("Google login is coming soon.")
    cred = str(d.get("credential") or "")
    if not cred or len(cred) > 5000:
        raise InputError("Google sign-in failed. Please try again.")
    try:
        info = http_json("GET", "https://oauth2.googleapis.com/tokeninfo?id_token=" + urllib.parse.quote(cred))
    except ProviderError:
        raise AuthError("Google could not confirm this sign-in. Please try again.", 401)
    if info.get("aud") != GOOGLE_CLIENT_ID or info.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
        raise AuthError("This Google sign-in is not for Clinora.", 401)
    if str(info.get("email_verified")).lower() != "true":
        raise AuthError("Please verify your Google email first.", 401)
    if int(info.get("exp") or 0) < time.time():
        raise AuthError("This Google sign-in expired. Please try again.", 401)
    return social_member(conn, "google", info.get("sub"), info.get("email"), info.get("name"), str(d.get("kind") or "patient"))


def oauth_start_url(prov, kind):
    for k, v in list(OAUTH_STATES.items()):
        if v["ts"] < time.time() - 600:
            OAUTH_STATES.pop(k, None)
    state = secrets.token_urlsafe(24)
    rec = {"prov": prov, "kind": kind if kind in MEMBER_KINDS else "patient", "ts": time.time()}
    if prov == "facebook":
        OAUTH_STATES[state] = rec
        return "https://www.facebook.com/v19.0/dialog/oauth?" + urllib.parse.urlencode(
            {"client_id": FACEBOOK_APP_ID, "redirect_uri": oauth_redirect_uri("facebook"), "state": state, "scope": "email,public_profile"})
    if prov == "x":
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        OAUTH_STATES[state] = dict(rec, verifier=verifier)
        return "https://x.com/i/oauth2/authorize?" + urllib.parse.urlencode(
            {"response_type": "code", "client_id": X_CLIENT_ID, "redirect_uri": oauth_redirect_uri("x"), "state": state,
             "scope": "users.read tweet.read users.email", "code_challenge": challenge, "code_challenge_method": "S256"})
    raise InputError("Unknown sign-in provider")


def oauth_finish(conn, prov, query):
    state = (query.get("state") or [""])[0]
    rec = OAUTH_STATES.pop(state, None)
    if not rec or rec["prov"] != prov or rec["ts"] < time.time() - 600:
        raise AuthError("This sign-in link expired. Please try again.", 400)
    code = (query.get("code") or [""])[0]
    if not code:
        raise AuthError("Sign-in was cancelled.", 400)
    if prov == "facebook":
        tok = http_json("GET", "https://graph.facebook.com/v19.0/oauth/access_token?" + urllib.parse.urlencode(
            {"client_id": FACEBOOK_APP_ID, "client_secret": FACEBOOK_APP_SECRET, "redirect_uri": oauth_redirect_uri("facebook"), "code": code}))
        me = http_json("GET", "https://graph.facebook.com/me?" + urllib.parse.urlencode(
            {"fields": "id,name,email", "access_token": tok.get("access_token", "")}))
        return social_member(conn, "facebook", me.get("id"), me.get("email"), me.get("name"), rec["kind"])
    if prov == "x":
        tok = http_json("POST", "https://api.x.com/2/oauth2/token", auth=(X_CLIENT_ID, X_CLIENT_SECRET),
                        form={"code": code, "grant_type": "authorization_code", "redirect_uri": oauth_redirect_uri("x"),
                              "code_verifier": rec["verifier"], "client_id": X_CLIENT_ID})
        me = http_json("GET", "https://api.x.com/2/users/me?user.fields=confirmed_email", bearer=tok.get("access_token", "")).get("data", {})
        return social_member(conn, "x", me.get("id"), me.get("confirmed_email"), me.get("name") or me.get("username"), rec["kind"])
    raise InputError("Unknown sign-in provider")


# ---------------------------------------------------------------- videos: doctors' demo videos, patients' video reviews
VIDEO_DIR = DATA_DIR / "videos"
MAX_VIDEO_BYTES = 30_000_000   # about 1 minute of phone video
MAX_DEMO_VIDEOS = 6
VIDEO_TYPES = {"video/mp4": "mp4", "video/webm": "webm", "video/quicktime": "mov"}


def video_file(vid, mime):
    return VIDEO_DIR / f"{int(vid)}.{VIDEO_TYPES.get(mime, 'mp4')}"


def looks_like_video(head, mime):
    if mime == "video/webm":
        return head[:4] == b"\x1aE\xdf\xa3"
    return head[4:8] == b"ftyp"  # mp4 and mov


def video_upload(conn, me, mime, raw, lid, caption):
    need_member(me)
    if mime not in VIDEO_TYPES:
        raise InputError("Please choose an MP4, MOV or WebM video.")
    if len(raw) > MAX_VIDEO_BYTES:
        raise InputError("That video is too large. Please keep it under 30 MB (about 1 minute).")
    if not looks_like_video(raw[:16], mime):
        raise InputError("That file is not a video we can play.")
    lst = conn.execute("SELECT id, owner, name FROM listings WHERE id=?", (lid,)).fetchone()
    if not lst:
        raise InputError("This doctor is no longer listed")
    caption = str(caption or "").strip()[:140]
    if caption and LINK_RE.search(caption):
        raise InputError("Please don't put links in captions")
    if lst["owner"] == me["id"]:  # the doctor's own demo video, live straight away
        if conn.execute("SELECT COUNT(*) FROM videos WHERE listing_id=? AND kind='demo'", (lid,)).fetchone()[0] >= MAX_DEMO_VIDEOS:
            raise InputError(f"You can show up to {MAX_DEMO_VIDEOS} videos. Remove one first.")
        kind, status = "demo", "live"
    else:  # a patient's video review: hidden until the doctor approves it
        if me["kind"] != "patient":
            raise AuthError("Only patients can add a video review.")
        if too_many("video", str(me["id"]), 5, 3600):
            raise AuthError("Too many uploads. Please try again later.", 429)
        old = conn.execute("SELECT id, mime FROM videos WHERE listing_id=? AND member_id=? AND kind='review'", (lid, me["id"])).fetchone()
        if old:  # one video review per patient per doctor: the new one replaces the old
            video_file(old["id"], old["mime"]).unlink(missing_ok=True)
            conn.execute("DELETE FROM videos WHERE id=?", (old["id"],))
        kind, status = "review", "pending"
    cur = conn.execute("INSERT INTO videos(listing_id,member_id,kind,caption,status,mime,size,ts) VALUES(?,?,?,?,?,?,?,?)",
                       (lid, me["id"], kind, caption, status, mime, len(raw), now_ms()))
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    video_file(cur.lastrowid, mime).write_bytes(raw)
    if kind == "review" and lst["owner"]:
        notify(conn, lst["owner"], "video", f"{short_name(me['name'])} sent you a video review",
               "Approve it to show it on your profile.", f"reviews:{lid}")
    return listing_reviews(conn, lid, me)


def m_video_moderate(conn, d, me):
    need_member(me, "doctor")
    v = conn.execute("SELECT v.*, l.owner FROM videos v JOIN listings l ON l.id=v.listing_id WHERE v.id=?", (int(d.get("id") or 0),)).fetchone()
    if not v or v["owner"] != me["id"]:
        raise AuthError("You can only approve videos on your own profile.")
    if d.get("approve"):
        conn.execute("UPDATE videos SET status='live' WHERE id=?", (v["id"],))
        notify(conn, v["member_id"], "video", f"{me['name']} approved your video review", "It is now on their profile. Thank you!", f"reviews:{v['listing_id']}")
    else:
        conn.execute("DELETE FROM videos WHERE id=?", (v["id"],))
        video_file(v["id"], v["mime"]).unlink(missing_ok=True)
    return listing_reviews(conn, v["listing_id"], me)


def m_video_delete(conn, d, me):
    need_member(me)
    v = conn.execute("SELECT v.*, l.owner FROM videos v JOIN listings l ON l.id=v.listing_id WHERE v.id=?", (int(d.get("id") or 0),)).fetchone()
    if not v or me["id"] not in (v["member_id"], v["owner"]):
        raise AuthError("You can only remove your own videos.")
    conn.execute("DELETE FROM videos WHERE id=?", (v["id"],))
    video_file(v["id"], v["mime"]).unlink(missing_ok=True)
    return listing_reviews(conn, v["listing_id"], me)


def video_visible(conn, vid, me):
    v = conn.execute("SELECT v.*, l.owner FROM videos v JOIN listings l ON l.id=v.listing_id WHERE v.id=?", (vid,)).fetchone()
    if not v:
        return None
    if v["status"] == "live" or (me and me["id"] in (v["member_id"], v["owner"])):
        return v
    return None


MEMBER_ROUTES = {"/api/m/me": lambda conn, d, me: None, "/api/m/profile": m_profile, "/api/m/status": m_status,
                 "/api/m/fav": m_fav, "/api/m/send": m_send, "/api/m/thread": m_thread, "/api/m/photo": m_photo,
                 "/api/m/reviews": m_reviews, "/api/m/review": m_review, "/api/m/review/delete": m_review_delete,
                 "/api/m/review/reply": m_review_reply, "/api/m/gallery/add": m_gallery_add, "/api/m/gallery/delete": m_gallery_delete,
                 "/api/m/video/moderate": m_video_moderate, "/api/m/video/delete": m_video_delete,
                 "/api/m/verify/submit": m_verify_submit, "/api/m/reminder/save": m_reminder_save,
                 "/api/m/reminder/toggle": m_reminder_toggle, "/api/m/reminder/delete": m_reminder_delete}




# ---------------------------------------------------------------- member video calls (WhatsApp-style)
# Room "M<low id>-<high id>": the same browser-to-browser WebRTC as appointment calls. The member with the
# lower id plays the "doctor" side of the signalling (sends the offer); that's only a technical role.
RINGS = {}  # callee member id -> {"from", "name", "room", "photo_ts", "ts"}
MROOM_RE = re.compile(r"^M(\d{1,9})-(\d{1,9})$")


def can_contact(conn, me, other_id):
    other = conn.execute("SELECT id, name, kind, photo_ts FROM members WHERE id=?", (other_id,)).fetchone()
    if not other or other["id"] == me["id"]:
        raise InputError("Can't call this person")
    if me["kind"] == "patient" and other["kind"] == "doctor":
        return other
    if conn.execute("SELECT 1 FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) LIMIT 1",
                    (me["id"], other_id, other_id, me["id"])).fetchone():
        return other
    raise AuthError("You can call people you already chat with, or any doctor.")


def mroom(a, b):
    return f"M{min(a, b)}-{max(a, b)}"


def mcall_role(conn, d, me):
    need_member(me)
    m = MROOM_RE.match(str(d.get("room") or ""))
    if not m:
        raise AuthError("This call link is not valid.", 404)
    a, b = int(m.group(1)), int(m.group(2))
    if me["id"] not in (a, b) or a >= b:
        raise AuthError("You are not part of this call.", 403)
    other = can_contact(conn, me, b if me["id"] == a else a)
    return ("doctor" if me["id"] == a else "patient"), m.group(0), other


def mcall_join(conn, d, me):
    role, room, other = mcall_role(conn, d, me)
    conn.execute("DELETE FROM call_signals WHERE ts < ?", (now_ms() - 86_400_000,))
    last = conn.execute("SELECT COALESCE(MAX(id),0) FROM call_signals WHERE room=?", (room,)).fetchone()[0]
    RINGS.pop(me["id"], None)  # answering stops the ringing
    return {"role": role, "last_id": last, "ice_servers": ICE_SERVERS,
            "peer": {"id": other["id"], "name": other["name"], "kind": other["kind"], "photo_ts": other["photo_ts"]}}


def mcall_send(conn, d, me):
    role, room, _ = mcall_role(conn, d, me)
    kind = one_of(d, "kind", SIGNAL_KINDS)
    payload = json.dumps(d.get("payload"))
    if len(payload) > 20_000:
        raise InputError("Signal too large")
    conn.execute("INSERT INTO call_signals(room,sender,kind,payload,ts) VALUES(?,?,?,?,?)", (room, role, kind, payload, now_ms()))
    if kind == "bye":
        for k, v in list(RINGS.items()):
            if v["room"] == room:
                RINGS.pop(k, None)
    return {"ok": True}


def mcall_poll(conn, d, me):
    role, room, _ = mcall_role(conn, d, me)
    PRESENCE[(room, role)] = time.time()
    other = "patient" if role == "doctor" else "doctor"
    since = int(d.get("since") or 0)
    rows = conn.execute("SELECT id, kind, payload FROM call_signals WHERE room=? AND sender=? AND id>? ORDER BY id LIMIT 200",
                        (room, other, since)).fetchall()
    return {"messages": [{"id": r["id"], "kind": r["kind"], "payload": json.loads(r["payload"])} for r in rows],
            "peer_online": time.time() - PRESENCE.get((room, other), 0) < 6}


def mcall_ring(conn, d, me):
    need_member(me)
    if too_many("ring", str(me["id"]), 30, 3600):
        raise AuthError("Too many calls. Please wait a little.", 429)
    other = can_contact(conn, me, int(d.get("to") or 0))
    room = mroom(me["id"], other["id"])
    RINGS[other["id"]] = {"from": me["id"], "name": me["name"], "room": room, "photo_ts": me.get("photo_ts"), "ts": time.time()}
    notify(conn, other["id"], "call", f"Video call from {me['name']}", "Missed it? Call back from your messages.", "account")
    return {"room": room}


def mcall_decline(conn, d, me):
    need_member(me)
    ring = RINGS.pop(me["id"], None)
    if ring:  # tell the caller
        a, b = (int(x) for x in MROOM_RE.match(ring["room"]).groups())
        conn.execute("INSERT INTO call_signals(room,sender,kind,payload,ts) VALUES(?,?,?,?,?)",
                     (ring["room"], "doctor" if me["id"] == a else "patient", "bye", json.dumps({"declined": True}), now_ms()))
    return {"ok": True}


def m_incoming(conn, d, me):
    need_member(me)
    ring = RINGS.get(me["id"])
    if ring and time.time() - ring["ts"] > 45:
        RINGS.pop(me["id"], None)
        ring = None
    return {"ring": {k: ring[k] for k in ("from", "name", "room", "photo_ts")} if ring else None}


MCALL_ROUTES = {"/api/mcall/join": mcall_join, "/api/mcall/send": mcall_send, "/api/mcall/poll": mcall_poll,
                "/api/mcall/ring": mcall_ring, "/api/mcall/decline": mcall_decline, "/api/mcall/incoming": m_incoming}


# ---------------------------------------------------------------- FOOD SCAN: is this safe for me to eat?
FOOD_SYSTEM = """You are the food checker on Clinora, a health website. People photograph what they are about to eat or drink: home food, restaurant and street food, junk food, sweets, drinks, fruit, leftovers, packaged snacks, nutrition labels and ingredient lists. Tell them clearly whether it is OK for them to eat, like a friendly, honest dietitian.

- Identify the food. Estimate portion, calories and nutrition for what is visible. If it is a packaged product, read the label and ingredients.
- verdict: "safe" (fine to eat), "moderation" (fine sometimes or in a small portion, e.g. most junk food), "caution" (real concern for this person, e.g. very high sugar with diabetes, possible allergen, looks undercooked), "avoid" (do not eat: visible mould or spoilage, clear allergen for this person, raw or unsafe meat/eggs/seafood, something not meant to be eaten), "unclear" (cannot tell from the photo).
- Check the person's allergies, conditions, diet and note. Put anything that matters for them in personal_warnings. A listed allergen that may be present always means "caution" or "avoid".
- Look for visible freshness and hygiene problems (mould, discolouration, sliminess, swollen packs, flies, raw meat next to cooked food). Say honestly that a photo can't detect germs, toxins or contamination, and give the smell / expiry / "when in doubt, throw it out" checks when relevant.
- If the photo isn't food (or is a medicine, chemical, plant or mushroom you can't identify), set is_food false and verdict "unclear" or "avoid"; never say an unidentified wild mushroom or berry is safe.
- Be kind and non-judgemental about junk food: say how to enjoy it more safely and a better swap.
- health_score: 1 (very unhealthy) to 10 (very healthy) for this person.
- Keep every text short and plain. Reply in the language given in the request."""

_S = {"type": "string"}
_A = {"type": "array", "items": {"type": "string"}}
FOOD_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "is_food": {"type": "boolean"}, "name": _S,
        "verdict": {"type": "string", "enum": ["safe", "moderation", "caution", "avoid", "unclear"]},
        "headline": _S, "portion": _S, "calories": _S, "health_score": {"type": "integer"},
        "nutrition": {"type": "object", "additionalProperties": False,
                      "properties": {k: _S for k in ("protein", "carbs", "sugar", "fat", "salt", "fibre")},
                      "required": ["protein", "carbs", "sugar", "fat", "salt", "fibre"]},
        "ingredients": _A, "allergens": _A, "personal_warnings": _A, "risks": _A,
        "freshness": _S, "better_choice": _S, "tips": _A,
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
    },
    "required": ["is_food", "name", "verdict", "headline", "portion", "calories", "health_score", "nutrition", "ingredients",
                 "allergens", "personal_warnings", "risks", "freshness", "better_choice", "tips", "confidence"],
}
MAX_FOOD_PHOTO = 3_000_000


def str_list(v, n=20, ln=40):
    return [str(x).strip()[:ln] for x in (v if isinstance(v, list) else [])[:n] if str(x).strip()]


def food_scan(d, ip):
    if client is None:
        print("[AI] Food Scan unavailable: no ANTHROPIC_API_KEY in .env", flush=True)
        raise InputError("Food Scan is resting right now. Please try again a little later.")
    if too_many("food", ip, 30, 3600):
        raise AuthError("You've scanned a lot this hour. Please try again a little later.", 429)
    prefix = "data:image/jpeg;base64,"
    frames = d.get("frames") if isinstance(d.get("frames"), list) else None
    shots = [str(x or "") for x in frames[:8]] if frames else [str(d.get("image") or "")]
    if not shots or not shots[0]:
        raise InputError("Please take or choose a photo of the food")
    images = []
    for data in shots:
        if not data.startswith(prefix):
            raise InputError("Please take or choose a photo of the food")
        try:
            raw = base64.b64decode(data[len(prefix):], validate=True)
        except ValueError:
            raise InputError("That photo could not be read")
        if len(raw) > (900_000 if frames else MAX_FOOD_PHOTO) or not raw.startswith(b"\xff\xd8\xff"):
            raise InputError("That photo could not be used. Try another one.")
        images.append({"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data[len(prefix):]}})
    prof = d.get("profile") if isinstance(d.get("profile"), dict) else {}
    about = "\n".join([
        "Allergies: " + (", ".join(str_list(prof.get("allergies"))) or "none given"),
        "Health conditions: " + (", ".join(str_list(prof.get("conditions"))) or "none given"),
        "Diet: " + (", ".join(str_list(prof.get("diet"))) or "none given"),
        "Their note: " + (str(d.get("note") or "").strip()[:300] or "none"),
        "Country: " + str(d.get("country") or "")[:40],
        "Reply language: " + str(d.get("lang") or "English")[:40],
    ])
    response = client.beta.messages.create(
        model=MODEL, max_tokens=8000, system=FOOD_SYSTEM,
        messages=[{"role": "user", "content": images + [
            {"type": "text", "text": ("These are frames, in order, from a short video of the food. Look at all of them together "
                                      "(different sides, the label, how it is stored or cooked).\n" if frames else "")
             + "Is this safe and OK for me to eat?\n" + about}]}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": FOOD_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if response.stop_reason == "refusal":
        raise InputError("Sorry, this photo can't be checked. Try a clearer photo of the food.")
    txt = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        return json.loads(txt)
    except ValueError:
        raise InputError("The check didn't finish. Please try again.")

# ---------------------------------------------------------------- doctors on university & institute websites (AI + web search)
UNI_SYSTEM = """You find medical doctors listed on the official websites of universities, medical colleges, institutes and their hospitals or health centres (for example AIIMS, PGIMER, JIPMER, CMC Vellore, IIT and NIT hospitals / health centres, university medical schools anywhere in the world).

Use web search. Only list people whose name appears on an official page of that institute (its own domain, such as *.ac.in, *.edu, *.edu.in, aiims.edu, or the institute hospital's own site). Never invent or guess names, and never use directory or review sites as the source.

Reply with JSON only, no other text, in exactly this shape:
{"institute": "official name", "website": "https://... or null", "doctors": [{"name": "Dr ...", "designation": "e.g. Professor / Medical Officer", "department": "e.g. Cardiology", "source_url": "https://official page where the name appears"}], "note": "one short sentence for the patient"}
List at most 40 doctors. If the request names a department, prefer that department. If you find no official list, return an empty doctors list and say so in note."""


def uni_doctors(conn_unused, d, ip):
    q = text(d, "institute", 120)
    dept = text(d, "department", 60, False)
    key = (q + "|" + dept).lower().strip()
    with DB_LOCK, connect() as conn:
        row = conn.execute("SELECT result, ts FROM unidocs_cache WHERE q=?", (key,)).fetchone()
        if row and row["ts"] > now_ms() - 7 * 86_400_000:
            return dict(json.loads(row["result"]), cached=True)
    if client is None:
        print("[AI] University search unavailable: no ANTHROPIC_API_KEY in .env", flush=True)
        raise InputError("This search is resting right now. Please try again a little later.")
    if too_many("uni", ip, 10, 3600):
        raise AuthError("Too many searches. Please try again in a little while.", 429)
    messages = [{"role": "user", "content": f"Institute: {q}" + (f"\nDepartment: {dept}" if dept else "")}]
    response = None
    for _ in range(4):
        response = client.beta.messages.create(
            model=MODEL, max_tokens=16000, system=UNI_SYSTEM, messages=messages,
            tools=[{"type": "web_search_20260209", "name": "web_search", "max_uses": 6}],
            output_config={"effort": "low"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        if response.stop_reason != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in response.content]}]
    if response is None or response.stop_reason == "refusal":
        raise InputError("The search could not be completed. Try another name.")
    raw = "\n".join(b.text for b in response.content if getattr(b, "type", "") == "text")
    try:
        data = json.loads(raw[raw.index("{"): raw.rindex("}") + 1])
    except ValueError:
        raise InputError("The search did not return a clear list. Try a more exact name, e.g. 'AIIMS New Delhi'.")
    safe = lambda u: u if isinstance(u, str) and u.startswith(("https://", "http://")) and len(u) < 500 else None
    docs = []
    for x in (data.get("doctors") or [])[:40]:
        if not isinstance(x, dict) or not str(x.get("name") or "").strip() or not safe(x.get("source_url")):
            continue
        docs.append({k: str(x.get(k) or "")[:120] for k in ("name", "designation", "department")} | {"source_url": safe(x.get("source_url"))})
    result = {"institute": str(data.get("institute") or q)[:150], "website": safe(data.get("website")),
              "doctors": docs, "note": str(data.get("note") or "")[:300]}
    with DB_LOCK, connect() as conn:
        conn.execute("INSERT OR REPLACE INTO unidocs_cache VALUES(?,?,?)", (key, json.dumps(result), now_ms()))
    return result

# ---------------------------------------------------------------- video calls (WebRTC signaling)
# The video itself goes directly between the two browsers. This server only passes the short
# "how to connect" messages (offer / answer / network candidates) between doctor and patient.
ICE_SERVERS = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]
SIGNAL_KINDS = {"hello", "offer", "answer", "ice", "bye"}
PRESENCE = {}  # (room, role) -> last poll time


def call_role(conn, d, user):
    """Who is asking to be in this call room: the patient (with the secret link) or the doctor/admin."""
    room = text(d, "room", 12).upper()
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (room,)).fetchone()
    if not appt or appt["mode"] != "video" or not appt["call_token"]:
        raise AuthError("This video call link is not valid.", 404)
    if appt["status"] == "Cancelled":
        raise AuthError("This appointment was cancelled.", 410)
    token = str(d.get("token") or "")
    if token and hmac.compare_digest(token, appt["call_token"]):
        if REQUIRE_VIDEO_PAYMENT and appt["pay_status"] != "paid":
            raise AuthError("Please pay for your video consultation before joining.", 402)
        return "patient", appt
    if user and (user["role"] == "admin" or user["doctor_id"] == appt["doc"]):
        return "doctor", appt
    raise AuthError("You don't have access to this call. Log in as the doctor, or use the patient's link.", 403)


def call_join(conn, d, user):
    role, appt = call_role(conn, d, user)
    conn.execute("DELETE FROM call_signals WHERE ts < ?", (now_ms() - 86_400_000,))
    last = conn.execute("SELECT COALESCE(MAX(id),0) FROM call_signals WHERE room=?", (appt["id"],)).fetchone()[0]
    info = {"id": appt["id"], "doc": appt["doc"], "date": appt["date"], "time": appt["time"]}
    if role == "doctor":
        info["patient"] = appt["name"]
    else:
        info["patient"] = appt["name"].split(" ")[0]
    return {"role": role, "last_id": last, "appointment": info, "ice_servers": ICE_SERVERS}


def call_send(conn, d, user):
    role, appt = call_role(conn, d, user)
    kind = one_of(d, "kind", SIGNAL_KINDS)
    payload = json.dumps(d.get("payload"))
    if len(payload) > 20_000:
        raise InputError("Signal too large")
    conn.execute("INSERT INTO call_signals(room,sender,kind,payload,ts) VALUES(?,?,?,?,?)",
                 (appt["id"], role, kind, payload, now_ms()))
    return {"ok": True}


def call_poll(conn, d, user):
    role, appt = call_role(conn, d, user)
    PRESENCE[(appt["id"], role)] = time.time()
    other = "patient" if role == "doctor" else "doctor"
    since = int(d.get("since") or 0)
    rows = conn.execute("SELECT id, kind, payload FROM call_signals WHERE room=? AND sender=? AND id>? ORDER BY id LIMIT 200",
                        (appt["id"], other, since)).fetchall()
    return {"messages": [{"id": r["id"], "kind": r["kind"], "payload": json.loads(r["payload"])} for r in rows],
            "peer_online": time.time() - PRESENCE.get((appt["id"], other), 0) < 6}


CALL_ROUTES = {"/api/call/join": call_join, "/api/call/send": call_send, "/api/call/poll": call_poll}


# ---------------------------------------------------------------- payments
def pay_appt(conn, d):
    """The patient proves it's their booking with the payment link (or their video-call link)."""
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (text(d, "id", 12).upper(),)).fetchone()
    token = str(d.get("token") or "")
    if not appt or not token or not (hmac.compare_digest(token, appt["pay_token"] or "") or
                                     hmac.compare_digest(token, appt["call_token"] or "")):
        raise AuthError("This payment link is not valid.", 404)
    return appt


def reload(conn, appt_id):
    return conn.execute("SELECT * FROM appointments WHERE id=?", (appt_id,)).fetchone()


def pay_summary(appt):
    return {"id": appt["id"], "doc": appt["doc"], "doctor": DOCTOR_NAMES.get(appt["doc"]), "date": appt["date"],
            "time": appt["time"], "mode": appt["mode"], "status": appt["status"], "pay_status": appt["pay_status"],
            "amount": appt["amount"], "currency": appt["currency"] or CURRENCY, "pay_mode": PAY_MODE,
            "patient": appt["name"].split(" ")[0], "paid_ts": appt["paid_ts"],
            "pay_method": appt["pay_method"], "pay_currency": appt["pay_currency"], "pay_amount": appt["pay_amount"],
            "currencies": offered_currencies(), "base_currency": CURRENCY, "demo_allowed": ALLOW_DEMO_PAYMENTS,
            "call": appt["call_token"] if appt["mode"] == "video" else None, "pay_ref": (appt["pay_ref"] or "")[-8:]}


def log_payment(conn, appt_id, event, provider=None, ref=None, amount=None, currency=None, detail=None):
    """Permanent record of every payment step (for disputes and accounting). Never stores card/UPI details."""
    conn.execute("INSERT INTO payment_events(appt_id,event,provider,ref,amount,currency,detail,ts) VALUES(?,?,?,?,?,?,?,?)",
                 (appt_id, event, provider, ref, amount, currency, (detail or "")[:300], now_ms()))


def mark_paid(conn, appt_id, ref, provider=None, amount=None, currency=None):
    """Mark a booking paid exactly once. A payment for a cancelled booking is flagged for refund instead."""
    appt = conn.execute("SELECT status, pay_status FROM appointments WHERE id=?", (appt_id,)).fetchone()
    if not appt:
        log_payment(conn, appt_id, "paid_unknown_booking", provider, ref, amount, currency)
        return
    if appt["pay_status"] in ("paid", "refund_due", "refunded"):
        log_payment(conn, appt_id, "duplicate_ignored", provider, ref, amount, currency)
        return
    status = "refund_due" if appt["status"] == "Cancelled" else "paid"
    conn.execute("UPDATE appointments SET pay_status=?, pay_ref=?, paid_ts=? WHERE id=?", (status, ref, now_ms(), appt_id))
    log_payment(conn, appt_id, "paid" if status == "paid" else "paid_after_cancel_refund_due", provider, ref, amount, currency)


def amount_matches(appt, amount_minor, currency):
    return appt["pay_amount"] is not None and int(amount_minor) == int(appt["pay_amount"]) \
        and str(currency).lower() == (appt["pay_currency"] or "").lower()


def pay_info(conn, d, user=None):
    return {"payment": pay_summary(pay_appt(conn, d))}


def pay_quote(conn, d, user=None):
    appt = pay_appt(conn, d)
    q = quote(appt["doc"], str(d.get("currency") or CURRENCY))
    return {"quote": q, "methods": methods_for(q["currency"])}


def pay_checkout(conn, d, user=None):
    appt = pay_appt(conn, d)
    if appt["status"] == "Cancelled":
        raise InputError("This appointment was cancelled.")
    if appt["pay_status"] == "paid":
        raise InputError("This appointment is already paid.")
    q = quote(appt["doc"], str(d.get("currency") or CURRENCY))
    method = str(d.get("method") or "")
    if method not in {m["id"] for m in methods_for(q["currency"])}:
        raise InputError("This payment method isn't available for this currency.")
    conn.execute("UPDATE appointments SET pay_method=?, pay_currency=?, pay_amount=? WHERE id=?",
                 (method, q["currency"], q["amount"], appt["id"]))
    log_payment(conn, appt["id"], "checkout_started", method, None, q["amount"], q["currency"])
    if PAY_MODE == "demo" and not ALLOW_DEMO_PAYMENTS:
        raise InputError("Online payment isn't available yet. Please pay at the clinic.")
    token = str(d.get("token"))
    back = f"{PUBLIC_URL}/#pay/{appt['id']}.{token}"
    title = f"{'Video consultation' if appt['mode'] == 'video' else 'Consultation'} with {DOCTOR_NAMES.get(appt['doc'])}"
    if ALLOW_DEMO_PAYMENTS:
        return {"url": f"#checkout/{appt['id']}.{token}"}
    if method == "stripe":
        session = stripe.checkout.Session.create(
            mode="payment",
            line_items=[{"quantity": 1, "price_data": {"currency": q["currency"], "unit_amount": q["amount"],
                         "product_data": {"name": title, "description": f"Booking #{appt['id']} on {appt['date']} at {appt['time']}"}}}],
            client_reference_id=appt["id"], metadata={"appointment_id": appt["id"]},
            idempotency_key=f"chk-{appt['id']}-{q['currency']}-{q['amount']}-{int(time.time() // 900)}",
            success_url=f"{PUBLIC_URL}/?paid={appt['id']}.{token}&session_id={{CHECKOUT_SESSION_ID}}", cancel_url=back)
        conn.execute("UPDATE appointments SET pay_ref=? WHERE id=?", (session.id, appt["id"]))
        return {"url": session.url}
    if method == "razorpay":
        order = http_json("POST", "https://api.razorpay.com/v1/orders",
                          {"amount": q["amount"], "currency": q["currency"].upper(), "receipt": appt["id"],
                           "notes": {"appointment_id": appt["id"]}}, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        conn.execute("UPDATE appointments SET pay_ref=? WHERE id=?", (order["id"], appt["id"]))
        return {"razorpay": {"key": RAZORPAY_KEY_ID, "order_id": order["id"], "amount": q["amount"],
                             "currency": q["currency"].upper(), "name": CLINIC_NAME, "description": title,
                             "prefill": {"name": appt["name"], "contact": appt["phone"]}}}
    if method == "paypal":
        order = http_json("POST", PAYPAL_API + "/v2/checkout/orders", {
            "intent": "CAPTURE",
            "purchase_units": [{"reference_id": appt["id"], "custom_id": appt["id"], "description": title[:120],
                                "amount": {"currency_code": q["currency"].upper(), "value": major_str(q["amount"], q["currency"])}}],
            "payment_source": {"paypal": {"experience_context": {
                "return_url": f"{PUBLIC_URL}/?paid={appt['id']}.{token}&pp=1", "cancel_url": back,
                "user_action": "PAY_NOW", "brand_name": CLINIC_NAME}}}}, bearer=paypal_token())
        conn.execute("UPDATE appointments SET pay_ref=? WHERE id=?", (order["id"], appt["id"]))
        link = next((l["href"] for l in order.get("links", []) if l.get("rel") in ("payer-action", "approve")), None)
        if not link:
            raise ProviderError("PayPal did not return a payment page")
        return {"url": link}
    raise InputError("Unknown payment method")


def pay_demo_complete(conn, d, user=None):
    if not ALLOW_DEMO_PAYMENTS:
        raise AuthError("Demo payments are switched off on this website.")
    appt = pay_appt(conn, d)
    if appt["pay_status"] != "paid":
        mark_paid(conn, appt["id"], "demo_" + secrets.token_hex(6), "demo", appt["pay_amount"], appt["pay_currency"])
    return {"payment": pay_summary(reload(conn, appt["id"]))}


def pay_verify(conn, d, user=None):
    appt = pay_appt(conn, d)
    method = appt["pay_method"]
    if appt["pay_status"] != "paid" and PAY_MODE == "live":
        if method == "stripe" and d.get("session_id"):
            session = stripe.checkout.Session.retrieve(text(d, "session_id", 200))
            if session.metadata.get("appointment_id") != appt["id"]:
                raise AuthError("This payment belongs to another booking.")
            if session.payment_status == "paid":
                if not amount_matches(appt, session.amount_total, session.currency):
                    log_payment(conn, appt["id"], "amount_mismatch", "stripe", session.id, session.amount_total, session.currency)
                    raise AuthError("The amount paid doesn't match this booking. The clinic has been notified.")
                mark_paid(conn, appt["id"], session.payment_intent or session.id, "stripe", session.amount_total, session.currency)
        elif method == "razorpay" and d.get("razorpay_payment_id"):
            order_id, pay_id = text(d, "razorpay_order_id", 60), text(d, "razorpay_payment_id", 60)
            expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{pay_id}".encode(), hashlib.sha256).hexdigest()
            if order_id != appt["pay_ref"] or not hmac.compare_digest(expected, str(d.get("razorpay_signature") or "")):
                log_payment(conn, appt["id"], "bad_signature", "razorpay", pay_id)
                raise AuthError("The payment could not be verified.")
            pay = http_json("GET", f"https://api.razorpay.com/v1/payments/{pay_id}", auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
            if pay.get("order_id") != order_id or pay.get("status") not in ("captured", "authorized") \
                    or not amount_matches(appt, pay.get("amount", -1), pay.get("currency", "")):
                log_payment(conn, appt["id"], "amount_mismatch", "razorpay", pay_id, pay.get("amount"), pay.get("currency"), pay.get("status"))
                raise AuthError("The payment could not be confirmed. The clinic has been notified.")
            mark_paid(conn, appt["id"], pay_id, "razorpay", pay.get("amount"), pay.get("currency"))
        elif method == "paypal" and d.get("paypal_order"):
            order_id = text(d, "paypal_order", 60)
            if order_id != appt["pay_ref"]:
                raise AuthError("This payment belongs to another booking.")
            try:
                order = http_json("POST", f"{PAYPAL_API}/v2/checkout/orders/{order_id}/capture", {}, bearer=paypal_token())
            except ProviderError:
                order = http_json("GET", f"{PAYPAL_API}/v2/checkout/orders/{order_id}", bearer=paypal_token())
            caps = ((order.get("purchase_units") or [{}])[0].get("payments") or {}).get("captures") or []
            cap = next((c for c in caps if c.get("status") == "COMPLETED"), None)
            if cap and cap["amount"]["value"] == major_str(appt["pay_amount"], appt["pay_currency"]) \
                    and cap["amount"]["currency_code"].lower() == appt["pay_currency"]:
                mark_paid(conn, appt["id"], "paypal:" + cap["id"], "paypal", appt["pay_amount"], appt["pay_currency"])
            elif cap:
                log_payment(conn, appt["id"], "amount_mismatch", "paypal", cap.get("id"), None, cap["amount"].get("currency_code"), cap["amount"].get("value"))
    return {"payment": pay_summary(reload(conn, appt["id"]))}


def pay_mark_cash(conn, d, user=None):
    need_login(user)
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (text(d, "id", 12),)).fetchone()
    if not appt:
        raise InputError("Booking not found")
    if user["role"] == "doctor" and appt["doc"] != user["doctor_id"]:
        raise AuthError("You can only change your own appointments.")
    conn.execute("UPDATE appointments SET pay_method='cash' WHERE id=?", (appt["id"],))
    mark_paid(conn, appt["id"], "cash", "cash", appt["amount"], appt["currency"])
    log_payment(conn, appt["id"], "cash_marked_by", None, None, None, None, user["email"])


def pay_refund(conn, d, user=None):
    need_admin(user)
    appt = conn.execute("SELECT * FROM appointments WHERE id=?", (text(d, "id", 12),)).fetchone()
    if not appt or appt["pay_status"] not in ("paid", "refund_due"):
        raise InputError("Only paid bookings can be refunded")
    ref = appt["pay_ref"] or ""
    note = "Marked refunded. Return cash/demo payments yourself."
    if STRIPE_ON and ref.startswith("pi_"):
        stripe.Refund.create(payment_intent=ref, idempotency_key=f"refund-{appt['id']}-{ref}")
        note = "Refunded through Stripe"
    elif RAZORPAY_ON and ref.startswith("pay_"):
        http_json("POST", f"https://api.razorpay.com/v1/payments/{ref}/refund", {}, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        note = "Refunded through Razorpay"
    elif PAYPAL_ON and ref.startswith("paypal:"):
        http_json("POST", f"{PAYPAL_API}/v2/payments/captures/{ref[7:]}/refund", {}, bearer=paypal_token())
        note = "Refunded through PayPal"
    conn.execute("UPDATE appointments SET pay_status='refunded' WHERE id=?", (appt["id"],))
    log_payment(conn, appt["id"], "refunded", None, ref, appt["pay_amount"], appt["pay_currency"], f"{note} by {user['email']}")
    return {"note": note}


def stripe_webhook(conn, payload, signature):
    event = stripe.Webhook.construct_event(payload, signature, STRIPE_WEBHOOK_SECRET)
    if event["type"] == "checkout.session.completed":
        sess = event["data"]["object"]
        appt_id = (sess.get("metadata") or {}).get("appointment_id")
        appt = reload(conn, appt_id) if appt_id else None
        if appt and sess.get("payment_status") == "paid":
            if amount_matches(appt, sess.get("amount_total", -1), sess.get("currency", "")):
                mark_paid(conn, appt_id, sess.get("payment_intent") or sess.get("id"), "stripe", sess.get("amount_total"), sess.get("currency"))
            else:
                log_payment(conn, appt_id, "amount_mismatch", "stripe", sess.get("id"), sess.get("amount_total"), sess.get("currency"))


def razorpay_webhook(conn, payload, signature):
    """Razorpay calls this when a payment is captured (even if the patient closed the page)."""
    expected = hmac.new(RAZORPAY_WEBHOOK_SECRET.encode(), payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature or ""):
        raise AuthError("bad signature")
    event = json.loads(payload)
    if event.get("event") not in ("payment.captured", "order.paid"):
        return
    pay = ((event.get("payload") or {}).get("payment") or {}).get("entity") or {}
    row = conn.execute("SELECT * FROM appointments WHERE pay_ref=? OR pay_ref=?", (pay.get("order_id"), pay.get("id"))).fetchone()
    if not row:
        return
    if pay.get("status") == "captured" and amount_matches(row, pay.get("amount", -1), pay.get("currency", "")):
        mark_paid(conn, row["id"], pay.get("id"), "razorpay", pay.get("amount"), pay.get("currency"))
    else:
        log_payment(conn, row["id"], "amount_mismatch", "razorpay", pay.get("id"), pay.get("amount"), pay.get("currency"), pay.get("status"))


def paypal_webhook(conn, payload, headers):
    """PayPal calls this when a capture completes. The message is verified with PayPal before it is trusted."""
    event = json.loads(payload)
    check = http_json("POST", PAYPAL_API + "/v1/notifications/verify-webhook-signature", {
        "auth_algo": headers.get("PAYPAL-AUTH-ALGO"), "cert_url": headers.get("PAYPAL-CERT-URL"),
        "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"), "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
        "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"), "webhook_id": PAYPAL_WEBHOOK_ID, "webhook_event": event},
        bearer=paypal_token())
    if check.get("verification_status") != "SUCCESS":
        raise AuthError("bad signature")
    if event.get("event_type") != "PAYMENT.CAPTURE.COMPLETED":
        return
    cap = event.get("resource") or {}
    order_id = ((cap.get("supplementary_data") or {}).get("related_ids") or {}).get("order_id")
    row = conn.execute("SELECT * FROM appointments WHERE pay_ref=?", (order_id,)).fetchone()
    if not row:
        return
    amt = cap.get("amount") or {}
    if amt.get("value") == major_str(row["pay_amount"] or 0, row["pay_currency"] or "") and (amt.get("currency_code") or "").lower() == row["pay_currency"]:
        mark_paid(conn, row["id"], "paypal:" + cap.get("id", ""), "paypal", row["pay_amount"], row["pay_currency"])
    else:
        log_payment(conn, row["id"], "amount_mismatch", "paypal", cap.get("id"), None, amt.get("currency_code"), amt.get("value"))


def find_appointments(conn, d, user=None):
    phone = phone_of(d)
    rows = conn.execute("SELECT id, doc, date, time, mode, phone, call_token, pay_token, pay_status, amount FROM appointments WHERE status='Confirmed' "
                        "AND date >= date('now','-1 day') ORDER BY date, time").fetchall()
    return {"bookings": [dict({k: r[k] for k in ("id", "doc", "date", "time", "mode", "pay_status", "amount")},
                              call=r["call_token"], pay=r["pay_token"])
                         for r in rows if same_phone(r["phone"], phone)]}


ROUTES = {
    "/api/appointments/find": find_appointments,
    "/api/auth/password": change_password,
    "/api/users/create": create_user,
    "/api/users/delete": delete_user,
    "/api/appointments": create_appointment,
    "/api/appointments/status": set_status,
    "/api/appointments/cancel": cancel_appointment,
    "/api/alerts": add_alert,
    "/api/live": set_live,
    "/api/stats/chat": count_chat,
    "/api/listings": add_listing,
    "/api/listings/delete": delete_listing,
    "/api/pay/info": pay_info,
    "/api/pay/checkout": pay_checkout,
    "/api/pay/quote": pay_quote,
    "/api/pay/demo_complete": pay_demo_complete,
    "/api/pay/verify": pay_verify,
    "/api/pay/mark_cash": pay_mark_cash,
    "/api/pay/refund": pay_refund,
    "/api/reset": reset_demo,
    "/api/verify/list": verify_queue,
    "/api/verify/decide": verify_decide,
}


def run_route(path, data, token):
    with DB_LOCK, connect() as conn:  # "with connect()" commits on success, rolls back on error
        user = user_for_token(conn, token)
        result = ROUTES[path](conn, data, user) or {}
        return {"ok": True, "created": result, "data": snapshot(conn, user)}


# ---------------------------------------------------------------- AI website translation (100+ languages)
# The site's English text lives in i18n.js (short texts) and index.html (paragraphs marked data-i18n).
# The first time someone picks a language, Claude translates everything once; the result is saved in
# data/i18n/<code>.json and served from there forever after (no more AI cost for that language).
I18N_DIR = ROOT / "data" / "i18n"
BUILTIN_LANGS = {"en", "hi", "es", "fr", "ar", "pt", "de", "zh", "ru"}
TRANSLATE_LOCKS = {}
TRANSLATE_LOCKS_GUARD = threading.Lock()


class TranslateUnavailable(Exception):
    pass


def language_catalog():
    js = (ROOT / "i18n.js").read_text()
    block = js[js.index("const LANG_LIST"):js.index("const LANGS =")]
    out = {}
    for m in re.finditer(r"(?:'([\w-]+)'|\b([\w]+)):\[('|\")(.*?)\3,\s*'([^']*)'", block):
        out[m.group(1) or m.group(2)] = m.group(5)
    return out


def translation_source():
    """English strings to translate: {key: english}."""
    js = (ROOT / "i18n.js").read_text()
    body = js[js.index("const T = {"):js.index("/* ---------------------------------------------------------------- engine */")]
    src = {}
    for m in re.finditer(r'^\s*"((?:[^"\\]|\\.)*)":\s*\{', body, re.M):
        key = json.loads('"' + m.group(1) + '"')
        if key.startswith("@"):
            continue
        src[key] = key
    greet = re.search(r'"__greet":\s*\{en:"((?:[^"\\]|\\.)*)"', body)
    src["__greet"] = json.loads('"' + greet.group(1) + '"') if greet else "Hello!"
    src["__ask"] = "View this website in this language?"
    src["__yes"] = "Yes, switch"
    html = (ROOT / "index.html").read_text()
    for m in re.finditer(r'<(\w+)[^>]*?data-i18n="([\w-]+)"[^>]*>(.*?)</\1>', html, re.S):
        src["@" + m.group(2)] = m.group(3).strip()
    return src


TRANSLATE_SYSTEM = """You translate the user interface of Clinora, a website where patients anywhere in the world find doctors, book appointments and video consultations, and get emergency numbers.

Translate every item into {name}. Rules:
- Natural, simple, friendly wording that an ordinary patient understands. Use the script normally used for this language.
- Medical and emergency text must be accurate and clear.
- Keep unchanged: emojis, numbers, symbols such as // → · * … ★ ⚡, phone numbers, \\n line breaks, and these names: Clinora, Clinora Medical Center, WhatsApp, OpenStreetMap, Google, Stripe.
- Keep every HTML tag and attribute exactly as in the source (only translate the visible text between tags).
- Items written in CAPITALS stay in capitals if the script has capital letters.
- Item "__ask" asks the visitor whether to view the site in {name}; item "__yes" is the short button to accept.
Return ONLY a JSON object with exactly the same ids as the input, each mapped to its translation."""


def _tags(text):
    return sorted(re.findall(r"</?\w+[^>]*>", text))


def translate_language(code):
    """Return {key: translation} for a language, translating with Claude once and caching to disk."""
    catalog = language_catalog()
    if code not in catalog:
        raise InputError("Unknown language")
    path = I18N_DIR / f"{code}.json"
    if path.exists():
        return json.loads(path.read_text())
    if client is None:
        raise TranslateUnavailable("The AI translator isn't connected yet (it needs the AI key).")
    with TRANSLATE_LOCKS_GUARD:
        lock = TRANSLATE_LOCKS.setdefault(code, threading.Lock())
    with lock:  # one translation per language at a time; later visitors get the saved file
        if path.exists():
            return json.loads(path.read_text())
        source = translation_source()
        keys = list(source)
        items = {str(i): source[k] for i, k in enumerate(keys)}
        # streamed: a whole site translation is long, and streaming avoids HTTP timeouts
        with client.beta.messages.stream(
            model=MODEL, max_tokens=32000,
            system=TRANSLATE_SYSTEM.replace("{name}", catalog[code]),
            messages=[{"role": "user", "content": json.dumps(items, ensure_ascii=False)}],
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"], fallbacks="default",
        ) as stream:
            response = stream.get_final_message()
        if response.stop_reason in ("refusal", "max_tokens"):
            raise TranslateUnavailable(f"Translation stopped early ({response.stop_reason}). Please try again.")
        raw = "".join(b.text for b in response.content if b.type == "text")
        start, end = raw.find("{"), raw.rfind("}")
        try:
            got = json.loads(raw[start:end + 1])
        except ValueError:
            raise TranslateUnavailable("The translation came back in the wrong format. Please try again.")
        result = {}
        for i, k in enumerate(keys):
            val = got.get(str(i))
            if not isinstance(val, str) or not val.strip():
                continue  # missing: the site shows English for this text
            if "<" in source[k] and _tags(val) != _tags(source[k]):
                continue  # HTML changed: unsafe, keep English
            if "<script" in val.lower() or "javascript:" in val.lower():
                continue
            result[k] = val
        if len(result) < len(keys) * 0.6:
            raise TranslateUnavailable("Too much of the translation was unusable. Please try again.")
        I18N_DIR.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(result, ensure_ascii=False, indent=1))
        tmp.replace(path)
        return result


def ready_languages():
    return sorted(BUILTIN_LANGS | ({f.stem for f in I18N_DIR.glob("*.json")} if I18N_DIR.exists() else set()))


MAX_MESSAGES = 80
MAX_BODY = 400_000


def chat_turn(messages, context):
    system = [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": "Context for this chat:\n" + context},
    ]
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=system,
        tools=TOOLS,
        messages=messages,
        output_config={"effort": "low"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    return {
        "stop_reason": response.stop_reason,
        "content": [block.model_dump(exclude_none=True) for block in response.content],
    }


PUBLIC_FILES = {"index.html", "i18n.js", "manifest.json", "sw.js"}
LEGAL_PAGES = {"/privacy": "privacy.html", "/terms": "terms.html", "/delete-account": "delete-account.html"}
SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "").strip()
TRUST_PROXY = os.environ.get("TRUST_PROXY", "").lower() in ("1", "true", "yes")  # behind Render / a load balancer
TWA_PACKAGE = os.environ.get("TWA_PACKAGE", "").strip()          # Android app id, e.g. com.clinora.app
TWA_SHA256 = os.environ.get("TWA_SHA256", "").strip()            # signing key fingerprint from Play Console


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("Permissions-Policy", "camera=(self), microphone=(self), geolocation=(self), payment=(self)")
        if PUBLIC_URL.startswith("https://"):
            self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        super().end_headers()

    def session_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "sd_session":
                return v
        return ""

    def cookie(self, token, max_age):
        secure = "; Secure" if (self.headers.get("X-Forwarded-Proto") == "https" or PUBLIC_URL.startswith("https://")) else ""
        return f"sd_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}{secure}"

    def send_json(self, status, payload, cookie=None):
        body = json.dumps(payload).encode()
        self.send_response(status)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path_only = self.path.split("?")[0]
        if path_only == "/api/prices":
            cur = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("currency", [CURRENCY])[0].lower()
            if cur not in FX_PER_USD:
                cur = CURRENCY
            return self.send_json(200, {"currency": cur, "prices": {d: quote(d, cur) for d in DOCTOR_FEES}})
        if path_only == "/api/i18n":
            return self.send_json(200, {"ai": client is not None, "ready": ready_languages()})
        if path_only.startswith("/api/i18n/"):
            code = path_only.rsplit("/", 1)[1]
            try:
                return self.send_json(200, {"lang": code, "strings": translate_language(code)})
            except InputError as e:
                return self.send_json(404, {"error": str(e)})
            except TranslateUnavailable as e:
                return self.send_json(503, {"error": str(e)})
            except Exception as e:
                if anthropic and isinstance(e, anthropic.APIError):
                    return self.send_json(502, {"error": "The AI translator is busy. Please try again in a minute."})
                raise
        if self.path.split("?")[0] == "/api/data":
            with connect() as conn:
                return self.send_json(200, snapshot(conn, user_for_token(conn, self.session_token())))
        if self.path.startswith("/api/status"):
            return self.send_json(200, {"ai": client is not None, "reason": AI_REASON, "model": MODEL, "oauth": oauth_status(),
                                        "pay_mode": PAY_MODE, "currency": CURRENCY, "video_needs_payment": REQUIRE_VIDEO_PAYMENT})
        if path_only.removesuffix(".html") in LEGAL_PAGES:
            name = LEGAL_PAGES[path_only.removesuffix(".html")]
            page = (ROOT / "legal" / name).read_text(encoding="utf-8")
            site = PUBLIC_URL
            page = page.replace("{{SUPPORT_EMAIL}}", SUPPORT_EMAIL or "the email address shown in the Clinora app")
            page = page.replace("{{SITE_URL}}", site).replace("{{UPDATED}}", "25 November 2026")
            return self.send_text(200, page, "text/html; charset=utf-8")
        if path_only == "/robots.txt":
            return self.send_text(200, f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {PUBLIC_URL}/sitemap.xml\n", "text/plain")
        if path_only == "/sitemap.xml":
            urls = "".join(f"<url><loc>{PUBLIC_URL}{u}</loc></url>" for u in ("/", "/privacy", "/terms", "/delete-account"))
            return self.send_text(200, '<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                                  + urls + "</urlset>", "application/xml")
        if path_only == "/.well-known/assetlinks.json":
            links = [] if not (TWA_PACKAGE and TWA_SHA256) else [{
                "relation": ["delegate_permission/common.handle_all_urls"],
                "target": {"namespace": "android_app", "package_name": TWA_PACKAGE,
                           "sha256_cert_fingerprints": [x.strip() for x in TWA_SHA256.split(",") if x.strip()]}}]
            return self.send_json(200, links)
        if path_only.startswith("/api/m/avatar/"):
            return self.send_avatar(path_only.rsplit("/", 1)[1])
        if path_only.startswith("/api/verify/cert/") and path_only.rsplit("/", 1)[1].isdigit():
            with connect() as conn:
                user = user_for_token(conn, self.session_token())
            f = VERIFY_DIR / f"{int(path_only.rsplit('/', 1)[1])}.jpg"
            if not user or user["role"] != "admin" or not f.is_file():
                return self.send_json(404, {"error": "not found"})
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        if path_only.startswith("/api/m/video/") and path_only.rsplit("/", 1)[1].isdigit():
            return self.send_video(int(path_only.rsplit("/", 1)[1]))
        m = re.fullmatch(r"/api/m/oauth/(facebook|x)/(start|callback)", path_only)
        if m:
            return self.oauth_get(m.group(1), m.group(2))
        if path_only.startswith("/api/m/gallery/"):
            gid = path_only.rsplit("/", 1)[1]
            f = GALLERY_DIR / f"{int(gid)}.jpg" if gid.isdigit() else None
            if not f or not f.is_file():
                return self.send_json(404, {"error": "not found"})
            body = f.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.is_public_file():
            return self.send_json(404, {"error": "not found"})
        return super().do_GET()

    def do_HEAD(self):
        if not self.is_public_file():
            return self.send_json(404, {"error": "not found"})
        return super().do_HEAD()

    def is_public_file(self):
        """Allowlist: only the website itself and its images. Everything else (database, .env, code,
        git history, tools) is never served, however the address is written (%2e, ./, etc.)."""
        try:
            real = Path(self.translate_path(self.path)).resolve()
            rel = real.relative_to(ROOT.resolve())
        except (ValueError, OSError):
            return False
        parts = rel.parts
        if any(part.startswith(".") for part in parts):
            return False
        if not parts:  # the home page "/"
            return True
        if len(parts) == 1:
            return parts[0] in PUBLIC_FILES
        return parts[0] == "assets" and real.is_file()

    def send_avatar(self, raw_id):
        try:
            mid = int(raw_id)
        except ValueError:
            return self.send_json(404, {"error": "not found"})
        with DB_LOCK, connect() as conn:
            row = conn.execute("SELECT kind, photo_ts FROM members WHERE id=?", (mid,)).fetchone()
            if not row or not row["photo_ts"]:
                return self.send_json(404, {"error": "not found"})
            if row["kind"] != "doctor":  # patient photos: only the patient and people they chat with
                me = member_for_token(conn, self.member_token())
                if not me or (me["id"] != mid and not conn.execute(
                        "SELECT 1 FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) LIMIT 1",
                        (mid, me["id"], me["id"], mid)).fetchone()):
                    return self.send_json(404, {"error": "not found"})
        f = AVATAR_DIR / f"{mid}.jpg"
        if not f.is_file():
            return self.send_json(404, {"error": "not found"})
        body = f.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, limit):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > limit:
            raise InputError("Request too large or empty")
        try:
            return json.loads(self.rfile.read(length))
        except ValueError:
            raise InputError("Bad JSON")

    def do_POST(self):
        path = self.path.split("?")[0]
        if path in ("/api/pay/razorpay-webhook", "/api/pay/paypal-webhook"):
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(min(length, 1_000_000))
            try:
                with DB_LOCK, connect() as conn:
                    if path.endswith("razorpay-webhook"):
                        if not (RAZORPAY_ON and RAZORPAY_WEBHOOK_SECRET):
                            return self.send_json(400, {"error": "Webhook not configured"})
                        razorpay_webhook(conn, payload, self.headers.get("X-Razorpay-Signature", ""))
                    else:
                        if not (PAYPAL_ON and PAYPAL_WEBHOOK_ID):
                            return self.send_json(400, {"error": "Webhook not configured"})
                        paypal_webhook(conn, payload, self.headers)
                return self.send_json(200, {"received": True})
            except Exception:
                return self.send_json(400, {"error": "Invalid webhook"})
        if path == "/api/pay/webhook":
            if not STRIPE_ON or not STRIPE_WEBHOOK_SECRET:
                return self.send_json(400, {"error": "Webhook not configured"})
            length = int(self.headers.get("Content-Length") or 0)
            payload = self.rfile.read(min(length, 1_000_000))
            try:
                with DB_LOCK, connect() as conn:
                    stripe_webhook(conn, payload, self.headers.get("Stripe-Signature", ""))
                return self.send_json(200, {"received": True})
            except Exception:
                return self.send_json(400, {"error": "Invalid webhook"})
        # Video uploads send the raw file. "video/..." is not a type other websites can send without the browser's
        # permission check (CORS preflight), so this is as safe against cross-site posts as the JSON rule below.
        if path == "/api/m/video/upload" and (self.headers.get("Content-Type") or "").startswith("video/"):
            return self.video_upload_raw()
        # Only JSON requests: blocks other websites from submitting plain forms here (CSRF)
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send_json(415, {"error": "JSON required"})
        if path in ("/api/auth/login", "/api/auth/setup", "/api/auth/logout"):
            return self.auth(path)
        if path.startswith("/api/m/"):
            return self.member(path)
        if path in MCALL_ROUTES:
            try:
                data = self.read_json(40_000)
                if not isinstance(data, dict):
                    raise InputError("Bad request")
                with DB_LOCK, connect() as conn:
                    return self.send_json(200, MCALL_ROUTES[path](conn, data, member_for_token(conn, self.member_token())))
            except InputError as e:
                return self.send_json(400, {"error": str(e)})
            except AuthError as e:
                return self.send_json(e.status, {"error": str(e)})
        if path == "/api/foodscan":
            try:
                data = self.read_json(7_000_000)
                if not isinstance(data, dict):
                    raise InputError("Bad request")
                return self.send_json(200, food_scan(data, self.client_ip()))
            except InputError as e:
                return self.send_json(400, {"error": str(e)})
            except AuthError as e:
                return self.send_json(e.status, {"error": str(e)})
            except Exception as e:
                print("Food scan error:", repr(e)[:300])
                return self.send_json(502, {"error": "The food checker is busy. Please try again."})
        if path == "/api/unidocs":
            try:
                data = self.read_json(2_000)
                if not isinstance(data, dict):
                    raise InputError("Bad request")
                return self.send_json(200, uni_doctors(None, data, self.client_ip()))
            except InputError as e:
                return self.send_json(400, {"error": str(e)})
            except AuthError as e:
                return self.send_json(e.status, {"error": str(e)})
            except Exception as e:
                print("University search error:", repr(e)[:300])
                return self.send_json(502, {"error": "The search service is busy. Please try again."})
        if path in CALL_ROUTES:
            try:
                data = self.read_json(40_000)
                if not isinstance(data, dict):
                    raise InputError("Bad request")
                with DB_LOCK, connect() as conn:
                    return self.send_json(200, CALL_ROUTES[path](conn, data, user_for_token(conn, self.session_token())))
            except InputError as e:
                return self.send_json(400, {"error": str(e)})
            except AuthError as e:
                return self.send_json(e.status, {"error": str(e)})
        if path == "/api/pay/checkout" and too_many("pay", self.client_ip(), 20, 600):
            return self.send_json(429, {"error": "Too many payment attempts. Please wait a few minutes."})
        if path in ROUTES:
            try:
                data = self.read_json(20_000)
                if not isinstance(data, dict):
                    raise InputError("Bad request")
                return self.send_json(200, run_route(path, data, self.session_token()))
            except InputError as e:
                return self.send_json(400, {"error": str(e)})
            except AuthError as e:
                return self.send_json(e.status, {"error": str(e)})
            except Exception as e:
                if stripe and isinstance(e, stripe.StripeError):
                    return self.send_json(502, {"error": f"Payment provider error: {getattr(e, 'user_message', None) or 'please try again'}"})
                if isinstance(e, ProviderError):
                    print("Payment provider error:", e)
                    return self.send_json(502, {"error": "The payment provider didn't respond correctly. Please try again."})
                raise
        if not path.startswith("/api/chat"):
            return self.send_json(404, {"error": "not found"})
        if client is None:
            return self.send_json(503, {"code": "ai_unavailable",
                                        "error": "Our AI assistant is taking a short break. I'll help you with quick replies instead."})
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            return self.send_json(413, {"error": "Message too large."})
        try:
            data = json.loads(self.rfile.read(length))
            messages = data["messages"][-MAX_MESSAGES:]
            context = str(data.get("context", ""))[:2000]
        except (ValueError, KeyError, TypeError):
            return self.send_json(400, {"error": "Bad request."})
        try:
            return self.send_json(200, chat_turn(messages, context))
        except anthropic.APIError as e:
            # Patients never see technical details (API keys, billing, error codes).
            # The real reason goes to the server log for the clinic's admin.
            print(f"[AI] chat failed: {type(e).__name__} {getattr(e, 'status_code', '')} {getattr(e, 'message', e)}", flush=True)
            if isinstance(e, anthropic.RateLimitError):
                return self.send_json(429, {"code": "ai_busy",
                                            "error": "Our AI assistant is very busy right now. I'll help you with quick replies instead."})
            return self.send_json(503, {"code": "ai_unavailable",
                                        "error": "Our AI assistant is taking a short break. I'll help you with quick replies instead."})

    def client_ip(self):
        if TRUST_PROXY:
            fwd = (self.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
            if fwd:
                return fwd
        return self.client_address[0]

    def send_text(self, status, body, ctype):
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def video_upload_raw(self):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            if length <= 0 or length > MAX_VIDEO_BYTES:
                raise InputError("That video is too large. Please keep it under 30 MB (about 1 minute).")
            raw = self.rfile.read(length)
            mime = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            with DB_LOCK, connect() as conn:
                me = member_for_token(conn, self.member_token())
                out = video_upload(conn, me, mime, raw, int((q.get("listing_id") or ["0"])[0] or 0), (q.get("caption") or [""])[0])
                return self.send_json(200, {"result": out})
        except InputError as e:
            return self.send_json(400, {"error": str(e)})
        except AuthError as e:
            return self.send_json(e.status, {"error": str(e)})

    def send_video(self, vid):
        with connect() as conn:
            v = video_visible(conn, vid, member_for_token(conn, self.member_token()))
        f = video_file(vid, v["mime"]) if v else None
        if not f or not f.is_file():
            return self.send_json(404, {"error": "not found"})
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = re.fullmatch(r"bytes=(\d*)-(\d*)", self.headers.get("Range") or "")
        if rng and (rng.group(1) or rng.group(2)):
            if rng.group(1):
                start = int(rng.group(1)); end = min(int(rng.group(2)) if rng.group(2) else size - 1, size - 1)
            else:
                start = max(0, size - int(rng.group(2)))
            if start > end:
                self.send_response(416); self.send_header("Content-Range", f"bytes */{size}"); self.end_headers(); return
        with f.open("rb") as fh:
            fh.seek(start)
            body = fh.read(end - start + 1)
        self.send_response(206 if rng else 200)
        self.send_header("Content-Type", v["mime"])
        self.send_header("Accept-Ranges", "bytes")
        if rng:
            self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "private, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location, cookie=None):
        self.send_response(302)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def oauth_get(self, prov, step):
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        on = oauth_status()[prov]
        if not on:
            return self.redirect("/#account/login-soon")
        if step == "start":
            if too_many("oauth", self.client_ip(), 30, 3600):
                return self.redirect("/#account/login-error")
            return self.redirect(oauth_start_url(prov, (q.get("kind") or ["patient"])[0]))
        try:
            with DB_LOCK, connect() as conn:
                mid = oauth_finish(conn, prov, q)
                token = new_member_session(conn, mid)
            return self.redirect("/#account", cookie=self.member_cookie(token, 30 * 86_400))
        except (InputError, AuthError, ProviderError) as e:
            print(f"[login] {prov} sign-in failed: {e}", flush=True)
            return self.redirect("/#account/login-error")

    def member_token(self):
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "cl_member":
                return v
        return ""

    def member_cookie(self, token, max_age):
        secure = "; Secure" if (self.headers.get("X-Forwarded-Proto") == "https" or PUBLIC_URL.startswith("https://")) else ""
        return f"cl_member={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={max_age}{secure}"

    def member(self, path):
        ip = self.client_ip()
        try:
            data = self.read_json(1_700_000 if path in ("/api/m/gallery/add", "/api/m/verify/submit") else 450_000 if path == "/api/m/photo" else 10_000)
            if not isinstance(data, dict):
                raise InputError("Bad request")
            with DB_LOCK, connect() as conn:
                if path == "/api/m/logout":
                    conn.execute("DELETE FROM member_sessions WHERE token=?", (token_hash(self.member_token()),))
                    return self.send_json(200, {"me": None}, cookie=self.member_cookie("", 0))
                if path == "/api/m/delete":
                    me = member_for_token(conn, self.member_token())
                    m_delete_account(conn, data, me, ip)
                    return self.send_json(200, {"me": None, "deleted": True}, cookie=self.member_cookie("", 0))
                if path == "/api/m/forgot":
                    return self.send_json(200, m_forgot(conn, data, ip))
                if path == "/api/m/reset":
                    mid = m_reset(conn, data)
                    token = new_member_session(conn, mid)  # logged in on this device with the new password
                    return self.send_json(200, member_state(conn, member_for_token(conn, token)), cookie=self.member_cookie(token, 30 * 86_400))
                if path in ("/api/m/notifs", "/api/m/notifs/read"):  # light: polled by the bell, no listings
                    me = member_for_token(conn, self.member_token())
                    return self.send_json(200, (m_notifs if path.endswith("notifs") else m_notifs_read)(conn, data, me))
                if path == "/api/m/password":
                    me = member_for_token(conn, self.member_token())
                    extra = m_password(conn, data, me, ip)
                    # signs out every other phone or computer; this one stays logged in
                    conn.execute("DELETE FROM member_sessions WHERE member_id=? AND token<>?", (me["id"], token_hash(self.member_token())))
                    out = member_state(conn, me)
                    out["result"] = extra
                    return self.send_json(200, out)
                if path == "/api/m/oauth/google":
                    if too_many("oauth", ip, 30, 3600):
                        raise AuthError("Too many sign-in attempts. Try again later.", 429)
                    mid = google_login(conn, data)
                    token = new_member_session(conn, mid)
                    return self.send_json(200, member_state(conn, member_for_token(conn, token)), cookie=self.member_cookie(token, 30 * 86_400))
                if path in ("/api/m/signup", "/api/m/login"):
                    mid = (m_signup if path.endswith("signup") else m_login)(conn, data, None, ip)
                    token = new_member_session(conn, mid)
                    me = member_for_token(conn, token)
                    return self.send_json(200, member_state(conn, me), cookie=self.member_cookie(token, 30 * 86_400))
                if path not in MEMBER_ROUTES:
                    return self.send_json(404, {"error": "not found"})
                me = member_for_token(conn, self.member_token())
                extra = MEMBER_ROUTES[path](conn, data, me) or {}
                if me:  # re-read: the route may have changed the photo or online status
                    me = member_for_token(conn, self.member_token())
                out = member_state(conn, me)
                out["result"] = extra
                out["listings"] = public_listings(conn)
                return self.send_json(200, out)
        except InputError as e:
            return self.send_json(400, {"error": str(e)})
        except AuthError as e:
            return self.send_json(e.status, {"error": str(e)})

    def auth(self, path):
        try:
            data = self.read_json(5_000) if path != "/api/auth/logout" else {}
            with DB_LOCK, connect() as conn:
                if path == "/api/auth/logout":
                    conn.execute("DELETE FROM sessions WHERE token=?", (token_hash(self.session_token()),))
                    return self.send_json(200, {"ok": True, "data": snapshot(conn)}, self.cookie("", 0))
                uid = setup_admin(conn, data) if path == "/api/auth/setup" else login(conn, data, self.client_ip())
                token = new_session(conn, uid)
                user = user_for_token(conn, token)
                return self.send_json(200, {"ok": True, "data": snapshot(conn, user)},
                                      self.cookie(token, SESSION_DAYS * 86_400))
        except InputError as e:
            return self.send_json(400, {"error": str(e)})
        except AuthError as e:
            return self.send_json(e.status, {"error": str(e)})

    def log_message(self, fmt, *args):
        first = str(args[0]) if args else ""
        if "/api/" in first and "/api/call/poll" not in first:
            super().log_message(fmt, *args)


if __name__ == "__main__":
    if len(sys.argv) > 2 and sys.argv[1] == "--translate":
        # Pre-translate languages ahead of time:  python server.py --translate all   (or: --translate bn,ur,sw)
        wanted = [c for c in language_catalog() if c not in BUILTIN_LANGS] if sys.argv[2] == "all" else sys.argv[2].split(",")
        for i, code in enumerate(wanted, 1):
            try:
                n = len(translate_language(code))
                print(f"[{i}/{len(wanted)}] {code}: {n} texts ready")
            except Exception as e:
                print(f"[{i}/{len(wanted)}] {code}: FAILED - {e}")
        sys.exit(0)
    init_db()
    print("Database:", DB_PATH)
    print(f"Clinora AI running at http://localhost:{PORT}")
    print("AI:", "ON (" + MODEL + ")" if client else "OFF - " + AI_REASON)
    on = [n for n, ok in (("Stripe", STRIPE_ON), ("Razorpay", RAZORPAY_ON), ("PayPal (" + os.environ.get("PAYPAL_ENV", "sandbox") + ")", PAYPAL_ON)) if ok]
    print("Payments:", ", ".join(on) if on else ("OFF (production: no provider keys, online payment disabled)" if PRODUCTION
          else "DEMO mode (no money moves). Add provider keys to .env for real payments."))
    if PRODUCTION and not PUBLIC_URL.startswith("https://"):
        print("WARNING: APP_ENV=production but PUBLIC_URL is not https://. Real payments must only run over HTTPS.")
    threading.Thread(target=reminder_loop, daemon=True).start()
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), PORT), Handler).serve_forever()

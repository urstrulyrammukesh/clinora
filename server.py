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
CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT, reporter_id INTEGER NOT NULL, target_type TEXT NOT NULL,
  target_id INTEGER NOT NULL, owner_id INTEGER, reason TEXT NOT NULL, details TEXT, evidence TEXT, status TEXT NOT NULL DEFAULT 'open',
  action TEXT, ts INTEGER NOT NULL, reviewed INTEGER, reviewer TEXT);
CREATE INDEX IF NOT EXISTS report_target ON reports(target_type, target_id, status);
CREATE TABLE IF NOT EXISTS blocks(member_id INTEGER NOT NULL, blocked_id INTEGER NOT NULL, ts INTEGER NOT NULL, PRIMARY KEY(member_id, blocked_id));
CREATE TABLE IF NOT EXISTS dbookings(id INTEGER PRIMARY KEY AUTOINCREMENT, listing_id INTEGER NOT NULL, patient_id INTEGER NOT NULL,
  for_name TEXT NOT NULL, date TEXT NOT NULL, time TEXT NOT NULL, tz TEXT NOT NULL, at INTEGER NOT NULL, mode TEXT NOT NULL, reason TEXT,
  status TEXT NOT NULL, fee INTEGER, cur TEXT, cancel_by TEXT, cancel_reason TEXT, ts INTEGER NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS dbook_slot ON dbookings(listing_id, date, time) WHERE status='booked';
CREATE INDEX IF NOT EXISTS dbook_patient ON dbookings(patient_id, at);
CREATE TABLE IF NOT EXISTS push_subs(endpoint TEXT PRIMARY KEY, member_id INTEGER NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS family(id INTEGER PRIMARY KEY AUTOINCREMENT, member_id INTEGER NOT NULL, name TEXT NOT NULL, relation TEXT NOT NULL,
  year INTEGER, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS prescriptions(id INTEGER PRIMARY KEY AUTOINCREMENT, booking_id INTEGER UNIQUE NOT NULL, doctor_id INTEGER NOT NULL,
  patient_id INTEGER NOT NULL, data TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS wa_threads(phone TEXT PRIMARY KEY, history TEXT NOT NULL, ts INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS email_confirms(token TEXT PRIMARY KEY, member_id INTEGER NOT NULL, expires INTEGER NOT NULL);
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
    if PRODUCTION:  # live site: start clean, no sample patients
        for key in ("clinic", "d1", "d2", "d3", "d4"):
            conn.execute("INSERT OR REPLACE INTO live VALUES(?,?)", (key, 1))
        conn.execute("INSERT OR REPLACE INTO stats VALUES('chats', 0)")
        return
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
        if "suspended" not in mcols:
            conn.execute("ALTER TABLE members ADD COLUMN suspended INTEGER NOT NULL DEFAULT 0")
        if "email_ok" not in mcols:  # accounts made before email confirmation existed count as confirmed
            conn.execute("ALTER TABLE members ADD COLUMN email_ok INTEGER NOT NULL DEFAULT 0")
            conn.execute("UPDATE members SET email_ok=1")
        conn.executescript(EXTRA_SCHEMA)
        bcols = {r["name"] for r in conn.execute("PRAGMA table_info(dbookings)")}
        for col, kind in [("pay_status", "TEXT NOT NULL DEFAULT 'none'"), ("pay_ref", "TEXT"), ("pay_amount", "INTEGER"), ("hold_until", "INTEGER")]:
            if col not in bcols:
                conn.execute(f"ALTER TABLE dbookings ADD COLUMN {col} {kind}")
        if "payout_acc" not in {r["name"] for r in conn.execute("PRAGMA table_info(listings)")}:
            conn.execute("ALTER TABLE listings ADD COLUMN payout_acc TEXT")
        rcols = {r["name"] for r in conn.execute("PRAGMA table_info(reminders)")}
        if "ref" not in rcols:
            conn.execute("ALTER TABLE reminders ADD COLUMN ref TEXT")
        if "until" not in rcols:
            conn.execute("ALTER TABLE reminders ADD COLUMN until TEXT")
        lcols = {r["name"] for r in conn.execute("PRAGMA table_info(listings)")}
        for col, kind in [("owner", "INTEGER"), ("social", "TEXT"), ("hours", "TEXT"), ("tz", "TEXT"), ("hidden", "INTEGER NOT NULL DEFAULT 0"), ("booking", "TEXT")]:
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


ADMIN_SETUP_CODE = os.environ.get("ADMIN_SETUP_CODE", "").strip()


def setup_admin(conn, d):
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]:
        raise AuthError("Setup is already done. Please log in.")
    # On the live site the first visitor must not become admin: creating it needs the code from the server settings.
    if PRODUCTION or ADMIN_SETUP_CODE:
        if not ADMIN_SETUP_CODE:
            raise AuthError("Admin setup is locked. Set ADMIN_SETUP_CODE in the server settings, restart, then try again.", 403)
        if not hmac.compare_digest(str(d.get("code") or "").strip().encode(), ADMIN_SETUP_CODE.encode()):
            raise AuthError("Wrong setup code.", 403)
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
        "setup_code": PRODUCTION or bool(ADMIN_SETUP_CODE), "production": PRODUCTION,
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
            data["reports_open"] = conn.execute("SELECT COUNT(DISTINCT target_type || target_id) FROM reports WHERE status='open'").fetchone()[0]
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
    if PRODUCTION:
        raise AuthError("Reset is turned off on the live site, so real bookings can never be deleted by mistake.")
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
        "FROM listings l LEFT JOIN members m ON m.id = l.owner WHERE l.hidden = 0 ORDER BY l.ts")
    out = []
    for r in rows:
        d = dict(r)
        seen = d.pop("m_seen")
        d["online"] = bool(d.pop("m_online")) and (seen or 0) > cutoff
        d["last_seen"] = seen or None
        d["video"] = bool(d["video"])
        d["verified"] = bool(d.get("verified"))
        cfg = booking_cfg(d)
        d["booking"] = dict({k: cfg[k] for k in ("fee", "cur", "modes", "slot")}, prepay=bool(cfg.get("prepay"))) if cfg else None
        d.pop("payout_acc", None)  # private
        d["page"] = "/doctor/" + doctor_slug(d)
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
        "SELECT m.id, m.email, m.name, m.kind, m.city, m.online, m.photo_ts, m.email_ok FROM member_sessions s JOIN members m ON m.id = s.member_id "
        "WHERE s.token = ? AND s.expires > ? AND m.suspended = 0", (token_hash(token), now_ms())).fetchone()
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


def need_confirmed(me):
    """Messaging, reviews, uploads, bookings and doctor profiles need a confirmed email: stops fake accounts."""
    if not me.get("email_ok"):
        raise AuthError("Please confirm your email first. We sent you a link (check spam too). You can resend it on your Account page.", 403)


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
            "verification": dict(ver) if ver else None, "reminders": reminder_list(conn, me["id"]), "bookings": my_bookings(conn, me), "push_key": PUSH_KEY,
            "family": [dict(r) for r in conn.execute("SELECT id, name, relation, year FROM family WHERE member_id=? ORDER BY id", (me["id"],))],
            "favs": fav_ids, "threads": threads,
            "listing": dict(lst, social=json.loads(lst["social"] or "{}"), video=bool(lst["video"]),
                            booking=json.loads(lst["booking"] or "null")) if lst else None}


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
    send_confirm_email(conn, cur.lastrowid)
    return cur.lastrowid


def m_login(conn, d, me, ip):
    if too_many_failures(ip):
        raise AuthError("Too many failed attempts. Try again in 15 minutes.", 429)
    row = conn.execute("SELECT id, pw FROM members WHERE email=?", (str(d.get("email") or "").strip().lower(),)).fetchone()
    if not row or not check_password(str(d.get("password") or ""), row["pw"]):
        FAILED_LOGINS.setdefault(ip, []).append(time.time())
        raise AuthError("Wrong email or password.", 401)
    if conn.execute("SELECT suspended FROM members WHERE id=?", (row["id"],)).fetchone()[0]:
        raise AuthError("This account is suspended after reports from other users. Contact support if you think this is a mistake.", 403)
    return row["id"]


def m_profile(conn, d, me):
    """A doctor creates or updates their own public listing."""
    need_member(me, "doctor")
    need_confirmed(me)
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
    need_confirmed(me)
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
    if conn.execute("SELECT 1 FROM blocks WHERE member_id=? AND blocked_id=?", (me["id"], to)).fetchone():
        raise InputError("You blocked this person. Unblock them to send a message.")
    if conn.execute("SELECT 1 FROM blocks WHERE member_id=? AND blocked_id=?", (to, me["id"])).fetchone():
        raise AuthError("You can't message this person.")
    if me["kind"] == "patient" and other_kind != "doctor":
        raise AuthError("Patients can message doctors only.")
    if me["kind"] == "doctor" and other_kind == "patient" and not has_booking(conn, me["id"], to) and not conn.execute(
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
    blocked = bool(conn.execute("SELECT 1 FROM blocks WHERE member_id=? AND blocked_id=?", (me["id"], other)).fetchone())
    return {"with": {"id": o["id"], "name": o["name"], "kind": o["kind"], "online": online, "photo_ts": o["photo_ts"], "blocked": blocked}, "messages": msgs}


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
    need_confirmed(me)
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
    need_confirmed(me)
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
    need_confirmed(me)
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
    until = r.get("until") if isinstance(r, dict) else (r["until"] if "until" in r.keys() else None)
    for i in range(10):
        day = start + datetime.timedelta(days=i)
        if until and day.isoformat() > until:
            return None  # the course is finished
        if r["days"] & (1 << day.weekday()):  # bit 0 = Monday … bit 6 = Sunday
            ms = int((datetime.datetime(day.year, day.month, day.day, h, m, tzinfo=zone) - lead).timestamp() * 1000)
            if ms > after_ms:
                return ms
    return None


def reminder_list(conn, mid):
    return [dict(r) for r in conn.execute("SELECT id, kind, title, note, at, days, date, tz, lead, email, active, next_at, last_sent, until "
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
    until = str(d.get("until") or "") or None
    if until and (not days or not DATE_RE.match(until)):
        raise InputError("Check the end date")
    r = {"at": at, "days": days, "date": date, "tz": tz, "lead": lead, "until": until}
    nxt = reminder_next(r, now_ms())
    if nxt is None:
        raise InputError("That time has already passed. Pick a time in the future.")
    vals = (kind, title, text(d, "note", 200, False), at, days, date, tz, lead, 1 if d.get("email") else 0, nxt, until)
    if rid:
        conn.execute("UPDATE reminders SET kind=?,title=?,note=?,at=?,days=?,date=?,tz=?,lead=?,email=?,next_at=?,until=?,active=1 WHERE id=?", vals + (rid,))
    else:
        rid = conn.execute("INSERT INTO reminders(kind,title,note,at,days,date,tz,lead,email,next_at,until,member_id,created) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
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
                release_unpaid(conn)
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
    conn.execute("DELETE FROM push_subs WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM family WHERE member_id=?", (mid,))
    conn.execute("DELETE FROM prescriptions WHERE patient_id=? OR doctor_id=?", (mid, mid))
    for (bid, owner, when) in conn.execute("SELECT b.id, l.owner, b.date || ' ' || b.time FROM dbookings b JOIN listings l ON l.id=b.listing_id "
                                           "WHERE b.patient_id=? AND b.status='booked' AND b.at>?", (mid, now_ms())).fetchall():
        notify(conn, owner, "booking", "❌ A patient cancelled", f"{when} · the patient deleted their account", "account")
    for (pid, when, lname) in conn.execute("SELECT b.patient_id, b.date || ' ' || b.time, l.name FROM dbookings b JOIN listings l ON l.id=b.listing_id "
                                           "WHERE l.owner=? AND b.status='booked' AND b.at>?", (mid, now_ms())).fetchall():
        notify(conn, pid, "booking", f"❌ {lname} cancelled your visit", f"{when} · the doctor left Clinora. Please book someone else.", "account")
        conn.execute("DELETE FROM reminders WHERE member_id=? AND ref LIKE 'dbook:%' AND title LIKE ?", (pid, lname + "%"))
    conn.execute("DELETE FROM dbookings WHERE patient_id=? OR listing_id IN (SELECT id FROM listings WHERE owner=?)", (mid, mid))
    conn.execute("DELETE FROM reports WHERE reporter_id=?", (mid,))
    conn.execute("DELETE FROM blocks WHERE member_id=? OR blocked_id=?", (mid, mid))
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
NOTIF_KINDS = {"welcome", "message", "review", "reply", "call", "video", "security", "reminder", "booking"}


def notify(conn, member_id, kind, title, body="", link=""):
    if not member_id:
        return
    conn.execute("INSERT INTO notifs(member_id,kind,title,body,link,ts) VALUES(?,?,?,?,?,?)",
                 (member_id, kind if kind in NOTIF_KINDS else "welcome", str(title)[:120], str(body or "")[:200], str(link or "")[:60], now_ms()))
    # keep the newest 100 per person
    conn.execute("DELETE FROM notifs WHERE member_id=? AND id NOT IN (SELECT id FROM notifs WHERE member_id=? ORDER BY id DESC LIMIT 100)",
                 (member_id, member_id))
    if kind not in PUSH_SKIP:
        push_to(conn, member_id, str(title)[:120], str(body or "")[:200], str(link or ""))


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
    need_confirmed(me)
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


# ---------------------------------------------------------------- confirm email on sign-up
CONFIRM_HOURS = 48


def send_confirm_email(conn, mid):
    row = conn.execute("SELECT email, name, email_ok FROM members WHERE id=?", (mid,)).fetchone()
    if not row or row["email_ok"] or row["email"].endswith("@users.clinora.invalid"):
        return
    token = secrets.token_urlsafe(32)
    conn.execute("DELETE FROM email_confirms WHERE expires < ? OR member_id=?", (now_ms(), mid))
    conn.execute("INSERT INTO email_confirms VALUES(?,?,?)", (token_hash(token), mid, now_ms() + CONFIRM_HOURS * 3600_000))
    link = f"{PUBLIC_URL}/#confirm/{token}"
    first = html.escape((row["name"] or "there").split()[0])
    send_email(row["email"], "Confirm your email for Clinora",
               f"Hi {first},\n\nWelcome to Clinora! Please confirm your email by opening this link (it works for {CONFIRM_HOURS} hours):\n{link}\n\n"
               "If you didn't create a Clinora account, ignore this email.\n\nClinora",
               f"""<div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;max-width:480px;margin:auto;padding:24px;color:#0f172a">
<h2 style="color:#0d9488;margin:0 0 12px">Confirm your email</h2><p>Hi {first},</p><p>Welcome to Clinora! Tap the button to confirm this is your email.</p>
<p style="margin:26px 0"><a href="{link}" style="background:#0d9488;color:#fff;padding:12px 22px;border-radius:10px;text-decoration:none;font-weight:700">Confirm my email</a></p>
<p style="color:#475569;font-size:14px">This link works for {CONFIRM_HOURS} hours. If you didn't create a Clinora account, ignore this email.</p>
<p style="color:#94a3b8;font-size:12px;margin-top:28px">Clinora · find doctors, book visits</p></div>""")


def m_confirm_resend(conn, d, me):
    need_member(me)
    if me.get("email_ok"):
        return {"already": True}
    if too_many("confirm", str(me["id"]), 3, 3600):
        raise AuthError("We already sent a few links. Please check your inbox and spam folder, or try again in an hour.", 429)
    send_confirm_email(conn, me["id"])
    return {"sent": True}


def m_confirm(conn, d):
    token = str(d.get("token") or "")
    row = conn.execute("SELECT member_id, expires FROM email_confirms WHERE token=?", (token_hash(token),)).fetchone() if token else None
    if not row or row["expires"] < now_ms():
        raise AuthError("This confirmation link has expired or was already used. Log in and tap Resend on your Account page.", 400)
    conn.execute("UPDATE members SET email_ok=1 WHERE id=?", (row["member_id"],))
    conn.execute("DELETE FROM email_confirms WHERE member_id=?", (row["member_id"],))
    notify(conn, row["member_id"], "security", "✅ Email confirmed", "You can now message doctors, write reviews and book visits.", "account")
    return row["member_id"]


def m_reset(conn, d):
    token = str(d.get("token") or "")
    row = conn.execute("SELECT member_id, expires, used FROM pw_resets WHERE token=?", (token_hash(token),)).fetchone() if token else None
    if not row or row["used"] or row["expires"] < now_ms():
        raise AuthError("This reset link has expired or was already used. Please ask for a new one.", 400)
    new = valid_password(d, "new")
    mid = row["member_id"]
    conn.execute("UPDATE members SET pw=?, email_ok=1 WHERE id=?", (hash_password(new), mid))
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
    mid = _social_member(conn, prov, pid, email, name, kind)
    if conn.execute("SELECT suspended FROM members WHERE id=?", (mid,)).fetchone()[0]:
        raise AuthError("This account is suspended after reports from other users. Contact support if you think this is a mistake.", 403)
    return mid


def _social_member(conn, prov, pid, email, name, kind):
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
            conn.execute("UPDATE members SET provider=COALESCE(provider, ?), provider_id=COALESCE(provider_id, ?), email_ok=1 WHERE id=?",
                         (prov, pid, row["id"]))
            return row["id"]
    kind = kind if kind in MEMBER_KINDS else "patient"
    cur = conn.execute("INSERT INTO members(email,name,kind,pw,created,last_seen,provider,provider_id,email_ok) VALUES(?,?,?,?,?,?,?,?,1)",
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
    need_confirmed(me)
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


# ---------------------------------------------------------------- reports & blocking
# Anyone logged in can report a doctor profile, a review, a video or a person who messaged them.
# The clinic admin reviews reports in the Clinic Dashboard and can remove the content, hide a profile or suspend an account.
REPORT_TYPES = {"listing", "review", "video", "member"}
REPORT_REASONS = {"fake": "Fake or pretending to be someone", "spam": "Spam or advertising", "abuse": "Rude, hateful or harassing",
                  "unsafe": "Dangerous medical advice", "sexual": "Sexual or inappropriate", "privacy": "Shares private information",
                  "wrong": "Wrong details (address, phone...)", "other": "Something else"}


def _report_target(conn, kind, tid, me):
    """Returns (owner member id, evidence dict) for something that can be reported, or raises."""
    if kind == "listing":
        r = conn.execute("SELECT name, spec, city, phone, owner FROM listings WHERE id=?", (tid,)).fetchone()
        if not r:
            raise InputError("This profile no longer exists")
        return r["owner"], {"name": r["name"], "spec": r["spec"], "city": r["city"], "phone": r["phone"]}
    if kind == "review":
        r = conn.execute("SELECT r.member_id, r.stars, r.body, r.gif, l.name AS listing FROM reviews r JOIN listings l ON l.id=r.listing_id "
                         "WHERE r.id=?", (tid,)).fetchone()
        if not r:
            raise InputError("This review no longer exists")
        return r["member_id"], {"stars": r["stars"], "body": r["body"], "gif": r["gif"], "on": r["listing"]}
    if kind == "video":
        v = video_visible(conn, tid, me)
        if not v:
            raise InputError("This video no longer exists")
        return v["member_id"], {"kind": v["kind"], "caption": v["caption"]}
    o = conn.execute("SELECT id, name, kind FROM members WHERE id=?", (tid,)).fetchone()
    if not o:
        raise InputError("This account no longer exists")
    # the last messages between the two people go with the report, so the admin can see what happened
    msgs = [dict(m) for m in conn.execute(
        "SELECT from_id, body, ts FROM messages WHERE (from_id=? AND to_id=?) OR (from_id=? AND to_id=?) ORDER BY id DESC LIMIT 20",
        (me["id"], tid, tid, me["id"]))][::-1]
    return o["id"], {"name": o["name"], "kind": o["kind"], "messages": msgs}


def m_report(conn, d, me):
    need_member(me)
    if too_many("report", str(me["id"]), 20, 86400):
        raise AuthError("You have sent many reports today. Please try again tomorrow.", 429)
    kind = one_of(d, "type", REPORT_TYPES)
    reason = one_of(d, "reason", set(REPORT_REASONS))
    tid = int(d.get("id") or 0)
    details = text(d, "details", 500, False)
    if reason == "other" and len(details) < 5:
        raise InputError("Please tell us a little about the problem")
    owner, evidence = _report_target(conn, kind, tid, me)
    if owner == me["id"]:
        raise InputError("You can't report your own content")
    old = conn.execute("SELECT id FROM reports WHERE reporter_id=? AND target_type=? AND target_id=? AND status='open'",
                       (me["id"], kind, tid)).fetchone()
    if old:
        conn.execute("UPDATE reports SET reason=?, details=?, evidence=?, ts=? WHERE id=?",
                     (reason, details, json.dumps(evidence), now_ms(), old["id"]))
    else:
        conn.execute("INSERT INTO reports(reporter_id,target_type,target_id,owner_id,reason,details,evidence,ts) VALUES(?,?,?,?,?,?,?,?)",
                     (me["id"], kind, tid, owner, reason, details, json.dumps(evidence), now_ms()))
    if kind == "member" and d.get("block"):
        conn.execute("INSERT OR IGNORE INTO blocks VALUES(?,?,?)", (me["id"], tid, now_ms()))
    return {"reported": True}


def m_block(conn, d, me):
    need_member(me)
    other = int(d.get("with") or 0)
    if other == me["id"] or not conn.execute("SELECT 1 FROM members WHERE id=?", (other,)).fetchone():
        raise InputError("Can't block this person")
    if d.get("on"):
        conn.execute("INSERT OR IGNORE INTO blocks VALUES(?,?,?)", (me["id"], other, now_ms()))
    else:
        conn.execute("DELETE FROM blocks WHERE member_id=? AND blocked_id=?", (me["id"], other))
    return {"blocked": bool(d.get("on"))}


def _target_state(conn, kind, tid, owner):
    if kind == "listing":
        r = conn.execute("SELECT hidden FROM listings WHERE id=?", (tid,)).fetchone()
        st = "gone" if not r else "hidden" if r["hidden"] else "live"
    elif kind == "review":
        st = "live" if conn.execute("SELECT 1 FROM reviews WHERE id=?", (tid,)).fetchone() else "gone"
    elif kind == "video":
        st = "live" if conn.execute("SELECT 1 FROM videos WHERE id=?", (tid,)).fetchone() else "gone"
    else:
        st = "live"
    o = conn.execute("SELECT name, email, kind, suspended FROM members WHERE id=?", (owner,)).fetchone() if owner else None
    return st, (dict(o) if o else None)


def report_queue(conn, d, user):
    """Reports grouped by what was reported, open ones first."""
    need_admin(user)
    groups = {}
    for r in conn.execute("SELECT r.*, m.name AS reporter, m.email AS reporter_email FROM reports r LEFT JOIN members m ON m.id=r.reporter_id "
                          "ORDER BY CASE r.status WHEN 'open' THEN 0 ELSE 1 END, r.ts DESC LIMIT 400"):
        key = (r["target_type"], r["target_id"], r["status"] == "open")
        g = groups.get(key)
        if not g:
            st, owner = _target_state(conn, r["target_type"], r["target_id"], r["owner_id"])
            g = groups[key] = {"id": r["id"], "type": r["target_type"], "target_id": r["target_id"], "owner_id": r["owner_id"], "owner": owner,
                               "state": st, "status": r["status"], "action": r["action"], "reviewer": r["reviewer"],
                               "evidence": json.loads(r["evidence"] or "{}"), "ts": r["ts"], "reports": []}
        g["reports"].append({"reporter": r["reporter"], "reporter_email": r["reporter_email"],
                             "reason": REPORT_REASONS.get(r["reason"], r["reason"]), "details": r["details"], "ts": r["ts"]})
    items = list(groups.values())[:100]
    return {"reports": items, "open": sum(1 for g in items if g["status"] == "open")}


REPORT_ACTIONS = {"dismiss", "remove", "hide", "unhide", "suspend", "unsuspend"}


def report_decide(conn, d, user):
    need_admin(user)
    r = conn.execute("SELECT * FROM reports WHERE id=?", (int(d.get("id") or 0),)).fetchone()
    if not r:
        raise InputError("Report not found")
    action = one_of(d, "action", REPORT_ACTIONS)
    kind, tid, owner = r["target_type"], r["target_id"], r["owner_id"]
    if action == "remove":
        if kind == "review":
            conn.execute("DELETE FROM reviews WHERE id=?", (tid,))
            notify(conn, owner, "security", "Your review was removed",
                   "It broke the Clinora rules after a report. You can write a new, respectful review.", "account")
        elif kind == "video":
            v = conn.execute("SELECT mime FROM videos WHERE id=?", (tid,)).fetchone()
            if v:
                conn.execute("DELETE FROM videos WHERE id=?", (tid,))
                video_file(tid, v["mime"]).unlink(missing_ok=True)
            notify(conn, owner, "security", "Your video was removed", "It broke the Clinora rules after a report.", "account")
        else:
            raise InputError("Use hide or suspend for this report")
    elif action in ("hide", "unhide"):
        if kind != "listing":
            raise InputError("Only doctor profiles can be hidden")
        conn.execute("UPDATE listings SET hidden=? WHERE id=?", (1 if action == "hide" else 0, tid))
        notify(conn, owner, "security", "Your profile is hidden" if action == "hide" else "Your profile is visible again",
               "Patients can't find it after reports. Please update your details or contact support." if action == "hide" else "", "account")
    elif action in ("suspend", "unsuspend"):
        if not owner:
            raise InputError("No account to suspend")
        conn.execute("UPDATE members SET suspended=? WHERE id=?", (1 if action == "suspend" else 0, owner))
        if action == "suspend":
            conn.execute("DELETE FROM member_sessions WHERE member_id=?", (owner,))
    if action in ("unhide", "unsuspend"):  # undoing an earlier decision: the reports stay closed
        conn.execute("UPDATE reports SET action=?, reviewer=?, reviewed=? WHERE target_type=? AND target_id=?",
                     (action, user["name"], now_ms(), kind, tid))
        return report_queue(conn, d, user)
    reporters = [x[0] for x in conn.execute("SELECT DISTINCT reporter_id FROM reports WHERE target_type=? AND target_id=? AND status='open'", (kind, tid))]
    conn.execute("UPDATE reports SET status=?, action=?, reviewed=?, reviewer=? WHERE target_type=? AND target_id=? AND status='open'",
                 ("dismissed" if action == "dismiss" else "actioned", action, now_ms(), user["name"], kind, tid))
    for rid in reporters:
        notify(conn, rid, "security", "Thanks for your report",
               "We checked it and did not find a rule break this time." if action == "dismiss"
               else "We checked it and took action. Thank you for keeping Clinora safe.", "")
    return report_queue(conn, d, user)


# ---------------------------------------------------------------- database backups
# Every BACKUP_EVERY_HOURS (default 24) a safe copy of the database plus profile photos, work photos and
# verification certificates is packed into data/backups/clinora-<date>-<time>.tar.gz. The newest BACKUP_KEEP
# (default 14) are kept. With the BACKUP_S3_* settings each backup is also uploaded to cloud storage
# (Cloudflare R2, Backblaze B2, AWS S3...), so a lost server disk doesn't lose your data. See docs/backups.md.
BACKUP_DIR = Path(os.environ.get("BACKUP_DIR") or (DATA_DIR / "backups"))
BACKUP_EVERY_H = max(1.0, float(os.environ.get("BACKUP_EVERY_HOURS") or 24))
BACKUP_KEEP = max(2, int(os.environ.get("BACKUP_KEEP") or 14))
BACKUP_VIDEOS = os.environ.get("BACKUP_VIDEOS", "").strip() == "1"
S3_ENDPOINT = os.environ.get("BACKUP_S3_ENDPOINT", "").strip().rstrip("/")
S3_BUCKET = os.environ.get("BACKUP_S3_BUCKET", "").strip()
S3_KEY_ID = os.environ.get("BACKUP_S3_KEY_ID", "").strip()
S3_SECRET = os.environ.get("BACKUP_S3_SECRET", "").strip()
S3_REGION = os.environ.get("BACKUP_S3_REGION", "").strip() or "auto"
S3_ON = bool(S3_ENDPOINT.startswith("https://") and S3_BUCKET and S3_KEY_ID and S3_SECRET)
BACKUP_NAME_RE = re.compile(r"^clinora-\d{8}-\d{6}\.tar\.gz$")
BACKUP_FOLDERS = ("avatars", "gallery", "verify")
BACKUP_LOCK = threading.Lock()


def _backup_status(update=None):
    f = BACKUP_DIR / "status.json"
    try:
        st = json.loads(f.read_text())
    except Exception:
        st = {}
    if update:
        st.update(update)
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        f.write_text(json.dumps(st))
    return st


def list_backups():
    if not BACKUP_DIR.is_dir():
        return []
    out = [{"name": f.name, "size": f.stat().st_size, "ts": int(f.stat().st_mtime * 1000)}
           for f in BACKUP_DIR.iterdir() if BACKUP_NAME_RE.match(f.name)]
    return sorted(out, key=lambda b: b["name"], reverse=True)


def s3_put(key, path):
    """Uploads one file with AWS Signature V4 (works with S3, Cloudflare R2, Backblaze B2, Wasabi, MinIO)."""
    import urllib.parse
    import urllib.request
    body = Path(path).read_bytes()
    payload_hash = hashlib.sha256(body).hexdigest()
    host = urllib.parse.urlparse(S3_ENDPOINT).netloc
    now = datetime.datetime.now(datetime.timezone.utc)
    amz_date, day = now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%Y%m%d")
    uri = "/" + urllib.parse.quote(S3_BUCKET, safe="") + "/" + urllib.parse.quote(key, safe="/")
    signed = "content-type;host;x-amz-content-sha256;x-amz-date"
    canonical = "\n".join(["PUT", uri, "", "content-type:application/gzip", f"host:{host}",
                           f"x-amz-content-sha256:{payload_hash}", f"x-amz-date:{amz_date}", "", signed, payload_hash])
    scope = f"{day}/{S3_REGION}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    k = hmac.new(("AWS4" + S3_SECRET).encode(), day.encode(), hashlib.sha256).digest()
    for part in (S3_REGION, "s3", "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    sig = hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request(S3_ENDPOINT + uri, data=body, method="PUT", headers={
        "Content-Type": "application/gzip", "x-amz-content-sha256": payload_hash, "x-amz-date": amz_date,
        "Authorization": f"AWS4-HMAC-SHA256 Credential={S3_KEY_ID}/{scope}, SignedHeaders={signed}, Signature={sig}"})
    with urllib.request.urlopen(req, timeout=300) as r:
        if r.status not in (200, 201):
            raise RuntimeError(f"storage answered {r.status}")


def make_backup(reason="auto"):
    """Creates one backup file and returns its info. Safe to run while Clinora is serving people."""
    import tarfile
    if not BACKUP_LOCK.acquire(blocking=False):
        raise InputError("A backup is already running. Try again in a minute.")
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        name = "clinora-" + datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d-%H%M%S") + ".tar.gz"
        snap, part = BACKUP_DIR / ".snapshot.db", BACKUP_DIR / (name + ".part")
        snap.unlink(missing_ok=True)
        src, dst = sqlite3.connect(DB_PATH, timeout=30), sqlite3.connect(snap)
        try:
            src.backup(dst)  # SQLite's own online backup: a consistent copy even while people use the site
            if dst.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise RuntimeError("the database copy failed its integrity check")
            counts = {t: dst.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
                      for (t,) in dst.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        finally:
            src.close()
            dst.close()
        manifest = json.dumps({"app": "clinora", "created": now_ms(), "reason": reason, "rows": counts,
                               "videos": BACKUP_VIDEOS}, indent=1).encode()
        with tarfile.open(part, "w:gz") as tar:
            tar.add(snap, arcname=DB_PATH.name)
            if VAPID_FILE.exists():
                tar.add(VAPID_FILE, arcname=VAPID_FILE.name)
            info = tarfile.TarInfo("manifest.json")
            info.size, info.mtime = len(manifest), time.time()
            import io
            tar.addfile(info, io.BytesIO(manifest))
            for folder in BACKUP_FOLDERS + (("videos",) if BACKUP_VIDEOS else ()):
                d = DATA_DIR / folder
                if d.is_dir():
                    tar.add(d, arcname=folder)
        part.rename(BACKUP_DIR / name)
        snap.unlink(missing_ok=True)
        for old in list_backups()[BACKUP_KEEP:]:
            (BACKUP_DIR / old["name"]).unlink(missing_ok=True)
        size = (BACKUP_DIR / name).stat().st_size
        _backup_status({"last_ok": now_ms(), "last_name": name, "last_error": None})
        print(f"[backup] {name} ({size // 1024} KB, {reason})", flush=True)
        if S3_ON:
            try:
                s3_put("clinora-backups/" + name, BACKUP_DIR / name)
                _backup_status({"upload_ok": now_ms(), "upload_name": name, "upload_error": None})
                print(f"[backup] uploaded {name} to cloud storage", flush=True)
            except Exception as e:
                _backup_status({"upload_error": f"{type(e).__name__}: {e}"[:300], "upload_error_ts": now_ms()})
                print(f"[backup] UPLOAD FAILED: {type(e).__name__}: {e}", flush=True)
        return {"name": name, "size": size}
    except InputError:
        raise
    except Exception as e:
        _backup_status({"last_error": f"{type(e).__name__}: {e}"[:300], "last_error_ts": now_ms()})
        print(f"[backup] FAILED: {type(e).__name__}: {e}", flush=True)
        raise
    finally:
        for f in BACKUP_DIR.glob("*.part"):
            f.unlink(missing_ok=True)
        BACKUP_LOCK.release()


def backup_loop():
    time.sleep(60)  # let the server start first
    while True:
        try:
            latest = list_backups()
            if not latest or time.time() * 1000 - latest[0]["ts"] >= BACKUP_EVERY_H * 3600_000:
                make_backup("auto")
        except Exception:
            pass  # already logged; tried again next round
        time.sleep(600)


def backup_info(conn, d, user):
    need_admin(user)
    return {"backups": list_backups(), "status": _backup_status(), "every_h": BACKUP_EVERY_H, "keep": BACKUP_KEEP,
            "offsite": S3_ON, "videos": BACKUP_VIDEOS, "folder": str(BACKUP_DIR)}


def backup_now(conn, d, user):
    need_admin(user)
    if too_many("backup", str(user["id"]), 6, 3600):
        raise AuthError("Too many backups this hour. Please wait a little.", 429)
    if BACKUP_LOCK.locked():
        raise InputError("A backup is already running. Try again in a minute.")
    threading.Thread(target=lambda: make_backup("manual by " + user["name"]), daemon=True).start()
    return {"started": True}


def restore_backup(path):
    """python server.py --restore data/backups/clinora-....tar.gz   (stop Clinora first)"""
    import socket
    import tarfile
    src = Path(path)
    if not src.is_file():
        sys.exit(f"File not found: {src}")
    try:
        with socket.create_connection(("127.0.0.1", PORT), timeout=1):
            sys.exit(f"Clinora is still running on port {PORT}. Stop it first (Ctrl+C in its window), then run this again.")
    except OSError:
        pass
    allowed = (DB_PATH.name, "manifest.json", "vapid_private.pem")
    with tarfile.open(src, "r:gz") as tar:
        members = tar.getmembers()
        for m in members:
            parts = Path(m.name).parts
            bad = m.name.startswith("/") or ".." in parts or not (m.isfile() or m.isdir())
            if bad or not (m.name in allowed or (parts and parts[0] in BACKUP_FOLDERS + ("videos",))):
                sys.exit(f"Refusing this file: it contains an unexpected item ({m.name}).")
        if DB_PATH.name not in [m.name for m in members]:
            sys.exit("This is not a Clinora backup (no database inside).")
        try:
            made = json.loads(tar.extractfile("manifest.json").read()).get("created")
            print("Backup made on:", datetime.datetime.fromtimestamp(made / 1000).strftime("%d %b %Y, %H:%M"))
        except Exception:
            pass
        keep = DATA_DIR / ("before-restore-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
        keep.mkdir(parents=True)
        for f in [DB_PATH, DB_PATH.with_name(DB_PATH.name + "-wal"), DB_PATH.with_name(DB_PATH.name + "-shm")] + \
                 [DATA_DIR / x for x in BACKUP_FOLDERS + (("videos",) if "videos" in {Path(m.name).parts[0] for m in members} else ())]:
            if f.exists():
                f.rename(keep / f.name)
        for m in members:
            if m.name != "manifest.json":
                try:
                    tar.extract(m, DATA_DIR, filter="data")  # newer Python: extra safety checks
                except TypeError:
                    tar.extract(m, DATA_DIR)
    print(f"Restored from {src.name}. Your previous data was moved to {keep} (delete it once all is well).")
    print("Now start Clinora again.")


# ---------------------------------------------------------------- launch check:  python server.py --check
def launch_check():
    """Prints what is ready for a live launch and what is still missing. Never prints secret values."""
    rows, bad = [], 0
    def line(level, what, tip=""):
        nonlocal bad
        bad += level == "❌"
        rows.append(f"{level} {what}" + (f"\n     → {tip}" if tip else ""))
    line("✅" if PRODUCTION else "❌", "APP_ENV=production" if PRODUCTION else "APP_ENV is not 'production'",
         "" if PRODUCTION else "Set APP_ENV=production on the live server (turns off demo payments and demo data).")
    line("✅" if PUBLIC_URL.startswith("https://") and "localhost" not in PUBLIC_URL else "❌", f"PUBLIC_URL = {PUBLIC_URL}",
         "" if PUBLIC_URL.startswith("https://") else "Your real address with https, e.g. https://clinora.in")
    line("✅" if ADMIN_SETUP_CODE else ("❌" if PRODUCTION else "⚠️"), "ADMIN_SETUP_CODE is set" if ADMIN_SETUP_CODE else "ADMIN_SETUP_CODE missing",
         "" if ADMIN_SETUP_CODE else "A secret code needed to create the first admin account, so nobody else can take the dashboard.")
    line("✅" if SUPPORT_EMAIL else "❌", "SUPPORT_EMAIL is set" if SUPPORT_EMAIL else "SUPPORT_EMAIL missing",
         "" if SUPPORT_EMAIL else "Shown on the Privacy, Terms and Delete-account pages (legally needed).")
    line("✅" if TRUST_PROXY else "⚠️", "TRUST_PROXY=1" if TRUST_PROXY else "TRUST_PROXY not set", "" if TRUST_PROXY else "Needed on Render, so rate limits see real visitor addresses.")
    line("✅" if client else "❌", "AI (Claude) key works" if client else "AI is off: " + AI_REASON,
         "" if client else "Add ANTHROPIC_API_KEY and credits at https://console.anthropic.com")
    line("✅" if SMTP_HOST else "❌", "Email (SMTP) is set" if SMTP_HOST else "Email is off", "" if SMTP_HOST else "Forgot-password and reminder emails need it. See docs/email-setup.md")
    pays = [n for n, on in (("Razorpay", RAZORPAY_ON), ("Stripe", STRIPE_ON), ("PayPal", PAYPAL_ON)) if on]
    line("✅" if pays else "⚠️", "Payments: " + (", ".join(pays) if pays else "none (patients pay at the clinic)"))
    if STRIPE_ON and STRIPE_KEY.startswith("sk_test_"):
        line("⚠️", "Stripe is in TEST mode (sk_test_ key)", "Use the live key (sk_live_) when you are ready for real money.")
    if RAZORPAY_ON and RAZORPAY_KEY_ID.startswith("rzp_test_"):
        line("⚠️", "Razorpay is in TEST mode (rzp_test_ key)", "Use the live key when you are ready for real money.")
    if PAYPAL_ON and "sandbox" in PAYPAL_API:
        line("⚠️", "PayPal is in sandbox mode", "Set PAYPAL_ENV=live for real money.")
    for name, on, sec in (("Stripe", STRIPE_ON, STRIPE_WEBHOOK_SECRET), ("Razorpay", RAZORPAY_ON, RAZORPAY_WEBHOOK_SECRET), ("PayPal", PAYPAL_ON, PAYPAL_WEBHOOK_ID)):
        if on and not sec:
            line("❌", f"{name} webhook secret missing", "Without it, payments can't be confirmed safely.")
    social = [n for n, on in (("Google", GOOGLE_CLIENT_ID), ("Facebook", FACEBOOK_APP_ID), ("X", X_CLIENT_ID)) if on]
    line("✅" if social else "⚠️", "Social login: " + (", ".join(social) if social else "off (email login works)"), "" if social else "Optional. See docs/social-login.md")
    line("✅" if S3_ON else "⚠️", "Cloud copy of backups is on" if S3_ON else "Backups stay on the server disk only", "" if S3_ON else "Strongly recommended. See docs/backups.md")
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        free = __import__("shutil").disk_usage(DATA_DIR).free
        line("✅" if free > 300_000_000 else "⚠️", f"Data folder {DATA_DIR} is writable, {free // 1_000_000} MB free",
             "" if free > 300_000_000 else "Low space: give the disk more GB (videos and backups need room).")
    except Exception as e:
        line("❌", f"Data folder {DATA_DIR} is not writable: {e}")
    print("\nClinora launch check\n" + "\n".join(rows))
    print("\n" + ("✅ Ready to go live." if not bad else f"❌ {bad} thing(s) to fix before going live.") + "  (⚠️ = recommended, not required)\n")
    return bad


# ---------------------------------------------------------------- booking real doctors
# A doctor turns on online booking and sets days, hours, an optional break, slot length, visit types and fee.
# Patients pick a free slot (shown in the doctor's time zone). Both get bell alerts; the patient gets reminders.
BOOK_CURRENCIES = {"INR", "USD", "EUR", "GBP", "AED", "SAR", "PKR", "BDT", "NPR", "LKR", "NGN", "KES", "CAD", "AUD", "SGD", "MYR", "IDR", "PHP"}
BOOK_DAYS_AHEAD = 21
BOOK_STATUSES = {"booked", "done", "no_show", "cancelled"}


def booking_cfg(lst):
    try:
        c = json.loads(lst["booking"] or "{}") if lst else {}
    except (ValueError, TypeError):
        c = {}
    return c if c.get("on") else None


def _mins(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def m_booking_settings(conn, d, me):
    need_member(me, "doctor")
    need_confirmed(me)
    lst = my_listing(conn, me)
    if not lst:
        raise InputError("Save your public profile first")
    if not d.get("on"):
        old = json.loads(lst["booking"] or "{}") if lst["booking"] else {}
        old["on"] = 0
        conn.execute("UPDATE listings SET booking=? WHERE id=?", (json.dumps(old), lst["id"]))
        return {"on": False}
    days = int(d.get("days") or 0)
    start, end = str(d.get("start") or ""), str(d.get("end") or "")
    if not 1 <= days <= 127:
        raise InputError("Pick at least one day")
    if not HHMM_RE.match(start) or not HHMM_RE.match(end) or _mins(end) - _mins(start) < 15:
        raise InputError("Check your start and end time")
    brk = d.get("brk") or None
    if brk:
        if not (isinstance(brk, list) and len(brk) == 2 and all(HHMM_RE.match(str(x)) for x in brk) and _mins(brk[0]) < _mins(brk[1])):
            raise InputError("Check your break time")
        brk = [str(brk[0]), str(brk[1])]
    slot = int(d.get("slot") or 0)
    if slot not in (10, 15, 20, 30, 45, 60):
        raise InputError("Pick a visit length")
    modes = [m for m in ("clinic", "video") if m in (d.get("modes") or [])]
    if not modes:
        raise InputError("Pick in-clinic, video, or both")
    try:
        fee = int(d.get("fee") or 0)
    except (TypeError, ValueError):
        fee = -1
    if not 0 <= fee <= 1_000_000:
        raise InputError("Check the fee")
    cur = str(d.get("cur") or "INR").upper()
    if cur not in BOOK_CURRENCIES:
        raise InputError("Pick a currency")
    tz = str(d.get("tz") or lst["tz"] or "UTC")[:64]
    if not TZ_RE.match(tz) or _zone(tz) is datetime.timezone.utc:
        tz = "UTC"
    prepay = bool(d.get("prepay")) and fee > 0
    if prepay and not doctor_pay_ready(lst, cur):
        raise InputError("Online payment needs INR fees and a payout account. Ask the Clinora admin to connect your bank account first.")
    cfg = {"on": 1, "days": days, "start": start, "end": end, "brk": brk, "slot": slot, "modes": modes, "fee": fee, "cur": cur, "tz": tz,
           "note": text(d, "note", 200, False), "prepay": prepay}
    conn.execute("UPDATE listings SET booking=? WHERE id=?", (json.dumps(cfg), lst["id"]))
    return {"on": True}


def free_slots(conn, lst, cfg, days=BOOK_DAYS_AHEAD):
    zone = _zone(cfg["tz"])
    now = datetime.datetime.now(zone)
    soonest = now + datetime.timedelta(minutes=60)  # at least 1 hour notice
    taken = {(r["date"], r["time"]) for r in conn.execute(
        "SELECT date, time FROM dbookings WHERE listing_id=? AND status='booked' AND date>=?", (lst["id"], now.date().isoformat()))}
    out = []
    s, e, step = _mins(cfg["start"]), _mins(cfg["end"]), cfg["slot"]
    b = (_mins(cfg["brk"][0]), _mins(cfg["brk"][1])) if cfg.get("brk") else None
    for i in range(days):
        day = now.date() + datetime.timedelta(days=i)
        if not cfg["days"] & (1 << day.weekday()):
            continue
        times = []
        t = s
        while t + step <= e:
            if not (b and t < b[1] and t + step > b[0]):
                hm = f"{t // 60:02d}:{t % 60:02d}"
                at = datetime.datetime(day.year, day.month, day.day, t // 60, t % 60, tzinfo=zone)
                if at >= soonest and (day.isoformat(), hm) not in taken:
                    times.append(hm)
            t += step
        if times:
            out.append({"date": day.isoformat(), "times": times})
    return out


def m_slots(conn, d, me):
    lst = conn.execute("SELECT * FROM listings WHERE id=? AND hidden=0", (int(d.get("listing_id") or 0),)).fetchone()
    cfg = booking_cfg(lst)
    if not cfg:
        raise InputError("This doctor doesn't take online bookings yet. Send a message instead.")
    pub = dict({k: cfg[k] for k in ("slot", "modes", "fee", "cur", "tz", "note")}, prepay=bool(cfg.get("prepay")))
    return {"listing_id": lst["id"], "name": lst["name"], "cfg": pub, "days": free_slots(conn, lst, cfg)}


def _booking_view(r, side):
    return {"id": r["id"], "listing_id": r["listing_id"], "doctor": r["doctor_name"], "doctor_id": r["doctor_id"], "patient": r["for_name"],
            "patient_id": r["patient_id"], "account": r["patient_name"], "date": r["date"], "time": r["time"], "tz": r["tz"], "mode": r["mode"],
            "reason": r["reason"], "status": r["status"], "fee": r["fee"], "cur": r["cur"], "at": r["at"], "side": side,
            "cancel_reason": r["cancel_reason"], "addr": r["addr"], "rx_id": r["rx_id"], "slot": r["slot"], "pay_status": r["pay_status"],
            "hold_until": r["hold_until"]}


def my_bookings(conn, me):
    q = ("SELECT b.*, l.name AS doctor_name, l.addr || ', ' || l.city AS addr, l.owner AS doctor_id, m.name AS patient_name, "
         "(SELECT id FROM prescriptions p WHERE p.booking_id=b.id) AS rx_id, CAST(json_extract(l.booking, '$.slot') AS INTEGER) AS slot FROM dbookings b "
         "JOIN listings l ON l.id=b.listing_id JOIN members m ON m.id=b.patient_id WHERE {} AND b.at > ? ORDER BY b.at LIMIT 60")
    since = now_ms() - 7 * 86_400_000
    mine = [_booking_view(r, "patient") for r in conn.execute(q.format("b.patient_id=?"), (me["id"], since))]
    lst = my_listing(conn, me) if me["kind"] == "doctor" else None
    theirs = [_booking_view(r, "doctor") for r in conn.execute(q.format("b.listing_id=?"), (lst["id"], since))] if lst else []
    return {"as_patient": mine, "as_doctor": theirs}


def m_book(conn, d, me):
    need_member(me)
    need_confirmed(me)
    if too_many("book", str(me["id"]), 10, 86400):
        raise AuthError("You made many bookings today. Please try again tomorrow.", 429)
    lst = conn.execute("SELECT * FROM listings WHERE id=? AND hidden=0", (int(d.get("listing_id") or 0),)).fetchone()
    cfg = booking_cfg(lst)
    if not cfg:
        raise InputError("This doctor doesn't take online bookings right now.")
    if lst["owner"] == me["id"]:
        raise InputError("You can't book yourself")
    if conn.execute("SELECT 1 FROM blocks WHERE member_id=? AND blocked_id=?", (lst["owner"], me["id"])).fetchone():
        raise AuthError("You can't book this doctor.")
    date, tm = str(d.get("date") or ""), str(d.get("time") or "")
    mode = str(d.get("mode") or "")
    if mode not in cfg["modes"]:
        raise InputError("Pick in-clinic or video")
    if not any(x["date"] == date and tm in x["times"] for x in free_slots(conn, lst, cfg)):
        raise InputError("That time was just taken or is no longer free. Please pick another time.")
    upcoming = conn.execute("SELECT COUNT(*) FROM dbookings WHERE listing_id=? AND patient_id=? AND status='booked' AND at>?",
                            (lst["id"], me["id"], now_ms())).fetchone()[0]
    if upcoming >= 3:
        raise InputError("You already have 3 upcoming visits with this doctor. Cancel one first.")
    for_name = text(d, "for_name", 80, False) or me["name"]
    if for_name != me["name"] and not conn.execute("SELECT 1 FROM family WHERE member_id=? AND name=?", (me["id"], for_name)).fetchone():
        raise InputError("Add this person under Family on your Account page first")
    reason = text(d, "reason", 300, False)
    zone = _zone(cfg["tz"])
    day = datetime.date.fromisoformat(date)
    at = int(datetime.datetime(day.year, day.month, day.day, *map(int, tm.split(":")), tzinfo=zone).timestamp() * 1000)
    prepay = bool(cfg.get("prepay")) and cfg["fee"] > 0 and doctor_pay_ready(lst, cfg["cur"])
    try:
        bid = conn.execute("INSERT INTO dbookings(listing_id,patient_id,for_name,date,time,tz,at,mode,reason,status,fee,cur,ts,pay_status,hold_until) "
                           "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (lst["id"], me["id"], for_name, date, tm, cfg["tz"], at, mode, reason,
                                                                    "booked", cfg["fee"], cfg["cur"], now_ms(),
                                                                    "pending" if prepay else "none", now_ms() + HOLD_MIN * 60_000 if prepay else None)).lastrowid
    except sqlite3.IntegrityError:
        raise InputError("That time was just taken. Please pick another time.")
    nice = f"{day.strftime('%a %d %b')} at {tm}"
    if prepay:
        return {"id": bid, "when": nice, "pay": True, "hold_min": HOLD_MIN}
    booking_confirmed(conn, bid)
    return {"id": bid, "when": nice}


def booking_confirmed(conn, bid):
    """Tell the doctor and set the patient's reminders (right away, or once an online payment arrives)."""
    b = conn.execute("SELECT * FROM dbookings WHERE id=?", (bid,)).fetchone()
    lst = conn.execute("SELECT * FROM listings WHERE id=?", (b["listing_id"],)).fetchone()
    me = conn.execute("SELECT id, name FROM members WHERE id=?", (b["patient_id"],)).fetchone()
    date, tm, mode, reason, for_name = b["date"], b["time"], b["mode"], b["reason"] or "", b["for_name"]
    day = datetime.date.fromisoformat(date)
    nice = f"{day.strftime('%a %d %b')} at {tm}"
    cfg = {"tz": b["tz"]}
    who = for_name if for_name == me["name"] else f"{for_name} (booked by {me['name']})"
    notify(conn, lst["owner"], "booking", f"📅 New booking: {who}", f"{nice} · {'Video' if mode == 'video' else 'In clinic'}"
           + (" · 💳 paid online" if b["pay_status"] == "paid" else "") + (f" · {reason[:80]}" if reason else ""), "account")
    for lead in (1440, 60):
        r = {"at": tm, "days": 0, "date": date, "tz": cfg["tz"], "lead": lead}
        nxt = reminder_next(r, now_ms())
        if nxt:
            conn.execute("INSERT INTO reminders(kind,title,note,at,days,date,tz,lead,email,next_at,member_id,created,ref) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         ("appointment", f"{lst['name']}" + (f" · {for_name}" if for_name != me["name"] else ""),
                          ("Video visit: open Clinora and message or call the doctor." if mode == "video" else f"In clinic: {lst['addr']}, {lst['city']}")[:200],
                          tm, 0, date, cfg["tz"], lead, 1, nxt, me["id"], now_ms(), f"dbook:{bid}"))


def m_booking_cancel(conn, d, me):
    need_member(me)
    r = conn.execute("SELECT b.*, l.owner, l.name AS lname FROM dbookings b JOIN listings l ON l.id=b.listing_id WHERE b.id=?",
                     (int(d.get("id") or 0),)).fetchone()
    if not r or me["id"] not in (r["patient_id"], r["owner"]):
        raise InputError("Booking not found")
    if r["status"] != "booked":
        raise InputError("This visit is not active any more")
    if r["at"] < now_ms():
        raise InputError("This visit has already started or passed")
    reason = text(d, "reason", 200, False)
    by_doctor = me["id"] == r["owner"]
    conn.execute("UPDATE dbookings SET status='cancelled', cancel_by=?, cancel_reason=? WHERE id=?", ("doctor" if by_doctor else "patient", reason, r["id"]))
    refund_note = ""
    if r["pay_status"] == "paid":
        if by_doctor or r["at"] - now_ms() >= REFUND_HOURS * 3600_000:
            refund_note = " · " + refund_booking(conn, r)
        else:
            refund_note = f" · no refund (cancelled less than {REFUND_HOURS} h before)"
    elif r["pay_status"] == "pending":
        conn.execute("UPDATE dbookings SET pay_status='none' WHERE id=?", (r["id"],))
    conn.execute("DELETE FROM reminders WHERE ref=?", (f"dbook:{r['id']}",))
    when = f"{datetime.date.fromisoformat(r['date']).strftime('%a %d %b')} at {r['time']}"
    if by_doctor:
        notify(conn, r["patient_id"], "booking", f"❌ {r['lname']} cancelled your visit", f"{when}" + (f" · {reason}" if reason else " · Please book another time.") + refund_note, "account")
    else:
        notify(conn, r["owner"], "booking", f"❌ {r['for_name']} cancelled", when + (f" · {reason}" if reason else "") + refund_note, "account")
    return {"refund": refund_note.strip(" ·")}


def m_booking_mark(conn, d, me):
    need_member(me, "doctor")
    lst = my_listing(conn, me)
    st = str(d.get("status") or "")
    if st not in ("done", "no_show", "booked"):
        raise InputError("Unknown status")
    r = conn.execute("SELECT * FROM dbookings WHERE id=? AND listing_id=?", (int(d.get("id") or 0), lst["id"] if lst else -1)).fetchone()
    if not r or r["status"] == "cancelled":
        raise InputError("Booking not found")
    conn.execute("UPDATE dbookings SET status=? WHERE id=?", (st, r["id"]))
    if st == "done" and r["status"] != "done":
        ask_review(conn, r, lst)


def has_booking(conn, a, b):
    """True when one of the two people booked a visit with the other (lets the doctor message or call that patient)."""
    return bool(conn.execute("SELECT 1 FROM dbookings x JOIN listings l ON l.id=x.listing_id WHERE x.status!='cancelled' AND "
                             "((x.patient_id=? AND l.owner=?) OR (x.patient_id=? AND l.owner=?)) LIMIT 1", (a, b, b, a)).fetchone())


# ---------------------------------------------------------------- phone / computer notifications (Web Push)
# Bell alerts (messages, bookings, reminders...) also pop up on the person's phone or computer, even when
# Clinora is closed. The browser's push service delivers them; our VAPID key proves they come from us.
try:
    from pywebpush import webpush, WebPushException
except ImportError:
    webpush = None
VAPID_FILE = DATA_DIR / "vapid_private.pem"
PUSH_SKIP = {"welcome"}


def vapid_public_key():
    """Creates the key pair once (kept in the data folder) and returns the public part browsers need."""
    if not webpush:
        return None
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import base64
    if not VAPID_FILE.exists():
        VAPID_FILE.parent.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        VAPID_FILE.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        os.chmod(VAPID_FILE, 0o600)
    key = serialization.load_pem_private_key(VAPID_FILE.read_bytes(), None)
    raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


PUSH_KEY = None


def m_push_subscribe(conn, d, me):
    need_member(me)
    endpoint = str(d.get("endpoint") or "")
    keys = d.get("keys") or {}
    if not endpoint.startswith("https://") or len(endpoint) > 800 or not isinstance(keys, dict):
        raise InputError("This browser's notification details look wrong")
    p256, auth = str(keys.get("p256dh") or ""), str(keys.get("auth") or "")
    if not (20 < len(p256) < 200 and 8 < len(auth) < 60):
        raise InputError("This browser's notification details look wrong")
    if conn.execute("SELECT COUNT(*) FROM push_subs WHERE member_id=?", (me["id"],)).fetchone()[0] >= 10:
        conn.execute("DELETE FROM push_subs WHERE endpoint IN (SELECT endpoint FROM push_subs WHERE member_id=? ORDER BY ts LIMIT 1)", (me["id"],))
    conn.execute("INSERT OR REPLACE INTO push_subs VALUES(?,?,?,?,?)", (endpoint, me["id"], p256, auth, now_ms()))
    return {"on": True}


def m_push_unsubscribe(conn, d, me):
    need_member(me)
    conn.execute("DELETE FROM push_subs WHERE member_id=? AND endpoint=?", (me["id"], str(d.get("endpoint") or "")))
    return {"on": False}


def push_to(conn, member_id, title, body, link):
    if not webpush or not VAPID_FILE.exists():
        return
    subs = [dict(r) for r in conn.execute("SELECT endpoint, p256dh, auth FROM push_subs WHERE member_id=?", (member_id,))]
    if not subs:
        return
    payload = json.dumps({"title": title, "body": body, "link": link or "account"})
    claims = {"sub": "mailto:" + (SUPPORT_EMAIL or "support@clinora.invalid")}

    def run():
        gone = []
        for s in subs:
            try:
                webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, payload,
                        vapid_private_key=str(VAPID_FILE), vapid_claims=dict(claims), ttl=86400, timeout=10)
            except WebPushException as e:
                if e.response is not None and e.response.status_code in (404, 410):
                    gone.append(s["endpoint"])  # the person turned notifications off or reinstalled the browser
                else:
                    print(f"[push] failed: {e}", flush=True)
            except Exception as e:
                print(f"[push] failed: {type(e).__name__}: {e}", flush=True)
        if gone:
            with DB_LOCK, connect() as c2:
                c2.executemany("DELETE FROM push_subs WHERE endpoint=?", [(g,) for g in gone])
    threading.Thread(target=run, daemon=True).start()


# ---------------------------------------------------------------- public doctor pages:  /doctor/12-dr-sharma-srinagar
# A real web page for every doctor: easy to share on WhatsApp/Instagram and found by Google.
def slugify(s):
    return re.sub(r"[^a-z0-9]+", "-", str(s or "").lower()).strip("-")[:60] or "doctor"


def doctor_slug(lst):
    return f"{lst['id']}-{slugify(lst['name'] + ' ' + (lst['city'] or ''))}"


def doctor_page(conn, lid):
    lst = conn.execute("SELECT l.*, m.photo_ts FROM listings l LEFT JOIN members m ON m.id=l.owner WHERE l.id=? AND l.hidden=0", (lid,)).fetchone()
    if not lst:
        return None, None
    e = html.escape
    rv = listing_reviews(conn, lid)
    verified = conn.execute("SELECT 1 FROM verifications WHERE listing_id=? AND status='verified'", (lid,)).fetchone()
    cfg = booking_cfg(lst)
    url = f"{PUBLIC_URL}/doctor/{doctor_slug(lst)}"
    kind = {"doctors": "Doctor", "clinic": "Clinic", "hospital": "Hospital", "dentist": "Dentist"}.get(lst["type"], "Doctor")
    where = ", ".join(x for x in (lst["city"], lst["country"]) if x)
    desc = f"{lst['name']}" + (f", {lst['spec']}" if lst["spec"] else "") + f" in {where}." + \
           (f" Rated {rv['avg']}★ by {rv['count']} patients." if rv["count"] else "") + (" Book a visit online on Clinora." if cfg else " Message on Clinora.")
    try:
        social = json.loads(lst["social"] or "{}")
    except ValueError:
        social = {}
    ld = {"@context": "https://schema.org", "@type": "Dentist" if lst["type"] == "dentist" else "Hospital" if lst["type"] == "hospital"
          else "MedicalClinic" if lst["type"] == "clinic" else "Physician", "name": lst["name"], "url": url,
          "address": {"@type": "PostalAddress", "streetAddress": lst["addr"], "addressLocality": lst["city"], "addressCountry": lst["cc"] or lst["country"]},
          "geo": {"@type": "GeoCoordinates", "latitude": lst["lat"], "longitude": lst["lon"]}, "telephone": lst["phone"]}
    if lst["spec"]:
        ld["medicalSpecialty"] = lst["spec"]
    if rv["count"]:
        ld["aggregateRating"] = {"@type": "AggregateRating", "ratingValue": rv["avg"], "reviewCount": rv["count"]}
    photo = f"/api/m/avatar/{lst['owner']}?v={lst['photo_ts']}" if lst["owner"] and lst["photo_ts"] else ""
    stars = lambda n: "★" * n + "☆" * (5 - n)
    revs = "".join(f"<div class='rv'><b>{e(r['name'])}</b> <span class='st'>{stars(r['stars'])}</span><p>{e(r['body'])}</p>"
                   + (f"<div class='rp'><b>Reply from the doctor:</b> {e(r['reply'])}</div>" if r["reply"] else "") + "</div>"
                   for r in rv["reviews"][:6])
    links = "".join(f"<a href='{e(v if str(v).startswith('http') else '#')}' rel='noopener nofollow' target='_blank'>{e(k.title())}</a>"
                    for k, v in social.items() if v and str(v).startswith("https://"))
    book = (f"<p class='fee'>📅 Online booking · {e(str(cfg['fee']) + ' ' + cfg['cur']) if cfg['fee'] else 'Free'} · "
            f"{' & '.join('🏥 In clinic' if m == 'clinic' else '📹 Video' for m in cfg['modes'])}</p>"
            f"<a class='btn' href='/#book/{lid}'>📅 Book a visit</a>") if cfg else ""
    ld_json = json.dumps(ld).replace("</", "<\\/")
    tel = re.sub(r"[^0-9+]", "", lst["phone"])
    title_spec = " · " + e(lst["spec"]) if lst["spec"] else ""
    av_html = f'<img src="{e(photo)}" alt="">' if photo else e((lst["name"] or "?")[:1])
    badge = '<span class="ok">✓ Verified</span>' if verified else ""
    plural = "s" if rv["count"] != 1 else ""
    rating_html = f"<div><span class='st'>{stars(round(rv['avg']))}</span> {rv['avg']} ({rv['count']} review{plural})</div>" if rv["count"] else ""
    hours_html = f"<p>🕘 Online hours: {e(lst['hours'])}</p>" if lst["hours"] else ""
    video_html = " · 📹 Video visits" if lst["video"] else ""
    links_html = f"<p class='links'>{links}</p>" if links else ""
    revs_html = revs or "<p class='mu'>No reviews yet.</p>"
    more_html = f"<p><a href='/#doctor/{lid}'>See all {rv['count']} reviews on Clinora →</a></p>" if rv["count"] > 6 else ""
    og_image = e(PUBLIC_URL + (photo or "/assets/icons/icon-512.png"))
    page = f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(lst['name'])}{title_spec} in {e(lst['city'] or '')} · Clinora</title>
<meta name="description" content="{e(desc)}"><link rel="canonical" href="{e(url)}"><link rel="icon" href="/assets/icons/favicon-48.png">
<meta property="og:type" content="profile"><meta property="og:title" content="{e(lst['name'])} · Clinora"><meta property="og:description" content="{e(desc)}">
<meta property="og:url" content="{e(url)}"><meta property="og:image" content="{og_image}"><meta name="twitter:card" content="summary">
<script type="application/ld+json">{ld_json}</script>
<style>body{{margin:0;background:#06080b;color:#e9eff3;font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Arial,sans-serif}}
main{{max-width:720px;margin:0 auto;padding:24px 18px 70px}}a{{color:#5cc8ff}}.top{{display:flex;align-items:center;gap:10px;font-weight:800;font-size:20px;color:#e9eff3;text-decoration:none}}
.top img{{width:32px;height:32px;border-radius:9px}}.card{{background:#0c1015;border:1px solid #1c242e;border-radius:16px;padding:20px;margin-top:18px}}
.hd{{display:flex;gap:16px;align-items:center}}.av{{width:84px;height:84px;border-radius:50%;background:#14b8a6;display:flex;align-items:center;justify-content:center;font-size:30px;font-weight:800;overflow:hidden;flex:0 0 84px}}
.av img{{width:100%;height:100%;object-fit:cover}}h1{{font-size:26px;margin:0}}.mu{{color:#8693a0}}.ok{{background:linear-gradient(90deg,#0ea5e9,#2563eb);color:#fff;border-radius:99px;padding:2px 10px;font-size:12px;font-weight:700;vertical-align:middle}}
.btn{{display:inline-block;background:#14b8a6;color:#fff;text-decoration:none;font-weight:700;padding:11px 20px;border-radius:12px;margin:6px 8px 0 0}}.btn.g{{background:none;border:1px solid #2a3440;color:#e9eff3}}
.st{{color:#fbbf24}}.rv{{border-top:1px solid #1c242e;padding:12px 0}}.rv p{{margin:4px 0}}.rp{{background:#111821;border-radius:10px;padding:8px 10px;font-size:14px}}
.links a{{margin-right:12px}}.fee{{margin:10px 0 0}}</style></head><body><main>
<a class="top" href="/"><img src="/assets/icons/icon-192.png" alt="">Clinora</a>
<div class="card"><div class="hd"><div class="av">{av_html}</div>
<div><h1>{e(lst['name'])} {badge}</h1>
<div class="mu">{e(kind)}{title_spec} · {e(where)}</div>
{rating_html}</div></div>
<p>📍 {e(lst['addr'])}, {e(where)} · <a href="https://www.google.com/maps/dir/?api=1&amp;destination={lst['lat']},{lst['lon']}" target="_blank" rel="noopener">Directions</a></p>
<p>📞 <a href="tel:{e(tel)}">{e(lst['phone'])}</a>{video_html}</p>
{hours_html}
{book}<a class="btn g" href="/#doctor/{lid}">💬 Message / reviews</a>
{links_html}</div>
<div class="card"><h2 style="margin-top:0">Patient reviews</h2>{revs_html}
{more_html}</div>
<p class="mu" style="font-size:13px;margin-top:22px">Clinora is not a medical service and does not check every detail on this page. In an emergency, call your local emergency number.
<a href="/privacy">Privacy</a> · <a href="/terms">Terms</a></p></main></body></html>"""
    return page, doctor_slug(lst)


# ---------------------------------------------------------------- family members (book and set reminders for parents, children...)
FAMILY_RELATIONS = {"mother", "father", "child", "spouse", "sibling", "grandparent", "other"}


def m_family_save(conn, d, me):
    need_member(me)
    fid = int(d.get("id") or 0)
    name = text(d, "name", 60)
    if len(name) < 2:
        raise InputError("Please write their name")
    rel = one_of(d, "relation", FAMILY_RELATIONS)
    year = d.get("year")
    year = int(year) if str(year or "").isdigit() else None
    if year and not 1900 <= year <= datetime.date.today().year:
        raise InputError("Check the birth year")
    if fid:
        if not conn.execute("SELECT 1 FROM family WHERE id=? AND member_id=?", (fid, me["id"])).fetchone():
            raise InputError("Not found")
        conn.execute("UPDATE family SET name=?, relation=?, year=? WHERE id=?", (name, rel, year, fid))
    else:
        if conn.execute("SELECT COUNT(*) FROM family WHERE member_id=?", (me["id"],)).fetchone()[0] >= 10:
            raise InputError("You can add up to 10 family members")
        conn.execute("INSERT INTO family(member_id,name,relation,year,ts) VALUES(?,?,?,?,?)", (me["id"], name, rel, year, now_ms()))


def m_family_delete(conn, d, me):
    need_member(me)
    conn.execute("DELETE FROM family WHERE id=? AND member_id=?", (int(d.get("id") or 0), me["id"]))


# ---------------------------------------------------------------- admin statistics (Clinic Dashboard)
def stats_overview(conn, d, user):
    need_admin(user)
    now = now_ms()
    week = 7 * 86_400_000
    one = lambda q, *a: conn.execute(q, a).fetchone()[0] or 0
    totals = {
        "patients": one("SELECT COUNT(*) FROM members WHERE kind='patient'"),
        "doctors": one("SELECT COUNT(*) FROM members WHERE kind='doctor'"),
        "profiles": one("SELECT COUNT(*) FROM listings WHERE owner IS NOT NULL AND hidden=0"),
        "verified": one("SELECT COUNT(*) FROM verifications WHERE status='verified'"),
        "bookable": sum(1 for r in conn.execute("SELECT booking FROM listings WHERE hidden=0 AND booking IS NOT NULL") if booking_cfg(r)),
        "active_7d": one("SELECT COUNT(*) FROM members WHERE last_seen > ?", now - week),
        "confirmed": one("SELECT COUNT(*) FROM members WHERE email_ok=1"),
        "visits_upcoming": one("SELECT COUNT(*) FROM dbookings WHERE status='booked' AND at > ?", now),
        "visits_done": one("SELECT COUNT(*) FROM dbookings WHERE status='done'"),
        "visits_cancelled": one("SELECT COUNT(*) FROM dbookings WHERE status='cancelled'"),
        "visits_no_show": one("SELECT COUNT(*) FROM dbookings WHERE status='no_show'"),
        "messages": one("SELECT COUNT(*) FROM messages"),
        "reviews": one("SELECT COUNT(*) FROM reviews"),
        "avg_rating": conn.execute("SELECT ROUND(AVG(stars), 2) FROM reviews").fetchone()[0],
        "reminders_on": one("SELECT COUNT(*) FROM reminders WHERE active=1"),
        "push_devices": one("SELECT COUNT(*) FROM push_subs"),
        "reports_open": one("SELECT COUNT(DISTINCT target_type || target_id) FROM reports WHERE status='open'"),
        "clinic_bookings": one("SELECT COUNT(*) FROM appointments"),
    }
    # last 8 weeks, oldest first
    start = now - 8 * week
    def weekly(q):
        b = [0] * 8
        for (ts,) in conn.execute(q, (start,)):
            i = int((ts - start) // week)
            if 0 <= i < 8:
                b[i] += 1
        return b
    series = {
        "signups": weekly("SELECT created FROM members WHERE created > ?"),
        "visits": weekly("SELECT ts FROM dbookings WHERE ts > ?"),
        "messages": weekly("SELECT ts FROM messages WHERE ts > ?"),
        "reviews": weekly("SELECT ts FROM reviews WHERE ts > ?"),
    }
    top = [dict(r) for r in conn.execute(
        "SELECT l.name, l.city, COUNT(b.id) AS visits FROM listings l JOIN dbookings b ON b.listing_id=l.id AND b.status!='cancelled' "
        "GROUP BY l.id ORDER BY visits DESC LIMIT 5")]
    cities = [dict(r) for r in conn.execute(
        "SELECT city, COUNT(*) AS n FROM members WHERE city IS NOT NULL AND city!='' GROUP BY LOWER(city) ORDER BY n DESC LIMIT 5")]
    return {"totals": totals, "series": series, "week_start": start, "top_doctors": top, "cities": cities}


# ---------------------------------------------------------------- after the visit: prescription and review request
RX_FOODS = {"before", "after", "with", "any"}


def m_rx_write(conn, d, me):
    """The doctor writes the prescription for a visit (in-clinic or video). The patient can print it and turn it into reminders."""
    need_member(me, "doctor")
    need_confirmed(me)
    lst = my_listing(conn, me)
    b = conn.execute("SELECT * FROM dbookings WHERE id=? AND listing_id=?", (int(d.get("booking_id") or 0), lst["id"] if lst else -1)).fetchone()
    if not b or b["status"] == "cancelled":
        raise InputError("Visit not found")
    meds = []
    for m in (d.get("meds") or [])[:15]:
        if not isinstance(m, dict):
            continue
        name = str(m.get("name") or "").strip()[:80]
        if not name:
            continue
        times = [x for x in (m.get("times") or []) if HHMM_RE.match(str(x))][:6]
        meds.append({"name": name, "strength": str(m.get("strength") or "")[:40], "dose": str(m.get("dose") or "")[:60], "times": times,
                     "days": max(0, min(int(m.get("days") or 0), 365)), "food": m.get("food") if m.get("food") in RX_FOODS else "any",
                     "note": str(m.get("note") or "")[:120]})
    data = {"diagnosis": text(d, "diagnosis", 300, False), "advice": text(d, "advice", 800, False), "meds": meds,
            "followup": str(d.get("followup") or "")[:10] if DATE_RE.match(str(d.get("followup") or "")) else "", "tests": text(d, "tests", 300, False)}
    if not (meds or data["advice"] or data["diagnosis"]):
        raise InputError("Write at least one medicine or some advice")
    conn.execute("INSERT INTO prescriptions(booking_id,doctor_id,patient_id,data,ts) VALUES(?,?,?,?,?) "
                 "ON CONFLICT(booking_id) DO UPDATE SET data=excluded.data, ts=excluded.ts", (b["id"], me["id"], b["patient_id"], json.dumps(data), now_ms()))
    rx_id = conn.execute("SELECT id FROM prescriptions WHERE booking_id=?", (b["id"],)).fetchone()[0]
    if b["status"] == "booked" and b["at"] < now_ms():
        conn.execute("UPDATE dbookings SET status='done' WHERE id=?", (b["id"],))
        ask_review(conn, b, lst)
    notify(conn, b["patient_id"], "booking", f"💊 Prescription from {lst['name']}", "Open it to print, or add the medicines to your reminders.", "account")
    return {"rx_id": rx_id}


def ask_review(conn, b, lst):
    if not conn.execute("SELECT 1 FROM reviews WHERE listing_id=? AND member_id=?", (lst["id"], b["patient_id"])).fetchone():
        notify(conn, b["patient_id"], "review", f"⭐ How was your visit with {lst['name']}?", "A short review helps other patients choose.", f"reviews:{lst['id']}")


def prescription_for(conn, rx_id, me):
    if not me:
        return None
    r = conn.execute("SELECT p.*, b.for_name, b.date, b.time, b.mode, l.name AS doctor, l.addr, l.city, l.phone, l.spec, m.name AS patient_account "
                     "FROM prescriptions p JOIN dbookings b ON b.id=p.booking_id JOIN listings l ON l.id=b.listing_id JOIN members m ON m.id=p.patient_id "
                     "WHERE p.id=?", (rx_id,)).fetchone()
    if not r or me["id"] not in (r["doctor_id"], r["patient_id"]):
        return None
    out = dict(r)
    out["data"] = json.loads(r["data"])
    v = conn.execute("SELECT reg_no, council, qualification FROM verifications WHERE member_id=? AND status='verified'", (r["doctor_id"],)).fetchone()
    out["reg"] = dict(v) if v else None
    return out


def m_rx_get(conn, d, me):
    need_member(me)
    rx = prescription_for(conn, int(d.get("id") or 0), me)
    if not rx:
        raise InputError("Prescription not found")
    return {"id": rx["id"], "booking_id": rx["booking_id"], "data": rx["data"], "for_name": rx["for_name"], "doctor": rx["doctor"]}


def prescription_page(rx):
    e = html.escape
    d = rx["data"]
    food = {"before": "before food", "after": "after food", "with": "with food", "any": ""}
    rows = "".join(f"<tr><td><b>{e(m['name'])}</b> {e(m['strength'])}</td><td>{e(m['dose'])}</td><td>{e(', '.join(m['times']) or 'as advised')}</td>"
                   f"<td>{str(m['days']) + ' days' if m['days'] else ''}</td><td>{e(food.get(m['food'], ''))} {e(m['note'])}</td></tr>" for m in d["meds"])
    reg = rx["reg"]
    reg_line = f"Reg. no. {e(reg['reg_no'])} · {e(reg['council'])} · {e(reg['qualification'])}" if reg else "Registration not verified on Clinora"
    meds_html = (f"<table><tr><th>Medicine</th><th>Dose</th><th>Times</th><th>For</th><th>Notes</th></tr>{rows}</table>" if rows else "")
    when = datetime.date.fromisoformat(rx["date"]).strftime("%d %b %Y")
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Prescription · {e(rx['for_name'])} · {when}</title><meta name="robots" content="noindex">
<style>body{{font:15px/1.55 -apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#0f172a;margin:0;background:#f1f5f9}}main{{max-width:760px;margin:20px auto;background:#fff;padding:28px 30px;border-radius:14px}}
h1{{margin:0;font-size:22px}}.mu{{color:#64748b;font-size:13px}}hr{{border:0;border-top:2px solid #0d9488;margin:14px 0}}table{{width:100%;border-collapse:collapse;margin:10px 0}}
td,th{{border:1px solid #e2e8f0;padding:7px 8px;text-align:left;font-size:14px;vertical-align:top}}th{{background:#f0fdfa}}.rx{{font-size:30px;color:#0d9488;font-weight:800}}
.btn{{background:#0d9488;color:#fff;border:0;border-radius:10px;padding:10px 18px;font-weight:700;cursor:pointer;margin-right:8px;text-decoration:none;display:inline-block}}
@media print{{body{{background:#fff}}main{{margin:0;padding:0}}.np{{display:none}}}}</style></head><body><main>
<div class="np" style="margin-bottom:14px"><button class="btn" type="button" id="pr">🖨️ Print / Save as PDF</button><a class="btn" style="background:#475569" href="/#account">← Back to Clinora</a></div>
<h1>{e(rx['doctor'])}</h1><div class="mu">{e(rx['spec'] or '')} · {e(rx['addr'])}, {e(rx['city'])} · {e(rx['phone'])}<br>{reg_line}</div><hr>
<p><b>Patient:</b> {e(rx['for_name'])} &nbsp; <b>Date:</b> {when} &nbsp; <b>Visit:</b> {'Video consultation' if rx['mode'] == 'video' else 'In clinic'}</p>
{f"<p><b>Diagnosis / findings:</b> {e(d['diagnosis'])}</p>" if d['diagnosis'] else ''}
<div class="rx">℞</div>{meds_html}
{f"<p><b>Tests:</b> {e(d['tests'])}</p>" if d.get('tests') else ''}
{f"<p><b>Advice:</b> {e(d['advice'])}</p>" if d['advice'] else ''}
{f"<p><b>Follow-up:</b> {datetime.date.fromisoformat(d['followup']).strftime('%d %b %Y')}</p>" if d.get('followup') else ''}
<p class="mu" style="margin-top:26px">Issued through Clinora by the doctor named above, who is responsible for this advice. Clinora does not check prescriptions.
Follow your doctor's advice; contact them if anything is unclear. In an emergency, call your local emergency number.</p></main>
<script nonce="__NONCE__">document.getElementById('pr').onclick=()=>window.print()</script></body></html>"""


# ---------------------------------------------------------------- online payment to doctors (Razorpay Route)
# The patient pays when booking; Razorpay sends the fee minus Clinora's share straight to the doctor's linked account.
# Without Razorpay keys (on your own computer) a demo payment button is shown instead. INR only (Route works in India).
PLATFORM_FEE_PCT = max(0.0, min(30.0, float(os.environ.get("PLATFORM_FEE_PCT") or 5)))
HOLD_MIN = 15
REFUND_HOURS = 24
ACC_RE = re.compile(r"^acc_[A-Za-z0-9]{8,30}$")


def doctor_pay_ready(lst, cur):
    if cur != "INR":
        return False
    if RAZORPAY_ON:
        return bool(lst["payout_acc"])
    return ALLOW_DEMO_PAYMENTS


def _paid_booking(conn, bid, me):
    b = conn.execute("SELECT b.*, l.name AS lname, l.payout_acc, l.owner FROM dbookings b JOIN listings l ON l.id=b.listing_id WHERE b.id=?", (bid,)).fetchone()
    if not b or b["patient_id"] != me["id"]:
        raise InputError("Booking not found")
    if b["status"] != "booked" or b["pay_status"] != "pending":
        raise InputError("This visit doesn't need a payment now")
    if (b["hold_until"] or 0) < now_ms():
        raise InputError("The 15 minutes to pay have passed, so the time was released. Please book again.")
    return b


def m_book_pay(conn, d, me):
    need_member(me)
    b = _paid_booking(conn, int(d.get("id") or 0), me)
    amount = int(b["fee"]) * 100
    if not RAZORPAY_ON:
        if not ALLOW_DEMO_PAYMENTS:
            raise InputError("Online payment isn't available yet.")
        return {"demo": True, "amount": amount, "cur": "INR"}
    share = int(round(amount * (1 - PLATFORM_FEE_PCT / 100)))
    order = http_json("POST", "https://api.razorpay.com/v1/orders", {
        "amount": amount, "currency": "INR", "receipt": f"dbook-{b['id']}", "notes": {"dbooking_id": str(b["id"])},
        "transfers": [{"account": b["payout_acc"], "amount": share, "currency": "INR", "on_hold": 0,
                       "notes": {"dbooking_id": str(b["id"])}}]}, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    conn.execute("UPDATE dbookings SET pay_ref=?, pay_amount=? WHERE id=?", (order["id"], amount, b["id"]))
    return {"razorpay": {"key": RAZORPAY_KEY_ID, "order_id": order["id"], "amount": amount, "currency": "INR", "name": "Clinora",
                         "description": f"Visit with {b['lname']} · {b['date']} {b['time']}", "prefill": {"name": me["name"], "email": me["email"]}}}


def mark_booking_paid(conn, bid, ref, amount):
    b = conn.execute("SELECT * FROM dbookings WHERE id=?", (bid,)).fetchone()
    if not b or b["pay_status"] == "paid":
        return
    conn.execute("UPDATE dbookings SET pay_status='paid', pay_ref=?, pay_amount=?, hold_until=NULL WHERE id=?", (ref, amount, bid))
    if b["status"] == "booked":
        booking_confirmed(conn, bid)
    else:  # paid after the hold ran out and the time was released: give the money back
        refund_booking(conn, conn.execute("SELECT * FROM dbookings WHERE id=?", (bid,)).fetchone())


def m_book_pay_demo(conn, d, me):
    need_member(me)
    if RAZORPAY_ON or not ALLOW_DEMO_PAYMENTS:
        raise AuthError("Demo payments are switched off on this website.")
    b = _paid_booking(conn, int(d.get("id") or 0), me)
    mark_booking_paid(conn, b["id"], "demo_" + secrets.token_hex(6), int(b["fee"]) * 100)
    return {"paid": True}


def m_book_pay_verify(conn, d, me):
    need_member(me)
    b = conn.execute("SELECT * FROM dbookings WHERE id=? AND patient_id=?", (int(d.get("id") or 0), me["id"])).fetchone()
    if not b or not RAZORPAY_ON:
        raise InputError("Booking not found")
    order_id, pay_id = text(d, "razorpay_order_id", 60), text(d, "razorpay_payment_id", 60)
    expected = hmac.new(RAZORPAY_KEY_SECRET.encode(), f"{order_id}|{pay_id}".encode(), hashlib.sha256).hexdigest()
    if order_id != b["pay_ref"] or not hmac.compare_digest(expected, str(d.get("razorpay_signature") or "")):
        raise AuthError("The payment could not be verified.")
    pay = http_json("GET", f"https://api.razorpay.com/v1/payments/{pay_id}", auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    if pay.get("order_id") != order_id or pay.get("status") not in ("captured", "authorized") or pay.get("amount") != b["pay_amount"]:
        raise AuthError("The payment could not be confirmed.")
    mark_booking_paid(conn, b["id"], pay_id, pay.get("amount"))
    return {"paid": True}


def refund_booking(conn, b):
    ref = b["pay_ref"] or ""
    if RAZORPAY_ON and ref.startswith("pay_"):
        try:  # reverse_all also takes back the doctor's share from their linked account
            http_json("POST", f"https://api.razorpay.com/v1/payments/{ref}/refund", {"reverse_all": 1}, auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
        except Exception as e:
            conn.execute("UPDATE dbookings SET pay_status='refund_due' WHERE id=?", (b["id"],))
            print(f"[pay] refund failed for visit {b['id']}: {e}", flush=True)
            return "refund pending (the clinic team will finish it)"
    conn.execute("UPDATE dbookings SET pay_status='refunded' WHERE id=?", (b["id"],))
    return "full refund sent (3–7 working days)" if ref.startswith("pay_") else "demo payment refunded"


def release_unpaid(conn):
    """Frees time slots whose online payment wasn't finished within 15 minutes."""
    for r in conn.execute("SELECT id, patient_id FROM dbookings WHERE status='booked' AND pay_status='pending' AND hold_until < ?", (now_ms(),)).fetchall():
        conn.execute("UPDATE dbookings SET status='cancelled', cancel_by='system', cancel_reason='Payment not finished in time', pay_status='none' WHERE id=?", (r["id"],))
        notify(conn, r["patient_id"], "booking", "⏳ Visit not booked", "The payment wasn't finished in 15 minutes, so the time was released. Please book again.", "account")


def payout_list(conn, d, user):
    need_admin(user)
    rows = conn.execute("SELECT l.id, l.name, l.city, l.payout_acc, m.email, (SELECT status FROM verifications v WHERE v.member_id=l.owner) AS ver "
                        "FROM listings l JOIN members m ON m.id=l.owner WHERE l.hidden=0 ORDER BY l.name")
    return {"doctors": [dict(r) for r in rows], "fee_pct": PLATFORM_FEE_PCT, "live": RAZORPAY_ON,
            "paid": conn.execute("SELECT COUNT(*), COALESCE(SUM(pay_amount),0) FROM dbookings WHERE pay_status='paid'").fetchone()[:]}


def payout_set(conn, d, user):
    need_admin(user)
    acc = str(d.get("acc") or "").strip()
    if acc and not ACC_RE.match(acc):
        raise InputError("A Razorpay linked account id looks like acc_XXXXXXXXXXXX")
    conn.execute("UPDATE listings SET payout_acc=? WHERE id=?", (acc or None, int(d.get("listing_id") or 0)))
    return payout_list(conn, d, user)


# ---------------------------------------------------------------- WhatsApp: Clinora's assistant on the WhatsApp Business Cloud API
# Patients message Clinora's WhatsApp number. The assistant answers in their language and finds real Clinora doctors
# with a one-tap booking link. Turn on with WHATSAPP_TOKEN, WHATSAPP_PHONE_ID, WHATSAPP_VERIFY_TOKEN, WHATSAPP_APP_SECRET.
WA_TOKEN = os.environ.get("WHATSAPP_TOKEN", "").strip()
WA_PHONE_ID = os.environ.get("WHATSAPP_PHONE_ID", "").strip()
WA_VERIFY = os.environ.get("WHATSAPP_VERIFY_TOKEN", "").strip()
WA_SECRET = os.environ.get("WHATSAPP_APP_SECRET", "").strip()
WA_API = os.environ.get("WHATSAPP_API_BASE", "https://graph.facebook.com/v21.0").rstrip("/")
WA_ON = bool(WA_TOKEN and WA_PHONE_ID and WA_VERIFY and WA_SECRET)
WA_SEEN = {}  # message id -> time, so a message Meta re-sends is answered only once

WA_SYSTEM = """You are Clinora's assistant on WhatsApp. Clinora helps people find and book real doctors.
- Reply in the same language the person writes in (Hindi, Hinglish, English, Urdu, Tamil...). Keep replies short: 1 to 5 lines, WhatsApp style, a few emojis at most.
- To find doctors use the find_doctors tool, then list up to 3 with name, specialty, fee and the booking link exactly as given. Never invent doctors or links.
- You don't give diagnoses or prescriptions. For medicines or symptoms give simple general guidance and suggest seeing a doctor.
- Emergencies (chest pain, trouble breathing, stroke signs, heavy bleeding, suicide thoughts): tell them to call 112 (India) or their local emergency number right now.
- You can't see bookings or accounts here. For their visits, reminders and prescriptions they open the Clinora website."""
WA_TOOLS = [{"name": "find_doctors", "description": "Search doctors and clinics registered on Clinora by city and/or specialty.",
             "input_schema": {"type": "object", "properties": {"city": {"type": "string"}, "specialty": {"type": "string"}}, "additionalProperties": False}}]


def find_doctors(conn, city="", specialty=""):
    city, spec = str(city or "").strip().lower(), str(specialty or "").strip().lower()
    out = []
    for d in public_listings(conn):
        hay = f"{d['name']} {d.get('spec') or ''} {d['type']}".lower()
        if city and city not in f"{d['city']} {d['country']}".lower():
            continue
        if spec and spec not in hay:
            continue
        b = d.get("booking")
        out.append({"name": d["name"], "specialty": d.get("spec") or d["type"], "city": d["city"], "verified": d["verified"],
                    "rating": d.get("rating"), "fee": f"{b['fee']} {b['cur']}" if b else None,
                    "book": f"{PUBLIC_URL}/#book/{d['id']}" if b else f"{PUBLIC_URL}{d['page']}", "online_booking": bool(b)})
    out.sort(key=lambda x: (not x["online_booking"], not x["verified"], -(x["rating"] or 0)))
    return out[:5]


def wa_menu_reply(conn, text_in):
    """Used when the AI is off: a simple keyword assistant."""
    t = text_in.strip().lower()
    if re.search(r"\b(chest pain|can'?t breathe|breathing|unconscious|suicid|bleeding|stroke|heart attack)\b", t):
        return "🚨 This sounds urgent. Call 112 (India) or your local emergency number right now."
    m = re.match(r"^(doctor|dr|doc|find)\s+(.+)$", t)
    if m:
        words = m.group(2).split()
        found = find_doctors(conn, city=words[-1], specialty=" ".join(words[:-1]))
        if not found:
            found = find_doctors(conn, specialty=" ".join(words))
        if not found:
            return f"😕 No Clinora doctors found for “{m.group(2)}” yet. Try: doctor dentist Srinagar\nOr search the map: {PUBLIC_URL}/#nearby"
        return "👨‍⚕️ Doctors on Clinora:\n" + "\n".join(
            f"• {d['name']} ({d['specialty']}, {d['city']}){' ✓' if d['verified'] else ''}{' · ' + d['fee'] if d['fee'] else ''}\n  {d['book']}" for d in found[:3])
    return (f"👋 Hi! I'm Clinora on WhatsApp.\n• Find a doctor: send *doctor dentist Srinagar*\n• Book, reminders, prescriptions: {PUBLIC_URL}\n"
            "• Emergency: call 112")


def wa_ai_reply(conn, phone, text_in):
    row = conn.execute("SELECT history FROM wa_threads WHERE phone=?", (phone,)).fetchone()
    hist = json.loads(row["history"]) if row else []
    msgs = hist[-16:] + [{"role": "user", "content": text_in[:2000]}]
    for _ in range(3):
        r = client.beta.messages.create(model=MODEL, max_tokens=1200, system=WA_SYSTEM, tools=WA_TOOLS, messages=msgs,
                                        output_config={"effort": "low"}, betas=["server-side-fallback-2026-07-01"], fallbacks="default")
        content = [b.model_dump(exclude_none=True) for b in r.content]
        msgs.append({"role": "assistant", "content": content})
        uses = [b for b in content if b.get("type") == "tool_use"]
        if r.stop_reason != "tool_use" or not uses:
            break
        msgs.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": u["id"],
                                                  "content": json.dumps(find_doctors(conn, **{k: v for k, v in (u.get("input") or {}).items() if k in ("city", "specialty")}))}
                                                 for u in uses]})
    reply = "\n".join(b.get("text", "") for b in msgs[-1]["content"] if b.get("type") == "text").strip() if msgs[-1]["role"] == "assistant" else ""
    keep = [m for m in msgs if isinstance(m["content"], str)] + ([{"role": "assistant", "content": reply}] if reply else [])
    conn.execute("INSERT OR REPLACE INTO wa_threads VALUES(?,?,?)", (phone, json.dumps(keep[-16:]), now_ms()))
    return reply or wa_menu_reply(conn, text_in)


def wa_send(phone, body):
    http_json("POST", f"{WA_API}/{WA_PHONE_ID}/messages",
              {"messaging_product": "whatsapp", "to": phone, "type": "text", "text": {"preview_url": True, "body": body[:4000]}}, bearer=WA_TOKEN)


def wa_handle(payload):
    """Runs in the background so Meta gets its 200 at once."""
    try:
        data = json.loads(payload)
    except ValueError:
        return
    for entry in data.get("entry") or []:
        for ch in entry.get("changes") or []:
            for msg in (ch.get("value") or {}).get("messages") or []:
                mid, phone = str(msg.get("id") or ""), re.sub(r"\D", "", str(msg.get("from") or ""))
                if not phone or mid in WA_SEEN:
                    continue
                WA_SEEN[mid] = time.time()
                if too_many("wa", phone, 30, 3600):
                    continue
                text_in = ((msg.get("text") or {}).get("body") or "").strip() if msg.get("type") == "text" else ""
                try:
                    with DB_LOCK, connect() as conn:
                        conn.execute("DELETE FROM wa_threads WHERE ts < ?", (now_ms() - 7 * 86_400_000,))
                        if not text_in:
                            reply = "🙏 I can read text messages only. Please type your question."
                        elif client is not None:
                            reply = None
                        else:
                            reply = wa_menu_reply(conn, text_in)
                    if reply is None:  # AI call outside the database lock
                        with connect() as conn:
                            reply = wa_ai_reply(conn, phone, text_in)
                    wa_send(phone, reply)
                except Exception as e:
                    print(f"[whatsapp] reply failed: {type(e).__name__}: {e}", flush=True)
    for k in [k for k, v in WA_SEEN.items() if v < time.time() - 86400]:
        WA_SEEN.pop(k, None)


MEMBER_ROUTES = {"/api/m/me": lambda conn, d, me: None, "/api/m/profile": m_profile, "/api/m/status": m_status,
                 "/api/m/fav": m_fav, "/api/m/send": m_send, "/api/m/thread": m_thread, "/api/m/photo": m_photo,
                 "/api/m/reviews": m_reviews, "/api/m/review": m_review, "/api/m/review/delete": m_review_delete,
                 "/api/m/review/reply": m_review_reply, "/api/m/gallery/add": m_gallery_add, "/api/m/gallery/delete": m_gallery_delete,
                 "/api/m/video/moderate": m_video_moderate, "/api/m/video/delete": m_video_delete,
                 "/api/m/verify/submit": m_verify_submit, "/api/m/reminder/save": m_reminder_save,
                 "/api/m/reminder/toggle": m_reminder_toggle, "/api/m/reminder/delete": m_reminder_delete,
                 "/api/m/report": m_report, "/api/m/block": m_block, "/api/m/confirm/resend": m_confirm_resend,
                 "/api/m/booking/settings": m_booking_settings, "/api/m/book": m_book, "/api/m/booking/cancel": m_booking_cancel,
                 "/api/m/booking/mark": m_booking_mark, "/api/m/slots": m_slots,
                 "/api/m/push/subscribe": m_push_subscribe, "/api/m/push/unsubscribe": m_push_unsubscribe,
                 "/api/m/family/save": m_family_save, "/api/m/family/delete": m_family_delete, "/api/m/rx/write": m_rx_write, "/api/m/rx/get": m_rx_get,
                 "/api/m/book/pay": m_book_pay, "/api/m/book/pay/demo": m_book_pay_demo, "/api/m/book/pay/verify": m_book_pay_verify}




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
                    (me["id"], other_id, other_id, me["id"])).fetchone() or has_booking(conn, me["id"], other_id):
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

# ---------------------------------------------------------------- prescription photo -> medicine reminders
RX_SYSTEM = """You read photos of medical prescriptions (handwritten or printed, from any country) for Clinora, a health website, so the patient can set medicine reminders.

Rules:
- Only list medicines you can actually read on the paper. Never guess a medicine name: if a word is unclear, write what you see and say in "note" that it was hard to read.
- Turn dosing into clock times in 24-hour HH:MM: once daily/OD -> 09:00; twice/BD/BID -> 09:00 and 21:00; three times/TDS/TID -> 08:00, 14:00, 20:00; four times/QID -> 08:00, 12:00, 16:00, 20:00; at night/HS/bedtime -> 22:00; morning-afternoon-night codes like 1-0-1 or 1-1-1 -> 08:00, 14:00, 21:00 for each 1; SOS/PRN/as needed -> no times.
- "days" = length of the course if written (e.g. "x 5 days" -> 5), otherwise 0.
- "food": before / after / with / any, as written (AC = before, PC = after).
- Do not give medical advice and do not change doses. Put anything important (e.g. "taper", "stop if rash") in "note".
- If the photo is not a prescription or can't be read, set readable=false and explain in "warning" in one short sentence.
- Write the warning and notes in the requested language."""
RX_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "properties": {
        "readable": {"type": "boolean"},
        "warning": {"type": "string"},
        "medicines": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "properties": {"name": {"type": "string"}, "strength": {"type": "string"}, "dose": {"type": "string"},
                           "times": {"type": "array", "items": {"type": "string"}}, "days": {"type": "integer"},
                           "food": {"type": "string", "enum": ["before", "after", "with", "any"]}, "note": {"type": "string"}},
            "required": ["name", "strength", "dose", "times", "days", "food", "note"]}}},
    "required": ["readable", "warning", "medicines"]}


def rx_scan(d, ip):
    if client is None:
        print("[AI] Prescription scan unavailable: no ANTHROPIC_API_KEY in .env", flush=True)
        raise InputError("Prescription reading is resting right now. Please add reminders by hand, or try later.")
    if too_many("rx", ip, 20, 3600):
        raise AuthError("You've scanned a lot this hour. Please try again a little later.", 429)
    prefix = "data:image/jpeg;base64,"
    data = str(d.get("image") or "")
    if not data.startswith(prefix):
        raise InputError("Please take or choose a photo of the prescription")
    try:
        raw = base64.b64decode(data[len(prefix):], validate=True)
    except ValueError:
        raise InputError("That photo could not be read")
    if len(raw) > MAX_FOOD_PHOTO or not raw.startswith(b"\xff\xd8\xff"):
        raise InputError("That photo could not be used. Try another one.")
    response = client.beta.messages.create(
        model=MODEL, max_tokens=4000, system=RX_SYSTEM,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data[len(prefix):]}},
            {"type": "text", "text": "Read this prescription and list the medicines with reminder times. Reply language: "
             + str(d.get("lang") or "English")[:40]}]}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": RX_SCHEMA}},
        betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    if response.stop_reason == "refusal":
        raise InputError("Sorry, this photo can't be read. Try a clearer photo of the prescription.")
    txt = next((b.text for b in response.content if getattr(b, "type", "") == "text"), "")
    try:
        out = json.loads(txt)
    except ValueError:
        raise InputError("Reading didn't finish. Please try again.")
    for m in out.get("medicines", []):  # keep only valid clock times and sane course lengths
        m["times"] = [x for x in m.get("times", []) if HHMM_RE.match(str(x))][:6]
        m["days"] = max(0, min(int(m.get("days") or 0), 365))
    return out


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
        b = conn.execute("SELECT * FROM dbookings WHERE pay_ref=?", (pay.get("order_id"),)).fetchone()
        if b and pay.get("status") == "captured" and pay.get("amount") == b["pay_amount"]:
            mark_booking_paid(conn, b["id"], pay.get("id"), pay.get("amount"))
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
    "/api/report/list": report_queue,
    "/api/backup/list": backup_info,
    "/api/stats/overview": stats_overview,
    "/api/payout/list": payout_list,
    "/api/payout/set": payout_set,
    "/api/backup/now": backup_now,
    "/api/report/decide": report_decide,
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


# Content-Security-Policy: the browser only runs scripts from our own page (with the per-load nonce) and the
# few services we use, so injected <script> or onclick=... code is blocked even if something slipped through.
CSP_PAGE = ("default-src 'self'; script-src 'self' 'nonce-{n}' https://unpkg.com https://accounts.google.com https://checkout.razorpay.com; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com https://accounts.google.com; img-src 'self' data: blob: https:; "
            "font-src 'self' data: https:; connect-src 'self' https: wss:; media-src 'self' blob: mediastream:; worker-src 'self' blob:; "
            "child-src 'self' blob:; frame-src https://accounts.google.com https://*.razorpay.com; object-src 'none'; base-uri 'self'; "
            "form-action 'self' https:; frame-ancestors 'none'; manifest-src 'self'")
CSP_OTHER = "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
_INDEX_CACHE = {}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        self._cache = self._csp = None
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", getattr(self, "_cache", None) or "no-store")
        self.send_header("Content-Security-Policy", getattr(self, "_csp", None) or CSP_OTHER)
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

    def send_index(self):
        """The home page: a fresh CSP nonce on every script tag, gzip-compressed (about 380 KB → 90 KB)."""
        import gzip
        f = ROOT / "index.html"
        mt = f.stat().st_mtime
        if _INDEX_CACHE.get("mt") != mt:
            _INDEX_CACHE.update(mt=mt, html=f.read_text(encoding="utf-8"))
        nonce = secrets.token_urlsafe(16)
        body = _INDEX_CACHE["html"].replace("<script", f'<script nonce="{nonce}"').encode()
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "")
        if gz:
            body = gzip.compress(body, 6)
        self._cache, self._csp = "no-cache", CSP_PAGE.format(n=nonce)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Vary", "Accept-Encoding")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_static_gz(self, rel, ctype):
        import gzip
        body = (ROOT / rel).read_bytes()
        gz = "gzip" in (self.headers.get("Accept-Encoding") or "") and len(body) > 1500
        if gz:
            body = gzip.compress(body, 6)
        self._cache = "no-cache"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Vary", "Accept-Encoding")
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._cache = self._csp = None
        path_only = self.path.split("?")[0]
        if path_only in ("/", "/index.html"):
            return self.send_index()
        if path_only == "/i18n.js":
            return self.send_static_gz("i18n.js", "text/javascript; charset=utf-8")
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
        if path_only == "/api/whatsapp/webhook":
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if WA_ON and q.get("hub.mode", [""])[0] == "subscribe" and hmac.compare_digest(q.get("hub.verify_token", [""])[0], WA_VERIFY):
                return self.send_text(200, q.get("hub.challenge", [""])[0][:200], "text/plain")
            return self.send_text(403, "forbidden", "text/plain")
        m = re.fullmatch(r"/rx/(\d+)", path_only)
        if m:
            with connect() as conn:
                rx = prescription_for(conn, int(m.group(1)), member_for_token(conn, self.member_token()))
            if not rx:
                return self.send_text(404, "<!DOCTYPE html><title>Not found</title><p>Prescription not found, or you are not logged in. <a href='/#account'>Log in</a></p>",
                                      "text/html; charset=utf-8")
            nonce = secrets.token_urlsafe(16)
            self._csp = CSP_OTHER.replace("default-src 'none'", f"default-src 'none'; script-src 'nonce-{nonce}'")
            return self.send_text(200, prescription_page(rx).replace("__NONCE__", nonce), "text/html; charset=utf-8")
        m = re.fullmatch(r"/doctor/(\d+)(?:-[a-z0-9-]*)?", path_only)
        if m:
            with connect() as conn:
                page, slug = doctor_page(conn, int(m.group(1)))
            if not page:
                return self.send_text(404, "<!DOCTYPE html><title>Not found</title><p>This doctor is no longer on Clinora. <a href='/'>Find another doctor</a></p>",
                                      "text/html; charset=utf-8")
            if path_only != f"/doctor/{slug}":  # one address per doctor, even if the name changes
                return self.redirect(f"/doctor/{slug}")
            self._cache = "no-cache"
            return self.send_text(200, page, "text/html; charset=utf-8")
        if path_only == "/robots.txt":
            return self.send_text(200, f"User-agent: *\nAllow: /\nDisallow: /api/\nSitemap: {PUBLIC_URL}/sitemap.xml\n", "text/plain")
        if path_only == "/sitemap.xml":
            with connect() as conn:
                docs = [f"/doctor/{doctor_slug(r)}" for r in conn.execute("SELECT id, name, city FROM listings WHERE hidden=0 ORDER BY id")]
            urls = "".join(f"<url><loc>{html.escape(PUBLIC_URL + u)}</loc></url>" for u in ["/", "/privacy", "/terms", "/delete-account"] + docs)
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
        if path_only.startswith("/api/backup/file/"):
            name = path_only.rsplit("/", 1)[1]
            with connect() as conn:
                user = user_for_token(conn, self.session_token())
            f = BACKUP_DIR / name
            if not user or user["role"] != "admin" or not BACKUP_NAME_RE.match(name) or not f.is_file():
                return self.send_json(404, {"error": "not found"})
            self.send_response(200)
            self.send_header("Content-Type", "application/gzip")
            self.send_header("Content-Length", str(f.stat().st_size))
            self.send_header("Content-Disposition", f'attachment; filename="{name}"')
            self.send_header("Cache-Control", "private, no-store")
            self.end_headers()
            with f.open("rb") as fh:
                while chunk := fh.read(1 << 20):
                    self.wfile.write(chunk)
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
        if path_only == "/sw.js":  # the service worker runs under its own policy: it only talks to our own site
            self._csp = "default-src 'self'"
        if path_only.startswith("/assets/"):  # images, icons, GIFs: cache a week (change the ?v= to refresh)
            self._cache = "public, max-age=604800"
        else:
            self._cache = "no-cache"
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
        self._cache = self._csp = None
        path = self.path.split("?")[0]
        if path == "/api/whatsapp/webhook":
            length = int(self.headers.get("Content-Length") or 0)
            if not WA_ON or length > 1_000_000:
                return self.send_json(404, {"error": "not found"})
            payload = self.rfile.read(length)
            sig = (self.headers.get("X-Hub-Signature-256") or "").removeprefix("sha256=")
            if not hmac.compare_digest(hmac.new(WA_SECRET.encode(), payload, hashlib.sha256).hexdigest(), sig):
                return self.send_json(403, {"error": "bad signature"})
            threading.Thread(target=wa_handle, args=(payload,), daemon=True).start()
            return self.send_json(200, {"ok": True})
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
        if path == "/api/rxscan":
            try:
                data = self.read_json(2_000_000)
                if not isinstance(data, dict):
                    raise InputError("Bad request")
                return self.send_json(200, rx_scan(data, self.client_ip()))
            except InputError as e:
                return self.send_json(400, {"error": str(e)})
            except AuthError as e:
                return self.send_json(e.status, {"error": str(e)})
            except Exception as e:
                print("Prescription scan error:", repr(e)[:300], flush=True)
                return self.send_json(502, {"error": "Prescription reading is busy. Please try again."})
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
                if path == "/api/m/confirm":
                    mid = m_confirm(conn, data)
                    me = member_for_token(conn, self.member_token())
                    if me and me["id"] == mid:
                        return self.send_json(200, member_state(conn, me))
                    token = new_member_session(conn, mid)  # opened the link on another device: log in there
                    return self.send_json(200, member_state(conn, member_for_token(conn, token)), cookie=self.member_cookie(token, 30 * 86_400))
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
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        sys.exit(1 if launch_check() else 0)
    if len(sys.argv) > 2 and sys.argv[1] == "--restore":
        restore_backup(sys.argv[2])
        sys.exit(0)
    if len(sys.argv) > 1 and sys.argv[1] == "--backup":
        init_db()
        print(make_backup("command line"))
        sys.exit(0)
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
    try:
        PUSH_KEY = vapid_public_key()
    except Exception as e:
        print("Push notifications OFF:", e)
    print("Push notifications:", "ON" if PUSH_KEY else "OFF (pip install pywebpush)")
    threading.Thread(target=reminder_loop, daemon=True).start()
    threading.Thread(target=backup_loop, daemon=True).start()
    print("Backups:", f"every {BACKUP_EVERY_H:g} h, keeping {BACKUP_KEEP}, in {BACKUP_DIR}" + (" + cloud copy" if S3_ON else " (this computer/disk only)"))
    ThreadingHTTPServer((os.environ.get("HOST", "127.0.0.1"), PORT), Handler).serve_forever()

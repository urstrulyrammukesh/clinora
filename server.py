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

Safety:
- You are not a doctor. Do not diagnose, prescribe, or give dosage advice. You may suggest which kind of specialist fits the symptoms and help book them.
- If the message suggests an emergency (chest pain, trouble breathing, stroke signs, heavy bleeding, unconsciousness, severe allergic reaction, suicidal thoughts, poisoning, serious injury), first call get_emergency_numbers and alert_clinic_staff, then tell them to call the local emergency number now, before anything else.
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
        {"page": {"type": "string", "enum": ["home", "nearby", "directory", "dashboard"]}},
    ),
]

# ---------------------------------------------------------------- database
DB_PATH = ROOT / "data" / "sehatdesk.db"
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
    DB_PATH.parent.mkdir(exist_ok=True)
    with DB_LOCK, connect() as conn:
        conn.executescript(SCHEMA)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(appointments)")}
        for col, kind in [("call_token", "TEXT"), ("pay_token", "TEXT"), ("pay_status", "TEXT DEFAULT 'unpaid'"),
                          ("amount", "INTEGER"), ("currency", "TEXT"), ("pay_ref", "TEXT"), ("paid_ts", "INTEGER"),
                          ("pay_method", "TEXT"), ("pay_currency", "TEXT"), ("pay_amount", "INTEGER")]:
            if col not in cols:
                conn.execute(f"ALTER TABLE appointments ADD COLUMN {col} {kind}")
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
        "listings": [dict(r, video=bool(r["video"])) for r in conn.execute("SELECT * FROM listings ORDER BY ts")],
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
        "INSERT INTO listings(name,type,spec,phone,email,web,addr,city,country,cc,video,lat,lon,ts) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (text(d, "name", 100), one_of(d, "type", LIST_TYPES), text(d, "spec", 80, False), phone_of(d),
         text(d, "email", 120, False), web, text(d, "addr", 160), text(d, "city", 80), text(d, "country", 80),
         text(d, "cc", 2, False).upper(), 1 if d.get("video") else 0, lat, lon, now_ms()))


def delete_listing(conn, d, user=None):
    need_admin(user)
    conn.execute("DELETE FROM listings WHERE id=?", (int(d.get("id") or 0),))


def reset_demo(conn, d, user=None):
    need_admin(user)
    conn.executescript("DELETE FROM appointments; DELETE FROM alerts; DELETE FROM live; DELETE FROM stats;")
    seed(conn)


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
            return self.send_json(200, {"ai": client is not None, "reason": AI_REASON, "model": MODEL,
                                        "pay_mode": PAY_MODE, "currency": CURRENCY, "video_needs_payment": REQUIRE_VIDEO_PAYMENT})
        # never serve private files
        name = self.path.split("?")[0].lstrip("/")
        if name.startswith((".env", ".venv", "server.py", "data", "set-key", ".claude")):
            return self.send_json(404, {"error": "not found"})
        return super().do_GET()

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
        # Only JSON requests: blocks other websites from submitting plain forms here (CSRF)
        if not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return self.send_json(415, {"error": "JSON required"})
        if path in ("/api/auth/login", "/api/auth/setup", "/api/auth/logout"):
            return self.auth(path)
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
        if path == "/api/pay/checkout" and too_many("pay", self.client_address[0], 20, 600):
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
            return self.send_json(503, {"error": AI_REASON})
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
        except anthropic.AuthenticationError:
            return self.send_json(401, {"error": "The API key was rejected. Check ANTHROPIC_API_KEY in .env."})
        except anthropic.RateLimitError:
            return self.send_json(429, {"error": "The AI is busy right now. Please try again in a moment."})
        except anthropic.BadRequestError as e:
            return self.send_json(400, {"error": f"Request rejected: {e.message}"})
        except anthropic.APIStatusError as e:
            return self.send_json(502, {"error": f"AI service error ({e.status_code}). Please try again."})
        except anthropic.APIConnectionError:
            return self.send_json(502, {"error": "Could not reach the AI service. Check the internet connection."})

    def auth(self, path):
        try:
            data = self.read_json(5_000) if path != "/api/auth/logout" else {}
            with DB_LOCK, connect() as conn:
                if path == "/api/auth/logout":
                    conn.execute("DELETE FROM sessions WHERE token=?", (token_hash(self.session_token()),))
                    return self.send_json(200, {"ok": True, "data": snapshot(conn)}, self.cookie("", 0))
                uid = setup_admin(conn, data) if path == "/api/auth/setup" else login(conn, data, self.client_address[0])
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
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()

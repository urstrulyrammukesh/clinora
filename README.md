# ✚ Clinora

**AI receptionist for clinics, built for patients anywhere in the world.**

Patients can chat with an AI receptionist (powered by Claude) to book in-clinic visits or video consultations, find doctors, hospitals, labs and medical colleges in any city, see who is open right now on a 3D map, pay in their own currency, and book a cab to the hospital. Clinics get a private dashboard with doctor logins.

> ⚠️ Demo project. The clinic, doctors and sample data are placeholders. The AI does not give medical advice. In an emergency, call your local emergency number.

## Features
- 💬 **AI chat panel** on every page (Claude): bookings, cancellations, fees, emergencies, worldwide directory search
- 🌍 **139 languages**: 9 hand-translated, the rest translated by AI once and saved; right-to-left support
- 📍 **Nearby doctors** on a 3D map with open/closed status and local emergency numbers
- 🗂️ **World directory**: hospitals, clinics, doctors, dentists, pharmacies, labs, universities and medical colleges (OpenStreetMap data)
- 📹 **Video consultations** (browser-to-browser WebRTC)
- 💳 **Payments** in 52 currencies: UPI / Paytm / Google Pay (Razorpay), cards / Apple Pay / Google Pay (Stripe), PayPal. Runs in demo mode until keys are added
- 🚕 **Ride booking** links per country (Uber, Ola, Rapido, Lyft, Careem, Grab, Bolt…)
- 🔒 **Clinic dashboard** with admin and doctor roles, hashed passwords, private patient data
- 🎛️ **Style panel**: motion level, colours, font and text size

## Run it on your computer (macOS)
1. Double-click **`start.command`**. The first run sets everything up.
2. Open **http://localhost:8765**

Or from a terminal:
```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

## Keys (optional)
Copy `.env.example` to `.env` and add your own keys. **Never commit `.env`.**
- `ANTHROPIC_API_KEY`: turns on the real AI chat and AI translations
- `STRIPE_SECRET_KEY`, `RAZORPAY_KEY_ID` / `RAZORPAY_KEY_SECRET`, `PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`: real payments (use test keys first)

Without keys, the site runs with simple built-in chat replies and demo payments.

## Files
| File | What it is |
|---|---|
| `index.html` | The whole website |
| `i18n.js` | Translations and the language list |
| `server.py` | Web server, AI, database (SQLite), logins, payments, video-call signalling |
| `data/` | Database and saved AI translations (the database is not uploaded) |
| `assets/` | Images |

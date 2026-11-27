# Changelog

All notable changes to Clinora. Dates are when the work landed on `main`.

## [1.2.0] – 2026-11-27

### Security
- **Two-factor login for clinic staff** (issue #6): authenticator apps (Google/Microsoft Authenticator, Authy…) via QR code, 10 one-time recovery codes, codes can't be reused, 6 wrong codes → 15-minute lock. The secret is stored encrypted (AES-256-GCM) and recovery codes only as hashes. Admins can reset 2FA for staff who lost their phone.
- QR codes are made by Clinora itself (no outside service), checked against the python-qrcode library and a real QR scanner

### Also
- Visitor statistics panel translated into all 8 built-in languages (issue #4)

## [1.1.0] – 2026-11-27

Security audit release. Report: [docs/security-audit.md](docs/security-audit.md) · threat model: [docs/threat-model.md](docs/threat-model.md)

### Security
- Scripts from other sites are now allowed **by exact file**, not whole sites (an injected unpkg.com script would have run before)
- **Rate limit on the AI chat** (60 messages per visitor per hour) to stop "denial of wallet" abuse
- Fixed 8 known vulnerabilities in packages pulled in by `pywebpush` (`aiohttp`, `multidict`)
- Unexpected errors return a plain message; details stay in the server log
- `Cross-Origin-Opener-Policy` header; https-only backup storage; only web addresses for outgoing requests
- Rate-limit tables can no longer grow without end
- CI now also runs Bandit, pip-audit and measures test coverage (55%)

### New
- **Visitor statistics** for admins: visitors per day, countries, devices, where they came from, app opens and installs. Anonymous: no cookies, no IP addresses stored, Do-Not-Track respected
- **Keeps data on free hosting**: a last cloud backup when the server stops, automatic restore when it starts on an empty disk
- Demo GIF, issue and pull-request templates, CONTRIBUTING guide, custom-domain guide

## [1.0.0] – 2026-11-27

The first complete version: live at **https://clinora-cwxu.onrender.com**.

### For patients
- Find doctors, hospitals, labs and pharmacies worldwide (OpenStreetMap), on a 3D map, with "open now" and filters
- **Book real doctors**: free slots, in-clinic or video, family members, online payment (Razorpay Route) with automatic refunds
- **Video visits** with a Join button, **printable prescriptions** and one-tap medicine reminders
- **Reminders** by bell, phone push, email, SMS and WhatsApp; prescription photo → reminders
- **Encrypted health records** (AES-256-GCM), shared with one doctor for one visit
- **Clinic queue tokens** with a live tracking link (no login) and turn alerts
- AI assistant in 139 languages, Food Scan, cheaper generic medicines, voice input, free medical books
- **Installed phone app** with its own home screen and bottom tabs

### For doctors and clinics
- Public doctor pages (5 designs) that Google can find; verified-doctor badge
- Online booking calendar, patient history (EHR lite) with private notes, receipts
- Doctor dashboard: visits, no-show rate, earnings, busiest hours; clinic teams; invite links
- Clinic admin: statistics, doctor verification, reports & blocking, payouts, daily backups

### Security & quality
- Strict Content-Security-Policy with nonce, SRI, PBKDF2 passwords, HttpOnly cookies, rate limits, HMAC webhooks
- Email and phone verification, first-admin setup code, suspended accounts
- 33 automated end-to-end test groups on every push, CodeQL security scanning, Dependabot
- Accessibility: names for every field, skip link, visible keyboard focus

### Infrastructure
- One-command launch check (`python server.py --check`), Render blueprint, backups with optional cloud copy
- WhatsApp Cloud API assistant, Web Push notifications, SMS (MSG91 / Twilio)

See every step in the [build timeline](https://github.com/urstrulyrammukesh/clinora-tech-stack/blob/main/TIMELINE.md).

# Clinora security audit — 27 November 2026

I audited my own app the way an outside tester would: automated scanners first, then hand checks on the live site, then fixes, each one locked in by an automated test.

**Scope:** `server.py` (Python server, 128 API endpoints), `index.html` (web app), dependencies, and the live site at `clinora-cwxu.onrender.com`.
**Tools:** [Bandit](https://bandit.readthedocs.io) (Python code scanner), [pip-audit](https://pypi.org/project/pip-audit/) (known vulnerabilities in packages), GitHub CodeQL (runs on every push), `curl` and a browser for live checks.

## Summary

| # | Finding | Severity | Status |
|---|---|---|---|
| 1 | Script rules allowed **all of unpkg.com** | Medium | ✅ Fixed |
| 2 | Known vulnerabilities in `aiohttp` (7) and `multidict` (1) | Medium | ✅ Fixed |
| 3 | Unexpected server errors dropped the connection | Low | ✅ Fixed |
| 4 | No `Cross-Origin-Opener-Policy` header | Low | ✅ Fixed |
| 5 | Outgoing requests accepted any URL scheme (Bandit B310) | Low | ✅ Hardened |
| 6 | Backup storage address could be plain `http://` | Low | ✅ Fixed |
| 7 | SQL built with an f-string (Bandit B608) | — | False positive, documented |
| 8 | **AI chat had no rate limit** (anyone could run up the AI bill) | Medium | ✅ Fixed |
| 9 | Rate-limit memory never shrank (slow memory exhaustion) | Low | ✅ Fixed |

## Findings

### 1. Script rules allowed all of unpkg.com — Medium
**What:** The Content-Security-Policy said `script-src … https://unpkg.com`. unpkg serves *every* npm package, so if an attacker ever managed to inject a `<script src="https://unpkg.com/their-package">` tag, the browser would have run it. That cancels most of the protection a CSP gives.
**Fix:** CSP now allows the **exact file** (`https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js`) and Google sign-in only under `/gsi/`. The file also carries a Subresource-Integrity hash, so even a changed copy would be refused.
**Proof:** in a browser, the map library still loads and Google sign-in still loads, but `https://unpkg.com/lodash@4.17.21/lodash.min.js` is **blocked**. Test: `tests/test_site.py::test_security_audit_fixes`.

### 2. Vulnerable dependencies — Medium
**What:** `pip-audit` found 7 advisories in `aiohttp 3.13.5` and 1 in `multidict 6.7.1`. Clinora doesn't use them directly; they come in through `pywebpush` (phone notifications).
**Fix:** `requirements.txt` now requires `aiohttp>=3.14.4` and `multidict>=6.9.1`. Dependabot watches for new ones every week.

### 3. Unexpected errors dropped the connection — Low
**What:** if something unplanned failed inside an API call (for example a missing library), the server closed the connection with no answer. Visitors saw a broken page, and the full error went only to the log by accident.
**Fix:** every unexpected error now returns a plain `500 "Something went wrong on our side"` with **no stack trace or file paths**, and the full details are written to the server log for me.

### 4. Missing Cross-Origin-Opener-Policy — Low
**Fix:** `Cross-Origin-Opener-Policy: same-origin-allow-popups` on every response. Other sites that open Clinora in a popup can't reach into its window (stops "tabnabbing"-style tricks), while Google and Razorpay pop-ups still work.

### 5. Outgoing requests accepted any URL scheme — Low
**What:** Bandit B310: `urllib.urlopen` can open `file://` addresses. All Clinora's addresses are fixed `https://` provider URLs, so this wasn't exploitable, but one mistake in settings could change that.
**Fix:** the shared request helper refuses anything that isn't `http(s)://`.

### 6. Backup storage over plain http — Low
**Fix:** `BACKUP_S3_ENDPOINT` must start with `https://`; otherwise the cloud copy is turned off with a clear log message, so backups are never sent unencrypted.

### 7. SQL f-string — false positive
`make_backup` counts rows with `f'SELECT COUNT(*) FROM "{t}"'`. The table names come from SQLite's own `sqlite_master`, never from a visitor. Marked `# nosec B608` with the reason. Every query that touches visitor input uses `?` placeholders.

### 8. AI chat had no rate limit — Medium
**What:** found by hand while checking every limit for this report. Logins, sign-ups, codes, bookings and uploads were all limited, but `/api/chat` was not. A script could send thousands of messages and every one is a paid call to the AI provider ("denial of wallet").
**Fix:** 60 messages per visitor per hour (setting `CHAT_PER_HOUR`), then a friendly "please wait" message.

### 9. Rate-limit memory never shrank — Low
**What:** the in-memory tables of recent requests and failed logins kept one entry per visitor address forever. Requests from many different addresses would slowly use up the server's memory.
**Fix:** each entry keeps only what its limit needs, and old visitors are forgotten once the table gets large.

## What was already strong (checked on the live site)

| Check | Result |
|---|---|
| HTTPS + HSTS (1 year, subdomains) | ✅ |
| CSP with a new random nonce on every page load; no inline `onclick=` handlers | ✅ |
| `X-Frame-Options: DENY`, `frame-ancestors 'none'` (no clickjacking) | ✅ |
| `X-Content-Type-Options: nosniff`, strict `Referrer-Policy`, `Permissions-Policy` | ✅ |
| `/server.py`, `/.env`, `/data/*.db`, `/../` path tricks → 404/400 | ✅ |
| `TRACE` method → 405 | ✅ |
| Passwords: PBKDF2-SHA256, 310,000 rounds, per-user salt | ✅ |
| Session cookies `HttpOnly`, `SameSite=Lax`, `Secure` on HTTPS | ✅ |
| Rate limits on login (8 failures → 15-minute lock), sign-up, codes, bookings, uploads | ✅ |
| Payment and WhatsApp webhooks verified with HMAC | ✅ |
| Health records encrypted with AES-256-GCM (record id bound in as extra data) | ✅ |
| Uploads: type checked against allow-list (HTML/script files refused) | ✅ |
| Other patients' records/visits → 404, not 403 (doesn't reveal they exist) | ✅ |

## Results after the fixes

- Bandit: **0 high**, 3 medium (all reviewed: fixed `https` provider URLs), 2 low (`try/except/pass` around optional clean-up)
- pip-audit (Python 3.11, as on Render): **0 known vulnerabilities**
- Tests: **all 36 pass** in CI (the push test needs `pywebpush` installed), including the new `test_security_audit_fixes`
- CodeQL: no alerts

## Still to do (needs money or accounts, tracked in `docs/go-live.md`)
- Two-factor login for clinic admins
- A paid penetration test before handling real patient data at scale
- Web Application Firewall rules (Cloudflare) once on a custom domain

See also the [threat model](threat-model.md).

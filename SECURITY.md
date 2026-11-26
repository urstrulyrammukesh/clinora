# Security policy

Clinora handles health information, so security reports are taken seriously and answered quickly.

## Reporting a vulnerability

**Please do not open a public issue for security problems.**

- Use GitHub's **[private vulnerability report](https://github.com/urstrulyrammukesh/clinora/security/advisories/new)** (Security tab → *Report a vulnerability*), or
- email **xxxtenticonicon@gmail.com** with the subject `Clinora security`.

Please include: what you found, steps to reproduce, the impact, and (if you like) a suggested fix.

## What to expect

| Step | Target time |
|---|---|
| First reply | within 72 hours |
| Confirmation and severity | within 7 days |
| Fix for critical/high issues | as soon as possible, usually within 30 days |

You will be credited in the release notes unless you prefer to stay anonymous.

## Scope

In scope: this repository's code (`server.py`, `index.html`, `sw.js`) and the demo at `clinora-cwxu.onrender.com`.

Out of scope: denial-of-service and load testing, social engineering, physical attacks, and third-party services (Render, Razorpay, Meta, Anthropic…). Please use test accounts only and never access other people's data.

## Security already built in

Strict Content-Security-Policy with per-page nonce · Subresource Integrity · PBKDF2 password hashing · HttpOnly/SameSite cookies · CSRF and rate limits · HMAC-verified webhooks · AES-256-GCM encrypted health records · email and phone verification · doctor registration checks · automated tests and CodeQL scanning on every push.

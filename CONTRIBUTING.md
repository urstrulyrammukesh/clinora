# Contributing to Clinora

Thanks for wanting to help! Clinora is a health platform, so **security and patient privacy come first** in every change.

## Quick start

```bash
git clone https://github.com/urstrulyrammukesh/clinora.git
cd clinora
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python server.py          # then open http://localhost:8765
```

No keys are needed: payments run in demo mode, emails and SMS are printed in the terminal.

## Before you open a pull request

```bash
.venv/bin/pytest -q tests                                  # all tests must pass
CLINORA_COVERAGE=1 .venv/bin/pytest -q tests && coverage combine && coverage report   # optional: coverage
```

- Add a test for what you change (`tests/`). Tests start a real server with an empty database, so they're easy to write: look at `tests/test_booking.py`.
- Check every piece of visitor input **on the server**, not only in the page.
- Use `?` placeholders in SQL, never string formatting with visitor input.
- New outside scripts must be added to the Content-Security-Policy **as exact files** (see [docs/security-audit.md](docs/security-audit.md)).
- Never commit `.env`, keys, or anything from `data/`.

## Good first issues

Look for the [`good first issue`](https://github.com/urstrulyrammukesh/clinora/labels/good%20first%20issue) label: small, well-described tasks that are a good way to learn the code.

## How the code is laid out

| File | What's in it |
|---|---|
| `server.py` | The whole server: API, database, security, background jobs |
| `index.html` | The whole web app (plain JavaScript, no build step) |
| `i18n.js` | Translations |
| `tests/` | End-to-end tests with pytest |
| `docs/` | Guides: going live, backups, payments, WhatsApp, security |

## Reporting security problems

Please **don't** open a public issue. See [SECURITY.md](SECURITY.md).

## Questions

Ask in [Discussions](https://github.com/urstrulyrammukesh/clinora/discussions).

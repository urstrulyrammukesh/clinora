"""Security headers, compression, doctor pages, backups, statistics, live-site safeguards."""
import gzip
import io
import json
import re
import tarfile
import time

from conftest import Server


def test_home_page_csp_and_gzip(server):
    c = server.client()
    s, body, h = c.get("/", {"Accept-Encoding": "gzip"})
    assert s == 200 and h["Content-Encoding"] == "gzip"
    page = gzip.decompress(body).decode()
    nonce = re.search(r"'nonce-([\w-]+)'", h["Content-Security-Policy"]).group(1)
    assert all(f'nonce="{nonce}"' in tag for tag in re.findall(r"<script[^>]*>", page))
    assert not re.search(r"\son(click|error|load)=\"", page)  # no inline handlers
    assert "frame-ancestors 'none'" in h["Content-Security-Policy"]
    assert c.get("/server.py")[0] == 404 and c.get("/data/sehatdesk.db")[0] == 404 and c.get("/.env")[0] == 404


def test_security_audit_fixes(server):
    """From docs/security-audit.md: outside scripts are allowed by exact file, not whole sites; COOP is set."""
    s, _, h = server.client().get("/")
    csp = h["Content-Security-Policy"]
    script_src = re.search(r"script-src ([^;]+)", csp).group(1).split()
    assert "https://unpkg.com" not in script_src and "https://accounts.google.com" not in script_src
    assert "https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js" in script_src
    assert h["Cross-Origin-Opener-Policy"] == "same-origin-allow-popups"
    assert h["X-Frame-Options"] == "DENY" and h["X-Content-Type-Options"] == "nosniff"


def test_doctor_page_and_sitemap(server, uniq):
    doc = server.client()
    doc.signup("doctor", "Dr Page", uniq())
    lid = doc.profile("Page Clinic")
    s, body, h = server.client().get(f"/doctor/{lid}")
    assert s == 200 and b"Page Clinic" in body and b'"@type": "Physician"' in body
    _, sm, _ = server.client().get("/sitemap.xml")
    assert f"/doctor/{lid}-page-clinic".encode() in sm
    assert server.client().get("/doctor/999999")[0] == 404


def test_backup_and_admin_only(server, admin):
    p = server.client()
    assert p.post("/api/backup/list")[0] in (401, 403)
    assert admin.post("/api/backup/now")[0] == 200
    for _ in range(40):
        b = admin.post("/api/backup/list")[1]["created"]["backups"]
        if b:
            break
        time.sleep(0.25)
    s, body, h = admin.get("/api/backup/file/" + b[0]["name"])
    assert s == 200 and h["Content-Disposition"].startswith("attachment")
    tf = tarfile.open(fileobj=io.BytesIO(body))
    assert "sehatdesk.db" in tf.getnames() and json.loads(tf.extractfile("manifest.json").read())["app"] == "clinora"
    assert p.get("/api/backup/file/" + b[0]["name"])[0] == 404


def test_stats_admin_only(server, admin):
    assert server.client().post("/api/stats/overview")[0] in (401, 403)
    s, j = admin.post("/api/stats/overview")
    assert s == 200 and len(j["created"]["series"]["signups"]) == 8


def test_live_site_safeguards(tmp_path):
    live = Server(tmp_path / "live", {"APP_ENV": "production", "ADMIN_SETUP_CODE": "secret-code-123"})
    try:
        c = live.client()
        A = {"name": "Admin", "email": "a@test.in", "password": "Adminpass123"}
        assert c.post("/api/auth/setup", A)[0] == 403
        assert c.post("/api/auth/setup", dict(A, code="guess"))[0] == 403
        s, j = c.post("/api/auth/setup", dict(A, code="secret-code-123"))
        assert s == 200 and j["data"]["appointments"] == []  # no sample patients on the live site
        assert c.post("/api/reset")[0] == 403
    finally:
        live.stop()


def test_medicine_finder(server):
    c = server.client()
    s, j = c.post("/api/medfind", {"name": "Dolo 650"})
    assert s == 200 and j["found"] and j["generic"] == "Paracetamol" and "janaushadhi" in j["links"]["janaushadhi"]
    s, j = c.post("/api/medfind", {"name": "Zzyzx-unknown"})
    assert s == 200 and j["found"] is False  # AI is off in tests: unknown names are not guessed
    assert c.post("/api/medfind", {"name": "x"})[0] == 400


def test_doctor_page_themes(server, uniq):
    doc = server.client()
    doc.signup("doctor", "Dr Theme", uniq())
    lid = doc.profile("Theme Clinic")
    assert b"#06080b" in server.client().get(f"/doctor/{lid}")[1]  # default: midnight
    assert doc.post("/api/m/page/theme", {"theme": "nope"})[0] == 400
    assert doc.post("/api/m/page/theme", {"theme": "warm"})[0] == 200
    body = server.client().get(f"/doctor/{lid}")[1]
    assert b"#fff8f1" in body and b"#06080b" not in body


def test_anonymous_visitor_stats(server, admin):
    a, b = server.client(), server.client()
    a.post("/api/hit", {"p": "home", "tz": "Asia/Kolkata", "w": 390, "ref": "https://www.linkedin.com/feed/"})
    a.post("/api/hit", {"p": "doctors", "tz": "Asia/Kolkata", "w": 390})  # same visitor, second page
    b.post("/api/hit", {"p": "home", "tz": "Europe/Berlin", "w": 1440, "app": 1})
    b.post("/api/hit", {"ev": "install"})
    v = admin.post("/api/stats/overview")[1]["created"]["visitors"]
    assert v["today"] >= 2 and v["views30"] >= 3 and v["installs30"] >= 1 and v["app_opens30"] >= 1
    assert {"key": "linkedin.com", "n": 1} in v["sources"]
    countries = {c["key"] for c in v["countries"]}
    assert {"IN", "DE"} <= countries or "??" in countries  # "??" only where the OS has no time-zone table
    rows = server.db().execute("SELECT * FROM visits").fetchall()
    assert not any("10." in str(tuple(r)) for r in rows)  # no IP addresses stored
    assert server.client().post("/api/stats/overview")[0] in (401, 403)

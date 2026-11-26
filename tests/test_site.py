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

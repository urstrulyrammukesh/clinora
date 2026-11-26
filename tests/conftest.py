"""Test helpers: every test session starts a real Clinora server on a free port with an empty, temporary database.

Run:  pip install -r requirements.txt pytest   then   pytest -q
"""
import http.cookiejar
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
# a tiny valid JPEG (8x8 white), so tests don't need an image library
JPEG_B64 = ("/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDABALDA4MChAODQ4SERATGCgaGBYWGDEjJR0oOjM9PDkzODdASFxOQERXRTc4UG1RV19iZ2hnPk1xeXBkeFxlZ2P/2wBDARESEhgVGC8aGi9jQjhCY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2NjY2P/wAARCAAIAAgDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwD0CiiigD//2Q==")
JPEG_DATA_URL = "data:image/jpeg;base64," + JPEG_B64


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    """A running Clinora server for tests."""

    def __init__(self, data_dir, env=None):
        self.port = free_port()
        self.data_dir = Path(data_dir)
        self.log = self.data_dir / "server.log"
        full_env = {k: v for k, v in os.environ.items() if not k.startswith(("ANTHROPIC", "SMTP", "STRIPE", "RAZORPAY", "PAYPAL", "BACKUP_S3"))}
        # TRUST_PROXY: each test "browser" sends its own X-Forwarded-For, like visitors behind Render's proxy
        full_env.update({"DATA_DIR": str(self.data_dir), "PORT": str(self.port), "PYTHONUNBUFFERED": "1", "TRUST_PROXY": "1"}, **(env or {}))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        # CLINORA_COVERAGE=1 measures which server lines the tests run (see .coveragerc and the Tests workflow)
        cmd = [sys.executable, "-m", "coverage", "run", "--parallel-mode", str(ROOT / "server.py")] \
            if os.environ.get("CLINORA_COVERAGE") == "1" else [sys.executable, str(ROOT / "server.py")]
        self.proc = subprocess.Popen(cmd, cwd=ROOT, env=full_env,
                                     stdout=open(self.log, "w"), stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                urllib.request.urlopen(f"{self.url}/api/status", timeout=1)
                return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("server did not start:\n" + self.log.read_text())

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def stop(self):
        self.proc.terminate()
        self.proc.wait(timeout=10)

    def db(self):
        c = sqlite3.connect(self.data_dir / "sehatdesk.db")
        c.row_factory = sqlite3.Row
        return c

    def logtext(self):
        return self.log.read_text()

    def client(self):
        return Client(self)


class Client:
    """One browser: keeps its own cookies."""

    _ip = [0]

    def __init__(self, server):
        self.s = server
        Client._ip[0] += 1
        self.ip = f"10.{Client._ip[0] // 65536 % 256}.{Client._ip[0] // 256 % 256}.{Client._ip[0] % 256}"
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def post(self, path, data=None):
        req = urllib.request.Request(self.s.url + path, json.dumps(data or {}).encode(),
                                     {"Content-Type": "application/json", "Origin": self.s.url, "X-Forwarded-For": self.ip})
        try:
            r = self.opener.open(req)
            return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read() or b"{}")

    def get(self, path, headers=None):
        req = urllib.request.Request(self.s.url + path, headers=dict(headers or {}, **{"X-Forwarded-For": self.ip}))
        try:
            r = self.opener.open(req)
            return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def signup(self, kind, name, email, confirm=True, password="Pass123456!"):
        s, j = self.post("/api/m/signup", {"kind": kind, "name": name, "email": email, "password": password, "agree": True})
        assert s == 200, j
        if confirm:
            with self.s.db() as c:
                c.execute("UPDATE members SET email_ok=1 WHERE email=?", (email.lower(),))
        return j["me"]["id"]

    def profile(self, name="Test Clinic"):
        s, j = self.post("/api/m/profile", {"name": name, "type": "doctors", "spec": "GP", "phone": "+919999999999", "addr": "Main road",
                                            "city": "Srinagar", "country": "India", "cc": "IN", "lat": 34.08, "lon": 74.8})
        assert s == 200, j
        return j["me"]["listing_id"]


@pytest.fixture(scope="session")
def server(tmp_path_factory):
    srv = Server(tmp_path_factory.mktemp("clinora"))
    yield srv
    srv.stop()


@pytest.fixture(scope="session")
def admin(server):
    a = server.client()
    s, j = a.post("/api/auth/setup", {"name": "Admin", "email": "admin@test.in", "password": "Adminpass123"})
    assert s == 200, j
    return a


_n = [0]


@pytest.fixture
def uniq():
    """A fresh email each time, so tests don't clash."""
    def make(prefix="u"):
        _n[0] += 1
        return f"{prefix}{_n[0]}-{time.time_ns()}@test.in"
    return make

"""Phone notifications: a fake push service receives the alert; we decrypt it like a phone would."""
import base64
import http.server
import json
import os
import threading
import time

import pytest

http_ece = pytest.importorskip("http_ece")
from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import ec  # noqa: E402


def test_push_delivered_encrypted_and_cleaned_up(server, uniq):
    got, status = [], {"code": 201}

    class PushService(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            got.append(({k.lower(): v for k, v in self.headers.items()}, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(status["code"])
            self.end_headers()

        def log_message(self, *a):
            pass

    svc = http.server.HTTPServer(("127.0.0.1", 0), PushService)
    threading.Thread(target=svc.serve_forever, daemon=True).start()
    doc, pat = server.client(), server.client()
    did = doc.signup("doctor", "Dr Push", uniq())
    lid = doc.profile("Push Clinic")
    pat.signup("patient", "Asha", uniq())
    assert doc.post("/api/m/me")[1]["push_key"]
    assert doc.post("/api/m/push/subscribe", {"endpoint": "http://evil", "keys": {}})[0] == 400
    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    auth = os.urandom(16)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    assert doc.post("/api/m/push/subscribe", {"endpoint": "https://push.example/x", "keys": {"p256dh": b64(pub), "auth": b64(auth)}})[0] == 200
    with server.db() as c:  # point the subscription at our fake push service
        c.execute("UPDATE push_subs SET endpoint=? WHERE member_id=?", (f"http://127.0.0.1:{svc.server_port}/sub", did))
    pat.post("/api/m/send", {"listing_id": lid, "body": "Is tomorrow ok?"})
    for _ in range(50):
        if got:
            break
        time.sleep(0.1)
    headers, body = got[0]
    assert headers["authorization"].startswith("vapid t=")
    msg = json.loads(http_ece.decrypt(body, private_key=key, auth_secret=auth, version="aes128gcm"))
    assert msg["title"].startswith("New message from Asha") and "tomorrow" in msg["body"]
    status["code"] = 410  # the phone unsubscribed
    pat.post("/api/m/send", {"listing_id": lid, "body": "second"})
    for _ in range(50):
        with server.db() as c:
            if not c.execute("SELECT COUNT(*) FROM push_subs WHERE member_id=?", (did,)).fetchone()[0]:
                break
        time.sleep(0.1)
    else:
        raise AssertionError("expired subscription was not removed")
    svc.shutdown()

"""WhatsApp assistant: Meta's webhook handshake, signed messages, and the reply (with the AI off, the keyword menu)."""
import hashlib
import hmac
import http.server
import json
import threading
import time
import urllib.error
import urllib.request

from conftest import Server


def test_whatsapp_webhook(tmp_path):
    sent = []

    class Graph(http.server.BaseHTTPRequestHandler):  # stands in for graph.facebook.com
        def do_POST(self):
            sent.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"messages":[{"id":"wamid.1"}]}')

        def log_message(self, *a):
            pass

    graph = http.server.HTTPServer(("127.0.0.1", 0), Graph)
    threading.Thread(target=graph.serve_forever, daemon=True).start()
    srv = Server(tmp_path / "wa", {"WHATSAPP_TOKEN": "tok", "WHATSAPP_PHONE_ID": "123", "WHATSAPP_VERIFY_TOKEN": "verify-me",
                                   "WHATSAPP_APP_SECRET": "app-secret", "WHATSAPP_API_BASE": f"http://127.0.0.1:{graph.server_port}"})
    try:
        doc = srv.client()
        doc.signup("doctor", "Dr Wa", "wa-doc@test.in")
        doc.profile("Smile Dental Care")
        # Meta's one-time handshake
        assert srv.client().get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=verify-me&hub.challenge=abc123")[1] == b"abc123"
        assert srv.client().get("/api/whatsapp/webhook?hub.mode=subscribe&hub.verify_token=wrong&hub.challenge=x")[0] == 403

        def deliver(text, mid, secret="app-secret"):
            body = json.dumps({"entry": [{"changes": [{"value": {"messages": [{"id": mid, "from": "919800000001", "type": "text",
                                                                                 "text": {"body": text}}]}}]}]}).encode()
            sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
            req = urllib.request.Request(srv.url + "/api/whatsapp/webhook", body, {"Content-Type": "application/json", "X-Hub-Signature-256": sig})
            try:
                return urllib.request.urlopen(req).status
            except urllib.error.HTTPError as e:
                return e.code

        assert deliver("hi", "m0", secret="wrong") == 403
        assert deliver("doctor smile srinagar", "m1") == 200
        assert deliver("doctor smile srinagar", "m1") == 200  # Meta retries: answered once
        for _ in range(50):
            if sent:
                break
            time.sleep(0.1)
        time.sleep(0.5)
        assert len(sent) == 1
        path, auth, msg = sent[0]
        assert path == "/123/messages" and auth == "Bearer tok" and msg["to"] == "919800000001"
        assert "Smile Dental Care" in msg["text"]["body"] and "/doctor/" in msg["text"]["body"]
        deliver("I have chest pain", "m2")
        for _ in range(50):
            if len(sent) > 1:
                break
            time.sleep(0.1)
        assert "112" in sent[1][2]["text"]["body"]
    finally:
        srv.stop()
        graph.shutdown()

"""Free hosting starts every deploy with an empty disk. With cloud backups set up, Clinora saves a last backup
when the host stops it (SIGTERM) and brings the newest one back when it starts on an empty disk."""
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from conftest import Server, free_port


class FakeS3(BaseHTTPRequestHandler):
    """Just enough of the S3 API: PUT an object, list by prefix, GET an object."""
    store = {}

    def log_message(self, *a):
        pass

    def _key(self):
        return self.path.split("?")[0].split("/", 2)[2] if self.path.count("/") >= 2 else ""

    def do_PUT(self):
        assert self.headers["Authorization"].startswith("AWS4-HMAC-SHA256 Credential=testkey/")
        self.store[self._key()] = self.rfile.read(int(self.headers["Content-Length"]))
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        assert "Signature=" in self.headers["Authorization"]
        if "list-type=2" in self.path:
            prefix = re.search(r"prefix=([^&]+)", self.path).group(1).replace("%2F", "/")
            keys = "".join(f"<Contents><Key>{k}</Key></Contents>" for k in self.store if k.startswith(prefix))
            body = f"<ListBucketResult>{keys}</ListBucketResult>".encode()
        elif self._key() in self.store:
            body = self.store[self._key()]
        else:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_backup_on_shutdown_and_restore_on_empty_disk(tmp_path, uniq):
    port = free_port()
    s3 = ThreadingHTTPServer(("127.0.0.1", port), FakeS3)
    threading.Thread(target=s3.serve_forever, daemon=True).start()
    env = {"BACKUP_S3_ENDPOINT": f"http://127.0.0.1:{port}", "BACKUP_S3_BUCKET": "clinora",
           "BACKUP_S3_KEY_ID": "testkey", "BACKUP_S3_SECRET": "testsecret"}
    try:
        first = Server(tmp_path / "deploy1", env)
        email = uniq()
        first.client().signup("patient", "Kept Patient", email)
        first.stop()  # the host stops the server (SIGTERM) -> last backup goes to the cloud
        assert any(k.startswith("clinora-backups/clinora-") for k in FakeS3.store), first.logtext()

        second = Server(tmp_path / "deploy2", env)  # new deploy, empty disk
        try:
            assert "brought back" in second.logtext()
            row = second.db().execute("SELECT name FROM members WHERE email=?", (email.lower(),)).fetchone()
            assert row and row["name"] == "Kept Patient"
        finally:
            second.stop()
    finally:
        s3.shutdown()

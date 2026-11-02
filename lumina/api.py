"""HTTP ingest endpoint that n8n workflows call. Stdlib only, local use only (no auth)."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from lumina import kb

MAX_BODY = 1_000_000


def make_server(host, port, db_path, profile):
    db = kb.connect(db_path)
    write_lock = threading.Lock()  # one shared connection, so writes are serialized

    class Handler(BaseHTTPRequestHandler):
        timeout = 10

        def _send(self, code, payload):
            data = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/health":
                with write_lock:
                    self._send(200, {"status": "ok", **kb.stats(db)})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/ingest":
                return self._send(404, {"error": "not found"})
            # Requiring JSON forces a CORS preflight, so a web page cannot post here from a browser.
            if self.headers.get_content_type() != "application/json":
                return self._send(415, {"error": "Content-Type must be application/json"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "bad Content-Length"})
            if length < 0:
                return self._send(400, {"error": "bad Content-Length"})
            if length > MAX_BODY:
                return self._send(413, {"error": "payload too large"})
            try:
                items = json.loads(self.rfile.read(length))["items"]
                if not isinstance(items, list):
                    raise TypeError
                with write_lock:
                    report = kb.triage(db, items, profile)
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {"error": f"bad payload: {e}"})
            except NotImplementedError as e:
                return self._send(502, {"error": str(e)})
            self._send(200, report)

        def log_message(self, *args):
            pass

    return ThreadingHTTPServer((host, port), Handler)

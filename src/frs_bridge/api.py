"""Read-only loopback event API. No recording or embedding download endpoints."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from urllib.parse import parse_qs, urlparse


def server(store, port=8765):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            url = urlparse(self.path)
            status = 200
            if url.path == "/health":
                body = {"ok": True, "schema": "frs-bridge.event.v1"}
            elif url.path == "/events":
                try:
                    query = parse_qs(url.query)
                    after = int(query.get("after", ["0"])[0])
                    limit = int(query.get("limit", ["100"])[0])
                    if after < 0 or not 1 <= limit <= 1000:
                        raise ValueError()
                    rows = store.events(after, limit)
                    body = {"events": rows, "next_after": rows[-1]["id"] if rows else after}
                except ValueError:
                    status, body = 400, {"error": "after must be nonnegative; limit must be 1..1000"}
            else:
                status, body = 404, {"error": "not found"}
            payload = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_):
            pass
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)

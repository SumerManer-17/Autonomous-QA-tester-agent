"""DemoShop / Hotel Booking Demo application server.

A tiny, single-file static file server for the local demo website.
Intended to run on http://localhost:3000 (or another port) so the
Autonomous QA Testing Agent has a real, local target to explore and test.

No external dependencies: uses only the Python standard library.

Defect control endpoint (demo only):
  GET    /__demo/defects   -> JSON list of enabled defect keys
  POST   /__demo/defects   -> JSON body {"defects": [...]} to enable defects
These let the QA agent enable injected defects deterministically for a demo
run, independent of any browser localStorage.
"""

from __future__ import annotations

import http.server
import json
import os
import socketserver
import sys
from typing import Optional
from urllib.parse import urlparse

DEFAULT_PORT = 3000

DEFECT_KEYS = [
    "invalid_email_accepted",
    "incorrect_login_error",
    "filter_ignored",
    "invalid_date_range_accepted",
    "no_confirmation",
]

# Server-side defect state (demo control endpoint only).
ENABLED_DEFECTS: list[str] = []


class DemoHandler(http.server.SimpleHTTPRequestHandler):
    """Serves files from the directory this script lives in."""

    def __init__(self, *args, directory: Optional[str] = None, **kwargs):
        super().__init__(*args, directory=directory, **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    def _send_json(self, status: int, body: dict | list) -> None:
        payload = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/__demo/defects":
            self._send_json(200, list(ENABLED_DEFECTS))
            return
        return super().do_GET()

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/__demo/defects":
            try:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                data = json.loads(raw.decode("utf-8") or "{}")
                defects = data.get("defects", [])
                if not isinstance(defects, list):
                    raise ValueError("defects must be a list")
                global ENABLED_DEFECTS
                ENABLED_DEFECTS = [d for d in defects if d in DEFECT_KEYS]
                self._send_json(200, {"defects": ENABLED_DEFECTS})
            except Exception as exc:
                self._send_json(400, {"error": str(exc)})
            return
        self._send_json(404, {"error": "not found"})

    def log_message(self, fmt, *args):  # pragma: no cover - demo logging only
        sys.stdout.write(f"{self.address_string()} - {fmt % args}\n")


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PORT
    directory = os.path.dirname(os.path.abspath(__file__))

    handler = lambda *args, **kwargs: DemoHandler(*args, directory=directory, **kwargs)
    with socketserver.TCPServer(("", port), handler) as httpd:
        httpd.allow_reuse_address = True
        print(f"DemoShop / Hotel Booking Demo serving at http://localhost:{port}")
        print(f"Serving directory: {directory}")
        print(f"Defect control: GET/POST http://localhost:{port}/__demo/defects")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down demo server.")
            httpd.server_close()


if __name__ == "__main__":
    main()

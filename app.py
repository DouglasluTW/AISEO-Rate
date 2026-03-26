#!/usr/bin/env python3
"""Local web UI for the AEO scorer."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from aeo_score import score_target


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
HOST = os.getenv("HOST", "127.0.0.1")
PORT = int(os.getenv("PORT", "8000"))


class AppHandler(BaseHTTPRequestHandler):
    server_version = "AEOScoreHTTP/0.1"

    def do_GET(self) -> None:
        if self.path == "/":
            self._serve_file(WEB_DIR / "index.html")
            return
        if self.path.startswith("/assets/"):
            relative_path = self.path.removeprefix("/assets/")
            self._serve_file(WEB_DIR / relative_path)
            return
        self._json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path != "/api/score":
            self._json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._json_response({"error": "Invalid content length"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json_response({"error": "Invalid JSON body"}, HTTPStatus.BAD_REQUEST)
            return

        url = str(payload.get("url", "")).strip()
        if not url:
            self._json_response({"error": "URL is required"}, HTTPStatus.BAD_REQUEST)
            return
        if not self._is_valid_url(url):
            self._json_response({"error": "Enter a valid http or https URL"}, HTTPStatus.BAD_REQUEST)
            return

        try:
            result = score_target(url=url)
            self._json_response(result, HTTPStatus.OK)
        except Exception as exc:
            self._json_response(
                {"error": str(exc)},
                HTTPStatus.BAD_GATEWAY,
            )

    def log_message(self, fmt: str, *args: object) -> None:
        sys.stdout.write("%s - - [%s] %s\n" % (self.address_string(), self.log_date_time_string(), fmt % args))

    def _serve_file(self, file_path: Path) -> None:
        if not file_path.exists() or not file_path.is_file():
            self._json_response({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return

        content_type, _ = mimetypes.guess_type(file_path.name)
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _json_response(self, payload: dict[str, object], status: HTTPStatus) -> None:
        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    @staticmethod
    def _is_valid_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def main() -> int:
    server = ThreadingHTTPServer((HOST, PORT), AppHandler)
    print(f"AEO Score UI running at http://{HOST}:{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

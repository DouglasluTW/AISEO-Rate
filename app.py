#!/usr/bin/env python3
"""Local web UI for the AEO scorer."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import threading
from collections import Counter
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from aeo_score import score_target


BASE_DIR = Path(__file__).resolve().parent
WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
STATS_PATH = DATA_DIR / "usage_stats.json"
HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
RECENT_EVENT_LIMIT = 100
RECENT_DOMAIN_WINDOW = 50
STATS_LOCK = threading.Lock()


def default_stats() -> dict[str, object]:
    return {
        "total_visits": 0,
        "total_scores": 0,
        "score_successes": 0,
        "score_failures": 0,
        "recent_score_events": [],
    }


def load_stats_locked() -> dict[str, object]:
    if not STATS_PATH.exists():
        return default_stats()

    try:
        payload = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return default_stats()

    stats = default_stats()
    stats["total_visits"] = int(payload.get("total_visits", 0))
    stats["total_scores"] = int(payload.get("total_scores", 0))
    stats["score_successes"] = int(payload.get("score_successes", 0))
    stats["score_failures"] = int(payload.get("score_failures", 0))
    events = payload.get("recent_score_events", [])
    if isinstance(events, list):
        stats["recent_score_events"] = [
            {"domain": str(item.get("domain", "")).strip(), "success": bool(item.get("success", False))}
            for item in events
            if isinstance(item, dict)
        ][-RECENT_EVENT_LIMIT:]
    return stats


def save_stats_locked(stats: dict[str, object]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    serializable = {
        "total_visits": int(stats.get("total_visits", 0)),
        "total_scores": int(stats.get("total_scores", 0)),
        "score_successes": int(stats.get("score_successes", 0)),
        "score_failures": int(stats.get("score_failures", 0)),
        "recent_score_events": list(stats.get("recent_score_events", []))[-RECENT_EVENT_LIMIT:],
    }
    temp_path = STATS_PATH.with_suffix(".tmp")
    temp_path.write_text(json.dumps(serializable, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(STATS_PATH)


def update_stats(mutator) -> dict[str, object]:
    with STATS_LOCK:
        stats = load_stats_locked()
        mutator(stats)
        save_stats_locked(stats)
        return build_public_stats(stats)


def build_public_stats(stats: dict[str, object]) -> dict[str, object]:
    recent_events = list(stats.get("recent_score_events", []))[-RECENT_DOMAIN_WINDOW:]
    counts = Counter(event.get("domain", "") for event in recent_events if event.get("domain"))
    recent_domains = [
        {"domain": domain, "count": count}
        for domain, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    return {
        "total_visits": int(stats.get("total_visits", 0)),
        "total_scores": int(stats.get("total_scores", 0)),
        "score_successes": int(stats.get("score_successes", 0)),
        "score_failures": int(stats.get("score_failures", 0)),
        "recent_domain_window": len(recent_events),
        "recent_domains": recent_domains[:8],
    }


def get_public_stats() -> dict[str, object]:
    with STATS_LOCK:
        return build_public_stats(load_stats_locked())


def record_visit() -> dict[str, object]:
    return update_stats(lambda stats: stats.__setitem__("total_visits", int(stats["total_visits"]) + 1))


def record_score(domain: str, *, success: bool) -> dict[str, object]:
    def mutator(stats: dict[str, object]) -> None:
        stats["total_scores"] = int(stats["total_scores"]) + 1
        if success:
            stats["score_successes"] = int(stats["score_successes"]) + 1
        else:
            stats["score_failures"] = int(stats["score_failures"]) + 1
        events = list(stats.get("recent_score_events", []))
        events.append({"domain": domain, "success": success})
        stats["recent_score_events"] = events[-RECENT_EVENT_LIMIT:]

    return update_stats(mutator)


def extract_domain(value: str) -> str:
    return (urlparse(value).netloc or "").lower()


class AppHandler(BaseHTTPRequestHandler):
    server_version = "AEOScoreHTTP/0.1"

    def do_GET(self) -> None:
        if self.path == "/":
            record_visit()
            self._serve_file(WEB_DIR / "index.html")
            return
        if self.path == "/api/stats":
            self._json_response(get_public_stats(), HTTPStatus.OK)
            return
        if self.path == "/mosquito":
            self._serve_file(WEB_DIR / "mosquito.html")
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
            self._json_response({"error": "請輸入網址。"}, HTTPStatus.BAD_REQUEST)
            return
        if not self._is_valid_url(url):
            self._json_response({"error": "請輸入有效的 http 或 https 網址。"}, HTTPStatus.BAD_REQUEST)
            return

        domain = extract_domain(url)
        try:
            result = score_target(url=url)
            record_score(domain, success=True)
            self._json_response(result, HTTPStatus.OK)
        except Exception as exc:
            record_score(domain, success=False)
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

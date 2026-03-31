"""
Vercel serverless entry: one poll cycle, state in Upstash Redis.
Trigger with GET or POST and Authorization: Bearer <CRON_SECRET> or X-Cron-Secret.
"""
from __future__ import annotations

import hmac
import json
import os
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from upstash_redis import Redis

from poll_once import run_poll_cycle

_ROOT = Path(__file__).resolve().parent.parent
_PLAYER_CACHE = _ROOT / "player_cache.json"
_REDIS_KEY = os.getenv("UPSTASH_SEEN_KEY", "espn_drop_bot:seen_json")
# Stay under Vercel Hobby ~10s function limit; tune if you upgrade Pro.
_FETCH_TIMEOUT = int(os.getenv("ESPN_FETCH_TIMEOUT_SEC", "8"))


def _redis_client() -> Redis:
    url = os.getenv("UPSTASH_REDIS_REST_URL", "").strip()
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "").strip()
    if not url or not token:
        raise RuntimeError(
            "UPSTASH_REDIS_REST_URL and UPSTASH_REDIS_REST_TOKEN must be set"
        )
    return Redis(url=url, token=token)


def _load_seen(r: Redis) -> set[str]:
    raw = r.get(_REDIS_KEY)
    if not raw:
        return set()
    try:
        data = json.loads(raw)
        ids = data.get("transaction_ids")
        if not isinstance(ids, list):
            return set()
        return {str(x) for x in ids}
    except (json.JSONDecodeError, TypeError):
        return set()


def _save_seen(r: Redis, seen: set[str]) -> None:
    r.set(_REDIS_KEY, json.dumps({"transaction_ids": sorted(seen)}))


def _authorized(req: BaseHTTPRequestHandler) -> bool:
    expected = os.getenv("CRON_SECRET", "").strip()
    if not expected:
        return False
    auth = req.headers.get("Authorization") or ""
    if auth.startswith("Bearer "):
        got = auth[7:].strip()
        return hmac.compare_digest(got, expected)
    x = (req.headers.get("X-Cron-Secret") or "").strip()
    if x:
        return hmac.compare_digest(x, expected)
    return False


class handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self) -> None:  # noqa: N802
        self._handle()

    def do_POST(self) -> None:  # noqa: N802
        self._handle()

    def _handle(self) -> None:
        if not _authorized(self):
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        try:
            r = _redis_client()
        except RuntimeError as e:
            self._json(500, {"ok": False, "error": str(e)})
            return

        seen = _load_seen(r)

        def persist(new_seen: set[str]) -> None:
            _save_seen(r, new_seen)

        try:
            result = run_poll_cycle(
                seen=seen,
                save_seen=persist,
                player_cache_path=_PLAYER_CACHE,
                fetch_timeout=_FETCH_TIMEOUT,
            )
        except Exception as e:  # noqa: BLE001
            self._json(500, {"ok": False, "error": str(e)})
            return

        # 200 even when ESPN fails so GitHub Actions cron does not show a failed run by default.
        self._json(200, result)

    def _json(self, status: int, body: object) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

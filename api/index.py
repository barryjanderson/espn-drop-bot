"""
Vercel Python WSGI entrypoint.

Vercel's current Python runtime detects an `app` callable in recognized
entrypoint filenames (such as api/index.py).
"""

from __future__ import annotations

import hmac
import json
import os
from pathlib import Path
from typing import Any

from upstash_redis import Redis

from poll_once import run_poll_cycle

_ROOT = Path(__file__).resolve().parent.parent
_PLAYER_CACHE = _ROOT / "player_cache.json"
_REDIS_KEY = os.getenv("UPSTASH_SEEN_KEY", "espn_drop_bot:seen_json")
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


def _authorized(auth_header: str, cron_header: str) -> bool:
    expected = os.getenv("CRON_SECRET", "").strip()
    if not expected:
        return False
    if auth_header.startswith("Bearer "):
        got = auth_header[7:].strip()
        return hmac.compare_digest(got, expected)
    if cron_header:
        return hmac.compare_digest(cron_header, expected)
    return False


def _json_response(status: int, body: dict[str, Any]) -> tuple[str, list[tuple[str, str]], bytes]:
    raw = json.dumps(body).encode("utf-8")
    status_line = f"{status} {'OK' if status < 400 else 'ERROR'}"
    headers = [
        ("Content-Type", "application/json; charset=utf-8"),
        ("Content-Length", str(len(raw))),
    ]
    return status_line, headers, raw


def app(environ: dict[str, Any], start_response: Any) -> list[bytes]:
    auth = (environ.get("HTTP_AUTHORIZATION") or "").strip()
    x_secret = (environ.get("HTTP_X_CRON_SECRET") or "").strip()
    if not _authorized(auth, x_secret):
        status, headers, raw = _json_response(401, {"ok": False, "error": "unauthorized"})
        start_response(status, headers)
        return [raw]

    try:
        r = _redis_client()
        seen = _load_seen(r)

        def persist(new_seen: set[str]) -> None:
            _save_seen(r, new_seen)

        result = run_poll_cycle(
            seen=seen,
            save_seen=persist,
            player_cache_path=_PLAYER_CACHE,
            fetch_timeout=_FETCH_TIMEOUT,
        )
        status, headers, raw = _json_response(200, result)
        start_response(status, headers)
        return [raw]
    except Exception as e:  # noqa: BLE001
        status, headers, raw = _json_response(500, {"ok": False, "error": str(e)})
        start_response(status, headers)
        return [raw]

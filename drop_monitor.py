#!/usr/bin/env python3
"""
Poll ESPN Fantasy transactions every 5 minutes; notify Discord on new drops.
State: seen_transactions.json (gitignored). Configure via .env (see .env.example).
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from espn_client import get_env_required
from poll_once import run_poll_cycle

_PROJECT_ROOT = Path(__file__).resolve().parent
PLAYER_CACHE_PATH = _PROJECT_ROOT / "player_cache.json"

POLL_INTERVAL_SEC = int(os.getenv("POLL_INTERVAL_SEC", "300"))
STATE_PATH = os.getenv("STATE_PATH", "seen_transactions.json")


def load_player_cache(path: Path) -> dict[int, str]:
    if not path.is_file():
        print(
            f"[warn] {path.name} not found — player names will fall back to IDs. "
            "Run `python fetch_player_cache.py` to generate it.",
            file=sys.stderr,
        )
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw: dict[str, str] = json.load(f)
        return {int(k): v for k, v in raw.items()}
    except (json.JSONDecodeError, OSError, ValueError) as e:
        print(f"[warn] Could not load player cache: {e}", file=sys.stderr)
        return {}


def load_seen(path: str) -> set[str]:
    if not os.path.isfile(path):
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return set()
    ids = data.get("transaction_ids")
    if not isinstance(ids, list):
        return set()
    return {str(x) for x in ids}


def save_seen(path: str, seen: set[str]) -> None:
    payload = {"transaction_ids": sorted(seen)}
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
    os.replace(tmp, path)


def discord_webhook_url() -> str:
    return get_env_required("DISCORD_WEBHOOK_URL")


def loop() -> None:
    _ = discord_webhook_url()
    player_cache = load_player_cache(PLAYER_CACHE_PATH)
    if player_cache:
        print(f"Loaded {len(player_cache)} players from {PLAYER_CACHE_PATH.name}")
    seen = load_seen(STATE_PATH)
    print(f"Loaded {len(seen)} known transaction ids from {STATE_PATH}")
    print(f"Polling every {POLL_INTERVAL_SEC}s...")

    state: dict[str, Any] = {"seen": seen}

    def persist(new_seen: set[str]) -> None:
        save_seen(STATE_PATH, new_seen)
        state["seen"] = new_seen

    while True:
        result = run_poll_cycle(
            seen=state["seen"],
            save_seen=persist,
            player_cache_path=PLAYER_CACHE_PATH,
            fetch_timeout=30,
        )
        if not result.get("ok"):
            err = result.get("error", "unknown")
            print(f"Poll error: {err}")
            if result.get("body_preview"):
                print(str(result["body_preview"])[:500])
        else:
            if result.get("seeded"):
                print(
                    f"Seed: marked {result.get('seeded_count', 0)} historical drop txs as seen "
                    "(no Discord). Set SEED_ON_FIRST_RUN=0 to skip this."
                )
            elif result.get("notified", 0):
                print(f"Notified on {result['notified']} new drop(s).")

        time.sleep(POLL_INTERVAL_SEC)


def main() -> None:
    try:
        loop()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

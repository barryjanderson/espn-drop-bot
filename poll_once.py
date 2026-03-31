"""
Single ESPN poll + drop processing. Used by drop_monitor.py (loop) and api/monitor.py (serverless).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Callable

import requests

from espn_client import fetch_league_json_from_env, get_env_required
from transaction_utils import (
    build_team_map,
    is_drop_transaction,
    iter_dropped_players,
    player_label_from_item,
    team_name,
)


def load_player_cache(path: Path) -> dict[int, str]:
    if not path.is_file():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw: dict[str, str] = json.load(f)
        return {int(k): v for k, v in raw.items()}
    except (json.JSONDecodeError, OSError, ValueError):
        return {}


def notify_discord(
    webhook_url: str,
    *,
    team: str,
    players: list[str],
    tx_id: str,
    tx_date: Any,
) -> None:
    player_str = ", ".join(players)
    desc_lines = [f"**Team:** {team}"]
    if tx_date is not None:
        desc_lines.append(f"**When:** {tx_date}")
    body = {
        "embeds": [
            {
                "title": f"{player_str} dropped",
                "description": "\n".join(desc_lines),
                "color": 15158332,
                "footer": {"text": f"transaction id {tx_id}"},
            }
        ]
    }
    r = requests.post(webhook_url, json=body, timeout=15)
    r.raise_for_status()


def seed_existing_drop_ids(data: dict[str, Any], seen: set[str]) -> set[str]:
    new_seen = set(seen)
    for tx in data.get("transactions") or []:
        if not isinstance(tx, dict) or not is_drop_transaction(tx):
            continue
        tx_id = tx.get("id")
        if tx_id is None:
            continue
        new_seen.add(str(tx_id))
    return new_seen


def process_payload(
    data: dict[str, Any],
    seen: set[str],
    webhook_url: str,
    player_cache: dict[int, str],
) -> set[str]:
    team_map = build_team_map(data)
    transactions = data.get("transactions") or []
    new_seen = set(seen)

    for tx in transactions:
        if not isinstance(tx, dict):
            continue
        if not is_drop_transaction(tx):
            continue
        tx_id = tx.get("id")
        if tx_id is None:
            continue
        key = str(tx_id)
        if key in new_seen:
            continue

        team_id = tx.get("teamId")
        team_id_int: int | None = None
        if team_id is not None:
            try:
                team_id_int = int(team_id)
            except (TypeError, ValueError):
                pass
        tname = team_name(team_map, team_id_int)

        players = [
            player_label_from_item(i, player_cache) for i in iter_dropped_players(tx)
        ]
        if not players:
            players = ["(drop detected; no player label in payload)"]

        print(f"[notify] new drop tx={key} team={tname} players={players}")
        notify_discord(
            webhook_url,
            team=tname,
            players=players,
            tx_id=key,
            tx_date=tx.get("date") or tx.get("processDate"),
        )
        new_seen.add(key)

    return new_seen


def seed_on_first_run_enabled() -> bool:
    return os.getenv("SEED_ON_FIRST_RUN", "1").strip() in ("1", "true", "yes")


def run_poll_cycle(
    *,
    seen: set[str],
    save_seen: Callable[[set[str]], None],
    player_cache_path: Path,
    fetch_timeout: int = 30,
) -> dict[str, Any]:
    """
    One ESPN fetch; updates seen via save_seen when the response is usable JSON.
    Returns a small dict for logging/API responses.
    """
    webhook_url = get_env_required("DISCORD_WEBHOOK_URL")
    player_cache = load_player_cache(player_cache_path)
    initial_seed_pending = seed_on_first_run_enabled() and len(seen) == 0
    notified = 0
    seeded_count = 0

    try:
        status, body = fetch_league_json_from_env(timeout=fetch_timeout)
    except RuntimeError as e:
        return {"ok": False, "error": str(e), "http_status": None}

    if status != 200:
        return {
            "ok": False,
            "error": f"ESPN HTTP {status}",
            "http_status": status,
            "body_preview": str(body)[:500] if body else "",
        }

    if not isinstance(body, dict):
        return {
            "ok": False,
            "error": "ESPN response is not a JSON object",
            "http_status": status,
        }

    if initial_seed_pending:
        n_before = len(seen)
        seen = seed_existing_drop_ids(body, seen)
        seeded_count = len(seen) - n_before
        save_seen(seen)
        return {
            "ok": True,
            "seeded": True,
            "seeded_count": seeded_count,
            "seen_total": len(seen),
            "http_status": status,
        }

    before = len(seen)
    seen = process_payload(body, seen, webhook_url, player_cache)
    notified = len(seen) - before
    save_seen(seen)
    return {
        "ok": True,
        "seeded": False,
        "notified": notified,
        "seen_total": len(seen),
        "http_status": status,
    }

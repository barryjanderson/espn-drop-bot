#!/usr/bin/env python3
"""
One-time script: fetch all active MLB players from ESPN and write player_cache.json.

Run once (or whenever you want to refresh):
    python fetch_player_cache.py

Output: player_cache.json  — { "playerId": "Full Name", ... }
drop_monitor.py loads this at startup for player name lookups.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

import requests
from espn_client import (
    _api_base,
    build_headers,
    get_espn_credentials,
    _parse_response_json,
)

CACHE_PATH = Path(__file__).resolve().parent / "player_cache.json"


def fetch_all_players() -> dict[int, str]:
    league_id, espn_s2, swid, season = get_espn_credentials()

    # Season-level endpoint (not league-scoped) — matches espn-api's get_pro_players() pattern.
    url = f"{_api_base()}/flb/seasons/{season}/players"
    params = {"view": "players_wl"}
    headers = build_headers(league_id)
    # filterActive limits to active players (smaller payload, all we need for name lookups)
    headers["x-fantasy-filter"] = json.dumps({"filterActive": {"value": True}})
    cookies = {"espn_s2": espn_s2, "SWID": swid}

    print(f"Fetching player list from:\n  {url}")
    r = requests.get(url, params=params, headers=headers, cookies=cookies, timeout=60)

    if r.status_code != 200:
        print(f"Error HTTP {r.status_code}: {r.text[:500]}", file=sys.stderr)
        sys.exit(1)

    data = _parse_response_json(r)
    if data is None:
        print("Unexpected response (not JSON):", r.text[:500], file=sys.stderr)
        sys.exit(1)

    # Response is a list of player pool entries when using players_wl
    entries = data if isinstance(data, list) else data.get("players") or []
    player_map: dict[int, str] = {}

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # Each entry has either top-level `id` + nested `player`, or is a playerPoolEntry dict
        player_info = entry.get("player") or entry.get("onTeamInfo") or {}
        pid = entry.get("id") or entry.get("playerId")
        name = player_info.get("fullName") or entry.get("fullName")
        if pid is not None and name:
            player_map[int(pid)] = str(name)

    return player_map


def main() -> None:
    player_map = fetch_all_players()
    if not player_map:
        print("Warning: got 0 players — check credentials and season.", file=sys.stderr)
        sys.exit(1)

    out: dict[str, str] = {str(k): v for k, v in sorted(player_map.items())}
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)

    print(f"Saved {len(out)} players to {CACHE_PATH}")


if __name__ == "__main__":
    main()

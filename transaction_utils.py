"""
ESPN Fantasy transaction helpers.

The private API returns `transactions` with `items` describing roster moves.
Drop detection: any item with `type` \"DROP\" or \"DROPPED\" (case-insensitive),
or numeric item types 2 / 5 seen in some FLB payloads for releases.

Refine using `test_espn.py` sample output if your league differs.
"""
from __future__ import annotations

from typing import Any, Iterator

_ITEM_DROP_STRINGS = frozenset({"DROP", "DROPPED"})
# Top-level transaction `type` for pickups / waivers (usually includes ADD + optional DROP items).
_WAIVER_FA_TOP_LEVEL = frozenset({"FREEAGENT", "WAIVER", "WAIVER_ERROR"})
# Observed numeric codes on *items* in some ESPN responses (sport/version dependent).
_ITEM_DROP_NUMERIC = frozenset({2, 5})


def _normalize_item_type(item: dict[str, Any]) -> tuple[str | None, int | None]:
    t = item.get("type")
    if isinstance(t, str):
        return t.upper(), None
    if isinstance(t, int):
        return None, t
    if isinstance(t, float) and t == int(t):
        return None, int(t)
    return None, None


def transaction_items(tx: dict[str, Any]) -> list[dict[str, Any]]:
    items = tx.get("items")
    if not items:
        return []
    return [x for x in items if isinstance(x, dict)]


def is_waiver_or_freeagent_transaction(tx: dict[str, Any]) -> bool:
    """True if ESPN classifies this row as FA / waiver activity (not a pure lineup slot shuffle)."""
    t = tx.get("type")
    return isinstance(t, str) and t.upper() in _WAIVER_FA_TOP_LEVEL


def is_lineup_only_transaction(tx: dict[str, Any]) -> bool:
    """True when every item is LINEUP (bench ↔ slot moves); not a waiver drop."""
    items = transaction_items(tx)
    if not items:
        return False
    for item in items:
        s, _ = _normalize_item_type(item)
        if s != "LINEUP":
            return False
    return True


def is_drop_transaction(tx: dict[str, Any]) -> bool:
    """True if this transaction includes at least one dropped player."""
    for item in transaction_items(tx):
        s, n = _normalize_item_type(item)
        if s in _ITEM_DROP_STRINGS:
            return True
        if n is not None and n in _ITEM_DROP_NUMERIC:
            return True
    return False


def iter_dropped_players(tx: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Yield item dicts that represent drops."""
    for item in transaction_items(tx):
        s, n = _normalize_item_type(item)
        if s in _ITEM_DROP_STRINGS or (n is not None and n in _ITEM_DROP_NUMERIC):
            yield item


def player_label_from_item(
    item: dict[str, Any],
    player_cache: dict[int, str] | None = None,
) -> str:
    """
    Best-effort display name from a transaction item.
    Prefers the local player_cache (populated by fetch_player_cache.py), then
    falls back to the inline playerPoolEntry (rarely present in mTransactions2),
    then falls back to the numeric id.
    """
    pid = item.get("playerId")
    if player_cache is not None and pid is not None:
        name = player_cache.get(int(pid))
        if name:
            return name
    pool = item.get("playerPoolEntry") or {}
    player = pool.get("player") or {}
    full = player.get("fullName")
    if full:
        return str(full)
    return f"player_id {pid}" if pid is not None else "unknown player"


def team_name(team_map: dict[int, str], team_id: int | None) -> str:
    if team_id is None:
        return "unknown team"
    tid = int(team_id)
    return team_map.get(tid, f"team_id {tid}")


def build_team_map(data: dict[str, Any]) -> dict[int, str]:
    """Build id -> display name from league JSON `teams` list."""
    out: dict[int, str] = {}
    for team in data.get("teams") or []:
        if not isinstance(team, dict):
            continue
        tid = team.get("id")
        if tid is None:
            continue
        name = team.get("name")
        if not name:
            loc = (team.get("location") or "").strip()
            nick = (team.get("nickname") or "").strip()
            name = f"{loc} {nick}".strip() or str(tid)
        out[int(tid)] = str(name)
    return out

#!/usr/bin/env python3
"""Quick ESPN API smoke test — reads credentials from .env (see .env.example)."""
import json
import sys
from collections import Counter
from pathlib import Path

from dotenv import load_dotenv

# Load before espn_client: guarantees project `.env` even if tooling sets cwd elsewhere,
# and override=True beats empty LEAGUE_ID from the parent environment.
load_dotenv(Path(__file__).resolve().parent / ".env", override=True)

from espn_client import fetch_league_json_from_env
from transaction_utils import (
    is_drop_transaction,
    is_lineup_only_transaction,
    is_waiver_or_freeagent_transaction,
)


def main() -> None:
    try:
        status, body = fetch_league_json_from_env()
    except RuntimeError as e:
        print(e, file=sys.stderr)
        print("See .env.example — save `.env` with real values (file must be saved to disk).", file=sys.stderr)
        sys.exit(1)

    print(f"Status: {status}")

    if status != 200:
        print("Failed:", str(body)[:800])
        sys.exit(1)

    if not isinstance(body, dict):
        print(
            "ESPN returned HTTP 200 but the body is not JSON (often HTML or a bot block). "
            "Try fresh cookies, run from your home IP (no VPN), and open the league in a browser first.",
            file=sys.stderr,
        )
        print(str(body)[:1200])
        sys.exit(1)

    data = body
    transactions = [t for t in (data.get("transactions") or []) if isinstance(t, dict)]
    teams = data.get("teams", [])
    print(f"Teams in payload: {len(teams)}")
    print(f"Total transactions in this response: {len(transactions)}")

    top_types = Counter(str(t.get("type") or "?") for t in transactions)
    print(f"By transaction.type: {dict(top_types)}")

    item_types = Counter()
    for t in transactions:
        for it in t.get("items") or []:
            if isinstance(it, dict):
                item_types[str(it.get("type") or "?")] += 1
    if item_types:
        print(f"By items[].type: {dict(item_types)}")

    drops = [t for t in transactions if is_drop_transaction(t)]
    fa_waiver = [t for t in transactions if is_waiver_or_freeagent_transaction(t)]
    lineup_only = [t for t in transactions if is_lineup_only_transaction(t)]

    print(f"Rows the drop monitor would treat as a drop: {len(drops)}")
    print(f"Rows typed FREEAGENT/WAIVER/WAIVER_ERROR: {len(fa_waiver)}")
    print(f"Rows that look like lineup/bench shuffles only: {len(lineup_only)}")

    if not drops and not fa_waiver and lineup_only:
        print(
            "\nNote: Everything in this batch is LINEUP / ROSTER moves (slot ↔ bench). "
            "Those are not waiver drops. Real drops show items with type DROPPED/DROP, "
            "usually under transaction.type FREEAGENT or WAIVER.\n"
            "The API only returns a small recent window; after someone adds/drops, run again.\n"
        )

    show: list[dict] = []
    if drops:
        print("\n--- Sample DROP payloads (up to 3) ---")
        show = drops[:3]
    elif fa_waiver:
        print("\n--- Sample FREEAGENT/WAIVER payloads (up to 3) ---")
        show = fa_waiver[:3]
    elif transactions:
        print("\n--- First 3 transactions (may be lineup-only) ---")
        show = transactions[:3]

    for t in show:
        print(json.dumps(t, indent=2))


if __name__ == "__main__":
    main()

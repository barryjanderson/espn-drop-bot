"""
Shared ESPN Fantasy API client for the drop bot POC.
Credentials come from environment variables (see .env.example).
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Optional

import requests
from dotenv import load_dotenv

# Load `.env` next to this module (project root). Use override=True so values from the file
# win over empty vars some shells/IDEs inject (python-dotenv defaults to not overriding).
_PROJECT_ROOT = Path(__file__).resolve().parent
_ENV_FILE = _PROJECT_ROOT / ".env"
if _ENV_FILE.is_file():
    load_dotenv(_ENV_FILE, override=True)
else:
    # Fallback: cwd (e.g. alternate working directory)
    load_dotenv(Path.cwd() / ".env", override=True)


def get_env_required(key: str) -> str:
    raw = os.getenv(key)
    if raw is None:
        raise RuntimeError(
            f"Missing required environment variable: {key}. "
            f"Set it in `.env` at {_PROJECT_ROOT / '.env'} (see .env.example)."
        )
    value = raw.strip()
    if not value:
        raise RuntimeError(
            f"{key} is empty. Save `.env` with a non-blank value after `=` "
            f"(unsaved editor buffers do not count), or unset a conflicting empty "
            f"export in your shell/IDE."
        )
    return value


def get_espn_credentials() -> tuple[str, str, str, str]:
    """Returns league_id, espn_s2, swid, season."""
    league_id = get_env_required("LEAGUE_ID")
    espn_s2 = get_env_required("ESPN_S2")
    swid = get_env_required("SWID")
    season = os.getenv("ESPN_SEASON", "2026").strip() or "2026"
    return league_id, espn_s2, swid, season


def _api_base() -> str:
    """
    JSON league data should hit the read API host (matches espn-api / Dusty Turner writeups).
    fantasy.espn.com/apis/... often returns the public Fantasy HTML shell instead of JSON.
    """
    return os.getenv(
        "ESPN_API_BASE",
        "https://lm-api-reads.fantasy.espn.com/apis/v3/games",
    ).rstrip("/")


def build_league_api_url(league_id: str, season: str) -> str:
    return f"{_api_base()}/flb/seasons/{season}/segments/0/leagues/{league_id}"


def _transaction_filter_header_value() -> str | None:
    """
    Limit mTransactions2 to waiver / free-agent moves (drops live here), not LINEUP swaps.
    Matches cwendt94/espn-api League.transactions() filter shape.
    """
    if os.getenv("ESPN_TRANSACTION_FILTER", "1").strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return None
    raw = os.getenv("ESPN_TRANSACTION_FILTER_TYPES", "").strip()
    if raw:
        types = [x.strip().upper() for x in raw.split(",") if x.strip()]
    else:
        types = ["FREEAGENT", "WAIVER", "WAIVER_ERROR"]
    if not types:
        return None
    return json.dumps(
        {"transactions": {"filterType": {"value": types}}},
        separators=(",", ":"),
    )


def build_headers(league_id: str) -> dict[str, str]:
    """
    Browser-like headers + ESPN fantasy client hints (helps avoid CDN 403s).
    Referer should match league context.
    """
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json",
        "Referer": f"https://fantasy.espn.com/baseball/league?leagueId={league_id}",
        "Origin": "https://fantasy.espn.com",
        "x-fantasy-source": "kona",
        # Matches logged-in web client pattern (exact value can rotate; cookies matter most)
        "x-fantasy-platform": "kona-PROD-87a80957c881e75a550d8333be46831eea27e08a",
    }


def _parse_response_json(response: requests.Response) -> Any | None:
    """
    Parse JSON from ESPN response. Returns None if body is empty, non-JSON (e.g. HTML), or invalid.
    Handles optional JSONP-style prefix used by some endpoints.
    """
    text = (response.text or "").strip()
    if text.startswith(")]}'"):
        text = text[4:].lstrip()
    if not text or text[0] not in "{[":
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def fetch_league_json(
    league_id: str,
    espn_s2: str,
    swid: str,
    season: str,
    *,
    extra_views: Optional[list[str]] = None,
    timeout: int = 30,
) -> tuple[int, Any]:
    """
    GET league endpoint with one or more view params.
    Returns (status_code, body): body is dict/list on JSON success; otherwise a short str preview
    (ESPN sometimes returns HTTP 200 with HTML or a non-JSON challenge page).
    """
    url = build_league_api_url(league_id, season)
    views = list(extra_views or ["mTeam", "mTransactions2"])
    params: list[tuple[str, Any]] = [("view", v) for v in views]
    scoring_period = os.getenv("ESPN_SCORING_PERIOD_ID", "").strip()
    if scoring_period.isdigit():
        # Optional: scope transactions to one scoring period (see league page / schedule).
        params.append(("scoringPeriodId", int(scoring_period)))
    # Cookie names match browser/devtools (SWID is uppercase).
    cookies = {"espn_s2": espn_s2, "SWID": swid}
    headers = build_headers(league_id)
    tx_filter = _transaction_filter_header_value()
    if tx_filter is not None:
        headers["x-fantasy-filter"] = tx_filter

    response = requests.get(
        url,
        params=params,
        cookies=cookies,
        headers=headers,
        timeout=timeout,
    )
    if response.status_code != 200:
        return response.status_code, response.text

    data = _parse_response_json(response)
    if data is None:
        preview = (response.text or "")[:2500].strip()
        return response.status_code, (
            preview if preview else "[empty body — not JSON]"
        )
    return response.status_code, data


def fetch_league_json_from_env(**kwargs: Any) -> tuple[int, Any]:
    league_id, espn_s2, swid, season = get_espn_credentials()
    return fetch_league_json(league_id, espn_s2, swid, season, **kwargs)

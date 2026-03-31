# ESPN Fantasy Baseball — drop monitor (POC)

Polls the ESPN Fantasy private API for league transactions, detects drops, and posts to a Discord webhook. **Local runs** store state in `seen_transactions.json` (gitignored). **Cloud** uses [Vercel](https://vercel.com) (Python serverless) plus [Upstash Redis](https://upstash.com) for state, triggered every 5 minutes by [GitHub Actions](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule) (needed on Vercel Hobby, which only allows daily cron at most).

## Setup

1. **Python 3.11+** recommended.

2. **Virtualenv** (from project root):

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. **Environment variables** — copy [.env.example](.env.example) to `.env` and fill in:

   If you see “Missing required environment variable: LEAGUE_ID” even though `.env` is set, check that nothing in your shell or editor exports an **empty** `LEAGUE_ID` — the loader uses `override=True` so values from `.env` replace those. Quotes help for `SWID` if it contains `{` `}`: `SWID="{...}"`.

   - `LEAGUE_ID` — from the league URL (`leagueId=...`)
   - `ESPN_S2`, `SWID` — browser cookies while logged in at `fantasy.espn.com` (DevTools → Application → Cookies)
   - `DISCORD_WEBHOOK_URL` — Discord server webhook URL
   - Optional: `ESPN_SEASON` (default `2026`), `POLL_INTERVAL_SEC`, `SEED_ON_FIRST_RUN`

4. **Smoke-test the ESPN API:**

   ```bash
   python test_espn.py
   ```

   Expect HTTP `200` and JSON (transaction count). Requests use **`lm-api-reads.fantasy.espn.com`** (not `fantasy.espn.com/apis`), which avoids the generic Fantasy HTML page. If you still see HTML or `401`, refresh `espn_s2` and `SWID` from the browser while logged into the league.

   By default, league fetches send **`x-fantasy-filter`** so `mTransactions2` only includes **FREEAGENT**, **WAIVER**, and **WAIVER_ERROR** moves (same idea as `espn-api`’s `transactions()`), which drops most lineup-only transactions. Set `ESPN_TRANSACTION_FILTER=0` in `.env` to get the unfiltered list again.

   **`test_espn.py` output:** Transactions with `type: ROSTER` and `items[].type: LINEUP` are **bench ↔ lineup slot** moves, not drops. Waivers/add-drops use top-level **`FREEAGENT`** or **`WAIVER`** and usually include items with **`DROPPED`** / **`ADD`**. ESPN only returns a **short recent list**; if nobody has added/dropped lately, you’ll mostly see lineup noise — `drop_monitor` still only alerts on real drops.

5. **Run the monitor locally:**

   ```bash
   python drop_monitor.py
   ```

   On the first successful poll with an empty state file, existing drops are recorded **without** Discord notifications (`SEED_ON_FIRST_RUN=1` by default). After that, new drops trigger webhook posts.

## Deploy (Vercel + Upstash + GitHub cron)

1. **Upstash** — Create a Redis database (free tier). Copy the **REST URL** and **REST TOKEN**.

2. **GitHub** — Push this repo (or connect it to Vercel from GitHub). In the repo **Settings → Secrets and variables → Actions**, add:
   - `MONITOR_URL` — `https://<your-deployment>.vercel.app/api/monitor` (your real Vercel URL)
   - `CRON_SECRET` — a long random string (same value you set in Vercel below)

3. **Vercel** — New project from the repo. Set environment variables (Production):
   - All ESPN + Discord vars from `.env.example` (`LEAGUE_ID`, `ESPN_S2`, `SWID`, `DISCORD_WEBHOOK_URL`, optional `ESPN_SEASON`, etc.)
   - `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`
   - `CRON_SECRET` — must match the GitHub secret

   Redeploy after changing env vars.

4. **Workflow** — [.github/workflows/cron.yml](.github/workflows/cron.yml) runs every 5 minutes and `curl`s the monitor with `Authorization: Bearer <CRON_SECRET>`. Fix `MONITOR_URL` if your Vercel URL changes.

5. **Player names** — [player_cache.json](player_cache.json) is committed so Discord embeds resolve names in serverless (ESPN’s `mTransactions2` usually lacks full names). Refresh with `python fetch_player_cache.py` and commit when the player pool changes.

6. **Limits** — Vercel Hobby functions cap at **10s**; [vercel.json](vercel.json) sets `maxDuration` to 10 and the serverless handler uses an 8s ESPN timeout by default (`ESPN_FETCH_TIMEOUT_SEC`). If you see timeouts, upgrade Vercel Pro for longer functions or tune the timeout env.

First cloud poll with an **empty** Upstash key behaves like local: `SEED_ON_FIRST_RUN` seeds existing drops **without** Discord spam.

## Files

| File | Purpose |
|------|---------|
| `espn_client.py` | League URL, headers, `fetch_league_json_from_env` |
| `transaction_utils.py` | Drop detection + team map helpers |
| `poll_once.py` | Single poll + Discord (shared local + Vercel) |
| `api/monitor.py` | Vercel HTTP handler; Redis state + auth |
| `test_espn.py` | One-shot API test |
| `drop_monitor.py` | Local poll loop + file state |

## Security

- Never commit `.env` or real cookie values (`.gitignore` covers `.env` and `seen_transactions.json`).
- Rotate `ESPN_S2` / `SWID` if they leak.
- Keep `CRON_SECRET` private; it gates the `/api/monitor` endpoint.

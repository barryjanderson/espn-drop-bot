# ESPN Fantasy — drop monitor

Small Python tool that polls the **unofficial** ESPN Fantasy private API for your league’s transactions, detects player drops, and posts to a **Discord** webhook. It is **not affiliated with ESPN or Discord**; the API is undocumented and may change without notice.

**Local:** state lives in `seen_transactions.json` (gitignored).  
**Cloud:** [Vercel](https://vercel.com) serverless + [Upstash Redis](https://upstash.com) for state, triggered every 5 minutes by [GitHub Actions](https://docs.github.com/en/actions/using-workflows/events-that-trigger-workflows#schedule) — needed on Vercel Hobby, which only allows daily cron at most.

## What you need

- Python **3.11+**
- An ESPN Fantasy baseball league you can open while logged in at `fantasy.espn.com` (for cookies)
- A Discord channel webhook URL (optional if you only want to test the API)

## Quick start (local)

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — see below
python test_espn.py
python drop_monitor.py
```

## Environment variables

Copy [.env.example](.env.example) to `.env` and fill in:

| Variable | Required | Description |
|----------|----------|-------------|
| `LEAGUE_ID` | yes | From the league URL (`leagueId=...`) |
| `ESPN_S2`, `SWID` | yes | Browser cookies while logged in at `fantasy.espn.com` (DevTools → Application → Cookies) |
| `DISCORD_WEBHOOK_URL` | yes for notifications | Discord server webhook |
| `ESPN_SEASON` | no | Default `2026` |
| `POLL_INTERVAL_SEC` | no | Local loop interval (default `300`) |
| `SEED_ON_FIRST_RUN` | no | First run with empty state: record existing drops without Discord (default `1`) |

**Loader quirk:** If you see “Missing required environment variable: `LEAGUE_ID`” even though `.env` looks correct, check that your shell or IDE is not exporting an **empty** `LEAGUE_ID`. This project loads `.env` with `override=True`, so file values should win — but fixing stray empty exports helps. Use quotes for `SWID` if it contains `{` or `}`: `SWID="{...}"`.

**Transaction filter:** League fetches send `x-fantasy-filter` so `mTransactions2` focuses on **FREEAGENT**, **WAIVER**, and **WAIVER_ERROR** moves (similar to common `espn-api` usage), which cuts most lineup-only noise. Set `ESPN_TRANSACTION_FILTER=0` in `.env` for the unfiltered list.

### Smoke test (`test_espn.py`)

Expect HTTP `200` and JSON (transaction count). Requests use **`lm-api-reads.fantasy.espn.com`**, not `fantasy.espn.com/apis`, which avoids the generic Fantasy HTML page. If you get HTML or `401`, refresh `ESPN_S2` and `SWID` from the browser while logged into the league.

**Reading the output:** Transactions with `type: ROSTER` and `items[].type: LINEUP` are bench ↔ lineup moves, not drops. Real adds/drops use top-level **`FREEAGENT`** or **`WAIVER`** and usually include **`DROPPED`** / **`ADD`**. ESPN returns a **short recent** list — if there have been no adds/drops, you may mostly see lineup churn. The monitor still only alerts on real drops.

## Deploy (Vercel + Upstash + GitHub Actions)

1. **Upstash** — Create a Redis database (free tier). Copy the **REST URL** and **REST TOKEN**.

2. **Vercel** — New project from this repo. In **Production** environment variables, set everything from `.env.example` that applies (`LEAGUE_ID`, `ESPN_S2`, `SWID`, `DISCORD_WEBHOOK_URL`, optional `ESPN_SEASON`, etc.), plus:
   - `UPSTASH_REDIS_REST_URL`, `UPSTASH_REDIS_REST_TOKEN`
   - `CRON_SECRET` — long random string; must match GitHub (next step)

   Redeploy after changing env vars.

3. **GitHub** — In the repo **Settings → Secrets and variables → Actions**, add:
   - `MONITOR_URL` — your monitor URL, e.g. `https://<project>.vercel.app/api/monitor`
   - `CRON_SECRET` — same value as on Vercel
   - `VERCEL_BYPASS_TOKEN` — **optional**. Only if [Vercel Deployment Protection](https://vercel.com/docs/deployment-protection) is enabled: create a protection bypass token in the Vercel project and store it here. The workflow appends `x-vercel-protection-bypass=...` when this secret is set.

4. **Workflow** — [.github/workflows/cron.yml](.github/workflows/cron.yml) runs every 5 minutes and calls the monitor with `Authorization: Bearer <CRON_SECRET>`. Update `MONITOR_URL` if your deployment hostname changes.

5. **Player names** — [player_cache.json](player_cache.json) is committed so Discord embeds can resolve names in serverless (ESPN’s `mTransactions2` often omits full names). Regenerate with `python fetch_player_cache.py` and commit when the player pool changes meaningfully.

6. **Timeouts** — Vercel Hobby functions are capped around **10s**. [vercel.json](vercel.json) sets `maxDuration` to 10 for the API handlers; the handler defaults to an **8s** ESPN timeout (`ESPN_FETCH_TIMEOUT_SEC`). If you hit timeouts, consider Vercel Pro for longer functions or tune the env var.

The first cloud poll with an **empty** Upstash key behaves like local: with `SEED_ON_FIRST_RUN` (default), existing drops are recorded **without** Discord spam.

## Project layout

| File | Purpose |
|------|---------|
| `espn_client.py` | League URL, headers, `fetch_league_json_from_env` |
| `transaction_utils.py` | Drop detection and team map helpers |
| `poll_once.py` | Single poll + Discord (shared by local and Vercel) |
| `api/monitor.py` | Vercel HTTP handler; Redis state + auth |
| `api/index.py` | WSGI entry used by some Vercel Python runtimes |
| `test_espn.py` | One-shot API test |
| `drop_monitor.py` | Local poll loop + file-backed state |
| `fetch_player_cache.py` | Refresh `player_cache.json` |

## License

[MIT](LICENSE)

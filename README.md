# Support & Resistance Dashboard

Self-hosted support/resistance detection for equities, run four times a day on a
GitHub Actions cron and served as a static dashboard from GitHub Pages. Full
design rationale is in [`sr-dashboard-design.md`](sr-dashboard-design.md); this
file covers day-to-day setup, tuning, and running it.

## How it works

Alpaca 15-minute bars → pivot detection → clustering into levels → volume
profile (high-volume nodes) → scoring → signal rules → SQLite (history) +
`docs/levels.json`, `docs/bars/*.json`, `docs/metrics.json` (dashboard feed).
See section 1 of the design spec for the full architecture diagram.

## One-time setup

1. **Alpaca account** — sign up at [alpaca.markets](https://alpaca.markets),
   enable Paper Trading, generate an API Key ID + Secret Key.
2. **GitHub repo secrets** — Settings → Secrets and variables → Actions, add
   `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY`.
3. **GitHub Pages** — Settings → Pages → Source: *Deploy from branch* →
   `main` / `docs`. Won't show as deployed until after the first run commits
   something into `docs/`.
4. **Actions write permission** — Settings → Actions → General → Workflow
   permissions → *Read and write*. Required so the cron job can commit
   `docs/levels.json`, `docs/metrics.json`, `docs/bars/`, and `data/levels.db`
   back to `main`.
5. **`tickers.txt`** — one symbol per line, uppercase, no blank lines. The
   full universe fetched and scored every run.
6. **`holdings.txt`** (optional) — the subset of `tickers.txt` you actually
   own, same one-per-line format. Drives the dashboard's "My Holdings" vs
   "Watchlist" tabs: anything in `holdings.txt` shows under Holdings,
   everything else in `tickers.txt` shows under Watchlist. Leave it out (or
   empty) and everything falls under Watchlist.

## Running locally

```bash
pip install -r requirements.txt
```

Create a `.env` file (never committed — it's in `.gitignore`) at the repo root:

```
ALPACA_API_KEY_ID=your_key_id
ALPACA_API_SECRET_KEY=your_secret_key
```

Then:

```bash
python -m src.main
```

This reads `tickers.txt`, fetches 60 days of 15-minute bars (cached to
`data/cache/` so a rerun over the same range doesn't re-hit the API), computes
levels and signals for every symbol, and writes `data/levels.db` plus
`docs/levels.json`, `docs/metrics.json`, and `docs/bars/<SYMBOL>.json`.

To preview the dashboard itself:

```bash
cd docs && python -m http.server 8000
```

then open `http://localhost:8000`. It reads only static JSON files it fetches
via relative paths — no server-side code needed, which is also exactly how
GitHub Pages serves it in production.

### Running tests

```bash
pip install pytest
python -m pytest
```

`pivots.py`, `volume.py`, and `scoring.py` are pure functions (no I/O), so
they're fully covered by fixture-based unit tests in `tests/`. `test_pivots.py`
in particular uses a small hand-built bar series with pivots you can verify
by eye — see the docstring at the top of that file for the layout.

## Tuning thresholds

Every threshold lives in `src/config.py` — nowhere else. Change values there,
not in the modules that consume them:

| Constant | Meaning | Default |
|---|---|---|
| `PIVOT_WINDOW` | Bars on each side a pivot must beat | 5 |
| `CLUSTER_TOLERANCE` | Merge pivots within this % of each other | 0.5% |
| `MIN_TOUCH_COUNT` | Discard clusters with fewer touches | 2 |
| `VOLUME_BUCKET_COUNT` | Buckets across the 60-day price range | 50 |
| `HVN_PERCENTILE` | Top-decile-by-volume threshold for HVNs | 0.9 |
| `TOUCH_WEIGHT` / `RECENCY_WEIGHT` / `HVN_BONUS` | Scoring formula weights | 3 / 2 / 2 |
| `RECENCY_FULL_WEIGHT_DAYS` / `RECENCY_MIN_WEIGHT_DAYS` | Recency decay window | 5 / 60 days |
| `TOP_N_LEVELS` | Supports/resistances kept per symbol | 3 |
| `PROXIMITY_PCT` | "Within X%" for BUY_ZONE / CALL_ZONE | 1% |
| `NEUTRAL_PCT` | ">X% from both" for NEUTRAL | 2% |
| `STRIKE_INCREMENTS` | Option strike rounding tiers | $0.50 / $1 / $5 |

If the dashboard feels cluttered (too many rows in a zone), start with
`PROXIMITY_PCT` — that's the most common thing worth loosening or tightening.
If levels feel noisy, raise `PIVOT_WINDOW` before touching anything else.

Full formula rationale is commented directly in `src/scoring.py` — read the
docstrings there before changing the weights, not just this table.

## Scheduling

`.github/workflows/refresh-levels.yml` runs weekdays at 08:00 / 12:00 / 16:00 /
18:00 ET (cron is UTC and doesn't observe DST — the times in the file are
correct for EDT; shift by +1 hour during EST, or accept the drift). It also
supports `workflow_dispatch` for a manual run from the Actions tab.

GitHub disables scheduled workflows after 60 days of repo inactivity — a
commit on every run (which this workflow does whenever data changed) keeps it
alive.

## Known limitations

- **15-minute delay** on Alpaca's free IEX feed — levels are historical
  anyway, but the "current price" column lags. Don't trade the last 15
  minutes off it.
- **IEX-only volume** — a fraction of total market volume, so the volume
  profile is directionally right but not absolute.
- **Pattern detection, not prediction.** Levels break, often on news no
  chart anticipated.
- **Strike suggestions are arithmetic**, not a liquidity or IV assessment.
  Verify open interest and bid-ask spread before writing anything — see
  `src/scoring.py`'s `round_strike` docstring.
- **Level hold rate is a proxy metric.** `metrics.json`'s hold rate checks
  whether a support level's price persists between consecutive runs, not
  whether price actually touched it and held. It needs a few weeks of cron
  history to be meaningful at all — with 0-1 runs it's empty by design.

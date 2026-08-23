# Claude Code Prompt

Paste everything below the line into Claude Code, in an empty repo, with `sr-dashboard-design.md` in the working directory.

---

Build a support and resistance dashboard for equities. The full design spec is in `sr-dashboard-design.md` in this directory — read it first and follow it. This prompt covers execution order and the things I care most about.

## What you're building

A Python pipeline that pulls 15-minute bars from Alpaca, computes support/resistance levels via pivot detection and volume profile, scores them, writes results to SQLite plus a JSON feed, and renders a static dashboard served from GitHub Pages. It runs on a GitHub Actions cron four times a day on weekdays.

## Environment

- Python 3.11+
- Alpaca credentials come from env vars `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY` — never hardcode them, never log them
- Use `alpaca-py` for the data client
- Ticker list lives in `tickers.txt`, one symbol per line
- Free tier: IEX feed, 15-minute delayed data

## Build order

1. **Scaffold** — repo structure per section 7 of the spec, `requirements.txt`, `.gitignore` (exclude `.env`, `__pycache__`, raw bar cache).
2. **`src/fetch.py`** — Alpaca client. Batch symbols in groups of 20, handle `next_page_token` pagination, cache raw bars to `data/cache/` keyed by symbol and date so reruns are cheap. Retry with exponential backoff on 429 and 5xx.
3. **`src/pivots.py`** — pivot high/low detection with configurable window (default 5), then clustering at 0.5% tolerance. Return level objects with price, touch count, last touch timestamp.
4. **`src/volume.py`** — volume profile over 50 buckets, identify high-volume nodes at the top decile.
5. **`src/scoring.py`** — the scoring formula and signal rules from spec sections 3.4 and 3.5, plus strike rounding. Keep the thresholds (`1%` proximity, `0.5%` clustering, window size) in a single `config.py` so I can tune them without hunting through modules.
6. **`src/store.py`** — SQLite schema per spec section 4, append-only. Also export `docs/levels.json` with just the latest run.
7. **`src/main.py`** — orchestration with structured logging. Should be runnable locally as `python -m src.main`.
8. **`docs/`** — the static dashboard. Vanilla JS, no build step. Table sorted by distance-to-nearest-level, colour-coded rows, click-to-expand candlestick chart using Lightweight Charts from CDN. Include the level-hold-rate metric chart at the top.
9. **`.github/workflows/refresh-levels.yml`** — the cron schedule from spec section 5, plus `workflow_dispatch`. Commits `docs/levels.json` and `data/levels.db` back to `main`.
10. **`README.md`** — setup steps, how to tune thresholds, how to run locally.

## Constraints

- Stop after each numbered step and let me review before continuing.
- Pure functions in `pivots.py`, `volume.py`, and `scoring.py` — no I/O in those modules. I want to unit test them.
- Write pytest tests for pivot detection and clustering against a small hand-built bar fixture where I can verify the levels by eye.
- The pipeline must not crash on a single bad ticker. Log it, skip it, continue.
- No secrets in committed files. No `print()` for anything that could contain a key.
- Don't add a web framework, a database server, or a frontend build toolchain. Static and boring is the point.
- Comment the scoring logic thoroughly — that's the part I'll be tuning most.

## Start with

Step 1 and 2 only. Show me the fetch layer working against three tickers before building anything on top of it.

# Support & Resistance Dashboard — Design Spec

A self-hosted dashboard that computes support and resistance levels from raw market data, refreshes every four hours during market hours, and surfaces covered-call strike candidates.

---

## 0. Prerequisites (do these before running Claude Code)

| # | Task | Notes |
|---|------|-------|
| 1 | **Create an Alpaca account** | [alpaca.markets](https://alpaca.markets) → sign up → enable **Paper Trading**. No funding required. Generate an API Key ID + Secret Key from the dashboard and save both. |
| 2 | **Create a GitHub repo** | Private is fine. Settings → Pages → Source: *Deploy from branch* → `main` / `docs` folder. |
| 3 | **Add repo secrets** | Settings → Secrets and variables → Actions → New secret. Add `ALPACA_API_KEY_ID` and `ALPACA_API_SECRET_KEY`. |
| 4 | **Export your ticker list** | Pull your ~70 symbols out of Robinhood into a flat list. One symbol per line. |
| 5 | **Install Python 3.11+ locally** | Only needed if you want to test runs before scheduling. `python --version` to confirm. |
| 6 | **Enable Actions write permission** | Settings → Actions → General → Workflow permissions → *Read and write*. Required so the job can commit results back. |

> **Alpaca free tier reality check:** IEX feed only, 15-minute delayed data, 200 API calls/min. That's ample for 70 tickers on a 4-hour cadence. Real-time SIP data requires a paid plan — not needed for level detection.

---

## 1. Architecture

```
┌─────────────────────────────────────────────┐
│  PRESENTATION   GitHub Pages (static)       │
│                 table + per-ticker charts   │
└────────────────────┬────────────────────────┘
                     │ reads levels.json
┌────────────────────┴────────────────────────┐
│  STORAGE        SQLite (history) +          │
│                 levels.json (dashboard feed)│
└────────────────────┬────────────────────────┘
                     │ writes
┌────────────────────┴────────────────────────┐
│  COMPUTE        GitHub Actions, cron        │
│                 pivots → clusters → volume  │
│                 profile → scoring → signals │
└────────────────────┬────────────────────────┘
                     │ fetches
┌────────────────────┴────────────────────────┐
│  DATA           Alpaca Market Data API      │
│                 15-min bars, 60-day window  │
└─────────────────────────────────────────────┘
```

Each layer is swappable. Replacing Alpaca with Polygon later means rewriting one module.

---

## 2. Data layer

**Endpoint:** `GET /v2/stocks/bars` (multi-symbol, comma-separated)

**Parameters:**
- `symbols` — batch in groups of 20 to stay well inside rate limits
- `timeframe` — `15Min`
- `start` — now minus 60 days
- `feed` — `iex`
- `adjustment` — `split`

**Returns:** OHLCV bars per symbol. Roughly 1,560 bars per ticker over 60 days (26 bars/day × 60).

Handle pagination via `next_page_token`. Cache raw bars to disk between runs so a failed compute doesn't force a re-fetch.

---

## 3. Compute layer

### 3.1 Pivot detection

Walk the bar series with a lookback window `W = 5`.

- **Pivot high:** `bar[i].high > bar[i±1..W].high` for all neighbours
- **Pivot low:** `bar[i].low < bar[i±1..W].low` for all neighbours

Smaller `W` = more levels, noisier. Start at 5, tune upward if the dashboard is cluttered.

### 3.2 Clustering

Raw pivots produce near-duplicates. Merge any pivots within **0.5%** of each other into a single level.

```
level_price = volume_weighted_mean(cluster_pivots)
touch_count = len(cluster_pivots)
last_touch  = max(pivot.timestamp for pivot in cluster)
```

Discard clusters with `touch_count < 2` — a single pivot is noise, not a level.

### 3.3 Volume profile

Slice the 60-day price range into 50 buckets. For each bar, add its volume to the bucket containing its typical price `(high + low + close) / 3`.

Buckets in the top decile by volume are **High Volume Nodes (HVNs)** — they act as magnets and barriers. Flag any price level sitting inside an HVN.

### 3.4 Scoring

```
score = (touch_count × 3)
      + (recency_weight × 2)      # 1.0 if touched in last 5 days, decaying to 0.2 at 60 days
      + (hvn_bonus)               # +2 if level sits in a high-volume node
```

Sort levels by score. Keep the **top 3 supports below current price** and **top 3 resistances above**.

### 3.5 Signal rules

This is the thin layer that turns numbers into decisions.

| Condition | Signal |
|-----------|--------|
| Price within 1% above nearest support | `BUY_ZONE` |
| Price within 1% below nearest resistance | `CALL_ZONE` — good spot to write the call |
| Price between, >2% from both | `NEUTRAL` |
| Price below nearest support | `BROKEN_SUPPORT` — level failed, re-evaluate |

**Strike selection for covered calls:**

1. Take nearest resistance above current price.
2. Round **up** to the nearest listed strike (increments are $0.50 under $25, $1.00 under $200, $5.00 above — verify against the actual chain).
3. Report both the raw resistance and the rounded strike, plus the percentage gap from current price.

> The dashboard suggests strikes; it does not verify the option chain exists or is liquid. Check open interest and bid-ask spread in Robinhood before writing anything. Covered calls need 100 shares per contract.

---

## 4. Storage layer

**SQLite** — single file, committed to the repo or kept as an Actions artifact.

```sql
CREATE TABLE levels (
    id              INTEGER PRIMARY KEY,
    symbol          TEXT NOT NULL,
    run_timestamp   TEXT NOT NULL,
    current_price   REAL,
    level_price     REAL,
    level_type      TEXT,      -- 'support' | 'resistance'
    touch_count     INTEGER,
    last_touch      TEXT,
    in_hvn          INTEGER,
    score           REAL
);

CREATE TABLE signals (
    id              INTEGER PRIMARY KEY,
    symbol          TEXT NOT NULL,
    run_timestamp   TEXT NOT NULL,
    current_price   REAL,
    nearest_support REAL,
    nearest_resist  REAL,
    pct_to_support  REAL,
    pct_to_resist   REAL,
    signal          TEXT,
    suggested_strike REAL
);

CREATE INDEX idx_symbol_run ON levels(symbol, run_timestamp);
```

Append, don't overwrite — level drift over weeks is genuinely useful signal.

Alongside the DB, write **`docs/levels.json`** containing only the latest run. That's what the dashboard fetches.

---

## 5. Scheduling

`.github/workflows/refresh-levels.yml`

```yaml
on:
  schedule:
    - cron: '0 12 * * 1-5'   # 08:00 ET
    - cron: '0 16 * * 1-5'   # 12:00 ET
    - cron: '0 20 * * 1-5'   # 16:00 ET
    - cron: '0 22 * * 1-5'   # 18:00 ET
  workflow_dispatch:          # manual trigger
```

**Caveats:**
- GitHub cron is **UTC** and does not observe DST. The times above are correct for EDT (Mar–Nov); during EST you'll need to shift each by +1 hour, or just accept the drift.
- GitHub delays scheduled runs by 5–20 minutes under load. Fine at this cadence.
- Scheduled workflows are **disabled automatically after 60 days of repo inactivity**. A commit every run keeps it alive.

---

## 6. Presentation layer

Static page in `docs/`, served by GitHub Pages.

### Table view (default)

| Symbol | Price | Support | % to S | Resistance | % to R | Strike | Signal |
|--------|-------|---------|--------|------------|--------|--------|--------|

- Sort by **absolute distance to nearest level**, ascending — actionable rows float to the top
- Row tint: green for `BUY_ZONE`, amber for `CALL_ZONE`, red for `BROKEN_SUPPORT`
- Click a row to expand the chart

### Chart view (per ticker)

Use **Lightweight Charts** (TradingView's open-source library, ~45KB, MIT licensed):

- Candlestick series from the cached bars
- Horizontal price lines for each level, opacity scaled by score
- Volume histogram in a lower pane

### Metrics worth tracking over time

- **Level hold rate** — of levels flagged as support, what % held on the next touch? This tells you whether your `W` and clustering thresholds are tuned right.
- **Signal count per day** — if every ticker is always in a zone, your 1% threshold is too loose.
- **Realised gap** — distance between entry and where resistance actually capped the move.

Render these as a small line chart at the top of the page from the SQLite history.

---

## 7. Repo structure

```
├── .github/workflows/refresh-levels.yml
├── src/
│   ├── fetch.py         # Alpaca client, batching, pagination, caching
│   ├── pivots.py        # pivot detection + clustering
│   ├── volume.py        # volume profile, HVN identification
│   ├── scoring.py       # level scoring + signal rules + strike rounding
│   ├── store.py         # SQLite writes, levels.json export
│   └── main.py          # orchestration
├── docs/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── levels.json      # regenerated each run
├── data/
│   └── levels.db
├── tickers.txt
├── requirements.txt
└── README.md
```

---

## 8. Known limitations

- **15-minute delay** on the free feed. Levels are historical anyway, but the "current price" column will lag — don't trade the last 15 minutes off it.
- **IEX feed only** covers a fraction of total volume, so volume profile is directionally right but not absolute.
- Support and resistance is **pattern detection on past price**, not prediction. Levels break, often on news that no chart anticipated.
- The strike suggestion is arithmetic, not an assessment of whether the trade is sound. Liquidity, IV, earnings dates, and assignment risk all sit outside this system.

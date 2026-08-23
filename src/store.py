"""SQLite storage (append-only history) and the docs/levels.json dashboard feed.

Unlike pivots.py/volume.py/scoring.py, this module does real I/O on purpose —
it's the one place in the pipeline allowed to touch disk for persistence.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from src import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS levels (
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

CREATE TABLE IF NOT EXISTS signals (
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

CREATE INDEX IF NOT EXISTS idx_symbol_run ON levels(symbol, run_timestamp);
"""


def init_db(db_path: str | Path) -> sqlite3.Connection:
    """Open (creating if needed) the SQLite file and ensure the schema exists."""
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def write_levels(
    conn: sqlite3.Connection,
    symbol: str,
    run_timestamp: str,
    current_price: float,
    levels: list[dict],
) -> None:
    """Append one row per scored level. `levels` items need price, level_type,
    touch_count, last_touch, in_hvn, score — the shape scoring.score_level
    returns. Append-only: never UPDATE or DELETE existing rows, so level
    drift over weeks stays queryable.
    """
    conn.executemany(
        """
        INSERT INTO levels
            (symbol, run_timestamp, current_price, level_price, level_type,
             touch_count, last_touch, in_hvn, score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                symbol,
                run_timestamp,
                current_price,
                lv["price"],
                lv["level_type"],
                lv["touch_count"],
                lv["last_touch"],
                int(bool(lv.get("in_hvn", False))),
                lv["score"],
            )
            for lv in levels
        ],
    )
    conn.commit()


def write_signal(
    conn: sqlite3.Connection,
    symbol: str,
    run_timestamp: str,
    current_price: float,
    nearest_support: float | None,
    nearest_resist: float | None,
    pct_to_support: float | None,
    pct_to_resist: float | None,
    signal: str,
    suggested_strike: float | None,
) -> None:
    """Append one signal row for this symbol's run. Append-only, same as write_levels."""
    conn.execute(
        """
        INSERT INTO signals
            (symbol, run_timestamp, current_price, nearest_support, nearest_resist,
             pct_to_support, pct_to_resist, signal, suggested_strike)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            symbol,
            run_timestamp,
            current_price,
            nearest_support,
            nearest_resist,
            pct_to_support,
            pct_to_resist,
            signal,
            suggested_strike,
        ),
    )
    conn.commit()


def export_levels_json(conn: sqlite3.Connection, run_timestamp: str, out_path: str | Path = "docs/levels.json") -> None:
    """Write docs/levels.json containing just this run: one entry per symbol
    with its current price, signal, nearest support/resistance, and full
    level list. This — not the SQLite file — is what the dashboard fetches.
    """
    signal_rows = conn.execute(
        """
        SELECT symbol, current_price, nearest_support, nearest_resist,
               pct_to_support, pct_to_resist, signal, suggested_strike
        FROM signals
        WHERE run_timestamp = ?
        """,
        (run_timestamp,),
    ).fetchall()

    level_rows = conn.execute(
        """
        SELECT symbol, level_price, level_type, touch_count, last_touch, in_hvn, score
        FROM levels
        WHERE run_timestamp = ?
        ORDER BY symbol, score DESC
        """,
        (run_timestamp,),
    ).fetchall()

    levels_by_symbol: dict[str, list[dict]] = {}
    for symbol, price, level_type, touch_count, last_touch, in_hvn, score in level_rows:
        levels_by_symbol.setdefault(symbol, []).append(
            {
                "price": price,
                "level_type": level_type,
                "touch_count": touch_count,
                "last_touch": last_touch,
                "in_hvn": bool(in_hvn),
                "score": score,
            }
        )

    symbols = [
        {
            "symbol": symbol,
            "current_price": current_price,
            "nearest_support": nearest_support,
            "nearest_resist": nearest_resist,
            "pct_to_support": pct_to_support,
            "pct_to_resist": pct_to_resist,
            "signal": signal,
            "suggested_strike": suggested_strike,
            "levels": levels_by_symbol.get(symbol, []),
        }
        for (
            symbol,
            current_price,
            nearest_support,
            nearest_resist,
            pct_to_support,
            pct_to_resist,
            signal,
            suggested_strike,
        ) in signal_rows
    ]

    payload = {"run_timestamp": run_timestamp, "symbols": symbols}

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))


def export_metrics_json(
    conn: sqlite3.Connection,
    out_path: str | Path = "docs/metrics.json",
    tolerance: float = config.CLUSTER_TOLERANCE,
) -> None:
    """Write docs/metrics.json: signal-count-per-run, and a level-hold-rate
    time series, both read back from SQLite history (not just this run).

    Level-hold-rate here is a proxy for spec section 6's "of levels flagged
    as support, what % held on the next touch": for each pair of consecutive
    runs, it's the fraction of a symbol's support levels from the earlier
    run that still show up (within `tolerance`) as a support level in the
    later run. It's a same-price-persisted check, not a true touch-by-touch
    outcome — that needs matching each level to its *next actual price
    touch*, which this pipeline doesn't track yet. Good enough once a few
    weeks of cron runs have accumulated; with 0-1 runs it's just empty.
    """
    runs = [r[0] for r in conn.execute("SELECT DISTINCT run_timestamp FROM levels ORDER BY run_timestamp")]

    signal_counts_by_run: dict[str, dict[str, int]] = {}
    for run in runs:
        rows = conn.execute(
            "SELECT signal, COUNT(*) FROM signals WHERE run_timestamp = ? GROUP BY signal", (run,)
        ).fetchall()
        signal_counts_by_run[run] = {sig: cnt for sig, cnt in rows}

    level_hold_rate_by_run: dict[str, float | None] = {}
    for i in range(1, len(runs)):
        prev_run, cur_run = runs[i - 1], runs[i]
        prev_supports = conn.execute(
            "SELECT symbol, level_price FROM levels WHERE run_timestamp = ? AND level_type = 'support'",
            (prev_run,),
        ).fetchall()

        cur_by_symbol: dict[str, list[float]] = {}
        for symbol, price in conn.execute(
            "SELECT symbol, level_price FROM levels WHERE run_timestamp = ? AND level_type = 'support'",
            (cur_run,),
        ):
            cur_by_symbol.setdefault(symbol, []).append(price)

        held, total = 0, 0
        for symbol, price in prev_supports:
            total += 1
            candidates = cur_by_symbol.get(symbol, [])
            if any(abs(c - price) / price <= tolerance for c in candidates):
                held += 1
        level_hold_rate_by_run[cur_run] = (held / total) if total else None

    payload = {
        "runs": runs,
        "signal_counts_by_run": signal_counts_by_run,
        "level_hold_rate_by_run": level_hold_rate_by_run,
    }

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2))


def export_bars_json(bars_by_symbol: dict[str, list[dict]], out_dir: str | Path = "docs/bars") -> None:
    """Write one docs/bars/<SYMBOL>.json per symbol, bars reshaped for
    Lightweight Charts (time as UNIX seconds, not the ISO string fetch.py
    uses internally).

    GitHub Pages only serves the docs/ folder — data/cache/ is gitignored
    and outside docs/ anyway — so without this export the dashboard's
    click-to-expand candlestick chart would have nothing to fetch.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for symbol, bars in bars_by_symbol.items():
        if not bars:
            continue
        shaped = [
            {
                "time": int(datetime.fromisoformat(b["t"]).timestamp()),
                "open": b["o"],
                "high": b["h"],
                "low": b["l"],
                "close": b["c"],
                "volume": b["v"],
            }
            for b in bars
        ]
        (out / f"{symbol}.json").write_text(json.dumps(shaped))

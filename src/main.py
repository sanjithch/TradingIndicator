"""Pipeline orchestration. Runnable locally as `python -m src.main`.

Reads tickers.txt, fetches bars, computes levels and signals per symbol,
writes everything to SQLite, and exports docs/levels.json for the dashboard.
A single bad ticker is logged and skipped — it never aborts the run.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import config
from src.fetch import fetch_bars
from src.pivots import cluster_pivots, find_pivots
from src.scoring import determine_signal, score_level, select_top_levels, suggested_strike
from src.store import (
    export_bars_json,
    export_holdings_json,
    export_levels_json,
    export_metrics_json,
    init_db,
    write_levels,
    write_signal,
)
from src.volume import build_volume_profile, high_volume_nodes, price_in_hvn

logger = logging.getLogger("sr_dashboard")

TICKERS_FILE = "tickers.txt"
HOLDINGS_FILE = "holdings.txt"
DB_PATH = "data/levels.db"
LEVELS_JSON_PATH = "docs/levels.json"
LOOKBACK_DAYS = 60


def _log(event: str, **fields) -> None:
    """Structured-ish logging: one line per event, key=value fields appended.
    Deliberately not a JSON logging library — this is a small pipeline, a
    grep-able log line is enough and keeps requirements.txt boring.
    """
    kv = " ".join(f"{k}={v!r}" for k, v in fields.items())
    logger.info("%s %s", event, kv)


def load_tickers(path: str | Path = TICKERS_FILE) -> list[str]:
    return [line.strip().upper() for line in Path(path).read_text().splitlines() if line.strip()]


def load_holdings(path: str | Path = HOLDINGS_FILE) -> list[str]:
    """Symbols you actually own, one per line — the same format as
    tickers.txt. Missing file just means no holdings tagged (everything
    shows up as watchlist-only on the dashboard), not an error.
    """
    p = Path(path)
    if not p.exists():
        return []
    return [line.strip().upper() for line in p.read_text().splitlines() if line.strip()]


def process_symbol(symbol: str, bars: list[dict], as_of: datetime) -> dict | None:
    """Run one symbol through pivots -> clustering -> volume profile ->
    scoring -> signal. Returns a result dict, or None if there wasn't
    enough data to produce anything meaningful (logged, not raised).
    """
    if len(bars) < 2 * config.PIVOT_WINDOW + 1:
        _log("skip_symbol", symbol=symbol, reason="not_enough_bars", bar_count=len(bars))
        return None

    current_price = bars[-1]["c"]

    pivots = find_pivots(bars, window=config.PIVOT_WINDOW)
    raw_levels = cluster_pivots(
        pivots, tolerance=config.CLUSTER_TOLERANCE, min_touch_count=config.MIN_TOUCH_COUNT
    )
    if not raw_levels:
        _log("skip_symbol", symbol=symbol, reason="no_levels_found")
        return None

    buckets = build_volume_profile(bars, bucket_count=config.VOLUME_BUCKET_COUNT)
    hvns = high_volume_nodes(buckets, percentile=config.HVN_PERCENTILE)

    scored_levels = [
        score_level(level, in_hvn=price_in_hvn(level["price"], hvns), as_of=as_of)
        for level in raw_levels
    ]

    top = select_top_levels(scored_levels, current_price, top_n=config.TOP_N_LEVELS)
    kept_levels = top["supports"] + top["resistances"]

    nearest_support = max((lv["price"] for lv in top["supports"]), default=None)
    nearest_resist = min((lv["price"] for lv in top["resistances"]), default=None)

    pct_to_support = (current_price - nearest_support) / nearest_support if nearest_support else None
    pct_to_resist = (nearest_resist - current_price) / nearest_resist if nearest_resist else None

    signal = determine_signal(current_price, nearest_support, nearest_resist)

    strike_info = suggested_strike(nearest_resist, current_price) if nearest_resist else None

    return {
        "current_price": current_price,
        "levels": kept_levels,
        "nearest_support": nearest_support,
        "nearest_resist": nearest_resist,
        "pct_to_support": pct_to_support,
        "pct_to_resist": pct_to_resist,
        "signal": signal,
        "suggested_strike": strike_info["suggested_strike"] if strike_info else None,
    }


def run() -> None:
    run_timestamp = datetime.now(timezone.utc).isoformat()
    _log("run_start", run_timestamp=run_timestamp)

    symbols = load_tickers()
    _log("tickers_loaded", count=len(symbols))

    start = datetime.now(timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    all_bars = fetch_bars(symbols, start=start)

    conn = init_db(DB_PATH)

    processed = 0
    skipped = 0
    for symbol in symbols:
        bars = all_bars.get(symbol, [])
        if not bars:
            _log("skip_symbol", symbol=symbol, reason="no_bars_fetched")
            skipped += 1
            continue

        try:
            result = process_symbol(symbol, bars, as_of=datetime.now(timezone.utc))
        except Exception as e:
            # A single bad ticker must never take the whole run down.
            _log("symbol_error", symbol=symbol, error=str(e))
            skipped += 1
            continue

        if result is None:
            skipped += 1
            continue

        write_levels(conn, symbol, run_timestamp, result["current_price"], result["levels"])
        write_signal(
            conn,
            symbol,
            run_timestamp,
            result["current_price"],
            result["nearest_support"],
            result["nearest_resist"],
            result["pct_to_support"],
            result["pct_to_resist"],
            result["signal"],
            result["suggested_strike"],
        )
        processed += 1
        _log("symbol_done", symbol=symbol, signal=result["signal"], price=result["current_price"])

    export_levels_json(conn, run_timestamp, LEVELS_JSON_PATH)
    export_metrics_json(conn)
    export_bars_json(all_bars)
    export_holdings_json(load_holdings())
    conn.close()

    _log("run_complete", processed=processed, skipped=skipped, total=len(symbols))


if __name__ == "__main__":
    import dotenv

    dotenv.load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        stream=sys.stdout,
    )
    run()

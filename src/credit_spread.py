"""Credit Spread Watchlist tab: daily-bar technicals (panel 1) + upcoming
catalysts (panel 2). Called from src/main.py's run() so `python -m src.main`
still does everything in one command.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src import config
from src.catalysts import upcoming_events
from src.fetch import fetch_bars
from src.store import export_credit_spread_json
from src.technicals import pct_distance, rolling_high_low, rsi, sma
from alpaca.data.timeframe import TimeFrame

logger = logging.getLogger("sr_dashboard")

CATALYSTS_SEED_PATH = "data/catalysts_seed.json"
DAILY_CACHE_SUBDIR = "daily"


def _log(event: str, **fields) -> None:
    kv = " ".join(f"{k}={v!r}" for k, v in fields.items())
    logger.info("%s %s", event, kv)


def load_catalysts_seed(path: str | Path = CATALYSTS_SEED_PATH) -> dict:
    """Static seed data (earnings + macro dates) — see that file's _comment
    for why this isn't a live fetch. Missing file just means an empty
    catalysts panel, not a crash.
    """
    p = Path(path)
    if not p.exists():
        _log("catalysts_seed_missing", path=str(p))
        return {"earnings": [], "macro": []}
    return json.loads(p.read_text())


def compute_technicals(symbol: str, bars: list[dict]) -> dict | None:
    """One row for panel 1: swing support/resistance at each configured
    lookback, 50/200-day SMA, 14-day RSI, and the current price plus every
    distance-as-percentage the panel needs. None if there are no bars at
    all for this symbol (logged, not raised — a single bad ticker must
    never abort the run).
    """
    if not bars:
        return None

    current_price = bars[-1]["c"]

    levels = {}
    for lookback in config.SWING_LOOKBACKS:
        hl = rolling_high_low(bars, lookback)
        levels[str(lookback)] = {
            "support": hl["support"],
            "resistance": hl["resistance"],
            "bars_used": hl["bars_used"],
            "pct_to_support": pct_distance(current_price, hl["support"]),
            "pct_to_resistance": pct_distance(current_price, hl["resistance"]),
        }

    mas = {}
    for period in config.SMA_PERIODS:
        value = sma(bars, period)
        mas[str(period)] = {
            "value": value,
            "pct_distance": pct_distance(current_price, value),
        }

    return {
        "symbol": symbol,
        "current_price": current_price,
        "bar_count": len(bars),
        "levels": levels,
        "sma": mas,
        "rsi14": rsi(bars, config.RSI_PERIOD),
    }


def run() -> None:
    """Fetch daily bars for config.CREDIT_SPREAD_TICKERS, compute panel-1
    technicals per symbol, compute panel-2 catalysts, and write
    docs/credit_spread.json. A single bad ticker is logged and skipped —
    same rule as the rest of the pipeline.
    """
    run_timestamp = datetime.now(timezone.utc).isoformat()
    _log("credit_spread_start", tickers=config.CREDIT_SPREAD_TICKERS)

    start = datetime.now(timezone.utc) - timedelta(days=config.CREDIT_SPREAD_DAILY_LOOKBACK_DAYS)
    all_bars = fetch_bars(
        config.CREDIT_SPREAD_TICKERS,
        start=start,
        timeframe=TimeFrame.Day,
        cache_subdir=DAILY_CACHE_SUBDIR,
    )

    technicals = []
    for symbol in config.CREDIT_SPREAD_TICKERS:
        bars = all_bars.get(symbol, [])
        try:
            result = compute_technicals(symbol, bars)
        except Exception as e:
            _log("credit_spread_symbol_error", symbol=symbol, error=str(e))
            continue
        if result is None:
            _log("credit_spread_skip_symbol", symbol=symbol, reason="no_bars_fetched")
            continue
        technicals.append(result)
        _log("credit_spread_symbol_done", symbol=symbol, price=result["current_price"], rsi14=result["rsi14"])

    seed = load_catalysts_seed()
    catalysts = upcoming_events(
        seed,
        now=datetime.now(timezone.utc),
        window_days=config.CATALYST_WINDOW_DAYS,
        watchlist_tickers=config.CREDIT_SPREAD_TICKERS,
    )

    export_credit_spread_json(run_timestamp, technicals, catalysts)
    _log("credit_spread_complete", technicals=len(technicals), catalysts=len(catalysts))

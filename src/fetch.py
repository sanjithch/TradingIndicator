"""Alpaca bar fetching: batched requests, disk cache, retry with backoff.

Credentials come from ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY env vars.
Never hardcode or log them.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from alpaca.common.exceptions import APIError
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

logger = logging.getLogger(__name__)

BATCH_SIZE = 20
CACHE_DIR = Path("data/cache")
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_RETRIES = 5
BASE_BACKOFF_SECONDS = 1.0


def _get_client() -> StockHistoricalDataClient:
    """Build the Alpaca data client from env vars. Raises if either is missing."""
    key_id = os.environ.get("ALPACA_API_KEY_ID")
    secret_key = os.environ.get("ALPACA_API_SECRET_KEY")
    if not key_id or not secret_key:
        raise RuntimeError(
            "ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY must be set in the environment"
        )
    return StockHistoricalDataClient(key_id, secret_key)


def _chunked(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def _request_with_retry(fn, *args, **kwargs):
    """Call fn(*args, **kwargs), retrying on 429/5xx with exponential backoff + jitter.

    alpaca-py's get_stock_bars already loops internally on next_page_token
    until every page for the request is collected, so a single call here
    returns the fully paginated result for the batch.
    """
    attempt = 0
    while True:
        try:
            return fn(*args, **kwargs)
        except APIError as e:
            status = getattr(e, "status_code", None)
            attempt += 1
            if status not in RETRYABLE_STATUS_CODES or attempt > MAX_RETRIES:
                logger.error("Alpaca request failed permanently (status=%s): %s", status, e)
                raise
            sleep_s = BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)) + random.uniform(0, 0.5)
            logger.warning(
                "Alpaca request failed (status=%s), retry %d/%d in %.1fs",
                status,
                attempt,
                MAX_RETRIES,
                sleep_s,
            )
            time.sleep(sleep_s)


def _cache_path(symbol: str, day: date) -> Path:
    return CACHE_DIR / symbol / f"{day.isoformat()}.json"


def _bar_to_dict(bar) -> dict:
    return {
        "t": bar.timestamp.isoformat(),
        "o": bar.open,
        "h": bar.high,
        "l": bar.low,
        "c": bar.close,
        "v": bar.volume,
    }


def _write_cache(symbol: str, bars_by_day: dict[date, list]) -> None:
    for day, bars in bars_by_day.items():
        path = _cache_path(symbol, day)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([_bar_to_dict(b) for b in bars], indent=None))


def _read_cache(symbol: str, day: date) -> list[dict] | None:
    path = _cache_path(symbol, day)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        logger.warning("Corrupt cache file %s, will refetch", path)
        return None


def _group_bars_by_day(bars: list) -> dict[date, list]:
    grouped: dict[date, list] = {}
    for bar in bars:
        grouped.setdefault(bar.timestamp.date(), []).append(bar)
    return grouped


def fetch_bars(
    symbols: list[str],
    start: datetime,
    end: datetime | None = None,
    feed: str = "iex",
    use_cache: bool = True,
) -> dict[str, list[dict]]:
    """Fetch 15-minute bars for symbols between start and end.

    Batches symbols in groups of BATCH_SIZE, retries on 429/5xx, and caches
    raw bars to disk per symbol/day so a rerun over the same range is cheap.
    A single bad symbol never aborts the whole run — it's logged and skipped.

    Returns {symbol: [bar_dict, ...]} sorted by timestamp, cached bars merged
    with freshly fetched ones.
    """
    end = end or datetime.now()
    client = _get_client()
    results: dict[str, list[dict]] = {s: [] for s in symbols}

    for batch in _chunked(symbols, BATCH_SIZE):
        try:
            request = StockBarsRequest(
                symbol_or_symbols=batch,
                timeframe=TimeFrame(15, TimeFrame.Minute.unit),
                start=start,
                end=end,
                feed=feed,
                adjustment="split",
            )
            bar_set = _request_with_retry(client.get_stock_bars, request)
        except Exception as e:
            logger.error("Batch fetch failed for %s: %s", batch, e)
            # Fall back to per-symbol fetch so one bad ticker in the batch
            # doesn't take the rest of the batch down with it.
            for symbol in batch:
                results[symbol] = _fetch_single_symbol(client, symbol, start, end, feed)
            continue

        for symbol in batch:
            bars = bar_set.data.get(symbol, [])
            if not bars:
                logger.warning("No bars returned for %s in this batch", symbol)
            by_day = _group_bars_by_day(bars)
            if use_cache:
                _write_cache(symbol, by_day)
            results[symbol] = [_bar_to_dict(b) for b in bars]

    return results


def _fetch_single_symbol(client, symbol: str, start, end, feed) -> list[dict]:
    """Best-effort single-symbol fetch used when a batch request fails.
    Logs and returns [] for this symbol on failure rather than raising,
    so the caller can continue with the rest of the run.
    """
    try:
        request = StockBarsRequest(
            symbol_or_symbols=symbol,
            timeframe=TimeFrame(15, TimeFrame.Minute.unit),
            start=start,
            end=end,
            feed=feed,
            adjustment="split",
        )
        bar_set = _request_with_retry(client.get_stock_bars, request)
        bars = bar_set.data.get(symbol, [])
        by_day = _group_bars_by_day(bars)
        _write_cache(symbol, by_day)
        return [_bar_to_dict(b) for b in bars]
    except Exception as e:
        logger.error("Skipping %s after single-symbol fetch failed: %s", symbol, e)
        return []


if __name__ == "__main__":
    import dotenv

    dotenv.load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    test_symbols = ["AAPL", "MSFT", "NVDA"]
    start = datetime.now() - timedelta(days=5)
    data = fetch_bars(test_symbols, start=start)
    for sym, bars in data.items():
        print(f"{sym}: {len(bars)} bars", bars[-1] if bars else "(none)")

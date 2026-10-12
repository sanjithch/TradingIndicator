"""Oil prices and Treasury yields for the dashboard's market strip.

Runs as its own entry point (`python -m src.market`) on its own, faster
schedule (.github/workflows/refresh-market.yml) -- deliberately NOT part of
src/main.py's run(), so a fast refresh never races the heavier pipeline over
the same files.

Sources (both free, no API key):
  * Oil + intraday 10Y: Yahoo Finance chart API. Unofficial but widely used;
    NYMEX futures are ~10-15 min delayed. It sends no CORS headers, so the
    browser can't call it directly -- hence a scheduled fetch committed to
    docs/market.json.
  * Yield curve: US Treasury daily par yield curve CSV. Official, but
    published once per business day (after the close), so it is end-of-day
    by nature, not intraday.

Parsers are pure (canned-payload testable); only fetch_* / run() do I/O.
A failed source keeps its previous value, flagged stale, rather than
blanking the dashboard.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from src import config
from src.store import export_market_json

logger = logging.getLogger("sr_dashboard")

MARKET_JSON_PATH = "docs/market.json"
YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?interval=5m&range=1d"
TREASURY_URL = (
    "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
    "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
    "&field_tdr_date_value={year}&page&_format=csv"
)
USER_AGENT = "Mozilla/5.0 (compatible; sr-dashboard/1.0)"


# ----------------------------- pure parsers -----------------------------


def parse_yahoo_quote(payload: dict, label: str) -> dict:
    """One quote from a Yahoo chart-API response. Raises KeyError/IndexError/
    TypeError on a malformed payload -- the caller treats that as a failed
    fetch and falls back to the previous value.
    """
    meta = payload["chart"]["result"][0]["meta"]
    price = float(meta["regularMarketPrice"])
    prev = meta.get("chartPreviousClose") or meta.get("previousClose")
    prev = float(prev) if prev is not None else None
    change = price - prev if prev is not None else None
    return {
        "symbol": meta["symbol"],
        "label": label,
        "price": price,
        "prev_close": prev,
        "change": change,
        "change_pct": (change / prev * 100) if prev else None,
        "as_of": datetime.fromtimestamp(meta["regularMarketTime"], tz=timezone.utc).isoformat(),
    }


def parse_treasury_curve(csv_text: str, maturities: list[str]) -> dict | None:
    """Latest and prior-day par yields for `maturities`, plus the 2s10s
    spread in basis points. Returns None if there are fewer than two usable
    rows (nothing to take a day-over-day change from).
    """
    rows = []
    for row in csv.DictReader(io.StringIO(csv_text)):
        try:
            day = datetime.strptime(row["Date"], "%m/%d/%Y").date()
        except (KeyError, ValueError):
            continue
        rows.append((day, row))
    rows.sort(key=lambda r: r[0])
    if len(rows) < 2:
        return None

    (prior_day, prior), (day, latest) = rows[-2], rows[-1]

    def rate(row: dict, maturity: str) -> float | None:
        raw = (row.get(maturity) or "").strip()
        return float(raw) if raw else None

    curve = []
    for m in maturities:
        now, before = rate(latest, m), rate(prior, m)
        curve.append(
            {
                "maturity": m.replace(" Mo", "M").replace(" Yr", "Y"),
                "rate": now,
                "prior": before,
                "change_bp": round((now - before) * 100, 1) if now is not None and before is not None else None,
            }
        )

    two, ten = rate(latest, "2 Yr"), rate(latest, "10 Yr")
    return {
        "as_of": day.isoformat(),
        "prior_as_of": prior_day.isoformat(),
        "curve": curve,
        "spread_2s10s_bp": round((ten - two) * 100, 1) if two is not None and ten is not None else None,
    }


def keep_previous(new, old, stale_marker: bool = True):
    """Fallback rule: use the fresh value; if the fetch failed (None), reuse
    the previous one flagged stale so the page shows old data honestly
    rather than nothing.
    """
    if new is not None:
        return new
    if old is None:
        return None
    return {**old, "stale": True} if stale_marker else old


# ------------------------------- I/O layer -------------------------------


def _http_get(url: str, timeout: int = 20, attempts: int = 2) -> str:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read().decode("utf-8")
        except Exception as e:  # network/HTTP errors: retry once, then give up
            last = e
    raise RuntimeError(f"GET failed for {url}: {last}")


def fetch_quote(symbol: str, label: str) -> dict:
    url = YAHOO_URL.format(symbol=urllib.parse.quote(symbol))
    return parse_yahoo_quote(json.loads(_http_get(url)), label)


def fetch_curve(maturities: list[str], today: datetime | None = None) -> dict | None:
    year = (today or datetime.now(timezone.utc)).year
    text = _http_get(TREASURY_URL.format(year=year))
    curve = parse_treasury_curve(text, maturities)
    if curve is None:  # early January: new year's file may have <2 rows yet
        text = _http_get(TREASURY_URL.format(year=year - 1)) + "\n" + "\n".join(text.splitlines()[1:])
        curve = parse_treasury_curve(text, maturities)
    return curve


def _load_previous(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def run(path: str | Path = MARKET_JSON_PATH) -> dict:
    previous = _load_previous(path)
    prev_oil = {q["symbol"]: q for q in previous.get("oil", [])}
    errors: list[str] = []

    oil = []
    for symbol, label in config.MARKET_OIL_SYMBOLS:
        try:
            quote = fetch_quote(symbol, label)
        except Exception as e:
            logger.error("market_fetch_failed source=%s error=%s", symbol, e)
            errors.append(f"{symbol}: {e}")
            quote = None
        merged = keep_previous(quote, prev_oil.get(symbol))
        if merged is not None:
            oil.append(merged)

    try:
        intraday = fetch_quote(*config.MARKET_INTRADAY_YIELD)
    except Exception as e:
        logger.error("market_fetch_failed source=%s error=%s", config.MARKET_INTRADAY_YIELD[0], e)
        errors.append(f"{config.MARKET_INTRADAY_YIELD[0]}: {e}")
        intraday = None

    try:
        treasury = fetch_curve(config.MARKET_CURVE_MATURITIES)
    except Exception as e:
        logger.error("market_fetch_failed source=treasury error=%s", e)
        errors.append(f"treasury: {e}")
        treasury = None

    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "oil": oil,
        "yield_10y_intraday": keep_previous(intraday, previous.get("yield_10y_intraday")),
        "treasury": keep_previous(treasury, previous.get("treasury")),
        "errors": errors,
    }
    export_market_json(payload, path)
    logger.info("market_done oil=%d treasury=%s errors=%d", len(oil), bool(payload["treasury"]), len(errors))
    return payload


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    run()

"""Swing support/resistance, moving averages, and RSI — daily-bar technicals
for the Credit Spread Watchlist tab.

Pure functions only — no I/O, matching pivots.py/volume.py/scoring.py.
Unlike pivots.py's clustering approach (built for intraday touch/cluster
levels), swing support/resistance here is the simpler, standard "N-day
high/low" definition: the rolling extreme over a lookback window. That's a
different, coarser concept than a clustered pivot level and is intentionally
not reusing find_pivots/cluster_pivots — those need multiple touches within
a tolerance band, which isn't how a 20-day high/low is defined.

Bars are the same dicts fetch.py produces:
    {"t": iso_timestamp_str, "o": float, "h": float, "l": float, "c": float, "v": float}
assumed sorted ascending by timestamp, one bar per trading day.
"""

from __future__ import annotations


def rolling_high_low(bars: list[dict], lookback: int) -> dict | None:
    """Support/resistance from the last `lookback` bars' extremes:
    resistance = highest high, support = lowest low. Uses all available
    bars if there are fewer than `lookback` (a fresh listing, say) rather
    than returning nothing — the result is just a shorter-window value,
    which the caller can see for itself from the bar count if it matters.

    Returns None only when `bars` is empty.
    """
    if not bars:
        return None
    window = bars[-lookback:] if len(bars) >= lookback else bars
    return {
        "support": min(b["l"] for b in window),
        "resistance": max(b["h"] for b in window),
        "bars_used": len(window),
    }


def sma(bars: list[dict], period: int) -> float | None:
    """Simple moving average of closes over the last `period` bars.
    None if there aren't at least `period` bars — an SMA computed from a
    partial window isn't the SMA a chart would show, so don't pretend it is.
    """
    if len(bars) < period:
        return None
    window = bars[-period:]
    return sum(b["c"] for b in window) / period


def rsi(bars: list[dict], period: int = 14) -> float | None:
    """Wilder's RSI over the last `period` bars' closes.

    Standard formula: seed the average gain/loss from the first `period`
    day-over-day changes (simple mean), then smooth every change after that
    with Wilder's recursive average — avg = (avg*(period-1) + new) / period.
    RSI = 100 - 100/(1+RS) where RS = avg_gain/avg_loss.

    None if there aren't at least `period + 1` bars (need `period` changes,
    which takes period+1 closes). An RSI of exactly 100 (all gains, zero
    losses) is returned as 100.0 rather than raising on the RS
    divide-by-zero — that's a legitimate, if extreme, reading.
    """
    if len(bars) < period + 1:
        return None

    closes = [b["c"] for b in bars[-(period + 1) :]]
    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]

    gains = [max(c, 0) for c in changes]
    losses = [max(-c, 0) for c in changes]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # With exactly period+1 bars there's exactly one seed window and no
    # further smoothing steps to run — the loop below is then a no-op.
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def pct_distance(current_price: float, level: float | None) -> float | None:
    """(current - level) / level, as a fraction — positive means price is
    above the level, negative means below. None propagates (missing level
    or missing price means no distance to report).
    """
    if level is None or current_price is None:
        return None
    return (current_price - level) / level

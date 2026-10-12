"""Macro tilt: a rules-based read of oil + 10Y-yield momentum, calibrated
against VOO's subsequent returns.

Pure functions only -- no I/O (calibration data is fetched by
src/calibrate_signal.py, the live inputs by src/market.py).

IMPORTANT -- what this is and isn't. It was built after measuring ten years
of VOO against WTI and the 10Y yield (2016-2026) and the honest finding is
that oil and yields explain very little of VOO's moves: same-day
correlations are ~0.1 and flip sign between eras. The rules below are the
two effects that were visible in the data, not a forecast:

  * Yields FALLING sharply (10Y down >=30bp over 20 trading days) was
    followed by above-average VOO returns in both halves of the sample.
  * Oil AND yields rising together (WTI up >=10%, 10Y up >=10bp) was
    followed by below-average -- but still positive on average -- returns,
    clearly only in the later half. So "bearish tilt" means "weaker tailwind
    than usual", not "expect a decline".

Thresholds live in config.py. Re-run `python -m src.calibrate_signal` to
refresh the historical numbers shown next to the signal.
"""

from __future__ import annotations

from src import config

BULLISH = "BULLISH"
NEUTRAL = "NEUTRAL"
BEARISH = "BEARISH"


def pct_change(values: list[float], n: int) -> float | None:
    """Percent change of the newest value vs the one `n` observations
    earlier (values oldest -> newest). None if the history is too short or
    the base is not positive.
    """
    if len(values) <= n or values[-1 - n] <= 0:
        return None
    return (values[-1] / values[-1 - n] - 1) * 100


def diff_bp(values: list[float], n: int) -> float | None:
    """Change in basis points of the newest value vs `n` observations
    earlier, for series quoted in percent (yields)."""
    if len(values) <= n:
        return None
    return (values[-1] - values[-1 - n]) * 100


def classify(
    wti_pct: float | None,
    y10_bp: float | None,
    yield_bp: float = config.SIGNAL_YIELD_BP,
    oil_pct: float = config.SIGNAL_OIL_PCT,
    oil_yield_bp: float = config.SIGNAL_OIL_YIELD_BP,
) -> dict | None:
    """Score the two rules and map the total to a state.

    score = yield_points + oil_points, each in {-1, 0, +1}:
      yield_points: +1 if y10_bp <= -yield_bp; -1 if y10_bp >= +yield_bp
      oil_points:   -1 if wti_pct >= oil_pct AND y10_bp >= oil_yield_bp
    state: BULLISH if score >= 1, BEARISH if score <= -1, else NEUTRAL.

    Returns None if the yield move is unknown (the signal's main input).
    A missing oil figure just scores that rule 0 and says so in the
    component note. `components` explains each point so the UI can show
    *why*, not just the verdict.
    """
    if y10_bp is None:
        return None

    if y10_bp <= -yield_bp:
        y_pts, y_note = 1, f"10Y fell {abs(y10_bp):.0f} bp in 20d (>= {yield_bp} bp drop)"
    elif y10_bp >= yield_bp:
        y_pts, y_note = -1, f"10Y rose {y10_bp:.0f} bp in 20d (>= {yield_bp} bp rise)"
    else:
        y_pts, y_note = 0, f"10Y {y10_bp:+.0f} bp in 20d (inside +/-{yield_bp} bp)"

    if wti_pct is None:
        o_pts, o_note = 0, "WTI 20d change unavailable"
    elif wti_pct >= oil_pct and y10_bp >= oil_yield_bp:
        o_pts, o_note = -1, f"WTI +{wti_pct:.0f}% with yields rising (oil + rates headwind)"
    else:
        o_pts, o_note = 0, f"WTI {wti_pct:+.0f}% in 20d (no oil + rates headwind)"

    score = y_pts + o_pts
    state = BULLISH if score >= 1 else BEARISH if score <= -1 else NEUTRAL
    return {
        "state": state,
        "score": score,
        "wti_20d_pct": wti_pct,
        "y10_20d_bp": y10_bp,
        "components": [
            {"name": "10Y momentum", "points": y_pts, "note": y_note},
            {"name": "Oil + rates", "points": o_pts, "note": o_note},
        ],
    }


def backtest(
    dates: list[str],
    voo: list[float],
    wti: list[float],
    y10: list[float],
    horizon: int = config.SIGNAL_LOOKBACK,
) -> dict:
    """Replay `classify` over history and report VOO's forward `horizon`-day
    return by signal state, overall and split into two halves of the sample
    (an effect that exists in only one half is not trustworthy).

    Inputs are aligned daily series (oldest -> newest, same length). Rows
    with WTI <= 5 (the Apr-2020 negative-price print) are dropped first, as
    are windows with an absurd >=100% oil move. The signal at day t uses only
    data up to t; the forward return runs from t's close.

    NOTE the forward windows overlap, so the effective sample is roughly
    n / horizon -- read small gaps between states as noise.
    """
    rows = [(d, v, w, y) for d, v, w, y in zip(dates, voo, wti, y10) if w > 5]
    dts = [r[0] for r in rows]
    v = [r[1] for r in rows]
    w = [r[2] for r in rows]
    y = [r[3] for r in rows]

    samples = []  # (date, state, fwd_pct)
    for i in range(horizon, len(rows) - horizon):
        wp = pct_change(w[: i + 1], horizon)
        if wp is None or abs(wp) >= 100:
            continue
        sig = classify(wp, diff_bp(y[: i + 1], horizon))
        fwd = (v[i + horizon] / v[i] - 1) * 100
        samples.append((dts[i], sig["state"], fwd))

    if not samples:
        return {"horizon_days": horizon, "n": 0, "baseline": None, "states": {}}

    mid = samples[len(samples) // 2][0]

    def stats(sel: list[float]) -> dict:
        return {
            "n": len(sel),
            "mean_pct": round(sum(sel) / len(sel), 2) if sel else None,
            "pct_positive": round(100 * sum(1 for s in sel if s > 0) / len(sel)) if sel else None,
        }

    allf = [s[2] for s in samples]
    out = {
        "horizon_days": horizon,
        "n": len(samples),
        "first": samples[0][0],
        "last": samples[-1][0],
        "baseline": stats(allf),
        "states": {},
    }
    for state in (BULLISH, NEUTRAL, BEARISH):
        sel = [s for s in samples if s[1] == state]
        out["states"][state] = {
            **stats([s[2] for s in sel]),
            "first_half_mean_pct": stats([s[2] for s in sel if s[0] < mid])["mean_pct"],
            "second_half_mean_pct": stats([s[2] for s in sel if s[0] >= mid])["mean_pct"],
        }
    return out

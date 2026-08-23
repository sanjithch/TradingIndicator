"""Level scoring, signal rules, and covered-call strike rounding.

Pure functions only — no I/O. This is the module you'll be tuning most, so
every rule is commented with the *why*, not just the *what*. Thresholds
themselves live in config.py — change values there, not here.
"""

from __future__ import annotations

from datetime import datetime

from src import config


def recency_weight(
    last_touch: str,
    as_of: datetime,
    full_weight_days: float = config.RECENCY_FULL_WEIGHT_DAYS,
    min_weight_days: float = config.RECENCY_MIN_WEIGHT_DAYS,
    max_weight: float = config.RECENCY_MAX_WEIGHT,
    min_weight: float = config.RECENCY_MIN_WEIGHT,
) -> float:
    """How "alive" a level's most recent touch still is, on a 0-1-ish scale.

    A level touched yesterday means more than one touched two months ago —
    price action from 60 days back may no longer reflect current supply and
    demand. This gives full weight (max_weight) to anything touched within
    `full_weight_days`, floors at `min_weight` for anything `min_weight_days`
    or older, and interpolates linearly between the two. It's a straight
    line, not a curve, deliberately — easy to reason about when tuning.

    `last_touch` and `as_of` must both be either naive or both tz-aware;
    mixing raises a TypeError from the subtraction, which is the right
    failure mode (silently comparing apples to oranges would be worse).
    """
    last_touch_dt = datetime.fromisoformat(last_touch)
    days_ago = (as_of - last_touch_dt).total_seconds() / 86400

    if days_ago <= full_weight_days:
        return max_weight
    if days_ago >= min_weight_days:
        return min_weight

    frac = (days_ago - full_weight_days) / (min_weight_days - full_weight_days)
    return max_weight - frac * (max_weight - min_weight)


def score_level(
    level: dict,
    in_hvn: bool,
    as_of: datetime,
    touch_weight: float = config.TOUCH_WEIGHT,
    recency_score_weight: float = config.RECENCY_WEIGHT,
    hvn_bonus: float = config.HVN_BONUS,
) -> dict:
    """Score one level: score = touch_count*touch_weight + recency_weight*recency_score_weight + hvn_bonus.

    Rationale for each term:
      - touch_count carries the most weight (x3 by default) because a level
        that price has repeatedly respected is the strongest evidence we
        have — it's the whole basis of support/resistance as a concept.
      - recency contributes less (x2) and is capped at 1.0 pre-multiplier —
        it should nudge the ranking toward "still relevant," not override
        touch count. A level touched 4 times 40 days ago should usually
        outrank one touched twice last week.
      - the HVN bonus is a flat add, not a multiplier, because sitting in a
        high-volume node is corroborating evidence from a different
        signal (traded volume) rather than a repeat of the touch-count
        signal — it shouldn't compound with it.

    Returns a new dict: the input `level` plus "score" and "in_hvn" keys.
    """
    rw = recency_weight(level["last_touch"], as_of)
    score = level["touch_count"] * touch_weight + rw * recency_score_weight + (hvn_bonus if in_hvn else 0)
    return {**level, "score": score, "in_hvn": in_hvn}


def select_top_levels(
    scored_levels: list[dict],
    current_price: float,
    top_n: int = config.TOP_N_LEVELS,
) -> dict:
    """Split scored levels into supports (below current price) and
    resistances (above current price), each sorted by score descending and
    truncated to the top `top_n`. A level exactly at current_price is
    excluded from both — it's neither above nor below.

    Returns {"supports": [...], "resistances": [...]}.
    """
    supports = sorted(
        (lv for lv in scored_levels if lv["level_type"] == "support" and lv["price"] < current_price),
        key=lambda lv: lv["score"],
        reverse=True,
    )[:top_n]
    resistances = sorted(
        (lv for lv in scored_levels if lv["level_type"] == "resistance" and lv["price"] > current_price),
        key=lambda lv: lv["score"],
        reverse=True,
    )[:top_n]
    return {"supports": supports, "resistances": resistances}


def determine_signal(
    current_price: float,
    nearest_support: float | None,
    nearest_resistance: float | None,
    proximity_pct: float = config.PROXIMITY_PCT,
    neutral_pct: float = config.NEUTRAL_PCT,
) -> str:
    """Turn distance-to-nearest-level into a decision per spec section 3.5.

    Checked in this order, first match wins:
      1. BROKEN_SUPPORT — price has fallen below the nearest support. This
         takes priority over everything else: a broken level is a warning,
         not an opportunity, even if price also happens to be near some
         other level.
      2. BUY_ZONE — price is at or up to `proximity_pct` above support.
         "At or above" (not strictly above) because a level is a zone in
         practice, not a single tick — testing it from either side counts.
      3. CALL_ZONE — mirror image: at or up to `proximity_pct` below
         resistance. Good spot to consider writing a covered call.
      4. NEUTRAL — the fallback. The spec's own definition of NEUTRAL is
         ">2% from both" (neutral_pct), but the gap between proximity_pct
         (1%) and neutral_pct (2%) is left undefined by the spec table.
         Rather than invent a fifth signal for that gap, anything that
         isn't clearly a zone or clearly broken defaults to NEUTRAL —
         "no strong signal" is a safe default when a rule doesn't apply.

    A missing support or resistance (None — e.g. no support level exists
    below current price at all) simply can't trigger its own branch and
    falls through toward NEUTRAL, which is correct: no level, no signal.
    """
    if nearest_support is not None and current_price < nearest_support:
        return "BROKEN_SUPPORT"

    if (
        nearest_support is not None
        and current_price >= nearest_support
        and (current_price - nearest_support) / nearest_support <= proximity_pct
    ):
        return "BUY_ZONE"

    if (
        nearest_resistance is not None
        and current_price <= nearest_resistance
        and (nearest_resistance - current_price) / nearest_resistance <= proximity_pct
    ):
        return "CALL_ZONE"

    return "NEUTRAL"


def round_strike(price: float, increments: list[tuple[float, float]] = config.STRIKE_INCREMENTS) -> float:
    """Round `price` UP to the nearest listed option strike increment.

    `increments` is a list of (price_ceiling, increment) pairs, checked in
    order — the first ceiling `price` falls under determines the increment
    used. Real strike ladders vary by underlying and by broker; this is
    arithmetic, not a live option chain — always verify against the actual
    chain before trading (see spec section 3.5's closing caveat).
    """
    for ceiling, increment in increments:
        if price < ceiling:
            import math

            return math.ceil(price / increment) * increment
    raise ValueError(f"No increment tier covers price {price} — check config.STRIKE_INCREMENTS")


def suggested_strike(resistance_price: float, current_price: float) -> dict:
    """Covered-call strike suggestion from the nearest resistance above price.

    Returns the raw resistance, the rounded listed strike, and the percentage
    gap between that strike and current price — report all three per spec
    section 3.5 step 3, since the rounded strike alone hides how far out
    it actually is.
    """
    rounded = round_strike(resistance_price)
    return {
        "raw_resistance": resistance_price,
        "suggested_strike": rounded,
        "pct_gap": (rounded - current_price) / current_price,
    }

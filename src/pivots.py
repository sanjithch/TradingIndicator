"""Pivot high/low detection and clustering into support/resistance levels.

Pure functions only — no I/O, no network, no disk access — so these are
straightforward to unit test against a hand-built bar fixture.

Bars are plain dicts shaped like fetch.py's output:
    {"t": iso_timestamp_str, "o": float, "h": float, "l": float, "c": float, "v": float}
"""

from __future__ import annotations

DEFAULT_WINDOW = 5
DEFAULT_CLUSTER_TOLERANCE = 0.005  # 0.5%
DEFAULT_MIN_TOUCH_COUNT = 2


def find_pivots(bars: list[dict], window: int = DEFAULT_WINDOW) -> list[dict]:
    """Detect pivot highs and lows using a symmetric lookback/lookahead window.

    A bar at index i is a pivot high if its high is strictly greater than the
    high of every bar in the `window` bars immediately before AND after it —
    same rule mirrored for pivot lows. Bars within `window` of either edge of
    the series can't be evaluated (not enough neighbours on one side) and are
    skipped, which is standard for swing-pivot detection.

    Returns a flat list of {"kind": "high"|"low", "price": float,
    "timestamp": str, "volume": float} — a single bar can produce both a
    high and a low pivot dict if it happens to be both.
    """
    n = len(bars)
    pivots: list[dict] = []
    if n <= 2 * window:
        return pivots

    for i in range(window, n - window):
        neighborhood = bars[i - window : i] + bars[i + 1 : i + 1 + window]
        bar = bars[i]

        if bar["h"] > max(b["h"] for b in neighborhood):
            pivots.append(
                {"kind": "high", "price": bar["h"], "timestamp": bar["t"], "volume": bar["v"]}
            )
        if bar["l"] < min(b["l"] for b in neighborhood):
            pivots.append(
                {"kind": "low", "price": bar["l"], "timestamp": bar["t"], "volume": bar["v"]}
            )

    return pivots


def cluster_pivots(
    pivots: list[dict],
    tolerance: float = DEFAULT_CLUSTER_TOLERANCE,
    min_touch_count: int = DEFAULT_MIN_TOUCH_COUNT,
) -> list[dict]:
    """Merge near-duplicate pivots into levels.

    Highs and lows are clustered separately (they become resistance and
    support respectively). Within each kind, pivots are sorted by price and
    grouped sequentially: a pivot joins the current cluster if it's within
    `tolerance` of that cluster's running mean price, else it starts a new
    one. Clusters with fewer than `min_touch_count` pivots are discarded —
    a single touch is noise, not a level.

    Returns a list of {"price": volume_weighted_mean, "touch_count": int,
    "last_touch": str, "level_type": "support"|"resistance"}.
    """
    levels: list[dict] = []

    for kind, level_type in (("high", "resistance"), ("low", "support")):
        kind_pivots = sorted((p for p in pivots if p["kind"] == kind), key=lambda p: p["price"])

        clusters: list[list[dict]] = []
        current: list[dict] = []
        for p in kind_pivots:
            if current:
                cluster_mean = sum(x["price"] for x in current) / len(current)
                if abs(p["price"] - cluster_mean) / cluster_mean > tolerance:
                    clusters.append(current)
                    current = []
            current.append(p)
        if current:
            clusters.append(current)

        for cluster in clusters:
            if len(cluster) < min_touch_count:
                continue
            total_volume = sum(x["volume"] for x in cluster)
            if total_volume > 0:
                vw_price = sum(x["price"] * x["volume"] for x in cluster) / total_volume
            else:
                vw_price = sum(x["price"] for x in cluster) / len(cluster)
            levels.append(
                {
                    "price": vw_price,
                    "touch_count": len(cluster),
                    "last_touch": max(x["timestamp"] for x in cluster),
                    "level_type": level_type,
                }
            )

    return levels

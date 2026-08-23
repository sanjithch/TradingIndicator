"""Volume profile and high-volume-node (HVN) identification.

Pure functions only — no I/O.
"""

from __future__ import annotations

DEFAULT_BUCKET_COUNT = 50
DEFAULT_HVN_PERCENTILE = 0.9  # top decile


def build_volume_profile(bars: list[dict], bucket_count: int = DEFAULT_BUCKET_COUNT) -> list[dict]:
    """Slice the bars' price range into `bucket_count` equal-width buckets and
    accumulate each bar's volume into the bucket containing its typical price
    (high + low + close) / 3.

    Returns a list of `bucket_count` dicts, ordered low to high price:
    {"low": float, "high": float, "volume": float}. If every bar's typical
    price is identical (or there are no bars), everything piles into a
    single degenerate bucket spanning that one value.
    """
    if not bars:
        return []

    typical_prices = [(b["h"] + b["l"] + b["c"]) / 3 for b in bars]
    lo, hi = min(typical_prices), max(typical_prices)

    if lo == hi:
        return [{"low": lo, "high": hi, "volume": sum(b["v"] for b in bars)}]

    width = (hi - lo) / bucket_count
    buckets = [{"low": lo + i * width, "high": lo + (i + 1) * width, "volume": 0.0} for i in range(bucket_count)]

    for bar, tp in zip(bars, typical_prices):
        idx = int((tp - lo) / width)
        idx = min(idx, bucket_count - 1)  # tp == hi lands exactly on the boundary
        buckets[idx]["volume"] += bar["v"]

    return buckets


def high_volume_nodes(buckets: list[dict], percentile: float = DEFAULT_HVN_PERCENTILE) -> list[dict]:
    """Return the buckets in the top `1 - percentile` share by volume — the
    high-volume nodes that act as magnets/barriers. Empty buckets (volume 0)
    are never included even if the percentile threshold is <= 0.
    """
    nonzero = [b for b in buckets if b["volume"] > 0]
    if not nonzero:
        return []

    sorted_volumes = sorted(b["volume"] for b in nonzero)
    threshold_idx = int(len(sorted_volumes) * percentile)
    threshold_idx = min(threshold_idx, len(sorted_volumes) - 1)
    threshold = sorted_volumes[threshold_idx]

    return [b for b in nonzero if b["volume"] >= threshold]


def price_in_hvn(price: float, hvns: list[dict]) -> bool:
    """True if `price` falls inside any high-volume-node bucket's [low, high) range."""
    return any(b["low"] <= price < b["high"] for b in hvns)

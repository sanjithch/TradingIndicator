"""Hand-built fixture so pivot/cluster output can be verified by eye.

Fixture layout (11 bars, window=2, index 0-10):
  index:   0   1   2    3   4   5   6   7   8    9  10
  high:   10  10  15   10  10  10  10  10  14   10  10
  low:     5   5   5    5   5   1   5   5   5    5   5

By construction:
  - i=2  high=15 beats its 4 neighbours (all 10) -> pivot high
  - i=5  low=1   beats its 4 neighbours (all 5)  -> pivot low
  - i=8  high=14 beats its 4 neighbours (all 10) -> pivot high
No other bar stands out from its neighbourhood, so those are the only three
pivots window=2 should find.
"""

from src.pivots import cluster_pivots, find_pivots

HIGHS = [10, 10, 15, 10, 10, 10, 10, 10, 14, 10, 10]
LOWS = [5, 5, 5, 5, 5, 1, 5, 5, 5, 5, 5]
VOLUMES = [100] * 11


def make_bars(highs=HIGHS, lows=LOWS, volumes=VOLUMES):
    return [
        {
            "t": f"2024-01-01T00:{i:02d}:00Z",
            "o": lows[i],
            "h": highs[i],
            "l": lows[i],
            "c": lows[i],
            "v": volumes[i],
        }
        for i in range(len(highs))
    ]


def test_find_pivots_detects_exactly_the_hand_verified_pivots():
    bars = make_bars()
    pivots = find_pivots(bars, window=2)

    highs_found = [(p["price"], p["timestamp"]) for p in pivots if p["kind"] == "high"]
    lows_found = [(p["price"], p["timestamp"]) for p in pivots if p["kind"] == "low"]

    assert highs_found == [(15, "2024-01-01T00:02:00Z"), (14, "2024-01-01T00:08:00Z")]
    assert lows_found == [(1, "2024-01-01T00:05:00Z")]


def test_find_pivots_skips_bars_too_close_to_either_edge():
    # window=2 needs 2 bars on each side, so only indices 2..8 are eligible
    # in an 11-bar series -- a spike planted at index 0 or 10 can't be seen.
    highs = HIGHS.copy()
    highs[0] = 100  # would dominate every neighbourhood if it were eligible
    bars = make_bars(highs=highs)
    pivots = find_pivots(bars, window=2)
    assert not any(p["price"] == 100 for p in pivots)


def test_find_pivots_too_short_series_returns_nothing():
    bars = make_bars()[:4]  # shorter than 2*window
    assert find_pivots(bars, window=2) == []


def test_cluster_pivots_merges_near_duplicates_and_scores_by_volume():
    # Two resistance touches 0.2% apart should merge into one level; a lone
    # touch 10% away is noise and must be dropped (min_touch_count=2).
    pivots = [
        {"kind": "high", "price": 100.0, "timestamp": "2024-01-01T00:00:00Z", "volume": 100},
        {"kind": "high", "price": 100.2, "timestamp": "2024-01-02T00:00:00Z", "volume": 300},
        {"kind": "high", "price": 110.0, "timestamp": "2024-01-03T00:00:00Z", "volume": 500},
    ]

    levels = cluster_pivots(pivots, tolerance=0.005, min_touch_count=2)

    assert len(levels) == 1
    level = levels[0]
    assert level["level_type"] == "resistance"
    assert level["touch_count"] == 2
    assert level["last_touch"] == "2024-01-02T00:00:00Z"
    # volume-weighted mean of 100.0@100 and 100.2@300
    expected = (100.0 * 100 + 100.2 * 300) / 400
    assert level["price"] == expected


def test_cluster_pivots_keeps_support_and_resistance_separate():
    pivots = [
        {"kind": "high", "price": 100.0, "timestamp": "t1", "volume": 10},
        {"kind": "high", "price": 100.1, "timestamp": "t2", "volume": 10},
        {"kind": "low", "price": 50.0, "timestamp": "t3", "volume": 10},
        {"kind": "low", "price": 50.05, "timestamp": "t4", "volume": 10},
    ]

    levels = cluster_pivots(pivots)
    types = sorted(level["level_type"] for level in levels)
    assert types == ["resistance", "support"]


def test_end_to_end_pipeline_from_fixture_produces_no_spurious_levels():
    # Every pivot in the fixture is a lone touch (touch_count=1), so with
    # the default min_touch_count=2 nothing should survive clustering.
    bars = make_bars()
    pivots = find_pivots(bars, window=2)
    levels = cluster_pivots(pivots)
    assert levels == []

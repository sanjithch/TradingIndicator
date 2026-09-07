import math

from src.technicals import pct_distance, rolling_high_low, rsi, sma


def make_bars(closes, highs=None, lows=None):
    highs = highs or closes
    lows = lows or closes
    return [
        {"t": f"2024-01-{i+1:02d}T00:00:00Z", "o": c, "h": h, "l": l, "c": c, "v": 100}
        for i, (c, h, l) in enumerate(zip(closes, highs, lows))
    ]


def test_rolling_high_low_uses_only_the_lookback_window():
    # last 3 bars have high=30/low=5 as the extremes; bar 0's high=100 and
    # low=1 are outside the window and must not leak in.
    bars = make_bars(closes=[10, 10, 10, 10], highs=[100, 20, 30, 25], lows=[1, 8, 5, 9])
    result = rolling_high_low(bars, lookback=3)
    assert result == {"support": 5, "resistance": 30, "bars_used": 3}


def test_rolling_high_low_uses_all_bars_when_fewer_than_lookback():
    bars = make_bars(closes=[10, 10], highs=[15, 20], lows=[5, 8])
    result = rolling_high_low(bars, lookback=20)
    assert result == {"support": 5, "resistance": 20, "bars_used": 2}


def test_rolling_high_low_empty_bars():
    assert rolling_high_low([], lookback=20) is None


def test_sma_averages_last_n_closes_only():
    bars = make_bars(closes=[100, 1, 2, 3, 4, 5])  # first bar (100) must be excluded
    assert sma(bars, period=3) == (3 + 4 + 5) / 3


def test_sma_none_when_not_enough_bars():
    bars = make_bars(closes=[1, 2])
    assert sma(bars, period=3) is None


def test_rsi_all_gains_is_100():
    closes = list(range(1, 17))  # 16 closes, 15 changes, all +1
    bars = make_bars(closes)
    assert rsi(bars, period=14) == 100.0


def test_rsi_all_losses_is_0():
    closes = list(range(16, 0, -1))
    bars = make_bars(closes)
    assert rsi(bars, period=14) == 0.0


def test_rsi_none_when_not_enough_bars():
    bars = make_bars([1, 2, 3])
    assert rsi(bars, period=14) is None


def test_rsi_hand_verified_mixed_series():
    # Wilder's classic worked example (New Concepts in Technical Trading
    # Systems). 15 closes = 14 changes = exactly period+1, so this exercises
    # only the seed average (no further Wilder smoothing steps run) —
    # gains/losses summed and averaged independently below, not by calling
    # back into the function under test.
    closes = [
        44, 44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10,
        45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
    ]
    changes = [round(closes[i] - closes[i - 1], 10) for i in range(1, len(closes))]
    gains = [c for c in changes if c > 0]
    losses = [-c for c in changes if c < 0]
    avg_gain = sum(gains) / 14
    avg_loss = sum(losses) / 14
    expected_rsi = 100 - 100 / (1 + avg_gain / avg_loss)

    bars = make_bars(closes)
    assert math.isclose(rsi(bars, period=14), expected_rsi)


def test_pct_distance_sign_and_none_propagation():
    assert pct_distance(110, 100) == 0.1
    assert pct_distance(90, 100) == -0.1
    assert pct_distance(100, None) is None
    assert pct_distance(None, 100) is None

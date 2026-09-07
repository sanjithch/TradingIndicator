from src.credit_spread import compute_technicals


def make_bars(closes):
    return [
        {"t": f"2024-01-{i+1:02d}T00:00:00Z", "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 100}
        for i, c in enumerate(closes)
    ]


def test_compute_technicals_none_when_no_bars():
    assert compute_technicals("AVGO", []) is None


def test_compute_technicals_shape_and_values():
    # 250 rising closes so every configured lookback/SMA/RSI window is satisfiable
    closes = [100 + i * 0.1 for i in range(250)]
    bars = make_bars(closes)

    result = compute_technicals("AVGO", bars)

    assert result["symbol"] == "AVGO"
    assert result["current_price"] == closes[-1]
    assert result["bar_count"] == 250

    # every configured lookback and SMA period must produce a row
    assert set(result["levels"].keys()) == {"20", "60", "120"}
    assert set(result["sma"].keys()) == {"50", "200"}

    # rising series: the last bar's high is the resistance for every lookback
    # (fixture sets high = close + 1)
    assert result["levels"]["20"]["resistance"] == closes[-1] + 1

    # monotonically rising closes -> RSI should be strongly bullish
    assert result["rsi14"] > 90

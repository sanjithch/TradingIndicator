import math

from src.calibrate_signal import parse_fred, parse_yahoo_adjclose
from src.macro_signal import BEARISH, BULLISH, NEUTRAL, backtest, classify, diff_bp, pct_change
from src.market import build_signal, parse_fred_series, parse_series


def test_pct_change_and_diff_bp():
    assert math.isclose(pct_change([100, 110], 1), 10.0)
    assert pct_change([100], 1) is None  # history too short
    assert pct_change([0, 5], 1) is None  # non-positive base
    assert round(diff_bp([4.80, 4.50], 1), 6) == -30.0


def test_classify_yield_drop_is_bullish():
    s = classify(wti_pct=0, y10_bp=-35)
    assert s["state"] == BULLISH and s["score"] == 1


def test_classify_yield_rise_is_bearish():
    assert classify(wti_pct=0, y10_bp=30)["state"] == BEARISH  # boundary is inclusive


def test_classify_oil_plus_rates_headwind_needs_both():
    assert classify(wti_pct=12, y10_bp=15)["state"] == BEARISH
    assert classify(wti_pct=12, y10_bp=5)["state"] == NEUTRAL  # oil up, yields not
    assert classify(wti_pct=2, y10_bp=15)["state"] == NEUTRAL  # yields up, oil not


def test_classify_rules_can_stack_and_cancel():
    s = classify(wti_pct=15, y10_bp=40)  # both bearish rules fire
    assert s["score"] == -2 and s["state"] == BEARISH
    assert [c["points"] for c in s["components"]] == [-1, -1]


def test_classify_missing_inputs():
    assert classify(wti_pct=5, y10_bp=None) is None
    s = classify(wti_pct=None, y10_bp=-40)
    assert s["state"] == BULLISH and "unavailable" in s["components"][1]["note"]


def test_backtest_separates_states_on_a_hand_built_series():
    # 10Y falls 40bp early on (-> BULLISH from day 20), then sits flat.
    # VOO then rises 1%/day for 20 days after that point, otherwise flat,
    # so BULLISH days must show a higher forward return than NEUTRAL ones.
    n = 80
    dates = [f"2020-01-{i + 1:02d}" if i < 31 else f"2020-02-{i - 30:02d}" if i < 60 else f"2020-03-{i - 59:02d}" for i in range(n)]
    y10 = [5.0] * 10 + [4.6] * (n - 10)  # -40bp step at index 10
    wti = [50.0] * n
    voo = [100.0] * 20 + [100.0 * 1.01 ** (i - 19) for i in range(20, 40)] + [100.0 * 1.01 ** 20] * (n - 40)
    out = backtest(dates, voo, wti, y10, horizon=20)
    bull, neutral = out["states"][BULLISH], out["states"][NEUTRAL]
    assert bull["n"] > 0 and neutral["n"] > 0
    assert bull["mean_pct"] > neutral["mean_pct"]


def test_backtest_drops_the_negative_oil_print():
    n = 60
    dates = [f"2020-01-{i + 1:02d}" if i < 31 else f"2020-02-{i - 30:02d}" for i in range(n)]
    wti = [50.0] * n
    wti[30] = -37.0  # Apr-2020 style print must be dropped, not crash on it
    out = backtest(dates, [100.0] * n, wti, [4.0] * n, horizon=20)
    assert out["n"] > 0


def test_backtest_empty_when_history_too_short():
    out = backtest(["2020-01-01"], [100.0], [50.0], [4.0])
    assert out["n"] == 0 and out["states"] == {}


def test_parsers_for_series_and_calibration():
    tsy = 'Date,"10 Yr"\n10/09/2026,5.24\n10/08/2026,\n10/07/2026,5.20\n'
    assert parse_series(tsy, "10 Yr") == [("2026-10-07", 5.20), ("2026-10-09", 5.24)]
    fred = "observation_date,DCOILWTICO\n2026-10-05,96.13\n2026-10-06,.\n2026-10-07,95.00\n"
    assert parse_fred_series(fred, "DCOILWTICO") == [("2026-10-05", 96.13), ("2026-10-07", 95.0)]
    multi = "observation_date,DGS10,DCOILWTICO\n2016-11-01,1.8,.\n2016-11-02,1.9,45.0\n1999-01-01,5.0,9.0\n"
    assert parse_fred(multi) == {"DGS10": {"2016-11-01": 1.8, "2016-11-02": 1.9}, "DCOILWTICO": {"2016-11-02": 45.0}}
    yahoo = {"chart": {"result": [{"timestamp": [1791572395], "indicators": {"adjclose": [{"adjclose": [500.0]}]}}]}}
    assert list(parse_yahoo_adjclose(yahoo).values()) == [500.0]


def test_build_signal_end_to_end():
    # Treasury CSV dates are MM/DD/YYYY
    rows = "\n".join(f"{(i // 28) + 1:02d}/{(i % 28) + 1:02d}/2026,{4.0 + i * 0.02:.2f}" for i in range(30))
    text = 'Date,"10 Yr"\n' + rows
    wti = [(f"2026-01-{i + 1:02d}", 50.0 + i) for i in range(30)]
    sig = build_signal(text, wti, {"baseline": {"mean_pct": 1.26}})
    assert sig["y10_20d_bp"] > 30  # rising 2bp/day for 20 days = +40bp
    assert sig["state"] == BEARISH
    assert sig["calibration"]["baseline"]["mean_pct"] == 1.26
    assert build_signal(None, wti, None) is None

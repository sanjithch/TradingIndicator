from datetime import datetime

from src.scoring import (
    determine_signal,
    recency_weight,
    round_strike,
    score_level,
    select_top_levels,
    suggested_strike,
)


def test_recency_weight_full_and_floor_and_interpolation():
    as_of = datetime(2024, 3, 1)
    assert recency_weight("2024-02-28T00:00:00", as_of) == 1.0  # 2 days ago, <= 5
    assert recency_weight("2023-12-01T00:00:00", as_of) == 0.2  # way past 60 days
    # exactly 32.5 days ago is the midpoint between 5 and 60 -> midpoint weight
    midpoint = datetime(2024, 3, 1) - datetime.fromisoformat("2024-01-27T12:00:00")
    assert 0.2 < recency_weight("2024-01-27T12:00:00", as_of) < 1.0


def test_score_level_combines_touch_recency_and_hvn():
    level = {"price": 100, "touch_count": 3, "last_touch": "2024-03-01T00:00:00", "level_type": "support"}
    as_of = datetime(2024, 3, 1)
    scored = score_level(level, in_hvn=True, as_of=as_of)
    # touch_count(3)*3 + recency(1.0)*2 + hvn_bonus(2) = 9 + 2 + 2 = 13
    assert scored["score"] == 13
    assert scored["in_hvn"] is True


def test_select_top_levels_splits_and_ranks():
    levels = [
        {"price": 90, "level_type": "support", "score": 5},
        {"price": 95, "level_type": "support", "score": 10},
        {"price": 110, "level_type": "resistance", "score": 3},
        {"price": 105, "level_type": "resistance", "score": 8},
        {"price": 100, "level_type": "support", "score": 999},  # equals current price, excluded
    ]
    result = select_top_levels(levels, current_price=100, top_n=3)
    assert [lv["price"] for lv in result["supports"]] == [95, 90]  # ranked by score desc
    assert [lv["price"] for lv in result["resistances"]] == [105, 110]


def test_determine_signal_all_branches():
    assert determine_signal(current_price=95, nearest_support=100, nearest_resistance=110) == "BROKEN_SUPPORT"
    assert determine_signal(current_price=100.5, nearest_support=100, nearest_resistance=110) == "BUY_ZONE"
    assert determine_signal(current_price=109.5, nearest_support=100, nearest_resistance=110) == "CALL_ZONE"
    assert determine_signal(current_price=105, nearest_support=100, nearest_resistance=110) == "NEUTRAL"
    assert determine_signal(current_price=105, nearest_support=None, nearest_resistance=None) == "NEUTRAL"


def test_round_strike_increment_tiers():
    assert round_strike(19.10) == 19.5   # <$25 -> $0.50 increments
    assert round_strike(150.20) == 151.0  # <$200 -> $1.00 increments
    assert round_strike(301.0) == 305.0   # >=$200 -> $5.00 increments, already-round stays put on ceil
    assert round_strike(300.01) == 305.0


def test_suggested_strike_reports_raw_and_gap():
    result = suggested_strike(resistance_price=151.2, current_price=148.0)
    assert result["raw_resistance"] == 151.2
    assert result["suggested_strike"] == 152.0
    assert round(result["pct_gap"], 4) == round((152.0 - 148.0) / 148.0, 4)

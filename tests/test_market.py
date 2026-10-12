import pytest

from src.market import keep_previous, parse_treasury_curve, parse_yahoo_quote

MATS = ["3 Mo", "2 Yr", "10 Yr"]

# Newest row first, like the real file; the 3 Mo cell is blank in the
# prior-day row to exercise the missing-value path.
CSV = (
    'Date,"3 Mo","2 Yr","10 Yr"\n'
    "10/09/2026,4.25,4.80,5.24\n"
    "10/08/2026,,4.75,5.22\n"
    "10/07/2026,4.20,4.70,5.20\n"
)


def yahoo(price=90.0, prev=92.0, symbol="CL=F", t=1791773073):
    return {"chart": {"result": [{"meta": {
        "symbol": symbol, "regularMarketPrice": price,
        "chartPreviousClose": prev, "regularMarketTime": t}}]}}


def test_yahoo_quote_change_and_pct():
    q = parse_yahoo_quote(yahoo(price=90.0, prev=100.0), "WTI crude")
    assert q["label"] == "WTI crude"
    assert q["change"] == -10.0
    assert q["change_pct"] == -10.0
    assert q["as_of"].endswith("+00:00")


def test_yahoo_quote_without_prev_close_has_no_change():
    p = yahoo()
    del p["chart"]["result"][0]["meta"]["chartPreviousClose"]
    q = parse_yahoo_quote(p, "x")
    assert q["change"] is None and q["change_pct"] is None


def test_yahoo_malformed_payload_raises():
    with pytest.raises((KeyError, IndexError, TypeError)):
        parse_yahoo_quote({"chart": {"result": None}}, "x")


def test_treasury_latest_prior_change_and_spread():
    c = parse_treasury_curve(CSV, MATS)
    assert c["as_of"] == "2026-10-09" and c["prior_as_of"] == "2026-10-08"
    ten = next(r for r in c["curve"] if r["maturity"] == "10Y")
    assert ten["rate"] == 5.24 and ten["change_bp"] == 2.0
    assert c["spread_2s10s_bp"] == 44.0  # (5.24 - 4.80) * 100


def test_treasury_blank_prior_cell_gives_no_change_not_a_crash():
    c = parse_treasury_curve(CSV, MATS)
    three = next(r for r in c["curve"] if r["maturity"] == "3M")
    assert three["rate"] == 4.25 and three["change_bp"] is None


def test_treasury_too_few_rows_is_none():
    assert parse_treasury_curve('Date,"2 Yr"\n10/09/2026,4.8\n', ["2 Yr"]) is None


def test_keep_previous_prefers_fresh_then_flags_stale():
    assert keep_previous({"v": 2}, {"v": 1}) == {"v": 2}
    assert keep_previous(None, {"v": 1}) == {"v": 1, "stale": True}
    assert keep_previous(None, None) is None

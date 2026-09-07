from datetime import datetime

from src.catalysts import upcoming_events

WATCHLIST = ["AVGO", "HPE", "MU", "DRAM", "SNDK", "IONQ"]


def make_seed(earnings=None, macro=None):
    return {"earnings": earnings or [], "macro": macro or []}


def test_direct_ticker_earnings_affects_only_itself():
    seed = make_seed(earnings=[
        {"ticker": "AVGO", "date": "2026-09-10", "timing": "pm", "verified": True, "is_sector_peer": False, "peer_group": None},
    ])
    events = upcoming_events(seed, now=datetime(2026, 9, 6), window_days=14, watchlist_tickers=WATCHLIST)
    assert len(events) == 1
    assert events[0]["affects"] == ["AVGO"]
    assert events[0]["is_sector_peer"] is False


def test_sector_peer_earnings_affects_whole_watchlist():
    seed = make_seed(earnings=[
        {"ticker": "NVDA", "date": "2026-09-10", "timing": "pm", "verified": True, "is_sector_peer": True, "peer_group": "memory_semis"},
    ])
    events = upcoming_events(seed, now=datetime(2026, 9, 6), window_days=14, watchlist_tickers=WATCHLIST)
    assert events[0]["affects"] == WATCHLIST
    assert events[0]["is_sector_peer"] is True
    assert events[0]["peer_group"] == "memory_semis"


def test_macro_event_affects_whole_watchlist():
    seed = make_seed(macro=[{"date": "2026-09-16", "type": "fomc", "title": "FOMC Decision"}])
    events = upcoming_events(seed, now=datetime(2026, 9, 6), window_days=14, watchlist_tickers=WATCHLIST)
    assert events[0]["category"] == "macro"
    assert events[0]["affects"] == WATCHLIST


def test_events_outside_window_are_excluded():
    seed = make_seed(
        earnings=[{"ticker": "AVGO", "date": "2026-12-09", "timing": "pm", "verified": True, "is_sector_peer": False, "peer_group": None}],
        macro=[{"date": "2026-08-01", "type": "cpi", "title": "CPI"}],  # in the past
    )
    events = upcoming_events(seed, now=datetime(2026, 9, 6), window_days=14, watchlist_tickers=WATCHLIST)
    assert events == []


def test_window_boundaries_are_inclusive():
    seed = make_seed(macro=[
        {"date": "2026-09-06", "type": "cpi", "title": "start of window"},
        {"date": "2026-09-20", "type": "ppi", "title": "end of window"},
        {"date": "2026-09-21", "type": "jobs_report", "title": "one day past"},
    ])
    events = upcoming_events(seed, now=datetime(2026, 9, 6), window_days=14, watchlist_tickers=WATCHLIST)
    titles = [e["title"] for e in events]
    assert "start of window" in titles
    assert "end of window" in titles
    assert "one day past" not in titles


def test_events_sorted_chronologically_across_categories():
    seed = make_seed(
        earnings=[{"ticker": "IONQ", "date": "2026-09-15", "timing": "am", "verified": True, "is_sector_peer": False, "peer_group": None}],
        macro=[{"date": "2026-09-08", "type": "cpi", "title": "CPI"}],
    )
    events = upcoming_events(seed, now=datetime(2026, 9, 6), window_days=14, watchlist_tickers=WATCHLIST)
    assert [e["date"] for e in events] == ["2026-09-08", "2026-09-15"]


def test_tentative_earnings_marked_in_title():
    seed = make_seed(earnings=[
        {"ticker": "HPE", "date": "2026-09-10", "timing": "pm", "verified": False, "is_sector_peer": False, "peer_group": None},
    ])
    events = upcoming_events(seed, now=datetime(2026, 9, 6), window_days=14, watchlist_tickers=WATCHLIST)
    assert "tentative" in events[0]["title"]

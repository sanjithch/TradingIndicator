"""Upcoming-catalysts filtering for the Credit Spread Watchlist tab.

Pure function only — no I/O. Takes the static seed data (loaded elsewhere
from data/catalysts_seed.json) plus "now", and returns the events that fall
in the next `window_days`, chronologically sorted, each tagged with which
watchlist tickers it's likely to affect.

Seed data is necessarily static (see data/catalysts_seed.json's _comment):
GitHub Actions can't reach Robinhood's earnings API (needs an authenticated
session this pipeline doesn't have), and the macro dates are official,
pre-announced-for-the-year schedules that don't need live fetching at all.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

MACRO_TITLES = {
    "cpi": "CPI",
    "ppi": "PPI",
    "jobs_report": "Jobs Report",
    "fomc": "FOMC Decision",
}


def _parse_date(s: str) -> date:
    return datetime.fromisoformat(s).date()


def _in_window(event_date: date, start: date, end: date) -> bool:
    return start <= event_date <= end


def upcoming_events(
    seed: dict,
    now: datetime,
    window_days: int,
    watchlist_tickers: list[str],
) -> list[dict]:
    """Returns events in [now, now + window_days], sorted chronologically.

    Each event dict: {date, category ("earnings"|"macro"), title, affects
    (list of watchlist tickers this is likely to move), is_sector_peer,
    source_ticker (the peer/watchlist ticker that reports, for earnings
    events only)}.

    Sector-peer earnings (is_sector_peer=True) are tagged as affecting the
    *entire* watchlist, not just their own sub-sector — per the panel's
    purpose, a big memory/semis or AI-infra print moves sentiment across
    the whole credit-spread group, not just its closest peers. Direct
    watchlist-ticker earnings affect only that one ticker. Macro events
    (CPI/PPI/FOMC/jobs) affect the whole watchlist too — broad market
    moves, not stock-specific ones.
    """
    start = now.date()
    end = start + timedelta(days=window_days)
    events: list[dict] = []

    for entry in seed.get("earnings", []):
        event_date = _parse_date(entry["date"])
        if not _in_window(event_date, start, end):
            continue
        is_peer = entry.get("is_sector_peer", False)
        events.append(
            {
                "date": entry["date"],
                "category": "earnings",
                "title": f"{entry['ticker']} earnings" + ("" if entry.get("verified", True) else " (tentative)"),
                "affects": list(watchlist_tickers) if is_peer else [entry["ticker"]],
                "is_sector_peer": is_peer,
                "source_ticker": entry["ticker"],
                "peer_group": entry.get("peer_group"),
            }
        )

    for entry in seed.get("macro", []):
        event_date = _parse_date(entry["date"])
        if not _in_window(event_date, start, end):
            continue
        events.append(
            {
                "date": entry["date"],
                "category": "macro",
                "title": entry.get("title") or MACRO_TITLES.get(entry["type"], entry["type"]),
                "affects": list(watchlist_tickers),
                "is_sector_peer": False,
                "source_ticker": None,
                "peer_group": None,
            }
        )

    events.sort(key=lambda e: e["date"])
    return events

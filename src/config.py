"""Tunable thresholds for the pipeline. Change values here, not in the
compute modules — pivots.py, volume.py, and scoring.py all take these as
parameters with these as their defaults.
"""

# --- pivots.py ---
PIVOT_WINDOW = 5
CLUSTER_TOLERANCE = 0.005  # 0.5% — merge pivots within this of each other
MIN_TOUCH_COUNT = 2  # discard clusters with fewer touches than this

# --- volume.py ---
VOLUME_BUCKET_COUNT = 50
HVN_PERCENTILE = 0.9  # top decile of buckets by volume = high-volume nodes

# --- scoring.py: score = touch_count*TOUCH_WEIGHT + recency_weight*RECENCY_WEIGHT + hvn_bonus ---
TOUCH_WEIGHT = 3
RECENCY_WEIGHT = 2
HVN_BONUS = 2

# Recency weight decays linearly from RECENCY_MAX_WEIGHT (touched within
# RECENCY_FULL_WEIGHT_DAYS) down to RECENCY_MIN_WEIGHT (touched
# RECENCY_MIN_WEIGHT_DAYS or longer ago).
RECENCY_FULL_WEIGHT_DAYS = 5
RECENCY_MIN_WEIGHT_DAYS = 60
RECENCY_MAX_WEIGHT = 1.0
RECENCY_MIN_WEIGHT = 0.2

TOP_N_LEVELS = 3  # top supports below price, top resistances above, each

# --- scoring.py: signal rules ---
PROXIMITY_PCT = 0.01  # 1% — "within 1% of a level" for BUY_ZONE / CALL_ZONE
NEUTRAL_PCT = 0.02  # >2% from both levels = NEUTRAL

# --- scoring.py: strike rounding — (price_ceiling, increment), first match wins ---
STRIKE_INCREMENTS = [
    (25.0, 0.50),
    (200.0, 1.00),
    (float("inf"), 5.00),
]

# --- Market strip: oil + Treasury yields (market.py) ---
# Yahoo Finance chart-API symbols -> display label. NYMEX front-month
# futures, ~10-15 min delayed.
MARKET_OIL_SYMBOLS = [("CL=F", "WTI crude"), ("BZ=F", "Brent crude")]
# Intraday 10Y yield index (quoted directly in percent), same Yahoo source.
MARKET_INTRADAY_YIELD = ("^TNX", "10Y (intraday)")
# Official Treasury par-curve columns to display, in this order.
MARKET_CURVE_MATURITIES = ["3 Mo", "2 Yr", "5 Yr", "10 Yr", "30 Yr"]

# --- Macro tilt signal (macro_signal.py), calibrated against VOO ---
MARKET_REFERENCE = ("VOO", "VOO (S&P 500)")  # the measuring stick; shown as a tile
SIGNAL_LOOKBACK = 20  # trading days for the oil / 10Y momentum windows
SIGNAL_YIELD_BP = 30  # 10Y 20d move that counts as a shock (either direction)
SIGNAL_OIL_PCT = 10  # WTI 20d rise (%) that counts as an oil shock...
SIGNAL_OIL_YIELD_BP = 10  # ...when the 10Y is also up at least this much

# --- Credit Spread Watchlist tab (technicals.py, catalysts.py, credit_spread.py) ---
CREDIT_SPREAD_TICKERS = ["AVGO", "HPE", "MU", "DRAM", "SNDK", "IONQ"]

# Daily-bar lookback windows for swing support/resistance (in trading days,
# used as a bar count against daily bars — not the 15-min bars the rest of
# the pipeline uses).
SWING_LOOKBACKS = [20, 60, 120]
SMA_PERIODS = [50, 200]
RSI_PERIOD = 14

# Calendar days of daily bars to fetch: needs to comfortably cover the
# longest SMA/lookback (200 trading days) plus weekends/holidays padding.
CREDIT_SPREAD_DAILY_LOOKBACK_DAYS = 300

# Catalysts panel: how far ahead to look, and which tickers "move the whole
# group" when they report — sector peers of the watchlist above, grouped by
# sub-sector for labeling only (any peer reporting is flagged against the
# *entire* watchlist, not just its own sub-sector — see catalysts.py).
CATALYST_WINDOW_DAYS = 14
SECTOR_PEER_GROUPS = {
    "memory_semis": ["WDC", "STX", "NVDA", "TSM"],
    "ai_infra": ["DELL", "SMCI", "ANET"],
    "quantum": ["RGTI", "QBTS"],
}

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

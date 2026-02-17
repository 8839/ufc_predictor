"""All tunable parameters for UFC Fight Predictor."""

import os

# Database
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "ufc.db")

# Scraping
REQUEST_DELAY = 1.5  # seconds between requests
BASE_URL = "http://www.ufcstats.com"

# FQS Weights (must sum to 1.0)
WEIGHT_OPPONENT_QUALITY = 0.30
WEIGHT_WIN_METHOD = 0.18
WEIGHT_LOSS_QUALITY = 0.14
WEIGHT_RECENCY = 0.13
WEIGHT_STREAK = 0.10
WEIGHT_CHAMPIONSHIP = 0.05
WEIGHT_ACTIVITY_RATE = 0.10

# Activity rate constants
ACTIVITY_LOOKBACK_YEARS = 3.0
ACTIVITY_OPTIMAL_FIGHTS_PER_YEAR = 2.5
ACTIVITY_RING_RUST_DAYS = 548

# Overall UFC finish rates (used as weight-class normalization baseline)
OVERALL_KO_RATE = 0.332
OVERALL_SUB_RATE = 0.198
OVERALL_DEC_RATE = 0.470

# Style evolution
STYLE_EVOLUTION_THRESHOLD = 0.40
STYLE_RECENT_FIGHT_COUNT = 5

# Win Method Points (keys match actual DB values from UFCStats)
WIN_METHOD_POINTS = {
    "KO/TKO": 10,
    "SUB": 9,
    "U-DEC": 7,
    "M-DEC": 6,
    "S-DEC": 5,
    "DQ": 4,
    "Overturned": 3,
    "CNC": 0,
}

# Recency decay
RECENCY_LAMBDA = 0.3

# Prediction caps
MIN_PROBABILITY = 0.15
MAX_PROBABILITY = 0.85

# Iterative FQS convergence
FQS_MAX_ITERATIONS = 5
FQS_CONVERGENCE_THRESHOLD = 0.1

# Refresh: number of days — only update fighters with fights newer than this
REFRESH_WINDOW_DAYS = 90

# Fuzzy match threshold
FUZZY_MATCH_THRESHOLD = 80

"""All tunable parameters for UFC Fight Predictor."""

import os

# Database
DB_PATH = os.path.join(os.path.dirname(__file__), "data", "ufc.db")

# Scraping
REQUEST_DELAY = 1.5  # seconds between requests
BASE_URL = "http://www.ufcstats.com"

# FQS Weights (must sum to 1.0)
WEIGHT_OPPONENT_QUALITY = 0.35
WEIGHT_WIN_METHOD = 0.20
WEIGHT_LOSS_QUALITY = 0.15
WEIGHT_RECENCY = 0.15
WEIGHT_STREAK = 0.10
WEIGHT_CHAMPIONSHIP = 0.05

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
FQS_MAX_ITERATIONS = 3
FQS_CONVERGENCE_THRESHOLD = 0.1

# Refresh: number of days — only update fighters with fights newer than this
REFRESH_WINDOW_DAYS = 90

# Fuzzy match threshold
FUZZY_MATCH_THRESHOLD = 80

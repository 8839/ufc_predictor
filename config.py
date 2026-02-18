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
STYLE_EVOLUTION_THRESHOLD = 0.25  # lowered from 0.40 — was too strict (zero fighters triggered)
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

# Age decline curve
AGE_PEAK_START = 28
AGE_PEAK_END = 32
AGE_GRADUAL_DECLINE_END = 35
AGE_STEEP_DECLINE_END = 38
AGE_FACTOR_FLOOR = 0.55
AGE_DECLINE_STYLE_MODIFIERS = {
    "Wrestler": 0.60,         # wrestlers age best (technique/control)
    "Grappler": 0.65,
    "Wrestle-Striker": 0.70,
    "Balanced": 0.80,
    "Pressure Fighter": 0.85, # cardio-dependent
    "Striker": 0.90,          # speed-dependent
    "Counter Striker": 0.95,  # reflex-dependent, ages worst
}
AGE_ADJUSTMENT_SCALE = 0.12
AGE_ADJUSTMENT_MAX = 0.06    # cap at +/-6%

# Stance matchup
STANCE_SOUTHPAW_VS_ORTHODOX = 0.020
STANCE_SWITCH_VS_ORTHODOX = 0.015
STANCE_SWITCH_VS_SOUTHPAW = 0.010
STANCE_STRIKER_AMPLIFIER = 1.5   # amplify in striker vs striker

# Prediction adjustments (widened from V2 hardcoded values)
PREDICTION_STRIKING_ADJ = 0.04    # was 0.03
PREDICTION_GRAPPLING_ADJ = 0.04   # was 0.03
PREDICTION_PHYSICAL_ADJ = 0.025   # was 0.02
PREDICTION_COMMON_OPP_ADJ = 0.03  # was 0.025

# Scraper validation
MIN_SIG_STRIKES_PER_ROUND = 5

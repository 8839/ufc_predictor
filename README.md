# UFC Fight Predictor

A data-driven MMA fight prediction system that scrapes fighter statistics from UFCStats.com and uses composite scoring algorithms to predict fight outcomes.

## How It Works

The predictor uses a multi-layered analysis pipeline:

1. **Data Collection** — Scrapes fighter profiles, fight histories, and per-fight statistics (strikes, takedowns, control time, etc.) from UFCStats.com into a local SQLite database.

2. **Fighter Quality Score (FQS)** — Computes a 0-100 composite score for each fighter using 7 weighted sub-scores:
   - Opponent Quality (30%) — Iteratively computed based on opponents' own FQS
   - Win Method Quality (18%) — Finishes score higher than decisions
   - Loss Quality (14%) — Losses to elite opponents penalized less
   - Recency (13%) — Recent fights weighted more via exponential decay
   - Streak Momentum (10%) — Win/loss streaks shift score
   - Activity Rate (10%) — Penalizes ring rust (>18 months inactive)
   - Championship Experience (5%) — Bonus for title fight history

3. **Head-to-Head Matchup Analysis** — Compares fighters across:
   - Striking (volume, accuracy, defense, absorption, grappling-adjusted SLpM)
   - Grappling (takedown offense/defense, submissions, control time)
   - Physical attributes (height, reach, weight, age)
   - Common opponent performance
   - Style classification and evolution detection

4. **Prediction Modifiers** — Adjustments applied to the base FQS comparison:
   - Striking/grappling/physical edges
   - Age decline curve (style-dependent: wrestlers age best, counter-strikers worst)
   - Stance matchup (southpaw advantage, switch stance bonus)
   - Knockout power differential
   - Common opponent results
   - Finish rate and method of victory prediction

## Project Structure

```
ufc_predictor/
├── main.py          # CLI entry point
├── config.py        # All tunable parameters
├── database.py      # SQLite schema and CRUD operations
├── scraper.py       # UFCStats.com web scraper
├── scoring.py       # Fighter Quality Score (FQS) engine
├── matchup.py       # Head-to-head matchup analysis
├── predictor.py     # Final prediction assembly and formatting
├── utils.py         # Fuzzy name matching utilities
├── requirements.txt
└── data/
    └── ufc.db       # SQLite database (generated after scraping)
```

## Setup

```bash
# Clone and install dependencies
cd ufc_predictor
pip install -r requirements.txt

# Build the database (first run — scrapes ~4000 fighters and ~7000 fights)
python main.py scrape --full
```

The full scrape takes a while due to rate limiting (1.5s between requests). Subsequent updates are much faster:

```bash
# Incremental refresh (only recent fighters)
python main.py scrape --refresh

# Re-scrape only fight stats (fixes data without full rebuild)
python main.py scrape --fight-stats
```

## Usage

### Predict a Fight

```bash
python main.py predict "Jon Jones" "Tom Aspinall"
```

Outputs a detailed breakdown including FQS scores, striking/grappling/physical analysis, age factors, stance matchup, predicted winner with confidence percentage, and predicted method of victory.

### View Fighter Profile

```bash
python main.py fighter "Islam Makhachev"
```

Shows the fighter's FQS breakdown, style classification, age factor, and key statistics.

### Track Prediction Accuracy

```bash
# View prediction history
python main.py history

# Record actual result to track accuracy
python main.py update-result --prediction-id 1 --winner "Jon Jones" --method "KO/TKO"
```

## Configuration

All tunable parameters are centralized in `config.py`:

- **FQS weights** — Adjust how much each sub-score contributes
- **Age decline curve** — Peak age range, decline rates, style modifiers
- **Stance matchup values** — Southpaw/switch advantages
- **Prediction adjustment scales** — How much each factor shifts the prediction
- **Scraper settings** — Request delay, validation thresholds

## Requirements

- Python 3.10+
- Dependencies: `requests`, `beautifulsoup4`, `thefuzz`, `python-Levenshtein`, `tabulate`

## Data Source

All fighter and fight data is scraped from [UFCStats.com](http://www.ufcstats.com), the official UFC statistics provider.

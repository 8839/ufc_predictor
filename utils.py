"""Fuzzy matching, date helpers, and formatting utilities."""

import re
from datetime import datetime, date

from thefuzz import fuzz, process

import database
from config import FUZZY_MATCH_THRESHOLD


def fuzzy_find_fighter(name: str, prompt_user: bool = True) -> dict | None:
    """Find a fighter by fuzzy name matching.

    Returns the matched fighter dict or None if no match found.
    If multiple close matches exist and prompt_user is True, prompts
    the user to select one.
    """
    all_fighters = database.get_all_fighters()
    if not all_fighters:
        print("No fighters in database. Run 'scrape --full' first.")
        return None

    names = {f["name"]: f for f in all_fighters}
    matches = process.extract(name, names.keys(), scorer=fuzz.token_sort_ratio, limit=5)

    # Filter to those above threshold — extract returns (name, score) or (name, score, key)
    good_matches = [(m[0], m[1]) for m in matches if m[1] >= FUZZY_MATCH_THRESHOLD]

    if not good_matches:
        print(f"No fighter found matching '{name}'.")
        return None

    # Exact or very high confidence single match
    if good_matches[0][1] >= 95:
        return names[good_matches[0][0]]

    if len(good_matches) == 1:
        return names[good_matches[0][0]]

    if not prompt_user:
        return names[good_matches[0][0]]

    # Multiple matches — ask user to pick
    print(f"\nMultiple matches for '{name}':")
    for i, (match_name, score) in enumerate(good_matches, 1):
        f = names[match_name]
        record = f"{f['wins']}-{f['losses']}-{f['draws']}"
        print(f"  {i}. {match_name} ({record}) [{score}% match]")

    while True:
        try:
            choice = input("\nSelect fighter number (or 0 to cancel): ").strip()
            idx = int(choice)
            if idx == 0:
                return None
            if 1 <= idx <= len(good_matches):
                return names[good_matches[idx - 1][0]]
        except (ValueError, EOFError):
            pass
        print("Invalid selection. Try again.")


def parse_height(height_str: str) -> int | None:
    """Parse a height string like '5\\'10\"' or '5' 10\"' into total inches."""
    if not height_str or height_str.strip() == "--":
        return None
    match = re.search(r"(\d+)'?\s*(\d+)", height_str)
    if match:
        feet = int(match.group(1))
        inches = int(match.group(2))
        return feet * 12 + inches
    return None


def parse_reach(reach_str: str) -> float | None:
    """Parse reach string like '76\"' or '76.0\"' into float inches."""
    if not reach_str or reach_str.strip() == "--":
        return None
    match = re.search(r"([\d.]+)", reach_str)
    if match:
        return float(match.group(1))
    return None


def parse_weight(weight_str: str) -> int | None:
    """Parse weight string like '185 lbs.' into int pounds."""
    if not weight_str or weight_str.strip() == "--":
        return None
    match = re.search(r"(\d+)", weight_str)
    if match:
        return int(match.group(1))
    return None


def parse_percentage(pct_str: str) -> float | None:
    """Parse a percentage string like '54%' into 0.54."""
    if not pct_str or pct_str.strip() == "--":
        return None
    match = re.search(r"([\d.]+)", pct_str)
    if match:
        return float(match.group(1)) / 100.0
    return None


def parse_stat_float(stat_str: str) -> float | None:
    """Parse a stat string like '4.32' into a float."""
    if not stat_str or stat_str.strip() == "--":
        return None
    try:
        return float(stat_str.strip())
    except ValueError:
        return None


def parse_date(date_str: str) -> str | None:
    """Parse various date formats into YYYY-MM-DD."""
    if not date_str or date_str.strip() == "--":
        return None
    date_str = date_str.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def parse_record(record_str: str) -> tuple[int, int, int, int]:
    """Parse record string like '22-5-0 (1 NC)' into (wins, losses, draws, nc)."""
    nc = 0
    nc_match = re.search(r"\((\d+)\s*NC\)", record_str, re.IGNORECASE)
    if nc_match:
        nc = int(nc_match.group(1))
    parts = re.match(r"(\d+)-(\d+)-(\d+)", record_str.strip())
    if parts:
        return int(parts.group(1)), int(parts.group(2)), int(parts.group(3)), nc
    return 0, 0, 0, nc


def parse_control_time(time_str: str) -> int:
    """Parse control time string like '4:32' into total seconds."""
    if not time_str or time_str.strip() in ("--", ""):
        return 0
    match = re.match(r"(\d+):(\d+)", time_str.strip())
    if match:
        return int(match.group(1)) * 60 + int(match.group(2))
    return 0


def parse_strikes(strikes_str: str) -> tuple[int, int]:
    """Parse strikes string like '48 of 92' into (landed, attempted)."""
    if not strikes_str or strikes_str.strip() == "--":
        return 0, 0
    match = re.match(r"(\d+)\s+of\s+(\d+)", strikes_str.strip())
    if match:
        return int(match.group(1)), int(match.group(2))
    return 0, 0


def years_since(date_str: str | None) -> float:
    """Calculate years elapsed since a given YYYY-MM-DD date string."""
    if not date_str:
        return 0.0
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        delta = datetime.now() - dt
        return delta.days / 365.25
    except ValueError:
        return 0.0


def calculate_age(dob: str | None) -> int | None:
    """Calculate current age from DOB string (YYYY-MM-DD)."""
    if not dob:
        return None
    try:
        born = datetime.strptime(dob, "%Y-%m-%d").date()
        today = date.today()
        return today.year - born.year - ((today.month, today.day) < (born.month, born.day))
    except ValueError:
        return None


def format_height(inches: int | None) -> str:
    """Format height in inches to feet'inches\" string."""
    if inches is None:
        return "N/A"
    feet = inches // 12
    remaining = inches % 12
    return f"{feet}'{remaining}\""


def confidence_label(probability: float) -> str:
    """Map a win probability (0-1) to a confidence label."""
    pct = probability * 100
    if pct < 55:
        return "Toss-up \u2014 very slight edge"
    elif pct < 62:
        return "Lean \u2014 moderate edge"
    elif pct < 70:
        return "Confident \u2014 clear edge"
    elif pct < 78:
        return "Strong \u2014 significant advantage"
    else:
        return "Very Strong \u2014 dominant advantage"

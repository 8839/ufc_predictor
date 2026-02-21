"""Head-to-head matchup comparison logic."""

import database
import utils
from config import (
    STYLE_EVOLUTION_THRESHOLD, STYLE_RECENT_FIGHT_COUNT,
    AGE_PEAK_START, AGE_PEAK_END, AGE_GRADUAL_DECLINE_END,
    AGE_STEEP_DECLINE_END, AGE_FACTOR_FLOOR, AGE_DECLINE_STYLE_MODIFIERS,
    AGE_ADJUSTMENT_SCALE, AGE_ADJUSTMENT_MAX,
    STANCE_SOUTHPAW_VS_ORTHODOX, STANCE_SWITCH_VS_ORTHODOX,
    STANCE_SWITCH_VS_SOUTHPAW, STANCE_STRIKER_AMPLIFIER,
)
from scoring import calc_fqs


# ---------------------------------------------------------------------------
# Fight-stats helpers (per-fight data from fight_stats table)
# ---------------------------------------------------------------------------

def _recent_fight_stats(fighter_id: str, n: int = 5,
                        cutoff_date: str | None = None) -> list[dict]:
    """Get stats for a fighter's last N fights (most recent first)."""
    fights = database.get_fighter_fights(fighter_id, cutoff_date)
    recent = []
    for fight in fights[:n]:
        stats = database.get_fight_stats(fight["id"], fighter_id)
        if stats:
            stats["event_date"] = fight["event_date"]
            recent.append(stats)
    return recent


def _aggregate_fight_stats(stats_list: list[dict]) -> dict:
    """Aggregate a list of fight_stats into averages."""
    if not stats_list:
        return {
            "avg_kd": 0, "avg_sig_landed": 0, "avg_sig_attempted": 0,
            "sig_accuracy": 0, "avg_td_landed": 0, "avg_td_attempted": 0,
            "td_accuracy": 0, "avg_sub_att": 0, "avg_ctrl": 0, "count": 0,
        }
    n = len(stats_list)
    total_kd = sum(s.get("knockdowns", 0) for s in stats_list)
    total_sig_l = sum(s.get("sig_strikes_landed", 0) for s in stats_list)
    total_sig_a = sum(s.get("sig_strikes_attempted", 0) for s in stats_list)
    total_td_l = sum(s.get("takedowns_landed", 0) for s in stats_list)
    total_td_a = sum(s.get("takedowns_attempted", 0) for s in stats_list)
    total_sub = sum(s.get("submission_attempts", 0) for s in stats_list)
    total_ctrl = sum(s.get("control_time_seconds", 0) for s in stats_list)
    return {
        "avg_kd": total_kd / n,
        "avg_sig_landed": total_sig_l / n,
        "avg_sig_attempted": total_sig_a / n,
        "sig_accuracy": total_sig_l / total_sig_a if total_sig_a > 0 else 0,
        "avg_td_landed": total_td_l / n,
        "avg_td_attempted": total_td_a / n,
        "td_accuracy": total_td_l / total_td_a if total_td_a > 0 else 0,
        "avg_sub_att": total_sub / n,
        "avg_ctrl": total_ctrl / n,
        "count": n,
    }


# ---------------------------------------------------------------------------
# 6.1 FQS Comparison
# ---------------------------------------------------------------------------

def fqs_comparison(f1_id: str, f2_id: str, fqs_cache: dict | None = None,
                   wc_baselines: dict | None = None,
                   cutoff_date: str | None = None) -> dict:
    """Return FQS breakdown for both fighters."""
    return {
        "fighter1": calc_fqs(f1_id, fqs_cache, wc_baselines, cutoff_date),
        "fighter2": calc_fqs(f2_id, fqs_cache, wc_baselines, cutoff_date),
    }


# ---------------------------------------------------------------------------
# 6.2 Striking Analysis
# ---------------------------------------------------------------------------

def striking_analysis(f1: dict, f2: dict,
                      cutoff_date: str | None = None) -> dict:
    """Compare striking stats using career averages + recent fight stats."""
    # Career stats
    f1_slpm = f1.get("sig_strikes_landed_per_min") or 0.0
    f2_slpm = f2.get("sig_strikes_landed_per_min") or 0.0
    f1_acc = f1.get("sig_strike_accuracy") or 0.0
    f2_acc = f2.get("sig_strike_accuracy") or 0.0
    f1_sapm = f1.get("sig_strikes_absorbed_per_min") or 0.0
    f2_sapm = f2.get("sig_strikes_absorbed_per_min") or 0.0
    f1_def = f1.get("sig_strike_defense") or 0.0
    f2_def = f2.get("sig_strike_defense") or 0.0

    # Recent form (last 5 fights) — blend with career stats for a more current picture
    f1_recent = _aggregate_fight_stats(_recent_fight_stats(f1["id"], 5, cutoff_date))
    f2_recent = _aggregate_fight_stats(_recent_fight_stats(f2["id"], 5, cutoff_date))

    # Knockdown rate from fight stats (career + recent)
    f1_kd_rate = _knockdown_rate(f1["id"], cutoff_date)
    f2_kd_rate = _knockdown_rate(f2["id"], cutoff_date)
    f1_recent_kd = f1_recent["avg_kd"]
    f2_recent_kd = f2_recent["avg_kd"]

    # Blend recent accuracy with career (40% recent, 60% career)
    if f1_recent["count"] >= 3:
        f1_acc_blend = f1_acc * 0.6 + f1_recent["sig_accuracy"] * 0.4
    else:
        f1_acc_blend = f1_acc
    if f2_recent["count"] >= 3:
        f2_acc_blend = f2_acc * 0.6 + f2_recent["sig_accuracy"] * 0.4
    else:
        f2_acc_blend = f2_acc

    # Grappling context: fighters with high TD avg spend more time grappling,
    # so their lower SLpM reflects less striking time, not worse striking.
    # Boost effective SLpM proportionally to takedown activity.
    f1_td_avg = f1.get("takedown_avg_per_15min") or 0.0
    f2_td_avg = f2.get("takedown_avg_per_15min") or 0.0
    f1_slpm_adj = f1_slpm * (1.0 + f1_td_avg * 0.08)
    f2_slpm_adj = f2_slpm * (1.0 + f2_td_avg * 0.08)

    # Determine edge: higher output (grappling-adjusted), accuracy, defense; lower absorbed
    # KD power is handled as a separate adjustment in predictor.py to avoid double-counting
    f1_score = f1_slpm_adj + f1_acc_blend * 10 + f1_def * 10 - f1_sapm
    f2_score = f2_slpm_adj + f2_acc_blend * 10 + f2_def * 10 - f2_sapm

    edge = f1["name"] if f1_score >= f2_score else f2["name"]
    edge_id = f1["id"] if f1_score >= f2_score else f2["id"]

    return {
        "edge": edge,
        "edge_id": edge_id,
        "fighter1": {
            "slpm": f1_slpm, "accuracy": f1_acc,
            "sapm": f1_sapm, "defense": f1_def,
            "kd_rate": f1_kd_rate,
            "recent_sig_landed": f1_recent["avg_sig_landed"],
            "recent_kd": f1_recent_kd,
        },
        "fighter2": {
            "slpm": f2_slpm, "accuracy": f2_acc,
            "sapm": f2_sapm, "defense": f2_def,
            "kd_rate": f2_kd_rate,
            "recent_sig_landed": f2_recent["avg_sig_landed"],
            "recent_kd": f2_recent_kd,
        },
        "diff_slpm": round(f1_slpm - f2_slpm, 1),
        "diff_acc": round((f1_acc - f2_acc) * 100, 1),
        "diff_sapm": round(f1_sapm - f2_sapm, 1),
    }


def _knockdown_rate(fighter_id: str, cutoff_date: str | None = None) -> float:
    """Knockdowns per fight for a fighter."""
    stats = database.get_fighter_all_stats(fighter_id, cutoff_date)
    if not stats:
        return 0.0
    total_kd = sum(s.get("knockdowns", 0) for s in stats)
    return total_kd / len(stats)


# ---------------------------------------------------------------------------
# 6.3 Grappling Analysis
# ---------------------------------------------------------------------------

def grappling_analysis(f1: dict, f2: dict,
                       cutoff_date: str | None = None) -> dict:
    """Compare grappling stats using career averages + recent fight stats."""
    f1_td = f1.get("takedown_avg_per_15min") or 0.0
    f2_td = f2.get("takedown_avg_per_15min") or 0.0
    f1_td_acc = f1.get("takedown_accuracy") or 0.0
    f2_td_acc = f2.get("takedown_accuracy") or 0.0
    f1_td_def = f1.get("takedown_defense") or 0.0
    f2_td_def = f2.get("takedown_defense") or 0.0
    f1_sub = f1.get("submission_avg_per_15min") or 0.0
    f2_sub = f2.get("submission_avg_per_15min") or 0.0

    # Recent form for control time and TD accuracy (more current than career avg)
    f1_recent = _aggregate_fight_stats(_recent_fight_stats(f1["id"], 5, cutoff_date))
    f2_recent = _aggregate_fight_stats(_recent_fight_stats(f2["id"], 5, cutoff_date))

    # Use recent control time if available, otherwise career
    f1_ctrl = f1_recent["avg_ctrl"] if f1_recent["count"] >= 3 else _avg_control_time(f1["id"], cutoff_date)
    f2_ctrl = f2_recent["avg_ctrl"] if f2_recent["count"] >= 3 else _avg_control_time(f2["id"], cutoff_date)

    # Weight TD volume and control time heavily — these indicate actual grappling activity.
    # TD accuracy is only meaningful with volume, so scale it by TD avg.
    # TD defense is always relevant regardless of offensive volume.
    f1_score = (
        f1_td * 3.0              # takedown volume (primary offensive grappling indicator)
        + f1_td_acc * f1_td * 2  # accuracy scaled by volume (high acc + low volume = low score)
        + f1_td_def * 4.0        # defense is always important
        + f1_sub * 2.0           # submission threat
        + f1_ctrl / 30           # control time (seconds → ~1 point per 30s avg)
    )
    f2_score = (
        f2_td * 3.0
        + f2_td_acc * f2_td * 2
        + f2_td_def * 4.0
        + f2_sub * 2.0
        + f2_ctrl / 30
    )

    edge = f1["name"] if f1_score >= f2_score else f2["name"]
    edge_id = f1["id"] if f1_score >= f2_score else f2["id"]

    return {
        "edge": edge,
        "edge_id": edge_id,
        "fighter1": {
            "td_avg": f1_td, "td_acc": f1_td_acc, "td_def": f1_td_def,
            "sub_avg": f1_sub, "ctrl_avg": f1_ctrl,
        },
        "fighter2": {
            "td_avg": f2_td, "td_acc": f2_td_acc, "td_def": f2_td_def,
            "sub_avg": f2_sub, "ctrl_avg": f2_ctrl,
        },
        "diff_td": round(f1_td - f2_td, 1),
        "diff_td_acc": round((f1_td_acc - f2_td_acc) * 100, 1),
        "diff_ctrl": round(f1_ctrl - f2_ctrl, 0),
    }


def _avg_control_time(fighter_id: str, cutoff_date: str | None = None) -> float:
    """Average control time in seconds per fight."""
    stats = database.get_fighter_all_stats(fighter_id, cutoff_date)
    if not stats:
        return 0.0
    total = sum(s.get("control_time_seconds", 0) for s in stats)
    return total / len(stats)


# ---------------------------------------------------------------------------
# 6.4a Age Decline Curve
# ---------------------------------------------------------------------------

def compute_age_factor(age: int | None, style: str) -> float:
    """Compute age factor (0.55-1.0) using a piecewise linear decline curve.

    Peak at 28-32 (factor=1.0), gradual decline 33-35 (-0.02/yr),
    steep 36-38 (-0.03/yr), severe 39+ (-0.04/yr).
    Style modifies only the decline portion.
    """
    if age is None:
        return 0.95  # conservative default

    if age <= AGE_PEAK_END:
        return 1.0

    style_mod = AGE_DECLINE_STYLE_MODIFIERS.get(style, 0.80)

    if age <= AGE_GRADUAL_DECLINE_END:
        years_past = age - AGE_PEAK_END
        raw_decline = years_past * 0.02
    elif age <= AGE_STEEP_DECLINE_END:
        gradual_years = AGE_GRADUAL_DECLINE_END - AGE_PEAK_END  # 3 years
        steep_years = age - AGE_GRADUAL_DECLINE_END
        raw_decline = gradual_years * 0.02 + steep_years * 0.03
    else:
        gradual_years = AGE_GRADUAL_DECLINE_END - AGE_PEAK_END  # 3 years
        steep_years = AGE_STEEP_DECLINE_END - AGE_GRADUAL_DECLINE_END  # 3 years
        severe_years = age - AGE_STEEP_DECLINE_END
        raw_decline = gradual_years * 0.02 + steep_years * 0.03 + severe_years * 0.04

    adjusted_decline = raw_decline * style_mod
    factor = max(AGE_FACTOR_FLOOR, 1.0 - adjusted_decline)
    return round(factor, 3)


def age_matchup_analysis(f1: dict, f2: dict,
                         f1_style: str, f2_style: str) -> dict:
    """Compute age factors for both fighters and return matchup adjustment.

    Returns dict with age factors, ages, and a clamped adjustment value.
    Positive adjustment favors fighter 1.
    """
    f1_age = utils.calculate_age(f1.get("dob"))
    f2_age = utils.calculate_age(f2.get("dob"))

    f1_factor = compute_age_factor(f1_age, f1_style)
    f2_factor = compute_age_factor(f2_age, f2_style)

    raw_diff = f1_factor - f2_factor
    adjustment = max(-AGE_ADJUSTMENT_MAX,
                     min(AGE_ADJUSTMENT_MAX, raw_diff * AGE_ADJUSTMENT_SCALE))

    return {
        "fighter1_age": f1_age,
        "fighter2_age": f2_age,
        "fighter1_factor": f1_factor,
        "fighter2_factor": f2_factor,
        "fighter1_style": f1_style,
        "fighter2_style": f2_style,
        "adjustment": round(adjustment, 4),
    }


# ---------------------------------------------------------------------------
# 6.4b Stance Matchup
# ---------------------------------------------------------------------------

def stance_matchup_adjustment(f1: dict, f2: dict,
                              f1_style: str, f2_style: str) -> tuple[float, str]:
    """Return a probability adjustment and description for stance matchup.

    Southpaw vs Orthodox: favors southpaw (+0.020).
    Switch vs Orthodox: favors switch (+0.015).
    Switch vs Southpaw: favors switch (+0.010).
    Same stance: 0.0.
    Amplified by 1.5x when both fighters are strikers.
    Positive value favors fighter 1.
    """
    s1 = (f1.get("stance") or "").strip()
    s2 = (f2.get("stance") or "").strip()

    if not s1 or not s2 or s1 == s2:
        return 0.0, ""

    striker_styles = ("Striker", "Counter Striker", "Pressure Fighter")
    both_strikers = f1_style in striker_styles and f2_style in striker_styles

    adjustment = 0.0
    desc = ""

    # Determine advantage based on stance pairing
    if s1 == "Southpaw" and s2 == "Orthodox":
        adjustment = STANCE_SOUTHPAW_VS_ORTHODOX
        desc = f"Southpaw vs Orthodox — favors {f1['name']}"
    elif s1 == "Orthodox" and s2 == "Southpaw":
        adjustment = -STANCE_SOUTHPAW_VS_ORTHODOX
        desc = f"Southpaw vs Orthodox — favors {f2['name']}"
    elif s1 == "Switch" and s2 == "Orthodox":
        adjustment = STANCE_SWITCH_VS_ORTHODOX
        desc = f"Switch vs Orthodox — favors {f1['name']}"
    elif s1 == "Orthodox" and s2 == "Switch":
        adjustment = -STANCE_SWITCH_VS_ORTHODOX
        desc = f"Switch vs Orthodox — favors {f2['name']}"
    elif s1 == "Switch" and s2 == "Southpaw":
        adjustment = STANCE_SWITCH_VS_SOUTHPAW
        desc = f"Switch vs Southpaw — favors {f1['name']}"
    elif s1 == "Southpaw" and s2 == "Switch":
        adjustment = -STANCE_SWITCH_VS_SOUTHPAW
        desc = f"Switch vs Southpaw — favors {f2['name']}"

    if adjustment != 0.0 and both_strikers:
        adjustment *= STANCE_STRIKER_AMPLIFIER
        desc += " (amplified: both strikers)"

    return round(adjustment, 4), desc


# ---------------------------------------------------------------------------
# 6.4 Physical Attribute Analysis
# ---------------------------------------------------------------------------

def physical_analysis(f1: dict, f2: dict) -> dict:
    """Compare physical attributes."""
    f1_reach = f1.get("reach_inches") or 0
    f2_reach = f2.get("reach_inches") or 0
    f1_height = f1.get("height_inches") or 0
    f2_height = f2.get("height_inches") or 0
    f1_age = utils.calculate_age(f1.get("dob"))
    f2_age = utils.calculate_age(f2.get("dob"))

    edge_id = None
    edge = "Even"
    reach_diff = f1_reach - f2_reach
    height_diff = f1_height - f2_height
    physical_score = reach_diff * 0.5 + height_diff * 0.3

    if physical_score > 0:
        edge = f1["name"]
        edge_id = f1["id"]
    elif physical_score < 0:
        edge = f2["name"]
        edge_id = f2["id"]

    return {
        "edge": edge,
        "edge_id": edge_id,
        "reach_diff": reach_diff,
        "height_diff": height_diff,
        "fighter1_age": f1_age,
        "fighter2_age": f2_age,
        "fighter1_stance": f1.get("stance"),
        "fighter2_stance": f2.get("stance"),
    }


# ---------------------------------------------------------------------------
# 6.5 Common Opponent Analysis
# ---------------------------------------------------------------------------

def common_opponent_analysis(f1_id: str, f2_id: str,
                             cutoff_date: str | None = None) -> dict:
    """Find common opponents and compare results."""
    f1_fights = database.get_fighter_fights(f1_id, cutoff_date)
    f2_fights = database.get_fighter_fights(f2_id, cutoff_date)

    def _opponents(fights, fighter_id):
        opps = {}
        for fight in fights:
            opp_id = (
                fight["fighter2_id"]
                if fight["fighter1_id"] == fighter_id
                else fight["fighter1_id"]
            )
            opps[opp_id] = fight
        return opps

    f1_opps = _opponents(f1_fights, f1_id)
    f2_opps = _opponents(f2_fights, f2_id)

    common_ids = set(f1_opps.keys()) & set(f2_opps.keys())

    comparisons = []
    f1_advantage = 0
    f2_advantage = 0

    for opp_id in common_ids:
        opp = database.get_fighter(opp_id)
        opp_name = opp["name"] if opp else opp_id

        fight1 = f1_opps[opp_id]
        fight2 = f2_opps[opp_id]

        f1_won = fight1["winner_id"] == f1_id
        f2_won = fight2["winner_id"] == f2_id

        f1_result = "won" if f1_won else "lost"
        f2_result = "won" if f2_won else "lost"

        f1_method = fight1["win_method"] or ""
        f2_method = fight2["win_method"] or ""
        f1_round = f"R{fight1['finish_round']}" if fight1["finish_round"] else ""
        f2_round = f"R{fight2['finish_round']}" if fight2["finish_round"] else ""

        f1_desc = f"{f1_result} ({f1_method} {f1_round})".strip()
        f2_desc = f"{f2_result} ({f2_method} {f2_round})".strip()

        if f1_won and not f2_won:
            f1_advantage += 1
        elif f2_won and not f1_won:
            f2_advantage += 1

        comparisons.append({
            "opponent_name": opp_name,
            "fighter1_result": f1_desc,
            "fighter2_result": f2_desc,
        })

    edge = "Even"
    edge_id = None
    if f1_advantage > f2_advantage:
        edge_id = f1_id
    elif f2_advantage > f1_advantage:
        edge_id = f2_id

    return {
        "count": len(common_ids),
        "comparisons": comparisons,
        "edge_id": edge_id,
        "f1_advantage": f1_advantage,
        "f2_advantage": f2_advantage,
    }


# ---------------------------------------------------------------------------
# 6.6 Style Classification & Matchup
# ---------------------------------------------------------------------------

def classify_style(stats: dict) -> str:
    """Classify a fighter's primary style based on stat profile.

    Accepts either a fighter dict (career stats keys) or a rate dict
    with generic keys (slpm, td_avg, sub_avg, str_acc, str_def, td_def).

    Styles:
    - Wrestler: high takedown volume, uses wrestling to control
    - Grappler: submission threat, works off back or in scrambles
    - Striker: high striking output, low takedown usage
    - Wrestle-Striker: mixes wrestling with striking, moderate both
    - Pressure Fighter: high output everywhere, pushes pace
    - Counter Striker: lower output but high accuracy and defense
    """
    # Support both fighter-dict keys and generic rate keys
    slpm = stats.get("slpm") or stats.get("sig_strikes_landed_per_min") or 0.0
    td_avg = stats.get("td_avg") or stats.get("takedown_avg_per_15min") or 0.0
    sub_avg = stats.get("sub_avg") or stats.get("submission_avg_per_15min") or 0.0
    str_acc = stats.get("str_acc") or stats.get("sig_strike_accuracy") or 0.0
    str_def = stats.get("str_def") or stats.get("sig_strike_defense") or 0.0

    # Heavy wrestler — high TD volume is the primary indicator
    if td_avg >= 3.0:
        return "Wrestler"

    # Grappler — submission threat with some takedown activity
    if sub_avg >= 1.5 and td_avg >= 1.0:
        return "Grappler"

    # Pure striker — high striking, low wrestling
    if slpm >= 4.5 and td_avg < 1.0:
        # Counter striker variant: lower volume but high accuracy + defense
        if slpm < 5.5 and str_acc >= 0.50 and str_def >= 0.60:
            return "Counter Striker"
        return "Striker"

    # Wrestle-striker — meaningful output in both
    if td_avg >= 1.5 and slpm >= 3.0:
        return "Wrestle-Striker"

    # Pressure fighter — high output across the board
    if slpm >= 4.0 and (td_avg >= 1.0 or sub_avg >= 0.5):
        return "Pressure Fighter"

    # Counter striker — lower volume but efficient
    if str_acc >= 0.50 and str_def >= 0.60 and slpm >= 2.5:
        return "Counter Striker"

    return "Balanced"


def _recent_activity_profile(stats_list: list[dict]) -> dict | None:
    """Compute the proportion of striking vs grappling in recent fights.

    Returns {striking_share, grappling_share, sub_share} where each is 0-1,
    or None if insufficient data.  Takedowns and submissions are weighted
    by 10x to balance against the much higher absolute strike counts.
    """
    if not stats_list:
        return None

    total_sig = sum(s.get("sig_strikes_landed", 0) for s in stats_list)
    total_td = sum(s.get("takedowns_landed", 0) for s in stats_list)
    total_sub = sum(s.get("submission_attempts", 0) for s in stats_list)

    # Weight grappling actions up so they're comparable to strike counts
    weighted_td = total_td * 10
    weighted_sub = total_sub * 10
    total = total_sig + weighted_td + weighted_sub

    if total == 0:
        return None

    return {
        "striking_share": total_sig / total,
        "grappling_share": weighted_td / total,
        "sub_share": weighted_sub / total,
    }


def _career_activity_profile(fighter: dict) -> dict:
    """Compute the proportion of striking vs grappling from career stats."""
    slpm = fighter.get("sig_strikes_landed_per_min") or 0.0
    td_avg = fighter.get("takedown_avg_per_15min") or 0.0
    sub_avg = fighter.get("submission_avg_per_15min") or 0.0

    # Normalize to same time base (per minute)
    td_per_min = td_avg / 15.0
    sub_per_min = sub_avg / 15.0

    # Weight grappling up (same 10x as recent profile)
    weighted_td = td_per_min * 10
    weighted_sub = sub_per_min * 10
    total = slpm + weighted_td + weighted_sub

    if total == 0:
        return {"striking_share": 0.5, "grappling_share": 0.25, "sub_share": 0.25}

    return {
        "striking_share": slpm / total,
        "grappling_share": weighted_td / total,
        "sub_share": weighted_sub / total,
    }


def _infer_recent_style(fighter: dict, recent_profile: dict,
                        recent_fights: list[dict]) -> str:
    """Infer recent style by scaling career stats by recent activity proportions.

    Takes the fighter's career stat magnitudes but adjusts the balance
    between striking/grappling/submissions based on recent fight proportions.
    """
    career_profile = _career_activity_profile(fighter)
    slpm = fighter.get("sig_strikes_landed_per_min") or 0.0
    td_avg = fighter.get("takedown_avg_per_15min") or 0.0
    sub_avg = fighter.get("submission_avg_per_15min") or 0.0

    # Compute shift ratios (how much each share changed)
    if career_profile["striking_share"] > 0:
        strike_shift = recent_profile["striking_share"] / career_profile["striking_share"]
    else:
        strike_shift = 1.0
    if career_profile["grappling_share"] > 0:
        grap_shift = recent_profile["grappling_share"] / career_profile["grappling_share"]
    else:
        grap_shift = 1.0
    if career_profile["sub_share"] > 0:
        sub_shift = recent_profile["sub_share"] / career_profile["sub_share"]
    else:
        sub_shift = 1.0

    # Also factor in recent win methods
    ko_wins = sum(1 for f in recent_fights
                  if f.get("winner_id") == fighter["id"]
                  and (f.get("win_method") or "") in ("KO/TKO",))
    sub_wins = sum(1 for f in recent_fights
                   if f.get("winner_id") == fighter["id"]
                   and (f.get("win_method") or "") == "SUB")
    total_recent_wins = sum(1 for f in recent_fights
                           if f.get("winner_id") == fighter["id"])

    # Boost shift if win methods reinforce the pattern
    if total_recent_wins >= 2:
        ko_rate = ko_wins / total_recent_wins
        sub_rate = sub_wins / total_recent_wins
        if ko_rate >= 0.6:
            strike_shift *= 1.15
        if sub_rate >= 0.4:
            sub_shift *= 1.15

    # Apply shifts to career stats
    adjusted = {
        "slpm": slpm * strike_shift,
        "td_avg": td_avg * grap_shift,
        "sub_avg": sub_avg * sub_shift,
        "str_acc": fighter.get("sig_strike_accuracy") or 0.0,
        "str_def": fighter.get("sig_strike_defense") or 0.0,
    }

    return classify_style(adjusted)


def detect_style_evolution(fighter: dict,
                           cutoff_date: str | None = None) -> dict:
    """Detect whether a fighter's style has evolved recently.

    Uses proportion-based comparison: compares the balance of striking vs
    grappling in recent fights to the career average.  Avoids unreliable
    per-minute rate conversions from raw fight stats.

    Returns dict with:
      career_style, recent_style, has_evolved, effective_style, evolution_note
    """
    career_style = classify_style(fighter)
    no_evolution = {
        "career_style": career_style,
        "recent_style": career_style,
        "has_evolved": False,
        "effective_style": career_style,
        "evolution_note": None,
    }

    fights = database.get_fighter_fights(fighter["id"], cutoff_date)
    recent_fights = fights[:STYLE_RECENT_FIGHT_COUNT]

    if len(recent_fights) < 3:
        return no_evolution

    # Gather fight stats for recent fights
    stats_list = []
    for fight in recent_fights:
        s = database.get_fight_stats(fight["id"], fighter["id"])
        if s:
            stats_list.append(s)

    if len(stats_list) < 3:
        return no_evolution

    recent_profile = _recent_activity_profile(stats_list)
    if not recent_profile:
        return no_evolution

    career_profile = _career_activity_profile(fighter)

    # Check if proportions shifted significantly
    strike_delta = abs(recent_profile["striking_share"] - career_profile["striking_share"])
    grap_delta = abs(recent_profile["grappling_share"] - career_profile["grappling_share"])
    max_delta = max(strike_delta, grap_delta)

    if max_delta < STYLE_EVOLUTION_THRESHOLD:
        return no_evolution

    recent_style = _infer_recent_style(fighter, recent_profile, recent_fights)

    if recent_style == career_style:
        return no_evolution

    return {
        "career_style": career_style,
        "recent_style": recent_style,
        "has_evolved": True,
        "effective_style": recent_style,
        "evolution_note": f"{career_style} -> {recent_style}",
    }


def style_matchup_modifier(f1: dict, f2: dict,
                           f1_evolution: dict | None = None,
                           f2_evolution: dict | None = None,
                           cutoff_date: str | None = None) -> tuple[float, str]:
    """Return a probability adjustment and description for the style matchup.

    Positive value favors fighter 1, negative favors fighter 2.
    Uses effective_style from evolution data when available.
    """
    s1 = f1_evolution["effective_style"] if f1_evolution else classify_style(f1)
    s2 = f2_evolution["effective_style"] if f2_evolution else classify_style(f2)

    adjustment = 0.0
    description = f"{s1} vs {s2}"

    f1_td_def = f1.get("takedown_defense") or 0.5
    f2_td_def = f2.get("takedown_defense") or 0.5

    wrestler_styles = ("Wrestler", "Wrestle-Striker")
    striker_styles = ("Striker", "Counter Striker", "Pressure Fighter")

    # Wrestler/Wrestle-Striker vs Striker — depends on TD defense
    if s1 in wrestler_styles and s2 in striker_styles:
        if f2_td_def < 0.65:
            adjustment = 0.04
            description += f" \u2014 {f2['name']}'s TD defense ({f2_td_def*100:.0f}%) vulnerable"
        elif f2_td_def < 0.80:
            adjustment = 0.02
        else:
            adjustment = 0.01
            description += f" \u2014 {f2['name']}'s TD defense ({f2_td_def*100:.0f}%) holds up"
    elif s2 in wrestler_styles and s1 in striker_styles:
        if f1_td_def < 0.65:
            adjustment = -0.04
            description += f" \u2014 {f1['name']}'s TD defense ({f1_td_def*100:.0f}%) vulnerable"
        elif f1_td_def < 0.80:
            adjustment = -0.02
        else:
            adjustment = -0.01
            description += f" \u2014 {f1['name']}'s TD defense ({f1_td_def*100:.0f}%) holds up"
    elif s1 == "Grappler" and s2 in wrestler_styles:
        adjustment = -0.02
    elif s2 == "Grappler" and s1 in wrestler_styles:
        adjustment = 0.02
    elif s1 in striker_styles and s2 in striker_styles:
        f1_acc = f1.get("sig_strike_accuracy") or 0.0
        f2_acc = f2.get("sig_strike_accuracy") or 0.0
        kd1 = _knockdown_rate(f1["id"], cutoff_date)
        kd2 = _knockdown_rate(f2["id"], cutoff_date)
        if f1_acc > f2_acc and kd1 >= kd2:
            adjustment = 0.03
            description += f" \u2014 {f1['name']} more accurate/powerful"
        elif f2_acc > f1_acc and kd2 >= kd1:
            adjustment = -0.03
            description += f" \u2014 {f2['name']} more accurate/powerful"
    elif s1 == "Pressure Fighter" and s2 == "Counter Striker":
        adjustment = 0.02
        description += " \u2014 pressure can overwhelm counters"
    elif s2 == "Pressure Fighter" and s1 == "Counter Striker":
        adjustment = -0.02
        description += " \u2014 pressure can overwhelm counters"

    return adjustment, description


def full_matchup(f1_id: str, f2_id: str, fqs_cache: dict | None = None,
                 wc_baselines: dict | None = None,
                 cutoff_date: str | None = None) -> dict:
    """Run all matchup analyses and return combined results."""
    f1 = database.get_fighter(f1_id)
    f2 = database.get_fighter(f2_id)

    fqs = fqs_comparison(f1_id, f2_id, fqs_cache, wc_baselines, cutoff_date)
    striking = striking_analysis(f1, f2, cutoff_date)
    grappling = grappling_analysis(f1, f2, cutoff_date)
    physical = physical_analysis(f1, f2)
    common = common_opponent_analysis(f1_id, f2_id, cutoff_date)

    # Style evolution detection
    f1_evolution = detect_style_evolution(f1, cutoff_date)
    f2_evolution = detect_style_evolution(f2, cutoff_date)

    style_adj, style_desc = style_matchup_modifier(f1, f2, f1_evolution, f2_evolution, cutoff_date)

    # Age matchup (uses effective styles from evolution data)
    f1_eff_style = f1_evolution["effective_style"]
    f2_eff_style = f2_evolution["effective_style"]
    age = age_matchup_analysis(f1, f2, f1_eff_style, f2_eff_style)

    # Stance matchup
    stance_adj, stance_desc = stance_matchup_adjustment(f1, f2, f1_eff_style, f2_eff_style)

    # Weight class info
    f1_wc = database.get_fighter_primary_weight_class(f1_id, cutoff_date)
    f2_wc = database.get_fighter_primary_weight_class(f2_id, cutoff_date)

    return {
        "fighter1": f1,
        "fighter2": f2,
        "fqs": fqs,
        "striking": striking,
        "grappling": grappling,
        "physical": physical,
        "common_opponents": common,
        "style_adjustment": style_adj,
        "style_description": style_desc,
        "fighter1_style": f1_evolution["effective_style"],
        "fighter2_style": f2_evolution["effective_style"],
        "fighter1_evolution": f1_evolution,
        "fighter2_evolution": f2_evolution,
        "fighter1_weight_class": f1_wc,
        "fighter2_weight_class": f2_wc,
        "age": age,
        "stance_adjustment": stance_adj,
        "stance_description": stance_desc,
    }

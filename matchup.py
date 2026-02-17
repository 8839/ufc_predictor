"""Head-to-head matchup comparison logic."""

import database
import utils
from scoring import calc_fqs


# ---------------------------------------------------------------------------
# Fight-stats helpers (per-fight data from fight_stats table)
# ---------------------------------------------------------------------------

def _recent_fight_stats(fighter_id: str, n: int = 5) -> list[dict]:
    """Get stats for a fighter's last N fights (most recent first)."""
    fights = database.get_fighter_fights(fighter_id)
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

def fqs_comparison(f1_id: str, f2_id: str, fqs_cache: dict | None = None) -> dict:
    """Return FQS breakdown for both fighters."""
    return {
        "fighter1": calc_fqs(f1_id, fqs_cache),
        "fighter2": calc_fqs(f2_id, fqs_cache),
    }


# ---------------------------------------------------------------------------
# 6.2 Striking Analysis
# ---------------------------------------------------------------------------

def striking_analysis(f1: dict, f2: dict) -> dict:
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
    f1_recent = _aggregate_fight_stats(_recent_fight_stats(f1["id"], 5))
    f2_recent = _aggregate_fight_stats(_recent_fight_stats(f2["id"], 5))

    # Knockdown rate from fight stats (career + recent)
    f1_kd_rate = _knockdown_rate(f1["id"])
    f2_kd_rate = _knockdown_rate(f2["id"])
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

    # Determine edge: higher output, accuracy, defense; lower absorbed; knockdown power
    f1_score = f1_slpm + f1_acc_blend * 10 + f1_def * 10 - f1_sapm + f1_kd_rate * 3
    f2_score = f2_slpm + f2_acc_blend * 10 + f2_def * 10 - f2_sapm + f2_kd_rate * 3

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


def _knockdown_rate(fighter_id: str) -> float:
    """Knockdowns per fight for a fighter."""
    stats = database.get_fighter_all_stats(fighter_id)
    if not stats:
        return 0.0
    total_kd = sum(s.get("knockdowns", 0) for s in stats)
    return total_kd / len(stats)


# ---------------------------------------------------------------------------
# 6.3 Grappling Analysis
# ---------------------------------------------------------------------------

def grappling_analysis(f1: dict, f2: dict) -> dict:
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
    f1_recent = _aggregate_fight_stats(_recent_fight_stats(f1["id"], 5))
    f2_recent = _aggregate_fight_stats(_recent_fight_stats(f2["id"], 5))

    # Use recent control time if available, otherwise career
    f1_ctrl = f1_recent["avg_ctrl"] if f1_recent["count"] >= 3 else _avg_control_time(f1["id"])
    f2_ctrl = f2_recent["avg_ctrl"] if f2_recent["count"] >= 3 else _avg_control_time(f2["id"])

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


def _avg_control_time(fighter_id: str) -> float:
    """Average control time in seconds per fight."""
    stats = database.get_fighter_all_stats(fighter_id)
    if not stats:
        return 0.0
    total = sum(s.get("control_time_seconds", 0) for s in stats)
    return total / len(stats)


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
    # Youth advantage (younger is slightly better, unless too young)
    if f1_age and f2_age:
        age_diff = f2_age - f1_age  # positive means f1 is younger
        physical_score += age_diff * 0.2

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
        "fighter1_over_37": f1_age is not None and f1_age > 37,
        "fighter2_over_37": f2_age is not None and f2_age > 37,
    }


# ---------------------------------------------------------------------------
# 6.5 Common Opponent Analysis
# ---------------------------------------------------------------------------

def common_opponent_analysis(f1_id: str, f2_id: str) -> dict:
    """Find common opponents and compare results."""
    f1_fights = database.get_fighter_fights(f1_id)
    f2_fights = database.get_fighter_fights(f2_id)

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

def classify_style(fighter: dict) -> str:
    """Classify a fighter's primary style based on stat profile.

    Styles:
    - Wrestler: high takedown volume, uses wrestling to control
    - Grappler: submission threat, works off back or in scrambles
    - Striker: high striking output, low takedown usage
    - Wrestle-Striker: mixes wrestling with striking, moderate both
    - Pressure Fighter: high output everywhere, pushes pace
    - Counter Striker: lower output but high accuracy and defense
    """
    slpm = fighter.get("sig_strikes_landed_per_min") or 0.0
    td_avg = fighter.get("takedown_avg_per_15min") or 0.0
    sub_avg = fighter.get("submission_avg_per_15min") or 0.0
    str_acc = fighter.get("sig_strike_accuracy") or 0.0
    str_def = fighter.get("sig_strike_defense") or 0.0
    td_def = fighter.get("takedown_defense") or 0.0

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


def style_matchup_modifier(f1: dict, f2: dict) -> tuple[float, str]:
    """Return a probability adjustment and description for the style matchup.

    Positive value favors fighter 1, negative favors fighter 2.
    """
    s1 = classify_style(f1)
    s2 = classify_style(f2)

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
        kd1 = _knockdown_rate(f1["id"])
        kd2 = _knockdown_rate(f2["id"])
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


def full_matchup(f1_id: str, f2_id: str, fqs_cache: dict | None = None) -> dict:
    """Run all matchup analyses and return combined results."""
    f1 = database.get_fighter(f1_id)
    f2 = database.get_fighter(f2_id)

    fqs = fqs_comparison(f1_id, f2_id, fqs_cache)
    striking = striking_analysis(f1, f2)
    grappling = grappling_analysis(f1, f2)
    physical = physical_analysis(f1, f2)
    common = common_opponent_analysis(f1_id, f2_id)
    style_adj, style_desc = style_matchup_modifier(f1, f2)

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
        "fighter1_style": classify_style(f1),
        "fighter2_style": classify_style(f2),
    }

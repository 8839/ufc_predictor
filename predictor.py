"""Final prediction assembly, method-of-victory prediction, and output formatting."""

from datetime import datetime

import database
import utils
from config import MAX_PROBABILITY, MIN_PROBABILITY, OVERALL_KO_RATE, OVERALL_SUB_RATE
from matchup import full_matchup


def predict_fight(f1_id: str, f2_id: str, fqs_cache: dict | None = None,
                  wc_baselines: dict | None = None) -> dict:
    """Generate a full fight prediction.

    Returns a dict with all matchup data plus prediction details.
    """
    analysis = full_matchup(f1_id, f2_id, fqs_cache, wc_baselines)
    f1 = analysis["fighter1"]
    f2 = analysis["fighter2"]
    fqs = analysis["fqs"]

    f1_fqs = fqs["fighter1"]["fqs"]
    f2_fqs = fqs["fighter2"]["fqs"]

    # 7.1 Base probability
    total = f1_fqs + f2_fqs
    if total == 0:
        base_prob = 0.5
    else:
        base_prob = f1_fqs / total

    # Apply adjustments
    adjustments = []

    # Striking edge
    striking = analysis["striking"]
    if striking["edge_id"] == f1_id:
        adj = 0.03
    elif striking["edge_id"] == f2_id:
        adj = -0.03
    else:
        adj = 0.0
    adjustments.append(("Striking edge", adj))

    # Grappling edge
    grappling = analysis["grappling"]
    if grappling["edge_id"] == f1_id:
        adj = 0.03
    elif grappling["edge_id"] == f2_id:
        adj = -0.03
    else:
        adj = 0.0
    adjustments.append(("Grappling edge", adj))

    # Physical advantages
    physical = analysis["physical"]
    if physical["edge_id"] == f1_id:
        adj = 0.02
    elif physical["edge_id"] == f2_id:
        adj = -0.02
    else:
        adj = 0.0
    adjustments.append(("Physical edge", adj))

    # Common opponent advantage
    common = analysis["common_opponents"]
    if common["edge_id"] == f1_id:
        adj = 0.025
    elif common["edge_id"] == f2_id:
        adj = -0.025
    else:
        adj = 0.0
    adjustments.append(("Common opponents", adj))

    # Style matchup
    style_adj = analysis["style_adjustment"]
    adjustments.append(("Style matchup", style_adj))

    # Momentum/streak
    streak_diff = fqs["fighter1"]["streak_momentum"] - fqs["fighter2"]["streak_momentum"]
    momentum_adj = (streak_diff / 100.0) * 0.03  # scale to ±3%
    adjustments.append(("Momentum", momentum_adj))

    # KD power differential (from fight stats)
    f1_kd = striking["fighter1"].get("kd_rate", 0)
    f2_kd = striking["fighter2"].get("kd_rate", 0)
    kd_diff = f1_kd - f2_kd
    if abs(kd_diff) > 0.15:  # meaningful difference
        kd_adj = max(-0.03, min(0.03, kd_diff * 0.05))
        adjustments.append(("KD power", kd_adj))

    # Sum adjustments
    total_adj = sum(a for _, a in adjustments)
    final_prob = base_prob + total_adj

    # Cap
    final_prob = max(MIN_PROBABILITY, min(MAX_PROBABILITY, final_prob))

    # Determine winner
    if final_prob >= 0.5:
        winner_id = f1_id
        winner_name = f1["name"]
        loser = f2
        win_prob = final_prob
    else:
        winner_id = f2_id
        winner_name = f2["name"]
        loser = f1
        win_prob = 1.0 - final_prob

    # 7.2 Predicted method of victory
    weight_class = analysis.get("fighter1_weight_class") or analysis.get("fighter2_weight_class")
    method, round_range = _predict_method(winner_id, loser["id"], weight_class, wc_baselines)

    # 7.3 Confidence label
    label = utils.confidence_label(win_prob)

    # Limited data warning
    f1_fights = database.get_fighter_fights(f1_id)
    f2_fights = database.get_fighter_fights(f2_id)
    limited_data = len(f1_fights) < 3 or len(f2_fights) < 3

    prediction = {
        "analysis": analysis,
        "f1_fqs": f1_fqs,
        "f2_fqs": f2_fqs,
        "base_probability": round(base_prob * 100, 1),
        "adjustments": adjustments,
        "final_probability": round(win_prob * 100, 1),
        "predicted_winner_id": winner_id,
        "predicted_winner_name": winner_name,
        "confidence_label": label,
        "predicted_method": method,
        "predicted_round_range": round_range,
        "limited_data": limited_data,
    }

    return prediction


def _is_ko(method: str) -> bool:
    return "KO" in method or "TKO" in method

def _is_sub(method: str) -> bool:
    return method == "SUB" or "Submission" in method

def _is_decision(method: str) -> bool:
    return "DEC" in method


def _predict_method(winner_id: str, loser_id: str,
                    weight_class: str | None = None,
                    wc_baselines: dict | None = None) -> tuple[str, str]:
    """Predict method of victory and approximate round range.

    Blends fighter rates with weight-class tendencies (80/20) when available.
    """
    fights = database.get_fighter_fights(winner_id)

    ko_count = 0
    sub_count = 0
    dec_count = 0
    total_wins = 0
    finish_rounds = []

    for fight in fights:
        if fight["winner_id"] != winner_id:
            continue
        total_wins += 1
        method = fight["win_method"] or ""
        if _is_ko(method):
            ko_count += 1
            if fight["finish_round"]:
                finish_rounds.append(fight["finish_round"])
        elif _is_sub(method):
            sub_count += 1
            if fight["finish_round"]:
                finish_rounds.append(fight["finish_round"])
        elif _is_decision(method):
            dec_count += 1

    if total_wins == 0:
        return "Decision - Unanimous", "Round 3"

    ko_rate = ko_count / total_wins
    sub_rate = sub_count / total_wins
    dec_rate = dec_count / total_wins
    finish_rate = (ko_count + sub_count) / total_wins

    # Check loser's vulnerability
    loser_fights = database.get_fighter_fights(loser_id)
    loser_ko_losses = 0
    loser_sub_losses = 0
    loser_total_losses = 0
    for fight in loser_fights:
        if fight["winner_id"] is not None and fight["winner_id"] != loser_id:
            loser_total_losses += 1
            method = fight["win_method"] or ""
            if _is_ko(method):
                loser_ko_losses += 1
            elif _is_sub(method):
                loser_sub_losses += 1

    # Adjust rates based on opponent vulnerability (30% weight)
    if loser_total_losses > 0:
        loser_ko_vuln = loser_ko_losses / loser_total_losses
        loser_sub_vuln = loser_sub_losses / loser_total_losses
        ko_rate = ko_rate * 0.7 + loser_ko_vuln * 0.3
        sub_rate = sub_rate * 0.7 + loser_sub_vuln * 0.3

    # Blend with weight-class tendencies (80% fighter, 20% WC)
    if wc_baselines and weight_class and weight_class in wc_baselines:
        bl = wc_baselines[weight_class]
        wc_ko = bl.get("ko_rate", OVERALL_KO_RATE)
        wc_sub = bl.get("sub_rate", OVERALL_SUB_RATE)
        ko_rate = ko_rate * 0.8 + wc_ko * 0.2
        sub_rate = sub_rate * 0.8 + wc_sub * 0.2

    # Determine method
    if finish_rate >= 0.5:
        if ko_rate >= sub_rate:
            predicted = "KO/TKO"
        else:
            predicted = "Submission"
    elif ko_rate >= sub_rate and ko_rate >= dec_rate:
        predicted = "KO/TKO"
    elif sub_rate >= ko_rate and sub_rate >= dec_rate:
        predicted = "Submission"
    else:
        predicted = "Decision - Unanimous"

    # Round range for finishes
    if predicted in ("KO/TKO", "Submission"):
        if finish_rounds:
            avg_round = sum(finish_rounds) / len(finish_rounds)
            low = max(1, int(avg_round - 0.5))
            high = min(5, int(avg_round + 1.0))
            if low == high:
                round_range = f"Round {low}"
            else:
                round_range = f"Round {low}-{high}"
        else:
            round_range = "Round 1-3"
    else:
        round_range = "Full fight"

    return predicted, round_range


# ---------------------------------------------------------------------------
# Save prediction
# ---------------------------------------------------------------------------

def save_prediction(pred: dict) -> int:
    """Save a prediction to the database. Returns the prediction ID."""
    record = {
        "fighter1_id": pred["analysis"]["fighter1"]["id"],
        "fighter2_id": pred["analysis"]["fighter2"]["id"],
        "predicted_winner_id": pred["predicted_winner_id"],
        "confidence": pred["final_probability"],
        "predicted_method": pred["predicted_method"],
        "fighter1_fqs": pred["f1_fqs"],
        "fighter2_fqs": pred["f2_fqs"],
        "actual_winner_id": None,
        "actual_method": None,
        "correct": None,
        "prediction_date": datetime.utcnow().isoformat(),
        "fight_date": None,
    }
    return database.save_prediction(record)


# ---------------------------------------------------------------------------
# Output Formatting
# ---------------------------------------------------------------------------

def format_prediction(pred: dict) -> str:
    """Format prediction into the terminal output specified in section 8.3."""
    f1 = pred["analysis"]["fighter1"]
    f2 = pred["analysis"]["fighter2"]
    fqs = pred["analysis"]["fqs"]
    striking = pred["analysis"]["striking"]
    grappling = pred["analysis"]["grappling"]
    physical = pred["analysis"]["physical"]
    common = pred["analysis"]["common_opponents"]

    f1_age = physical["fighter1_age"]
    f2_age = physical["fighter2_age"]
    f1_height = utils.format_height(f1.get("height_inches"))
    f2_height = utils.format_height(f2.get("height_inches"))
    f1_reach = f"{f1.get('reach_inches', 'N/A')}\"" if f1.get("reach_inches") else "N/A"
    f2_reach = f"{f2.get('reach_inches', 'N/A')}\"" if f2.get("reach_inches") else "N/A"
    f1_record = f"{f1.get('wins', 0)}-{f1.get('losses', 0)}-{f1.get('draws', 0)}"
    f2_record = f"{f2.get('wins', 0)}-{f2.get('losses', 0)}-{f2.get('draws', 0)}"
    f1_nick = f'"{f1["nickname"]}"' if f1.get("nickname") else ""
    f2_nick = f'"{f2["nickname"]}"' if f2.get("nickname") else ""

    lines = []
    w = 60
    lines.append("=" * w)
    lines.append("FIGHT PREDICTION ANALYSIS".center(w))
    lines.append("=" * w)
    lines.append("")

    # Fighter header
    left = f"  {f1['name']} ({f1_record})"
    right = f"{f2['name']} ({f2_record})"
    lines.append(f"{left:<30}vs{right:>28}")

    if f1_nick or f2_nick:
        lines.append(f"  {f1_nick:<28}    {f2_nick:>26}")

    f1_info = f"  Age: {f1_age or 'N/A'} | {f1_height} | {f1_reach} reach"
    f2_info = f"Age: {f2_age or 'N/A'} | {f2_height} | {f2_reach} reach"
    lines.append(f"{f1_info:<30}    {f2_info:>26}")

    f1_stance = f"  {f1.get('stance') or 'N/A'}"
    f2_stance = f"{f2.get('stance') or 'N/A'}"
    lines.append(f"{f1_stance:<30}    {f2_stance:>26}")

    lines.append("")
    lines.append("-" * w)
    lines.append("QUALITY SCORES".center(w))
    lines.append("-" * w)

    fqs1 = fqs["fighter1"]
    fqs2 = fqs["fighter2"]
    lines.append(f"  FQS: {fqs1['fqs']:<24}           FQS: {fqs2['fqs']}")
    for label, key in [
        ("Opponent Quality", "opponent_quality"),
        ("Win Method", "win_method"),
        ("Loss Quality", "loss_quality"),
        ("Recency", "recency"),
        ("Momentum", "streak_momentum"),
        ("Championship", "championship"),
        ("Activity Rate", "activity_rate"),
    ]:
        lines.append(
            f"    {label + ':':<20} {fqs1[key]:<10}       "
            f"{label + ':':<20} {fqs2[key]}"
        )

    lines.append("")
    lines.append("-" * w)
    lines.append("MATCHUP ANALYSIS".center(w))
    lines.append("-" * w)

    # Striking
    lines.append(f"  STRIKING EDGE:    {striking['edge']}")
    diff_sign = "+" if striking["diff_slpm"] >= 0 else ""
    lines.append(
        f"    {diff_sign}{striking['diff_slpm']} sig. strikes/min | "
        f"{diff_sign}{striking['diff_acc']}% accuracy | "
        f"{diff_sign}{striking['diff_sapm']} absorbed/min"
    )

    # Grappling
    lines.append(f"\n  GRAPPLING EDGE:   {grappling['edge']}")
    diff_sign = "+" if grappling["diff_td"] >= 0 else ""
    lines.append(
        f"    {diff_sign}{grappling['diff_td']} TD avg | "
        f"{diff_sign}{grappling['diff_td_acc']}% TD accuracy | "
        f"{diff_sign}{int(grappling['diff_ctrl'])}s avg control time"
    )

    # Physical
    lines.append(f"\n  PHYSICAL EDGE:    {physical['edge']}")
    phys_parts = []
    if physical["reach_diff"]:
        phys_parts.append(f"{abs(physical['reach_diff'])}\" reach advantage")
    if physical["height_diff"]:
        phys_parts.append(f"{abs(physical['height_diff'])}\" height")
    if f1_age and f2_age:
        diff = abs(f1_age - f2_age)
        if diff > 0:
            phys_parts.append(f"{diff} years younger")
    if phys_parts:
        lines.append(f"    {' | '.join(phys_parts)}")

    if f1_age and f1_age > 37:
        lines.append(f"    * {f1['name']} is {f1_age} (statistical decline zone)")
    if f2_age and f2_age > 37:
        lines.append(f"    * {f2['name']} is {f2_age} (statistical decline zone)")

    # Common opponents
    f1_last = f1["name"].split()[-1]
    f2_last = f2["name"].split()[-1]
    lines.append(f"\n  COMMON OPPONENTS: {common['count']} found")
    for comp in common["comparisons"]:
        lines.append(
            f"    vs {comp['opponent_name']}:  "
            f"{f1_last} {comp['fighter1_result']} | "
            f"{f2_last} {comp['fighter2_result']}"
        )

    # Style
    lines.append(f"\n  STYLE MATCHUP:    {pred['analysis']['style_description']}")
    f1_evo = pred["analysis"].get("fighter1_evolution")
    f2_evo = pred["analysis"].get("fighter2_evolution")
    f1_style_str = pred["analysis"]["fighter1_style"]
    f2_style_str = pred["analysis"]["fighter2_style"]
    if f1_evo and f1_evo.get("has_evolved"):
        f1_style_str = f"{f1_evo['career_style']} -> {f1_evo['recent_style']} (evolving)"
    if f2_evo and f2_evo.get("has_evolved"):
        f2_style_str = f"{f2_evo['career_style']} -> {f2_evo['recent_style']} (evolving)"
    lines.append(
        f"    {f1['name']}: {f1_style_str} | "
        f"{f2['name']}: {f2_style_str}"
    )

    lines.append("")
    lines.append("-" * w)
    lines.append("PREDICTION".center(w))
    lines.append("-" * w)

    lines.append(
        f"  >>> {pred['predicted_winner_name']} wins "
        f"({pred['final_probability']}% confidence) <<<"
    )
    lines.append(f"  Confidence: {pred['confidence_label']}")
    lines.append(
        f"  Likely Method: {pred['predicted_method']} "
        f"({pred['predicted_round_range']})"
    )

    if pred["limited_data"]:
        lines.append("\n  * WARNING: Limited fight data — lower confidence")

    # Key factors
    lines.append("\n  Key Factors:")
    for label, adj in pred["adjustments"]:
        if abs(adj) > 0.005:
            direction = f1["name"] if adj > 0 else f2["name"]
            lines.append(f"  * {label}: favors {direction} ({adj*100:+.1f}%)")

    lines.append("=" * w)

    return "\n".join(lines)


def format_fighter_profile(fighter_id: str, fqs_cache: dict | None = None,
                          wc_baselines: dict | None = None) -> str:
    """Format a single fighter's profile with FQS breakdown."""
    from scoring import calc_fqs
    from matchup import detect_style_evolution, classify_style

    f = database.get_fighter(fighter_id)
    if not f:
        return f"Fighter {fighter_id} not found."

    fqs = calc_fqs(fighter_id, fqs_cache, wc_baselines)
    age = utils.calculate_age(f.get("dob"))
    height = utils.format_height(f.get("height_inches"))
    fights = database.get_fighter_fights(fighter_id)
    wc = database.get_fighter_primary_weight_class(fighter_id)

    # Style evolution
    evolution = detect_style_evolution(f)

    lines = []
    w = 50
    lines.append("=" * w)
    lines.append(f"  {f['name']}")
    if f.get("nickname"):
        lines.append(f'  "{f["nickname"]}"')
    lines.append(f"  Record: {f.get('wins', 0)}-{f.get('losses', 0)}-{f.get('draws', 0)}")
    if f.get("no_contests"):
        lines.append(f"  No Contests: {f['no_contests']}")
    lines.append(f"  Age: {age or 'N/A'} | Height: {height} | Reach: {f.get('reach_inches', 'N/A')}\"")
    lines.append(f"  Stance: {f.get('stance', 'N/A')} | Weight: {f.get('weight_lbs', 'N/A')} lbs")
    if wc:
        lines.append(f"  Weight Class: {wc}")
    # Style
    style_str = evolution["effective_style"]
    if evolution["has_evolved"]:
        style_str = f"{evolution['career_style']} -> {evolution['recent_style']} (evolving)"
    lines.append(f"  Style: {style_str}")
    lines.append("-" * w)
    lines.append("  FQS BREAKDOWN")
    lines.append(f"    Overall FQS:     {fqs['fqs']}")
    lines.append(f"    Opponent Quality: {fqs['opponent_quality']}")
    lines.append(f"    Win Method:       {fqs['win_method']}")
    lines.append(f"    Loss Quality:     {fqs['loss_quality']}")
    lines.append(f"    Recency:          {fqs['recency']}")
    lines.append(f"    Momentum:         {fqs['streak_momentum']}")
    lines.append(f"    Championship:     {fqs['championship']}")
    lines.append(f"    Activity Rate:    {fqs['activity_rate']}")
    lines.append("-" * w)
    lines.append("  CAREER STATS")
    lines.append(f"    Sig. Strikes/Min: {f.get('sig_strikes_landed_per_min', 'N/A')}")
    lines.append(f"    Sig. Strike Acc:  {_pct(f.get('sig_strike_accuracy'))}")
    lines.append(f"    Sig. Strikes Abs: {f.get('sig_strikes_absorbed_per_min', 'N/A')}")
    lines.append(f"    Sig. Strike Def:  {_pct(f.get('sig_strike_defense'))}")
    lines.append(f"    Takedown Avg:     {f.get('takedown_avg_per_15min', 'N/A')}")
    lines.append(f"    Takedown Acc:     {_pct(f.get('takedown_accuracy'))}")
    lines.append(f"    Takedown Def:     {_pct(f.get('takedown_defense'))}")
    lines.append(f"    Submission Avg:   {f.get('submission_avg_per_15min', 'N/A')}")
    lines.append("-" * w)
    lines.append(f"  RECENT FIGHTS ({min(5, len(fights))} most recent)")
    for fight in fights[:5]:
        opp_id = (
            fight["fighter2_id"]
            if fight["fighter1_id"] == fighter_id
            else fight["fighter1_id"]
        )
        opp = database.get_fighter(opp_id)
        opp_name = opp["name"] if opp else opp_id
        result = "W" if fight["winner_id"] == fighter_id else ("L" if fight["winner_id"] else "D/NC")
        method = fight["win_method"] or ""
        rd = f" R{fight['finish_round']}" if fight["finish_round"] else ""
        date = fight["event_date"] or ""
        lines.append(f"    {result} vs {opp_name} — {method}{rd} ({date})")
    lines.append("=" * w)

    return "\n".join(lines)


def _pct(value) -> str:
    if value is None:
        return "N/A"
    return f"{value * 100:.1f}%"


def format_history() -> str:
    """Format prediction history and accuracy report."""
    predictions = database.get_all_predictions()
    if not predictions:
        return "No predictions recorded yet."

    lines = []
    total = len(predictions)
    resolved = [p for p in predictions if p["correct"] is not None]
    correct = sum(1 for p in resolved if p["correct"])

    lines.append("=" * 60)
    lines.append("PREDICTION HISTORY".center(60))
    lines.append("=" * 60)
    lines.append(f"  Total predictions: {total}")
    lines.append(f"  Resolved: {len(resolved)}")
    if resolved:
        accuracy = correct / len(resolved) * 100
        lines.append(f"  Correct: {correct}/{len(resolved)} ({accuracy:.1f}%)")
    lines.append("-" * 60)

    for p in predictions:
        status = ""
        if p["correct"] is None:
            status = "PENDING"
        elif p["correct"]:
            status = "CORRECT"
        else:
            status = "WRONG"

        f1_name = p.get("fighter1_name", p["fighter1_id"])
        f2_name = p.get("fighter2_name", p["fighter2_id"])
        winner_name = p.get("predicted_winner_name", p["predicted_winner_id"])

        lines.append(
            f"  #{p['id']} | {f1_name} vs {f2_name} | "
            f"Pick: {winner_name} ({p['confidence']:.1f}%) | "
            f"{p['predicted_method']} | [{status}]"
        )
        if p["correct"] is not None:
            actual = p.get("actual_winner_name", p.get("actual_winner_id", "N/A"))
            lines.append(f"       Actual: {actual} by {p.get('actual_method', 'N/A')}")

    lines.append("=" * 60)
    return "\n".join(lines)

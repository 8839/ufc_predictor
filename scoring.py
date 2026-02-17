"""Fighter Quality Score (FQS) calculation engine."""

import math
from datetime import datetime

import database
import utils
from config import (
    FQS_CONVERGENCE_THRESHOLD,
    FQS_MAX_ITERATIONS,
    RECENCY_LAMBDA,
    WEIGHT_CHAMPIONSHIP,
    WEIGHT_LOSS_QUALITY,
    WEIGHT_OPPONENT_QUALITY,
    WEIGHT_RECENCY,
    WEIGHT_STREAK,
    WEIGHT_WIN_METHOD,
    WIN_METHOD_POINTS,
)


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


# ---------------------------------------------------------------------------
# 5.1 Opponent Quality Score
# ---------------------------------------------------------------------------

def _opponent_win_rate(fighter_id: str) -> float:
    """Simple win rate for a fighter (0-1)."""
    f = database.get_fighter(fighter_id)
    if not f:
        return 0.5
    total = (f["wins"] or 0) + (f["losses"] or 0)
    if total == 0:
        return 0.5
    return (f["wins"] or 0) / total


def _opponent_opponent_strength(fighter_id: str) -> float:
    """Average win rate of a fighter's opponents (level 2)."""
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 0.5
    rates = []
    for fight in fights:
        opp_id = fight["fighter2_id"] if fight["fighter1_id"] == fighter_id else fight["fighter1_id"]
        rates.append(_opponent_win_rate(opp_id))
    return sum(rates) / len(rates) if rates else 0.5


def calc_opponent_quality(fighter_id: str) -> float:
    """Calculate opponent quality score (0-100). Spec section 5.1."""
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 50.0

    win_qualities = []
    loss_qualities = []

    for fight in fights:
        opp_id = fight["fighter2_id"] if fight["fighter1_id"] == fighter_id else fight["fighter1_id"]

        opp_strength = _opponent_win_rate(opp_id)
        opp_opp_strength = _opponent_opponent_strength(opp_id)
        fight_opp_quality = 0.7 * opp_strength + 0.3 * opp_opp_strength

        is_win = fight["winner_id"] == fighter_id
        is_loss = fight["winner_id"] is not None and fight["winner_id"] != fighter_id

        if is_win:
            win_qualities.append(fight_opp_quality)
        elif is_loss:
            loss_qualities.append(fight_opp_quality)
        # draws/NC: skip

    avg_win_q = sum(win_qualities) / len(win_qualities) if win_qualities else 0.0
    avg_loss_penalty = (
        sum(1.0 - q for q in loss_qualities) / len(loss_qualities)
        if loss_qualities
        else 0.0
    )

    raw = avg_win_q - 0.5 * avg_loss_penalty
    # Normalize: raw is roughly in [-0.5, 1.0] range → map to 0-100
    return _clamp(raw * 100.0)


# ---------------------------------------------------------------------------
# 5.2 Win Method Score
# ---------------------------------------------------------------------------

def calc_win_method_score(fighter_id: str) -> float:
    """Calculate win method score (0-100). Spec section 5.2."""
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 50.0

    scores = []
    for fight in fights:
        if fight["winner_id"] != fighter_id:
            continue
        method = fight["win_method"] or ""
        base = WIN_METHOD_POINTS.get(method, 5)

        # Round bonus for finishes
        round_bonus = 0.0
        is_finish = method in ("KO/TKO", "SUB")
        if is_finish and fight["finish_round"]:
            round_bonus = max(0, (6 - fight["finish_round"])) * 0.5

        scores.append(base + round_bonus)

    if not scores:
        return 50.0

    avg = sum(scores) / len(scores)
    # Max possible score = 10 + 2.5 = 12.5, normalize to 0-100
    return _clamp((avg / 12.5) * 100.0)


# ---------------------------------------------------------------------------
# 5.3 Loss Quality Score
# ---------------------------------------------------------------------------

def calc_loss_quality(fighter_id: str, fqs_cache: dict | None = None) -> float:
    """Calculate loss quality score (0-100). Spec section 5.3.

    Tuned so that:
    - Undefeated fighters get 100.
    - A fighter with few losses relative to wins is barely penalized.
    - Context matters: losing to a great fighter by split decision is mild,
      getting finished by a low-level fighter is severe.
    - The loss *ratio* (losses / total fights) scales the penalty so that
      a 27-1 fighter isn't destroyed by one bad loss.
    """
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 100.0

    losses = []
    total_decided = 0  # fights with a winner (not draws/NC)
    for fight in fights:
        if fight["winner_id"] is None:
            continue
        total_decided += 1
        if fight["winner_id"] != fighter_id:
            losses.append(fight)

    if not losses:
        return 100.0

    # Calculate per-loss penalty multiplier (0 = no penalty, 1 = full penalty)
    penalties = []
    for fight in losses:
        opp_id = fight["winner_id"]
        opp_fqs = 50.0
        if fqs_cache and opp_id in fqs_cache:
            opp_fqs = fqs_cache[opp_id]
        else:
            # Fallback: estimate from win rate
            opp = database.get_fighter(opp_id)
            if opp:
                opp_total = (opp["wins"] or 0) + (opp["losses"] or 0)
                if opp_total > 0:
                    opp_fqs = ((opp["wins"] or 0) / opp_total) * 100

        method = fight["win_method"] or ""
        is_finish = method in ("KO/TKO", "SUB")
        is_split = method == "S-DEC"

        if opp_fqs > 75:
            if is_split:
                multiplier = 0.3
            elif is_finish:
                multiplier = 0.5
            else:
                multiplier = 0.4
        elif opp_fqs > 55:
            # Average-to-good opponent
            if is_split:
                multiplier = 0.4
            elif is_finish:
                multiplier = 0.6
            else:
                multiplier = 0.5
        elif opp_fqs > 40:
            # Below average opponent
            if is_finish:
                multiplier = 0.8
            else:
                multiplier = 0.65
        else:
            # Low-level opponent
            multiplier = 1.0

        penalties.append(multiplier)

    avg_penalty = sum(penalties) / len(penalties)

    # Scale by loss ratio — a 27-1 fighter (ratio ~0.04) should keep most of their score,
    # while a 5-5 fighter (ratio 0.5) feels the full weight.
    # Use sqrt to soften the curve so a few losses still register.
    loss_ratio = len(losses) / total_decided if total_decided > 0 else 0
    scaled_penalty = avg_penalty * math.sqrt(loss_ratio)

    # Convert: 0 penalty = 100 score, 1.0 penalty = 0 score
    return _clamp(100.0 - scaled_penalty * 100.0)


# ---------------------------------------------------------------------------
# 5.4 Recency Score
# ---------------------------------------------------------------------------

def calc_recency_score(fighter_id: str) -> float:
    """Calculate recency-weighted score (0-100). Spec section 5.4."""
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 50.0

    weighted_scores = []
    total_weight = 0.0

    for fight in fights:
        years = utils.years_since(fight["event_date"])
        weight = math.exp(-RECENCY_LAMBDA * years)

        # Per-fight score: combine win method value + opponent quality signal
        if fight["winner_id"] == fighter_id:
            method = fight["win_method"] or ""
            base = WIN_METHOD_POINTS.get(method, 5)
            round_bonus = 0.0
            if method in ("KO/TKO", "SUB") and fight["finish_round"]:
                round_bonus = max(0, (6 - fight["finish_round"])) * 0.5
            fight_score = (base + round_bonus) / 12.5  # normalize to 0-1
        elif fight["winner_id"] is not None:
            fight_score = 0.3  # loss (was 0.2 — slightly less punishing)
        else:
            fight_score = 0.5  # draw/NC

        weighted_scores.append(fight_score * weight)
        total_weight += weight

    if total_weight == 0:
        return 50.0

    return _clamp((sum(weighted_scores) / total_weight) * 100.0)


# ---------------------------------------------------------------------------
# 5.5 Streak & Momentum Score
# ---------------------------------------------------------------------------

def calc_streak_score(fighter_id: str) -> float:
    """Calculate streak and momentum score (0-100). Spec section 5.5."""
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 50.0

    # Determine current streak (fights already sorted by date DESC)
    streak_length = 0
    direction = 0  # +1 win streak, -1 loss streak
    streak_has_finish = False
    streak_has_title_win = False

    for fight in fights:
        if fight["winner_id"] == fighter_id:
            if direction == 0:
                direction = 1
            if direction == 1:
                streak_length += 1
                if fight["win_method"] in ("KO/TKO", "SUB"):
                    streak_has_finish = True
                if fight["is_title_fight"]:
                    streak_has_title_win = True
            else:
                break
        elif fight["winner_id"] is not None and fight["winner_id"] != fighter_id:
            if direction == 0:
                direction = -1
            if direction == -1:
                streak_length += 1
            else:
                break
        else:
            # Draw/NC breaks streak counting
            break

    score = 50.0 + streak_length * direction * 5

    if direction == 1:
        if streak_has_finish:
            score += 5
        if streak_has_title_win:
            score += 10

    # Ring rust penalty
    if fights:
        years_since_last = utils.years_since(fights[0]["event_date"])
        if years_since_last > 1.5:
            score -= 10

    return _clamp(score)


# ---------------------------------------------------------------------------
# 5.6 Championship Modifier
# ---------------------------------------------------------------------------

def calc_championship_score(fighter_id: str) -> float:
    """Calculate championship modifier score (0-100). Spec section 5.6."""
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 0.0

    bonus = 0.0
    title_wins = 0
    title_defenses = 0
    first_title_win_seen = False

    # Sort chronologically for defense counting
    sorted_fights = sorted(fights, key=lambda f: f["event_date"] or "")

    for fight in sorted_fights:
        if not fight["is_title_fight"]:
            continue
        if fight["winner_id"] == fighter_id:
            if not first_title_win_seen:
                bonus += 15  # Has won a UFC title
                first_title_win_seen = True
            else:
                title_defenses += 1
            title_wins += 1

    # Defense bonus: +5 per defense, cap at +20
    bonus += min(title_defenses * 5, 20)

    # Wins over ranked/title-holding opponents: +3 per win, cap +15
    # We approximate "ranked/title-holding" as opponents who have had title fights
    ranked_wins = 0
    for fight in fights:
        if fight["winner_id"] != fighter_id:
            continue
        opp_id = (
            fight["fighter2_id"]
            if fight["fighter1_id"] == fighter_id
            else fight["fighter1_id"]
        )
        opp_fights = database.get_fighter_fights(opp_id)
        if any(of["is_title_fight"] for of in opp_fights):
            ranked_wins += 1

    bonus += min(ranked_wins * 3, 15)

    # Max raw bonus = 15 + 20 + 15 = 50. Normalize to 0-100.
    return _clamp((bonus / 50.0) * 100.0)


# ---------------------------------------------------------------------------
# 5.7 Final FQS
# ---------------------------------------------------------------------------

def calc_fqs(fighter_id: str, fqs_cache: dict | None = None) -> dict:
    """Calculate full FQS breakdown for a fighter.

    Returns dict with each sub-score and the final composite FQS.
    """
    oq = calc_opponent_quality(fighter_id)
    wm = calc_win_method_score(fighter_id)
    lq = calc_loss_quality(fighter_id, fqs_cache)
    rc = calc_recency_score(fighter_id)
    st = calc_streak_score(fighter_id)
    ch = calc_championship_score(fighter_id)

    fqs = (
        oq * WEIGHT_OPPONENT_QUALITY
        + wm * WEIGHT_WIN_METHOD
        + lq * WEIGHT_LOSS_QUALITY
        + rc * WEIGHT_RECENCY
        + st * WEIGHT_STREAK
        + ch * WEIGHT_CHAMPIONSHIP
    )

    return {
        "fqs": round(fqs, 1),
        "opponent_quality": round(oq, 1),
        "win_method": round(wm, 1),
        "loss_quality": round(lq, 1),
        "recency": round(rc, 1),
        "streak_momentum": round(st, 1),
        "championship": round(ch, 1),
    }


def calc_all_fqs() -> dict[str, float]:
    """Calculate FQS for all fighters with iterative convergence.

    Returns a dict mapping fighter_id → FQS value.
    """
    fighters = database.get_all_fighters()
    fqs_cache: dict[str, float] = {}

    for iteration in range(FQS_MAX_ITERATIONS):
        print(f"  FQS iteration {iteration + 1}/{FQS_MAX_ITERATIONS}...")
        new_cache: dict[str, float] = {}
        max_change = 0.0

        for f in fighters:
            result = calc_fqs(f["id"], fqs_cache)
            new_fqs = result["fqs"]
            old_fqs = fqs_cache.get(f["id"], 50.0)
            max_change = max(max_change, abs(new_fqs - old_fqs))
            new_cache[f["id"]] = new_fqs

        fqs_cache = new_cache
        print(f"    Max change: {max_change:.2f}")

        if max_change < FQS_CONVERGENCE_THRESHOLD:
            print(f"  Converged after {iteration + 1} iterations.")
            break

    return fqs_cache

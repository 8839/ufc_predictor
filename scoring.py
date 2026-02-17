"""Fighter Quality Score (FQS) calculation engine."""

import math
from datetime import datetime

import database
import utils
from config import (
    ACTIVITY_LOOKBACK_YEARS,
    ACTIVITY_OPTIMAL_FIGHTS_PER_YEAR,
    ACTIVITY_RING_RUST_DAYS,
    FQS_CONVERGENCE_THRESHOLD,
    FQS_MAX_ITERATIONS,
    OVERALL_DEC_RATE,
    OVERALL_KO_RATE,
    OVERALL_SUB_RATE,
    RECENCY_LAMBDA,
    WEIGHT_ACTIVITY_RATE,
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
# Weight Class Baselines Computation
# ---------------------------------------------------------------------------

def compute_weight_class_baselines() -> dict[str, dict]:
    """Compute KO/SUB/DEC rates per weight class from all fights.

    Persists results to the weight_class_baselines table and returns
    a dict mapping weight_class -> {ko_rate, sub_rate, dec_rate,
    avg_finish_round, avg_fights_per_year}.
    """
    conn = database.get_connection()

    rows = conn.execute("""
        SELECT weight_class,
               COUNT(*) as total,
               SUM(CASE WHEN win_method = 'KO/TKO' THEN 1 ELSE 0 END) as ko_count,
               SUM(CASE WHEN win_method = 'SUB' THEN 1 ELSE 0 END) as sub_count,
               SUM(CASE WHEN win_method IN ('U-DEC','M-DEC','S-DEC') THEN 1 ELSE 0 END) as dec_count,
               AVG(CASE WHEN win_method IN ('KO/TKO','SUB') THEN finish_round ELSE NULL END) as avg_finish_round,
               MIN(event_date) as earliest,
               MAX(event_date) as latest
        FROM fights
        WHERE weight_class IS NOT NULL AND winner_id IS NOT NULL
        GROUP BY weight_class
    """).fetchall()

    conn.close()

    baselines = {}
    now = datetime.now()

    for r in rows:
        wc = r["weight_class"]
        total = r["total"]
        if total == 0:
            continue

        ko_rate = (r["ko_count"] or 0) / total
        sub_rate = (r["sub_count"] or 0) / total
        dec_rate = (r["dec_count"] or 0) / total
        avg_finish = r["avg_finish_round"] or 2.0

        # Avg fights per year for this weight class
        earliest = r["earliest"]
        latest = r["latest"]
        if earliest and latest:
            try:
                dt_early = datetime.strptime(earliest, "%Y-%m-%d")
                dt_late = datetime.strptime(latest, "%Y-%m-%d")
                span_years = max((dt_late - dt_early).days / 365.25, 1.0)
                avg_fights_per_year = total / span_years
            except ValueError:
                avg_fights_per_year = 2.0
        else:
            avg_fights_per_year = 2.0

        baseline = {
            "weight_class": wc,
            "ko_rate": round(ko_rate, 4),
            "sub_rate": round(sub_rate, 4),
            "dec_rate": round(dec_rate, 4),
            "avg_finish_round": round(avg_finish, 2),
            "avg_fights_per_year": round(avg_fights_per_year, 2),
            "last_computed": now.isoformat(),
        }

        database.upsert_weight_class_baseline(baseline)
        baselines[wc] = baseline

    return baselines


# ---------------------------------------------------------------------------
# 5.1 Opponent Quality Score
# ---------------------------------------------------------------------------

def _get_opponent_id(fight: dict, fighter_id: str) -> str:
    """Return the opponent's fighter ID from a fight record."""
    return fight["fighter2_id"] if fight["fighter1_id"] == fighter_id else fight["fighter1_id"]


def _opponent_win_rate(fighter_id: str) -> float:
    """Simple win rate for a fighter (0-1)."""
    f = database.get_fighter(fighter_id)
    if not f:
        return 0.5
    total = (f["wins"] or 0) + (f["losses"] or 0)
    if total == 0:
        return 0.5
    return (f["wins"] or 0) / total


def _fqs_cache_range(fqs_cache: dict) -> tuple[float, float]:
    """Return (min, max) of FQS values in the cache."""
    vals = fqs_cache.values()
    return min(vals), max(vals)


def _opponent_strength(fighter_id: str, fqs_cache: dict | None = None,
                       fqs_range: tuple[float, float] | None = None) -> float:
    """Get opponent strength (0-1).

    When fqs_cache is available, rescales the opponent's FQS to the typical
    win-rate range [0.25, 0.90] and returns the maximum of that and the raw
    win rate.  This uplifts fighters whose record doesn't reflect their true
    quality (e.g. a gatekeeper who fights only killers).
    """
    win_rate = _opponent_win_rate(fighter_id)
    if fqs_cache and fighter_id in fqs_cache and fqs_range:
        fqs_val = fqs_cache[fighter_id]
        fqs_min, fqs_max = fqs_range
        if fqs_max > fqs_min:
            normalized = (fqs_val - fqs_min) / (fqs_max - fqs_min)
            fqs_scaled = 0.25 + normalized * 0.65  # maps to [0.25, 0.90]
        else:
            fqs_scaled = 0.50
        return max(win_rate, fqs_scaled)
    return win_rate


def _opponent_opponent_strength(fighter_id: str, fqs_cache: dict | None = None,
                                fqs_range: tuple[float, float] | None = None) -> float:
    """Average strength of a fighter's opponents (level 2)."""
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 0.5
    rates = []
    for fight in fights:
        opp_id = _get_opponent_id(fight, fighter_id)
        rates.append(_opponent_strength(opp_id, fqs_cache, fqs_range))
    return sum(rates) / len(rates) if rates else 0.5


def calc_opponent_quality(fighter_id: str, fqs_cache: dict | None = None) -> float:
    """Calculate opponent quality score (0-100). Spec section 5.1.

    Uses recency-weighted opponent strength so that recent fights against
    elite opponents count more than early-career fights.  When fqs_cache is
    provided, uses FQS-based opponent strength (via max(win_rate, fqs/100))
    so fighters get proper credit for beating high-quality opponents whose
    records may be deflated by tough competition.
    """
    fights = database.get_fighter_fights(fighter_id)
    if not fights:
        return 50.0

    # Precompute FQS range once for rescaling
    fqs_range = _fqs_cache_range(fqs_cache) if fqs_cache else None

    win_qualities = []
    win_weights = []
    loss_qualities = []
    loss_weights = []

    for fight in fights:
        opp_id = _get_opponent_id(fight, fighter_id)

        opp_str = _opponent_strength(opp_id, fqs_cache, fqs_range)
        opp_opp_str = _opponent_opponent_strength(opp_id, fqs_cache, fqs_range)
        fight_opp_quality = 0.7 * opp_str + 0.3 * opp_opp_str

        # Recency weight: recent fights count more (decay over years)
        years = utils.years_since(fight.get("event_date"))
        recency_weight = math.exp(-0.15 * years)  # gentler decay than recency score

        is_win = fight["winner_id"] == fighter_id
        is_loss = fight["winner_id"] is not None and fight["winner_id"] != fighter_id

        if is_win:
            win_qualities.append(fight_opp_quality * recency_weight)
            win_weights.append(recency_weight)
        elif is_loss:
            loss_qualities.append((1.0 - fight_opp_quality) * recency_weight)
            loss_weights.append(recency_weight)

    total_win_w = sum(win_weights)
    total_loss_w = sum(loss_weights)
    avg_win_q = sum(win_qualities) / total_win_w if total_win_w > 0 else 0.0
    avg_loss_penalty = sum(loss_qualities) / total_loss_w if total_loss_w > 0 else 0.0

    raw = avg_win_q - 0.5 * avg_loss_penalty
    # Stretch factor: raw practically ranges [0, 0.75] due to level-2
    # regression.  Use *130 to spread the distribution into full 0-100.
    return _clamp(raw * 130.0)


# ---------------------------------------------------------------------------
# 5.2 Win Method Score
# ---------------------------------------------------------------------------

def _wc_method_multiplier(method: str, fight_wc: str | None,
                          wc_baselines: dict | None) -> float:
    """Weight-class multiplier for a win method.

    KO at flyweight (low KO rate) gets a bonus; KO at heavyweight (high KO
    rate) gets a penalty.  Decisions at heavyweight get a slight bonus
    (surviving = durability).  Clamped to [0.75, 1.35].
    """
    if not wc_baselines or not fight_wc or fight_wc not in wc_baselines:
        return 1.0

    bl = wc_baselines[fight_wc]

    if method == "KO/TKO":
        wc_rate = bl.get("ko_rate") or OVERALL_KO_RATE
        raw = OVERALL_KO_RATE / wc_rate if wc_rate > 0 else 1.0
    elif method == "SUB":
        wc_rate = bl.get("sub_rate") or OVERALL_SUB_RATE
        raw = OVERALL_SUB_RATE / wc_rate if wc_rate > 0 else 1.0
    elif method in ("U-DEC", "M-DEC", "S-DEC"):
        wc_rate = bl.get("dec_rate") or OVERALL_DEC_RATE
        raw = OVERALL_DEC_RATE / wc_rate if wc_rate > 0 else 1.0
    else:
        return 1.0

    return max(0.75, min(1.35, raw))


def calc_win_method_score(fighter_id: str, wc_baselines: dict | None = None) -> float:
    """Calculate win method score (0-100). Spec section 5.2.

    When wc_baselines is provided, applies weight-class multipliers so that
    e.g. a KO at flyweight is worth more than a KO at heavyweight.
    """
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

        raw_score = base + round_bonus

        # Apply weight-class multiplier
        wc_mult = _wc_method_multiplier(method, fight.get("weight_class"), wc_baselines)
        scores.append(raw_score * wc_mult)

    if not scores:
        return 50.0

    avg = sum(scores) / len(scores)
    # Max possible = (10 + 2.5) * 1.35 ≈ 16.9, use 15.0 as normalizer
    return _clamp((avg / 15.0) * 100.0)


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

    # Ring rust penalty removed — now handled by calc_activity_rate

    return _clamp(score)


# ---------------------------------------------------------------------------
# 5.6 Activity Rate Score (NEW in V2)
# ---------------------------------------------------------------------------

def calc_activity_rate(fighter_id: str, wc_baselines: dict | None = None) -> float:
    """Calculate activity rate score (0-100).

    Components:
      1. (0-50 pts) fights/year over last ACTIVITY_LOOKBACK_YEARS vs optimal
      2. (0-40 pts) days since last fight (tiered)
      3. (0-10 pts) compared to weight class average activity
    """
    fight_dates = database.get_fighter_fight_dates(fighter_id)
    if not fight_dates:
        return 25.0  # no data — below average

    now = datetime.now()

    # Component 1: fights per year in lookback window
    cutoff = now.timestamp() - ACTIVITY_LOOKBACK_YEARS * 365.25 * 86400
    recent_count = 0
    for d in fight_dates:
        try:
            dt = datetime.strptime(d, "%Y-%m-%d")
            if dt.timestamp() >= cutoff:
                recent_count += 1
        except ValueError:
            continue

    fights_per_year = recent_count / ACTIVITY_LOOKBACK_YEARS
    ratio = fights_per_year / ACTIVITY_OPTIMAL_FIGHTS_PER_YEAR
    comp1 = min(ratio, 1.0) * 50.0

    # Component 2: days since last fight (tiered)
    try:
        last_fight = datetime.strptime(fight_dates[0], "%Y-%m-%d")
        days_since = (now - last_fight).days
    except ValueError:
        days_since = 9999

    if days_since < 90:
        comp2 = 40.0
    elif days_since < 180:
        comp2 = 35.0
    elif days_since < 365:
        comp2 = 25.0
    elif days_since < ACTIVITY_RING_RUST_DAYS:
        comp2 = 15.0
    elif days_since < 730:
        comp2 = 8.0
    else:
        comp2 = 0.0

    # Component 3: compared to weight class average
    comp3 = 5.0  # default middle value
    if wc_baselines:
        wc = database.get_fighter_primary_weight_class(fighter_id)
        if wc and wc in wc_baselines:
            wc_avg = wc_baselines[wc].get("avg_fights_per_year", 2.0)
            if wc_avg > 0:
                wc_ratio = fights_per_year / wc_avg
                comp3 = min(wc_ratio, 1.5) / 1.5 * 10.0

    return _clamp(comp1 + comp2 + comp3)


# ---------------------------------------------------------------------------
# 5.7 Championship Modifier
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

def calc_fqs(fighter_id: str, fqs_cache: dict | None = None,
             wc_baselines: dict | None = None) -> dict:
    """Calculate full FQS breakdown for a fighter.

    Returns dict with each sub-score and the final composite FQS.
    """
    oq = calc_opponent_quality(fighter_id, fqs_cache)
    wm = calc_win_method_score(fighter_id, wc_baselines)
    lq = calc_loss_quality(fighter_id, fqs_cache)
    rc = calc_recency_score(fighter_id)
    st = calc_streak_score(fighter_id)
    ch = calc_championship_score(fighter_id)
    ar = calc_activity_rate(fighter_id, wc_baselines)

    fqs = (
        oq * WEIGHT_OPPONENT_QUALITY
        + wm * WEIGHT_WIN_METHOD
        + lq * WEIGHT_LOSS_QUALITY
        + rc * WEIGHT_RECENCY
        + st * WEIGHT_STREAK
        + ch * WEIGHT_CHAMPIONSHIP
        + ar * WEIGHT_ACTIVITY_RATE
    )

    return {
        "fqs": round(fqs, 1),
        "opponent_quality": round(oq, 1),
        "win_method": round(wm, 1),
        "loss_quality": round(lq, 1),
        "recency": round(rc, 1),
        "streak_momentum": round(st, 1),
        "championship": round(ch, 1),
        "activity_rate": round(ar, 1),
    }


def calc_all_fqs(wc_baselines: dict | None = None) -> dict[str, float]:
    """Calculate FQS for all fighters with iterative convergence.

    Returns a dict mapping fighter_id -> FQS value.
    """
    fighters = database.get_all_fighters()
    fqs_cache: dict[str, float] = {}

    for iteration in range(FQS_MAX_ITERATIONS):
        print(f"  FQS iteration {iteration + 1}/{FQS_MAX_ITERATIONS}...")
        new_cache: dict[str, float] = {}
        max_change = 0.0

        for f in fighters:
            result = calc_fqs(f["id"], fqs_cache, wc_baselines)
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

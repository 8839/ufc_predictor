"""Backtesting and weight learning for UFC Fight Predictor."""

import json
import os
import random
import time
from datetime import datetime

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

import database
from scoring import calc_fqs, calc_all_fqs, compute_weight_class_baselines

TRAIN_CUTOFF = "2023-01-01"


def _collect_sub_scores(fights: list[dict], fqs_cache: dict,
                        wc_baselines: dict, cutoff_date: str) -> list[dict]:
    """Compute FQS sub-score differences for a list of fights.

    For each fight, computes the 7 sub-scores for both fighters using data
    available before cutoff_date, then returns the differences (f1 - f2)
    along with the label (1 if fighter1 won, 0 if fighter2 won).

    Note: The DB always stores the winner as fighter1_id, so we randomly
    swap fighter order for 50% of fights to create balanced labels.
    """
    rng = random.Random(42)  # deterministic for reproducibility
    samples = []
    total = len(fights)

    for i, fight in enumerate(fights):
        if (i + 1) % 200 == 0:
            print(f"    Processing fight {i + 1}/{total}...")

        f1_id = fight["fighter1_id"]
        f2_id = fight["fighter2_id"]
        winner_id = fight["winner_id"]

        # Skip if we can't determine winner relative to fighter1/fighter2
        if winner_id not in (f1_id, f2_id):
            continue

        # Randomly swap fighter order to balance labels (since DB always
        # stores winner as fighter1_id)
        if rng.random() < 0.5:
            f1_id, f2_id = f2_id, f1_id

        # Compute sub-scores for both fighters using pre-fight data
        f1_scores = calc_fqs(f1_id, fqs_cache, wc_baselines, cutoff_date)
        f2_scores = calc_fqs(f2_id, fqs_cache, wc_baselines, cutoff_date)

        # Both fighters need some fight history
        if f1_scores["fqs"] == 0.0 and f2_scores["fqs"] == 0.0:
            continue

        sample = {
            "fight_id": fight["id"],
            "event_date": fight["event_date"],
            "f1_id": f1_id,
            "f2_id": f2_id,
            "winner_id": winner_id,
            "label": 1 if winner_id == f1_id else 0,
            # Sub-score differences (fighter1 - fighter2)
            "oq_diff": f1_scores["opponent_quality"] - f2_scores["opponent_quality"],
            "wm_diff": f1_scores["win_method"] - f2_scores["win_method"],
            "lq_diff": f1_scores["loss_quality"] - f2_scores["loss_quality"],
            "rc_diff": f1_scores["recency"] - f2_scores["recency"],
            "st_diff": f1_scores["streak_momentum"] - f2_scores["streak_momentum"],
            "ch_diff": f1_scores["championship"] - f2_scores["championship"],
            "ar_diff": f1_scores["activity_rate"] - f2_scores["activity_rate"],
            # Also store raw FQS for baseline comparison
            "f1_fqs": f1_scores["fqs"],
            "f2_fqs": f2_scores["fqs"],
        }
        samples.append(sample)

    return samples


def learn_weights(quiet: bool = False) -> dict:
    """Learn optimal FQS weights from pre-2023 fight data using logistic regression.

    Returns dict with learned weights (normalized to sum to 1.0) and model metrics.
    """
    if not quiet:
        print("\n" + "=" * 60)
        print("LEARNING FQS WEIGHTS FROM HISTORICAL DATA")
        print("=" * 60)

    # Step 1: Compute FQS cache and baselines from pre-training data
    # Use pre-2020 data for FQS cache to avoid leakage into 2020-2022 training fights
    fqs_cutoff = "2020-01-01"
    if not quiet:
        print(f"\n  Computing FQS cache using data before {fqs_cutoff}...")
    wc_baselines = compute_weight_class_baselines(fqs_cutoff)
    fqs_cache = calc_all_fqs(wc_baselines, fqs_cutoff, quiet=quiet)

    # Step 2: Collect training data from 2020-2022 fights
    # This way FQS cache doesn't include the fights we're training on
    if not quiet:
        print(f"\n  Collecting training samples (2020-01-01 to {TRAIN_CUTOFF})...")
    train_fights = database.get_fights_in_range("2020-01-01", TRAIN_CUTOFF)
    if not quiet:
        print(f"    Found {len(train_fights)} training fights")

    train_samples = _collect_sub_scores(train_fights, fqs_cache, wc_baselines, fqs_cutoff)
    if not quiet:
        print(f"    Collected {len(train_samples)} valid training samples")

    if len(train_samples) < 50:
        print("  ERROR: Not enough training data for logistic regression.")
        return {}

    # Step 3: Build feature matrix
    feature_names = ["oq_diff", "wm_diff", "lq_diff", "rc_diff",
                     "st_diff", "ch_diff", "ar_diff"]
    X = np.array([[s[f] for f in feature_names] for s in train_samples])
    y = np.array([s["label"] for s in train_samples])

    # Step 4: Train logistic regression
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = LogisticRegression(
        penalty="l2",
        C=1.0,
        max_iter=1000,
        solver="lbfgs",
        fit_intercept=True,
    )
    model.fit(X_scaled, y)

    # Step 5: Extract and normalize coefficients to weights
    raw_coefs = model.coef_[0]

    # Convert scaled coefficients back to original feature space
    # coef_original = coef_scaled / std_dev
    original_coefs = raw_coefs / scaler.scale_

    # Take absolute values (sign doesn't matter for weighting since features
    # are already differences — positive diff = fighter1 advantage)
    abs_coefs = np.abs(original_coefs)
    weight_sum = abs_coefs.sum()

    if weight_sum == 0:
        print("  ERROR: All coefficients are zero.")
        return {}

    normalized_weights = abs_coefs / weight_sum

    learned = {}
    weight_keys = ["opponent_quality", "win_method", "loss_quality",
                   "recency", "streak", "championship", "activity_rate"]
    for key, weight in zip(weight_keys, normalized_weights):
        learned[key] = round(float(weight), 4)

    # Step 6: Training accuracy
    train_preds = model.predict(X_scaled)
    train_acc = np.mean(train_preds == y) * 100

    # Also compute FQS-ratio baseline accuracy on training data
    fqs_baseline_correct = sum(
        1 for s in train_samples
        if (s["f1_fqs"] >= s["f2_fqs"]) == (s["label"] == 1)
    )
    fqs_baseline_acc = fqs_baseline_correct / len(train_samples) * 100

    if not quiet:
        print(f"\n  Training results ({len(train_samples)} fights):")
        print(f"    Logistic regression accuracy: {train_acc:.1f}%")
        print(f"    FQS-ratio baseline accuracy:  {fqs_baseline_acc:.1f}%")
        print(f"    Random baseline:              50.0%")
        print(f"\n  Learned weights (normalized to sum=1.0):")
        from config import (WEIGHT_OPPONENT_QUALITY, WEIGHT_WIN_METHOD,
                            WEIGHT_LOSS_QUALITY, WEIGHT_RECENCY, WEIGHT_STREAK,
                            WEIGHT_CHAMPIONSHIP, WEIGHT_ACTIVITY_RATE)
        old_weights = {
            "opponent_quality": WEIGHT_OPPONENT_QUALITY,
            "win_method": WEIGHT_WIN_METHOD,
            "loss_quality": WEIGHT_LOSS_QUALITY,
            "recency": WEIGHT_RECENCY,
            "streak": WEIGHT_STREAK,
            "championship": WEIGHT_CHAMPIONSHIP,
            "activity_rate": WEIGHT_ACTIVITY_RATE,
        }
        print(f"    {'Component':<22} {'Old':>8} {'Learned':>8} {'Change':>8}")
        print(f"    {'-'*22} {'-'*8} {'-'*8} {'-'*8}")
        for key in weight_keys:
            old = old_weights[key]
            new = learned[key]
            change = new - old
            print(f"    {key:<22} {old:>8.4f} {new:>8.4f} {change:>+8.4f}")

    return {
        "weights": learned,
        "train_accuracy": round(train_acc, 2),
        "fqs_baseline_accuracy": round(fqs_baseline_acc, 2),
        "train_samples": len(train_samples),
        "intercept": float(model.intercept_[0]),
    }


def run_backtest(use_learned_weights: bool = True) -> dict:
    """Run backtest on 2023+ fights using data available before each fight.

    Steps:
    1. Learn weights from pre-2023 data (if use_learned_weights)
    2. Compute FQS cache from pre-2023 data
    3. For each 2023+ fight, predict outcome using pre-fight data
    4. Report accuracy vs baselines
    """
    print("\n" + "=" * 60)
    print("UFC FIGHT PREDICTOR — BACKTEST")
    print("=" * 60)

    start_time = time.time()

    # Step 1: Learn weights or load from previous run
    learned_weights = None
    learning_result = {}
    if use_learned_weights:
        weights_path = os.path.join(os.path.dirname(__file__), "data", "learned_weights.json")
        if os.path.exists(weights_path):
            with open(weights_path) as f:
                saved = json.load(f)
            learned_weights = saved["weights"]
            learning_result = saved
            print(f"  Loaded previously learned weights from {weights_path}")
            print(f"  Weights: {learned_weights}")
        else:
            learning_result = learn_weights()
            if learning_result:
                learned_weights = learning_result["weights"]
            else:
                print("  Weight learning failed, using default weights.")

    # Step 2: Compute FQS cache from pre-2023 data
    print(f"\n  Computing FQS cache using data before {TRAIN_CUTOFF}...")
    wc_baselines = compute_weight_class_baselines(TRAIN_CUTOFF)
    fqs_cache = calc_all_fqs(wc_baselines, TRAIN_CUTOFF, learned_weights, quiet=False)

    # Step 3: Get test fights (2023+)
    test_fights = database.get_fights_in_range(TRAIN_CUTOFF)
    print(f"\n  Test set: {len(test_fights)} fights from {TRAIN_CUTOFF} onward")

    # Step 4: Predict each test fight
    # Note: DB stores winner as fighter1_id always, so we compare FQS of both
    # fighters and check if the higher-FQS fighter is the actual winner.
    print("  Running predictions...")
    results = {
        "correct_default": 0,
        "correct_learned": 0,
        "correct_favorite": 0,  # always pick fighter with more wins
        "total": 0,
        "skipped": 0,
        "by_confidence": {
            "high": {"correct": 0, "total": 0},    # >= 65%
            "medium": {"correct": 0, "total": 0},   # 55-65%
            "low": {"correct": 0, "total": 0},      # < 55%
        },
    }

    for i, fight in enumerate(test_fights):
        if (i + 1) % 200 == 0:
            print(f"    Predicting fight {i + 1}/{len(test_fights)}...")

        # fighter1_id is always the winner in this DB
        winner_id = fight["fighter1_id"]
        loser_id = fight["fighter2_id"]

        if not fight["winner_id"]:
            results["skipped"] += 1
            continue

        # Compute FQS for both fighters with default weights
        winner_fqs_def = calc_fqs(winner_id, fqs_cache, wc_baselines, TRAIN_CUTOFF)
        loser_fqs_def = calc_fqs(loser_id, fqs_cache, wc_baselines, TRAIN_CUTOFF)

        total_fqs = winner_fqs_def["fqs"] + loser_fqs_def["fqs"]
        if total_fqs == 0:
            results["skipped"] += 1
            continue

        # Default weights: correct if winner has higher FQS
        default_correct = winner_fqs_def["fqs"] >= loser_fqs_def["fqs"]
        default_winner_prob = winner_fqs_def["fqs"] / total_fqs

        # Learned weights prediction
        learned_correct = default_correct
        learned_winner_prob = default_winner_prob
        if learned_weights:
            winner_fqs_lr = calc_fqs(winner_id, fqs_cache, wc_baselines,
                                     TRAIN_CUTOFF, learned_weights)
            loser_fqs_lr = calc_fqs(loser_id, fqs_cache, wc_baselines,
                                    TRAIN_CUTOFF, learned_weights)
            total_lr = winner_fqs_lr["fqs"] + loser_fqs_lr["fqs"]
            if total_lr > 0:
                learned_winner_prob = winner_fqs_lr["fqs"] / total_lr
                learned_correct = winner_fqs_lr["fqs"] >= loser_fqs_lr["fqs"]

        # Favorite baseline: pick fighter with more total wins
        w_data = database.get_fighter(winner_id)
        l_data = database.get_fighter(loser_id)
        w_wins = (w_data or {}).get("wins", 0) or 0
        l_wins = (l_data or {}).get("wins", 0) or 0
        fav_correct = w_wins >= l_wins

        results["total"] += 1
        results["correct_default"] += int(default_correct)
        results["correct_learned"] += int(learned_correct)
        results["correct_favorite"] += int(fav_correct)

        # Confidence bucketing: how confident is the model in its *pick*?
        prob = learned_winner_prob if learned_weights else default_winner_prob
        model_conf = max(prob, 1.0 - prob)  # confidence in model's pick
        is_correct = learned_correct if learned_weights else default_correct
        if model_conf >= 0.65:
            bucket = "high"
        elif model_conf >= 0.55:
            bucket = "medium"
        else:
            bucket = "low"
        results["by_confidence"][bucket]["total"] += 1
        results["by_confidence"][bucket]["correct"] += int(is_correct)

    elapsed = time.time() - start_time

    # Step 5: Report results
    total = results["total"]
    if total == 0:
        print("\n  No test fights could be evaluated.")
        return results

    default_acc = results["correct_default"] / total * 100
    learned_acc = results["correct_learned"] / total * 100
    fav_acc = results["correct_favorite"] / total * 100

    print("\n" + "=" * 60)
    print("BACKTEST RESULTS")
    print("=" * 60)
    print(f"  Test period:       {TRAIN_CUTOFF} to present")
    print(f"  Fights evaluated:  {total}")
    print(f"  Fights skipped:    {results['skipped']}")
    print(f"  Time elapsed:      {elapsed:.1f}s")
    print()
    print(f"  {'Model':<30} {'Accuracy':>10} {'Correct':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10}")
    print(f"  {'Random baseline':<30} {'50.0%':>10} {'':<10}")
    print(f"  {'Pick more wins (favorite)':<30} {fav_acc:>9.1f}% {results['correct_favorite']:>10}/{total}")
    print(f"  {'FQS (default weights)':<30} {default_acc:>9.1f}% {results['correct_default']:>10}/{total}")
    if learned_weights:
        print(f"  {'FQS (learned weights)':<30} {learned_acc:>9.1f}% {results['correct_learned']:>10}/{total}")

    print("\n  Accuracy by confidence tier (learned weights):")
    for tier_name, tier_data in results["by_confidence"].items():
        if tier_data["total"] > 0:
            tier_acc = tier_data["correct"] / tier_data["total"] * 100
            print(f"    {tier_name:>8}: {tier_acc:>5.1f}%  ({tier_data['correct']}/{tier_data['total']})")
        else:
            print(f"    {tier_name:>8}: N/A  (0 fights)")

    # Save learned weights to file
    if learned_weights:
        weights_path = os.path.join(os.path.dirname(__file__), "data", "learned_weights.json")
        output = {
            "weights": learned_weights,
            "train_accuracy": learning_result.get("train_accuracy"),
            "test_accuracy_default": round(default_acc, 2),
            "test_accuracy_learned": round(learned_acc, 2),
            "test_fights": total,
            "train_samples": learning_result.get("train_samples"),
            "computed_date": datetime.utcnow().isoformat(),
        }
        with open(weights_path, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\n  Learned weights saved to: {weights_path}")

    print("\n" + "=" * 60)

    return {
        "total": total,
        "default_accuracy": round(default_acc, 2),
        "learned_accuracy": round(learned_acc, 2) if learned_weights else None,
        "favorite_accuracy": round(fav_acc, 2),
        "learned_weights": learned_weights,
        "by_confidence": results["by_confidence"],
    }

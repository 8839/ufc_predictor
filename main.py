"""CLI entry point for UFC Fight Predictor."""

import argparse
import sys

import database
import scraper
import utils
from predictor import (
    format_fighter_profile,
    format_history,
    format_prediction,
    predict_fight,
    save_prediction,
)
from scoring import compute_weight_class_baselines


def cmd_scrape(args):
    """Handle scrape command."""
    if args.full:
        scraper.full_scrape()
    elif args.refresh:
        scraper.refresh_scrape()
    else:
        print("Specify --full or --refresh. Use --help for details.")


def cmd_predict(args):
    """Handle predict command."""
    database.init_db()

    f1 = utils.fuzzy_find_fighter(args.fighter1)
    if not f1:
        sys.exit(1)
    f2 = utils.fuzzy_find_fighter(args.fighter2)
    if not f2:
        sys.exit(1)

    print(f"\nAnalyzing: {f1['name']} vs {f2['name']}...")
    print("  Computing weight class baselines...")
    wc_baselines = compute_weight_class_baselines()
    print()

    prediction = predict_fight(f1["id"], f2["id"], wc_baselines=wc_baselines)
    output = format_prediction(prediction)
    print(output)

    # Save prediction
    pred_id = save_prediction(prediction)
    print(f"\nPrediction saved (ID: {pred_id})")


def cmd_fighter(args):
    """Handle fighter command."""
    database.init_db()

    fighter = utils.fuzzy_find_fighter(args.name)
    if not fighter:
        sys.exit(1)

    print("  Computing weight class baselines...")
    wc_baselines = compute_weight_class_baselines()

    output = format_fighter_profile(fighter["id"], wc_baselines=wc_baselines)
    print(output)


def cmd_history(args):
    """Handle history command."""
    database.init_db()
    print(format_history())


def cmd_update_result(args):
    """Handle update-result command."""
    database.init_db()

    # Find the winner fighter
    winner = utils.fuzzy_find_fighter(args.winner)
    if not winner:
        sys.exit(1)

    pred = database.get_prediction(args.prediction_id)
    if not pred:
        print(f"Prediction #{args.prediction_id} not found.")
        sys.exit(1)

    correct = database.update_prediction_result(
        args.prediction_id, winner["id"], args.method
    )

    if correct:
        print(f"Prediction #{args.prediction_id} marked as CORRECT.")
    else:
        print(f"Prediction #{args.prediction_id} marked as WRONG.")


def main():
    parser = argparse.ArgumentParser(
        description="UFC Fight Predictor — predict fight outcomes using data analysis"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # scrape
    scrape_parser = subparsers.add_parser("scrape", help="Scrape data from UFCStats.com")
    scrape_group = scrape_parser.add_mutually_exclusive_group(required=True)
    scrape_group.add_argument("--full", action="store_true", help="Full database build")
    scrape_group.add_argument(
        "--refresh", action="store_true", help="Incremental refresh"
    )
    scrape_parser.set_defaults(func=cmd_scrape)

    # predict
    predict_parser = subparsers.add_parser("predict", help="Predict a fight outcome")
    predict_parser.add_argument("fighter1", help="First fighter name")
    predict_parser.add_argument("fighter2", help="Second fighter name")
    predict_parser.set_defaults(func=cmd_predict)

    # fighter
    fighter_parser = subparsers.add_parser(
        "fighter", help="View fighter profile and FQS"
    )
    fighter_parser.add_argument("name", help="Fighter name")
    fighter_parser.set_defaults(func=cmd_fighter)

    # history
    history_parser = subparsers.add_parser(
        "history", help="View prediction history and accuracy"
    )
    history_parser.set_defaults(func=cmd_history)

    # update-result
    update_parser = subparsers.add_parser(
        "update-result", help="Update a prediction with actual result"
    )
    update_parser.add_argument(
        "--prediction-id", type=int, required=True, help="Prediction ID to update"
    )
    update_parser.add_argument(
        "--winner", required=True, help="Actual winner name"
    )
    update_parser.add_argument(
        "--method", required=True, help="Actual method of victory"
    )
    update_parser.set_defaults(func=cmd_update_result)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    args.func(args)


if __name__ == "__main__":
    main()

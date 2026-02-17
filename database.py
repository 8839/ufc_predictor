"""SQLite setup, migrations, and CRUD operations."""

import sqlite3
from datetime import datetime

from config import DB_PATH


def get_connection():
    """Return a connection to the SQLite database."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create all tables if they don't exist."""
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fighters (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            nickname TEXT,
            height_inches INTEGER,
            weight_lbs INTEGER,
            reach_inches REAL,
            stance TEXT,
            dob TEXT,
            wins INTEGER,
            losses INTEGER,
            draws INTEGER,
            no_contests INTEGER,
            sig_strikes_landed_per_min REAL,
            sig_strike_accuracy REAL,
            sig_strikes_absorbed_per_min REAL,
            sig_strike_defense REAL,
            takedown_avg_per_15min REAL,
            takedown_accuracy REAL,
            takedown_defense REAL,
            submission_avg_per_15min REAL,
            last_updated TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fights (
            id TEXT PRIMARY KEY,
            event_name TEXT,
            event_date TEXT,
            fighter1_id TEXT REFERENCES fighters(id),
            fighter2_id TEXT REFERENCES fighters(id),
            winner_id TEXT REFERENCES fighters(id),
            win_method TEXT,
            win_method_detail TEXT,
            finish_round INTEGER,
            finish_time TEXT,
            is_title_fight INTEGER,
            weight_class TEXT,
            num_rounds INTEGER
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS fight_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fight_id TEXT REFERENCES fights(id),
            fighter_id TEXT REFERENCES fighters(id),
            knockdowns INTEGER,
            sig_strikes_landed INTEGER,
            sig_strikes_attempted INTEGER,
            total_strikes_landed INTEGER,
            total_strikes_attempted INTEGER,
            takedowns_landed INTEGER,
            takedowns_attempted INTEGER,
            submission_attempts INTEGER,
            reversals INTEGER,
            control_time_seconds INTEGER,
            UNIQUE(fight_id, fighter_id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS weight_class_baselines (
            weight_class TEXT PRIMARY KEY,
            ko_rate REAL,
            sub_rate REAL,
            dec_rate REAL,
            avg_finish_round REAL,
            avg_fights_per_year REAL,
            last_computed TEXT
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fighter1_id TEXT REFERENCES fighters(id),
            fighter2_id TEXT REFERENCES fighters(id),
            predicted_winner_id TEXT REFERENCES fighters(id),
            confidence REAL,
            predicted_method TEXT,
            fighter1_fqs REAL,
            fighter2_fqs REAL,
            actual_winner_id TEXT,
            actual_method TEXT,
            correct INTEGER,
            prediction_date TEXT,
            fight_date TEXT
        )
    """)

    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Fighter CRUD
# ---------------------------------------------------------------------------

def upsert_fighter(fighter: dict):
    """Insert or update a fighter record."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO fighters (
            id, name, nickname, height_inches, weight_lbs, reach_inches,
            stance, dob, wins, losses, draws, no_contests,
            sig_strikes_landed_per_min, sig_strike_accuracy,
            sig_strikes_absorbed_per_min, sig_strike_defense,
            takedown_avg_per_15min, takedown_accuracy, takedown_defense,
            submission_avg_per_15min, last_updated
        ) VALUES (
            :id, :name, :nickname, :height_inches, :weight_lbs, :reach_inches,
            :stance, :dob, :wins, :losses, :draws, :no_contests,
            :sig_strikes_landed_per_min, :sig_strike_accuracy,
            :sig_strikes_absorbed_per_min, :sig_strike_defense,
            :takedown_avg_per_15min, :takedown_accuracy, :takedown_defense,
            :submission_avg_per_15min, :last_updated
        )
        ON CONFLICT(id) DO UPDATE SET
            name=excluded.name, nickname=excluded.nickname,
            height_inches=excluded.height_inches, weight_lbs=excluded.weight_lbs,
            reach_inches=excluded.reach_inches, stance=excluded.stance,
            dob=excluded.dob, wins=excluded.wins, losses=excluded.losses,
            draws=excluded.draws, no_contests=excluded.no_contests,
            sig_strikes_landed_per_min=excluded.sig_strikes_landed_per_min,
            sig_strike_accuracy=excluded.sig_strike_accuracy,
            sig_strikes_absorbed_per_min=excluded.sig_strikes_absorbed_per_min,
            sig_strike_defense=excluded.sig_strike_defense,
            takedown_avg_per_15min=excluded.takedown_avg_per_15min,
            takedown_accuracy=excluded.takedown_accuracy,
            takedown_defense=excluded.takedown_defense,
            submission_avg_per_15min=excluded.submission_avg_per_15min,
            last_updated=excluded.last_updated
    """, fighter)
    conn.commit()
    conn.close()


def get_fighter(fighter_id: str) -> dict | None:
    """Get a fighter by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM fighters WHERE id = ?", (fighter_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_all_fighters() -> list[dict]:
    """Return all fighters."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM fighters").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def search_fighters(name: str) -> list[dict]:
    """Search fighters by name (LIKE query)."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM fighters WHERE name LIKE ?", (f"%{name}%",)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Fight CRUD
# ---------------------------------------------------------------------------

def upsert_fight(fight: dict):
    """Insert or update a fight record."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO fights (
            id, event_name, event_date, fighter1_id, fighter2_id,
            winner_id, win_method, win_method_detail, finish_round,
            finish_time, is_title_fight, weight_class, num_rounds
        ) VALUES (
            :id, :event_name, :event_date, :fighter1_id, :fighter2_id,
            :winner_id, :win_method, :win_method_detail, :finish_round,
            :finish_time, :is_title_fight, :weight_class, :num_rounds
        )
        ON CONFLICT(id) DO UPDATE SET
            event_name=excluded.event_name, event_date=excluded.event_date,
            fighter1_id=excluded.fighter1_id, fighter2_id=excluded.fighter2_id,
            winner_id=excluded.winner_id, win_method=excluded.win_method,
            win_method_detail=excluded.win_method_detail,
            finish_round=excluded.finish_round, finish_time=excluded.finish_time,
            is_title_fight=excluded.is_title_fight,
            weight_class=excluded.weight_class, num_rounds=excluded.num_rounds
    """, fight)
    conn.commit()
    conn.close()


def get_fighter_fights(fighter_id: str) -> list[dict]:
    """Get all fights for a given fighter, ordered by date descending."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT * FROM fights
        WHERE fighter1_id = ? OR fighter2_id = ?
        ORDER BY event_date DESC
    """, (fighter_id, fighter_id)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_fight(fight_id: str) -> dict | None:
    """Get a single fight by ID."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM fights WHERE id = ?", (fight_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Fight Stats CRUD
# ---------------------------------------------------------------------------

def upsert_fight_stats(stats: dict):
    """Insert or update fight stats for a fighter in a fight."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO fight_stats (
            fight_id, fighter_id, knockdowns,
            sig_strikes_landed, sig_strikes_attempted,
            total_strikes_landed, total_strikes_attempted,
            takedowns_landed, takedowns_attempted,
            submission_attempts, reversals, control_time_seconds
        ) VALUES (
            :fight_id, :fighter_id, :knockdowns,
            :sig_strikes_landed, :sig_strikes_attempted,
            :total_strikes_landed, :total_strikes_attempted,
            :takedowns_landed, :takedowns_attempted,
            :submission_attempts, :reversals, :control_time_seconds
        )
        ON CONFLICT(fight_id, fighter_id) DO UPDATE SET
            knockdowns=excluded.knockdowns,
            sig_strikes_landed=excluded.sig_strikes_landed,
            sig_strikes_attempted=excluded.sig_strikes_attempted,
            total_strikes_landed=excluded.total_strikes_landed,
            total_strikes_attempted=excluded.total_strikes_attempted,
            takedowns_landed=excluded.takedowns_landed,
            takedowns_attempted=excluded.takedowns_attempted,
            submission_attempts=excluded.submission_attempts,
            reversals=excluded.reversals,
            control_time_seconds=excluded.control_time_seconds
    """, stats)
    conn.commit()
    conn.close()


def get_fight_stats(fight_id: str, fighter_id: str) -> dict | None:
    """Get fight stats for a specific fighter in a specific fight."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM fight_stats WHERE fight_id = ? AND fighter_id = ?",
        (fight_id, fighter_id),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_fighter_all_stats(fighter_id: str) -> list[dict]:
    """Get all fight stats for a fighter across all their fights."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM fight_stats WHERE fighter_id = ?", (fighter_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Prediction CRUD
# ---------------------------------------------------------------------------

def save_prediction(prediction: dict) -> int:
    """Save a prediction and return its ID."""
    conn = get_connection()
    cur = conn.execute("""
        INSERT INTO predictions (
            fighter1_id, fighter2_id, predicted_winner_id,
            confidence, predicted_method, fighter1_fqs, fighter2_fqs,
            actual_winner_id, actual_method, correct,
            prediction_date, fight_date
        ) VALUES (
            :fighter1_id, :fighter2_id, :predicted_winner_id,
            :confidence, :predicted_method, :fighter1_fqs, :fighter2_fqs,
            :actual_winner_id, :actual_method, :correct,
            :prediction_date, :fight_date
        )
    """, prediction)
    prediction_id = cur.lastrowid
    conn.commit()
    conn.close()
    return prediction_id


def update_prediction_result(prediction_id: int, winner_id: str, method: str):
    """Update a prediction with the actual result."""
    conn = get_connection()
    row = conn.execute(
        "SELECT predicted_winner_id FROM predictions WHERE id = ?",
        (prediction_id,),
    ).fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"Prediction {prediction_id} not found")

    correct = 1 if row["predicted_winner_id"] == winner_id else 0
    conn.execute("""
        UPDATE predictions
        SET actual_winner_id = ?, actual_method = ?, correct = ?
        WHERE id = ?
    """, (winner_id, method, correct, prediction_id))
    conn.commit()
    conn.close()
    return correct


def get_all_predictions() -> list[dict]:
    """Return all predictions, most recent first."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*,
               f1.name AS fighter1_name,
               f2.name AS fighter2_name,
               pw.name AS predicted_winner_name,
               aw.name AS actual_winner_name
        FROM predictions p
        LEFT JOIN fighters f1 ON p.fighter1_id = f1.id
        LEFT JOIN fighters f2 ON p.fighter2_id = f2.id
        LEFT JOIN fighters pw ON p.predicted_winner_id = pw.id
        LEFT JOIN fighters aw ON p.actual_winner_id = aw.id
        ORDER BY p.prediction_date DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_prediction(prediction_id: int) -> dict | None:
    """Get a single prediction by ID."""
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM predictions WHERE id = ?", (prediction_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


# ---------------------------------------------------------------------------
# Weight Class Baselines
# ---------------------------------------------------------------------------

def get_fighter_primary_weight_class(fighter_id: str) -> str | None:
    """Return the most frequent weight class for a fighter."""
    conn = get_connection()
    row = conn.execute("""
        SELECT weight_class, COUNT(*) as cnt
        FROM fights
        WHERE (fighter1_id = ? OR fighter2_id = ?) AND weight_class IS NOT NULL
        GROUP BY weight_class
        ORDER BY cnt DESC
        LIMIT 1
    """, (fighter_id, fighter_id)).fetchone()
    conn.close()
    return row["weight_class"] if row else None


def get_fighter_fight_dates(fighter_id: str) -> list[str]:
    """Return event dates for a fighter's fights, most recent first."""
    conn = get_connection()
    rows = conn.execute("""
        SELECT event_date FROM fights
        WHERE (fighter1_id = ? OR fighter2_id = ?) AND event_date IS NOT NULL
        ORDER BY event_date DESC
    """, (fighter_id, fighter_id)).fetchall()
    conn.close()
    return [r["event_date"] for r in rows]


def upsert_weight_class_baseline(baseline: dict):
    """Insert or update a weight class baseline record."""
    conn = get_connection()
    conn.execute("""
        INSERT INTO weight_class_baselines (
            weight_class, ko_rate, sub_rate, dec_rate,
            avg_finish_round, avg_fights_per_year, last_computed
        ) VALUES (
            :weight_class, :ko_rate, :sub_rate, :dec_rate,
            :avg_finish_round, :avg_fights_per_year, :last_computed
        )
        ON CONFLICT(weight_class) DO UPDATE SET
            ko_rate=excluded.ko_rate, sub_rate=excluded.sub_rate,
            dec_rate=excluded.dec_rate, avg_finish_round=excluded.avg_finish_round,
            avg_fights_per_year=excluded.avg_fights_per_year,
            last_computed=excluded.last_computed
    """, baseline)
    conn.commit()
    conn.close()


def get_all_weight_class_baselines() -> dict[str, dict]:
    """Return all weight class baselines as {weight_class: {ko_rate, ...}}."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM weight_class_baselines").fetchall()
    conn.close()
    return {r["weight_class"]: dict(r) for r in rows}

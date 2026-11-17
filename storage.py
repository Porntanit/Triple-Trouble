"""Local, structured profile and experiment storage (Python 3.10 compatible)."""

import json
import energy
from contextlib import contextmanager
import math
import sqlite3
from pathlib import Path

AGE_RANGES = ("18–24", "25–34", "35–44", "45–54", "55–64", "65+")
GOALS = (
    "Balanced eating",
    "Build consistent habits",
    "Support an active lifestyle",
    "Eat more plant foods",
    "Plan affordable meals",
)
ACTIVITIES = ("Mostly seated", "Lightly active", "Moderately active", "Very active")
TEXT_FIELDS = ("name", "food_preferences", "foods_disliked", "allergies", "restrictions")
CRITERIA = ("fit", "practicality", "source_consistency")


@contextmanager
def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=15)
    db.row_factory = sqlite3.Row
    db.execute(
        """CREATE TABLE IF NOT EXISTS profiles (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, age_range TEXT NOT NULL,
        dietary_goal TEXT NOT NULL, food_preferences TEXT NOT NULL,
        foods_disliked TEXT NOT NULL, allergies TEXT NOT NULL, restrictions TEXT NOT NULL,
        activity_level TEXT NOT NULL, meal_budget REAL NOT NULL, meals_per_day INTEGER NOT NULL,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS comparisons (
        id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, question TEXT NOT NULL,
        profile_snapshot TEXT NOT NULL, general TEXT NOT NULL, personalized TEXT NOT NULL,
        passages TEXT NOT NULL, ratings TEXT, notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
    )
    columns = {row[1] for row in db.execute("PRAGMA table_info(profiles)")}
    for name, sql_type in (
        ("age", "INTEGER"),
        ("height_cm", "REAL"),
        ("weight_kg", "REAL"),
        ("energy_equation", "TEXT"),
    ):
        if name not in columns:
            db.execute(f"ALTER TABLE profiles ADD COLUMN {name} {sql_type}")
    try:
        with db:
            yield db
    finally:
        db.close()


def validate_profile(data):
    if not isinstance(data, dict):
        raise ValueError("Send a profile object.")
    profile = {}
    for field in TEXT_FIELDS:
        value = data.get(field, "")
        limit = 80 if field == "name" else 500
        if not isinstance(value, str) or len(value.strip()) > limit:
            raise ValueError(
                f"{field.replace('_', ' ').capitalize()} must be text of at most {limit} characters."
            )
        profile[field] = value.strip()
    if not profile["name"]:
        raise ValueError("Enter a name or nickname.")
    for field, choices in (
        ("age_range", AGE_RANGES),
        ("dietary_goal", GOALS),
        ("activity_level", ACTIVITIES),
    ):
        if data.get(field) not in choices:
            raise ValueError(f"Choose a valid {field.replace('_', ' ')}.")
        profile[field] = data[field]
    budget, meals = data.get("meal_budget"), data.get("meals_per_day")
    if (
        isinstance(budget, bool)
        or not isinstance(budget, (int, float))
        or not math.isfinite(budget)
        or not 1 <= budget <= 10000
    ):
        raise ValueError("Daily food budget must be between 1 and 10,000 THB.")
    if isinstance(meals, bool) or not isinstance(meals, int) or not 1 <= meals <= 6:
        raise ValueError("Choose between 1 and 6 meals per day.")
    profile.update(energy.validate(data))
    profile.update(meal_budget=budget, meals_per_day=meals)
    if profile["age"] is not None:
        age = profile["age"]
        profile["age_range"] = next(
            (r for r, upper in zip(AGE_RANGES, (24, 34, 44, 54, 64, 100)) if age <= upper), "65+"
        )
    energy.estimate(profile)
    return profile


def get_profile(path, profile_id):
    with connect(path) as db:
        row = db.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()
    if not row:
        return None
    profile = dict(row)
    calculated = energy.estimate(profile)
    profile["energy_estimate"] = calculated
    profile["daily_target"] = calculated["daily_target"] if calculated else None
    return profile


def save_profile(path, profile_id, data):
    profile = validate_profile(data)
    fields = list(profile)
    with connect(path) as db:
        db.execute(
            f"INSERT INTO profiles (id,{','.join(fields)}) VALUES ({','.join('?' for _ in range(len(fields)+1))}) "
            f"ON CONFLICT(id) DO UPDATE SET {','.join(f'{f}=excluded.{f}' for f in fields)}, updated_at=CURRENT_TIMESTAMP",
            [profile_id] + [profile[f] for f in fields],
        )
    return get_profile(path, profile_id)


def save_comparison(path, profile_id, question, profile, general, personalized, passages):
    with connect(path) as db:
        cursor = db.execute(
            """INSERT INTO comparisons
            (profile_id,question,profile_snapshot,general,personalized,passages) VALUES (?,?,?,?,?,?)""",
            (
                profile_id,
                question,
                json.dumps(profile),
                json.dumps(general),
                json.dumps(personalized),
                json.dumps(passages),
            ),
        )
        return cursor.lastrowid


def comparisons(path, profile_id):
    with connect(path) as db:
        rows = db.execute(
            "SELECT * FROM comparisons WHERE profile_id=? ORDER BY id DESC", (profile_id,)
        ).fetchall()
    output = []
    for row in rows:
        item = dict(row)
        for field in ("profile_snapshot", "general", "personalized", "passages", "ratings"):
            item[field] = json.loads(item[field]) if item[field] else None
        output.append(item)
    return output


def rate(path, profile_id, comparison_id, payload):
    if not isinstance(payload, dict) or not isinstance(payload.get("ratings"), dict):
        raise ValueError("Supply ratings for both answers.")
    ratings = payload["ratings"]
    for mode in ("general", "personalized"):
        scores = ratings.get(mode)
        if not isinstance(scores, dict):
            raise ValueError("Rate both answers on all three criteria.")
        for criterion in CRITERIA:
            score = scores.get(criterion)
            if type(score) is not int or not 1 <= score <= 5:
                raise ValueError("Every rating must be a whole number from 1 to 5.")
    notes = payload.get("notes", "")
    if not isinstance(notes, str) or len(notes) > 2000:
        raise ValueError("Notes must be at most 2,000 characters.")
    cleaned = {
        mode: {c: ratings[mode][c] for c in CRITERIA} for mode in ("general", "personalized")
    }
    with connect(path) as db:
        result = db.execute(
            "UPDATE comparisons SET ratings=?,notes=? WHERE id=? AND profile_id=?",
            (json.dumps(cleaned), notes.strip(), comparison_id, profile_id),
        )
        return result.rowcount > 0

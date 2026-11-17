"""Manual daily calorie logs. Targets are user supplied, never medical estimates."""

import math
from datetime import datetime, date
from zoneinfo import ZoneInfo

import storage


def today():
    return datetime.now(ZoneInfo("Asia/Bangkok")).date().isoformat()


def valid_date(value):
    if not isinstance(value, str):
        raise ValueError("Choose a valid date.")
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError("Choose a valid date (YYYY-MM-DD).")
    if parsed.isoformat() != value or value > today():
        raise ValueError("Choose today or an earlier date.")
    return value


def number(value, label, minimum, maximum):
    if (
        type(value) not in (int, float)
        or not math.isfinite(value)
        or not minimum <= value <= maximum
    ):
        raise ValueError(f"{label} must be a number between {minimum:,} and {maximum:,}.")
    return round(value, 1)


def connect(path):
    return storage.connect(path)


def init_tables(db):
    db.execute(
        """CREATE TABLE IF NOT EXISTS calorie_settings (
        profile_id TEXT PRIMARY KEY, daily_target REAL NOT NULL)"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS calorie_days (
        profile_id TEXT NOT NULL, day TEXT NOT NULL, target REAL NOT NULL,
        rating INTEGER, PRIMARY KEY(profile_id,day))"""
    )
    db.execute(
        """CREATE TABLE IF NOT EXISTS calorie_entries (
        id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, day TEXT NOT NULL,
        food TEXT NOT NULL, calories REAL NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""
    )
    db.execute("CREATE INDEX IF NOT EXISTS calorie_entry_day ON calorie_entries(profile_id,day)")
    db.execute(
        """CREATE TABLE IF NOT EXISTS food_photos (
        entry_id INTEGER PRIMARY KEY, profile_id TEXT NOT NULL, analysis_id TEXT UNIQUE NOT NULL,
        image BLOB NOT NULL, analysis TEXT NOT NULL)"""
    )


def snapshot(path, profile_id, day):
    with connect(path) as db:
        init_tables(db)
        setting = db.execute(
            "SELECT daily_target FROM calorie_settings WHERE profile_id=?", (profile_id,)
        ).fetchone()
        rows = db.execute(
            """SELECT d.day,d.target,d.rating,COALESCE(SUM(e.calories),0) AS consumed
            FROM calorie_days d LEFT JOIN calorie_entries e ON e.profile_id=d.profile_id AND e.day=d.day
            WHERE d.profile_id=? GROUP BY d.day,d.target,d.rating ORDER BY d.day DESC""",
            (profile_id,),
        ).fetchall()
        history = [dict(row) for row in rows]
        for row in history:
            row["consumed"] = round(row["consumed"], 1)
            row["remaining"] = round(row["target"] - row["consumed"], 1)
        selected = next((row for row in history if row["day"] == day), None)
        if selected is None:
            target = setting["daily_target"] if setting else None
            selected = dict(day=day, target=target, rating=None, consumed=0, remaining=target)
        entries = [
            dict(row)
            for row in db.execute(
                "SELECT e.id,e.food,e.calories,EXISTS(SELECT 1 FROM food_photos p WHERE p.entry_id=e.id AND p.profile_id=e.profile_id) AS has_photo FROM calorie_entries e WHERE e.profile_id=? AND e.day=? ORDER BY e.id DESC",
                (profile_id, day),
            )
        ]
        return dict(selected=selected, history=history, entries=entries)


def save_day(path, profile_id, data):
    if not isinstance(data, dict):
        raise ValueError("Send daily tracking data.")
    day = valid_date(data.get("date"))
    if "target" not in data and "rating" not in data:
        raise ValueError("Set a calorie target or a self-rating.")
    rating = data.get("rating")
    if "rating" in data and (type(rating) is not int or not 1 <= rating <= 5):
        raise ValueError("Choose a self-rating from 1 to 5.")
    target = number(data["target"], "Calorie target", 1, 20000) if "target" in data else None
    with connect(path) as db:
        init_tables(db)
        existing = db.execute(
            "SELECT * FROM calorie_days WHERE profile_id=? AND day=?", (profile_id, day)
        ).fetchone()
        setting = db.execute(
            "SELECT daily_target FROM calorie_settings WHERE profile_id=?", (profile_id,)
        ).fetchone()
        target = (
            target
            if target is not None
            else existing["target"] if existing else setting["daily_target"] if setting else None
        )
        if target is None:
            raise ValueError("Set your daily calorie target first.")
        final_rating = rating if "rating" in data else existing["rating"] if existing else None
        db.execute(
            "INSERT INTO calorie_days(profile_id,day,target,rating) VALUES(?,?,?,?) ON CONFLICT(profile_id,day) DO UPDATE SET target=excluded.target,rating=excluded.rating",
            (profile_id, day, target, final_rating),
        )
        if "target" in data and day == today():
            db.execute(
                "INSERT INTO calorie_settings VALUES(?,?) ON CONFLICT(profile_id) DO UPDATE SET daily_target=excluded.daily_target",
                (profile_id, target),
            )
    return snapshot(path, profile_id, day)


def add_entry(path, profile_id, data):
    if not isinstance(data, dict):
        raise ValueError("Send a food entry.")
    day = valid_date(data.get("date"))
    food = data.get("food")
    if not isinstance(food, str) or not 1 <= len(food.strip()) <= 120:
        raise ValueError("Enter a food or meal name of 1–120 characters.")
    amount = number(data.get("calories"), "Calories", 0.1, 20000)
    with connect(path) as db:
        init_tables(db)
        existing = db.execute(
            "SELECT target FROM calorie_days WHERE profile_id=? AND day=?", (profile_id, day)
        ).fetchone()
        setting = db.execute(
            "SELECT daily_target FROM calorie_settings WHERE profile_id=?", (profile_id,)
        ).fetchone()
        if not existing:
            if not setting:
                raise ValueError("Set your daily calorie target first.")
            db.execute(
                "INSERT INTO calorie_days(profile_id,day,target) VALUES(?,?,?)",
                (profile_id, day, setting["daily_target"]),
            )
        db.execute(
            "INSERT INTO calorie_entries(profile_id,day,food,calories) VALUES(?,?,?,?)",
            (profile_id, day, food.strip(), amount),
        )
    return snapshot(path, profile_id, day)


def delete_entry(path, profile_id, entry_id):
    with connect(path) as db:
        init_tables(db)
        entry = db.execute(
            "SELECT day FROM calorie_entries WHERE id=? AND profile_id=?", (entry_id, profile_id)
        ).fetchone()
        if not entry:
            return None
        db.execute(
            "DELETE FROM food_photos WHERE entry_id=? AND profile_id=?", (entry_id, profile_id)
        )
        db.execute(
            "DELETE FROM calorie_entries WHERE id=? AND profile_id=?", (entry_id, profile_id)
        )
    return snapshot(path, profile_id, entry["day"])


def sync_profile_target(path, profile):
    if profile.get("daily_target") is None:
        return
    with connect(path) as db:
        init_tables(db)
        db.execute(
            "INSERT INTO calorie_settings VALUES(?,?) ON CONFLICT(profile_id) DO UPDATE SET daily_target=excluded.daily_target",
            (profile["id"], profile["daily_target"]),
        )
        db.execute(
            "UPDATE calorie_days SET target=? WHERE profile_id=? AND day=?",
            (profile["daily_target"], profile["id"], today()),
        )

"""Populate SnapMacro with synthetic data so you can see the full experience
(go-tos, weekly average, calibration) without waiting a week or snapping real food.

Usage (from the project root, using the venv python):
    backend/.venv/bin/python backend/seed.py          # add 7 days of realistic history
    backend/.venv/bin/python backend/seed.py --reset  # wipe ALL data, then reseed
    backend/.venv/bin/python backend/seed.py --clear  # wipe ALL data, leave it empty

Writes to the SAME database the server uses, so just refresh the app afterward.
"""
import sys
import json
import random
from datetime import datetime, timedelta

import db

# A realistic set of athlete staples. Each entry: meal + the hour it usually gets eaten.
STAPLES = [
    # breakfast (hours 6-8)
    {"name": "Oats, banana & whey", "hour": 7,
     "items": [{"food": "oats cooked", "grams": 240}, {"food": "banana", "grams": 118},
               {"food": "whey protein powder", "grams": 32}],
     "calories": 520, "protein": 38, "carbs": 72, "fat": 9},
    {"name": "Egg & avocado toast", "hour": 8,
     "items": [{"food": "eggs", "grams": 150}, {"food": "whole wheat bread", "grams": 56},
               {"food": "avocado", "grams": 70}],
     "calories": 540, "protein": 26, "carbs": 38, "fat": 31},
    # lunch (hours 12-13)
    {"name": "Chicken, rice & broccoli", "hour": 12,
     "items": [{"food": "grilled chicken breast", "grams": 200}, {"food": "white rice cooked", "grams": 220},
               {"food": "broccoli", "grams": 120}],
     "calories": 720, "protein": 62, "carbs": 78, "fat": 12},
    {"name": "Turkey & sweet potato bowl", "hour": 13,
     "items": [{"food": "ground turkey", "grams": 170}, {"food": "sweet potato baked", "grams": 200},
               {"food": "spinach", "grams": 60}],
     "calories": 610, "protein": 48, "carbs": 55, "fat": 20},
    # dinner (hours 18-20)
    {"name": "Steak, potatoes & greens", "hour": 19,
     "items": [{"food": "beef sirloin steak", "grams": 225}, {"food": "potato baked", "grams": 200},
               {"food": "asparagus", "grams": 90}, {"food": "olive oil", "grams": 8}],
     "calories": 780, "protein": 56, "carbs": 48, "fat": 38},
    {"name": "Salmon & quinoa", "hour": 20,
     "items": [{"food": "salmon", "grams": 200}, {"food": "quinoa cooked", "grams": 185},
               {"food": "green beans", "grams": 90}],
     "calories": 690, "protein": 50, "carbs": 44, "fat": 33},
    # snack (hour 15-16)
    {"name": "Greek yogurt & berries", "hour": 16,
     "items": [{"food": "greek yogurt plain nonfat", "grams": 200}, {"food": "blueberries", "grams": 80},
               {"food": "honey", "grams": 12}],
     "calories": 250, "protein": 22, "carbs": 32, "fat": 3},
]


def clear():
    with db.get_db() as conn:
        for t in ("entries", "meals", "corrections"):
            conn.execute(f"DELETE FROM {t}")
        # reset autoincrement counters if the table exists
        try:
            conn.execute("DELETE FROM sqlite_sequence")
        except Exception:
            pass
    print("Cleared all SnapMacro data.")


def _insert_entry(meal_id, s, when, source):
    with db.get_db() as conn:
        conn.execute(
            """INSERT INTO entries (meal_id, name, items, calories, protein, carbs, fat,
               confidence, source, logged_at, log_date, log_hour)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (meal_id, s["name"], json.dumps(s["items"]), s["calories"], s["protein"],
             s["carbs"], s["fat"], "high", source, when.isoformat(),
             when.date().isoformat(), when.hour),
        )
        conn.execute("UPDATE meals SET times_logged = times_logged + 1 WHERE id = ?", (meal_id,))


def seed(days=7):
    db.init_db()
    # 1) build the library
    ids = {}
    for s in STAPLES:
        ids[s["name"]] = db.upsert_meal(
            s["name"], s["items"],
            {"calories": s["calories"], "protein": s["protein"], "carbs": s["carbs"], "fat": s["fat"]})

    breakfasts = [s for s in STAPLES if s["hour"] < 11]
    lunches = [s for s in STAPLES if 11 <= s["hour"] < 15]
    snacks = [s for s in STAPLES if s["name"].startswith("Greek")]
    dinners = [s for s in STAPLES if s["hour"] >= 18]

    today = datetime.now()
    total = 0
    for d in range(days):
        day = today - timedelta(days=(days - 1 - d))
        # pick meals, biased toward repetition so go-tos form clearly
        plan = [
            random.choice(breakfasts),
            random.choice(lunches),
            random.choice(snacks),
            random.choice(dinners),
        ]
        for s in plan:
            jitter = random.randint(-25, 25)  # +/- minutes around the usual hour
            when = day.replace(hour=s["hour"], minute=30, second=0, microsecond=0) + timedelta(minutes=jitter)
            _insert_entry(ids[s["name"]], s, when, "photo" if d == days - 1 else "goto")
            total += 1

    # 2) add a calibration example: user found "Chicken, rice & broccoli" runs ~12% high
    db.update_factor(ids["Chicken, rice & broccoli"], 0.88)

    print(f"Seeded {len(STAPLES)} staple meals and {total} log entries across {days} days.")
    print("Added a sample calibration (Chicken/rice/broccoli x0.88).")
    print("Refresh the app — go-tos, today's log, and the 7-day average will all be populated.")


if __name__ == "__main__":
    if "--clear" in sys.argv:
        clear()
    elif "--reset" in sys.argv:
        clear()
        seed()
    else:
        seed()

"""Populate ONE user's account with synthetic history (for demoing the full experience).

Usage (DATABASE_URL must be set in .env):
    backend/.venv/bin/python backend/seed.py --code <your-personal-code>   # seed that user
    backend/.venv/bin/python backend/seed.py --new "Demo Name"             # create + seed a new user
    backend/.venv/bin/python backend/seed.py --code <code> --clear         # wipe that user's data

Get your personal code from the app: Settings -> your private link ends in ?u=<code>.
"""
import sys
import json
import random
from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()
import db

STAPLES = [
    {"name": "Oats, banana & whey", "hour": 7,
     "items": [{"food": "oats cooked", "grams": 240}, {"food": "banana", "grams": 118}, {"food": "whey protein powder", "grams": 32}],
     "calories": 520, "protein": 38, "carbs": 72, "fat": 9},
    {"name": "Egg & avocado toast", "hour": 8,
     "items": [{"food": "eggs", "grams": 150}, {"food": "whole wheat bread", "grams": 56}, {"food": "avocado", "grams": 70}],
     "calories": 540, "protein": 26, "carbs": 38, "fat": 31},
    {"name": "Chicken, rice & broccoli", "hour": 12,
     "items": [{"food": "grilled chicken breast", "grams": 200}, {"food": "white rice cooked", "grams": 220}, {"food": "broccoli", "grams": 120}],
     "calories": 720, "protein": 62, "carbs": 78, "fat": 12},
    {"name": "Turkey & sweet potato bowl", "hour": 13,
     "items": [{"food": "ground turkey", "grams": 170}, {"food": "sweet potato baked", "grams": 200}, {"food": "spinach", "grams": 60}],
     "calories": 610, "protein": 48, "carbs": 55, "fat": 20},
    {"name": "Steak, potatoes & greens", "hour": 19,
     "items": [{"food": "beef sirloin steak", "grams": 225}, {"food": "potato baked", "grams": 200}, {"food": "asparagus", "grams": 90}, {"food": "olive oil", "grams": 8}],
     "calories": 780, "protein": 56, "carbs": 48, "fat": 38},
    {"name": "Greek yogurt & berries", "hour": 16,
     "items": [{"food": "greek yogurt plain nonfat", "grams": 200}, {"food": "blueberries", "grams": 80}, {"food": "honey", "grams": 12}],
     "calories": 250, "protein": 22, "carbs": 32, "fat": 3},
]


def clear(uid):
    with db.pool().connection() as conn:
        conn.execute("delete from entries where user_id=%s", (uid,))
        conn.execute("delete from corrections where user_id=%s", (uid,))
        conn.execute("delete from meals where user_id=%s", (uid,))
    print("Cleared all data for user", uid)


def seed(uid, days=7):
    ids = {}
    for s in STAPLES:
        ids[s["name"]] = db.upsert_meal(uid, s["name"], s["items"],
            {"calories": s["calories"], "protein": s["protein"], "carbs": s["carbs"], "fat": s["fat"]})
    breakfasts = [s for s in STAPLES if s["hour"] < 11]
    lunches = [s for s in STAPLES if 11 <= s["hour"] < 15]
    snacks = [s for s in STAPLES if s["name"].startswith("Greek")]
    dinners = [s for s in STAPLES if s["hour"] >= 18]
    today = datetime.now()
    total = 0
    for d in range(days):
        day = today - timedelta(days=(days - 1 - d))
        for s in [random.choice(breakfasts), random.choice(lunches), random.choice(snacks), random.choice(dinners)]:
            when = day.replace(hour=s["hour"], minute=30, second=0, microsecond=0) + timedelta(minutes=random.randint(-25, 25))
            with db.pool().connection() as conn:
                conn.execute(
                    """insert into entries (user_id, meal_id, name, items, calories, protein, carbs, fat,
                       confidence, source, logged_at, log_date, log_hour)
                       values (%s,%s,%s,%s,%s,%s,%s,%s,'high',%s,%s,%s,%s)""",
                    (uid, ids[s["name"]], s["name"], json.dumps(s["items"]), s["calories"], s["protein"],
                     s["carbs"], s["fat"], "photo" if d == days-1 else "goto", when, when.date(), when.hour))
                conn.execute("update meals set times_logged=times_logged+1 where id=%s", (ids[s["name"]],))
            total += 1
    db.update_factor(uid, ids["Chicken, rice & broccoli"], 0.88)
    print(f"Seeded {len(STAPLES)} meals + {total} entries across {days} days for user {uid}.")


if __name__ == "__main__":
    args = sys.argv[1:]
    user = None
    if "--new" in args:
        name = args[args.index("--new") + 1] if len(args) > args.index("--new") + 1 else "Demo"
        u = db.create_user(name)
        print(f"Created user '{name}' — personal link: /?u={u['code']}")
        user = u
    elif "--code" in args:
        code = args[args.index("--code") + 1]
        user = db.get_user_by_code(code)
        if not user:
            print("No user with that code."); sys.exit(1)
    else:
        print(__doc__); sys.exit(0)

    if "--clear" in args:
        clear(user["id"])
    else:
        seed(user["id"])
    print("Done. Refresh the app.")

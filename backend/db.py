"""SQLite persistence for SnapMacro. Zero-setup, single-file DB.

Tables:
  meals       - the personal meal library (named, reusable staples)
  entries     - the daily log (what was eaten, when)
  corrections - per-meal calibration factors learned from user corrections
"""
import sqlite3
import json
import os
from datetime import datetime, date
from contextlib import contextmanager

DB_PATH = os.getenv("SNAPMACRO_DB") or os.path.join(os.path.dirname(__file__), "snapmacro.db")


@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS meals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                items TEXT,                 -- JSON list of food items
                calories REAL, protein REAL, carbs REAL, fat REAL,
                times_logged INTEGER DEFAULT 0,
                created_at TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_id INTEGER,            -- nullable: links to library meal if matched
                name TEXT,
                items TEXT,
                calories REAL, protein REAL, carbs REAL, fat REAL,
                confidence TEXT,
                source TEXT,                -- 'photo' | 'goto' | 'manual'
                logged_at TEXT,
                log_date TEXT,
                log_hour INTEGER
            );

            CREATE TABLE IF NOT EXISTS corrections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meal_id INTEGER,
                factor REAL DEFAULT 1.0,    -- running portion multiplier for this meal
                samples INTEGER DEFAULT 0,
                updated_at TEXT
            );
            """
        )


# ---------- meals (library) ----------

def upsert_meal(name, items, macros):
    now = datetime.now().isoformat()
    with get_db() as conn:
        row = conn.execute("SELECT id, times_logged FROM meals WHERE name = ?", (name,)).fetchone()
        if row:
            conn.execute(
                """UPDATE meals SET items=?, calories=?, protein=?, carbs=?, fat=?,
                   times_logged=times_logged+1, updated_at=? WHERE id=?""",
                (json.dumps(items), macros["calories"], macros["protein"], macros["carbs"],
                 macros["fat"], now, row["id"]),
            )
            return row["id"]
        cur = conn.execute(
            """INSERT INTO meals (name, items, calories, protein, carbs, fat,
               times_logged, created_at, updated_at)
               VALUES (?,?,?,?,?,?,1,?,?)""",
            (name, json.dumps(items), macros["calories"], macros["protein"],
             macros["carbs"], macros["fat"], now, now),
        )
        return cur.lastrowid


def get_meal(meal_id):
    with get_db() as conn:
        r = conn.execute("SELECT * FROM meals WHERE id=?", (meal_id,)).fetchone()
        return dict(r) if r else None


def all_meals():
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM meals ORDER BY times_logged DESC, updated_at DESC").fetchall()]


# ---------- entries (daily log) ----------

def add_entry(name, items, macros, confidence, source, meal_id=None):
    now = datetime.now()
    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO entries (meal_id, name, items, calories, protein, carbs, fat,
               confidence, source, logged_at, log_date, log_hour)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (meal_id, name, json.dumps(items), macros["calories"], macros["protein"],
             macros["carbs"], macros["fat"], confidence, source,
             now.isoformat(), now.date().isoformat(), now.hour),
        )
        return cur.lastrowid


def entries_for_date(d=None):
    d = d or date.today().isoformat()
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            "SELECT * FROM entries WHERE log_date=? ORDER BY logged_at", (d,)).fetchall()]


def entries_last_n_days(n=7):
    with get_db() as conn:
        return [dict(r) for r in conn.execute(
            """SELECT log_date, SUM(calories) c, SUM(protein) p, SUM(carbs) cb, SUM(fat) f
               FROM entries GROUP BY log_date ORDER BY log_date DESC LIMIT ?""", (n,)).fetchall()]


def delete_entry(entry_id):
    with get_db() as conn:
        conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))


def get_entry(entry_id):
    with get_db() as conn:
        r = conn.execute("SELECT * FROM entries WHERE id=?", (entry_id,)).fetchone()
        return dict(r) if r else None


def update_entry(entry_id, name, macros):
    with get_db() as conn:
        conn.execute(
            """UPDATE entries SET name=?, calories=?, protein=?, carbs=?, fat=? WHERE id=?""",
            (name, macros["calories"], macros["protein"], macros["carbs"], macros["fat"], entry_id),
        )


def update_meal_macros(meal_id, name, macros):
    """Refresh a library meal's stored macros so go-tos reflect the corrected reality."""
    now = datetime.now().isoformat()
    with get_db() as conn:
        conn.execute(
            """UPDATE meals SET name=?, calories=?, protein=?, carbs=?, fat=?, updated_at=? WHERE id=?""",
            (name, macros["calories"], macros["protein"], macros["carbs"], macros["fat"], now, meal_id),
        )


# ---------- go-tos (time-of-day surfacing) ----------

def gotos_for_hour(hour, limit=3, window=2):
    """Meals most frequently logged within +/- `window` hours of `hour`."""
    lo, hi = hour - window, hour + window
    with get_db() as conn:
        rows = conn.execute(
            """SELECT m.* , COUNT(e.id) AS hits
               FROM entries e JOIN meals m ON e.meal_id = m.id
               WHERE e.meal_id IS NOT NULL AND e.log_hour BETWEEN ? AND ?
               GROUP BY m.id ORDER BY hits DESC, m.times_logged DESC LIMIT ?""",
            (lo, hi, limit)).fetchall()
        if rows:
            return [dict(r) for r in rows]
        # fallback: most-logged meals overall (helps brand-new users)
        return [dict(r) for r in conn.execute(
            "SELECT * FROM meals ORDER BY times_logged DESC LIMIT ?", (limit,)).fetchall()]


# ---------- corrections (calibration) ----------

def get_factor(meal_id):
    with get_db() as conn:
        r = conn.execute("SELECT factor FROM corrections WHERE meal_id=?", (meal_id,)).fetchone()
        return r["factor"] if r else 1.0


def update_factor(meal_id, observed_factor):
    """Blend the new observed correction into a running average (capped to sane range)."""
    observed_factor = max(0.2, min(5.0, observed_factor))
    now = datetime.now().isoformat()
    with get_db() as conn:
        r = conn.execute("SELECT factor, samples FROM corrections WHERE meal_id=?", (meal_id,)).fetchone()
        if r:
            new_samples = r["samples"] + 1
            new_factor = (r["factor"] * r["samples"] + observed_factor) / new_samples
            conn.execute("UPDATE corrections SET factor=?, samples=?, updated_at=? WHERE meal_id=?",
                         (new_factor, new_samples, now, meal_id))
            return new_factor
        conn.execute("INSERT INTO corrections (meal_id, factor, samples, updated_at) VALUES (?,?,1,?)",
                     (meal_id, observed_factor, now))
        return observed_factor

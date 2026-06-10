"""Postgres (Supabase) data layer for SnapMacro — multi-user.

Every row is scoped by user_id. The backend connects as the database owner via
DATABASE_URL (which bypasses RLS); the anon key is never used, and the tables live in a
dedicated `snapmacro` schema with RLS enabled, so they're not reachable from the public API.

Set DATABASE_URL in .env to the Supabase connection string (Settings -> Database ->
Connection string -> URI). Example:
  DATABASE_URL=postgresql://postgres.<ref>:<password>@<pooler-host>:6543/postgres
"""
import os
import secrets
from datetime import datetime, date

from psycopg_pool import ConnectionPool
from psycopg.rows import dict_row
from psycopg.types.json import Json

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

# Pool is created lazily so the app can import even before the URL is set.
_pool = None


def pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL is not set — add it to backend/.env")
        def _configure(conn):
            # Supabase's transaction pooler (PgBouncer) doesn't support prepared
            # statements — disable them to avoid "prepared statement already exists".
            conn.prepare_threshold = None
        _pool = ConnectionPool(
            conninfo=DATABASE_URL, min_size=1, max_size=5, open=True, configure=_configure,
            kwargs={"row_factory": dict_row, "options": "-c search_path=snapmacro,public"},
        )
    return _pool


def init_db():
    # Schema/tables are managed via Supabase migrations; just verify connectivity.
    if not DATABASE_URL:
        return
    with pool().connection() as conn:
        conn.execute("select 1")


# ---------- users ----------

def create_user(name):
    code = secrets.token_urlsafe(12)
    with pool().connection() as conn:
        row = conn.execute(
            "insert into users (name, code) values (%s, %s) returning id, code, name",
            (name.strip()[:60] or "You", code),
        ).fetchone()
    return row


def get_user_by_code(code):
    if not code:
        return None
    with pool().connection() as conn:
        return conn.execute("select * from users where code = %s", (code,)).fetchone()


def get_user(user_id):
    with pool().connection() as conn:
        return conn.execute("select * from users where id = %s", (user_id,)).fetchone()


def update_targets(user_id, t):
    with pool().connection() as conn:
        conn.execute(
            """update users set target_calories=%s, target_protein=%s,
               target_carbs=%s, target_fat=%s where id=%s""",
            (t["calories"], t["protein"], t["carbs"], t["fat"], user_id),
        )


def update_name(user_id, name):
    with pool().connection() as conn:
        conn.execute("update users set name=%s where id=%s", (name.strip()[:60] or "You", user_id))


# ---------- meals (library) ----------

def upsert_meal(user_id, name, items, macros):
    with pool().connection() as conn:
        row = conn.execute(
            "select id from meals where user_id=%s and name=%s", (user_id, name)).fetchone()
        if row:
            conn.execute(
                """update meals set items=%s, calories=%s, protein=%s, carbs=%s, fat=%s,
                   times_logged=times_logged+1, updated_at=now() where id=%s and user_id=%s""",
                (Json(items), macros["calories"], macros["protein"], macros["carbs"],
                 macros["fat"], row["id"], user_id),
            )
            return row["id"]
        new = conn.execute(
            """insert into meals (user_id, name, items, calories, protein, carbs, fat, times_logged)
               values (%s,%s,%s,%s,%s,%s,%s,1) returning id""",
            (user_id, name, Json(items), macros["calories"], macros["protein"],
             macros["carbs"], macros["fat"]),
        ).fetchone()
        return new["id"]


def get_meal(user_id, meal_id):
    with pool().connection() as conn:
        return conn.execute(
            "select * from meals where id=%s and user_id=%s", (meal_id, user_id)).fetchone()


def update_meal_macros(user_id, meal_id, name, macros):
    with pool().connection() as conn:
        conn.execute(
            """update meals set name=%s, calories=%s, protein=%s, carbs=%s, fat=%s,
               updated_at=now() where id=%s and user_id=%s""",
            (name, macros["calories"], macros["protein"], macros["carbs"], macros["fat"],
             meal_id, user_id),
        )


# ---------- entries (daily log) ----------

def add_entry(user_id, name, items, macros, confidence, source, meal_id=None):
    now = datetime.now()
    with pool().connection() as conn:
        row = conn.execute(
            """insert into entries (user_id, meal_id, name, items, calories, protein, carbs,
               fat, confidence, source, logged_at, log_date, log_hour)
               values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) returning id""",
            (user_id, meal_id, name, Json(items), macros["calories"], macros["protein"],
             macros["carbs"], macros["fat"], confidence, source,
             now, now.date(), now.hour),
        ).fetchone()
        return row["id"]


def entries_for_date(user_id, d=None):
    d = d or date.today()
    with pool().connection() as conn:
        return conn.execute(
            "select * from entries where user_id=%s and log_date=%s order by logged_at",
            (user_id, d)).fetchall()


def entries_last_n_days(user_id, n=7):
    with pool().connection() as conn:
        return conn.execute(
            """select log_date, sum(calories) c, sum(protein) p, sum(carbs) cb, sum(fat) f
               from entries where user_id=%s group by log_date order by log_date desc limit %s""",
            (user_id, n)).fetchall()


def get_entry(user_id, entry_id):
    with pool().connection() as conn:
        return conn.execute(
            "select * from entries where id=%s and user_id=%s", (entry_id, user_id)).fetchone()


def update_entry(user_id, entry_id, name, macros):
    with pool().connection() as conn:
        conn.execute(
            """update entries set name=%s, calories=%s, protein=%s, carbs=%s, fat=%s
               where id=%s and user_id=%s""",
            (name, macros["calories"], macros["protein"], macros["carbs"], macros["fat"],
             entry_id, user_id),
        )


def delete_entry(user_id, entry_id):
    with pool().connection() as conn:
        row = conn.execute(
            "delete from entries where id=%s and user_id=%s returning id",
            (entry_id, user_id)).fetchone()
        return row is not None


# ---------- go-tos ----------

def gotos_for_hour(user_id, hour, limit=3, window=2):
    lo, hi = hour - window, hour + window
    with pool().connection() as conn:
        rows = conn.execute(
            """select m.*, count(e.id) as hits
               from entries e join meals m on e.meal_id = m.id
               where e.user_id=%s and e.meal_id is not null and e.log_hour between %s and %s
               group by m.id order by hits desc, m.times_logged desc limit %s""",
            (user_id, lo, hi, limit)).fetchall()
        if rows:
            return rows
        return conn.execute(
            "select * from meals where user_id=%s order by times_logged desc limit %s",
            (user_id, limit)).fetchall()


# ---------- corrections (calibration) ----------

def get_factor(user_id, meal_id):
    with pool().connection() as conn:
        r = conn.execute(
            "select factor from corrections where user_id=%s and meal_id=%s",
            (user_id, meal_id)).fetchone()
        return float(r["factor"]) if r else 1.0


def update_factor(user_id, meal_id, observed_factor):
    observed_factor = max(0.2, min(5.0, observed_factor))
    with pool().connection() as conn:
        r = conn.execute(
            "select factor, samples from corrections where user_id=%s and meal_id=%s",
            (user_id, meal_id)).fetchone()
        if r:
            n = r["samples"] + 1
            new = (float(r["factor"]) * r["samples"] + observed_factor) / n
            conn.execute(
                """update corrections set factor=%s, samples=%s, updated_at=now()
                   where user_id=%s and meal_id=%s""",
                (new, n, user_id, meal_id))
            return new
        conn.execute(
            "insert into corrections (user_id, meal_id, factor, samples) values (%s,%s,%s,1)",
            (user_id, meal_id, observed_factor))
        return observed_factor

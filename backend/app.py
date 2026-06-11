"""SnapMacro backend — multi-user FastAPI app (Postgres/Supabase).

Auth model: each user gets a private code (no passwords). The code lives in an httponly
cookie. A personal link (?u=<code>) logs a returning user in. New users sign up with just
a name. All data is scoped by user_id.

Run:  uvicorn app:app --reload --host 0.0.0.0 --port 8000
"""
import os
import time
import secrets
from collections import defaultdict, deque
from datetime import date, datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

import db
import analyzer
import imageutil

app = FastAPI(title="SnapMacro")
db.init_db()

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
COOKIE = "sm_user"
COOKIE_MAX_AGE = 60 * 60 * 24 * 365  # 1 year

# --- per-IP rate limiting (in-memory) ---
_hits = defaultdict(lambda: defaultdict(deque))
_LIMITS = {
    "default": (120, 60),
    "analyze": (15, 60),
    "signup":  (8, 3600),   # 8 new accounts / hour / IP
}


def _client_ip(request):
    xff = request.headers.get("x-forwarded-for", "")
    return xff.split(",")[0].strip() if xff else (request.client.host if request.client else "?")


def _rate_ok(ip, bucket):
    limit, window = _LIMITS[bucket]
    now = time.time()
    _sweep(now)
    dq = _hits[ip][bucket]
    while dq and dq[0] <= now - window:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


_last_sweep = 0.0


def _sweep(now):
    """Drop IPs whose windows have fully expired so _hits can't grow without bound
    (a public URL gets scanned; each scanner IP would otherwise live forever)."""
    global _last_sweep
    if now - _last_sweep < 600:
        return
    _last_sweep = now
    for ip in list(_hits):
        for bucket in list(_hits[ip]):
            _, window = _LIMITS[bucket]
            dq = _hits[ip][bucket]
            while dq and dq[0] <= now - window:
                dq.popleft()
            if not dq:
                del _hits[ip][bucket]
        if not _hits[ip]:
            del _hits[ip]


@app.middleware("http")
async def rate_limit(request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        ip = _client_ip(request)
        if not _rate_ok(ip, "default"):
            return JSONResponse({"error": "rate_limited", "detail": "Slow down a moment."}, status_code=429)
        if path == "/api/analyze" and not _rate_ok(ip, "analyze"):
            return JSONResponse({"error": "rate_limited", "detail": "Too many photos — wait a minute."}, status_code=429)
    return await call_next(request)


# --- auth dependency ---

def current_user(request: Request):
    code = request.cookies.get(COOKIE) or request.headers.get("x-app-token", "")
    user = db.get_user_by_code(code)
    if not user:
        raise HTTPException(401, "Not signed in")
    return user


def _targets(user):
    return {"calories": float(user["target_calories"]), "protein": float(user["target_protein"]),
            "carbs": float(user["target_carbs"]), "fat": float(user["target_fat"])}


def _is_https(request):
    # Behind a TLS-terminating proxy (Render, Railway) the app sees plain http;
    # trust x-forwarded-proto so the session cookie still gets the Secure flag.
    fwd = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
    return request.url.scheme == "https" or fwd == "https"


def _set_cookie(resp, code, secure):
    resp.set_cookie(COOKIE, code, max_age=COOKIE_MAX_AGE, httponly=True,
                    samesite="lax", secure=secure, path="/")


# ---------- pages ----------

@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(FRONTEND, "index.html"), encoding="utf-8") as f:
        return f.read()


# ---------- auth / onboarding ----------

class SignupIn(BaseModel):
    name: str


@app.post("/api/signup")
def signup(body: SignupIn, request: Request):
    if not _rate_ok(_client_ip(request), "signup"):
        raise HTTPException(429, "Too many signups from here — try again later.")
    user = db.create_user(body.name)
    secure = _is_https(request)
    resp = JSONResponse({"id": user["id"], "name": user["name"], "code": user["code"]})
    _set_cookie(resp, user["code"], secure)
    return resp


class LoginIn(BaseModel):
    code: str


@app.post("/api/login")
def login(body: LoginIn, request: Request):
    user = db.get_user_by_code(body.code.strip())
    if not user:
        raise HTTPException(404, "Unknown code")
    secure = _is_https(request)
    resp = JSONResponse({"id": user["id"], "name": user["name"]})
    _set_cookie(resp, user["code"], secure)
    return resp


@app.post("/api/logout")
def logout():
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(COOKIE, path="/")
    return resp


@app.get("/api/me")
def me(user=Depends(current_user)):
    return {"id": user["id"], "name": user["name"], "code": user["code"],
            "targets": _targets(user), "mock": not bool(analyzer.GEMINI_API_KEY),
            "model": analyzer.GEMINI_MODEL}


class SettingsIn(BaseModel):
    name: str | None = None
    calories: float | None = None
    protein: float | None = None
    carbs: float | None = None
    fat: float | None = None


@app.post("/api/settings")
def settings(body: SettingsIn, user=Depends(current_user)):
    if body.name is not None:
        db.update_name(user["id"], body.name)
    if None not in (body.calories, body.protein, body.carbs, body.fat):
        db.update_targets(user["id"], {"calories": body.calories, "protein": body.protein,
                                       "carbs": body.carbs, "fat": body.fat})
    return {"ok": True}


# ---------- analyze / log ----------

@app.post("/api/analyze")
async def analyze_photo(image: UploadFile = File(...), note: str = Form(""),
                        user=Depends(current_user)):
    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty image")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large (max 15 MB).")
    note = note.strip()[:200]

    # PIL decode + Gemini (30s timeout) + USDA lookups are all blocking; run off the
    # event loop so one slow photo can't stall every other user's request.
    def _work():
        norm, mime = imageutil.normalize(data, image.content_type or "image/jpeg")
        return analyzer.analyze(norm, mime, note)
    return await run_in_threadpool(_work)


class LogIn(BaseModel):
    name: str
    items: list = []
    calories: float
    protein: float
    carbs: float
    fat: float
    confidence: str = "medium"
    source: str = "photo"
    meal_id: int | None = None
    save_to_library: bool = True


@app.post("/api/log")
def log_entry(body: LogIn, user=Depends(current_user)):
    uid = user["id"]
    macros = {"calories": body.calories, "protein": body.protein,
              "carbs": body.carbs, "fat": body.fat}
    meal_id = body.meal_id
    if meal_id and body.source == "photo":
        factor = db.get_factor(uid, meal_id)
        if factor != 1.0:
            macros = {k: round(v * factor) for k, v in macros.items()}
    if body.save_to_library and body.source != "goto":
        meal_id = db.upsert_meal(uid, body.name, body.items, macros)
    elif body.source == "goto" and meal_id:
        db.upsert_meal(uid, body.name, body.items, macros)
    entry_id = db.add_entry(uid, body.name, body.items, macros, body.confidence, body.source, meal_id)
    return {"ok": True, "entry_id": entry_id, "meal_id": meal_id, "macros": macros}


class EditIn(BaseModel):
    name: str
    calories: float
    protein: float
    carbs: float
    fat: float


@app.post("/api/entry/{entry_id}")
def edit_entry(entry_id: int, body: EditIn, user=Depends(current_user)):
    uid = user["id"]
    entry = db.get_entry(uid, entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    new = {"calories": body.calories, "protein": body.protein, "carbs": body.carbs, "fat": body.fat}
    db.update_entry(uid, entry_id, body.name, new)
    learned, factor = False, None
    meal_id = entry.get("meal_id")
    old_cal = float(entry.get("calories") or 0)
    if meal_id and old_cal > 0 and abs(body.calories - old_cal) > 1:
        factor = round(db.update_factor(uid, meal_id, body.calories / old_cal), 3)
        db.update_meal_macros(uid, meal_id, body.name, new)
        learned = True
    return {"ok": True, "learned": learned, "factor": factor}


@app.delete("/api/entry/{entry_id}")
def remove_entry(entry_id: int, user=Depends(current_user)):
    if not db.delete_entry(user["id"], entry_id):
        raise HTTPException(404, "Entry not found")
    return {"ok": True}


# ---------- views ----------

@app.get("/api/today")
def today(user=Depends(current_user)):
    tg = _targets(user)
    entries = db.entries_for_date(user["id"])
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    for e in entries:
        for k in totals:
            totals[k] += float(e.get(k) or 0)
    remaining = {k: round(tg[k] - totals[k]) for k in totals}
    return {"date": date.today().isoformat(), "entries": entries,
            "totals": {k: round(v) for k, v in totals.items()},
            "remaining": remaining, "targets": tg}


@app.get("/api/gotos")
def gotos(user=Depends(current_user)):
    hour = datetime.now().hour
    return {"hour": hour, "gotos": db.gotos_for_hour(user["id"], hour)}


@app.get("/api/week")
def week(user=Depends(current_user)):
    days = db.entries_last_n_days(user["id"], 7)
    if not days:
        return {"days": [], "avg": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}}
    n = len(days)
    avg = {"calories": round(sum(float(d["c"] or 0) for d in days) / n),
           "protein": round(sum(float(d["p"] or 0) for d in days) / n),
           "carbs": round(sum(float(d["cb"] or 0) for d in days) / n),
           "fat": round(sum(float(d["f"] or 0) for d in days) / n)}
    return {"days": days, "avg": avg, "note": "Weekly average is the metric that matters."}

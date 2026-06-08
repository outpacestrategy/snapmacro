"""SnapMacro backend — FastAPI app that serves the API and the mobile web UI.

Run:  uvicorn app:app --reload --host 0.0.0.0 --port 8000
Then open http://localhost:8000 on your computer, or http://<your-ip>:8000 on your phone
(same Wi-Fi). With no GEMINI_API_KEY set it runs in mock mode.
"""
import os
import time
import secrets
from collections import defaultdict, deque
from datetime import date, datetime

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import db
import analyzer
import imageutil

app = FastAPI(title="SnapMacro")
db.init_db()

# Optional access gate. Set APP_PASSWORD in the host env when deploying publicly so
# random visitors can't use (and bill) your Gemini key. Unset = open (fine for localhost).
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # 15 MB hard cap on photo uploads

# --- simple in-memory, per-IP rate limiting (no extra deps; single-process uvicorn) ---
_hits = defaultdict(lambda: defaultdict(deque))
_LIMITS = {
    "default":   (120, 60),   # 120 API calls / 60s per IP (normal use is well under this)
    "analyze":   (15, 60),    # 15 photo analyses / 60s per IP (this one costs money)
    "authfail":  (10, 300),   # 10 failed password attempts / 5 min per IP (anti-brute-force)
}


def _client_ip(request):
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _rate_ok(ip, bucket):
    limit, window = _LIMITS[bucket]
    now = time.time()
    dq = _hits[ip][bucket]
    while dq and dq[0] <= now - window:
        dq.popleft()
    if len(dq) >= limit:
        return False
    dq.append(now)
    return True


@app.middleware("http")
async def gate(request, call_next):
    path = request.url.path
    if path.startswith("/api/"):
        ip = _client_ip(request)
        if not _rate_ok(ip, "default"):
            return JSONResponse({"error": "rate_limited", "detail": "Slow down a moment."}, status_code=429)
        if path == "/api/analyze" and not _rate_ok(ip, "analyze"):
            return JSONResponse({"error": "rate_limited", "detail": "Too many photos — wait a minute."}, status_code=429)
        if APP_PASSWORD:
            token = request.cookies.get("smtoken") or request.headers.get("x-app-token", "")
            if not secrets.compare_digest(token, APP_PASSWORD):  # constant-time
                if not _rate_ok(ip, "authfail"):
                    return JSONResponse({"error": "too_many_attempts"}, status_code=429)
                return JSONResponse({"error": "unauthorized"}, status_code=401)
    return await call_next(request)

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "frontend")

TARGETS = {
    "calories": float(os.getenv("TARGET_CALORIES", 2600)),
    "protein": float(os.getenv("TARGET_PROTEIN", 190)),
    "carbs": float(os.getenv("TARGET_CARBS", 280)),
    "fat": float(os.getenv("TARGET_FAT", 80)),
}


def _macros(d):
    return {k: d.get(k, 0) for k in ("calories", "protein", "carbs", "fat")}


@app.get("/", response_class=HTMLResponse)
def home():
    with open(os.path.join(FRONTEND, "index.html"), encoding="utf-8") as f:
        return f.read()


@app.get("/api/config")
def config():
    return {"targets": TARGETS, "mock": not bool(analyzer.GEMINI_API_KEY),
            "model": analyzer.GEMINI_MODEL}


@app.post("/api/analyze")
async def analyze_photo(image: UploadFile = File(...)):
    data = await image.read()
    if not data:
        raise HTTPException(400, "Empty image")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, "Image too large (max 15 MB).")
    # Normalize first: HEIC -> JPEG, auto-rotate, downscale oversized photos.
    norm, mime = imageutil.normalize(data, image.content_type or "image/jpeg")
    result = analyzer.analyze(norm, mime)
    return result


class LogIn(BaseModel):
    name: str
    items: list = []
    calories: float
    protein: float
    carbs: float
    fat: float
    confidence: str = "medium"
    source: str = "photo"          # photo | goto | manual
    meal_id: int | None = None
    save_to_library: bool = True


@app.post("/api/log")
def log_entry(body: LogIn):
    macros = {"calories": body.calories, "protein": body.protein,
              "carbs": body.carbs, "fat": body.fat}
    meal_id = body.meal_id

    # Calibration factor corrects a FRESH photo estimate that was matched to a known meal.
    # Go-to logs already use the meal's stored (already-corrected) macros, so no factor there.
    if meal_id and body.source == "photo":
        factor = db.get_factor(meal_id)
        if factor != 1.0:
            macros = {k: round(v * factor) for k, v in macros.items()}

    if body.save_to_library and body.source != "goto":
        meal_id = db.upsert_meal(body.name, body.items, macros)
    elif body.source == "goto" and meal_id:
        db.upsert_meal(body.name, body.items, macros)  # bumps times_logged

    entry_id = db.add_entry(body.name, body.items, macros, body.confidence,
                            body.source, meal_id)
    return {"ok": True, "entry_id": entry_id, "meal_id": meal_id, "macros": macros}


class CorrectIn(BaseModel):
    entry_id: int
    meal_id: int
    new_calories: float
    old_calories: float


@app.post("/api/correct")
def correct(body: CorrectIn):
    if body.old_calories <= 0:
        raise HTTPException(400, "old_calories must be > 0")
    observed = body.new_calories / body.old_calories
    factor = db.update_factor(body.meal_id, observed)
    return {"ok": True, "meal_id": body.meal_id, "new_factor": round(factor, 3),
            "note": "Future logs of this meal auto-adjust by this factor."}


class EditIn(BaseModel):
    name: str
    calories: float
    protein: float
    carbs: float
    fat: float


@app.post("/api/entry/{entry_id}")
def edit_entry(entry_id: int, body: EditIn):
    """Correct a logged meal. Updates today's totals AND — if it's a known library meal —
    teaches a per-meal calibration factor so future logs of it auto-adjust. This is the
    learning loop."""
    entry = db.get_entry(entry_id)
    if not entry:
        raise HTTPException(404, "Entry not found")
    new = {"calories": body.calories, "protein": body.protein,
           "carbs": body.carbs, "fat": body.fat}
    db.update_entry(entry_id, body.name, new)

    learned, factor = False, None
    meal_id = entry.get("meal_id")
    old_cal = entry.get("calories") or 0
    if meal_id and old_cal > 0 and abs(body.calories - old_cal) > 1:
        factor = round(db.update_factor(meal_id, body.calories / old_cal), 3)
        db.update_meal_macros(meal_id, body.name, new)   # keep go-tos honest
        learned = True
    return {"ok": True, "learned": learned, "factor": factor,
            "note": ("Future logs of this meal will auto-adjust." if learned
                     else "Entry updated.")}


@app.get("/api/today")
def today():
    entries = db.entries_for_date()
    totals = {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}
    for e in entries:
        for k in totals:
            totals[k] += e.get(k) or 0
    remaining = {k: round(TARGETS[k] - totals[k]) for k in totals}
    return {"date": date.today().isoformat(), "entries": entries,
            "totals": {k: round(v) for k, v in totals.items()},
            "remaining": remaining, "targets": TARGETS}


@app.get("/api/gotos")
def gotos():
    hour = datetime.now().hour
    return {"hour": hour, "gotos": db.gotos_for_hour(hour)}


@app.get("/api/week")
def week():
    days = db.entries_last_n_days(7)
    if not days:
        return {"days": [], "avg": {"calories": 0, "protein": 0, "carbs": 0, "fat": 0}}
    n = len(days)
    avg = {
        "calories": round(sum(d["c"] or 0 for d in days) / n),
        "protein": round(sum(d["p"] or 0 for d in days) / n),
        "carbs": round(sum(d["cb"] or 0 for d in days) / n),
        "fat": round(sum(d["f"] or 0 for d in days) / n),
    }
    return {"days": days, "avg": avg, "note": "Weekly average is the metric that matters."}


@app.delete("/api/entry/{entry_id}")
def remove_entry(entry_id: int):
    db.delete_entry(entry_id)
    return {"ok": True}

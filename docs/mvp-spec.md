# SnapMacro — MVP Spec

**Locked decisions (June 5, 2026):**
- **Shape:** Backend + phone-friendly web capture first. Native iOS widget comes later
  once the engine is proven (see `ios-widget-notes.md`).
- **Vision:** Gemini 2.5 Flash-Lite, single structured-JSON call, macros optionally
  grounded against the free USDA FoodData Central DB. Runs in **mock mode** with no key.
- **Device:** iPhone Pro — LiDAR depth deferred to a later phase (photo-only is fine for
  weekly-average tracking).

## What the MVP does

1. **Snap a photo** of your food from your phone's browser (full-screen camera).
2. Backend sends it to the vision model → returns `{items, portion, calories, protein,
   carbs, fat, confidence}` as JSON.
3. The result is **logged to today** automatically. Daily running totals show as a
   glanceable "widget" card at the top — calories + P/C/F consumed.
4. **Personalization (the real accuracy lever):**
   - Every confirmed meal is saved to your **personal meal library** (named).
   - **Time-of-day Go-Tos:** the home screen surfaces your top 2–3 meals for the current
     hour, so logging your usual is **one tap, zero photo, $0 API cost**.
   - **Per-meal portion calibration:** when you correct a portion/macros, the app stores a
     correction factor for that meal and auto-applies it next time. Kills systematic bias
     on your daily staples.
5. **Honesty by design:** every estimate shows a confidence flag and is fully editable.
   The app never hides that it's an educated guess. Weekly average is the headline metric,
   not the noisy daily number.

## Architecture (intentionally simple)

```
phone browser (camera + widget UI)
        │  POST /api/analyze (image)  ·  POST /api/log  ·  GET /api/today
        ▼
   FastAPI backend  ──►  analyzer.py  ──►  Gemini 2.5 Flash-Lite  (or MOCK)
        │                                  └─► USDA FoodData Central (grounding)
        ▼
     SQLite  (meals library, daily log, calibration, go-tos)
```

- **Backend:** Python + FastAPI, serves both the API and the web UI (one process).
- **DB:** SQLite (zero setup). Tables: `meals` (library), `entries` (daily log),
  `corrections` (calibration factors).
- **Frontend:** one mobile-first HTML/JS page. No framework, no build step.
- **Cost control:** Go-To re-logs and library matches never hit the API. Only genuinely
  new photos cost money (~$0.0002–0.001 each).

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | The mobile web app (widget + camera + go-tos). |
| POST | `/api/analyze` | Upload a photo → AI estimate (does not log yet). |
| POST | `/api/log` | Confirm/log an estimate or a go-to to today; saves to library. |
| POST | `/api/correct` | Apply a portion/macro correction → stores calibration. |
| GET | `/api/today` | Today's entries + running totals (powers the widget). |
| GET | `/api/gotos` | Top meals for the current hour-of-day. |
| GET | `/api/week` | 7-day average (the metric that actually matters). |

## Explicitly out of scope for v1 (and why)

- **LiDAR depth capture** — real accuracy gain, but native-only; add after the web engine
  is proven.
- **Native home-screen widget** — needs Xcode/Apple Developer; web "add to home screen"
  stands in for now.
- **Text-embedding auto-match (pgvector)** — Tier-2 nicety; the time-of-day Go-Tos cover
  most repeat-meal friction at zero complexity.
- **Multi-user / auth** — it's a personal tool. Single user, local DB.

## How accuracy is handled honestly

Per the research: ~15–25% per-meal error is the floor (hidden oils/sugar are invisible to
any camera). The MVP does **not** pretend otherwise. It (a) shows confidence, (b) makes
correction one tap, (c) learns staples so repeat days get consistent, and (d) headlines the
**7-day average vs. your activity**, where random per-meal errors cancel out.

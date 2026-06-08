# SnapMacro — Handoff / Context for Claude Code

You're picking up an in-progress build. Read this fully before changing anything.

## What it is

An effortless photo-based calorie/macro tracker. The user snaps a photo of food; the app
estimates calories + macros, grounds the numbers in the USDA database, logs them, and learns
the user's staple meals over time. Read `docs/direction.md` for the product vision and the
hard boundary (**we are NOT building a manual food tracker** — no barcode/database-search/
recipe builder; that's the incumbents' turf). Read `research/landscape-report.md` for the
honest market/accuracy reality.

## Repo layout

```
backend/
  app.py          FastAPI: routes, auth (per-user code in httponly cookie), rate limiting
  db.py           Postgres (Supabase) data layer, psycopg pool, all queries scoped by user_id
  analyzer.py     food photo -> {is_food, items[{food,grams}], macros, confidence}; Gemini + USDA grounding + guardrails
  imageutil.py    normalize uploads (HEIC->JPEG, EXIF rotate, downscale to 1024px)
  seed.py         synthetic data for ONE user (multi-user aware: --code / --new)
  requirements.txt
  .env            SECRETS, git-ignored. Holds DATABASE_URL, GEMINI_API_KEY, USDA_API_KEY
  .env.example    template (no secrets)
frontend/
  index.html      entire web UI (vanilla JS, single file): widget, capture, onboarding, settings, edit sheet
render.yaml       Render deploy blueprint
run.sh            local launcher (creates .venv, installs, runs uvicorn on :8000)
DEPLOY.md, SECURITY.md, docs/, research/
```

## Architecture / how it works

- **One backend, multiple thin clients.** Web UI is one client; the planned Telegram agent
  and home-screen widget will be additional clients calling the same API.
- **Auth:** no passwords. `POST /api/signup {name}` creates a user with a random `code`,
  sets an httponly cookie `sm_user=<code>`. A personal link `/?u=<code>` logs a returning
  user in (`POST /api/login`). `current_user` dependency resolves the cookie to a user row;
  all data is scoped by `user_id`.
- **DB:** Supabase Postgres, project **Outpace Hub** (ref `wosnatgumgpawrfodwnp`), dedicated
  schema **`snapmacro`**, tables `users, meals, entries, corrections`. RLS is ON (no
  policies) — the backend connects as the DB owner via `DATABASE_URL` which bypasses RLS;
  the anon key is never used. Manage schema via Supabase migrations, not ad-hoc.
- **Vision pipeline:** Gemini 2.5 Flash-Lite returns food items + grams; we look up real
  per-100g macros in USDA FoodData Central and compute the meal; grounded numbers become
  primary when coverage ≥ 60%. Mock mode if no `GEMINI_API_KEY`. Non-food / absurd / failed
  inputs return honest error/`is_food:false` states, never a fabricated meal.
- **Personalization (the moat):** per-user meal library + one-tap go-tos surfaced by
  time-of-day + per-meal calibration factor learned when the user corrects a logged meal.

## Current state

- **Phase 1 (done):** single-user web engine — analyze, USDA grounding, calibration,
  edge-case guardrails, per-ingredient gram editing with live recompute, camera-roll upload.
- **Phase 2 (just built, NOT yet live-tested):** migrated SQLite → Supabase Postgres,
  multi-user, personal-code auth, onboarding, settings (name + targets + private link),
  per-user data. Code imports clean; all SQL validated against the real DB via Supabase MCP.
  **The one missing step is a live run** — it needs `DATABASE_URL` in `backend/.env`.

## YOUR IMMEDIATE NEXT STEPS

1. **Confirm `DATABASE_URL` is set** in `backend/.env` (Supabase Session pooler URI with the
   DB password). If absent, ask the user for it — it's the only blocker.
2. **Run and live-test multi-user:** `./run.sh`, open http://localhost:8000, complete
   onboarding (enter name → get private link), log a meal (real or mock), tap it to correct,
   check go-tos/weekly. Then open an incognito window, make a SECOND user, and verify the two
   users have **completely isolated** data (no leakage). Fix anything that breaks.
3. **Deploy to Render** (see `DEPLOY.md`): push to GitHub (remote is
   `github.com/outpacestrategy/snapmacro`), then Render → Blueprint → set `DATABASE_URL` and
   `GEMINI_API_KEY` as dashboard secrets. Hand the user the live URL so friends can test with
   their own `/?u=<code>` links.

## Then (future phases)

- **Phase 3 — Telegram agent** (the effortless front door): a bot that takes a photo (+
  optional text caption as description), runs the same `/api/analyze` + log pipeline, replies
  with the breakdown. Design rule: **ask at most ONE clarifying question, only when
  confidence is low AND it materially changes the numbers**; otherwise log silently. Map each
  Telegram user to a SnapMacro user.
- **Phase 4 — home-screen widget:** read-only daily totals + deep link into the bot chat.
  iOS path via the Scriptable app may avoid full native dev.

## Gotchas / conventions (don't relearn these the hard way)

- **Secrets:** `backend/.env` is git-ignored — NEVER commit it or print the key/DB password.
  Gemini key is sent as an `x-goog-api-key` header (not in the URL) so it can't leak via logs.
- **jsonb items:** `meals.items`/`entries.items` are jsonb; psycopg returns them as native
  Python lists, so the API returns arrays. Frontend uses `asItems()` to accept array-or-string.
  Store via `psycopg.types.json.Json(...)`.
- **Decimal:** Postgres `numeric` → Python `Decimal`. Cast to `float()` before arithmetic
  with floats (already done in `app.py` aggregations) to avoid type errors.
- **Supabase transaction pooler:** prepared statements are disabled in the pool
  (`prepare_threshold=None`) — keep it that way or you'll get "prepared statement already
  exists" errors.
- **Rate limiting** is in-memory per-IP (resets on restart; fine for one instance):
  120 API/min, 15 analyses/min, 8 signups/hr.
- **USDA** uses shared `DEMO_KEY` by default (rate-limited under load). A user's own free key
  is more reliable; grounding degrades gracefully to AI-only if USDA fails.
- **Testing without a local Postgres:** the sandbox can't run Postgres; validate SQL via the
  Supabase MCP (`execute_sql`) or run the app against the real DB once `DATABASE_URL` is set.
- **Verify before declaring done:** syntax-check frontend JS (`node --check` on the extracted
  `<script>`), import-check the backend, and do a real two-user isolation test.

## Task tracker (where things stand)

Done: repo, research, MVP spec, USDA grounding, edge-case guardrails, image normalization +
calibration loop, security hardening, Supabase schema, Postgres migration, multi-user auth.
Pending: **live multi-user test**, **deploy**, then Telegram agent, then widget.

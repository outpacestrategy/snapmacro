# Deploying SnapMacro

Goal: a public URL so you (and friends) can use it on any phone, anywhere — each person on
their own personal `/?u=<code>` link with fully isolated data.

## 0. Safety first — your secrets

Two secrets live in `backend/.env`, which is git-ignored and **never** gets pushed:

- `DATABASE_URL` — the Supabase Session-pooler connection string (with the DB password).
- `GEMINI_API_KEY` — your Google AI Studio key (the app runs in MOCK mode without it).

On the host you set these as **dashboard secrets**, not in the repo. There is no global
app password: auth is per-user (a random `code` in an httponly cookie, and a personal
`/?u=<code>` link). Anyone who reaches the URL can create an account via onboarding, so the
real abuse guard is (a) the built-in rate limits (8 signups/hr, 15 analyses/min, 120 API/min
per IP) and (b) a spending cap on the Gemini key — see section 4.

## 1. Push to GitHub

The repo already exists at `github.com/outpacestrategy/snapmacro` with `origin/main` set up,
so this is just a normal commit + push:

```bash
cd ~/Desktop/snapmacro
git add -A                  # .env is git-ignored and won't be staged
git commit -m "your message"
git push origin main
```

Confirm on GitHub that there is **no `.env` file** in the repo (you should only see
`backend/.env.example`).

## 2. Deploy on Render (easiest)

1. Go to https://render.com, sign in with GitHub.
2. New → Blueprint → pick the `snapmacro` repo. It reads `render.yaml` automatically
   (Python 3.12 is pinned there; root dir is `backend`).
3. Before the first deploy finishes, open the service's **Environment** tab and set the two
   secrets (`render.yaml` marks them `sync: false`, so Render will prompt for them):
   - `DATABASE_URL` = the Supabase Session-pooler URI (same value as your local `backend/.env`).
   - `GEMINI_API_KEY` = your real key (omit to run in mock mode).
   `GEMINI_MODEL` and `USDA_API_KEY` already have defaults in `render.yaml`.
4. Deploy. You get a URL like `https://snapmacro.onrender.com`. Open it, complete onboarding,
   and you'll get your personal `/?u=<code>` link — add it to your home screen. Share each
   friend their own link after they onboard (everyone gets a distinct code + isolated data).

(Railway or Fly.io work too — the included `Procfile` covers Railway/Heroku-style hosts.
Set the same `DATABASE_URL` + `GEMINI_API_KEY` secrets there.)

## 3. Data persistence — durable

Data lives in **Supabase Postgres** (project *Outpace Hub*, schema `snapmacro`), not on the
host's disk. So logged meals, corrections, and the personal meal library **persist across
redeploys and across the free tier's sleep/wake cycles**. The only host-local state is the
in-memory per-IP rate-limit counters, which reset on restart (harmless).

Note: Render's free tier sleeps after inactivity, so the first request after idle takes a few
seconds to wake — the data is still there, it's just a cold start.

## 4. Cost guardrail

Set a spending cap on your Gemini key in Google AI Studio. Combined with the built-in rate
limits, a leaked URL can't run up a real bill. USDA grounding uses the shared `DEMO_KEY` by
default (rate-limited under load); add your own free key
(https://fdc.nal.usda.gov/api-key-signup) as `USDA_API_KEY` for more reliable grounding.

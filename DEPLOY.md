# Deploying SnapMacro

Goal: a public URL so you can use it on your phone anywhere, not just home Wi-Fi.

## 0. Safety first — your API key

Your real key lives in `backend/.env`, which is git-ignored and **never** gets pushed.
On the host, you set `GEMINI_API_KEY` as a secret env var in the dashboard — not in the repo.
Also set `APP_PASSWORD` so the public URL isn't open for strangers to use (and bill) your key.

## 1. Push to GitHub (run on your Mac)

The repo was first created inside a sandbox that left git in a locked state, so the cleanest
move is a fresh init on your Mac:

```bash
cd ~/Desktop/snapmacro
rm -rf .git                 # discard the sandbox's locked git; your files are untouched
git init -b main
git add -A
git commit -m "SnapMacro MVP"
```

Then create the GitHub repo and push. Easiest with the GitHub CLI:

```bash
brew install gh        # if you don't have it
gh auth login          # follow the prompts
gh repo create snapmacro --private --source=. --push
```

No CLI? Create an empty repo at github.com/new (name it `snapmacro`, Private), then:

```bash
git remote add origin https://github.com/<your-username>/snapmacro.git
git push -u origin main
```

Confirm on GitHub that there is **no `.env` file** in the repo (you should only see
`backend/.env.example`).

## 2. Deploy on Render (easiest)

1. Go to https://render.com, sign in with GitHub.
2. New → Blueprint → pick your `snapmacro` repo. It reads `render.yaml` automatically.
3. Before the first deploy finishes, open the service's **Environment** tab and set:
   - `GEMINI_API_KEY` = your real key
   - `APP_PASSWORD` = a password you choose (you'll type it once on your phone)
4. Deploy. You get a URL like `https://snapmacro.onrender.com`. Open it, enter the password,
   add it to your home screen.

(Railway or Fly.io work too — the included `Procfile` covers Railway/Heroku-style hosts.)

## 3. Known limitation — data persistence

The free tier uses an **ephemeral filesystem**, so the SQLite database (your logged meals)
**resets whenever the service redeploys or sleeps**. Fine for trying it out; not fine for a
long-term log.

When you want durable history, the upgrade is to swap SQLite for Postgres (Render and Railway
both offer a free Postgres add-on) or attach a persistent disk/volume. That's a follow-up —
ask and I'll wire it in.

## 4. Cost guardrail

Set a spending cap on your Gemini key in Google AI Studio. With `APP_PASSWORD` set and a cap
in place, a leaked URL can't run up a real bill.

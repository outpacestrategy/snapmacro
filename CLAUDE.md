# CLAUDE.md — SnapMacro

Guidance for Claude Code / any AI agent working in this repo. Read this first, every session.

## Start of every session

1. Read **`HANDOFF.md`** (full architecture, current state, next steps, gotchas).
2. Skim **`docs/direction.md`** (product vision + the hard boundary: this is NOT a manual
   food tracker).
3. Run `git pull` so you're on the latest — the GitHub repo is the single source of truth.

## Standing rule: the repo is the portable brain — keep it synced

The whole point of this repo is that the user can sit down at ANY computer, `git pull`, and an
agent has the complete scope to keep building. That only works if context lives in the repo and
is pushed regularly. So:

- **Keep `HANDOFF.md` current.** Whenever you finish a meaningful chunk of work, or change the
  architecture, state, or next steps, update `HANDOFF.md` to reflect reality before you stop.
- **Capture decisions in the repo, not just in chat.** Product/architecture decisions go in
  `docs/` (e.g. `docs/direction.md`); deploy/runbook details in `DEPLOY.md`; security posture in
  `SECURITY.md`. Don't leave important context only in a conversation that another machine can't see.
- **Commit and push at the end of every working session** (and after any significant milestone),
  so another computer can pull the full, current scope. Use clear commit messages.
- If you add a new subsystem (e.g. the Telegram bot), document it in `HANDOFF.md` and add a short
  doc in `docs/` so the next session understands it without re-reading all the code.

A good end-of-session checklist: update `HANDOFF.md` → verify no secrets are staged →
`git add -A && git commit -m "..." && git push`.

## Never commit secrets

- `backend/.env` is git-ignored and holds `DATABASE_URL`, `GEMINI_API_KEY`, `USDA_API_KEY`.
  NEVER commit it, print it, or paste secrets into tracked files or chat. Only `.env.example`
  (placeholders) is tracked.
- Before any commit, sanity-check that no real key or DB password is in a tracked file.

## Conventions (see HANDOFF.md for the full list)

- One FastAPI backend; the web UI, future Telegram agent, and widget are thin clients of it.
- Postgres via Supabase (schema `snapmacro`, project ref `wosnatgumgpawrfodwnp`); all data scoped
  by `user_id`; manage schema via Supabase migrations.
- `items` columns are jsonb (frontend `asItems()` helper); cast Postgres `Decimal` to `float`
  before arithmetic; keep `prepare_threshold=None` for the Supabase pooler.
- Mock mode when `GEMINI_API_KEY` is unset; USDA grounding degrades gracefully on failure.

## Verify before declaring done

- Frontend: `node --check` the extracted `<script>`.
- Backend: import-check, and run a real test (e.g. two-user data isolation) — not just "it imports".
- Add a verification step to any non-trivial task.

## Roadmap

Phase 1 (done): web engine. Phase 2 (built, needs live test + deploy): multi-user on Supabase.
Phase 3: Telegram agent (effortless front door; ask ≤1 clarifying question, only when it matters).
Phase 4: home-screen widget (read-only daily totals + deep link to the chat).

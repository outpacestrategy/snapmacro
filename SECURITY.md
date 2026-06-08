# SnapMacro — Security posture

Scope: a personal tool. These measures make it safe to expose on a public URL without
inviting abuse or leaking your key. It is not hardened to multi-tenant SaaS standards.

## What's protected

- **API key never in the repo.** `backend/.env` is git-ignored; only `.env.example`
  (no real key) is tracked. Verified the key string appears in no source file or git history.
- **Key never in a URL.** The Gemini key is sent as an `x-goog-api-key` header, so it can't
  leak through error messages or host access logs (which echo request URLs).
- **Access gate.** Set `APP_PASSWORD` on the host → all `/api/*` calls require it (cookie or
  `x-app-token` header). The page shell loads, but no data/AI calls work without the password.
  Password check is **constant-time** (`secrets.compare_digest`) to avoid timing attacks.
- **Rate limiting (per IP, in-memory):**
  - 120 API calls / 60s overall
  - 15 photo analyses / 60s (the endpoint that costs money)
  - 10 failed password attempts / 5 min (anti-brute-force lockout)
- **Upload cap.** Photos over 15 MB are rejected (413) before any processing.
- **External-call cap.** At most 12 USDA lookups per photo (cost/DoS guard).
- **Injection-safe.** All SQL uses parameterized queries. All user/AI-supplied strings shown
  in the UI are HTML-escaped. No user-controlled file paths.
- **CSRF.** Auth cookie is `SameSite=Lax` (+ `Secure` over HTTPS), which blocks cross-site
  state-changing requests.

## Residual risks (know these)

- **Single shared password, no per-user accounts.** Fine for one person; don't share the URL.
- **Rate limiting is in-memory and per-process.** Resets on restart and isn't shared across
  multiple instances. Adequate for a single free-tier instance; not for horizontal scaling.
- **Free-tier data is ephemeral** (see DEPLOY.md) — a durability concern, not a security one.
- **The auth cookie is readable by JS** (it's set client-side), so a successful XSS could read
  it. XSS surface is mitigated by escaping, but keep that in mind before adding any feature
  that renders raw HTML.

## Before you deploy — checklist

1. Set `APP_PASSWORD` to something only you know.
2. Set `GEMINI_API_KEY` as a host secret (never in the repo).
3. Set a **spending cap** on the Gemini key in Google AI Studio — the ultimate backstop.
4. (Optional but wise) Rotate the Gemini key once, since the original was typed during setup.
5. Confirm the pushed GitHub repo shows no `.env` — only `backend/.env.example`.

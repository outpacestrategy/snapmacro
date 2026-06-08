# SnapMacro (working title)

Effortless calorie + macro tracking. No logging, no UI to fight with. Take a photo
of your food → the app estimates calories and macros in the background → your day's
running totals live on a home-screen widget.

## The core idea

The honest framing: this is **a very close educated guess**, not a food scale. The
target user (Drew) eats roughly the same things every day and is an athlete who wants
to understand intake *relative to* activity (steps, training) — not to log every gram.
"Close enough, every day, with zero friction" beats "precise but I stop doing it in a
week."

## Design principles

1. **Zero interface.** The primary interaction is: open camera → snap food → done. The
   app handles classification, portion estimation, and macro math on the backend.
2. **Glanceable.** A home-screen widget shows calories + macros remaining/consumed for
   the day. That's the main surface, not an app you open.
3. **Cheap to run.** Use the lowest-cost AI vision that's accurate enough. Per-photo
   cost is the key unit economic.
4. **Trainable.** The user can correct estimates, and the app learns their staples so
   repeat meals get more accurate over time. Reference objects (e.g. always include
   your hand, or a known object) help calibrate portion size.
5. **Radical honesty.** This project file and the assistant working on it will not
   inflate accuracy, hide limitations, or tell Drew what he wants to hear. If photo
   calorie estimation can't hit a useful error band, that gets said plainly.

## Inputs the user might give

- Photo of a plated meal (primary)
- Photo of a nutrition label (optional, high-accuracy path)
- A correction ("that was 8oz not 6oz") to train the model

## Open questions (resolved during research / spec)

- Platform: iOS-first (home-screen widget + camera). Native vs. cross-platform?
- Which vision API hits the accuracy/cost sweet spot?
- How good is photo-only portion estimation really, and does a reference object
  meaningfully help?
- What's the cheapest reliable per-photo pipeline?

## Run it

```bash
cd ~/Desktop/snapmacro
./run.sh
```

First run installs dependencies and creates `backend/.env` (it'll run in **mock mode**
right away — simulated analysis so you can try the whole flow). Then open the printed URL:
`http://localhost:8000` on your Mac, or `http://<your-ip>:8000` on your iPhone (same
Wi-Fi) — the "Snap food" button opens your camera.

**To turn on real AI estimates:** get a free key at https://aistudio.google.com/apikey,
paste it into `backend/.env` as `GEMINI_API_KEY=...`, restart. Cost ≈ $0.0002–0.001/photo.

Set your daily targets (calories/protein/carbs/fat) in `backend/.env` too.

## Status

- [x] Repo created
- [x] Deep research dive — see `research/landscape-report.md`
- [x] MVP spec locked — see `docs/mvp-spec.md`
- [x] MVP build (web engine) — backend + mobile capture UI, tested end-to-end
- [ ] Add real Gemini key & test on real food photos
- [ ] (Later) Native iOS home-screen widget + LiDAR depth — see `docs/ios-widget-notes.md`

## Research TL;DR (the honest version)

- **As a personal tool for you: strong yes.** Your case is the rare one where photo
  tracking actually works — you eat the same staples (personalization makes it accurate
  fast), you care about *weekly trends vs. activity* (so per-meal error doesn't matter,
  only consistency), and you want zero friction (the genuine gap everyone under-delivers).
- **As a standalone business: be skeptical.** Red ocean. MyFitnessPal bought Cal AI (Mar
  2026); photo AI is commoditized table stakes; accuracy is unwinnable (the only people
  claiming an accuracy moat are faking studies to do it).
- **Accuracy reality:** ~15–25% per-meal error is the real floor (hidden oils/sugar are
  invisible to any camera). But errors are partly random and **cancel over a week** — track
  the 7-day average against bodyweight, not daily numbers.
- **Cheapest pipeline:** one **Gemini 2.5 Flash-Lite** call, structured JSON, optionally
  grounded on the free USDA database. **~$0.0002–0.001/photo → ~$2–4/mo at 10k photos.**
- **The real moat for your use case is personalization, and it's cheap:** a named
  confirmed-meal library + one-tap re-log + time-of-day "Go-Tos" + per-meal portion
  calibration. Retrieval + UX, not custom ML.

See `research/` for the landscape report and `docs/` for the spec.

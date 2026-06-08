# SnapMacro — Product Direction

The north star: **effortless macro tracking for people who would otherwise not track at
all.** Not a better manual logger — a way to not have to log.

## The three surfaces (one backend)

The FastAPI backend is the brain (analyze → USDA-ground → log → calibrate → personal meal
library). Every surface is a thin client calling the same API. Nothing is single-surface.

1. **The Agent (front door — effortless capture).** A chat agent (Telegram first) where the
   user sends a food photo, optionally with a short text description ("post-workout, ~6oz
   chicken"). The agent logs it and replies with the breakdown. This is the primary,
   effortless path — the whole point of the product.

2. **The Widget (the glance).** A home-screen widget showing today's calories + macros, with
   a button that deep-links straight into the agent chat. Read-only. The only piece the
   agent channel can't provide itself.

3. **The Web UI (the back office — hands-on review & control).** Review the day, see the
   ingredient breakdown, correct an estimate, check the weekly trend, adjust targets. For
   the user who occasionally wants to get hands-on. Same backend, complementary to the agent.

## The boundary — what we will NOT build

We are **not** building a manual food tracker. No barcode scanner, no giant searchable food
database, no recipe builder, no meal planner. That is MyFitnessPal's and MacroFactor's turf;
competing there means becoming a worse version of them and losing the one thing that makes us
different. If a user fundamentally wants meticulous manual logging, **they are not our user** —
and that's fine. Knowing who it's *not* for keeps us focused.

The web UI's job is **review and control**, not data entry from scratch. The risk to guard
against is scope creep turning the review surface into a competing logger. Hold that line.

## Design rules (the "effortless" contract)

- **Default path is silent.** Send photo → logged → done. No questions, no taps required.
- **The agent asks at most ONE clarifying question, and only when** confidence is low *and*
  the ambiguity materially changes the numbers (e.g. "grilled or fried?"). An agent that asks
  two questions per meal is more annoying than no agent. When in doubt, log it and let the
  user correct later if they care.
- **Optional, never required.** A text description sharpens the estimate but is never demanded.
- **Honesty over false precision.** Show confidence, show the breakdown, headline the weekly
  average — never pretend a photo is a food scale.
- **Personalization carries the accuracy.** Staples get learned (calibration + library), so
  repeat meals get consistent and cheap, which is where real users live.

## Who it's for

The person who would rather text a photo and glance at a widget than open an app and search a
database. Athletes/consistent eaters who care about weekly trends vs. activity, not gram-level
daily precision. We serve them excellently across all three surfaces — precisely because we're
not trying to be everything to everyone.

## Rough roadmap

- **Phase 1 (done):** Web engine — analyze, USDA grounding, personal library, calibration,
  edge-case guardrails, per-ingredient editing.
- **Phase 2 (next):** Multi-user + persistent storage + public deploy, so real people (friends)
  can test with their own separate data.
- **Phase 3:** Telegram agent — the effortless front door.
- **Phase 4:** Home-screen widget (read-only daily totals + deep link to the chat).

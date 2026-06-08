# Native iOS widget + LiDAR — notes for the next phase

Deferred from the MVP on purpose. The web app proves the engine first; this is the
upgrade path once you've confirmed it's actually useful day-to-day.

## What a true home-screen widget requires

- A native Swift app (the web "Add to Home Screen" is a stand-in, but iOS does **not**
  allow interactive third-party home-screen widgets — they're glanceable only, tap opens
  the app).
- Built in **Xcode** on your Mac, with a **WidgetKit** extension.
- An **Apple Developer account** ($99/yr) to run it on your own iPhone beyond 7-day
  free-provisioning, and required for TestFlight/App Store.

## Recommended native shape (reuses this backend unchanged)

- **App:** thin SwiftUI client that calls the same FastAPI endpoints (`/api/analyze`,
  `/api/log`, `/api/today`, `/api/gotos`). Host the backend on a cheap VPS or Fly.io so
  your phone reaches it anywhere, not just home Wi-Fi.
- **Capture:** share-sheet + Camera; optionally a Lock Screen / Control Center quick action.
- **Widget (WidgetKit):** small/medium widget showing calories + P/C/F remaining, pulling
  `/api/today` on a timeline refresh. Tapping a Go-To deep-links into a one-tap log.

## LiDAR depth (iPhone Pro — you have it)

- Use **ARKit** scene depth / the TrueDepth-or-LiDAR depth map at capture time.
- Per the research, depth roughly **halves portion error** (Nutrition5k: calorie MAE
  26% → 16.5%) and it's **passive** — no extra user step, so no added friction.
- Send the depth map (or a derived volume estimate) alongside the photo to the backend;
  add a `portion_volume_ml` hint to the analyzer prompt to anchor the portion guess.
- This is the single highest-value native-only upgrade. Everything else (DB, AI, macros,
  personalization) is already done and platform-agnostic.

## Order of operations

1. Prove the web MVP is genuinely effortless and useful for ~2–4 weeks.
2. Host the backend remotely.
3. Build the SwiftUI app + WidgetKit extension against the existing API.
4. Add LiDAR depth capture as the accuracy upgrade.

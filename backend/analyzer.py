"""Food photo -> calories/macros, grounded in real nutrition data.

The compound-system idea (why this beats raw "ask an LLM what's in the photo"):
  1. Gemini does what it is good at: identify each food and estimate its WEIGHT in grams.
  2. We then look up the REAL per-100g macros for each food in the USDA FoodData Central
     database and compute the meal from actual numbers — not the model's guessed macros.
  3. If USDA covers most of the plate, the grounded numbers become the primary estimate;
     the model's own guess is kept as a fallback/comparison.

If GEMINI_API_KEY is not set, falls back to MOCK mode so the whole app runs immediately.
USDA grounding still runs in mock mode (it only needs USDA_API_KEY, default DEMO_KEY).
"""
import os
import json
import base64
import random
from concurrent.futures import ThreadPoolExecutor

import httpx

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
USDA_API_KEY = os.getenv("USDA_API_KEY", "DEMO_KEY").strip()
GROUND = os.getenv("GROUND_WITH_USDA", "true").lower() != "false"

PROMPT = """You are a sports-nutrition vision estimator. First decide: does this photo
actually show food or drink a person would eat/log? If it does NOT (it's a person, object,
scene, screenshot, empty plate, etc.), set "is_food" false, leave items empty, and set all
macros to 0 — do NOT invent a meal.

If it IS food: identify each distinct item and estimate its EDIBLE WEIGHT in grams (your
strongest job is portion size; macros are looked up separately). Hidden oils/butter/sugar
are invisible, so include a realistic cooking-fat item if the dish was likely cooked in fat.

Packaged/branded products: READ any visible can/label text. If a drink or packaged item is
sugar-free, zero-sugar, or diet, you MUST say so in its food name using the words
"sugar-free" or "zero sugar" (e.g. "sugar-free energy drink", never just "energy drink") —
the macro database matches on your food name and would otherwise assume full sugar. If you
recognize the exact product, use its real label nutrition for your macro totals.

Return ONLY valid minified JSON, no markdown, exactly:
{"is_food":true|false,
"name":"<short meal name, or what the photo shows if not food>",
"items":[{"food":"<plain USDA-style food name>","grams":<int>}],
"portion_note":"<brief portion reasoning, or why it's not food>",
"calories":<int>,"protein_g":<int>,"carbs_g":<int>,"fat_g":<int>,
"confidence":"high|medium|low"}
Keep totals realistic for one human meal (calories roughly 0-3000). Be terse."""

# Sanity bounds for a single human meal. Outside these = flag for review, never silent.
MAX_BOUNDS = {"calories": 4000, "protein": 400, "carbs": 600, "fat": 300}

# Mock meals now carry per-item grams so grounding can run end-to-end offline-of-Gemini.
MOCK_MEALS = [
    {"name": "Chicken, rice & broccoli",
     "items": [{"food": "grilled chicken breast", "grams": 170},
               {"food": "white rice cooked", "grams": 180},
               {"food": "broccoli", "grams": 90}],
     "portion_note": "~6oz chicken, ~1 cup rice", "calories": 540, "protein_g": 48,
     "carbs_g": 55, "fat_g": 11, "confidence": "medium"},
    {"name": "Oatmeal, banana & peanut butter",
     "items": [{"food": "oats cooked", "grams": 240},
               {"food": "banana", "grams": 118},
               {"food": "peanut butter", "grams": 16}],
     "portion_note": "~1 cup oats, 1 banana, 1 tbsp PB", "calories": 420, "protein_g": 14,
     "carbs_g": 62, "fat_g": 13, "confidence": "medium"},
    {"name": "Greek yogurt & berries",
     "items": [{"food": "greek yogurt plain nonfat", "grams": 200},
               {"food": "blueberries", "grams": 70},
               {"food": "honey", "grams": 10}],
     "portion_note": "~1 cup yogurt, handful berries", "calories": 230, "protein_g": 22,
     "carbs_g": 28, "fat_g": 3, "confidence": "high"},
    {"name": "Steak & sweet potato",
     "items": [{"food": "beef sirloin steak", "grams": 225},
               {"food": "sweet potato baked", "grams": 150},
               {"food": "asparagus", "grams": 85},
               {"food": "olive oil", "grams": 7}],
     "portion_note": "~8oz steak, 1 medium sweet potato", "calories": 680, "protein_g": 52,
     "carbs_g": 40, "fat_g": 32, "confidence": "low"},
]

# USDA nutrient name -> our macro key. Energy handled separately (needs KCAL unit).
NUTRIENT_MAP = {
    "Protein": "protein",
    "Carbohydrate, by difference": "carbs",
    "Total lipid (fat)": "fat",
}


def _normalize(raw: dict) -> dict:
    def num(*keys):
        for k in keys:
            if k in raw and raw[k] is not None:
                try:
                    return float(raw[k])
                except (TypeError, ValueError):
                    pass
        return 0.0

    # items may be list[str] (legacy) or list[{food,grams}] (new). Normalize both.
    raw_items = raw.get("items", [])
    items, items_named = [], []
    if isinstance(raw_items, list):
        for it in raw_items:
            if isinstance(it, dict):
                food = str(it.get("food", "")).strip()
                grams = it.get("grams")
                try:
                    grams = float(grams) if grams is not None else None
                except (TypeError, ValueError):
                    grams = None
                if food:
                    items_named.append({"food": food, "grams": grams})
                    items.append(food)
            elif isinstance(it, str) and it.strip():
                items.append(it.strip())
                items_named.append({"food": it.strip(), "grams": None})

    is_food = raw.get("is_food", True)
    if isinstance(is_food, str):
        is_food = is_food.strip().lower() not in ("false", "no", "0")

    return {
        "is_food": bool(is_food),
        "name": str(raw.get("name", "Meal")).strip()[:60] or "Meal",
        "items": items,                       # flat list for display/storage (back-compat)
        "items_named": items_named,           # with grams, for grounding
        "portion_note": str(raw.get("portion_note", "")).strip()[:160],
        "calories": round(num("calories", "kcal")),
        "protein": round(num("protein_g", "protein")),
        "carbs": round(num("carbs_g", "carbs")),
        "fat": round(num("fat_g", "fat")),
        "confidence": str(raw.get("confidence", "medium")).lower(),
    }


def validate(out: dict) -> dict:
    """Guardrails: catch non-food, absurd magnitudes, and empty results. Never silent —
    flags get surfaced to the user. Returns the (possibly annotated) dict."""
    flags = []

    # 1) Non-food: zero it out so nothing garbage can be logged by accident.
    if not out.get("is_food", True):
        out.update({"calories": 0, "protein": 0, "carbs": 0, "fat": 0,
                    "items": [], "items_named": [], "confidence": "low"})
        out["needs_attention"] = True
        out["flag"] = "This doesn't look like food. Retake, or add it manually below."
        return out

    # 2) Absurd magnitudes (e.g. a model returning 1.5M calories).
    for k, cap in MAX_BOUNDS.items():
        v = out.get(k, 0) or 0
        if v < 0:
            out[k] = 0
        elif v > cap:
            flags.append(f"{k} looked off ({v}); please check.")

    # 3) Food but no numbers at all.
    if out.get("is_food", True) and out.get("calories", 0) == 0 and not out.get("items"):
        out["needs_attention"] = True
        flags.append("Couldn't read a clear meal here. Retake, or add it manually.")

    if flags:
        out["needs_attention"] = True
        out["flag"] = " ".join(flags)
        out["confidence"] = "low"
    return out


def _mock(image_bytes: bytes) -> dict:
    idx = (sum(image_bytes[:64]) if image_bytes else random.randint(0, 99)) % len(MOCK_MEALS)
    out = _normalize(dict(MOCK_MEALS[idx]))
    out["mock"] = True
    return out


def _gemini(image_bytes: bytes, mime: str = "image/jpeg") -> dict:
    # Key goes in a header, NOT the URL — so it can't leak via error messages or logs
    # (httpx error strings echo the request URL).
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_MODEL}:generateContent")
    headers = {"x-goog-api-key": GEMINI_API_KEY}
    payload = {
        "contents": [{
            "parts": [
                {"text": PROMPT},
                {"inline_data": {"mime_type": mime,
                                 "data": base64.b64encode(image_bytes).decode()}},
            ]
        }],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 500,
                             "responseMimeType": "application/json"},
    }
    with httpx.Client(timeout=30) as client:
        r = client.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    out = _normalize(json.loads(text))
    out["mock"] = False
    return out


# ---------- USDA grounding ----------

def _usda_per100g(query: str, client: httpx.Client):
    """Return per-100g macros for a food name, preferring whole-food data types."""
    try:
        r = client.get(
            "https://api.nal.usda.gov/fdc/v1/foods/search",
            params={"query": query, "pageSize": 1, "api_key": USDA_API_KEY,
                    "dataType": "Foundation,SR Legacy,Survey (FNDDS)"},
        )
        if r.status_code != 200 or not r.json().get("foods"):
            # retry without dataType filter (lets branded foods through)
            r = client.get("https://api.nal.usda.gov/fdc/v1/foods/search",
                           params={"query": query, "pageSize": 1, "api_key": USDA_API_KEY})
        foods = r.json().get("foods", [])
        if not foods:
            return None
        food = foods[0]
        macros = {"calories": None, "protein": None, "carbs": None, "fat": None}
        for n in food.get("foodNutrients", []):
            name, unit, val = n.get("nutrientName"), n.get("unitName"), n.get("value")
            if name == "Energy" and unit == "KCAL" and macros["calories"] is None:
                macros["calories"] = val
            elif name in NUTRIENT_MAP and macros[NUTRIENT_MAP[name]] is None:
                macros[NUTRIENT_MAP[name]] = val
        if macros["calories"] is None:
            return None
        return {"desc": food.get("description", "")[:60], "per100g": macros}
    except Exception:  # noqa: BLE001 - grounding is best-effort
        return None


def ground_with_usda(result: dict) -> dict:
    """Compute the meal from real USDA per-100g data when the model gave per-item grams.
    Sets grounded macros as primary if coverage is good; always keeps the model's own
    estimate under `ai_estimate` for transparency."""
    named = [it for it in result.get("items_named", []) if it.get("grams")]
    named = named[:12]  # cap external lookups per photo (DoS / cost guard)
    if not result.get("is_food", True) or not GROUND or not USDA_API_KEY or not named:
        return result

    ai_estimate = {k: result[k] for k in ("calories", "protein", "carbs", "fat")}
    totals = {"calories": 0.0, "protein": 0.0, "carbs": 0.0, "fat": 0.0}
    breakdown, matched = [], 0

    # Look items up concurrently — sequentially this is the slowest part of the photo
    # flow (up to 12 round-trips). httpx.Client is thread-safe; ex.map keeps order.
    with httpx.Client(timeout=15) as client:
        with ThreadPoolExecutor(max_workers=min(6, len(named))) as ex:
            refs = list(ex.map(lambda it: _usda_per100g(it["food"], client), named))

    for it, ref in zip(named, refs):
        if not ref:
            breakdown.append({"food": it["food"], "grams": it["grams"], "matched": False})
            continue
        f = it["grams"] / 100.0
        per = ref["per100g"]
        item_macros = {k: round((per.get(k) or 0) * f) for k in totals}
        for k in totals:
            totals[k] += item_macros[k]
        matched += 1
        breakdown.append({"food": it["food"], "grams": it["grams"], "matched": True,
                          "usda": ref["desc"],
                          "per100g": {k: round(per.get(k) or 0, 1) for k in totals},
                          **item_macros})

    coverage = matched / len(named)
    result["ai_estimate"] = ai_estimate
    result["grounding"] = {"coverage": round(coverage, 2), "matched": matched,
                           "total_items": len(named), "breakdown": breakdown,
                           "grounded_totals": {k: round(v) for k, v in totals.items()}}

    # Use grounded numbers as the primary estimate when most of the plate matched —
    # unless they wildly contradict the AI's own estimate. A huge gap usually means a
    # bad generic DB match (e.g. a sugar-free energy drink matched to the sugared
    # generic, or "diet coke" matched to "Roll, diet"); the label-aware AI estimate is
    # more trustworthy there, and we surface the conflict instead of silently picking.
    ai_cal, gr_cal = float(ai_estimate.get("calories") or 0), totals["calories"]
    conflict = (ai_cal > 0 and gr_cal > 0 and abs(ai_cal - gr_cal) > 100
                and max(ai_cal, gr_cal) / min(ai_cal, gr_cal) > 2.5)
    if coverage >= 0.6 and conflict:
        result["source_of_numbers"] = "ai_estimate_db_conflict"
        result["needs_attention"] = True
        result["confidence"] = "low"
        result["flag"] = (f"AI read this as ~{round(ai_cal)} kcal but the nutrition DB "
                          f"match says ~{round(gr_cal)} — likely a diet/branded product "
                          f"the DB matched wrong. Check before logging.")
    elif coverage >= 0.6:
        for k in totals:
            result[k] = round(totals[k])
        result["source_of_numbers"] = "usda_grounded"
    else:
        result["source_of_numbers"] = "ai_only"
    return result


def _error_result(reason: str) -> dict:
    """Explicit failure state — never a fabricated meal. The UI shows this honestly."""
    return {"is_food": None, "error": True, "needs_attention": True,
            "name": "Couldn't analyze photo", "items": [], "items_named": [],
            "portion_note": "", "calories": 0, "protein": 0, "carbs": 0, "fat": 0,
            "confidence": "low", "mock": False,
            "flag": reason, "warning": reason}


def analyze(image_bytes: bytes, mime: str = "image/jpeg") -> dict:
    """Main entry point. Never raises — always returns a usable, honest dict.

    No API key  -> MOCK demo meal (clearly flagged).
    API/parse error -> explicit ERROR state (never a fake meal).
    Success     -> validated, USDA-grounded estimate.
    """
    if not GEMINI_API_KEY:
        return validate(ground_with_usda(_mock(image_bytes)))
    try:
        result = _gemini(image_bytes, mime)
    except json.JSONDecodeError:
        return _error_result("The AI response couldn't be read. Try retaking the photo.")
    except httpx.HTTPStatusError as e:
        code = e.response.status_code
        if code in (401, 403):
            return _error_result("API key was rejected (401/403). Check GEMINI_API_KEY in .env.")
        if code == 429:
            return _error_result("Rate/quota limit hit (429). Wait a moment and try again.")
        return _error_result(f"Image couldn't be analyzed (HTTP {code}). Try a different photo.")
    except Exception as e:  # noqa: BLE001
        return _error_result(f"Analysis failed ({type(e).__name__}). Try again.")
    return validate(ground_with_usda(result))

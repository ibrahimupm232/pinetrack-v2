"""
Plot-level cultivation recommendations from the cleaned soil and weather data.

Version 1 is a transparent, rule-based scorer, so every recommendation can be
explained to a farmer. Each variety has preferred ranges; a plot's score is how
well its recent average conditions fit them. The confidence shown with every
recommendation comes from the data-quality scores of the readings it used:
this is where the data-quality pipeline (O2) reaches the user.

The ranges below are indicative values for Malaysian pineapple growing,
compiled for this prototype. They should be reviewed with an agronomist
(e.g. MPIB) before the system is used for real decisions.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from app.models import CleanedReading, Harvest
from app.services.data_quality_service import NUMERIC, normalise_plot

LOOKBACK_DAYS = 180   # readings older than this (relative to the plot's newest) are not averaged
MIN_READINGS = 3      # fewer than this lowers confidence

# Preferred (low, high) ranges; soil: preferred, acceptable
VARIETIES = {
    "MD2": {
        "description": "Sweet, low-acid fresh-market variety; highest export value. Best on well-drained mineral soil.",
        "ph": (4.5, 5.5), "temperature": (23, 32), "rainfall": (2.5, 5.5), "moisture": (20, 45),
        "soil": {"mineral": 1.0, "peat": 0.6},
    },
    "Josapine": {
        "description": "Malaysian hybrid for the fresh market; early maturing and does well on both peat and mineral soil.",
        "ph": (4.0, 5.5), "temperature": (22, 32), "rainfall": (2.5, 6.0), "moisture": (25, 55),
        "soil": {"peat": 1.0, "mineral": 0.9},
    },
    "Morris": {
        "description": "Traditional Malaysian variety, tolerant of acidic peat; used fresh and for canning.",
        "ph": (3.5, 5.0), "temperature": (22, 33), "rainfall": (3.0, 7.0), "moisture": (30, 60),
        "soil": {"peat": 1.0, "mineral": 0.7},
    },
    "N36": {
        "description": "Hardy canning variety bred for peat; high yield in wet, acidic conditions.",
        "ph": (3.5, 5.0), "temperature": (22, 33), "rainfall": (3.0, 7.5), "moisture": (35, 65),
        "soil": {"peat": 1.0, "mineral": 0.5},
    },
}
WEIGHTS = {"ph": 0.35, "soil": 0.25, "temperature": 0.2, "rainfall": 0.1, "moisture": 0.1}
LABELS = {"ph": "Soil pH", "temperature": "Temperature", "rainfall": "Rainfall", "moisture": "Soil moisture", "soil": "Soil type"}


def range_fit(value: float, low: float, high: float) -> float:
    """
    1.0 at the centre of the preferred range, 0.8 at its edges, then falling
    linearly to 0 one range-width outside it. The gradient inside the range
    separates varieties whose ranges both contain the value.
    """
    width = high - low or 1.0
    if low <= value <= high:
        half = width / 2
        return 1.0 - 0.2 * abs(value - (low + half)) / half
    gap = low - value if value < low else value - high
    return max(0.0, 0.8 * (1.0 - gap / width))


def score_variety(profile: dict, conditions: dict) -> tuple[float, list[dict]]:
    """Weighted fit of conditions to one variety's ranges (missing parameters are left out)"""
    parts, total, weight = [], 0.0, 0.0
    for key, w in WEIGHTS.items():
        if key == "soil":
            soil = conditions.get("soil_type")
            if not soil:
                continue
            fit = profile["soil"].get(soil, 0.3)
            parts.append({"factor": LABELS[key], "fit": round(fit * 100), "value": soil, "preferred": max(profile["soil"], key=profile["soil"].get)})
        else:
            v = conditions.get(key)
            if v is None:
                continue
            lo, hi = profile[key]
            fit = range_fit(v, lo, hi)
            parts.append({"factor": LABELS[key], "fit": round(fit * 100), "value": round(v, 2), "preferred": f"{lo}–{hi}"})
        total += fit * w
        weight += w
    return (round(100 * total / weight, 1) if weight else 0.0), parts


def fertiliser_advice(c: dict) -> list[str]:
    tips = []
    ph, n, p, k, ec = (c.get(x) for x in ("ph", "nitrogen", "phosphorus", "potassium", "ec"))
    if ph is not None and ph < 4.0:
        tips.append("Soil is very acidic (pH below 4.0): apply a light dose of ground magnesium limestone (GML) to bring pH towards 4.5–5.0. Do not over-lime; pineapple prefers acidic soil.")
    elif ph is not None and ph > 5.5:
        tips.append("pH is above 5.5: avoid lime and alkaline fertilisers; ammonium-based nitrogen helps bring pH down over time.")
    if n is not None and n < 40:
        tips.append("Nitrogen is low: increase nitrogen in the split NPK programme (e.g. urea or 15-15-15 applied every 2–3 months).")
    elif n is not None and n > 250:
        tips.append("Nitrogen is high: reduce nitrogen to avoid excessive leaf growth and late flowering.")
    if p is not None and p < 15:
        tips.append("Phosphorus is low: apply rock phosphate or a phosphorus-rich basal fertiliser at planting.")
    if k is not None and k < 100:
        tips.append("Potassium is low: increase potash (muriate or sulphate of potash), important for fruit size and sweetness.")
    if ec is not None and ec > 2.0:
        tips.append("Electrical conductivity is high (above 2 dS/m): salt build-up risk; reduce fertiliser rate and check drainage.")
    if not tips:
        tips.append("Nutrient levels are in the normal range: keep the standard split NPK programme.")
    return tips


def irrigation_advice(c: dict) -> list[str]:
    tips = []
    m, rain = c.get("moisture"), c.get("rainfall")
    if m is not None and m < 20:
        tips.append("Soil moisture is low (below 20%): irrigate, especially in the first 3 months after planting and during fruit development.")
    elif m is not None and m > 60:
        tips.append("Soil is very wet (above 60%): waterlogging risk causes root and heart rot; clear drains and avoid irrigating.")
    if rain is not None and rain < 2.0:
        tips.append("Rainfall is low (under 2 mm/day on average): plan supplementary irrigation.")
    elif rain is not None and rain > 8.0:
        tips.append("Heavy rainfall: maintain drainage channels and watch for fungal disease.")
    if not tips:
        tips.append("Moisture and rainfall are adequate: no extra irrigation needed now.")
    return tips


def timing_advice(c: dict, variety: str) -> list[str]:
    t = c.get("temperature")
    months = "10–12" if variety == "MD2" else "8–10"
    tips = [f"Flowering induction for {variety} is typically {months} months after planting; harvest about 5 months after induction."]
    if t is not None and t > 32:
        tips.append("Temperatures are high: schedule induction so the fruit matures in a cooler period, and protect fruit from sunburn.")
    elif t is not None and t < 22:
        tips.append("Temperatures are low: expect slower growth; induction may need to be delayed.")
    return tips


def confidence_label(score: float) -> str:
    return "high" if score >= 80 else "medium" if score >= 60 else "low"


def plot_conditions(rows: list[CleanedReading]) -> dict:
    """Average recent conditions of a plot from its usable cleaned readings"""
    newest = max(r.reading_date for r in rows)
    recent = [r for r in rows if r.reading_date >= newest - timedelta(days=LOOKBACK_DAYS)]
    cond = {}
    for f in NUMERIC:
        vals = [getattr(r, f) for r in recent if getattr(r, f) is not None]
        cond[f] = round(statistics.fmean(vals), 2) if vals else None
    soils = [r.soil_type for r in recent if r.soil_type]
    cond["soil_type"] = Counter(soils).most_common(1)[0][0] if soils else None
    return {"conditions": cond, "readings": recent, "newest": newest}


def recommend_for_plot(plot: str, rows: list[CleanedReading]) -> dict:
    pc = plot_conditions(rows)
    cond, recent = pc["conditions"], pc["readings"]
    ranked = []
    for name, prof in VARIETIES.items():
        s, parts = score_variety(prof, cond)
        ranked.append({"variety": name, "score": s, "description": prof["description"], "factors": parts})
    ranked.sort(key=lambda v: v["score"], reverse=True)

    quality = statistics.fmean(r.quality_score for r in recent)
    confidence = quality * (1.0 if len(recent) >= MIN_READINGS else 0.85)
    best = ranked[0]["variety"]
    notes = []
    if len(recent) < MIN_READINGS:
        notes.append(f"Only {len(recent)} reading(s) for this plot; add more for a more reliable recommendation.")
    if (date.today() - pc["newest"]).days > 90:
        notes.append("The newest reading is more than 3 months old; take a new soil reading.")
    return {
        "plot_name": plot,
        "recommended_variety": best,
        "varieties": ranked,
        "conditions": cond,
        "fertiliser": fertiliser_advice(cond),
        "irrigation": irrigation_advice(cond),
        "timing": timing_advice(cond, best),
        "confidence": round(confidence, 1),
        "confidence_level": confidence_label(confidence),
        "readings_used": len(recent),
        "latest_reading": pc["newest"],
        "notes": notes,
    }


def usable_by_plot(db: Session) -> dict[str, list[CleanedReading]]:
    groups: dict[str, list[CleanedReading]] = defaultdict(list)
    for r in db.query(CleanedReading).filter(CleanedReading.is_usable.is_(True)).all():
        groups[r.plot_name].append(r)
    return groups


def all_recommendations(db: Session) -> list[dict]:
    return [recommend_for_plot(p, rows) for p, rows in sorted(usable_by_plot(db).items())]


def plot_recommendation(db: Session, plot: str) -> Optional[dict]:
    rows = usable_by_plot(db).get(normalise_plot(plot))
    return recommend_for_plot(normalise_plot(plot), rows) if rows else None


def harvest_outcomes(db: Session) -> list[dict]:
    """
    Proposal §4.4: link each plot's harvest results (grades and rejections from
    the post-harvest module) back to its soil and weather conditions.
    """
    groups = usable_by_plot(db)
    harvests = db.query(Harvest).all()
    by_plot: dict[str, list[Harvest]] = defaultdict(list)
    for h in harvests:
        by_plot[normalise_plot(h.field_name)].append(h)

    out = []
    for plot in sorted(set(groups) | set(by_plot)):
        hs = by_plot.get(plot, [])
        total = sum(h.quantity_kg or 0 for h in hs)
        rejected = sum((h.rejected_kg or 0) + (h.spoilage_kg or 0) for h in hs)
        grades: Counter = Counter()
        for h in hs:
            if h.grades:
                for g in h.grades:
                    grades[g.grade] += g.quantity_kg or 0
            elif (h.quality_grade or "").upper() in ("A", "B", "C", "D"):
                grades[h.quality_grade.upper()] += h.quantity_kg or 0
        graded = sum(grades.values())
        cond = plot_conditions(groups[plot])["conditions"] if plot in groups else None
        out.append({
            "plot_name": plot,
            "batches": len(hs),
            "harvested_kg": round(total, 1),
            "rejected_kg": round(rejected, 1),
            "rejection_rate": round(100 * rejected / total, 1) if total else None,
            "grade_share": {g: round(100 * grades.get(g, 0) / graded, 1) for g in "ABCD"} if graded else {},
            "conditions": cond,
            "has_soil_data": plot in groups,
        })
    return out

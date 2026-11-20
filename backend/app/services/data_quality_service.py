"""
Six-stage data-quality pipeline for soil and weather readings (FYP objective O2).

    1. Profile    - types, missing values, ranges and duplicates of the raw data
    2. Clean      - standardise units, labels and plot names; drop impossible values
    3. Missing    - impute with median, mean or k-nearest-neighbours, or flag the
                    record as unreliable when too much of it is missing
    4. Outliers   - interquartile-range rule; outliers are flagged, never deleted,
                    so rare but valid readings are kept
    5. Normalise  - min-max scale every numeric field to 0..1 for the model
    6. Validate   - apply the domain rules and compute the data-quality indicators
                    (DAMA dimensions) before and after, plus a 0-100 score per record

The pipeline is pure Python (no pandas/numpy) so it runs inside the same small
serverless function as the rest of the API. Everything here works on plain dicts;
`run_pipeline` is the only function that touches the database.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Optional

from sqlalchemy.orm import Session

from app.models import CleanedReading, DataQualityRun, SoilWeatherReading


@dataclass(frozen=True)
class FieldRule:
    label: str
    unit: str
    valid: tuple[float, float]  # physically possible; outside this the value is an error


# Valid ranges are deliberately wide: they reject impossible values only.
# Agronomic suitability (what pineapple prefers) lives in recommendation_service.py.
FIELDS: dict[str, FieldRule] = {
    "ph":              FieldRule("Soil pH", "", (2.0, 10.0)),
    "nitrogen":        FieldRule("Nitrogen (N)", "mg/kg", (0, 5000)),
    "phosphorus":      FieldRule("Phosphorus (P)", "mg/kg", (0, 2000)),
    "potassium":       FieldRule("Potassium (K)", "mg/kg", (0, 5000)),
    "ec":              FieldRule("Electrical conductivity", "dS/m", (0, 20)),
    "moisture":        FieldRule("Soil moisture", "%", (0, 100)),
    "organic_matter":  FieldRule("Organic matter", "%", (0, 100)),
    "temperature":     FieldRule("Temperature", "°C", (5, 45)),
    "rainfall":        FieldRule("Rainfall", "mm/day", (0, 400)),
    "humidity":        FieldRule("Relative humidity", "%", (0, 100)),
    "solar_radiation": FieldRule("Solar radiation", "MJ/m²/day", (0, 40)),
}
NUMERIC = list(FIELDS)
ALL_FIELDS = NUMERIC + ["soil_type"]

SOIL_TYPE_ALIASES = {
    "peat": "peat", "gambut": "peat", "tanah gambut": "peat", "organic": "peat", "histosol": "peat", "peat soil": "peat",
    "mineral": "mineral", "tanah mineral": "mineral", "mineral soil": "mineral", "clay": "mineral", "loam": "mineral",
    "sandy": "mineral", "sand": "mineral", "clay loam": "mineral", "sandy loam": "mineral", "liat": "mineral",
    "pasir": "mineral", "lom": "mineral",
}

IMPUTATION_METHODS = ("median", "mean", "knn")
UNRELIABLE_MISSING_SHARE = 0.5  # more than half the fields missing: flag instead of inventing data
IQR_K = 1.5
KNN_K = 3

# Weights of the DAMA dimensions in the overall score
DIMENSION_WEIGHTS = {
    "completeness": 0.25, "validity": 0.25, "consistency": 0.15,
    "uniqueness": 0.15, "accuracy": 0.10, "timeliness": 0.10,
}


class PipelineError(ValueError):
    pass


# ─── helpers ────────────────────────────────────────────────────────────────

def _num(v: Any) -> Optional[float]:
    """A number, or None for blanks and text such as 'NA' or '-'"""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) if v == v else None  # NaN check
    s = str(v).strip().replace(",", ".")
    if s == "" or s.lower() in {"na", "n/a", "nan", "null", "none", "-", "--"}:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def normalise_plot(name: Any) -> str:
    """'  block a ' and 'Block  A' are the same plot"""
    return " ".join(str(name or "").split()).title()


def normalise_soil_type(v: Any) -> Optional[str]:
    if v is None:
        return None
    return SOIL_TYPE_ALIASES.get(" ".join(str(v).lower().split()))


def timeliness_factor(reading_date: date, today: date) -> float:
    age = (today - reading_date).days
    if age <= 30:
        return 1.0
    if age <= 90:
        return 0.75
    if age <= 365:
        return 0.5
    return 0.25


def _pct(part: float, whole: float) -> float:
    return round(100.0 * part / whole, 1) if whole else 100.0


def overall_score(metrics: dict[str, float]) -> float:
    return round(sum(metrics[d] * w for d, w in DIMENSION_WEIGHTS.items()), 1)


def quartiles(values: list[float]) -> tuple[float, float]:
    if len(values) < 4:
        return (min(values), max(values)) if values else (0.0, 0.0)
    q = statistics.quantiles(values, n=4, method="inclusive")
    return q[0], q[2]


# ─── stage 1: profile ───────────────────────────────────────────────────────

def profile(rows: list[dict]) -> dict:
    """Shape of the raw data: per-field missing count, range, mean and invalid count"""
    fields = {}
    for f in NUMERIC:
        rule = FIELDS[f]
        raw = [r.get(f) for r in rows]
        nums = [n for n in (_num(v) for v in raw) if n is not None]
        unreadable = sum(1 for v in raw if v not in (None, "") and _num(v) is None)
        fields[f] = {
            "label": rule.label, "unit": rule.unit,
            "present": len(nums), "missing": len(rows) - len(nums), "unreadable": unreadable,
            "min": round(min(nums), 3) if nums else None,
            "max": round(max(nums), 3) if nums else None,
            "mean": round(statistics.fmean(nums), 3) if nums else None,
            "out_of_range": sum(1 for n in nums if not rule.valid[0] <= n <= rule.valid[1]),
        }
    soil = [r.get("soil_type") for r in rows]
    fields["soil_type"] = {
        "label": "Soil type", "unit": "",
        "present": sum(1 for s in soil if s not in (None, "")),
        "missing": sum(1 for s in soil if s in (None, "")),
        "unrecognised": sum(1 for s in soil if s not in (None, "") and normalise_soil_type(s) is None),
        "values": sorted({str(s) for s in soil if s not in (None, "")})[:20],
    }
    return {
        "records": len(rows),
        "plots": len({normalise_plot(r.get("plot_name")) for r in rows}),
        "duplicates": len(find_duplicates(rows)),
        "fields": fields,
    }


def _dup_key(r: dict) -> tuple:
    return (normalise_plot(r.get("plot_name")).lower(), str(r.get("reading_date")),
            *(_num(r.get(f)) for f in NUMERIC), normalise_soil_type(r.get("soil_type")))


def find_duplicates(rows: list[dict]) -> set[int]:
    """Indexes of rows that repeat an earlier row (same plot, date and values)"""
    seen, dups = set(), set()
    for i, r in enumerate(rows):
        k = _dup_key(r)
        if k in seen:
            dups.add(i)
        seen.add(k)
    return dups


# ─── quality indicators (stage 6, also used on the raw data) ────────────────

def raw_metrics(rows: list[dict], today: date) -> dict[str, float]:
    """DAMA indicators of the data as it arrived"""
    if not rows:
        return {d: 0.0 for d in DIMENSION_WEIGHTS}
    cells = len(rows) * len(ALL_FIELDS)
    present = valid = inconsistent = 0
    numeric_valid: dict[str, list[float]] = {f: [] for f in NUMERIC}
    for r in rows:
        for f in NUMERIC:
            n = _num(r.get(f))
            if n is None:
                continue
            present += 1
            lo, hi = FIELDS[f].valid
            if lo <= n <= hi:
                valid += 1
                numeric_valid[f].append(n)
            if _needs_unit_fix(f, n):
                inconsistent += 1
        s = r.get("soil_type")
        if s not in (None, ""):
            present += 1
            canon = normalise_soil_type(s)
            if canon:
                valid += 1
                if str(s).strip().lower() != canon:
                    inconsistent += 1
        if str(r.get("plot_name") or "") != normalise_plot(r.get("plot_name")):
            inconsistent += 1
    outliers = sum(len(_outlier_idx(vals)) for vals in numeric_valid.values())
    n_valid_numeric = sum(len(v) for v in numeric_valid.values())
    metrics = {
        "completeness": _pct(present, cells),
        "validity": _pct(valid, present),
        "consistency": _pct(present - inconsistent, present),
        "uniqueness": _pct(len(rows) - len(find_duplicates(rows)), len(rows)),
        "accuracy": _pct(n_valid_numeric - outliers, n_valid_numeric),
        "timeliness": round(100 * statistics.fmean(_tf(r, today) for r in rows), 1),
    }
    metrics["overall"] = overall_score(metrics)
    return metrics


def _tf(r: dict, today: date) -> float:
    d = r.get("reading_date")
    return timeliness_factor(d, today) if isinstance(d, date) else 0.25


def _needs_unit_fix(field: str, n: float) -> bool:
    return (field == "temperature" and 50 < n <= 120) or (field in ("moisture", "humidity") and 0 < n <= 1)


def _outlier_idx(values: list[float]) -> set[int]:
    if len(values) < 4:
        return set()
    q1, q3 = quartiles(values)
    iqr = q3 - q1
    lo, hi = q1 - IQR_K * iqr, q3 + IQR_K * iqr
    return {i for i, v in enumerate(values) if v < lo or v > hi}


# ─── stages 2-6 ─────────────────────────────────────────────────────────────

def clean_record(r: dict) -> tuple[dict, list[dict], int]:
    """
    Stage 2. Returns the cleaned values, flags, and how many values were
    originally present (for the unreliable-record check).
    """
    out: dict[str, Any] = {"plot_name": normalise_plot(r.get("plot_name")), "reading_date": r.get("reading_date")}
    flags: list[dict] = []
    present = 0
    for f in NUMERIC:
        raw = r.get(f)
        n = _num(raw)
        if raw not in (None, "") and n is None:
            flags.append({"field": f, "type": "unreadable", "detail": f"'{raw}' is not a number; treated as missing"})
        if n is not None:
            present += 1
            if f == "temperature" and 50 < n <= 120:
                c = round((n - 32) * 5 / 9, 2)
                flags.append({"field": f, "type": "corrected", "detail": f"{n} looks like °F; converted to {c} °C"})
                n = c
            elif f in ("moisture", "humidity") and 0 < n <= 1:
                flags.append({"field": f, "type": "corrected", "detail": f"{n} looks like a fraction; converted to {n * 100:g} %"})
                n = round(n * 100, 3)
            lo, hi = FIELDS[f].valid
            if not lo <= n <= hi:
                flags.append({"field": f, "type": "invalid",
                              "detail": f"{n} is outside the possible range {lo}–{hi} {FIELDS[f].unit}".strip()})
                n = None
        out[f] = n
    s = r.get("soil_type")
    canon = normalise_soil_type(s)
    if s not in (None, ""):
        present += 1
        if canon is None:
            flags.append({"field": "soil_type", "type": "invalid", "detail": f"Unknown soil type '{s}'"})
        elif str(s).strip().lower() != canon:
            flags.append({"field": "soil_type", "type": "corrected", "detail": f"'{s}' standardised to '{canon}'"})
    out["soil_type"] = canon
    return out, flags, present


def _impute_value(field: str, rec: dict, pool: list[dict], method: str, scale: dict) -> Optional[float]:
    """Stage 3 for one value. pool = usable cleaned records, preferably the same plot first."""
    same_plot = [p[field] for p in pool if p[field] is not None and p["plot_name"] == rec["plot_name"] and p is not rec]
    everywhere = [p[field] for p in pool if p[field] is not None and p is not rec]
    if method == "knn":
        candidates = [p for p in pool if p is not rec and p[field] is not None]
        shared = [f for f in NUMERIC if f != field and rec[f] is not None]
        if candidates and shared:
            def dist(p):
                d, k = 0.0, 0
                for f in shared:
                    if p[f] is None:
                        continue
                    lo, hi = scale[f]
                    span = (hi - lo) or 1.0
                    d += ((rec[f] - p[f]) / span) ** 2
                    k += 1
                return (d / k) ** 0.5 if k else float("inf")
            nearest = sorted(candidates, key=dist)[:KNN_K]
            return round(statistics.fmean(p[field] for p in nearest), 3)
        method = "median"  # nothing to compare with: fall back
    values = same_plot or everywhere
    if not values:
        return None
    return round(statistics.median(values) if method == "median" else statistics.fmean(values), 3)


def record_score(present: int, flags: list[dict], reading_date: Any, today: date) -> float:
    """0-100 quality of one record: completeness 40, validity 30, plausibility 20, timeliness 10"""
    total = len(ALL_FIELDS)
    invalid = sum(1 for f in flags if f["type"] in ("invalid", "unreadable"))
    outliers = sum(1 for f in flags if f["type"] == "outlier")
    completeness = present / total
    validity = 1 - (invalid / present) if present else 0
    plausibility = 1 - (outliers / max(present, 1))
    timeliness = timeliness_factor(reading_date, today) if isinstance(reading_date, date) else 0.25
    return round(100 * (0.4 * completeness + 0.3 * max(validity, 0) + 0.2 * max(plausibility, 0) + 0.1 * timeliness), 1)


def process(rows: list[dict], method: str = "median", today: Optional[date] = None) -> dict:
    """
    Run stages 1-6 on raw rows (dicts with the SoilWeatherReading columns, plus 'id').
    Pure function: returns everything run_pipeline stores.
    """
    if method not in IMPUTATION_METHODS:
        raise PipelineError(f"Unknown imputation method '{method}'. Use one of: {', '.join(IMPUTATION_METHODS)}")
    today = today or date.today()
    log: list[str] = []

    # 1. Profile
    prof = profile(rows)
    before = raw_metrics(rows, today)
    log.append(f"Profiled {len(rows)} records across {prof['plots']} plots; raw quality score {before['overall']}.")

    # 2. Clean (+ uniqueness)
    dups = find_duplicates(rows)
    recs: list[dict] = []
    corrections = invalid = 0
    for i, r in enumerate(rows):
        c, flags, present = clean_record(r)
        corrections += sum(1 for f in flags if f["type"] == "corrected")
        invalid += sum(1 for f in flags if f["type"] in ("invalid", "unreadable"))
        c.update(id=r.get("id"), _flags=flags, _present=present, _usable=True)
        if i in dups:
            c["_usable"] = False
            flags.append({"field": None, "type": "duplicate", "detail": "Same plot, date and values as an earlier record"})
        elif present / len(ALL_FIELDS) < (1 - UNRELIABLE_MISSING_SHARE):
            c["_usable"] = False
            flags.append({"field": None, "type": "unreliable",
                          "detail": f"Only {present} of {len(ALL_FIELDS)} fields recorded; not imputed and not used for recommendations"})
        recs.append(c)
    usable = [c for c in recs if c["_usable"]]
    log.append(f"Cleaning: {corrections} unit/label corrections, {invalid} impossible or unreadable values removed, "
               f"{len(dups)} duplicates set aside, {len(recs) - len(usable) - len(dups)} records flagged unreliable.")

    # 3. Missing values
    scale = {}
    for f in NUMERIC:
        vals = [c[f] for c in usable if c[f] is not None]
        scale[f] = (min(vals), max(vals)) if vals else (0.0, 1.0)
    imputed = 0
    fills: list[tuple[dict, str, float]] = []
    for c in usable:
        for f in NUMERIC:
            if c[f] is None:
                v = _impute_value(f, c, usable, method, scale)
                if v is not None:
                    fills.append((c, f, v))
    for c, f, v in fills:  # applied after, so imputed values never feed other imputations
        c[f] = v
        c["_flags"].append({"field": f, "type": "imputed", "detail": f"Missing; filled with {method} = {v}"})
        imputed += 1
    for c in usable:
        if c["soil_type"] is None:
            plot_types = [p["soil_type"] for p in usable if p["plot_name"] == c["plot_name"] and p["soil_type"]]
            if plot_types:
                c["soil_type"] = statistics.mode(plot_types)
                c["_flags"].append({"field": "soil_type", "type": "imputed",
                                    "detail": f"Missing; filled with the plot's usual type '{c['soil_type']}'"})
                imputed += 1
    log.append(f"Missing values: {imputed} values imputed using {method}"
               f"{' (k=' + str(KNN_K) + ')' if method == 'knn' else ''}, same plot first, then all plots.")

    # 4. Outliers (flag only)
    outliers = 0
    for f in NUMERIC:
        vals = [(c, c[f]) for c in usable if c[f] is not None]
        idx = _outlier_idx([v for _, v in vals])
        if idx:
            q1, q3 = quartiles([v for _, v in vals])
            iqr = q3 - q1
            for i in idx:
                c, v = vals[i]
                c["_flags"].append({"field": f, "type": "outlier",
                                    "detail": f"{v} is outside the IQR fence {q1 - IQR_K * iqr:.2f}–{q3 + IQR_K * iqr:.2f}; kept, please check"})
                outliers += 1
    log.append(f"Outliers: {outliers} values flagged with the IQR rule (k={IQR_K}) and kept for review.")

    # 5. Normalise
    for f in NUMERIC:
        vals = [c[f] for c in usable if c[f] is not None]
        scale[f] = (min(vals), max(vals)) if vals else (0.0, 1.0)
    for c in recs:
        norm = {}
        for f in NUMERIC:
            if c[f] is not None and c["_usable"]:
                lo, hi = scale[f]
                norm[f] = round((c[f] - lo) / (hi - lo), 4) if hi > lo else 0.0
        c["_normalised"] = norm
    log.append("Normalisation: min-max scaling to 0–1 of every numeric field over the usable records.")

    # 6. Validate and score
    for c in recs:
        c["_score"] = record_score(c["_present"], c["_flags"], c["reading_date"], today)
        if not c["_usable"]:
            c["_score"] = min(c["_score"], 40.0)
    after = cleaned_metrics(usable, today) if usable else {d: 0.0 for d in DIMENSION_WEIGHTS} | {"overall": 0.0}
    log.append(f"Validation: quality score {before['overall']} → {after['overall']} "
               f"on {len(usable)} usable records.")

    return {
        "profile": prof, "before": before, "after": after, "records": recs, "log": log,
        "counts": {
            "records_processed": len(rows), "duplicates_removed": len(dups), "values_imputed": imputed,
            "outliers_flagged": outliers, "invalid_values": invalid, "corrections_made": corrections,
        },
    }


def cleaned_metrics(usable: list[dict], today: date) -> dict[str, float]:
    """DAMA indicators of the cleaned, usable records"""
    cells = len(usable) * len(ALL_FIELDS)
    present = sum(1 for c in usable for f in ALL_FIELDS if c[f] is not None)
    n_values = sum(1 for c in usable for f in NUMERIC if c[f] is not None)
    outliers = sum(1 for c in usable for fl in c["_flags"] if fl["type"] == "outlier")
    metrics = {
        "completeness": _pct(present, cells),
        "validity": 100.0,      # impossible values were removed in stage 2
        "consistency": 100.0,   # units, labels and plot names are standardised
        "uniqueness": 100.0,    # duplicates are set aside
        "accuracy": _pct(n_values - outliers, n_values),
        "timeliness": round(100 * statistics.fmean(timeliness_factor(c["reading_date"], today) for c in usable), 1),
    }
    metrics["overall"] = overall_score(metrics)
    return metrics


# ─── database ───────────────────────────────────────────────────────────────

def reading_to_dict(r: SoilWeatherReading) -> dict:
    d = {f: getattr(r, f) for f in ALL_FIELDS}
    d.update(id=r.id, plot_name=r.plot_name, reading_date=r.reading_date)
    return d


def run_pipeline(db: Session, user_id: Optional[int], method: str = "median") -> DataQualityRun:
    """Process every raw reading and replace the cleaned table with the result"""
    readings = db.query(SoilWeatherReading).order_by(SoilWeatherReading.id).all()
    if not readings:
        raise PipelineError("There are no soil or weather readings to process yet.")
    result = process([reading_to_dict(r) for r in readings], method)

    run = DataQualityRun(
        user_id=user_id, imputation_method=method, **result["counts"],
        score_before=result["before"]["overall"], score_after=result["after"]["overall"],
        metrics_before_json=json.dumps(result["before"]), metrics_after_json=json.dumps(result["after"]),
        profile_json=json.dumps(result["profile"]), log_json=json.dumps(result["log"]),
    )
    db.add(run)
    db.query(CleanedReading).delete()
    db.flush()
    for c in result["records"]:
        db.add(CleanedReading(
            reading_id=c["id"], run_id=run.id, plot_name=c["plot_name"], reading_date=c["reading_date"],
            soil_type=c["soil_type"], **{f: c[f] for f in NUMERIC},
            normalised_json=json.dumps(c["_normalised"]), flags_json=json.dumps(c["_flags"]),
            quality_score=c["_score"], is_usable=c["_usable"],
        ))
    db.commit()
    db.refresh(run)
    return run


def run_to_dict(run: DataQualityRun) -> dict:
    return {
        "id": run.id, "created_at": run.created_at, "imputation_method": run.imputation_method,
        "records_processed": run.records_processed, "duplicates_removed": run.duplicates_removed,
        "values_imputed": run.values_imputed, "outliers_flagged": run.outliers_flagged,
        "invalid_values": run.invalid_values, "corrections_made": run.corrections_made,
        "score_before": run.score_before, "score_after": run.score_after,
        "metrics_before": json.loads(run.metrics_before_json), "metrics_after": json.loads(run.metrics_after_json),
        "profile": json.loads(run.profile_json), "log": json.loads(run.log_json),
    }


def iter_csv_rows(text: str) -> Iterable[dict]:
    """CSV import: header names are matched loosely (case, spaces, common synonyms)"""
    import csv
    import io

    synonyms = {
        "plot": "plot_name", "plot_name": "plot_name", "field": "plot_name", "field_name": "plot_name", "block": "plot_name",
        "date": "reading_date", "reading_date": "reading_date",
        "ph": "ph", "soil_ph": "ph", "n": "nitrogen", "nitrogen": "nitrogen", "p": "phosphorus", "phosphorus": "phosphorus",
        "k": "potassium", "potassium": "potassium", "ec": "ec", "moisture": "moisture", "soil_moisture": "moisture",
        "organic_matter": "organic_matter", "om": "organic_matter", "soil_type": "soil_type", "soil": "soil_type",
        "temperature": "temperature", "temp": "temperature", "rainfall": "rainfall", "rain": "rainfall",
        "humidity": "humidity", "rh": "humidity", "solar_radiation": "solar_radiation", "solar": "solar_radiation",
        "notes": "notes",
    }
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    for raw in reader:
        row = {}
        for k, v in raw.items():
            if k is None:
                continue
            key = synonyms.get("_".join(k.strip().lower().replace("(", " ").replace(")", " ").split()).split("_mg")[0])
            if key:
                row[key] = v.strip() if isinstance(v, str) else v
        yield row

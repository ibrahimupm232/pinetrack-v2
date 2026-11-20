"""
Smart Cultivation API: soil & weather data (O1), data-quality pipeline (O2),
quality evaluation (O3) and plot recommendations.

Workers record readings from their phones and see recommendations; the data
quality pipeline, imports and evaluation are admin only.
"""

import json
import statistics
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_db
from app.middleware.rbac import require_admin, require_worker
from app.models import CleanedReading, DataQualityRun, Harvest, SoilWeatherReading
from app.services import data_quality_service as dq
from app.services import recommendation_service as rec

router = APIRouter()


class ReadingIn(BaseModel):
    """
    Values are stored exactly as entered; checking them is the pipeline's job,
    so only the plot and date are required here.
    """
    plot_name: str = Field(..., min_length=1, max_length=100)
    reading_date: date
    source: Literal["manual", "csv", "sensor", "agency"] = "manual"
    ph: Optional[float] = None
    nitrogen: Optional[float] = None
    phosphorus: Optional[float] = None
    potassium: Optional[float] = None
    ec: Optional[float] = None
    moisture: Optional[float] = None
    organic_matter: Optional[float] = None
    soil_type: Optional[str] = Field(None, max_length=30)
    temperature: Optional[float] = None
    rainfall: Optional[float] = None
    humidity: Optional[float] = None
    solar_radiation: Optional[float] = None
    notes: Optional[str] = Field(None, max_length=1000)


class ImportIn(BaseModel):
    csv_text: str = Field(..., min_length=1, max_length=5_000_000)
    source: Literal["csv", "sensor", "agency"] = "csv"


class RunIn(BaseModel):
    method: Literal["median", "mean", "knn"] = "median"


def _reading_out(r: SoilWeatherReading) -> dict:
    d = {f: getattr(r, f) for f in dq.ALL_FIELDS}
    d.update(id=r.id, plot_name=r.plot_name, reading_date=r.reading_date, source=r.source, notes=r.notes,
             user_id=r.user_id, recorded_by=(r.user.full_name or r.user.username) if r.user else None,
             created_at=r.created_at)
    c = r.cleaned
    d["quality"] = None if c is None else {
        "score": c.quality_score, "usable": c.is_usable, "flags": json.loads(c.flags_json),
        "cleaned": {f: getattr(c, f) for f in dq.ALL_FIELDS},
    }
    return d


def _make_reading(data: dict, user_id: int) -> SoilWeatherReading:
    return SoilWeatherReading(user_id=user_id, **data)


# ─── O1: data acquisition ───────────────────────────────────────────────────

@router.get("/fields")
def field_reference(current_user: dict = Depends(require_worker)):
    """Field labels, units and possible ranges, so forms and imports describe the same data"""
    return {
        "fields": [{"key": k, "label": r.label, "unit": r.unit, "valid_min": r.valid[0], "valid_max": r.valid[1]}
                   for k, r in dq.FIELDS.items()],
        "soil_types": ["peat", "mineral"],
    }


@router.get("/plots")
def list_plots(current_user: dict = Depends(require_worker), db: Session = Depends(get_db)):
    """Known plots: from readings and from harvest field names, so both modules share plot names"""
    names = {dq.normalise_plot(p) for (p,) in db.query(SoilWeatherReading.plot_name).distinct()}
    names |= {dq.normalise_plot(p) for (p,) in db.query(Harvest.field_name).distinct()}
    return sorted(n for n in names if n)


@router.post("/readings", status_code=status.HTTP_201_CREATED)
def create_reading(data: ReadingIn, current_user: dict = Depends(require_worker), db: Session = Depends(get_db)):
    r = _make_reading(data.model_dump(), current_user["user_id"])
    r.plot_name = dq.normalise_plot(r.plot_name)
    db.add(r)
    db.commit()
    db.refresh(r)
    return _reading_out(r)


@router.get("/readings")
def list_readings(
    plot: Optional[str] = None,
    mine: bool = False,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    current_user: dict = Depends(require_worker),
    db: Session = Depends(get_db),
):
    """Admins see every reading; workers see their own"""
    q = db.query(SoilWeatherReading)
    if mine or current_user["role"] != "admin":
        q = q.filter(SoilWeatherReading.user_id == current_user["user_id"])
    if plot:
        q = q.filter(SoilWeatherReading.plot_name == dq.normalise_plot(plot))
    total = q.count()
    rows = q.order_by(SoilWeatherReading.reading_date.desc(), SoilWeatherReading.id.desc()).offset(skip).limit(limit).all()
    return {"items": [_reading_out(r) for r in rows], "total": total}


@router.delete("/readings/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reading(reading_id: int, current_user: dict = Depends(require_worker), db: Session = Depends(get_db)):
    r = db.get(SoilWeatherReading, reading_id)
    if not r:
        raise HTTPException(status_code=404, detail="Reading not found")
    if current_user["role"] != "admin" and r.user_id != current_user["user_id"]:
        raise HTTPException(status_code=403, detail="You can only delete your own readings")
    db.delete(r)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/import/template", response_class=Response)
def import_template(current_user: dict = Depends(require_admin)):
    header = "plot_name,reading_date," + ",".join(dq.ALL_FIELDS)
    example = "Block A,2026-11-01,4.8,45,18,140,0.6,32,55,peat,29.5,4.2,82,17"
    return Response(content=f"{header}\n{example}\n", media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="soil_weather_template.csv"'})


@router.post("/import")
def import_csv(data: ImportIn, current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Bulk import from sensor logs or agency records. Values are stored as they are;
    rows without a plot or a readable date are skipped and reported.
    """
    imported, skipped, unreadable = 0, [], 0
    for line, row in enumerate(dq.iter_csv_rows(data.csv_text), start=2):
        plot = dq.normalise_plot(row.get("plot_name"))
        try:
            when = date.fromisoformat(str(row.get("reading_date", "")).strip()[:10])
        except ValueError:
            when = None
        if not plot or not when:
            skipped.append({"line": line, "reason": "missing plot name" if not plot else "date must be YYYY-MM-DD"})
            continue
        values = {}
        for f in dq.NUMERIC:
            raw = row.get(f)
            n = dq._num(raw)
            if raw not in (None, "") and n is None:
                unreadable += 1
            values[f] = n
        db.add(SoilWeatherReading(
            user_id=current_user["user_id"], plot_name=plot, reading_date=when, source=data.source,
            soil_type=(row.get("soil_type") or None), notes=row.get("notes") or None, **values,
        ))
        imported += 1
    if not imported and not skipped:
        raise HTTPException(status_code=400, detail="The file has no data rows")
    db.commit()
    return {"imported": imported, "skipped": skipped, "unreadable_values": unreadable}


# ─── O2: data-quality pipeline ──────────────────────────────────────────────

@router.post("/quality/run")
def run_quality(data: RunIn, current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Run the six-stage pipeline on every raw reading"""
    try:
        run = dq.run_pipeline(db, current_user["user_id"], data.method)
    except dq.PipelineError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return dq.run_to_dict(run)


@router.get("/quality/runs")
def list_runs(limit: int = Query(20, ge=1, le=100), current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    runs = db.query(DataQualityRun).order_by(DataQualityRun.id.desc()).limit(limit).all()
    return [{k: v for k, v in dq.run_to_dict(r).items() if k not in ("profile", "log")} for r in runs]


@router.get("/quality/latest")
def latest_run(current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    run = db.query(DataQualityRun).order_by(DataQualityRun.id.desc()).first()
    pending = db.query(SoilWeatherReading).outerjoin(CleanedReading).filter(CleanedReading.id.is_(None)).count()
    return {"run": dq.run_to_dict(run) if run else None, "unprocessed_readings": pending,
            "total_readings": db.query(SoilWeatherReading).count()}


@router.get("/quality/plots")
def plot_quality(current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Average quality score per plot after the latest run"""
    groups: dict[str, list[CleanedReading]] = {}
    for c in db.query(CleanedReading).all():
        groups.setdefault(c.plot_name, []).append(c)
    out = []
    for plot, rows in sorted(groups.items()):
        flags = [f for r in rows for f in json.loads(r.flags_json)]
        out.append({
            "plot_name": plot, "readings": len(rows), "usable": sum(r.is_usable for r in rows),
            "avg_score": round(statistics.fmean(r.quality_score for r in rows), 1),
            "imputed": sum(f["type"] == "imputed" for f in flags),
            "outliers": sum(f["type"] == "outlier" for f in flags),
            "invalid": sum(f["type"] in ("invalid", "unreadable") for f in flags),
        })
    return out


@router.get("/quality/issues")
def quality_issues(
    type: Optional[Literal["invalid", "unreadable", "corrected", "imputed", "outlier", "duplicate", "unreliable"]] = None,
    limit: int = Query(200, ge=1, le=1000),
    current_user: dict = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Every flag the pipeline raised, newest readings first: the documented processing decisions"""
    out = []
    rows = db.query(CleanedReading).order_by(CleanedReading.reading_date.desc(), CleanedReading.id.desc()).all()
    for c in rows:
        for f in json.loads(c.flags_json):
            if type and f["type"] != type:
                continue
            out.append({"reading_id": c.reading_id, "plot_name": c.plot_name, "reading_date": c.reading_date, **f})
            if len(out) >= limit:
                return out
    return out


@router.get("/quality/report", response_class=Response)
def quality_report(current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Data-quality report as CSV: one row per reading with its cleaned values, score and flags"""
    import csv
    import io
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["reading_id", "plot_name", "reading_date", *dq.ALL_FIELDS, "quality_score", "usable", "flags"])
    for c in db.query(CleanedReading).order_by(CleanedReading.plot_name, CleanedReading.reading_date).all():
        flags = "; ".join(f"{f['type']}: {f['detail']}" for f in json.loads(c.flags_json))
        w.writerow([c.reading_id, c.plot_name, c.reading_date, *(getattr(c, f) for f in dq.ALL_FIELDS),
                    c.quality_score, "yes" if c.is_usable else "no", flags])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="data_quality_report.csv"'})


# ─── O3: evaluation ─────────────────────────────────────────────────────────

@router.get("/quality/impact")
def recommendation_impact(current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """
    Raw versus cleaned: the recommendation each plot would get from its raw
    readings as entered, next to the one from the cleaned data.
    """
    raw_groups: dict[str, list[SoilWeatherReading]] = {}
    for r in db.query(SoilWeatherReading).all():
        raw_groups.setdefault(dq.normalise_plot(r.plot_name), []).append(r)
    clean_groups = rec.usable_by_plot(db)
    out = []
    for plot, rows in sorted(raw_groups.items()):
        raw_cond = {}
        for f in ("ph", "temperature", "rainfall", "moisture"):
            vals = [getattr(r, f) for r in rows if getattr(r, f) is not None]
            raw_cond[f] = statistics.fmean(vals) if vals else None
        soils = [r.soil_type.strip().lower() for r in rows if r.soil_type]
        raw_cond["soil_type"] = max(set(soils), key=soils.count) if soils else None  # unstandardised, as entered
        raw_rank = sorted(((rec.score_variety(p, raw_cond)[0], v) for v, p in rec.VARIETIES.items()), reverse=True)
        cleaned = rec.recommend_for_plot(plot, clean_groups[plot]) if plot in clean_groups else None
        out.append({
            "plot_name": plot,
            "raw_variety": raw_rank[0][1], "raw_score": raw_rank[0][0],
            "raw_conditions": {k: (round(v, 2) if isinstance(v, float) else v) for k, v in raw_cond.items()},
            "clean_variety": cleaned["recommended_variety"] if cleaned else None,
            "clean_score": cleaned["varieties"][0]["score"] if cleaned else None,
            "clean_conditions": {k: cleaned["conditions"].get(k) for k in raw_cond} if cleaned else None,
            "changed": bool(cleaned) and cleaned["recommended_variety"] != raw_rank[0][1],
        })
    return {"plots": out, "changed": sum(p["changed"] for p in out)}


# ─── recommendations ────────────────────────────────────────────────────────

@router.get("/recommendations")
def recommendations(current_user: dict = Depends(require_worker), db: Session = Depends(get_db)):
    return rec.all_recommendations(db)


@router.get("/recommendations/{plot}")
def recommendation_for_plot(plot: str, current_user: dict = Depends(require_worker), db: Session = Depends(get_db)):
    result = rec.plot_recommendation(db, plot)
    if not result:
        raise HTTPException(status_code=404, detail="No processed readings for this plot yet")
    return result


@router.get("/outcomes")
def outcomes(current_user: dict = Depends(require_admin), db: Session = Depends(get_db)):
    """Harvest grades and rejections per plot next to the plot's soil and weather conditions"""
    return rec.harvest_outcomes(db)

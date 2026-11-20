"""
Demo soil and weather readings for the Smart Cultivation module.

Run from the backend folder (after seed.py has created the accounts):
    python seed_soil.py            # add demo readings if there are none yet
    python seed_soil.py --reset    # replace all soil readings and data-quality runs
    python seed_soil.py --run      # also run the data-quality pipeline afterwards

The plots match the post-harvest demo batches (Block A-1 ... Block C-1), so the
harvest outcomes link up. The data is realistic but deliberately imperfect, the
way real field data is: some temperatures logged in °F, moisture as a fraction,
Malay soil labels ('Gambut'), missing values, a duplicated row, a pH typed as 48
instead of 4.8, an extreme potassium reading and a nearly empty record. That gives
the data-quality pipeline real work to show. Nothing else in the database is changed.
"""

import random
import sys
from datetime import date, timedelta

from app.config import Base, SessionLocal, engine
from app import models  # noqa: F401
from app.models import CleanedReading, DataQualityRun, SoilWeatherReading, User
from app.services.data_quality_service import run_pipeline

# plot: (soil type label as typed, base pH, base moisture, base N, base K, organic matter)
PLOTS = {
    "Block A-1": ("peat", 4.1, 48, 55, 140, 62),
    "Block A-2": ("Gambut", 3.9, 52, 60, 120, 68),
    "Block A-3": ("peat", 4.2, 45, 38, 95, 58),
    "Block B-1": ("mineral", 5.1, 30, 45, 170, 4),
    "Block B-2": ("Clay loam", 5.3, 27, 70, 160, 3),
    "Block C-1": ("peat", 4.6, 40, 50, 130, 35),
}
WORKERS = ["arif", "hazriq", "ibrahim"]


def build_rows(today: date) -> list[dict]:
    rnd = random.Random(42)
    rows = []
    for plot, (soil, ph, moist, n, k, om) in PLOTS.items():
        for i in range(6):  # one reading roughly every 3 weeks
            day = today - timedelta(days=5 + i * 21 + rnd.randint(0, 4))
            rows.append({
                "plot_name": plot, "reading_date": day, "source": "manual" if i % 2 else "sensor",
                "soil_type": soil,
                "ph": round(ph + rnd.uniform(-0.2, 0.2), 2),
                "nitrogen": round(n + rnd.uniform(-8, 8), 1),
                "phosphorus": round(18 + rnd.uniform(-5, 5), 1),
                "potassium": round(k + rnd.uniform(-15, 15), 1),
                "ec": round(0.6 + rnd.uniform(-0.2, 0.3), 2),
                "moisture": round(moist + rnd.uniform(-5, 5), 1),
                "organic_matter": round(om + rnd.uniform(-3, 3), 1),
                "temperature": round(28.5 + rnd.uniform(-2, 3), 1),
                "rainfall": round(rnd.uniform(1.5, 9), 1),
                "humidity": round(rnd.uniform(72, 90), 1),
                "solar_radiation": round(rnd.uniform(14, 20), 1),
            })

    # ── Deliberate data-quality problems ──
    rows[1]["temperature"] = 86.0           # logged in °F
    rows[8]["temperature"] = 84.2           # °F
    rows[13]["moisture"] = 0.29             # fraction instead of %
    rows[20]["humidity"] = 0.81             # fraction
    rows[3]["ph"] = None                    # missing values
    rows[9]["nitrogen"] = None
    rows[9]["phosphorus"] = None
    rows[15]["moisture"] = None
    rows[27]["rainfall"] = None
    rows[30]["ph"] = 48.0                   # typo for 4.8: impossible pH
    rows[22]["rainfall"] = -2.0             # negative rainfall: sensor error
    rows[25]["potassium"] = 1450.0          # extreme reading: outlier, kept for review
    rows[4]["soil_type"] = "tanah gambut"   # inconsistent labels
    rows[33]["soil_type"] = None
    rows[11]["plot_name"] = "  block a-2"   # inconsistent plot name
    rows.append(dict(rows[6]))              # duplicate entry
    rows.append({"plot_name": "Block C-1", "reading_date": today - timedelta(days=2), "source": "manual",
                 "ph": 4.5})                # nearly empty record
    return rows


def seed_soil(reset: bool = False, run: bool = False) -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if reset:
            db.query(CleanedReading).delete()
            db.query(DataQualityRun).delete()
            db.query(SoilWeatherReading).delete()
            db.commit()
            print("Removed existing soil readings and data-quality runs.")
        elif db.query(SoilWeatherReading).count():
            print("Soil readings already present - skipped. Use --reset to replace them.")
            return

        users = {u.username: u.id for u in db.query(User).all()}
        admin_id = users.get("admin")
        rows = build_rows(date.today())
        for i, r in enumerate(rows):
            uid = admin_id if r["source"] == "sensor" else users.get(WORKERS[i % len(WORKERS)], admin_id)
            db.add(SoilWeatherReading(user_id=uid, **r))
        db.commit()
        print(f"Added {len(rows)} soil and weather readings across {len(PLOTS)} plots.")

        if run:
            result = run_pipeline(db, admin_id, "median")
            print(f"Data-quality run #{result.id}: score {result.score_before} -> {result.score_after}")
    finally:
        db.close()


if __name__ == "__main__":
    seed_soil(reset="--reset" in sys.argv, run="--run" in sys.argv)

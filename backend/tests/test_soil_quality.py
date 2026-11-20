"""
Tests for Smart Cultivation: soil & weather data, the six-stage data-quality
pipeline and plot recommendations.
"""

from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

from app.config import Base, SessionLocal, engine, get_db, is_sqlite
from app.main import app
from app.models import Harvest, User
from app.services import data_quality_service as dq
from app.services import recommendation_service as rec
from app.services.auth_service import create_access_token

TODAY = date.today()


def row(i, plot="Block A", days_ago=5, **values):
    base = dict(id=i, plot_name=plot, reading_date=TODAY - timedelta(days=days_ago), ph=4.8, nitrogen=50,
                phosphorus=20, potassium=150, ec=0.5, moisture=35, organic_matter=40, soil_type="peat",
                temperature=29, rainfall=4, humidity=80, solar_radiation=17)
    base.update(values)
    return base


# ─── pipeline (pure functions) ──────────────────────────────────────────────

def test_clean_converts_fahrenheit_and_fractions():
    c, flags, _ = dq.clean_record(row(1, temperature=86, moisture=0.35, soil_type="Tanah Gambut"))
    assert c["temperature"] == 30.0
    assert c["moisture"] == 35.0
    assert c["soil_type"] == "peat"
    assert sum(f["type"] == "corrected" for f in flags) == 3


def test_clean_removes_impossible_values():
    c, flags, _ = dq.clean_record(row(1, ph=15, rainfall=-3))
    assert c["ph"] is None and c["rainfall"] is None
    assert {f["field"] for f in flags if f["type"] == "invalid"} == {"ph", "rainfall"}


def test_plot_names_are_standardised():
    assert dq.normalise_plot("  block   a ") == "Block A"


def test_duplicates_are_detected_and_set_aside():
    rows = [row(1), row(2), row(3, ph=5.0)]
    assert dq.find_duplicates(rows) == {1}
    result = dq.process(rows)
    assert result["counts"]["duplicates_removed"] == 1
    assert not result["records"][1]["_usable"]


def test_missing_values_are_imputed_from_the_same_plot_first():
    rows = [row(1, ph=4.0), row(2, ph=4.2, nitrogen=60), row(3, ph=None), row(4, plot="Block B", ph=6.0, nitrogen=70)]
    result = dq.process(rows, "median")
    filled = result["records"][2]
    assert filled["ph"] == 4.1  # median of Block A only, not Block B's 6.0
    assert any(f["type"] == "imputed" and f["field"] == "ph" for f in filled["_flags"])


@pytest.mark.parametrize("method", ["mean", "knn"])
def test_other_imputation_methods_fill_values(method):
    rows = [row(1, ph=4.0), row(2, ph=4.4, nitrogen=55), row(3, ph=None, nitrogen=52), row(4, ph=5.0, nitrogen=90)]
    result = dq.process(rows, method)
    assert result["records"][2]["ph"] is not None
    assert result["counts"]["values_imputed"] == 1


def test_mostly_empty_record_is_flagged_not_invented():
    sparse = dict(id=9, plot_name="Block A", reading_date=TODAY, ph=4.8)
    result = dq.process([row(1), row(2, ph=5), sparse])
    rec_ = result["records"][2]
    assert not rec_["_usable"]
    assert rec_["nitrogen"] is None
    assert any(f["type"] == "unreliable" for f in rec_["_flags"])


def test_outliers_are_flagged_but_kept():
    rows = [row(i, potassium=150 + i) for i in range(1, 9)] + [row(20, potassium=1500)]
    result = dq.process(rows)
    odd = result["records"][-1]
    assert odd["potassium"] == 1500
    assert any(f["type"] == "outlier" and f["field"] == "potassium" for f in odd["_flags"])


def test_normalised_values_are_between_zero_and_one():
    result = dq.process([row(1, ph=4), row(2, ph=5), row(3, ph=6)])
    assert [r["_normalised"]["ph"] for r in result["records"]] == [0.0, 0.5, 1.0]


def test_quality_score_improves_after_cleaning():
    rows = [row(1), row(2), row(3, temperature=88, soil_type="Gambut"), row(4, ph=None, nitrogen=None),
            row(5, ph=22), row(6, plot=" block a ")]
    result = dq.process(rows)
    assert result["after"]["overall"] > result["before"]["overall"]
    assert result["after"]["validity"] == 100.0
    assert result["before"]["uniqueness"] < 100.0


def test_unknown_method_is_rejected():
    with pytest.raises(dq.PipelineError):
        dq.process([row(1)], "magic")


def test_csv_rows_accept_loose_headers():
    text = "Plot,Date,Soil pH,N (mg/kg),Temp,Soil\nBlock C,2026-10-01,4.9,44,30,mineral\n"
    (r,) = list(dq.iter_csv_rows(text))
    assert r == {"plot_name": "Block C", "reading_date": "2026-10-01", "ph": "4.9", "nitrogen": "44",
                 "temperature": "30", "soil_type": "mineral"}


# ─── recommendation rules ───────────────────────────────────────────────────

def test_range_fit():
    assert rec.range_fit(5, 4.5, 5.5) == 1.0                     # centre
    assert rec.range_fit(5.5, 4.5, 5.5) == pytest.approx(0.8)    # edge
    assert rec.range_fit(6.0, 4.5, 5.5) == pytest.approx(0.4)    # half a width outside
    assert rec.range_fit(9, 4.5, 5.5) == 0.0



def test_acidic_peat_prefers_peat_varieties_and_mineral_prefers_md2():
    peat = {"ph": 3.8, "temperature": 29, "rainfall": 6, "moisture": 50, "soil_type": "peat"}
    mineral = {"ph": 5.2, "temperature": 28, "rainfall": 4, "moisture": 30, "soil_type": "mineral"}
    best = lambda c: max(rec.VARIETIES, key=lambda v: rec.score_variety(rec.VARIETIES[v], c)[0])
    assert best(peat) in ("Morris", "N36")
    assert best(mineral) == "MD2"


def test_advice_reacts_to_conditions():
    assert any("limestone" in t for t in rec.fertiliser_advice({"ph": 3.6}))
    assert any("irrigate" in t for t in rec.irrigation_advice({"moisture": 12}))
    assert any("waterlogging" in t for t in rec.irrigation_advice({"moisture": 75}))


# ─── API ────────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    assert is_sqlite
    Base.metadata.create_all(bind=engine)
    s = SessionLocal()
    yield s
    s.close()
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session):
    def override():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()
    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def users(db_session):
    made = {}
    for name, role in (("admin", "admin"), ("arif", "worker"), ("ibrahim", "worker")):
        u = User(username=name, email=f"{name}@t.com", password_hash="x", full_name=name, role=role)
        db_session.add(u)
        made[name] = u
    db_session.commit()
    return made


def auth(u):
    return {"Authorization": f"Bearer {create_access_token(u.id, u.role)}"}


def post_reading(client, user, **values):
    body = {k: v for k, v in row(0, **values).items() if k != "id"}
    body["reading_date"] = body["reading_date"].isoformat()
    res = client.post("/api/soil/readings", json=body, headers=auth(user))
    assert res.status_code == 201, res.text
    return res.json()


def test_worker_records_and_sees_only_own_readings(client, users):
    post_reading(client, users["arif"], plot_name=" block a ")
    post_reading(client, users["ibrahim"])
    mine = client.get("/api/soil/readings", headers=auth(users["arif"])).json()
    assert mine["total"] == 1 and mine["items"][0]["plot_name"] == "Block A"
    assert client.get("/api/soil/readings", headers=auth(users["admin"])).json()["total"] == 2


def test_worker_cannot_run_pipeline_or_import(client, users):
    assert client.post("/api/soil/quality/run", json={}, headers=auth(users["arif"])).status_code == 403
    assert client.post("/api/soil/import", json={"csv_text": "x"}, headers=auth(users["arif"])).status_code == 403


def test_worker_cannot_delete_someone_elses_reading(client, users):
    r = post_reading(client, users["ibrahim"])
    assert client.delete(f"/api/soil/readings/{r['id']}", headers=auth(users["arif"])).status_code == 403
    assert client.delete(f"/api/soil/readings/{r['id']}", headers=auth(users["ibrahim"])).status_code == 204


def test_import_run_and_recommend_end_to_end(client, users, db_session):
    csv_text = (
        "plot_name,reading_date,ph,nitrogen,temperature,moisture,soil_type,rainfall\n"
        f"Block A,{TODAY},3.9,40,86,0.5,Gambut,6\n"
        f"Block A,{TODAY - timedelta(days=3)},3.8,NA,29,48,peat,6.5\n"
        f"Block A,{TODAY - timedelta(days=3)},3.8,NA,29,48,peat,6.5\n"
        f"Block B,{TODAY},5.1,60,28,30,mineral,4\n"
        f"Block B,{TODAY - timedelta(days=7)},5.2,55,27,28,clay,3.8\n"
        ",2026-01-01,5,5,5,5,peat,5\n"
        "Block C,yesterday,5,5,5,5,peat,5\n"
    )
    admin = auth(users["admin"])
    imp = client.post("/api/soil/import", json={"csv_text": csv_text}, headers=admin).json()
    assert imp["imported"] == 5 and len(imp["skipped"]) == 2 and imp["unreadable_values"] == 2

    run = client.post("/api/soil/quality/run", json={"method": "median"}, headers=admin)
    assert run.status_code == 200, run.text
    run = run.json()
    assert run["duplicates_removed"] == 1
    assert run["corrections_made"] >= 3  # °F, fraction, 'Gambut', 'clay'
    assert run["score_after"] > run["score_before"]

    latest = client.get("/api/soil/quality/latest", headers=admin).json()
    assert latest["run"]["id"] == run["id"] and latest["unprocessed_readings"] == 0
    assert client.get("/api/soil/quality/issues?type=duplicate", headers=admin).json()
    assert "quality_score" in client.get("/api/soil/quality/report", headers=admin).text
    assert len(client.get("/api/soil/quality/plots", headers=admin).json()) == 2

    recs = client.get("/api/soil/recommendations", headers=auth(users["arif"])).json()
    by_plot = {r["plot_name"]: r for r in recs}
    assert by_plot["Block A"]["recommended_variety"] in ("Morris", "N36")
    assert by_plot["Block B"]["recommended_variety"] == "MD2"
    assert by_plot["Block A"]["confidence_level"] in ("high", "medium", "low")
    assert client.get("/api/soil/recommendations/block b", headers=auth(users["arif"])).status_code == 200
    assert client.get("/api/soil/recommendations/Nowhere", headers=auth(users["arif"])).status_code == 404

    impact = client.get("/api/soil/quality/impact", headers=admin).json()
    assert {p["plot_name"] for p in impact["plots"]} == {"Block A", "Block B"}

    db_session.add(Harvest(user_id=users["arif"].id, batch_number="B-1", field_name="block a",
                           harvest_date=TODAY, quantity_kg=1000, rejected_kg=50, spoilage_kg=50, quality_grade="A"))
    db_session.commit()
    out = {o["plot_name"]: o for o in client.get("/api/soil/outcomes", headers=admin).json()}
    assert out["Block A"]["rejection_rate"] == 10.0 and out["Block A"]["has_soil_data"]


def test_run_without_data_is_a_clear_error(client, users):
    res = client.post("/api/soil/quality/run", json={}, headers=auth(users["admin"]))
    assert res.status_code == 400


def test_plots_include_harvest_fields(client, users, db_session):
    db_session.add(Harvest(user_id=users["arif"].id, batch_number="B-9", field_name="Block Z",
                           harvest_date=TODAY, quantity_kg=10))
    db_session.commit()
    assert "Block Z" in client.get("/api/soil/plots", headers=auth(users["arif"])).json()

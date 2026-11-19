import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from airq.server import api, db

T0 = datetime(2016, 3, 1)


def _reading(station, hour, pm25, flags=(), sent_ms=5):
    ts = T0 + timedelta(hours=hour)
    sent = datetime(2026, 11, 19, 12, 0, 0)
    return {
        "station": station, "ts": ts.isoformat(), "pm25": pm25, "pm10": 80.0, "seq": hour,
        "sent_at": sent.isoformat(timespec="milliseconds"),
        "received_at": (sent + timedelta(milliseconds=sent_ms)).isoformat(timespec="milliseconds"),
        "quality_flags": json.dumps(list(flags)),
    }  # fmt: skip


@pytest.fixture()
def client(tmp_path):
    path = tmp_path / "t.db"
    con = db.connect(path)
    for h in range(100):
        db.upsert_reading(con, _reading("Dongsi", h, 50.0 + h, flags=["stuck"] if h == 99 else ()))
    db.upsert_reading(con, _reading("Dongsi", 99, 1.0))  # a QoS1 duplicate
    db.upsert_reading(con, _reading("Huairou", 0, 30.0))
    db.set_device_status(con, "Dongsi", "online", "2016-03-05T03:00:00")
    db.set_device_status(con, "Huairou", "offline", "2016-03-05T03:00:00")
    for h in (1, 6, 24):
        for made in (98, 99):
            ts = T0 + timedelta(hours=made)
            db.upsert_prediction(con, {
                "station": "Dongsi", "made_at_ts": ts.isoformat(),
                "target_ts": (ts + timedelta(hours=h)).isoformat(), "horizon": h,
                "yhat": 100.0 + h, "n_neighbors": 11, "model_version": "v",
            })  # fmt: skip
    con.execute(
        "INSERT INTO warnings VALUES ('Dongsi', ?, 6, 150, 160.0, 'point', 'x')",
        ((T0 + timedelta(hours=99)).isoformat(),),
    )
    db.add_event(
        con, "2026-11-19T12:00:00", "edge_stats", json.dumps({"received": 201, "invalid": 0})
    )
    con.commit()
    metrics = tmp_path / "reports" / "metrics"
    metrics.mkdir(parents=True)
    (metrics / "forecast_v0.json").write_text(json.dumps({"evaluated_on": "val"}))
    return TestClient(api.create_app(path, tmp_path / "reports"))


def test_health_and_missing_database(tmp_path):
    c = TestClient(api.create_app(tmp_path / "none.db", tmp_path))
    assert c.get("/health").json() == {"status": "ok", "db": False}
    assert c.get("/stations").status_code == 503  # explicit error, not an empty list


def test_stations_lists_status_last_value_flags_and_warnings(client):
    rows = {r["station"]: r for r in client.get("/stations").json()}
    d = rows["Dongsi"]
    assert d["status"] == "online" and d["last_pm25"] == 149.0  # duplicate did not overwrite
    assert d["quality_flags"] == ["stuck"] and d["active_warnings"] == 1
    assert rows["Huairou"]["status"] == "offline"


def test_readings_window_is_chronological_and_validated(client):
    r = client.get("/readings/Dongsi", params={"hours": 5}).json()
    assert [x["seq"] for x in r] == [95, 96, 97, 98, 99]
    assert client.get("/readings/Nowhere").status_code == 404
    assert client.get("/readings/Dongsi", params={"hours": 0}).status_code == 422
    assert client.get("/readings/Dongsi", params={"hours": "abc"}).status_code == 422


def test_forecast_filters_by_horizon_and_validates(client):
    all_rows = client.get("/forecast/Dongsi").json()
    assert len(all_rows) == 6 and {r["horizon"] for r in all_rows} == {1, 6, 24}
    only6 = client.get("/forecast/Dongsi", params={"horizon": 6}).json()
    assert len(only6) == 2 and all(r["horizon"] == 6 for r in only6)
    assert client.get("/forecast/Dongsi", params={"horizon": 7}).status_code == 422
    assert client.get("/forecast/Nowhere").status_code == 404
    assert client.get("/forecast/Huairou").json() == []  # known station, no predictions yet


def test_warnings_filters_and_rejects_a_bad_timestamp(client):
    assert len(client.get("/warnings").json()) == 1
    assert client.get("/warnings", params={"station": "Huairou"}).json() == []
    assert len(client.get("/warnings", params={"since": "2016-03-05T00:00:00"}).json()) == 1
    assert client.get("/warnings", params={"since": "2016-03-06T00:00:00"}).json() == []
    assert client.get("/warnings", params={"since": "yesterday"}).status_code == 422


def test_metrics_exposes_offline_result_files(client):
    assert client.get("/metrics").json() == {"forecast_v0": {"evaluated_on": "val"}}


def test_system_stats_reports_duplicates_latency_and_edge_counters(client):
    s = client.get("/system/stats").json()
    assert s["unique_messages"] == 101 and s["duplicates"] == 1
    assert s["duplicate_rate"] == pytest.approx(1 / 101)
    assert s["latency_ms"]["p50"] == pytest.approx(5.0) and s["online_devices"] == 1
    assert s["edge"] == {"received": 201, "invalid": 0}


def test_tables_and_figures_are_served_safely(client, tmp_path):
    reports = tmp_path / "reports"
    (reports / "tables").mkdir()
    (reports / "tables" / "rq1_main.csv").write_text("h,model,rmse\n1,B0,19.6\n6,B0,54.9\n")
    (reports / "figures").mkdir()
    (reports / "figures" / "rq1_horizon.png").write_bytes(b"\x89PNG\r\n\x1a\nxx")
    assert client.get("/tables").json() == ["rq1_main"]
    t = client.get("/tables/rq1_main").json()
    assert t["columns"] == ["h", "model", "rmse"] and len(t["rows"]) == 2
    assert client.get("/tables/rq1_main", params={"limit": 1}).json()["rows"] == [
        {"h": "1", "model": "B0", "rmse": "19.6"}
    ]
    assert client.get("/tables/nope").status_code == 404
    assert client.get("/tables/..%2Fsecret").status_code in (404, 422)
    assert client.get("/tables/a.b").status_code == 422
    r = client.get("/figures/rq1_horizon")
    assert r.status_code == 200 and r.headers["content-type"] == "image/png"
    assert client.get("/figures/missing").status_code == 404

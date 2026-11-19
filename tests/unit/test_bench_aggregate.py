from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from airq.pipelines.rq3a import _warning_quality, paired_rmse, seq_gaps
from airq.server import db

T0 = datetime(2017, 1, 1)


def _db(path, preds=(), readings=()):
    con = db.connect(path)
    for station, hour, h, yhat in preds:
        ts = T0 + timedelta(hours=hour)
        db.upsert_prediction(
            con,
            {
                "station": station,
                "made_at_ts": ts.isoformat(),
                "target_ts": (ts + timedelta(hours=h)).isoformat(),
                "horizon": h,
                "yhat": yhat,
                "n_neighbors": 5,
                "model_version": "v",
            },
        )
    for station, seq in readings:
        db.upsert_reading(
            con,
            {
                "station": station,
                "ts": (T0 + timedelta(hours=seq)).isoformat(),
                "pm25": 1.0,
                "seq": seq,
                "sent_at": "2017-01-01T00:00:00.000",
                "received_at": "2017-01-01T00:00:00.010",
                "quality_flags": "[]",
            },
        )
    con.commit()
    con.close()


def _truth(stations, hours=10, value=100.0):
    return pd.DataFrame(
        [
            {"station": s, "ts": T0 + timedelta(hours=h), "pm25_raw": value}
            for s in stations
            for h in range(hours)
        ]
    )


def test_paired_rmse_uses_only_keys_present_in_both_runs(tmp_path):
    # baseline predicts for A and B (errors 10 and 50); the offline run only for A (error 20)
    base = [("A", 1, 1, 110.0), ("A", 2, 1, 110.0), ("B", 1, 1, 150.0), ("B", 2, 1, 150.0)]
    run = [("A", 1, 1, 120.0), ("A", 2, 1, 120.0)]
    _db(tmp_path / "base.db", preds=base)
    _db(tmp_path / "run.db", preds=run)
    out = paired_rmse(tmp_path / "run.db", tmp_path / "base.db", _truth(["A", "B"]))
    assert out["paired_n_h1"] == 2  # station B has no counterpart and is excluded
    assert out["paired_rmse_h1"] == pytest.approx(20.0)
    assert out["paired_rmse_base_h1"] == pytest.approx(10.0)  # NOT mixed with B's error of 50
    assert out["paired_delta_h1"] == pytest.approx(10.0)
    assert "paired_rmse_h6" not in out  # no horizon-6 predictions


def test_paired_rmse_ignores_targets_without_an_observation(tmp_path):
    preds = [("A", 1, 1, 130.0), ("A", 9, 1, 500.0)]  # target hour 10 has no observation
    _db(tmp_path / "b.db", preds=preds)
    _db(tmp_path / "r.db", preds=preds)
    out = paired_rmse(tmp_path / "r.db", tmp_path / "b.db", _truth(["A"], hours=10))
    assert out["paired_n_h1"] == 1 and out["paired_delta_h1"] == 0.0


def test_seq_gaps_counts_readings_missing_from_the_seq_streams(tmp_path):
    # A delivered seq 0,1,3,4 (2 lost); B delivered 0,1,2 (complete); trailing losses are unseen
    _db(
        tmp_path / "g.db", readings=[("A", s) for s in (0, 1, 3, 4)] + [("B", s) for s in (0, 1, 2)]
    )
    assert seq_gaps(tmp_path / "g.db") == 1


def test_event_recall_can_be_restricted_to_the_stations_that_were_online():
    onset = T0 + timedelta(hours=30)
    events = pd.DataFrame(
        {
            "type": "exceedance",
            "threshold": 150.0,
            "station": ["A", "B"],
            "start": [onset, onset],
            "end": [onset + timedelta(hours=5)] * 2,
        }
    )
    warns = pd.DataFrame(
        {
            "station": ["A"],
            "made_at_ts": [onset - timedelta(hours=3)],
            "horizon": [6],
            "threshold": [150.0],
        }
    )  # only A (online) warned
    truth = pd.concat([_truth([s], hours=60, value=200.0) for s in ("A", "B")])
    end = T0 + timedelta(hours=59)
    both = _warning_quality(warns, truth, events, end)
    online = _warning_quality(warns, truth, events, end, stations=["A"])
    assert both["event_recall_150"] == pytest.approx(0.5)  # B is offline: its event is not covered
    assert online["event_recall_150"] == pytest.approx(1.0)
    assert not np.isnan(online["false_alarm_150"])

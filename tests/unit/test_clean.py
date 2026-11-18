import numpy as np
import pandas as pd

from airq.data.clean import clean, wind_to_sincos


def _raw(ts_list, pm25, station="A"):
    df = pd.DataFrame({"station": station, "ts": pd.to_datetime(ts_list), "pm25": pm25})
    for c in ["pm10", "so2", "no2", "co", "o3", "temp", "pres", "dewp", "rain", "wspm"]:
        df[c] = 1.0
    df["wd"] = "N"
    return df


def test_missing_hours_are_added_and_ffill_is_limited_to_three():
    raw = _raw(["2016-01-01 00:00", "2016-01-01 06:00"], [50.0, 70.0])
    out = clean(raw, "2016-01-01 00:00", "2016-01-01 06:00", ffill_limit=3)
    assert len(out) == 7
    pm = out["pm25"].tolist()
    assert pm[:4] == [50.0] * 4  # original + 3 filled
    assert np.isnan(pm[4]) and np.isnan(pm[5])  # beyond limit stays NaN
    assert pm[6] == 70.0


def test_pm25_raw_is_never_filled_and_missing_flag_is_pre_fill():
    raw = _raw(["2016-01-01 00:00", "2016-01-01 03:00"], [50.0, 70.0])
    out = clean(raw, "2016-01-01 00:00", "2016-01-01 03:00")
    assert out["pm25_raw"].isna().sum() == 2
    assert out["pm25_missing"].tolist() == [False, True, True, False]


def test_no_backfill_leading_gap_stays_nan():
    raw = _raw(["2016-01-01 03:00"], [70.0])
    out = clean(raw, "2016-01-01 00:00", "2016-01-01 03:00")
    assert out["pm25"].iloc[:3].isna().all()


def test_ffill_does_not_cross_stations():
    a = _raw(["2016-01-01 00:00"], [50.0], "A")
    b = _raw(["2016-01-01 02:00"], [70.0], "B")
    out = clean(pd.concat([a, b]), "2016-01-01 00:00", "2016-01-01 02:00")
    b_first = out[(out["station"] == "B") & (out["ts"] == "2016-01-01 00:00")]
    assert np.isnan(b_first["pm25"].iloc[0])


def test_wind_encoding_and_missing_direction():
    s, c = wind_to_sincos(pd.Series(["E", "N", None]))
    assert np.isclose(s.iloc[0], 1.0) and np.isclose(c.iloc[1], 1.0)
    assert np.isnan(s.iloc[2]) and np.isnan(c.iloc[2])

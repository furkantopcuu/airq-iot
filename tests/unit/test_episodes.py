import numpy as np
import pandas as pd

from airq.data.episodes import exceedance_events, regional_haze


def _series(values):
    idx = pd.date_range("2016-03-01", periods=len(values), freq="h")
    return pd.Series(values, index=idx, dtype=float)


def test_exceedance_needs_min_hours():
    s = _series([10, 80, 80, 10, 10, 10, 10, 10, 10, 90, 90, 90, 10])
    ev = exceedance_events(s, "A", 75, min_hours=3, merge_gap_h=6)
    assert len(ev) == 1  # the 2-hour block is too short
    assert ev.loc[0, "start"] == s.index[9] and ev.loc[0, "hours"] == 3


def test_blocks_closer_than_gap_are_merged():
    # two 3-h blocks separated by 5 non-exceeding hours (< 6) -> one event
    s = _series([80] * 3 + [10] * 5 + [80] * 3)
    ev = exceedance_events(s, "A", 75, 3, 6)
    assert len(ev) == 1 and ev.loc[0, "hours"] == 11 and ev.loc[0, "start"] == s.index[0]


def test_blocks_with_enough_gap_stay_separate():
    s = _series([80] * 3 + [10] * 6 + [80] * 3)
    assert len(exceedance_events(s, "A", 75, 3, 6)) == 2


def test_nan_does_not_count_as_exceeding():
    s = _series([80, np.nan, 80, 80])
    assert exceedance_events(s, "A", 75, 3, 6).empty


def test_regional_haze_requires_stations_and_duration():
    idx = pd.date_range("2016-03-01", periods=12, freq="h")
    wide = pd.DataFrame(10.0, index=idx, columns=list("ABCDEFGHIJ"))
    wide.iloc[2:8, :8] = 200  # 8 stations for 6 h -> episode
    wide.iloc[9:12, :9] = 200  # 3 h only -> no episode
    ep = regional_haze(wide, min_stations=8, threshold=150, min_hours=6)
    assert len(ep) == 1
    assert ep.loc[0, "hours"] == 6 and ep.loc[0, "peak"] == 200

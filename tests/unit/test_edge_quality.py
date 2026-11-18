import numpy as np
import pandas as pd

from airq.config import load_config
from airq.edge.quality import (
    MISSING,
    OUT_OF_RANGE,
    PM_INCONSISTENT,
    RATE_JUMP,
    STUCK,
    QualityParams,
    StreamChecker,
    _stuck_reference,
    apply_filter,
    fit_params,
    flag_frame,
    flag_series,
)

P = QualityParams(lo=0, hi=999, stuck_n=4, tau_rate=100, pm_eps=0.1, pm_c=10)


def _series(vals, pm10=None):
    idx = pd.date_range("2016-01-01", periods=len(vals), freq="h")
    x = pd.Series(vals, index=idx, dtype=float)
    y = pd.Series(pm10 if pm10 is not None else [np.nan] * len(vals), index=idx, dtype=float)
    return x, y


def test_range_rule():
    x, y = _series([50, -1, 1000, 999, 0])
    f = flag_series(x, y, P)
    assert f[OUT_OF_RANGE].tolist() == [False, True, True, False, False]


def test_rate_rule_needs_two_observed_neighbours():
    x, y = _series([50, 200, np.nan, 500, 520])
    f = flag_series(x, y, P)
    assert f[RATE_JUMP].tolist() == [False, True, False, False, False]  # no jump across a gap


def test_stuck_flags_the_nth_equal_value_onward():
    x, y = _series([10, 7, 7, 7, 7, 7, 8, 8, 8, np.nan, 8, 8, 8, 8])
    f = flag_series(x, y, P)
    assert f[STUCK].tolist() == [False, False, False, False, True, True, False, False, False,
                                 False, False, False, False, True]  # fmt: skip  # n=4 equal values


def test_physical_consistency_uses_tolerance_and_ignores_missing_pm10():
    x, y = _series([50, 130, 120, 300], pm10=[100, 100, 100, np.nan])
    f = flag_series(x, y, P)
    # limit = pm10*1.1 + 10 = 120 -> 130 is inconsistent, 120 is not, missing pm10 is not checked
    assert f[PM_INCONSISTENT].tolist() == [False, True, False, False]


def test_missing_flag_and_filter_nulls_only_untrustworthy_values():
    x, y = _series([50, np.nan, 5000, 5010, 60])
    f = flag_series(x, y, P)
    assert f[MISSING].tolist() == [False, True, False, False, False]
    out = apply_filter(x, f)
    assert np.isnan(out.iloc[2]) and out.iloc[0] == 50  # out-of-range value removed
    assert out.iloc[3] != 5010 and np.isnan(out.iloc[3])  # 5010 is also out of range
    # a one-off spike also flags the return sample: the rate rule compares with the previous value
    spike, _ = _series([50, 400, 52])
    assert flag_series(spike, _, P)[RATE_JUMP].tolist() == [False, True, True]


def test_vectorized_equals_streaming_on_random_data_with_faults():
    rng = np.random.default_rng(0)
    n = 3000
    x = np.abs(rng.normal(80, 40, n)).round()
    x[200:230] = 77  # stuck
    x[500] = 1500  # out of range + jump
    x[800:805] = [20, 400, 25, 330, 30]  # jumps
    x[rng.random(n) < 0.03] = np.nan
    pm10 = np.abs(x * rng.uniform(0.6, 1.6, n)).round()
    pm10[rng.random(n) < 0.05] = np.nan
    s, t = _series(x, pm10)
    vec = flag_series(s, t, P)
    chk = StreamChecker(P)
    online = [
        chk.update(None if np.isnan(a) else a, None if np.isnan(b) else b)
        for a, b in zip(x, pm10, strict=True)
    ]
    for name in (MISSING, OUT_OF_RANGE, RATE_JUMP, STUCK, PM_INCONSISTENT):
        assert vec[name].tolist() == [name in fl for fl in online], f"offline != online for {name}"
    assert vec[STUCK].sum() > 20 and vec[RATE_JUMP].sum() > 3  # the test exercises the rules


def test_stuck_matches_a_simple_reference():
    rng = np.random.default_rng(1)
    vals = list(rng.integers(0, 3, 500).astype(float))  # many repeats
    vals[100] = np.nan
    s, t = _series(vals)
    ref = _stuck_reference([None if np.isnan(v) else v for v in vals], 4)
    assert flag_series(s, t, P)[STUCK].tolist() == ref


def test_flag_frame_does_not_leak_between_stations():
    ts = pd.date_range("2016-01-01", periods=6, freq="h")
    a = pd.DataFrame({"station": "A", "ts": ts, "pm25_raw": [5.0] * 6, "pm10": 50.0})
    b = pd.DataFrame(
        {"station": "B", "ts": ts, "pm25_raw": [9.0, 10, 11, 12, 13, 14], "pm10": 50.0}
    )
    df = pd.concat([a, b], ignore_index=True)
    f = flag_frame(df, P)
    assert f.loc[df["station"] == "A", STUCK].sum() == 3
    assert f.loc[df["station"] == "B", STUCK].sum() == 0


def test_params_are_fit_on_the_rows_they_are_given_only():
    cfg = load_config()
    rng = np.random.default_rng(2)
    ts = pd.date_range("2016-01-01", periods=500, freq="h")
    base = pd.DataFrame({"station": "A", "ts": ts, "pm25_raw": np.abs(rng.normal(80, 30, 500)),
                         "pm10": 120.0, "pm10_missing": False})  # fmt: skip
    p1 = fit_params(base, cfg)
    spiky = base.copy()
    spiky.loc[400:, "pm25_raw"] = rng.normal(900, 50, 100)  # "future" data not given to fit
    assert fit_params(base.iloc[:400], cfg) == fit_params(spiky.iloc[:400], cfg)
    assert p1.lo == 0 and p1.hi == 999 and p1.stuck_n == 4 and p1.tau_rate > 0

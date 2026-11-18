import pandas as pd

from airq.config import load_config
from airq.data.splits import assign_split, horizon_mask, split_bounds

CFG = load_config()


def test_bounds_are_ordered_and_disjoint():
    b = split_bounds(CFG)
    assert b["train"][1] < b["val"][0] < b["val"][1] < b["test"][0]


def test_assign_split_boundaries():
    ts = pd.to_datetime(["2013-03-01 00:00", "2015-08-31 23:00", "2015-09-01 00:00",
                         "2016-02-29 23:00", "2016-03-01 00:00", "2017-02-28 23:00",
                         "2012-01-01 00:00"])  # fmt: skip
    got = assign_split(ts, CFG).tolist()
    assert got[:6] == ["train", "train", "val", "val", "test", "test"]
    assert pd.isna(got[6])


def test_same_timestamp_same_split_for_all_stations():
    ts = pd.date_range("2015-08-31 20:00", periods=10, freq="h")
    df = pd.DataFrame({"ts": list(ts) * 3, "station": ["a"] * 10 + ["b"] * 10 + ["c"] * 10})
    df["split"] = assign_split(df["ts"], CFG).to_numpy()
    assert df.groupby("ts")["split"].nunique().max() == 1


def test_target_boundary_rule_drops_rows_whose_target_leaves_the_split():
    ts = pd.to_datetime(["2015-08-31 22:00", "2015-08-31 23:00", "2015-08-31 12:00"])
    m1 = horizon_mask(ts, "train", 1, CFG).tolist()
    m6 = horizon_mask(ts, "train", 6, CFG).tolist()
    m24 = horizon_mask(ts, "train", 24, CFG).tolist()
    assert m1 == [True, False, True]  # 23:00 + 1 h -> val
    assert m6 == [False, False, True]
    assert m24 == [False, False, False]  # 12:00 + 24 h crosses into val


def test_no_train_row_has_target_in_later_split():
    ts = pd.date_range("2015-08-01", "2015-09-05", freq="h")
    for h in (1, 6, 24):
        kept = ts[horizon_mask(ts, "train", h, CFG).to_numpy()]
        assert (kept + pd.Timedelta(hours=h)).max() <= split_bounds(CFG)["train"][1]

import numpy as np
import pandas as pd
import pytest

from airq.warning.evaluate import event_leads, false_alarm_stats, hourly_metrics, summarize_leads
from airq.warning.rules import apply_cooldown, fbeta, select_delta, warning_flags

T = pd.Timestamp


def test_warning_rule_uses_the_safety_margin_and_ignores_missing_forecasts():
    yhat = np.array([60.0, 70.0, np.nan, 80.0])
    assert warning_flags(yhat, theta=75, delta=0).tolist() == [False, False, False, True]
    assert warning_flags(yhat, theta=75, delta=10).tolist() == [False, True, False, True]  # > 65


def test_cooldown_merges_consecutive_warnings_into_one_alert():
    flags = np.array([1, 1, 1, 0, 0, 0, 1, 1, 0, 0, 0, 0, 1], dtype=bool)
    alerts = apply_cooldown(flags, cooldown_h=6)
    # alert at 0; rows 1-5 suppressed; the warning is still on at row 6 -> a new alert; 7 suppressed
    assert np.flatnonzero(alerts).tolist() == [0, 6, 12]
    assert apply_cooldown(np.zeros(5, dtype=bool), 6).sum() == 0


def test_f2_weights_recall_more_than_precision():
    assert fbeta(0.5, 1.0, 2.0) == pytest.approx(5 * 0.5 / (4 * 0.5 + 1.0))
    assert fbeta(1.0, 0.5, 2.0) < fbeta(
        0.5, 1.0, 2.0
    )  # missing events costs more than false alarms
    assert fbeta(0.0, 0.0) == 0.0


def test_delta_is_chosen_by_f2_on_the_given_rows_and_ties_pick_the_smaller():
    y_bool = np.array([True, True, False, False])
    yhat = np.array([70.0, 60.0, 40.0, 74.0])
    delta, table = select_delta(y_bool, yhat, 75, [0, 5, 10, 15, 20, 30, 40])
    by = {row["delta"]: row["fbeta"] for row in table}
    assert by[0] == 0 and by[10] == pytest.approx(0.5)
    assert by[20] == pytest.approx(5 * (2 / 3) / (4 * (2 / 3) + 1))
    assert by[20] == pytest.approx(by[30]) and delta == 20  # tie between 20 and 30 -> smaller
    assert by[40] < by[20]  # too large a margin brings more false alarms


def test_hourly_metrics_hand_example():
    m = hourly_metrics(np.array([True, False, True, False]), np.array([80.0, 80, 50, 40]), 75, 0)
    assert m["precision"] == 0.5 and m["recall"] == 0.5 and m["f1"] == 0.5 and m["f2"] == 0.5
    assert m["n_warnings"] == 2 and m["n_pos"] == 2 and 0 <= m["pr_auc"] <= 1


def test_event_leads_window_boundaries_and_misses():
    onsets = pd.Series([T("2016-03-05 12:00"), T("2016-03-10 00:00"), T("2016-03-12 06:00"),
                        T("2016-03-15 00:00")])  # fmt: skip
    alerts = np.array(
        [
            "2016-03-04 14:00",
            "2016-03-05 10:00",  # event 1: first alert 22 h before
            "2016-03-08 00:00",  # event 2: 48 h before -> outside the 24 h window
            "2016-03-12 06:00",  # event 3: alert exactly at the onset -> lead 0
            "2016-03-14 00:00",
        ],
        dtype="datetime64[ns]",
    )  # event 4: exactly 24 h before
    assert event_leads(onsets, alerts, 24) == [22.0, None, 0.0, 24.0]


def test_lead_summary_counts_recall_and_median():
    s = summarize_leads([22.0, None, 0.0, 24.0])
    assert s["n_events"] == 4 and s["n_caught"] == 3 and s["event_recall"] == 0.75
    assert s["lead_median"] == 22.0 and s["lead_mean"] == pytest.approx(46 / 3)
    empty = summarize_leads([None, None])
    assert empty["event_recall"] == 0 and np.isnan(empty["lead_median"])
    assert np.isnan(summarize_leads([])["event_recall"])


def test_false_alarm_counts_alerts_without_an_exceedance_in_the_next_24_hours():
    obs = np.full(60, 10.0)
    obs[1] = 80.0  # an exceedance right after alert 0
    obs[40] = np.nan  # a missing value is never an exceedance
    false, total = false_alarm_stats(np.array([0, 5, 38]), obs, theta=75)
    assert (false, total) == (2, 3)  # alert 0 is true; alerts 5 and 38 are false


def test_persistence_style_alert_has_lead_time_zero_at_best():
    pm = np.r_[np.full(10, 40.0), np.full(10, 90.0)]  # exceedance onset at index 10
    ts = pd.date_range("2016-03-01", periods=20, freq="h")
    alerts = apply_cooldown(warning_flags(pm, 75, 0), 6)  # PM2.5(t) > theta, no margin
    lead = event_leads(pd.Series([ts[10]]), ts.to_numpy()[alerts], 24)
    assert lead == [0.0]  # persistence can only notice the event when it has started
    early = apply_cooldown(warning_flags(np.r_[np.full(8, 40.0), np.full(12, 90.0)], 75, 0), 6)
    assert event_leads(pd.Series([ts[8]]), ts.to_numpy()[early], 24) == [0.0]


def test_matched_leads_ignore_alerts_about_other_events():
    from airq.warning.evaluate import combine_any, matched_leads

    onset, end = T("2016-03-05 12:00"), T("2016-03-05 20:00")
    alerts = np.array(["2016-03-05 06:00", "2016-03-05 11:00"], dtype="datetime64[ns]")
    # h=6: the alert at 06:00 forecasts 12:00 = onset (inside the event) -> lead 6; the one at
    # 11:00 forecasts 17:00 (also inside) but is later, so the earliest match wins
    assert matched_leads(pd.Series([onset]), pd.Series([end]), alerts, 6, 24) == [6.0]
    # h=1: only an alert at 11:00 (forecasting 12:00) matches; 06:00 forecasts 07:00 (no event)
    assert matched_leads(pd.Series([onset]), pd.Series([end]), alerts, 1, 24) == [1.0]
    only_old = np.array(["2016-03-05 03:00"], dtype="datetime64[ns]")  # forecasts 04:00 / 09:00
    assert matched_leads(pd.Series([onset]), pd.Series([end]), only_old, 1, 24) == [None]
    assert matched_leads(pd.Series([onset]), pd.Series([end]), only_old, 6, 24) == [None]
    # an alert issued after the event started is not an EARLY warning
    late = np.array(["2016-03-05 13:00"], dtype="datetime64[ns]")
    assert matched_leads(pd.Series([onset]), pd.Series([end]), late, 6, 24) == [None]
    # the 24 h window also bounds long horizons
    long = np.array(["2016-03-04 00:00"], dtype="datetime64[ns]")  # 36 h before the onset
    assert matched_leads(pd.Series([onset]), pd.Series([end]), long, 24, 24) == [None]
    assert combine_any([[6.0, None, 1.0], [None, None, 24.0]]) == [6.0, None, 24.0]

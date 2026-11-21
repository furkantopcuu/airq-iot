from datetime import datetime, timedelta

import pytest

from airq.dashboard import data as dash

T0 = datetime(2016, 3, 1)


def test_aqi_band_edges_follow_the_hj633_pm25_bounds():
    idx = {v: dash.aqi_band(v)["index"] for v in (0, 35, 36, 75, 76, 115, 116, 150, 151, 250, 251)}
    assert idx == {0: 0, 35: 0, 36: 1, 75: 1, 76: 2, 115: 2, 116: 3, 150: 3, 151: 4, 250: 4, 251: 5}
    assert (
        dash.aqi_band(None)["label"] == "Veri yok" and dash.aqi_band(float("nan"))["index"] is None
    )
    assert dash.aqi_band(300)["label"] == "Çok ağır kirli"
    assert len({b["color"] for b in dash.AQI_BANDS}) == 6  # six distinct colours


def _fc(made, h, yhat, n=11):
    ts = T0 + timedelta(hours=made)
    return {"made_at_ts": ts.isoformat(), "target_ts": (ts + timedelta(hours=h)).isoformat(),
            "horizon": h, "yhat": yhat, "q10": None, "q90": None, "n_neighbors": n}  # fmt: skip


def test_latest_forecasts_keeps_the_newest_per_horizon():
    rows = [_fc(1, 6, 100), _fc(3, 6, 120), _fc(2, 6, 110), _fc(3, 24, 80)]
    got = dash.latest_forecasts(rows)
    assert got[6]["yhat"] == 120 and got[24]["yhat"] == 80 and 1 not in got


def test_station_card_combines_status_value_forecast_and_warning():
    info = {"station": "Dongsi", "status": "online", "last_ts": "2016-03-01T03:00:00",
            "last_pm25": 160.0, "quality_flags": ["stuck"], "active_warnings": 2}  # fmt: skip
    card = dash.station_card(info, [_fc(3, 6, 260.0, n=9)])
    assert card["online"] and card["band"]["label"] == "Ağır kirli"
    assert card["forecast6"] == 260.0 and card["forecast6_band"]["label"] == "Çok ağır kirli"
    assert card["n_neighbors"] == 9 and card["warning"] and card["flags"] == ["stuck"]
    off = dash.station_card({"station": "X", "status": "offline"}, [])
    assert not off["online"] and off["last_pm25"] is None and off["forecast6"] is None
    assert not off["warning"] and off["band"]["label"] == "Veri yok"


def test_card_html_shows_the_warning_badge_only_when_warned_and_never_relies_on_colour_alone():
    info = {"station": "Dongsi", "status": "online", "last_pm25": 90.0, "active_warnings": 1}
    html = dash.card_html(dash.station_card(info, []))
    assert "UYARI (1)" in html and "Dongsi" in html and "çevrimiçi" in html and "µg/m³" in html
    assert "Hafif kirli" in html  # the band is named in text as well as coloured
    quiet = dash.card_html(dash.station_card({**info, "active_warnings": 0}, []))
    assert "UYARI" not in quiet
    off = dash.card_html(dash.station_card({"station": "Y", "status": "offline"}, []))
    assert "çevrimdışı" in off


def _reading(h, pm25):
    return {"ts": (T0 + timedelta(hours=h)).isoformat(), "pm25": pm25, "pm10": 100.0,
            "quality_flags": [], "seq": h}  # fmt: skip


def test_station_figure_has_units_thresholds_forecast_points_and_warning_markers():
    readings = [_reading(h, 50.0 + h) for h in range(10)]
    forecast = [_fc(9, 1, 70), _fc(9, 6, 90), _fc(9, 24, 110), _fc(8, 6, 85)]
    warnings = [{"station": "A", "made_at_ts": (T0 + timedelta(hours=9)).isoformat(), "horizon": 6,
                 "threshold": 75.0, "yhat": 90.0, "basis": "point"}]  # fmt: skip
    fig = dash.station_figure(readings, forecast, warnings, title="A")
    names = [t.name for t in fig.data]
    assert (
        "Ölçüm" in names
        and "Uyarı" in names
        and {"Tahmin +1 sa", "Tahmin +6 sa", "Tahmin +24 sa"} <= set(names)
    )
    assert fig.layout.yaxis.title.text == "PM2.5 (µg/m³)" and "Zaman" in fig.layout.xaxis.title.text
    assert {s.y0 for s in fig.layout.shapes} == {75, 150}  # both thresholds drawn
    assert fig.layout.font.size >= 16  # projector-readable
    warn = next(t for t in fig.data if t.name == "Uyarı")
    assert warn.x[0] == T0 + timedelta(hours=15)  # a warning sits at its TARGET time (made + h)


def test_warnings_table_marks_whether_the_exceedance_happened():
    made = T0 + timedelta(hours=2)
    base = {"station": "A", "horizon": 3, "threshold": 75.0, "yhat": 80.0, "basis": "point"}
    warns = [{**base, "made_at_ts": made.isoformat()},
             {**base, "made_at_ts": (made + timedelta(hours=1)).isoformat()},
             {**base, "made_at_ts": (made + timedelta(hours=50)).isoformat()}]  # fmt: skip
    readings = {"A": [_reading(5, 120.0), _reading(6, 40.0)]}  # targets: hour 5 (high), 6 (low)
    rows = dash.warnings_table(warns, readings)
    assert [r["Gerçekleşti mi"] for r in rows] == ["evet", "hayır", "bilinmiyor"]
    assert rows[0]["Eşik (µg/m³)"] == 75.0 and rows[0]["Ufuk (sa)"] == 3


def test_system_summary_lists_latency_duplicates_and_edge_counters():
    stats = {"online_devices": 12, "unique_messages": 288, "duplicate_rate": 0.0125,
             "latency_ms": {"p50": 2.0, "p95": 5.0, "p99": 6.0},
             "edge": {"received": 300, "invalid": 1, "seq_lost": 0, "filter_on": True}}  # fmt: skip
    rows = dict(dash.system_summary(stats))
    assert rows["Çevrimiçi cihaz"] == "12" and rows["Tekrar oranı (QoS 1)"] == "%1.25"
    assert rows["Gecikme p50 / p95 / p99 (ms)"] == "2.0 / 5.0 / 6.0"
    assert rows["Edge: geçersiz"] == "1" and rows["Edge filtresi"] == "açık"
    assert dict(dash.system_summary({}))["Gecikme p50 / p95 / p99 (ms)"] == "— / — / —"


def test_api_client_reports_an_unreachable_api_clearly():
    from airq.dashboard.client import ApiClient, ApiError

    c = ApiClient("http://127.0.0.1:9", timeout_s=0.5)
    with pytest.raises(ApiError, match="ulaşılamıyor"):
        c.get("/health")
    assert c.get_bytes("/figures/x") is None


def test_numeric_where_possible_converts_only_fully_numeric_columns():
    import pandas as pd

    df = pd.DataFrame(
        {"h": ["1", "6"], "model": ["B0", "M2"], "rmse": ["19.6", ""], "mix": ["1", "x"]}
    )
    out = dash.numeric_where_possible(df)
    assert (
        out["h"].tolist() == [1, 6] and out["rmse"].iloc[0] == 19.6 and out["rmse"].isna().iloc[1]
    )
    assert out["model"].tolist() == ["B0", "M2"] and out["mix"].tolist() == ["1", "x"]


def test_station_figure_draws_the_q10_q90_band_only_when_the_forecast_has_one():
    readings = [_reading(h, 50.0 + h) for h in range(10)]
    plain = [_fc(8, 6, 85), _fc(9, 6, 90)]
    plain_names = [t.name for t in dash.station_figure(readings, plain, []).data]
    assert "q10-q90 aralığı (6 sa)" not in plain_names
    banded = [{**r, "q10": r["yhat"] - 15, "q90": r["yhat"] + 25} for r in plain]
    fig = dash.station_figure(readings, banded, [])
    band = next(t for t in fig.data if t.name == "q10-q90 aralığı (6 sa)")
    upper = fig.data[list(fig.data).index(band) - 1]
    assert band.fill == "tonexty" and list(band.y) == [70.0, 75.0]
    assert list(upper.y) == [110.0, 115.0]  # q90 is the line the band fills down from
    mixed = [{**plain[0], "q10": None, "q90": None}, banded[1]]
    assert (
        len(
            next(
                t
                for t in dash.station_figure(readings, mixed, []).data
                if t.name == "q10-q90 aralığı (6 sa)"
            ).x
        )
        == 1
    )  # rows without a band are skipped


def test_a_card_says_warming_up_until_the_forecaster_has_its_history():
    from airq.dashboard import data as dash

    info = {"station": "Dongsi", "status": "online", "last_pm25": 12.0, "active_warnings": 0}
    until, now = "2017-01-02T16:00:00", "2016-12-29T16:00:00"
    left = dash.warmup_left_hours(until, now)
    assert left == 96.0
    html = dash.card_html(dash.station_card(info, [], left))
    assert "ısınıyor" in html and "96" in html and "—" not in html.split("6 saat sonra")[1][:80]
    assert dash.warmup_left_hours(until, "2017-01-03T00:00:00") is None  # warm-up over
    assert dash.warmup_left_hours(None, now) is None and dash.warmup_left_hours(until, None) is None
    assert dash.warmup_left_hours("not a time", now) is None
    # a forecast present: the normal number, no warm-up text
    row = {"horizon": 6, "yhat": 80.0, "made_at_ts": "2016-12-29T16:00:00", "n_neighbors": 11}
    assert "ısınıyor" not in dash.card_html(dash.station_card(info, [row], left))

"""Widget values -> API bodies and API rows -> tables (no Streamlit, no network)."""

from airq.dashboard import control as ctl
from airq.iot.schemas import Command


def test_device_payloads_are_valid_commands_for_every_mode():
    base = {"target": "Dongsi", "variables": ["pm25"]}
    cases = {
        "manual": {"value": 250.0},
        "offset": {"delta": 40.0},
        "scale": {"factor": 1.5},
        "ramp": {"ramp_kind": "delta", "ramp_value": 100.0, "duration_h": 6.0},
        "perturb": {"perturb_type": "spike", "severity": 8, "duration_h": 3.0},
        "offline": {"duration_h": 12.0},
        "replay": {},
    }
    for mode, kw in cases.items():
        body = ctl.device_payload(base["target"], base["variables"], mode, **kw)
        Command(cmd_id="x", issued_at="2016-01-01T00:00:00", **body)  # validates
    ramp = ctl.device_payload("all", ["pm25"], "ramp", ramp_kind="target", ramp_value=250,
                              duration_h=6)  # fmt: skip
    assert ramp["params"] == {"target": 250} and ramp["target"] == "all"


def test_zero_duration_means_until_reset_and_blank_label_is_dropped():
    body = ctl.device_payload("Dongsi", ["pm25"], "manual", value=5.0, duration_h=0.0, label="  ")
    assert body["duration_h"] is None and body["label"] is None
    stuck = ctl.device_payload("A", ["pm25"], "perturb", perturb_type="stuck", duration_h=2.0)
    assert stuck["params"] == {"type": "stuck"}  # severity only belongs to spikes


def test_result_text_covers_acks_errors_and_scenario_status():
    assert ctl.result_text({"ok": True, "acks": [{}, {}]}) == (True, "Onaylandı (2 ack)")
    ok, text = ctl.result_text({"ok": False, "errors": ["outside the physical range"]})
    assert not ok and "outside the physical range" in text
    ok, text = ctl.result_text({"name": "sensor_takilmasi", "steps_total": 4})
    assert ok and "sensor_takilmasi" in text


def test_scorecard_table_is_readable_and_handles_missing_numbers():
    rows = [
        {"label": "stuck-edge-on", "stations": "Dongsi", "mode": "perturb", "edge_filter": "on",
         "warned": False, "matched": False, "lead_time_h": None, "mae_next_6h_h1": 4.0,
         "mae_next_6h_h6": 11.26, "peak_forecast_h6": 80.4, "delivery_ratio": 1.0,
         "n_forecasts": 12},
        {"label": "stuck-edge-off", "stations": "Dongsi", "mode": "perturb", "edge_filter": "off",
         "warned": True, "matched": False, "lead_time_h": 2.0, "mae_next_6h_h1": None,
         "mae_next_6h_h6": 30.0, "peak_forecast_h6": None, "delivery_ratio": None,
         "n_forecasts": 0},
    ]  # fmt: skip
    df = ctl.format_scorecard(rows)
    assert list(df["Etiket"]) == ["stuck-edge-off", "stuck-edge-on"]
    off = df.iloc[0]
    assert (
        off["Edge"] == "kapalı"
        and off["Uyarı verildi"] == "Evet"
        and off["Aşımla eşleşti"] == "Hayır"
    )
    assert off["MAE h=1 (µg/m³)"] == "—" and off["Öncül süre (sa)"] == "2.0"
    assert df.iloc[1]["MAE h=6 (µg/m³)"] == "11.3"
    assert ctl.format_scorecard([]).empty


def test_status_line_and_active_table():
    state = {
        "interventions": [{"station": "Dongsi", "mode": "ramp", "variables": ["pm25"],
                           "start_ts": "2016-06-11T00:00:00", "end_ts": None, "label": "x"}],
        "network": {"all": {"loss_rate": 0.15, "delay_ms": 300}},
        "edge_filter": "off", "fleet": {"paused": True, "speedup": 7200},
    }  # fmt: skip
    line = ctl.status_line(state)
    assert "KAPALI" in line and "%15" in line and "300 ms" in line and "duraklatıldı" in line
    assert "7200×" in line
    table = ctl.format_active(state)
    assert (
        table.iloc[0]["Bitiş"] == "reset'e kadar"
        and table.iloc[0]["Başlangıç"] == "2016-06-11 00:00"
    )
    assert ctl.format_active({}).empty


def test_speed_presets_and_payload():
    from airq.dashboard import control as ctl

    assert ctl.SPEED_REALISTIC < ctl.SPEED_FAST
    assert ctl.speed_payload(ctl.SPEED_REALISTIC) == {"action": "speedup", "value": 60.0}
    assert ctl.speed_payload(3600)["value"] == 3600.0
    for bad in (0, -1):  # 0 would mean "as fast as possible" in the fleet
        try:
            ctl.speed_payload(bad)
        except ValueError:
            continue
        raise AssertionError(bad)

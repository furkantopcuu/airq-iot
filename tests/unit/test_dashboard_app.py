"""Run the real Streamlit app (all pages) against the real FastAPI app over HTTP."""

import json
import socket
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from streamlit.testing.v1 import AppTest

import airq.dashboard
from airq.iot.schemas import Ack
from airq.server import api, db

APP = Path(airq.dashboard.__file__).parent / "app.py"
T0 = datetime(2016, 3, 1)
PAGES = [
    "Senaryo Kontrol + Canlı izleme",
    "Ağ görünümü",
    "İstasyon detayı",
    "Uyarılar",
    "Sistem",
    "Deney sonuçları",
]


SCENARIOS = Path(__file__).resolve().parents[2] / "configs" / "scenarios"


class FakeController:
    """Stands in for the MQTT controller: every command is acknowledged, nothing is published."""

    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)

    def wait_acks(self, cmd_id, expect=1, timeout_s=5.0):
        return [Ack(cmd_id=cmd_id, source=f"s{i}", ok=True) for i in range(expect)]


FAKE = FakeController()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def live_api(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("dash")
    con = db.connect(tmp / "t.db")
    for st_name, base in (("Dongsi", 80.0), ("Huairou", 40.0)):
        for h in range(120):
            ts = T0 + timedelta(hours=h)
            sent = datetime(2026, 11, 19, 12, 0, 0)
            db.upsert_reading(con, {
                "station": st_name, "ts": ts.isoformat(), "pm25": base + h % 30, "pm10": 120.0,
                "seq": h, "sent_at": sent.isoformat(timespec="milliseconds"),
                "received_at": (sent + timedelta(milliseconds=4)).isoformat(
                    timespec="milliseconds"
                ),
                "quality_flags": json.dumps([]),
            })  # fmt: skip
        for h in (1, 6, 24):
            made = T0 + timedelta(hours=119)
            db.upsert_prediction(con, {
                "station": st_name, "made_at_ts": made.isoformat(),
                "target_ts": (made + timedelta(hours=h)).isoformat(), "horizon": h,
                "yhat": base + 20 + h, "n_neighbors": 11, "model_version": "v",
            })  # fmt: skip
        db.set_device_status(con, st_name, "online", "2016-03-05T00:00:00")
    con.execute(
        "INSERT INTO warnings VALUES ('Dongsi', ?, 6, 75, 125.0, 'point', 'x')",
        ((T0 + timedelta(hours=119)).isoformat(),),
    )
    con.execute(  # one accepted, still active intervention so the panel has something to show
        "INSERT INTO interventions(cmd_id, station, variables, mode, params, start_ts, label, "
        "acked) VALUES ('demo1', 'Dongsi', '[\"pm25\"]', 'manual', '{\"value\": 250}', ?, "
        "'demo-yerel', 1)",
        ((T0 + timedelta(hours=100)).isoformat(),),
    )
    db.add_event(
        con, "2026-11-19T12:00:00", "edge_stats", json.dumps({"received": 240, "invalid": 0})
    )
    con.commit()
    reports = tmp / "reports"
    (reports / "tables").mkdir(parents=True)
    (reports / "tables" / "rq1_main.csv").write_text("h,model,rmse\n1,B0,19.6\n6,B0,54.9\n")
    (reports / "figures").mkdir()
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(api.create_app(tmp / "t.db", reports, controller=FAKE,
                                           scenarios_dir=SCENARIOS), host="127.0.0.1",
                                           port=port, log_level="error"))  # fmt: skip
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def _run(url: str) -> AppTest:
    import streamlit as st

    st.cache_resource.clear()
    import os

    os.environ["AIRQ_API_URL"] = url
    return AppTest.from_file(str(APP), default_timeout=60).run()


def test_every_page_renders_without_errors_against_the_real_api(live_api):
    at = _run(live_api)
    assert not at.exception
    assert list(at.sidebar.radio[0].options) == PAGES
    for page in PAGES:
        at.sidebar.radio[0].set_value(page).run()
        assert not at.exception, f"{page}: {at.exception}"
        assert not at.error, f"{page}: {[e.value for e in at.error]}"
        assert at.title and at.title[0].value == page


def test_live_page_shows_cards_counts_and_the_station_chart(live_api):
    at = _run(live_api)
    html = " ".join(m.value for m in at.markdown)
    assert "Dongsi" in html and "Huairou" in html and "UYARI (1)" in html
    metrics = {m.label: m.value for m in at.metric}
    assert metrics["Çevrimiçi cihaz"] == "2" and metrics["Aktif uyarı"] == "1"
    assert len(at.get("plotly_chart")) >= 1


def test_station_warning_and_system_pages_show_the_data(live_api):
    at = _run(live_api)
    at.sidebar.radio[0].set_value("Uyarılar").run()
    assert any("Gerçekleşti mi" in df.value.columns for df in at.dataframe)
    at.sidebar.radio[0].set_value("Sistem").run()
    table = " ".join(str(t.value) for t in at.table)
    assert "Çevrimiçi cihaz" in table and "Gecikme" in table


def test_pages_report_a_missing_api_instead_of_crashing():
    at = _run("http://127.0.0.1:9")
    assert not at.exception  # the app survives and shows an error message
    assert at.sidebar.error or at.error


def _sent(kind):
    return [m for m in FAKE.sent if type(m).__name__ == kind]


def test_control_panel_sends_a_device_command_through_the_api(live_api):
    at = _run(live_api)
    n = len(_sent("Command"))
    at.selectbox(key="ctl_target").set_value("Dongsi")
    at.number_input(key="ctl_value").set_value(300.0)
    at.number_input(key="ctl_duration").set_value(4.0)
    at.checkbox(key="ctl_coupled").set_value(True)
    at.text_input(key="ctl_label").set_value("ekrandan")
    at.button(key="ctl_send_device").click().run()
    assert not at.exception
    cmd = _sent("Command")[n]
    assert (cmd.target, cmd.mode, cmd.params, cmd.duration_h) == (
        "Dongsi",
        "manual",
        {"value": 300.0},
        4.0,
    )
    assert cmd.coupled and cmd.label == "ekrandan" and cmd.variables == ["pm25"]
    assert any("Onaylandı" in x.value for x in at.success)


def test_control_panel_shows_the_reason_when_the_api_refuses(live_api):
    at = _run(live_api)
    n = len(_sent("Command"))
    at.selectbox(key="ctl_mode").set_value("ramp")
    at.run()
    at.number_input(key="ctl_duration").set_value(0.0)  # a ramp needs a length
    at.button(key="ctl_send_device").click().run()
    assert len(_sent("Command")) == n  # nothing was published
    assert any("duration_h" in e.value for e in at.error)


def test_control_panel_edge_fleet_network_and_reset_buttons(live_api):
    at = _run(live_api)
    at.radio(key="ctl_edge").set_value("off")
    at.button(key="ctl_edge_apply").click().run()
    assert _sent("EdgeControl")[-1].filter == "off"
    at.button(key="ctl_pause").click().run()
    assert _sent("FleetControl")[-1].action == "pause"
    at.slider(key="ctl_loss").set_value(0.2)
    at.number_input(key="ctl_delay").set_value(300.0)
    at.button(key="ctl_net_apply").click().run()
    net = _sent("NetControl")[-1]
    assert (net.loss_rate, net.delay_ms, net.target) == (0.2, 300.0, "all")
    at.button(key="ctl_reset").click().run()
    assert _sent("FleetControl")[-1].action == "reset" and _sent("EdgeControl")[-1].filter == "on"
    assert not at.exception


def test_active_interventions_and_scoreboard_are_listed(live_api):
    at = _run(live_api)
    frames = [df.value for df in at.dataframe]
    assert any("Etiket" in f.columns and "demo-yerel" in set(f["Etiket"]) for f in frames)
    assert any("Uyarı verildi" in f.columns for f in frames)  # scoreboard columns
    assert any("Edge filtresi" in c.value for c in at.caption)


def test_scenario_can_be_started_from_the_panel(live_api):
    at = _run(live_api)
    at.selectbox(key="ctl_scenario").set_value("bolgesel_artis")
    at.button(key="ctl_run_scenario").click().run()
    assert not at.exception and any("Senaryo başladı" in x.value for x in at.success)
    at.button(key="ctl_reset").click().run()  # stops the player

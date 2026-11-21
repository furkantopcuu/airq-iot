"""Streamlit dashboard (reads ONLY from the API). Run: streamlit run src/airq/dashboard/app.py

Large fonts and a colour-blind-safe palette for a projector; units on every axis.
Pages: scenario control + live monitoring, network view, station detail, warnings, system,
experiment results.
"""

import pandas as pd
import streamlit as st

from airq.dashboard import control as ctl
from airq.dashboard import data as dash
from airq.dashboard.client import ApiClient, ApiError

st.set_page_config(page_title="airq-iot", page_icon="🌫️", layout="wide")
st.markdown(
    "<style>html, body, [class*='css'] {font-size: 18px;} "
    "h1, h2, h3 {font-weight: 800;} .block-container {padding-top: 1.5rem;}</style>",
    unsafe_allow_html=True,
)
FIGURES = [
    ("eda_corr_missing", "Veri: korelasyon ve eksik veri"),
    ("rq1_horizon", "RQ1: ufuk bazında RMSE ve kazanç"),
    ("rq1_ablation_loso", "RQ1: komşu ablasyonu ve LOSO"),
    ("rq1_shap_groups", "RQ1: SHAP grup payları"),
    ("rq2_pr_lead", "RQ2: PR eğrisi ve öncül süre"),
    ("rq2_haze_example", "RQ2: haze epizodu örneği"),
]
PAGES = [
    "Senaryo Kontrol + Canlı izleme",
    "Ağ görünümü",
    "İstasyon detayı",
    "Uyarılar",
    "Sistem",
    "Deney sonuçları",
]


@st.cache_resource
def get_api() -> ApiClient:
    return ApiClient()


api = get_api()
page = st.sidebar.radio("Sayfa", PAGES)
refresh = st.sidebar.slider("Yenileme aralığı (sn)", 1, 5, 2)
try:
    api.get("/health")
    st.sidebar.success(f"API bağlı: {api.base_url}")
except ApiError as exc:
    st.sidebar.error(str(exc))


def load_cards() -> list[dict]:
    cards = []
    for info in api.get("/stations"):
        rows = api.get(f"/forecast/{info['station']}", hours=6)
        cards.append(dash.station_card(info, rows))
    return cards


def render_cards(cards: list[dict], columns: int = 4) -> None:
    cols = st.columns(columns)
    for i, card in enumerate(cards):
        cols[i % columns].markdown(dash.card_html(card), unsafe_allow_html=True)


def station_chart(station: str, hours: int) -> None:
    readings = api.get(f"/readings/{station}", hours=hours)
    forecast = api.get(f"/forecast/{station}", hours=hours)
    warns = api.get("/warnings", station=station)
    last = readings[-1]["ts"] if readings else None
    if last:
        warns = [w for w in warns if w["made_at_ts"] >= readings[0]["ts"]]
    st.plotly_chart(
        dash.station_figure(readings, forecast, warns, title=station), use_container_width=True
    )


def live(render) -> None:
    """Run `render` as a fragment that refreshes itself every `refresh` seconds."""
    st.fragment(run_every=refresh)(render)()


def send(path: str, body: dict | None = None) -> None:
    """POST a control command and keep the one-line outcome for the panel."""
    try:
        ok, text = ctl.result_text(api.post(path, body))
    except ApiError as exc:
        ok, text = False, str(exc)
    st.session_state["ctl_result"] = (ok, text)


def control_panel(names: list[str]) -> None:
    """Senaryo Kontrol: device interventions, fleet, network, edge filter, scenarios (spec 9)."""
    st.subheader("Senaryo Kontrol")
    with st.expander("Müdahale (cihaz)", expanded=True):
        target = st.selectbox("İstasyon", [ctl.ALL, *names], key="ctl_target")
        variables = st.multiselect("Değişken", ["pm25", "pm10"], default=["pm25"], key="ctl_vars")
        mode = st.selectbox("Mod", list(ctl.MODE_LABELS), format_func=ctl.MODE_LABELS.get,
                            key="ctl_mode")  # fmt: skip
        kw: dict = {}
        if mode == "manual":
            kw["value"] = st.number_input("Değer (µg/m³)", value=250.0, key="ctl_value")
        elif mode == "offset":
            kw["delta"] = st.number_input("Eklenecek (µg/m³)", value=50.0, key="ctl_delta")
        elif mode == "scale":
            kw["factor"] = st.number_input("Çarpan", value=1.5, key="ctl_factor")
        elif mode == "ramp":
            kw["ramp_kind"] = st.radio("Rampa", ["target", "delta"], horizontal=True,
                                       format_func={"target": "hedefe", "delta": "artış"}.get,
                                       key="ctl_ramp_kind")  # fmt: skip
            kw["ramp_value"] = st.number_input("Hedef / artış (µg/m³)", value=200.0, key="ctl_ramp")
        elif mode == "perturb":
            kw["perturb_type"] = st.selectbox("Hata türü", list(ctl.PERTURB_LABELS),
                                              format_func=ctl.PERTURB_LABELS.get,
                                              key="ctl_ptype")  # fmt: skip
            if kw["perturb_type"] == "spike":
                kw["severity"] = st.selectbox("Şiddet k (σ)", [3, 5, 8], index=1, key="ctl_sev")
        if mode != "replay":
            kw["duration_h"] = st.number_input(
                "Süre (saat, 0 = sıfırlayana kadar; rampada rampa uzunluğu)",
                min_value=0.0, value=6.0, key="ctl_duration",
            )  # fmt: skip
        kw["coupled"] = st.checkbox("PM10 birlikte değişsin (coupled)", key="ctl_coupled")
        kw["allow_invalid"] = st.checkbox(
            "Hatalı girdi testi (fiziksel sınırı aşan değerlere izin ver)", key="ctl_invalid"
        )
        kw["label"] = st.text_input("Etiket", key="ctl_label")
        if st.button("Müdahaleyi gönder", key="ctl_send_device", type="primary"):
            send("/control/device", ctl.device_payload(target, variables, mode, **kw))
    with st.expander("Filo"):
        c1, c2 = st.columns(2)
        if c1.button("Duraklat", key="ctl_pause"):
            send("/control/fleet", {"action": "pause"})
        if c2.button("Devam", key="ctl_resume"):
            send("/control/fleet", {"action": "resume"})
        s1, s2 = st.columns(2)
        if s1.button("Hızlı (3600×)", key="ctl_speed_fast", help="1 sn = 1 simüle saat"):
            send("/control/fleet", ctl.speed_payload(ctl.SPEED_FAST))
        if s2.button("Gerçekçi (60×)", key="ctl_speed_real", help="1 dk = 1 simüle saat"):
            send("/control/fleet", ctl.speed_payload(ctl.SPEED_REALISTIC))
        speed = st.number_input("Özel hız (×; 3600 = 1 sn = 1 saat)", min_value=1.0, value=3600.0,
                                key="ctl_speed")  # fmt: skip
        if st.button("Hızı uygula", key="ctl_speedup"):
            send("/control/fleet", ctl.speed_payload(speed))
    with st.expander("Ağ"):
        net_target = st.selectbox("Hedef", [ctl.ALL, *names], key="ctl_net_target")
        loss = st.slider("Mesaj kaybı", 0.0, 0.5, 0.0, 0.05, key="ctl_loss")
        delay = st.number_input("Gecikme (ms)", min_value=0.0, value=0.0, key="ctl_delay")
        jitter = st.number_input("Jitter (ms)", min_value=0.0, value=0.0, key="ctl_jitter")
        reorder = st.slider("Sırasızlık", 0.0, 0.5, 0.0, 0.05, key="ctl_reorder")
        n1, n2 = st.columns(2)
        if n1.button("Ağı uygula", key="ctl_net_apply"):
            send("/control/network", ctl.network_payload(net_target, loss, delay, jitter, reorder))
        if n2.button("Ağı sıfırla", key="ctl_net_reset"):
            send("/control/network", {"target": net_target, "reset": True})
    with st.expander("Edge doğrulama filtresi"):
        choice = st.radio("Filtre", ["on", "off"], horizontal=True, key="ctl_edge",
                          format_func={"on": "Açık", "off": "Kapalı"}.get)  # fmt: skip
        if st.button("Filtreyi uygula", key="ctl_edge_apply"):
            send("/control/edge", {"filter": choice})
    with st.expander("Hazır senaryolar"):
        try:
            scenarios = api.get("/control/scenarios")
        except ApiError as exc:
            scenarios = []
            st.error(str(exc))
        if scenarios:
            by_name = {s["name"]: s for s in scenarios}
            name = st.selectbox("Senaryo", list(by_name), key="ctl_scenario")
            st.caption(by_name[name]["description"])
            if st.button("Senaryoyu çalıştır", key="ctl_run_scenario"):
                send(f"/control/scenario/{name}")
    if st.button("Her şeyi sıfırla", key="ctl_reset"):
        send("/control/reset")
    if "ctl_result" in st.session_state:
        ok, text = st.session_state["ctl_result"]
        (st.success if ok else st.error)(text)


def active_and_scorecard() -> None:
    """Right-hand lower part: what is in force now, and the scoreboard (spec 9.6)."""
    try:
        state = api.get("/control/active")
        board = api.get("/control/scorecard")
    except ApiError as exc:
        st.error(str(exc))
        return
    st.caption(ctl.status_line(state))
    scenario = state.get("scenario")
    if scenario and scenario.get("name"):
        st.progress(scenario["steps_fired"] / max(scenario["steps_total"], 1),
                    text=f"Senaryo: {scenario['name']} ({scenario['steps_fired']}/"
                         f"{scenario['steps_total']} adım)")  # fmt: skip
    active = ctl.format_active(state)
    st.markdown("**Aktif müdahaleler**")
    if active.empty:
        st.info("Aktif müdahale yok (veri kayıtlı haliyle oynuyor).")
    else:
        st.dataframe(active, use_container_width=True, hide_index=True)
    st.markdown("**Puan tablosu**")
    table = ctl.format_scorecard(board["rows"])
    if table.empty:
        st.info("Henüz puanlanacak müdahale yok.")
    else:
        st.caption(f"Referans: {board['reference']}")
        st.dataframe(table, use_container_width=True, hide_index=True)


def page_live() -> None:
    st.title("Senaryo Kontrol + Canlı izleme")
    try:
        names = [i["station"] for i in api.get("/stations")]
    except ApiError as exc:
        st.error(str(exc))
        return
    left, right = st.columns([1, 3])
    with left:
        control_panel(names)

    def body():
        try:
            cards = load_cards()
        except ApiError as exc:
            st.error(str(exc))
            return
        c1, c2, c3 = st.columns(3)
        c1.metric("Çevrimiçi cihaz", sum(c["online"] for c in cards))
        c2.metric("Aktif uyarı", sum(c["n_warnings"] for c in cards))
        last_ts = max((c["last_ts"] or "" for c in cards), default="")
        c3.metric("Son benzetim saati", last_ts.replace("T", " ")[:16] or "—")
        render_cards(cards, columns=4)
        station = st.selectbox("İstasyon", names, key="live_station") if names else None
        if station:
            station_chart(station, 72)
        active_and_scorecard()

    with right:
        live(body)


def page_network() -> None:
    st.title("Ağ görünümü")
    live(lambda: render_cards(load_cards(), columns=4))


def page_station() -> None:
    st.title("İstasyon detayı")
    names = [i["station"] for i in api.get("/stations")]
    if not names:
        st.warning("Henüz veri yok.")
        return
    station = st.selectbox("İstasyon", names)
    hours = st.slider("Geçmiş penceresi (saat)", 24, 240, 72)

    def body():
        station_chart(station, hours)
        rows = api.get(f"/readings/{station}", hours=12)
        st.subheader("Son ölçümler")
        st.dataframe(pd.DataFrame(rows).iloc[::-1], use_container_width=True, hide_index=True)

    live(body)


def page_warnings() -> None:
    st.title("Uyarılar")
    names = ["(tümü)"] + [i["station"] for i in api.get("/stations")]
    station = st.selectbox("İstasyon", names)

    def body():
        warns = api.get("/warnings", station=None if station == "(tümü)" else station)
        if not warns:
            st.info("Henüz uyarı yok.")
            return
        readings = {s: api.get(f"/readings/{s}", hours=240) for s in {w["station"] for w in warns}}
        st.dataframe(pd.DataFrame(dash.warnings_table(warns, readings)), use_container_width=True,
                     hide_index=True)  # fmt: skip

    live(body)


def page_system() -> None:
    st.title("Sistem")

    def body():
        stats = api.get("/system/stats")
        st.table(
            pd.DataFrame(dash.system_summary(stats), columns=["Ölçüt", "Değer"]).set_index("Ölçüt")
        )

    live(body)


def page_results() -> None:
    st.title("Deney sonuçları")
    st.caption("reports/ altındaki RQ1–RQ2 sonuçları (API üzerinden).")
    st.subheader("Şekiller")
    for name, title in FIGURES:
        png = api.get_bytes(f"/figures/{name}")
        if png:
            st.image(png, caption=title, use_container_width=True)
    st.subheader("Tablolar")
    tables = api.get("/tables")
    if tables:
        name = st.selectbox(
            "Tablo", tables, index=tables.index("rq1_main") if "rq1_main" in tables else 0
        )
        t = api.get(f"/tables/{name}", limit=2000)
        df = dash.numeric_where_possible(pd.DataFrame(t["rows"], columns=t["columns"]))
        st.dataframe(df, use_container_width=True, hide_index=True)


try:
    {
        "Senaryo Kontrol + Canlı izleme": page_live,
        "Ağ görünümü": page_network,
        "İstasyon detayı": page_station,
        "Uyarılar": page_warnings, "Sistem": page_system, "Deney sonuçları": page_results,
    }[page]()  # fmt: skip
except ApiError as exc:
    st.error(str(exc))

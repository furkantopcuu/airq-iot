"""Streamlit dashboard (reads ONLY from the API). Run: streamlit run src/airq/dashboard/app.py

Large fonts and a colour-blind-safe palette for a projector; units on every axis.
Pages: live monitoring, network view, station detail, warnings, system, experiment results.
"""

import pandas as pd
import streamlit as st

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
PAGES = ["Canlı izleme", "Ağ görünümü", "İstasyon detayı", "Uyarılar", "Sistem", "Deney sonuçları"]


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


def page_live() -> None:
    st.title("Canlı izleme")

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
        left, right = st.columns([1, 3])
        with left:
            st.info(
                "Senaryo Kontrol paneli (müdahale, ağ ve edge kontrolü) ileride bu alana eklenecek."
            )
            names = [c["station"] for c in cards]
            station = st.selectbox("İstasyon", names, key="live_station") if names else None
        with right:
            render_cards(cards, columns=4)
        if station:
            station_chart(station, 72)

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
        "Canlı izleme": page_live, "Ağ görünümü": page_network, "İstasyon detayı": page_station,
        "Uyarılar": page_warnings, "Sistem": page_system, "Deney sonuçları": page_results,
    }[page]()  # fmt: skip
except ApiError as exc:
    st.error(str(exc))

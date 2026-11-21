"""Streamlit dashboard (reads ONLY from the API). Run: streamlit run src/airq/dashboard/app.py

Large fonts and a colour-blind-safe palette for a projector; units on every axis.
Pages: scenario control + live monitoring, network view, station detail, warnings, system,
experiment results.
"""

import os

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


def warmup_left() -> float | None:
    """Demo only: hours of replay left until the forecaster has its 240 h of history."""
    until = os.environ.get("AIRQ_WARMUP_UNTIL")
    if not until:
        return None
    try:
        return dash.warmup_left_hours(until, api.get("/control/active").get("sim_now"))
    except ApiError:
        return None


def load_cards() -> list[dict]:
    cards = []
    left = warmup_left()
    for info in api.get("/stations"):
        rows = api.get(f"/forecast/{info['station']}", hours=6)
        cards.append(dash.station_card(info, rows, left))
    return cards


def render_cards(cards: list[dict], columns: int = 4) -> None:
    cols = st.columns(columns)
    for i, card in enumerate(cards):
        cols[i % columns].markdown(dash.card_html(card), unsafe_allow_html=True)


STATION_CHART_HELP = (
    "Siyah çizgi: ölçüm. Mavi noktalı çizgi ve bant: geçmiş 6 saatlik tahminler ve q10–q90 "
    "aralığı (gerçek değerin %80 olasılıkla içinde olduğu bant). Elmaslar: son 1, 6 ve 24 saatlik "
    "tahmin. Üçgenler: uyarı (hedef saatte). Kesikli çizgiler: 75 ve 150 µg/m³ eşikleri."
)


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


def fleet_state() -> dict:
    try:
        return api.get("/control/active")
    except ApiError:
        return {}


def control_panel(names: list[str]) -> None:
    """Senaryo Kontrol: scenarios, device interventions, pace, network, edge filter (spec 9)."""
    st.subheader("Kontrol paneli")
    st.caption(
        "Bir hazır senaryo çalıştır ya da kendin bir müdahale gönder. Etkisi sağdaki kartlarda, "
        "grafikte ve puan tablosunda görünür."
    )
    with st.expander("1 · Hazır senaryolar", expanded=True):
        try:
            scenarios = api.get("/control/scenarios")
        except ApiError as exc:
            scenarios = []
            st.error(str(exc))
        if scenarios:
            by_name = {s["name"]: s for s in scenarios}
            name = st.selectbox("Senaryo", list(by_name), key="ctl_scenario")
            st.caption(by_name[name]["description"])
            if st.button(
                "Senaryoyu çalıştır",
                key="ctl_run_scenario",
                type="primary",
                use_container_width=True,
            ):
                send(f"/control/scenario/{name}")
    with st.expander("2 · Müdahale (bir istasyon ya da hepsi)"):
        target = st.selectbox(
            "İstasyon",
            [ctl.ALL, *names],
            key="ctl_target",
            help="'all': tüm istasyonlara uygulanır",
        )
        variables = st.multiselect(
            "Değişken", ["pm25", "pm10"], default=["pm25"], key="ctl_vars",
            help="Hangi ölçüm değişsin: PM2.5 ve/veya PM10 (µg/m³)",
        )  # fmt: skip
        mode = st.selectbox("Mod", list(ctl.MODE_LABELS), format_func=ctl.MODE_LABELS.get,
                            key="ctl_mode")  # fmt: skip
        st.caption(ctl.MODE_HELP[mode])
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
                kw["severity"] = st.selectbox(
                    "Şiddet k (σ)", [3, 5, 8], index=1, key="ctl_sev",
                    help="Sıçramanın büyüklüğü: ölçümün standart sapmasının kaç katı",
                )  # fmt: skip
        if mode != "replay":
            kw["duration_h"] = st.number_input(
                "Süre (simüle saat)", min_value=0.0, value=6.0, key="ctl_duration",
                help="0 = sıfırlayana kadar sürer; rampada rampanın uzunluğudur",
            )  # fmt: skip
        kw["coupled"] = st.checkbox(
            "PM10 birlikte değişsin", key="ctl_coupled",
            help="Açıksa PM10 da PM2.5 ile birlikte oranlı değişir (coupled)",
        )  # fmt: skip
        kw["allow_invalid"] = st.checkbox(
            "Hatalı girdi testi", key="ctl_invalid",
            help="Fiziksel sınırı aşan değerlere izin verir (edge filtresini sınamak için)",
        )  # fmt: skip
        kw["label"] = st.text_input("Etiket (isteğe bağlı)", key="ctl_label",
                                    help="Puan tablosunda bu müdahalenin adı")  # fmt: skip
        if st.button(
            "Müdahaleyi gönder", key="ctl_send_device", type="primary", use_container_width=True
        ):
            send("/control/device", ctl.device_payload(target, variables, mode, **kw))
    with st.expander("3 · Hız ve duraklatma", expanded=True):
        state = fleet_state()
        fleet = state.get("fleet") or {}
        if fleet:
            now = "duraklatıldı" if fleet.get("paused") else "çalışıyor"
            speed_now = fleet.get("speedup")
            st.caption(f"Şu an: {now}" + (f", hız {speed_now:g}×" if speed_now else ""))
        c1, c2 = st.columns(2)
        if c1.button("Duraklat", key="ctl_pause", help="Yeni ölçüm gelmez"):
            send("/control/fleet", {"action": "pause"})
        if c2.button("Devam", key="ctl_resume"):
            send("/control/fleet", {"action": "resume"})
        left = warmup_left()
        if left:
            st.warning(
                f"Isınma sürüyor (tahmin için ≈{left:.0f} simüle saat kaldı). "
                "Hızı şimdi yavaşlatma: tahmin gecikir."
            )
        if st.button("Hızlı (3600×)", key="ctl_speed_fast", help="1 sn = 1 simüle saat",
                     use_container_width=True):  # fmt: skip
            send("/control/fleet", ctl.speed_payload(ctl.SPEED_FAST))
        if st.button("Gerçekçi (60×)", key="ctl_speed_real", help="1 dk = 1 simüle saat",
                     use_container_width=True):  # fmt: skip
            send("/control/fleet", ctl.speed_payload(ctl.SPEED_REALISTIC))
        st.caption(
            "Hızlı: değerler saniyede bir saat ilerler (sunum için). "
            "Gerçekçi: her istasyon dakikada bir yeni ölçüm alır."
        )
        speed = st.number_input("Özel hız (×)", min_value=1.0, value=3600.0, key="ctl_speed",
                                help="3600 = 1 sn'de 1 simüle saat")  # fmt: skip
        if st.button("Hızı uygula", key="ctl_speedup", use_container_width=True):
            send("/control/fleet", ctl.speed_payload(speed))
    with st.expander("4 · Ağ bozulması"):
        st.caption("Mesajların ağda bozulmasını taklit eder (uygulama katmanında).")
        net_target = st.selectbox("Hedef", [ctl.ALL, *names], key="ctl_net_target")
        loss = st.slider("Mesaj kaybı", 0.0, 0.5, 0.0, 0.05, key="ctl_loss",
                         help="Hiç yayınlanmayan mesajların oranı")  # fmt: skip
        delay = st.number_input("Gecikme (ms)", min_value=0.0, value=0.0, key="ctl_delay")
        jitter = st.number_input("Jitter (ms)", min_value=0.0, value=0.0, key="ctl_jitter",
                                 help="Gecikmenin rastgele değişimi")  # fmt: skip
        reorder = st.slider("Sırasızlık", 0.0, 0.5, 0.0, 0.05, key="ctl_reorder",
                            help="Mesajların sırasının karışma oranı")  # fmt: skip
        n1, n2 = st.columns(2)
        if n1.button("Ağı uygula", key="ctl_net_apply"):
            send("/control/network", ctl.network_payload(net_target, loss, delay, jitter, reorder))
        if n2.button("Ağı sıfırla", key="ctl_net_reset"):
            send("/control/network", {"target": net_target, "reset": True})
    with st.expander("5 · Edge doğrulama filtresi"):
        st.caption(
            "Açıkken edge, 5 kurala uymayan değeri güvenilmez işaretler (tahmin onu kullanmaz); "
            "kapalıyken değer olduğu gibi geçer."
        )
        choice = st.radio("Filtre", ["on", "off"], horizontal=True, key="ctl_edge",
                          format_func={"on": "Açık", "off": "Kapalı"}.get)  # fmt: skip
        if st.button("Filtreyi uygula", key="ctl_edge_apply", use_container_width=True):
            send("/control/edge", {"filter": choice})
    if st.button(
        "Her şeyi sıfırla", key="ctl_reset", use_container_width=True,
        help="Müdahaleleri, ağ bozulmasını ve senaryoyu temizler",
    ):  # fmt: skip
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


HOW_TO_READ = """
**Kartlar:** her kart bir istasyondur. Büyük sayı son ölçülen **PM2.5** (µg/m³); renk ve yazı
kirlilik sınıfını gösterir (renk anahtarı kartların üstünde).

**Tahmin +1 / +6 / +24 sa:** modelin 1, 6 ve 24 saat sonrası için tahmini. Model 240 simüle saatlik
geçmiş istediği için demo başında "ısınıyor" yazar.

**⚠ UYARI:** tahmin bir eşiği (75 ya da 150 µg/m³) aşacak görününce üretilir. Kartta yazan sayı
**son 24 simüle saatteki uyarı kaydı** sayısıdır; bir kayıt = bir ufuk + bir eşik. Tek bir kirlilik
dalgası bu yüzden birden çok kayıt üretir. Ayrıntılar: Uyarılar sayfası.

**Kontrol paneli:** soldan hazır senaryo çalıştır ya da kendin müdahale gönder; **Hız** bölümünde
Hızlı (sunum) ve Gerçekçi (yavaş) hız arasında geçiş yapılır. Sonuç grafikte ve **Puan tablosu**nda
görünür.
"""


def page_live() -> None:
    st.title("Senaryo Kontrol + Canlı izleme")
    try:
        names = [i["station"] for i in api.get("/stations")]
    except ApiError as exc:
        st.error(str(exc))
        return
    with st.expander("Bu ekranı nasıl okurum?"):
        st.markdown(HOW_TO_READ)
    left, right = st.columns([1.2, 3])
    with left:
        control_panel(names)

    def body():
        try:
            cards = load_cards()
        except ApiError as exc:
            st.error(str(exc))
            return
        state = fleet_state()
        for level, text in dash.status_messages(cards, state, warmup_left()):
            {"info": st.info, "warning": st.warning, "success": st.success}[level](text)
        n = len(cards)
        c1, c2 = st.columns(2)
        c1.metric("Çevrimiçi cihaz", f"{sum(c['online'] for c in cards)} / {n}")
        c2.metric(
            "Uyarı veren istasyon", f"{sum(c['warning'] for c in cards)} / {n}",
            help=dash.WARNING_HELP,
        )  # fmt: skip
        last_ts = max((c["last_ts"] or "" for c in cards), default="")
        st.caption(f"Benzetim saati (son ölçüm): {last_ts.replace('T', ' ')[:16] or '—'}")
        st.markdown(dash.legend_html(), unsafe_allow_html=True)
        render_cards(cards, columns=4)
        station = st.selectbox("Grafik için istasyon", names, key="live_station") if names else None
        if station:
            station_chart(station, 72)
            st.caption(STATION_CHART_HELP)
        active_and_scorecard()

    with right:
        live(body)


def page_network() -> None:
    st.title("Ağ görünümü")
    st.caption(
        "İstasyonların anlık durumu. Kartlardaki alanların anlamı için ilk sayfadaki "
        '"Bu ekranı nasıl okurum?" bölümüne bak.'
    )
    st.markdown(dash.legend_html(), unsafe_allow_html=True)
    live(lambda: render_cards(load_cards(), columns=4))


def page_station() -> None:
    st.title("İstasyon detayı")
    names = [i["station"] for i in api.get("/stations")]
    if not names:
        st.warning("Henüz veri yok.")
        return
    station = st.selectbox("İstasyon", names)
    hours = st.slider("Geçmiş penceresi (simüle saat)", 24, 240, 72)

    def body():
        station_chart(station, hours)
        st.caption(STATION_CHART_HELP)
        rows = api.get(f"/readings/{station}", hours=12)
        st.subheader("Son ölçümler")
        st.dataframe(pd.DataFrame(rows).iloc[::-1], use_container_width=True, hide_index=True)

    live(body)


def page_warnings() -> None:
    st.title("Uyarılar")
    st.caption(
        "Her satır bir uyarı kaydıdır: o saatte, o ufuk için, o eşiğin aşılacağı tahmin edildi. "
        '"Gerçekleşti mi": hedef saatteki ölçüm eşiği gerçekten aştı mı.'
    )
    names = ["(tümü)"] + [i["station"] for i in api.get("/stations")]
    station = st.selectbox("İstasyon", names)

    def body():
        warns = api.get("/warnings", station=None if station == "(tümü)" else station)
        if not warns:
            st.info("Henüz uyarı yok.")
            return
        readings = {s: api.get(f"/readings/{s}", hours=240) for s in {w["station"] for w in warns}}
        rows = sorted(dash.warnings_table(warns, readings), key=lambda r: r["Uyarı zamanı"],
                      reverse=True)  # fmt: skip
        known = [r for r in rows if r["Gerçekleşti mi"] != "bilinmiyor"]
        hit = sum(r["Gerçekleşti mi"] == "evet" for r in known)
        st.markdown(
            f"**{len(rows)} kayıt**, {len({r['İstasyon'] for r in rows})} istasyon"
            + (f" · hedef saati bilinenlerin {hit} / {len(known)}'i gerçekleşti" if known else "")
        )
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    live(body)


def page_system() -> None:
    st.title("Sistem")
    st.caption(
        "IoT hattının sağlığı: kaç cihaz bağlı, kaç benzersiz mesaj geldi, tekrar (QoS 1) oranı, "
        "cihazdan veritabanına gecikme (ms) ve edge doğrulamasının saydıkları."
    )

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

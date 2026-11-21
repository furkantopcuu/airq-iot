"""Dashboard logic without Streamlit: AQI bands, station cards, figures (unit-testable)."""

from __future__ import annotations

import html
from datetime import datetime, timedelta

import pandas as pd
import plotly.graph_objects as go

AQI_BOUNDS = (35, 75, 115, 150, 250)  # HJ 633-2012 PM2.5 bands (configs: aqi_bands_pm25)
# colour-blind-safe, sequential from clean to severe; text colour keeps the contrast readable
AQI_BANDS = [
    {"label": "Mükemmel", "color": "#56B4E9", "text": "#000000"},
    {"label": "İyi", "color": "#009E73", "text": "#FFFFFF"},
    {"label": "Hafif kirli", "color": "#F0E442", "text": "#000000"},
    {"label": "Orta kirli", "color": "#E69F00", "text": "#000000"},
    {"label": "Ağır kirli", "color": "#D55E00", "text": "#FFFFFF"},
    {"label": "Çok ağır kirli", "color": "#4B0F6B", "text": "#FFFFFF"},
]
UNKNOWN_BAND = {"label": "Veri yok", "color": "#BBBBBB", "text": "#000000", "index": None}
THRESHOLDS = (75, 150)
HORIZONS = (1, 6, 24)


def aqi_band(pm25: float | None, bounds: tuple[float, ...] = AQI_BOUNDS) -> dict:
    """Band (label, colours, index) for a PM2.5 value in µg/m³; unknown when missing."""
    if pm25 is None or pm25 != pm25:  # None or NaN
        return dict(UNKNOWN_BAND)
    idx = sum(pm25 > b for b in bounds)
    return {**AQI_BANDS[idx], "index": idx}


def latest_forecasts(rows: list[dict]) -> dict[int, dict]:
    """The most recent forecast per horizon (largest made_at_ts)."""
    out: dict[int, dict] = {}
    for r in rows:
        cur = out.get(r["horizon"])
        if cur is None or r["made_at_ts"] > cur["made_at_ts"]:
            out[r["horizon"]] = r
    return out


def warmup_left_hours(until: str | None, sim_now: str | None) -> float | None:
    """Simulated hours until the forecaster has its history (None: not warming up / unknown)."""
    if not until or not sim_now:
        return None
    try:
        left = (_dt(until) - _dt(sim_now)).total_seconds() / 3600
    except ValueError:
        return None
    return left if left > 0 else None


def station_card(info: dict, forecast_rows: list[dict], warmup_left: float | None = None) -> dict:
    """Everything one network card shows: status, last value, band, forecasts, warning badge."""
    latest = latest_forecasts(forecast_rows)
    f6 = latest.get(6)
    last = info.get("last_pm25")
    return {
        "station": info["station"],
        "online": info.get("status") == "online",
        "last_ts": info.get("last_ts"),
        "last_pm25": last,
        "band": aqi_band(last),
        "forecast6": f6["yhat"] if f6 else None,
        "forecast6_band": aqi_band(f6["yhat"]) if f6 else dict(UNKNOWN_BAND),
        "forecasts": {h: latest[h]["yhat"] for h in HORIZONS if h in latest},
        "warmup_left": None if f6 else warmup_left,
        "n_neighbors": f6["n_neighbors"] if f6 else None,
        "warning": info.get("active_warnings", 0) > 0,
        "n_warnings": info.get("active_warnings", 0),
        "flags": info.get("quality_flags", []),
    }


WARNING_HELP = (
    "Son 24 simüle saatte bu istasyon için üretilen uyarı kayıtlarının sayısı. Her kayıt bir ufuk "
    "(1, 6 ya da 24 saat) ve bir eşik (75 ya da 150 µg/m³) çiftidir; bu yüzden tek bir kirlilik "
    "dalgası birden çok kayıt üretir. Ayrı ayrı görmek için Uyarılar sayfasına bak."
)


def legend_html() -> str:
    """The colour key of the cards: PM2.5 ranges (µg/m³) and the class name, text beside colour."""
    edges = [0, *AQI_BOUNDS]
    parts = []
    for i, band in enumerate(AQI_BANDS):
        lo = edges[i]
        rng = (
            f"≤ {AQI_BOUNDS[0]}"
            if i == 0
            else (f"> {AQI_BOUNDS[-1]}" if i == len(AQI_BANDS) - 1 else f"{lo + 1}–{AQI_BOUNDS[i]}")
        )
        parts.append(
            f"<span style='background:{band['color']};color:{band['text']};padding:2px 8px;"
            f"border-radius:4px;margin:0 6px 4px 0;display:inline-block;white-space:nowrap'>"
            f"{html.escape(band['label'])} <b>{rng}</b></span>"
        )
    return "<div style='font-size:0.8em'>PM2.5 (µg/m³) sınıfları: " + "".join(parts) + "</div>"


def card_html(card: dict) -> str:
    """HTML of one card (large font, high contrast, status in text as well as colour)."""
    # station names, flags and labels travel through MQTT: they are DATA, never markup
    esc = html.escape
    b = card["band"]
    last = "—" if card["last_pm25"] is None else f"{card['last_pm25']:.0f}"
    dot = "● çevrimiçi" if card["online"] else "○ çevrimdışı"
    chips = ""
    for h in HORIZONS:
        v = card.get("forecasts", {}).get(h)
        if v is None and h == 6 and card.get("forecast6") is not None:
            v = card["forecast6"]
        if v is None:
            continue
        fb = aqi_band(v)
        chips += (
            f"<span title='{h} saat sonrası için tahmin ({esc(fb['label'])})' "
            f"style='background:{fb['color']};color:{fb['text']};padding:1px 6px;"
            f"border-radius:3px;margin-right:4px;white-space:nowrap'>+{h} sa <b>{v:.0f}</b></span>"
        )
    if not chips:
        if card.get("warmup_left"):
            chips = (
                "<i>ısınıyor</i> <span style='font-size:0.8em'>"
                f"(tahmin ≈{card['warmup_left']:.0f} simüle saat sonra)</span>"
            )
        else:
            chips = "—"
    badge = (
        f"<div title='{esc(WARNING_HELP)}' style='background:#000;color:#fff;padding:2px 8px;"
        "margin-top:6px;display:inline-block;border-radius:4px'>"
        f"<b>⚠ UYARI</b> <span style='font-size:0.8em'>{card['n_warnings']} kayıt · son 24 sa"
        "</span></div>"
        if card["warning"]
        else ""
    )
    flags = (
        f"<div style='font-size:0.8em'>kalite: {esc(', '.join(card['flags']))}</div>"
        if card["flags"]
        else ""
    )
    return (
        f"<div style='border:3px solid {b['color']};border-radius:8px;"
        "padding:8px 10px;margin-bottom:8px'>"
        f"<div style='font-size:1.1em;font-weight:700'>{esc(str(card['station']))}</div>"
        f"<div style='font-size:0.75em'>{dot}</div>"
        f"<div style='background:{b['color']};color:{b['text']};padding:4px 8px;"
        f"border-radius:4px;margin-top:4px'><span style='font-size:1.8em;font-weight:800'>{last}"
        f"</span> <span style='font-size:0.8em'>µg/m³</span><br>"
        f"<span style='font-size:0.85em'>{esc(b['label'])}</span></div>"
        f"<div style='margin-top:6px;font-size:0.85em'>Tahmin (µg/m³): {chips}</div>"
        f"{badge}{flags}</div>"
    )


def status_messages(
    cards: list[dict], state: dict | None, warmup_left: float | None
) -> list[tuple[str, str]]:
    """What the operator must know right now, as (level, text) with level info|warning|success."""
    out: list[tuple[str, str]] = []
    fleet = (state or {}).get("fleet") or {}
    online = sum(c["online"] for c in cards)
    if cards and online == 0:
        out.append(
            (
                "warning",
                "Hiçbir cihaz çevrimiçi değil: veri tekrarı bitmiş ya da filo durmuş olabilir. "
                "Yeniden başlatmak için demoyu kapatıp `demo.ps1 -StopOld` çalıştır.",
            )
        )
    elif fleet.get("paused"):
        out.append(("warning", "Filo duraklatıldı: yeni ölçüm gelmiyor. Filo > Devam ile sürdür."))
    if warmup_left:
        out.append(
            (
                "info",
                "Tahmin modeli ısınıyor: 240 simüle saatlik geçmiş gerekir, "
                f"≈{warmup_left:.0f} saat kaldı. Bu sürede kartlarda tahmin görünmez; "
                "hızı yavaşlatma.",
            )
        )
    if not out and cards:
        speed = fleet.get("speedup")
        what = "1 sn = 1 simüle saat" if speed and speed >= 1000 else "yavaş, gerçekçi hız"
        pace = f" Hız {speed:g}× ({what})." if speed else ""
        out.append(("success", f"Çalışıyor: {online} / {len(cards)} cihaz çevrimiçi.{pace}"))
    return out


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s)


def display_offset(sim_now: str | None, now: datetime | None = None) -> timedelta | None:
    """Shift that makes the newest replayed timestamp read as the current date and time.

    The data is a recorded 2016-2017 Beijing series played back as if live; for display the
    timeline is moved so that "now" is today. Differences between points stay exactly as recorded.
    None when the simulated clock is unknown (nothing is shifted)."""
    if not sim_now:
        return None
    try:
        return (now or datetime.now()).replace(microsecond=0) - _dt(sim_now)
    except ValueError:
        return None


def shift_iso(ts: str | None, offset: timedelta | None) -> str | None:
    """An ISO timestamp moved by `offset` (unchanged without an offset or if not a time)."""
    if not ts or offset is None:
        return ts
    try:
        return (_dt(ts) + offset).isoformat(timespec="seconds")
    except ValueError:
        return ts


def shift_rows(rows: list[dict], keys: tuple[str, ...], offset: timedelta | None) -> list[dict]:
    """Copies of `rows` with the timestamp fields `keys` shifted for display."""
    if offset is None:
        return rows
    return [{**r, **{k: shift_iso(r.get(k), offset) for k in keys if k in r}} for r in rows]


def station_figure(
    readings: list[dict], forecast: list[dict], warnings: list[dict], title: str = ""
) -> go.Figure:
    """Observed PM2.5, the latest forecast points (h=1/6/24), past 6 h forecasts, thresholds,
    and warning markers. Units on the axes; sizes meant for a projector."""
    fig = go.Figure()
    obs = [(_dt(r["ts"]), r["pm25"]) for r in readings]
    fig.add_trace(go.Scatter(x=[t for t, _ in obs], y=[v for _, v in obs], mode="lines",
                             name="Ölçüm", line={"color": "#000000", "width": 3}))  # fmt: skip
    past6 = sorted((r for r in forecast if r["horizon"] == 6), key=lambda r: r["target_ts"])
    if past6:
        fig.add_trace(
            go.Scatter(
                x=[_dt(r["target_ts"]) for r in past6],
                y=[r["yhat"] for r in past6],
                mode="lines",
                name="6 saatlik tahmin (geçmiş)",
                line={"color": "#0072B2", "width": 2, "dash": "dot"},
            )
        )
    band = [r for r in past6 if r.get("q10") is not None and r.get("q90") is not None]
    if (
        band
    ):  # q10-q90 interval of the 6 h forecast (RQ4); absent when the predictor runs without it
        xs = [_dt(r["target_ts"]) for r in band]
        fig.add_trace(go.Scatter(x=xs, y=[r["q90"] for r in band], mode="lines", line={"width": 0},
                                 hoverinfo="skip", showlegend=False))  # fmt: skip
        fig.add_trace(go.Scatter(
            x=xs, y=[r["q10"] for r in band], mode="lines", line={"width": 0}, fill="tonexty",
            fillcolor="rgba(0, 114, 178, 0.18)", name="q10-q90 aralığı (6 sa)", hoverinfo="skip",
        ))  # fmt: skip
    colors = {1: "#009E73", 6: "#0072B2", 24: "#D55E00"}
    for h, r in sorted(latest_forecasts(forecast).items()):
        fig.add_trace(go.Scatter(
            x=[_dt(r["target_ts"])], y=[r["yhat"]], mode="markers+text", text=[f"{h} sa"],
            textposition="top center", name=f"Tahmin +{h} sa",
            marker={"size": 16, "color": colors[h], "symbol": "diamond"},
        ))  # fmt: skip
    if warnings:
        fig.add_trace(go.Scatter(
            x=[_dt(w["made_at_ts"]) + timedelta(hours=w["horizon"]) for w in warnings],
            y=[w["yhat"] for w in warnings], mode="markers", name="Uyarı",
            marker={"size": 13, "color": "#CC79A7", "symbol": "triangle-up",
                    "line": {"width": 1, "color": "#000"}},
        ))  # fmt: skip
    for th in THRESHOLDS:
        fig.add_hline(y=th, line={"color": "#555555", "dash": "dash", "width": 1.5},
                      annotation_text=f"{th} µg/m³", annotation_position="top left")  # fmt: skip
    fig.update_layout(
        title=title, xaxis_title="Zaman (benzetim saati)", yaxis_title="PM2.5 (µg/m³)",
        font={"size": 16}, template="plotly_white", height=440,
        margin={"l": 60, "r": 20, "t": 50, "b": 50}, legend={"orientation": "h", "y": -0.25},
    )  # fmt: skip
    return fig


def warnings_table(warnings: list[dict], readings_by_station: dict[str, list[dict]]) -> list[dict]:
    """Warning rows with 'did it happen?' (observed PM2.5 at the target hour vs the threshold)."""
    obs = {s: {_dt(r["ts"]): r["pm25"] for r in rows} for s, rows in readings_by_station.items()}
    out = []
    for w in warnings:
        target = _dt(w["made_at_ts"]) + timedelta(hours=w["horizon"])
        seen = obs.get(w["station"], {}).get(target)
        happened = "bilinmiyor" if seen is None else ("evet" if seen > w["threshold"] else "hayır")
        out.append({
            "İstasyon": w["station"], "Uyarı zamanı": w["made_at_ts"], "Ufuk (sa)": w["horizon"],
            "Eşik (µg/m³)": w["threshold"], "Tahmin (µg/m³)": round(w["yhat"], 1),
            "Gerçekleşti mi": happened,
        })  # fmt: skip
    return out


def system_summary(stats: dict) -> list[tuple[str, str]]:
    """(label, value) pairs for the System page."""
    lat = stats.get("latency_ms") or {}
    edge = stats.get("edge") or {}
    rows = [
        ("Çevrimiçi cihaz", str(stats.get("online_devices", 0))),
        ("Benzersiz mesaj", str(stats.get("unique_messages", 0))),
        ("Tekrar oranı (QoS 1)", f"%{100 * stats.get('duplicate_rate', 0):.2f}"),
        (
            "Gecikme p50 / p95 / p99 (ms)",
            " / ".join(str(lat.get(k, "—")) for k in ("p50", "p95", "p99")),
        ),
    ]
    for key, label in (("received", "Edge: alınan"), ("invalid", "Edge: geçersiz"),
                       ("seq_lost", "Edge: kayıp (seq)"), ("duplicates", "Edge: tekrar"),
                       ("values_filtered", "Edge: filtrelenen değer")):  # fmt: skip
        if key in edge:
            rows.append((label, str(edge[key])))
    if "filter_on" in edge:
        rows.append(("Edge filtresi", "açık" if edge["filter_on"] else "kapalı"))
    return rows


def numeric_where_possible(df: pd.DataFrame) -> pd.DataFrame:
    """Convert string columns that are entirely numeric (or empty) to numbers, keep the rest.

    API tables arrive as strings (CSV); `errors="ignore"` no longer exists in current pandas.
    """
    out = df.copy()
    for col in out.columns:
        converted = pd.to_numeric(out[col].replace("", pd.NA), errors="coerce")
        if converted.notna().sum() == out[col].replace("", pd.NA).notna().sum():
            out[col] = converted
    return out

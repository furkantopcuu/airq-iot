"""Pure helpers of the Senaryo Kontrol panel: widget values -> API bodies, API rows -> tables.

Kept free of Streamlit so they are unit-testable; app.py only renders them.
"""

from __future__ import annotations

import pandas as pd

MODE_LABELS = {
    "manual": "Sabitle (manual)",
    "offset": "Ekle (offset)",
    "scale": "Çarp (scale)",
    "ramp": "Rampa (ramp)",
    "perturb": "Sensör hatası (perturb)",
    "offline": "Cihazı düşür (offline)",
    "replay": "Kayıtlı veriye dön (replay)",
}
MODE_HELP = {
    "manual": "Ölçümü sabit bir değere kilitler.",
    "offset": "Gerçek ölçüme sabit bir miktar ekler.",
    "scale": "Gerçek ölçümü bir çarpanla büyütür ya da küçültür.",
    "ramp": "Ölçümü zamanla bir hedefe doğru yükseltir (ya da artırır).",
    "perturb": "Sensör hatası taklidi: ani sıçrama, takılı kalma ya da kesinti.",
    "offline": "Cihaz haber vermeden susar; broker 'çevrimdışı' duyurur.",
    "replay": "Müdahaleyi bırakır; cihaz kayıtlı veriyi oynamaya döner.",
}
PERTURB_LABELS = {"spike": "Ani sıçrama (spike)", "stuck": "Takılı kalma (stuck)",
                  "dropout": "Kesinti (dropout)"}  # fmt: skip
ALL = "all"
# replay pace presets (x real time): fast = one simulated hour per second, realistic = per minute
SPEED_FAST, SPEED_REALISTIC = 3600.0, 60.0


def device_payload(
    target: str,
    variables: list[str],
    mode: str,
    *,
    value: float | None = None,
    delta: float | None = None,
    factor: float | None = None,
    ramp_kind: str = "target",
    ramp_value: float | None = None,
    perturb_type: str = "spike",
    severity: float = 5.0,
    duration_h: float | None = None,
    coupled: bool = False,
    allow_invalid: bool = False,
    label: str | None = None,
) -> dict:
    """Body of POST /control/device. A duration of 0 / None means "until reset"."""
    params: dict = {}
    if mode == "manual":
        params = {"value": value}
    elif mode == "offset":
        params = {"delta": delta}
    elif mode == "scale":
        params = {"factor": factor}
    elif mode == "ramp":
        params = {"target" if ramp_kind == "target" else "delta": ramp_value}
    elif mode == "perturb":
        params = {"type": perturb_type}
        if perturb_type == "spike":
            params["severity"] = severity
    body = {
        "target": target, "variables": variables, "mode": mode, "params": params,
        "duration_h": duration_h if duration_h else None, "coupled": coupled,
        "allow_invalid": allow_invalid, "label": (label or "").strip() or None,
    }  # fmt: skip
    return body


def speed_payload(value: float) -> dict:
    """Body of the fleet speed command (the fleet clamps nothing: 0 would mean unthrottled)."""
    if value <= 0:
        raise ValueError("speed must be positive")
    return {"action": "speedup", "value": float(value)}


def network_payload(
    target: str, loss: float, delay_ms: float, jitter_ms: float, reorder: float
) -> dict:
    return {"target": target, "loss_rate": loss, "delay_ms": delay_ms, "jitter_ms": jitter_ms,
            "reorder_rate": reorder}  # fmt: skip


def result_text(resp: dict) -> tuple[bool, str]:
    """(ok, one-line message) for a /control/* answer."""
    if "steps_total" in resp:  # /control/scenario/{name} answers with the player status
        return True, f"Senaryo başladı: {resp['name']} ({resp['steps_total']} adım)"
    n = len(resp.get("acks", []))
    if resp.get("ok"):
        return True, f"Onaylandı ({n} ack)"
    return False, "Reddedildi: " + "; ".join(str(e) for e in resp.get("errors", []) if e)


def _yn(v) -> str:
    return "—" if v is None else ("Evet" if v else "Hayır")


def _num(v, nd=1) -> str:
    return "—" if v is None or pd.isna(v) else f"{v:.{nd}f}"


def format_scorecard(rows: list[dict]) -> pd.DataFrame:
    """Scoreboard table; edge off/on of the same scenario sit next to each other."""
    out = []
    for r in rows:
        out.append(
            {
                "Etiket": r["label"], "İstasyon": r["stations"], "Mod": r["mode"],
                "Edge": "açık" if r["edge_filter"] == "on" else "kapalı",
                "Uyarı verildi": _yn(r.get("warned")), "Aşımla eşleşti": _yn(r.get("matched")),
                "Öncül süre (sa)": _num(r.get("lead_time_h")),
                "MAE h=1 (µg/m³)": _num(r.get("mae_next_6h_h1")),
                "MAE h=6 (µg/m³)": _num(r.get("mae_next_6h_h6")),
                "En yüksek h=6 tahmini": _num(r.get("peak_forecast_h6"), 0),
                "Teslim oranı": _num(r.get("delivery_ratio"), 3),
                "Tahmin sayısı": r.get("n_forecasts", 0),
            }
        )  # fmt: skip
    df = pd.DataFrame(out)
    return df if df.empty else df.sort_values(["Etiket"]).reset_index(drop=True)


def format_active(state: dict, shift=None) -> pd.DataFrame:
    """Active interventions; `shift` maps a timestamp to its display form (identity by default)."""
    shift = shift or (lambda ts: ts)
    rows = [
        {"İstasyon": i["station"], "Mod": i["mode"], "Değişken": ",".join(i["variables"]),
         "Başlangıç": (shift(i["start_ts"]) or "").replace("T", " ")[:16],
         "Bitiş": (shift(i["end_ts"]) or "reset'e kadar").replace("T", " ")[:16],
         "Etiket": i.get("label") or ""}
        for i in state.get("interventions", [])
    ]  # fmt: skip
    return pd.DataFrame(rows)


def status_line(state: dict) -> str:
    """One line: edge filter, network emulation, fleet state."""
    net = state.get("network") or {}
    net_txt = (
        "yok"
        if not net
        else "; ".join(
            f"{k}: kayıp %{v.get('loss_rate', 0) * 100:.0f}, gecikme {v.get('delay_ms', 0):.0f} ms"
            for k, v in net.items()
        )
    )
    fleet = state.get("fleet") or {}
    speed = fleet.get("speedup")
    fleet_txt = ("duraklatıldı" if fleet.get("paused") else "çalışıyor") + (
        f", {speed:g}×" if speed else ""
    )
    edge = "açık" if state.get("edge_filter", "on") == "on" else "KAPALI"
    return f"Edge filtresi: {edge} · Ağ emülasyonu: {net_txt} · Filo: {fleet_txt}"

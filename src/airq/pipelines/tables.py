"""Result tables for the paper (LaTeX, booktabs) and the README (Markdown).

Source: reports/tables/*.csv.

Every cell is computed from a CSV in `reports/tables`; no number is typed by hand (spec 11.3, 11.4).
Each builder returns a display frame of strings. A table whose source CSV is missing is skipped
(Colab runs may only have some of them). `paper/tables/_index.json` records source -> table.

python -m scripts.make_tables [--readme]
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from airq.env import resolve_home, resolve_paths

MODEL_NAMES = {
    "B0_persistence": "B0 persistence",
    "B1_seasonal_naive": "B1 seasonal naive",
    "B2_ridge_k0": "B2 ridge (k=0)",
    "M1_lgbm_k0": "M1 LightGBM (k=0)",
    "M2_lgbm_k3": "M2a LightGBM (k=3)",
    "M2_lgbm_k11": "M2b LightGBM (k=11)",
}
HORIZONS = (1, 6, 24)
LATEX_SYMBOLS = {
    "µg/m³": r"\textmu g/m$^3$", "≥": r"$\geq$", "σ": r"$\sigma$", "Δ": r"$\Delta$",
    "±": r"$\pm$", "→": r"$\rightarrow$", "×": r"$\times$", "–": "--",
}  # fmt: skip


def fmt(x, nd: int = 2) -> str:
    """Number -> string with `nd` decimals; missing -> '--'."""
    if x is None or (isinstance(x, float) and np.isnan(x)) or pd.isna(x):
        return "--"
    return f"{float(x):.{nd}f}"


def pct(x, nd: int = 1) -> str:
    return fmt(x, nd)


@dataclass(frozen=True)
class TableSpec:
    name: str
    source: str  # csv file stem(s), comma separated
    caption_tr: str
    caption_en: str
    build: Callable[[Path], pd.DataFrame]


def _read(tables: Path, stem: str) -> pd.DataFrame:
    return pd.read_csv(tables / f"{stem}.csv")


def _by_h(df: pd.DataFrame, value: str, nd: int = 2, label: str | None = None) -> dict:
    """{'<label> h=1': ..} columns for one value column, rows already indexed by model."""
    out = {}
    for h in HORIZONS:
        sub = df[df["h"] == h].set_index("model")[value]
        out[f"{label or value} h={h}"] = sub.map(lambda v, nd=nd: fmt(v, nd))
    return out


def t_dataset(tables: Path) -> pd.DataFrame:
    d = _read(tables, "dataset_summary")
    return pd.DataFrame(
        {
            "Station": d["station"],
            "Rows": d["rows"].map(lambda v: f"{int(v):,}".replace(",", " ")),
            "PM2.5 missing (%)": d["pm25_missing_pct"].map(lambda v: fmt(v, 2)),
            "Mean": d["pm25_mean"].map(lambda v: fmt(v, 1)),
            "Median": d["pm25_median"].map(lambda v: fmt(v, 1)),
            "P95": d["pm25_p95"].map(lambda v: fmt(v, 0)),
        }
    )


def t_rq1_main(tables: Path) -> pd.DataFrame:
    m = _read(tables, "rq1_main")
    cols = {**_by_h(m, "rmse", 2, "RMSE"), **_by_h(m, "improvement_vs_b0_pct", 1, "Δ% vs B0")}
    out = pd.DataFrame(cols)
    out.index = [MODEL_NAMES.get(i, i) for i in out.index]
    order = [MODEL_NAMES[k] for k in MODEL_NAMES if MODEL_NAMES[k] in out.index]
    return out.loc[order].rename_axis("Model").reset_index()


def t_rq1_ablation(tables: Path) -> pd.DataFrame:
    a = _read(tables, "rq1_ablation")
    cols = {**_by_h(a, "rmse", 2, "RMSE"), **_by_h(a, "improvement_vs_m1_pct", 1, "Δ% vs M1")}
    out = pd.DataFrame(cols)
    out.index = [MODEL_NAMES.get(i, i) for i in out.index]
    return out.rename_axis("Model").reset_index()


def t_rq1_loso(tables: Path) -> pd.DataFrame:
    """Mean over the held-out stations; the per-station values stay in the CSV."""
    loso = _read(tables, "rq1_loso")
    g = loso.groupby("h")[
        ["rmse_loso", "rmse_in_sample_m2", "improvement_loso_pct", "improvement_in_sample_pct"]
    ].mean()
    return pd.DataFrame(
        {
            "h": [f"{h} h" for h in g.index],
            "RMSE LOSO": g["rmse_loso"].map(lambda v: fmt(v, 2)),
            "RMSE in-sample": g["rmse_in_sample_m2"].map(lambda v: fmt(v, 2)),
            "Δ% vs B0 LOSO": g["improvement_loso_pct"].map(lambda v: fmt(v, 1)),
            "Δ% vs B0 in-sample": g["improvement_in_sample_pct"].map(lambda v: fmt(v, 1)),
            "Stations": [str(loso[loso["h"] == h]["station"].nunique()) for h in g.index],
        }
    )


def t_rq1_extreme(tables: Path) -> pd.DataFrame:
    e = _read(tables, "rq1_extreme")
    e = e[e["subset"] == "target >= train p95"]
    out = pd.DataFrame(_by_h(e, "rmse", 1, "RMSE"))
    out.index = [MODEL_NAMES.get(i, i) for i in out.index]
    return out.rename_axis("Model").reset_index()


def t_rq2_warning(tables: Path) -> pd.DataFrame:
    w = _read(tables, "rq2_warning")
    w = w[(w["grid"] == "spec") & (w["h"].astype(str).isin(["1", "6", "24"]))]
    w = w[w["method"].isin(["B0_persistence", "M2_lgbm_k11"])]
    w = w.assign(h=w["h"].astype(int)).sort_values(["theta", "h", "method"])
    return pd.DataFrame(
        {
            "θ": w["theta"].map(lambda v: f"{int(v)}"),
            "h": w["h"].map(lambda v: f"{v} h"),
            "Method": w["method"].map(lambda m: MODEL_NAMES.get(m, m)),
            "δ": w["delta"].map(lambda v: fmt(v, 0)),
            "Precision": w["precision"].map(lambda v: fmt(v, 3)),
            "Recall": w["recall"].map(lambda v: fmt(v, 3)),
            "F2": w["f2"].map(lambda v: fmt(v, 3)),
            "PR-AUC": w["pr_auc"].map(lambda v: fmt(v, 3)),
            "False alarm": w["false_alarm_rate"].map(lambda v: fmt(v, 3)),
        }
    ).reset_index(drop=True)


def t_rq2_haze(tables: Path) -> pd.DataFrame:
    z = _read(tables, "rq2_haze")
    z = z[z["grid"] == "spec"].assign(hk=lambda d: d["h"].astype(str).str.zfill(3))
    z = z.sort_values(["hk", "method"])
    return pd.DataFrame(
        {
            "h": z["h"].map(lambda v: f"{v} h" if str(v).isdigit() else str(v)),
            "Method": z["method"].map(lambda m: MODEL_NAMES.get(m, m)),
            "Episodes": z["n_events"].map(lambda v: f"{int(v)}"),
            "Event recall": z["event_recall"].map(lambda v: fmt(v, 2)),
            "Lead median (h)": z["lead_median"].map(lambda v: fmt(v, 1)),
            "Horizon-matched recall": z["m_event_recall"].map(lambda v: fmt(v, 2)),
            "Horizon-matched lead (h)": z["m_lead_median"].map(lambda v: fmt(v, 1)),
        }
    ).reset_index(drop=True)


def t_rq3a(tables: Path) -> pd.DataFrame:
    b = _read(tables, "rq3a_bench").sort_values(["speedup", "offline_k", "loss", "delay_ms"])
    return pd.DataFrame(
        {
            "Speed (×)": b["speedup"].map(lambda v: f"{int(v)}"),
            "Loss (%)": (100 * b["loss"]).map(lambda v: fmt(v, 0)),
            "Delay (ms)": b["delay_ms"].map(lambda v: fmt(v, 0)),
            "Offline": b["offline_k"].map(lambda v: f"{int(v)}"),
            "Reps": b["reps"].map(lambda v: f"{int(v)}"),
            "PDR": b["pdr_mean"].map(lambda v: fmt(v, 3)),
            "DB p50 (ms)": b["lat_db_p50_ms_mean"].map(lambda v: fmt(v, 0)),
            "DB p95 (ms)": b["lat_db_p95_ms_mean"].map(lambda v: fmt(v, 0)),
            "Msg/s": b["throughput_msg_s_mean"].map(lambda v: fmt(v, 0)),
            "Δ RMSE h=1": b["paired_delta_h1_mean"].map(lambda v: fmt(v, 2)),
        }
    ).reset_index(drop=True)


def t_rq3b(tables: Path) -> pd.DataFrame:
    r = _read(tables, "rq3b_robustness")
    r = r[r["scope"] == "affected"].sort_values(["method", "h"])
    return pd.DataFrame(
        {
            "Method": r["method"].map(lambda m: MODEL_NAMES.get(m, m)),
            "h": r["h"].map(lambda v: f"{int(v)} h"),
            "RMSE clean": r["rmse_clean"].map(lambda v: fmt(v, 2)),
            "Damage, edge off": r["damage_off"].map(lambda v: fmt(v, 2)),
            "Damage, edge on": r["damage_on"].map(lambda v: fmt(v, 2)),
            "Recovered (%)": r["recovered_pct"].map(lambda v: fmt(v, 1)),
        }
    ).reset_index(drop=True)


def t_scenarios(tables: Path) -> pd.DataFrame:
    s = _read(tables, "scenarios_summary")
    ref = s["reference"].map(lambda v: "" if pd.isna(v) else fmt(v, 2))
    return pd.DataFrame(
        {
            "Scenario": s["scenario"],
            "Item": s["label"],
            "Metric": s["metric"],
            "Expected": s["relation"].map(lambda v: v.replace("_", " ")),
            "Reference": ref,
            "Measured": s["measured"].map(
                lambda v: v if isinstance(v, str) and v in ("True", "False") else fmt(v, 2)
            ),
            "Verdict": s["verdict"],
        }
    )


TABLES = [
    TableSpec(
        "dataset",
        "dataset_summary",
        "Beijing çok-istasyonlu veri seti özeti.",
        "Beijing multi-site dataset summary (PM2.5, µg/m³).",
        t_dataset,
    ),
    TableSpec(
        "rq1_main",
        "rq1_main",
        "Test döneminde tahmin hatası (RMSE, µg/m³) ve persistence'a göre iyileşme.",
        "Test-period forecast error (RMSE, µg/m³) and improvement over persistence.",
        t_rq1_main,
    ),
    TableSpec(
        "rq1_ablation",
        "rq1_ablation",
        "Komşu özelliği ablasyonu: M1'e göre iyileşme.",
        "Neighbour-feature ablation: improvement over M1.",
        t_rq1_ablation,
    ),
    TableSpec(
        "rq1_loso",
        "rq1_loso",
        "Görülmemiş istasyon (LOSO) ile örneklem içi karşılaştırma (istasyon ortalaması).",
        "Leave-one-station-out versus in-sample (mean over stations).",
        t_rq1_loso,
    ),
    TableSpec(
        "rq1_extreme",
        "rq1_extreme",
        "Aşırı olaylarda (hedef ≥ train p95) RMSE (µg/m³).",
        "RMSE on extreme targets (target ≥ train p95), µg/m³.",
        t_rq1_extreme,
    ),
    TableSpec(
        "rq2_warning",
        "rq2_warning",
        "Erken uyarı: val'de seçilen δ ile test başarımı (belirtilen δ ızgarası).",
        "Early warning on the test period with δ chosen on validation (specified grid).",
        t_rq2_warning,
    ),
    TableSpec(
        "rq2_haze",
        "rq2_haze",
        "Bölgesel haze epizotlarında yakalama ve öncül süre.",
        "Regional haze episodes: recall and lead time.",
        t_rq2_haze,
    ),
    TableSpec(
        "rq3a",
        "rq3a_bench",
        "RQ3a: ağ bozulması altında sistem ölçümleri (kısaltılmış plan).",
        "RQ3a: live-system measurements under network impairment (reduced plan).",
        t_rq3a,
    ),
    TableSpec(
        "rq3b",
        "rq3b_robustness",
        "RQ3b: hatalı girdinin yol açtığı RMSE artışı, edge kapalı ve açık.",
        "RQ3b: RMSE increase caused by faulty inputs, edge filter off vs on.",
        t_rq3b,
    ),
    TableSpec(
        "scenarios",
        "scenarios_summary",
        "Hazır senaryoların hipotezleri ve gerçek sonuçları.",
        "Scenario hypotheses and what was measured.",
        t_scenarios,
    ),
]


# --- renderers -------------------------------------------------------------------------------
def latex_escape(text: str) -> str:
    out = []
    for ch in str(text):
        out.append({"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#",
                    "_": r"\_", "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}",
                    "^": r"\textasciicircum{}"}.get(ch, ch))  # fmt: skip
    escaped = "".join(out)
    for src, dst in LATEX_SYMBOLS.items():
        escaped = escaped.replace(src, dst)
    return escaped


def render_latex(df: pd.DataFrame, caption: str, label: str) -> str:
    left_cols = {c for c in df.columns if df[c].astype(str).str.contains(r"[A-Za-z]{4,}").any()}
    spec = "".join("l" if c in left_cols else "r" for c in df.columns)
    lines = [
        "\\begin{table}[t]",
        f"\\caption{{{latex_escape(caption)}}}",
        f"\\label{{tab:{label}}}",
        "\\centering\\footnotesize",
        f"\\begin{{tabular}}{{{spec}}}",
        "\\toprule",
        " & ".join(latex_escape(str(c)) for c in df.columns) + " \\\\",
        "\\midrule",
    ]
    for _, row in df.iterrows():
        lines.append(" & ".join(latex_escape(str(v)) for v in row) + " \\\\")
    lines += ["\\bottomrule", "\\end{tabular}", "\\end{table}", ""]
    return "\n".join(lines)


def render_markdown(df: pd.DataFrame) -> str:
    head = "| " + " | ".join(str(c) for c in df.columns) + " |"
    sep = "|" + "|".join("---" for _ in df.columns) + "|"
    rows = ["| " + " | ".join(str(v) for v in r) + " |" for _, r in df.iterrows()]
    return "\n".join([head, sep, *rows]) + "\n"


# --- stage -----------------------------------------------------------------------------------
def build_all(cfg: dict, only: list[str] | None = None) -> dict[str, list[Path]]:
    """Write paper/tables/<name>.tex and .md for every table whose CSV exists."""
    paths = resolve_paths(cfg["paths"])
    tables_dir = paths["reports"] / "tables"
    out_dir = resolve_home() / "paper" / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    made: dict[str, list[Path]] = {}
    index = {}
    for spec in TABLES:
        if only and spec.name not in only:
            continue
        missing = [s for s in spec.source.split(",") if not (tables_dir / f"{s}.csv").exists()]
        if missing:
            print(f"skip {spec.name}: missing {missing}")
            continue
        df = spec.build(tables_dir)
        tex, md = out_dir / f"{spec.name}.tex", out_dir / f"{spec.name}.md"
        tex.write_text(render_latex(df, spec.caption_tr, spec.name), encoding="utf-8")
        md.write_text(render_markdown(df), encoding="utf-8")
        made[spec.name] = [tex, md]
        index[spec.name] = {
            "source": [f"reports/tables/{s}.csv" for s in spec.source.split(",")],
            "caption_en": spec.caption_en,
            "rows": len(df),
            "columns": list(df.columns),
        }
    (out_dir / "_index.json").write_text(
        json.dumps(
            {"generated_at": datetime.now().isoformat(timespec="seconds"), "tables": index},
            indent=2,
            ensure_ascii=False,
        ),  # fmt: skip
        encoding="utf-8",
    )
    return made


MARKER = r"<!-- TABLE:{name} -->.*?<!-- /TABLE:{name} -->"


def update_readme(cfg: dict, readme: Path, names: list[str]) -> list[str]:
    """Replace `<!-- TABLE:name --> ... <!-- /TABLE:name -->` blocks with the generated Markdown."""
    out_dir = resolve_home() / "paper" / "tables"
    text, done = readme.read_text(encoding="utf-8"), []
    for name in names:
        md = out_dir / f"{name}.md"
        if not md.exists() or f"<!-- TABLE:{name} -->" not in text:
            continue
        block = f"<!-- TABLE:{name} -->\n{md.read_text(encoding='utf-8')}<!-- /TABLE:{name} -->"
        text = re.sub(MARKER.format(name=re.escape(name)), lambda _m, b=block: b, text, flags=re.S)
        done.append(name)
    readme.write_text(text, encoding="utf-8")
    return done

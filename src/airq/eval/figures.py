"""Publication figures: vector PDF for the paper, 200 dpi PNG for slides/README (spec 11.3).

Single column = 3.5 in, full width = 7.16 in; text >= 8 pt; colour-blind-safe (Okabe-Ito) and
readable in greyscale.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

OKABE_ITO = ["#0072B2", "#E69F00", "#009E73", "#D55E00", "#CC79A7", "#56B4E9", "#F0E442", "#000000"]
FULL_W, COL_W = 7.16, 3.5


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.size": 8,
            "axes.titlesize": 9,
            "axes.labelsize": 8,
            "xtick.labelsize": 8,
            "ytick.labelsize": 8,
            "legend.fontsize": 8,
            "figure.dpi": 100,
            "savefig.bbox": "tight",
            "axes.prop_cycle": plt.cycler(color=OKABE_ITO),
        }
    )


def save(fig: plt.Figure, out_dir: Path, name: str) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext, kw in (("pdf", {}), ("png", {"dpi": 200})):
        p = out_dir / f"{name}.{ext}"
        fig.savefig(p, **kw)
        paths.append(p)
    plt.close(fig)
    return paths


def corr_and_missing(df: pd.DataFrame, out_dir: Path, name: str = "eda_corr_missing") -> list[Path]:
    """Fig. S2: station PM2.5 correlation matrix (left) and monthly missing-PM2.5 map (right)."""
    apply_style()
    wide = df.pivot(index="ts", columns="station", values="pm25_raw")
    corr = wide.corr()
    miss = (
        df.assign(month=df["ts"].dt.to_period("M").astype(str), miss=df["pm25_raw"].isna())
        .pivot_table(index="station", columns="month", values="miss", aggfunc="mean")
        .mul(100)
    )
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL_W, 3.1), gridspec_kw={"width_ratios": [1, 1.7]})
    im = a.imshow(corr.to_numpy(), vmin=corr.to_numpy().min(), vmax=1.0, cmap="viridis")
    labels = [c[:6] for c in corr.columns]
    a.set_xticks(range(len(labels)), labels, rotation=90)
    a.set_yticks(range(len(labels)), labels)
    a.set_title("PM2.5 correlation")
    fig.colorbar(im, ax=a, fraction=0.046, pad=0.04, label="Pearson r")
    im2 = b.imshow(
        miss.to_numpy(), aspect="auto", cmap="magma_r", vmin=0, vmax=max(5.0, miss.to_numpy().max())
    )
    b.set_yticks(range(len(miss.index)), [s[:6] for s in miss.index])
    ticks = np.arange(0, miss.shape[1], 6)
    b.set_xticks(ticks, [miss.columns[i] for i in ticks], rotation=90)
    b.set_title("Missing PM2.5 by month")
    fig.colorbar(im2, ax=b, fraction=0.03, pad=0.02, label="missing (%)")
    fig.tight_layout()
    return save(fig, out_dir, name)


def rq1_horizon(main: pd.DataFrame, out_dir: Path, name: str = "rq1_horizon") -> list[Path]:
    """Fig. 3: RMSE by horizon (left) and % improvement over persistence with 95% CI (right)."""
    apply_style()
    models = ["B0_persistence", "B2_ridge_k0", "M1_lgbm_k0", "M2_lgbm_k3", "M2_lgbm_k11"]
    labels = {
        "B0_persistence": "B0 persistence",
        "B2_ridge_k0": "B2 Ridge",
        "M1_lgbm_k0": "M1 LGBM k=0",
        "M2_lgbm_k3": "M2a LGBM k=3",
        "M2_lgbm_k11": "M2b LGBM k=11",
    }
    hs = sorted(main["h"].unique())
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL_W, 2.9))
    w = 0.8 / len(models)
    for i, m in enumerate(models):
        sub = main[main["model"] == m].set_index("h").reindex(hs)
        x = np.arange(len(hs)) + (i - (len(models) - 1) / 2) * w
        a.bar(
            x, sub["rmse"], w, label=labels[m], color=OKABE_ITO[i], edgecolor="black", linewidth=0.3
        )
        if m != "B0_persistence":
            err = [
                sub["improvement_vs_b0_pct"] - sub["pct_ci_lo"],
                sub["pct_ci_hi"] - sub["improvement_vs_b0_pct"],
            ]
            b.bar(
                x,
                sub["improvement_vs_b0_pct"],
                w,
                yerr=err,
                color=OKABE_ITO[i],
                edgecolor="black",
                linewidth=0.3,
                capsize=1.5,
                error_kw={"linewidth": 0.6},
            )
    for ax, ylab in ((a, "RMSE (µg/m³)"), (b, "RMSE improvement vs persistence (%)")):
        ax.set_xticks(range(len(hs)), [f"{h} h ahead" for h in hs])
        ax.set_ylabel(ylab)
    a.legend(frameon=False, fontsize=7)
    a.set_title("Test RMSE by horizon")
    b.set_title("Gain over persistence (95% block-bootstrap CI)")
    fig.tight_layout()
    return save(fig, out_dir, name)


def rq1_ablation_loso(
    abl: pd.DataFrame, loso: pd.DataFrame, out_dir: Path, name: str = "rq1_ablation_loso"
) -> list[Path]:
    """Fig. 4: neighbor ablation (gain of M2 over M1) and LOSO vs in-sample gain per station."""
    apply_style()
    hs = sorted(abl["h"].unique())
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL_W, 2.9))
    for i, (m, lab) in enumerate((("M2_lgbm_k3", "k=3"), ("M2_lgbm_k11", "k=11"))):
        sub = abl[abl["model"] == m].set_index("h").reindex(hs)
        x = np.arange(len(hs)) + (i - 0.5) * 0.38
        a.bar(
            x,
            sub["improvement_vs_m1_pct"],
            0.38,
            label=lab,
            color=OKABE_ITO[3 + i],
            edgecolor="black",
            linewidth=0.3,
        )
    a.axhline(0, color="black", linewidth=0.6)
    a.set_xticks(range(len(hs)), [f"{h} h ahead" for h in hs])
    a.set_ylabel("RMSE gain of network model over M1 (%)")
    a.set_title("Neighbor ablation")
    a.legend(frameon=False)
    if loso is not None and len(loso):
        for i, h in enumerate(hs):
            sub = loso[loso["h"] == h]
            b.scatter(
                np.full(len(sub), i - 0.12),
                sub["improvement_in_sample_pct"],
                s=14,
                color=OKABE_ITO[0],
                label="in-sample (k=11)" if i == 0 else None,
            )
            b.scatter(
                np.full(len(sub), i + 0.12),
                sub["improvement_loso_pct"],
                s=14,
                color=OKABE_ITO[1],
                marker="s",
                label="LOSO (unseen station)" if i == 0 else None,
            )
        b.set_xticks(range(len(hs)), [f"{h} h ahead" for h in hs])
        b.set_ylabel("RMSE gain over persistence (%), per station")
        b.set_title("Generalisation to an unseen station")
        b.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return save(fig, out_dir, name)


def shap_groups(shap: pd.DataFrame, out_dir: Path, name: str = "rq1_shap_groups") -> list[Path]:
    """Fig. 5: TreeSHAP share (%) of each feature group, per horizon."""
    apply_style()
    order = [
        "own PM2.5 history",
        "network (neighbors)",
        "meteorology",
        "co-pollutants",
        "calendar",
        "other",
    ]
    hs = sorted(shap["h"].unique())
    fig, ax = plt.subplots(figsize=(COL_W * 1.6, 2.8))
    bottom = np.zeros(len(hs))
    for i, g in enumerate(order):
        vals = np.array(
            [shap[(shap["h"] == h) & (shap["group"] == g)]["share_pct"].sum() for h in hs]
        )
        ax.bar(
            [f"{h} h ahead" for h in hs],
            vals,
            bottom=bottom,
            label=g,
            color=OKABE_ITO[i],
            edgecolor="black",
            linewidth=0.3,
        )
        bottom += vals
    ax.set_ylabel("share of mean |SHAP| (%)")
    ax.legend(frameon=False, fontsize=7, loc="center left", bbox_to_anchor=(1.0, 0.5))
    ax.set_title("What drives the forecast")
    fig.tight_layout()
    return save(fig, out_dir, name)


def rq2_example(example: pd.DataFrame, meta: dict, out_dir: Path, name: str = "rq2_haze_example"):
    """Fig. 6: observed PM2.5, 6 h and 24 h forecasts and the alerts around the largest haze."""
    apply_style()
    fig, ax = plt.subplots(figsize=(FULL_W, 3.0))
    ts = pd.to_datetime(example["ts"])
    onset = pd.Timestamp(meta["onset"])
    ax.plot(ts, example["y_obs"], color="black", linewidth=1.2, label="observed")
    ax.plot(ts, example["yhat_h6"], color=OKABE_ITO[0], linewidth=0.9, label="forecast 6 h ahead")
    ax.plot(ts, example["yhat_h24"], color=OKABE_ITO[3], linewidth=0.9, label="forecast 24 h ahead")
    ax.axhline(150, color=OKABE_ITO[7], linestyle=":", linewidth=0.8)
    ax.text(ts.iloc[0], 156, "150 µg/m³", fontsize=7)
    ax.axvline(onset, color=OKABE_ITO[2], linewidth=1.0)
    top = float(np.nanmax(example["y_obs"])) * 1.05
    for col, marker, color, lab in (
        ("alert_h24", "v", OKABE_ITO[3], "alert (24 h forecast)"),
        ("alert_h6", "v", OKABE_ITO[0], "alert (6 h forecast)"),
    ):
        sel = example[col].astype(bool)
        y = top if col == "alert_h24" else top * 0.95
        ax.scatter(ts[sel], np.full(sel.sum(), y), marker=marker, s=14, color=color, label=lab)
    leads = ", ".join(
        f"{k.split('_h')[1]} h: {v:.0f} h"
        for k, v in meta.items()
        if k.startswith("lead_h") and v is not None
    )
    ax.set_title(f"{meta['station']}: largest regional haze (green = onset); matched lead {leads}")
    ax.set_ylabel("PM2.5 (µg/m³)")
    ax.legend(frameon=False, fontsize=7, ncol=5, loc="upper center", bbox_to_anchor=(0.5, -0.22))
    ax.set_ylim(top=top * 1.12)
    fig.autofmt_xdate()
    fig.tight_layout()
    return save(fig, out_dir, name)


def rq2_pr_lead(pr: pd.DataFrame, hist: pd.DataFrame, out_dir: Path, name: str = "rq2_pr_lead"):
    """Fig. 7: precision-recall (theta=150, 6 h) and horizon-matched lead-time distribution."""
    apply_style()
    labels = {"B0_persistence": "persistence", "M1_lgbm_k0": "M1 (k=0)", "M2_lgbm_k11": "M2 (k=11)"}
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL_W, 2.9))
    for i, (m, lab) in enumerate(labels.items()):
        sub = pr[pr["method"] == m].sort_values("recall")
        a.plot(
            sub["recall"], sub["precision"], color=OKABE_ITO[[7, 1, 0][i]], label=lab, linewidth=1.2
        )
    a.set_xlabel("recall")
    a.set_ylabel("precision")
    a.set_title("PM2.5 > 150, 6 h ahead (test)")
    a.legend(frameon=False)
    h = hist[(hist["theta"] == 150) & (hist["kind"] == "matched") & (hist["h"] == "spec:any")]
    w = 0.38
    for i, m in enumerate(("B0_persistence", "M2_lgbm_k11")):
        sub = h[h["method"] == m].sort_values("lead_h")
        tot = max(sub["count"].sum(), 1)
        b.bar(
            sub["lead_h"] + (i - 0.5) * w,
            100 * sub["count"] / tot,
            w,
            label=labels[m],
            color=OKABE_ITO[7 if i == 0 else 0],
            edgecolor="black",
            linewidth=0.2,
        )
    b.set_xlabel("lead time (h), horizon-matched, any horizon")
    b.set_ylabel("caught events (%)")
    b.set_title("Lead time of caught exceedance events (> 150)")
    b.legend(frameon=False)
    fig.tight_layout()
    return save(fig, out_dir, name)


def rq3b_damage(rob: pd.DataFrame, out_dir: Path, name: str = "rq3b_damage") -> list[Path]:
    """Fig. 9: RMSE increase caused by faulty inputs, edge filter off vs on.

    Left: rows whose last 24 h of input contain a fault, by horizon, persistence vs main model.
    Right: by fault type at the 6 h horizon for the main model.
    """
    apply_style()
    models = [m for m in ("B0_persistence", "M2_lgbm_k11", "M1_lgbm_k0") if m in set(rob["method"])]
    main = "M2_lgbm_k11" if "M2_lgbm_k11" in models else "M1_lgbm_k0"
    pair = [m for m in ("B0_persistence", main) if m in models]
    labels = {"B0_persistence": "persistence", main: "LightGBM (main)"}
    fig, (a, b) = plt.subplots(1, 2, figsize=(FULL_W, 2.9))
    hs = sorted(rob["h"].unique())
    w = 0.8 / (2 * len(pair))
    for i, m in enumerate(pair):
        sub = rob[(rob["method"] == m) & (rob["scope"] == "affected")].set_index("h").reindex(hs)
        for j, (col, lab, hatch) in enumerate(
            (("damage_off", "edge off", ""), ("damage_on", "edge on", "//"))
        ):
            x = np.arange(len(hs)) + (2 * i + j - (2 * len(pair) - 1) / 2) * w
            a.bar(
                x,
                sub[col],
                w,
                color=OKABE_ITO[[7, 0][i]],
                hatch=hatch,
                edgecolor="white" if hatch else "black",
                linewidth=0.4,
                label=f"{labels[m]}, {lab}",
            )
    a.set_xticks(range(len(hs)), [f"{h} h ahead" for h in hs])
    a.set_ylabel("RMSE increase (µg/m³)")
    a.set_title("Rows with a fault in the last 24 h")
    a.legend(frameon=False, fontsize=6.5)
    h6 = 6 if 6 in hs else hs[0]
    kinds = [k for k in ("spike", "stuck", "dropout") if k in set(rob["scope"])]
    for j, (col, lab, hatch) in enumerate(
        (("damage_off", "edge off", ""), ("damage_on", "edge on", "//"))
    ):
        vals = [
            rob[(rob["method"] == main) & (rob["h"] == h6) & (rob["scope"] == k)][col].mean()
            for k in kinds
        ]
        b.bar(
            np.arange(len(kinds)) + (j - 0.5) * 0.38,
            vals,
            0.38,
            color=OKABE_ITO[0],
            hatch=hatch,
            edgecolor="white" if hatch else "black",
            linewidth=0.4,
            label=lab,
        )
    b.set_xticks(range(len(kinds)), kinds)
    b.set_ylabel("RMSE increase (µg/m³)")
    b.set_title(f"By fault type, main model, {h6} h ahead")
    b.legend(frameon=False)
    fig.tight_layout()
    return save(fig, out_dir, name)


def rq3a_system(agg: pd.DataFrame, out_dir: Path, name: str = "rq3a_system") -> list[Path]:
    """Fig. 8: delivery, latency and forecast damage under emulated network faults."""
    apply_style()
    net = agg[agg["offline_k"] == 0]
    fast = net[net["speedup"] == 36000]
    slow = net[net["speedup"] == 3600]
    fig, axes = plt.subplots(1, 3, figsize=(FULL_W, 2.8))
    a, b, c = axes
    loss = sorted(fast["loss"].unique())
    for d, mk in ((0.0, "o"), (200.0, "s")):
        sub = fast[fast["delay_ms"] == d].sort_values("loss")
        a.plot(
            100 * sub["loss"],
            100 * sub["pdr_mean"],
            mk,
            color=OKABE_ITO[0],
            label=f"delay {d:.0f} ms",
        )
    a.plot(
        [0, 100 * max(loss)],
        [100, 100 * (1 - max(loss))],
        color="black",
        linewidth=0.8,
        label="ideal",
    )
    a.set_xlabel("emulated loss (%)")
    a.set_ylabel("PDR (%)")
    a.set_title("Packet delivery ratio")
    a.legend(frameon=False, fontsize=7)
    for d, mk, col in ((0.0, "o", OKABE_ITO[2]), (200.0, "s", OKABE_ITO[3])):
        s1 = fast[fast["delay_ms"] == d].sort_values("loss")
        b.plot(
            100 * s1["loss"],
            s1["lat_db_p95_ms_mean"],
            mk,
            color=col,
            label=f"to DB p95, delay {d:.0f} ms",
        )
    s2 = slow[slow["delay_ms"] == 0].sort_values("loss")
    b.plot(
        100 * s2["loss"],
        s2["lat_warn_p50_ms_mean"],
        "^",
        color=OKABE_ITO[0],
        label="to warning p50 (real time)",
    )
    b.set_yscale("log")
    b.set_xlabel("emulated loss (%)")
    b.set_ylabel("latency (ms)")
    b.set_title("End-to-end latency")
    b.legend(frameon=False, fontsize=6.5)
    f0 = fast[fast["delay_ms"] == 0].sort_values("loss")
    c.errorbar(
        100 * f0["loss"],
        f0["paired_delta_h1_mean"],
        yerr=f0["paired_delta_h1_std"],
        fmt="o-",
        color=OKABE_ITO[0],
        capsize=2,
        label="36 000x (2 reps)",
    )
    c.plot(
        100 * s2["loss"],
        s2["paired_delta_h1_mean"],
        "^",
        color=OKABE_ITO[1],
        label="3 600x (1 rep)",
    )
    c.set_xlabel("emulated loss (%)")
    c.set_ylabel("RMSE increase, 1 h (µg/m³)")
    c.set_title("Forecast damage")
    c.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    return save(fig, out_dir, name)


def architecture(out_dir: Path, name: str = "architecture") -> list[Path]:
    """Fig. 1: hub-and-spoke architecture around the MQTT broker, drawn from code.

    Every component talks to the broker only; the database is written by ingest / predictor and
    read by the API; the dashboard talks to the API over HTTP. Arrow labels name the topic family
    (airq/raw, airq/edge, airq/warnings, airq/cmd, airq/cmd/ack; see iot/topics.py for QoS).
    Dashed arrows are the control path (Senaryo Kontrol): API -> cmd -> devices, fleet, edge -> ack.
    """
    from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

    apply_style()
    fig, ax = plt.subplots(figsize=(FULL_W, 4.1))
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 63)
    ax.axis("off")

    def box(x, y, w, h, text, color):
        ax.add_patch(
            FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.35", fc=color, ec="black", lw=0.8)
        )
        ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=7)

    def arrow(p, q, dashed=False, both=False):
        ax.add_patch(
            FancyArrowPatch(
                p, q, arrowstyle="<|-|>" if both else "-|>", mutation_scale=8, lw=0.9,
                ls="--" if dashed else "-", color="black",
            )
        )  # fmt: skip

    def label(x, y, text, ha="left"):
        ax.text(x, y, text, ha=ha, va="center", fontsize=6.5, style="italic")

    top, bar0, bar1 = 40, 23, 30
    box(1, top, 17, 14, "Virtual sensors\n12 stations\nreplay + netem", OKABE_ITO[5])
    box(22, top, 17, 14, "Edge gateway\nvalidate, quality\nflags, seq, filter", OKABE_ITO[1])
    box(43, top, 15, 14, "Ingest\n(single\nwriter)", OKABE_ITO[2])
    box(62, top, 17, 14, "Predictor\nLightGBM h=1/6/24\n+ warning rule", OKABE_ITO[2])
    ax.add_patch(
        FancyBboxPatch((1, bar0), 78, bar1 - bar0, boxstyle="round,pad=0.35", fc="#F0F0F0",
                       ec="black", lw=0.8)
    )  # fmt: skip
    ax.text(40, (bar0 + bar1) / 2, "MQTT broker (Mosquitto / amqtt)   QoS 1 · retained · LWT",
            ha="center", va="center", fontsize=7.5)  # fmt: skip
    lo, hi = bar1 + 0.6, top - 0.5
    arrow((5, hi), (5, lo))  # sensors publish raw telemetry
    label(5.8, 35.5, "raw")
    arrow((13, lo), (13, hi), dashed=True)  # sensors receive cmd
    label(13.8, 35.5, "cmd")
    arrow((25, lo), (25, hi))  # edge subscribes raw
    label(25.8, 35.5, "raw")
    arrow((31, hi), (31, lo))  # edge publishes validated telemetry
    label(31.8, 35.5, "edge")
    arrow((37.5, lo), (37.5, hi), dashed=True)  # edge receives cmd/edge
    label(38.3, 35.5, "cmd")
    arrow((50.5, lo), (50.5, hi))  # ingest subscribes edge, status, cmd, ack
    label(51.3, 35.5, "edge, status,\ncmd, ack")
    arrow((66, lo), (66, hi))  # predictor subscribes edge telemetry
    label(66.8, 35.5, "edge")
    arrow((74, hi), (74, lo))  # predictor publishes warnings
    label(74.8, 35.5, "warnings")
    # database (written by ingest and predictor, read by the API)
    box(84, 5, 15, 50, "SQLite\n(WAL)\n\nreadings\npredictions\nwarnings\ninterventions\n"
        "device_status", "#DDDDDD")  # fmt: skip
    arrow((79.6, 47), (83.4, 47))
    ax.plot([50.5, 50.5, 91.5, 91.5], [54.5, 59.5, 59.5, 55.8], color="black", lw=0.9)
    arrow((91.5, 56.8), (91.5, 55.7))  # arrow head of the ingest -> SQLite route above the boxes
    label(70, 61, "writes", ha="center")
    # serving layer
    box(43, 4, 17, 13, "Streamlit\nSenaryo Kontrol\n+ live monitoring", OKABE_ITO[4])
    box(63, 4, 16, 13, "FastAPI\nread + control", OKABE_ITO[4])
    arrow((83.4, 10.5), (79.6, 10.5))
    label(81.5, 13, "read", ha="center")
    arrow((62.4, 10.5), (60.6, 10.5), both=True)
    label(61.5, 18.8, "HTTP", ha="center")
    arrow((68, 17.6), (68, bar0 - 0.6), dashed=True)  # API publishes cmd
    label(68.8, 20.4, "cmd")
    arrow((75, bar0 - 0.6), (75, 17.6), dashed=True)  # API receives ack
    label(75.8, 20.4, "ack")
    ax.text(1, 1.2, "solid: data path   dashed: control path   labels: airq/<label>/... topic "
            "families", fontsize=6.5, va="center")  # fmt: skip
    return save(fig, out_dir, name)


def scenarios_edge(results: list[dict], out_dir: Path, name: str = "scenarios_edge") -> list[Path]:
    """Fig. 10: live fault scenarios with the edge filter off vs on (reports/scenarios/*.json).

    Forecast error against the CLEAN recording in the 6 h after the fault started (h=1 and h=6).
    One run per scenario (no variance); the two windows are not paired.
    """
    apply_style()
    wanted = [("sensor_sicramasi", "spike (k=8 σ, 3 h)"), ("sensor_takilmasi", "stuck (12 h)")]
    by_name = {r["scenario"]: r for r in results}
    panels = [(by_name[n], title) for n, title in wanted if n in by_name]
    if not panels:
        raise FileNotFoundError("scenario results not found; run scripts.run_scenarios")
    fig, axes = plt.subplots(1, len(panels), figsize=(FULL_W, 2.7), squeeze=False)
    for ax, (res, title) in zip(axes[0], panels, strict=False):
        rows = {r["edge_filter"]: r for r in res["scorecard"] if r["kind"] == "fault"}
        hs = ("mae_next_6h_h1", "mae_next_6h_h6")
        x = np.arange(len(hs))
        for j, (state, lab, hatch) in enumerate((("off", "edge off", ""), ("on", "edge on", "//"))):
            vals = [(rows.get(state) or {}).get(h) or 0.0 for h in hs]
            ax.bar(x + (j - 0.5) * 0.36, vals, 0.36, label=lab, hatch=hatch,
                   color=OKABE_ITO[3 if state == "off" else 0], edgecolor="white")  # fmt: skip
            for xi, v in zip(x + (j - 0.5) * 0.36, vals, strict=False):
                ax.text(xi, v, f"{v:.1f}", ha="center", va="bottom", fontsize=7)
        ax.set_xticks(x, ["h = 1 h", "h = 6 h"])
        ax.set_ylabel("MAE vs clean recording (µg/m³)")
        ax.set_title(title)
        ax.legend(frameon=False)
    fig.tight_layout()
    return save(fig, out_dir, name)

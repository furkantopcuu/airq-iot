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

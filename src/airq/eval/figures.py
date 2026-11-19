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

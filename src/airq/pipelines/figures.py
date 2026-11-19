"""Figure stage: EDA figures from the cleaned dataset."""

from __future__ import annotations

import pandas as pd

from airq.env import resolve_paths
from airq.eval import figures


def eda(cfg: dict) -> list:
    paths = resolve_paths(cfg["paths"])
    df = pd.read_parquet(paths["processed"] / "clean.parquet")
    return figures.corr_and_missing(df, paths["reports"] / "figures")


def rq1(cfg: dict) -> list:
    """Figures 3-5 from the RQ1 tables (run after scripts.run_final)."""
    paths = resolve_paths(cfg["paths"])
    t, out = paths["reports"] / "tables", paths["reports"] / "figures"
    made = list(figures.rq1_horizon(pd.read_csv(t / "rq1_main.csv"), out))
    loso = pd.read_csv(t / "rq1_loso.csv") if (t / "rq1_loso.csv").exists() else None
    made += figures.rq1_ablation_loso(pd.read_csv(t / "rq1_ablation.csv"), loso, out)
    if (t / "rq1_shap.csv").exists():
        made += figures.shap_groups(pd.read_csv(t / "rq1_shap.csv"), out)
    return made


def rq2(cfg: dict) -> list:
    """Figures 6-7 from the RQ2 outputs (run after scripts.run_warning)."""
    import json

    paths = resolve_paths(cfg["paths"])
    t, out = paths["reports"] / "tables", paths["reports"] / "figures"
    made = list(
        figures.rq2_pr_lead(
            pd.read_csv(t / "rq2_pr_curve.csv"), pd.read_csv(t / "rq2_lead_hist.csv"), out
        )
    )
    meta = json.loads((paths["reports"] / "metrics" / "warning_test.json").read_text())["example"]
    if meta and (t / "rq2_example.csv").exists():
        made += figures.rq2_example(pd.read_csv(t / "rq2_example.csv"), meta, out)
    return made


def rq3b(cfg: dict) -> list:
    """Figure 9 from the RQ3b table (run after scripts.run_robustness)."""
    paths = resolve_paths(cfg["paths"])
    t, out = paths["reports"] / "tables", paths["reports"] / "figures"
    return list(figures.rq3b_damage(pd.read_csv(t / "rq3b_robustness.csv"), out))


def rq3a(cfg: dict) -> list:
    """Figure 8 from the RQ3a benchmark table (run after scripts.run_system_bench --aggregate)."""
    paths = resolve_paths(cfg["paths"])
    t, out = paths["reports"] / "tables", paths["reports"] / "figures"
    return list(figures.rq3a_system(pd.read_csv(t / "rq3a_bench.csv"), out))

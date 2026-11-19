"""Figure stage: EDA figures from the cleaned dataset."""

from __future__ import annotations

import pandas as pd

from airq.env import resolve_paths
from airq.eval import figures


def eda(cfg: dict) -> list:
    paths = resolve_paths(cfg["paths"])
    df = pd.read_parquet(paths["processed"] / "clean.parquet")
    return figures.corr_and_missing(df, paths["reports"] / "figures")

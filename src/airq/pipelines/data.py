"""Data stage: raw CSVs -> cleaned parquet, dataset summary, episodes, repro.json."""

from __future__ import annotations

import json
import platform
from importlib import metadata
from pathlib import Path

import pandas as pd

from airq.config import config_hash
from airq.data.clean import clean
from airq.data.episodes import label_all
from airq.data.load import load_raw
from airq.data.splits import assign_split, split_bounds
from airq.env import resolve_paths

PACKAGES = ["pandas", "numpy", "pyarrow", "scipy", "scikit-learn", "lightgbm", "paho-mqtt"]


def _find_csv_dir(raw: Path) -> Path:
    hits = sorted((raw / "beijing").rglob("PRSA_Data_*.csv"))
    if not hits:
        raise FileNotFoundError("Raw CSVs not found; run `python -m scripts.download_data` first.")
    return hits[0].parent


def _pkg_versions() -> dict[str, str | None]:
    out: dict[str, str | None] = {}
    for name in PACKAGES:
        try:
            out[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            out[name] = None
    return out


def dataset_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Per-station and overall summary (Table 1 source)."""

    def row(name: str, g: pd.DataFrame) -> dict:
        obs = g["pm25_raw"].dropna()
        return {
            "station": name,
            "rows": len(g),
            "ts_min": g["ts"].min(),
            "ts_max": g["ts"].max(),
            "pm25_missing_pct": round(100 * g["pm25_raw"].isna().mean(), 3),
            "pm25_mean": round(obs.mean(), 2),
            "pm25_median": round(obs.median(), 2),
            "pm25_p95": round(obs.quantile(0.95), 2),
        }

    rows = [row(s, g) for s, g in df.groupby("station", sort=True)]
    rows.append(row("ALL", df))
    return pd.DataFrame(rows)


def physical_consistency(df_train: pd.DataFrame) -> pd.DataFrame:
    """Share of rows with observed PM2.5 > PM10 on train (sets the edge rule tolerance, 8.3)."""
    both = df_train.dropna(subset=["pm25_raw", "pm10"]).copy()
    both = both[~both["pm10_missing"]]
    both["excess"] = both["pm25_raw"] - both["pm10"]
    rows = []
    for name, g in [*both.groupby("station", sort=True), ("ALL", both)]:
        rows.append(
            {
                "station": name,
                "n_pairs": len(g),
                "pct_pm25_gt_pm10": round(100 * (g["excess"] > 0).mean(), 4),
                "excess_p99": round(g["excess"].quantile(0.99), 2),
                "excess_p999": round(g["excess"].quantile(0.999), 2),
                "excess_max": round(g["excess"].max(), 2),
            }
        )
    return pd.DataFrame(rows)


def run(cfg: dict, quick: bool = False, force: bool = False) -> dict:
    paths = resolve_paths(cfg["paths"])
    tables = paths["reports"] / "tables"
    metrics = paths["reports"] / "metrics"
    for d in (tables, metrics, paths["processed"], paths["interim"]):
        d.mkdir(parents=True, exist_ok=True)

    raw = load_raw(_find_csv_dir(paths["raw"]))
    stations = cfg["colab"]["quick"]["stations"] if quick else cfg["data"]["stations"]
    raw = raw[raw["station"].isin(stations)]

    start, end = cfg["split"]["train"][0], cfg["split"]["test"][1]
    df = clean(raw, start, end, cfg["data"]["ffill_limit"])
    df["split"] = assign_split(df["ts"], cfg).to_numpy()
    df.to_parquet(paths["processed"] / "clean.parquet", index=False)

    dataset_summary(df).to_csv(tables / "dataset_summary.csv", index=False)
    train = df[df["split"] == "train"]
    physical_consistency(train).to_csv(tables / "physical_consistency.csv", index=False)

    train_stats = {
        "pm25_p95_train": float(train["pm25_raw"].quantile(cfg["forecast"]["extreme_quantile"])),
        "pm25_mean_train": float(train["pm25_raw"].mean()),
    }
    (metrics / "train_stats.json").write_text(json.dumps(train_stats, indent=2), encoding="utf-8")

    wide = df.pivot(index="ts", columns="station", values="pm25_raw")
    episodes = label_all(wide, cfg)
    for split in ("train", "val", "test"):
        episodes[episodes["split"] == split].drop(columns="split").to_csv(
            tables / f"episodes_{split}.csv", index=False
        )

    download_json = paths["raw"] / "beijing" / "download.json"
    sha = json.loads(download_json.read_text())["sha256"] if download_json.exists() else None
    repro = {
        "dataset_zip_sha256": sha,
        "config_hash": config_hash(cfg),
        "python": platform.python_version(),
        "packages": _pkg_versions(),
        "quick": quick,
        "rows": int(len(df)),
        "split_bounds": {k: [str(a), str(b)] for k, (a, b) in split_bounds(cfg).items()},
    }
    (paths["reports"] / "repro.json").write_text(json.dumps(repro, indent=2), encoding="utf-8")
    return {"rows": len(df), "episodes": episodes.groupby(["type", "split"]).size().to_dict()}

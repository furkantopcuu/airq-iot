"""Compare two `reports/` folders: does a reproduction give the committed numbers?

Tables (CSV) are compared cell by cell: numbers within a relative / absolute tolerance, everything
else exactly. Timing-dependent outputs (RQ3a benchmark, scenarios) are excluded by default because
they depend on the machine. Used to verify `scripts.run_all` against the committed results.

python -m scripts.compare_reports --a reports --b ..\\airq-repro\\home\\reports [--rtol 1e-6]
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

TIMING_DEPENDENT = ("rq3a_bench", "scenarios_summary")


@dataclass
class TableDiff:
    name: str
    status: str  # identical | within_tolerance | different | missing_a | missing_b
    max_abs: float = 0.0
    max_rel: float = 0.0
    n_cells: int = 0
    n_different: int = 0
    note: str = ""
    worst: list[str] = field(default_factory=list)


def compare_frames(a: pd.DataFrame, b: pd.DataFrame, rtol: float, atol: float) -> TableDiff:
    d = TableDiff("", "identical")
    if list(a.columns) != list(b.columns):
        return TableDiff(
            "", "different", note=f"columns differ: {list(a.columns)} vs {list(b.columns)}"
        )
    if len(a) != len(b):
        return TableDiff("", "different", note=f"row counts differ: {len(a)} vs {len(b)}")
    exact = True
    for col in a.columns:
        x, y = a[col], b[col]
        numeric = pd.api.types.is_numeric_dtype(x) and pd.api.types.is_numeric_dtype(y)
        for i in range(len(a)):
            u, v = x.iloc[i], y.iloc[i]
            d.n_cells += 1
            if pd.isna(u) and pd.isna(v):
                continue
            if numeric and not (pd.isna(u) or pd.isna(v)):
                u, v = float(u), float(v)
                diff = abs(u - v)
                if diff == 0:
                    continue
                exact = False
                rel = diff / max(abs(u), abs(v))
                d.max_abs, d.max_rel = max(d.max_abs, diff), max(d.max_rel, rel)
                if diff > atol + rtol * max(abs(u), abs(v)):
                    d.n_different += 1
                    if len(d.worst) < 3:
                        d.worst.append(f"{col}[{i}]: {u:.6g} vs {v:.6g}")
            elif u != v:
                d.n_different += 1
                exact = False
                if len(d.worst) < 3:
                    d.worst.append(f"{col}[{i}]: {u!r} vs {v!r}")
    d.status = "different" if d.n_different else ("identical" if exact else "within_tolerance")
    return d


def compare_reports(
    a: Path, b: Path, rtol: float = 1e-6, atol: float = 1e-9, include_timing: bool = False
) -> list[TableDiff]:
    """Compare every CSV of a/tables against b/tables (a is the reference)."""
    out: list[TableDiff] = []
    names = sorted(
        {p.stem for p in (a / "tables").glob("*.csv")}
        | {p.stem for p in (b / "tables").glob("*.csv")}
    )
    for name in names:
        if name in TIMING_DEPENDENT and not include_timing:
            continue
        pa, pb = a / "tables" / f"{name}.csv", b / "tables" / f"{name}.csv"
        if not pa.exists() or not pb.exists():
            out.append(TableDiff(name, "missing_a" if not pa.exists() else "missing_b"))
            continue
        diff = compare_frames(pd.read_csv(pa), pd.read_csv(pb), rtol, atol)
        diff.name = name
        out.append(diff)
    return out


def compare_json(a: Path, b: Path, rtol: float = 1e-6) -> list[str]:
    """Differences between two metric JSON files (numbers within rtol); empty list = equal."""
    problems: list[str] = []

    def walk(x, y, path: str) -> None:
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y)):
                if k not in x or k not in y:
                    problems.append(f"{path}/{k}: only in one file")
                else:
                    walk(x[k], y[k], f"{path}/{k}")
        elif isinstance(x, list) and isinstance(y, list) and len(x) == len(y):
            for i, (u, v) in enumerate(zip(x, y, strict=True)):
                walk(u, v, f"{path}[{i}]")
        elif isinstance(x, (int, float)) and isinstance(y, (int, float)):
            if not np.isclose(x, y, rtol=rtol, atol=1e-9):
                problems.append(f"{path}: {x} vs {y}")
        elif x != y:
            problems.append(f"{path}: {x!r} vs {y!r}")

    walk(json.loads(a.read_text(encoding="utf-8")), json.loads(b.read_text(encoding="utf-8")), "")
    return problems


def summarize(diffs: list[TableDiff]) -> str:
    lines = [f"{'table':26s} {'status':17s} {'max rel':>10s} {'max abs':>10s} cells  different"]
    for d in diffs:
        lines.append(
            f"{d.name:26s} {d.status:17s} {d.max_rel:10.2e} {d.max_abs:10.2e} {d.n_cells:5d}  "
            f"{d.n_different}{'  ' + d.note if d.note else ''}"
        )
        lines += [f"    {w}" for w in d.worst]
    return "\n".join(lines)

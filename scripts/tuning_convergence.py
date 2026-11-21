"""How much does the Optuna search still gain after the 10th trial? (evidence for 20 trials)

Reads the stored studies (models/optuna.db) and writes reports/tables/rq1_tuning_convergence.csv:
per study the best validation RMSE after 1, 10 and 20 trials and the gain from the 10th to the 20th.
Only the first 20 trials of every study count (one study ran 40; see docs/KARARLAR.md).

    python -m scripts.tuning_convergence
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "models" / "optuna.db"
OUT = ROOT / "reports" / "tables" / "rq1_tuning_convergence.csv"
BUDGET = 20


def main() -> int:
    import optuna

    optuna.logging.set_verbosity(optuna.logging.ERROR)
    if not DB.exists():
        print(f"{DB} not found: run the tuning stage first (python -m scripts.run_all)")
        return 1
    url = f"sqlite:///{DB.as_posix()}"
    rows = []
    for summary in optuna.study.get_all_study_summaries(url):
        study = optuna.load_study(study_name=summary.study_name, storage=url)
        values = [
            t.value for t in study.trials if t.state.name == "COMPLETE" and t.value is not None
        ]
        values = values[:BUDGET]
        if len(values) < BUDGET:
            continue
        best = np.minimum.accumulate(values)
        rows.append(
            {
                "study": summary.study_name,
                "trials": len(values),
                "best_rmse_after_1": float(best[0]),
                "best_rmse_after_10": float(best[9]),
                "best_rmse_after_20": float(best[19]),
                "gain_10_to_20_pct": float(100 * (best[9] - best[19]) / best[9]),
            }
        )
    df = pd.DataFrame(rows).sort_values("study").reset_index(drop=True)
    mean = {"study": "MEAN", "trials": BUDGET, **{c: float(df[c].mean()) for c in df.columns[2:]}}
    df = pd.concat([df, pd.DataFrame([mean])], ignore_index=True)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(OUT, index=False, lineterminator="\n")
    print(df.round(3).to_string(index=False))
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

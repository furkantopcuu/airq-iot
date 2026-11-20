"""Result tables as LaTeX (paper/tables/*.tex) and Markdown (README) from reports/tables/*.csv.

python -m scripts.make_tables [--only NAME ...] [--readme]
--readme  also refreshes the <!-- TABLE:name --> blocks of README.md and README.tr.md
"""

from __future__ import annotations

import argparse

from airq.config import load_config
from airq.env import resolve_home
from airq.pipelines.tables import build_all, update_readme


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", nargs="*", help="table names (default: all)")
    ap.add_argument("--readme", action="store_true", help="refresh the README table blocks")
    args = ap.parse_args()
    cfg = load_config()
    made = build_all(cfg, args.only)
    for name, paths in made.items():
        print(f"{name}: {paths[0].name}, {paths[1].name}")
    if args.readme:
        for readme in ("README.md", "README.tr.md"):
            path = resolve_home() / readme
            if path.exists():
                print(readme, "->", update_readme(cfg, path, list(made)))


if __name__ == "__main__":
    main()

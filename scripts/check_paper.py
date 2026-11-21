"""Static checks for paper/main.tex (no LaTeX installation needed).

    python -m scripts.check_paper            # exit 1 on any ERROR
    python -m scripts.check_paper --literals # also list number literals typed in the running text

Checks: every \\nName macro is defined in numbers.tex; every \\cite key is in refs.bib; every \\ref has a
\\label; every \\input and figure file exists; braces and environments balance; abstract length; and
macros are followed by `{}` (otherwise LaTeX swallows the next space). The last option lists numbers that
were typed by hand instead of coming from a macro, so the NUMBERS.md review (TALIMAT 11.4) can be done.
"""

from __future__ import annotations

# ruff: noqa: E501  (long regular expressions and help text)
import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAPER = ROOT / "paper"


def strip_comments(text: str) -> str:
    return "\n".join(re.sub(r"(?<!\\)%.*$", "", line) for line in text.splitlines())


def load_macros() -> dict[str, str]:
    text = (PAPER / "numbers.tex").read_text(encoding="utf-8")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", text))


def bib_keys() -> set[str]:
    text = (PAPER / "refs.bib").read_text(encoding="utf-8")
    return set(re.findall(r"@\w+\{([^,\s]+),", text))


def labels() -> set[str]:
    found = set(
        re.findall(
            r"\\label\{([^}]+)\}", strip_comments((PAPER / "main.tex").read_text(encoding="utf-8"))
        )
    )
    main_body = strip_comments((PAPER / "main.tex").read_text(encoding="utf-8"))
    for name in re.findall(r"\\widetable\{([^}#]+)\}", main_body):
        f = PAPER / "tables" / f"{name}.tex"
        if f.exists():  # only the tables that main.tex really includes
            found |= set(re.findall(r"\\label\{([^}]+)\}", f.read_text(encoding="utf-8")))
    return found


def abstract_words(body: str, macros: dict[str, str], english: bool) -> int:
    if english:
        m = re.search(r"\\textit\{Abstract\}---\}%(.*?)\\selectlanguage\{turkish\}", body, re.S)
    else:
        m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", body, re.S)
    if not m:
        return 0
    text = m.group(1)
    for name, val in macros.items():
        text = text.replace(f"\\{name}{{}}", val)
    text = re.sub(r"\\[a-zA-Z]+\*?(\{[^}]*\})?", " ", text)
    text = re.sub(r"[\$\\{}~%]", " ", text)
    return len(re.findall(r"[^\W_]+(?:[.'’-][^\W_]+)*", text))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--literals", action="store_true", help="list numbers typed by hand in the running text"
    )
    args = ap.parse_args()
    errors: list[str] = []
    notes: list[str] = []

    raw = (PAPER / "main.tex").read_text(encoding="utf-8")
    body = strip_comments(raw)
    macros = load_macros()

    used = set(re.findall(r"\\(n[A-Z][A-Za-z]*)\b", body))
    for name in sorted(used - set(macros)):
        errors.append(f"macro \\{name} is used but not defined in numbers.tex")
    unused = sorted(set(macros) - used)
    notes.append(f"{len(used & set(macros))} number macros used, {len(unused)} defined but unused")
    for m in re.finditer(r"\\(n[A-Z][A-Za-z]*)(?!\{\})(?![A-Za-z])", body):
        if m.group(1) in macros and not body[m.end() :].startswith("{}"):
            line = body.count("\n", 0, m.start()) + 1
            errors.append(
                f"line {line}: \\{m.group(1)} is not followed by {{}} (the next space would be lost)"
            )

    keys = bib_keys()
    cited: set[str] = set()
    for group in re.findall(r"\\cite\{([^}]+)\}", body):
        cited |= {k.strip() for k in group.split(",")}
    for k in sorted(cited - keys):
        errors.append(f"\\cite key {k} is not in refs.bib")
    notes.append(f"{len(cited)} references cited; {len(keys - cited)} in refs.bib but not cited: "
                 f"{', '.join(sorted(keys - cited)) or 'none'}")  # fmt: skip

    defined = labels()
    refs = set(re.findall(r"\\ref\{([^}]+)\}", body))
    for r in sorted(refs - defined):
        errors.append(f"\\ref{{{r}}} has no \\label")
    for r in sorted(defined - refs):
        notes.append(f"label {r} is never referenced")

    for f in re.findall(r"\\(?:widetable|input)\{([^}#]+)\}", body):
        path = (
            PAPER / "tables" / f"{f}.tex"
            if (PAPER / "tables" / f"{f}.tex").exists()
            else PAPER / f"{f}.tex"
        )
        if not path.exists():
            errors.append(f"\\input/\\widetable file not found: {f}")
    for f in re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", body):
        if not (PAPER / f).exists():
            errors.append(f"figure not found: {f}")

    if body.count("{") != body.count("}"):
        errors.append(
            f"unbalanced braces in main.tex ({body.count('{')} open, {body.count('}')} close)"
        )
    for env in sorted(set(re.findall(r"\\begin\{([^}]+)\}", body))):
        if body.count(f"\\begin{{{env}}}") != body.count(f"\\end{{{env}}}"):
            errors.append(f"environment {env}: \\begin and \\end counts differ")

    for english, label in ((False, "Turkish abstract"), (True, "English abstract")):
        n = abstract_words(raw, macros, english)
        notes.append(f"{label}: about {n} words")
        if not 150 <= n <= 250:
            errors.append(f"{label} has {n} words, expected 150-250")

    if args.literals:
        text = re.sub(r"\\(cite|ref|label|input|widetable|includegraphics|bibliography\w*|usepackage|documentclass)"
                      r"(\[[^\]]*\])?\{[^}]*\}", " ", body)  # fmt: skip
        text = re.sub(r"\\n[A-Z][A-Za-z]*\{\}", " ", text)
        text = text.split("\\begin{document}", 1)[-1]
        found = []
        design = {
            "0",
            "1",
            "2",
            "3",
            "5",
            "6",
            "8",
            "10",
            "12",
            "20",
            "24",
            "50",
            "90",
            "95",
            "200",
        }
        for m in re.finditer(r"(?<![\w\\])\d+(?:[.,]\d+)?", text):
            if m.group(0) in design:  # horizons, thresholds, formula and grid constants
                continue
            start = max(0, m.start() - 28)
            found.append((m.group(0), text[start : m.end() + 20].replace("\n", " ")))
        notes.append(f"{len(found)} number literals typed in the text (design constants, years, section numbers "
                     "are expected; results must be macros):")  # fmt: skip
        notes.extend(f"    {num:>6}  ...{ctx}..." for num, ctx in found)

    for n in notes:
        print("note:", n)
    for e in errors:
        print("ERROR:", e)
    print(f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

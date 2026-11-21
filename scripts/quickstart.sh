#!/usr/bin/env bash
# airq-iot quick start for Linux, macOS, WSL and Git Bash (Windows PowerShell users: see README).
#
#   scripts/quickstart.sh [demo|test|live|all] [--dry-run] [--no-install]
#
#   demo   (default) set up, download the recorded demo run (checksum verified), open the dashboard on it.
#                    No data, models or MQTT broker needed.
#   test   set up and run the fast unit tests.
#   live   set up, download the models, run the full live demo (needs the cleaned dataset: see README).
#   all    test, then demo.
#
# Options: --dry-run prints every command without running it; --no-install skips pip install.
# Environment: PYTHON=python3.12 picks the interpreter (Python 3.11 or newer).
set -euo pipefail

MODE="demo"
DRY=0
INSTALL=1
for arg in "$@"; do
  case "$arg" in
    demo | test | live | all) MODE="$arg" ;;
    --dry-run) DRY=1 ;;
    --no-install) INSTALL=0 ;;
    -h | --help)
      sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "unknown argument: $arg (try --help)" >&2
      exit 2
      ;;
  esac
done

cd "$(dirname "$0")/.."

run() {
  echo "+ $*"
  if [ "$DRY" -eq 0 ]; then "$@"; fi
}

# --- find Python >= 3.11 -------------------------------------------------------------------------
find_python() {
  local c
  for c in "${PYTHON:-}" python3.12 python3.11 python3 python; do
    [ -n "$c" ] || continue
    if command -v "$c" > /dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2> /dev/null; then
      echo "$c"
      return 0
    fi
  done
  return 1
}

if ! PY="$(find_python)"; then
  echo "Python 3.11 or newer is required (set PYTHON=/path/to/python)." >&2
  exit 1
fi
echo "Using $("$PY" --version 2>&1) ($PY)"

# --- virtual environment -------------------------------------------------------------------------
if [ ! -d .venv ]; then
  run "$PY" -m venv .venv
fi
if [ -f .venv/bin/activate ]; then
  ACTIVATE=".venv/bin/activate"
elif [ -f .venv/Scripts/activate ]; then
  ACTIVATE=".venv/Scripts/activate"
else
  ACTIVATE=""
fi
if [ "$DRY" -eq 0 ]; then
  if [ -z "$ACTIVATE" ]; then
    echo "could not find the virtual environment's activate script in .venv" >&2
    exit 1
  fi
  # shellcheck disable=SC1090
  . "$ACTIVATE"
  PY=python
else
  echo "+ . ${ACTIVATE:-.venv/bin/activate}"
fi

if [ "$INSTALL" -eq 1 ]; then
  run "$PY" -m pip install --quiet --upgrade pip
  run "$PY" -m pip install --quiet -r requirements.txt
  run "$PY" -m pip install --quiet -e .
fi

# --- what to do ----------------------------------------------------------------------------------
do_test() {
  run "$PY" -m pytest -m "not broker and not slow" -q
}

do_demo() {
  run "$PY" -m scripts.fetch_release --only demo
  echo
  echo "Opening the dashboard on the recorded run: http://127.0.0.1:8501  (Ctrl+C stops everything)"
  run "$PY" -m scripts.demo --offline
}

do_live() {
  run "$PY" -m scripts.fetch_release --only models
  echo
  echo "The live demo also needs the cleaned dataset (python -m scripts.run_all, see README)."
  echo "Starting the live demo (broker, devices, edge, ingest, predictor, API, dashboard)."
  run "$PY" -m scripts.demo
}

case "$MODE" in
  test) do_test ;;
  demo) do_demo ;;
  live) do_live ;;
  all)
    do_test
    do_demo
    ;;
esac

# Contributing

- Branches: `feat/ml-*`, `feat/iot-*`, `paper/*`, `docs/*`; open a PR, CI must be green, squash-merge.
- Commit prefixes: `feat:`, `fix:`, `docs:`, `test:`, `exp:`, `paper:`, `chore:`. English messages.
- Run `pre-commit install` and `pytest -m "not broker and not slow"` before pushing.
- No secrets, raw data, absolute local paths or files larger than 5 MB.

#!/usr/bin/env bash
# Local validation for Unix-like shells. Run from the repository root: bash scripts/validate.sh
set -euo pipefail

python3.12 -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
[ -d .venv ] || python3.12 -m venv .venv
PY=.venv/bin/python
"$PY" -m pip install --upgrade pip
"$PY" -m pip install -e ".[dev]"
"$PY" -c "import tmc_access; print(tmc_access.__version__)"
"$PY" -m ruff check .
"$PY" -m ruff format --check .
"$PY" scripts/check_workflow.py
"$PY" scripts/scan_secrets.py
"$PY" -m pytest
echo "ALL VALIDATION STEPS PASSED (skipped tests are PENDING functionality, not successes)."

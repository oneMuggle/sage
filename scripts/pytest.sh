#!/usr/bin/env bash
# Portable pytest wrapper for lefthook pre-push hook.
#
# Resolution order (first match wins):
#   1. PYTEST_BIN environment variable (explicit override)
#   2. /home/fz/anaconda3/envs/sage-backend/bin/pytest (project default conda env)
#   3. `pytest` on PATH
#   4. `python -m pytest` (any python with pytest installed)
#
# Usage: scripts/pytest.sh [pytest-args...]
#
# Skips with warning (exit 0) only when pytest is entirely unavailable.

set -euo pipefail

if [ -n "${PYTEST_BIN:-}" ] && [ -x "${PYTEST_BIN}" ]; then
    exec "${PYTEST_BIN}" "$@"
fi

DEFAULT_CONDA_PYTEST="/home/fz/anaconda3/envs/sage-backend/bin/pytest"
if [ -x "${DEFAULT_CONDA_PYTEST}" ]; then
    exec "${DEFAULT_CONDA_PYTEST}" "$@"
fi

if command -v pytest > /dev/null 2>&1; then
    exec pytest "$@"
fi

if command -v python > /dev/null 2>&1 && python -c "import pytest" 2>/dev/null; then
    exec python -m pytest "$@"
fi

if command -v python3 > /dev/null 2>&1 && python3 -c "import pytest" 2>/dev/null; then
    exec python3 -m pytest "$@"
fi

echo "WARN: pytest not found in PYTEST_BIN, conda env, PATH, or python -m; skipping" >&2
exit 0

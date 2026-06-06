#!/usr/bin/env bash
# Portable ruff wrapper for lefthook hooks.
#
# Resolution order (first match wins):
#   1. RUFF_BIN environment variable (explicit override)
#   2. /home/fz/anaconda3/envs/sage-backend/bin/ruff (project default conda env)
#   3. `ruff` on PATH
#   4. `python -m ruff` (any python with ruff installed)
#
# Usage: scripts/lint.sh <ruff-subcommand> [args...]
#   e.g. scripts/lint.sh check --fix backend/foo.py
#        scripts/lint.sh format backend/foo.py
#
# Exit codes: forwarded from ruff. Skips silently (exit 0) only when ruff is
# entirely unavailable, with a warning to stderr.

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <ruff-subcommand> [args...]" >&2
    exit 2
fi

if [ -n "${RUFF_BIN:-}" ] && [ -x "${RUFF_BIN}" ]; then
    exec "${RUFF_BIN}" "$@"
fi

DEFAULT_CONDA_RUFF="/home/fz/anaconda3/envs/sage-backend/bin/ruff"
if [ -x "${DEFAULT_CONDA_RUFF}" ]; then
    exec "${DEFAULT_CONDA_RUFF}" "$@"
fi

if command -v ruff > /dev/null 2>&1; then
    exec ruff "$@"
fi

if command -v python > /dev/null 2>&1 && python -c "import ruff" 2>/dev/null; then
    exec python -m ruff "$@"
fi

if command -v python3 > /dev/null 2>&1 && python3 -c "import ruff" 2>/dev/null; then
    exec python3 -m ruff "$@"
fi

echo "WARN: ruff not found in RUFF_BIN, conda env, PATH, or python -m; skipping" >&2
exit 0

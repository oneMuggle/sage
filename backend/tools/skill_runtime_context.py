"""Non-secret Sage runtime metadata for shell-facing tools.

The backend process knows which Python interpreter runs it (propagated
by Electron via ``SAGE_RUNTIME_PYTHON``). This module exposes that
knowledge to tools (bash, skill scripts) so the LLM can reference the
Sage interpreter explicitly instead of guessing ``python3`` on PATH.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any, Dict, Optional

# Keys that must NEVER appear in the env dict returned by get_runtime_context().
_SECRET_SUFFIXES = (
    "_TOKEN",
    "_KEY",
    "_SECRET",
    "_PASSWORD",
)
_SECRET_EXACT = frozenset({
    "SAGE_LOCAL_AUTH_TOKEN",
    "SAGE_BACKEND_OWNERSHIP_TOKEN",
})


def _is_safe_env_key(key: str) -> bool:
    upper = key.upper()
    if upper in _SECRET_EXACT:
        return False
    return not any(upper.endswith(suffix) for suffix in _SECRET_SUFFIXES)


def get_runtime_context() -> Dict[str, Any]:
    """Return structured non-secret runtime metadata.

    Fields:
        python_path: validated value of ``SAGE_RUNTIME_PYTHON`` when it is a
            regular executable file, or None if absent/invalid. Sourced solely
            from the env var — no fallback to CONDA_PREFIX, sys.executable,
            or shutil.which("python").
        env: dict of non-secret environment variables (PATH, LANG, etc.).
    """
    python_path: Optional[str] = None
    raw = os.environ.get("SAGE_RUNTIME_PYTHON")
    if raw:
        try:
            st = Path(raw).stat()
            if stat.S_ISREG(st.st_mode) and os.access(raw, os.X_OK):
                python_path = raw
        except (OSError, ValueError):
            python_path = None

    env = {k: v for k, v in os.environ.items() if _is_safe_env_key(k)}

    return {"python_path": python_path, "env": env}

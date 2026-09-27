# ruff: noqa: UP038 — Python 3.8 does not support isinstance union types
"""Optional Excel calculation in a terminable, resource-limited subprocess.

Parsing, formula enumeration, engine import, computation and serialization
share one 15-second worker deadline. Win7 without formulas/job support keeps
cached values and the existing unresolved-formula notice. This is not an
egress/security sandbox; cancellation is an internal API, not yet UI-wired.
"""
from __future__ import annotations

import logging
import math
import re
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from .worker_process import MAX_INPUT_BYTES, run_json_worker

logger = logging.getLogger(__name__)
_MAX_FORMULA_CELLS = 500
_EVAL_TIMEOUT_SECONDS = 15.0
_WORKER_SCRIPT = Path(__file__).with_name("formula_worker.py")


def _validate_result(payload: Any) -> Optional[Dict[str, Dict[str, Any]]]:  # noqa: PLR0911 — protocol guards
    if not isinstance(payload, dict) or payload.get("version") != 1:
        return None
    values = payload.get("values")
    if not isinstance(values, dict):
        return None
    count = 0
    for sheet, cells in values.items():
        if not isinstance(sheet, str) or not isinstance(cells, dict):
            return None
        count += len(cells)
        if count > _MAX_FORMULA_CELLS:
            return None
        for address, value in cells.items():
            if not isinstance(address, str) or not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", address):
                return None
            if not isinstance(value, (str, bool, int, float)):
                return None
            if isinstance(value, float) and not math.isfinite(value):
                return None
    return values


def evaluate_workbook(
    file_path: Path, *, cancel_event: Optional[threading.Event] = None
) -> Optional[Dict[str, Dict[str, Any]]]:
    """Return formula values, {} for no formulas, None on any unavailable result."""
    try:
        path = Path(file_path).resolve()
        if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
            return None
        with tempfile.TemporaryDirectory(prefix="sage-formula-") as directory:
            output = Path(directory) / "result.json"
            result = run_json_worker(
                [sys.executable, "-I", str(_WORKER_SCRIPT), str(path), str(output),
                 str(_MAX_FORMULA_CELLS), str(max(1, math.ceil(_EVAL_TIMEOUT_SECONDS)))],
                output,
                timeout=_EVAL_TIMEOUT_SECONDS,
                cancel_event=cancel_event,
            )
            return _validate_result(result)
    except Exception:  # noqa: BLE001 — malformed/unavailable calculations are optional
        logger.warning("excel_eval: local evaluation unavailable", exc_info=True)
        return None


__all__ = ["evaluate_workbook"]

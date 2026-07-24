#!/usr/bin/env python3
"""Stdlib-only Windows path-safety canary for the Office module.

This script is the lightweight CI guardrail for
``backend.office.path_safety.is_within``. It exercises the Windows
flavor of the helper without requiring any third-party dependency
(FastAPI, Pydantic, the Office readers, etc.) to be importable — only
the standard library is used, so it can run from a fresh
``actions/setup-python`` Python on the Windows runner before the full
Python bundle is assembled.

Why this exists:

* ``backend/office/path_safety.py`` fixes a sibling-prefix bug
  (``/tmp/work-evil`` slipping past a ``startswith(workspace)`` check)
  by delegating to ``PurePath.relative_to``. The fix is load-bearing
  for the Office workspace sandbox; losing it in a future refactor
  would silently re-open the traversal.
* This canary is intentionally stdlib-only so it can run **before** the
  full Python embeddable bundle (which carries python-pptx /
  python-docx / openpyxl and is several hundred MB) is built. Failing
  fast on the cheap guardrail saves CI time.

Exit codes:

* ``0`` — all assertions passed (valid fixture is inside the workspace,
  the sibling-prefix fixture is rejected).
* ``1`` — at least one assertion failed. The script prints a human
  readable diagnostic to stderr before exiting.

Usage::

    python scripts/verify-office-paths.py
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import PureWindowsPath


# Positional import: ``backend`` is only resolvable when the script runs
# from the repository root with PYTHONPATH set (CI does this). We probe
# ``backend.office.path_safety`` defensively — if the package layout is
# broken (e.g. a refactor moves the module), the script prints a clear
# error instead of a confusing ImportError stack trace.
def _load_path_safety():
    try:
        return importlib.import_module("backend.office.path_safety")
    except Exception:
        traceback.print_exc()
        print(
            "verify-office-paths: failed to import backend.office.path_safety. "
            "Run from the repository root with PYTHONPATH=.",
            file=sys.stderr,
        )
        sys.exit(1)


def _assert(cond: bool, message: str) -> None:
    if not cond:
        print(f"FAIL: {message}", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    path_safety = _load_path_safety()

    workspace = PureWindowsPath(r"C:\work")
    valid_target = PureWindowsPath(r"C:\work\office\word\id\file.docx")
    sibling_prefix = PureWindowsPath(r"C:\work-evil\office\word\id\file.docx")
    outside = PureWindowsPath(r"D:\elsewhere\file.docx")
    same_root = PureWindowsPath(r"C:\work")

    # 1. Happy path: a real Office doc inside the workspace.
    _assert(
        path_safety.is_within(workspace, valid_target),
        "expected C:\\work\\office\\word\\id\\file.docx to be inside C:\\work",
    )

    # 2. Sibling-prefix traversal: the bug the fix was written for.
    # ``C:\work-evil`` shares the ``C:\work`` string prefix but is NOT a
    # child. A naive str.startswith check would accept this; relative_to
    # must reject it.
    _assert(
        not path_safety.is_within(workspace, sibling_prefix),
        "sibling-prefix C:\\work-evil was accepted as inside C:\\work — "
        "path_safety.is_within has regressed to a str.startswith check",
    )

    # 3. Different drive entirely.
    _assert(
        not path_safety.is_within(workspace, outside),
        "D:\\elsewhere\\file.docx should NOT be inside C:\\work",
    )

    # 4. Workspace itself: relative_to(base, base) succeeds with an
    # empty Path — make sure we don't accidentally reject the
    # workspace-as-its-own-child case.
    _assert(
        path_safety.is_within(workspace, same_root),
        "workspace itself should be considered inside its own root",
    )

    print("verify-office-paths: OK (workspace, sibling-prefix, outside, self)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
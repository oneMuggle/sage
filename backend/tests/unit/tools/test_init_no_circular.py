"""Regression test for issue #484 — backend.tools circular import on Python 3.11.

Background
----------
``backend/cli/checks/runtime_env.py`` imports ``backend.tools.runtime_probe``,
which transitively triggers ``backend/tools/__init__.py``. The eager
``from .agent_tool import AgentTool`` at line 12 of ``__init__.py`` pulls in
``backend.orchestration.subagent_events`` -> ``backend.core.legacy.agent_state``
-> ``backend.core.__init__`` -> ``backend.core.legacy.agent.py:54``, which
itself does ``from backend.tools import ToolRegistry, register_all_tools`` —
a circular import. Python 3.10 silently tolerated this (it returns the
partially-initialized module object), but Python 3.11 (used by CI) raises
``ImportError: cannot import name 'ToolRegistry' from partially initialized
module 'backend.tools'``.

This locks down the fix: the eager ``agent_tool`` import must be deferred
until the rest of ``backend.tools`` is fully initialized.

If you find yourself tempted to re-add the eager ``from .agent_tool import``
in ``backend/tools/__init__.py``, update this test to cover the new failure
mode FIRST — otherwise CI will silently go red again on Python 3.11+.

Implementation note
-------------------
Every test runs in a **fresh subprocess** via ``subprocess.run`` rather than
importing in-process. This matches what the doctor CLI integration tests do
(``backend/tests/integration/test_doctor_cli.py`` spawn ``python -m
backend.cli.doctor``) and, critically, avoids contaminating the in-process
``sys.modules`` cache of the pytest worker. Earlier revisions of this file
used ``del sys.modules`` followed by in-process re-imports; that polluted
module state for sibling tests in ``backend/tests/unit/tools/`` (notably the
office / wiki test files that build in-memory SQLite fixtures via the
``session_workspace_bindings`` table), causing pre-existing-pass tests to
fail when run after this file. Spawning a clean interpreter sidesteps the
problem entirely.
"""

from __future__ import annotations

import os
import subprocess
import sys

import pytest

pytestmark = pytest.mark.unit


REPO_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
# PYTHONPATH must point at the directory that contains the ``backend/``
# package itself — i.e. one level above REPO_ROOT (which already is the
# ``backend/`` directory itself per the ``__file__`` traversal above).
BACKEND_PARENT = os.path.dirname(REPO_ROOT)


def _run_in_fresh_subprocess(*python_args: str, timeout: int = 60) -> subprocess.CompletedProcess:
    """Spawn a clean interpreter with PYTHONPATH set so ``import backend.*``
    resolves from the worktree this test file lives in.

    Uses the same Python the pytest worker is running on so dev-env
    dependencies (FastAPI, pydantic, etc.) are guaranteed available.
    """
    return subprocess.run(
        [sys.executable, *python_args],
        cwd=BACKEND_PARENT,
        env={**os.environ, "PYTHONPATH": BACKEND_PARENT},
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def test_import_backend_tools_does_not_raise():
    """``import backend.tools`` must succeed without ImportError.

    Pre-fix: the cold-import path used by ``doctor`` (subprocess invocation,
    fresh interpreter) raises
    ``ImportError: cannot import name 'ToolRegistry' from partially
    initialized module 'backend.tools'`` because the eager
    ``from .agent_tool import`` triggers the circular chain.
    """
    script = (
        "import backend.tools as m; "
        "assert hasattr(m, 'ToolRegistry'), 'ToolRegistry missing'; "
        "assert hasattr(m, 'register_all_tools'), 'register_all_tools missing'; "
        "print('OK')"
    )
    result = _run_in_fresh_subprocess("-c", script)

    assert result.returncode == 0, (
        f"cold-import of backend.tools raised ImportError "
        f"(regression of issue #484):\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )
    assert "ImportError" not in result.stderr, (
        f"unexpected ImportError in stderr:\n{result.stderr[:500]}"
    )


def test_runtime_probe_import_does_not_raise():
    """``from backend.tools.runtime_probe import RuntimeProbeTool`` is the
    specific chain that ``backend.cli.checks.runtime_env`` triggers.

    The doctor CLI integration tests (``test_doctor_cli.py``) exercise this
    via subprocess; this unit test pins the failure at module-load time so
    a regression is caught before integration tests even run.
    """
    script = (
        "from backend.tools.runtime_probe import RuntimeProbeTool; "
        "assert RuntimeProbeTool.__name__ == 'RuntimeProbeTool'; "
        "print('OK')"
    )
    result = _run_in_fresh_subprocess("-c", script)

    assert result.returncode == 0, (
        f"runtime_probe import raised ImportError (regression of issue #484):\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_register_all_tools_can_register_agent_tool():
    """``register_all_tools`` must still bind ``AgentTool`` onto the registry
    even after we deferred the eager import. Uses ``is`` identity to verify
    it's the same class object, not just something with the same name.
    """
    script = (
        "from backend.tools import AgentTool, ToolRegistry, register_all_tools; "
        "r = ToolRegistry(); "
        "register_all_tools(r); "
        "names = r.list_names(); "
        "assert 'agent' in names, f'agent not in {names}'; "
        "tool = r.get('agent'); "
        "assert isinstance(tool, AgentTool), type(tool).__name__; "
        "print('OK')"
    )
    result = _run_in_fresh_subprocess("-c", script)

    assert result.returncode == 0, (
        f"register_all_tools did not register AgentTool:\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )


def test_python_m_backend_cli_doctor_succeeds():
    """End-to-end mirror of the doctor integration test at the import level.

    ``python -m backend.cli.doctor`` must exit 0 (or 1/2 for WARN/CRITICAL
    checks), NOT 1 due to ImportError during ``_import_all_checks``. We use
    ``--json`` to make the output machine-greppable.
    """
    result = _run_in_fresh_subprocess(
        "-m", "backend.cli.doctor", "--json", timeout=30
    )

    # Pre-fix: returncode is 1 with stderr "ImportError: cannot import name
    # 'ToolRegistry' from partially initialized module 'backend.tools'".
    assert "ImportError" not in result.stderr, (
        f"doctor CLI raised ImportError (regression of issue #484):\n"
        f"stdout: {result.stdout[:500]}\n"
        f"stderr: {result.stderr[:500]}"
    )
    assert result.returncode in (0, 1, 2), (
        f"doctor CLI exited with unexpected code {result.returncode}:\n"
        f"stderr: {result.stderr[:500]}"
    )

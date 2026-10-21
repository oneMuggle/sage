"""py38_compat_rewrite.py `--check --fail-on-drift` 的退出码契约。

背景：该 flag 自 2026-10 起在文档里被描述为「已支持退出码」，
但 `main()` 结尾无条件 `return 0`，于是任何把它当闸门用的 CI 都是空转 ——
漂移永远被发现、永远不失败。这个文件是那处修复的回归测试。
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("libcst", reason="py38_compat_rewrite 依赖 libcst")

REPO = Path(__file__).resolve().parents[3]
SCRIPT = REPO / "scripts" / "py38_compat_rewrite.py"

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 10),
    reason="脚本自身使用 PEP 604 语法，import 即需要 Python 3.10+",
)

# 会被重写成 typing.Optional[int]
DRIFT_SOURCE = "def f(x: int | None) -> int | None:\n    return x\n"
# 无需重写
CLEAN_SOURCE = "def f(x):\n    return x\n"


def _run(tmp_path: Path, source: str, *flags: str) -> subprocess.CompletedProcess:
    target = tmp_path / "sample.py"
    target.write_text(source, encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(SCRIPT), *flags, str(target)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_drift_with_fail_on_drift_exits_nonzero(tmp_path: Path) -> None:
    proc = _run(tmp_path, DRIFT_SOURCE, "--check", "--fail-on-drift")
    assert proc.returncode == 1, proc.stdout + proc.stderr
    assert "would rewrite" in proc.stdout


def test_drift_without_flag_still_exits_zero(tmp_path: Path) -> None:
    proc = _run(tmp_path, DRIFT_SOURCE, "--check")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "would rewrite" in proc.stdout


def test_no_drift_exits_zero(tmp_path: Path) -> None:
    proc = _run(tmp_path, CLEAN_SOURCE, "--check", "--fail-on-drift")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "would rewrite" not in proc.stdout

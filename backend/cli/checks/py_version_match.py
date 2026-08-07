"""检查当前 Python 版本与 backend/requirements.txt 声明是否一致。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register

# 形如 "python>=3.11" / "python==3.8" / "python~=3.10"
_PY_REQ_RE = re.compile(r"^\s*python\s*(>=|<=|==|~=|!=|>|<)\s*([0-9.]+)\s*$", re.IGNORECASE)


def _parse_python_requirement(req_path: Path):
    """从 requirements.txt 解析 python 约束。

    返回 (op, version_tuple) 或 None(未声明)。
    """
    if not req_path.exists():
        return None
    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return None

    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        m = _PY_REQ_RE.match(line)
        if m:
            op, ver = m.group(1), m.group(2)
            parts = ver.split(".")
            try:
                version_tuple = tuple(int(p) for p in parts)
            except ValueError:
                return None
            return op, version_tuple
    return None


def _compare(current: tuple, op: str, target: tuple) -> bool:  # noqa: PLR0911 — 8 operators (>=, <=, ==, !=, >, <, ~=, !)
    """满足约束返回 True。"""
    if op == ">=":
        return current >= target
    if op == "<=":
        return current <= target
    if op == "==":
        return current == target
    if op == ">":
        return current > target
    if op == "<":
        return current < target
    if op == "!=":
        return current != target
    if op == "~=":
        return current[: len(target) - 1] == target[: len(target) - 1] and current >= target
    return False


@register
class PyVersionMatchCheck:
    name = "py_version_match"
    description = "Python 版本与 backend/requirements.txt 一致性"

    def run(self) -> CheckResult:
        # backend/cli/checks/py_version_match.py -> ../../../backend/requirements.txt
        req_path = Path(__file__).resolve().parents[2] / "requirements.txt"
        parsed = _parse_python_requirement(req_path)
        if parsed is None:
            return CheckResult(
                self.name,
                Severity.INFO,
                "backend/requirements.txt 未声明 python 版本约束",
            )

        op, target = parsed
        current = (sys.version_info.major, sys.version_info.minor)
        target_str = ".".join(str(p) for p in target)

        if _compare(current, op, target):
            return CheckResult(
                self.name,
                Severity.INFO,
                f"Python {current[0]}.{current[1]} 满足 requirements.txt 约束 python{op}{target_str}",
            )

        return CheckResult(
            self.name,
            Severity.CRITICAL,
            f"Python {current[0]}.{current[1]} 不满足 requirements.txt 约束 python{op}{target_str}",
            "切到正确的 conda 环境",
        )

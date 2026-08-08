"""检查当前 Python 版本与后端声明的 python 约束是否一致。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

from backend.cli.doctor import CheckResult, Severity, register

# 形如 "python>=3.11" / "python==3.8" / "python~=3.10"
# 以及 conda environment.yml 的 "- python=3.8"（行首 bullet + 单 "="）
_PY_REQ_RE = re.compile(r"^\s*python\s*(>=|<=|==|~=|!=|>|<|=)\s*([0-9.]+)\s*$", re.IGNORECASE)


def _parse_constraint(text: str):
    """从文本中解析 python 约束。

    同时支持 requirements 行（``python>=3.11``）与 conda environment.yml 的
    ``- python=3.8`` 列表项。返回 (op, version_tuple) 或 None(未声明)。
    """
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if line.startswith("- "):
            line = line[2:].strip()  # conda 列表项 bullet
        if not line:
            continue
        m = _PY_REQ_RE.match(line)
        if not m:
            continue
        op, ver = m.group(1), m.group(2)
        if op == "=":
            op = "=="  # conda `python=3.8` 等价于精确锁定 3.8.x
        parts = ver.split(".")
        try:
            version_tuple = tuple(int(p) for p in parts)
        except ValueError:
            return None
        return op, version_tuple
    return None


def _parse_python_requirement(req_path: Path):
    """从 requirements 文件解析 python 约束。

    返回 (op, version_tuple) 或 None(未声明)。
    """
    if not req_path.exists():
        return None
    try:
        text = req_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_constraint(text)


def _parse_environment_yml(env_path: Path):
    """从 conda environment.yml 解析 python 约束（``- python=X.Y``）。

    返回 (op, version_tuple) 或 None(未声明)。
    """
    if not env_path.exists():
        return None
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _parse_constraint(text)


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


def _find_python_constraint(backend_dir: Path):
    """按优先级查找后端声明的 python 约束。

    返回 (source_name, (op, version_tuple)) 或 (None, None)。

    来源优先级:
      1. ``requirements-py38.txt``（win7 LTS 分支的生效规范，main 上残留文件同样会先被查询）
      2. ``requirements.txt``
      3. ``environment.yml`` —— requirements 无法写裸 ``python==X.Y``（pip 会把
         它当 PyPI 包解析），conda 的 ``python=X.Y`` 是 python 版本约束的规范声明位置。

    同一优先级文件存在但未声明约束时继续尝试下一来源（首个命中约束者胜出）。
    """
    for name in ("requirements-py38.txt", "requirements.txt"):
        path = backend_dir / name
        if not path.exists():
            continue
        parsed = _parse_python_requirement(path)
        if parsed is not None:
            return name, parsed
    env_yml = backend_dir / "environment.yml"
    parsed = _parse_environment_yml(env_yml)
    if parsed is not None:
        return "environment.yml", parsed
    return None, None


@register
class PyVersionMatchCheck:
    name = "py_version_match"
    description = "Python 版本与 backend/requirements.txt / environment.yml 一致性"

    def run(self) -> CheckResult:
        backend_dir = Path(__file__).resolve().parents[2]
        src_name, parsed = _find_python_constraint(backend_dir)
        if parsed is None:
            return CheckResult(
                self.name,
                Severity.INFO,
                "backend/requirements.txt 与 environment.yml 均未声明 python 版本约束",
            )

        op, target = parsed
        current = (sys.version_info.major, sys.version_info.minor)
        target_str = ".".join(str(p) for p in target)

        if _compare(current, op, target):
            return CheckResult(
                self.name,
                Severity.INFO,
                f"Python {current[0]}.{current[1]} 满足 {src_name} 约束 python{op}{target_str}",
            )

        return CheckResult(
            self.name,
            Severity.CRITICAL,
            f"Python {current[0]}.{current[1]} 不满足 {src_name} 约束 python{op}{target_str}",
            "切到正确的 conda 环境",
        )

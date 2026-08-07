"""Sage Doctor — 安装/环境 self-check CLI。

用法::

    python -m backend.cli.doctor            # 人类可读文本报告
    python -m backend.cli.doctor --json     # 机器可读 JSON

协议骨架:

- :class:`Severity` 三级严重度
- :class:`CheckResult` dataclass 报告结果
- :class:`Check` Protocol,所有检查类实现 ``name`` / ``description`` / ``run()``
- :func:`register` 装饰器,把检查类加入全局 :data:`ALL_CHECKS` 列表
- :func:`main` CLI 入口,文本/JSON 双输出,失败 fail-open,退出码 0/1/2

Win7 LTS (Py3.8) 兼容约束:

- 模块顶层 ``from __future__ import annotations`` — 所有注解惰性求值
- 避免 walrus / match/case 在模块顶层
"""
from __future__ import annotations

import argparse
import dataclasses
import datetime
import enum
import json
import platform
import sys
from typing import Optional, Protocol, runtime_checkable


class Severity(str, enum.Enum):
    """检查结果严重度。

    ``str`` 混合使 ``json.dumps`` 直接序列化为字符串。
    """

    CRITICAL = "critical"
    WARN = "warn"
    INFO = "info"


@dataclasses.dataclass(frozen=True)
class CheckResult:
    """单次检查的不可变结果。"""

    name: str
    severity: Severity
    message: str
    fix_hint: Optional[str] = None

    def to_dict(self) -> dict:
        """序列化为 JSON 友好 dict。"""
        return {
            "name": self.name,
            "severity": self.severity.value,
            "message": self.message,
            "fix_hint": self.fix_hint,
        }


@runtime_checkable
class Check(Protocol):
    """所有检查类实现此协议。"""

    name: str
    description: str

    def run(self) -> CheckResult:
        """执行检查并返回结果。"""
        ...


# 全局注册表:每项 check 模块 import 时调用 ``register(cls)`` append。
ALL_CHECKS: list = []


def register(cls: type) -> type:
    """类装饰器:把 Check 类加入 :data:`ALL_CHECKS`。

    用法::

        @register
        class MyCheck:
            name = "my_check"
            ...

    返回原类以便链式使用。
    """
    ALL_CHECKS.append(cls)
    return cls


# ---------------------------------------------------------------------------
# 运行器
# ---------------------------------------------------------------------------


def _run_one(check_cls: type) -> CheckResult:
    """执行单个 check,异常时降级为 WARN(fail-open)。"""
    instance = check_cls()
    try:
        return instance.run()
    except Exception as exc:  # noqa: BLE001 - fail-open 由 doctor 兜底
        return CheckResult(
            name=getattr(instance, "name", check_cls.__name__),
            severity=Severity.WARN,
            message=f"check 自身异常: {exc.__class__.__name__}: {exc}",
            fix_hint="请检查该 check 实现,或上报 issue",
        )


def _summarize(results: list) -> dict:
    """统计严重度分布。"""
    summary = {"critical": 0, "warn": 0, "info": 0}
    for r in results:
        summary[r.severity.value] += 1
    return summary


def _format_text(results: list) -> str:
    """人类可读文本报告。"""
    lines: list = []
    timestamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")  # noqa: UP017 — datetime.timezone.utc for Py3.8/3.10 compat (UP017 only triggers on datetime.UTC)
    lines.append(f"sage doctor - {timestamp}")
    lines.append("=" * 60)
    for r in results:
        tag = f"[{r.severity.value.upper():>8}]"
        lines.append(f"{tag} {r.name:<22} {r.message}")
        if r.fix_hint:
            lines.append("{} fix: {}".format(" " * 12, r.fix_hint))
    lines.append("=" * 60)
    summary = _summarize(results)
    lines.append(
        "总计: {} 项检查 (CRITICAL: {}, WARN: {}, INFO: {})".format(
            len(results), summary["critical"], summary["warn"], summary["info"]
        )
    )
    return "\n".join(lines)


def _format_json(results: list) -> str:
    """JSON 报告(机器可读)。"""
    payload: dict = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),  # noqa: UP017 — datetime.timezone.utc for Py3.8/3.10 compat
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system().lower(),
        "checks": [r.to_dict() for r in results],
        "summary": _summarize(results),
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def _exit_code(results: list) -> int:
    """退出码:2=有 CRITICAL,1=有 WARN,0=全 OK/只有 INFO。"""
    has_critical = any(r.severity == Severity.CRITICAL for r in results)
    if has_critical:
        return 2
    has_warn = any(r.severity == Severity.WARN for r in results)
    if has_warn:
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------


def _import_all_checks() -> None:
    """导入所有 check 子模块,触发 ``@register`` 注册。

    用 ``importlib`` 而非静态 import,避免循环依赖。
    """
    import importlib

    pkg = "backend.cli.checks"
    for mod_name in (
        "conda_env",
        "backend_health",
        "sqlite_writable",
        "config_integrity",
        "port_backend",
        "port_frontend",
        "py_version_match",
        "disk_space",
    ):
        importlib.import_module(f"{pkg}.{mod_name}")


def build_parser() -> argparse.ArgumentParser:
    """构造 CLI 参数解析器(可独立测试)。"""
    parser = argparse.ArgumentParser(
        prog="backend.cli.doctor",
        description="Sage 安装/环境诊断 CLI",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="以 JSON 格式输出(机器可读)",
    )
    return parser


def main(argv: Optional[list] = None) -> int:
    """CLI 入口,返回退出码(0/1/2)。"""
    _import_all_checks()
    # python -m X.Y 时 sys.modules['X.Y'] 和 sys.modules['__main__'] 是两个独立模块对象,
    # check 子模块通过 ``from backend.cli.doctor import register`` 实际注册到 sys.modules['backend.cli.doctor'].
    # 改用已 import 的 backend.cli.doctor 模块读 ALL_CHECKS,避免空列表。
    import backend.cli.doctor as _qualified  # noqa: PLW0406 — python -m X.Y requires this
    all_checks = _qualified.ALL_CHECKS
    args = build_parser().parse_args(argv)

    results: list = [_run_one(cls) for cls in all_checks]

    if args.as_json:
        print(_format_json(results))  # noqa: T201 — CLI output
    else:
        print(_format_text(results))  # noqa: T201 — CLI output

    return _exit_code(results)


if __name__ == "__main__":
    sys.exit(main())

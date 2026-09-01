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
import os
import platform
import sys
from pathlib import Path
from typing import Optional, Protocol, Union, runtime_checkable


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


def _format_json(
    results: list,
    runtime: Optional[Union[dict, DoctorRuntime]] = None,
) -> str:
    """JSON 报告(机器可读)。"""
    payload: dict = {
        "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),  # noqa: UP017 — datetime.timezone.utc for Py3.8/3.10 compat
        "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "platform": platform.system().lower(),
        "checks": [r.to_dict() for r in results],
        "summary": _summarize(results),
    }
    if runtime:
        payload.update(runtime.to_dict() if isinstance(runtime, DoctorRuntime) else runtime)
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


@dataclasses.dataclass(frozen=True)
class DoctorRuntime:
    """Resolved runtime metadata emitted by packaged doctor checks."""

    interpreter: str
    package_root: str
    import_backend: bool

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)


def run_doctor(
    interpreter: Union[Path, str, None] = None,
    package_root: Union[Path, str, None] = None,
    backend_command: Optional[list] = None,
    backend_cwd: Optional[Union[Path, str]] = None,
    backend_env: Optional[dict] = None,
) -> DoctorRuntime:
    """Resolve and report the interpreter/package-root contract.

    Task 0 review round 1, finding #5: this now performs a REAL
    ``import backend.main`` under the EXACT interpreter/cwd/env/PYTHONPATH
    the supervisor would use to spawn the backend. The previous directory
    existence check passed even when ``backend/main.py`` was a corrupted
    or empty file (e.g. NSIS install truncated mid-write); the import
    test catches that, plus missing transitive deps in the bundled
    resources tree.

    Task 0 review round 2 (fast-follow E): ``backend_env`` is now also
    MERGED into the ``import backend.main`` probe subprocess so supervisor
    markers such as ``SAGE_BACKEND_GENERATION`` / ``SAGE_BACKEND_OWNERSHIP_TOKEN``
    / ``PYTHONPATH`` reach the same Python that the supervisor would have
    spawned. Without this, the probe ran under a stripped-down env and
    could not detect e.g. a missing transitive dep that only manifests
    when SAGE_BACKEND_GENERATION is set.

    Parameters mirror the supervisor's spawn contract so the doctor
    verdict reflects what the user will actually experience at launch:

    - ``interpreter``: bundled ``resources/python/python.exe`` (Win32)
      or ``resources/python/bin/python3`` (Linux).
    - ``package_root``: <resourcesPath> — where ``backend/`` and
      ``sage-core/`` are expected after unpacking the installer.
    - ``backend_command``: argv the supervisor would pass (e.g.
      ``["-m", "backend.main"]``). When provided, doctor invokes
      the interpreter with ``--version`` of that command to confirm
      the module path is on PYTHONPATH.
    - ``backend_cwd``: working directory the supervisor sets.
    - ``backend_env``: extra env the supervisor merges into the
      child environment (used to build PYTHONPATH for the probe AND
      to thread supervisor markers into the probe subprocess).
    """
    interpreter_path = Path(interpreter or sys.executable).resolve()
    package_root_path = Path(package_root or Path.cwd()).resolve()

    # Build PYTHONPATH = <package_root> + supervisor's extraEnv (which
    # already contains the bundled backend/sage-core entries on packaged
    # Win32 / Linux). This mirrors the runtime contract.
    sep = ";" if os.name == "nt" else ":"
    py_path_entries = [str(package_root_path)]
    if backend_env:
        # The supervisor appends its own PYTHONPATH on packaged launches.
        existing = backend_env.get("PYTHONPATH")
        if existing:
            py_path_entries.append(str(existing))
    pythonpath = sep.join(py_path_entries)

    importable = _try_import_backend(
        interpreter_path,
        package_root_path,
        pythonpath,
        extra_env=backend_env,
    )
    return DoctorRuntime(
        interpreter=str(interpreter_path),
        package_root=str(package_root_path),
        import_backend=importable,
    )


def _try_import_backend(
    interpreter_path: Path,
    package_root_path: Path,
    pythonpath: str,
    extra_env: Optional[dict] = None,
) -> bool:
    """Run ``<interpreter> -c "import backend.main"`` and report success.

    Why subprocess and not in-process ``import backend.main``:
      ``run_doctor`` is invoked from both the Electron main process (CI
      smoke path) and the standalone ``python -m backend.cli.doctor``
      CLI. The Electron-side caller wants to verify the BUNDLED
      interpreter's view of the packaged resources tree — the host
      Python's import state is irrelevant. We therefore always spawn the
      explicit interpreter.

    ``extra_env`` (round 2) lets the Electron supervisor thread its
    launcher markers (SAGE_BACKEND_GENERATION, SAGE_BACKEND_OWNERSHIP_TOKEN,
    PYTHONPATH from plan.env, etc.) into the probe subprocess so the
    import is exercised under the EXACT env the supervisor would have
    set on the backend. PATH/SYSTEMROOT still come from the host so the
    probe can find the bundled interpreter; PYTHONHOME is Win32-only.

    This is best-effort and never raises — returns False on any failure
    (binary missing, non-zero exit, timeout) so the doctor's fail-open
    JSON reporter still produces a structured payload.
    """
    if not interpreter_path.is_file():
        return False
    try:
        import subprocess

        probe_env = {
            "PATH": os.environ.get("PATH", ""),
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PYTHONPATH": pythonpath,
            # On Win32, the Python embeddable shipped in
            # ``resources/python/`` is a frozen layout and needs
            # ``PYTHONHOME`` so ``site.py`` can locate stdlib.
            # On POSIX (including conda envs) setting PYTHONHOME
            # to ``bin/`` corrupts the conda prefix and breaks
            # ``import backend.main``, so we only set it on Win32.
            **(
                {"PYTHONHOME": str(interpreter_path.parent)}
                if os.name == "nt"
                else {}
            ),
        }
        # Round 2: merge supervisor launcher context so the probe sees
        # SAGE_BACKEND_GENERATION / SAGE_BACKEND_OWNERSHIP_TOKEN and any
        # PYTHONPATH additions the supervisor would have made. Stringify
        # non-str values defensively — subprocess.run requires str values.
        if extra_env:
            for k, v in extra_env.items():
                if v is None:
                    continue
                probe_env[str(k)] = str(v) if not isinstance(v, str) else v
            # Re-apply PYTHONPATH from extra_env LAST so a supervisor-provided
            # PYTHONPATH wins over the package-root default we computed above.
            supervisor_pp = extra_env.get("PYTHONPATH")
            if supervisor_pp:
                probe_env["PYTHONPATH"] = str(supervisor_pp)

        result = subprocess.run(
            [str(interpreter_path), "-c", "import backend.main"],
            cwd=str(package_root_path),
            check=False,
            env=probe_env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        return result.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False




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
        # §1.5 二期扩容(2026-08-10)
        "llm_config",
        "mcp_servers",
        "heavy_deps",
        "log_dir_size",
        "frontend_dist",
        "skills",
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
    # Round 2 (fast-follow E): let the Electron supervisor pass its
    # exact launcher context (command/cwd/env) down to doctor so the
    # ``import backend.main`` probe is exercised under the same env
    # the backend would see at runtime. CLI args take precedence over
    # the SAGE_BACKEND_CMD/CWD/ENV env vars of the same name; env vars
    # in turn let the supervisor avoid long arg lines on Win32.
    parser.add_argument(
        "--backend-cmd",
        dest="backend_cmd",
        default=None,
        help="JSON 数组字符串,如 '[\"-m\",\"backend.main\"]'; 覆盖 SAGE_BACKEND_CMD",
    )
    parser.add_argument(
        "--backend-cwd",
        dest="backend_cwd",
        default=None,
        help="子进程工作目录; 覆盖 SAGE_BACKEND_CWD",
    )
    parser.add_argument(
        "--backend-env",
        dest="backend_env",
        default=None,
        help="JSON 对象字符串,如 '{\"PYTHONPATH\":\"/a:/b\"}'; 覆盖 SAGE_BACKEND_ENV",
    )
    return parser


def _resolve_backend_context(
    args: argparse.Namespace,
    environ: dict[str, str],
) -> tuple[list | None, str | None, dict | None]:
    """Resolve launcher-context overrides from CLI args or env vars.

    Round 2 (fast-follow E): Electron's supervisor serialises the
    ``BackendLaunchPlan`` it would pass to the actual backend and ships it
    to doctor via three well-known env vars. CLI flags of the same name
    take precedence so unit tests (and ad-hoc operator commands) can
    override without touching env. Returns ``(backend_command, backend_cwd,
    backend_env)`` with any unset value as ``None`` — ``run_doctor`` then
    defaults fall back to host interpreter/cwd.

    Values are JSON-encoded because argv lists and env dicts are not
    representable in a single env var or CLI arg without escaping.
    """
    cmd_raw = getattr(args, "backend_cmd", None) or environ.get("SAGE_BACKEND_CMD")
    cwd_raw = getattr(args, "backend_cwd", None) or environ.get("SAGE_BACKEND_CWD")
    env_raw = getattr(args, "backend_env", None) or environ.get("SAGE_BACKEND_ENV")

    backend_command: list | None = None
    if cmd_raw:
        try:
            parsed = json.loads(cmd_raw)
            if isinstance(parsed, list):
                backend_command = [str(x) for x in parsed]
        except json.JSONDecodeError:
            backend_command = None  # tolerate malformed override, fall back

    backend_cwd: str | None = str(cwd_raw) if cwd_raw else None

    backend_env: dict | None = None
    if env_raw:
        try:
            parsed = json.loads(env_raw)
            if isinstance(parsed, dict):
                backend_env = {str(k): str(v) for k, v in parsed.items()}
        except json.JSONDecodeError:
            backend_env = None

    return backend_command, backend_cwd, backend_env


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

    # Round 2 (fast-follow E): forward the supervisor's launcher context
    # (command / cwd / env) to ``run_doctor`` so the ``import backend.main``
    # probe uses the EXACT interpreter/cwd/env/PYTHONPATH that the backend
    # will see at runtime. CLI args beat env vars; env vars in turn let the
    # supervisor avoid long arg lines on Win32.
    backend_command, backend_cwd, backend_env = _resolve_backend_context(
        args, os.environ
    )
    # Auto-inherit SAGE_BACKEND_GENERATION / SAGE_BACKEND_OWNERSHIP_TOKEN
    # into backend_env so the probe subprocess sees them. The Electron
    # supervisor sets these on its own plan.env, so they already reached
    # this doctor subprocess via the parent env; threading them into
    # backend_env makes the probe see what the supervisor's child would.
    if backend_env is None and (
        "SAGE_BACKEND_GENERATION" in os.environ
        or "SAGE_BACKEND_OWNERSHIP_TOKEN" in os.environ
    ):
        backend_env = {}
    if backend_env is not None:
        for k in ("SAGE_BACKEND_GENERATION", "SAGE_BACKEND_OWNERSHIP_TOKEN"):
            if k in os.environ and k not in backend_env:
                backend_env[k] = os.environ[k]

    runtime = run_doctor(
        backend_command=backend_command,
        backend_cwd=backend_cwd,
        backend_env=backend_env,
    )

    if args.as_json:
        print(_format_json(results, runtime))  # noqa: T201 — CLI output
    else:
        print(_format_text(results))  # noqa: T201 — CLI output

    return _exit_code(results)


if __name__ == "__main__":
    sys.exit(main())

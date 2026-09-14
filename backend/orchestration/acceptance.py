"""``acceptance`` — A4 自动验收：lane 成功后跑 checks 并落事件。

lane 进入 ``succeeded`` 后，executor best-effort 调用本模块：
- 恒跑 ``git diff --stat``（产物摘要；非 git 目录记 skip）；
- 按白名单探测表自动选命令（pytest / tsc）；
- lane ``metadata.acceptance_checks`` 显式配置优先（上限 5 条）；
- 结果记 ``lane.acceptance.completed`` 事件，供前端交付包读取。

设计铁律：
- 验收是建议性的：checks 失败绝不翻转 lane 结论，只记录。
- 永不抛错：单条 check 超时/异常记为 failed 条目；整轮异常由
  调用方吞掉（executor Step 6.5 包 ``contextlib.suppress``）。
- 不走 tool 审批栈：subprocess 直调（同 worktree.py 先例），避免
  自检触发审批递归；命令白名单 + 无 shell=True。
- 跨平台：Windows 下 .cmd/.bat 经 ``cmd /c`` 启动；py3.8 兼容写法。
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

from backend.orchestration.events import EventProvenance, LaneEvent

if TYPE_CHECKING:  # py3.8: 注解期导入，零运行时依赖，避免循环 import
    from backend.orchestration.events import EventRecorder
    from backend.orchestration.models import Lane

logger = logging.getLogger(__name__)

CHECK_TIMEOUT_S = 180
DIFF_TIMEOUT_S = 30
MAX_CONFIGURED_CHECKS = 5
OUTPUT_TAIL_CHARS = 4000
SUMMARY_CHARS = 800


@dataclass
class CheckResult:
    """单条 check 结果。"""

    name: str
    passed: bool
    summary: str = ""
    skipped: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "summary": self.summary,
            "skipped": self.skipped,
        }


@dataclass
class AcceptanceReport:
    """一轮验收汇总。全跳过视为通过（无失败项）。"""

    checks: List[CheckResult] = dc_field(default_factory=list)

    @property
    def all_passed(self) -> bool:
        return all(c.passed or c.skipped for c in self.checks)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "checks": [c.to_dict() for c in self.checks],
            "all_passed": self.all_passed,
        }


# ------------------------------------------------------------------
# 探测表（白名单）：目录特征 → 校验命令
# ------------------------------------------------------------------


def _has_pytest_config(d: Path) -> bool:
    if (d / "pytest.ini").exists():
        return True
    pp = d / "pyproject.toml"
    if not pp.is_file():
        return False
    try:
        head = pp.read_bytes()[:65536].decode("utf-8", errors="replace")
    except OSError:
        return False
    return "[tool.pytest" in head


def _has_ts_config(d: Path) -> bool:
    return (d / "package.json").is_file() and (d / "tsconfig.json").is_file()


_DETECTORS: List[Tuple[str, Callable[[Path], bool], List[str]]] = [
    ("pytest", _has_pytest_config, ["pytest", "-q"]),
    ("tsc", _has_ts_config, ["npx", "tsc", "--noEmit"]),
]


def detect_check_commands(workdir: Path) -> List[Tuple[str, List[str]]]:
    """按探测表返回命中命令；IO 异常按未命中处理。"""
    found: List[Tuple[str, List[str]]] = []
    for name, probe, argv in _DETECTORS:
        try:
            hit = probe(workdir)
        except OSError:
            hit = False
        if hit:
            found.append((name, list(argv)))
    return found


def normalize_configured_checks(raw: Any) -> List[List[str]]:
    """lane metadata.acceptance_checks → argv 列表（上限 5，非法项丢弃）。"""
    if not isinstance(raw, list):
        return []
    out: List[List[str]] = []
    for item in raw:
        if isinstance(item, list) and item and all(isinstance(p, str) for p in item):
            out.append(list(item))
        elif isinstance(item, str) and item.strip():
            try:
                parts = shlex.split(item.strip(), posix=(os.name != "nt"))
            except ValueError:
                continue
            if parts:
                out.append(parts)
        if len(out) >= MAX_CONFIGURED_CHECKS:
            break
    return out


# ------------------------------------------------------------------
# 执行
# ------------------------------------------------------------------


def _resolve_argv(argv: List[str]) -> Optional[List[str]]:
    """解析可执行文件；缺失返回 None（记 skip）；Windows 脚本经 cmd /c。"""
    target = shutil.which(argv[0])
    if target is None:
        return None
    if os.name == "nt" and Path(target).suffix.lower() not in (".exe", ".com"):
        # .cmd/.bat 不能被 CreateProcess 直调，交 cmd 解析（argv[0] 不改写，
        # 由 cmd 按 PATH 搜索，避免含空格路径的引号坑）。
        return ["cmd", "/c", argv[0]] + argv[1:]
    return list(argv)


def _brief(output: str, fallback: str) -> str:
    tail = output.strip()[-SUMMARY_CHARS:]
    return tail if tail else fallback


def _run_command_check(
    name: str, argv: List[str], cwd: Path, timeout_s: int
) -> CheckResult:
    resolved = _resolve_argv(argv)
    if resolved is None:
        return CheckResult(
            name=name, passed=True, skipped=True,
            summary=f"工具缺失，已跳过：{argv[0]}",
        )
    try:
        proc = subprocess.run(
            resolved,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout_s,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            name=name, passed=False, summary=f"超时（>{timeout_s}s），已熔断"
        )
    except OSError as exc:
        return CheckResult(name=name, passed=False, summary=f"启动失败：{exc}")
    tail = ((proc.stdout or "") + (proc.stderr or ""))[-OUTPUT_TAIL_CHARS:]
    if proc.returncode == 0:
        return CheckResult(name=name, passed=True, summary=_brief(tail, "通过（rc=0）"))
    return CheckResult(
        name=name, passed=False, summary=_brief(tail, f"失败（rc={proc.returncode}）")
    )


def _run_diff_stat(cwd: Path) -> CheckResult:
    """产物摘要：git diff --stat + 未跟踪文件计数；非 git 目录记 skip。"""
    if shutil.which("git") is None:
        return CheckResult(
            name="diff", passed=True, skipped=True, summary="git 不可用，跳过"
        )
    try:
        proc = subprocess.run(
            ["git", "diff", "--stat"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=DIFF_TIMEOUT_S,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CheckResult(name="diff", passed=False, summary="git diff 超时，已熔断")
    except OSError as exc:
        return CheckResult(name="diff", passed=False, summary=f"git 启动失败：{exc}")
    if proc.returncode != 0:
        return CheckResult(
            name="diff", passed=True, skipped=True, summary="非 git 目录，跳过"
        )
    untracked = 0
    try:
        st = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=DIFF_TIMEOUT_S,
            check=False,
        )
        if st.returncode == 0:
            untracked = sum(1 for ln in st.stdout.splitlines() if ln.startswith("??"))
    except (subprocess.TimeoutExpired, OSError):
        pass  # 计数失败不影响主结论
    stat = (proc.stdout or "").strip()
    if not stat and untracked == 0:
        return CheckResult(name="diff", passed=True, summary="无文件变更")
    lines = []
    if stat:
        lines.append(stat[-SUMMARY_CHARS:])
    if untracked:
        lines.append(f"未跟踪文件：{untracked} 个")
    return CheckResult(name="diff", passed=True, summary="\n".join(lines))


def run_acceptance_checks(
    workdir: Optional[str],
    configured: Any = None,
    *,
    check_timeout_s: int = CHECK_TIMEOUT_S,
) -> AcceptanceReport:
    """跑一轮验收，永不抛错（调用方仍建议包 suppress，双保险）。"""
    report = AcceptanceReport()
    try:
        return _run_acceptance_checks_inner(workdir, configured, check_timeout_s)
    except Exception as exc:  # noqa: BLE001 — 验收绝不能炸主流程
        logger.warning("acceptance 整轮异常，转失败条目: %s", exc)
        report.checks.append(
            CheckResult(name="acceptance-runner", passed=False, summary=f"验收器异常：{exc}")
        )
        return report


def _run_acceptance_checks_inner(
    workdir: Optional[str], configured: Any, check_timeout_s: int
) -> AcceptanceReport:
    report = AcceptanceReport()
    if not workdir:
        report.checks.append(
            CheckResult(
                name="worktree", passed=True, skipped=True,
                summary="无隔离 worktree，检查跳过",
            )
        )
        return report
    cwd = Path(workdir)
    if not cwd.is_dir():
        report.checks.append(
            CheckResult(
                name="worktree", passed=True, skipped=True,
                summary=f"worktree 不存在，检查跳过：{workdir}",
            )
        )
        return report
    report.checks.append(_run_diff_stat(cwd))
    selected = normalize_configured_checks(configured)
    if selected:
        for i, argv in enumerate(selected):
            name = Path(argv[0]).name or f"check-{i + 1}"
            report.checks.append(_run_command_check(name, argv, cwd, check_timeout_s))
    else:
        for name, argv in detect_check_commands(cwd):
            report.checks.append(_run_command_check(name, argv, cwd, check_timeout_s))
    return report


def record_acceptance_event(
    event_recorder: EventRecorder, lane: Lane, report: AcceptanceReport
) -> Optional[str]:
    """落 lane.acceptance.completed 事件；失败返 None，永不抛错。"""
    try:
        return event_recorder.record(
            LaneEvent.ACCEPTANCE_COMPLETED,
            lane_id=lane.lane_id,
            task_id=lane.task_id,
            agent_id=lane.agent_id,
            provenance=EventProvenance.LIVE_LANE,
            metadata={
                "checks": [c.to_dict() for c in report.checks],
                "all_passed": report.all_passed,
            },
        )
    except Exception:  # noqa: BLE001 — 事件落库失败不得破坏主流程
        logger.warning("acceptance 事件落库失败 lane=%s", lane.lane_id, exc_info=True)
        return None

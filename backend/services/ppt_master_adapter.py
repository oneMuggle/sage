"""PptMasterAdapter — 原位调用官方 ppt-master 技能脚本的确定性工程层。

只负责 ppt-master 的"工程转换"部分，不含 AI 创作：

    svg_output/*.svg
        -> svg_quality_checker.py（质量门禁，写 validation/svg_quality_report.json）
        -> svg_to_pptx.py --quick-generate（SVG -> 原生可编辑 DrawingML PPTX）

为什么"原位调用"而不是把脚本拷进仓：

    scripts/attribution_guard.py 会相对技能根目录校验 SKILL.md 元数据、
    LICENSE 的 sha256、SPONSORS 文件与各闸门脚本；把脚本拷到别处会让
    守卫失败（exit != 0），脚本拒绝运行。因此本适配器必须指向一份完整的
    官方技能目录（含 scripts/ 与 SKILL.md），通过 subprocess 调用，禁止拷贝。

安全约束：
    - 无 shell，参数以 list 传入，杜绝命令注入；
    - 每次调用带超时；
    - 文本统一以 UTF-8 解码、errors="replace"，避免 Windows 控制台编码炸。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
<<<<<<< HEAD
from typing import List, Optional, Sequence
=======
from typing import Optional, Sequence
>>>>>>> origin/main

__all__ = [
    "PptMasterAdapter",
    "PptMasterEnvError",
    "PptMasterRunError",
    "QualityOutcome",
    "ConversionOutcome",
]

_DEFAULT_TIMEOUT_S = 180.0
_GUARD_MARKER = "attribution_guard.py"
<<<<<<< HEAD
# 技能脚本内部使用 PEP 604（`str | int`）等 3.9+ 语法，3.8 解释器会直接 TypeError。
_MIN_PYTHON = (3, 9)
=======
>>>>>>> origin/main


class PptMasterEnvError(RuntimeError):
    """ppt-master 运行环境不可用（技能目录缺失 / 完整性校验失败 / 解释器缺失）。"""


class PptMasterRunError(RuntimeError):
    """脚本实际运行但失败（非零退出或报告不可解析）。"""


@dataclass
class QualityOutcome:
    """一次质量检查的结果。"""

    passed: bool
    blocking_errors: list
    warnings: list
    summary: dict
    report_path: Optional[Path]
    raw: dict = field(default_factory=dict)


@dataclass
class ConversionOutcome:
    """一次 SVG->PPTX 转换的结果。"""

    output_path: Path
    postflight_report_path: Optional[Path]
    stdout: str


def _resolve_skill_root(explicit: Optional[Path]) -> Path:
    """定位 skills/ppt-master 目录（含 scripts/attribution_guard.py）。

    优先级：显式参数 > 环境变量 SAGE_PPT_MASTER_ROOT > 常见默认位置。
    环境变量/默认位置允许指向技能目录本身，或其上层仓库根（自动加
    skills/ppt-master）。
    """
<<<<<<< HEAD
    candidates: List[Path] = []
=======
    candidates: list[Path] = []
>>>>>>> origin/main
    if explicit is not None:
        candidates.append(Path(explicit))

    env_root = os.environ.get("SAGE_PPT_MASTER_ROOT")
    if env_root:
        candidates.append(Path(env_root))

    candidates.extend(
        [
            Path.home() / "project" / "ppt-master" / "skills" / "ppt-master",
            Path("/opt/agent-skills/ppt-master"),
        ]
    )

    for candidate in candidates:
        for base in (candidate, candidate / "skills" / "ppt-master"):
            guard = base / "scripts" / _GUARD_MARKER
            if guard.is_file():
                return base.resolve()

    raise PptMasterEnvError(
        "未找到 ppt-master 技能目录（需含 scripts/attribution_guard.py）。"
        "请设置环境变量 SAGE_PPT_MASTER_ROOT 指向技能目录或其仓库根。"
    )


class PptMasterAdapter:
    """封装对官方 ppt-master 技能脚本的子进程调用。"""

    def __init__(
        self,
        skill_root: Optional[Path] = None,
        python_executable: Optional[str] = None,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        self.skill_root = _resolve_skill_root(skill_root)
        self.python_executable = (
            python_executable or os.environ.get("SAGE_PPT_MASTER_PYTHON") or sys.executable
        )
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------ #
    # 环境 / 完整性
    # ------------------------------------------------------------------ #
    def check_environment(self) -> dict:
        """校验技能完整性（attribution_guard）与脚本存在性。

        返回描述性 dict；任何问题抛 PptMasterEnvError。
        """
        guard = self.skill_root / "scripts" / _GUARD_MARKER
        converter = self.skill_root / "scripts" / "svg_to_pptx.py"
        checker = self.skill_root / "scripts" / "svg_quality_checker.py"
        for required in (guard, converter, checker):
            if not required.is_file():
                raise PptMasterEnvError(f"技能目录缺少必需脚本：{required}")

        result = self._run([self.python_executable, str(guard)])
        if result.returncode != 0:
            raise PptMasterEnvError(
                "ppt-master 完整性校验失败（attribution_guard 非零退出）："
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
<<<<<<< HEAD
        version = self._interpreter_version()
        if version < _MIN_PYTHON:
            raise PptMasterEnvError(
                "ppt-master 技能脚本需要 Python >= "
                f"{_MIN_PYTHON[0]}.{_MIN_PYTHON[1]}，当前解释器 "
                f"{self.python_executable} 为 {version[0]}.{version[1]}。"
                "请设置 SAGE_PPT_MASTER_PYTHON 指向兼容版本的解释器。"
            )
        return {
            "skill_root": str(self.skill_root),
            "python": self.python_executable,
            "python_version": f"{version[0]}.{version[1]}",
        }

    def _interpreter_version(self) -> tuple:
        """探测目标解释器版本；无法解析时报环境错误。"""
        result = self._run(
            [
                self.python_executable,
                "-c",
                "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
            ]
        )
        text = (result.stdout or "").strip()
        if result.returncode != 0:
            raise PptMasterEnvError(
                f"无法运行 ppt-master 解释器 {self.python_executable}："
                f"{result.stderr.strip() or text}"
            )
        try:
            major, minor = text.split(".", 1)
            return int(major), int(minor)
        except ValueError as exc:
            raise PptMasterEnvError(
                f"无法解析解释器版本输出：{text!r}"
            ) from exc

=======
        return {
            "skill_root": str(self.skill_root),
            "python": self.python_executable,
        }

>>>>>>> origin/main
    # ------------------------------------------------------------------ #
    # 质量门禁
    # ------------------------------------------------------------------ #
    def quality_check(self, project_dir: Path) -> QualityOutcome:
        """对 quick 导出运行最终质量门禁，写入并解析 validation 报告。

        quick 导出路径无需 spec_lock.md；报告固定落在
        ``<project>/validation/svg_quality_report.json``（convert 步骤会读取它）。
        """
        project_dir = Path(project_dir)
        checker = self.skill_root / "scripts" / "svg_quality_checker.py"
        result = self._run(
            [
                self.python_executable,
                str(checker),
                str(project_dir),
                "--quick-generate",
                "--canonical-authoring",
                "--stage",
                "final",
                "--json",
            ]
        )
        report_path = project_dir / "validation" / "svg_quality_report.json"
        report = _load_json(report_path)
        if report is None:
            raise PptMasterRunError(
                "质量检查未产出可解析的 JSON 报告。"
                f"退出码={result.returncode} stderr={result.stderr.strip()}"
            )
        return _interpret_quality(report, report_path)

    # ------------------------------------------------------------------ #
    # 转换
    # ------------------------------------------------------------------ #
    def convert_to_pptx(self, project_dir: Path, output_path: Path) -> ConversionOutcome:
        """把 project/svg_output/*.svg 转成原生可编辑 PPTX。

        前置条件：质量门禁已通过且报告写在默认路径（convert 会校验它）。
        """
        project_dir = Path(project_dir)
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        converter = self.skill_root / "scripts" / "svg_to_pptx.py"
        result = self._run(
            [
                self.python_executable,
                str(converter),
                str(project_dir),
                "--quick-generate",
                "-o",
                str(output_path),
            ]
        )
        if result.returncode != 0 or not output_path.is_file():
            raise PptMasterRunError(
                "SVG->PPTX 转换失败。"
                f"退出码={result.returncode} "
                f"stdout={result.stdout.strip()} stderr={result.stderr.strip()}"
            )
        postflight = project_dir / "validation" / f"{output_path.stem}.report.json"
        return ConversionOutcome(
            output_path=output_path,
            postflight_report_path=postflight if postflight.is_file() else None,
            stdout=result.stdout,
        )

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _run(self, argv: Sequence[str]) -> subprocess.CompletedProcess:
        try:
            return subprocess.run(
                list(argv),
                cwd=str(self.skill_root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_s,
                check=False,
            )
        except FileNotFoundError as exc:
            raise PptMasterEnvError(f"解释器不可用：{argv[0]}（{exc}）") from exc
        except subprocess.TimeoutExpired as exc:
            raise PptMasterRunError(
                f"ppt-master 调用超时（>{self.timeout_s}s）：{argv[1]}"
            ) from exc


def _load_json(path: Path) -> Optional[dict]:
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _interpret_quality(report: dict, report_path: Path) -> QualityOutcome:
    """把质量报告归一为 passed / blocking / warnings。

    pass/fail 以 ``categories.blocking.count`` 为准（非阻塞 warning 不影响通过），
    回退到 ``summary.errors``。
    """
    categories = report.get("categories") if isinstance(report.get("categories"), dict) else {}
    blocking = categories.get("blocking") if isinstance(categories.get("blocking"), dict) else {}
    blocking_issues = list(blocking.get("issues") or [])
    summary = report.get("summary") if isinstance(report.get("summary"), dict) else {}

    blocking_count = blocking.get("count")
    if not isinstance(blocking_count, int):
        blocking_count = summary.get("errors", 0) if isinstance(summary.get("errors"), int) else 0

    introduced = (
        categories.get("introduced") if isinstance(categories.get("introduced"), dict) else {}
    )
    inherited = categories.get("inherited") if isinstance(categories.get("inherited"), dict) else {}
    warnings = list(introduced.get("issues") or []) + list(inherited.get("issues") or [])

    return QualityOutcome(
        passed=blocking_count == 0,
        blocking_errors=blocking_issues,
        warnings=warnings,
        summary=summary,
        report_path=report_path,
        raw=report,
    )

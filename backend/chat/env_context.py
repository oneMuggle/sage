# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""环境上下文 / 技能清单注入（对标增强第二轮批次 B L5）。

主流编码代理（Claude Code `<env>` 块、Qoder Context Engine）都会在 system
prompt 里告知模型其所处环境：平台、日期、工作区、git 状态、可用技能清单。
此前 Sage 的 `build_system_base()` 只有身份句 + 工具能力声明，模型对工作区
状态零感知，已注册技能只能靠 LLM 盲调 skill 工具发现。

本模块全部 fail-safe：任何一段信息收集失败都静默省略，绝不抛错阻断聊天。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from backend.tools.git_tool import _run_git

logger = logging.getLogger(__name__)

#: 环境块注入的 git 变更条目上限（防止超大工作区刷屏）
_GIT_STATUS_MAX_ENTRIES = 30

#: 技能清单注入上限（条数 / 字符数双重预算）
_SKILLS_MAX_COUNT = 20
_SKILLS_MAX_CHARS = 2000

_PLATFORM_LABELS = {
    "win32": "Windows",
    "darwin": "macOS",
    "linux": "Linux",
}

_WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")


def build_environment_block(workspace_path: Optional[str] = None) -> str:
    """构造 `<environment>` 块：平台 / 日期 / 工作区 / git 摘要。

    git 部分仅在 ``workspace_path`` 非空且确为 git 仓库时注入，任何失败
    （git 不在 PATH / 超时 / 非仓库）静默省略该行。
    """
    lines: List[str] = []

    platform_label = _PLATFORM_LABELS.get(sys.platform, sys.platform)
    now = datetime.now()
    date_label = "{} {} {:02d}:{:02d}".format(
        now.strftime("%Y-%m-%d"),
        _WEEKDAY_LABELS[now.weekday()],
        now.hour,
        now.minute,
    )
    lines.append(f"- 平台: {platform_label} (Python {sys.version.split()[0]})")
    lines.append(f"- 日期: {date_label} 本地时间")
    lines.append(f"- 工作区: {workspace_path or Path.cwd()}")

    git_summary = _git_summary(workspace_path)
    if git_summary:
        lines.append(f"- Git: {git_summary}")

    return "<environment>\n{}\n</environment>".format("\n".join(lines))


def build_skills_block() -> str:
    """构造可用技能清单块（名称 + 一行描述，双预算截断）。

    技能注册表不可用时返回空串（不注入块）。
    """
    try:
        from backend.adapters.out.skill.inproc import get_singleton

        specs = get_singleton().list_skills()
    except Exception as exc:  # noqa: BLE001 — 技能清单失败绝不影响聊天
        logger.debug("技能清单注入跳过: %s", exc)
        return ""

    if not specs:
        return ""

    lines: List[str] = []
    used = 0
    for spec in specs[:_SKILLS_MAX_COUNT]:
        description = (getattr(spec, "description", "") or "").strip().splitlines()
        first_line = description[0].strip() if description else ""
        line = "- /{}{}".format(spec.name, (f"：{first_line}") if first_line else "")
        if used + len(line) > _SKILLS_MAX_CHARS:
            lines.append("- …（其余技能已省略）")
            break
        lines.append(line)
        used += len(line)

    return (
        "<available-skills>\n"
        "以下技能已注册，可通过 skill 工具按名称调用（斜杠命令同样可用）：\n"
        "{}\n"
        "</available-skills>"
    ).format("\n".join(lines))


def _git_summary(workspace_path: Optional[str]) -> str:
    """git 分支 + 未提交变更数摘要；任何失败返回空串。"""
    if not workspace_path:
        return ""

    branch_out, error = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], workspace_path)
    if error is not None:
        return ""
    branch = (branch_out or "").strip()
    if not branch:
        return ""

    status_out, error = _run_git(["status", "--porcelain=v1"], workspace_path)
    if error is not None:
        return f"分支 {branch}"

    entries = [ln for ln in (status_out or "").splitlines() if ln.strip()]
    count = len(entries)
    if count == 0:
        return f"分支 {branch}（工作区干净）"

    preview = "、".join(
        entry[3:].strip() for entry in entries[:_GIT_STATUS_MAX_ENTRIES]
    )
    more = "" if count <= _GIT_STATUS_MAX_ENTRIES else f" 等 {count} 个"
    return f"分支 {branch}（{count} 个未提交变更{more}: {preview}）"


__all__ = ["build_environment_block", "build_skills_block"]

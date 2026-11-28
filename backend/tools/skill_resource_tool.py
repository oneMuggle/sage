"""skill_read_resource 工具 —— 读取技能内白名单资源（spec §4.2）。

只读能力（READ）：按「技能名 + 技能内相对路径」读取 ``references/`` /
``assets/`` / ``templates/`` / ``scripts/`` 下的已索引文件。

设计要点
--------
- **渐进披露**：不把资源内容预先灌进 system prompt，模型按需读取。
- **与技能加载同源**：技能目录解析顺序复用
  ``loader.discover_skill_md_dirs()`` + ``loader._discover_shipped_dir()``，
  避免「读到的和生效的不是同一份」。
- **不执行任何代码**：``.py`` 脚本只作为文本返回；脚本执行仍走
  ``ScriptRunner`` 的既有审批通道（spec §4.5）。
- **路径安全**：复用 ``resources.resolve_indexed_resource``，与渲染路径
  同口径的白名单 + 越界 + reparse-point 防护。
"""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path
from typing import Any, Dict, List, Optional

from backend.domain.risk import RiskClass
from backend.domain.tool_policy import ToolPolicy
from backend.skills.skill_md.loader import (
    _discover_shipped_dir,
    discover_skill_md_dirs,
)
from backend.skills.skill_md.resources import (
    build_resource_index,
    resolve_indexed_resource,
)

from .base import BaseTool, ToolResult, ToolSchema

logger = logging.getLogger(__name__)

SKILL_READ_RESOURCE_TOOL_NAME = "skill_read_resource"

#: 单次读取的最大行数（防止把大文件整篇灌进上下文）。
MAX_LINES = 2000
#: 默认读取行数。
DEFAULT_LINES = 300


def resolve_skill_dir(skill_name: str) -> Optional[Path]:
    """解析技能目录；解析顺序与技能实际加载顺序一致。

    顺序：``$SAGE_SKILLS_DIR`` > preference ``skills_dir`` > ``$CWD/skills``
    > ``~/.sage/skills`` > shipped。
    """
    name = str(skill_name or "").strip()
    if not name or "/" in name or "\\" in name or name.startswith("."):
        return None

    candidates: List[Path] = []
    for root in discover_skill_md_dirs():
        candidates.append(root / name)
    shipped = _discover_shipped_dir()
    if shipped is not None:
        candidates.append(shipped / name)

    for candidate in candidates:
        try:
            if candidate.is_dir() and (candidate / "SKILL.md").is_file():
                return candidate.resolve()
        except OSError:
            continue
    return None


def _read_text(path: Path) -> Optional[str]:
    """按 no-follow 方式读普通文件内容；不安全或失败返回 ``None``。"""
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path), flags)
    except OSError:
        return None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            return None
        with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except (OSError, UnicodeError):
        return None


class SkillReadResourceTool(BaseTool):
    """读取技能内白名单资源。"""

    risk = RiskClass.READ

    def __init__(self, policy: Optional[ToolPolicy] = None) -> None:
        super().__init__(policy)

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name=SKILL_READ_RESOURCE_TOOL_NAME,
            description=(
                "读取技能内的白名单资源（如 references/pipeline.md 的流程契约）。"
                "参数 skill=技能目录名，path=技能内相对路径。"
                "只读，不执行代码。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "skill": {
                        "type": "string",
                        "description": "技能名（目录名），如 literature-research",
                    },
                    "path": {
                        "type": "string",
                        "description": "技能内相对路径，如 references/pipeline.md",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "起始行（1 起），默认 1",
                    },
                    "limit": {
                        "type": "integer",
                        "description": (
                            f"读取行数，默认 {DEFAULT_LINES}，上限 {MAX_LINES}"
                        ),
                    },
                },
                "required": ["skill", "path"],
            },
        )

    def execute(
        self,
        skill: str = "",
        path: str = "",
        offset: int = 1,
        limit: int = DEFAULT_LINES,
        **kwargs: Any,
    ) -> ToolResult:
        """按技能名与相对路径读取资源。"""
        base_dir = resolve_skill_dir(skill)
        if base_dir is None:
            return ToolResult(
                success=False,
                error=f"skill_not_found: 找不到技能 {skill!r}",
            )

        index = build_resource_index(base_dir)
        resolved = resolve_indexed_resource(index, base_dir, path)
        if resolved is None:
            return ToolResult(
                success=False,
                error=f"invalid_resource_path: {path!r} 不是技能 {skill!r} 的可读资源",
            )

        text = _read_text(resolved)
        if text is None:
            return ToolResult(
                success=False,
                error=f"resource_read_failed: 无法读取 {path!r}",
            )

        lines = text.splitlines()
        total = len(lines)
        try:
            start = max(1, int(offset))
        except (TypeError, ValueError):
            start = 1
        try:
            count = int(limit)
        except (TypeError, ValueError):
            count = DEFAULT_LINES
        count = max(1, min(count, MAX_LINES))

        selected = lines[start - 1 : start - 1 + count]
        payload: Dict[str, Any] = {
            "path": path,
            "content": "\n".join(selected),
            "offset": start,
            "limit": count,
            "total_lines": total,
            "truncated": (start - 1 + len(selected)) < total,
        }
        return ToolResult(success=True, content=payload)

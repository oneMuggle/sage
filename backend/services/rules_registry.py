# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""四层规则聚合（M3，2026-11-07）。

存储层不变：项目约束在 ``project_constraints`` 表、规程规则在活动快照的
``spec_json``、项目总纲与全局规则是 Markdown 文件。本模块用适配器把四种
来源投影成统一的 :class:`RuleEntry`。只读聚合；写入由 ``rules_routes`` 分派。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_repo import Project

logger = logging.getLogger(__name__)

# 注入顺序：全局 → 项目总纲 → 项目规则 → 当前阶段规程/内容检查（spec §3.2.3）
LAYER_ORDER: Tuple[str, ...] = ("global", "doc", "constraint", "playbook")

PLAYBOOK_SOURCE_PREFIX = "playbook:"

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$")


@dataclass
class RuleEntry:
    """四层规则统一投影。id 每次拉取重新计算，除 constraint 外不持久化。"""

    id: str
    layer: str
    source_label: str
    scope: str
    category: str
    content: str
    enabled: bool = True
    editable: str = "full"  # full | partial | readonly
    priority: int = 5
    trigger: Optional[str] = None
    updated_at: Optional[int] = None
    origin: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "layer": self.layer,
            "source_label": self.source_label,
            "scope": self.scope,
            "category": self.category,
            "content": self.content,
            "enabled": self.enabled,
            "editable": self.editable,
            "priority": self.priority,
            "trigger": self.trigger,
            "updated_at": self.updated_at,
            "origin": self.origin,
        }


@dataclass
class MarkdownSection:
    heading: str
    level: int
    body: str  # 含标题行，按原文件切片
    start: int  # 在文件中的字符偏移（M4 小节替换用）


def split_markdown_sections(content: str) -> List[MarkdownSection]:
    """按 Markdown 标题切小节；首个无标题的前言也作为一个条目（heading=""）。"""
    sections: List[MarkdownSection] = []
    heading = ""
    level = 0
    buf: List[str] = []
    offset = 0
    start = 0
    for line in content.splitlines(keepends=True):
        match = _HEADING_RE.match(line.rstrip("\n"))
        if match:
            if "".join(buf).strip():
                sections.append(MarkdownSection(heading, level, "".join(buf), start))
            heading = match.group(2)
            level = len(match.group(1))
            buf = []
            start = offset
        buf.append(line)
        offset += len(line)
    if "".join(buf).strip():
        sections.append(MarkdownSection(heading, level, "".join(buf), start))
    return sections


def _normalize_content(value: str) -> str:
    return " ".join(value.split()).casefold()


def _triggers_overlap(left: Optional[str], right: Optional[str]) -> bool:
    """空触发词 = 无条件生效，与任何规则重叠；否则按包含关系判定。"""
    if not left or not right:
        return True
    return left in right or right in left


def detect_conflicts(entries: List[RuleEntry]) -> List[Dict[str, Any]]:
    """同 category + 触发词重叠 + 内容不同 → 提示冲突，不自动合并。"""
    active = [entry for entry in entries if entry.enabled]
    conflicts: List[Dict[str, Any]] = []
    for index, left in enumerate(active):
        for right in active[index + 1:]:
            if left.category != right.category:
                continue
            if not _triggers_overlap(left.trigger, right.trigger):
                continue
            if _normalize_content(left.content) == _normalize_content(right.content):
                continue
            conflicts.append(
                {
                    "a": left.id,
                    "b": right.id,
                    "category": left.category,
                    "triggers": [left.trigger, right.trigger],
                }
            )
    return conflicts


class ConstraintAdapter:
    """``project_constraints`` → RuleEntry；规程投影行只读。"""

    layer = "constraint"

    def __init__(self, repo_factory=ProjectConstraintRepository) -> None:
        self._repo_factory = repo_factory

    def read(self, project: Project) -> List[RuleEntry]:
        entries: List[RuleEntry] = []
        for constraint in self._repo_factory().list_by_project(project.id):
            source = constraint.source or "user"
            projected = source.startswith(PLAYBOOK_SOURCE_PREFIX)
            stage = source.split(":", 1)[1] if projected else ""
            entries.append(
                RuleEntry(
                    id=f"constraint:{constraint.id}",
                    layer=self.layer,
                    source_label=f"规程 · {stage}" if projected else "项目规则",
                    scope=stage or "全局",
                    category=constraint.category,
                    content=constraint.content,
                    enabled=bool(constraint.enabled),
                    editable="readonly" if projected else "full",
                    priority=constraint.priority,
                    trigger=constraint.trigger_pattern,
                    updated_at=constraint.updated_at or None,
                    origin=source if projected else None,
                )
            )
        return entries


class RulesRegistry:
    """聚合所有适配器；单个适配器失败只记日志，不影响其余层。"""

    def __init__(self, adapters: Optional[Sequence[Any]] = None) -> None:
        self._adapters: List[Any] = (
            list(adapters) if adapters is not None else [ConstraintAdapter()]
        )

    def list_rules(self, project: Project) -> List[RuleEntry]:
        entries: List[RuleEntry] = []
        for adapter in self._adapters:
            try:
                entries.extend(adapter.read(project))
            except Exception:  # noqa: BLE001 — 单层失败不阻断其余层
                logger.warning(
                    "rules adapter %s failed", type(adapter).__name__, exc_info=True
                )
        return sorted(entries, key=lambda entry: LAYER_ORDER.index(entry.layer))

    def effective(self, project: Project) -> Dict[str, Any]:
        entries = self.list_rules(project)
        active = [entry for entry in entries if entry.enabled]
        return {
            "entries": [entry.to_dict() for entry in active],
            "conflicts": detect_conflicts(active),
        }

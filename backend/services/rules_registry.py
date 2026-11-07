# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""四层规则聚合（M3，2026-11-07）。

存储层不变：项目约束在 ``project_constraints`` 表、规程规则在活动快照的
``spec_json``、项目总纲与全局规则是 Markdown 文件。本模块用适配器把四种
来源投影成统一的 :class:`RuleEntry`。只读聚合；写入由 ``rules_routes`` 分派。
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from backend.data.playbook_repo import PlaybookRepository
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


_DOC_FILENAMES: Tuple[str, ...] = ("SAGE.md", "CLAUDE.md", "AGENTS.md")
# 单文件保护上限：超过 1 MiB 的指令文件不解析（规则中心只做管理，不成正文编辑器）
_DOC_MAX_BYTES = 1024 * 1024


def _global_rules_path() -> Path:
    """与 ``backend/api/global_rules_routes._global_rules_path`` 同一路径。"""
    return Path.home() / ".sage" / "SAGE.md"


def _rule_text(rule: Any) -> str:
    """规程 spec 里的规则可能是裸字符串或 dict（键名随作者版本不同）。"""
    if isinstance(rule, str):
        return rule.strip()
    if isinstance(rule, dict):
        for key in ("text", "content", "rule", "label"):
            value = rule.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _markdown_entries(
    content: str,
    *,
    id_prefix: str,
    layer: str,
    source_label: str,
    scope: str,
    editable: str,
    origin: Optional[str],
) -> List[RuleEntry]:
    entries: List[RuleEntry] = []
    for index, section in enumerate(split_markdown_sections(content)):
        entries.append(
            RuleEntry(
                id=f"{id_prefix}#{index}",
                layer=layer,
                source_label=source_label,
                scope=scope,
                category=section.heading or "（开头）",
                content=section.body.strip(),
                editable=editable,
                origin=origin,
            )
        )
    return entries


def _safe_read(path: Path) -> Optional[str]:
    """拒绝符号链接越界（与 ``project_context._read_candidate_text`` 同语义）。"""
    try:
        if not path.is_file():
            return None
        resolved = Path(os.path.realpath(str(path)))
        if resolved.parent != Path(os.path.realpath(str(path.parent))):
            logger.warning("rules: skip symlink escape %s", path)
            return None
        if resolved.stat().st_size > _DOC_MAX_BYTES:
            logger.warning("rules: skip oversized doc %s", path)
            return None
        return resolved.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        logger.warning("rules: unreadable doc %s", path, exc_info=True)
        return None


def _playbook_check_entries(
    stage_id: str,
    stage_label: str,
    artifacts: Any,
    *,
    layer: str,
) -> List[RuleEntry]:
    """artifact 的 ``content_checks`` → RuleEntry（规程适配器的内层循环）。"""
    entries: List[RuleEntry] = []
    for artifact in artifacts or []:
        artifact_id = str(artifact.get("id") or "")
        for check in artifact.get("content_checks") or []:
            label = str(check.get("label") or check.get("id") or "内容检查")
            keywords = [str(item) for item in (check.get("keywords") or [])]
            content = label
            if keywords:
                content = f"{label}（关键词：{'、'.join(keywords)}）"
            entries.append(
                RuleEntry(
                    id=f"playbook:{stage_id}:check:{artifact_id}:{check.get('id')}",
                    layer=layer,
                    source_label=f"规程 · {stage_label} · 内容检查",
                    scope=stage_label,
                    category="content_check",
                    content=content,
                    editable="partial",
                    origin=stage_id,
                )
            )
    return entries


class PlaybookAdapter:
    """活动规程快照 → RuleEntry（阶段规则 + artifact 内容检查）。"""

    layer = "playbook"

    def read(self, project: Project) -> List[RuleEntry]:
        snapshot = PlaybookRepository().get_active(project.id)
        if snapshot is None:
            return []
        spec = snapshot.spec or {}
        entries: List[RuleEntry] = []
        for stage in spec.get("stages") or []:
            stage_id = str(stage.get("id") or "")
            stage_label = str(stage.get("label") or stage_id)
            for index, rule in enumerate(stage.get("rules") or []):
                content = _rule_text(rule)
                if not content:
                    continue
                entries.append(
                    RuleEntry(
                        id=f"playbook:{stage_id}:{index}",
                        layer=self.layer,
                        source_label=f"规程 · {stage_label}",
                        scope=stage_label,
                        category=str(rule.get("category") or "rule")
                        if isinstance(rule, dict)
                        else "rule",
                        content=content,
                        enabled=rule.get("enabled", True) is not False
                        if isinstance(rule, dict)
                        else True,
                        editable="partial",
                        priority=int(rule.get("priority") or 5)
                        if isinstance(rule, dict)
                        else 5,
                        trigger=(rule.get("trigger") or rule.get("trigger_pattern"))
                        if isinstance(rule, dict)
                        else None,
                        origin=stage_id,
                    )
                )
            entries.extend(
                _playbook_check_entries(
                    stage_id, stage_label, stage.get("artifacts"), layer=self.layer
                )
            )
        return entries


class GlobalRulesAdapter:
    """``~/.sage/SAGE.md`` 按 Markdown 小节拆条目，整文件可写。"""

    layer = "global"

    def read(self, project: Project) -> List[RuleEntry]:
        path = _global_rules_path()
        if path.is_symlink():
            logger.warning("rules: skip symlinked global rules %s", path)
            return []
        content = _safe_read(path)
        if content is None:
            return []
        return _markdown_entries(
            content,
            id_prefix="global:",
            layer=self.layer,
            source_label="全局规则",
            scope="全局",
            editable="full",
            origin=str(path),
        )


class ProjectDocAdapter:
    """项目根与祖先目录的 SAGE.md / CLAUDE.md / AGENTS.md，按小节拆条目。

    发现顺序与 ``backend/chat/project_context.py`` 一致：祖先在前、每级
    SAGE → CLAUDE → AGENTS。**只有项目根目录的 SAGE.md 可写**（spec §3.2.2）。
    """

    layer = "doc"

    def read(self, project: Project) -> List[RuleEntry]:
        root = Path(os.path.realpath(project.path))
        if not root.is_dir():
            return []
        chain: List[Path] = []
        cursor: Optional[Path] = root
        while cursor is not None:
            chain.append(cursor)
            parent = cursor.parent
            cursor = parent if parent != cursor else None
        entries: List[RuleEntry] = []
        for directory in reversed(chain):
            for filename in _DOC_FILENAMES:
                path = directory / filename
                content = _safe_read(path)
                if content is None:
                    continue
                writable = directory == root and filename == "SAGE.md"
                entries.extend(
                    _markdown_entries(
                        content,
                        id_prefix=f"doc:{filename}",
                        layer=self.layer,
                        source_label=f"项目总纲 {filename}",
                        scope=str(path),
                        editable="full" if writable else "readonly",
                        origin=str(path),
                    )
                )
        return entries


class RulesRegistry:
    """聚合所有适配器；单个适配器失败只记日志，不影响其余层。"""

    def __init__(self, adapters: Optional[Sequence[Any]] = None) -> None:
        self._adapters: List[Any] = (
            list(adapters)
            if adapters is not None
            else [
                GlobalRulesAdapter(),
                ProjectDocAdapter(),
                ConstraintAdapter(),
                PlaybookAdapter(),
            ]
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

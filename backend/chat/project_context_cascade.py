"""项目上下文级联继承 (P4, 2026-11-05 项目管理增强, 设计 §8)。

会话绑定到子项目路径时, 沿路径向上找出已注册的祖先项目, 把每一级目录内
的 SAGE.md/CLAUDE.md/AGENTS.md 按"父 → 子"顺序拼接注入 (越靠后优先级
越高)。链是派生的 (来自 projects 表的路径匹配), 不落库。

预算 (设计 §8.4):
- 单文件仍用 ``PER_FILE_CHAR_CAP`` (8000);
- 每层保底 ``CASCADE_PER_LAYER_FLOOR`` (2000), 防止内层被外层挤空;
- 总预算 ``CASCADE_TOTAL_CHAR_CAP`` (20000, ~5k token);
- 超预算从最外层开始截断, 允许低于保底;
- 内容哈希全局去重 (祖先先出现)。

失败永远降级为 ``discover_project_context`` (向上发现), 永不抛异常。
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Union

from backend.chat.project_context import (
    _CANDIDATES,
    CASCADE_HEADER,
    CASCADE_LEVEL_PROJECT,
    CASCADE_LEVEL_ROOT,
    CASCADE_PER_LAYER_FLOOR,
    CASCADE_PROJECT_LOOKUP_LIMIT,
    CASCADE_TOTAL_CHAR_CAP,
    PER_FILE_CHAR_CAP,
    RENDER_HEADER,
    ContextEntry,
    ProjectContext,
    _ancestor_chain,
    _read_candidate_text,
    _user_level_entries,
    discover_project_context,
)
from backend.data.project_repo import Project

logger = logging.getLogger(__name__)

__all__ = [
    "CASCADE_HEADER",
    "CASCADE_LEVEL_PROJECT",
    "CASCADE_LEVEL_ROOT",
    "CASCADE_PER_LAYER_FLOOR",
    "CASCADE_PROJECT_LOOKUP_LIMIT",
    "CASCADE_TOTAL_CHAR_CAP",
    "CascadeLayer",
    "ProjectContextCascade",
    "discover_project_context_cascade",
]


def _sanitize_marker_value(value: str) -> str:
    """项目名进入 HTML 注释标记前去掉换行/引号, 防止破坏标记结构。"""
    cleaned = re.sub(r'[\r\n"]+', " ", value or "").strip()
    return cleaned or "project"


def _registered_ancestor_projects(root: Path) -> List[Project]:
    """返回从文件系统根到 ``root`` (含) 的已注册项目链 (最外层在前)。

    以真实路径比较 (``normcase + realpath``), 兼容大小写不敏感文件系统与
    相对/符号链接形式的注册路径。任何失败 → 调用方降级为向上发现。
    """
    from backend.data.project_repo import ProjectRepository

    by_path: dict = {}
    for project in ProjectRepository().list(limit=CASCADE_PROJECT_LOOKUP_LIMIT):
        try:
            key = os.path.normcase(os.path.realpath(project.path))
        except OSError:
            continue
        by_path.setdefault(key, project)

    chain: List[Project] = []
    for directory in _ancestor_chain(root):
        key = os.path.normcase(os.path.realpath(str(directory)))
        project = by_path.get(key)
        if project is not None:
            chain.append(project)
    return chain


def _collect_layer_entries(directory: Path, seen_hashes: set) -> List[ContextEntry]:
    """收集单层目录内的指令文件 (不向上递归), 按内容哈希全局去重。"""
    entries: List[ContextEntry] = []
    for filename, source in _CANDIDATES:
        candidate = directory / filename
        content = _read_candidate_text(candidate)
        if content is None:
            continue
        digest = hashlib.sha256(content.strip().encode("utf-8", "replace")).hexdigest()
        if digest in seen_hashes:
            continue
        seen_hashes.add(digest)
        truncated = len(content) > PER_FILE_CHAR_CAP
        capped = content[:PER_FILE_CHAR_CAP]
        if not capped.strip():
            continue
        entries.append(
            ContextEntry(
                path=str(candidate),
                source=source,
                content=capped,
                truncated=truncated,
            )
        )
    return entries


def _apply_cascade_budget(
    layers: List[CascadeLayer],
    total_cap: int = CASCADE_TOTAL_CHAR_CAP,
    floor: int = CASCADE_PER_LAYER_FLOOR,
) -> None:
    """按 §8.4 预算就地截断 (写 ``budget_cut``): 从最外层开始, 每层先保底。"""
    lengths = [len(layer.plain_content()) for layer in layers]
    overshoot = sum(lengths) - total_cap
    if overshoot <= 0:
        return
    # 第一轮 — 从最外层开始压到每层保底, 只削减超出保底的部分
    for index, layer in enumerate(layers):
        if overshoot <= 0:
            break
        cut = min(overshoot, max(lengths[index] - min(floor, lengths[index]), 0))
        if cut:
            layer.budget_cut += cut
            overshoot -= cut
    # 第二轮 — 所有层都到保底仍超预算, 继续从最外层削, 允许低于保底
    for index, layer in enumerate(layers):
        if overshoot <= 0:
            break
        remaining = max(lengths[index] - layer.budget_cut, 0)
        cut = min(overshoot, remaining)
        if cut:
            layer.budget_cut += cut
            overshoot -= cut


@dataclass
class CascadeLayer:
    """级联链中的一层 (一个已注册项目目录)。"""

    project_id: str
    project_name: str
    path: str
    is_root: bool = False
    entries: List[ContextEntry] = field(default_factory=list)
    budget_cut: int = 0

    def marker(self) -> str:
        level = CASCADE_LEVEL_ROOT if self.is_root else CASCADE_LEVEL_PROJECT
        name = _sanitize_marker_value(self.project_name)
        return f'<!-- SAGE-CONTEXT level="{level}" project="{name}" -->'

    def plain_content(self) -> str:
        parts: List[str] = []
        for entry in self.entries:
            note = " [截断]" if entry.truncated else ""
            parts.append(f"--- {entry.path} [{entry.source}]{note} ---")
            parts.append(entry.content.rstrip())
        return "\n".join(parts)

    def content(self) -> str:
        body = self.plain_content()
        if self.budget_cut > 0 and body:
            body = body[: max(len(body) - self.budget_cut, 0)].rstrip()
            body = body + "\n[截断]" if body else ""
        return body


@dataclass
class ProjectContextCascade:
    """级联发现结果 + 渲染。

    ``fallback`` 非空表示链上没有注册项目 (或查询失败), 此时沿用既有的
    向上发现结果, 行为与 ``discover_project_context`` 一致。
    """

    workspace_root: str
    layers: List[CascadeLayer] = field(default_factory=list)
    global_entries: List[ContextEntry] = field(default_factory=list)
    fallback: Optional[ProjectContext] = None

    def has_content(self) -> bool:
        return bool(self.global_entries) or any(
            layer.content().strip() for layer in self.layers
        )

    def render(self) -> str:
        if self.fallback is not None:
            return self.fallback.render()
        parts: List[str] = []
        if self.global_entries:
            parts.append(RENDER_HEADER)
            for entry in self.global_entries:
                note = " [截断]" if entry.truncated else ""
                parts.append(f"\n--- {entry.path} [{entry.source}]{note} ---")
                parts.append(entry.content.rstrip())
        layer_parts: List[str] = []
        for layer in self.layers:
            body = layer.content()
            if not body.strip():
                continue
            layer_parts.append(layer.marker())
            layer_parts.append(body)
        if layer_parts:
            parts.append(CASCADE_HEADER)
            parts.extend(layer_parts)
        return "\n".join(parts)


def discover_project_context_cascade(
    workspace_root: Union[str, Path],
) -> ProjectContextCascade:
    """沿路径向上收集已注册祖先项目的上下文 (P4 级联, 设计 §8)。

    - 父 → 子顺序; 每层包 ``<!-- SAGE-CONTEXT level=... project=... -->``;
    - 单文件 8000, 每层保底 2000, 总预算 20000 (含用户级 ``~/.sage/SAGE.md``);
    - 超预算从最外层开始截断;
    - 内容哈希全局去重 (祖先先出现);
    - 链上没有注册项目 / 任何异常 → 降级为 ``discover_project_context``。
    永不抛异常。
    """
    root_str = str(workspace_root)
    try:
        root = Path(os.path.realpath(root_str))
        if not root.is_dir():
            return ProjectContextCascade(
                workspace_root=root_str,
                fallback=discover_project_context(root_str),
            )
        projects = _registered_ancestor_projects(root)
    except Exception as exc:  # noqa: BLE001 — 查询失败不能让聊天请求失败
        logger.debug("cascade: ancestor lookup failed, fallback: %s", exc)
        return ProjectContextCascade(
            workspace_root=root_str, fallback=discover_project_context(root_str)
        )

    if not projects:
        return ProjectContextCascade(
            workspace_root=root_str, fallback=discover_project_context(root_str)
        )

    try:
        seen_hashes: set = set()
        global_entries, used = _user_level_entries(
            seen_hashes, 0, total_cap=CASCADE_TOTAL_CHAR_CAP
        )
        layers: List[CascadeLayer] = []
        deepest = root
        for project in projects:
            try:
                directory = Path(os.path.realpath(project.path))
            except OSError:
                continue
            deepest = directory
            layers.append(
                CascadeLayer(
                    project_id=project.id,
                    project_name=project.name,
                    path=str(directory),
                    is_root=not layers,
                    entries=_collect_layer_entries(directory, seen_hashes),
                )
            )
        # 绑定的工作区比最深层注册项目更靠内 (且自身有指令文件) → 补叶子层
        if os.path.normcase(str(root)) != os.path.normcase(str(deepest)):
            leaf_entries = _collect_layer_entries(root, seen_hashes)
            if leaf_entries:
                layers.append(
                    CascadeLayer(
                        project_id="",
                        project_name=root.name,
                        path=str(root),
                        entries=leaf_entries,
                    )
                )
        _apply_cascade_budget(layers, total_cap=max(CASCADE_TOTAL_CHAR_CAP - used, 0))
        cascade = ProjectContextCascade(
            workspace_root=str(root),
            layers=layers,
            global_entries=global_entries,
        )
        if not cascade.has_content():
            cascade.fallback = discover_project_context(root_str)
        return cascade
    except Exception as exc:  # noqa: BLE001
        logger.warning("project context cascade failed (fallback): %s", exc)
        return ProjectContextCascade(
            workspace_root=root_str, fallback=discover_project_context(root_str)
        )

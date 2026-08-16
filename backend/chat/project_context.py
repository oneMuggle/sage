"""项目指令文件发现 (M6 生态扩展): SAGE.md / CLAUDE.md 向上搜索。

从 workspace 根目录一路向上遍历到文件系统根, 收集每一级的 SAGE.md 与
CLAUDE.md (两级都查, sage 优先)。设计改编自 claw-code
``rust/crates/runtime/src/prompt.rs`` (ProjectContext upward discovery +
content-hash dedupe + source tagging)。

约束:
- 按内容哈希去重 (strip 后比较);
- 单文件上限 ``PER_FILE_CHAR_CAP`` (8000), 总量上限 ``TOTAL_CHAR_CAP``
  (16000), 截断会在条目与 render 输出中标注;
- realpath 解析 workspace 根 (符号链接安全); 只读发现, 不跟随越界;
- 永不抛异常: 任何失败 → 空上下文 + 日志。
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

PER_FILE_CHAR_CAP = 8_000
TOTAL_CHAR_CAP = 16_000

SOURCE_SAGE_MD = "sage_md"
SOURCE_CLAUDE_MD = "claude_md"

RENDER_HEADER = "项目指令 (SAGE.md/CLAUDE.md):"

# 每级目录检查的候选文件 (顺序 = 优先级, sage 优先)
_CANDIDATES: Tuple[Tuple[str, str], ...] = (
    ("SAGE.md", SOURCE_SAGE_MD),
    ("CLAUDE.md", SOURCE_CLAUDE_MD),
)


@dataclass
class ContextEntry:
    """一个被收集的指令文件。"""

    path: str
    source: str  # "sage_md" | "claude_md"
    content: str
    truncated: bool = False


@dataclass
class ProjectContext:
    """发现结果 + 渲染。"""

    workspace_root: str
    entries: List[ContextEntry] = field(default_factory=list)

    def render(self) -> str:
        """渲染为可注入 system prompt 的文本块; 无条目 → 空串。"""
        if not self.entries:
            return ""
        parts: List[str] = [RENDER_HEADER]
        for entry in self.entries:
            note = " [截断]" if entry.truncated else ""
            parts.append(f"\n--- {entry.path} [{entry.source}]{note} ---")
            parts.append(entry.content.rstrip())
        return "\n".join(parts)


def _ancestor_chain(root: Path) -> List[Path]:
    """返回从文件系统根到 ``root`` 的目录链 (祖先在前)。"""
    chain: List[Path] = []
    cursor: Optional[Path] = root
    while cursor is not None:
        chain.append(cursor)
        parent = cursor.parent
        cursor = parent if parent != cursor else None
    chain.reverse()
    return chain


def _iter_candidates(root: Path) -> Iterator[Tuple[Path, str]]:
    """按发现顺序产出 (文件路径, source): 祖先在前, 每级 sage 先于 claude。"""
    for directory in _ancestor_chain(root):
        for filename, source in _CANDIDATES:
            yield directory / filename, source


def discover_project_context(workspace_root: Union[str, Path]) -> ProjectContext:
    """向上发现 SAGE.md/CLAUDE.md; 失败永远返回(可能为空的)上下文, 不抛。"""
    root_str = str(workspace_root)
    try:
        root = Path(os.path.realpath(root_str))
        if not root.is_dir():
            return ProjectContext(workspace_root=root_str)

        entries: List[ContextEntry] = []
        seen_hashes: set = set()
        total_chars = 0

        for candidate, source in _iter_candidates(root):
            if total_chars >= TOTAL_CHAR_CAP:
                logger.debug("project context: total cap reached, stop at %s", candidate)
                break
            try:
                if not candidate.is_file():
                    continue
                # 审查加固: 拒绝符号链接越界 —— 恶意仓库可用
                # SAGE.md → ~/.ssh/id_rsa 把任意文件注入 LLM 提示词。
                # 解析后的真实路径必须仍落在被扫描目录内 (工作区内互链放行)。
                resolved = Path(os.path.realpath(str(candidate)))
                scan_dir = Path(os.path.realpath(str(candidate.parent)))
                if resolved.parent != scan_dir:
                    logger.debug(
                        "project context: skip symlink escape %s -> %s",
                        candidate,
                        resolved,
                    )
                    continue
                content = resolved.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                logger.debug("project context: skip %s: %s", candidate, exc)
                continue

            digest = hashlib.sha256(content.strip().encode("utf-8", "replace")).hexdigest()
            if digest in seen_hashes:
                continue
            seen_hashes.add(digest)

            truncated = False
            capped = content
            if len(capped) > PER_FILE_CHAR_CAP:
                capped = capped[:PER_FILE_CHAR_CAP]
                truncated = True
            remaining = TOTAL_CHAR_CAP - total_chars
            if len(capped) > remaining:
                capped = capped[:remaining]
                truncated = True

            entries.append(
                ContextEntry(
                    path=str(candidate),
                    source=source,
                    content=capped,
                    truncated=truncated,
                )
            )
            total_chars += len(capped)

        return ProjectContext(workspace_root=str(root), entries=entries)
    except Exception as exc:
        logger.warning("project context discovery failed (empty context): %s", exc)
        return ProjectContext(workspace_root=root_str)

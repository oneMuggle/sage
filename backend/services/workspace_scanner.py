"""目录扫描与子项目发现（P2 of 2026-11-05 项目管理增强设计）。

职责单一：把一棵目录树翻译成"项目树"。

识别规则（设计 §7.2）::

    scan(dir, depth, parent_project):
        for entry in listdir(dir):
            if entry is symlink:
                → 记为 file_reference(kind='symlink')，不递归（防环）
                continue
            if not entry.is_dir(): continue
            if should_skip(entry): continue        # 默认排除 / .sageignore

            role = template.role_for(entry.name)
            has_ctx = contains_context_file(entry)

            if role == 'project' or has_ctx:
                → 注册为子项目
                → 递归进入
            elif depth < limit:
                → 继续递归寻找更深层子项目

目录树与数据库的同步遵循 **只增不删**（设计 §7.5）：磁盘上已消失的目录
不删除项目行（保留会话/记忆/规程），树构建阶段按路径存在性过滤。

安全约束：

- 扫描严格只读，不在用户目录写任何文件。
- 不跟随符号链接（``entry.is_symlink()`` 直接判定），避免环与拉入整棵外部目录树。
- 单目录条目数超限时停止递归该目录（仍记录其自身的项目身份）。
- 最大递归深度默认 6，覆盖「顶层 → 子项目 → 算例」等层级。
"""

from __future__ import annotations

import fnmatch
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

from backend.services.project_template import ProjectTemplate

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────
# 参数（设计 §7.3）
# ─────────────────────────────────────────────────────────────────────


#: 默认不扫描的目录名（与设计一致）。
DEFAULT_EXCLUDES: frozenset = frozenset(
    {
        ".git",
        "node_modules",
        "__pycache__",
        ".venv",
        "dist",
        "build",
        ".sage",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".idea",
        ".vscode",
    }
)

#: 最大递归深度（根 = 0）。
MAX_DEPTH = 6

#: 单目录最大条目数（超限停止递归该目录）。
MAX_ENTRIES_PER_DIR = 5000

#: 视为"目录即项目"的上下文文件名。
CONTEXT_FILE_NAMES: Tuple[str, ...] = ("SAGE.md", "CLAUDE.md", "AGENTS.md")

#: 扫描结果缓存 TTL（秒），避免频繁 I/O。
SCAN_CACHE_TTL_SECONDS = 30.0

#: 项目发现来源枚举。
DISCOVERY_MANUAL = "manual"
DISCOVERY_TEMPLATE = "template"
DISCOVERY_CONTEXT_FILE = "context_file"


# ─────────────────────────────────────────────────────────────────────
# 数据模型
# ─────────────────────────────────────────────────────────────────────


@dataclass
class ScannedNode:
    """扫描结果树中的一个目录节点。

    Attributes:
        path: 绝对路径（已规范化为字符串）。
        name: 目录名。
        rel_path: 相对于扫描根的 POSIX 相对路径（根为空字符串）。
        role: ``"root"`` | ``"project"`` | ``"folder"``。
        discovery_source: 项目节点的发现方式（``template`` / ``context_file`` /
            根节点为 ``manual``）；普通目录为 ``None``。
        children: 子节点（仅包含自身是项目或有项目后代的节点）。
    """

    path: str
    name: str
    rel_path: str
    role: str = "folder"
    discovery_source: Optional[str] = None
    children: List[ScannedNode] = field(default_factory=list)

    @property
    def is_project(self) -> bool:
        return self.role in ("root", "project")

    def to_dict(self) -> dict:
        return {
            "path": self.path,
            "name": self.name,
            "rel_path": self.rel_path,
            "role": self.role,
            "discovery_source": self.discovery_source,
            "children": [n.to_dict() for n in self.children],
        }


@dataclass(frozen=True)
class SymlinkRecord:
    """扫描中遇到的符号链接（记为文件引用，不递归）。"""

    rel_path: str  # 项目内虚拟位置（POSIX）
    name: str
    target_path: str  # 解析后的真实目标（``realpath``，不要求存在）

    def to_dict(self) -> dict:
        return {
            "rel_path": self.rel_path,
            "name": self.name,
            "target_path": self.target_path,
            "kind": "symlink",
        }


@dataclass
class ProjectTree:
    """一次扫描的完整结果。"""

    root: ScannedNode
    symlinks: List[SymlinkRecord] = field(default_factory=list)
    truncated_paths: List[str] = field(default_factory=list)
    scanned_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "root": self.root.to_dict(),
            "symlinks": [s.to_dict() for s in self.symlinks],
            "truncated": list(self.truncated_paths),
            "scanned_at": self.scanned_at,
        }

    def iter_projects(self) -> Iterator[ScannedNode]:
        """遍历所有项目节点（含根，深度优先）。"""

        def walk(node: ScannedNode) -> Iterator[ScannedNode]:
            if node.is_project:
                yield node
            for child in node.children:
                yield from walk(child)

        yield from walk(self.root)


# ─────────────────────────────────────────────────────────────────────
# .sageignore（gitignore 子集）
# ─────────────────────────────────────────────────────────────────────


def load_ignore_patterns(root: Path) -> List[str]:
    """读取 ``<root>/.sageignore``（gitignore 语法子集）。

    返回模式列表（保留顺序与 ``!`` 取反前缀）。文件不存在或读取失败返回空列表。
    """
    path = Path(root) / ".sageignore"
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        logger.warning("Cannot read .sageignore at %s: %s", path, exc)
        return []

    patterns: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _match_segments(pattern_parts: List[str], path_parts: List[str]) -> bool:  # noqa: PLR0911
    """逐段 glob 匹配，支持 ``**`` 跨任意层级。"""

    if not pattern_parts:
        return not path_parts
    head = pattern_parts[0]
    if head == "**":
        if len(pattern_parts) == 1:
            return True
        for i in range(len(path_parts) + 1):
            if _match_segments(pattern_parts[1:], path_parts[i:]):
                return True
        return False
    if not path_parts:
        return False
    if not fnmatch.fnmatchcase(path_parts[0], head):
        return False
    return _match_segments(pattern_parts[1:], path_parts[1:])


def _pattern_matches(pattern: str, rel_path: str, name: str) -> bool:
    """判断单个 gitignore 模式是否命中相对路径（目录）。"""
    anchored = pattern.startswith("/")
    body = pattern.lstrip("/")
    if body.endswith("/"):
        body = body[:-1]
    if not body:
        return False
    if anchored or "/" in body:
        return _match_segments(body.split("/"), rel_path.split("/"))
    # 无斜杠：按任意层级 basename 匹配
    return fnmatch.fnmatchcase(name, body)


def is_ignored(rel_path: str, name: str, patterns: List[str]) -> bool:
    """按 gitignore 语义求值（后匹配覆盖前匹配，支持 ``!`` 取反）。"""
    ignored = False
    for pattern in patterns:
        negated = pattern.startswith("!")
        body = pattern[1:] if negated else pattern
        if not body:
            continue
        if _pattern_matches(body, rel_path, name):
            ignored = not negated
    return ignored


# ─────────────────────────────────────────────────────────────────────
# 扫描器
# ─────────────────────────────────────────────────────────────────────


def contains_context_file(directory: Path) -> bool:
    """目录内是否直接存在任一上下文文件（SAGE.md / CLAUDE.md / AGENTS.md）。"""
    return any((Path(directory) / name).is_file() for name in CONTEXT_FILE_NAMES)


class WorkspaceScanner:
    """把目录树翻译为项目树。

    Args:
        max_depth: 最大递归深度（根 = 0，默认 6）。
        max_entries_per_dir: 单目录条目上限，超限停止递归该目录。
        excludes: 不扫描的目录名集合。
    """

    def __init__(
        self,
        max_depth: int = MAX_DEPTH,
        max_entries_per_dir: int = MAX_ENTRIES_PER_DIR,
        excludes: Optional[Set[str]] = None,
    ) -> None:
        self.max_depth = max(0, int(max_depth))
        self.max_entries_per_dir = max(1, int(max_entries_per_dir))
        self.excludes = frozenset(excludes) if excludes is not None else DEFAULT_EXCLUDES

    # ── 公共入口 ───────────────────────────────────────────────────

    def scan(
        self,
        root_path: Path,
        template: Optional[ProjectTemplate] = None,
    ) -> ProjectTree:
        """扫描 ``root_path``，返回项目树。

        Args:
            root_path: 项目根目录（须存在且是目录）。
            template: 可选模板，其 ``role == "project"`` 的目录声明直接识别为子项目。

        Raises:
            ValueError: ``root_path`` 不存在或不是目录。
        """
        root = Path(root_path).resolve()
        if not root.is_dir():
            raise ValueError(f"root_path is not a directory: {root}")

        project_roles = self._template_project_paths(template)
        ignore_patterns = load_ignore_patterns(root)
        tree = ProjectTree(
            root=ScannedNode(
                path=str(root),
                name=root.name,
                rel_path="",
                role="root",
                discovery_source=DISCOVERY_MANUAL,
            )
        )

        tree.root.children = self._scan_dir(
            root,
            depth=1,
            rel_prefix="",
            project_roles=project_roles,
            ignore_patterns=ignore_patterns,
            tree=tree,
        )
        return tree

    # ── 内部 ───────────────────────────────────────────────────────

    @staticmethod
    def _template_project_paths(template: Optional[ProjectTemplate]) -> Set[str]:
        """收集模板中声明为 ``role == "project"`` 的相对路径（POSIX）。"""
        if template is None:
            return set()
        paths: Set[str] = set()
        for d in template.directories:
            if d.role != "project":
                continue
            normalized = d.path.replace(os.sep, "/").strip("/")
            if normalized:
                paths.add(normalized)
        return paths

    def _should_skip_name(self, name: str) -> bool:
        return name in self.excludes

    def _scan_dir(
        self,
        directory: Path,
        depth: int,
        rel_prefix: str,
        project_roles: Set[str],
        ignore_patterns: List[str],
        tree: ProjectTree,
    ) -> List[ScannedNode]:
        """扫描 ``directory`` 的直接子目录，返回项目/容器节点列表。"""
        if depth > self.max_depth:
            return []

        try:
            with os.scandir(directory) as it:
                entries = list(it)
        except (PermissionError, OSError) as exc:
            logger.info("Skipping unreadable directory %s: %s", directory, exc)
            return []

        # 先排序再截断：保证超限时保留的是确定的前 N 个，输出可复现
        entries.sort(key=lambda e: e.name)

        truncated = len(entries) > self.max_entries_per_dir
        if truncated:
            rel_dir = rel_prefix or "."
            tree.truncated_paths.append(rel_dir)
            logger.info(
                "Directory %s has %d entries (> %d); recursion stopped",
                directory,
                len(entries),
                self.max_entries_per_dir,
            )
            entries = entries[: self.max_entries_per_dir]

        nodes: List[ScannedNode] = []
        for entry in entries:
            name = entry.name
            rel_path = f"{rel_prefix}/{name}" if rel_prefix else name

            # 符号链接：记录为文件引用，不递归（防环 / 防拉入外部目录树）
            if entry.is_symlink():
                tree.symlinks.append(
                    SymlinkRecord(
                        rel_path=rel_path,
                        name=name,
                        target_path=os.path.realpath(entry.path),
                    )
                )
                continue

            try:
                is_dir = entry.is_dir(follow_symlinks=False)
            except OSError:
                continue
            if not is_dir:
                continue

            if self._should_skip_name(name):
                continue
            if is_ignored(rel_path, name, ignore_patterns):
                continue

            role = "project" if rel_path in project_roles else None
            has_ctx = contains_context_file(Path(entry.path))

            if role == "project" or has_ctx:
                discovery = (
                    DISCOVERY_TEMPLATE if role == "project" else DISCOVERY_CONTEXT_FILE
                )
                node = ScannedNode(
                    path=str(Path(entry.path).resolve()),
                    name=name,
                    rel_path=rel_path,
                    role="project",
                    discovery_source=discovery,
                )
                if not truncated:
                    node.children = self._scan_dir(
                        Path(entry.path),
                        depth=depth + 1,
                        rel_prefix=rel_path,
                        project_roles=project_roles,
                        ignore_patterns=ignore_patterns,
                        tree=tree,
                    )
                nodes.append(node)
                continue

            # 普通目录：仅当内部存在项目后代时才作为容器节点保留，
            # 避免把整棵无关目录树塞进侧边栏。
            if truncated:
                continue
            descendants = self._scan_dir(
                Path(entry.path),
                depth=depth + 1,
                rel_prefix=rel_path,
                project_roles=project_roles,
                ignore_patterns=ignore_patterns,
                tree=tree,
            )
            if descendants:
                nodes.append(
                    ScannedNode(
                        path=str(Path(entry.path).resolve()),
                        name=name,
                        rel_path=rel_path,
                        role="folder",
                        discovery_source=None,
                        children=descendants,
                    )
                )

        return nodes


# ─────────────────────────────────────────────────────────────────────
# 模块级缓存（TTL 30s）
# ─────────────────────────────────────────────────────────────────────


_CACHE: Dict[str, ProjectTree] = {}
_CACHE_LOCK = threading.Lock()


def _cache_key(root_path: Path) -> str:
    return str(Path(root_path).resolve())


def scan_project(
    root_path: Path,
    template: Optional[ProjectTemplate] = None,
    *,
    force: bool = False,
    ttl: float = SCAN_CACHE_TTL_SECONDS,
) -> ProjectTree:
    """扫描项目目录（带 TTL 缓存）。

    Args:
        root_path: 项目根目录。
        template: 可选模板（用于 ``role == "project"`` 声明）。
        force: 强制重扫（忽略缓存）。
        ttl: 缓存有效期（秒）。

    Raises:
        ValueError: ``root_path`` 不存在或不是目录（缓存中过期的树不会被当成有效结果）。
    """
    # 先校验再查缓存：目录已消失时不能返回缓存里的旧树
    if not Path(root_path).is_dir():
        raise ValueError(f"root_path is not a directory: {root_path}")

    key = _cache_key(root_path)
    now = time.time()
    if not force:
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
        if cached is not None and (now - cached.scanned_at) < ttl:
            return cached

    tree = WorkspaceScanner().scan(root_path, template)
    with _CACHE_LOCK:
        _CACHE[key] = tree
    return tree


def invalidate_scan_cache(root_path: Optional[Path] = None) -> None:
    """清除扫描缓存；``root_path`` 为 ``None`` 时清空全部。"""
    with _CACHE_LOCK:
        if root_path is None:
            _CACHE.clear()
        else:
            _CACHE.pop(_cache_key(root_path), None)


# ─────────────────────────────────────────────────────────────────────
# 与数据库同步（设计 §7.5：只增不删）
# ─────────────────────────────────────────────────────────────────────


def sync_projects_from_tree(
    root_project_id: str,
    tree: ProjectTree,
) -> List[str]:
    """把扫描到的项目节点写回 ``projects`` 表。

    规则：

    - 根项目不动。
    - 每个扫描到的项目节点：已注册 → 刷新 ``parent_id`` / ``discovery_source``；
      未注册 → 新建项目行后写入嵌套信息。
    - **从不删除**项目行（磁盘上消失的目录由树构建阶段过滤）。
    - 项目行创建失败（如权限/路径校验失败）只记日志，不影响其余节点。

    Returns:
        本次新建的项目 id 列表。
    """
    # 延迟导入：避免测试导入本模块时初始化数据库单例
    from backend.data.project_repo import ProjectRepository

    repo = ProjectRepository()
    root_project = repo.get(root_project_id)
    if root_project is None:
        logger.warning("sync_projects_from_tree: root project %s not found", root_project_id)
        return []

    created: List[str] = []

    def walk(node: ScannedNode, parent_project_id: str) -> None:
        for child in node.children:
            if not child.is_project:
                # 容器目录：沿用当前最近的祖先项目
                walk(child, parent_project_id)
                continue

            existing = repo.get_project_for_workspace(child.path)
            if existing is None:
                try:
                    existing = repo.register(child.path)
                except Exception as exc:  # noqa: BLE001 — 单节点失败不阻断整树
                    logger.info("Cannot register scanned project %s: %s", child.path, exc)
                    walk(child, parent_project_id)
                    continue
                created.append(existing.id)

            repo.update_nesting(
                existing.id, parent_project_id, child.discovery_source
            )
            walk(child, existing.id)

    walk(tree.root, root_project_id)
    return created


def _owner_project_for_symlink(
    symlink_rel: str, project_nodes: List[Tuple[str, str]]
) -> Optional[Tuple[str, str]]:
    """找出符号链接所属的最近项目节点 (最长 rel_path 前缀)。

    返回 ``(项目内相对路径, project_id)``; 无归属项目 → None。
    """
    best: Optional[Tuple[str, str, str]] = None  # (node_rel, project_id, relative)
    for node_rel, project_id in project_nodes:
        if node_rel == "":
            relative = symlink_rel
        elif symlink_rel == node_rel:
            continue  # 符号链接占用了项目目录本身, 不归属该项目
        elif symlink_rel.startswith(node_rel + "/"):
            relative = symlink_rel[len(node_rel) + 1 :]
        else:
            continue
        if best is None or len(node_rel) > len(best[0]):
            best = (node_rel, project_id, relative)
    if best is None:
        return None
    return best[2], best[1]


def sync_file_references_from_tree(
    root_project_id: str,
    tree: ProjectTree,
) -> List[str]:
    """把扫描到的符号链接登记为 ``file_references`` (kind='symlink')。

    - 归属最近的已注册项目 (按 rel_path 最长前缀);
    - ``upsert_symlink`` 幂等: 同 rel_path 已存在则只更新目标;
    - **从不删除**引用 (磁盘上消失的符号链接保留记录, 由用户手动清理)。

    Returns:
        本次创建或更新的引用 id 列表。
    """
    if not tree.symlinks:
        return []
    # 延迟导入 —— 避免测试导入本模块时初始化数据库单例
    from backend.data.file_reference_repo import FileReferenceRepository
    from backend.data.project_repo import ProjectRepository

    project_repo = ProjectRepository()
    if project_repo.get(root_project_id) is None:
        logger.warning(
            "sync_file_references_from_tree: root project %s not found",
            root_project_id,
        )
        return []

    project_nodes: List[Tuple[str, str]] = [("", root_project_id)]

    def walk(node: ScannedNode) -> None:
        if node is not tree.root and node.is_project:
            project = project_repo.get_project_for_workspace(node.path)
            if project is not None:
                project_nodes.append((node.rel_path, project.id))
        for child in node.children:
            walk(child)

    walk(tree.root)

    reference_repo = FileReferenceRepository()
    touched: List[str] = []
    for symlink in tree.symlinks:
        owner = _owner_project_for_symlink(symlink.rel_path, project_nodes)
        if owner is None:
            continue
        rel_path, project_id = owner
        if not rel_path:
            continue
        try:
            reference = reference_repo.upsert_symlink(
                project_id,
                rel_path,
                symlink.target_path,
                alias_name=symlink.name,
            )
        except Exception as exc:  # noqa: BLE001 — 单条失败不阻断整树
            logger.info(
                "Cannot persist symlink reference %s: %s", symlink.rel_path, exc
            )
            continue
        touched.append(reference.id)
    return touched


__all__ = [
    "CONTEXT_FILE_NAMES",
    "DEFAULT_EXCLUDES",
    "DISCOVERY_CONTEXT_FILE",
    "DISCOVERY_MANUAL",
    "DISCOVERY_TEMPLATE",
    "MAX_DEPTH",
    "MAX_ENTRIES_PER_DIR",
    "ProjectTree",
    "SCAN_CACHE_TTL_SECONDS",
    "ScannedNode",
    "SymlinkRecord",
    "WorkspaceScanner",
    "contains_context_file",
    "invalidate_scan_cache",
    "is_ignored",
    "load_ignore_patterns",
    "scan_project",
    "sync_file_references_from_tree",
    "sync_projects_from_tree",
]

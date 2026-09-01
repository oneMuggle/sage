"""SKILL.md 资源索引与渲染（v2）。

- ``ResourceIndex``: skill 目录下的资源清单（scripts/references/assets/templates）
- ``build_resource_index``: 扫描 base_dir 构建索引
- ``validate_resource_path``: 路径遍历防御（复用 validation 模块）
- ``render_body_with_resources``: 替换 body 中的 ``{baseDir}/...`` 引用

设计要点
--------

- 仅索引白名单子目录（scripts/references/assets/templates），其他目录透明忽略
- scripts/ 仅接受 .py 文件，其他类型忽略（v1 简化）
- references/assets/templates 接受所有文件类型
- 隐藏目录/文件（以 . 开头）跳过
- ``render_body_with_resources`` 在替换占位符前校验路径不逃逸 base_dir
- ``validate_resource_path`` 复用 ``validation.validate_base_dir`` 的路径遍历防御
"""

from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import List, Set, Tuple

from .validation import SkillMdSecurityError

logger = logging.getLogger(__name__)

# 白名单子目录
ALLOWED_RESOURCE_DIRS = frozenset({"scripts", "references", "assets", "templates"})

# scripts/ 仅接受 .py 文件
_SCRIPT_EXTENSIONS = frozenset({".py"})
_WINDOWS_REPARSE_POINT = 0x0400


def _is_reparse_point(path: Path) -> bool:
    """Return whether a path has a link/reparse attribute; errors are unsafe."""
    try:
        result = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(result.st_mode):
        return True
    attributes = getattr(result, "st_file_attributes", 0)
    return bool(attributes & _WINDOWS_REPARSE_POINT)


def _resource_index_platform_supported() -> bool:
    """Return whether metadata-only resource enumeration is available.

    POSIX requires ``O_NOFOLLOW`` because indexed resources are consumed through
    the no-follow reopen path.  Windows may enumerate after metadata filtering,
    but this does not make pathname TOCTOU safe: rendering rechecks reparse
    points, regular-file status, containment, and index membership and never
    reads resource contents here.  Other platforms fail closed.
    """
    if os.name == "posix":
        return bool(getattr(os, "O_NOFOLLOW", 0))
    return os.name == "nt"


def _has_unsafe_component(path: Path, base_dir: Path) -> bool:
    """Check every lexical component without resolving through a link."""
    try:
        relative = path.relative_to(base_dir)
    except ValueError:
        return True
    current = base_dir
    for component in relative.parts:
        current /= component
        if _is_reparse_point(current):
            return True
    return False


_BASEDIR_PATTERN = re.compile(r"\{baseDir\}([\\/][^\s]*)?")
_BASEDIR_TOKEN = "{baseDir}"
# Punctuation that commonly terminates a resource reference in prose or Markdown.
# It is stripped only from the parsed path and retained in the rendered body.
_RESOURCE_TRAILING_PUNCTUATION = frozenset(
    ".,;:!?*_~`'\"-–—…，。；：！？、)]}）》」』】）〕"
)


def _split_trailing_resource_punctuation(suffix: str) -> Tuple[str, str]:
    """Separate prose punctuation from the resource path suffix."""
    split_at = len(suffix)
    while split_at > 1 and suffix[split_at - 1] in _RESOURCE_TRAILING_PUNCTUATION:
        split_at -= 1
    return suffix[:split_at], suffix[split_at:]


def _is_safe_root_placeholder_boundary(character: str, following: str = "") -> bool:
    """Allow prose punctuation, but not token/path concatenation."""
    if character in {"\x00", "\\", "{", "}"} or not character.isprintable():
        return False
    # A single dot can be prose punctuation (``{baseDir}.``), but a dot
    # followed by another dot or a path separator is a path-like suffix.
    if character == "." and following in {".", "/", "\\"}:
        return False
    return not (character.isalnum() or character == "_")


@dataclass(frozen=True)
class ResourceIndex:
    """skill 目录下的资源清单（v2）。

    字段全部为 ``tuple[Path, ...]``，按文件名字典序排列，确保测试可重现。
    """

    scripts: Tuple[Path, ...] = ()
    references: Tuple[Path, ...] = ()
    assets: Tuple[Path, ...] = ()
    templates: Tuple[Path, ...] = ()


def _iter_resource_files(directory: Path):
    """Yield files from a directory without descending through known reparse points.

    This metadata-first walk prevents recursion through reparse directories that are
    already known to be unsafe.  It is not an atomic handle-based defense against
    Windows TOCTOU races; consumers still perform their own no-follow reopen checks.
    """
    try:
        children = sorted(directory.iterdir(), key=lambda path: path.name)
    except OSError:
        return

    for child in children:
        # Check metadata before is_dir()/is_file(), both of which can follow links.
        try:
            if _is_reparse_point(child):
                continue
            if child.is_dir():
                yield from _iter_resource_files(child)
            elif child.is_file():
                yield child
        except OSError:
            # A metadata or traversal failure must not expose that branch.
            continue


def build_resource_index(base_dir: Path) -> ResourceIndex:
    """扫描 base_dir 下的白名单子目录，返回资源索引。

    扫描规则:
      - 仅扫描 ``ALLOWED_RESOURCE_DIRS`` 中的子目录
      - 跳过隐藏目录/文件（以 . 开头）
      - scripts/ 仅接受 ``.py`` 文件，其他扩展名忽略
      - references/assets/templates 接受所有文件类型
      - 子目录中可嵌套（递归扫描）

    Args:
        base_dir: skill 根目录（通常是 SKILL.md 所在目录）

    Returns:
        ``ResourceIndex``: 分类后的资源路径元组。base_dir 不存在时返回空索引（不抛异常）。
    """
    if not _resource_index_platform_supported():
        logger.warning("Resource index unavailable: platform lacks verified no-follow support")
        return ResourceIndex()
    try:
        if _is_reparse_point(base_dir) or not base_dir.is_dir():
            return ResourceIndex()
        # Store only canonical absolute paths so an index built from a relative
        # base remains valid when it is later re-authorized for rendering.
        canonical_base = base_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return ResourceIndex()

    base_dir = canonical_base
    scripts: List[Path] = []
    references: List[Path] = []
    assets: List[Path] = []
    templates: List[Path] = []

    for subdir_name in ALLOWED_RESOURCE_DIRS:
        subdir = base_dir / subdir_name
        try:
            if _has_unsafe_component(subdir, base_dir) or not subdir.is_dir():
                continue
        except OSError:
            # Metadata failures at the whitelist root fail closed.
            continue

        # A controlled walk checks each child before descending, unlike rglob(),
        # which may recurse into a junction/reparse directory first.
        for file_path in _iter_resource_files(subdir):
            try:
                if not file_path.is_file():
                    continue
                # 跳过隐藏文件
                if any(part.startswith(".") for part in file_path.relative_to(subdir).parts):
                    continue

                if _has_unsafe_component(file_path, base_dir):
                    logger.warning("Skipping symlinked/reparse resource: %s", file_path)
                    continue
                validate_resource_path(file_path, base_dir=base_dir)
            except (OSError, RuntimeError, ValueError, SkillMdSecurityError):
                logger.warning("Skipping unsafe resource candidate: %s", file_path)
                continue

            # scripts/ 仅接受 .py 文件
            if subdir_name == "scripts":
                if file_path.suffix not in _SCRIPT_EXTENSIONS:
                    continue
                scripts.append(file_path)
            elif subdir_name == "references":
                references.append(file_path)
            elif subdir_name == "assets":
                assets.append(file_path)
            elif subdir_name == "templates":
                templates.append(file_path)

    return ResourceIndex(
        scripts=tuple(scripts),
        references=tuple(references),
        assets=tuple(assets),
        templates=tuple(templates),
    )


def validate_resource_path(path: Path, base_dir: Path) -> Path:
    """校验资源路径不逃逸 base_dir（路径遍历防御）。

    检查逻辑:
      1. resolve 双方到绝对路径
      2. 检查 path 是否在 base_dir 内（允许 path == base_dir 自身）
      3. 失败抛 ``SkillMdSecurityError``

    Args:
        path: 待校验的资源路径
        base_dir: skill 根目录（通常是 SKILL.md 所在目录）

    Returns:
        resolve 后的绝对 ``Path``

    Raises:
        SkillMdSecurityError: path 不在 base_dir 内
    """
    try:
        resolved_path = path.resolve(strict=False)
        resolved_base = base_dir.resolve(strict=False)
    except OSError as exc:
        raise SkillMdSecurityError(f"cannot resolve path: {exc}") from exc

    # 检查 path 是否在 base_dir 内（允许 path == base_dir 自身）
    if resolved_path == resolved_base or resolved_base in resolved_path.parents:
        return resolved_path

    raise SkillMdSecurityError(f"resource path {path} is not under base_dir {base_dir}")


def _indexed_regular_resources(index: ResourceIndex, base_dir: Path) -> Set[Path]:
    """Return canonical regular files authorized by ``index``.

    ``ResourceIndex`` is an internal value, but callers can construct one by
    hand.  Re-apply the complete resource policy here instead of trusting the
    index fields to have been produced by :func:`build_resource_index`.
    """
    authorized: Set[Path] = set()
    try:
        resolved_base = base_dir.resolve(strict=True)
    except (OSError, RuntimeError):
        return authorized

    for category, resources in (
        ("scripts", index.scripts),
        ("references", index.references),
        ("assets", index.assets),
        ("templates", index.templates),
    ):
        for resource in resources:
            try:
                resource_path = Path(resource)
                if not resource_path.is_absolute():
                    # ResourceIndex entries are canonical absolute paths.  The
                    # relative fallback preserves compatibility with hand-built
                    # indexes while using the same canonical root.
                    resource_path = resolved_base / resource_path
                lexical_path = resource_path
                relative = lexical_path.relative_to(resolved_base)
                if (
                    not relative.parts
                    or relative.parts[0] != category
                    or any(part in {".", ".."} or part.startswith(".") for part in relative.parts)
                    or (category == "scripts" and resource_path.suffix not in _SCRIPT_EXTENSIONS)
                ):
                    continue
                if _has_unsafe_component(lexical_path, resolved_base):
                    continue
                resolved_resource = lexical_path.resolve(strict=True)
                if resolved_base not in resolved_resource.parents:
                    continue
                result = os.lstat(lexical_path)
                if not stat.S_ISREG(result.st_mode) or stat.S_ISLNK(result.st_mode):
                    continue
                if _is_reparse_point(lexical_path):
                    continue
                authorized.add(resolved_resource)
            except (OSError, RuntimeError, TypeError, ValueError):
                continue
    return authorized


def render_body_with_resources(body: str, base_dir: Path, index: ResourceIndex) -> str:
    """Replace placeholders with safe logical skill-relative paths.

    ``{baseDir}`` becomes ``.`` and a suffixed reference becomes its relative
    path.  Suffixed references must identify indexed regular resources.
    """
    matches = list(_BASEDIR_PATTERN.finditer(body))
    token_positions = [match.start() for match in matches]
    for token_position in token_positions:
        token_end = token_position + len(_BASEDIR_TOKEN)
        if token_end >= len(body):
            continue
        next_character = body[token_end]
        if not _is_safe_root_placeholder_boundary(
            next_character, body[token_end + 1 : token_end + 2]
        ):
            raise SkillMdSecurityError("invalid resource reference")
    if not matches:
        return body

    try:
        resolved_base = base_dir.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise SkillMdSecurityError("invalid skill resource base") from exc
    if not resolved_base.is_dir() or _is_reparse_point(base_dir):
        raise SkillMdSecurityError("invalid skill resource base")

    authorized = _indexed_regular_resources(index, base_dir)
    result = body
    for match in reversed(matches):
        suffix = match.group(1) or ""
        trailing_punctuation = ""
        if suffix:
            suffix, trailing_punctuation = _split_trailing_resource_punctuation(suffix)
        if not suffix:
            replacement = "." + trailing_punctuation
        else:
            if not suffix.startswith("/"):
                raise SkillMdSecurityError("invalid resource reference")
            relative_text = suffix[1:]
            if (
                not relative_text
                or "\x00" in relative_text
                or "\\" in relative_text
                or relative_text.startswith("/")
            ):
                raise SkillMdSecurityError("invalid resource reference")
            relative = Path(relative_text)
            if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
                raise SkillMdSecurityError("invalid resource reference")
            candidate = base_dir / relative
            try:
                resolved_candidate = validate_resource_path(candidate, base_dir=base_dir)
                result_stat = os.lstat(candidate)
            except (OSError, SkillMdSecurityError) as exc:
                raise SkillMdSecurityError("invalid resource reference") from exc
            if (
                not stat.S_ISREG(result_stat.st_mode)
                or stat.S_ISLNK(result_stat.st_mode)
                or resolved_candidate not in authorized
            ):
                raise SkillMdSecurityError("resource is not indexed")
            replacement = relative.as_posix() + trailing_punctuation
        result = result[: match.start()] + replacement + result[match.end() :]

    return result

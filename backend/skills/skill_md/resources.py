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
from typing import List, Tuple

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from .validation import SkillMdSecurityError

logger = logging.getLogger(__name__)

# 白名单子目录
ALLOWED_RESOURCE_DIRS = frozenset({"scripts", "references", "assets", "templates"})

# scripts/ 仅接受 .py 文件
_SCRIPT_EXTENSIONS = frozenset({".py"})

# {baseDir} 占位符正则（匹配 {baseDir}/任意路径）
_BASEDIR_PATTERN = re.compile(r"\{baseDir\}(/[^\s\)\]\}\,]*)?")


@dataclass(frozen=True)
class ResourceIndex:
    """skill 目录下的资源清单（v2）。

    字段全部为 ``tuple[Path, ...]``，按文件名字典序排列，确保测试可重现。
    """

    scripts: Tuple[Path, ...] = ()
    references: Tuple[Path, ...] = ()
    assets: Tuple[Path, ...] = ()
    templates: Tuple[Path, ...] = ()


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
    if not base_dir.is_dir():
        return ResourceIndex()

    scripts: List[Path] = []
    references: List[Path] = []
    assets: List[Path] = []
    templates: List[Path] = []

    for subdir_name in ALLOWED_RESOURCE_DIRS:
        subdir = base_dir / subdir_name
        if not subdir.is_dir():
            continue

        # 递归扫描子目录中的所有文件
        for file_path in sorted(subdir.rglob("*")):
            if not file_path.is_file():
                continue
            # 跳过隐藏文件
            if any(part.startswith(".") for part in file_path.relative_to(subdir).parts):
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


def render_body_with_resources(body: str, base_dir: Path, index: ResourceIndex) -> str:
    """替换 body 中的 ``{baseDir}/...`` 引用为绝对路径。

    校验逻辑:
      - ``{baseDir}`` 替换为 ``base_dir`` 的绝对路径
      - 替换后的路径必须通过 ``validate_resource_path`` 校验（不逃逸 base_dir）
      - 任何逃逸尝试抛 ``SkillMdSecurityError``

    Args:
        body: 原始 markdown body
        base_dir: skill 根目录
        index: 资源索引（当前未使用，保留接口）

    Returns:
        替换后的 body 字符串

    Raises:
        SkillMdSecurityError: 替换后的路径逃逸 base_dir
    """
    # 查找所有 {baseDir} 引用
    matches = list(_BASEDIR_PATTERN.finditer(body))

    if not matches:
        return body

    # 从后往前替换（避免索引偏移）
    resolved_base = base_dir.resolve()
    result = body

    for match in reversed(matches):
        # 获取 {baseDir} 后面的路径部分（如果有）
        path_suffix = match.group(1) or ""

        if path_suffix:
            # 构造完整路径并校验
            full_path = Path(str(resolved_base) + path_suffix)
            # 校验路径在 base_dir 内（防止 ../ 逃逸）
            validate_resource_path(full_path, base_dir=base_dir)
            resolved_path = full_path.resolve(strict=False)
        else:
            # 纯 {baseDir} 占位符，无路径后缀
            resolved_path = resolved_base

        # 替换占位符
        result = result[: match.start()] + str(resolved_path) + result[match.end() :]

    return result

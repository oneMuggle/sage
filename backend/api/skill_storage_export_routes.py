# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""M3/M4: 技能存储可见性与导出路由。

从 ``legacy_skills_routes.py`` 抽离，避免该文件越过 800 行架构上限。
包含:

- ``GET /skills/storage``           → 生效技能根目录 / 可写根 / 来源
- ``GET /skills/{name}/location``   → 单个 SKILL.md 技能真实目录（realpath 校验）
- ``GET /skills/export``            → 批量导出「我的技能」zip
- ``GET /skills/{name}/export``     → 单个技能 zip

所有路径都只在服务端解析；客户端拿到的路径仅用于主进程打开目录。
"""

from __future__ import annotations

import logging
import os
import zipfile
from io import BytesIO
from pathlib import Path
from typing import List
from urllib.parse import quote

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

logger = logging.getLogger(__name__)

router = APIRouter()

_EXPORT_ALLOWED_TOP_LEVEL = frozenset({"scripts", "references", "assets", "templates"})
_EXPORTABLE_MINE_ORIGINS = frozenset({"user", "imported", "generated"})


def _get_skill_adapter():
    """委托到 inproc 单例（与 REST 路由 / SkillTool 共享同一注册表）。"""
    from backend.adapters.out.skill.inproc import get_singleton

    return get_singleton()


def _resolve_writable_skills_root() -> tuple:
    """返回 (可写技能根目录, 来源)。优先级与 importer 保持一致。

    来源: ``env`` ($SAGE_SKILLS_DIR) > ``preference`` (设置项 skills_dir)
    > ``default`` (~/.sage/skills)。仅解析不 mkdir —— 存储信息接口是只读的。
    """
    env = os.environ.get("SAGE_SKILLS_DIR", "").strip()
    if env:
        return Path(env).expanduser(), "env"
    try:
        from backend.skills.skill_md.skills_dir_policy import read_skills_dir_preference

        preferred = read_skills_dir_preference()
    except Exception:  # noqa: BLE001 — 设置损坏不应让存储信息接口 500
        preferred = None
    if preferred is not None:
        return preferred, "preference"
    return Path.home() / ".sage" / "skills", "default"


def _is_within(child: Path, parent: Path) -> bool:
    """realpath 后判断 child 是否等于 parent 或位于其下（py38 无 is_relative_to）。"""
    try:
        child_resolved = child.resolve()
        parent_resolved = parent.resolve()
    except OSError:
        return False
    return child_resolved == parent_resolved or parent_resolved in child_resolved.parents


def _allowed_roots() -> List[Path]:
    from backend.skills.skill_md.loader import (
        _discover_shipped_dir,
        discover_skill_md_dirs,
    )

    roots = list(discover_skill_md_dirs())
    shipped = _discover_shipped_dir()
    if shipped is not None:
        roots.append(shipped)
    return roots


def _is_under_any(target: Path, roots: List[Path]) -> bool:
    """Whether ``target`` is inside one of ``roots``.

    同时接受「链接本身位于根内、resolve 后指向根外」的技能目录 —— 用户常在
    ``~/.sage/skills`` 里放软链接管理外部技能目录（本机已有 storage-analyzer
    先例）。绝对路径遍历（``../``）仍会被拒绝。
    """
    if any(_is_within(target, root) for root in roots):
        return True
    try:
        target_abs = Path(os.path.abspath(str(target)))
    except OSError:
        return False
    for root in roots:
        try:
            root_abs = Path(os.path.abspath(str(root)))
        except OSError:
            continue
        if target_abs == root_abs or root_abs in target_abs.parents:
            return True
    return False


@router.get("/skills/storage")
def get_skills_storage():
    """Return effective skills storage roots for the desktop UI.

    - 200 + ``{writable_root, writable_source, roots, shipped_root,
      installed_app_dir, writable_in_app_dir}``
    - 路径仅用于主进程「打开目录 / 在文件夹中显示」，不在普通列表接口透出。
    """
    from backend.skills.skill_md.loader import (
        _discover_shipped_dir,
        discover_skill_md_dirs,
    )

    writable, source = _resolve_writable_skills_root()
    roots = []
    for path in discover_skill_md_dirs():
        roots.append({"path": str(path), "writable": _is_within(path, writable)})
    shipped = _discover_shipped_dir()
    # backend/api/... → backend/api → backend → app root
    installed_app_dir = Path(__file__).resolve().parents[2]
    return {
        "writable_root": str(writable),
        "writable_source": source,
        "roots": roots,
        "shipped_root": str(shipped) if shipped is not None else None,
        "installed_app_dir": str(installed_app_dir),
        "writable_in_app_dir": _is_within(writable, installed_app_dir),
    }


@router.get("/skills/{name}/location")
def get_skill_location(name: str):
    """Return the real on-disk directory for a SKILL.md skill.

    - 200 + ``{"name", "path"}``
    - 404 — builtin（无磁盘目录）或技能不存在
    - 403 — 真实路径不在任何允许根（用户技能根 / shipped）之下
    """
    adapter = _get_skill_adapter()
    location = adapter.skill_location(name)
    if location is None:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "skill_location_unavailable",
                "message": "技能不存在或没有磁盘目录",
            },
        )
    target = Path(location)
    if not _is_under_any(target, _allowed_roots()):
        logger.warning("skill location rejected outside allowed roots: name=%s", name)
        raise HTTPException(
            status_code=403,
            detail={"type": "path_not_allowed", "message": "技能目录不在允许范围内"},
        )
    return {"name": name, "path": str(target.resolve())}


def _assert_exportable_skill_dir(name: str) -> Path:
    """Resolve a skill's real directory and enforce the allowed-roots boundary."""
    adapter = _get_skill_adapter()
    location = adapter.skill_location(name)
    if location is None:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "skill_not_exportable",
                "message": "内置技能由代码实现，没有可导出的磁盘目录",
            },
        )
    target = Path(location)
    if not _is_under_any(target, _allowed_roots()):
        logger.warning("skill export rejected outside allowed roots: name=%s", name)
        raise HTTPException(
            status_code=403,
            detail={"type": "path_not_allowed", "message": "技能目录不在允许范围内"},
        )
    if not target.is_dir():
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": "技能目录不存在"},
        )
    return target.resolve()


def _add_skill_to_zip(zf: zipfile.ZipFile, name: str, skill_dir: Path) -> int:
    """Add SKILL.md + allowed resource dirs, skipping symlinks and other files."""
    count = 0
    for path in sorted(skill_dir.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        rel = path.relative_to(skill_dir)
        if len(rel.parts) == 1:
            if rel.name != "SKILL.md":
                continue
        elif rel.parts[0] not in _EXPORT_ALLOWED_TOP_LEVEL:
            continue
        zf.write(path, arcname=f"{name}/{rel.as_posix()}")
        count += 1
    return count


def _zip_response(buffer: BytesIO, filename: str) -> Response:
    return Response(
        content=buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}"
        },
    )


@router.get("/skills/export")
def export_my_skills(scope: str = "mine"):
    """Export my skills (or all skillmd skills) as one zip.

    - 200 + application/zip
    - 404 + stable detail: 没有可导出的技能
    """
    adapter = _get_skill_adapter()
    allowed_origins = (
        _EXPORTABLE_MINE_ORIGINS if scope != "all" else _EXPORTABLE_MINE_ORIGINS | {"shipped"}
    )
    buffer = BytesIO()
    exported: List[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in adapter.list_skills_extended():
            if item.get("origin") not in allowed_origins:
                continue
            name = item.get("name")
            if not isinstance(name, str):
                continue
            try:
                target = _assert_exportable_skill_dir(name)
            except HTTPException:
                continue
            if _add_skill_to_zip(zf, name, target) > 0:
                exported.append(name)
    if not exported:
        raise HTTPException(
            status_code=404,
            detail={"type": "no_exportable_skills", "message": "没有可导出的技能"},
        )
    logger.info("Exported %d skills (scope=%s)", len(exported), scope)
    return _zip_response(buffer, "sage-skills.zip")


@router.get("/skills/{name}/export")
def export_skill(name: str):
    """Export a single SKILL.md skill directory as a zip.

    - 200 + application/zip
    - 404 — builtin / 不存在 / 目录为空
    - 403 — 真实路径越界
    """
    target = _assert_exportable_skill_dir(name)
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        count = _add_skill_to_zip(zf, name, target)
    if count == 0:
        raise HTTPException(
            status_code=404,
            detail={"type": "empty_skill", "message": "技能目录为空，无可导出内容"},
        )
    logger.info("Exported skill: %s (%d files)", name, count)
    return _zip_response(buffer, f"{name}.zip")


__all__ = ["router"]

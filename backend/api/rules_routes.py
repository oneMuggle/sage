# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""四层规则聚合与写接口（M3/M4，2026-11-07）。

读接口聚合全局 / 项目总纲 / 项目规则 / 规程四层；写接口只覆盖可写层
（`constraint` / `doc` / `global`）。`layer + rule_id` 走请求体/查询参数
而不进路径：`constraint:<uuid>` 自带冒号。
"""

from __future__ import annotations

import logging
import time
import uuid as uuid_module
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.data.database import make_with_db_lock
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_repo import Project, ProjectRepository
from backend.services.markdown_rules import (
    RuleValidationError,
    append_section,
    read_existing_text,
    remove_section,
    replace_section,
    validate_rule_text,
    write_text_atomic,
)
from backend.services.rules_registry import (
    PLAYBOOK_SOURCE_PREFIX,
    RulesRegistry,
    global_rules_path,
    split_markdown_sections,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["rules"])


def with_db_lock(func):  # noqa: ANN001 — 与 playbook_routes 同一装饰器工厂
    return make_with_db_lock(globals())(func)


def _error(status_code: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status_code, detail={"code": code, "message": message})


def _project_or_404(project_id: str) -> Project:
    project = ProjectRepository().get(project_id)
    if project is None:
        raise _error(404, "project_not_found", "项目不存在")
    if not Path(project.path).is_dir():
        raise _error(410, "project_path_missing", "项目目录不存在或已被移动")
    return project


@router.get("/projects/{project_id}/rules")
@with_db_lock
def list_project_rules(project_id: str) -> Dict[str, Any]:
    """四层规则聚合列表（只读）。"""
    project = _project_or_404(project_id)
    entries = RulesRegistry().list_rules(project)
    return {"rules": [entry.to_dict() for entry in entries]}


@router.get("/projects/{project_id}/rules/effective")
@with_db_lock
def effective_project_rules(project_id: str) -> Dict[str, Any]:
    """注入顺序 + 冲突提示。"""
    project = _project_or_404(project_id)
    return RulesRegistry().effective(project)


MAX_PROJECT_RULES = 200
_WRITABLE_LAYERS = ("constraint", "doc", "global")
_RAW_PREVIEW_CHARS = 100_000
_USER_SOURCE = "user"


class RuleCreateBody(BaseModel):
    layer: str
    category: Optional[str] = None
    content: str = ""
    trigger_pattern: Optional[str] = None
    priority: int = 5
    enabled: bool = True


class RulePatchBody(BaseModel):
    layer: str
    rule_id: str
    patch: Dict[str, Any] = Field(default_factory=dict)
    expected_updated_at: Optional[int] = None


def _raise_validation(exc: RuleValidationError) -> NoReturn:
    raise _error(exc.status_code, exc.code, exc.message)


def _validate_optional_text(value: Any) -> str:
    """空值放行；非空文本走与正文相同的 strip + 长度 + 扫描校验。"""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        return validate_rule_text(text)
    except RuleValidationError as exc:
        _raise_validation(exc)


def _patch_content(patch: Dict[str, Any]) -> str:
    """PATCH 的 content 必须是字符串；``None`` 不能隐式变成字面量 "None"。"""
    raw = patch.get("content")
    if not isinstance(raw, str):
        raise _error(422, "invalid_patch", "规则内容必须是字符串")
    return raw


def _user_constraints(project_id: str) -> List[Any]:
    return [
        row
        for row in ProjectConstraintRepository().list_by_project(project_id)
        if (row.source or _USER_SOURCE) == _USER_SOURCE
    ]


def _constraint_for_update(project_id: str, rule_id: str) -> Any:
    """定位用户来源的项目规则；规程投影行拒绝写。"""
    prefix, _, raw_id = rule_id.partition(":")
    if prefix != "constraint" or not raw_id:
        raise _error(404, "rule_not_found", "规则不存在")
    try:
        uuid_module.UUID(raw_id)
    except ValueError:
        raise _error(404, "rule_not_found", "规则不存在")
    for row in ProjectConstraintRepository().list_by_project(project_id):
        if row.id != raw_id:
            continue
        if (row.source or _USER_SOURCE).startswith(PLAYBOOK_SOURCE_PREFIX):
            raise _error(422, "rule_readonly", "规程投影规则请在规程编辑器中修改")
        return row
    raise _error(404, "rule_not_found", "规则不存在")


def _markdown_layer_path(project: Project, layer: str) -> Path:
    if layer == "global":
        return global_rules_path()
    if layer == "doc":
        return Path(project.path) / "SAGE.md"
    raise _error(422, "invalid_layer", "不支持的规则层")


def _markdown_target(
    project: Project, layer: str, rule_id: str
) -> Tuple[Path, int, str, Any]:
    """返回 (path, index, file_content, section)。

    只用 ``rule_id`` 定位条目，**真实路径取 adapter 的 ``origin``** —— `doc`
    层的 id 不含目录，祖先目录的同名文件会产出同一个 id；`editable == "full"`
    才唯一指向项目根 `SAGE.md`。
    """
    matches = [
        entry
        for entry in RulesRegistry().list_rules(project)
        if entry.layer == layer and entry.id == rule_id
    ]
    if not matches:
        raise _error(404, "rule_not_found", "规则不存在")
    writable = [entry for entry in matches if entry.editable == "full" and entry.origin]
    if not writable:
        raise _error(422, "rule_readonly", "该规则只读，请在编辑器中直接修改文件")
    entry = writable[0]
    path = Path(entry.origin)
    try:
        content = read_existing_text(path)
    except RuleValidationError as exc:
        _raise_validation(exc)
    try:
        index = int(rule_id.rsplit("#", 1)[1])
    except (IndexError, ValueError):
        raise _error(404, "rule_not_found", "规则不存在")
    sections = split_markdown_sections(content)
    if index < 0 or index >= len(sections):
        raise _error(409, "rule_conflict", "规则小节已变化，请刷新后重试")
    return path, index, content, sections[index]


def _render_section(section: Any, body: str) -> str:
    """保留原标题层级，只换正文；前言小节无标题行。"""
    if not section.heading:
        return body + "\n"
    return "{} {}\n\n{}\n".format("#" * max(section.level, 1), section.heading, body)


@router.post("/projects/{project_id}/rules", status_code=201)
@with_db_lock
def create_project_rule(project_id: str, body: RuleCreateBody) -> Dict[str, Any]:
    project = _project_or_404(project_id)
    if body.layer not in _WRITABLE_LAYERS:
        raise _error(422, "rule_readonly", "该层规则不可直接新建")
    try:
        content = validate_rule_text(body.content)
    except RuleValidationError as exc:
        _raise_validation(exc)
    if body.layer == "constraint":
        if len(_user_constraints(project_id)) >= MAX_PROJECT_RULES:
            raise _error(
                422,
                "rule_limit_reached",
                f"项目规则已达 {MAX_PROJECT_RULES} 条上限",
            )
        ProjectConstraintRepository().create(
            project_id=project_id,
            category=_validate_optional_text(body.category) or "general",
            content=content,
            trigger_pattern=_validate_optional_text(body.trigger_pattern) or None,
            priority=body.priority,
            source=_USER_SOURCE,
        )
        return {"ok": True}
    path = _markdown_layer_path(project, body.layer)
    heading = _validate_optional_text(body.category) or "规则"
    try:
        current = read_existing_text(path)
        write_text_atomic(path, append_section(current, heading, content))
    except RuleValidationError as exc:
        _raise_validation(exc)
    return {"ok": True}


def _constraint_updates(patch: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
    """把 PATCH body 规整成仓储层 update 参数。

    返回 ``(updates, clear_trigger)``。仓储层 ``update`` 忽略 ``None`` 而把
    ``""`` 原样落库；读侧会读回空串，因此「清空触发词」需要单独落 NULL。
    """
    updates: Dict[str, Any] = {}
    clear_trigger = False
    if "content" in patch:
        try:
            updates["content"] = validate_rule_text(_patch_content(patch))
        except RuleValidationError as exc:
            _raise_validation(exc)
    if "category" in patch:
        category = _validate_optional_text(patch["category"])
        if not category:
            raise _error(422, "invalid_category", "分类不能为空")
        updates["category"] = category
    if "trigger_pattern" in patch:
        trigger = _validate_optional_text(patch["trigger_pattern"])
        if trigger:
            updates["trigger_pattern"] = trigger
        else:
            clear_trigger = True
    if "priority" in patch:
        try:
            updates["priority"] = int(patch["priority"])
        except (TypeError, ValueError):
            raise _error(422, "invalid_priority", "优先级必须是整数")
    if "enabled" in patch:
        if not isinstance(patch["enabled"], bool):
            raise _error(422, "invalid_enabled", "enabled 必须是布尔值")
        updates["enabled"] = patch["enabled"]
    return updates, clear_trigger


def _clear_trigger(repo: ProjectConstraintRepository, constraint_id: str) -> None:
    """把触发词落成 NULL；仓储层没有「清空」语义，只能直接改这一列。"""
    conn = repo.db.get_connection()
    conn.execute(
        "UPDATE project_constraints SET trigger_pattern = NULL, updated_at = ? WHERE id = ?",
        (int(time.time() * 1000), constraint_id),
    )
    conn.commit()


def _apply_constraint_patch(project_id: str, body: RulePatchBody) -> Dict[str, Any]:
    row = _constraint_for_update(project_id, body.rule_id)
    if (
        body.expected_updated_at is not None
        and int(row.updated_at or 0) != body.expected_updated_at
    ):
        raise HTTPException(
            409,
            detail={
                "code": "rule_conflict",
                "message": "规则已被修改，请刷新后重试",
                "current": row.to_dict(),
            },
        )
    updates, clear_trigger = _constraint_updates(body.patch or {})
    constraint_id = body.rule_id.partition(":")[2]
    repo = ProjectConstraintRepository()
    if updates:
        repo.update(constraint_id, **updates)
    if clear_trigger:
        _clear_trigger(repo, constraint_id)
    return {"ok": True}


def _apply_markdown_patch(
    project: Project, layer: str, rule_id: str, patch: Dict[str, Any]
) -> Dict[str, Any]:
    if "content" not in patch:
        raise _error(422, "invalid_patch", "Markdown 规则只支持修改内容")
    path, index, current, section = _markdown_target(project, layer, rule_id)
    try:
        content = validate_rule_text(_patch_content(patch))
        write_text_atomic(
            path, replace_section(current, index, _render_section(section, content))
        )
    except RuleValidationError as exc:
        _raise_validation(exc)
    return {"ok": True}


@router.patch("/projects/{project_id}/rules")
@with_db_lock
def update_project_rule(project_id: str, body: RulePatchBody) -> Dict[str, Any]:
    project = _project_or_404(project_id)
    if body.layer == "constraint":
        return _apply_constraint_patch(project_id, body)
    if body.layer in ("doc", "global"):
        return _apply_markdown_patch(
            project, body.layer, body.rule_id, body.patch or {}
        )
    raise _error(422, "rule_readonly", "该层规则不可直接编辑")


@router.delete("/projects/{project_id}/rules")
@with_db_lock
def delete_project_rule(project_id: str, layer: str, rule_id: str) -> Dict[str, Any]:
    """DELETE 不带 body（``invokeBackend`` 只给 POST/PUT/PATCH 传 body）→ 走查询参数。"""
    project = _project_or_404(project_id)
    if layer == "constraint":
        row = _constraint_for_update(project_id, rule_id)
        if not ProjectConstraintRepository().delete(row.id):
            raise _error(404, "rule_not_found", "规则不存在")
        return {"ok": True}
    if layer in ("doc", "global"):
        path, index, current, _section = _markdown_target(project, layer, rule_id)
        try:
            write_text_atomic(path, remove_section(current, index))
        except RuleValidationError as exc:
            _raise_validation(exc)
        return {"ok": True}
    raise _error(422, "rule_readonly", "该层规则不可直接删除")


@router.get("/projects/{project_id}/rules/raw")
@with_db_lock
def read_raw_rules(project_id: str, layer: str = Query(...)) -> Dict[str, Any]:
    """整文件预览：让用户确知 `doc`/`global` 层改的是文件而不是数据库行。"""
    project = _project_or_404(project_id)
    if layer not in ("doc", "global"):
        raise _error(422, "invalid_layer", "只有项目总纲与全局规则支持整文件预览")
    path = _markdown_layer_path(project, layer)
    try:
        content = read_existing_text(path)
    except RuleValidationError as exc:
        _raise_validation(exc)
    return {
        "path": str(path),
        "content": content[:_RAW_PREVIEW_CHARS],
        "truncated": len(content) > _RAW_PREVIEW_CHARS,
    }

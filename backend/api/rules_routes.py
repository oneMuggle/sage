# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""四层规则聚合与写接口（M3/M4，2026-11-07）。

读接口聚合全局 / 项目总纲 / 项目规则 / 规程四层；写接口只覆盖可写层
（`constraint` / `doc` / `global`）。`layer + rule_id` 走请求体/查询参数
而不进路径：`constraint:<uuid>` 自带冒号。
"""

from __future__ import annotations

import json
import logging
import os
import time
import uuid as uuid_module
from pathlib import Path
from typing import Any, Dict, List, NoReturn, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from backend.data.database import make_with_db_lock
from backend.data.playbook_event_repo import record_playbook_event
from backend.data.playbook_repo import PlaybookRepository
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_repo import Project, ProjectRepository
from backend.memory.safety import get_scanner
from backend.services.markdown_rules import (
    RuleValidationError,
    append_section,
    read_existing_text,
    remove_section,
    replace_section,
    validate_rule_text,
    write_text_atomic,
)
from backend.services.playbook_library import (
    render_agents_markdown as render_playbook_agents_md,
    render_markdown_handbook as render_playbook_markdown,
)
from backend.services.rule_patch import (
    MAX_PATCH_OPERATIONS,
    PATCH_ACTIONS,
    PatchSchemaError,
    preview_patch,
)
from backend.services.rules_registry import (
    PLAYBOOK_SOURCE_PREFIX,
    RulesRegistry,
    global_rules_path,
    split_markdown_sections,
)
from backend.services.rules_transfer import (
    RulesImportValidationError,
    build_rules_export_envelope,
    diff_rules_import,
    parse_rules_import,
    render_rules_agents_md,
    render_rules_markdown,
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


class PatchPreviewBody(BaseModel):
    instruction: str = ""
    rule_id: Optional[str] = None


class PatchApplyBody(BaseModel):
    instruction: str = ""
    operations: List[Dict[str, Any]] = Field(default_factory=list)


def _op_result(
    op_id: str, status: str, message: str = "", current: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    result: Dict[str, Any] = {"op_id": op_id, "status": status, "message": message}
    if current is not None:
        result["current"] = current
    return result


def _entry_for(project: Project, layer: str, rule_id: str) -> Optional[Any]:
    for entry in RulesRegistry().list_rules(project):
        if entry.layer == layer and entry.id == rule_id:
            return entry
    return None


def _stale_snapshot(operation: Dict[str, Any], entry: Any) -> Optional[Dict[str, Any]]:
    """返回非空表示规则已被改动 —— 该条 conflict，不覆盖。

    ``constraint`` 有 ``updated_at`` 可精确比对；Markdown 层的条目没有时间戳
    （``updated_at=None``），改用 preview 时的 ``before.content`` 比对当前正文。
    """
    if entry.layer == "constraint":
        expected = operation.get("expected_updated_at")
        if expected is not None and int(entry.updated_at or 0) != int(expected):
            return entry.to_dict()
        return None
    before = operation.get("before") if isinstance(operation.get("before"), dict) else {}
    expected_content = str(before.get("content") or "").strip()
    if expected_content and expected_content != str(entry.content or "").strip():
        return entry.to_dict()
    return None


def _apply_add_op(
    project: Project, op_id: str, layer: str, after: Dict[str, Any]
) -> Dict[str, Any]:
    content = validate_rule_text(str(after.get("content") or ""))
    if layer == "constraint":
        if len(_user_constraints(project.id)) >= MAX_PROJECT_RULES:
            raise _error(
                422,
                "rule_limit_reached",
                f"项目规则已达 {MAX_PROJECT_RULES} 条上限",
            )
        ProjectConstraintRepository().create(
            project_id=project.id,
            category=_validate_optional_text(after.get("category")) or "general",
            content=content,
            trigger_pattern=_validate_optional_text(after.get("trigger_pattern")) or None,
            priority=int(after.get("priority") or 5),
            source=_USER_SOURCE,
        )
        return _op_result(op_id, "applied", "已新建")
    path = _markdown_layer_path(project, layer)
    heading = _validate_optional_text(after.get("category")) or "规则"
    write_text_atomic(path, append_section(read_existing_text(path), heading, content))
    return _op_result(op_id, "applied", "已新建")


def _constraint_update_values(after: Dict[str, Any]) -> Dict[str, Any]:
    """把 op.after 规整成仓储 update 参数；非法字段抛 HTTPException 交外层折成 invalid。"""
    updates: Dict[str, Any] = {}
    if "content" in after:
        updates["content"] = validate_rule_text(str(after.get("content") or ""))
    if "category" in after:
        category = _validate_optional_text(after.get("category"))
        if not category:
            raise _error(422, "invalid_patch", "分类不能为空")
        updates["category"] = category
    if "trigger_pattern" in after:
        updates["trigger_pattern"] = _validate_optional_text(after.get("trigger_pattern"))
    if "priority" in after:
        updates["priority"] = int(after["priority"])
    if "enabled" in after:
        if not isinstance(after["enabled"], bool):
            raise _error(422, "invalid_patch", "enabled 必须是布尔值")
        updates["enabled"] = after["enabled"]
    return updates


def _apply_update_op(
    project: Project, op_id: str, layer: str, rule_id: str, after: Dict[str, Any]
) -> Dict[str, Any]:
    if layer == "constraint":
        updates = _constraint_update_values(after)
        if not updates:
            return _op_result(op_id, "invalid", "没有可应用的修改")
        ProjectConstraintRepository().update(rule_id.partition(":")[2], **updates)
        return _op_result(op_id, "applied", "已更新")
    content = validate_rule_text(str(after.get("content") or ""))
    path, index, current, section = _markdown_target(project, layer, rule_id)
    write_text_atomic(
        path, replace_section(current, index, _render_section(section, content))
    )
    return _op_result(op_id, "applied", "已更新")


def _apply_delete_op(
    project: Project, op_id: str, layer: str, rule_id: str
) -> Dict[str, Any]:
    if layer == "constraint":
        if not ProjectConstraintRepository().delete(rule_id.partition(":")[2]):
            return _op_result(op_id, "invalid", "规则不存在")
    else:
        path, index, current, _section = _markdown_target(project, layer, rule_id)
        write_text_atomic(path, remove_section(current, index))
    return _op_result(op_id, "applied", "已删除")


def _apply_toggle_op(
    op_id: str, layer: str, rule_id: str, after: Dict[str, Any]
) -> Dict[str, Any]:
    enabled = after.get("enabled")
    if not isinstance(enabled, bool):
        return _op_result(op_id, "invalid", "enabled 必须是布尔值")
    if layer != "constraint":
        return _op_result(op_id, "invalid", "Markdown 规则不支持停用")
    ProjectConstraintRepository().update(rule_id.partition(":")[2], enabled=enabled)
    return _op_result(op_id, "applied", "已更新")


def _existing_target(
    project: Project, op_id: str, layer: str, operation: Dict[str, Any]
) -> Any:
    """返回可写条目；不可写时返回一条 invalid 结果（调用方直接返回）。"""
    rule_id = operation.get("rule_id")
    if not rule_id:
        return _op_result(op_id, "invalid", "缺少规则 ID")
    entry = _entry_for(project, layer, str(rule_id))
    if entry is None:
        return _op_result(op_id, "invalid", "规则不存在或已变更")
    if entry.editable != "full":
        return _op_result(op_id, "invalid", "该规则只读，请在规程编辑器中修改")
    return entry


def _conflict_result(
    op_id: str, operation: Dict[str, Any], entry: Any
) -> Optional[Dict[str, Any]]:
    stale = _stale_snapshot(operation, entry)
    if stale is None:
        return None
    return _op_result(op_id, "conflict", "规则已被修改，请刷新后重试", stale)


def _apply_existing_op(
    project: Project,
    op_id: str,
    action: str,
    layer: str,
    rule_id: str,
    after: Dict[str, Any],
) -> Dict[str, Any]:
    if action == "toggle":
        return _apply_toggle_op(op_id, layer, rule_id, after)
    if action == "delete":
        return _apply_delete_op(project, op_id, layer, rule_id)
    if action == "update":
        return _apply_update_op(project, op_id, layer, rule_id, after)
    return _op_result(op_id, "invalid", "未知操作类型")


def _dispatch_write_op(
    project: Project,
    op_id: str,
    action: str,
    layer: str,
    operation: Dict[str, Any],
    after: Dict[str, Any],
) -> Dict[str, Any]:
    if action == "add":
        return _apply_add_op(project, op_id, layer, after)
    target = _existing_target(project, op_id, layer, operation)
    if isinstance(target, dict):
        return target
    conflict = _conflict_result(op_id, operation, target)
    if conflict is not None:
        return conflict
    return _apply_existing_op(
        project, op_id, action, layer, str(operation.get("rule_id")), after
    )


def _apply_patch_operation(project: Project, operation: Dict[str, Any]) -> Dict[str, Any]:
    """单条 op 独立执行：任何失败都折成 results 项，不打断同批其他项。"""
    op_id = str(operation.get("op_id") or "")
    action = str(operation.get("action") or "")
    layer = str(operation.get("layer") or "")
    after = operation.get("after") if isinstance(operation.get("after"), dict) else {}
    if action not in PATCH_ACTIONS:
        return _op_result(op_id, "invalid", "未知操作类型")
    if layer not in _WRITABLE_LAYERS:
        return _op_result(op_id, "invalid", "该层规则只读，请在规程编辑器中修改")
    try:
        return _dispatch_write_op(project, op_id, action, layer, operation, after)
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        status = "conflict" if detail.get("code") == "rule_conflict" else "invalid"
        current = detail.get("current")
        return _op_result(
            op_id,
            status,
            str(detail.get("message") or "操作失败"),
            current if isinstance(current, dict) else None,
        )
    except RuleValidationError as exc:
        return _op_result(op_id, "invalid", exc.message)
    except (TypeError, ValueError):
        return _op_result(op_id, "invalid", "字段类型不正确")


# 不能套 @with_db_lock：锁是同步上下文管理，跨 await 持锁会卡住整个事件循环。
# DB 读取本身很短，交由事件循环直接执行。
@router.post("/projects/{project_id}/rules/patches/preview")
async def preview_rule_patch(project_id: str, body: PatchPreviewBody) -> Dict[str, Any]:
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise _error(422, "invalid_instruction", "请描述你想要的规则修改")
    project = _project_or_404(project_id)
    entries = RulesRegistry().list_rules(project)
    try:
        return await preview_patch(
            project, instruction, entries, focus_rule_id=body.rule_id
        )
    except PatchSchemaError as exc:
        raise _error(422, "patch_schema_invalid", str(exc))


@router.post("/projects/{project_id}/rules/patches/apply")
@with_db_lock
def apply_rule_patch(project_id: str, body: PatchApplyBody) -> Dict[str, Any]:
    project = _project_or_404(project_id)
    if not body.operations:
        raise _error(422, "invalid_patch", "没有可应用的修改")
    if len(body.operations) > MAX_PATCH_OPERATIONS:
        raise _error(
            422, "invalid_patch", f"一次最多应用 {MAX_PATCH_OPERATIONS} 条修改"
        )
    results = [_apply_patch_operation(project, operation) for operation in body.operations]
    applied = sum(1 for item in results if item["status"] == "applied")
    failed = len(results) - applied
    if applied:
        record_playbook_event(
            project_id,
            "rules_ai_apply",
            payload={
                "instruction": (body.instruction or "").strip()[:500],
                "ops": [
                    {
                        "action": operation.get("action"),
                        "layer": operation.get("layer"),
                        "rule_id": operation.get("rule_id"),
                    }
                    for operation in body.operations
                ],
                "applied": applied,
                "failed": failed,
            },
        )
    return {"results": results, "applied": applied, "failed": failed}


# ─────────────────────────────────────────────────────────────────────────────
# M6: 规则导出 / 导入端点（2026-11-07）
# ─────────────────────────────────────────────────────────────────────────────

EXPORT_FORMATS = {"json", "md", "agents"}

# 导入时 doc 层仅允许写入项目根 SAGE.md；CLAUDE.md / AGENTS.md 只读不写。
_IMPORT_WRITABLE_DOCS = frozenset({"SAGE.md"})


def _bound_playbook_spec(project: Project) -> Optional[Dict[str, Any]]:
    """从 PlaybookRepository 读取项目绑定的活跃规程快照。"""
    snapshot = PlaybookRepository().get_active(project.id)
    if snapshot and isinstance(snapshot.spec, dict):
        return snapshot.spec
    return None


def _format_response_format(fmt: str) -> str:
    """将请求的 format 参数映射为信封级格式名。"""
    if fmt == "json":
        return "sage.rules"
    if fmt == "md":
        return "markdown"
    return "agents"


def _scan_text_or_raise(text: str) -> Optional[str]:
    """安全扫描；返回 None 表示通过，否则返回原因字符串。"""
    scan = get_scanner().scan(text, level="all")
    if scan.blocked:
        return scan.reason
    return None


def _export_filename(project: Project, fmt: str) -> str:
    if fmt == "json":
        return f"rules-{project.name or project.id}.sagerules.json"
    if fmt == "md":
        return f"rules-{project.name or project.id}.sagerules.md"
    return "AGENTS.md"


def _export_content(
    project: Project,
    entries: List[Any],
    envelope: Dict[str, Any],
    playbook_spec: Optional[Dict[str, Any]],
    fmt: str,
) -> str:
    if fmt == "json":
        return json.dumps(envelope, ensure_ascii=False, indent=2)
    global_text = envelope["layers"].get("global_rules") or ""
    if fmt == "md":
        playbook_md = (
            render_playbook_markdown(playbook_spec) if playbook_spec else ""
        )
        return render_rules_markdown(
            project, entries, global_rules_text=global_text,
            playbook_markdown=playbook_md,
        )
    playbook_md = (
        render_playbook_agents_md(playbook_spec) if playbook_spec else ""
    )
    return render_rules_agents_md(
        project, entries, global_rules_text=global_text,
        playbook_agents_md=playbook_md,
    )


def _filter_export_entries(
    entries: List[Any],
    include_constraints: bool,
    include_docs: bool,
) -> List[Any]:
    """md/agents 渲染前按 include_* 开关过滤，JSON 信封另行构建。"""
    if include_constraints and include_docs:
        return entries
    return [
        entry
        for entry in entries
        if (include_constraints or entry.layer != "constraint")
        and (include_docs or entry.layer != "doc")
    ]


@router.get("/projects/{project_id}/rules/export")
@with_db_lock
def export_rules(
    project_id: str,
    format: str = "json",
    include_constraints: bool = True,
    include_playbook: bool = False,
    include_global: bool = False,
    include_docs: bool = True,
) -> Dict[str, Any]:
    """导出规则包。三种格式都以 JSON 返回（content 为字符串）。"""
    if format not in EXPORT_FORMATS:
        raise _error(400, "invalid_format", f"不支持的导出格式：{format}")
    project = _project_or_404(project_id)
    entries = RulesRegistry().list_rules(project)
    playbook_spec = _bound_playbook_spec(project) if include_playbook else None
    envelope = build_rules_export_envelope(
        project,
        entries,
        include_playbook=include_playbook and playbook_spec is not None,
        playbook_spec=playbook_spec,
        include_global=include_global,
        include_docs=include_docs,
        include_constraints=include_constraints,
    )
    render_entries = _filter_export_entries(
        entries, include_constraints, include_docs
    )
    content = _export_content(
        project, render_entries, envelope, playbook_spec, format
    )
    filename = _export_filename(project, format)
    record_playbook_event(
        project.id,
        "rules_export",
        payload={
            "format": format,
            "include_playbook": include_playbook,
            "include_global": include_global,
            "include_docs": include_docs,
            "filename": filename,
        },
    )
    return {
        "format": _format_response_format(format),
        "filename": filename,
        "content": content,
    }


class RulesImportPreviewBody(BaseModel):
    envelope: Any = None
    project_id: Optional[str] = None


class RulesImportApplyBody(BaseModel):
    envelope: Any = None
    project_id: Optional[str] = None
    selected: List[str] = Field(default_factory=list)
    overwrite: bool = False


def _candidate_to_dict(candidate: Any) -> Dict[str, Any]:
    return {
        "id": candidate.id,
        "kind": candidate.kind,
        "status": candidate.status,
        "content": candidate.content,
        "duplicate_of": candidate.duplicate_of,
        "layer": candidate.layer,
        "category": candidate.category,
        "trigger_pattern": candidate.trigger_pattern,
        "priority": candidate.priority,
        "enabled": candidate.enabled,
        "filename": candidate.filename,
    }


@router.post("/rules/import/preview")
@with_db_lock
def preview_rules_import(body: RulesImportPreviewBody) -> Dict[str, Any]:
    """解析信封 → 与当前状态比对 → 逐条返回 new/duplicate/conflict。"""
    try:
        envelope = parse_rules_import(body.envelope)
    except RulesImportValidationError as exc:
        raise _error(exc.status_code, "rules_import_invalid", exc.message)
    if not body.project_id:
        candidates = diff_rules_import(envelope, None, [])
        return {"candidates": [_candidate_to_dict(c) for c in candidates]}
    project = _project_or_404(body.project_id)
    existing = RulesRegistry().list_rules(project)
    candidates = diff_rules_import(envelope, project, existing)
    return {"candidates": [_candidate_to_dict(c) for c in candidates]}


def _validation_error_message(exc: Exception) -> str:
    """校验失败尽量保留具体原因；非校验异常返回通用文案。"""
    if isinstance(exc, RuleValidationError):
        return exc.message
    detail = getattr(exc, "detail", None)
    if isinstance(detail, dict):
        message = detail.get("message")
        if isinstance(message, str) and message:
            return message
    return "导入失败，请重试"


def _apply_constraint_candidate(
    project: Project,
    candidate: Any,
    item: Dict[str, Any],
    overwrite: bool,
    existing_count: int,
    editable_by_id: Dict[str, str],
) -> Dict[str, Any]:
    """约束候选落库：先校验后删旧；只读投影不可覆盖；替换不计入上限。"""
    cid = candidate.id
    if candidate.status == "duplicate":
        return _result(cid, "skipped", "已存在相同内容")
    if candidate.status == "conflict" and not overwrite:
        return _result(cid, "skipped", "已存在冲突，未开启覆盖")
    target_id = ""
    if candidate.status == "conflict":
        raw_id = candidate.duplicate_of or ""
        if editable_by_id.get(raw_id) == "full":
            target_id = raw_id.partition(":")[2]
        if not target_id:
            return _result(cid, "failed", "只读规则不可覆盖")
    try:
        content = validate_rule_text(str(item.get("content") or ""))
        category = _validate_optional_text(item.get("category")) or "general"
        trigger = _validate_optional_text(item.get("trigger_pattern")) or None
        priority = int(item.get("priority") or 5)
    except (RuleValidationError, HTTPException) as exc:
        return _result(cid, "failed", _validation_error_message(exc))
    if not target_id and existing_count >= MAX_PROJECT_RULES:
        return _result(
            cid, "failed", f"项目规则已达 {MAX_PROJECT_RULES} 条上限"
        )
    repo = ProjectConstraintRepository()
    if target_id:
        repo.delete(target_id)
    created = repo.create(
        project_id=project.id,
        category=category,
        content=content,
        trigger_pattern=trigger,
        priority=priority,
        source=_USER_SOURCE,
    )
    if item.get("enabled") is False:
        repo.update(created.id, enabled=False)
    return _result(cid, "applied", "已导入")


def _result(candidate_id: str, status: str, message: str) -> Dict[str, Any]:
    return {"id": candidate_id, "status": status, "message": message}


def _write_text_target(target: Path, text: str, overwrite: bool) -> str:
    """新建 / 追加 / 整文件覆盖；统一走原子写入，拒绝符号链接。"""
    if not target.exists():
        write_text_atomic(target, text)
        return "已创建"
    if overwrite:
        write_text_atomic(target, text)
        return "已覆盖"
    existing_text = target.read_text(encoding="utf-8")
    separator = "\n\n" if existing_text.strip() else ""
    write_text_atomic(target, existing_text + separator + text)
    return "已追加"


def _apply_doc_candidate(
    project: Project,
    candidate: Any,
    text: str,
    overwrite: bool,
) -> Dict[str, Any]:
    """Doc 候选落盘：仅允许写入项目根 SAGE.md。"""
    cid = candidate.id
    filename = candidate.filename or ""
    if filename not in _IMPORT_WRITABLE_DOCS:
        return _result(cid, "failed", "仅支持导入项目根 SAGE.md")
    root = os.path.realpath(project.path)
    target = Path(root) / filename
    if Path(os.path.realpath(str(target))).parent != Path(root):
        return _result(cid, "failed", "路径不合法")
    if candidate.status == "duplicate":
        return _result(cid, "skipped", "已存在相同内容")
    scan_reason = _scan_text_or_raise(text)
    if scan_reason:
        return _result(cid, "failed", "安全扫描未通过：" + scan_reason)
    return _result(cid, "applied", _write_text_target(target, text, overwrite))


def _apply_global_candidate(
    candidate: Any,
    text: str,
    overwrite: bool,
) -> Dict[str, Any]:
    """全局规则候选落盘：写入 ~/.sage/SAGE.md。"""
    cid = candidate.id
    if candidate.status == "duplicate":
        return _result(cid, "skipped", "已存在相同内容")
    target = global_rules_path()
    expected_parent = (Path.home() / ".sage").resolve()
    if target.resolve().parent != expected_parent:
        return _result(cid, "failed", "全局规则路径不合法")
    scan_reason = _scan_text_or_raise(text)
    if scan_reason:
        return _result(cid, "failed", "安全扫描未通过：" + scan_reason)
    return _result(cid, "applied", _write_text_target(target, text, overwrite))


def _apply_constraint_by_id(
    project: Project,
    candidate_id: str,
    candidate: Any,
    layers: Dict[str, Any],
    overwrite: bool,
    existing_count: int,
    editable_by_id: Dict[str, str],
) -> Dict[str, Any]:
    index = int(candidate_id.rsplit("-", 1)[1])
    constraints = layers.get("constraints") or []
    item = constraints[index] if 0 <= index < len(constraints) else None
    if item is None:
        return _result(candidate_id, "failed", "候选不存在")
    return _apply_constraint_candidate(
        project, candidate, item, overwrite, existing_count, editable_by_id
    )


def _apply_doc_by_id(
    project: Project,
    candidate_id: str,
    candidate: Any,
    layers: Dict[str, Any],
    overwrite: bool,
) -> Dict[str, Any]:
    text = (layers.get("project_docs") or {}).get(candidate.filename or "")
    if not text:
        return _result(candidate_id, "failed", "候选不存在")
    return _apply_doc_candidate(project, candidate, str(text), overwrite)


def _apply_global_by_id(
    candidate_id: str,
    candidate: Any,
    layers: Dict[str, Any],
    overwrite: bool,
) -> Dict[str, Any]:
    text = str(layers.get("global_rules") or "").strip()
    if not text:
        return _result(candidate_id, "failed", "候选不存在")
    return _apply_global_candidate(candidate, text, overwrite)


def _apply_import_candidate(
    project: Project,
    candidate_id: str,
    envelope: Dict[str, Any],
    overwrite: bool,
    candidate_by_id: Dict[str, Any],
    editable_by_id: Dict[str, str],
    existing_count: int,
) -> Dict[str, Any]:
    """按 id 分发到对应的 apply 辅助函数。"""
    candidate = candidate_by_id.get(candidate_id)
    if candidate is None:
        return _result(candidate_id, "failed", "候选不存在")
    layers = envelope.get("layers") or {}
    if candidate.kind == "constraint":
        return _apply_constraint_by_id(
            project,
            candidate_id,
            candidate,
            layers,
            overwrite,
            existing_count,
            editable_by_id,
        )
    if candidate.kind == "doc":
        return _apply_doc_by_id(project, candidate_id, candidate, layers, overwrite)
    if candidate.kind == "global":
        return _apply_global_by_id(candidate_id, candidate, layers, overwrite)
    if candidate.kind == "playbook":
        return _result(candidate_id, "deferred", "请通过规程库绑定")
    return _result(candidate_id, "failed", "未知候选")


def _consumes_limit(result: Dict[str, Any], candidate: Any) -> bool:
    """只有新建的 constraint 才占用上限；替换是净零操作。"""
    return (
        result["status"] == "applied"
        and candidate is not None
        and candidate.kind == "constraint"
        and candidate.status == "new"
    )


def _apply_selected_candidates(
    project: Project,
    envelope: Dict[str, Any],
    selected: List[str],
    overwrite: bool,
    candidate_by_id: Dict[str, Any],
    editable_by_id: Dict[str, str],
    existing_count: int,
) -> Tuple[List[Dict[str, Any]], int, int, int]:
    """逐条落库；单条异常不阻断批次，仅记为 failed。"""
    results: List[Dict[str, Any]] = []
    applied = 0
    failed = 0
    for candidate_id in selected:
        candidate = candidate_by_id.get(candidate_id)
        try:
            result = _apply_import_candidate(
                project,
                candidate_id,
                envelope,
                overwrite,
                candidate_by_id,
                editable_by_id,
                existing_count,
            )
            if _consumes_limit(result, candidate):
                existing_count += 1
        except RuleValidationError as exc:
            result = _result(candidate_id, "failed", exc.message)
        except Exception:
            logger.warning(
                "rules import candidate %s failed", candidate_id, exc_info=True
            )
            result = _result(candidate_id, "failed", "导入失败，请重试")
        results.append(result)
        if result["status"] == "applied":
            applied += 1
        elif result["status"] == "failed":
            failed += 1
    return results, applied, failed, existing_count


@router.post("/rules/import/apply")
@with_db_lock
def apply_rules_import(body: RulesImportApplyBody) -> Dict[str, Any]:
    """只提交勾选项，逐条落库，冲突项单独返回不阻断。"""
    try:
        envelope = parse_rules_import(body.envelope)
    except RulesImportValidationError as exc:
        raise _error(exc.status_code, "rules_import_invalid", exc.message)
    if not body.project_id:
        raise _error(400, "missing_project", "应用导入必须指定项目")
    project = _project_or_404(body.project_id)
    existing = RulesRegistry().list_rules(project)
    candidates = diff_rules_import(envelope, project, existing)
    candidate_by_id = {c.id: c for c in candidates}
    editable_by_id = {
        entry.id: entry.editable
        for entry in existing
        if entry.layer == "constraint"
    }
    results, applied, failed, _count = _apply_selected_candidates(
        project,
        envelope,
        list(body.selected),
        body.overwrite,
        candidate_by_id,
        editable_by_id,
        len(_user_constraints(project.id)),
    )
    record_playbook_event(
        project.id,
        "rules_import",
        payload={
            "applied": applied,
            "failed": failed,
            "selected": list(body.selected),
            "overwrite": body.overwrite,
        },
    )
    return {"applied": applied, "failed": failed, "results": results}


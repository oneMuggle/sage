# ruff: noqa: UP006, UP007, UP035 — release/win7 Python 3.8 兼容
"""规则导出 / 导入端点（M6，2026-11-07）。

从 ``rules_routes`` 拆出以守住单文件规模约束；路由前缀、参数与响应形状
与原模块完全一致。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.api.rules_routes import (
    _USER_SOURCE,
    MAX_PROJECT_RULES,
    _error,
    _project_or_404,
    _user_constraints,
    _validate_optional_text,
)
from backend.data.database import make_with_db_lock
from backend.data.playbook_event_repo import record_playbook_event
from backend.data.playbook_repo import PlaybookRepository
from backend.data.project_constraint_repo import ProjectConstraintRepository
from backend.data.project_repo import Project
from backend.memory.safety import get_scanner
from backend.services.markdown_rules import (
    RuleValidationError,
    validate_rule_text,
    write_text_atomic,
)
from backend.services.playbook_library import (
    render_agents_markdown as render_playbook_agents_md,
    render_markdown_handbook as render_playbook_markdown,
)
from backend.services.rules_registry import RulesRegistry, global_rules_path
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


def _record_export_event(
    project_id: str,
    fmt: str,
    include_playbook: bool,
    include_global: bool,
    include_docs: bool,
    filename: str,
) -> None:
    record_playbook_event(
        project_id,
        "rules_export",
        payload={
            "format": fmt,
            "include_playbook": include_playbook,
            "include_global": include_global,
            "include_docs": include_docs,
            "filename": filename,
        },
    )


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
    _record_export_event(
        project.id, format, include_playbook, include_global, include_docs, filename
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


def _parse_import_priority(value: Any) -> int:
    try:
        return int(value or 5)
    except (TypeError, ValueError):
        raise RuleValidationError("invalid_priority", "priority 必须是整数")


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
        priority = _parse_import_priority(item.get("priority"))
    except (RuleValidationError, HTTPException) as exc:
        return _result(cid, "failed", _validation_error_message(exc))
    if not target_id and existing_count >= MAX_PROJECT_RULES:
        return _result(
            cid, "failed", f"项目规则已达 {MAX_PROJECT_RULES} 条上限"
        )
    repo = ProjectConstraintRepository()
    created = repo.create(
        project_id=project.id,
        category=category,
        content=content,
        trigger_pattern=trigger,
        priority=priority,
        source=_USER_SOURCE,
    )
    # 先建新再删旧：create 失败时旧规则仍完整；delete 失败只会多一条可恢复重复。
    if target_id:
        repo.delete(target_id)
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

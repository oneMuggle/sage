"""Office staging quarantine API routes (plan / run / report / restore).

暴露 ``backend/office/staging_quarantine.py`` 的隔离式清理能力，让应用
（Electron 渲染端 / 本地 HTTP 客户端）能走既有审计路径，而不是只能通过 CLI。

设计约束（与 docs/mcp-office-quarantine.md 一致，违反任一条都算回归）：

1. **不暴露永久删除**。``purge_entry`` 没有对应端点：隔离区里的副本只能
   被 ``restore`` 取回，永久删除仍只保留 CLI 三重门禁
   （``--allow-permanent-deletion`` + ``--confirm-id`` + 保留期届满）。
2. **数据库只读**。plan/run 走 ``_open_ro``（``mode=ro``，保留 live WAL
   可见性），本路由层不会写主库。
3. **默认零删除**。``QuarantineRunRequest.dry_run`` 默认 ``True``；只有显式
   传 ``false`` 才真的把候选复制进隔离区（复制后逐文件校验、源目录漂移即
   放弃、失败保留源）。即便 ``dry_run=False``，也只移动 ``no_reference_found``
   的候选，``referenced`` / ``unknown`` / ``fresh`` 一律保留。
4. **早拒绝**。工作区必须绝对且存在、SQLite 文件必须存在、``doc_types``
   必须属于 ``word|ppt|excel|pdf``、``quarantine_id`` 必须匹配严格字符集。
5. **响应宽容**。成功路径回传 ``extra="allow"`` 的 Pydantic 模型：模块新增
   证据字段不会被 schema 校验吃掉（否则会 500），但已建模字段仍有类型约束。
   错误路径一律走 ``error_contract.error_json``（HTTP 状态码 + legacy 信封），
   不发明第三种错误形状。

候选列表按 ``MAX_RESPONSE_CANDIDATES`` 截断，避免 5000 候选 × 每候选引用
证据把响应撑到数十 MB；截断与否由 ``candidates_truncated`` 明示。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from backend.api.error_contract import error_json
from backend.data.database import get_database
from backend.office.staging_quarantine import (
    DEFAULT_QUIET_HOURS,
    DEFAULT_RETENTION_DAYS,
    DEFAULT_SCAN_BUDGET_BYTES,
    DEFAULT_SCAN_FILE_BYTES,
    DOC_TYPES,
    plan_quarantine,
    quarantine_report,
    quarantine_run,
    restore_entry,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/office/quarantine", tags=["office-quarantine"])

#: Candidate lists are truncated to keep the HTTP payload bounded.
MAX_RESPONSE_CANDIDATES = 500

#: Quarantine ids are module-generated: ``<UTC stamp>-<doc_type>-<doc_id>-<pid>-<uuid8>``.
QUARANTINE_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,200}$")

#: Permitted doc types (mirrors ``staging_quarantine.DOC_TYPES``).
_ALLOWED_DOC_TYPES = tuple(DOC_TYPES)


# ──────────────────────────────────────────────────────────────────────
# Response models (permissive: extra="allow")
# ──────────────────────────────────────────────────────────────────────


class ImportLeaseModel(BaseModel):
    """Electron import sentinel verdict for one staging directory."""

    model_config = ConfigDict(extra="allow")

    marker_present: bool = False
    completed: bool = False
    active: bool = False
    state: str = "none"
    token_matches: Optional[bool] = None
    created_at: Optional[int] = None
    owner_pid: Optional[int] = None
    owner_alive: Optional[bool] = None


class QuarantineCandidateModel(BaseModel):
    """One managed staging directory plus its retention verdict."""

    model_config = ConfigDict(extra="allow")

    doc_type: str
    document_id: str
    path: str
    status: str
    reason: Optional[str] = None
    references: List[Any] = Field(default_factory=list)
    bytes: Optional[int] = None
    files: Optional[int] = None
    newest_mtime_ms: Optional[int] = None
    import_lease: Optional[ImportLeaseModel] = None


class QuarantinePlanResponse(BaseModel):
    """``GET /office/quarantine/plan`` — read-only classification."""

    model_config = ConfigDict(extra="allow")

    read_only: bool = True
    safe_to_delete: bool = False
    mode: str = "quarantine"
    workspace: str
    database: str
    quarantine_root: Optional[str] = None
    candidates: List[QuarantineCandidateModel] = Field(default_factory=list)
    candidates_total: int = 0
    candidates_truncated: bool = False
    summary: Dict[str, int] = Field(default_factory=dict)
    notes: List[str] = Field(default_factory=list)
    db_scan_status: Optional[str] = None
    filesystem_scan_status: Optional[str] = None
    generated_at: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None


class QuarantineRunResponse(BaseModel):
    """``POST /office/quarantine/run`` — plan + optional copy-into-quarantine."""

    model_config = ConfigDict(extra="allow")

    mode: str = "quarantine"
    dry_run: bool = True
    safe_to_delete: bool = False
    plan_summary: Optional[Dict[str, int]] = None
    notes: List[str] = Field(default_factory=list)
    planned: List[Dict[str, Any]] = Field(default_factory=list)
    quarantined: List[Dict[str, Any]] = Field(default_factory=list)
    retained: List[Dict[str, Any]] = Field(default_factory=list)
    resumed: List[Dict[str, Any]] = Field(default_factory=list)
    error: Optional[str] = None


class QuarantineEntryModel(BaseModel):
    """One manifest record as surfaced by ``quarantine_report``."""

    model_config = ConfigDict(extra="allow")

    quarantine_id: str
    document_id: Optional[str] = None
    doc_type: Optional[str] = None
    source_path: Optional[str] = None
    quarantine_path: Optional[str] = None
    present: bool = False
    bytes: Optional[int] = None
    files: Optional[int] = None
    state: Optional[str] = None
    quarantined_at: Optional[str] = None
    eligible_for_purge_after: Optional[str] = None
    days_since_eligible: Optional[float] = None
    recoverable: bool = False


class QuarantineReportResponse(BaseModel):
    """``GET /office/quarantine/report`` — inventory of the quarantine dir."""

    model_config = ConfigDict(extra="allow")

    quarantine_root: str
    entries: List[QuarantineEntryModel] = Field(default_factory=list)
    total_entries: int = 0
    recoverable: int = 0
    automatic_deletion: bool = False
    purge_requires_human_confirmation: bool = True


class QuarantineRestoreResponse(BaseModel):
    """``POST /office/quarantine/{quarantine_id}/restore``."""

    model_config = ConfigDict(extra="allow")

    quarantine_id: str
    status: str
    restored_to: Optional[str] = None
    error: Optional[str] = None


# ──────────────────────────────────────────────────────────────────────
# Request models (strict: extra="forbid", bounded)
# ──────────────────────────────────────────────────────────────────────


class QuarantineRunRequest(BaseModel):
    """Body for ``POST /office/quarantine/run``.

    ``extra="forbid"`` 是有意的：调用方多传字段通常意味着它以为存在某个
    我们没有的安全开关（例如 purge），宁可 422 也不要静默忽略。
    """

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, description="Absolute workspace directory")
    dry_run: bool = Field(
        default=True,
        description="True (default) only plans; False copies unreferenced candidates into quarantine",
    )
    quiet_hours: int = Field(default=DEFAULT_QUIET_HOURS, ge=0, le=24 * 365)
    retention_days: int = Field(default=DEFAULT_RETENTION_DAYS, ge=1, le=3650)
    scan_budget_bytes: int = Field(
        default=DEFAULT_SCAN_BUDGET_BYTES, ge=1024, le=2 * 1024 * 1024 * 1024
    )
    scan_file_bytes: int = Field(default=DEFAULT_SCAN_FILE_BYTES, ge=1024, le=512 * 1024 * 1024)
    deadline_seconds: float = Field(default=60.0, ge=1.0, le=600.0)
    skip_filesystem_scan: bool = False
    doc_types: Optional[List[str]] = Field(
        default=None,
        description="Restrict execution to these doc types; None means all managed types",
    )


class QuarantineRestoreRequest(BaseModel):
    """Body for ``POST /office/quarantine/{quarantine_id}/restore``."""

    model_config = ConfigDict(extra="forbid")

    workspace_path: str = Field(min_length=1, description="Absolute workspace directory")


# ──────────────────────────────────────────────────────────────────────
# Guards
# ──────────────────────────────────────────────────────────────────────


def _workspace_or_error(workspace_path: str) -> Union[Path, JSONResponse]:
    """Resolve the workspace, or build the legacy error envelope."""
    if not workspace_path or not workspace_path.strip():
        return error_json(400, "invalid_workspace_path", "工作区路径不能为空")
    candidate = Path(workspace_path)
    if not candidate.is_absolute():
        return error_json(400, "workspace_path_must_be_absolute", "工作区路径必须是绝对路径")
    try:
        resolved = candidate.resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        return error_json(400, "unresolvable_workspace_path", f"工作区路径无法解析: {exc}")
    if not resolved.is_dir():
        return error_json(404, "workspace_not_found", f"工作区不存在: {resolved}")
    return resolved


def _database_or_error() -> Union[Path, JSONResponse]:
    """Locate the app SQLite file (quarantine opens it read-only)."""
    raw = getattr(get_database(), "db_path", None)
    if not raw:
        return error_json(503, "database_unavailable", "数据库路径不可用，无法做只读引用判定")
    path = Path(str(raw))
    if not path.is_file():
        return error_json(503, "database_file_missing", f"数据库文件不存在: {path}")
    return path


def _doc_types_or_error(doc_types: Optional[List[str]]) -> Union[List[str], JSONResponse]:
    """Validate the optional doc-type allowlist (fail loud, never silently drop)."""
    if doc_types is None:
        return []
    cleaned = [item.strip() for item in doc_types if isinstance(item, str) and item.strip()]
    invalid = [item for item in cleaned if item not in _ALLOWED_DOC_TYPES]
    if invalid:
        return error_json(
            400,
            "invalid_doc_type",
            "doc_types 只支持 " + "/".join(_ALLOWED_DOC_TYPES) + f"，收到无效值: {invalid}",
        )
    return cleaned


def _quarantine_id_or_error(quarantine_id: str) -> Union[str, JSONResponse]:
    """Reject ids outside the module's generated charset before touching disk."""
    if not QUARANTINE_ID_RE.match(quarantine_id or ""):
        return error_json(400, "invalid_quarantine_id", "quarantine_id 含非法字符")
    return quarantine_id


def _truncate(items: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int, bool]:
    """Cap a candidate list; returns ``(items, total, truncated)``."""
    total = len(items)
    if total <= MAX_RESPONSE_CANDIDATES:
        return list(items), total, False
    return list(items[:MAX_RESPONSE_CANDIDATES]), total, True


# ──────────────────────────────────────────────────────────────────────
# Endpoints
# ──────────────────────────────────────────────────────────────────────


@router.get("/plan", response_model=QuarantinePlanResponse)
def quarantine_plan_endpoint(
    workspace_path: str,
    quiet_hours: int = Query(default=DEFAULT_QUIET_HOURS, ge=0, le=24 * 365),
    scan_budget_bytes: int = Query(
        default=DEFAULT_SCAN_BUDGET_BYTES, ge=1024, le=2 * 1024 * 1024 * 1024
    ),
    scan_file_bytes: int = Query(default=DEFAULT_SCAN_FILE_BYTES, ge=1024, le=512 * 1024 * 1024),
    deadline_seconds: float = Query(default=30.0, ge=1.0, le=600.0),
    skip_filesystem_scan: bool = Query(default=False),
) -> Union[QuarantinePlanResponse, JSONResponse]:
    """Read-only verdict for every managed staging directory.

    ``read_only=True`` / ``safe_to_delete=False`` 恒定；本端点不移动任何文件。
    """
    workspace = _workspace_or_error(workspace_path)
    if isinstance(workspace, JSONResponse):
        return workspace
    database = _database_or_error()
    if isinstance(database, JSONResponse):
        return database

    plan = plan_quarantine(
        database,
        workspace,
        quiet_hours=quiet_hours,
        scan_budget_bytes=scan_budget_bytes,
        scan_file_bytes=scan_file_bytes,
        deadline_seconds=deadline_seconds,
        skip_filesystem_scan=skip_filesystem_scan,
    )
    candidates, total, truncated = _truncate(list(plan.get("candidates") or []))
    response = QuarantinePlanResponse(
        read_only=bool(plan.get("read_only", True)),
        safe_to_delete=False,
        mode=str(plan.get("mode") or "quarantine"),
        workspace=str(plan.get("workspace") or workspace),
        database=str(plan.get("database") or database),
        quarantine_root=plan.get("quarantine_root"),
        candidates=candidates,
        candidates_total=total,
        candidates_truncated=truncated,
        summary=dict(plan.get("summary") or {}),
        notes=[str(note) for note in (plan.get("notes") or [])],
        db_scan_status=plan.get("db_scan_status"),
        filesystem_scan_status=plan.get("filesystem_scan_status"),
        generated_at=plan.get("generated_at"),
        duration_ms=plan.get("duration_ms"),
        error=plan.get("error"),
    )
    if plan.get("error"):
        logger.warning("quarantine plan degraded: %s", plan.get("error"))
    return response


@router.post("/run", response_model=QuarantineRunResponse)
def quarantine_run_endpoint(
    req: QuarantineRunRequest,
) -> Union[QuarantineRunResponse, JSONResponse]:
    """Plan, then (only when ``dry_run=False``) copy unreferenced staging aside.

    执行语义完全交给 ``quarantine_run``：复制后逐文件校验哈希、源目录在复制
    期间发生漂移即放弃并保留源、失败候选写 ``failed`` 清单行且不动源。
    本端点只加输入校验与响应截断，不额外决定谁该被隔离。
    """
    workspace = _workspace_or_error(req.workspace_path)
    if isinstance(workspace, JSONResponse):
        return workspace
    database = _database_or_error()
    if isinstance(database, JSONResponse):
        return database
    doc_types = _doc_types_or_error(req.doc_types)
    if isinstance(doc_types, JSONResponse):
        return doc_types

    result = quarantine_run(
        database,
        workspace,
        dry_run=req.dry_run,
        quiet_hours=req.quiet_hours,
        retention_days=req.retention_days,
        scan_budget_bytes=req.scan_budget_bytes,
        scan_file_bytes=req.scan_file_bytes,
        deadline_seconds=req.deadline_seconds,
        skip_filesystem_scan=req.skip_filesystem_scan,
        doc_types=doc_types or None,
    )
    if not req.dry_run:
        logger.info(
            "quarantine run executed: workspace=%s quarantined=%d retained=%d resumed=%d",
            workspace,
            len(result.get("quarantined") or []),
            len(result.get("retained") or []),
            len(result.get("resumed") or []),
        )
    return QuarantineRunResponse(
        mode=str(result.get("mode") or "quarantine"),
        dry_run=bool(result.get("dry_run", req.dry_run)),
        safe_to_delete=False,
        plan_summary=result.get("plan_summary"),
        notes=[str(note) for note in (result.get("notes") or [])],
        planned=[dict(item) for item in (result.get("planned") or [])],
        quarantined=[dict(item) for item in (result.get("quarantined") or [])],
        retained=[dict(item) for item in (result.get("retained") or [])],
        resumed=[dict(item) for item in (result.get("resumed") or [])],
        error=result.get("error"),
    )


@router.get("/report", response_model=QuarantineReportResponse)
def quarantine_report_endpoint(
    workspace_path: str,
) -> Union[QuarantineReportResponse, JSONResponse]:
    """Inventory the quarantine directory: age, retention state, recoverability.

    ``automatic_deletion=False`` / ``purge_requires_human_confirmation=True``
    由模块恒定返回，本端点原样透出，便于 UI 直接展示不可自动删除的事实。
    """
    workspace = _workspace_or_error(workspace_path)
    if isinstance(workspace, JSONResponse):
        return workspace

    report = quarantine_report(workspace)
    return QuarantineReportResponse(
        quarantine_root=str(report.get("quarantine_root") or ""),
        entries=[dict(item) for item in (report.get("entries") or [])],
        total_entries=int(report.get("total_entries") or 0),
        recoverable=int(report.get("recoverable") or 0),
        automatic_deletion=bool(report.get("automatic_deletion", False)),
        purge_requires_human_confirmation=bool(
            report.get("purge_requires_human_confirmation", True)
        ),
    )


@router.post("/{quarantine_id}/restore", response_model=QuarantineRestoreResponse)
def quarantine_restore_endpoint(
    quarantine_id: str,
    req: QuarantineRestoreRequest,
) -> Union[QuarantineRestoreResponse, JSONResponse]:
    """Copy quarantined bytes back to the original path and verify hashes.

    拒绝路径全部由 ``restore_entry`` 决定（未知 id / 非 done 状态 / 副本缺失 /
    原路径已被占用 / 清单无文件记录 / 校验失败），本端点只把它们透出为
    ``status="error"`` + ``error`` 机器码，HTTP 仍是 200：这些是业务裁决，
    不是传输错误。
    """
    workspace = _workspace_or_error(req.workspace_path)
    if isinstance(workspace, JSONResponse):
        return workspace
    qid = _quarantine_id_or_error(quarantine_id)
    if isinstance(qid, JSONResponse):
        return qid

    result = restore_entry(workspace, qid)
    status = str(result.get("status") or "error")
    if status != "restored":
        logger.info("quarantine restore refused: id=%s error=%s", qid, result.get("error"))
    return QuarantineRestoreResponse(
        quarantine_id=str(result.get("quarantine_id") or qid),
        status=status,
        restored_to=result.get("restored_to"),
        error=result.get("error"),
    )

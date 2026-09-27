# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
# ruff: noqa: UP006, UP007, UP035 — pydantic v1 + Python 3.8 兼容：
# pydantic v1 resolve_annotations 用 eval() 处理 forward refs，
# eval 在 Python 3.8 上无法解析 PEP 585 (List[X]) 和 PEP 604 (X | Y)，
# 所以本文件保留 typing.List/Optional/Union 写法
"""
API 路由定义
"""

from __future__ import annotations

# I5: 流式视觉延迟 — DONE 事件的 content 拆成 chunk 逐个入队,
# 让前端能逐字渲染 (避免 LLM 一次返回完整字符串时 "砰一下" 全显示)。
# 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls (大改),
# 先用这个 producer 端的 fake stream 解决 90% 的视觉体验。
_STREAMING_CHUNK_SIZE = 6
_STREAMING_CHUNK_DELAY_S = 0.04
import json
import logging
from typing import Any, Dict, List, Optional, Sequence, Set

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.chat.compaction import (
    estimate_messages_tokens,
)


def _resolve_effective_window(  # noqa: PLR0911 — Task 5 priority cascade, each branch is a distinct user-facing mode
    model_id: Optional[str] = None,
    max_context: Optional[int] = None,
    request_endpoint_id: Optional[str] = None,
    auto_context: Optional[bool] = None,
) -> Optional[int]:
    """Task 5: Resolve effective context window from model catalog.

    Priority for ``endpoint_id``: request > persisted settings > None.
    Behaviour by ``auto_context`` flag (after catalog resolve):

    - ``auto_context=True``  → resolve from catalog; ``max_context``, if
      set, is applied as a safety upper bound (``min(catalog, max)``).
      This is the path that lets the UI's ``autoContext`` switch actually
      turn on catalog-driven window sizing.
    - ``auto_context=False`` → fixed cap at ``max_context`` (user pinned
      a value). Catalog caps still apply via effective_window.
    - ``auto_context=None``  → resolve from catalog (the default for
      callers that do not yet pass the field), 4096 default cap.

    Returns ``max_context`` if the catalog cannot be resolved, else
    ``None`` so callers can decide how to fall back.
    """
    try:
        from backend.data.database import get_database
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository
        from backend.model_catalog.context import effective_window
        from backend.model_catalog.repository import CatalogRepository
        from backend.model_catalog.schemas import EndpointKey

        raw = SettingsRepository().get_json("app_settings")
        if not isinstance(raw, dict):
            return max_context if max_context else None
        settings = to_camel(raw)
        endpoints = settings.get("endpoints") or []
        if not isinstance(endpoints, list):
            return max_context if max_context else None

        # Priority: request endpoint_id > persisted settings
        endpoint_id = None
        if request_endpoint_id:
            # Verify the request endpoint_id exists in the endpoints list
            ep = next(
                (e for e in endpoints if isinstance(e, dict) and e.get("id") == request_endpoint_id),
                None,
            )
            if ep is not None:
                endpoint_id = request_endpoint_id

        if not endpoint_id:
            # Fallback to persisted settings
            selections = settings.get("modelSelections") or {}
            chat_sel = selections.get("chatModel") if isinstance(selections, dict) else None
            if isinstance(chat_sel, dict) and chat_sel.get("endpointId"):
                ep_id = chat_sel["endpointId"]
                ep = next(
                    (e for e in endpoints if isinstance(e, dict) and e.get("id") == ep_id),
                    None,
                )
                if ep is not None:
                    endpoint_id = ep_id

        if not endpoint_id or not model_id:
            return max_context if max_context else None

        repo = CatalogRepository(get_database())
        resolved = repo.resolve(EndpointKey(endpoint_id=endpoint_id, model_id=model_id))
        # auto_context=True (UI toggle on): catalog-driven window with
        # max_context as a safety upper bound. This is the only branch
        # where the UI's autoContext switch actually reaches catalog
        # resolution — without it, the previous logic made max_context
        # always win and the toggle was inert.
        if auto_context is True:
            # effective_window(automatic=True) ignores ``fixed`` per the
            # schema contract, so the natural catalog window is returned
            # first and only then clamped to max_context. 4096 is a
            # stand-in positive int — its value is discarded.
            window = effective_window(
                resolved.limits, automatic=True, fixed=4096,
            )
            if max_context:
                window = min(window, max_context)
            return window
        # auto_context=False: user explicitly pinned a value, treat as cap.
        if auto_context is False and max_context:
            return effective_window(
                resolved.limits, automatic=False, fixed=max_context,
            )
        # auto_context=None (or False without max_context): resolve from
        # catalog, 4096 default ceiling.
        return effective_window(
            resolved.limits, automatic=True, fixed=4096,
        )
    except Exception:
        return max_context if max_context else None


def _check_request_within_window(
    messages: Sequence[Dict[str, Any]],
    effective_window: Optional[int],
) -> None:
    """Brief line 16: explicit reject when required content overshoots window.

    The history was already truncated to ``max(0, effective_window - reserve)``,
    so this guard only fires when system / attachments / trailing_system /
    current user input alone exceed the resolved window (e.g., a 1 MB
    attachment + a long system prompt against a 4K-window model). Without
    this check the producer would silently send an over-budget request that
    the upstream LLM truncates or errors on — this gives the caller a
    deterministic 400 instead.

    No-op when the catalog has not resolved a window (``effective_window``
    is None or non-positive) so callers without catalog data keep the legacy
    behaviour.
    """
    if effective_window is None or effective_window <= 0:
        return
    total = estimate_messages_tokens(messages)
    if total > effective_window:
        raise HTTPException(
            status_code=400,
            detail=(
                f"required content (system + history + attachments + current "
                f"input) ~{total} tokens exceeds resolved context window "
                f"({effective_window} tokens); reduce input length, drop "
                f"attachments, or pick a larger-context model"
            ),
        )


from backend.skills.draft_store import get_skill_draft_store
from backend.skills.loader import get_skill_loader
from backend.skills.skill_md.frontmatter import (
    SkillMdParseError,
    dump as dump_skill_md,
    parse as parse_skill_md,
)

logger = logging.getLogger(__name__)

from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由 with_db_lock 闭包解析
    _SQLITE_LOCK,
    make_with_db_lock,
)


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。"""
    return make_with_db_lock(globals())(func)


from backend.api.legacy_skills_routes import (  # noqa: F401 — _get_skill_adapter 委托
    _get_skill_adapter,
)


def _safe_log_field(value: object, max_length: int = 64) -> str:
    """Sanitize a user-controlled field for safe logging.

    - Strip newlines and control chars to prevent log injection
    - Truncate to max_length to prevent log spam
    """
    s = str(value)
    s = "".join(c for c in s if c.isprintable() or c == " ")
    return s[:max_length]


router = APIRouter()

# ==================== C1 第三刀：Skill Draft/Audit/Rollback/Consolidation 路由组迁出 =====
# ------------------------------------------------------------------ #
# Skill Draft Approval Queue (Task 10)
#
# REST endpoints for reviewing skill drafts produced by the Background
# Review pipeline.
#
# - GET  /skill-drafts                 → list drafts (optional status filter)
# - POST /skill-drafts/{id}/approve    → approve draft + write SKILL.md to disk
# - POST /skill-drafts/{id}/reject     → reject draft
# ------------------------------------------------------------------ #


@router.get("/skill-drafts")
@with_db_lock
def list_skill_drafts(status: str = "pending"):
    """List skill drafts by status.

    - 200 + ``{"drafts": [...]}``
    - Query param ``status`` defaults to ``"pending"``.
    """
    draft_store = get_skill_draft_store()
    drafts = draft_store.list(status=status)
    return {"drafts": [_draft_to_dict(d) for d in drafts]}


def _validate_skill_draft_content(content: Any, draft_name: str) -> None:
    """Validate approved draft content without loading or executing skill code."""
    if not isinstance(content, str):
        raise ValueError("content must be a UTF-8 string")

    metadata, _ = parse_skill_md(content)
    if metadata.get("name") != draft_name:
        raise ValueError(
            f"frontmatter name {metadata.get('name')!r} does not match draft name {draft_name!r}"
        )


@router.post("/skill-drafts/{draft_id}/approve")
@with_db_lock
def approve_skill_draft(draft_id: str):
    """User approves skill draft → write to SKILL.md on disk.

    - 200 + ``{"status": "approved", "skill_name": ..., "draft_id": ...}``
    - 400 — invalid skill name (path traversal / separators / empty);
      draft status NOT updated (follow-up: regenerate or edit the draft)
    - 404 — draft not found
    - 409 — a skill with the same name already exists; draft status NOT updated
    - 500 — file-system write failure (status NOT updated)
    """
    draft_store = get_skill_draft_store()
    draft = draft_store.get(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "draft_not_found", "message": "Draft not found"},
        )

    # I-1 fix: validate name *before* touching the filesystem so that
    # drafts with un-writable names (LLM hallucinations like "../foo")
    # get a clean 400 instead of an opaque 500 OSError.
    from backend.skills.review_service import ReviewService

    try:
        ReviewService._validate_skill_name(draft.name)
    except ValueError as exc:
        logger.warning(
            "Skill draft %s has an invalid name (error_type=%s)",
            _safe_log_field(draft_id),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_skill_name", "message": "Invalid skill name"},
        ) from exc

    try:
        _validate_skill_draft_content(draft.content, draft.name)
    except (SkillMdParseError, TypeError, ValueError, UnicodeError) as exc:
        logger.warning(
            "Skill draft %s has invalid SKILL.md content (error_type=%s)",
            _safe_log_field(draft_id),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_skill_content",
                "message": "Invalid SKILL.md content",
            },
        ) from exc

    # Round 7: provenance frontmatter 注入 —— hermes 的 provenance 语义
    # (agent-created / user-created)，审计与巡检都依赖这个标记区分来源。
    content_to_write = draft.content
    try:
        meta, body = parse_skill_md(content_to_write)
        metadata_field = meta.get("metadata")
        if not isinstance(metadata_field, dict):
            metadata_field = {}
        metadata_field.setdefault("provenance", "agent-created")
        meta["metadata"] = metadata_field
        content_to_write = dump_skill_md(meta, body)
    except (SkillMdParseError, TypeError, ValueError, UnicodeError) as exc:
        logger.warning(
            "provenance 注入失败，按原文落盘 (draft=%s): %s",
            _safe_log_field(draft_id),
            type(exc).__name__,
        )

    try:
        skill_loader = get_skill_loader()
        skill_loader.write(draft.name, content_to_write, overwrite=False)
    except FileExistsError as exc:
        logger.info(
            "Skill already exists; draft=%s remains pending",
            _safe_log_field(draft_id),
        )
        raise HTTPException(
            status_code=409,
            detail={"code": "skill_already_exists", "message": "Skill already exists"},
        ) from exc
    except ValueError as exc:
        # Keep diagnostics server-side without exposing loader internals to clients.
        logger.error(
            "Failed to write skill draft: draft=%s error_type=%s errno=%s",
            _safe_log_field(draft_id),
            type(exc).__name__,
            getattr(exc, "errno", None),
        )
        raise HTTPException(
            status_code=400,
            detail={"code": "skill_write_rejected", "message": "Failed to write skill"},
        ) from exc
    except (PermissionError, OSError) as exc:
        # Filesystem exceptions can include absolute paths or file contents.
        logger.error(
            "Failed to write skill draft: draft=%s error_type=%s errno=%s",
            _safe_log_field(draft_id),
            type(exc).__name__,
            getattr(exc, "errno", None),
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "skill_write_failed", "message": "Failed to write skill"},
        ) from exc

    draft_store.update_status(draft_id, "approved")
    # Round 3: 审批创建动作进审计台账（append-only, best-effort）
    try:
        from backend.skills.audit import get_skill_audit_log

        get_skill_audit_log().record(
            draft.name,
            "create",
            actor="user",
            after_content=content_to_write,
            source=f"draft:{draft_id}",
        )
    except Exception as exc:  # noqa: BLE001 — 审计为旁路
        logger.warning("Skill audit hook (create) failed: %s", exc)
    try:
        reload_result = _get_skill_adapter().rescan_skill_mds()
    except Exception as exc:  # noqa: BLE001 — approval succeeds even if reload fails
        logger.warning(
            "Approved skill rescan failed: draft=%s error_type=%s",
            _safe_log_field(draft_id),
            type(exc).__name__,
        )
        reload_result = {"loaded": []}
    return {
        "status": "approved",
        "skill_name": draft.name,
        "draft_id": draft_id,
        "reloaded": any(
            item.get("name") == draft.name for item in reload_result.get("loaded", [])
        ),
    }


@router.post("/skill-drafts/{draft_id}/reject")
@with_db_lock
def reject_skill_draft(draft_id: str):
    """User rejects skill draft → mark as rejected.

    - 200 + ``{"status": "rejected", "draft_id": ...}``
    - 404 — draft not found
    """
    draft_store = get_skill_draft_store()
    draft = draft_store.get(draft_id)
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "draft_not_found", "message": "Draft not found"},
        )

    draft_store.update_status(draft_id, "rejected")
    return {"status": "rejected", "draft_id": draft_id}


# ---------------------------------------------------------------------------
# Round 3 (skill audit + rollback, 对标 hermes curator):
# 技能变更审计台账查询 + 单条一键回滚。
# ---------------------------------------------------------------------------


@router.get("/skills/{name}/audit")
def list_skill_audit(name: str, limit: int = 50):
    """List audit entries for a skill (append-only ledger).

    - 200 + ``{"skill_name": ..., "entries": [...]}``
    """
    from backend.skills.audit import get_skill_audit_log

    entries = get_skill_audit_log().list_entries(name, limit=max(1, min(limit, 200)))
    return {"skill_name": name, "entries": entries}


@router.post("/skills/{name}/rollback")
@with_db_lock
def rollback_skill(name: str):
    """Rollback a skill to its latest recorded previous content.

    - 200 + ``{"status": "rolled_back", "skill_name": ...}``
    - 404 — skill does not exist on disk
    - 409 — no rollback snapshot recorded for this skill
    - 400 — invalid skill name
    """
    from backend.skills.audit import get_skill_audit_log
    from backend.skills.loader import get_skill_loader

    loader = get_skill_loader()
    try:
        current = loader.read(name)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_skill_name", "message": "Invalid skill name"},
        ) from exc
    if current is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "skill_not_found", "message": "Skill not found"},
        )

    snapshot = get_skill_audit_log().latest_before_snapshot(name)
    if snapshot is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "no_rollback_snapshot",
                "message": "No previous content recorded for this skill",
            },
        )

    try:
        loader.write(name, snapshot, overwrite=True)
    except (OSError, ValueError) as exc:
        logger.error(
            "Skill rollback write failed: name=%s error_type=%s",
            _safe_log_field(name),
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=500,
            detail={"code": "skill_write_failed", "message": "Failed to write skill"},
        ) from exc

    get_skill_audit_log().record(
        name,
        "rollback",
        actor="user",
        before_content=current,
        after_content=snapshot,
    )
    logger.info("Skill rolled back: %s", _safe_log_field(name))
    return {"status": "rolled_back", "skill_name": name}


# ---------------------------------------------------------------------------
# Round 5 (curator consolidation): LLM 巡检建议 —— 只产建议进台账，
# 不自动动文件；人工审阅后走既有 archive / draft-approve 流程。
# ---------------------------------------------------------------------------


@router.post("/skills/consolidation/scan")
async def scan_skill_consolidation(auto_draft: bool = True, mode: str = "full"):
    """Run an LLM consolidation scan over active skills.

    - 200 + ``{"suggestions": [...], "scanned": N, "drafts_created": M, "mode": ...}``
    - 503 — LLM provider 未装配（巡检不可用）

    Round 9: merge/revise 建议自动生成 SkillDraft（pending，进既有审批面，
    落盘仍需人工批准）；archive 建议仅提示（已有可逆 archive 流程）。
    ``auto_draft=false`` 退回仅建议模式。

    R28 增量巡检：``mode=auto`` 时以上次巡检水位（台账最近一条
    consolidation_note 的时间戳）为界，仅复审水位后有使用/台账事件的技能；
    无水位（从未巡检）自动退化为全量。缺省 ``mode=full`` 行为不变。
    """
    from backend.skills.consolidator import (
        collect_active_skills,
        collect_delta_names,
        collect_skill_docs,
        get_consolidation_service,
        last_scan_watermark,
    )
    from backend.skills.lifecycle import get_lifecycle_store

    service = get_consolidation_service()
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "type": "llm_unavailable",
                "message": "LLM provider not configured; consolidation scan unavailable",
            },
        )

    scan_mode = "auto" if mode == "auto" else "full"
    candidate_names: Optional[Set[str]] = None
    if scan_mode == "auto":
        watermark = last_scan_watermark()
        if watermark is not None:
            candidate_names = collect_delta_names(watermark)

    store = get_lifecycle_store()
    pinned = store.get_pinned_names()
    skills = collect_active_skills(names=candidate_names)
    suggestions = await service.scan(skills, pinned_names=sorted(pinned))

    # 建议落审计台账（append-only；每条建议一条 consolidation_note）
    from backend.skills.audit import get_skill_audit_log

    audit_log = get_skill_audit_log()
    for suggestion in suggestions:
        audit_log.record(
            "+".join(suggestion["skill_names"]),
            "consolidation_note",
            actor="system",
            after_content=json.dumps(suggestion, ensure_ascii=False),
            source="consolidation_scan",
        )

    drafts_created = 0
    if auto_draft and suggestions:
        from backend.skills.draft_store import get_skill_draft_store

        skill_docs = collect_skill_docs(
            sorted({n for s in suggestions for n in s.get("skill_names", [])})
        )
        drafts_created = await service.generate_drafts(
            suggestions,
            skill_docs,
            get_skill_draft_store(),
            source="consolidation_scan",
        )
    return {
        "suggestions": suggestions,
        "scanned": len(skills),
        "drafts_created": drafts_created,
        "mode": scan_mode,
    }


class ConsolidationAcceptRequest(BaseModel):
    """``POST /skills/consolidation/accept`` 请求体（Round 15）。"""

    skill_names: List[str]


@router.post("/skills/consolidation/accept")
@with_db_lock
def accept_consolidation_archive(data: ConsolidationAcceptRequest):
    """采纳 archive 类建议：批量归档指定技能（Round 15）。

    - 200 + ``{"archived": [...], "skipped_pinned": [...], "missing": [...]}``
    - 400 — skill_names 为空
    pinned 技能自动跳过并在 skipped_pinned 报告（不会静默归档）。
    merge/revise 类建议不走此端点（已有草稿审批面）。
    """
    from backend.skills.lifecycle import get_lifecycle_store

    if not data.skill_names:
        raise HTTPException(
            status_code=400,
            detail={"type": "empty_skill_names", "message": "skill_names is required"},
        )
    store = get_lifecycle_store()
    adapter = _get_skill_adapter()
    known = {e.get("name") for e in adapter.list_skills_extended()}
    pinned = store.get_pinned_names()

    archived: List[str] = []
    skipped_pinned: List[str] = []
    missing: List[str] = []
    for name in data.skill_names:
        if name not in known:
            missing.append(name)
        elif name in pinned:
            skipped_pinned.append(name)
        else:
            store.set_archived(name, True)
            archived.append(name)
    return {
        "archived": archived,
        "skipped_pinned": skipped_pinned,
        "missing": missing,
    }


@router.get("/skills/consolidation/suggestions")
def list_consolidation_suggestions(limit: int = 50):
    """List recorded consolidation suggestions (from the audit ledger)."""
    from backend.skills.audit import get_skill_audit_log

    entries = get_skill_audit_log().list_entries(limit=limit)
    suggestions = []
    for entry in entries:
        if entry["action"] != "consolidation_note":
            continue
        try:
            suggestions.append(
                {
                    "skill_names": entry["skill_name"].split("+"),
                    "suggestion": json.loads(entry.get("after_content") or "{}"),
                    "created_at": entry["created_at"],
                }
            )
        except (json.JSONDecodeError, TypeError):
            continue
    return {"suggestions": suggestions}


def _draft_to_dict(draft) -> dict:
    """Serialize a SkillDraft dataclass to a JSON-safe dict."""
    return {
        "id": draft.id,
        "name": draft.name,
        "description": draft.description,
        "when_to_use": draft.when_to_use,
        "content": draft.content,
        "trigger_type": draft.trigger_type,
        "source_session_id": draft.source_session_id,
        "source_context": draft.source_context,
        "status": draft.status,
        "created_at": draft.created_at,
    }



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
import logging
from typing import Any, Dict, List, Optional, Sequence, Set

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, StrictBool

from backend.api.settings_models import LegacySettingsPayload
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



logger = logging.getLogger(__name__)

from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由 with_db_lock 闭包解析
    _SQLITE_LOCK,
    make_with_db_lock,
)


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    D3 同款（镜像 orch_routes / legacy_memory_routes）：make_with_db_lock
    把 wrapper 的 __globals__ 重绑到本模块（FastAPI 字符串注解须在本模块
    解析，body 模型如 SkillToggleRequest），_SQLITE_LOCK 经 import 共享
    同一对象，与 legacy_routes 的锁语义一致。
    """
    return make_with_db_lock(globals())(func)


router = APIRouter()

# ==================== 技能 API (C1 第二刀，自 legacy_routes.py 迁出)=====
# ==================== 技能 API (PR-7) ====================

# 进程内单例缓存已搬到 ``backend.adapters.out.skill.inproc``（M2b 重构：
# 断开 tools -> api 的反向 import 链，修 import-linter 违规）。本模块只
# 保留一个 thin wrapper 委托到 ``inproc.get_singleton()``，保证 REST 路由
# 与 ``SkillTool`` 共享同一注册表状态（enabled / usage_count 等内存字段）。


def _get_skill_adapter():
    """委托到 ``inproc.get_singleton()``（M2b 重构）。

    返回的 adapter 与 ``backend.tools.skill_tool.SkillTool._resolve_adapter``
    共享同一缓存 — 即所有 REST 路由与 in-loop 工具调用看到同一份
    ``InprocSkillAdapter`` 实例（enabled / usage_count 一致）。
    """
    from backend.adapters.out.skill.inproc import get_singleton

    return get_singleton()


def _skill_to_dict(
    ext: dict, enabled: bool, usage_count: int, pinned: Optional[bool] = None
) -> dict:
    """把扩展 SkillSpec dict + 路由层 enabled/usage_count 序列化为响应 dict。

    ``ext`` 来自 ``InprocSkillAdapter.list_skills_extended()``,
    含 ``source / body / base_dir / version`` 等字段 (SKILL.md 时填充, builtin 时不存在)。

    ``pinned`` 传 None 时不透出（Round 17 管理面：列表/单技能响应统一带 pin 态）。

    复制一份避免修改 adapter 返回的共享 dict (immutable-ish 风格)。
    """
    out = dict(ext)
    out["enabled"] = enabled
    out["usage_count"] = usage_count
    if pinned is not None:
        out["pinned"] = pinned
    return out


def _get_pinned_names() -> Set[str]:
    """lifecycle store 的 pin 集合（惰性导入，缺表时 best-effort 返回空集）。"""
    try:
        from backend.skills.lifecycle import get_lifecycle_store

        return get_lifecycle_store().get_pinned_names()
    except Exception:
        return set()


@router.get("/skills")
@with_db_lock
def list_skills():
    """列出所有已注册技能 (含 disabled 与 usage_count + SKILL.md 扩展字段)。"""
    adapter = _get_skill_adapter()
    pinned_names = _get_pinned_names()
    return [
        _skill_to_dict(
            ext,
            adapter.is_enabled(ext["name"]),
            adapter.usage_count(ext["name"]),
            pinned=ext["name"] in pinned_names,
        )
        for ext in adapter.list_skills_extended()
    ]


class SkillToggle(BaseModel):
    """``POST /skills/{name}/toggle`` 请求体。"""

    enabled: StrictBool


@router.post("/skills/{name}/toggle")
@with_db_lock
def toggle_skill(name: str, data: SkillToggle):
    """启用 / 禁用技能 (PR-7)。

    - 200 + 完整 skill dict (含新 enabled)
    - 404 + 结构化 detail (技能名不存在)
    - 422 (FastAPI 自动) — enabled 缺失 / 类型错
    """
    adapter = _get_skill_adapter()
    if not adapter.set_enabled(name, data.enabled):
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": f"skill '{name}' not found"},
        )
    # 返回完整 skill dict (与 list 接口一致) —— 用 list_skills_extended 拿带 source/body 的版本
    ext = next((e for e in adapter.list_skills_extended() if e["name"] == name), None)
    assert ext is not None  # set_enabled 已 guard
    return _skill_to_dict(
        ext, adapter.is_enabled(name), adapter.usage_count(name), pinned=name in _get_pinned_names()
    )


class SkillArchive(BaseModel):
    """``POST /skills/{name}/archive`` 请求体。"""

    archived: StrictBool


@router.post("/skills/{name}/archive")
@with_db_lock
def archive_skill(name: str, data: SkillArchive):
    """归档 / 取消归档技能（软标记，可逆；区别于物理 delete）。

    - 200 + 完整 skill dict（含新 lifecycle）
    - 404 + 结构化 detail（技能名不存在）
    - 409 — 技能被 pin（Round 5: 钉住技能不参与归档）
    - 422（FastAPI 自动）— archived 缺失 / 类型错

    归档技能从 auto_activate / slash 候选排除（adapter 层），文件不动、可恢复。
    """
    # Round 5: pin 防归档 —— 钉住技能拒绝 archive=True 请求
    if data.archived:
        from backend.skills.lifecycle import get_lifecycle_store

        if get_lifecycle_store().is_pinned(name):
            raise HTTPException(
                status_code=409,
                detail={
                    "type": "skill_pinned",
                    "message": f"skill '{name}' is pinned; unpin before archiving",
                },
            )
    adapter = _get_skill_adapter()
    if not adapter.set_archived(name, data.archived):
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": f"skill '{name}' not found"},
        )
    # 返回完整 skill dict（与 toggle 一致）—— lifecycle 已由 list_skills_extended 注入
    ext = next((e for e in adapter.list_skills_extended() if e["name"] == name), None)
    assert ext is not None  # set_archived 已 guard
    return _skill_to_dict(
        ext, adapter.is_enabled(name), adapter.usage_count(name), pinned=name in _get_pinned_names()
    )


class SkillPinRequest(BaseModel):
    """``POST /skills/{name}/pin`` 请求体（Round 5）。"""

    pinned: bool


@router.post("/skills/{name}/pin")
@with_db_lock
def pin_skill(name: str, data: SkillPinRequest):
    """钉住 / 取消钉住技能（Round 5: 钉住后不可归档，巡检不给出 archive 建议）。

    - 200 + ``{"name": ..., "pinned": ...}``
    - 404 — 技能名不存在
    """
    from backend.skills.lifecycle import get_lifecycle_store

    store = get_lifecycle_store()
    if not store.is_pinned(name):
        # 未 pin 过的技能名也可能尚未注册 —— 校验技能存在于技能面
        # （adapter 层成员检查，无副作用），否则 404。
        adapter = _get_skill_adapter()
        if not any(e.get("name") == name for e in adapter.list_skills_extended()):
            raise HTTPException(
                status_code=404,
                detail={
                    "type": "skill_not_found",
                    "message": f"skill '{name}' not found",
                },
            )
    store.set_pinned(name, data.pinned)
    return {"name": name, "pinned": data.pinned}


class SkillExecuteRequest(BaseModel):
    """``POST /skills/{name}/execute`` 请求体。

    - action: 技能子动作(单动作 builtin 留空字符串即可)
    - args:   技能参数 (透传给 BaseSkill.execute)
    """

    action: str = ""
    args: dict = {}


@router.post("/skills/{name}/execute")
async def execute_skill(name: str, data: SkillExecuteRequest):
    """执行技能 (PR-7)。

    - 200 + SkillResult (success / content / metadata / error)
    - 404 + 结构化 detail (技能名不存在 — 资源不存在的标准 REST 语义)
    - 422 (FastAPI 自动) — args 类型错等
    - execute 内部失败(技能 disabled / builtin 工具不可用)→ 200 + success=False,
      **不抛 4xx/5xx**,由前端按 success 字段判定。
    """
    adapter = _get_skill_adapter()
    # 资源不存在 → 404 (与 disabled 走 200 + success=False 区分开)
    if not adapter.has_skill(name):
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": f"skill '{name}' not found"},
        )
    result = await adapter.execute(name, data.action, data.args)
    # 使用计数已由 adapter.execute() 成功路径自动 bump（含 DB 持久化）
    return {
        "success": result.success,
        "content": result.content,
        "metadata": result.metadata,
        "error": result.error,
    }


# ==================== M10: slash command 暴露 ====================


class SkillCommandRequest(BaseModel):
    """``POST /skills/command`` 请求体 (M10)。

    - command: slash command 名 (带或不带 ``/``,如 ``/review`` 或 ``review``)
    - args: 命令参数列表 (透传给 SkillMdSkill.execute_v2 params['args'])
    """

    command: str
    args: List[str] = []


@router.post("/skills/command")
async def execute_slash_command(data: SkillCommandRequest):
    """执行 slash command (M10)。

    - 200 + SkillResult (success / content / metadata / error)
      - success=True → content 是 SKILL.md body,供聊天层注入 system prompt
      - success=False → 内部执行失败(脚本异常等),前端按 success 字段判定
    - 404 + 结构化 detail — command 未注册 (无 user_invocable 技能匹配)
    - 422 (FastAPI 自动) — command 缺失或类型错

    设计: chat 层剥离 ``/`` 前缀后 POST 此端点;不需要再走 SkillRegistry.exists()
    (slash registry 本身就是 user_invocable 技能的子集,索引已构建完成)。
    """
    adapter = _get_skill_adapter()
    try:
        result = await adapter.execute_command(data.command, data.args)
    except LookupError as exc:
        # 命令未注册 → 404 (与 skill_not_found 语义一致)
        raise HTTPException(
            status_code=404,
            detail={"type": "command_not_found", "message": str(exc)},
        ) from exc
    return {
        "success": result.success,
        "content": result.content,
        "metadata": result.metadata,
        "error": result.error,
    }


@router.get("/skills/commands")
@with_db_lock
def list_slash_commands():
    """列出所有已注册的 slash command (M10)。

    用于前端自动补全 / chat 输入提示。
    返回命令名列表 (带 ``/`` 前缀,如 ``["/review", "/commit"]``)。
    """
    adapter = _get_skill_adapter()
    return {"commands": adapter.list_slash_commands()}


# ========== PR-A: Skills management - 物理删除 SKILL.md ==========


@router.post("/skills/{name}/delete")
@with_db_lock
def delete_skill(name: str):
    """物理删除一个 SKILL.md 技能 (用户主动管理, PR-A Task 3)。

    - 200 + ``{"deleted": true, "name": ..., "base_dir": "."}``
    - 400 + stable detail: builtin 不可删 / name 非法 / base_dir 跑出
      SAGE_SKILLS_DIR
    - 404 + stable detail: skill 不存在 (registry 或磁盘)
    - 500 + stable detail: SAGE_SKILLS_DIR 未配置 / 其他文件系统错误
    """
    # 延迟导入避免循环 (legacy_routes → inproc → delete → registry → builtin)
    from backend.skills.skill_md.delete import (
        BuiltinSkillError,
        SkillMdNotFoundError,
    )

    adapter = _get_skill_adapter()
    try:
        result = adapter.delete_skill_md(name)
    except BuiltinSkillError as exc:
        logger.warning("skill delete rejected: type=%s name=%s", type(exc).__name__, name)
        raise HTTPException(
            status_code=400,
            detail={"type": "builtin_skill", "message": "内置技能不可删除"},
        ) from exc
    except SkillMdNotFoundError as exc:
        logger.info("skill delete not found: name=%s", name)
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": "技能不存在"},
        ) from exc
    except ValueError as exc:
        # name 非法 / base_dir 跑出 SAGE_SKILLS_DIR; keep diagnostics server-side.
        logger.warning("skill delete invalid request: name=%s error=%s", name, exc)
        raise HTTPException(
            status_code=400,
            detail={"type": "invalid_skill_request", "message": "技能请求无效"},
        ) from exc
    except FileNotFoundError as exc:
        # SAGE_SKILLS_DIR 未配置 / 其他 fs 错误; keep diagnostics server-side.
        logger.error("skill delete storage unavailable: name=%s error=%s", name, exc)
        raise HTTPException(
            status_code=500,
            detail={"type": "skills_storage_unavailable", "message": "技能目录不可用"},
        ) from exc
    return result


# ========== PR-C: Skills load-new (rescan + import) ==========


@router.post("/skills/rescan")
@with_db_lock
def rescan_skills():
    """重扫 SAGE_SKILLS_DIR / ~/.sage/skills / ./skills, 增量加载新 SKILL.md。

    - 200 + ``{"loaded": [{"name", "source", "path"}], "skipped": [...], "total_loaded": int}``
    - 不抛 4xx/5xx (内部失败 → 500 via FastAPI 默认, 但 adapter 层已 try/except)
    """
    adapter = _get_skill_adapter()
    return adapter.rescan_skill_mds()


@router.post("/skills/import")
async def import_skills(files: List[UploadFile] = File(default=[])):
    """导入 SKILL.md 文件 (multipart)。

    - 200 + ``{"imported": [{"name", "path": "."}], "skipped": [{"name", "reason"}]}``
    - 400 + detail: multipart 没 files (空列表)
    - 500 + detail: skills_dir 无法创建 (NoSkillsDirError)

    partial success 策略: 即使部分文件失败, HTTP 仍 200, 在 skipped 数组中报告。
    """
    if not files:
        raise HTTPException(
            status_code=400,
            detail={"type": "invalid_request", "message": "no files provided"},
        )

    from backend.skills.skill_md.exceptions import NoSkillsDirError

    adapter = _get_skill_adapter()
    try:
        result = await adapter.import_skill_mds(files)
    except NoSkillsDirError as exc:
        logger.error("skill import unavailable: error_type=%s", type(exc).__name__)
        raise HTTPException(
            status_code=500,
            detail={"type": "no_skills_dir", "message": "技能目录不可用"},
        ) from exc

    return result


# ==================== Settings & Preferences API ====================
#
# 这些端点在 hex_routes 中也有定义。legacy 模式下 hex_routes 不注册，
# 但 Electron 前端需要 /settings 和 /preferences/{key} 来加载配置，
# 因此在 legacy_routes 中也提供，确保两种 API_MODE 下都能工作。


# Task 1 round 1 (2026-08-24): LegacySettingsRequest → ``backend.api.settings_models.LegacySettingsPayload``.
# 原因:
# - Pydantic 1/2 双兼容 (``class Config`` 在两边都生效)
# - 强类型 ``endpoints: List[EndpointPayload]`` 而非 ``List[dict]`` (canonicalizer
#   兜底嵌套; 旧客户端不传 endpoints 不受影响, 因为 Optional)
# - 时区 / 协议 / 本地路径校验**下沉**到 canonicalizer.validate_settings_payload,
#   不再用 ``field_validator`` 装饰器 (Pydantic 2 语法在 Pydantic 1 / Win7 不可用).
# 取别名 ``LegacySettingsRequest`` 保持 legacy_routes 下游不动, 避免改动面爆炸.
LegacySettingsRequest = LegacySettingsPayload


class LegacySettingsResponse(BaseModel):
    """PUT /settings 响应体。"""

    status: str = "ok"
    changed_fields: List[str] = []


class LegacyPreferenceItem(BaseModel):
    """GET/PUT /preferences/{key} 请求/响应体。"""

    value: Optional[str] = None

    value_type: str = "string"
    category: str = "general"



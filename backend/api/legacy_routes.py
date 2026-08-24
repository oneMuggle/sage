# ruff: noqa: UP006, UP007, UP035 — pydantic v1 + Python 3.8 兼容：
# pydantic v1 resolve_annotations 用 eval() 处理 forward refs，
# eval 在 Python 3.8 上无法解析 PEP 585 (list[X]) 和 PEP 604 (X | Y)，
# 所以本文件保留 typing.List/Optional/Union 写法
"""
API 路由定义
"""

from __future__ import annotations

import asyncio
from typing import List

# I5: 流式视觉延迟 — DONE 事件的 content 拆成 chunk 逐个入队,
# 让前端能逐字渲染 (避免 LLM 一次返回完整字符串时 "砰一下" 全显示)。
# 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls (大改),
# 先用这个 producer 端的 fake stream 解决 90% 的视觉体验。
_STREAMING_CHUNK_SIZE = 6
_STREAMING_CHUNK_DELAY_S = 0.04
import json
import logging
import time
import uuid
from typing import Any, Dict, Optional, Set, Union

from fastapi import APIRouter, Body, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, StrictBool

from backend.api.chat_stream_registry import SENTINEL, StreamEntry, StreamRegistry
from backend.api.orch_routes import router as orch_routes_router
from backend.chat.compaction import (
    MIN_COMPACT_MESSAGE_COUNT,
    CompactionError,
    compact_messages,
    should_compact,
)
from backend.chat.executors import resolve_attachments
from backend.core.errors import LLMError
from backend.core.legacy.agent import SageAgent
from backend.data.database import get_database
from backend.data.session_repo import (
    ForkSourceNotFoundError,
    Message as DbMessage,
    MessageRepository,
    SessionRepository,
    fork_session as fork_session_core,
)
from backend.memory import get_memory_manager
from backend.office.chat_refs import ChatOfficeRef, authorize_chat_office_request
from backend.office.workspace_errors import (
    WorkspaceDocumentNotFoundError,
    WorkspaceNotBoundError,
    WorkspacePathMismatchError,
    WorkspaceSessionNotFoundError,
)
from backend.orchestration.chat_dispatcher import (
    ChatDispatcher,
    _classify_orchestration_mode,
)
from backend.orchestration.orch_settings import load_orch_settings
from backend.scheduler import get_evolution_logs
from backend.skills.draft_store import get_skill_draft_store
from backend.skills.loader import get_skill_loader
from backend.skills.review_queue import get_review_queue

logger = logging.getLogger(__name__)

router = APIRouter()


# §1.2 修复（PR #294）配套：全局 SQLite 串行化锁。
#
# Why: 34 个 `async def` handler 降级为 `def` 后，FastAPI 自动把它们 dispatch 到 anyio
# threadpool（默认 40 worker 线程）。`backend/data/database.py` 维护**单例**
# `sqlite3.Connection(check_same_thread=False)`，多线程并发访问同一连接会触发
# `cannot start a transaction within a transaction` 异常（实测，30 并发 session POST
# 即触发）。`busy_timeout=5000` 只能吸收 SQLITE_BUSY 锁冲突，不能吸收应用层事务嵌套错误。
#
# How: 用一个模块级 `threading.Lock` 串行化所有走 `_db._connection` 的写操作。锁
# 在 threadpool worker 线程内等待，**不阻塞事件循环**（事件循环的 SSE/chat handler
# 仍能持续响应）。这把"事件循环上串行跑 sync"语义平移到了"threadpool 上串行跑 sync"，
# 既修了 §1.2 阻塞问题，又避开单连接多线程冲突。
#
# Future: 计划在 PR B 把单连接拆成 thread-local connection pool（每 thread 一个
# sqlite3.Connection），那时可移除本锁。详见 `docs/plans/2026-08-09_*.md` §1.2。
import functools

# PR B §1.2 (CRITICAL fix): 共用 backend.data.database._SQLITE_LOCK,
# 而不是本模块私有的 threading.Lock。PR B 的 SqliteStorageAdapter._sync_X
# 在 to_thread worker 内获取同一把锁,两条路径才能在同一 sqlite3.Connection
# (check_same_thread=False) 上互斥,避免 "cannot start a transaction within
# a transaction"。
#
# 注意:with_db_lock 必须定义在本模块(而非 database.py)。FastAPI 在
# get_typed_signature 里用 ``call.__globals__`` 解析 `from __future__ import
# annotations` 产生的字符串注解(wrapper.__globals__ 是**定义装饰器的模块**
# 的 dict)。若 decorator 定义在 database.py,本文件 34 个带 body 模型的
# handler(ChatRequest 等)会报 PydanticUndefinedAnnotation。orch_routes.py
# 因此也保留同构的本地定义,共用同一把 _SQLITE_LOCK。
from backend.data.database import _SQLITE_LOCK


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    适用对象：34 个降级为 `def` 的 FastAPI handler —— 它们跑在 anyio threadpool,
    内部 `SessionRepository`/`MessageRepository` 等 sync 调用必须串行访问单连接。
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        with _SQLITE_LOCK:
            return func(*args, **kwargs)

    return wrapper


def _safe_log_field(value: object, max_length: int = 64) -> str:
    """Sanitize a user-controlled field for safe logging.

    - Strip newlines and control chars to prevent log injection
    - Truncate to max_length to prevent log spam
    """
    s = str(value)
    s = "".join(c for c in s if c.isprintable() or c == " ")
    return s[:max_length]


# ==================== Pydantic 模型 ====================


class SessionCreate(BaseModel):
    title: str = "新对话"
    parent_id: Optional[str] = None


class SessionUpdate(BaseModel):
    title: Optional[str] = None

    is_pinned: Optional[bool] = None


class ChatRequest(BaseModel):
    session_id: str
    message: str
    workspace_path: Optional[str] = None
    # 2026-07-30: 选 agent 的入口。None / 空字符串 → 端点 fallback 到 "primary"。
    # 真正的路由由 SageAgent(agent_id=...) 内部完成:从 SQLite 读 profile,
    # 透传到 get_available_tools → ToolRegistry.get_schemas_for_llm(allowed_tools=...)
    # 这样 memory_manager 之类的窄权限 agent 不会拿到 list_dir/read_file。
    agent_id: Optional[str] = None
    api_key: Optional[str] = None

    api_url: Optional[str] = None

    model: Optional[str] = None

    max_context: Optional[int] = None

    temperature: Optional[float] = None

    # 透传字段:provider 让后端不再硬写,reasoning_effort/thinking_budget
    # 让上游 LLM 启用 thinking 输出(provider 决定哪种 key 会被接受)
    # - provider: openai / claude / gemini / deepseek / ollama / custom
    # - reasoning_effort: OpenAI o1/o3/5 + DeepSeek OpenAI 兼容代理
    # - thinking_budget: Gemini 2.5 OpenAI 兼容模式
    provider: Optional[str] = None

    reasoning_effort: Optional[str] = None

    thinking_budget: Optional[int] = None

    # Task 6 (M1-M2 chat-read): frontend 把 @mention 解析成
    # ``backend.office.chat_refs.ChatOfficeRef`` 列表,``chat_stream_create``
    # 在调 LLM 前同步授权. 空列表 = legacy 路径(attachment_resolver).
    # 用 forward ref 避免 route→domain 循环导入; ``model_rebuild`` 在
    # legacy_routes 模块加载完毕时自动被 Pydantic v2 调用.
    office_refs: List[ChatOfficeRef] = Field(default_factory=list)

    # Multi-Agent Orchestration (spec 2026-08-11): 编排模式开关。
    # auto（默认）—— 轻量 LLM 二分类决定；force_multi / force_single ——
    # 用户斜杠命令 /orchestrate / /single 覆盖，跳过语义判定。
    # Optional: 兼容渲染进程 IPC payload 里显式 null(undefined ?? null 序列化的产物)。
    # Pydantic 默认值只在字段缺失时生效，显式 null 仍按类型校验 →
    # 不加 Optional 会被 422 拒绝。业务层 `data.orchestration_mode or "auto"` 已兜底。
    orchestration_mode: Optional[str] = "auto"

    # Wave 3 A10 (2026-08-14): resume 恢复流 —— plan_override 非空时跳过 LLM
    # 拆解，直接用存储计划建 dispatcher；run_id 复用 resume 返回的 new_run_id。
    plan_override: Optional[List[Dict[str, Any]]] = None
    run_id: Optional[str] = None


class MessageResponse(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    created_at: int
    model: Optional[str] = None

    tool_calls: Optional[str] = None


class ChatErrorInfo(BaseModel):
    """结构化的 /chat 错误信息。

    字段与 LLMError.to_dict() 对齐，便于前端统一处理。
    """

    type: str
    message: str
    status_code: Optional[int] = None

    retry_after: Optional[int] = None


class ChatResponse(BaseModel):
    """聊天响应：成功时含 message+session，失败时含 error+null message。"""

    message: Optional[MessageResponse] = None

    session: Optional[dict] = None

    error: Optional[ChatErrorInfo] = None


class EvolutionLogResponse(BaseModel):
    """进化日志响应"""

    id: str
    evolution_type: str
    description: str
    before_state: Optional[str] = None

    after_state: Optional[str] = None

    trigger_type: str
    trigger_condition: Optional[str] = None

    status: str
    error_message: Optional[str] = None

    tokens_used: Optional[int] = None

    created_at: int
    completed_at: Optional[int] = None


#: agent role 白名单（PATCH/POST 共用）。
_VALID_AGENT_ROLES = {
    "coordinator",
    "researcher",
    "coder",
    "memory_manager",
    "writer",
    "reviewer",
}


class AgentToggle(BaseModel):
    """PATCH /agents/{id}/toggle 请求体 (PR-5)。

    单字段 ``enabled`` 必填 — 缺失走 Pydantic 自动 422。专门用来对
    enable/disable 这一高频操作做语义化端点 (审计 + 未来权限),不
    与 PATCH /agents/{id} 重叠。

    注: 用 ``StrictBool`` 而非 ``bool`` — Pydantic v2 默认 lax 模式会把
    "yes"/"1"/1 等强转 True, 在 API 边界宁可 422 也不要静默转换。前端
    Type[Script 永远传真 bool, 严格模式不会误伤。
    """

    enabled: StrictBool


class AgentUpdate(BaseModel):
    """PATCH /agents/{id} 请求体 (PR-4)。

    所有字段可选 — 不传视为"该字段不更新"。role / max_iterations
    走 Pydantic 校验, 非法值 422 (由 FastAPI 自动处理)。
    """

    # 注: Pydantic v2 默认对 "model_" 前缀的字段名有保留命名空间保护.
    # 我们在类内用 model_config 字段, 通过 ConfigDict 关掉该保护.
    model_config = {"protected_namespaces": ()}

    name: Optional[str] = None

    role: Union[str, None] = None  # 校验放在路由层 (依赖 Pydantic Literal 不直观)

    system_prompt: Optional[str] = None

    tools: Optional[List[str]] = None

    memory_access: Optional[List[str]] = None

    model_config_data: Union[dict, None] = (
        None  # 字段名避开 Pydantic 保留名, 路由层映射到 model_config
    )

    max_iterations: Optional[int] = None  # 路由层校验 1..50

    enabled: Optional[bool] = None

    description: Optional[str] = None


class AgentCreate(BaseModel):
    """POST /agents 请求体（US-4 角色可扩展）。

    id / name 必填；其余字段带默认值。
    ``model_config_data`` 字段名避开 Pydantic 保留名（同 AgentUpdate）。
    """

    model_config = {"protected_namespaces": ()}

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    name: str = Field(min_length=1, max_length=64)
    role: str = "general"
    system_prompt: str = ""
    tools: Optional[List[str]] = None
    memory_access: Optional[List[str]] = None
    model_config_data: Optional[dict] = None
    max_iterations: Optional[int] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None


# ==================== 依赖注入 ====================


def get_session_repo() -> SessionRepository:
    return SessionRepository()


# P0-2 (2026-08-20): stream_id → 本流真实运行实例。旧 /interrupt 用
# Depends(get_agent) 每次新建空实例，中断信号永远到不了 producer 里
# 正在跑的 agent。producer 在 run_loop 前登记、finally 注销。
_ACTIVE_STREAMS: Dict[str, Dict[str, Any]] = {}
_PENDING_RUN_CANCELLATIONS: Set[str] = set()


class InterruptRequest(BaseModel):
    """/interrupt 请求体 —— stream_id 可选，兼容不带 body 的旧调用方。"""

    stream_id: Optional[str] = None


def interrupt_stream(stream_id: Optional[str]) -> str:
    """中断目标流：主 agent interrupt（+ multi 模式 cancel dispatcher）。

    返回命中标识（"stream"/"none"）供端点回传与测试断言。
    纯内存注册表操作，不依赖 DB。
    """
    if not stream_id:
        return "none"
    entry = _ACTIVE_STREAMS.get(stream_id)
    if entry is None:
        return "none"
    entry["cancelled"] = True
    agent_obj: SageAgent = entry["agent"]
    agent_obj.interrupt()
    run_id = entry.get("run_id")
    if run_id:
        from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

        dispatcher = entry.get("dispatcher") or _ACTIVE_DISPATCHERS.get(run_id)
        if dispatcher is not None:
            dispatcher.cancel()
    return "stream"


def interrupt_run(run_id: str) -> str:
    """Cancel every active stream belonging to an orchestration run.

    If planning has not bound the run id to its stream yet, retain a pending
    cancellation token.  The producer consumes it when the dispatcher binds.
    """
    matched = False
    for entry in list(_ACTIVE_STREAMS.values()):
        if entry.get("run_id") != run_id:
            continue
        matched = True
        entry["cancelled"] = True
        agent_obj: SageAgent = entry["agent"]
        agent_obj.interrupt()
        dispatcher = entry.get("dispatcher")
        if dispatcher is None:
            from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

            dispatcher = _ACTIVE_DISPATCHERS.get(run_id)
        if dispatcher is not None:
            dispatcher.cancel()
    if not matched:
        # P2-9 兼容回退：run 级 cancel 在无 stream entry 时仍直接命中
        # dispatcher 注册表（如 resume 流或仅注册 dispatcher 的场景）。
        from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS

        if _ACTIVE_DISPATCHERS.get(run_id) is not None:
            _ACTIVE_DISPATCHERS[run_id].cancel()
            return "stream"
        _PENDING_RUN_CANCELLATIONS.add(run_id)
    return "stream" if matched else "pending"


def _finalize_orch_run(
    run_id: Optional[str], status: str, final_summary: Optional[str]
) -> None:
    """P0-4 (2026-08-20): orch run 生命周期闭环（降级型）。

    此前 OrchRunRepository.finalize 生产路径零调用者，orch_runs 永远
    停留 "running"。single 路径 run_id=None 直接跳过。
    """
    if not run_id:
        return
    try:
        from backend.data.orch_run_repo import OrchRunRepository

        OrchRunRepository().finalize(run_id, status, final_summary)
    except Exception as exc:  # noqa: BLE001 — 闭环失败不影响主流
        logger.warning("orch run finalize 失败 (%s): %s", run_id, exc)


def _build_orchestration_dispatcher(
    *,
    stream_id: str,
    entry_queue: Any,
    run_id: str,
    llm_config: Optional[Dict[str, Any]],
    total_tasks: Optional[int],
    workspace_root: Optional[str],
) -> ChatDispatcher:
    """构造 ChatDispatcher；非法 run_id 的 ValueError 重抛为前端可读文案。

    ChatDispatcher.__init__ 对 run_id 做白名单 fullmatch（防路径穿越/非法
    字符），非法值抛 ``ValueError(f"非法 run_id: {run_id!r}")`` —— 原始串含
    repr 与英文，直接透传给前端不可读。这里只改写文案：**拒绝语义保留**，
    不吞错、不降级 single（非法 run_id 是客户端 bug，应显式失败提示刷新，
    而非用"单机模式"掩盖）。
    """
    try:
        return ChatDispatcher(
            stream_id=stream_id,
            entry_queue=entry_queue,
            run_id=run_id,
            llm_config=llm_config,
            total_tasks=total_tasks,
            settings=load_orch_settings(),
            workspace_root=workspace_root,
        )
    except ValueError as exc:
        raise ValueError(
            "编排启动失败：run_id 格式非法（应为 orch-* 标识符），"
            f"请刷新后重试。原始信息: {exc}"
        ) from exc


def get_agent() -> SageAgent:
    return SageAgent()


# ==================== 会话 API ====================


@router.post("/sessions", response_model=dict)
@with_db_lock
def create_session(data: SessionCreate, repo: SessionRepository = Depends(get_session_repo)):
    """创建新会话"""
    session = repo.create(title=data.title, parent_id=data.parent_id)
    return session.to_dict()


@router.get("/sessions", response_model=List[dict])
@with_db_lock
def list_sessions(
    limit: int = 100, offset: int = 0, repo: SessionRepository = Depends(get_session_repo)
):
    """获取会话列表"""
    sessions = repo.list(limit=limit, offset=offset)
    return [s.to_dict() for s in sessions]


@router.get("/sessions/{session_id}", response_model=dict)
@with_db_lock
def get_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """获取单个会话"""
    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.patch("/sessions/{session_id}", response_model=dict)
@with_db_lock
def update_session(
    session_id: str, data: SessionUpdate, repo: SessionRepository = Depends(get_session_repo)
):
    """更新会话"""
    update_data = {}
    if data.title is not None:
        update_data["title"] = data.title
    if data.is_pinned is not None:
        update_data["is_pinned"] = 1 if data.is_pinned else 0

    if update_data:
        repo.update(session_id, **update_data)

    session = repo.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    return session.to_dict()


@router.delete("/sessions/{session_id}")
@with_db_lock
def delete_session(session_id: str, repo: SessionRepository = Depends(get_session_repo)):
    """删除会话"""
    if not repo.delete(session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"status": "ok"}


# ==================== 会话压缩 / 分叉 API (M4) ====================
#
# 压缩逻辑本体在 backend/chat/compaction.py（对 DB 纯净，便于单测）；
# 本节只负责装配 LLM 客户端 + 落盘编排。


def _build_compaction_llm_callable():
    """从持久化的 app_settings 装配压缩摘要用的 LLM complete 回调。

    解析顺序: modelSelections.chatModel → 对应 endpoint 的 baseUrl/apiKey。
    chatModel 未选择 endpoint 时回退到第一个配置完整的 endpoint（桌面端
    单 endpoint 场景的务实兜底）。

    Returns:
        ``LLMClient.complete`` 协程函数；无可用配置时返回 ``None``。
    """
    from backend.data.settings_repo import SettingsRepository

    try:
        settings = SettingsRepository().get_json("app_settings")
    except (ValueError, TypeError):
        settings = None
    if not isinstance(settings, dict):
        return None

    selections = settings.get("modelSelections") or {}
    chat_sel = selections.get("chatModel") or {}
    endpoints = settings.get("endpoints") or []

    def _is_complete(ep: Any) -> bool:
        return isinstance(ep, dict) and bool(ep.get("baseUrl")) and bool(ep.get("apiKey"))

    endpoint = next(
        (ep for ep in endpoints if isinstance(ep, dict) and ep.get("id") == chat_sel.get("endpointId")),
        None,
    )
    if (endpoint is None or not _is_complete(endpoint)) and endpoints:
        fallback = next((ep for ep in endpoints if _is_complete(ep)), None)
        if fallback is not None:
            logger.info(
                "[M4] compact: chatModel endpoint 不可用, 回退到 endpoint id=%s",
                _safe_log_field(fallback.get("id")),
            )
            endpoint = fallback
    if not _is_complete(endpoint):
        return None

    from backend.core.legacy.llm_client import LLMClient, LLMConfig

    client = LLMClient(
        LLMConfig(
            provider="custom",
            api_key=endpoint["apiKey"],
            base_url=endpoint["baseUrl"],
            model=chat_sel.get("modelId") or "gpt-3.5-turbo",
            temperature=0.3,
        )
    )
    return client.complete


def _persist_compaction(
    session_id: str,
    messages: List[DbMessage],
    new_messages: List[Any],
    removed_count: int,
) -> int:
    """把压缩结果落盘：删除被摘要替代的消息行 + 插入续接消息 + 更新计数。

    CRITICAL-1: 全部动作经 ``MessageRepository.replace_prefix_with_continuation``
    在**单事务**中完成——旧流程逐条自动提交，若在"删完历史"与"写入摘要"
    之间崩溃会永久丢失历史且没有摘要兜底；现在任何一步失败整体回滚。

    续接消息的 created_at 取第一条保留消息的时间戳 -1ms，保证
    ORDER BY created_at ASC 下排在保留尾部之前、旧消息之后的位置。

    Args:
        session_id: 目标会话
        messages: 压缩前的完整消息列表（升序，来自同一快照）
        new_messages: compact_messages 返回的新列表（首元素为续接 dict）
        removed_count: 被替代的消息数（= messages 前缀长度）

    Returns:
        压缩后的消息总数

    Raises:
        Exception: 落盘事务失败时抛出（DB 已回滚，保持压缩前状态）。
    """
    summary = new_messages[0]
    first_kept = messages[removed_count] if len(messages) > removed_count else None
    created_at = (first_kept.created_at - 1) if first_kept is not None else int(time.time() * 1000)
    continuation = DbMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=summary["role"],
        content=summary["content"],
        created_at=created_at,
    )

    after = len(new_messages)
    MessageRepository().replace_prefix_with_continuation(
        session_id,
        [stale.id for stale in messages[:removed_count]],
        continuation,
        after,
    )
    # WS-C P0-3: 压缩失效点 — 压缩事务提交后, 通知 hex 路径 ChatService
    # 实例失效该 session 的 system prompt 快照 (下一轮 run_turn 重建)。
    # _persist_compaction 是自动 / 手动压缩共用的唯一落盘出口, 挂这里
    # 一条代码路径覆盖两者。best-effort: 失败只记日志, 不影响压缩结果。
    try:
        from backend.application.services.chat_service import invalidate_session_snapshot

        invalidate_session_snapshot(session_id)
    except Exception as exc:
        logger.warning(
            "[M4] session=%s 压缩快照失效失败(忽略): %s",
            _safe_log_field(session_id),
            exc,
        )
    return after


async def _maybe_auto_compact_session(session_id: str, llm_config: Optional[dict]) -> None:
    """聊天请求层的自动压缩钩子（M4）。

    在 run_loop 之前检查会话历史：达到压缩阈值时先压缩再继续。
    LLM 客户端优先用本次请求自带的 llm_config（与聊天同配置），
    缺省时回退到 app_settings 里的持久化配置。

    已知限制（review HIGH-1）：当前 legacy chat producer 只组装
    ``[system, attachments?, user]`` 交给 run_loop，**尚未注入持久化历史**，
    因此自动压缩的实际收益 = 持久化存储有界 + UI / fork 健全性；
    **每轮 LLM token 节省要等聊天路径开始把持久化历史喂给 run_loop
    才会生效**（跟进标记见 docs/plans/2026-07-29_session-compact-fork-m4.md
    §6「已知限制」）。

    本函数**可以抛 CompactionError / 其他异常**——调用方（producer）
    统一 try/except：压缩失败只记日志，绝不阻塞聊天。
    """
    message_repo = MessageRepository()
    messages = message_repo.get_by_session(session_id, limit=100000)
    if not should_compact(messages):
        return

    if llm_config:
        from backend.core.legacy.llm_client import LLMClient, LLMConfig

        llm_complete = LLMClient(LLMConfig(**llm_config)).complete
    else:
        llm_complete = _build_compaction_llm_callable()
    if llm_complete is None:
        logger.info(
            "[M4] session=%s 达到压缩阈值但无 LLM 配置, 跳过自动压缩",
            _safe_log_field(session_id),
        )
        return

    new_messages, removed_count = await compact_messages(messages, llm_complete)
    after = _persist_compaction(session_id, messages, new_messages, removed_count)
    logger.info(
        "[M4] session=%s 自动压缩完成: removed=%s after=%s",
        _safe_log_field(session_id),
        removed_count,
        after,
    )


# ===== WS-C P0-2: 统一记忆写入路径 (legacy /chat/stream) =====
async def _extract_legacy_chat_memory(
    request_id: str,
    session_id: str,
    user_text: str,
    assistant_text: str,
) -> None:
    """legacy /chat/stream 在 assistant 消息落盘后 best-effort 提取记忆。

    记忆提取异步化：本函数只做廉价装配（读 autoMemory 开关、构建
    MemoryAdapter / MemoryExtractor），然后把耗时的 LLM 提取投递到
    后台队列（``get_memory_extraction_queue().submit``），由单 worker
    串行消费，不阻塞流式请求收尾。

    - 开关：读 app_settings.autoMemory, 缺省 True（与前端 defaultSettings
      及 hex 路径"有 memory 即写"的现行行为一致）。
    - 实例：get_memory_manager() 全局单例 + MemoryAdapter 包装（与
      main.py hex 装配方式一致）；提取 LLM 复用 HttpxLLMAdapter,
      调用失败时 MemoryExtractor 内部降级为关键词提取。
    - 函数保持 async 签名（调用点 await 不变），但 submit 非阻塞,
      装配完立即返回。
    - 任何异常只 warning 绝不外抛——记忆写入不得影响已完成的流式响应。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        settings = SettingsRepository().get_json("app_settings")
        enabled = True
        if isinstance(settings, dict):
            enabled = bool(settings.get("autoMemory", True))
        if not enabled:
            return

        from backend.adapters.out.llm.httpx_adapter import HttpxLLMAdapter
        from backend.adapters.out.memory.adapter import MemoryAdapter
        from backend.memory.async_extractor import (
            ExtractionRequest,
            get_memory_extraction_queue,
        )
        from backend.memory.extractor import MemoryExtractor

        # 记忆提取异步化：廉价装配（读设置/建 adapter）仍在本函数内完成，
        # 仅把耗时的 LLM 提取投递到后台队列，不阻塞流式请求收尾。
        get_memory_extraction_queue().submit(
            ExtractionRequest(
                memory_port=MemoryAdapter(get_memory_manager()),
                extractor=MemoryExtractor(llm_client=HttpxLLMAdapter()),
                user_text=user_text,
                assistant_text=assistant_text,
                session_id=session_id,
                enabled=True,
            )
        )
    except Exception as exc:
        logger.warning(
            f"[REQ {request_id}] legacy 记忆提取失败(忽略, 不影响聊天): {exc}"
        )
# ===== WS-C P0-2 END =====


# 进程内重入护栏（MEDIUM-1 后端兜底）：同一会话并发手动压缩时，两者都会在
# 对方落盘前通过 should_compact 检查，导致续接消息行重复写入。前端
# isLoading 守卫是第一道防线，这里是便宜的第二道。
_compact_in_progress: Set[str] = set()


@router.post("/sessions/{session_id}/compact", response_model=dict)
async def compact_session(session_id: str):
    """手动压缩会话上下文（M4，对应前端 /compact slash action）。

    - 200 + ``{"ok": true, "compacted": true, "before", "after", "removed"}``
    - 200 + ``{"ok": true, "compacted": false, "reason", ...}`` — 低于压缩
      地板（消息数 < 12 或 token 未达阈值），DB 不动
    - 404 — 会话不存在
    - 409 + ``{"ok": false, "error": "compact_in_progress"}`` — 同会话压缩
      正在进行（重复触发）
    - 502 + ``{"ok": false, "error"}`` — 无 LLM 配置 / 摘要失败 / 落盘失败，
      DB 不动（落盘走单事务，失败整体回滚）
    """
    session_repo = SessionRepository()
    if session_repo.get(session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")

    message_repo = MessageRepository()
    messages = message_repo.get_by_session(session_id, limit=100000)
    before = len(messages)

    if not should_compact(messages):
        reason = (
            "below_message_floor"
            if before < MIN_COMPACT_MESSAGE_COUNT
            else "below_token_threshold"
        )
        return {
            "ok": True,
            "compacted": False,
            "reason": reason,
            "before": before,
            "after": before,
            "removed": 0,
        }

    if session_id in _compact_in_progress:
        return JSONResponse(
            status_code=409,
            content={
                "ok": False,
                "error": "compact_in_progress",
                "message": "该会话正在压缩中，请勿重复触发",
            },
        )

    llm_complete = _build_compaction_llm_callable()
    if llm_complete is None:
        return JSONResponse(
            status_code=502,
            content={
                "ok": False,
                "error": "llm_not_configured",
                "message": "没有可用的 LLM 配置，无法生成压缩摘要",
            },
        )

    _compact_in_progress.add(session_id)
    try:
        try:
            new_messages, removed_count = await compact_messages(messages, llm_complete)
        except CompactionError as exc:
            logger.warning(
                "[M4] compact session=%s 失败(DB 未改动): %s", _safe_log_field(session_id), exc
            )
            return JSONResponse(
                status_code=502,
                content={"ok": False, "error": "compaction_failed", "message": str(exc)},
            )

        try:
            after = _persist_compaction(session_id, messages, new_messages, removed_count)
        except Exception as exc:
            # 单事务已回滚——DB 保持压缩前状态（CRITICAL-1 的核心保证）。
            logger.warning(
                "[M4] compact session=%s 落盘失败(事务已回滚, DB 未改动): %s",
                _safe_log_field(session_id),
                exc,
            )
            return JSONResponse(
                status_code=502,
                content={
                    "ok": False,
                    "error": "persist_failed",
                    "message": "压缩结果落盘失败，数据库未改动",
                },
            )
    finally:
        _compact_in_progress.discard(session_id)

    logger.info(
        "[M4] compact session=%s 完成: before=%s after=%s removed=%s",
        _safe_log_field(session_id),
        before,
        after,
        removed_count,
    )
    return {"ok": True, "compacted": True, "before": before, "after": after, "removed": removed_count}


class ForkSessionRequest(BaseModel):
    """POST /sessions/{session_id}/fork 请求体。"""

    at_message_id: Optional[str] = None
    title: Optional[str] = None


@router.post("/sessions/{session_id}/fork", response_model=dict)
@with_db_lock
def fork_session(session_id: str, data: ForkSessionRequest):
    """从当前会话分叉出新会话（M4）。

    复制 ``at_message_id`` 及之前的全部消息（省略时复制全部）到新会话，
    消息获得新 id 但保留顺序 / 角色 / 内容 / 时间戳。新会话写入
    ``fork_root=<源 id>`` 与 ``forked_at_message_id``。

    刻意采用**全量前缀复制**而非计划文档最初的 copy-on-write 设计：
    桌面级会话只有数百条消息，复制更简单安全（详见 docs/plans/2026-07-29_session-compact-fork-m4.md）。

    - 200 + 新会话 JSON（含 fork_root / forked_at_message_id）
    - 404 + 结构化 detail — 源会话或分叉点消息不存在
    """
    try:
        forked = fork_session_core(
            SessionRepository(),
            MessageRepository(),
            session_id,
            at_message_id=data.at_message_id,
            title=data.title,
        )
    except ForkSourceNotFoundError as exc:
        raise HTTPException(
            status_code=404,
            detail={"type": f"{exc.kind}_not_found", "message": str(exc)},
        ) from exc
    return forked.to_dict()


# ==================== 消息 API ====================


@router.post("/messages/{message_id}/delete")
@with_db_lock
def delete_message(message_id: str):
    """删除单条消息（物理删除，非软删）。

    对应 Tauri command ``delete_message`` (PR-2):
    - 现有消息 → 200 + ``{"deleted": true}``
    - 不存在消息 → 404 + 结构化 detail (前端可分类处理)
    - 重复删除 → 第二次 404 (幂等性)

    注: 选 POST 而非 DELETE 是为了与项目其他 `/<resource>/<id>/delete` 路由
    (sessions/{id}/delete) 保持一致; 真正的 RESTful DELETE 在 v2 改造时再做。
    """
    from backend.data.session_repo import MessageRepository

    deleted = MessageRepository().delete(message_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail={
                "type": "message_not_found",
                "message": f"message {message_id} not found",
            },
        )
    return {"deleted": True}


# ==================== Agent API (PR-3) ====================
#
# 4 个默认 agent (primary/researcher/coder/memory_manager) 由
# backend/main.py:lifespan 启动时通过 AgentRepository.seed_defaults_if_empty
# 种子化到 SQLite agents 表. 本节路由不写 (PR-4/5 负责 PATCH /toggle).


@router.get("/agents")
@with_db_lock
def list_agents():
    """列出所有 agent (含 disabled), 按 id 排序。

    对应 Tauri command ``list_agents`` (PR-3)。
    """
    from backend.data.agent_repo import AgentRepository

    return AgentRepository().list_all()


@router.get("/agents/{agent_id}")
@with_db_lock
def get_agent_by_id(agent_id: str):
    """按 id 取单个 agent。

    命名注意: 不能叫 ``get_agent`` — 与本文件 line 136 的 dependency
    provider ``def get_agent()`` 同名会覆盖, 导致 ``/interrupt`` 路由
    拿错函数. 后续 PR 可把 dependency 改名 ``make_sage_agent()``,
    本 PR 仅做局部重命名.
    """
    from backend.data.agent_repo import AgentRepository

    agent = AgentRepository().get(agent_id)
    if not agent:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )
    return agent


@router.patch("/agents/{agent_id}")
@with_db_lock
def update_agent(agent_id: str, data: AgentUpdate):
    """部分更新 agent (PR-4)。

    - 200 + 更新后完整 profile
    - 404 + 结构化 detail (id 不存在)
    - 422 (FastAPI 自动) — 字段类型 / role 白名单 / max_iterations 范围
    - PATCH 是 partial update: 缺省字段保留原值
    - 空 body: 视为 no-op, 返回当前 profile, updated_at 不动
    """
    from backend.data.agent_repo import AgentRepository

    # 字段级校验: role 白名单
    valid_roles = _VALID_AGENT_ROLES
    if data.role is not None and data.role not in valid_roles:
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_role",
                "message": f"role must be one of {sorted(valid_roles)}, got {data.role!r}",
            },
        )

    # 字段级校验: max_iterations 范围
    if data.max_iterations is not None and not (1 <= data.max_iterations <= 50):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": f"max_iterations must be in 1..50, got {data.max_iterations}",
            },
        )

    repo = AgentRepository()

    # 不存在 → 404 (update 返回 0 时区分"没字段改"和"id 不存在")
    if repo.get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )

    # 转 dict 给 repo.update; 字段名 model_config_data → model_config (避开 Pydantic 保留名)
    update_payload = data.model_dump(exclude_none=True)
    if "model_config_data" in update_payload:
        update_payload["model_config"] = update_payload.pop("model_config_data")

    repo.update(agent_id, update_payload)
    return repo.get(agent_id)


@router.patch("/agents/{agent_id}/toggle")
@with_db_lock
def toggle_agent(agent_id: str, data: AgentToggle):
    """启用/禁用 agent (PR-5)。

    - 200 + 更新后完整 profile (含 enabled / updated_at 新值)
    - 404 + 结构化 detail (id 不存在, 与 PR-3/PR-4 复用同一 type)
    - 422 (FastAPI 自动) — enabled 缺失 / 类型错

    选 ``/toggle`` 子路径而非复用 ``PATCH /agents/{id}`` 的理由:
    - 审计语义清晰: events.jsonl 里可单独 grep 出 toggle 操作
    - 未来权限模型: toggle 与 system_prompt 编辑可独立授权

    同值 toggle 也走 SQL UPDATE — 幂等但 updated_at 仍刷新, 符合
    set_enabled() 语义。
    """
    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()

    # 与 update_agent 一致: 显式查存在性, 给出比 set_enabled() 更友好的 404 detail
    if repo.get(agent_id) is None:
        raise HTTPException(
            status_code=404,
            detail={"type": "agent_not_found", "message": f"agent {agent_id} not found"},
        )

    repo.set_enabled(agent_id, data.enabled)
    return repo.get(agent_id)


@router.post("/agents")
@with_db_lock
def create_agent(data: AgentCreate):
    """创建自定义 agent（US-4）。

    - 200 + 完整 profile
    - 409 + 结构化 detail（id 已存在）
    - 422 — role 白名单 / max_iterations 范围
    """
    from backend.data.agent_repo import AgentRepository

    if data.role not in _VALID_AGENT_ROLES and data.role != "general":
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_role",
                "message": (
                    f"role must be one of {sorted(_VALID_AGENT_ROLES)} "
                    f"or 'general', got {data.role!r}"
                ),
            },
        )

    if data.max_iterations is not None and not (1 <= data.max_iterations <= 50):
        raise HTTPException(
            status_code=422,
            detail={
                "type": "invalid_max_iterations",
                "message": f"max_iterations must be in 1..50, got {data.max_iterations}",
            },
        )

    repo = AgentRepository()
    if repo.get(data.id) is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "type": "agent_already_exists",
                "message": f"agent {data.id!r} already exists",
            },
        )

    payload = data.model_dump(exclude_none=True)
    if "model_config_data" in payload:
        payload["model_config"] = payload.pop("model_config_data")
    payload.setdefault("tools", [])
    payload.setdefault("memory_access", [])
    payload.setdefault("model_config", {})
    payload.setdefault("max_iterations", 10)
    payload.setdefault("enabled", True)
    payload.setdefault("description", "")

    repo.upsert(payload)
    return repo.get(data.id)


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


def _skill_to_dict(ext: dict, enabled: bool, usage_count: int) -> dict:
    """把扩展 SkillSpec dict + 路由层 enabled/usage_count 序列化为响应 dict。

    ``ext`` 来自 ``InprocSkillAdapter.list_skills_extended()``,
    含 ``source / body / base_dir / version`` 等字段 (SKILL.md 时填充, builtin 时不存在)。

    复制一份避免修改 adapter 返回的共享 dict (immutable-ish 风格)。
    """
    out = dict(ext)
    out["enabled"] = enabled
    out["usage_count"] = usage_count
    return out


@router.get("/skills")
@with_db_lock
def list_skills():
    """列出所有已注册技能 (含 disabled 与 usage_count + SKILL.md 扩展字段)。"""
    adapter = _get_skill_adapter()
    return [
        _skill_to_dict(ext, adapter.is_enabled(ext["name"]), adapter.usage_count(ext["name"]))
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
    return _skill_to_dict(ext, adapter.is_enabled(name), adapter.usage_count(name))


class SkillArchive(BaseModel):
    """``POST /skills/{name}/archive`` 请求体。"""

    archived: StrictBool


@router.post("/skills/{name}/archive")
@with_db_lock
def archive_skill(name: str, data: SkillArchive):
    """归档 / 取消归档技能（软标记，可逆；区别于物理 delete）。

    - 200 + 完整 skill dict（含新 lifecycle）
    - 404 + 结构化 detail（技能名不存在）
    - 422（FastAPI 自动）— archived 缺失 / 类型错

    归档技能从 auto_activate / slash 候选排除（adapter 层），文件不动、可恢复。
    """
    adapter = _get_skill_adapter()
    if not adapter.set_archived(name, data.archived):
        raise HTTPException(
            status_code=404,
            detail={"type": "skill_not_found", "message": f"skill '{name}' not found"},
        )
    # 返回完整 skill dict（与 toggle 一致）—— lifecycle 已由 list_skills_extended 注入
    ext = next((e for e in adapter.list_skills_extended() if e["name"] == name), None)
    assert ext is not None  # set_archived 已 guard
    return _skill_to_dict(ext, adapter.is_enabled(name), adapter.usage_count(name))


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

    - 200 + ``{"deleted": true, "name": ..., "base_dir": ...}``
    - 400 + detail=str(exc): builtin 不可删 / name 非法 / base_dir 跑出
      SAGE_SKILLS_DIR
    - 404 + detail=str(exc): skill 不存在 (registry 或磁盘)
    - 500 + detail=str(exc): SAGE_SKILLS_DIR 未配置 / 其他文件系统错误
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
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except SkillMdNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        # name 非法 / base_dir 跑出 SAGE_SKILLS_DIR
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        # SAGE_SKILLS_DIR 未配置 / 其他 fs 错误 — 路由层转 500
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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

    - 200 + ``{"imported": [{"name", "path"}], "skipped": [{"name", "reason"}]}``
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
        raise HTTPException(
            status_code=500,
            detail={"type": "no_skills_dir", "message": str(exc)},
        ) from exc

    return result


# ==================== Settings & Preferences API ====================
#
# 这些端点在 hex_routes 中也有定义。legacy 模式下 hex_routes 不注册，
# 但 Electron 前端需要 /settings 和 /preferences/{key} 来加载配置，
# 因此在 legacy_routes 中也提供，确保两种 API_MODE 下都能工作。


from pydantic import ConfigDict as _ConfigDict


class LegacySettingsRequest(BaseModel):
    """PUT /settings 请求体（legacy 路径）。所有字段可选。"""

    model_config = _ConfigDict(extra="allow")

    api_base_url: Optional[str] = None

    api_key: Optional[str] = None  # noqa: S105

    model: Optional[str] = None


class LegacySettingsResponse(BaseModel):
    """PUT /settings 响应体。"""

    status: str = "ok"
    changed_fields: List[str] = []


class LegacyPreferenceItem(BaseModel):
    """GET/PUT /preferences/{key} 请求/响应体。"""

    value: Optional[str] = None

    value_type: str = "string"
    category: str = "general"


@router.get("/settings")
@with_db_lock
def legacy_get_settings() -> Optional[dict]:
    """读取持久化的 settings；不存在返回 null。

    翻译历史 snake_case 残留到 camelCase 返回，与 AppSettings 类型对齐。
    JSON 损坏 / 顶层非 dict (list / scalar) → null fallback，不抛 500，与 hex GET 对齐。
    """
    from backend.data.settings_canonicalizer import (
        detect_legacy_snake_pollution,
        to_camel,
    )
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        raw = repo.get_json("app_settings")
    except (ValueError, TypeError):
        logger.warning("[LEGACY] /settings: corrupted app_settings JSON, returning null")
        return None
    if raw is None:
        return None
    if not isinstance(raw, dict):
        # get_json 可返回任意合法 JSON; app_settings 必须是 dict; 与 hex GET 对齐。
        logger.warning("[LEGACY] /settings: top-level non-dict JSON, returning null")
        return None
    detect_legacy_snake_pollution(raw)
    return to_camel(raw)


@router.put("/settings", response_model=LegacySettingsResponse)
@with_db_lock
def legacy_update_settings(req: LegacySettingsRequest) -> LegacySettingsResponse:
    """持久化 settings 到 preferences 表。

    v3.1 修复：合并而非覆盖。
    LegacySettingsRequest 只有 api_base_url/api_key/model 三个字段，
    如果直接替换，会丢失 endpoints、model_selections 等其他数据。
    修复策略：先读现有 settings，再把请求字段 merge 进去。

    Task 2 (settings-schema-canonicalization):
    - 整树翻译到 camelCase (to_camel)
    - 白名单校验 (validate_settings_shape) 拒绝白名单外字段 → 400
    """
    from backend.data.settings_canonicalizer import (
        strip_unknown_fields,
        to_camel,
        validate_settings_shape,
    )
    from backend.data.settings_repo import SettingsRepository

    repo = SettingsRepository()
    try:
        existing = repo.get_json("app_settings") or {}
    except (ValueError, TypeError):
        # DB 行 JSON 损坏 → 当空树处理, 避免 500 阻断合法的 PUT
        existing = {}
    if not isinstance(existing, dict):
        # existing 是 list/scalar (脏数据) → 用空树, 不阻断合法 PUT; 与 hex PUT 对齐.
        existing = {}

    # LegacySettingsRequest 是 extra="allow", model_dump(exclude_none=True) 会包含所有 set 字段
    # (含 extras, 如 streaming/foo/endpoints) — 这是设计: 旧客户端 PUT schema 之外字段不丢。
    payload = req.model_dump(exclude_none=True)

    # 剥离 legacy compatibility 3 字段: api_base_url / api_key / model.
    # 这 3 字段不进 DB (与 hex PUT 对齐, 见 eebbedd), 仅用于审计和 changed_fields.
    # 原因: 这 3 个 snake 字段通过 to_camel 翻译后 (apiKey) 或原样保留 (api_base_url/model)
    # 都不在 LEGAL_TOP_KEYS, 会触发 validate_settings_shape 400, 但它们是合法 legacy schema 字段.
    legacy_compat_fields = {"api_base_url", "api_key", "model"}
    legacy_compat_payload = {k: payload.pop(k) for k in list(payload) if k in legacy_compat_fields}

    # existing 里的历史残留字段（compactMode / proxyMode 等前端已删）会让
    # validate_settings_shape 对整棵合并树报 400。只剥离 existing 侧的残留，
    # payload 侧的未知字段仍原样保留并触发 400（与 hex PUT 对齐）。
    camel_existing = strip_unknown_fields(to_camel(existing))
    camel_merged = {**camel_existing, **to_camel(payload)}
    try:
        validate_settings_shape(camel_merged)
    except ValueError as exc:
        logger.warning(f"[LEGACY] /settings rejected unknown field: {exc}")
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    repo.set_json("app_settings", camel_merged, category="general")
    changed_fields = [k for k in payload if k != "api_key"]
    if "api_key" in payload:
        changed_fields.append("api_key")
    # 同时把 legacy 兼容字段记进 changed_fields (审计可见), 即使不进 DB
    changed_fields.extend(k for k in legacy_compat_payload if k not in changed_fields)
    logger.info(f"[LEGACY] /settings updated: changed={changed_fields}")
    return LegacySettingsResponse(status="ok", changed_fields=changed_fields)


@router.get("/preferences/{key}", response_model=LegacyPreferenceItem)
@with_db_lock
def legacy_get_preference(key: str) -> LegacyPreferenceItem:
    """通用 KV 读取（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    val = SettingsRepository().get(key)
    return LegacyPreferenceItem(value=val)


@router.put("/preferences/{key}", response_model=LegacyPreferenceItem)
@with_db_lock
def legacy_put_preference(key: str, item: LegacyPreferenceItem) -> LegacyPreferenceItem:
    """通用 KV 写入（白名单限定 key）。"""
    from backend.data.settings_repo import SettingsRepository

    if key not in SettingsRepository.KEYS:
        raise HTTPException(status_code=400, detail=f"key {key!r} not in whitelist")
    if item.value is not None:
        SettingsRepository().set(
            key, item.value, value_type=item.value_type, category=item.category
        )
    return item


# ==================== 聊天 API ====================


@router.post("/chat", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    request: Request,
):
    """发送聊天消息（单 agent；流式编排见 /chat/stream）。

    错误处理：
    - LLMError: 返回 HTTP 200 + 结构化 error 字段
    - 其他未预期错误: 返回 HTTP 200 + 通用 unknown 错误
    - request_id 来自中间件（确保响应头与日志一致）
    """
    request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
    logger.info(
        f"[REQ {request_id}] /chat received: session_id={_safe_log_field(data.session_id)}, "
        f"api_key={'***' if data.api_key else 'MISSING'}, "
        f"model={_safe_log_field(data.model or 'default')}"
    )

    try:
        llm_config = None
        if data.api_key and data.api_url:
            llm_config = {
                "provider": "custom",
                "api_key": data.api_key,
                "base_url": data.api_url,
                "model": data.model or "gpt-3.5-turbo",
                "temperature": data.temperature or 0.7,
            }
            logger.info(
                f"[REQ {request_id}] using custom LLM config: model={_safe_log_field(llm_config['model'])}"
            )

        # 2026-07-30: chat 默认加载 primary profile,让 profile.tools 白名单生效
        # (memory_manager 之类窄权限 agent 才不会拿到 list_dir/read_file 全部工具)
        agent = SageAgent(agent_id=data.agent_id or "primary")
        result = await agent.chat(data.session_id, data.message, llm_config=llm_config)

        # agent.chat() may return a structured error dict (Task 6 refactor) instead of raising
        if isinstance(result, dict) and result.get("error"):
            logger.warning(
                f"[REQ {request_id}] /chat returned error from agent: "
                f"type={result['error'].get('type')}, message={result['error'].get('message')}"
            )
        else:
            msg = result.get("message") if isinstance(result, dict) else None
            msg_id = msg.get("id") if isinstance(msg, dict) else None
            logger.info(f"[REQ {request_id}] /chat success: message_id={msg_id}")
        return result

    except LLMError as e:
        logger.warning(
            f"[REQ {request_id}] /chat LLM error: type={e.type.value}, message={e.message}"
        )
        return {
            "error": e.to_dict(),
            "message": None,
            "session": None,
        }
    except Exception:
        logger.exception(f"[REQ {request_id}] /chat unexpected error")
        return {
            "error": {
                "type": "unknown",
                "message": "服务内部错误",
                "status_code": 500,
                "retry_after": None,
            },
            "message": None,
            "session": None,
        }


@router.post("/chat/stream")
async def chat_stream_create(data: ChatRequest, request: Request):
    """创建 chat 流 (I2)。

    立即返回 ``{"streamId": "..."}``,后台启动 ``agent.run_loop`` 跑一次 LLM,
    事件入 ``app.state.streams[streamId].queue``。

    Electron 端拿到 streamId 后调 ``GET /chat/stream/{streamId}`` attach 取事件。
    这样 LLM 只被调一次(原方案 invoke 阶段读首行 + relay 重放 = 两次)。

    Args:
        data: 与原 /chat 相同的 ChatRequest 体
        request: FastAPI Request,用于访问 app.state

    Returns:
        ``{"streamId": "<uuid4>"}``
    """
    request_id = str(uuid.uuid4())
    stream_id = str(uuid.uuid4())
    logger.info(
        f"[REQ {request_id}] /chat/stream create: "
        f"streamId={stream_id}, "
        f"session_id={_safe_log_field(data.session_id)}, "
        f"api_key={'***' if data.api_key else 'MISSING'}, "
        f"model={_safe_log_field(data.model or 'default')}"
    )

    # Task 6 (M1-M2): 同步授权 ChatOfficeRef. 这一步必须在
    # ``registry.create`` 之前完成 — 一旦 stream id 进入注册表,
    # 失败路径就必须显式清理才能避免孤儿. 把授权放到 producer 启动
    # 之前还有一个好处:授权失败时既不消耗 stream slot,也不浪费 LLM token.
    # 错误映射见 ``backend.office.workspace_errors`` 模块注释.
    try:
        db = get_database()
        _auth_conn = db.get_connection()
        _auth_result = authorize_chat_office_request(
            _auth_conn,
            data.session_id,
            data.workspace_path,
            data.office_refs,
        )
    except WorkspacePathMismatchError as exc:
        logger.warning(
            f"[REQ {request_id}] /chat/stream office-ref path mismatch: {exc.safe_message}"
        )
        raise HTTPException(
            status_code=400,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )
    except WorkspaceNotBoundError as exc:
        logger.warning(f"[REQ {request_id}] /chat/stream office-ref not bound: {exc.safe_message}")
        raise HTTPException(
            status_code=403,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )
    except WorkspaceSessionNotFoundError as exc:
        logger.warning(
            f"[REQ {request_id}] /chat/stream office-ref session not found: {exc.safe_message}"
        )
        raise HTTPException(
            status_code=404,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )
    except WorkspaceDocumentNotFoundError as exc:
        logger.warning(
            f"[REQ {request_id}] /chat/stream office-ref doc not found: {exc.safe_message}"
        )
        raise HTTPException(
            status_code=404,
            detail={
                "type": exc.code,
                "message": exc.safe_message,
            },
        )

    registry: StreamRegistry = request.app.state.streams

    async def producer(entry: StreamEntry) -> None:
        """后台跑 agent.run_loop,事件入 entry.queue。

        这里把 AgentEvent.to_dict() 在入队时序列化,避免对象跨 task 边界泄漏
        内部状态(detached Pydantic / cyclic ref 等)。
        """
        # Task 9 (M1-M2): build a ToolExecutionContext from the captured
        # authorization so Office tools can read the session's binding.
        # set/reset around ``agent.run_loop`` via try/finally so the
        # ContextVar never leaks across producer invocations.
        from backend.tools.context import (
            ToolExecutionContext,
            reset_tool_context,
            set_tool_context,
        )

        _tool_ctx_token = None
        if _auth_result is not None:
            _tool_ctx = ToolExecutionContext(
                session_id=_auth_result.session_id,
                stream_id=stream_id,
                binding_generation=_auth_result.binding_generation,
                office_doc_scope=_auth_result.office_doc_scope,
            )
        else:
            # F2 (2026-08-12): 普通聊天（无 office 授权）也设置上下文 —— 否则
            # write_file 等工具的 artifact 记录会因 current_tool_context() 为
            # None 静默早退，产物无法在 Artifacts 面板展示。binding_generation
            # = 0 表示无 workspace 绑定；office 工具不在普通聊天 profile 白名单
            # （primary/researcher/coder/memory_manager/writer 均无）。
            _tool_ctx = ToolExecutionContext(
                session_id=data.session_id,
                stream_id=stream_id,
                binding_generation=0,
                office_doc_scope=frozenset(),
            )
        _tool_ctx_token = set_tool_context(_tool_ctx)
        # P1 todo 接线 (spec 2026-08-21): todo_write 变更 → todo_snapshot
        # SSE 全量快照。会话过滤防跨流串扰；队列满静默降级（尽力而为）。
        from backend.tools.todo_state import (
            add_todo_listener,
            remove_todo_listener,
        )

        def _push_todo_snapshot(session_id: str, todos: Any) -> None:
            if session_id != data.session_id:
                return
            try:
                entry.queue.put_nowait(
                    {
                        "state": "todo_snapshot",
                        "session_id": session_id,
                        "todos": todos,
                    }
                )
            except Exception:  # noqa: BLE001 — 降级铁律
                logger.debug("todo_snapshot 推送失败（队列满/关闭），忽略")

        add_todo_listener(_push_todo_snapshot)
        try:
            # P0-4 (2026-08-20): 终态变量前置到 try 顶部 —— finally 无条件读取
            # 它们，若留在数百行之后声明，早期异常（如 resolve_attachments 抛错、
            # CancelledError）会让 finally 触发 UnboundLocalError，既掩盖原始异常
            # 又跳过后续的 reset_tool_context 清理。
            done_content: Optional[str] = None
            run_outcome = "failed"

            llm_config = None
            if data.api_key and data.api_url:
                llm_config = {
                    # 修: provider 不再硬写,从前端请求透传;
                    # 默认 "custom" 保留向后兼容(老客户端/无 provider 字段)
                    "provider": data.provider or "custom",
                    "api_key": data.api_key,
                    "base_url": data.api_url,
                    "model": data.model or "gpt-3.5-turbo",
                    "temperature": data.temperature or 0.7,
                }
                # 推理参数:None 时不传,避免污染老 LLM
                if data.reasoning_effort is not None:
                    llm_config["reasoning_effort"] = data.reasoning_effort
                if data.thinking_budget is not None:
                    llm_config["thinking_budget"] = data.thinking_budget
                logger.info(
                    f"[REQ {request_id}] /chat/stream producer using custom LLM: "
                    f"model={_safe_log_field(llm_config['model'])}"
                )

            agent = SageAgent(agent_id=data.agent_id or "primary")
            # P0 cancellation: register the primary before any blocking await.
            _ACTIVE_STREAMS[stream_id] = {
                "agent": agent,
                "run_id": None,
                "dispatcher": None,
                "cancelled": False,
            }

            # Build system prompt with optional diagram tool guidance
            from backend.agents.profiles import build_system_base

            system_content = build_system_base()

            # ===== Multi-Agent Orchestration (spec 2026-08-11) =====
            # tool-toggle 门: 语义判定（独立轻量 LLM 二分类）决定 mode。
            # single → 不注册 dispatch_subagents 工具、不跑 decompose_request
            #          （简单任务结构上无法被过度拆解 — 硬约束 2）
            # multi  → 复用 Planner 预规划 + conductor 经 dispatch 工具执行
            #          （复杂任务必出 task_plan + 必注册工具 — 硬约束 1）
            from backend.orchestration.llm_factory import (
                build_llm_client_from_settings,
            )

            # A10 (2026-08-14): plan_override 非空 → 视为 force_multi，跳过语义判定。
            if data.plan_override:
                mode = "multi"
            else:
                try:
                    mode = await _classify_orchestration_mode(
                        data.message,
                        data.orchestration_mode or "auto",
                        llm_client=build_llm_client_from_settings(),
                    )
                except Exception as exc:  # noqa: BLE001 — 编排判定失败必须降级 single
                    logger.warning("编排语义判定失败，降级 single: %s", exc)
                    mode = "single"
            run_id: Optional[str] = None
            dispatcher = None
            if mode == "multi":
                from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS
                from backend.orchestration.planner import Planner
                from backend.orchestration.task_registry import TaskRegistry
                from backend.orchestration.team_registry import TeamRegistry
                from backend.tools.subagent_tool import DispatchSubagentsTool

                if data.plan_override:
                    # A10 (2026-08-14): override 路径 —— items 自带 task_id，
                    # 直接透传，不重枚举；run_id 复用 resume 返回的 new_run_id。
                    plan_tasks = data.plan_override
                    run_id = data.run_id or f"orch-{uuid.uuid4()}"
                else:
                    # P2-8 (2026-08-14): orchestration_mode=template:<id> → 确定性模板拆解。
                    orchestration_mode = data.orchestration_mode or "auto"
                    template_id = (
                        orchestration_mode.split(":", 1)[1]
                        if orchestration_mode.startswith("template:")
                        else None
                    )
                    try:
                        if template_id is not None:
                            plan = await Planner(
                                task_registry=TaskRegistry(),
                                team_registry=TeamRegistry(),
                                llm_client=build_llm_client_from_settings(),
                            ).decompose_from_template(template_id, data.message)
                        else:
                            plan = await Planner(
                                task_registry=TaskRegistry(),
                                team_registry=TeamRegistry(),
                                llm_client=build_llm_client_from_settings(),
                            ).decompose_request(data.message)
                        plan_tasks = list(plan.tasks if plan else [])
                    except Exception as exc:  # noqa: BLE001 — 模板/规划失败降级 single
                        if template_id is not None:
                            logger.warning(
                                "编排模板 %s 拆解失败，降级 single: %s", template_id, exc
                            )
                        else:
                            logger.warning("编排规划失败，降级 single: %s", exc)
                        mode = "single"
                        plan_tasks = []
                    run_id = f"orch-{uuid.uuid4()}"
                if len(plan_tasks) <= 1 and not data.plan_override:
                    # LLM 没拆开（或降级单任务）→ 视为没开编排；
                    # override 单任务仍保持 multi（恢复流尊重用户指定计划）。
                    mode = "single"
                if mode == "multi":
                    # 归一为 {task_id, agent_id, goal, depends_on} 列表 —— 下游
                    # plan_block / init / task_plan 事件同构。override 路径透传
                    # 自带 task_id；decompose 路径从 Task 对象重新编号 t1..tN。
                    plan_items: List[Dict[str, Any]]
                    if data.plan_override:
                        plan_items = [
                            {
                                "task_id": str(it["task_id"]),
                                "agent_id": str(it.get("agent_id", "primary")),
                                "goal": str(it.get("goal", "")),
                                "depends_on": list(it.get("depends_on") or []),
                            }
                            for it in data.plan_override
                        ]
                    else:
                        plan_items = [
                            {
                                "task_id": f"t{i}",
                                "agent_id": t.parameters.get("agent_hint", "primary"),
                                "goal": t.description or t.name,
                                "depends_on": list(t.blocked_by),
                            }
                            for i, t in enumerate(plan_tasks, 1)
                        ]
                    dispatcher_workspace_root = None
                    try:
                        from backend.office.session_workspace import get_workspace_binding

                        binding = get_workspace_binding(
                            get_database().get_connection(), data.session_id
                        )
                        if binding is not None and binding.workspace_path:
                            dispatcher_workspace_root = binding.workspace_path
                    except Exception as workspace_err:  # noqa: BLE001 — 降级旧 scratch
                        logger.debug(
                            "编排 workspace 绑定读取失败，回落 scratch: %s",
                            workspace_err,
                        )
                    dispatcher = _build_orchestration_dispatcher(
                        stream_id=stream_id,
                        entry_queue=entry.queue,
                        run_id=run_id,
                        llm_config=llm_config,
                        total_tasks=len(plan_items),
                        workspace_root=dispatcher_workspace_root,
                    )
                    # P2-9 (2026-08-14): 进程内注册表登记 —— 长连接期间 run 级
                    # cancel 端点能定位到本 dispatcher 并置位取消事件。
                    _ACTIVE_DISPATCHERS[run_id] = dispatcher
                    stream_entry = _ACTIVE_STREAMS.get(stream_id)
                    if stream_entry is not None:
                        stream_entry["run_id"] = run_id
                        stream_entry["dispatcher"] = dispatcher
                        if (
                            stream_entry.get("cancelled")
                            or run_id in _PENDING_RUN_CANCELLATIONS
                        ):
                            stream_entry["cancelled"] = True
                            _PENDING_RUN_CANCELLATIONS.discard(run_id)
                            agent.interrupt()
                            dispatcher.cancel()
                    agent.tool_registry.register(DispatchSubagentsTool(dispatcher))
                    if (
                        agent.profile is not None
                        and agent.profile.get("tools") is not None
                    ):
                        agent.profile["tools"].append("dispatch_subagents")
                    # 计划块注入 system prompt —— conductor 依据计划调用工具
                    # 注: system_content 已在插入点之前由 build_system_base()
                    # 赋值（L1598），这里只追加计划块，不再重新赋值（否则覆盖）。
                    plan_block = "\n".join(
                        f"- {i}. [{it['agent_id']}] {it['goal']}"
                        for i, it in enumerate(plan_items, 1)
                    )
                    system_content += (
                        "\n\n以下为已确认的任务计划，请调用 dispatch_subagents "
                        "工具并行执行这些子任务（可合并/调整）。不要复述计划，直接执行。\n"
                        + plan_block
                        # 进度可视化 P0-2 后置 (2026-08-12): 强化"必须全量执行完
                        # 才汇总"约束。dispatch_subagents 每次调用可能只派发部分
                        # 子任务（分批/合并），若聚合头只反映"本批已收到 X/X"，
                        # LLM 可能误以为全部完成而提前总结。这里显式给出总数 N，
                        # 要求必须等到 N 个全部有结果才输出最终汇总。
                        + "\n\n必须执行完计划中的全部"
                        + str(len(plan_items))
                        + " 个子任务，等到所有子任务都返回结果后，才能输出最终汇总。"
                        "若本次 dispatch 只执行了部分子任务，请继续调用工具执行剩余任务，"
                        "不要提前给出结论。"
                    )
                    # 计划先行：子 agent 跑之前先推 task_plan（可展示、可取消）
                    # Wave 2 P1-4: 首次 dispatch 前把 run + plan 落库,供 resume 端点重建。
                    # 失败降级（logger.warning）,绝不阻塞聊天。
                    # A10: reasoning 捕获 —— override 路径 plan 未定义 → 常量
                    # "plan_override"；decompose 路径 plan.reasoning（可为空串）。
                    # 避免 override 路径直接引用未定义的 plan 抛 NameError。
                    reasoning = (
                        "plan_override"
                        if data.plan_override
                        else (plan.reasoning if plan else "")
                    )
                    try:
                        if dispatcher is not None and hasattr(dispatcher, "init_orch_run"):
                            dispatcher.init_orch_run(
                                session_id=data.session_id,
                                plan_json=json.dumps(
                                    {"tasks": plan_items, "reasoning": reasoning},
                                    ensure_ascii=False,
                                ),
                                # Wave 3 A9: resume 恢复流逐字重发原始请求。
                                original_request=data.message,
                            )
                    except Exception as exc:  # noqa: BLE001 — 降级铁律
                        logger.warning("dispatcher.init_orch_run 失败: %s", exc)
                    await entry.queue.put(
                        {
                            "state": "task_plan",
                            "run_id": run_id,
                            "plan": plan_items,
                        }
                    )
                    # 进度可视化 P0-2 (2026-08-12): task_plan 之后立即推
                    # 一次 task_progress 初始化事件,前端 taskBoard 在子
                    # agent 跑之前就能拿到 total,UI 可立即渲染"已拆解为 N
                    # 个子任务,等待结果中…"。后续 5 元组由 reducer 从
                    # task_status 实时聚合。
                    await entry.queue.put(
                        {
                            "state": "task_progress",
                            "run_id": run_id,
                            "total": len(plan_items),
                            "done": 0,
                            "running": 0,
                            "queued": len(plan_items),
                            "failed": 0,
                        }
                    )
            try:
                from backend.core.diagram_prompt import (
                    DIAGRAM_TOOL_PROMPT,
                    registry_has_drawio_tool,
                )

                # Check if any drawio MCP tools are registered. Prefix
                # scan (mcp__drawio__*) — M3 renamed tools to
                # mcp__<server>__<tool>, and a fixed-name exists() check
                # would silently die on the next server-side rename.
                _registry = getattr(agent, "tool_registry", None)
                if _registry and registry_has_drawio_tool(_registry):
                    system_content += DIAGRAM_TOOL_PROMPT
            except Exception:
                pass  # Graceful fallback if diagram module unavailable

            # ===== M6 PROJECT CONTEXT BEGIN =====
            # SAGE.md/CLAUDE.md 向上发现 → 注入 system prompt。仅当会话已
            # 绑定 workspace 时注入; 任何失败静默跳过 (见 backend/chat/
            # project_context.py)。独立标记块, rebase 友好。
            try:
                from backend.chat.project_context import discover_project_context
                from backend.office.session_workspace import get_workspace_binding

                m6_binding = get_workspace_binding(
                    get_database().get_connection(), data.session_id
                )
                if m6_binding is not None and m6_binding.workspace_path:
                    m6_context_block = discover_project_context(
                        m6_binding.workspace_path
                    ).render()
                    if m6_context_block:
                        system_content += "\n\n" + m6_context_block
            except Exception as m6_ctx_err:
                logger.debug(f"[REQ {request_id}] M6 project context skipped: {m6_ctx_err}")
            # ===== M6 PROJECT CONTEXT END =====

            attachment_block = await resolve_attachments(data.message, data.workspace_path or "")
            messages = [{"role": "system", "content": system_content}]
            if attachment_block:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "The user has referenced the following attached documents. "
                            "Treat them as primary context for the user's request.\n\n"
                            f"{attachment_block}"
                        ),
                    }
                )
            messages.append({"role": "user", "content": data.message})
            # M4 自动压缩: run_loop 之前检查历史是否达到压缩阈值,达到则
            # 先压缩再继续。整块 try/except 隔离——压缩失败只记日志,
            # 绝不阻塞本次聊天(流式事件照常产出)。注: AgentEvent 没有
            # notice 类事件, 本里程碑不向前端推送压缩状态。
            try:
                await _maybe_auto_compact_session(data.session_id, llm_config)
            except Exception as compact_err:
                logger.warning(
                    f"[REQ {request_id}] 自动压缩失败(忽略, 继续未压缩聊天): {compact_err}"
                )

            # PR-7: 流式 chat 持久化。run_loop() 自身不写库(保持通用 ReAct
            # 迭代器纯净),由 producer 整合层负责落 user+assistant 消息 + 更新
            # session metadata。每个落盘独立 try/except,失败只 logger.warning
            # 不破坏流。
            message_repo = MessageRepository()
            session_repo = SessionRepository()
            user_now = int(time.time() * 1000)
            try:
                message_repo.save(
                    DbMessage(
                        id=str(uuid.uuid4()),
                        session_id=data.session_id,
                        role="user",
                        content=data.message,
                        created_at=user_now,
                    )
                )
            except Exception as db_err:
                logger.warning(f"[REQ {request_id}] 用户消息持久化失败: {db_err}")

            done_reasoning: Optional[str] = None

            # 暂存 DONE 事件 — 待 post-loop 标题生成后再推入队列，
            # 确保前端 onDone 时 loadSessions() 能读到已更新的标题。
            done_event = None

            # P0-2 (2026-08-20): registration is created immediately after agent.
            # Keep the same entry and only refresh late-bound fields here.
            stream_entry = _ACTIVE_STREAMS.get(stream_id)
            if stream_entry is not None:
                stream_entry["run_id"] = run_id
                stream_entry["dispatcher"] = dispatcher
                if run_id in _PENDING_RUN_CANCELLATIONS:
                    stream_entry["cancelled"] = True
                    _PENDING_RUN_CANCELLATIONS.discard(run_id)
                    agent.interrupt()
                    if dispatcher is not None:
                        dispatcher.cancel()
                elif stream_entry.get("cancelled") and dispatcher is not None:
                    dispatcher.cancel()

            async for evt in agent.run_loop(messages, llm_config=llm_config):
                # I5: DONE 事件的 content 拆成 chunk 逐个入队,前端累积实现逐字显示。
                # 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls,
                # 那是更大的重构;这个 producer 端的 fake stream 给出 90% 视觉效果。
                if evt.state.value == "done" and evt.content:
                    done_content = evt.content
                    content = evt.content
                    for i in range(0, len(content), _STREAMING_CHUNK_SIZE):
                        delta = content[i : i + _STREAMING_CHUNK_SIZE]
                        await entry.queue.put(
                            {
                                "state": "content_delta",
                                "iteration": evt.iteration,
                                "content": delta,
                            }
                        )
                        await asyncio.sleep(_STREAMING_CHUNK_DELAY_S)
                    # 暂存 DONE 事件，不立即推入队列 —
                    # 待 post-loop 标题生成 + session_updated 事件后再推送，
                    # 保证前端 onDone → loadSessions() 时标题已落盘。
                    done_event = evt
                    run_outcome = "completed"
                elif evt.state.value == "reasoning" and evt.reasoning:
                    # PR-7b: 累积 reasoning 事件,持久化时一起写入 DB
                    if done_reasoning is None:
                        done_reasoning = evt.reasoning
                    else:
                        done_reasoning += evt.reasoning
                    # 流式输出 reasoning: 拆成小块逐个入队,模拟逐字显示效果
                    reasoning = evt.reasoning
                    for i in range(0, len(reasoning), _STREAMING_CHUNK_SIZE):
                        delta = reasoning[i : i + _STREAMING_CHUNK_SIZE]
                        await entry.queue.put(
                            {
                                "state": "reasoning_delta",
                                "iteration": evt.iteration,
                                "reasoning": delta,
                                "agent_id": evt.agent_id,
                            }
                        )
                        await asyncio.sleep(_STREAMING_CHUNK_DELAY_S)
                    # 最终 reasoning 事件携带累积全量 (而非单次 evt.reasoning)。
                    # 这样: 持久化、最终事件、前端累积 三者 reasoning 文本一致,
                    # 不依赖前端每个 delta 都没丢。
                    final_reasoning_event = evt.to_dict()
                    final_reasoning_event["reasoning"] = done_reasoning
                    await entry.queue.put(final_reasoning_event)
                else:
                    await entry.queue.put(evt.to_dict())

            # run_loop 正常结束 (DONE) → 持久化 assistant + 更新 session。
            # LLMError 走 except 分支,此块不执行 (无 assistant 可保存)。
            if done_content:
                assistant_now = int(time.time() * 1000)
                assistant_persisted = False
                try:
                    message_repo.save(
                        DbMessage(
                            id=str(uuid.uuid4()),
                            session_id=data.session_id,
                            role="assistant",
                            content=done_content,
                            reasoning_content=done_reasoning,
                            created_at=assistant_now,
                            model=(llm_config.get("model") if llm_config else "local"),
                        )
                    )
                    assistant_persisted = True
                except Exception as db_err:
                    logger.warning(f"[REQ {request_id}] 助手消息持久化失败: {db_err}")
                # WS-C P0-2: 统一记忆写入路径 — assistant 落盘**成功后**才触发
                # 提取（落盘失败则跳过, 避免产生无对应消息的脏记忆）。
                # best-effort + autoMemory 开关, 失败只 warning, 不影响流。
                if assistant_persisted:
                    await _extract_legacy_chat_memory(
                        request_id, data.session_id, data.message, done_content
                    )
                try:
                    sess = session_repo.get(data.session_id)
                    if sess is not None:
                        session_repo.update(
                            data.session_id,
                            last_message_at=assistant_now,
                            message_count=sess.message_count + 2,
                        )
                except Exception as db_err:
                    logger.warning(f"[REQ {request_id}] 会话更新失败: {db_err}")

                # 标题自动生成：首轮对话后 (message_count 从 0 → 2)。
                # 在推送 DONE 事件前完成，确保前端 onDone → loadSessions() 读到新标题。
                if done_event and sess and sess.message_count <= 2:
                    try:
                        from backend.chat.title_generator import TitleGenerator
                        from backend.orchestration.llm_factory import (
                            build_llm_client_from_settings,
                        )

                        title_client = build_llm_client_from_settings()
                        if title_client:
                            title = await TitleGenerator(title_client).generate(
                                data.message, done_content
                            )
                            if title:
                                session_repo.update(data.session_id, title=title)
                                await entry.queue.put(
                                    {
                                        "type": "session_updated",
                                        "subtype": "title_updated",
                                        "title": title,
                                    }
                                )
                    except Exception as e:
                        logger.warning(
                            f"[REQ {request_id}] 标题生成失败: {e}"
                        )

                # 推送暂存的 DONE 事件（在 session_updated 之后）
                if done_event:
                    await entry.queue.put(done_event.to_dict())
        except LLMError as e:
            logger.warning(
                f"[REQ {request_id}] /chat/stream LLM error: "
                f"type={e.type.value}, message={e.message}"
            )
            await entry.queue.put({"error": e.to_dict(), "state": "failed"})
        finally:
            # P2-9 (2026-08-14): 长连接结束注销注册表条目（run 级 cancel 不再命中）。
            # run_id 为 None（single 路径）时跳过 —— 从未注册过。
            if run_id:
                _ACTIVE_DISPATCHERS.pop(run_id, None)
            # P0-2 (2026-08-20): 注销流注册表 —— stream 结束 / interrupt 不再命中陈旧实例。
            _ACTIVE_STREAMS.pop(stream_id, None)
            # P0-4 (2026-08-20): orch run 终态闭环 —— 让 run 离开 "running"。
            _finalize_orch_run(run_id, run_outcome, done_content)
            # Task 9 (M1-M2): always reset the tool context so the
            # ContextVar never leaks into the next producer invocation.
            if _tool_ctx_token is not None:
                reset_tool_context(_tool_ctx_token)
            # P1 todo 接线: 注销监听器（闭包持有 entry/queue 引用，
            # 不注销会随全局 _listeners 泄漏并推已关闭的流）。
            remove_todo_listener(_push_todo_snapshot)

    await registry.create(stream_id, queue_maxsize=1000, producer=producer)
    return {"streamId": stream_id}


@router.get("/chat/stream/{stream_id}")
async def chat_stream_attach(stream_id: str, request: Request):
    """attach 到已创建的 chat 流 (I2),NDJSON 推送事件。

    从 ``app.state.streams[stream_id].queue`` 拉事件,序列化 NDJSON 返回。
    多次同时 attach 到同一 streamId 会**共享**queue(广播) — 不会触发新的 LLM 调用。
    客户端断开时(CancelledError)不取消后台 producer(已消耗的 token 不浪费),
    producer 跑完后会通过 SENTINEL 关闭此流。

    Args:
        stream_id: create 端点返回的 streamId
        request: FastAPI Request

    Returns:
        StreamingResponse(media_type=application/x-ndjson)

    Raises:
        HTTPException 404: streamId 不存在或已过期
    """
    registry: StreamRegistry = request.app.state.streams
    entry = registry.get(stream_id)
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"chat stream not found or expired: {stream_id}",
        )
    logger.info(f"chat-stream attach: streamId={stream_id} status={entry.status}")

    async def event_generator():
        try:
            while True:
                try:
                    # 短 timeout 让多消费者场景下能感知 producer done 状态。
                    # SENTINEL 只入队一次,只有一个 attach 能拿到 — 其余
                    # attach 必须靠 status 字段判断流是否结束。
                    event = await asyncio.wait_for(entry.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:  # noqa: UP041 — Py3.10 中 asyncio.TimeoutError ≠ built-in TimeoutError
                    # 1s 内没新事件 — 检查 producer 是否已结束
                    # 注: Python 3.10 中 asyncio.TimeoutError 不等同内置 TimeoutError
                    if entry.status in ("done", "failed"):
                        break
                    continue
                if event is SENTINEL:
                    break
                yield _ndjson(event)
        except asyncio.CancelledError:
            # 客户端断开 — 后台 producer 继续跑,队列中未消费的事件留给下次 attach
            logger.info(f"chat-stream attach cancelled: streamId={stream_id}")
            return

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")


def _ndjson(d: dict) -> str:
    """序列化为 NDJSON 行（以 \\n 结尾）。

    Args:
        d: 可被 json.dumps 序列化的字典

    Returns:
        单行 JSON 字符串，末尾带换行符
    """
    return json.dumps(d, ensure_ascii=False) + "\n"


@router.post("/interrupt")
@with_db_lock
def interrupt(data: Optional[InterruptRequest] = Body(default=None)):
    """中断 Agent（P0-2: 经 stream_id 定位真实运行的 agent）"""
    stream_id = data.stream_id if data is not None else None
    target = interrupt_stream(stream_id)
    return {"status": "ok", "target": target}


# ==================== 消息 API ====================


@router.get("/sessions/{session_id}/messages", response_model=List[dict])
@with_db_lock
def get_messages(session_id: str, limit: int = 100, offset: int = 0):
    """获取会话消息"""
    repo = MessageRepository()
    messages = repo.get_by_session(session_id, limit=limit, offset=offset)
    return [m.to_dict() for m in messages]


# ==================== 进化系统 API ====================


@router.get("/evolution/logs", response_model=List[EvolutionLogResponse])
@with_db_lock
def list_evolution_logs(limit: int = 50, offset: int = 0):
    """获取进化日志列表"""
    try:
        db = get_database()
        return get_evolution_logs(db, limit=limit, offset=offset)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ==================== Background Review (Background Review) ====================
#
# /learn: 用户显式触发当前会话的 review,产生技能草案候选。
# 与 Task 8 的自动 signal detection (complex_turn / low_success_rate)
# 互补 — 本端点是 manual trigger,trigger_type="explicit_learn"。


class LearnRequest(BaseModel):
    """POST /learn 请求体。

    - session_id: 要 review 的会话 (必填)
    - prompt: 用户附加的提示,传给 LLM 作为 review 上下文 (可选)
    """

    session_id: str
    prompt: str = ""


@router.post("/learn")
@with_db_lock
def learn_from_session(request: LearnRequest):
    """User explicitly triggers review of current conversation.

    Enqueues a review event with trigger_type="explicit_learn".
    The background worker will pull it, load conversation history,
    and generate a skill draft via ReviewService.

    - 200 + ``{"status": "queued", "message": "..."}``
    - 404 — session_id does not exist
    - 422 (FastAPI 自动) — session_id 缺失

    .. note:: fix/security-perf-quickwins §1.3a d (2026-08-09)
        The route enqueues ``messages: []`` as a placeholder and the
        background worker loads the full conversation history from
        ``session_id`` via ``MessageRepository.get_by_session`` before
        invoking ``ReviewService``. This keeps the HTTP request body
        small while still giving the LLM a complete context to summarize.
    """
    # I-2 fix: validate session existence before enqueueing — avoids
    # wasting LLM tokens on reviews for non-existent sessions.
    session_repo = SessionRepository()
    if session_repo.get(request.session_id) is None:
        raise HTTPException(
            status_code=404,
            detail=f"Session not found: {request.session_id}",
        )

    review_queue = get_review_queue()
    review_queue.enqueue(
        trigger_type="explicit_learn",
        session_id=request.session_id,
        context={
            # fix/security-perf-quickwins (2026-08-09, §1.3a d): the worker
            # now loads conversation history from MessageRepository before
            # invoking ReviewService (see backend/skills/review_queue.py
            # _process_event). The empty placeholder below is intentional —
            # it signals to the worker that loading is required, and also
            # keeps the request body small (no point shipping N messages
            # over HTTP when the worker can read them from the DB).
            "messages": [],
            "user_prompt": request.prompt,
        },
    )
    logger.info(
        "/learn: enqueued explicit_learn for session=%s",
        _safe_log_field(request.session_id),
    )
    return {"status": "queued", "message": "Review started"}


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


@router.post("/skill-drafts/{draft_id}/approve")
@with_db_lock
def approve_skill_draft(draft_id: str):
    """User approves skill draft → write to SKILL.md on disk.

    - 200 + ``{"status": "approved", "skill_name": ..., "draft_id": ...}``
    - 400 — invalid skill name (path traversal / separators / empty);
      draft status NOT updated (follow-up: regenerate or edit the draft)
    - 404 — draft not found
    - 500 — file-system write failure (status NOT updated)
    """
    draft_store = get_skill_draft_store()
    draft = draft_store.get(draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    # I-1 fix: validate name *before* touching the filesystem so that
    # drafts with un-writable names (LLM hallucinations like "../foo")
    # get a clean 400 instead of an opaque 500 OSError.
    from backend.skills.review_service import ReviewService

    try:
        ReviewService._validate_skill_name(draft.name)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid skill name: {exc}",
        ) from exc

    try:
        skill_loader = get_skill_loader()
        skill_loader.write(draft.name, draft.content)
    except ValueError as exc:
        # Skill loader rejected the name (caught separately from OSError
        # so the route can return 400 for invalid names vs 500 for FS errors).
        logger.error("Failed to write skill %s: %s", draft.name, exc)
        raise HTTPException(
            status_code=400, detail=f"Failed to write skill: {exc}"
        ) from exc
    except (PermissionError, OSError) as exc:
        logger.error("Failed to write skill %s: %s", draft.name, exc)
        raise HTTPException(
            status_code=500, detail=f"Failed to write skill: {exc}"
        ) from exc

    draft_store.update_status(draft_id, "approved")
    return {"status": "approved", "skill_name": draft.name, "draft_id": draft_id}


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
        raise HTTPException(status_code=404, detail="Draft not found")

    draft_store.update_status(draft_id, "rejected")
    return {"status": "rejected", "draft_id": draft_id}


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


# ==================== 记忆 API ====================

# get_memory_manager 从 backend.memory 导入（全局单例）


class MemorySearchRequest(BaseModel):
    query: str
    memory_type: Optional[str] = None

    limit: int = 20


class MemorySaveRequest(BaseModel):
    content: str
    memory_type: str = "episodic"
    importance: int = 5
    tags: List[str] = []


class MemoryDeleteRequest(BaseModel):
    id: str


@router.get("/memory/search")
@with_db_lock
def search_memory(query: str, limit: int = 20, type: Optional[str] = None):
    """搜索记忆"""
    try:
        mm = get_memory_manager()
        return mm.search_memories(query=query, memory_type=type, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/save")
@with_db_lock
def save_memory(data: MemorySaveRequest):
    """保存记忆"""
    try:
        mm = get_memory_manager()
        memory_id = mm.memorize(
            content=data.content,
            memory_type=data.memory_type,
            importance=data.importance,
            tags=data.tags,
        )
        return {"id": memory_id, "status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/memory/delete")
@with_db_lock
def delete_memory(data: MemoryDeleteRequest):
    """删除记忆"""
    try:
        mm = get_memory_manager()
        # 尝试从所有类型中删除
        for mtype in ["episodic", "semantic"]:
            if mm.delete_memory(data.id, mtype):
                return {"status": "ok"}
        raise HTTPException(status_code=404, detail="记忆不存在")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/memory/list")
@with_db_lock
def list_memories(page: int = 1, page_size: int = 20, type: Optional[str] = None):
    """获取记忆列表"""
    try:
        mm = get_memory_manager()
        if type == "episodic":
            results = mm.episodic.get_recent(limit=page_size)
        elif type == "semantic":
            results = mm.semantic.get_recent(limit=page_size)
        else:
            results = mm.episodic.get_recent(limit=page_size)
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Wave 2 P1-4 (2026-08-14): 编排 run 读取/resume/计划更新端点挂载。
# orch_routes 用独立 APIRouter(prefix="/orch")，经 include_router 并入
# legacy_router → main.py 挂载后最终前缀 /api/v1/orch。
router.include_router(orch_routes_router)

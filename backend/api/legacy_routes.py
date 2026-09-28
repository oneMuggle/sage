# ruff: noqa: UP006, UP007, UP035 — pydantic v1 + Python 3.8 兼容：
# pydantic v1 resolve_annotations 用 eval() 处理 forward refs，
# eval 在 Python 3.8 上无法解析 PEP 585 (list[X]) 和 PEP 604 (X | Y)，
# 所以本文件保留 typing.List/Optional/Union 写法
"""
API 路由定义
"""

from __future__ import annotations

import asyncio
import sys

# I5: 流式视觉延迟 — DONE 事件的 content 拆成 chunk 逐个入队,
# 让前端能逐字渲染 (避免 LLM 一次返回完整字符串时 "砰一下" 全显示)。
# 真 LLM streaming 需要 OpenAI stream=true + adapter 支持 tool_calls (大改),
# 先用这个 producer 端的 fake stream 解决 90% 的视觉体验。
_STREAMING_CHUNK_SIZE = 6
_STREAMING_CHUNK_DELAY_S = 0.04
import json
import logging
import os
import time
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.api.chat_request_policy import (  # C2b: 唯一实现，原五份逐字重复收编
    _check_request_within_window,
    _resolve_effective_window,
)
from backend.api.chat_stream_registry import (
    SENTINEL,
    SessionBusyError,
    StreamEntry,
    StreamRegistry,
)
from backend.api.orch_routes import router as orch_routes_router
from backend.chat.executors import resolve_attachments
from backend.chat.history_context import (
    build_request_messages,
    build_request_messages_from_events,
    history_token_budget,
)
from backend.chat.sources_extractor import extract_sources_from_tool, merge_sources
from backend.core.errors import LLMError
from backend.core.legacy.agent import SageAgent
from backend.data import answer_version_repo as answer_versions
from backend.data.database import get_database
from backend.data.session_repo import (
    Message as DbMessage,
    MessageRepository,
    SessionRepository,
)
from backend.office.chat_refs import authorize_chat_office_request
from backend.office.workspace_errors import (
    WorkspaceDocumentNotFoundError,
    WorkspaceNotBoundError,
    WorkspacePathMismatchError,
    WorkspaceSessionNotFoundError,
)
from backend.orchestration.chat_dispatcher import (
    _classify_orchestration_mode,
)
from backend.orchestration.llm_factory import load_llm_config_for_chat
from backend.scheduler import get_evolution_logs
from backend.services.scheduler import get_scheduler_service
from backend.skills.review_queue import get_review_queue
from backend.utils import py_compat

logger = logging.getLogger(__name__)

router = APIRouter()


def _event_repo():
    """SE2: SessionEventRepository 惰性构造（避免模块级 import 环）。"""
    from backend.data.session_event_repo import SessionEventRepository

    return SessionEventRepository()


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
from backend.data.database import (  # noqa: F401 — _SQLITE_LOCK 由测试与文档语义保留
    _SQLITE_LOCK,
    make_with_db_lock,
)


def with_db_lock(func):
    """装饰器：把 sync 函数包在全局 `_SQLITE_LOCK` 内,串行化 SQLite 访问。

    适用对象：34 个降级为 `def` 的 FastAPI handler —— 它们跑在 anyio threadpool,
    内部 `SessionRepository`/`MessageRepository` 等 sync 调用必须串行访问单连接。
    D3 (P6): 实现统一收敛到 ``database.make_with_db_lock`` (约束与解法
    见 orch_routes.with_db_lock docstring)。
    """
    return make_with_db_lock(globals())(func)






# ==================== Pydantic 模型 ====================
#: PM1 (round8): 计划模式 system 指令 —— 只读调研 + 结构化计划产出；
#: 执行被权限门（per-run READ_ONLY）与指令双重约束，批准后由前端衔接。
#: 计划前置 Round (2026-09-19): 追加"歧义先澄清"——对照 Claude Code plan
#: mode，调研之前先把范围/格式/验收标准的歧义问清（≤2 问），未答按合理
#: 默认并在计划中写明假设。
_PLAN_MODE_DIRECTIVE = (

    "\n\n【计划模式】当前为计划模式：你只能做只读调研（读文件/搜索/列目录等），"
    "不能写文件、执行命令或出网修改任何状态。"
    "若目标存在会显著影响方案的歧义（范围/交付格式/验收标准），先用 "
    "ask_user_question 向用户澄清（至多 2 个问题）；用户未回答则按合理默认值"
    "执行，并在计划中写明关键假设。请基于调研输出一份结构化执行计划，"
    "格式：\n## 目标\n## 分步计划\n（每步：做什么 / 涉及哪些文件或命令 / 预期结果）\n"
    "## 验收标准\n## 风险与注意\n计划要具体到可直接执行。用户批准计划后，"
    "你将在后续消息中被要求严格按计划执行——本轮不要尝试执行任何计划步骤。"
)







# C1e (DSH 对标 R27): 13 个 legacy 请求/响应模型迁出至 legacy_models.py
# （纯物理拆分；本模块再导出保持既有 import 路径——含测试——不变）。
from backend.api.legacy_models import (  # noqa: F401 — 再导出面
    AgentCreate,
    AgentToggle,
    AgentUpdate,
    ChatErrorInfo,
    ChatRequest,
    ChatResponse,
    EvolutionLogResponse,
    InterruptRequest,
    LearnRequest,
    MessageResponse,
    SessionCreate,
    SessionUpdate,
    SteerRequest,
)

# ==================== 依赖注入 ====================


def get_session_repo() -> SessionRepository:
    return SessionRepository()


# C2c (DSH 对标 R28): 流状态注册表 + 中断函数迁出至 chat_stream_state.py
# （本模块再导出——orch_routes 经 legacy_routes 导入 _RUN_CONFIRM_EVENTS
#  的既有路径不变；对注册表只做原地变异，跨模块共享同一对象即正确）。
from backend.api.chat_stream_state import (  # noqa: F401 — 再导出面
    _ACTIVE_STREAMS,
    _PENDING_RUN_CANCELLATIONS,
    _RUN_CONFIRM_EVENTS,
    interrupt_run,
    interrupt_stream,
)

# C2f (DSH 对标 R31): 聊天流支撑函数迁出至 chat_stream_support.py
# （本模块再导出：调用方在 producer 内，测试 patch legacy_routes 命名空间
#  的既有 seam 不变）。
from backend.api.chat_stream_support import (  # noqa: F401 — 再导出面
    _CHAT_IMAGE_MAX_BYTES,
    _CHAT_IMAGE_MAX_COUNT,
    _build_orchestration_dispatcher,
    _clear_working_segment,
    _finalize_orch_run,
    _memory_used_event_from_hits,
    _ndjson,
    _validate_chat_images,
)


def get_agent() -> SageAgent:
    return SageAgent(scheduler_service_getter=get_scheduler_service)


# ==================== 会话 API ====================
#
# S7-3 (P7): 会话 CRUD 与会话级模型覆盖 7 端点已拆至
# backend/api/legacy_session_routes.py (复用本模块 router 对象,
# 装配顺序见 main.py)。本文件保留 compact/fork 等与流/LLM 装配
# 耦合的会话端点。


# ---------------------------------------------------------------------------
# G5 (2026-09-06): 会话级模型覆盖 —— {session_id: model_id} KV
# ---------------------------------------------------------------------------



# C2d (DSH 对标 R29): 会话压缩/分叉/检查点/记忆提取五函数 + _safe_log_field
# 迁出至 chat_session_lifecycle.py（本模块再导出——legacy_session_routes
# 经 _legacy_routes._persist_compaction 等模块属性访问与测试导入路径不变）。
from backend.api.chat_session_lifecycle import (  # noqa: F401 — 再导出面
    _auto_checkpoint_if_enabled,
    _build_compaction_llm_callable,
    _compact_in_progress,
    _extract_legacy_chat_memory,
    _maybe_auto_compact_session,
    _persist_compaction,
    _run_db_sync,
    _safe_log_field,
)

# ==================== 消息 API ====================
# C2e (DSH 对标 R30): Agent API 迁出至 legacy_agent_routes.py
# （纯物理拆分，路径/行为零变更；与 C1a/b/c/d 同款 include 模式）。
from backend.api.legacy_agent_routes import (  # noqa: F401 — 经 include 挂载
    _VALID_AGENT_ROLES,  # noqa: F401 — 再导出（测试经 legacy_routes 导入）
    router as legacy_agent_routes_router,
)

router.include_router(legacy_agent_routes_router)

# C1 第二刀 (DSH 对标 R15): 技能 API 迁出至 legacy_skills_routes.py
# （纯物理拆分，路径/行为零变更；与 orch_routes 同款 include 模式）。
from backend.api.legacy_skills_routes import (  # noqa: F401 — skills handler 引用 _get_skill_adapter
    _get_skill_adapter,
    router as legacy_skills_routes_router,
)

router.include_router(legacy_skills_routes_router)

# C1d (DSH 对标 R25): settings / preferences API 迁出至 legacy_settings_routes.py
# （纯物理拆分，路径/行为零变更；与 C1a/b/c 同款 include 模式）。
from backend.api.legacy_settings_routes import (  # noqa: F401 — 经 include 挂载
    router as legacy_settings_routes_router,
)

router.include_router(legacy_settings_routes_router)


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
                # temperature=0 是合法值 (确定性输出), 不能用 or 兜底
                "temperature": 0.7 if data.temperature is None else data.temperature,
            }
            logger.info(
                f"[REQ {request_id}] using custom LLM config: model={_safe_log_field(llm_config['model'])}"
            )

        # 2026-07-30: chat 默认加载 primary profile,让 profile.tools 白名单生效
        # (memory_manager 之类窄权限 agent 才不会拿到 list_dir/read_file 全部工具)
        agent = SageAgent(
            agent_id=data.agent_id or "primary",
            scheduler_service_getter=get_scheduler_service,
        )
        # G5 (2026-09-06): 请求未显式带端点配置时，用「全局端点 + 会话覆盖/
        # profile 模型」解析 —— 会话里切换模型不影响其他会话与全局设置。
        if llm_config is None:
            profile_model = (
                (agent.profile or {}).get("model_config") or {}
            ).get("model")
            llm_config = load_llm_config_for_chat(
                session_id=data.session_id, profile_model=profile_model
            )
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

    # C2: 原位重新生成只允许会话最后一轮 (在占用 stream slot 之前拒绝)
    if data.regenerate_of and not await _run_db_sync(
        answer_versions.AnswerVersionRepository().is_last_turn, data.session_id, data.regenerate_of
    ):
        raise HTTPException(
            status_code=409,
            detail={"type": "anchor_not_last", "message": "只能原位重新生成会话的最后一轮"},
        )

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
        # live-events P2 (2026-09-07) / P1 todo 接线 / S7 产物 / right-panel R5:
        # 四路事件推送原为四个内联闭包（会话过滤 + put_nowait + 静默降级），
        # C2a 收敛为 StreamEventSink（见 chat_stream_sinks.py，行为逐字节等价）。
        # producer 与各事件源同一事件循环,put_nowait 安全;finally 注销
        # （sink 持有 queue 引用,不注销会向已关闭的流推送 / 随全局表泄漏）。
        from backend.api.chat_stream_sinks import StreamEventSink

        sink = StreamEventSink(entry.queue, data.session_id)
        sink.register()
        # B4 (2026-09-09): 流启动时推送持久化的 todo 快照 —— 此前 todo 只在
        # todo_write 写入时推送，重启/重开会话后任务板为空。get() 命中
        # session_todos 持久层（缓存 miss 回填），恢复上次任务清单。
        await sink.push_persisted_todo()
        try:
            # P0-4 (2026-08-20): 终态变量前置到 try 顶部 —— finally 无条件读取
            # 它们，若留在数百行之后声明，早期异常（如 resolve_attachments 抛错、
            # CancelledError）会让 finally 触发 UnboundLocalError，既掩盖原始异常
            # 又跳过后续的 reset_tool_context 清理。
            done_content: Optional[str] = None
            run_outcome = "failed"
            # S1 (2026-09-06): 失败原因摘要 —— finally 落库 sessions.last_error。
            _producer_error: Optional[str] = None

            # S1 (2026-09-06): 会话运行态落库（running）。写库点收敛两处：
            # 此处置 running，finally 落终态；失败 fail-open 只 debug，不影响主流。
            # /btw 等伪会话（sessions 表无行）update 零命中，静默即可。
            # 刻意 new 一个独立实例而非用下方 producer 内的 session_repo 变量 ——
            # 那个变量在数百行之后才绑定，早期失败路径 finally 会 UnboundLocalError。
            try:
                await _run_db_sync(
                    SessionRepository().update_run_status, data.session_id, "running"
                )
            except Exception as status_err:  # noqa: BLE001 — fail-open
                logger.debug("会话运行态(running)写入失败: %s", status_err)

            # ===== B-2 (round5 批次 B): 发送前自动快照 BEGIN =====
            # 偏好 auto_checkpoint 非显式 "0"（缺省=开）且会话绑定工作区时, run
            # 开始前打一份 checkpoint（一键回滚安全网）。zip 是秒级同步操作, 丢 executor
            # 跑, 不阻塞事件循环与流启动; 全程 fail-open（函数内部已兜底）。
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(
                    None, _auto_checkpoint_if_enabled, data.session_id
                )
            except Exception as auto_cp_err:  # noqa: BLE001 — fail-open
                logger.debug(
                    "[B-2] 自动快照调度失败(忽略): %s", auto_cp_err
                )
            # ===== B-2 自动快照 END =====

            llm_config = None
            if data.api_key and data.api_url:
                llm_config = {
                    # 修: provider 不再硬写,从前端请求透传;
                    # 默认 "custom" 保留向后兼容(老客户端/无 provider 字段)
                    "provider": data.provider or "custom",
                    "api_key": data.api_key,
                    "base_url": data.api_url,
                    "model": data.model or "gpt-3.5-turbo",
                    # temperature=0 是合法值 (确定性输出), 不能用 or 兜底
                    "temperature": 0.7 if data.temperature is None else data.temperature,
                }
                # 推理参数:None 时不传,避免污染老 LLM
                if data.reasoning_effort is not None:
                    llm_config["reasoning_effort"] = data.reasoning_effort
                if data.thinking_budget is not None:
                    llm_config["thinking_budget"] = data.thinking_budget
                # D-1 (round5 批次 D): 偏好 fallback_model —— 主模型重试耗尽
                # 后同 endpoint 降级; 未配置时为 None（LLMConfig 默认不降级）
                from backend.data.settings_repo import SettingsRepository

                fallback_pref = SettingsRepository().get("fallback_model")
                if fallback_pref and fallback_pref != (data.model or ""):
                    llm_config["fallback_model"] = fallback_pref
                # Task 5: resolve endpoint_id for usage attribution
                # Priority: request data.endpoint_id > persisted settings
                if data.endpoint_id:
                    # Request provided endpoint_id directly — use it
                    llm_config["endpoint_id"] = data.endpoint_id
                else:
                    # Fallback to persisted settings
                    try:
                        from backend.data.settings_canonicalizer import to_camel
                        _raw_settings = SettingsRepository().get_json("app_settings")
                        if isinstance(_raw_settings, dict):
                            _camel = to_camel(_raw_settings)
                            _eps = _camel.get("endpoints") or []
                            _sel = (_camel.get("modelSelections") or {}).get("chatModel") or {}
                            _ep_id = _sel.get("endpointId")
                            if _ep_id:
                                for _ep in _eps:
                                    if isinstance(_ep, dict) and _ep.get("id") == _ep_id:
                                        llm_config["endpoint_id"] = _ep_id
                                        break
                    except Exception:
                        pass  # fail-open: endpoint_id is best-effort
                logger.info(
                    f"[REQ {request_id}] /chat/stream producer using custom LLM: "
                    f"model={_safe_log_field(llm_config['model'])}"
                )

            # ===== L11 user_prompt_submit 钩子 BEGIN (批次 C-2) =====
            # 用户自定义钩子可在消息进入 agent 循环前检查/拦截 (deny)。
            # fail-open: 钩子故障视为放行。deny → failed 事件, 不消耗 LLM。
            try:
                from backend.data.settings_repo import SettingsRepository
                from backend.hooks.config import load_hooks
                from backend.hooks.runner import run_event_hooks

                l11_hooks = load_hooks(SettingsRepository())
                if l11_hooks:
                    l11_outcome = await run_event_hooks(
                        l11_hooks,
                        "user_prompt_submit",
                        "",  # 无工具名; matcher 仅 "*" 对本事件有意义
                        {
                            "hook_event_name": "user_prompt_submit",
                            "prompt": data.message,
                            "session_id": data.session_id,
                        },
                    )
                    if l11_outcome.denied:
                        logger.info(
                            "[REQ %s] user_prompt_submit 钩子拦截: %s",
                            request_id,
                            l11_outcome.reason,
                        )
                        # 2026-09 (同步 #1100): 失败信封统一 dict {type, message}
                        await entry.queue.put(
                            {
                                "state": "failed",
                                "error": {
                                    "type": "prompt_blocked_by_hook",
                                    "message": l11_outcome.reason
                                    or "该消息已被本地钩子拦截",
                                },
                            }
                        )
                        return
            except Exception as l11_prompt_err:
                logger.debug(
                    f"[REQ {request_id}] user_prompt_submit hooks skipped: {l11_prompt_err}"
                )
            # ===== L11 user_prompt_submit 钩子 END =====

            # F5 花费限额 (批次 C): 今日已花费(持久化估算, 重启不丢)达到
            # 限额时拒绝本次聊天。限额 0/未配置 = 不限。DB 故障 fail-open
            # (today_cost_usd 返回 0 → 永不拦截)。注: run_id/dispatcher 前置
            # 初始化 —— 此处可能提前 return, finally 无条件读取它们 (P0-4)。
            run_id: Optional[str] = None
            dispatcher = None
            try:
                from backend.data.settings_repo import SettingsRepository
                from backend.services.usage_tracker import usage_tracker as _usage_tracker

                # win7 惯例 (PR A §1.2): 同步 DB 读经 _run_db_sync; today_cost_usd
                # 内部自带 _SQLITE_LOCK, 不能再包 _run_db_sync(非重入死锁),
                # 改走裸 executor 线程。
                _raw_limit = await _run_db_sync(
                    SettingsRepository().get, "spend_limit_usd"
                )
                _spend_limit = float(_raw_limit) if _raw_limit and _raw_limit.strip() else 0.0
            except Exception as limit_read_err:
                logger.debug(f"[REQ {request_id}] 花费限额读取失败(视为不限): {limit_read_err}")
                _spend_limit = 0.0
            if _spend_limit > 0:
                _today_cost = await asyncio.get_running_loop().run_in_executor(
                    None, _usage_tracker.today_cost_usd
                )
                if _today_cost >= _spend_limit:
                    logger.warning(
                        "[REQ %s] 花费限额拦截: today=%.4f USD >= limit=%.2f USD",
                        request_id,
                        _today_cost,
                        _spend_limit,
                    )
                    # S1: finally 落库 failed + 原因
                    _producer_error = "今日花费已达限额（spend_limit_exceeded）"
                    # 2026-09 修复: 失败信封统一为 dict {type, message} ——
                    # 与 _run_producer 的 LLMError.to_dict() 同构, 前端已双态兼容。
                    await entry.queue.put(
                        {
                            "state": "failed",
                            "error": {
                                "type": "spend_limit_exceeded",
                                "message": _producer_error,
                            },
                        }
                    )
                    return

            agent = SageAgent(
                agent_id=data.agent_id or "primary",
                scheduler_service_getter=get_scheduler_service,
            )
            # PM1 (round8): 计划模式 per-run 只读门 —— 实例级 enforcer 注入
            # （run_loop 对非空 permission_enforcer 直接复用），override 为
            # READ_ONLY；全局 settings 的 permission_mode 不动。失败降级为
            # 仅指令约束（门禁是纵深防御的第二层，缺一层不阻塞）。
            if data.plan_mode:
                try:
                    from backend.tools.permissions import PermissionMode

                    plan_enforcer = agent._build_permission_enforcer()
                    plan_enforcer.force_mode(PermissionMode.READ_ONLY)
                    agent.permission_enforcer = plan_enforcer
                except Exception as pm_exc:  # noqa: BLE001 — 降级不阻塞
                    logger.warning("计划模式只读门注入失败（仅指令约束）: %s", pm_exc)
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

            # PM1 (round8): 单 agent 计划模式 —— 只读调研 + 计划产出指令；
            # 与编排互斥（计划模式在主对话内调研，不派子代理），批准后由
            # 前端经普通消息衔接执行。
            if data.plan_mode:
                system_content += _PLAN_MODE_DIRECTIVE

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
            if data.plan_mode:
                # PM1: 计划模式与编排互斥 —— 主对话内只读调研。
                mode = "single"
            elif data.plan_override:
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
            if mode == "multi":
                from backend.orchestration.chat_dispatcher import _ACTIVE_DISPATCHERS
                from backend.orchestration.planner import Planner
                from backend.orchestration.task_registry import TaskRegistry
                from backend.orchestration.team_registry import TeamRegistry
                from backend.tools.replan_tool import (
                    AddTaskToPlanTool,
                    CancelPendingTaskTool,
                    UpdatePendingTaskTool,
                )
                from backend.tools.subagent_tool import (
                    CollectSubagentsTool,
                    DispatchSubagentsTool,
                )

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
                            # 计划前置 (2026-09-19, docs/plans/2026-09-19_
                            # orch-plan-preflight-plan.md): 拆解前先澄清需求
                            # （QuestionGate 结构化提问）+ 只读侦察（事实清单），
                            # 产出注入 planner context。内部任何失败降级为
                            # None —— 等价于现状 decompose_request(message)。
                            from backend.orchestration.plan_preflight import (
                                run_plan_preflight,
                            )

                            preflight_context = await run_plan_preflight(
                                data.message, emit=entry.queue.put
                            )
                            plan = await Planner(
                                task_registry=TaskRegistry(),
                                team_registry=TeamRegistry(),
                                llm_client=build_llm_client_from_settings(),
                            ).decompose_request(data.message, context=preflight_context)
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
                                # 层级透传（override 可带 parent；depth 由下方
                                # 归一化统一重算，客户端值不作权威）。
                                "parent_task_id": it.get("parent_task_id"),
                            }
                            for it in data.plan_override
                        ]
                    else:
                        # 任务层级（spec 2026-09-19）：Task 的 parent 是真实
                        # task_id，计划项用 t1..tN 编号 → 需要索引映射后透传，
                        # 否则前端树与 dispatcher 都拿不到父子关系。
                        _index_by_task_id = {
                            t.task_id: f"t{i}"
                            for i, t in enumerate(plan_tasks, 1)
                        }
                        plan_items = [
                            {
                                "task_id": f"t{i}",
                                "agent_id": t.parameters.get("agent_hint", "primary"),
                                "goal": t.description or t.name,
                                "depends_on": list(t.blocked_by),
                                "parent_task_id": (
                                    _index_by_task_id.get(t.parent_task_id)
                                    if getattr(t, "parent_task_id", None)
                                    else None
                                ),
                                "depth": int(getattr(t, "depth", 0) or 0),
                            }
                            for i, t in enumerate(plan_tasks, 1)
                        ]
                    # 层级归一化（spec 2026-09-19）：depth 以后端计算为准，
                    # override 传入值不采信；坏引用/超深 fail-open 剪枝为根。
                    try:
                        from backend.orchestration.plan_hierarchy import (
                            normalize_task_hierarchy,
                        )

                        plan_items = normalize_task_hierarchy(plan_items)
                    except Exception as hierarchy_err:  # noqa: BLE001 — 降级铁律
                        logger.warning(
                            "计划层级归一化失败，回落无层级: %s", hierarchy_err
                        )
                        plan_items = [
                            {
                                k: v
                                for k, v in item.items()
                                if k not in {"depth", "parent_task_id"}
                            }
                            for item in plan_items
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
                        # O3 (2026-09-08): 会话归因 —— 子代理用量计入本会话。
                        session_id=data.session_id,
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
                    # BD (round12): 后台派发的收集侧工具（与 dispatch 配对）。
                    agent.tool_registry.register(CollectSubagentsTool(dispatcher))
                    if (
                        agent.profile is not None
                        and agent.profile.get("tools") is not None
                    ):
                        agent.profile["tools"].append("dispatch_subagents")
                        # BD (round12): collect 与 dispatch 成对加入白名单。
                        agent.profile["tools"].append("collect_subagents")
                    # RP1 (round34, 2026-09-19): re-plan 工具族 —— conductor 在
                    # run 中动态调整计划（改 goal / 取消任务 / 加任务并声明依赖）。
                    # 与 dispatch_subagents 同一 tool-toggle 门：仅 multi 模式注册。
                    agent.tool_registry.register(UpdatePendingTaskTool(dispatcher))
                    agent.tool_registry.register(CancelPendingTaskTool(dispatcher))
                    agent.tool_registry.register(AddTaskToPlanTool(dispatcher))
                    if (
                        agent.profile is not None
                        and agent.profile.get("tools") is not None
                    ):
                        agent.profile["tools"].append("update_pending_task")
                        agent.profile["tools"].append("cancel_pending_task")
                        agent.profile["tools"].append("add_task_to_plan")
                    # O4 (2026-09-08): observe_subagents 注册 —— conductor 主动
                    # 轮询子任务进度的只读工具（此前类已实现但从未接线，生产
                    # 不可用）。快照通道未装配时降级不注册，不阻塞编排。
                    try:
                        from backend.api.orch_run_control import get_snapshot_store
                        from backend.tools.observe_tool import ObserveSubagentsTool

                        snapshot_store = get_snapshot_store()
                        if snapshot_store is not None:
                            agent.tool_registry.register(
                                ObserveSubagentsTool(
                                    snapshot_store, default_run_id=run_id
                                )
                            )
                            if (
                                agent.profile is not None
                                and agent.profile.get("tools") is not None
                            ):
                                agent.profile["tools"].append("observe_subagents")
                    except Exception as obs_exc:  # noqa: BLE001 — 观测降级
                        logger.warning(
                            "observe_subagents 注册失败（跳过）: %s", obs_exc
                        )
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
                        # RT11 (round7): 失败处理指令 —— 此前 conductor 只被告知
                        # "必须全部执行完"，失败子任务无任何再规划指引，唯一出路
                        # 是 LLM 对聚合文本的自由裁量。
                        + "\n\n子任务失败时的处理方式：阅读该任务的失败原因文本，"
                        "判断是可修复错误（参数不当、依赖文件缺失、路径错误等）还是"
                        "不可行任务。可修复的，调整 goal 描述或改派更合适的 agent 重新"
                        "派发该工作（可派发新任务，或用 retry_of 重派并继承现场）；"
                        "不可行的，在最终汇总中说明原因。"
                        "不要原样重派已经失败的同一任务。"
                        # BD4 (round15): 后台工作流指引 —— background=true 派发后
                        # 立即返回，期间可先做其他工作，再 collect_subagents 收取。
                        # BD5 (round16): 补充非阻塞快照与提前汇总策略。
                        + "\n\n当某些子任务耗时较长而你希望先推进其他工作时，可在 "
                        "dispatch_subagents 传 background=true 后台派发（立即返回），"
                        "期间执行你自己的其他工具调用，之后调用 collect_subagents "
                        "获取聚合结果；collect 超时只表示还没跑完，任务板仍在推进，"
                        "可再次 collect。"
                        "collect 可传 wait=false 立即获取各子任务当前状态与结果"
                        "预览快照——若已有信息足以支撑最终结论，可据此提前汇总，"
                        "无需等待全部子任务完成。"
                        # RP1 (round34, 2026-09-19): re-plan 工具族指引 ——
                        # 此前 conductor 只能靠上段"失败处理指令"做任务级微调，
                        # 无法主动调整计划结构（改目标/取消/加任务）。
                        + "\n\n发现原计划不再适用时可主动调整计划，有三个工具："
                        "\n- update_pending_task：修改尚未派发任务的 goal 或执行"
                        "角色，参数 task_id 必填、goal 与 agent_id 至少给一个。"
                        "\n- cancel_pending_task：取消不再需要的任务，参数 task_id "
                        "必填、reason 可选。未派发的直接移出计划，已派发仍在排队的"
                        "会被跳过，运行中的会被软中断；取消后请勿重派该任务。"
                        "\n- add_task_to_plan：把新发现的工作加入计划，参数 task_id "
                        "/ goal / agent_id 必填，depends_on 可选且只能引用已存在的"
                        "task_id。添加后调用 dispatch_subagents 派发即可执行。"
                        "\n任务失败时不要原样重派 —— 先判断该改目标、换角色、取消，"
                        "还是补充新任务。"
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
                    # Fix #3 (2026-09-06): 用户确认门控 —— producer 在此暂停,
                    # 等待前端调用 POST /orch/runs/{id}/confirm（用户点击
                    # "开始执行"）。cancel_run 也会唤醒（以取消状态退出）。
                    # 超时自动取消,避免 producer 永久挂起。
                    # SAGE_ORCH_CONFIRM_TIMEOUT: 等待秒数（默认 600）。测试套件
                    # 里 5 个 multi-mode 集成测试不 confirm,曾各挂满 600s 导致
                    # CI Backend job 从 ~6min 涨到 ~77min（#1587 起的回归）;
                    # tests/conftest.py 将其设为 1s,测试走超时取消路径秒过。
                    confirm_timeout = float(
                        os.environ.get("SAGE_ORCH_CONFIRM_TIMEOUT", "600")
                    )
                    confirm_event = asyncio.Event()
                    _RUN_CONFIRM_EVENTS[run_id] = confirm_event
                    try:
                        try:
                            await asyncio.wait_for(
                                confirm_event.wait(), timeout=confirm_timeout
                            )
                        except asyncio.TimeoutError:  # noqa: UP041 — py3.8: asyncio.TimeoutError 不等于 builtin TimeoutError (3.11 才统一)
                            logger.warning(
                                "编排确认超时 (%ss)，自动取消 run %s",
                                confirm_timeout,
                                run_id,
                            )
                            from backend.data.orch_run_repo import OrchRunRepository

                            OrchRunRepository().update_status(run_id, "cancelled")
                            await entry.queue.put(
                                {
                                    "state": "task_review",
                                    "run_id": run_id,
                                    "verdict": "cancelled",
                                    "summary": (
                                        "编排计划确认超时（"
                                        f"{confirm_timeout:g} 秒无响应），已自动取消"
                                    ),
                                    "assertions": [],
                                }
                            )
                            mode = "single"  # 跳过后续 conductor 启动
                    finally:
                        _RUN_CONFIRM_EVENTS.pop(run_id, None)
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

            # ===== M3 PROJECT OVERVIEW + MATERIALS BEGIN (2026-09-15) =====
            # 项目元数据 (description + instructions) 与用户显式添加的资料。
            # 优先级: 应用安全规则 > 项目指令 (此处注入) > 全局风格偏好。
            # 资料标注"不得覆盖上方指令", 沿用 PER_FILE_CHAR_CAP / TOTAL_CHAR_CAP
            # 预算裁剪, 详见 backend/chat/project_context.py。独立标记块, rebase 友好。
            try:
                from backend.chat.project_context import (
                    build_constraints_block,
                    build_project_materials_block,
                    build_project_metadata_block,
                )
                from backend.data.project_material_repo import (
                    ProjectMaterialRepository,
                )
                from backend.data.project_repo import ProjectRepository
                from backend.office.session_workspace import get_workspace_binding

                m3_binding = get_workspace_binding(
                    get_database().get_connection(), data.session_id
                )
                if m3_binding is not None and m3_binding.workspace_path:
                    m3_project = (
                        ProjectRepository()
                        .get_project_for_workspace(m3_binding.workspace_path)
                    )
                    metadata_block = build_project_metadata_block(m3_project)
                    if metadata_block:
                        system_content += "\n\n" + metadata_block
                    # ===== 项目约束注入 BEGIN (项目类型分类系统, 2026-09-24) =====
                    # 约束作为行为指导规则，优先级高于资料（materials）
                    if m3_project is not None:
                        constraints_block = build_constraints_block(m3_project.id)
                        if constraints_block:
                            system_content += "\n\n" + constraints_block
                    # ===== 项目约束注入 END =====
                    if m3_project is not None:
                        active_materials = (
                            ProjectMaterialRepository()
                            .get_active_materials_for_project(m3_project.id)
                        )
                        materials_block = build_project_materials_block(
                            active_materials
                        )
                        if materials_block:
                            system_content += "\n\n" + materials_block
            except Exception as m3_ctx_err:
                logger.debug(
                    f"[REQ {request_id}] M3 project overview skipped: {m3_ctx_err}"
                )
            # ===== M3 PROJECT OVERVIEW + MATERIALS END =====

            # ===== L5 环境上下文 + 技能清单 BEGIN (对标增强第二轮批次 B) =====
            # 告知模型平台/日期/工作区/git 状态与可用技能（此前模型对工作区
            # 状态零感知、技能只能盲调 skill 工具发现）。内部全 fail-safe:
            # 任何一段收集失败静默省略,绝不阻断聊天。独立标记块, rebase 友好。
            # L4' (round4 批次 C): 环境块含分钟级时间戳 + git 状态 —— 每轮必
            # 变。若拼进头部 system,前缀缓存(OpenAI 系/DeepSeek 逐字节前缀
            # 命中)每轮全灭;改为收集进 dynamic_context_parts,经
            # build_request_messages(trailing_system=...) 注入到历史之后的
            # 尾部独立 system 消息,让"稳定 system + 追加式历史"保持缓存前缀。
            dynamic_context_parts: List[str] = []
            # 对标 S2：临时聊天 —— 本轮跳过记忆注入 / 召回事件 / 事后提取。
            memory_off = (data.memory_mode or "on") == "off"
            try:
                from backend.chat.env_context import (
                    build_environment_block,
                    build_skills_block,
                )

                l5_binding = get_workspace_binding(
                    get_database().get_connection(), data.session_id
                )
                dynamic_context_parts.append(
                    build_environment_block(
                        workspace_path=(
                            l5_binding.workspace_path if l5_binding is not None else None
                        )
                    )
                )
                skills_block = build_skills_block()
                if skills_block:
                    # 技能清单仅在注册表变化时变 —— 相对稳定,留头部前缀。
                    system_content += "\n\n" + skills_block
            except Exception as l5_env_err:
                logger.debug(
                    f"[REQ {request_id}] L5 environment context skipped: {l5_env_err}"
                )
            # ===== L5 环境上下文 + 技能清单 END =====

            # ===== R38 A16 技能自动激活 BEGIN (对标 chat_service.py 2.6) =====
            # legacy /chat/stream 此前缺少 A16 自动激活(仅 hex 路径有),
            # 补齐后用户消息匹配 SKILL.md when_to_use 时自动注入技能指令。
            # fail-safe: 任何故障静默降级,不影响对话主流程。
            # MEDIUM-1 修复: 改用 _get_skill_adapter() (委托 InprocSkillAdapter),
            # 而非 getattr(agent, "skills", None) (SageAgent 无 skills 属性, 恒 None)。
            # 首次调用 _get_skill_adapter() 会同步扫描文件系统, 用 asyncio.to_thread
            # 包裹避免阻塞事件循环。
            r38_activated_skill_list: List[Dict] = []
            try:
                from backend.application.services.chat_service import (
                    _skill_activation_block,
                )

                r38_skills_port = await py_compat.to_thread(_get_skill_adapter)
                r38_block, r38_activated_skill_list = _skill_activation_block(
                    data.message or "", r38_skills_port
                )
                if r38_block:
                    dynamic_context_parts.append(r38_block)
            except Exception as r38_skill_err:
                logger.debug(
                    f"[REQ {request_id}] R38 A16 skill auto-activation skipped: {r38_skill_err}"
                )
            # ===== R38 A16 技能自动激活 END =====

            # R82 (2026-09-19) 去重说明: 此处原有的第一段 L13 记忆注入 + R17-E
            # 召回事件已删除 —— 它与下方 Task 14 段隔离版完全重复,导致每次
            # 请求把记忆上下文注入两遍（双倍 token）,且旧版无 segment 隔离,
            # 会把旧段工作记忆残留在 Task 14 修复后继续漏进请求。召回事件与
            # r38_memories 捕获统一收敛到下方段隔离版本。
            # R38 (2026-09-18): r38_memories 提升到本轮作用域 —— 随 assistant
            # 行落盘（重载后 memory chip 不丢）；捕获点在下方段隔离召回处。
            r38_memories: list = []


            # ===== R38 技能激活展示事件 BEGIN =====
            # A16 自动激活后推送 skill_activated 事件,前端渲染可展开 chip。
            # fail-safe: 任何异常只跳过事件,绝不影响对话主流程。
            # MEDIUM-3 修复: r38_activated_skill_list 已是事件载荷形状
            # [{"name": str, "triggers_matched": List[str]}], 直接透传。
            if r38_activated_skill_list:
                try:
                    entry.queue.put_nowait({
                        "state": "skill_activated",
                        "session_id": data.session_id,
                        "skills": r38_activated_skill_list,
                    })
                except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞主流程
                    logger.debug(
                        f"[REQ {request_id}] skill_activated event push failed, ignored"
                    )
            # ===== R38 技能激活展示事件 END =====

            # ===== R37 文本文档附件注入 BEGIN =====
            # 已上传文本文档（attachment_media_ids）按 id 读全文，截断后并入
            # 尾部 dynamic 块。fail-safe：单条失败跳过，绝不阻断聊天。
            # R81 (2026-09-19): rag_citations 列与 main 对齐；win7 暂无 r71
            # RAG 检索（无捕获来源），恒空，待 r66/r71 同步后启用。
            r81_rag_citations: list = []
            r81_rag_citations_written = False
            try:
                from backend.services.multimodal.media_store import (
                    MEDIA_ROOT,
                    MediaKind,
                    MediaStore,
                )

                r37_store = MediaStore(root=MEDIA_ROOT)
                for r37_mid in data.attachment_media_ids[:10]:
                    try:
                        _r37_loaded = r37_store.load(r37_mid)
                    except Exception:
                        _r37_loaded = None
                    if _r37_loaded is None:
                        continue
                    _r37_ref, r37_bytes = _r37_loaded
                    if _r37_ref.kind != MediaKind.DOCUMENT:
                        continue
                    try:
                        r37_text = r37_bytes.decode("utf-8")[:100_000]
                    except UnicodeDecodeError:
                        continue
                    if not r37_text.strip():
                        continue
                    # R81: win7 暂无 r66/r71 附件 RAG 检索注入（超长文档仍全文
                    # 截断），此处恒为空 —— rag_citations 列与 main 保持 schema
                    # 对齐，待 r66/r71 同步到 win7 后在此补捕获。
                    dynamic_context_parts.append(
                        "<attached_document id=" + repr(r37_mid) + ">" + chr(10)
                        + r37_text + chr(10) + "</attached_document>"
                    )
            except Exception as r37_att_err:
                logger.debug(f"[REQ {request_id}] attachment media inject skipped: {r37_att_err}")
            # ===== R37 文本文档附件注入 END =====

            attachment_block = await resolve_attachments(data.message, data.workspace_path or "")

            # ===== S3 实体引用 (@memory:/@wiki:/@skill:/@agent:) BEGIN =====
            # 对标 S3（统一入口）：把消息里的实体引用解析为 <references> 块，
            # 并入尾部 dynamic system（易变上下文，保前缀缓存）。同步 I/O
            # 走附件线程池；任何失败静默省略，绝不阻断聊天。
            # R86: @memory:/@wiki: 的命中同时抽取为结构化来源（process_with_sources
            # 一次解析两用，不为溯源重跑检索），暂存后并入 r81_turn_sources。
            r81_entity_sources: list = []
            try:
                from backend.chat import entity_refs as _entity_refs
                from backend.chat.executors import ATTACHMENT_EXECUTOR

                if _entity_refs.extract_entity_refs(data.message):
                    refs_block, r81_entity_hits = (
                        await asyncio.get_running_loop().run_in_executor(
                            ATTACHMENT_EXECUTOR,
                            _entity_refs.process_with_sources,
                            data.message,
                            data.session_id,
                        )
                    )
                    r81_entity_sources.extend(r81_entity_hits)
                    if refs_block:
                        dynamic_context_parts.append(refs_block)
            except Exception as refs_err:  # noqa: BLE001
                logger.debug(f"[REQ {request_id}] entity refs skipped: {refs_err}")
            # ===== S3 实体引用 END =====

            # G6 (2026-09-06): 图片附件校验提前（多模态 user 消息在下方
            # 历史组装后转换,与 L1 历史接线共用 build_request_messages 流程）
            if data.images:
                multimodal_error = _validate_chat_images(data.images)
                if multimodal_error:
                    raise HTTPException(status_code=400, detail=multimodal_error)

            # M4 自动压缩: run_loop 之前检查历史是否达到压缩阈值,达到则
            # 先压缩再继续。整块 try/except 隔离——压缩失败只记日志,
            # 绝不阻塞本次聊天(流式事件照常产出)。
            # R38 (2026-09-18): 压缩成功后推送 compact_triggered 事件,
            # 前端渲染特殊系统消息气泡。
            # L1 (2026-09-06): 压缩必须在加载历史之前 —— 它缩的是持久化
            # 历史,而历史马上会注入本轮 LLM 请求(见下)。
            compact_result = None
            try:
                compact_result = await _maybe_auto_compact_session(data.session_id, llm_config)
            except Exception as compact_err:
                logger.warning(
                    f"[REQ {request_id}] 自动压缩失败(忽略, 继续未压缩聊天): {compact_err}"
                )
            # R38: 推送 compact_triggered 事件（fail-safe）
            if compact_result is not None:
                try:
                    entry.queue.put_nowait({
                        "state": "compact_triggered",
                        "session_id": data.session_id,
                        "compact": compact_result,
                    })
                except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞主流程
                    logger.debug(f"[REQ {request_id}] compact_triggered event push failed, ignored")

            # L1 会话历史接线 (对标增强第二轮, docs/plans/2026-09-06-parity-round2):
            # 把持久化历史注入本轮 LLM 请求 —— 此前只发 [system, attachments?, user],
            # 用户第二条消息起 agent"失忆",压缩也不省每轮 token。此处本轮 user
            # 消息尚未落盘(落盘在下方),历史天然不含本轮消息。历史加载失败时
            # 降级为无历史的旧行为,绝不阻断聊天。
            repo = MessageRepository()
            try:
                # win7 惯例 (PR A §1.2): 同步 SQLite I/O 经 _run_db_sync 卸载到
                # 线程池,避免阻塞事件循环 + 与 _SQLITE_LOCK 守护路径并发冲突。
                # Task 4 (2026-09-17): 显式上下文重置
                if data.context_reset:
                    # Task 14 (context-isolation): 记录旧段 id,advance 后只清旧段
                    # 工作记忆,避免 clear() 把其他段一并擦掉破坏段隔离语义。
                    _old_seg = await _run_db_sync(
                        repo.get_active_segment_id, data.session_id
                    )
                    await _run_db_sync(repo.advance_segment, data.session_id)
                    try:
                        _clear_working_segment(agent, data.session_id, _old_seg)
                    except Exception as mem_err:
                        logger.warning("working memory clear_segment failed: %s", mem_err)

                history_rows = await _run_db_sync(
                    repo.get_active_segment, data.session_id
                )
            except Exception as hist_err:
                logger.warning(
                    f"[REQ {request_id}] 历史消息加载失败(降级为无历史): {hist_err}"
                )
                history_rows = []
            # C2: 原位重新生成 —— 历史剔除锚点 user 消息与旧回答 (事件投影同样剔除)
            regen_excluded = await _run_db_sync(
                answer_versions.regenerate_excluded_ids, data.session_id, data.regenerate_of
            )
            history_rows = answer_versions.drop_excluded(history_rows, regen_excluded)
            # Task 10 (2026-09-17): 自动话题检测 — 用户未显式 context_reset
            # 且 auto_topic_detection 启用时，扫描最近 N 条 assistant 文本；
            # 正则层命中或向量层平均相似度 < 阈值即视作话题切换，自动
            # advance_segment 并推 topic_shifted SSE。设置严格 opt-in:
            # 仅 "true" (大小写不敏感) 启用;缺失或其他值视为关闭,避免
            # 未显式配置的会话发生隐式上下文切换 (2026-09-18)。
            try:
                from backend.data.settings_repo import SettingsRepository as _SettingsRepo
                _auto_detect_raw = _SettingsRepo().get("auto_topic_detection")
            except Exception:
                _auto_detect_raw = None
            _auto_detect_on = (
                _auto_detect_raw is not None
                and _auto_detect_raw.strip().lower() == "true"
            )
            if not data.context_reset and _auto_detect_on and not data.regenerate_of:
                recent_assistant = [
                    r.content for r in (history_rows or [])[-6:]
                    if getattr(r, "role", None) == "assistant"
                ]
                embed_fn = None
                try:
                    from backend.memory.embedder_factory import create_embedder
                    _embedder = create_embedder()
                    def embed_fn(t):
                        return _embedder.encode(t)
                except Exception:
                    pass

                from backend.chat.topic_detection import detect_topic_shift
                is_new, _shift_reason = detect_topic_shift(
                    data.message, recent_assistant, embed_fn=embed_fn
                )
                if is_new:
                    # Task 14 (context-isolation): 记录旧段 id,advance 后清旧段
                    # 工作记忆,与显式 context_reset 路径保持一致清理口径。
                    _old_seg_auto = await _run_db_sync(
                        repo.get_active_segment_id, data.session_id
                    )
                    new_seg = await _run_db_sync(repo.advance_segment, data.session_id)
                    try:
                        _clear_working_segment(agent, data.session_id, _old_seg_auto)
                    except Exception as wm_err:
                        logger.warning("working memory clear_segment (auto) failed: %s", wm_err)
                    history_rows = await _run_db_sync(
                        repo.get_active_segment, data.session_id
                    )
                    try:
                        await entry.queue.put(
                            {
                                "state": "topic_shifted",
                                "segment_id": new_seg,
                                "reason": _shift_reason,
                            }
                        )
                    except Exception:
                        logger.warning("failed to emit topic_shifted event")
            # ===== L13 记忆上下文注入 BEGIN (Task 14 context-isolation) =====
            # legacy /chat/stream 此前完全不注入记忆上下文(只能靠 LLM 主动
            # 调 memory_search)——与 PHILOSOPHY"记忆优先"定位相悖。对齐
            # agent.chat() 单发路径的注入口径(get_context limit=10),fail-safe。
            # L4': 记忆随会话演进,同属易变上下文 → 并入尾部 dynamic 块。
            # Task 14: 从 history_rows[-1].segment_id 推导当前活跃段 id,透传给
            # MemoryManager.get_context → WorkingMemory.get_context,避免把
            # 旧段的工作记忆残留混进当前段的 LLM 请求。
            # R99: hits 先声明再进 try —— 注入抛错时下游事件块仍可安全判空
            # （未绑定变量会让 producer 整个 run 崩掉,CI smoke 已抓到）。
            l13_hits: list = []
            try:
                l13_memory_manager = getattr(agent, "memory_manager", None)
                if l13_memory_manager is not None and not memory_off:
                    # win7 惯例 (PR A §1.2): get_context 背后的 episodic 查询
                    # 直连共享连接, 统一经 _run_db_sync 拿锁, 防跨事务冲突。
                    active_segment_id = await _run_db_sync(
                        repo.get_active_segment_id, data.session_id
                    )
                    # R99: get_context_with_hits —— 一次检索同时产出注入文本
                    # 与结构化命中（替代原先独立的 recall() 第二次查询）。
                    l13_memory, l13_hits = await _run_db_sync(
                        l13_memory_manager.get_context_with_hits,
                        limit=10,
                        session_id=data.session_id,
                        segment_id=active_segment_id,
                    )
                    if l13_memory and str(l13_memory).strip():
                        dynamic_context_parts.append(
                            "以下是相关的记忆上下文：\n" + str(l13_memory)
                        )
            except Exception as l13_mem_err:
                logger.debug(
                    f"[REQ {request_id}] L13 memory context skipped: {l13_mem_err}"
                )
            # ===== L13 记忆上下文注入 END =====

            # ===== R17-E 记忆召回展示事件 BEGIN =====
            # L13 注入是静默的 —— 用户无法知道回答用了哪些记忆。注入成功
            # 后推送 memory_used 流事件；前端 Message 气泡显示"N 条记忆已
            # 应用"并可展开查看明细。
            # fail-safe：任何异常只跳过事件，绝不影响注入与对话主流程。
            # R82 (2026-09-19): 本事件唯一推送点（原上方无段隔离的重复推送
            # 已删除）。
            # R99 (2026-09-23): r38_memories 直接取注入命中的 hits —— 芯片
            # 展示与实际注入上下文严格同源，且不再单独跑 recall()。
            if dynamic_context_parts and not memory_off and l13_hits:
                l13_evt = _memory_used_event_from_hits(
                    l13_hits, session_id=data.session_id
                )
                r38_memories = l13_evt["memories"]
                try:
                    entry.queue.put_nowait(l13_evt)
                except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞主流程
                    logger.debug(
                        f"[REQ {request_id}] memory_used event push failed, ignored"
                    )
            # ===== R17-E 记忆召回展示事件 END =====
            # Task 5 (2026-09-15): catalog-based context budget.
            # Resolve effective window from model catalog, then compute budget
            # as window - reserve. Old >=20000 gate removed.
            effective_window = _resolve_effective_window(
                model_id=data.model,
                max_context=data.max_context,
                request_endpoint_id=data.endpoint_id,
                auto_context=data.auto_context,
            )
            # 把窗口透传给 run_loop：其预防性压缩阈值按实际窗口派生
            # （window − output 预留 − 缓冲），而不是固定 100k 常量。
            # 解析不到时保持缺省，run_ctx_budget_tokens 回退默认常量。
            if llm_config is not None and effective_window:
                llm_config["context_window"] = int(effective_window)
            # 上下文明细改造: reserve 不再硬编码 16384——本轮非历史开销
            # (system/附件/动态上下文/当前输入/工具 schema) 按实际大小实测,
            # 另加输出预算 (LLMConfig.max_tokens 默认 4096)。测量失败或
            # 窗口未知时回退旧默认口径,绝不阻断聊天。
            l9_reserve: Optional[int] = None
            try:
                if effective_window:
                    from backend.chat.context_breakdown import measure_request_reserve

                    l9_trailing = (
                        "\n\n".join(dynamic_context_parts)
                        if dynamic_context_parts
                        else None
                    )
                    l9_user_content: Any = data.message
                    if data.images:
                        l9_user_content = [
                            {"type": "text", "text": data.message},
                            *[
                                {"type": "image_url", "image_url": {"url": image_url}}
                                for image_url in data.images
                            ],
                        ]
                    l9_reserve = measure_request_reserve(
                        system_content,
                        attachment_block=attachment_block or None,
                        trailing_system=l9_trailing,
                        user_content=l9_user_content,
                        tools=agent.get_available_tools(),
                    )
            except Exception as reserve_err:  # noqa: BLE001 — 实测失败回退默认
                logger.debug(
                    f"[REQ {request_id}] 预留位实测失败(回退默认 16384): {reserve_err}"
                )
                l9_reserve = None
            l9_budget = history_token_budget(
                effective_window=effective_window,
                reserve=l9_reserve if l9_reserve is not None else 16384,
            )
            # Task 7 (2026-09-17): context-isolation turn limit.
            # Read ``context_turn_limit`` from settings (whitelisted in Task 6).
            # Setting is stored as str; parse defensively — bad value falls back
            # to None rather than 500-ing the chat request.
            turn_limit: Optional[int] = None
            try:
                from backend.data.settings_repo import SettingsRepository

                turn_limit_raw = SettingsRepository().get("context_turn_limit")
                if turn_limit_raw:
                    try:
                        turn_limit = int(turn_limit_raw)
                    except (ValueError, TypeError):
                        logger.warning(
                            "[REQ %s] context_turn_limit setting is invalid: %r, ignoring",
                            request_id,
                            turn_limit_raw,
                        )
                        turn_limit = None
            except Exception as sl_err:  # noqa: BLE001 — 任何 settings 读取失败都不应阻断聊天
                logger.warning(
                    "[REQ %s] context_turn_limit 读取失败(降级为不限): %s",
                    request_id,
                    sl_err,
                )
                turn_limit = None
            # SE2 (DSH 对标 R2): 历史从事件日志投影（"Model-visible ⟺ logged"）。
            # 事件为空且表里有历史（回填竞态/双写缺口）时防御性回退旧表投影。
            try:
                _session_events = await py_compat.to_thread(
                    lambda: _event_repo().get_by_session(data.session_id)
                )
            except Exception as ev_err:  # noqa: BLE001 — 事件读取失败回退表投影
                logger.warning(
                    "[REQ %s] 事件日志读取失败(回退表投影): %s", request_id, ev_err
                )
                _session_events = []
            _session_events = answer_versions.drop_excluded(_session_events, regen_excluded)
            if _session_events or not history_rows:
                messages, omitted_history = build_request_messages_from_events(
                    system_content=system_content,
                    user_text=data.message,
                    events=_session_events,
                    attachment_block=attachment_block or None,
                    budget_tokens=l9_budget,
                    # L4': 易变上下文(环境块/记忆)注入尾部,保前缀缓存
                    trailing_system=(
                        "\n\n".join(dynamic_context_parts)
                        if dynamic_context_parts
                        else None
                    ),
                    turn_limit=turn_limit,
                )
            else:
                logger.warning(
                    "[REQ %s] 会话 %s 无事件但有 %s 条表历史(疑似回填缺口)，回退表投影",
                    request_id,
                    data.session_id,
                    len(history_rows),
                )
                messages, omitted_history = build_request_messages(
                    system_content=system_content,
                    user_text=data.message,
                    history_rows=history_rows,
                    attachment_block=attachment_block or None,
                    budget_tokens=l9_budget,
                    # L4': 易变上下文(环境块/记忆)注入尾部,保前缀缓存
                    trailing_system=(
                        "\n\n".join(dynamic_context_parts)
                        if dynamic_context_parts
                        else None
                    ),
                    turn_limit=turn_limit,
                )
            if omitted_history > 0:
                logger.info(
                    "[REQ %s] 历史已省略最早 %s 条 (turn_limit %s, token 预算 %s)",
                    request_id,
                    omitted_history,
                    turn_limit,
                    l9_budget,
                )
            # TM1 (DSH 对标 R4): 上下文水位计量 —— 确定性估算本请求的
            # total/by_role/budget/pressure，结构化日志供观测与后续
            # 状态栏/性能预算消费。纯计量，不影响任何阈值行为。
            try:
                from backend.chat.token_meter import measure_request_messages

                _pressure = measure_request_messages(
                    messages, effective_window=effective_window
                )
                logger.info(
                    "[REQ %s] context_pressure: %s",
                    request_id,
                    _pressure.to_dict(),
                )
            except Exception as tm_err:  # noqa: BLE001 — 计量失败绝不阻断聊天
                logger.debug("[REQ %s] context_pressure 计量失败: %s", request_id, tm_err)
            else:
                # TM2: 水位随活跃流推送（duck-typed dict，与 compact_triggered
                # 同构；队列满/关闭静默降级——水位是增强信息不阻断聊天）。
                try:
                    entry.queue.put_nowait(
                        {
                            "state": "context_pressure",
                            "session_id": data.session_id,
                            "context_pressure": _pressure.to_dict(),
                        }
                    )
                except Exception:  # noqa: BLE001 — 队列满/关闭不阻断主流程
                    logger.debug(
                        "[REQ %s] context_pressure 事件推送失败，忽略", request_id
                    )

            # G6 (2026-09-06): 图片附件 → 多模态 user 消息（OpenAI content 分段格式）。
            # 校验已在 attachment 之后提前完成,此处只做末条 user 消息的形态转换。
            if data.images:
                messages[-1] = {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": data.message},
                        *[
                            {"type": "image_url", "image_url": {"url": image_url}}
                            for image_url in data.images
                        ],
                    ],
                }

            # Task 5 (round 2): explicit reject when the assembled request
            # exceeds the catalog-resolved window. History was already
            # truncated to ``l9_budget`` (= effective_window - reserve), so
            # this only fires when system / attachments / trailing_system /
            # current user input alone overshoot the reserve. Brief line 16
            # requires this guard; without it we silently send an over-budget
            # request the upstream LLM truncates or errors on.
            _check_request_within_window(messages, effective_window)

            # PR-7: 流式 chat 持久化。run_loop() 自身不写库(保持通用 ReAct
            # 迭代器纯净),由 producer 整合层负责落 user+assistant 消息 + 更新
            # session metadata。每个落盘独立 try/except,失败只 logger.warning
            # 不破坏流。
            #
            # PR A §1.2 (win7): 这些调用必须经 ``_run_db_sync`` 包装,否则:
            # 1) 同步 SQLite I/O 直接跑在事件循环线程,会阻塞其他 SSE/chat handler;
            # 2) 与 ``_SQLITE_LOCK`` 守护的 compact / fork / watchdog / storage
            #    adapter 路径并发时,会触发
            #    "cannot start a transaction within a transaction"。
            message_repo = MessageRepository()
            session_repo = SessionRepository()
            if data.regenerate_of:  # C2: 旧回答在本轮首次落库前归档为版本
                message_repo = answer_versions.ArchiveOnFirstSave(
                    message_repo, data.session_id, data.regenerate_of
                )
            # R38 (2026-09-18): 通知载荷序列化 —— sqlite3 不能直接绑定
            # dict/list，必须 json.dumps（ensure_ascii=False 保留中文）。
            # memory_refs 落**本轮第一条** assistant 行（与前端把 chip 挂在
            # 首个流式气泡上的行为一致）；flag 防多步 run 重复落盘。
            r38_activated_skills_json = (
                json.dumps(r38_activated_skill_list, ensure_ascii=False)
                if r38_activated_skill_list
                else None
            )
            r38_memory_refs_json = (
                json.dumps(r38_memories, ensure_ascii=False) if r38_memories else None
            )
            r38_memory_refs_written = False
            # R81: r71 附件检索 citations 与本轮工具来源落库载荷 —— 均为
            # JSON-in-TEXT 列, 序列化失败降级 None（列缺失仅丢展示不丢消息）。
            r81_rag_citations_json = (
                json.dumps(r81_rag_citations, ensure_ascii=False)
                if r81_rag_citations
                else None
            )
            r81_sources_json: Optional[str] = None
            user_now = int(time.time() * 1000)
            # client_message_id (同步 #1155): 确定性 user id —— 前端乐观消息
            # 用同一 id, 对账按 id 精确命中; 未传时维持 UUID。
            user_message_id = (
                f"u-{data.client_message_id}"
                if data.client_message_id
                else str(uuid.uuid4())
            )
            # client_message_id 幂等 (同步 #1196): 同 cmid 重试时复用既有
            # user 消息 (内容一致), 不再重复落库/触发主键冲突告警。
            reuse_existing_user = False
            if data.client_message_id:
                existing_user = await _run_db_sync(message_repo.get, user_message_id)
                reuse_existing_user = (
                    existing_user is not None
                    and existing_user.content == data.message
                )
                if reuse_existing_user:
                    logger.info(
                        "[REQ %s] client_message_id 幂等复用: %s",
                        request_id,
                        user_message_id,
                    )
            # C2: 原位重新生成沿用锚点 user 消息, 不再落库
            if data.regenerate_of:
                user_message_id, reuse_existing_user = data.regenerate_of, True
            if not reuse_existing_user:
                try:
                    await _run_db_sync(
                        message_repo.save,
                        DbMessage(
                            id=user_message_id,
                            session_id=data.session_id,
                            role="user",
                            content=data.message,
                            activated_skills=r38_activated_skills_json,
                            created_at=user_now,
                        ),
                    )
                except Exception as db_err:
                    logger.warning(f"[REQ {request_id}] 用户消息持久化失败: {db_err}")

            done_reasoning: Optional[str] = None

            # alpha.36 (Bug #4): 累积本次 run 的工具调用,持久化到 assistant 消息的
            # tool_calls 字段。用户切会话再切回时,前端 loadMessages 从 DB 读到
            # tool_calls 就能恢复中间步骤(否则只有最终 content,中间信息全丢)。
            # 形状对齐前端 ToolCall: {id, name, args, result?}
            accumulated_tool_calls: List[Dict[str, Any]] = []

            # L2 真流式 (2026-09-06): run_loop 在 THINKING 段实时发 CONTENT_DELTA
            # 事件时置位 —— 此时 DONE.content 已实时下发过,不再做假切块,
            # 否则前端会收到两遍内容。
            streamed_content_delta = False

            # RT7 (round7): 流式增量累积 —— 用户中断时把已产出的 partial
            # 内容落盘（DONE 才落盘的旧语义会留下无回复的悬空 user 消息，
            # 已渲染内容重载即丢）。
            streamed_partial_parts: List[str] = []

            # R81 统一参考来源: OBSERVING 事件里的检索类工具命中（web_search/
            # web_fetch/wiki_search/wiki_answer/MCP）解析成结构化来源,done 前
            # 推 sources_used 事件并随终稿 assistant 行落盘。提取/合并全
            # fail-safe（sources_extractor 内部吞异常）,绝不影响对话主流程。
            r81_turn_sources: list = []
            # R86: @memory:/@wiki: 实体引用命中并入统一来源（按 url/path/title 去重）
            r81_turn_sources[:] = merge_sources(r81_turn_sources, r81_entity_sources)
            # R83 增量推送: 每个 STEP_DONE 边界把已累积来源快照推给前端（长
            # run 中"先搜索后长文写作"时用户不必等 DONE 才看到来源）。记录
            # 上次推送时的条数,仅在有新增时推,避免逐 step 空转刷事件。
            r81_pushed_sources_len: int = 0

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

            # 从 settings 读 profile 迭代上限（用户可配），不回退到 profile 硬编码值
            from backend.orchestration.orch_settings import load_orch_settings
            _orch = load_orch_settings()
            _profile_name = agent.profile.get("name", "primary") if agent.profile else "primary"
            _profile_max_iter = {
                "primary": _orch.max_primary_iterations,
                "coder": _orch.max_coder_iterations,
                "reviewer": _orch.max_reviewer_iterations,
                "writer": _orch.max_writer_iterations,
            }.get(_profile_name, _orch.max_primary_iterations)

            async for evt in agent.run_loop(
                messages, llm_config=llm_config, session_id=data.session_id,
                max_iterations=_profile_max_iter,
            ):
                # L2 真流式: run_loop 流式 THINKING 产出的内容增量直接转发
                # (事件结构与旧 fake stream 的 content_delta 完全一致,前端无感)。
                if evt.state.value == "content_delta":
                    streamed_content_delta = True
                    streamed_partial_parts.append(str(evt.content or ""))
                    await entry.queue.put(evt.to_dict())
                # I5: DONE 事件的 content 拆成 chunk 逐个入队,前端累积实现逐字显示。
                # 真 LLM streaming 已由 run_loop 的 CONTENT_DELTA 覆盖(streamed_content_delta
                # 置位时跳过);非流式回退路径(不支持的 provider / 流式首块前失败)
                # 仍走这里,保持旧视觉行为。
                elif evt.state.value == "done" and evt.content:
                    done_content = evt.content
                    if not streamed_content_delta:
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
                    # 2026-09-02 bug fix: 之前用 evt.to_dict() 复制出来的 final 事件
                    # state 字段是 "reasoning",前端 appendReasoning 又把它当作增量追加,
                    # 导致 reasoning_delta + reasoning 双重累积 (用户视觉上"重复两遍")。
                    # 改成显式 state="reasoning_final" 区分:
                    #   - reasoning_delta: 增量,前端 append
                    #   - reasoning_final: 全量(对齐持久化字段),前端 replace 兜底
                    # 不再依赖 evt.to_dict() 的隐式 state,避免类似 future 漂移。
                    await entry.queue.put(
                        {
                            "state": "reasoning_final",
                            "iteration": evt.iteration,
                            "agent_id": evt.agent_id,
                            "reasoning": done_reasoning,
                        }
                    )
                # alpha.36 (Bug #4): 累积工具调用请求(ACTING)和结果(OBSERVING),
                # 持久化时写入 assistant 消息的 tool_calls 字段。
                elif evt.state.value == "acting" and evt.tool_call:
                    tc = evt.tool_call
                    accumulated_tool_calls.append(
                        {
                            "id": tc.id,
                            "name": tc.name,
                            "args": dict(tc.arguments) if isinstance(tc.arguments, dict) else {},
                        }
                    )
                    await entry.queue.put(evt.to_dict())
                elif evt.state.value == "observing" and evt.tool_result:
                    # 把结果回填到最后一条匹配的 tool_call(按 id)
                    tr = evt.tool_result
                    for tc in reversed(accumulated_tool_calls):
                        if tc.get("id") == tr.tool_call_id:
                            tc["result"] = tr.content
                            break
                    # R81: 检索类工具命中 → 解析成参考来源条目（fail-safe）
                    r81_tool_name = getattr(evt.tool_call, "name", "") or ""
                    if r81_tool_name:
                        r81_turn_sources[:] = merge_sources(
                            r81_turn_sources,
                            extract_sources_from_tool(r81_tool_name, tr.content),
                        )
                    await entry.queue.put(evt.to_dict())
                # 2026-09 step-by-step: 每完成一次 ReAct 迭代(OBSERVING 之后),
                # agent.py 在该迭代边界 yield STEP_DONE。这里把"当前 step 的累加器"
                # 快照成一行 assistant 消息,重置累加器准备下一步。最终步骤由 done
                # 分支单独处理(无 tool_calls,只含 LLM 终稿 content)。
                elif evt.state.value == "step_done":
                    try:
                        step_now = int(time.time() * 1000)
                        step_content = "".join(streamed_partial_parts)
                        step_tool_calls_json = (
                            json.dumps(accumulated_tool_calls, ensure_ascii=False)
                            if accumulated_tool_calls
                            else None
                        )
                        message_repo.save(
                            DbMessage(
                                id=str(uuid.uuid4()),
                                session_id=data.session_id,
                                role="assistant",
                                content=step_content,
                                reasoning_content=done_reasoning,
                                tool_calls=step_tool_calls_json,
                                # step_index=evt.step_index (== evt.iteration,
                                # agent.py 在并行/串行路径都同步设置)
                                step_index=evt.step_index,
                                # R38: 记忆召回挂本轮首条 assistant 行
                                memory_refs=(
                                    r38_memory_refs_json
                                    if not r38_memory_refs_written
                                    else None
                                ),
                                # R81: 附件检索 citations 同挂首条 assistant 行
                                rag_citations=(
                                    r81_rag_citations_json
                                    if not r81_rag_citations_written
                                    else None
                                ),
                                created_at=step_now,
                                model=(llm_config.get("model") if llm_config else "local"),
                            ),
                        )
                        if r38_memory_refs_json and not r38_memory_refs_written:
                            r38_memory_refs_written = True
                        if r81_rag_citations_json and not r81_rag_citations_written:
                            r81_rag_citations_written = True
                    except Exception as step_db_err:
                        logger.warning(
                            f"[REQ {request_id}] step {evt.step_index} 持久化失败: {step_db_err}"
                        )
                    # 重置 per-step 累加器,让下一步的 delta/reasoning/tool_call
                    # 累积到空 buffer(后续 STEP_DONE 看到的是干净的当前 step)。
                    accumulated_tool_calls = []
                    done_reasoning = None
                    streamed_partial_parts = []
                    # R83 增量推送: 有新增来源时在 step 边界推送累积快照 ——
                    # 前端 updateMessage 对 sources 是整体替换语义,快照幂等。
                    if len(r81_turn_sources) > r81_pushed_sources_len:
                        r81_pushed_sources_len = len(r81_turn_sources)
                        try:
                            await entry.queue.put(
                                {
                                    "state": "sources_used",
                                    "session_id": data.session_id,
                                    "sources": list(r81_turn_sources),
                                }
                            )
                        except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞主流程
                            logger.debug(
                                f"[REQ {request_id}] incremental sources_used push failed, ignored"
                            )
                    # STEP_DONE 转发到前端,前端据此把当前 streaming 气泡快照成
                    # completed step + 重置 streaming 准备下一步。
                    await entry.queue.put(evt.to_dict())
                else:
                    await entry.queue.put(evt.to_dict())

            # run_loop 正常结束 (DONE) → 持久化 assistant + 更新 session。
            # LLMError 走 except 分支,此块不执行 (无 assistant 可保存)。
            if done_content:
                assistant_now = int(time.time() * 1000)
                assistant_message_id: Optional[str] = None
                # R81: 本轮工具来源此时已收集完毕,序列化一次供终稿行落库。
                if r81_turn_sources:
                    r81_sources_json = json.dumps(
                        r81_turn_sources, ensure_ascii=False
                    )
                try:
                    saved = await _run_db_sync(
                        message_repo.save,
                        DbMessage(
                            id=str(uuid.uuid4()),
                            session_id=data.session_id,
                            role="assistant",
                            content=done_content,
                            reasoning_content=done_reasoning,
                            # alpha.36 (Bug #4): 持久化工具调用中间信息,
                            # 切会话再切回时前端 loadMessages 能恢复。
                            tool_calls=(
                                json.dumps(accumulated_tool_calls, ensure_ascii=False)
                                if accumulated_tool_calls
                                else None
                            ),
                            # 2026-09 step-by-step: 最终步骤的 step_index 即
                            # done_event.iteration (与 evt.iteration 同步)。
                            step_index=(
                                done_event.iteration if done_event is not None else 0
                            ),
                            # R38: 单步 run 无 STEP_DONE，记忆召回挂这条终稿行
                            memory_refs=(
                                r38_memory_refs_json
                                if not r38_memory_refs_written
                                else None
                            ),
                            # R81: 引用落库 —— 附件 citations 同款首写 flag；
                            # 工具来源挂终稿行（前端来源区块所在的气泡）。
                            rag_citations=(
                                r81_rag_citations_json
                                if not r81_rag_citations_written
                                else None
                            ),
                            sources=r81_sources_json,
                            finish_reason=getattr(done_event, "finish_reason", None),  # B2 截断标记
                            generation_stats=getattr(done_event, "generation_stats_json", None),
                            created_at=assistant_now,
                            model=(llm_config.get("model") if llm_config else "local"),
                        ),
                    )
                    assistant_message_id = getattr(saved, "id", None)
                    if r38_memory_refs_json and not r38_memory_refs_written:
                        r38_memory_refs_written = True
                    if r81_rag_citations_json and not r81_rag_citations_written:
                        r81_rag_citations_written = True
                except Exception as db_err:
                    logger.warning(f"[REQ {request_id}] 助手消息持久化失败: {db_err}")
                sess = None
                # WS-C P0-2: 统一记忆写入路径 — assistant 落盘**成功后**才触发
                # 提取（落盘失败则跳过, 避免产生无对应消息的脏记忆）。
                # best-effort + autoMemory 开关, 失败只 warning, 不影响流。
                if assistant_message_id is not None:
                    # ===== L11 stop 钩子 (批次 C-2, observe-only) =====
                    # run 正常结束通知; deny/modify 无语义, 一律忽略。
                    try:
                        from backend.hooks.config import load_hooks as _load_hooks_fn
                        from backend.hooks.runner import run_event_hooks as _run_hooks_fn

                        def _load_stop_hooks():
                            from backend.data.settings_repo import SettingsRepository

                            return _load_hooks_fn(SettingsRepository())

                        _stop_hooks = await _run_db_sync(_load_stop_hooks)
                        if _stop_hooks:
                            _capped = done_content[:4096]
                            await _run_hooks_fn(
                                _stop_hooks,
                                "stop",
                                "",
                                {
                                    "hook_event_name": "stop",
                                    "session_id": data.session_id,
                                    "final_content": _capped,
                                },
                            )
                    except Exception as l11_stop_err:
                        logger.debug(
                            f"[REQ {request_id}] stop hooks skipped: {l11_stop_err}"
                        )
                try:
                    sess = await _run_db_sync(session_repo.get, data.session_id)
                except Exception as db_err:
                    logger.warning(f"[REQ {request_id}] 会话读取失败: {db_err}")
                if sess is not None:
                    try:
                        await _run_db_sync(
                            session_repo.update,
                            data.session_id,
                            last_message_at=assistant_now,
                            # C2 重新生成不落 user 行: 只新增 1 条
                            message_count=sess.message_count
                            + (1 if data.regenerate_of else 2),
                        )
                    except Exception as db_err:
                        logger.warning(f"[REQ {request_id}] 会话更新失败: {db_err}")
                # Important-1 (win7 Task 6): when lifespan has installed a lifecycle
                # manager, use it so memory_written hooks and traceability are
                # emitted. Otherwise fall back to the async extraction queue.
                if assistant_message_id is not None:
                    lifecycle = getattr(request.app.state, "lifecycle", None)
                    if lifecycle is not None and not memory_off:
                        try:
                            await lifecycle.on_turn_complete(
                                data.session_id,
                                [
                                    {"role": "user", "content": data.message},
                                    {"role": "assistant", "content": done_content},
                                ],
                                source_message_id=assistant_message_id,
                            )
                        except Exception as exc:
                            logger.warning(
                                f"[REQ {request_id}] lifecycle on_turn_complete failed: {exc}"
                            )
                    elif not memory_off:
                        # 对标 S2: 临时聊天（memory_mode='off'）不提取记忆
                        await _extract_legacy_chat_memory(
                            request_id, data.session_id, data.message, done_content
                        )

                # 推送暂存的 DONE 事件先行 —— 2026-09 修复 (同步 #1100):
                # 标题生成内部自带 3 次退避重试, 最长可拖 15s+, 此前阻塞在
                # DONE 之前, 内容已生成完用户仍在转圈。现 DONE 立即推送,
                # 标题转后台任务生成, 完成后落库并补发 title_updated。
                # R81: DONE 之前推送 sources_used —— 前端在收到 DONE 收尾前
                # 就能把参考来源挂到 assistant 气泡上（与 memory_used 同为
                # 增强信息, 非空才推）。R83: 这里是全量兜底推送 —— 覆盖无
                # STEP_DONE 的单步 run（增量推送只在 step 边界触发）;对多步
                # run 与前端整体替换语义幂等,重复无害。
                if r81_turn_sources:
                    try:
                        await entry.queue.put(
                            {
                                "state": "sources_used",
                                "session_id": data.session_id,
                                "sources": r81_turn_sources,
                            }
                        )
                    except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞主流程
                        logger.debug(
                            f"[REQ {request_id}] sources_used event push failed, ignored"
                        )
                if done_event:
                    done_payload = done_event.to_dict()
                    # 同步 #1155: DONE 附带 assistant 消息服务端 id
                    if assistant_message_id is not None:
                        done_payload["message_id"] = assistant_message_id
                    # 同步 #1196: 首轮对话标题将在后台生成 —— 提示前端稍后
                    # 补刷侧栏 (2026-09)。
                    if sess is not None and sess.message_count <= 2:
                        done_payload["title_pending"] = True
                    await entry.queue.put(done_payload)

                # 标题自动生成：首轮对话后 (message_count 从 0 → 2)。
                if done_event and sess and sess.message_count <= 2:

                    async def _generate_title() -> None:
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
                                    # PR A §1.2: 标题更新同样需经 ``_run_db_sync``
                                    # 走 ``_SQLITE_LOCK``,与本会话其他写入串行化。
                                    await _run_db_sync(
                                        session_repo.update, data.session_id, title=title
                                    )
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

                    asyncio.create_task(_generate_title())
        except LLMError as e:
            logger.warning(
                f"[REQ {request_id}] /chat/stream LLM error: "
                f"type={e.type.value}, message={e.message}"
            )
            # S1: finally 落库 failed + 原因
            _producer_error = e.message
            # R120: 失败路径同样推送已收集的参考来源 —— 失败场景恰恰是
            # 用户最需要核对"搜索到了什么"的时机（落库侧 partial 行已带
            # sources，此处补齐前端实时可见性）。
            if r81_turn_sources:
                try:
                    await entry.queue.put(
                        {
                            "state": "sources_used",
                            "session_id": data.session_id,
                            "sources": r81_turn_sources,
                        }
                    )
                except Exception:  # noqa: BLE001 — 队列满/关闭不阻塞主流程
                    logger.debug(
                        f"[REQ {request_id}] sources_used push on failed, ignored"
                    )
            await entry.queue.put({"error": e.to_dict(), "state": "failed"})
        finally:
            # S1 (2026-09-06): 会话运行态终态落库。优先级：
            #   suspended > 用户中断(idle) > completed > failed。
            # cancelled 标志必须在 _ACTIVE_STREAMS 注销前读取；未捕获异常时
            # sys.exc_info() 仍在传播中，可取到错误摘要。/btw 伪会话零命中静默。
            _cancelled_by_user = bool(_ACTIVE_STREAMS.get(stream_id, {}).get("cancelled"))
            # RT7 (round7): 用户中断且 DONE 未产出时，把已流出的 partial
            # 内容落盘为 assistant 消息（带 [已中断] 标记）——对齐 Claude
            # Code 的 partial 保留语义：重载后 UI 与 DB 一致，续聊上下文
            # 完整。LLMError / 自然完成路径不落 partial（保持既有语义）。
            if _cancelled_by_user and not done_content and streamed_partial_parts:
                partial_text = "".join(streamed_partial_parts).strip()
                if partial_text:
                    try:
                        # 落盘走与 DONE 持久化同一把 _SQLITE_LOCK（_run_db_sync）。
                        await _run_db_sync(
                            message_repo.save,
                            DbMessage(
                                id=str(uuid.uuid4()),
                                session_id=data.session_id,
                                role="assistant",
                                content=partial_text + "\n\n[已中断]",
                                reasoning_content=None,
                                # alpha.36 (Bug #4): 中断时也持久化已累积的工具调用,
                                # 切会话再切回能看到中断前已发生的工具步骤。
                                tool_calls=(
                                    json.dumps(accumulated_tool_calls, ensure_ascii=False)
                                    if accumulated_tool_calls
                                    else None
                                ),
                                # R81: 中断行也带上已捕获的引用信息（首写 flag
                                # 置位防与已落库的 step 行重复）。win7 无
                                # step-by-step 落库, 不写 step_index。
                                rag_citations=(
                                    r81_rag_citations_json
                                    if not r81_rag_citations_written
                                    else None
                                ),
                                sources=(
                                    json.dumps(r81_turn_sources, ensure_ascii=False)
                                    if r81_turn_sources
                                    else None
                                ),
                                created_at=int(time.time() * 1000),
                                model=(llm_config.get("model") if llm_config else "local"),
                            ),
                        )
                        await entry.queue.put(
                            {"state": "partial_persisted", "content": partial_text}
                        )
                        logger.info(
                            "[REQ %s] 中断 partial 已落盘 (%d 字符)",
                            request_id,
                            len(partial_text),
                        )
                    except Exception as partial_err:  # noqa: BLE001 — 收尾尽力而为
                        logger.warning(
                            "[REQ %s] 中断 partial 落盘失败: %s", request_id, partial_err
                        )
            if getattr(entry, "status", None) == "suspended":
                _terminal_status = "suspended"
                _terminal_error = None
            elif _cancelled_by_user:
                _terminal_status = "idle"
                _terminal_error = None
            elif run_outcome == "completed":
                _terminal_status = "completed"
                _terminal_error = None
            else:
                _terminal_status = "failed"
                if _producer_error:
                    _terminal_error = _producer_error
                else:
                    _exc_info = sys.exc_info()
                    _terminal_error = (
                        str(_exc_info[1]) if _exc_info and _exc_info[0] else "运行失败"
                    )
            try:
                await _run_db_sync(
                    SessionRepository().update_run_status,
                    data.session_id,
                    _terminal_status,
                    _terminal_error,
                )
            except Exception as status_err:  # noqa: BLE001 — fail-open
                logger.debug("会话运行态(%s)写入失败: %s", _terminal_status, status_err)
            # C2a: 注销四路事件监听（sink 持有 entry/queue 引用，不注销
            # 会向已关闭的流推送 / 随全局 listener 表泄漏）。
            sink.unregister()
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

    # RT6 (round7): 同会话已有活跃流时服务端仲裁 409（此前纯靠前端守卫）。
    try:
        await registry.create(stream_id, queue_maxsize=1000, producer=producer)
    except SessionBusyError as busy_err:
        logger.warning(
            "[REQ %s] /chat/stream create 409 session_busy: active=%s",
            request_id,
            busy_err.active_stream_id,
        )
        raise HTTPException(
            status_code=409,
            detail={"code": "session_busy", "active_stream_id": busy_err.active_stream_id},
        )
    return {"streamId": stream_id}


@router.get("/chat/stream/active")
def get_active_chat_stream(session_id: str, request: Request):
    """R25-D4: 查询会话当前活跃的 chat 流（renderer 重载后 reattach 用）。

    Returns:
        ``{"streamId": "<uuid>" | None}`` —— None 表示该会话没有活跃流。
    """
    registry: StreamRegistry = request.app.state.streams
    return {"streamId": registry.find_active_by_session(session_id)}


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
        subscriber_queue = await registry.subscribe(stream_id)
        if subscriber_queue is None:
            return
        try:
            while True:
                try:
                    # 短 timeout 让多消费者场景下能感知 producer done 状态。
                    event = await asyncio.wait_for(subscriber_queue.get(), timeout=1.0)
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
            # 客户端断开 — 后台 producer 继续跑，其他 subscriber 不受影响。
            logger.info(f"chat-stream attach cancelled: streamId={stream_id}")
            return
        finally:
            await registry.unsubscribe(stream_id, subscriber_queue)

    return StreamingResponse(event_generator(), media_type="application/x-ndjson")




@router.post("/interrupt")
@with_db_lock
def interrupt(data: Optional[InterruptRequest] = Body(default=None)):
    """中断 Agent（P0-2: 经 stream_id 定位真实运行的 agent）"""
    stream_id = data.stream_id if data is not None else None
    target = interrupt_stream(stream_id)
    return {"status": "ok", "target": target}


#: steering 消息长度上限（与编排链 O1 steering 端点同额度）
_STEER_MAX_CHARS = 8192


@router.post("/chat/steer")
def steer_agent(data: SteerRequest):
    """RT5 (round7): 单 agent steering —— 运行中转达用户补充指示。

    消息在目标 run 的**下一迭代边界**注入 LLM 上下文（agent.run_loop
    消费，与编排链 O1 边界投递同语义）。纯内存注册表 + deque 操作，
    不走 DB 锁；失败面：
  - 404 stream_not_found：stream 不存在/已结束
    - 409 not_running：stream 存在但 agent 不在 run 活跃窗口
      （前端收到 409 回退排队语义——run 结束后作为新消息发送）
    - 400 msg_too_long：超过 8KB 额度
    """
    text = (data.content or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail={"code": "empty_content"})
    if len(text) > _STEER_MAX_CHARS:
        raise HTTPException(status_code=400, detail={"code": "msg_too_long"})
    entry = _ACTIVE_STREAMS.get(data.stream_id)
    if entry is None:
        raise HTTPException(status_code=404, detail={"code": "stream_not_found"})
    agent_obj: SageAgent = entry["agent"]
    if not agent_obj.inject_user_message(text):
        raise HTTPException(status_code=409, detail={"code": "not_running"})
    return {"ok": True}


# ==================== 消息 API ====================


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


# C1 第三刀 (DSH 对标 R16): Skill Draft/Audit/Rollback/Consolidation 迁出至
# legacy_skill_draft_routes.py（纯物理拆分，路径/行为零变更；与 orch_routes
# 同款 include 模式）。
from backend.api.legacy_skill_draft_routes import router as legacy_skill_draft_routes_router

router.include_router(legacy_skill_draft_routes_router)
# C1 第一刀 (DSH 对标 R14): 记忆 API 迁出至 legacy_memory_routes.py
# （纯物理拆分，路径/行为零变更；与 orch_routes 同款 include 模式）。
from backend.api.legacy_memory_list_routes import router as legacy_memory_list_routes_router
from backend.api.legacy_memory_routes import router as legacy_memory_routes_router

router.include_router(legacy_memory_routes_router)
router.include_router(legacy_memory_list_routes_router)
router.include_router(orch_routes_router)

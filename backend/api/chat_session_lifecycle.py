# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""会话生命周期装配（C2d，DSH 对标 R29，自 legacy_routes.py 迁出）。

压缩/分叉路径的装配层唯一归属：压缩摘要 LLM 客户端装配、压缩结果落盘、
自动压缩编排、检查点触发、legacy 聊天记忆提取，以及日志脱敏小工具
``_safe_log_field``（唯一实现，legacy_routes 再导出）。

legacy_session_routes 经 ``_legacy_routes._persist_compaction`` 等模块
属性访问的既有路径由 legacy_routes 的再导出保持不变。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict, List, Optional, Set

from backend.chat.compaction import compact_messages, should_compact
from backend.data.database import _SQLITE_LOCK, get_database
from backend.data.session_repo import Message as DbMessage, MessageRepository
from backend.memory import get_memory_manager

logger = logging.getLogger(__name__)


def _safe_log_field(value: object, max_length: int = 64) -> str:
    """Sanitize a user-controlled field for safe logging.

    - Strip newlines and control chars to prevent log injection
    - Truncate to max_length to prevent log spam
    """
    s = str(value)
    s = "".join(c for c in s if c.isprintable() or c == " ")
    return s[:max_length]


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
    # Task 14 (context-isolation): 续接摘要继承被压缩段的 segment_id,
    # 避免落库为 segment_id=0 导致活跃段识别错乱或段感知切片丢弃压缩历史。
    last_removed = messages[removed_count - 1] if removed_count > 0 else None
    # R38 (2026-09-18): 续接行携带压缩统计 —— 重载后前端据此渲染压缩横幅。
    # 口径: before = 压缩前消息数, after = 压缩后消息数(含续接行),
    # removed = 被摘要替代的前缀长度。注意 after = before - removed + 1
    # (续接摘要自身占一行), 前端文案已按此解释。
    before = len(messages)
    after = len(new_messages)
    continuation = DbMessage(
        id=str(uuid.uuid4()),
        session_id=session_id,
        role=summary["role"],
        content=summary["content"],
        compact_info=json.dumps(
            {"before": before, "after": after, "removed": removed_count},
            ensure_ascii=False,
        ),
        created_at=created_at,
        segment_id=last_removed.segment_id if last_removed is not None else 0,
    )

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


async def _maybe_auto_compact_session(
    session_id: str, llm_config: Optional[Dict]
) -> Optional[Dict[str, int]]:
    """聊天请求层的自动压缩钩子（M4）。

    在 run_loop 之前检查会话历史：达到压缩阈值时先压缩再继续。
    LLM 客户端优先用本次请求自带的 llm_config（与聊天同配置），
    缺省时回退到 app_settings 里的持久化配置。

    L1 (2026-09-06)：producer 现在把持久化历史注入本轮 LLM 请求，压缩
    直接决定每轮请求的上下文长度 —— 本函数因此必须在历史加载之前调用。
    调用顺序约定见 producer 内注释。

    本函数**可以抛 CompactionError / 其他异常**——调用方（producer）
    统一 try/except：压缩失败只记日志，绝不阻塞聊天。

    重入保护（PR A §1.2 cherry-pick from main #294）与返回值说明：
    自动压缩路径也必须在 ``_compact_in_progress`` 中登记，与手动 compact
    互斥。压缩成功时返回 ``{"before": int, "after": int, "removed": int}``；
    未达到阈值或无 LLM 配置时返回 ``None``。
    """
    # 进队列前先检查；如果已经被压缩中（手动或并发自动），直接跳过。
    # 本进程内手动/自动 compact 共用同一 ``_compact_in_progress``。
    if session_id in _compact_in_progress:
        logger.debug(
            "[M4] session=%s 已在压缩中, 跳过本次自动压缩",
            _safe_log_field(session_id),
        )
        return None

    message_repo = MessageRepository()
    # Task 12 (context-isolation): 压缩只对当前 segment 起作用——
    # 历史 segment 已被 advance_segment() 封存成 topic_separator + 摘要续接,
    # 旧 segment 的对话本来就不会再注入本轮 LLM 请求, 没有压缩必要.
    # 用 get_by_session 会把多个 segment 一起塞进 LLM 摘要 prompt, 浪费 token
    # 且破坏"segment 间互相隔离"的口径.
    messages = await _run_db_sync(message_repo.get_active_segment, session_id)
    if not should_compact(messages):
        return None

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
        return None

    # 二次检查 + 占位：should_compact 检查与 LLM 调用之间，并发请求
    # 可能已进入压缩流程（``_compact_in_progress`` 已被占用）。
    if _compact_in_progress_add(session_id) is False:
        logger.debug(
            "[M4] session=%s 并发抢先, 跳过本次自动压缩",
            _safe_log_field(session_id),
        )
        return None
    try:
        before_count = len(messages)
        new_messages, removed_count = await compact_messages(messages, llm_complete)
        after = await _run_db_sync(
            _persist_compaction, session_id, messages, new_messages, removed_count
        )
        logger.info(
            "[M4] session=%s 自动压缩完成: removed=%s after=%s",
            _safe_log_field(session_id),
            removed_count,
            after,
        )
        return {"before": before_count, "after": after, "removed": removed_count}
    finally:
        _compact_in_progress.discard(session_id)


def _compact_in_progress_add(session_id: str) -> bool:
    """原子地把 session_id 加入 ``_compact_in_progress``，返回是否成功占位。

    手动 compact 直接 ``_compact_in_progress.add()``，自动 compact 因为
    需要"二次检查 + 占位"语义而走本 helper。
    """
    if session_id in _compact_in_progress:
        return False
    _compact_in_progress.add(session_id)
    return True


def _auto_checkpoint_if_enabled(session_id: str) -> Optional[str]:
    """round5 批次 B-2: 发送前自动快照（偏好 "auto_checkpoint" 缺省/"1" 时）。

    在 run 开始前为会话绑定的工作区打一份 checkpoint，提供"整轮改动
    一键回滚"安全网。设计口径：

    - **默认开**（偏好缺省即开启；仅显式 "0" 关闭）——安全网类开关，
      2026-09-18 默认值收口时从"默认关"翻转；
    - 全程 fail-open：任何一步（偏好读 / 绑定 / zip）失败只记 debug，
      返回 None，绝不阻塞聊天流；
    - 快照即 CheckpointCreateTool（与 U2' 面板同一实现口径，受 8MiB/
      256MiB/10 份保留上限约束）。

    Returns:
        成功时的 checkpoint_id；未启用/未绑定/失败均为 None。

    注意：zip 大工作区是秒级同步操作，producer 侧须经 ``run_in_executor``
    调用本函数，不要在事件循环内直接 await。
    """
    try:
        from backend.data.settings_repo import SettingsRepository

        enabled = SettingsRepository().get("auto_checkpoint")
        if enabled == "0":
            return None
        from backend.office.session_workspace import get_workspace_binding

        root = get_workspace_binding(get_database().get_connection(), session_id)
        if root is None or not root.workspace_path:
            return None
        from backend.domain.tool_policy import ToolPolicy
        from backend.tools.checkpoint_tool import CheckpointCreateTool

        result = CheckpointCreateTool(ToolPolicy(workspace_root=root.workspace_path)).execute()
        if not result.success:
            logger.debug(
                "[B-2] session=%s 自动快照失败: %s",
                _safe_log_field(session_id),
                result.error,
            )
            return None
        content = result.content if isinstance(result.content, dict) else {}
        checkpoint_id = str(content.get("checkpoint_id", ""))
        logger.info(
            "[B-2] session=%s 发送前自动快照: %s files=%s",
            _safe_log_field(session_id),
            checkpoint_id,
            content.get("files"),
        )
        return checkpoint_id or None
    except Exception as checkpoint_err:  # noqa: BLE001 — fail-open
        logger.debug(
            "[B-2] session=%s 自动快照异常(忽略): %s",
            _safe_log_field(session_id),
            checkpoint_err,
        )
        return None


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

        # 记忆提取异步化：廉价装配（读设置/建 adapter）仍在本函数内完成，
        # 仅把耗时的 LLM 提取投递到后台队列，不阻塞流式请求收尾。
        from backend.application.services.chat_service import _pop_env_observations
        from backend.memory.async_extractor import (
            ExtractionRequest,
            get_memory_extraction_queue,
        )
        from backend.memory.extractor import MemoryExtractor

        get_memory_extraction_queue().submit(
            ExtractionRequest(
                memory_port=MemoryAdapter(get_memory_manager()),
                extractor=MemoryExtractor(llm_client=HttpxLLMAdapter()),
                user_text=user_text,
                assistant_text=assistant_text,
                session_id=session_id,
                enabled=True,
                tool_observations=_pop_env_observations(session_id),
            )
        )
    except Exception as exc:
        logger.warning(
            f"[REQ {request_id}] legacy 记忆提取失败(忽略, 不影响聊天): {exc}"
        )
# ===== WS-C P0-2 END =====


async def _run_db_sync(func, *args, **kwargs):
    """在线程池中执行一个受 SQLite 锁保护的同步操作。

    异步 handler 不能直接调用共享连接；锁必须在线程池 worker 内获取，
    才能同时保护同步路由和 storage adapter 的访问。
    """
    loop = asyncio.get_running_loop()

    def locked_call():
        with _SQLITE_LOCK:
            return func(*args, **kwargs)

    return await loop.run_in_executor(None, locked_call)


# 进程内重入护栏（MEDIUM-1 后端兜底）：同一会话并发手动压缩时，两者都会在
# 对方落盘前通过 should_compact 检查，导致续接消息行重复写入。前端
# isLoading 守卫是第一道防线，这里是便宜的第二道。
_compact_in_progress: Set[str] = set()

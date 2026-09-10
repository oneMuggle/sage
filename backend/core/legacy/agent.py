"""
SageAgent - 核心对话引擎
基于 ReAct 模式的 Agent 实现
"""

from __future__ import annotations

import asyncio
import contextlib
import functools
import hashlib
import json
import logging
import os
import time
import uuid
from collections import deque
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from backend.core.errors import LLMError, LLMErrorType
from backend.core.exceptions import AgentError, ToolCallError
from backend.core.legacy.agent_state import AgentEvent, AgentState, ToolCallRequest, ToolCallResult
from backend.core.legacy.context_first_aid import (
    estimate_messages_tokens,
    first_aid_compact,
    run_ctx_budget_tokens,
)
from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse
from backend.data.database import get_database
from backend.data.session_repo import Message as DbMessage, MessageRepository, SessionRepository
from backend.domain.tool_policy import ToolPolicy

# ===== M6 HOOKS BEGIN: user-defined hooks around tool execution =====
from backend.hooks.config import HookConfig, load_hooks
from backend.hooks.runner import build_payload, run_event_hooks, validate_modified_args

# ===== M6 HOOKS END =====
from backend.memory import (
    ConsolidationPipeline,
    EpisodicMemory,
    MemoryManager,
    SemanticMemory,
    SessionSummaryStore,
    WorkingMemory,
)
from backend.services.permission_gate import (
    DEFAULT_APPROVAL_TIMEOUT_S,
    ApprovalAnswer,
    ApprovalRequest,
    get_permission_gate,
)
from backend.services.question_gate import (
    DEFAULT_QUESTION_TIMEOUT_S,
    QuestionAnswer,
    QuestionRequest,
    get_question_gate,
)
from backend.tools import ToolRegistry, register_all_tools
from backend.tools.ask_user_tool import ASK_USER_QUESTION_TOOL_NAME, validate_ask_user_args
from backend.tools.base import ToolResult

#: M2b 审查加固: 连续未应答提问上限。超时软结果使循环继续, 若无此限,
#: 被操纵/犯错的 LLM 可循环提问持续骚扰用户。超限后直接返回错误结果。
MAX_CONSECUTIVE_UNANSWERED_QUESTIONS = 3

#: ``run_loop`` 的迭代兜底值——仅在既没显式传 ``max_iterations``、
#: profile 也没有该键时生效（profile 加载失败等降级路径）。
#: 与 ``agents/profiles.py`` 的 dataclass 默认、``data/database.py``
#: 的 DB 列默认保持一致，避免降级路径静默砍半预算。
DEFAULT_MAX_ITERATIONS = 10

#: RT2 (round7): 上下文溢出急救压缩的最大重试次数。第 1 次用常规压缩
#: （保留最近 6 条），第 2 次用激进压缩（保留最近 2 条）；仍溢出则按
#: 原错误面终止——同一请求盲目重试必然复现，压缩是唯一出路。
_MAX_FIRST_AID_ATTEMPTS = 2
from backend.tools.bash_validation import validate_bash
from backend.tools.context import current_tool_context
from backend.tools.permissions import (
    DEFAULT_PERMISSION_MODE,
    PermissionDecision,
    PermissionEnforcer,
    ToolCapability,
    classify_tool,
    load_enforcer_from_settings,
    make_office_path_boundary,
)

logger = logging.getLogger(__name__)


class QueryCache:
    """
    简单内存缓存
    最近查询结果缓存，TTL=5分钟
    """

    def __init__(self, ttl: int = 300, max_size: int = 100):
        """
        初始化缓存

        Args:
            ttl: 缓存生存时间（秒），默认5分钟
            max_size: 缓存最大条目数
        """
        self.ttl = ttl
        self.max_size = max_size
        self._cache: deque = deque(maxlen=max_size)
        self._lock = Lock()

    def _generate_key(self, session_id: str, message: str) -> str:
        """
        生成缓存键

        Args:
            session_id: 会话ID
            message: 消息内容

        Returns:
            缓存键的哈希值
        """
        key_str = f"{session_id}:{message}"
        return hashlib.md5(key_str.encode()).hexdigest()

    def get(self, session_id: str, message: str) -> Dict[str, Any] | None:
        """
        获取缓存结果

        Args:
            session_id: 会话ID
            message: 消息内容

        Returns:
            缓存结果，如果不存在或已过期返回None
        """
        key = self._generate_key(session_id, message)

        with self._lock:
            for item in self._cache:
                if item["key"] == key:
                    # 检查是否过期
                    if time.time() - item["timestamp"] < self.ttl:
                        logger.debug(f"缓存命中: {key[:8]}...")
                        return item["result"]
                    else:
                        # 已过期，移除
                        self._cache.remove(item)
                        break
        return None

    def set(self, session_id: str, message: str, result: Dict[str, Any]) -> None:
        """
        设置缓存

        Args:
            session_id: 会话ID
            message: 消息内容
            result: 结果数据
        """
        key = self._generate_key(session_id, message)

        with self._lock:
            # 移除已存在的相同键
            self._cache = deque(
                (item for item in self._cache if item["key"] != key), maxlen=self.max_size
            )

            # 添加新条目
            self._cache.append(
                {
                    "key": key,
                    "session_id": session_id,
                    "message": message,
                    "result": result,
                    "timestamp": time.time(),
                }
            )

    def clear(self) -> None:
        """清空缓存"""
        with self._lock:
            self._cache.clear()

    def cleanup(self) -> int:
        """
        清理过期缓存

        Returns:
            清理的条目数
        """
        now = time.time()
        removed = 0

        with self._lock:
            original_len = len(self._cache)
            self._cache = deque(
                (item for item in self._cache if now - item["timestamp"] < self.ttl),
                maxlen=self.max_size,
            )
            removed = original_len - len(self._cache)

        if removed > 0:
            logger.debug(f"清理了 {removed} 个过期缓存条目")

        return removed


class SageAgent:
    """
    Sage 对话引擎

    负责:
    - 管理对话循环
    - 调用 LLM
    - 调用工具
    - 维护上下文
    """

    def __init__(
        self,
        llm_config: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        bare: bool = False,
        policy: Optional[ToolPolicy] = None,
    ):
        """初始化 SageAgent。

        Args:
            llm_config: 可选的 LLM 配置；缺省时 llm_client 为 None。
            agent_id: 可选的 agent profile id。
            bare: 轻量构造模式（AgentTool 子代理专用）。跳过记忆栈与
                ``register_all_tools``（后者会冷启动 MCP list_tools）——
                这些对只跑 ``run_loop`` 的子代理毫无用处，默认注册表还会
                被 AgentTool 立刻丢弃。bare 实例仅支持 ``run_loop``；
                ``chat()`` 需要完整构造（memory_manager/consolidation 在
                bare 模式下为 None）。现有调用方默认 bare=False，行为不变。
            policy: M2 工具策略；非 bare 构造时透传给
                ``register_all_tools``（P0-3 scratch 隔离注入点）。
                ``None`` 时 register_all_tools 使用默认策略，行为不变。
        """
        self.session_repo = SessionRepository()
        self.message_repo = MessageRepository()
        self._interrupted = False
        # L12-lite (批次 C-3): 中断事件 —— run_loop 起点创建, interrupt()
        # 置位; 工具执行以 task 竞争该事件, 中断先到即取消当前工具。
        self._interrupt_event: Optional[asyncio.Event] = None
        self._current_session_id: Optional[str] = None
        # RT5 (round7): 单 agent steering —— 运行中注入的用户补充消息。
        # run_loop 每轮迭代顶部排空（迭代边界语义，与中断检查同位）；
        # _run_loop_active 为 False 时 inject 拒绝（调用方回退排队语义）。
        self._pending_user_messages: deque = deque()
        self._run_loop_active = False
        # L7: 每-run 工具调用数守卫的配置来源（register_all_tools 透传同一
        # policy;此处自留一份供 run_loop 读 max_tool_calls_per_run）。
        self.tool_policy = policy or ToolPolicy()

        # 加载 agent profile (阶段 1: Profile → 运行时)
        # 从 SQLite 读最新版本, 用户刚 PATCH 的 enabled/system_prompt 立即生效
        # agent_id 不存在 / 已禁用 → self.profile = None → 保持默认行为(向后兼容)
        self.profile: Optional[Dict[str, Any]] = None
        self.agent_id: Optional[str] = None
        if agent_id:
            from backend.agents.profiles import get_enabled_agent

            loaded = get_enabled_agent(agent_id)
            if loaded is not None:
                self.profile = loaded
                self.agent_id = agent_id
                logger.info(f"Agent profile loaded: id={agent_id}, role={loaded.get('role')}")
            else:
                logger.warning(
                    f"Agent profile not available for id={agent_id} "
                    "(disabled or missing), falling back to default"
                )

        # 初始化查询缓存 (TTL=5分钟)
        # 2026-09: 聊天回复缓存默认关闭。相同 (session, message) 重发通常意味着
        # 用户想要一个新答案(或刚切换模型/配置)，返回陈旧缓存反直觉；且缓存
        # 命中路径会跳过用户消息落库。设 SAGE_CHAT_CACHE=1 显式开启。
        self._cache_enabled = os.getenv("SAGE_CHAT_CACHE", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        )
        self._cache = QueryCache(ttl=300, max_size=100)
        if self._cache_enabled:
            logger.info("查询缓存已启用 (SAGE_CHAT_CACHE=1)，TTL=300秒，最大条目=100")
        else:
            logger.info("查询缓存默认关闭 (设 SAGE_CHAT_CACHE=1 开启)")

        if bare:
            # 轻量构造：run_loop 不触碰记忆栈，默认工具注册表也会被
            # AgentTool 整体替换为只读白名单 —— 两者都跳过。
            self.memory_manager = None
            self.tool_registry = ToolRegistry()
        else:
            # 初始化记忆系统
            db = get_database()
            working = WorkingMemory(max_size=20, max_tokens=4000)
            episodic = EpisodicMemory(db)
            semantic = SemanticMemory(db)
            self.memory_manager = MemoryManager(
                working,
                episodic,
                semantic,
                summary_store=SessionSummaryStore(db),
            )

            # 初始化工具注册表
            self.tool_registry = ToolRegistry()
            register_all_tools(self.tool_registry, policy=policy)
            # 注入记忆管理器：register_all_tools 创建的 MemorySearchTool /
            # MemorySaveTool 默认 self.memory=None，runtime 调用会返回
            # "未初始化"。agent 路径直接把已构造的 self.memory_manager
            # 灌进去（不是再走 get_memory_manager 单例）以保证 agent 内
            # 显式记忆栈是工具可见的唯一来源。注入逻辑统一在
            # ``inject_memory_manager``，仅使用 ``ToolRegistry`` 公开 API
            # （list_names + get），不触碰私有字典。
            from backend.tools.memory_tool import inject_memory_manager

            inject_memory_manager(self.tool_registry, self.memory_manager)
            logger.info(f"工具注册表初始化完成，已注册 {len(self.tool_registry.list())} 个工具")

        # M1 工具安全加固: 权限执行器注入点。
        # - permission_enforcer: None 时 run_loop 从 settings 现读现建;
        #   测试 / 特殊场景可直接赋值覆盖。
        # - approval_timeout: 审批等待秒数; None → gate 默认 300s。
        self.permission_enforcer: Optional[PermissionEnforcer] = None
        self.approval_timeout: Optional[float] = None
        # M2 part B: 提问等待秒数; None → gate 默认 300s（测试可缩短）。
        self.question_timeout: Optional[float] = None

        # 初始化 LLM 客户端
        if llm_config:
            self.llm_config = LLMConfig(**llm_config)
            self.llm_client: Optional[LLMClient] = LLMClient(self.llm_config)
            logger.info(
                "LLM 客户端已初始化: provider={}, model={}".format(
                    llm_config.get("provider"), llm_config.get("model")
                )
            )
        else:
            self.llm_config = None
            self.llm_client = None
            logger.warning("LLM 未配置，将使用本地模拟响应")

        # 初始化记忆压缩管道（chat-only；bare 模式跳过）
        if bare:
            self.consolidation = None
        else:
            # 批次三 step 4 接线修复:summary_store 必须注入压缩管道,
            # 否则 consolidation 走 save_compressed() 把"对话摘要"
            # 伪装成普通事实写入 episodic,违反 spec §4.3 step 4
            # "不伪装为普通事实"的硬约束。
            self.consolidation = ConsolidationPipeline(
                llm_client=self.llm_client,
                summary_store=self.memory_manager.summary_store,
            )

    async def _restore_llm_after_dynamic(
        self,
        llm_config: Optional[Dict[str, Any]],
        original_llm_client: Optional[LLMClient],
        original_llm_config: Optional[LLMConfig],
    ) -> None:
        """恢复原始 LLM client/config, 并关闭动态配置新建的 client。

        动态配置路径每次 new 一个 LLMClient(内部持独立 httpx.AsyncClient),
        只恢复引用不 close 会让半开连接随调用次数累积 —— 长会话高频切换
        模型时泄漏放大。动态 client 与原 client 是同一实例时(例如上层直接
        复用)不关闭。
        """
        if not llm_config:
            return
        dynamic_client = self.llm_client
        self.llm_client = original_llm_client
        self.llm_config = original_llm_config
        if dynamic_client is not None and dynamic_client is not original_llm_client:
            with contextlib.suppress(Exception):  # 关闭失败不影响恢复语义
                await dynamic_client.close()

    async def chat(
        self, session_id: str, message: str, llm_config: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        处理用户消息

        Args:
            session_id: 会话 ID
            message: 用户消息
            llm_config: 可选的动态 LLM 配置（覆盖初始化时的配置）

        Returns:
            包含 message 和 session 的字典
        """
        try:
            # 检查缓存 (默认关闭, SAGE_CHAT_CACHE=1 开启)
            if self._cache_enabled:
                cached_result = self._cache.get(session_id, message)
                if cached_result:
                    logger.info(f"返回缓存结果，会话: {session_id}")
                    return cached_result

            self._current_session_id = session_id
            self._interrupted = False

            # 如果传入了动态 LLM 配置，临时覆盖
            original_llm_client = self.llm_client
            original_llm_config = self.llm_config
            if llm_config:
                self.llm_config = LLMConfig(**llm_config)
                self.llm_client = LLMClient(self.llm_config)
                logger.info(
                    "使用动态 LLM 配置: provider={}, model={}".format(
                        llm_config.get("provider"), llm_config.get("model")
                    )
                )

            # 创建用户消息
            now = int(time.time() * 1000)
            user_message = {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": "user",
                "content": message,
                "created_at": now,
            }

            # 持久化用户消息
            try:
                self.message_repo.save(
                    DbMessage(
                        id=user_message["id"],
                        session_id=session_id,
                        role="user",
                        content=message,
                        created_at=now,
                    )
                )
            except Exception as db_err:
                logger.warning(f"用户消息持久化失败: {db_err}")

            # 对话前：获取记忆上下文
            memory_context = self.memory_manager.get_context(
                limit=10, session_id=session_id
            )

            # 将用户消息添加到工作记忆
            self.memory_manager.add_to_working("user", message, session_id=session_id)

            # 调用 LLM
            if self.llm_client:
                llm_response: LLMResponse = await self._call_llm(message, memory_context)
                assistant_content = llm_response.content
            else:
                assistant_content = f"收到消息: {message}\n\n(LLM 未配置，使用模拟响应)"

            assistant_message = {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "role": "assistant",
                "content": assistant_content,
                "created_at": int(time.time() * 1000),
                "model": self.llm_config.model if self.llm_config else "local",
            }

            # 持久化助手消息
            try:
                self.message_repo.save(
                    DbMessage(
                        id=assistant_message["id"],
                        session_id=session_id,
                        role="assistant",
                        content=assistant_content,
                        created_at=assistant_message["created_at"],
                        model=assistant_message["model"],
                    )
                )
            except Exception as db_err:
                logger.warning(f"助手消息持久化失败: {db_err}")

            # 将助手消息添加到工作记忆
            self.memory_manager.add_to_working(
                "assistant", assistant_message["content"], session_id=session_id
            )

            # 对话后：提取关键信息存入情景记忆
            self._extract_and_save_memories(session_id, user_message, assistant_message)

            # 对话后：检查是否需要压缩工作记忆
            if self.memory_manager.working.total_tokens_for(session_id) > 3000:
                self.consolidation.consolidate(
                    self.memory_manager, session_id=session_id
                )

            # 更新会话
            session = self.session_repo.get(session_id)
            if session:
                self.session_repo.update(
                    session_id,
                    last_message_at=assistant_message["created_at"],
                    message_count=session.message_count + 2,
                )

            result = {
                "message": assistant_message,
                "session": session.to_dict() if session else None,
            }

            # 存入缓存 (仅 SAGE_CHAT_CACHE=1 时生效)
            if self._cache_enabled:
                self._cache.set(session_id, message, result)

            # 恢复原始 LLM 配置 (并关闭动态新建的 client)
            await self._restore_llm_after_dynamic(
                llm_config, original_llm_client, original_llm_config
            )

            return result

        except LLMError as e:
            logger.error(f"chat LLM 错误: type={e.type.value}, message={e.message}")
            # 恢复原始 LLM 配置 (并关闭动态新建的 client)
            await self._restore_llm_after_dynamic(
                llm_config, original_llm_client, original_llm_config
            )
            return {
                "error": e.to_dict(),
                "message": None,
                "session": None,
            }
        except Exception as e:
            logger.exception(f"chat 处理异常: {str(e)}")
            # 恢复原始 LLM 配置 (并关闭动态新建的 client)
            await self._restore_llm_after_dynamic(
                llm_config, original_llm_client, original_llm_config
            )
            wrapped = LLMError(LLMErrorType.UNKNOWN, str(e))
            return {
                "error": wrapped.to_dict(),
                "message": None,
                "session": None,
            }

    def _extract_and_save_memories(
        self, session_id: str, user_message: Dict[str, Any], assistant_message: Dict[str, Any]
    ) -> None:
        """
        从对话中提取关键信息并存入情景记忆

        Args:
            session_id: 会话 ID
            user_message: 用户消息
            assistant_message: 助手消息
        """
        try:
            user_content = user_message.get("content", "")
            assistant_content = assistant_message.get("content", "")

            # 对于较长的对话，保存到情景记忆
            if len(user_content) > 100 or len(assistant_content) > 100:
                combined_content = f"[用户]: {user_content}\n[助手]: {assistant_content}"
                importance = 5

                # 检测是否包含偏好或设置信息
                preference_keywords = ["喜欢", "偏好", "不要", "记得", "设置", "以后"]
                for keyword in preference_keywords:
                    if keyword in user_content:
                        importance = 7
                        break

                self.memory_manager.remember(
                    combined_content,
                    {
                        "session_id": session_id,
                        "importance": importance,
                        "memory_type": "conversation",
                    },
                )
        except Exception as e:
            logger.warning(f"提取记忆失败: {str(e)}")

    async def _call_llm(self, user_message: str, memory_context: str) -> LLMResponse:
        """
        调用 LLM 生成回复。

        让 LLMError 透传给调用方，由 chat() 统一处理为结构化 error 响应。
        返回 LLMResponse 而非 str，以保留 tool_calls 等元数据供 Task 9 使用。

        Args:
            user_message: 用户消息
            memory_context: 记忆上下文

        Returns:
            LLMResponse：包含 content 和 tool_calls（透传不被吞没）
        """
        # 阶段 1: 优先从 profile 读 system_prompt, 否则用默认
        if self.profile and self.profile.get("system_prompt"):
            system_prompt = self.profile["system_prompt"]
        else:
            from backend.agents.profiles import build_system_base

            system_prompt = build_system_base()
        if memory_context:
            system_prompt += "\n\n以下是相关的记忆上下文：\n" + memory_context

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]

        # 让 LLMError 透传给调用方，由 chat() 统一处理
        return await self.llm_client.chat(messages)

    def _is_parallel_eligible(  # noqa: PLR0911 — 守卫链逐条 return 可读性更好
        self,
        batch: List[Any],
        enforcer: Any,
        hooks: List[Any],
        tool_calls_used: int,
    ) -> bool:
        """L6 (批次 C-3): 判断本批 tool_calls 能否并行执行。

        全部满足才并行（否则回退串行, 语义与旧版完全一致）:
        - 批大小 >= 2, 且未处于中断;
        - 无 pre_tool_use 钩子（钩子的 deny/modify 是顺序语义）;
        - 预算余量足够整批;
        - 每个工具: 存在、声明 READ、非阻塞、非特殊工具
          (ask_user / agent / dispatch_subagents);
        - 权限预检全部免审放行（避免并行弹多个审批框）。
        """
        if len(batch) < 2 or self.is_interrupted() or hooks:
            return False
        if tool_calls_used + len(batch) > self._effective_max_tool_calls_per_run():
            return False
        from backend.domain.risk import RiskClass

        for tc in batch:
            if tc.name in (
                ASK_USER_QUESTION_TOOL_NAME,
                "agent",
                "dispatch_subagents",
            ):
                return False
            tool = self.tool_registry.get(tc.name)
            if tool is None:
                return False
            if getattr(tool, "risk", RiskClass.READ) != RiskClass.READ:
                return False
            if getattr(tool, "is_blocking", False):
                return False
            try:
                args = (
                    json.loads(tc.arguments)
                    if isinstance(tc.arguments, str)
                    else tc.arguments
                )
            except json.JSONDecodeError:
                return False
            if not isinstance(args, dict):
                return False
            decision = enforcer.check(tc.name, args)
            if decision.needs_approval or not decision.allowed:
                return False
        return True

    async def _await_tool_execution(
        self,
        tool: Any,
        name: str,
        args: Dict[str, Any],
        tool_call_id: Optional[str] = None,
    ) -> Tuple[bool, Any]:
        """L12-lite: 执行工具并与中断事件竞争。

        返回 ``(cancelled, result)``。同步内联工具瞬时完成不参与竞争;
        agent / dispatch_subagents / 阻塞型工具包成 task —— 中断先到时
        取消执行任务（executor 线程内的子进程尽力等其自然超时, 事件循环
        立即恢复）, cancelled=True。

        live-events P0: ``tool_call_id`` 仅用于 dispatch_subagents —— 注入
        ``_tool_call_id``（dict 重建覆盖 LLM 可能注入的同名 key）, dispatcher
        给子任务标 parent_tool_call_id, 前端把子代理实时步骤挂到 Delegate 卡片。
        """
        if name == "agent":
            # live-events P2 (2026-09-07): 优先走 execute_async —— 子代理作为
            # 原生协程落在事件循环上：wait_for 超时/中断取消都能真正收口
            # （根修 L12 遗弃线程），子代理中间事件经 agent_event_bridge
            # 投影进聊天流。仅当工具未实现 execute_async（测试桩/旧扩展）
            # 才回落 run_in_executor 同步通路（行为与历史一致）。
            afn = getattr(tool, "execute_async", None)
            if callable(afn):
                agent_kwargs = dict(args)
                if tool_call_id:
                    agent_kwargs["_tool_call_id"] = tool_call_id
                coro = afn(**agent_kwargs)
            else:
                coro = asyncio.get_running_loop().run_in_executor(
                    None, functools.partial(tool.execute, **args)
                )
        elif name == "dispatch_subagents":
            dispatch_kwargs = dict(args)
            if tool_call_id:
                dispatch_kwargs["_tool_call_id"] = tool_call_id
            coro = tool.execute_async(**dispatch_kwargs)
        elif getattr(tool, "is_blocking", False):
            coro = asyncio.get_running_loop().run_in_executor(
                None, functools.partial(tool.execute, **args)
            )
        else:
            return False, tool.execute(**args)

        event = self._interrupt_event
        if event is None or event.is_set():
            return False, await coro

        exec_task = asyncio.ensure_future(coro)
        stop_waiter = asyncio.ensure_future(event.wait())
        try:
            done, _pending = await asyncio.wait(
                {exec_task, stop_waiter}, return_when=asyncio.FIRST_COMPLETED
            )
        finally:
            stop_waiter.cancel()
        if exec_task in done:
            return False, exec_task.result()
        # 中断先到 → 取消执行。注意不 await: run_in_executor 的底层线程
        # 不可强杀(进程内命令会跑到自然超时), 等它等于没取消。挂一个
        # 回调消费 future 异常, 防止 "exception never retrieved" 告警。
        exec_task.cancel()

        def _consume_exception(fut: asyncio.Future) -> None:
            if not fut.cancelled():
                fut.exception()

        exec_task.add_done_callback(_consume_exception)
        return True, None

    def _effective_max_tool_calls_per_run(self) -> int:
        """L7: 每-run 工具调用数上限（env ``SAGE_MAX_TOOL_CALLS_PER_RUN`` 可覆盖）。

        默认取 ``self.tool_policy.max_tool_calls_per_run``（ToolPolicy 默认 25）。
        env 非法值静默回退，本方法永不抛错。
        """
        raw = os.environ.get("SAGE_MAX_TOOL_CALLS_PER_RUN", "").strip()
        if raw:
            try:
                value = int(raw)
                if value >= 1:
                    return value
            except ValueError:
                logger.warning("env SAGE_MAX_TOOL_CALLS_PER_RUN=%r 非法,回退 policy 默认", raw)
        return int(getattr(self.tool_policy, "max_tool_calls_per_run", 25) or 25)

    @staticmethod
    def _should_stream(llm_client: Optional[LLMClient]) -> bool:
        """是否尝试流式 LLM 调用（L2 真流式开关）。

        - env ``SAGE_LLM_STREAMING`` 设为 0/false/off/no 时全局关闭；
        - 该 client 实例流式已失败过一次（``stream_unsupported``）则跳过,
          避免每次迭代都白打一个失败请求；
        - 其余情况默认开启（失败自动回退非流式,不影响可用性）。
        """
        raw = os.environ.get("SAGE_LLM_STREAMING", "").strip().lower()
        if raw in {"0", "false", "off", "no"}:
            return False
        return not getattr(llm_client, "stream_unsupported", False)

    async def run_loop(  # noqa: PLR0911 — 状态机多出口
        self,
        messages: List[Dict[str, Any]],
        max_iterations: Optional[int] = None,
        llm_config: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ):
        """ReAct 主循环。

        状态机:IDLE → THINKING → (ACTING → OBSERVING)* → DONE/FAILED

        Args:
            messages: 完整消息历史（含 system/user/assistant/tool），会被就地修改
            max_iterations: 最大循环次数，防止死循环。None 时取 profile.max_iterations
                (若 profile 也不存在, 兜底 DEFAULT_MAX_ITERATIONS=10)。
                显式传入的 int 覆盖 profile 值。
            llm_config: 可选的动态 LLM 配置(覆盖初始化时的配置),允许调用方
                在 agent 实例没有默认 LLM 时通过 per-request 配置运行。
                如果同时存在 self.llm_client,会临时覆盖并在循环结束后恢复。
            session_id: 可选的会话归因 (L8, 批次 C) —— 注入 llm_client 供
                usage_tracker 落库 usage_events;None 时用量记为 unattributed。

        Yields:
            AgentEvent:状态机事件,前端通过流式响应(NDJSON)接收。每个事件携带
                ``agent_id`` 字段(来自构造时传入的 agent_id, 供前端显示"当前处理 agent")。

        Raises:
            AgentError: 既没有 self.llm_client 也没传 llm_config 时
        """
        if self.llm_client is None and not llm_config:
            raise AgentError("LLM 未配置,无法运行 Agent 循环")

        # 每次 run_loop 重置未应答计数(跨会话不累积)
        self._consecutive_unanswered = 0
        # L12-lite: 本轮 run 的中断事件 (fresh, 绑定当前事件循环)
        self._interrupt_event = asyncio.Event()
        # RT5: run 活跃窗口 —— steering 注入仅在窗口内被接受；
        # 残留的未消费消息（上一 run 中断遗留）在此丢弃，不跨 run 泄漏。
        self._pending_user_messages.clear()
        self._run_loop_active = True
        # L7: 每-run 工具调用计数（跨迭代累计,超 ToolPolicy.max_tool_calls_per_run 终止）
        tool_calls_used = 0

        # 阶段 1: max_iterations 默认从 profile 读, 否则兜底 DEFAULT_MAX_ITERATIONS
        effective_max_iterations = (
            max_iterations
            if max_iterations is not None
            else (
                self.profile.get("max_iterations", DEFAULT_MAX_ITERATIONS)
                if self.profile
                else DEFAULT_MAX_ITERATIONS
            )
        )

        # 如果传入了动态 LLM 配置,临时覆盖
        original_llm_client = self.llm_client
        original_llm_config = self.llm_config
        if llm_config:
            self.llm_config = LLMConfig(**llm_config)
            self.llm_client = LLMClient(self.llm_config)
            logger.info(
                "run_loop: 使用动态 LLM 配置: provider={}, model={}".format(
                    llm_config.get("provider"), llm_config.get("model")
                )
            )

        # L8: 会话归因注入 (批次 C) —— usage_tracker 落库 usage_events 用。
        # client 可能是动态新建的,也可能是构造时注入的;统一设置属性。
        if session_id and self.llm_client is not None:
            with contextlib.suppress(Exception):  # 测试替身可能拒绝设属性
                self.llm_client.session_id = session_id

        # M1: 权限执行器在 run 起点构造一次（读 settings: permission_mode /
        # permission_rules），整轮循环复用——避免每次工具调用都打 DB。
        enforcer = self._build_permission_enforcer()

        # B1: run 内工具结果上下文预算。工具结果此前无截断直入 messages,并在
        # 后续每轮迭代重复发送 —— read_file 上限 5MiB,一次大读取会把后续每轮
        # 请求拖成巨型 payload（bash 的 30KiB 输出 cap 是唯一既有例外）。
        # UI 事件 (AgentEvent.tool_result) 保留全文,只有进 LLM 的消息被截断。
        tool_cap_chars = int(os.getenv("SAGE_TOOL_RESULT_CAP_CHARS", "32000"))
        remaining_budget = int(os.getenv("SAGE_TOOL_RESULT_RUN_BUDGET_CHARS", "256000"))

        def cap_result_for_context(content: str) -> str:
            """按单结果上限 + run 级累计预算截断进 LLM 上下文的工具结果。"""
            nonlocal remaining_budget
            if len(content) <= tool_cap_chars and len(content) <= remaining_budget:
                remaining_budget -= len(content)
                return content
            allowed = min(tool_cap_chars, remaining_budget)
            if allowed <= 0:
                return (
                    f"[已截断] 工具结果超出 run 内上下文预算, "
                    f"原始长度 {len(content)} 字符, 本次未注入上下文。"
                )
            remaining_budget -= allowed
            return (
                content[:allowed]
                + f"\n[已截断: 原始长度 {len(content)} 字符, 保留前 {allowed} 字符, "
                f"如需其余部分请用更精确的查询/offset 重试]"
            )

        try:
            for i in range(effective_max_iterations):
                # P0-1 (2026-08-20): 中断检查 —— 每轮迭代顶部消费一次中断信号（one-shot）。
                # 此前 interrupt() 只置标志位、is_interrupted() 零调用者，run_loop 从不读，
                # 中断请求完全无效。现在最迟在下一轮迭代开头终止：发 FAILED 事件，
                # 前端 chatStream 收到 failed 走 onError + onDone 正常收尾。
                if self.is_interrupted():
                    self.reset_interrupt()
                    logger.info("run_loop 被用户中断 (iteration %s)", i)
                    yield AgentEvent(
                        state=AgentState.FAILED,
                        iteration=i,
                        error="interrupted by user",
                        agent_id=self.agent_id,
                    )
                    return

                # RT5: 迭代边界排空 steering —— 用户运行中补充的指示以
                # user 消息进入本轮 LLM 调用（与编排链 O1 边界投递同语义）。
                _steer_messages = self._drain_pending_user_messages()
                if _steer_messages:
                    messages.extend(_steer_messages)
                    logger.info(
                        "run_loop 迭代 %s 注入 %d 条用户补充消息", i, len(_steer_messages)
                    )

                # RT2 (round7): 迭代边界高水位预防 —— 估算 token 超预算时先
                # 机械压缩（透明治理，仅日志），避免请求撑爆窗口后才被动急救。
                # env SAGE_RUN_CTX_BUDGET_TOKENS=0 可关闭。
                _ctx_budget = run_ctx_budget_tokens()
                if _ctx_budget > 0 and estimate_messages_tokens(messages) > _ctx_budget:
                    _before, _after = first_aid_compact(messages)
                    logger.info(
                        "run_loop 迭代 %s 高水位压缩：估算 token %d → %d (预算 %d)",
                        i,
                        _before,
                        _after,
                        _ctx_budget,
                    )

                yield AgentEvent(state=AgentState.THINKING, iteration=i, agent_id=self.agent_id)

                # Pass available tools to LLM so it can call them
                available_tools = self.get_available_tools()

                # L2 真流式 (对标增强第二轮, docs/plans/2026-09-06-parity-round2):
                # THINKING 段优先走流式 tool-calling —— 内容增量以 CONTENT_DELTA
                # 事件实时下发（前端 appendContent 既有契约），工具调用增量在
                # 流内聚合。流式不可用（上游不支持 stream+tools / stream_options,
                # 或首个增量前请求失败）时自动回退非流式 chat(),行为与旧版完全
                # 一致;首个增量之后失败无法安全重放,按原错误面终止。
                response: Optional[LLMResponse] = None
                # RT2 (round7): 溢出急救环 —— CONTEXT_OVERFLOW 时就地机械压缩
                # messages 后重试（最多 _MAX_FIRST_AID_ATTEMPTS 次：常规 → 激进），
                # 仍溢出按原错误面终止。重试对生成端透明：压缩标记直接嵌在被截断
                # 的消息里，模型可自察上下文被治理过。
                _first_aid_attempts = 0
                while True:
                    try:
                        if self._should_stream(self.llm_client):
                            saw_content_delta = False
                            stream_reasoning_parts: List[str] = []
                            try:
                                async for evt_kind, payload in self.llm_client.chat_stream_events(
                                    messages, tools=available_tools or None
                                ):
                                    if evt_kind == "content_delta":
                                        saw_content_delta = True
                                        yield AgentEvent(
                                            state=AgentState.CONTENT_DELTA,
                                            iteration=i,
                                            content=payload,
                                            agent_id=self.agent_id,
                                        )
                                    elif evt_kind == "reasoning_delta":
                                        # 汇总后在流收尾统一发一条 REASONING（producer
                                        # 会再做 reasoning_delta 切块,拆成多事件会重复）
                                        stream_reasoning_parts.append(payload)
                                    elif evt_kind == "response":
                                        response = payload
                            except LLMError as stream_err:
                                if saw_content_delta:
                                    # RT2: 首个增量之后失败无法安全重放（重试会重复
                                    # 下发内容）——打标记让外层急救环跳过本次溢出重试。
                                    stream_err._saw_content_delta = True  # type: ignore[attr-defined]
                                    raise
                                logger.warning(
                                    "流式 LLM 调用失败(首个增量前),回退非流式: %s", stream_err
                                )
                                # 标记该 client 实例,本次 run_loop 后续迭代直接走非流式
                                with contextlib.suppress(AttributeError):  # 测试替身可能没有该属性
                                    self.llm_client.stream_unsupported = True
                                response = None
                            if response is not None and stream_reasoning_parts:
                                yield AgentEvent(
                                    state=AgentState.REASONING,
                                    iteration=i,
                                    reasoning="".join(stream_reasoning_parts),
                                    agent_id=self.agent_id,
                                )
                        if response is None:
                            response = await self.llm_client.chat(
                                messages, tools=available_tools or None
                            )
                            # 如果 LLM 返回了 reasoning_content，yield REASONING 事件
                            # 这允许前端展示 LLM 的思考/推理过程
                            if response.reasoning_content:
                                yield AgentEvent(
                                    state=AgentState.REASONING,
                                    iteration=i,
                                    reasoning=response.reasoning_content,
                                    agent_id=self.agent_id,
                                )
                        break
                    except LLMError as overflow_err:
                        if (
                            overflow_err.type is LLMErrorType.CONTEXT_OVERFLOW
                            and _first_aid_attempts < _MAX_FIRST_AID_ATTEMPTS
                            and not getattr(overflow_err, "_saw_content_delta", False)
                        ):
                            _first_aid_attempts += 1
                            _keep_recent = 6 if _first_aid_attempts == 1 else 2
                            _before, _after = first_aid_compact(
                                messages, keep_recent=_keep_recent
                            )
                            logger.warning(
                                "run_loop 上下文溢出，第 %d 次急救压缩后重试："
                                "估算 token %d → %d (iteration %s)",
                                _first_aid_attempts,
                                _before,
                                _after,
                                i,
                            )
                            continue
                        raise

                if not response.tool_calls:
                    messages.append(
                        {
                            "role": "assistant",
                            "content": response.content,
                        }
                    )
                    yield AgentEvent(
                        state=AgentState.DONE,
                        iteration=i,
                        content=response.content,
                        agent_id=self.agent_id,
                    )
                    return

                messages.append(
                    {
                        "role": "assistant",
                        "content": response.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.name,
                                    "arguments": tc.arguments,
                                },
                            }
                            for tc in response.tool_calls
                        ],
                    }
                )

                # 审查加固: 钩子配置每轮 LLM 响应只加载一次 (原实现每个
                # tool call 都读一次 settings + 校验, 并行工具批次下 N 倍浪费)
                m6_hooks = self._load_m6_hooks()

                # ===== L6 并行只读批次 BEGIN (批次 C-3) =====
                # 全只读/免审/无钩子的批次并发执行 —— 多文件读/多搜索场景
                # 耗时从串行叠加降为最慢单工具。事件与消息仍按原顺序产出,
                # 对 LLM 与前端完全透明。不满足严格条件即回退串行。
                if self._is_parallel_eligible(
                    response.tool_calls, enforcer, m6_hooks, tool_calls_used
                ):
                    tool_calls_used += len(response.tool_calls)

                    def _run_one(tc: Any) -> Tuple[str, bool]:
                        try:
                            args_p = json.loads(tc.arguments) if isinstance(tc.arguments, str) else tc.arguments
                            tool_p = self.tool_registry.get(tc.name)
                            if tool_p is None:
                                return f"[错误] 工具不存在: {tc.name}", True
                            result_p = tool_p.execute(**args_p)
                            if hasattr(result_p, "success") and hasattr(result_p, "content"):
                                if result_p.success:
                                    value = (
                                        result_p.output
                                        if isinstance(result_p, ToolResult)
                                        and result_p.output is not None
                                        else result_p.content
                                    )
                                    return json.dumps(value, ensure_ascii=False), False
                                return result_p.error or "工具执行失败", True
                            return json.dumps(result_p, ensure_ascii=False, default=str), False
                        except Exception as exc:  # noqa: BLE001
                            logger.error(f"并行工具执行失败: {tc.name}, error: {exc}")
                            return f"[工具错误] {exc}", True

                    for tc_p in response.tool_calls:
                        yield AgentEvent(
                            state=AgentState.ACTING,
                            iteration=i,
                            tool_call=ToolCallRequest(
                                id=tc_p.id,
                                name=tc_p.name,
                                arguments=json.loads(tc_p.arguments)
                                if isinstance(tc_p.arguments, str)
                                else tc_p.arguments,
                            ),
                            agent_id=self.agent_id,
                        )

                    results_p = await asyncio.gather(
                        *(
                            asyncio.get_running_loop().run_in_executor(
                                None, functools.partial(_run_one, tc_p)
                            )
                            for tc_p in response.tool_calls
                        )
                    )

                    for tc_p, (content_p, err_p) in zip(response.tool_calls, results_p):  # noqa: B905 — py3.8 兼容(两侧等长)
                        args_p = json.loads(tc_p.arguments) if isinstance(tc_p.arguments, str) else tc_p.arguments
                        yield AgentEvent(
                            state=AgentState.OBSERVING,
                            iteration=i,
                            tool_call=ToolCallRequest(id=tc_p.id, name=tc_p.name, arguments=args_p),
                            tool_result=ToolCallResult(
                                tool_call_id=tc_p.id, content=content_p, is_error=err_p
                            ),
                            agent_id=self.agent_id,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc_p.id,
                                "content": cap_result_for_context(content_p),
                            }
                        )
                        await run_event_hooks(
                            m6_hooks,
                            "post_tool_use",
                            tc_p.name,
                            build_payload(
                                "post_tool_use",
                                tc_p.name,
                                args_p,
                                tool_output=content_p,
                                is_error=err_p,
                            ),
                        )
                    continue
                # ===== L6 并行只读批次 END =====

                for tc in response.tool_calls:
                    # L7 每-run 工具调用数守卫 (对标增强第二轮批次 B):
                    # ToolPolicy.max_tool_calls_per_run 此前只在 hex 路径生效,
                    # legacy run_loop 无刹车。超限时终止本次 run（与前端
                    # mapAgentErrorToText 的 "tool_budget_exceeded" 文案对齐）。
                    tool_calls_used += 1
                    if tool_calls_used > self._effective_max_tool_calls_per_run():
                        yield AgentEvent(
                            state=AgentState.FAILED,
                            iteration=i,
                            error="tool_budget_exceeded",
                            agent_id=self.agent_id,
                        )
                        return

                    # L7: 参数解析失败回传 LLM——此前静默变 {}，LLM 无从得知
                    # 参数错了会原样重犯。现在作为 is_error 工具结果回传，LLM
                    # 可修正参数重试。不发 ACTING 事件（工具并未执行）。
                    try:
                        args = (
                            json.loads(tc.arguments)
                            if isinstance(tc.arguments, str)
                            else tc.arguments
                        )
                    except json.JSONDecodeError as parse_err:
                        parse_content = (
                            f"[参数错误] 工具 {tc.name} 的 arguments 不是合法 JSON: {parse_err}。"
                            "请修正参数后重新调用。"
                        )
                        yield AgentEvent(
                            state=AgentState.OBSERVING,
                            iteration=i,
                            tool_call=ToolCallRequest(id=tc.id, name=tc.name, arguments={}),
                            tool_result=ToolCallResult(
                                tool_call_id=tc.id,
                                content=parse_content,
                                is_error=True,
                            ),
                            agent_id=self.agent_id,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": parse_content,
                            }
                        )
                        continue

                    # ===== M6 HOOKS BEGIN: pre_tool_use (deny/modify) =====
                    # 用户自定义钩子 (backend/hooks/)。Fail-open: 钩子故障
                    # 永不阻断循环, 仅显式 "deny" 拦截执行; "modify" 经 schema
                    # 再校验后替换参数。与 M1 enforcer 相互独立 — rebase 时
                    # 两个标记块都保留。
                    m6_pre = await run_event_hooks(
                        m6_hooks,
                        "pre_tool_use",
                        tc.name,
                        build_payload("pre_tool_use", tc.name, args),
                    )
                    if m6_pre.denied:
                        m6_deny_content = "hook 拒绝: {}".format(
                            m6_pre.reason or "denied by hook"
                        )
                        m6_deny_req = ToolCallRequest(id=tc.id, name=tc.name, arguments=args)
                        yield AgentEvent(
                            state=AgentState.ACTING,
                            iteration=i,
                            tool_call=m6_deny_req,
                            agent_id=self.agent_id,
                        )
                        yield AgentEvent(
                            state=AgentState.OBSERVING,
                            iteration=i,
                            tool_call=m6_deny_req,
                            tool_result=ToolCallResult(
                                tool_call_id=tc.id,
                                content=m6_deny_content,
                                is_error=True,
                            ),
                            agent_id=self.agent_id,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": tc.id,
                                "content": m6_deny_content,
                            }
                        )
                        continue
                    if m6_pre.modified and m6_pre.updated_input is not None:
                        m6_tool = self.tool_registry.get(tc.name)
                        m6_params = m6_tool.schema.parameters if m6_tool else None
                        m6_err = validate_modified_args(m6_pre.updated_input, m6_params)
                        if m6_err is None:
                            args = m6_pre.updated_input
                        else:
                            logger.warning(
                                "M6 hook modify ignored (schema re-validation failed): %s",
                                m6_err,
                            )
                    # ===== M6 HOOKS END =====

                    tool_req = ToolCallRequest(id=tc.id, name=tc.name, arguments=args)
                    yield AgentEvent(
                        state=AgentState.ACTING,
                        iteration=i,
                        tool_call=tool_req,
                        agent_id=self.agent_id,
                    )

                    is_error = False
                    result_content = ""

                    # M2 part B: ask_user_question —— 分发前特判（与 M1 审批同构）。
                    # 校验参数 → 发 ASK_USER_QUESTION 事件 → await 提问闸口 →
                    # 把应答注入工具执行。超时 / 闸口缺失 → 空应答软结果，循环
                    # 永不挂起。该工具有意跳过权限执行器（READ 且零副作用，
                    # 避免与提问闸口双重卡点）——因此用户 deny 规则对其不生效。
                    ask_handled = False
                    if tc.name == ASK_USER_QUESTION_TOOL_NAME:
                        ask_handled = True
                        validation_error = validate_ask_user_args(args)
                        if (
                            self._consecutive_unanswered
                            >= MAX_CONSECUTIVE_UNANSWERED_QUESTIONS
                        ):
                            # 审查加固: 防 LLM 循环提问骚扰用户
                            result_content = (
                                f"[错误] 已连续 {MAX_CONSECUTIVE_UNANSWERED_QUESTIONS} "
                                "次提问未获应答，停止提问，请直接推进任务"
                            )
                            is_error = True
                        elif validation_error is not None:
                            result_content = (
                                f"[参数错误] ask_user_question: {validation_error}"
                            )
                            is_error = True
                        else:
                            question_req = QuestionRequest.create(
                                question=args["question"],
                                options=args["options"],
                                header=args.get("header"),
                                multi_select=bool(args.get("multi_select", False)),
                            )
                            yield AgentEvent(
                                state=AgentState.ASK_USER_QUESTION,
                                iteration=i,
                                user_question=question_req.to_dict(),
                                agent_id=self.agent_id,
                            )
                            q_answer = await self._await_question_answer(question_req)
                            # gui 应答(含 Escape 空提交)清零; 超时/缺 gate 累加
                            if q_answer.answered_by == "gui":
                                self._consecutive_unanswered = 0
                            else:
                                self._consecutive_unanswered += 1
                            tool = self.tool_registry.get(tc.name)
                            if tool is None:
                                result_content = f"[错误] 工具不存在: {tc.name}"
                                is_error = True
                            else:
                                # 注入应答前剔除同名键，防 LLM 原始参数与注入冲突
                                injected_args = {
                                    k: v
                                    for k, v in args.items()
                                    if k not in ("answers", "custom")
                                }
                                q_result = tool.execute(
                                    **injected_args,
                                    answers=list(q_answer.answers),
                                    custom=q_answer.custom,
                                )
                                is_error = not q_result.success
                                if q_result.success:
                                    result_content = str(q_result.content)
                                else:
                                    result_content = q_result.error or "工具执行失败"

                    if not ask_handled:
                        # M1: enforcement-before-dispatch —— 每次工具调用先过权限
                        # 执行器（deny/allow 规则 → 模式矩阵 → bash 风险升级）。
                        # 被拒 → 注入错误 ToolResult，循环正常继续（不抛异常）。
                        decision = enforcer.check(tc.name, args)
                        if decision.needs_approval:
                            # 先推 PERMISSION_REQUEST 事件给前端，再 await 审批闸口
                            approval_req = self._build_approval_request(tc.name, args, decision)
                            yield AgentEvent(
                                state=AgentState.PERMISSION_REQUEST,
                                iteration=i,
                                permission_request=approval_req.to_dict(),
                                agent_id=self.agent_id,
                            )
                            answer = await self._await_approval_answer(approval_req)
                            if answer.approved:
                                decision = PermissionDecision(
                                    allowed=True,
                                    needs_approval=False,
                                    reason=f"{decision.reason}（用户已批准）",
                                )
                            else:
                                decision = PermissionDecision(
                                    allowed=False,
                                    needs_approval=False,
                                    reason=f"{decision.reason}（未获批准: {answer.answered_by}）",
                                )

                        if not decision.allowed:
                            logger.info(
                                "工具调用被权限执行器拒绝: tool=%s reason=%s",
                                tc.name,
                                decision.reason,
                            )
                            result_content = f"权限拒绝: {decision.reason}"
                            is_error = True
                        else:
                            try:
                                tool = self.tool_registry.get(tc.name)
                                if tool is None:
                                    result_content = f"[错误] 工具不存在: {tc.name}"
                                    is_error = True
                                else:
                                    # L12-lite: 可等待执行统一走中断竞争,
                                    # 中断先到即取消当前工具、事件循环立即恢复,
                                    # 否则语义与旧版完全一致。
                                    # live-events P0: dispatch_subagents 透传本工具
                                    # 调用 ID（helper 内注入）—— dispatcher 给子
                                    # 任务标 parent_tool_call_id，前端把子代理
                                    # 实时步骤挂到 Delegate 卡片。
                                    cancelled, result = await self._await_tool_execution(
                                        tool, tc.name, args, tool_call_id=tc.id
                                    )
                                    if cancelled:
                                        result_content = "[中断] 工具执行被用户取消"
                                        is_error = True
                                    elif hasattr(result, "success") and hasattr(result, "content"):
                                        is_error = not result.success
                                        if result.success:
                                            # ToolResult.output is the machine-readable
                                            # value (e.g. memory ID); retain content
                                            # fallback for legacy result objects.
                                            if isinstance(result, ToolResult):
                                                output_value = (
                                                    result.output
                                                    if result.output is not None
                                                    else result.content
                                                )
                                            else:
                                                output_value = result.content
                                            result_content = json.dumps(
                                                output_value, ensure_ascii=False
                                            )
                                        else:
                                            result_content = result.error or "工具执行失败"
                                    else:
                                        is_error = False
                                        result_content = json.dumps(
                                            result, ensure_ascii=False, default=str
                                        )
                            except Exception as e:
                                logger.error(f"工具执行失败: {tc.name}, error: {str(e)}")
                                result_content = f"[工具错误] {str(e)}"
                                is_error = True

                    tool_result = ToolCallResult(
                        tool_call_id=tc.id,
                        content=result_content,
                        is_error=is_error,
                    )
                    yield AgentEvent(
                        state=AgentState.OBSERVING,
                        iteration=i,
                        tool_call=tool_req,
                        tool_result=tool_result,
                        agent_id=self.agent_id,
                    )

                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "content": cap_result_for_context(result_content),
                        }
                    )

                    # ===== M6 HOOKS BEGIN: post_tool_use (observe-only) =====
                    # 观察/审计专用 — 无法修改工具结果。
                    await run_event_hooks(
                        m6_hooks,
                        "post_tool_use",
                        tc.name,
                        build_payload(
                            "post_tool_use",
                            tc.name,
                            args,
                            tool_output=result_content,
                            is_error=is_error,
                        ),
                    )
                    # ===== M6 HOOKS END =====

            yield AgentEvent(
                state=AgentState.FAILED,
                iteration=effective_max_iterations,
                error="max_iterations_exceeded",
                agent_id=self.agent_id,
            )
        finally:
            # RT5: 收窄 steering 注入窗口；残留消息一并丢弃。
            self._run_loop_active = False
            self._pending_user_messages.clear()
            # 恢复 agent 实例的原始 LLM client / config(不污染跨请求状态);
            # 动态新建的 client 一并关闭, 防止 httpx 连接泄漏。
            await self._restore_llm_after_dynamic(
                llm_config, original_llm_client, original_llm_config
            )

    # ------------------------------------------------------------------
    # M1 工具安全加固: 权限执行辅助
    # ------------------------------------------------------------------

    def _office_boundary_resolver(self) -> Optional[str]:
        """从当前会话绑定解析 workspace_root；未绑定返回 None。

        DB / 上下文查询失败时向上抛异常，不在此吞掉——校验器侧
        （``make_office_path_boundary``）会把解析失败升级为 ask（fail-closed），
        避免 DB 故障时静默放行工作区外写入。
        """
        ctx = current_tool_context()
        if ctx is None or not ctx.session_id:
            return None
        from backend.office.session_workspace import get_workspace_binding

        binding = get_workspace_binding(
            get_database().get_connection(), ctx.session_id
        )
        return binding.workspace_path if binding is not None else None

    def _build_permission_enforcer(self) -> PermissionEnforcer:
        """构造本轮 run 的权限执行器。

        优先用注入的 ``self.permission_enforcer``；否则从 settings 现读。
        office_create 的 path boundary 校验器注入：边界来自当前会话绑定
        （``_office_boundary_resolver``），写工作区外升级为 ask。
        """
        if self.permission_enforcer is not None:
            return self.permission_enforcer
        validator = make_office_path_boundary(self._office_boundary_resolver)
        try:
            return load_enforcer_from_settings(path_boundary_validator=validator)
        except Exception as exc:  # noqa: BLE001 — DB 故障不应阻塞 agent 启动
            logger.warning("权限执行器从 settings 构造失败，回退默认: %s", exc)
            return PermissionEnforcer(
                mode=DEFAULT_PERMISSION_MODE,
                rules=(),
                bash_validator=validate_bash,
                path_boundary_validator=validator,
            )

    def _build_approval_request(
        self, tool_name: str, args: Dict[str, Any], decision: PermissionDecision
    ) -> ApprovalRequest:
        """组装审批请求: 脱敏参数摘要 + bash 风险等级 + 写类工具 diff 预览（U15）。"""
        risk = "safe"
        if classify_tool(tool_name) is ToolCapability.EXECUTE:
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                risk = validate_bash(command).risk.value
        # diff 预览需要相对路径锚点 — 复用 office 边界解析器取会话绑定工作区;
        # 解析失败不阻塞审批（预览退化为 args_summary）。
        try:
            workspace_root = self._office_boundary_resolver()
        except Exception:  # noqa: BLE001 — 预览是尽力而为
            workspace_root = None
        return ApprovalRequest.create(
            tool_name=tool_name,
            args=args,
            risk=risk,
            message=decision.reason,
            workspace_root=workspace_root,
        )

    async def _await_approval_answer(self, req: ApprovalRequest) -> ApprovalAnswer:
        """await 审批闸口应答；gate 未装配时 default-deny（fail-closed）。"""
        gate = get_permission_gate()
        if gate is None:
            logger.warning(
                "权限审批闸口未初始化，default-deny: request_id=%s tool=%s",
                req.request_id,
                req.tool_name,
            )
            return ApprovalAnswer(approved=False, remember=False, answered_by="default-deny")
        timeout = (
            self.approval_timeout
            if self.approval_timeout is not None
            else DEFAULT_APPROVAL_TIMEOUT_S
        )
        return await gate.request(req, timeout=timeout)

    async def _await_question_answer(self, req: QuestionRequest) -> QuestionAnswer:
        """await 提问闸口应答；gate 未装配时按"无人应答"处理（不挂起）。

        与审批的 fail-closed 不同：提问超时/缺 gate 返回空应答，工具渲染
        "用户未回答"软结果，agent 带着它继续跑。
        """
        gate = get_question_gate()
        if gate is None:
            logger.warning(
                "提问闸口未初始化，按无人应答处理: request_id=%s", req.request_id
            )
            return QuestionAnswer(answers=(), custom=None, answered_by="timeout")
        timeout = (
            self.question_timeout
            if self.question_timeout is not None
            else DEFAULT_QUESTION_TIMEOUT_S
        )
        return await gate.request(req, timeout=timeout)

    # ===== M6 HOOKS BEGIN: config loader (fail-open) =====
    def _load_m6_hooks(self) -> List[HookConfig]:
        """加载用户自定义钩子; 任何故障 → 空列表 (fail-open)。"""
        try:
            from backend.data.settings_repo import SettingsRepository

            return load_hooks(SettingsRepository())
        except Exception as exc:
            logger.warning("M6 hooks load failed (fail-open): %s", exc)
            return []

    # ===== M6 HOOKS END =====

    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具

        M1: 同步入口同样先过权限执行器。同步上下文没有流事件通道，
        needs_approval 按 default-deny 处理（不静默放行）。

        注意：本方法是同步实现，阻塞型工具（is_blocking=True，如 bash）
        会阻塞调用线程。当前无生产调用方（仅测试引用）；若未来接入
        async 路由，需与 run_loop 分发点一致走 run_in_executor 卸载。

        Args:
            tool_name: 工具名称
            parameters: 工具参数

        Returns:
            工具执行结果
        """
        try:
            decision = self._build_permission_enforcer().check(tool_name, parameters)
            if decision.needs_approval or not decision.allowed:
                return {
                    "success": False,
                    "error": f"权限拒绝: {decision.reason}",
                }

            tool = self.tool_registry.get(tool_name)
            if tool is None:
                raise ToolCallError(tool_name, f"工具不存在: {tool_name}")

            result = tool.execute(**parameters)
            return result.to_dict()

        except ToolCallError:
            raise
        except Exception as e:
            logger.error(f"工具执行失败: {tool_name}, error: {str(e)}")
            raise ToolCallError(tool_name, str(e))

    def get_available_tools(self) -> List[Dict[str, Any]]:
        """
        获取所有可用工具的 Schema（OpenAI function-calling 格式）

        Pulls the active ``ToolExecutionContext`` (if any) from the
        ContextVar so per-request Office scoping is honored. Office-only
        tools are hidden when there is no context, and revealed when one
        is active -- normal tools are always visible.

        When ``self.profile`` is loaded with a non-empty ``tools`` list,
        that list is passed through as the registry's ``allowed_tools``
        whitelist so the LLM only sees tools the profile declared.
        ``profile=None`` or empty ``tools`` keeps the legacy behavior of
        exposing every tool.

        Returns:
            工具 Schema 列表，每个为：
            {"type": "function", "function": {"name", "description", "parameters"}}
        """
        allowed_tools = (
            self.profile.get("tools")
            if self.profile and self.profile.get("tools") is not None
            else None
        )
        schemas = self.tool_registry.get_schemas_for_llm(
            context=current_tool_context(),
            allowed_tools=allowed_tools,
        )
        return [
            {
                "type": "function",
                "function": {
                    "name": s["name"],
                    "description": s["description"],
                    "parameters": s["parameters"],
                },
            }
            for s in schemas
        ]

    def interrupt(self):
        """中断当前 Agent 操作"""
        self._interrupted = True
        # L12-lite: 唤醒工具执行的竞争等待者 (同事件循环; 跨线程调用时
        # Event.set 理论上非线程安全, 但本标志的既有语义也是尽力而为)
        event = self._interrupt_event
        if event is not None:
            with contextlib.suppress(Exception):  # 跨循环/已关闭等场景尽力而为
                event.set()
        logger.info("Agent 被中断")

    def is_interrupted(self) -> bool:
        """检查是否被中断"""
        return self._interrupted

    def reset_interrupt(self):
        """重置中断状态"""
        self._interrupted = False

    def inject_user_message(self, content: str) -> bool:
        """RT5 (round7): 运行中向当前 run 注入用户补充消息（steering）。

        消息在**下一迭代边界**以 ``【用户补充】`` 前缀的 user 消息进入
        LLM 上下文——与编排链 O1 的边界投递同语义。run 未活跃时返回
        False（调用方回退排队语义）；队列排空发生在 run_loop 内，
        ``deque.append`` 跨线程投递是 GIL 原子操作，尽力而为语义与
        interrupt() 一致。
        """
        text = (content or "").strip()
        if not text or not self._run_loop_active:
            return False
        self._pending_user_messages.append(text)
        logger.info("steering: 已接收用户补充消息 (%d 字符)，下一迭代边界生效", len(text))
        return True

    def _drain_pending_user_messages(self) -> List[Dict[str, Any]]:
        """排空待注入消息并组装为 user 消息列表（run_loop 迭代顶部调用）。"""
        drained: List[Dict[str, Any]] = []
        try:
            while self._pending_user_messages:
                drained.append(
                    {
                        "role": "user",
                        "content": f"【用户补充】{self._pending_user_messages.popleft()}",
                    }
                )
        except Exception:  # noqa: BLE001 — steering 是增强，绝不杀死 run
            logger.warning("steering: 排空待注入消息失败", exc_info=True)
        return drained

    def clear_cache(self) -> None:
        """清空查询缓存"""
        self._cache.clear()
        logger.info("查询缓存已清空")

    def cleanup_cache(self) -> int:
        """
        清理过期缓存

        Returns:
            清理的条目数
        """
        return self._cache.cleanup()

    def get_cache_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息

        Returns:
            缓存统计字典
        """
        return {
            "size": len(self._cache._cache),
            "max_size": self._cache.max_size,
            "ttl": self._cache.ttl,
        }

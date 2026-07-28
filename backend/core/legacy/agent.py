"""
SageAgent - 核心对话引擎
基于 ReAct 模式的 Agent 实现
"""

from __future__ import annotations

import asyncio
import functools
import hashlib
import json
import logging
import time
import uuid
from collections import deque
from threading import Lock
from typing import Any, Dict, List, Optional

from backend.core.errors import LLMError, LLMErrorType
from backend.core.exceptions import AgentError, ToolCallError
from backend.core.legacy.agent_state import AgentEvent, AgentState, ToolCallRequest, ToolCallResult
from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse
from backend.data.database import get_database
from backend.data.session_repo import Message as DbMessage, MessageRepository, SessionRepository

# ===== M6 HOOKS BEGIN: user-defined hooks around tool execution =====
from backend.hooks.config import HookConfig, load_hooks
from backend.hooks.runner import build_payload, run_event_hooks, validate_modified_args

# ===== M6 HOOKS END =====
from backend.memory import (
    ConsolidationPipeline,
    EpisodicMemory,
    MemoryManager,
    SemanticMemory,
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

#: M2b 审查加固: 连续未应答提问上限。超时软结果使循环继续, 若无此限,
#: 被操纵/犯错的 LLM 可循环提问持续骚扰用户。超限后直接返回错误结果。
MAX_CONSECUTIVE_UNANSWERED_QUESTIONS = 3
from backend.tools.bash_validation import validate_bash
from backend.tools.context import current_tool_context
from backend.tools.permissions import (
    DEFAULT_PERMISSION_MODE,
    PermissionDecision,
    PermissionEnforcer,
    ToolCapability,
    classify_tool,
    load_enforcer_from_settings,
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
        """
        self.session_repo = SessionRepository()
        self.message_repo = MessageRepository()
        self._interrupted = False
        self._current_session_id: Optional[str] = None

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
        self._cache = QueryCache(ttl=300, max_size=100)
        logger.info("查询缓存初始化完成，TTL=300秒，最大条目=100")

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
            self.memory_manager = MemoryManager(working, episodic, semantic)

            # 初始化工具注册表
            self.tool_registry = ToolRegistry()
            register_all_tools(self.tool_registry)
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
            self.consolidation = ConsolidationPipeline(llm_client=self.llm_client)

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
            # 检查缓存
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
            memory_context = self.memory_manager.get_context(limit=10)

            # 将用户消息添加到工作记忆
            self.memory_manager.add_to_working("user", message)

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
            self.memory_manager.add_to_working("assistant", assistant_message["content"])

            # 对话后：提取关键信息存入情景记忆
            self._extract_and_save_memories(session_id, user_message, assistant_message)

            # 对话后：检查是否需要压缩工作记忆
            if self.memory_manager.working.total_tokens > 3000:
                self.consolidation.consolidate(self.memory_manager, session_id=session_id)

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

            # 存入缓存
            self._cache.set(session_id, message, result)

            # 恢复原始 LLM 配置
            if llm_config:
                self.llm_config = original_llm_config
                self.llm_client = original_llm_client

            return result

        except LLMError as e:
            logger.error(f"chat LLM 错误: type={e.type.value}, message={e.message}")
            # 恢复原始 LLM 配置
            if llm_config:
                self.llm_config = original_llm_config
                self.llm_client = original_llm_client
            return {
                "error": e.to_dict(),
                "message": None,
                "session": None,
            }
        except Exception as e:
            logger.exception(f"chat 处理异常: {str(e)}")
            # 恢复原始 LLM 配置
            if llm_config:
                self.llm_config = original_llm_config
                self.llm_client = original_llm_client
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

    async def run_loop(
        self,
        messages: List[Dict[str, Any]],
        max_iterations: Optional[int] = None,
        llm_config: Optional[Dict[str, Any]] = None,
    ):
        """ReAct 主循环。

        状态机:IDLE → THINKING → (ACTING → OBSERVING)* → DONE/FAILED

        Args:
            messages: 完整消息历史（含 system/user/assistant/tool），会被就地修改
            max_iterations: 最大循环次数，防止死循环。None 时取 profile.max_iterations
                (若 profile 也不存在, 兜底 5)。显式传入的 int 覆盖 profile 值。
            llm_config: 可选的动态 LLM 配置(覆盖初始化时的配置),允许调用方
                在 agent 实例没有默认 LLM 时通过 per-request 配置运行。
                如果同时存在 self.llm_client,会临时覆盖并在循环结束后恢复。

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

        # 阶段 1: max_iterations 默认从 profile 读, 否则兜底 5
        effective_max_iterations = (
            max_iterations
            if max_iterations is not None
            else (self.profile.get("max_iterations", 5) if self.profile else 5)
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

        # M1: 权限执行器在 run 起点构造一次（读 settings: permission_mode /
        # permission_rules），整轮循环复用——避免每次工具调用都打 DB。
        enforcer = self._build_permission_enforcer()

        try:
            for i in range(effective_max_iterations):
                yield AgentEvent(state=AgentState.THINKING, iteration=i, agent_id=self.agent_id)

                # Pass available tools to LLM so it can call them
                available_tools = self.get_available_tools()
                response: LLMResponse = await self.llm_client.chat(
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

                for tc in response.tool_calls:
                    try:
                        args = (
                            json.loads(tc.arguments)
                            if isinstance(tc.arguments, str)
                            else tc.arguments
                        )
                    except json.JSONDecodeError:
                        args = {}

                    # ===== M6 HOOKS BEGIN: pre_tool_use (deny/modify) =====
                    # 用户自定义钩子 (backend/hooks/)。Fail-open: 钩子故障
                    # 永不阻断循环, 仅显式 "deny" 拦截执行; "modify" 经 schema
                    # 再校验后替换参数。与 M1 enforcer 相互独立 — rebase 时
                    # 两个标记块都保留。
                    m6_hooks = self._load_m6_hooks()
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
                                    if tc.name == "agent":
                                        # The agent tool blocks (future.result on
                                        # the sub-run, bounded by
                                        # SUBAGENT_TIMEOUT_S). Run it on an
                                        # executor thread so the event loop stays
                                        # responsive (health endpoint, board
                                        # polling, other sessions) during the
                                        # whole sub-run. Minimal special-case —
                                        # general tool dispatch stays inline.
                                        # ContextVar note: run_in_executor copies
                                        # the current context (Python 3.7.1+);
                                        # harmless here because AgentTool.execute
                                        # never reads the ToolExecutionContext
                                        # ContextVar — it builds all of its state
                                        # itself (verified in
                                        # backend/tools/agent_tool.py).
                                        result = await asyncio.get_running_loop().run_in_executor(
                                            None, functools.partial(tool.execute, **args)
                                        )
                                    else:
                                        result = tool.execute(**args)
                                    if hasattr(result, "success") and hasattr(result, "content"):
                                        is_error = not result.success
                                        if result.success:
                                            result_content = json.dumps(
                                                result.content, ensure_ascii=False
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
                            "content": result_content,
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
            # 恢复 agent 实例的原始 LLM client / config(不污染跨请求状态)
            if llm_config:
                self.llm_client = original_llm_client
                self.llm_config = original_llm_config

    # ------------------------------------------------------------------
    # M1 工具安全加固: 权限执行辅助
    # ------------------------------------------------------------------

    def _build_permission_enforcer(self) -> PermissionEnforcer:
        """构造本轮 run 的权限执行器。

        优先用注入的 ``self.permission_enforcer``（测试 / 特殊装配）；
        否则从 settings 现读（permission_mode / permission_rules）。
        settings 不可用时降级为默认模式 workspace_write + 无规则。
        """
        if self.permission_enforcer is not None:
            return self.permission_enforcer
        try:
            return load_enforcer_from_settings()
        except Exception as exc:  # noqa: BLE001 — DB 故障不应阻塞 agent 启动
            logger.warning("权限执行器从 settings 构造失败，回退默认: %s", exc)
            return PermissionEnforcer(
                mode=DEFAULT_PERMISSION_MODE, rules=(), bash_validator=validate_bash
            )

    def _build_approval_request(
        self, tool_name: str, args: Dict[str, Any], decision: PermissionDecision
    ) -> ApprovalRequest:
        """组装审批请求: 脱敏参数摘要 + bash 风险等级（非 EXECUTE 工具为 safe）。"""
        risk = "safe"
        if classify_tool(tool_name) is ToolCapability.EXECUTE:
            command = args.get("command")
            if isinstance(command, str) and command.strip():
                risk = validate_bash(command).risk.value
        return ApprovalRequest.create(
            tool_name=tool_name, args=args, risk=risk, message=decision.reason
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

        Returns:
            工具 Schema 列表，每个为：
            {"type": "function", "function": {"name", "description", "parameters"}}
        """
        schemas = self.tool_registry.get_schemas_for_llm(
            context=current_tool_context(),
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
        logger.info("Agent 被中断")

    def is_interrupted(self) -> bool:
        """检查是否被中断"""
        return self._interrupted

    def reset_interrupt(self):
        """重置中断状态"""
        self._interrupted = False

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

"""
SageAgent - 核心对话引擎
基于 ReAct 模式的 Agent 实现
"""

from __future__ import annotations
from typing import Dict, List, Optional

import hashlib
import json
import logging
import time
import uuid
from collections import deque
from threading import Lock
from typing import Any

from backend.core.errors import LLMError, LLMErrorType
from backend.core.exceptions import AgentError, ToolCallError
from backend.core.legacy.agent_state import AgentEvent, AgentState, ToolCallRequest, ToolCallResult
from backend.core.legacy.llm_client import LLMClient, LLMConfig, LLMResponse
from backend.data.database import get_database
from backend.data.session_repo import Message as DbMessage, MessageRepository, SessionRepository
from backend.memory import (
    ConsolidationPipeline,
    EpisodicMemory,
    MemoryManager,
    SemanticMemory,
    WorkingMemory,
)
from backend.tools import ToolRegistry, register_all_tools

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
    ):
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

        # 初始化记忆压缩管道
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

                    tool_req = ToolCallRequest(id=tc.id, name=tc.name, arguments=args)
                    yield AgentEvent(
                        state=AgentState.ACTING,
                        iteration=i,
                        tool_call=tool_req,
                        agent_id=self.agent_id,
                    )

                    is_error = False
                    result_content = ""
                    try:
                        tool = self.tool_registry.get(tc.name)
                        if tool is None:
                            result_content = f"[错误] 工具不存在: {tc.name}"
                            is_error = True
                        else:
                            result = tool.execute(**args)
                            if hasattr(result, "success") and hasattr(result, "content"):
                                is_error = not result.success
                                if result.success:
                                    result_content = json.dumps(result.content, ensure_ascii=False)
                                else:
                                    result_content = result.error or "工具执行失败"
                            else:
                                is_error = False
                                result_content = json.dumps(result, ensure_ascii=False, default=str)
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

    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行工具

        Args:
            tool_name: 工具名称
            parameters: 工具参数

        Returns:
            工具执行结果
        """
        try:
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

        Returns:
            工具 Schema 列表，每个为：
            {"type": "function", "function": {"name", "description", "parameters"}}
        """
        schemas = self.tool_registry.get_schemas_for_llm()
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

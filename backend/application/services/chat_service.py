"""ChatService — 编排 6 个 ports（LLM / Tool / Skill / Storage / Metric / Event）。

这是 application 层唯一一个 PG2 阶段落地的"用例服务"，承担一次
完整对话轮次（user message → 持久化 → 拉历史 → 调 LLM → 工具
执行（可选） → 持久化回复）的全部编排。

设计要点
--------

- **不依赖具体 adapter**：仅通过 ``backend.ports.*`` 中的
  ``Protocol`` 类型与外部能力交互；具体实现（``HttpxLLMAdapter``、
  ``SqliteStorageAdapter``、…）由 API 路由层在装配时注入。
- **单轮 LLM 调用**：PG2.9 阶段不实现 ReAct 多轮循环；如模型
  首次响应携带 ``tool_calls``，**只执行**一次工具并把
  ``ToolResult`` 暂存到上下文（**不**触发二次 LLM 调用）。
  完整多轮 ReAct 计划在 P3+。
- **可观测性内置**：每个关键步骤都会 emit 事件（``EventPort``）
  并 increment 计数器（``MetricPort``）；为 P3.x 的 Grafana /
  审计日志面板预留埋点。
- **错误透传**：``LLMError`` 不在 Service 内吞掉，统一由 API
  路由层翻译为 HTTP 响应；Service 只在指标 / 事件层记录。
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from sage_core import LLMError, Message, Role, ToolCall
from sage_core.repositories import EventPort, LLMPort, MetricPort, SkillPort, StoragePort, ToolPort

# Optional memory types (for backward compatibility)
try:
    from backend.domain.memory import MemoryContext
    from backend.ports.memory import MemoryPort
except ImportError:
    MemoryPort = None  # type: ignore
    MemoryContext = None  # type: ignore

from backend.domain.agent_event import RunEventScope
from backend.domain.tool_policy import ToolPolicy
from backend.utils.otel import get_tracer

logger = logging.getLogger(__name__)

# 默认拉取的历史消息窗口大小（最新 N 条）
_DEFAULT_HISTORY_LIMIT = 20

# 默认 LLM 调用计数 label
_DEFAULT_MODEL_LABEL = "default"

# OTel tracer（P3.3：用于在 span 上记录关键属性）
_tracer = get_tracer("chat_service")

# PrometheusMetricAdapter 9 指标名（spec § 6.1）— 集中定义便于复用
_LLM_CALL_DURATION_METRIC = "sage_llm_call_duration_seconds"
_LLM_CALLS_METRIC = "sage_llm_calls_total"
_TOKENS_CONSUMED_METRIC = "sage_tokens_consumed_total"
_REACT_STEPS_METRIC = "sage_react_steps_per_request"
_TOOL_INVOCATIONS_METRIC = "sage_tool_invocations_total"
_ERRORS_METRIC = "sage_errors_total"
_ACTIVE_SESSIONS_METRIC = "sage_active_sessions"


class ChatService:
    """通过 6 个 ports 编排一次对话轮次。

    装配时由 API 路由层注入具体 adapter。Service 本身只持有
    ports 抽象（structural typing，Protocol），不耦合任何 I/O
    框架或具体实现，便于单测用 mock 替换。
    """

    def __init__(
        self,
        llm: LLMPort,
        tools: ToolPort,
        skills: SkillPort,
        storage: StoragePort,
        metrics: MetricPort,
        events: EventPort,
        memory: MemoryPort | None = None,  # Optional for backward compatibility
        tool_policy: ToolPolicy | None = None,  # M2 工具调用预算守卫
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.skills = skills
        self.storage = storage
        self.metrics = metrics
        self.events = events
        self.memory = memory  # MemoryPort for memory integration
        self._tool_policy = tool_policy or ToolPolicy()
        # P3.2: 当前活跃 session 计数（用于 sage_active_sessions gauge）
        self._active_session_count: int = 0

    # ------------------------------------------------------------------ #
    # 会话生命周期（含审计事件 + Prometheus 指标）
    # ------------------------------------------------------------------ #

    async def create_session(self, title: str = "") -> str:
        """创建新会话并 emit ``session_created`` 审计事件 + ``active_sessions`` 计数 +1。

        P3.2 引入：业务方（API 路由 / CLI）应通过本方法建会话，而不是直接调
        ``self.storage.create_session``，确保审计与指标的"session_created"埋点
        不会被遗漏。

        P3.3 增强：包一层 OTel span ``session.create``，便于在 trace 后端
        查看"创建会话"步骤的耗时与上下文。
        """
        with _tracer.start_as_current_span("session.create") as span:
            session_id = await self.storage.create_session(title=title)
            span.set_attribute("session.id", session_id)
            # 审计事件：与 spec § 6.1 5 类事件对齐
            self.events.emit(
                "session_created",
                {"session_id": session_id, "title": title},
            )
            # 9 指标之一：active_sessions gauge（set 绝对值）
            self._active_session_count += 1
            self.metrics.gauge(
                _ACTIVE_SESSIONS_METRIC,
                float(self._active_session_count),
                {},
            )
            return session_id

    async def delete_session(self, session_id: str) -> None:
        """删除会话（仅当会话存在时减计数）。"""
        await self.storage.delete_session(session_id)
        self._active_session_count = max(0, self._active_session_count - 1)
        self.metrics.gauge(
            _ACTIVE_SESSIONS_METRIC,
            float(self._active_session_count),
            {},
        )

    # ------------------------------------------------------------------ #
    # 主入口：执行一轮对话
    # ------------------------------------------------------------------ #

    async def run_turn(
        self,
        session_id: str,
        user_message: Message,
    ) -> list[Message]:
        """执行一轮对话（含 ReAct 工具调用——PG2.9 阶段只做单轮）。

        Args:
            session_id:   会话 ID（必须已存在；如未存在，append_message
                          会按 ``MemoryStorageAdapter`` 行为自动建会话）。
            user_message: 用户消息（``role=USER``）。

        Returns:
            ``[user_message, assistant_response]``——返回值包含用户原始
            消息与 assistant 回复，便于路由层做"完整回显"。

        Raises:
            LLMError: 由底层 ``LLMPort`` 抛出（不吞掉）。
        """
        # P3.3: 包一层 OTel span，覆盖整个 run_turn 生命周期。
        # 子 span（llm.chat / tool.execute）由底层 adapter 自动 nest。
        with _tracer.start_as_current_span("chat.run_turn") as span:
            span.set_attribute("session.id", session_id)
            span.set_attribute("message.role", user_message.role.value)
            return await self._run_turn_inner(session_id, user_message, span)

    async def _run_turn_inner(
        self,
        session_id: str,
        user_message: Message,
        span: Any,
    ) -> list[Message]:
        """``run_turn`` 的实际实现，调用方需已开好 OTel span。"""
        # M1: run-lifecycle 事件作用域（稳定 run_id + 单调 seq）
        run = RunEventScope(self.events, uuid.uuid4().hex)
        run.emit("run_start", session_id=session_id)
        run.emit("turn_start", session_id=session_id)

        # 1) 持久化 user message
        await self.storage.append_message(session_id, user_message)
        self.events.emit(
            "chat_message_sent",
            {"session_id": session_id, "role": Role.USER.value},
        )

        # 1.5) 检索相关记忆 (Memory Integration)
        memory_context: MemoryContext | None = None
        if self.memory:
            try:
                memory_context = await self.memory.retrieve(
                    query=user_message.content,
                    session_id=session_id,
                    limit=5,
                )
                span.set_attribute("memory.has_memories", memory_context.has_memories)
            except Exception as e:
                logger.warning(f"Failed to retrieve memories: {e}")
                span.set_attribute("memory.error", str(e))

        # 2) 拉取历史上下文（用于喂给 LLM）
        history = await self.storage.get_messages(
            session_id,
            limit=_DEFAULT_HISTORY_LIMIT,
        )
        span.set_attribute("history.size", len(history))

        # Inject system prompt (including diagram tool guidance if available)
        from backend.agents.profiles import build_system_base

        system_content = build_system_base()
        try:
            from backend.core.diagram_prompt import DIAGRAM_TOOL_PROMPT

            # Check if diagram tools are available in the tool registry
            if self.tools and any("drawio" in t.name for t in self.tools.list()):
                system_content += DIAGRAM_TOOL_PROMPT
        except Exception:
            pass

        # 2.5) 注入记忆上下文到 system prompt (Memory Integration)
        if memory_context and memory_context.has_memories:
            system_content += "\n\n以下是相关的记忆上下文:\n"
            system_content += memory_context.format()

        # Prepend system message to history
        system_msg = Message(role=Role.SYSTEM, content=system_content)
        history = [system_msg] + list(history)

        # 3) 调 LLM（单次调用；错误时记 metric + event 后透传）
        # 埋点：LLM 调用计数（9 指标之一）
        self.metrics.counter(
            _LLM_CALLS_METRIC,
            {
                "model": _DEFAULT_MODEL_LABEL,
                "provider": "default",
                "outcome": "started",
            },
        )
        start = time.monotonic()
        try:
            # Build tool schemas for LLM (OpenAI function-calling format)
            llm_tools = None
            if self.tools:
                tool_specs = self.tools.list_tools()
                logger.info(f"[ChatService] ToolPort.list_tools() returned {len(tool_specs)} tools")
                if tool_specs:
                    llm_tools = [
                        {
                            "type": "function",
                            "function": {
                                "name": ts.name,
                                "description": ts.description,
                                "parameters": ts.parameters,
                            },
                        }
                        for ts in tool_specs
                    ]
                    logger.info(
                        f"[ChatService] Passing {len(llm_tools)} tools to LLM: {[t['function']['name'] for t in llm_tools]}"
                    )
                else:
                    logger.warning("[ChatService] ToolPort.list_tools() returned empty list!")
            else:
                logger.warning("[ChatService] self.tools is None!")

            response = await self.llm.chat(history, tools=llm_tools)
        except LLMError as exc:
            duration = time.monotonic() - start
            # 失败也记直方图，便于看错误率 / 失败延迟分布
            self.metrics.histogram(
                _LLM_CALL_DURATION_METRIC,
                duration,
                {"model": _DEFAULT_MODEL_LABEL},
            )
            self.metrics.counter(
                _LLM_CALLS_METRIC,
                {
                    "model": _DEFAULT_MODEL_LABEL,
                    "provider": "default",
                    "outcome": "error",
                },
            )
            self.events.emit(
                "llm_error",
                {"session_id": session_id, "type": exc.type.value},
            )
            self.metrics.counter(
                _ERRORS_METRIC,
                {"layer": "llm", "error_type": exc.type.value},
            )
            span.set_attribute("error", True)
            span.set_attribute("error.type", exc.type.value)
            run.emit("run_end", session_id=session_id, status="error", error_type=exc.type.value)
            raise

        # 成功路径：直方图 + 成功 outcome
        duration = time.monotonic() - start
        self.metrics.histogram(
            _LLM_CALL_DURATION_METRIC,
            duration,
            {"model": _DEFAULT_MODEL_LABEL},
        )
        self.metrics.counter(
            _LLM_CALLS_METRIC,
            {
                "model": _DEFAULT_MODEL_LABEL,
                "provider": "default",
                "outcome": "success",
            },
        )
        span.set_attribute("llm.duration_ms", int(duration * 1000))
        span.set_attribute("response.has_tool_calls", bool(response.tool_calls))

        # 4) 执行模型发起的 tool_calls（PG2.9：单轮执行；不触发二次 LLM）
        budget_exceeded = False
        if response.tool_calls:
            budget_exceeded = await self._execute_tool_calls(session_id, response.tool_calls, run)
            # 埋点：ReAct 步数（9 指标之一）— 本轮触发的 tool_call 数
            self.metrics.histogram(
                _REACT_STEPS_METRIC,
                float(len(response.tool_calls)),
                {},
            )
            span.set_attribute("tool_calls.count", len(response.tool_calls))

        # 5) 持久化 assistant response（即使触发了 tool_calls，
        #    仍把 LLM 原始的 assistant message 落库）
        await self.storage.append_message(session_id, response)
        self.events.emit(
            "chat_response_completed",
            {"session_id": session_id},
        )

        # 6) 埋点：token 消耗（9 指标之一）— 仅在响应携带 usage 时记录
        # MetricPort 的 counter 只能 inc(1)；此处用 Counter 表示
        # "至少发生了一次 token 消耗" 的事件计数。精确的 token 总数
        # 在 LLM 客户端 / 适配器层独立记录（不在 P3.1 范围）。
        usage = getattr(response, "usage", None)
        if isinstance(usage, dict) and usage:
            model_label = str(usage.get("model", _DEFAULT_MODEL_LABEL))
            prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens = int(usage.get("completion_tokens", 0) or 0)
            if prompt_tokens > 0:
                self.metrics.counter(
                    _TOKENS_CONSUMED_METRIC,
                    {"model": model_label, "kind": "prompt"},
                )
            if completion_tokens > 0:
                self.metrics.counter(
                    _TOKENS_CONSUMED_METRIC,
                    {"model": model_label, "kind": "completion"},
                )
            span.set_attribute("tokens.prompt", prompt_tokens)
            span.set_attribute("tokens.completion", completion_tokens)

        # 7) 提取并存储记忆 (Memory Integration)
        if self.memory:
            try:
                await self._extract_and_store_memory(
                    session_id=session_id,
                    user_message=user_message,
                    assistant_message=response,
                )
            except Exception as e:
                logger.warning(f"Failed to store memory: {e}")
                span.set_attribute("memory.store_error", str(e))

            # 8) 压缩工作记忆 (Memory Integration)
            try:
                await self.memory.compress(session_id)
            except Exception as e:
                logger.warning(f"Failed to compress working memory: {e}")
                span.set_attribute("memory.compress_error", str(e))

        run.emit(
            "run_end",
            session_id=session_id,
            status="tool_budget_exceeded" if budget_exceeded else "ok",
        )
        return [user_message, response]

    # ------------------------------------------------------------------ #
    # 内部辅助：记忆提取与存储 (Memory Integration)
    # ------------------------------------------------------------------ #

    async def _extract_and_store_memory(
        self,
        session_id: str,
        user_message: Message,
        assistant_message: Message,
    ) -> None:
        """从对话中提取关键信息并存入记忆系统

        使用 LLM 驱动的事实提取（MemoryExtractor），自动检测对话中的
        关键信息并存储到记忆系统。当 LLM 不可用时降级为关键词提取。

        Args:
            session_id: 会话 ID
            user_message: 用户消息
            assistant_message: 助手消息
        """
        if not self.memory:
            return

        from backend.memory.extractor import MemoryExtractor

        extractor = MemoryExtractor(llm_client=self.llm)
        facts = await extractor.extract(
            user_message=user_message.content or "",
            assistant_message=assistant_message.content or "",
        )

        for fact in facts:
            await self.memory.store(
                content=fact["content"],
                session_id=session_id,
                importance=fact.get("importance", 5),
                tags=fact.get("tags", ["conversation"]),
            )

        if facts:
            logger.debug(f"Extracted {len(facts)} facts for session {session_id}")

    # ------------------------------------------------------------------ #
    # 内部辅助：执行 tool_calls
    # ------------------------------------------------------------------ #

    async def _execute_tool_calls(
        self,
        session_id: str,
        tool_calls: list[ToolCall],
        run: RunEventScope,
    ) -> bool:
        """执行模型返回的 tool_calls，依次 emit 事件 / 计数 / 持久化。

        PG2.9 简化：每个 tool_call 都立即执行（不并发）、执行结果
        作为 ``role=TOOL`` 消息追加到会话历史，但不重新调 LLM。
        这样 P3+ 在此基础上扩展 ReAct 多轮循环时，行为是"在末尾
        加一层循环"，向后兼容。

        M2 工具调用预算守卫：单次 run 内 tool_call 累计超
        ``tool_policy.max_tool_calls_per_run`` 时停止执行；返回 ``True`` 让
        上层把 ``run_end`` 标记为 ``status="tool_budget_exceeded"``（对齐
        ``core/legacy/agent.py:611`` 的 ``max_iterations_exceeded`` 语义）。

        Returns:
            ``True`` 当预算被超额；否则 ``False``。
        """
        budget = self._tool_policy.max_tool_calls_per_run
        called = 0
        for tc in tool_calls:
            if called >= budget:
                # 预算用尽：剩余 tool_calls 不再执行，直接 break。
                break
            self.events.emit(
                "tool_invoked",
                {"session_id": session_id, "tool": tc.name, "args": tc.args},
            )
            # 新 9 指标命名：成功/失败由 outcome 区分
            self.metrics.counter(
                _TOOL_INVOCATIONS_METRIC,
                {"tool": tc.name, "outcome": "started"},
            )
            result = await self.tools.execute(tc.name, tc.args)
            # 把工具结果作为 TOOL 消息回写会话历史
            tool_message = Message(
                role=Role.TOOL,
                content=result.output if result.success else (result.error or ""),
                tool_call_id=tc.id,
            )
            await self.storage.append_message(session_id, tool_message)
            called += 1
            # M1: 对称的 tool_result 事件（与 tool_invoked 成对，带 run_id + seq）
            run.emit(
                "tool_result",
                session_id=session_id,
                tool=tc.name,
                success=result.success,
                error=result.error if not result.success else None,
            )
            if not result.success:
                self.events.emit(
                    "tool_failed",
                    {
                        "session_id": session_id,
                        "tool": tc.name,
                        "error": result.error,
                    },
                )
                self.metrics.counter(
                    _TOOL_INVOCATIONS_METRIC,
                    {"tool": tc.name, "outcome": "error"},
                )
                self.metrics.counter(
                    _ERRORS_METRIC,
                    {"layer": "tool", "error_type": "tool_failed"},
                )
            else:
                self.metrics.counter(
                    _TOOL_INVOCATIONS_METRIC,
                    {"tool": tc.name, "outcome": "success"},
                )
        return called >= budget and len(tool_calls) > budget

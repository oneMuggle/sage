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
import weakref
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional, Union

from sage_core import LLMError, Message, Role, ToolCall
from sage_core.repositories import EventPort, LLMPort, MetricPort, SkillPort, StoragePort, ToolPort

from backend.application.services.wake_store import WakeStore
from backend.domain.wake import Wake, WakeKind, to_utc_iso

# Optional memory types (for backward compatibility)
try:
    from backend.domain.memory import MemoryContext
    from backend.ports.memory import MemoryPort
except ImportError:
    MemoryPort = None  # type: ignore
    MemoryContext = None  # type: ignore

from backend.domain.agent_event import RunEventScope
from backend.domain.tool_policy import ToolPolicy
from backend.orchestration.permission import (
    AgentAction,
    LanePermission,
    PermissionPreset,
)
from backend.utils.otel import get_tracer

logger = logging.getLogger(__name__)

# 默认拉取的历史消息窗口大小（最新 N 条）
_DEFAULT_HISTORY_LIMIT = 20

# 默认 LLM 调用计数 label
_DEFAULT_MODEL_LABEL = "default"

# 技能 Nudge（借鉴 hermes-agent ``_iters_since_skill`` 的轻量版）:
# 单轮工具调用数达到阈值且未自动激活任何技能时, 在 assistant 回复末尾
# 追加一句"建议保存为技能"的提示。best-effort: 仅在 hex 路径生效,
# 阈值 4 以下不触发, 避免打扰简单对话。
SKILL_NUDGE_TOOL_CALL_THRESHOLD = 4
SKILL_NUDGE_SUFFIX = (
    "\n\n💡 这个任务涉及多次工具调用。"
    "如果它可能是你会重复的流程，可以考虑把它保存为一个技能（SKILL.md）。"
)

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
# A4 Suspend-Resume: 注册的 wake 计数（kind 维度）
_WAKES_CREATED_METRIC = "sage_wakes_created_total"


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
        memory: Optional[MemoryPort] = None,  # Optional for backward compatibility
        tool_policy: Optional[ToolPolicy] = None,  # M2 工具调用预算守卫
        permission_preset: Optional[PermissionPreset] = None,  # M3 权限预设
        permission_allowed_paths: Optional[List[str]] = None,  # M3 允许的路径
        permission_denied_tools: Optional[List[str]] = None,  # M3 黑名单
        lifecycle: Optional[Any] = None,  # Task 4 / Gap A — optional MemoryLifecycleManager
        wake_store: Optional[WakeStore] = None,  # A4 Suspend-Resume 唤醒仓储
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.skills = skills
        self.storage = storage
        self.metrics = metrics
        self.events = events
        self.memory = memory  # MemoryPort for memory integration
        self._lifecycle = lifecycle
        self._current_turn_id: Optional[str] = None
        self.wake_store = wake_store  # A4: None 时挂起 API 静默降级为 no-op
        self._tool_policy = tool_policy or ToolPolicy()
        # M3: 构造 LanePermission；缺省 IMPLEMENT 保持向后兼容
        self._permission = LanePermission(
            preset=permission_preset or PermissionPreset.IMPLEMENT,
            allowed_paths=list(permission_allowed_paths or []),
            denied_tools=list(permission_denied_tools or []),
        )
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
        extra_system_messages: Optional[List[Message]] = None,
    ) -> List[Message]:
        """执行一轮对话（含 ReAct 工具调用——PG2.9 阶段只做单轮）。

        Args:
            session_id:   会话 ID（必须已存在；如未存在，append_message
                          会按 ``MemoryStorageAdapter`` 行为自动建会话）。
            user_message: 用户消息（``role=USER``）。
            extra_system_messages:
                          临时 (request-scoped) system messages。仅用于
                          本轮 LLM 调用, 不写入 storage, 不进历史。典型
                          用例: Office @-mention 附件块 — 应当跟随
                          mention 出现, 而非永久留在会话 history。
                          按参数顺序在 ``build_system_base()`` 之后、
                          history user/assistant 之前插入。

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
            return await self._run_turn_inner(
                session_id,
                user_message,
                span,
                extra_system_messages,
            )

    async def _run_turn_inner(
        self,
        session_id: str,
        user_message: Message,
        span: Any,
        extra_system_messages: Optional[List[Message]] = None,
    ) -> List[Message]:
        """``run_turn`` 的实际实现，调用方需已开好 OTel span。"""
        # M1: run-lifecycle 事件作用域（稳定 run_id + 单调 seq）
        run = RunEventScope(self.events, uuid.uuid4().hex)
        run.emit("run_start", session_id=session_id)
        run.emit("turn_start", session_id=session_id)

        # F4 — expose the current turn id so memory extraction can tag stored
        # facts with the producing turn; also drive the lifecycle's
        # set_current_turn (production caller for the traceability hook).
        self._current_turn_id = run.run_id
        if self._lifecycle is not None:
            try:
                self._lifecycle.set_current_turn(run.run_id)
            except Exception as exc:  # noqa: BLE001 — never break the turn
                logger.warning("run_turn: set_current_turn failed: %s", exc)

        # 1) 持久化 user message
        # Gap E — capture the persisted message id so extracted facts can point
        # at the real message (Chat renders it as data-turn-id={message.id}).
        user_message_id = await self.storage.append_message(session_id, user_message)
        self.events.emit(
            "chat_message_sent",
            {"session_id": session_id, "role": Role.USER.value},
        )

        # 1.5) 检索相关记忆 (Memory Integration)
        memory_context: Optional[MemoryContext] = None
        if self.memory:
            try:
                # Important-2 (final review) — memory_retrieval preference
                # gate. The Settings UI's "记忆检索注入" toggle drives this
                # independently of auto_memory. Lifecycle exposes
                # is_memory_retrieval_enabled() (30s-cached, default True,
                # fail-open); the legacy path (no lifecycle) keeps retrieval
                # unconditionally enabled for backward compat.
                retrieval_enabled = True
                if self._lifecycle is not None:
                    retrieval_enabled = (
                        await self._lifecycle.is_memory_retrieval_enabled()
                    )
                if retrieval_enabled:
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

        # 2.6) A16: Skill Auto-Activation —— 扫描用户消息匹配 SKILL.md
        #      ``when_to_use`` 触发短语, 命中技能的 body 注入本轮 system
        #      prompt 动态段 (不进 frozen snapshot 缓存, 不写 storage,
        #      下一轮按新消息重新匹配)。best-effort: 任何故障静默降级。
        activation_block = _skill_activation_block(
            user_message.content or "", self.skills
        )
        if activation_block:
            system_content += activation_block
            span.set_attribute("skills.auto_activated", True)

        # Prepend system message to history
        system_msg = Message(role=Role.SYSTEM, content=system_content)
        history = [system_msg] + list(history)

        # 2.7) 注入 request-scoped extras (T4.M2 closure):
        #      Office @-mention 附件块走这里, 不写 storage,
        #      下一轮 LLM 调用不会重复看到历史 turn 的 mention 摘要.
        #      与 legacy /chat/stream 的 in-memory messages 对齐.
        if extra_system_messages:
            history = list(history) + list(extra_system_messages)

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

        # 4.5) 技能 Nudge（best-effort）: 单轮工具调用 ≥ 阈值且未自动激活技能
        #      时, 在 assistant 回复末尾追加"建议保存为技能"的提示。
        #      仅在 response 有正文时生效; 任何异常降级跳过, 不破坏对话轮次。
        #
        #      4.5.1) Background Review 信号检测：同一条件触发
        #      review event enqueue（complex_turn），供后台 worker 分析
        #      并可能生成新技能草稿。best-effort：review queue 不可用时
        #      静默降级，不影响对话热路径。
        try:
            tool_call_count = len(response.tool_calls or [])
            is_complex_turn = (
                tool_call_count >= SKILL_NUDGE_TOOL_CALL_THRESHOLD
                and not activation_block
            )

            if response.content and is_complex_turn:
                response.content = (response.content or "") + SKILL_NUDGE_SUFFIX
                span.set_attribute("skills.nudge_applied", True)

            # 4.5.1) Background Review: enqueue complex_turn signal
            if is_complex_turn:
                from backend.skills.review_queue import get_review_queue

                review_queue = get_review_queue()
                # ToolCall 数据类不可直接 JSON 序列化，转为 dict
                tool_calls_serialized = [
                    {"name": tc.name, "args": tc.args}
                    for tc in (response.tool_calls or [])
                ]
                review_queue.enqueue(
                    trigger_type="complex_turn",
                    session_id=session_id,
                    context={
                        "tool_calls": tool_calls_serialized,
                        "tool_call_count": tool_call_count,
                        "threshold": SKILL_NUDGE_TOOL_CALL_THRESHOLD,
                    },
                )
                span.set_attribute("review.complex_turn_enqueued", True)
        except Exception as exc:  # noqa: BLE001 - best-effort 契约
            logger.debug(f"Skill nudge / review signal skipped: {exc}")

        # 5) 持久化 assistant response（即使触发了 tool_calls，
        #    仍把 LLM 原始的 assistant message 落库）
        # Gap E — capture the persisted assistant message id for source_message_id.
        assistant_message_id = await self.storage.append_message(session_id, response)
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
        # Gate via auto_memory flag (caches 30s, default True). Lifecycle wrapper
        # exposes is_auto_memory_enabled(); legacy MemoryManager does not, so
        # hasattr() lets tests/older call sites pass through unchanged.
        if self.memory:
            if self._lifecycle is not None:
                # Task 6 — production end-of-turn path: the lifecycle hook does
                # extraction + persist + emits one memory_written per fact (gate
                # handled internally via is_auto_memory_enabled). source_message_id
                # threads the persisted assistant/user message id so click-to-trace
                # highlights the exact producing message.
                try:
                    await self._lifecycle.on_turn_complete(
                        session_id,
                        [user_message, response],
                        source_message_id=assistant_message_id or user_message_id,
                    )
                except Exception as e:  # noqa: BLE001 — never break the turn
                    logger.warning(f"on_turn_complete failed: {e}")
                    span.set_attribute("memory.store_error", str(e))
                try:
                    await self.memory.compress(session_id)
                except Exception as e:  # noqa: BLE001 — never break the turn
                    logger.warning(f"Failed to compress working memory: {e}")
                    span.set_attribute("memory.compress_error", str(e))
            elif hasattr(self.memory, "is_auto_memory_enabled"):
                try:
                    auto_enabled = await self.memory.is_auto_memory_enabled()
                except Exception as e:  # noqa: BLE001 — fail-open
                    logger.warning(f"auto_memory gate read failed, defaulting True: {e}")
                    auto_enabled = True
                if not auto_enabled:
                    logger.debug("auto_memory disabled, skipping extraction")
                else:
                    try:
                        await self._extract_and_store_memory(
                            session_id=session_id,
                            user_message=user_message,
                            assistant_message=response,
                            user_message_id=user_message_id,
                            assistant_message_id=assistant_message_id,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to store memory: {e}")
                        span.set_attribute("memory.store_error", str(e))
                    try:
                        await self.memory.compress(session_id)
                    except Exception as e:
                        logger.warning(f"Failed to compress working memory: {e}")
                        span.set_attribute("memory.compress_error", str(e))
            else:
                # Legacy path: MemoryManager doesn't have lifecycle wrapper yet
                try:
                    await self._extract_and_store_memory(
                        session_id=session_id,
                        user_message=user_message,
                        assistant_message=response,
                        user_message_id=user_message_id,
                        assistant_message_id=assistant_message_id,
                    )
                except Exception as e:
                    logger.warning(f"Failed to store memory: {e}")
                    span.set_attribute("memory.store_error", str(e))

            # 8) 压缩工作记忆 (Memory Integration) — 仅 win7 legacy path 兜底调用 compress：
            # hex path (lifecycle 不为 None) 已在 if 分支内部调；
            # gate path (memory.is_auto_memory_enabled) 已在 elif 分支内部调。
            if self.memory is not None and self._lifecycle is None and not hasattr(self.memory, "is_auto_memory_enabled"):
                try:
                    await self.memory.compress(session_id)
                except Exception as e:
                    logger.warning(f"Failed to compress working memory: {e}")
                    span.set_attribute("memory.compress_error", str(e))

            # 9) 标题自动生成：首轮对话后 (message_count <= 2)
            try:
                session_data = await self.storage.get_session(session_id)
                if session_data and session_data.get("message_count", 0) <= 2:
                    from backend.chat.title_generator import TitleGenerator

                    title = await TitleGenerator(self.llm).generate(
                        user_message.content or "", response.content or ""
                    )
                    if title:
                        await self.storage.update_session(session_id, title=title)
            except Exception as e:
                logger.warning(f"标题生成失败: {e}")

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
        user_message_id: Optional[str] = None,
        assistant_message_id: Optional[str] = None,
    ) -> None:
        """从对话中提取关键信息并存入记忆系统

        使用 LLM 驱动的事实提取（MemoryExtractor），自动检测对话中的
        关键信息并存储到记忆系统。当 LLM 不可用时降级为关键词提取。

        Args:
            session_id: 会话 ID
            user_message: 用户消息
            assistant_message: 助手消息
            user_message_id: 已持久化的用户消息 id（Gap E，可追溯性）
            assistant_message_id: 已持久化的助手消息 id（Gap E，可追溯性）
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
                # F4 — persist the extracted category + the producing turn so
                # the traceability columns get populated on the production
                # path (adapter.store → memorize → episodic.save).
                memory_category=fact.get("category", "project_fact"),
                source_turn_id=getattr(self, "_current_turn_id", None),
                # Gap E — point at the ACTUAL stored message so the Memory
                # page's click-to-trace (highlight_turn) can match Chat's
                # data-turn-id={message.id} instead of being a silent no-op.
                # Prefer the assistant reply; fall back to the user message.
                source_message_id=assistant_message_id or user_message_id,
            )

        if facts:
            logger.debug(f"Extracted {len(facts)} facts for session {session_id}")

    # ------------------------------------------------------------------ #
    # A4 Suspend-Resume：会话挂起 + 唤醒注册
    # ------------------------------------------------------------------ #

    async def sleep_for(
        self,
        session_id: str,
        seconds: float,
        *,
        note: str = "",
    ) -> Optional[Wake]:
        """挂起会话，``seconds`` 秒后由 WakeScheduler 唤醒。

        agent 在长轮询 / 等待外部副作用时调用：注册 TIMER wake 后让出
        执行权（配合 ``StreamRegistry.suspend``），空闲期间零上下文占用。

        Raises:
            ValueError: ``seconds`` 为负。
        """
        if seconds < 0:
            raise ValueError(f"seconds must be >= 0, got {seconds}")
        fire_at = to_utc_iso(
            datetime.now(timezone.utc) + timedelta(seconds=float(seconds))  # noqa: UP017
        )
        return await self._register_wake(
            Wake.create(session_id, WakeKind.TIMER, fire_at=fire_at, note=note)
        )

    async def sleep_until(
        self,
        session_id: str,
        when: Union[datetime, str],
        *,
        note: str = "",
    ) -> Optional[Wake]:
        """挂起会话，直到 ISO-8601 时间戳 ``when``（naive 时间按 UTC 解释）。

        过去的时间戳合法：wake 将在下一轮 scheduler tick 立即被消费。

        Raises:
            ValueError: 字符串无法解析为 ISO-8601。
            TypeError:  ``when`` 既不是 datetime 也不是 str。
        """
        if isinstance(when, str):
            try:
                when = datetime.fromisoformat(when)
            except ValueError:
                raise ValueError(f"invalid ISO-8601 timestamp: {when!r}")
        if not isinstance(when, datetime):
            raise TypeError(f"when must be datetime or ISO-8601 str, got {type(when)!r}")
        return await self._register_wake(
            Wake.create(session_id, WakeKind.TIMER, fire_at=to_utc_iso(when), note=note)
        )

    async def wake_on(
        self,
        session_id: str,
        job_id: str,
        *,
        note: str = "",
    ) -> Optional[Wake]:
        """挂起会话，直到后台任务 ``job_id`` 完成。

        任务退出路径调 ``WakeStore.complete_job(job_id)`` 把该 wake 标记
        为 DUE，下一轮 tick 恢复会话。

        Raises:
            ValueError: ``job_id`` 为空。
        """
        if not job_id or not str(job_id).strip():
            raise ValueError("job_id must be a non-empty string")
        return await self._register_wake(
            Wake.create(session_id, WakeKind.COMPLETION, job_id=str(job_id), note=note)
        )

    async def _register_wake(self, wake: Wake) -> Optional[Wake]:
        """落库 wake + 审计事件 + 计数。未装配 wake_store 时降级为 no-op。"""
        if self.wake_store is None:
            logger.warning(
                "wake_store 未装配，跳过唤醒注册（session=%s kind=%s）",
                wake.session_id,
                wake.kind.value,
            )
            return None
        self.wake_store.add_wake(wake)
        self.events.emit(
            "session_suspended",
            {
                "session_id": wake.session_id,
                "wake_id": wake.id,
                "kind": wake.kind.value,
            },
        )
        self.metrics.counter(_WAKES_CREATED_METRIC, {"kind": wake.kind.value})
        return wake

    # ------------------------------------------------------------------ #
    # 内部辅助：执行 tool_calls
    # ------------------------------------------------------------------ #

    async def _execute_tool_calls(
        self,
        session_id: str,
        tool_calls: List[ToolCall],
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
            # M3: 权限门禁——用 LanePermission.check 决定是否放行；
            # 被拒时不调底层 tools.execute，直接返回 permission_denied。
            target = _extract_action_target(tc.args)
            action = AgentAction(action_type=tc.name, target=target, parameters=dict(tc.args))
            decision = "allowed" if self._permission.check(action) else "denied"
            if decision == "denied":
                run.emit(
                    "tool_result",
                    session_id=session_id,
                    tool=tc.name,
                    success=False,
                    error="permission_denied: action not permitted by "
                    f"{self._permission.preset.value} preset",
                    permission_decision="denied",
                    resolved_path=target,
                )
                self.metrics.counter(
                    _TOOL_INVOCATIONS_METRIC,
                    {"tool": tc.name, "outcome": "denied"},
                )
                called += 1
                continue
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
                permission_decision="allowed",
                resolved_path=target,
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


# --------------------------------------------------------------------------- #
# A16: Skill Auto-Activation（when_to_use 自动匹配注入）
# --------------------------------------------------------------------------- #


def _skill_activation_block(message: str, skills: Optional[SkillPort]) -> str:
    """计算本轮用户消息自动激活的技能上下文块（含前导换行，可直接追加）。

    结构性探测：仅当 skills adapter 实现 ``auto_activate(message)`` 扩展
    方法（``InprocSkillAdapter``）时生效；纯 ``SkillPort`` mock / 其他
    实现无此属性 → 返回空串。adapter 返回对象的 ``context_block`` 属性
    非字符串（含 mock 返回值）同样视为无激活。

    任何失败（adapter 抛错 / 返回类型异常）都降级为空串 —— 注入失败
    绝不能破坏对话轮次（与记忆上下文注入同语义）。
    """
    if not message or skills is None:
        return ""
    auto_activate = getattr(skills, "auto_activate", None)
    if not callable(auto_activate):
        return ""
    try:
        result = auto_activate(message)
        block = getattr(result, "context_block", "")
    except Exception as exc:
        logger.debug(f"A16 skill auto-activation skipped: {exc}")
        return ""
    return f"\n\n{block}" if isinstance(block, str) and block else ""


# --------------------------------------------------------------------------- #
# WS-C P0-2: 统一记忆写入路径（模块级，hex ChatService 与 legacy /chat/stream 共用）
# --------------------------------------------------------------------------- #


async def extract_and_store_memory(
    memory_port: Optional[MemoryPort],
    extractor: Any,
    user_text: str,
    assistant_text: str,
    session_id: Optional[str],
    enabled: bool,
) -> int:
    """从一轮对话中提取原子事实并写入记忆系统（best-effort，绝不外抛）。

    WS-C P0-2：此前只有 hex ``ChatService.run_turn`` 触发 MemoryExtractor，
    legacy /chat/stream producer 不写记忆，导致一半对话数据不进记忆系统。
    本函数把提取 + 写入的核心逻辑抽成两条路径共用的唯一实现（legacy_routes
    在 assistant 消息落盘成功后调用，见 ``_extract_legacy_chat_memory``）。

    语义保证：
    - ``enabled=False``（autoMemory 关）或 ``memory_port is None`` → 立即返回 0；
    - extractor / store 的任何异常都在内部捕获并 ``logger.warning``，
      绝不外抛——记忆写入失败不得破坏对话轮次或流式响应。

    Args:
        memory_port:    MemoryPort 实现（如 MemoryAdapter）；None → 跳过。
        extractor:      MemoryExtractor 实例（持有各自的 LLM 客户端）。
        user_text:      用户消息文本。
        assistant_text: 助手回复文本。
        session_id:     关联会话 ID，原样透传给 ``memory_port.store``；可为 None。
        enabled:        autoMemory 开关；False → 跳过（返回 0）。

    Returns:
        实际写入记忆条数（失败 / 跳过时为 0）。
    """
    if not enabled or memory_port is None:
        return 0
    stored = 0
    try:
        facts = await extractor.extract(
            user_message=user_text or "",
            assistant_message=assistant_text or "",
        )
        # 用户画像类事实类别（extractor 产出）→ 路由到 store_profile
        profile_categories = ("preference", "goal")
        # 结构性探测 store_profile（MemoryPort 协议外的扩展方法）:
        # 用**类级** hasattr（而非实例 getattr）—— 无 spec 的 Mock 在实例上
        # 会自动创建任意属性, 类级探测可避免误判为"已实现"（review MEDIUM）。
        store_profile = (
            getattr(memory_port, "store_profile", None)
            if hasattr(type(memory_port), "store_profile")
            else None
        )
        for fact in facts:
            category = fact.get("category", "fact")
            if category in profile_categories and callable(store_profile):
                pid = await store_profile(
                    content=fact["content"],
                    category=category,
                    importance=fact.get("importance", 5),
                    session_id=session_id,
                )
                if pid:
                    stored += 1
            else:
                await memory_port.store(
                    content=fact["content"],
                    session_id=session_id,
                    importance=fact.get("importance", 5),
                    tags=fact.get("tags", ["conversation"]),
                )
                stored += 1
        if stored:
            logger.debug(f"Extracted {stored} facts for session {session_id}")
    except Exception as e:
        logger.warning(f"Failed to extract/store memory: {e}")
    return stored


# --------------------------------------------------------------------------- #
# WS-C P0-3: frozen snapshot 失效广播（legacy_routes 压缩落点调用）
# --------------------------------------------------------------------------- #

# 存活 ChatService 实例的弱引用登记表：压缩只在 legacy_routes 发生,
# ChatService 自身无感知; legacy_routes 压缩落盘后调模块级
# invalidate_session_snapshot() 广播失效, 各实例下一轮 run_turn 重建快照。
_CHAT_SERVICE_REGISTRY: weakref.WeakSet[ChatService] = weakref.WeakSet()


def invalidate_session_snapshot(session_id: str) -> None:
    """广播失效：通知所有存活 ChatService 实例丢弃指定 session 的 prompt 快照。

    模块级入口，供 legacy_routes 的压缩落盘路径（``_persist_compaction``，
    自动 / 手动压缩的唯一落点）调用。未知 session 或无存活实例时是 no-op，
    任何实例侧异常不影响其他实例。
    """
    for service in list(_CHAT_SERVICE_REGISTRY):
        try:
            service.invalidate_session_snapshot(session_id)
        except Exception as e:  # 防御性：单实例失效失败不阻断其余实例
            logger.warning(f"Failed to invalidate snapshot for session {session_id}: {e}")

def _extract_action_target(args: dict) -> str:
    """从工具参数中提取 ``LanePermission`` 关心的 target。

    read/write/delete_file → ``path``；execute/shell → ``command``；其他 → 第一个 str 值。
    """
    if not args:
        return ""
    for key in ("path", "command", "cmd", "url"):
        val = args.get(key)
        if isinstance(val, str):
            return val
    # 退而求其次：第一个字符串值
    for v in args.values():
        if isinstance(v, str):
            return v
    return ""

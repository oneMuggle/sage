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

from backend.domain.errors import LLMError
from backend.domain.message import Message, Role, ToolCall
from backend.ports.llm import LLMPort
from backend.ports.observability import EventPort, MetricPort
from backend.ports.skill import SkillPort
from backend.ports.storage import StoragePort
from backend.ports.tool import ToolPort

# 默认拉取的历史消息窗口大小（最新 N 条）
_DEFAULT_HISTORY_LIMIT = 20

# 默认 LLM 调用计数 label
_DEFAULT_MODEL_LABEL = "default"


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
    ) -> None:
        self.llm = llm
        self.tools = tools
        self.skills = skills
        self.storage = storage
        self.metrics = metrics
        self.events = events

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
        # 1) 持久化 user message
        await self.storage.append_message(session_id, user_message)
        self.events.emit(
            "chat_message_sent",
            {"session_id": session_id, "role": Role.USER.value},
        )
        self.metrics.counter(
            "chat_messages_total",
            {"role": Role.USER.value},
        )

        # 2) 拉取历史上下文（用于喂给 LLM）
        history = await self.storage.get_messages(
            session_id,
            limit=_DEFAULT_HISTORY_LIMIT,
        )

        # 3) 调 LLM（单次调用；错误时记 metric + event 后透传）
        self.metrics.counter(
            "llm_calls_total",
            {"model": _DEFAULT_MODEL_LABEL},
        )
        try:
            response = await self.llm.chat(history)
        except LLMError as exc:
            self.events.emit(
                "llm_error",
                {"session_id": session_id, "type": exc.type.value},
            )
            self.metrics.counter(
                "errors_total",
                {"layer": "llm", "type": exc.type.value},
            )
            raise

        # 4) 执行模型发起的 tool_calls（PG2.9：单轮执行；不触发二次 LLM）
        if response.tool_calls:
            await self._execute_tool_calls(session_id, response.tool_calls)

        # 5) 持久化 assistant response（即使触发了 tool_calls，
        #    仍把 LLM 原始的 assistant message 落库）
        await self.storage.append_message(session_id, response)
        self.events.emit(
            "chat_response_completed",
            {"session_id": session_id},
        )

        return [user_message, response]

    # ------------------------------------------------------------------ #
    # 内部辅助：执行 tool_calls
    # ------------------------------------------------------------------ #

    async def _execute_tool_calls(
        self,
        session_id: str,
        tool_calls: list[ToolCall],
    ) -> None:
        """执行模型返回的 tool_calls，依次 emit 事件 / 计数 / 持久化。

        PG2.9 简化：每个 tool_call 都立即执行（不并发）、执行结果
        作为 ``role=TOOL`` 消息追加到会话历史，但不重新调 LLM。
        这样 P3+ 在此基础上扩展 ReAct 多轮循环时，行为是"在末尾
        加一层循环"，向后兼容。
        """
        for tc in tool_calls:
            self.events.emit(
                "tool_invoked",
                {"session_id": session_id, "tool": tc.name, "args": tc.args},
            )
            self.metrics.counter(
                "tool_invocations_total",
                {"tool": tc.name},
            )
            result = await self.tools.execute(tc.name, tc.args)
            # 把工具结果作为 TOOL 消息回写会话历史
            tool_message = Message(
                role=Role.TOOL,
                content=result.output if result.success else (result.error or ""),
                tool_call_id=tc.id,
            )
            await self.storage.append_message(session_id, tool_message)
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
                    "tool_errors_total",
                    {"tool": tc.name},
                )

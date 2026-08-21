"""
In-loop Agent tool — spawn focused read-only sub-agents.

Adapts claw-code's ``execute_agent`` pattern to Sage: the primary agent can
delegate a focused investigation to a sub-agent via the ``agent`` tool. The
sub-agent runs a full ReAct loop (``SageAgent.run_loop``) on a worker thread
(the tool call is synchronous from the loop's perspective) and its run is
mirrored onto the LaneBoard as a Lane (``metadata.source = "subagent"``)
with lifecycle events recorded through ``EventRecorder``.

Security model (defense in depth):
- The sub-agent's tool registry is a hard READ-ONLY whitelist:
  ``read_file, list_dir, web_search, web_fetch, memory_search, calculator``.
  No terminal / write / edit / repl / office — ever. The whitelist is
  enforced structurally (the tools simply are not registered), and the
  sub-agent's own ToolPolicy enforcer still applies on top.
- Capability classification: ``backend/tools/permissions.py`` (the
  ``TOOL_CAPABILITIES`` table) does not exist on main — it arrives with the
  M1 branch. When M1 merges, classify ``agent`` as READ-equivalent (the
  sub-agent whitelist is read-only).

Timeouts and residual risk:
- ``execute`` bounds its wait on the sub-run with ``SUBAGENT_TIMEOUT_S``
  (default 300s; env ``SAGE_AGENT_TOOL_TIMEOUT`` overrides). On timeout the
  tool returns a failure ToolResult and the lane is marked FAILED; the
  primary ReAct loop continues.
- The sub-run executes on a worker thread that CANNOT be killed once
  started: after a timeout the abandoned worker runs on until its own
  iteration cap (``OrchSettings.max_subagent_iterations``, default 6 —
  falls back to ``SUBAGENT_MAX_ITERATIONS``) and then drains in the
  background.
  Mitigation: the sub-agent's ``LLMClient`` enforces a per-request httpx
  timeout (``LLMConfig.timeout``, default 60s — see
  ``backend/core/legacy/llm_client.py``), so a hung LLM call cannot wedge a
  single iteration indefinitely; worst case the leaked thread consumes up to
  6 × 60s of LLM time plus read-only tool time, then exits. If a caller
  injects a custom LLM client that lacks per-request timeouts, that client's
  behavior is the remaining exposure. No additional global kill mechanism is
  provided by design.
- Event-loop: ``SageAgent.run_loop`` dispatches this tool through
  ``loop.run_in_executor`` (see ``backend/core/legacy/agent.py``), so the
  blocking ``future.result()`` wait happens on a pool thread and never
  stalls the asyncio loop (health endpoint, board polling, other sessions).
  ``AgentTool.execute`` does not read the ``ToolExecutionContext``
  ContextVar — it builds all of its state itself — so the context copy
  semantics of ``run_in_executor`` are irrelevant for this tool.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import tempfile
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Optional, Tuple

from backend.domain.tool_policy import ToolPolicy
from backend.orchestration.events import EventProvenance, EventRecorder, LaneEvent
from backend.orchestration.lane_registry import LaneRegistry
from backend.orchestration.llm_factory import build_llm_client_from_settings
from backend.orchestration.models import Task
from backend.orchestration.orch_settings import load_orch_settings
from backend.orchestration.task_registry import TaskRegistry
from backend.tools.base import BaseTool, ToolResult, ToolSchema
from backend.tools.calculator import CalculatorTool
from backend.tools.file_tool import ListDirTool, ReadFileTool
from backend.tools.memory_tool import MemorySearchTool
from backend.tools.registry import ToolRegistry
from backend.tools.web_tool import WebFetchTool, WebSearchTool

logger = logging.getLogger(__name__)

# Hard read-only whitelist for sub-agents. glob/grep/todo arrive with the M2
# branch — do not reference them here.
SUBAGENT_TOOL_WHITELIST: Tuple[str, ...] = (
    "read_file",
    "list_dir",
    "web_search",
    "web_fetch",
    "memory_search",
    "calculator",
)

# Sub-agents are focused: small iteration budget, capped answers.
# ``SUBAGENT_MAX_ITERATIONS`` is the fallback when orch settings are
# unreadable; the effective budget comes from
# ``OrchSettings.max_subagent_iterations`` (same default).
SUBAGENT_MAX_ITERATIONS = 6
SUBAGENT_ANSWER_CAP = 20_000


def _resolve_subagent_iterations() -> int:
    """Effective sub-agent iteration budget (settings → constant fallback).

    Settings live in user-controlled JSON, so a malformed value or a broken
    settings backend must never break delegation: any failure — and any
    non-positive value — falls back to ``SUBAGENT_MAX_ITERATIONS``.
    """
    try:
        value = load_orch_settings().max_subagent_iterations
    except Exception:  # noqa: BLE001 — 配置读失败回落常量，绝不抛穿
        logger.warning(
            "load_orch_settings failed; falling back to SUBAGENT_MAX_ITERATIONS=%d",
            SUBAGENT_MAX_ITERATIONS,
            exc_info=True,
        )
        return SUBAGENT_MAX_ITERATIONS
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        return SUBAGENT_MAX_ITERATIONS
    return value


def _resolve_timeout() -> float:
    """Resolve the sub-run wait bound (env ``SAGE_AGENT_TOOL_TIMEOUT``)."""
    raw = os.environ.get("SAGE_AGENT_TOOL_TIMEOUT")
    if raw:
        try:
            value = float(raw)
            if value > 0:
                return value
        except ValueError:
            pass
        logger.warning(
            "Invalid SAGE_AGENT_TOOL_TIMEOUT=%r; falling back to 300s", raw
        )
    return 300.0


# Max time execute() waits on the sub-run before failing the tool call.
# Residual risk (worker thread cannot be killed) documented in the module
# docstring. Overridable via env for tests/ops.
SUBAGENT_TIMEOUT_S: float = _resolve_timeout()

SUBAGENT_SYSTEM_PROMPT = (
    "You are a focused Sage sub-agent performing a delegated task. "
    "You have READ-ONLY tools: file reading, directory listing, web search/fetch, "
    "memory search, and a calculator. You cannot modify files or run commands. "
    "File tools can only read the delegated scratch/workspace content; web fetch "
    "rejects private or local destinations. Complete the task concisely and "
    "return your final answer as plain text."
)


def _subagent_policy(policy: Optional[ToolPolicy]) -> ToolPolicy:
    parent = policy or ToolPolicy()
    root = parent.workspace_root or os.path.join(tempfile.gettempdir(), "sage-subagent-scratch")
    os.makedirs(root, exist_ok=True)
    return ToolPolicy(
        timeout_seconds=parent.timeout_seconds,
        max_output_bytes=parent.max_output_bytes,
        max_result_items=parent.max_result_items,
        max_read_bytes=parent.max_read_bytes,
        max_tool_calls_per_run=parent.max_tool_calls_per_run,
        workspace_root=root,
        subagent_only=True,
    )


def build_readonly_tool_registry(policy: Optional[ToolPolicy] = None) -> ToolRegistry:
    """Build the restricted read-only registry given to sub-agents."""
    policy = _subagent_policy(policy)
    registry = ToolRegistry()
    registry.register(ReadFileTool(policy=policy, enforce_workspace=True))
    registry.register(ListDirTool(policy=policy, enforce_workspace=True))
    registry.register(WebSearchTool(policy=policy))
    registry.register(WebFetchTool(policy=policy))
    registry.register(MemorySearchTool(policy=policy))
    registry.register(CalculatorTool(policy=policy))
    return registry


class AgentTool(BaseTool):
    """
    ``agent`` tool: spawn a focused read-only sub-agent.

    Params:
        description: Short label for the delegation (used on the LaneBoard).
        prompt: The task instruction for the sub-agent.
        subagent_type: Reserved, currently ignored.
    """

    def __init__(
        self,
        policy: Optional[ToolPolicy] = None,
        llm_client: Any = None,
        subagent_factory: Any = None,
    ) -> None:
        """
        Args:
            policy: ToolPolicy forwarded to the sub-agent's whitelisted tools.
            llm_client: Injectable LLM client for the sub-agent (tests). When
                None, a client is built from the user's endpoint settings at
                execute time; with no settings the tool fails cleanly.
            subagent_factory: Injectable callable ``(tool_registry) -> agent``
                exposing ``async run_loop(messages, max_iterations)`` yielding
                AgentEvents (tests). Defaults to a restricted ``SageAgent``.
        """
        super().__init__(policy=policy)
        self._injected_llm_client = llm_client
        self._subagent_factory = subagent_factory

    def _build_schema(self) -> ToolSchema:
        return ToolSchema(
            name="agent",
            description=(
                "Launch a focused sub-agent to handle a delegated task. The sub-agent "
                "has read-only tools (file/directory reading, web search/fetch, memory "
                "search, calculator) and returns a final answer. Use it to parallelize "
                "investigation work without polluting the main context."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "A short (3-5 word) label for the delegated task",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "The full task instruction for the sub-agent",
                    },
                    "subagent_type": {
                        "type": "string",
                        "description": "Reserved for future specialized sub-agents (ignored)",
                    },
                },
                "required": ["description", "prompt"],
            },
        )

    def execute(
        self,
        description: str = "",
        prompt: str = "",
        subagent_type: Optional[str] = None,  # reserved for future specialization
        **kwargs: Any,  # forward-compat: tolerate extra LLM-provided params
    ) -> ToolResult:
        """Run the sub-agent synchronously (worker thread) and mirror to a lane."""
        description = (description or "").strip()
        prompt = (prompt or "").strip()
        if not description or not prompt:
            return ToolResult(
                success=False,
                error="agent tool requires non-empty 'description' and 'prompt'",
            )

        llm_client = self._injected_llm_client
        if llm_client is None:
            llm_client = build_llm_client_from_settings()
        if llm_client is None:
            return ToolResult(
                success=False,
                error="no_llm_configured: sub-agent requires a configured LLM endpoint",
            )

        # Create the lane up-front so the board shows the live sub-agent run.
        task_registry = TaskRegistry()
        lane_registry = LaneRegistry()
        event_recorder = EventRecorder()

        task = Task(
            task_id=f"task-{uuid.uuid4().hex[:12]}",
            name=f"subagent: {description[:80]}",
            description=prompt[:500],
            task_type="research",
            parameters={"source": "subagent"},
        )
        task_registry.create_task(task)
        lane = lane_registry.create_lane(
            task.task_id,
            metadata={"source": "subagent", "description": description[:200]},
        )
        lane_registry.bind_agent(lane.lane_id, "subagent")
        event_recorder.record(
            LaneEvent.STARTED,
            lane_id=lane.lane_id,
            task_id=task.task_id,
            agent_id="subagent",
            provenance=EventProvenance.LIVE_LANE,
            metadata={"source": "subagent"},
        )
        # CREATED -> READY -> RUNNING so the board shows the live run.
        lane_registry.mark_ready(lane.lane_id)
        lane_registry.mark_running(lane.lane_id)

        try:
            answer, error = self._run_subagent_sync(llm_client, description, prompt)
        except concurrent.futures.TimeoutError:
            # Wait bound exceeded — the worker thread is abandoned (it drains
            # in the background; see module docstring residual-risk note). The
            # lane fails with a "timeout" reason and the primary loop goes on.
            logger.warning(
                "Sub-agent timed out after %.1fs (lane will be FAILED)",
                SUBAGENT_TIMEOUT_S,
            )
            error = (
                f"timeout: 子代理执行超时（{SUBAGENT_TIMEOUT_S:g} 秒），"
                "已放弃等待，后台线程将自行结束"
            )
            answer = ""
        except Exception as exc:  # sub-agent crashed — lane fails, loop continues
            logger.exception("Sub-agent execution crashed: %s", exc)
            error = str(exc)
            answer = ""

        if error is not None:
            lane_registry.mark_failed(lane.lane_id, error=error)
            event_recorder.record(
                LaneEvent.FAILED,
                lane_id=lane.lane_id,
                task_id=task.task_id,
                agent_id="subagent",
                provenance=EventProvenance.LIVE_LANE,
                metadata={"error": error[:500]},
            )
            task_registry.mark_failed(task.task_id, error=error)
            return ToolResult(
                success=False,
                error=f"subagent_failed: {error}",
                content={"lane_id": lane.lane_id},
            )

        lane_registry.mark_succeeded(lane.lane_id)
        event_recorder.record(
            LaneEvent.SUCCEEDED,
            lane_id=lane.lane_id,
            task_id=task.task_id,
            agent_id="subagent",
            provenance=EventProvenance.LIVE_LANE,
            metadata={"answer_chars": len(answer)},
        )
        task_registry.mark_completed(task.task_id, result={"answer_chars": len(answer)})

        truncated = len(answer) > SUBAGENT_ANSWER_CAP
        return ToolResult(
            success=True,
            content={
                "answer": answer[:SUBAGENT_ANSWER_CAP],
                "lane_id": lane.lane_id,
                "truncated": truncated,
            },
        )

    # ------------------------------------------------------------------
    # Sub-agent execution
    # ------------------------------------------------------------------

    def _run_subagent_sync(
        self,
        llm_client: Any,
        description: str,
        prompt: str,
    ) -> Tuple[str, Optional[str]]:
        """Run the async sub-agent loop on a worker thread (sync façade).

        Raises:
            concurrent.futures.TimeoutError: when the sub-run exceeds
                ``SUBAGENT_TIMEOUT_S``. The worker is abandoned (cannot be
                killed) and drains in the background.
        """
        # Deliberately NOT a context manager: ``__exit__`` calls
        # ``shutdown(wait=True)``, which on timeout would block the caller
        # until the hung worker finishes — defeating SUBAGENT_TIMEOUT_S.
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sage-subagent")
        try:
            future = pool.submit(
                asyncio.run,
                self._run_subagent_async(llm_client, description, prompt),
            )
            return future.result(timeout=SUBAGENT_TIMEOUT_S)
        finally:
            # wait=False: an abandoned worker keeps running on its own thread
            # and exits once the sub-loop hits its iteration cap.
            pool.shutdown(wait=False)

    async def _run_subagent_async(
        self,
        llm_client: Any,
        description: str,
        prompt: str,
    ) -> Tuple[str, Optional[str]]:
        """Drive ``run_loop`` to completion; return (answer, error)."""
        subagent = self._build_subagent()
        # Inject the LLM client post-construction so tests can pass mocks and
        # production reuses the settings-derived client without SageAgent
        # building its own.
        subagent.llm_client = llm_client

        messages = [
            {"role": "system", "content": SUBAGENT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Delegated task ({description}):\n\n{prompt}",
            },
        ]

        answer = ""
        error: Optional[str] = None
        saw_done = False
        async for event in subagent.run_loop(
            messages, max_iterations=_resolve_subagent_iterations()
        ):
            state = getattr(event, "state", None)
            state_value = getattr(state, "value", state)
            if state_value == "done":
                saw_done = True
                answer = event.content or ""
            elif state_value == "failed":
                error = event.error or "subagent_loop_failed"

        if error is not None:
            return "", error
        if not saw_done:
            return "", "subagent_exhausted_iterations"
        return answer, None

    def _build_subagent(self) -> Any:
        """Construct a SageAgent with the restricted read-only registry."""
        if self._subagent_factory is not None:
            return self._subagent_factory(build_readonly_tool_registry(self._policy))

        # Lazy import: backend.core.legacy.agent imports backend.tools — the
        # reverse direction — so importing at module load would cycle.
        from backend.core.legacy.agent import SageAgent

        # bare=True: skip the memory stack and register_all_tools (which
        # cold-starts MCP list_tools) — the full default registry built by a
        # plain SageAgent() would be discarded immediately below. The sub-run
        # only drives run_loop, which needs neither the memory stack nor the
        # default tools.
        subagent = SageAgent(bare=True)
        # Structural whitelist: install the read-only registry directly.
        subagent.tool_registry = build_readonly_tool_registry(self._policy)
        return subagent

"""
Lane Executor - manages Lane execution lifecycle.

Handles the complete execution flow for a Lane:
- Permission validation before execution
- State transitions (READY -> RUNNING -> SUCCEEDED/FAILED)
- Event recording at each transition
- Recovery policy application on failure
- Integration with existing agent/task execution
- TDD workflow loop (acceptance hard gate + task-level review)
"""
import asyncio
import contextlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.orchestration.acceptance import (
    record_acceptance_event,
    run_acceptance_checks,
)
from backend.orchestration.events import (
    EventProvenance,
    EventRecorder,
    LaneEvent,
    LaneEventPayload,
)
from backend.orchestration.models import (
    Lane,
    LaneStatus,
    Task,
)
from backend.orchestration.permission import (
    AgentAction,
    LanePermission,
    PermissionChecker,
    PermissionPreset,
)
from backend.orchestration.report_schema import (
    ProjectionRef,
    ReviewReport,
)
from backend.orchestration.run_event_adapter import (
    RunEventSink,
    lane_event_to_run_event,
)
from backend.orchestration.workflow_mode import resolve_workflow_mode

logger = logging.getLogger(__name__)


def _resolve_lane_workflow_mode(lane: Lane, task: Any) -> str:
    """解析 lane 的 workflow_mode：metadata > packet > parameters > env > 默认 "tdd"。"""
    explicit = lane.metadata.get("workflow_mode") if lane.metadata else None
    if explicit not in ("tdd", "fast"):
        packet = getattr(task, "packet", None)
        explicit = getattr(packet, "workflow_mode", None) if packet is not None else None
    if explicit not in ("tdd", "fast"):
        explicit = task.parameters.get("workflow_mode") if hasattr(task, "parameters") else None
    return resolve_workflow_mode(explicit=explicit)


class LaneExecutionError(Exception):
    """Raised when Lane execution fails."""

    def __init__(self, message: str, error_code: str = "EXECUTION_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


@dataclass
class TddLoopState:
    """Per-lane TDD 循环状态。

    独立于 ``RecoveryPolicy.max_retries``（lane 级 crash/timeout 重试）。
    ``max_rounds`` 默认 3：实现者最多被重新调用 3 次。
    """

    max_rounds: int = 3
    round: int = 0
    last_failure: str = ""


class LaneExecutor:
    """
    Manages the complete execution lifecycle of a Lane.

    The executor is the bridge between the orchestration layer's data model
    and the actual agent execution. It:
    1. Validates permissions before execution starts
    2. Transitions lane through READY -> RUNNING -> terminal states
    3. Records events at every state transition
    4. Applies recovery policies on failure
    """

    def __init__(
        self,
        lane_registry: Any,
        task_registry: Any,
        event_recorder: Optional[EventRecorder] = None,
        agent_runner: Optional[Callable] = None,
        interrupt_event: Optional[asyncio.Event] = None,
        run_event_sink: Optional[RunEventSink] = None,
        run_id: Optional[str] = None,
        acceptance_enabled: bool = True,
        task_reviewer: Optional[Callable] = None,
    ) -> None:
        """
        Initialize LaneExecutor.

        Args:
            lane_registry: LaneRegistry for lane persistence
            task_registry: TaskRegistry for task lookups
            event_recorder: EventRecorder for lifecycle events
            agent_runner: Optional async callable(task, agent_id) -> result
                for actual task execution. If None, uses default runner.
            acceptance_enabled: Run A4 acceptance checks after success.
                Advisory only — never flips the lane outcome.
            task_reviewer: Optional async callable for TDD task-level review.
                Signature: ``(goal, implementer_output, tdd_snapshot,
                acceptance_report) -> {"verdict": "pass"|"fail",
                "reason": str, "assertions": list}``. When None, TDD loop
                short-circuits to acceptance-only.
        """
        self.lane_registry = lane_registry
        self.task_registry = task_registry
        self.event_recorder = event_recorder or EventRecorder()
        self.agent_runner = agent_runner or self._default_agent_runner
        self.interrupt_event = interrupt_event
        self.run_event_sink = run_event_sink
        self.run_id = run_id
        self.acceptance_enabled = acceptance_enabled
        self.task_reviewer = task_reviewer

    async def execute_lane(  # noqa: PLR0911 — 7 returns: cancel/perm/fail/succeed/retry/abort/default
        self,
        lane: Lane,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Execute a Lane through its full lifecycle.

        Args:
            lane: The lane to execute
            agent_id: Optional agent ID (overrides lane.agent_id)

        Returns:
            Execution result dict with status, output, and metadata

        Raises:
            LaneExecutionError: If execution fails irrecoverably
        """
        if agent_id:
            lane.agent_id = agent_id

        if self._is_cancelled(lane):
            return self._cancelled_result(lane)

        # Step 1: Validate permissions before execution
        if not await self._validate_permissions(lane):
            return await self._fail_lane(
                lane,
                "Permission denied: agent cannot execute this lane",
                "PERMISSION_DENIED",
            )

        # Step 2: Transition CREATED -> READY
        if lane.status == LaneStatus.CREATED:
            self._record_event(
                lane,
                LaneEvent.READY,
                EventProvenance.LIVE_LANE,
                {"agent_id": lane.agent_id},
            )
            await self._publish_run_event(
                lane, LaneEvent.READY, EventProvenance.LIVE_LANE,
                {"agent_id": lane.agent_id},
            )
            lane.mark_ready()
            self.lane_registry.update_lane(lane)

        # Step 3: Transition READY -> RUNNING
        if lane.status == LaneStatus.READY:
            self._record_event(lane, LaneEvent.RUNNING, EventProvenance.LIVE_LANE)
            await self._publish_run_event(
                lane, LaneEvent.RUNNING, EventProvenance.LIVE_LANE
            )
            lane.mark_running()
            self.lane_registry.update_lane(lane)

        # Step 4: Look up the task
        task = self.task_registry.get_task(lane.task_id)
        if task is None:
            return await self._fail_lane(
                lane,
                f"Task {lane.task_id} not found",
                "TASK_NOT_FOUND",
            )

        # RT9 (round7): 重试带失败上下文 —— lane 重试分支记下的 retry_count /
        # last_error 写入 task.parameters["retry_hint"]，SubagentRunner 组装
        # prompt 时前置失败说明（盲重试 = 同一 prompt 跑三遍）。写经
        # task.parameters 而非改 agent_runner 调用签名 —— 测试桩零感知。
        if lane.metadata:
            _retry_count = lane.metadata.get("retry_count", 0)
            _last_error = lane.metadata.get("last_error")
            if _retry_count and _last_error:
                with contextlib.suppress(AttributeError):  # 测试桩的 parameters 可能不可写
                    task.parameters["retry_hint"] = {
                        "attempt": _retry_count,
                        "last_error": str(_last_error)[:2000],
                    }

        # Step 4.5 (TDD): 解析 workflow_mode，构造 TddGuard（跨轮共享）。
        workflow_mode = _resolve_lane_workflow_mode(lane, task)
        if workflow_mode == "tdd":
            from backend.orchestration.tdd_guard import TddGuard

            guard = TddGuard(mode="tdd")
            with contextlib.suppress(AttributeError):
                task.parameters["_tdd_guard"] = guard
        else:
            guard = None
        tdd_loop = TddLoopState(max_rounds=3)

        # Step 5 + Step 6.5 (TDD 循环): agent → acceptance → review → loop
        try:
            result: Optional[Dict[str, Any]] = None
            acceptance_summary: Optional[Dict[str, Any]] = None
            rounds_run = 0

            while tdd_loop.round < tdd_loop.max_rounds:
                result = await self.agent_runner(task, lane.agent_id)
                rounds_run += 1

                # Cancel check — 每轮开始时检查
                if self._is_cancelled(lane):
                    return self._cancelled_result(lane)

                # Step 6.5: acceptance checks（每轮都跑）
                acceptance_summary = None
                if self.acceptance_enabled:
                    with contextlib.suppress(Exception):
                        acceptance_summary = await self._run_acceptance(
                            lane, gate=(workflow_mode == "tdd")
                        )

                acceptance_passed = bool(
                    acceptance_summary and acceptance_summary.get("all_passed")
                )

                # fast 模式或 acceptance 通过 → 跳出循环
                if workflow_mode != "tdd" or acceptance_passed:
                    break

                # TDD 模式 + acceptance 未过 → task-level review
                if self.task_reviewer is None:
                    # 无 reviewer → 退化为仅记录 acceptance，跳出
                    break

                try:
                    review_result = await self.task_reviewer(
                        goal=task.parameters.get("goal", ""),
                        implementer_output=str(
                            (result or {}).get("output", "")
                        ),
                        tdd_snapshot=guard.snapshot() if guard is not None else {},
                        acceptance_report=acceptance_summary,
                    )
                except Exception:
                    logger.exception("task_reviewer 异常，跳过本轮 TDD 复核")
                    break

                if review_result.get("verdict") == "pass":
                    break

                # reviewer 判 fail → 准备下一轮
                tdd_loop.round += 1
                tdd_loop.last_failure = review_result.get(
                    "reason", "reviewer 判定不通过"
                )
                with contextlib.suppress(AttributeError):
                    task.parameters["retry_hint"] = {
                        "attempt": tdd_loop.round,
                        "last_error": tdd_loop.last_failure[:2000],
                    }
            else:
                # while 循环未 break（round >= max_rounds）→ 判定失败
                self._record_tdd_evidence(lane, guard, workflow_mode, rounds_run)
                return await self._fail_lane(
                    lane,
                    tdd_loop.last_failure or "TDD 循环已达上限",
                    "TDD_LOOP_EXHAUSTED",
                )

            # Step 6: 循环以 break 退出 → Mark succeeded
            if self._is_cancelled(lane):
                return self._cancelled_result(lane)
            self._record_tdd_evidence(lane, guard, workflow_mode, rounds_run)
            succeeded_metadata: Dict[str, Any] = {
                "result_keys": list(result.keys()) if isinstance(result, dict) else None,
            }
            if guard is not None:
                succeeded_metadata["tdd_loop_rounds"] = rounds_run
            self._record_event(
                lane,
                LaneEvent.SUCCEEDED,
                EventProvenance.LIVE_LANE,
                succeeded_metadata,
            )
            await self._publish_run_event(
                lane,
                LaneEvent.SUCCEEDED,
                EventProvenance.LIVE_LANE,
                succeeded_metadata,
            )
            lane.mark_succeeded()
            self.lane_registry.update_lane(lane)

            # Update task status
            self.task_registry.mark_completed(task.task_id, result=result)

            # Round 4 (2026-09-19, orch-acceptance-review-plan): 验收摘要随
            # lane 结果回传（dispatcher 收集后注入 reviewer 输入）。
            return {
                "status": "succeeded",
                "lane_id": lane.lane_id,
                "result": result,
                "acceptance": acceptance_summary,
            }

        except Exception as exc:
            logger.exception("Lane %s execution failed", lane.lane_id)
            if self._is_cancelled(lane):
                return self._cancelled_result(lane)
            # Preserve structured error_code from LaneExecutionError
            error_code = exc.error_code if isinstance(exc, LaneExecutionError) else None
            return await self._handle_failure(lane, task, str(exc), error_code=error_code)

    async def _run_acceptance(
        self, lane: Lane, *, gate: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Run A4 acceptance checks and record the result event.

        ``gate=True`` 时返回的摘要包含 ``"gate": True``，通知调用方（TDD
        循环）本轮 failure 是硬门而非仅记录；``gate=False``（默认）保持
        原 advisory 语义。
        """
        if not self.acceptance_enabled:
            return None
        if lane.agent_id == "reviewer":
            return None  # reviewer 自检无意义，跳过
        loop = asyncio.get_running_loop()
        report = await loop.run_in_executor(
            None,
            lambda: run_acceptance_checks(
                lane.worktree,
                configured=(lane.metadata or {}).get("acceptance_checks"),
                gate=gate,
            ),
        )
        record_acceptance_event(self.event_recorder, lane, report)
        return {
            "all_passed": report.all_passed,
            "checks": [c.to_dict() for c in report.checks],
            "gate": report.gate,
        }

    def _record_tdd_evidence(
        self,
        lane: Lane,
        guard: Any,
        workflow_mode: str,
        rounds: int,
    ) -> None:
        """落 ``lane.tdd.evidence`` 事件，供前端展示 red→green 证据链。

        fast 模式无 guard → snapshot 为空 dict，仍记录 mode，使前端可区分
        「未启用 TDD」与「TDD 但无证据」。落库失败不得破坏主流程。
        """
        try:
            snapshot = guard.snapshot() if guard is not None else {}
        except Exception:  # noqa: BLE001 — 证据快照绝不能炸主流程
            logger.warning("TDD 证据快照失败 lane=%s", lane.lane_id, exc_info=True)
            snapshot = {}
        self._record_event(
            lane,
            LaneEvent.TDD_EVIDENCE,
            EventProvenance.LIVE_LANE,
            {"mode": workflow_mode, "rounds": rounds, "snapshot": snapshot},
        )

    async def _validate_permissions(self, lane: Lane) -> bool:
        """
        Validate that the lane's agent has permission to execute.

        Args:
            lane: The lane to validate

        Returns:
            True if permitted, False otherwise
        """
        # Build permission profile from lane
        permission = self._build_permission(lane)
        checker = PermissionChecker(permission)

        # Check that the lane can be executed
        execute_action = AgentAction(
            action_type="execute_lane",
            target=lane.task_id,
            parameters={"lane_id": lane.lane_id, "agent_id": lane.agent_id},
        )

        try:
            checker.assert_permission(execute_action)
            return True
        except PermissionError as exc:
            logger.warning("Permission denied for lane %s: %s", lane.lane_id, exc)
            return False

    def _build_permission(self, lane: Lane) -> LanePermission:
        """
        Build LanePermission from lane's permission_preset.

        Args:
            lane: The lane

        Returns:
            LanePermission instance
        """
        try:
            preset = PermissionPreset(lane.permission_preset)
        except ValueError:
            preset = PermissionPreset.IMPLEMENT

        return LanePermission(preset=preset, allowed_paths=[], denied_tools=[])

    async def _handle_failure(
        self,
        lane: Lane,
        task: Task,
        error_message: str,
        error_code: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Handle lane execution failure using the task's recovery policy.

        Args:
            lane: The failed lane
            task: The task being executed
            error_message: Description of the failure
            error_code: Optional structured error code to preserve

        Returns:
            Failure result dict
        """
        if self._is_cancelled(lane):
            return self._cancelled_result(lane)
        recovery_policy = self._get_recovery_policy(task)
        action = recovery_policy.get("on_failure", "fail")

        logger.info(
            "Lane %s failed; recovery_policy.on_failure=%s, error=%s",
            lane.lane_id,
            action,
            error_message,
        )

        if action == "retry":
            retry_count = lane.metadata.get("retry_count", 0) if lane.metadata else 0
            max_retries = recovery_policy.get("max_retries", 2)

            if retry_count < max_retries:
                # Record retry event
                retry_metadata = {
                    "retry_count": retry_count + 1,
                    "max_retries": max_retries,
                    "error": error_message,
                }
                self._record_event(
                    lane,
                    LaneEvent.RUNNING,
                    EventProvenance.RETRY,
                    retry_metadata,
                )
                await self._publish_run_event(
                    lane,
                    LaneEvent.RUNNING,
                    EventProvenance.RETRY,
                    retry_metadata,
                )
                # Reset lane for retry
                lane.status = LaneStatus.READY
                lane.completed_at = None
                if lane.metadata is None:
                    lane.metadata = {}
                lane.metadata["retry_count"] = retry_count + 1
                lane.metadata["last_error"] = error_message
                self.lane_registry.update_lane(lane)
                return {
                    "status": "retrying",
                    "lane_id": lane.lane_id,
                    "retry_count": retry_count + 1,
                }

            # Max retries exhausted -> fail
            return await self._fail_lane(lane, error_message, "MAX_RETRIES_EXCEEDED")

        if action == "skip":
            return await self._fail_lane(lane, error_message, "SKIPPED")

        if action == "abort-siblings":
            return await self._fail_lane(lane, error_message, "ABORT_SIBLINGS")

        # Default: fail — preserve structured error_code if provided
        return await self._fail_lane(lane, error_message, error_code or "EXECUTION_ERROR")

    async def _fail_lane(
        self,
        lane: Lane,
        error_message: str,
        error_code: str,
    ) -> Dict[str, Any]:
        """
        Mark lane as failed and record event.

        Handles lanes in any non-terminal state by directly setting
        status (bypasses mark_failed's strict state machine check).

        Args:
            lane: The lane to fail
            error_message: Description of the failure
            error_code: Categorization of the error

        Returns:
            Failure result dict
        """
        if self._is_cancelled(lane):
            return self._cancelled_result(lane)
        failed_metadata = {"error": error_message, "error_code": error_code}
        self._record_event(
            lane,
            LaneEvent.FAILED,
            EventProvenance.LIVE_LANE,
            failed_metadata,
        )
        await self._publish_run_event(
            lane,
            LaneEvent.FAILED,
            EventProvenance.LIVE_LANE,
            failed_metadata,
        )
        # Direct state set — lane may be in CREATED/READY/BLOCKED
        # (e.g., permission denied before RUNNING)
        import time

        lane.status = LaneStatus.FAILED
        lane.error = error_message
        lane.completed_at = int(time.time() * 1000)
        self.lane_registry.update_lane(lane)

        # Update task status
        self.task_registry.mark_failed(lane.task_id, error=error_message)

        return {
            "status": "failed",
            "lane_id": lane.lane_id,
            "error": error_message,
            "error_code": error_code,
        }

    async def cancel_lane(
        self,
        lane: Lane,
        reason: str = "user_cancelled",
    ) -> Dict[str, Any]:
        """
        Cancel a running or queued lane.

        Args:
            lane: The lane to cancel
            reason: Reason for cancellation

        Returns:
            Cancellation result dict
        """
        if lane.status.is_terminal():
            return {
                "status": "noop",
                "lane_id": lane.lane_id,
                "reason": f"lane already in terminal state: {lane.status}",
            }

        stop_metadata = {"reason": reason}
        self._record_event(
            lane,
            LaneEvent.STOPPED,
            EventProvenance.MANUAL,
            stop_metadata,
        )
        await self._publish_run_event(
            lane,
            LaneEvent.STOPPED,
            EventProvenance.MANUAL,
            stop_metadata,
        )
        lane.mark_stopped()
        self.lane_registry.update_lane(lane)

        return {"status": "cancelled", "lane_id": lane.lane_id, "reason": reason}

    def _is_cancelled(self, lane: Lane) -> bool:
        current = self.lane_registry.get_lane(lane.lane_id)
        return bool(
            self.interrupt_event is not None and self.interrupt_event.is_set()
        ) or bool(current and current.status in (LaneStatus.STOPPED, LaneStatus.CANCELLED))

    def _cancelled_result(self, lane: Lane) -> Dict[str, Any]:
        """Return cancellation without allowing a late worker result to win."""
        if lane.status not in (LaneStatus.STOPPED, LaneStatus.CANCELLED):
            lane.status = LaneStatus.STOPPED
            self.lane_registry.update_lane(lane)
        return {"status": "cancelled", "lane_id": lane.lane_id}

    def _get_recovery_policy(self, task: Task) -> Dict[str, Any]:
        """
        Extract recovery policy from task packet.

        Args:
            task: The task

        Returns:
            Recovery policy dict with on_failure and max_retries
        """
        if task.packet is None:
            return {"on_failure": "fail", "max_retries": 0}

        return {
            "on_failure": task.packet.recovery_policy.on_failure,
            "max_retries": task.packet.recovery_policy.max_retries,
        }

    # ------------------------------------------------------------------
    # M2 — Review report submission
    # ------------------------------------------------------------------

    def submit_with_report(
        self,
        lane_id: str,
        task_id: str,
        assertions: list,
        reviewer_id: str = "system",
        verdict: Optional[str] = None,
    ) -> ReviewReport:
        """Build a `ReviewReport` v1 and emit a `lane.review.submitted` event.

        This is the M2 hook for the reviewer lane to record structured
        evidence before declaring a lane `lane.green`. The event payload's
        metadata carries the report's `canonical_id` and `content_hash` so
        downstream consumers can re-validate without re-reading the body.

        Args:
            lane_id: Lane being reviewed.
            task_id: Task being reviewed.
            assertions: List of `Assertion` (M1).
            reviewer_id: Identity of the reviewer (defaults to "system").
            verdict: Review verdict ("pass"/"fail"), recorded into the event.

        Returns:
            The constructed `ReviewReport` (already content-hashed and
            lineage-validated).
        """
        canonical_id = f"rep-{lane_id}-{reviewer_id}"

        # Construct with empty lineage first; __post_init__ computes hash;
        # then we pin the projection's source_hash to that canonical hash.
        report = ReviewReport(
            canonical_id=canonical_id,
            lane_id=lane_id,
            reviewer_id=reviewer_id,
            assertions=list(assertions),
            projection_lineage=[],
            redaction_provenance={},
        )
        report.projection_lineage.append(
            ProjectionRef(
                view="ops_full",
                source_hash=report.content_hash,
                downgrade_reason=None,
            )
        )

        # Emit the typed event for downstream consumers / audit.
        self.event_recorder.record(
            LaneEvent.REVIEW_SUBMITTED,
            lane_id=lane_id,
            task_id=task_id,
            agent_id=None,
            provenance=EventProvenance.LIVE_LANE,
            metadata={
                "canonical_id": report.canonical_id,
                "content_hash": report.content_hash,
                "reviewer_id": reviewer_id,
                "schema_version": report.schema_version,
                "assertion_count": len(report.assertions),
                "verdict": verdict,
            },
        )
        return report

    def _record_event(
        self,
        lane: Lane,
        event: LaneEvent,
        provenance: EventProvenance,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record a lane event with full context.

        Args:
            lane: The lane generating the event
            event: Event type
            provenance: Event source
            metadata: Additional event data
        """
        payload = LaneEventPayload(
            event=event,
            lane_id=lane.lane_id,
            task_id=lane.task_id,
            agent_id=lane.agent_id,
            provenance=provenance,
            metadata=metadata or {},
        )
        self.event_recorder.record_payload(payload)

    async def _publish_run_event(
        self,
        lane: Lane,
        event: LaneEvent,
        provenance: EventProvenance,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Translate a legacy lane event into a canonical RunEvent and publish it.

        No-op when no sink or run_id was provided, so existing callers that do
        not participate in the observability pipeline are unaffected.
        """
        if self.run_event_sink is None or not self.run_id:
            return
        try:
            await self.run_event_sink.publish(
                lane_event_to_run_event(
                    run_id=self.run_id,
                    lane=lane,
                    event=event,
                    provenance=provenance,
                    metadata=metadata,
                )
            )
        except Exception:  # pragma: no cover - observability must not break the lane
            logger.exception(
                "Failed to publish canonical RunEvent for lane %s (%s)",
                lane.lane_id,
                event,
            )

    async def _default_agent_runner(
        self,
        task: Task,
        agent_id: Optional[str],
    ) -> Dict[str, Any]:
        """
        Default agent runner. Override in production with real execution.

        Args:
            task: The task to execute
            agent_id: The agent that will execute

        Returns:
            Execution result dict

        Raises:
            LaneExecutionError: If no real runner is configured
        """
        raise LaneExecutionError(
            "No agent_runner configured. LaneExecutor requires an agent_runner "
            "callable or integration with the agent system.",
            error_code="NO_RUNNER",
        )

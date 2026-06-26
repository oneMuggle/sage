"""
Lane Executor - manages Lane execution lifecycle.

Handles the complete execution flow for a Lane:
- Permission validation before execution
- State transitions (READY -> RUNNING -> SUCCEEDED/FAILED)
- Event recording at each transition
- Recovery policy application on failure
- Integration with existing agent/task execution
"""

import logging
from collections.abc import Callable
from typing import Any

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

logger = logging.getLogger(__name__)


class LaneExecutionError(Exception):
    """Raised when Lane execution fails."""

    def __init__(self, message: str, error_code: str = "EXECUTION_ERROR") -> None:
        super().__init__(message)
        self.error_code = error_code


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
        event_recorder: EventRecorder | None = None,
        agent_runner: Callable | None = None,
    ) -> None:
        """
        Initialize LaneExecutor.

        Args:
            lane_registry: LaneRegistry for lane persistence
            task_registry: TaskRegistry for task lookups
            event_recorder: EventRecorder for lifecycle events
            agent_runner: Optional async callable(task, agent_id) -> result
                for actual task execution. If None, uses default runner.
        """
        self.lane_registry = lane_registry
        self.task_registry = task_registry
        self.event_recorder = event_recorder or EventRecorder()
        self.agent_runner = agent_runner or self._default_agent_runner

    async def execute_lane(
        self,
        lane: Lane,
        agent_id: str | None = None,
    ) -> dict[str, Any]:
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
            lane.mark_ready()
            self.lane_registry.update_lane(lane)

        # Step 3: Transition READY -> RUNNING
        if lane.status == LaneStatus.READY:
            self._record_event(lane, LaneEvent.RUNNING, EventProvenance.LIVE_LANE)
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

        # Step 5: Execute the task
        try:
            result = await self.agent_runner(task, lane.agent_id)

            # Step 6: Mark succeeded
            self._record_event(
                lane,
                LaneEvent.SUCCEEDED,
                EventProvenance.LIVE_LANE,
                {"result_keys": list(result.keys()) if isinstance(result, dict) else None},
            )
            lane.mark_succeeded()
            self.lane_registry.update_lane(lane)

            # Update task status
            self.task_registry.mark_completed(task.task_id, result=result)

            return {
                "status": "succeeded",
                "lane_id": lane.lane_id,
                "result": result,
            }

        except Exception as exc:
            logger.exception("Lane %s execution failed", lane.lane_id)
            # Preserve structured error_code from LaneExecutionError
            error_code = exc.error_code if isinstance(exc, LaneExecutionError) else None
            return await self._handle_failure(lane, task, str(exc), error_code=error_code)

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
        error_code: str | None = None,
    ) -> dict[str, Any]:
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
                self._record_event(
                    lane,
                    LaneEvent.RUNNING,
                    EventProvenance.RETRY,
                    {
                        "retry_count": retry_count + 1,
                        "max_retries": max_retries,
                        "error": error_message,
                    },
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
    ) -> dict[str, Any]:
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
        self._record_event(
            lane,
            LaneEvent.FAILED,
            EventProvenance.LIVE_LANE,
            {"error": error_message, "error_code": error_code},
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
    ) -> dict[str, Any]:
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

        self._record_event(
            lane,
            LaneEvent.STOPPED,
            EventProvenance.MANUAL,
            {"reason": reason},
        )
        lane.mark_stopped()
        self.lane_registry.update_lane(lane)

        return {"status": "cancelled", "lane_id": lane.lane_id, "reason": reason}

    def _get_recovery_policy(self, task: Task) -> dict[str, Any]:
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

    def _record_event(
        self,
        lane: Lane,
        event: LaneEvent,
        provenance: EventProvenance,
        metadata: dict[str, Any] | None = None,
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

    async def _default_agent_runner(
        self,
        task: Task,
        agent_id: str | None,
    ) -> dict[str, Any]:
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

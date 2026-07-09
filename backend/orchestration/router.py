"""
Router for multi-agent orchestration.

Routes tasks to appropriate agents based on:
- Task type and requirements
- Agent capabilities and specializations
- Agent availability and load
- Permission requirements
"""

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from backend.orchestration.models import Agent, Lane, LaneStatus, Task
from backend.orchestration.permission import PermissionPreset

if TYPE_CHECKING:
    from backend.orchestration.approval_tokens import ApprovalTokenStore
    from backend.orchestration.policy_engine import (
        PolicyContext,
        PolicyDecisionEvent,
        PolicyEngine,
    )


class DispatchStrategy(str, Enum):
    """Task dispatch strategies."""

    ROUND_ROBIN = "round_robin"  # Distribute evenly
    CAPABILITY_BASED = "capability_based"  # Match by agent capabilities
    LOAD_BASED = "load_based"  # Route to least loaded agent


@dataclass
class RoutingDecision:
    """Result of routing a task to an agent."""

    agent_id: str
    lane_id: str
    strategy_used: DispatchStrategy
    reasoning: str


class Router:
    """Routes tasks to agents and creates execution lanes."""

    def __init__(
        self,
        lane_registry,
        agent_registry,
        strategy: DispatchStrategy = DispatchStrategy.CAPABILITY_BASED,
        policy_engine: "PolicyEngine | None" = None,
        token_store: "ApprovalTokenStore | None" = None,
    ):
        """
        Initialize router.

        Args:
            lane_registry: LaneRegistry for creating/managing lanes
            agent_registry: AgentRegistry for querying available agents
            strategy: Dispatch strategy to use
            policy_engine: Optional PolicyEngine for typed decision events
                (M2). When None, `dispatch_with_policy` falls back to plain
                `route_task` semantics.
            token_store: Optional ApprovalTokenStore for privileged dispatch
                (M2). When None, `try_dispatch_privileged` denies any
                approval-required action with reason "token_store_unavailable".
        """
        self.lane_registry = lane_registry
        self.agent_registry = agent_registry
        self.strategy = strategy
        self.policy_engine = policy_engine
        self.token_store = token_store
        self._round_robin_index = 0

    async def route_task(self, task: Task) -> RoutingDecision:
        """
        Route a task to an appropriate agent.

        Args:
            task: Task to route

        Returns:
            RoutingDecision with agent assignment and lane creation

        Raises:
            ValueError: If no suitable agent is available
        """
        # Get available agents
        available_agents = await self._get_available_agents()
        if not available_agents:
            raise ValueError("No agents available for task routing")

        # Select agent based on strategy
        if self.strategy == DispatchStrategy.ROUND_ROBIN:
            agent = self._select_round_robin(available_agents)
            reasoning = "Round-robin selection"
        elif self.strategy == DispatchStrategy.CAPABILITY_BASED:
            agent = self._select_by_capability(task, available_agents)
            reasoning = f"Capability match for task type: {task.task_type}"
        else:  # LOAD_BASED
            agent = self._select_by_load(available_agents)
            reasoning = "Least loaded agent"

        if agent is None:
            raise ValueError(f"No suitable agent found for task {task.task_id}")

        # Create lane for execution
        lane = self._create_lane(task, agent)

        return RoutingDecision(
            agent_id=agent.agent_id,
            lane_id=lane.lane_id,
            strategy_used=self.strategy,
            reasoning=reasoning,
        )

    async def _get_available_agents(self) -> List[Agent]:
        """Get list of available agents (not at max concurrency)."""
        all_agents = self.agent_registry.list_agents()
        available = []
        for agent in all_agents:
            if agent.status == "active":
                running_lanes = self.lane_registry.list_lanes_by_agent(agent.agent_id)
                running_count = sum(
                    1 for lane in running_lanes if lane.status == LaneStatus.RUNNING
                )
                if running_count < agent.max_concurrent_tasks:
                    available.append(agent)
        return available

    def _select_round_robin(self, agents: List[Agent]) -> Agent | None:
        """Select agent using round-robin strategy."""
        if not agents:
            return None
        agent = agents[self._round_robin_index % len(agents)]
        self._round_robin_index += 1
        return agent

    def _select_by_capability(self, task: Task, agents: List[Agent]) -> Agent | None:
        """Select agent based on capability match."""
        # Simple capability matching based on task type
        # In production, this could be more sophisticated
        task_type = task.task_type.lower()

        # Score agents by capability match
        scored_agents = []
        for agent in agents:
            score = 0
            capabilities = [c.lower() for c in agent.capabilities]

            # Direct capability match
            if task_type in capabilities:
                score += 10

            # Specialization bonus
            if hasattr(agent, "specializations"):
                specs = [s.lower() for s in agent.specializations]
                if task_type in specs:
                    score += 5

            scored_agents.append((score, agent))

        # Sort by score (descending) and return best match
        scored_agents.sort(key=lambda x: x[0], reverse=True)
        return scored_agents[0][1] if scored_agents else None

    def _select_by_load(self, agents: List[Agent]) -> Agent | None:
        """Select agent with least current load."""
        if not agents:
            return None

        min_load = float("inf")
        selected_agent = None

        for agent in agents:
            running_lanes = self.lane_registry.list_lanes_by_agent(agent.agent_id)
            running_count = sum(1 for lane in running_lanes if lane.status == LaneStatus.RUNNING)
            load_ratio = running_count / agent.max_concurrent_tasks
            if load_ratio < min_load:
                min_load = load_ratio
                selected_agent = agent

        return selected_agent

    def _create_lane(self, task: Task, agent: Agent) -> Lane:
        """Create a lane for task execution."""
        lane_id = str(uuid.uuid4())

        # Determine permission preset based on task requirements
        permission_preset = self._determine_permission(task, agent)

        lane = Lane(
            lane_id=lane_id,
            task_id=task.task_id,
            agent_id=agent.agent_id,
            status=LaneStatus.CREATED,
            permission_preset=permission_preset,
            metadata={
                "task_type": task.task_type,
                "routed_at": uuid.uuid4().hex[:8],
            },
        )

        self.lane_registry.create_lane(lane)
        return lane

    def _determine_permission(self, task: Task, agent: Agent) -> PermissionPreset:
        """Determine appropriate permission preset for lane."""
        # If task specifies required permission, use it
        if hasattr(task, "required_permission") and task.required_permission:
            return PermissionPreset(task.required_permission)

        # If agent has default permission, use it
        if hasattr(agent, "default_permission") and agent.default_permission:
            return PermissionPreset(agent.default_permission)

        # Default to IMPLEMENT for most tasks
        return PermissionPreset.IMPLEMENT

    async def cancel_lane(self, lane_id: str) -> bool:
        """
        Cancel a running lane.

        Args:
            lane_id: ID of lane to cancel

        Returns:
            True if cancelled successfully, False otherwise
        """
        lane = self.lane_registry.get_lane(lane_id)
        if lane is None:
            return False

        if lane.status in [LaneStatus.RUNNING, LaneStatus.QUEUED]:
            self.lane_registry.update_lane_status(lane_id, LaneStatus.CANCELLED)
            return True

        return False

    def get_routing_stats(self) -> Dict[str, Any]:
        """Get routing statistics."""
        all_lanes = self.lane_registry.list_all_lanes()
        stats = {
            "total_lanes": len(all_lanes),
            "by_status": {},
            "by_strategy": self.strategy.value,
        }

        for lane in all_lanes:
            status = lane.status.value
            stats["by_status"][status] = stats["by_status"].get(status, 0) + 1

        return stats

    # ------------------------------------------------------------------
    # M2 — policy + approval integration
    # ------------------------------------------------------------------

    async def dispatch_with_policy(
        self,
        task: Task,
        context: "PolicyContext",
    ) -> Tuple[RoutingDecision, List["PolicyDecisionEvent"]]:
        """Evaluate the policy context and then dispatch the task.

        When `policy_engine` is None, this is a thin wrapper over `route_task`
        (returns empty events). When policy_engine is present, decision events
        are emitted for each matching rule (audit trail); dispatch always
        proceeds — privileged actions must use `try_dispatch_privileged`.
        """
        events: List[PolicyDecisionEvent] = []
        if self.policy_engine is not None:
            _, events = self.policy_engine.evaluate_with_events(context)
        decision = await self.route_task(task)
        return decision, events

    async def try_dispatch_privileged(
        self,
        task: Task,
        token_id: Optional[str],
        actor: str,
        context: "PolicyContext",
    ) -> Tuple[Optional[RoutingDecision], List["PolicyDecisionEvent"], Optional[str]]:
        """Dispatch a task that may require an approval token.

        Algorithm:
        1. Evaluate policy against the context.
        2. If any decision has kind=APPROVAL:
           - `token_store` must be configured, else deny with reason
             "token_store_unavailable".
           - `token_id` must be provided, else deny with "token_required".
           - The token must be consumable for (actor, action, repo, branch),
             else deny with the token store's `DenyReason`.
           - On successful consume, dispatch proceeds.
        3. Otherwise dispatch normally.
        """
        events: List[PolicyDecisionEvent] = []
        if self.policy_engine is not None:
            decisions, events = self.policy_engine.evaluate_with_events(context)
        else:
            decisions = []

        approval_decisions = [d for d in decisions if d.kind.value == "approval"]
        if approval_decisions:
            if self.token_store is None:
                return None, events, "token_store_unavailable"
            if token_id is None:
                return None, events, "token_required"
            result = self.token_store.consume(
                token_id=token_id,
                actor=actor,
                action=context.action or "",
                repo=context.repo,
                branch=context.branch,
                commit=context.commit or None,
            )
            if not result.granted:
                reason = result.reason.value if result.reason else "denied"
                return None, events, f"token_consume_failed:{reason}"

        decision = await self.route_task(task)
        return decision, events, None

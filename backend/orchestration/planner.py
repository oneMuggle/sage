"""
Planner for multi-agent orchestration.

Uses LLM to decompose user requests into multiple tasks with dependencies.
Creates Teams to manage task groups and supports plan refinement.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any

from backend.orchestration.models import Task, Team
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry


@dataclass
class Plan:
    """Represents a decomposition plan."""

    plan_id: str
    team_id: str
    tasks: list[Task]
    original_request: str
    reasoning: str


class Planner:
    """Decomposes user requests into task graphs using LLM."""

    def __init__(
        self,
        task_registry: TaskRegistry,
        team_registry: TeamRegistry,
        llm_client=None,
    ):
        """
        Initialize planner.

        Args:
            task_registry: TaskRegistry for creating/managing tasks
            team_registry: TeamRegistry for creating/managing teams
            llm_client: LLM client for task decomposition (optional)
        """
        self.task_registry = task_registry
        self.team_registry = team_registry
        self.llm_client = llm_client

    async def decompose_request(
        self,
        request: str,
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """
        Decompose a user request into multiple tasks.

        Args:
            request: User's natural language request
            context: Optional context (session info, user preferences, etc.)

        Returns:
            Plan with tasks and team association

        Raises:
            ValueError: If decomposition fails
        """
        # Create team for this plan
        team_id = str(uuid.uuid4())
        team = Team(
            team_id=team_id,
            name=f"Plan for: {request[:50]}",
            task_ids=[],
            metadata={
                "original_request": request,
                "context": context or {},
            },
        )
        self.team_registry.create_team(team)

        # Decompose using LLM or fallback to simple decomposition
        if self.llm_client:
            tasks, reasoning = await self._decompose_with_llm(request, context)
        else:
            tasks, reasoning = self._simple_decompose(request)

        # Create tasks with dependencies
        created_tasks = []
        for task_data in tasks:
            task = Task(
                task_id=str(uuid.uuid4()),
                name=task_data["name"],
                description=task_data["description"],
                task_type=task_data.get("task_type", "general"),
                parameters=task_data.get("parameters", {}),
                blocked_by=task_data.get("blocked_by", []),
                blocks=task_data.get("blocks", []),
                team_id=team_id,
            )
            self.task_registry.create_task(task)
            created_tasks.append(task)
            team.task_ids.append(task.task_id)

        # Update team with task IDs
        self.team_registry.update_team(team)

        return Plan(
            plan_id=str(uuid.uuid4()),
            team_id=team_id,
            tasks=created_tasks,
            original_request=request,
            reasoning=reasoning,
        )

    async def _decompose_with_llm(
        self,
        request: str,
        context: dict[str, Any] | None = None,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Decompose request using LLM.

        Returns:
            Tuple of (tasks_list, reasoning)
        """
        # Build prompt for task decomposition
        prompt = self._build_decomposition_prompt(request, context)

        # Call LLM
        try:
            response = await self.llm_client.generate(
                prompt=prompt,
                temperature=0.3,
                max_tokens=2000,
            )

            # Parse response
            tasks, reasoning = self._parse_llm_response(response)
            return tasks, reasoning

        except Exception:
            # Fallback to simple decomposition
            return self._simple_decompose(request)

    def _build_decomposition_prompt(
        self,
        request: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Build prompt for LLM task decomposition."""
        context_str = json.dumps(context, indent=2) if context else "None"

        return f"""You are a task planning assistant. Decompose the following user request into a graph of tasks.

User Request: {request}

Context: {context_str}

Instructions:
1. Break down the request into discrete, actionable tasks
2. Identify dependencies between tasks (which tasks block others)
3. Assign task types (general, research, coding, analysis, testing, etc.)
4. Provide clear descriptions for each task

Output format (JSON):
{{
  "tasks": [
    {{
      "name": "Task name",
      "description": "Detailed description",
      "task_type": "general|research|coding|analysis|testing",
      "parameters": {{}},
      "blocked_by": [],
      "blocks": []
    }}
  ],
  "reasoning": "Explanation of decomposition strategy"
}}

Return ONLY valid JSON, no additional text."""


    def _parse_llm_response(
        self,
        response: str,
    ) -> tuple[list[dict[str, Any]], str]:
        """Parse LLM response into tasks and reasoning."""
        try:
            # Extract JSON from response
            data = json.loads(response)
            tasks = data.get("tasks", [])
            reasoning = data.get("reasoning", "LLM decomposition")
            return tasks, reasoning
        except json.JSONDecodeError:
            # Fallback to simple decomposition
            return self._simple_decompose(response)

    def _simple_decompose(
        self,
        request: str,
    ) -> tuple[list[dict[str, Any]], str]:
        """
        Simple fallback decomposition without LLM.

        Creates a single task for the entire request.
        """
        task = {
            "name": f"Execute: {request[:100]}",
            "description": request,
            "task_type": "general",
            "parameters": {},
            "blocked_by": [],
            "blocks": [],
        }
        return [task], "Simple single-task decomposition (fallback)"

    async def refine_plan(
        self,
        plan: Plan,
        feedback: str,
    ) -> Plan:
        """
        Refine an existing plan based on feedback.

        Args:
            plan: Existing plan to refine
            feedback: User feedback or new requirements

        Returns:
            Updated Plan

        Raises:
            ValueError: If refinement fails
        """
        # TODO: Implement plan refinement with LLM
        # For now, return the original plan
        return plan

    def get_plan_status(self, plan_id: str) -> dict[str, Any]:
        """
        Get status of a plan.

        Args:
            plan_id: Plan ID to query

        Returns:
            Dict with plan status information
        """
        # Find team by plan_id (stored in metadata)
        # For now, return basic info
        return {
            "plan_id": plan_id,
            "status": "unknown",
            "message": "Plan status tracking not yet implemented",
        }

    def validate_task_graph(self, tasks: list[Task]) -> bool:
        """
        Validate task graph for cycles and consistency.

        Args:
            tasks: List of tasks to validate

        Returns:
            True if valid, False otherwise
        """
        # Build adjacency list
        task_map = {t.task_id: t for t in tasks}
        visited = set()
        rec_stack = set()

        def has_cycle(task_id: str) -> bool:
            if task_id not in rec_stack:
                rec_stack.add(task_id)
                visited.add(task_id)

                for blocked_id in task_map[task_id].blocked_by:
                    if blocked_id in task_map:
                        if blocked_id not in visited:
                            if has_cycle(blocked_id):
                                return True
                        elif blocked_id in rec_stack:
                            return True

                rec_stack.remove(task_id)
            return False

        # Check for cycles
        return all(not (task_id not in visited and has_cycle(task_id)) for task_id in task_map)

"""
Planner for multi-agent orchestration.

Uses LLM to decompose user requests into multiple tasks with dependencies.
Creates Teams to manage task groups and supports plan refinement.
"""

import json
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.orchestration.models import Task, Team
from backend.orchestration.task_registry import TaskRegistry
from backend.orchestration.team_registry import TeamRegistry

logger = logging.getLogger(__name__)

# Hard cap on planner-emitted tasks (LLM output is truncated to this).
MAX_PLAN_TASKS = 8


def _is_dispatchable_agent(agent_id: str) -> bool:
    """agent_id 当前是否可被 ChatDispatcher 派发（存在且启用）。

    F4 (2026-08-12): LLM 可能产出已下线/不存在的角色（如 content_writer、
    editor），若照单全收，ChatDispatcher._run_subagent 会因
    ``get_enabled_agent()`` 返回 None 而快速失败（spec §5.1），整批子任务
    failed。这里在 planner 源头静默丢弃非法 hint，conductor 后续以默认
    角色执行。

    判定用与 _run_subagent 完全相同的 ``get_enabled_agent()``（读 SQLite
    运行时状态），保证 planner 放行的 hint 一定能成功派发：
    - 内存注册表 ``get_agent_registry()`` 不反映 SQLite enabled 状态
      （toggle_agent 禁用后仍残留，用它校验会漏掉"已注册但禁用"一半）
    - 自定义 agent 只存 SQLite 不在内存注册表，必须走 SQLite 查询

    延迟 import 避免任何循环引用；每任务一次 SQLite 查询（≤8 任务，
    开销可忽略）。
    """
    from backend.agents.profiles import get_enabled_agent

    return get_enabled_agent(agent_id) is not None

# Hard cap on a single task description (titles are capped at 200; the
# description was previously bounded only by the LLM max_tokens).
MAX_TASK_DESCRIPTION_CHARS = 4000

# task_type values the rest of the orchestration layer understands.
KNOWN_TASK_TYPES = frozenset({"general", "research", "coding", "analysis", "testing"})

# Matches ```json ... ``` / ``` ... ``` fences some models emit anyway.
_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


@dataclass
class Plan:
    """Represents a decomposition plan."""

    plan_id: str
    team_id: str
    tasks: List[Task]
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
        context: Optional[Dict[str, Any]] = None,
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
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], str]:
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
        context: Optional[Dict[str, Any]] = None,
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
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Parse LLM response into tasks and reasoning."""
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        raw_tasks = data.get("tasks")
        if not isinstance(raw_tasks, list) or not raw_tasks:
            return None

        reasoning = data.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning:
            reasoning = "LLM decomposition"

        return self._sanitize_tasks(raw_tasks), reasoning

    def _sanitize_tasks(self, raw_tasks: List[Any]) -> List[Dict[str, Any]]:
        """Validate/clean LLM-emitted tasks into registry-ready dicts.

        Guarantees: at most MAX_PLAN_TASKS tasks; blocked_by only references
        earlier tasks in the list (structurally acyclic); every task has a
        non-empty name and description; names capped at 200 chars and
        descriptions at MAX_TASK_DESCRIPTION_CHARS.
        """
        sanitized: List[Dict[str, Any]] = []
        id_map: Dict[str, str] = {}  # LLM-provided id -> positional placeholder

        for index, raw in enumerate(raw_tasks[:MAX_PLAN_TASKS]):
            if not isinstance(raw, dict):
                continue

            title = raw.get("title") or raw.get("name")
            description = raw.get("description")
            if not isinstance(title, str) or not title.strip():
                if isinstance(description, str) and description.strip():
                    title = description.strip()[:60]
                else:
                    title = f"Task {index + 1}"
            if not isinstance(description, str) or not description.strip():
                description = title

            task_type = raw.get("task_type", "general")
            if task_type not in KNOWN_TASK_TYPES:
                task_type = "general"

            # Placeholder id used for dependency resolution; the registry
            # assigns the real id at creation time (callers re-map via the
            # returned order — blocked_by here uses placeholder tokens that
            # decompose_request's caller resolves). Simpler contract: we
            # resolve dependencies to *positional indexes* encoded as
            # "prev:<n>" tokens, then map to real ids post-creation.
            provided_id = raw.get("id")
            placeholder = f"idx:{index}"
            if isinstance(provided_id, str) and provided_id.strip():
                id_map[provided_id.strip()] = placeholder
            id_map[f"t{index + 1}"] = placeholder  # common default scheme

            agent_hint = raw.get("agent_hint")
            parameters: Dict[str, Any] = {}
            if (
                isinstance(agent_hint, str)
                and agent_hint.strip()
                and _is_dispatchable_agent(agent_hint.strip())
            ):
                # F4 (2026-08-12): 只接受可派发角色，非法 hint 静默丢弃
                # （见 _is_dispatchable_agent docstring）。
                parameters["agent_hint"] = agent_hint.strip()

            sanitized.append(
                {
                    "name": title.strip()[:200],
                    "description": description.strip()[:MAX_TASK_DESCRIPTION_CHARS],
                    "task_type": task_type,
                    "parameters": parameters,
                    "blocked_by": [],  # resolved below, once all ids are known
                    "_placeholder": placeholder,
                    "_raw_depends_on": raw.get("depends_on") or [],
                }
            )

        # Second pass: resolve depends_on to placeholders of EARLIER tasks
        # only (forward references / cycles are dropped — keeps a DAG).
        seen_placeholders = set()
        for item in sanitized:
            resolved: List[str] = []
            deps = item.pop("_raw_depends_on")
            placeholder = item["_placeholder"]
            if isinstance(deps, list):
                for dep in deps:
                    if not isinstance(dep, str):
                        continue
                    target = id_map.get(dep.strip())
                    if (
                        target is not None
                        and target in seen_placeholders
                        and target not in resolved
                        and target != placeholder
                    ):
                        resolved.append(target)
            item["blocked_by"] = resolved
            seen_placeholders.add(placeholder)

        return sanitized

    def _simple_decompose(
        self,
        request: str,
    ) -> Tuple[List[Dict[str, Any]], str]:
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

    def get_plan_status(self, plan_id: str) -> Dict[str, Any]:
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

    def validate_task_graph(self, tasks: List[Task]) -> bool:
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

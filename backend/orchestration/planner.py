"""
Planner for multi-agent orchestration.

Uses an LLM to decompose user requests into a task DAG (teams + tasks with
dependencies). When no LLM is available — none injected *and* none derivable
from the user's endpoint settings — planning degrades to a single-task
fallback (the raw goal) rather than failing.

The LLM default construction reuses the evolution-task pattern
(``backend/scheduler/evolution.py``): the client is injectable for tests and
otherwise built from persisted ``app_settings`` via
``backend.orchestration.llm_factory``.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from backend.orchestration.llm_factory import build_llm_client_from_settings
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
    """Decomposes user requests into task graphs using an LLM."""

    def __init__(
        self,
        task_registry: TaskRegistry,
        team_registry: TeamRegistry,
        llm_client: Any = None,
        auto_configure: bool = True,
    ) -> None:
        """
        Initialize planner.

        Args:
            task_registry: TaskRegistry for creating/managing tasks
            team_registry: TeamRegistry for creating/managing teams
            llm_client: Injectable LLM client exposing ``async complete(prompt)
                -> str``. When None and ``auto_configure`` is True, a client is
                built from the user's persisted endpoint settings (None if no
                endpoint is configured — planning degrades to single-task).
            auto_configure: Build a settings-derived LLM client when
                ``llm_client`` is None. Tests pass False to force the degraded
                path deterministically.
        """
        self.task_registry = task_registry
        self.team_registry = team_registry
        if llm_client is None and auto_configure:
            llm_client = build_llm_client_from_settings()
            if llm_client is None:
                logger.info("Planner: no LLM configured, single-task fallback active")
        self.llm_client = llm_client

    async def decompose_request(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Plan:
        """
        Decompose a user request into a team of tasks.

        Never raises for LLM failures — malformed output or a missing LLM
        yields a single-task plan wrapping the raw goal.

        Args:
            request: User's natural language request (the goal)
            context: Optional context (session info, agent hint, etc.)

        Returns:
            Plan with persisted tasks and team association
        """
        import uuid

        # Create the team that groups this plan's tasks.
        team: Team = self.team_registry.create_team(
            name=f"Plan for: {request[:50]}",
            metadata={
                "original_request": request,
                "context": context or {},
                "source": "planner",
            },
        )

        # Decompose using LLM or fallback to single-task decomposition.
        if self.llm_client is not None:
            tasks, reasoning = await self._decompose_with_llm(request, context)
        else:
            tasks, reasoning = self._simple_decompose(request)

        # Persist tasks first (real ids assigned here), then resolve the
        # positional dependency placeholders ("idx:N") to real task ids.
        created_tasks: List[Task] = []
        placeholders: List[str] = []
        for task_data in tasks:
            task = Task(
                task_id=f"task-{uuid.uuid4().hex[:12]}",
                name=task_data["name"],
                description=task_data["description"],
                task_type=task_data.get("task_type", "general"),
                parameters=task_data.get("parameters", {}),
                blocked_by=[],
                team_id=team.team_id,
            )
            self.task_registry.create_task(task)
            created_tasks.append(task)
            placeholders.append(task_data.get("_placeholder", f"idx:{len(placeholders)}"))
            self.team_registry.add_task(team.team_id, task.task_id)

        # Second pass: wire dependencies (sanitized to earlier tasks only).
        placeholder_to_id = {
            placeholder: created_tasks[index].task_id for index, placeholder in enumerate(placeholders)
        }
        created_by_id = {t.task_id: t for t in created_tasks}
        for index, task_data in enumerate(tasks):
            resolved = [
                placeholder_to_id[dep]
                for dep in task_data.get("blocked_by", [])
                if dep in placeholder_to_id
            ]
            if not resolved:
                continue
            created_tasks[index].blocked_by = resolved
            self.task_registry.repo.update(created_tasks[index])
            # Back-wire the bidirectional relationship (create_task only does
            # this when blocked_by is set at creation time). Mutate the
            # in-memory created instances so Plan.tasks stays consistent.
            for dep_id in resolved:
                dep_task = created_by_id.get(dep_id)
                if dep_task is not None and created_tasks[index].task_id not in dep_task.blocks:
                    dep_task.blocks.append(created_tasks[index].task_id)
                    self.task_registry.repo.update(dep_task)

        return Plan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            team_id=team.team_id,
            tasks=created_tasks,
            original_request=request,
            reasoning=reasoning,
        )

    async def decompose_from_template(
        self,
        template_id: str,
        request: str,
    ) -> Plan:
        """按内置模板确定性拆解（P2-8）—— 不走 LLM，可复现。

        模板不存在 → ``ValueError``（caller 降级 single）。stage goal 的
        ``{request}`` 用 ``str.replace`` 替换（同 classify，防 .format() 抛错）；
        无占位符则追加 ``\n目标: {request}``。``agent_hint`` 仅当角色可派发时
        写入（复用 F4 校验，否则回退 conductor 默认角色）。
        """
        import uuid

        from backend.orchestration.templates import get_template

        template = get_template(template_id)
        if template is None:
            raise ValueError(f"unknown orchestration template: {template_id}")

        team = self.team_registry.create_team(
            name=f"Template {template.name}: {request[:50]}",
            metadata={
                "original_request": request,
                "source": "template",
                "template": template_id,
            },
        )

        created_tasks: List[Task] = []
        stage_to_task: Dict[str, str] = {}
        for stage in template.stages:
            goal = (
                stage.goal.replace("{request}", request)
                if "{request}" in stage.goal
                else f"{stage.goal}\n目标: {request}"
            )
            parameters: Dict[str, Any] = {}
            if _is_dispatchable_agent(stage.agent_id):
                parameters["agent_hint"] = stage.agent_id
            task = Task(
                task_id=f"task-{uuid.uuid4().hex[:12]}",
                name=stage.id,  # 模板 stage 序号 t1..tN（depends_on 引用它）
                description=goal,
                task_type="general",
                parameters=parameters,
                blocked_by=[],
                team_id=team.team_id,
            )
            self.task_registry.create_task(task)
            created_tasks.append(task)
            stage_to_task[stage.id] = task.task_id
            self.team_registry.add_task(team.team_id, task.task_id)

        # 第二遍：stage.id 依赖 → 真实 task_id（只引更早任务，保 DAG）。
        created_by_id = {t.task_id: t for t in created_tasks}
        # Py3.8 兼容：zip 无 strict 关键字（main 用 strict=False，长度本已相等）。
        for stage, task in zip(template.stages, created_tasks):
            resolved = [stage_to_task[dep] for dep in stage.depends_on if dep in stage_to_task]
            if not resolved:
                continue
            task.blocked_by = resolved
            self.task_registry.repo.update(task)
            for dep_id in resolved:
                dep_task = created_by_id.get(dep_id)
                if dep_task is not None and task.task_id not in dep_task.blocks:
                    dep_task.blocks.append(task.task_id)
                    self.task_registry.repo.update(dep_task)

        return Plan(
            plan_id=f"plan-{uuid.uuid4().hex[:12]}",
            team_id=team.team_id,
            tasks=created_tasks,
            original_request=request,
            reasoning=f"template: {template_id}",
        )

    async def _decompose_with_llm(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[List[Dict[str, Any]], str]:
        """Decompose request via the LLM; any failure → single-task fallback."""
        prompt = self._build_decomposition_prompt(request, context)

        try:
            response = await self.llm_client.complete(prompt)
        except Exception as exc:
            logger.warning("Planner LLM call failed, falling back: %s", exc)
            return self._simple_decompose(request)

        if not response or not isinstance(response, str):
            return self._simple_decompose(request)

        parsed = self._parse_llm_response(response)
        if parsed is None:
            logger.warning("Planner: malformed LLM JSON, falling back to single task")
            return self._simple_decompose(request)

        tasks, reasoning = parsed
        if not tasks:
            return self._simple_decompose(request)
        return tasks, reasoning

    def _build_decomposition_prompt(
        self,
        request: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build the JSON-DAG decomposition prompt."""
        context_str = json.dumps(context, indent=2, ensure_ascii=False) if context else "None"

        return f"""You are a task planning assistant. Decompose the following goal into a directed acyclic graph of tasks.

Goal: {request}

Context: {context_str}

Instructions:
1. Break the goal into discrete, actionable tasks (at most {MAX_PLAN_TASKS}).
2. Express dependencies via "depends_on" referencing earlier task ids only.
3. Use "agent_hint" to suggest an executor role (e.g. researcher, coder, memory_manager) or omit.
4. Keep titles short; descriptions carry the detail.

Output format — return ONLY valid JSON, no markdown fences, no extra text:
{{
  "tasks": [
    {{
      "id": "t1",
      "title": "Short task title",
      "description": "Detailed description of the work",
      "depends_on": [],
      "agent_hint": "researcher"
    }}
  ],
  "reasoning": "Explanation of the decomposition strategy"
}}"""

    def _parse_llm_response(
        self,
        response: str,
    ) -> Optional[Tuple[List[Dict[str, Any]], str]]:
        """Parse + sanitize the LLM response.

        Returns:
            (sanitized_tasks, reasoning) or None when the payload is not
            usable JSON (caller falls back to single-task decomposition).
        """
        text = _CODE_FENCE_RE.sub("", response.strip()).strip()
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
        Degraded single-task decomposition (no LLM / malformed output).

        The raw goal becomes one executable task; planning still "works".
        """
        task = {
            "name": f"Execute: {request[:100]}",
            "description": request,
            "task_type": "general",
            "parameters": {},
            "blocked_by": [],
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

        return all(not (task_id not in visited and has_cycle(task_id)) for task_id in task_map)

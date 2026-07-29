"""
Adapter: seeded agent repository -> orchestration Router agent registry.

The orchestration ``Router`` expects an agent registry exposing
``list_agents() -> List[orchestration.Agent]``. The application's agents are
seeded into SQLite (``AgentRepository``: primary / researcher / coder /
memory_manager, see ``backend/agents/profiles.py``). This thin adapter maps
the persisted dict profiles to orchestration ``Agent`` models so the Router
can do capability dispatch against the real agent roster.

Shared by ``backend/main.py`` (lifespan wiring) and the orchestration API
router (lane creation endpoint).
"""

from __future__ import annotations

import json
from typing import List, Optional

from backend.orchestration.models import Agent


class SeededAgentRegistry:
    """Adapts ``AgentRepository`` (dict rows) to the Router's interface."""

    def __init__(self, repo=None) -> None:
        if repo is None:
            from backend.data.agent_repo import AgentRepository

            repo = AgentRepository()
        self._repo = repo

    def list_agents(self) -> List[Agent]:
        """List enabled seeded agents as orchestration ``Agent`` models."""
        agents: List[Agent] = []
        for profile in self._repo.list_all():
            if not profile.get("enabled", True):
                continue
            agents.append(self._to_agent(profile))
        return agents

    def get_agent(self, agent_id: str) -> Optional[Agent]:
        """Fetch a single enabled agent, or None (missing/disabled)."""
        profile = self._repo.get(agent_id)
        if profile is None or not profile.get("enabled", True):
            return None
        return self._to_agent(profile)

    @staticmethod
    def _to_agent(profile: dict) -> Agent:
        """Convert a persisted agent profile dict to an orchestration Agent."""
        tools = profile.get("tools", [])
        if isinstance(tools, str):
            try:
                tools = json.loads(tools)
            except (json.JSONDecodeError, TypeError):
                tools = []
        return Agent(
            agent_id=profile["id"],
            name=profile.get("name", profile["id"]),
            status="active",
            capabilities=list(tools) if tools else [profile.get("role", "general")],
            max_concurrent_tasks=2,
            default_permission="implement",
        )

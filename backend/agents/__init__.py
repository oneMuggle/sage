"""
Agents Module - 多Agent系统
"""
from backend.agents.profiles import (
    AgentProfile,
    AgentModelConfig,
    create_default_agents,
    get_agent,
    list_agents,
    register_agent,
    get_agent_registry,
)

__all__ = [
    "AgentProfile",
    "AgentModelConfig",
    "create_default_agents",
    "get_agent",
    "list_agents",
    "register_agent",
    "get_agent_registry",
]

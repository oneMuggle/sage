"""
Agent Profiles - Agent 角色定义和配置
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentModelConfig:
    """Agent 使用的 LLM 模型配置"""

    model: str = "gpt-3.5-turbo"
    temperature: float = 0.7
    max_tokens: int = 4096


@dataclass
class AgentProfile:
    """Agent 角色档案"""

    id: str
    name: str
    role: str  # "coordinator" | "researcher" | "coder" | "memory_manager"
    system_prompt: str
    tools: list[str] = field(default_factory=list)
    memory_access: list[str] = field(default_factory=lambda: ["working", "episodic", "semantic"])
    model_config: AgentModelConfig = field(default_factory=AgentModelConfig)
    max_iterations: int = 10
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """导出为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "role": self.role,
            "system_prompt": self.system_prompt,
            "tools": self.tools,
            "memory_access": self.memory_access,
            "model_config": self.model_config.__dict__,
            "max_iterations": self.max_iterations,
            "enabled": self.enabled,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProfile:
        """从字典创建"""
        model_data = data.pop("model_config", {})
        model_config = AgentModelConfig(**model_data) if model_data else AgentModelConfig()
        return cls(model_config=model_config, **data)


def create_default_agents() -> list[AgentProfile]:
    """创建默认的 Agent 配置"""
    return [
        AgentProfile(
            id="primary",
            name="Sage 主助手",
            role="coordinator",
            description="面向用户的协调 Agent，负责意图识别和任务分发",
            system_prompt="你是 Sage，一个智能 AI 助手。负责理解用户需求并协调其他 Agent 完成任务。",
            tools=["calculator", "memory_search", "memory_save"],
            memory_access=["working", "episodic", "semantic"],
            model_config=AgentModelConfig(model="gpt-4", temperature=0.7),
            max_iterations=10,
        ),
        AgentProfile(
            id="researcher",
            name="研究 Agent",
            role="researcher",
            description="负责网络搜索和信息收集的 Agent",
            system_prompt="你是一个专业的研究 Agent。负责搜索信息、综合资料、生成研究报告。",
            tools=["web_search", "web_fetch", "memory_search"],
            memory_access=["episodic", "semantic"],
            model_config=AgentModelConfig(model="gpt-4", temperature=0.5),
            max_iterations=8,
        ),
        AgentProfile(
            id="coder",
            name="编码 Agent",
            role="coder",
            description="负责代码生成、调试和解释的 Agent",
            system_prompt="你是一个专业的编码 Agent。负责生成高质量代码、调试、代码审查。",
            tools=["file_read", "file_write", "terminal", "calculator"],
            memory_access=["semantic"],
            model_config=AgentModelConfig(model="gpt-4", temperature=0.3),
            max_iterations=15,
        ),
        AgentProfile(
            id="memory_manager",
            name="记忆 Agent",
            role="memory_manager",
            description="负责记忆管理和知识提取的 Agent",
            system_prompt="你是一个记忆管理 Agent。负责提取、分类和管理对话中的知识。",
            tools=["memory_search", "memory_save"],
            memory_access=["working", "episodic", "semantic"],
            model_config=AgentModelConfig(model="gpt-3.5-turbo", temperature=0.5),
            max_iterations=5,
        ),
    ]


# 全局 Agent 注册表
_agent_registry: dict[str, AgentProfile] = {}


def get_agent_registry() -> dict[str, AgentProfile]:
    """获取 Agent 注册表"""
    if not _agent_registry:
        for agent in create_default_agents():
            _agent_registry[agent.id] = agent
    return _agent_registry


def register_agent(profile: AgentProfile) -> None:
    """注册一个 Agent"""
    _agent_registry[profile.id] = profile


def get_agent(agent_id: str) -> AgentProfile | None:
    """获取指定 Agent 的配置"""
    return get_agent_registry().get(agent_id)


def list_agents() -> list[AgentProfile]:
    """列出所有已注册的 Agent"""
    return list(get_agent_registry().values())

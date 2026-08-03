"""
Agent Profiles - Agent 角色定义和配置
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


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
    tools: List[str] = field(default_factory=list)
    memory_access: List[str] = field(default_factory=lambda: ["working", "episodic", "semantic"])
    model_config: AgentModelConfig = field(default_factory=AgentModelConfig)
    max_iterations: int = 10
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> Dict[str, Any]:
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
    def from_dict(cls, data: Dict[str, Any]) -> AgentProfile:
        """从字典创建"""
        model_data = data.pop("model_config", {})
        model_config = AgentModelConfig(**model_data) if model_data else AgentModelConfig()
        return cls(model_config=model_config, **data)


def create_default_agents() -> List[AgentProfile]:
    """创建默认的 Agent 配置"""
    return [
        AgentProfile(
            id="primary",
            name="Sage 主助手",
            role="coordinator",
            description="面向用户的协调 Agent，负责意图识别和任务分发",
            system_prompt="你是 Sage，一个智能 AI 助手。负责理解用户需求并协调其他 Agent 完成任务。",
            # 2026-07-30: 加 list_dir/read_file 让 chat 默认能跑代码 review;
            # max_iterations=15 给 coder 类工作流留出预算(否则会复现 max_iterations_exceeded)
            # 2026-08-01: 加 grep_search/glob_search/file_summary 三件套，
            # 解决大代码库分析时 max_iterations_exceeded 问题（PR #264）
            tools=[
                "calculator",
                "memory_search",
                "memory_save",
                "list_dir",
                "read_file",
                # 代码探索三件套（全部 READ 操作，无副作用风险）
                "grep_search",    # 正则内容搜索（GrepSearchTool）
                "glob_search",    # glob 文件名搜索（GlobSearchTool）
                "file_summary",   # 文件结构摘要（FileSummaryTool）
            ],
            memory_access=["working", "episodic", "semantic"],
            model_config=AgentModelConfig(model="gpt-4", temperature=0.7),
            max_iterations=15,
        ),
        AgentProfile(
            id="researcher",
            name="研究 Agent",
            role="researcher",
            description="负责网络搜索和信息收集的 Agent",
            system_prompt="你是一个专业的研究 Agent。负责搜索信息、综合资料、生成研究报告。",
            tools=["web_search", "web_fetch", "memory_search", "memory_save"],
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
        AgentProfile(
            id="writer",
            name="写作 Agent",
            role="writer",
            description="负责把研究资料整理成结构化的学习资料/操作指南等 markdown 文档",
            system_prompt=(
                "你是一个专业的写作 Agent。负责把资料整理成结构清晰、可执行的 "
                "学习资料、操作指南等 markdown 文档。产出文档请用 write_file 工具落盘。"
            ),
            tools=["read_file", "write_file", "memory_search"],
            memory_access=["semantic"],
            model_config=AgentModelConfig(model="gpt-4", temperature=0.4),
            max_iterations=10,
        ),
        AgentProfile(
            id="reviewer",
            name="Reviewer",
            role="reviewer",
            system_prompt=(
                "你是一个严格的复核 Agent。对照子任务的 goal 与产出，逐条给出 "
                "assertion，格式：\n"
                "[FACT|HYPOTHESIS|NEGATIVE_EVIDENCE] <断言> (confidence: 0-1)\n"
                "- FACT：产出中已证实的事实断言；\n"
                "- HYPOTHESIS：产出中提出但未经证实的假设；\n"
                "- NEGATIVE_EVIDENCE：与目标相矛盾或缺失关键证据的断言。\n"
                "只输出 assertions 列表，不要多余说明。"
            ),
            tools=[],
        ),
    ]


def ensure_default_agents() -> int:
    """确保所有默认 agent（含 writer）都存在。

    ``seed_defaults_if_empty`` 只在表为空时插，已存在的 DB 不会自动补
    writer —— 本函数逐个检查缺失的默认 id 并补插。返回补插条数。
    """
    from backend.data.agent_repo import AgentRepository

    repo = AgentRepository()
    inserted = 0
    for agent in create_default_agents():
        if repo.get(agent.id) is None:
            repo.upsert(agent.to_dict())
            inserted += 1
    return inserted


# 全局 Agent 注册表
_agent_registry: Dict[str, AgentProfile] = {}


def get_agent_registry() -> Dict[str, AgentProfile]:
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


def list_agents() -> List[AgentProfile]:
    """列出所有已注册的 Agent"""
    return list(get_agent_registry().values())


def get_enabled_agent(agent_id: str) -> Dict[str, Any] | None:
    """从 SQLite 获取启用的 agent profile（运行时读取最新版本）。

    返回 agent dict（与 ``AgentRepository.get()`` 同形态），或：
    - agent 不存在 → None
    - agent 已禁用 → None

    设计意图: 让 SageAgent / Orchestrator 在运行时总是读 SQLite
    (用户刚 PATCH 的 enabled / system_prompt 立即生效), 而不是内存注册表。
    """
    # 延迟 import: 避免 profiles.py (application 层) 在 import 时 eager import data 层
    from backend.data.agent_repo import AgentRepository

    profile = AgentRepository().get(agent_id)
    if profile is None:
        return None
    if not profile.get("enabled", True):
        return None
    return profile


def format_agents_for_prompt() -> str:
    """格式化已启用 Agent 列表，供注入 system prompt。"""
    agents = [a for a in list_agents() if a.enabled]
    if not agents:
        return ""
    lines = [f"- {a.name} ({a.id}): {a.description or a.role}" for a in agents]
    return "\n\n你可以向用户介绍以下可用 Agent：\n" + "\n".join(lines)


#: 默认 system prompt 的工具能力声明——明确告知 LLM 可调用的 Office 创建
#: 能力，避免其凭训练先验回复"没有创建本地文件的权限"（T6 Electron 实测
#: 暴露）。工具/能力变化时手动维护，与 legacy_routes 的 DIAGRAM_TOOL_PROMPT
#: 同模式。
_OFFICE_CREATE_CAPABILITY_PROMPT = (
    "\n\n你可以创建 Office 文档：当用户要求生成 Word/Excel/PPT 文件时，"
    "调用 office_create 工具（提供 doc_type / output_dir / filename / 内容结构）。"
    "写入工作区外（如桌面）时，用户会看到确认框，批准后才会真正写入。"
)


def build_system_base() -> str:
    """构建 system prompt 基础部分（身份 + 工具能力声明 + agent 列表）。"""
    base = "你是 Sage，一个智能 AI 助手。"
    return base + _OFFICE_CREATE_CAPABILITY_PROMPT + format_agents_for_prompt()

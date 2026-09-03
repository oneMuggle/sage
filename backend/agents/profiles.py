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
            # 2026-09-03: 改用 PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION 常量。
            # 出网任务通过 agent 工具委派给只读子代理，coordinator 不直接出网。
            system_prompt=PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION,
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
                # P0-5 (2026-08-20): 循环内只读子代理工具 —— 让主助手能在
                # ReAct 循环内派遣子 agent（AgentTool 只读，无写副作用）。
                "agent",
                # P1 todo 接线 (2026-08-21): 任务清单工具 —— 主助手可在多步
                # 任务中记录/更新计划（todo_state 存会话，无文件副作用）。
                "todo_write",
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
            tools=["web_search", "web_fetch", "http_download", "memory_search"],
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


# P0-5 (2026-08-20): 加 "agent" 之前的 primary 种子工具集合 —— 存量 DB 升级判定。
# 仅当现有白名单恰好等于旧种子时才追加 agent；用户自定义（任何增删）一律不动。
_PRIMARY_TOOLS_BEFORE_AGENT = {
    "calculator",
    "memory_search",
    "memory_save",
    "list_dir",
    "read_file",
    "grep_search",
    "glob_search",
    "file_summary",
}

# P1 todo 接线 (2026-08-21): 加 "todo_write" 之前的 primary 种子集合 ——
# 存量 DB 二段升级判定。仅当白名单恰好等于上一代种子时才追加。
_PRIMARY_TOOLS_BEFORE_TODO = {
    "calculator", "memory_search", "memory_save", "list_dir", "read_file",
    "grep_search", "glob_search", "file_summary", "agent",
}

# 2026-09-03 (PR #396 后置迁移): 加 "http_download" 之前的 researcher 种子集合
# —— 存量 DB 三段升级判定。仅当白名单恰好等于旧种子时追加 http_download;
# 用户自定义（任何增删）一律不动。
_RESEARCHER_TOOLS_BEFORE_HTTP_DOWNLOAD = {
    "web_search", "web_fetch", "memory_search",
}

# 2026-09-03 (PR #396 后置迁移): 加 "agent 子代理委派" 提示之前的 primary 系统提示。
# 存量 DB 命中此字符串才升级 —— 用户自定义 system_prompt 一律不动。
_PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION = (
    "你是 Sage，一个智能 AI 助手。负责理解用户需求并协调其他 Agent 完成任务。"
)


# 2026-09-03 (PR #396 后置迁移): 升级后的 primary system_prompt。新增一段明确指引:
# 网页访问/文件下载/网络搜索等出网任务 → 用 agent 工具委派给只读子代理
# (子代理 SUBAGENT_TOOL_WHITELIST 已含 web_search/web_fetch/http_download)。
# 保持 primary 的 coordinator 定位 —— 出网任务不直接进 primary 白名单,
# 避免 coordinator 同时承担"协调"与"出网执行"两个角色。
PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION = (
    "你是 Sage，一个智能 AI 助手。负责理解用户需求并协调其他 Agent 完成任务。\n\n"
    "对于网页访问、文件下载、网络搜索等出网任务，使用 agent 工具委派给"
    "只读子代理执行（子代理具备 web_search / web_fetch / http_download / memory_search"
    " 等只读工具）。直接回答时不要假装调用了这些工具。"
)


def _default_repo():
    from backend.data.agent_repo import AgentRepository

    return AgentRepository()


#: 测试注入点（monkeypatch 目标）；生产恒走 _default_repo
_repo_factory_for_tests = None


def ensure_default_agents() -> int:
    """确保所有默认 agent（含 writer）都存在。

    ``seed_defaults_if_empty`` 只在表为空时插，已存在的 DB 不会自动补
    writer —— 本函数逐个检查缺失的默认 id 并补插。返回补插条数。
    """
    repo = _repo_factory_for_tests() if _repo_factory_for_tests else _default_repo()
    inserted = 0
    for agent in create_default_agents():
        if repo.get(agent.id) is None:
            repo.upsert(agent.to_dict())
            inserted += 1
    # P0-5 (2026-08-20): 存量 DB primary 升级 —— 旧种子白名单追加 "agent"。
    # 一次 get() 缓存为 primary 局部引用，本函数三段都对它读写（dict 原地变更）。
    # repo.upsert(primary) 后内存与 DB 一致，无需重新 get。
    primary = repo.get("primary")
    if primary is not None:
        tools = primary.get("tools") or []
        if set(tools) == _PRIMARY_TOOLS_BEFORE_AGENT:
            primary["tools"] = tools + ["agent"]
            repo.upsert(primary)
    # P1 todo 接线 (2026-08-21): 存量 DB 二段升级 —— 旧种子追加 todo_write。
    # 顺序敏感：先 agent 后 todo。两级判定互斥（旧种子集合不含 todo_write、
    # 本段集合含 agent），一段升级后集合恰好等于二段判定集，链式生效；
    # 任意自定义白名单都不匹配任一集合，天然不动。
    if primary is not None:
        tools = primary.get("tools") or []
        if set(tools) == _PRIMARY_TOOLS_BEFORE_TODO:
            primary["tools"] = tools + ["todo_write"]
            repo.upsert(primary)
    # 2026-09-03 (PR #396 后置迁移): 存量 DB researcher 升级 —— 旧种子白名单追加
    # http_download。与 primary 升级模式一致：仅当白名单恰好等于旧集合时追加，
    # 用户自定义不动。researcher 自身不是迁移链多段，一次升级即可。
    researcher = repo.get("researcher")
    if researcher is not None:
        tools = researcher.get("tools") or []
        if set(tools) == _RESEARCHER_TOOLS_BEFORE_HTTP_DOWNLOAD:
            researcher["tools"] = tools + ["http_download"]
            repo.upsert(researcher)
    # 2026-09-03 (PR #396 后置迁移): 存量 DB primary system_prompt 升级 —— 命中旧
    # 字符串则替换为 PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION（含 agent 子代理委派提示）。
    # 与 tools 迁移相同的"集合相等/字符串相等"判定：用户自定义 system_prompt 一律不动。
    if primary is not None:
        if primary.get("system_prompt") == _PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION:
            primary["system_prompt"] = PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION
            repo.upsert(primary)
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

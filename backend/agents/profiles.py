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
            # 2026-09-03: 改用 PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT 常量。
            # 简单 fetch/download 由 primary 直调 (用户可见 LLM 行为, 便于分步指导)；
            # 复杂多步研究仍走 agent 工具委派给只读子代理 —— 守 PR #396 coordinator/executor 边界。
            system_prompt=PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT,
            # 2026-07-30: 加 list_dir/read_file 让 chat 默认能跑代码 review;
            # max_iterations=15 给 coder 类工作流留出预算(否则会复现 max_iterations_exceeded)
            # 2026-08-01: 加 grep_search/glob_search/file_summary 三件套，
            # 解决大代码库分析时 max_iterations_exceeded 问题（PR #264）
            # 2026-09-03: 加 web_fetch/http_download —— 用户可见 LLM 取页/下载行为,
            # 便于分步指导。OFFLINE 模式下 ToolRegistry 不注册 (NetworkPolicy 门禁)。
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
                # 2026-09-03 (post-§2 subset 迁移): 用户可见 LLM 取页/下载行为,
                # 便于分步指导和交互。受 NetworkPolicy 门禁, OFFLINE 不注册。
                "web_fetch",
                "http_download",
                # PR-1 (office CRUD 闭环接线) + PR-2 (archive/restore):
                # primary 代用户执行增/改/删/还原, 加上只读 list/read 方便
                # 引导。office_* doc_id 模式走 session binding 守护,
                # file_path 模式仍受 path_boundary_validator 升级审批。
                "office_list",
                "office_read",
                "office_create",
                "office_update",
                "office_delete",
                "office_restore",
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
            # 2026-09-03: PR #381 把 TerminalTool 重写为 BashTool (name="bash"),
            # file_read/file_write 是拼写错位(真实工具名 read_file/write_file)。
            tools=["read_file", "write_file", "bash", "calculator"],
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
            # PR-1 (office CRUD 接线) + PR-2 (archive/restore):
            # 写作 agent 现在可生成/编辑/还原 Office 文档 (report / 操作手册
            # 等适合 docx/xlsx/pptx 形态)。office_* 工具与 write_file 互补:
            # markdown 学习笔记走 write_file, 正式报告走 office_* (可被
            # office_restore 还原)。不给 office_delete —— 写作职责不含删档。
            tools=[
                "read_file",
                "write_file",
                "memory_search",
                "office_list",
                "office_read",
                "office_create",
                "office_update",
                "office_restore",
            ],
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


# 2026-09-03 (post-PR-#396 subset 迁移): primary 也可直接 fetch/download。
# 保留委派段 (复杂多步研究仍走子代理, 不破 PR #396 coordinator/executor 边界);
# 加一段明确指引 simple fetch/download 可由 primary 直调 —— 用户可见 LLM 行为
# (URL / 文件名), 便于分步指导和交互。OFFLINE 模式下 ToolRegistry 不注册
# web_fetch/http_download, primary 白名单里有也调不到 (NetworkPolicy 门禁)。
PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT = (
    "你是 Sage，一个智能 AI 助手。负责理解用户需求并协调其他 Agent 完成任务。\n\n"
    "你可以直接调用 web_fetch（取网页内容）和 http_download（下载文件到工作区）"
    "进行简单的网页访问/文件下载，让用户能实时看到你访问的 URL 和下载的文件，"
    "便于分步指导和交互。\n"
    "对于复杂的多步研究任务，使用 agent 工具委派给只读子代理执行"
    "（子代理具备 web_search / web_fetch / http_download / memory_search 等只读工具）。"
    "直接回答时不要假装调用了这些工具。"
)


# 2026-09-03: PR #381 把 TerminalTool 重写为 BashTool (name="bash"),
# file_read/file_write 是拼写错位(真实工具名 read_file/write_file)。
# 重命名段遍历所有 agent 的 tools 列表, 按此映射逐元素 in-place 替换;
# 用户额外项一字不动; 幂等(第二次跑不触发 upsert)。
LEGACY_TOOL_NAME_RENAMES: Dict[str, str] = {
    "terminal":   "bash",
    "file_read":  "read_file",
    "file_write": "write_file",
}


# 2026-09-04: 差集兜底段用的"当前默认"列表。既有 4 段迁移用"集合相等"判定,
# 存量 DB 只要落在任何历史快照之外就全部哑炮 —— 差集段兜住所有子集情况。
# primary 不含 bash 是 PR #396 的架构决定(coordinator 不直接执行);
# 变更时手动维护, 与既有 _BEFORE_* 常量同模式。
_PRIMARY_CURRENT_DEFAULT_TOOLS: List[str] = [
    "calculator", "memory_search", "memory_save",
    "list_dir", "read_file",
    "grep_search", "glob_search", "file_summary",
    "agent", "todo_write",
    "web_fetch", "http_download",
    # 2026-09-04: Office CRUD 六件套(含 PR-2 office_restore) —— 与上方白名单同步,
    # 存量 DB 差集段必须带 office_* 才能补齐; 反向约束由
    # test_office_tools_are_in_current_default_constants 锁。
    "office_list", "office_read", "office_create", "office_update", "office_delete",
    "office_restore",
]

_RESEARCHER_CURRENT_DEFAULT_TOOLS: List[str] = [
    "web_search", "web_fetch", "http_download", "memory_search",
]

_WRITER_CURRENT_DEFAULT_TOOLS: List[str] = [
    "read_file", "write_file", "memory_search",
    # 2026-09-04: 写作 agent 的 Office 读写五件套(不给 delete, 给 restore),
    # 与上方 writer.tools 同步。
    "office_list", "office_read", "office_create", "office_update", "office_restore",
]


def _append_missing_tools(agent: Dict[str, Any], current_default_tools: List[str]) -> bool:
    """当前默认集 ⊆ DB 时补齐缺项, 返回是否发生变更。

    只在 DB 缺当前默认项时追加(按 current_default_tools 顺序), 保留 DB 原有
    顺序与用户额外项。真超集 / 完全不相交都会返回 False —— 前者本就齐全,
    后者是用户整体替换过白名单, 不该被默认集"补回来"。
    """
    tools = agent.get("tools") or []
    existing = set(tools)
    missing = [t for t in current_default_tools if t not in existing]
    if not missing:
        return False
    if not (existing & set(current_default_tools)):
        return False
    agent["tools"] = list(tools) + missing
    return True


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
    # 2026-09-03: 工具名重命名迁移(§1)。先于种子补插 + 既有 4 段
    # "集合相等"判定 + subset 兜底段, 让后续所有判定都在重命名后的
    # tools 上运行 (例如 coder 重命名后的 tools 才能与 _BEFORE_* 段比较)。
    # 遍历 create_default_agents() 的默认 ID 集合, 用 repo.get() 拉取再重命名;
    # 不用 list_all() —— 既有 FakeRepo (intranet/todo) 还没实现 list_all(),
    # 走 get() 兼容老测试 mock。
    for default in create_default_agents():
        row = repo.get(default.id)
        if row is None:
            continue
        tools = row.get("tools") or []
        renamed = [LEGACY_TOOL_NAME_RENAMES.get(t, t) for t in tools]
        if renamed != tools:
            row["tools"] = renamed
            repo.upsert(row)
    inserted = 0
    for agent in create_default_agents():
        if repo.get(agent.id) is None:
            repo.upsert(agent.to_dict())
            inserted += 1
    # P0-5 (2026-08-20): 存量 DB primary 升级 —— 旧种子白名单追加 "agent"。
    # 一次 get() 缓存为 primary 局部引用，本函数三段都对它读写（dict 原地变更）。
    # repo.upsert(primary) 后内存与 DB 一致，无需重新 get。三段判定合一个外层 if
    # 满足 ruff SIM102；researcher 升级另起一个 if（变量不同）。
    primary = repo.get("primary")
    if primary is not None:
        # P1 todo 接线 (2026-08-21): 存量 DB 二段升级 —— 旧种子追加 todo_write。
        # 顺序敏感：先 agent 后 todo。两级判定互斥（旧种子集合不含 todo_write、
        # 本段集合含 agent），一段升级后集合恰好等于二段判定集，链式生效；
        # 任意自定义白名单都不匹配任一集合，天然不动。
        tools = primary.get("tools") or []
        if set(tools) == _PRIMARY_TOOLS_BEFORE_AGENT:
            primary["tools"] = tools + ["agent"]
            repo.upsert(primary)
        tools = primary.get("tools") or []
        if set(tools) == _PRIMARY_TOOLS_BEFORE_TODO:
            primary["tools"] = tools + ["todo_write"]
            repo.upsert(primary)
        # 2026-09-03 (PR #396 后置迁移): 存量 DB primary system_prompt 升级。
        # 链式合并：BEFORE_DELEGATION → WITH_DELEGATION → WITH_FETCH_DIRECT。
        # 任一段命中就一气呵成, 合并为单次 upsert 防 updated_at 抖动。
        # 用户自定义 system_prompt（不等于任一旧字符串）→ 全段跳过 → 不动。
        prompt = primary.get("system_prompt")
        if prompt == _PRIMARY_SYSTEM_PROMPT_BEFORE_DELEGATION:
            prompt = PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION
        if prompt == PRIMARY_SYSTEM_PROMPT_WITH_DELEGATION:
            prompt = PRIMARY_SYSTEM_PROMPT_WITH_FETCH_DIRECT
        if prompt != primary.get("system_prompt"):
            primary["system_prompt"] = prompt
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
    # 2026-09-04: 差集兜底 —— 上面的"集合相等"段只覆盖恰好命中历史快照的 DB。
    # 这一段兜住任意子集形状(如 PR-3 时期的 5 工具 primary)。真超集与
    # 完全不相交都不动, 见 _append_missing_tools 的 docstring。
    for agent_id, current_defaults in (
        ("primary", _PRIMARY_CURRENT_DEFAULT_TOOLS),
        ("researcher", _RESEARCHER_CURRENT_DEFAULT_TOOLS),
        ("writer", _WRITER_CURRENT_DEFAULT_TOOLS),
    ):
        row = repo.get(agent_id)
        if row is not None and _append_missing_tools(row, current_defaults):
            repo.upsert(row)
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


#: 默认 system prompt 的工具能力声明——明确告知 LLM 可调用的 Office CRUD
#: 能力，避免其凭训练先验回复"没有创建本地文件的权限"（T6 Electron 实测
#: 暴露）。工具/能力变化时手动维护，与 legacy_routes 的 DIAGRAM_TOOL_PROMPT
#: 同模式。
_OFFICE_CREATE_CAPABILITY_PROMPT = (
    "\n\n你可以对 Office 文档（Word/Excel/PPT）执行增删改查：\n"
    "- 创建：调用 office_create 工具（提供 doc_type / output_dir / filename / 内容结构）。\n"
    "- 查看当前会话工作区里的文档：office_list；读取内容：office_read。\n"
    "- 修改已有文档（原地编辑，按 op 列表执行）：office_update"
    "（用 doc_id 或绝对路径 file_path 定位文件）。\n"
    "- 删除文档（不可恢复）：office_delete（同样支持 doc_id / file_path）。\n"
    "- 归档文档（隐藏但不删）：office_archive；还原被归档文档：office_restore。"
    "office_update 改前会自动把旧版复制到 <managed_dir>/.snapshots/，可作为"
    "「撤销最近一次编辑」路径。"
    "写入或修改工作区外的路径（如桌面）时，用户会看到确认框，批准后才会真正执行。"
)


def build_system_base() -> str:
    """构建 system prompt 基础部分（身份 + 工具能力声明 + agent 列表）。"""
    base = "你是 Sage，一个智能 AI 助手。"
    return base + _OFFICE_CREATE_CAPABILITY_PROMPT + format_agents_for_prompt()

"""
工具系统初始化

提供所有内置工具的注册函数
"""

from typing import Optional

from backend.domain.network_policy import NetworkPolicy
from backend.domain.tool_policy import ToolPolicy

from .agent_tool import AgentTool
from .ask_user_tool import AskUserQuestionTool
from .base import BaseTool, ToolResult, ToolSchema
from .bash_tool import BashOutputTool, BashTool, KillShellTool
from .calculator import CalculatorTool
from .download_tool import HttpDownloadTool
from .edit_tool import EditTool
from .file_summary_tool import FileSummaryTool
from .file_tool import ListDirTool, ReadFileTool, WriteFileTool
from .memory_tool import MemorySaveTool, MemorySearchTool
from .network_config import load_network_policy
from .office_create_tool import OfficeCreateTool
from .office_delete_tool import OfficeDeleteTool
from .office_restore_tool import OfficeRestoreTool
from .office_tool import OfficeListTool, OfficeReadTool
from .office_update_tool import OfficeUpdateTool
from .registry import ToolRegistry
from .repl_tool import ReplTool
from .runtime_exec import RuntimeExecTool
from .runtime_probe import RuntimeProbeTool
from .project_diagnose import ProjectDiagnoseTool
from .search_tools import GlobSearchTool, GrepSearchTool
from .skill import SkillHotLoader
from .skill_tool import SkillTool
from .structured_output_tool import StructuredOutputTool
from .todo_tool import TodoWriteTool
from .web_tool import WebFetchTool, WebSearchTool


def register_all_tools(
    registry: ToolRegistry,
    policy: Optional[ToolPolicy] = None,
    network_policy: Optional[NetworkPolicy] = None,
) -> None:
    """
    注册所有内置工具到注册表

    Args:
        registry: 工具注册表
        policy:   M2 工具策略（缺省 ``ToolPolicy()``）；透传给每个内置工具。
        network_policy: 网络策略；``None`` 时从 settings 读。决定三个出网工具
            是否注册 —— 内网/气隙模式下不注册比返回错误更省 token，因为 LLM
            看到工具就会试（与 ``get_schemas_for_llm`` 隐藏 office 工具同理）。
    """
    policy = policy or ToolPolicy()
    network_policy = network_policy if network_policy is not None else load_network_policy()
    registry.register(BashTool(policy=policy))
    # 后台 shell 生命周期：bash(run_in_background=true) 起的进程由这两个工具
    # 轮询与终止。bash_output 归 READ（只读已捕获输出），kill_shell 归 WRITE。
    registry.register(BashOutputTool(policy=policy))
    registry.register(KillShellTool(policy=policy))
    registry.register(ReadFileTool(policy=policy))
    registry.register(WriteFileTool(policy=policy))
    registry.register(ListDirTool(policy=policy))
    if network_policy.search_enabled():
        registry.register(WebSearchTool(policy=policy))
    if network_policy.fetch_enabled():
        registry.register(WebFetchTool(policy=policy, network_policy=network_policy))
        registry.register(HttpDownloadTool(policy=policy, network_policy=network_policy))
    registry.register(CalculatorTool(policy=policy))
    registry.register(MemorySearchTool(policy=policy))
    registry.register(MemorySaveTool(policy=policy))
    registry.register(OfficeListTool(policy=policy))
    registry.register(OfficeReadTool(policy=policy))
    # T5: office_create —— 任意路径生成 Office 文档，写工作区外由 M1 权限执行器
    # 的 path_boundary_validator 升级为审批（agent._office_boundary_resolver）。
    registry.register(OfficeCreateTool(policy=policy))
    # Office CRUD 补全：office_update（原地编辑）/ office_delete（删除），
    # doc_id 模式走工作区绑定，file_path 模式越界同样由 path_boundary_validator
    # 升级为审批（permissions.make_office_path_boundary 覆盖三个工具）。
    registry.register(OfficeUpdateTool(policy=policy))
    registry.register(OfficeDeleteTool(policy=policy))
    # PR-2: office_restore —— 把 archived_at 抹掉的「还原」工具。
    # requires_tool_context=True (与 office_archive 对称), doc_id 模式唯一。
    # 与 office_update 配合使用可实现"撤销最近一次编辑"（pre-edit snapshot
    # 留在 <managed>/.snapshots/，可由 LLM 通过 read_file + write_file 还原）。
    registry.register(OfficeRestoreTool(policy=policy))
    # M2 agent 工具面扩展（移植 claw-code: edit/glob/grep/todo/structured/repl）
    registry.register(EditTool(policy=policy))
    registry.register(GlobSearchTool(policy=policy))
    registry.register(GrepSearchTool(policy=policy))
    registry.register(TodoWriteTool(policy=policy))
    registry.register(StructuredOutputTool(policy=policy))
    registry.register(ReplTool(policy=policy))
    # 本地开发环境助手（runtime_probe 只读探测 + project_diagnose 静态分析 +
    # runtime_exec 经审批后执行本地运行时）。Python 解释器/Node.js 适配器
    # 由 register_default_adapters() 在进程启动期注入。
    from backend.tools.adapters import register_default_adapters

    register_default_adapters()
    registry.register(RuntimeProbeTool(policy=policy))
    registry.register(ProjectDiagnoseTool(policy=policy))
    registry.register(RuntimeExecTool(policy=policy))
    # M2 part B: in-loop 技能调用（EXECUTE，M1 审批闸口按模式矩阵拦截）
    registry.register(SkillTool(policy=policy))
    # M2 part B: AskUserQuestion（READ，run_loop 分发前特判 + 提问闸口）
    registry.register(AskUserQuestionTool(policy=policy))
    # M5: in-loop sub-agent tool (claw-code execute_agent pattern). The
    # sub-agent itself only ever gets the read-only whitelist — see
    # agent_tool.SUBAGENT_TOOL_WHITELIST.
    registry.register(AgentTool(policy=policy))
    # 2026-08-01: 代码探索工具 - 文件结构摘要（解决大代码库 max_iterations_exceeded）
    registry.register(FileSummaryTool(policy=policy))

    # Register MCP tools (from external MCP servers like draw.io)
    try:
        from backend.mcp import register_mcp_tools

        register_mcp_tools(registry)
    except Exception as exc:
        import logging

        logging.getLogger(__name__).warning(f"Failed to register MCP tools: {exc}")


__all__ = [
    "ToolRegistry",
    "BaseTool",
    "ToolSchema",
    "ToolResult",
    "AgentTool",
    "BashTool",
    "BashOutputTool",
    "KillShellTool",
    "ReadFileTool",
    "WriteFileTool",
    "ListDirTool",
    "WebSearchTool",
    "WebFetchTool",
    "HttpDownloadTool",
    "CalculatorTool",
    "MemorySearchTool",
    "MemorySaveTool",
    "OfficeListTool",
    "OfficeReadTool",
    "OfficeCreateTool",
    "OfficeUpdateTool",
    "OfficeDeleteTool",
    "OfficeRestoreTool",
    "EditTool",
    "GlobSearchTool",
    "GrepSearchTool",
    "TodoWriteTool",
    "StructuredOutputTool",
    "ReplTool",
    "RuntimeProbeTool",
    "RuntimeExecTool",
    "ProjectDiagnoseTool",
    "SkillTool",
    "AskUserQuestionTool",
    "FileSummaryTool",
    "SkillHotLoader",
    "register_all_tools",
]

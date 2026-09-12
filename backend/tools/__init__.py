"""
工具系统初始化

提供所有内置工具的注册函数
"""

from typing import Optional

from backend.domain.network_policy import NetworkPolicy
from backend.domain.tool_policy import ToolPolicy

from .ask_user_tool import AskUserQuestionTool
from .asr_tool import SpeechToTextTool
from .base import BaseTool, ToolResult, ToolSchema
from .bash_tool import BashOutputTool, BashTool, KillShellTool
from .browser_tool import (
    BrowserCloseTool,
    BrowserInteractTool,
    BrowserLaunchTool,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
)
from .calculator import CalculatorTool
from .checkpoint_tool import CheckpointCreateTool, CheckpointListTool, CheckpointRestoreTool
from .codebase_search_tool import CodebaseSearchTool
from .commit_message_tool import GitCommitMessageTool
from .download_tool import HttpDownloadTool
from .edit_tool import EditTool
from .execute_code_tool import ExecuteCodeTool
from .file_summary_tool import FileSummaryTool
from .file_tool import ListDirTool, ReadFileTool, WriteFileTool
from .git_tool import (
    GitBranchTool,
    GitCheckoutTool,
    GitCommitTool,
    GitDiffTool,
    GitLogTool,
    GitStashTool,
    GitStatusTool,
)
from .image_gen_tool import ImageGenerationTool
from .memory_tool import MemorySaveTool, MemorySearchTool
from .network_config import load_network_policy
from .office_analyze_tool import OfficeAnalyzeTool
from .office_archive_tool import OfficeArchiveTool
from .office_bibtex_tool import OfficeBibTexTool
from .office_create_tool import OfficeCreateTool
from .office_delete_tool import OfficeDeleteTool
from .office_journal_tool import (
    OfficeJournalFillFromContentTool,
    OfficeJournalGenerateArticleTool,
    OfficeJournalParseTemplateTool,
    OfficeJournalValidateTool,
)
from .office_lint_tool import OfficeLintWordTool
from .office_pdf_tool import (
    OfficeFillPdfFormTool,
    OfficeGeneratePdfTool,
    OfficeReadPdfFormTool,
    OfficeReadPdfTool,
)
from .office_repair_tool import OfficeRepairWordTool
from .office_restore_tool import OfficeRestoreTool
from .office_template_tool import (
    OfficeAnalyzeWordTemplateTool,
    OfficeFillWordTemplateTool,
)
from .office_tool import OfficeListTool, OfficeReadTool
from .office_update_tool import OfficeUpdateTool
from .patch_tool import ApplyPatchTool
from .project_diagnose import ProjectDiagnoseTool
from .registry import ToolRegistry
from .repl_tool import ReplTool
from .runtime_exec import RuntimeExecTool
from .runtime_probe import RuntimeProbeTool
from .search_tools import GlobSearchTool, GrepSearchTool
from .session_search_tool import SessionSearchTool
from .skill import SkillHotLoader
from .skill_save_tool import SkillSaveTool
from .skill_tool import SkillTool
from .structured_output_tool import StructuredOutputTool
from .symbol_search_tool import SymbolSearchTool
from .todo_tool import TodoWriteTool
from .tts_tool import TextToSpeechTool
from .web_tool import WebFetchTool, WebSearchTool


def __getattr__(name):
    """Lazy attribute access — breaks the ``backend.tools`` circular import.

    ``agent_tool`` is intentionally NOT eagerly imported above. Its module
    pulls in ``backend.orchestration.subagent_events`` which transitively
    reaches ``backend.core.legacy.agent.py:54`` (``from backend.tools
    import ToolRegistry, register_all_tools``) — a back-edge into this
    package before its ``__init__`` finishes binding ``ToolRegistry`` at
    line 42. Python 3.10 silently tolerated the cycle (it returns the
    partially-initialized module); Python 3.11 (used by CI per
    ``.github/workflows/ci.yml`` line 82) raises
    ``ImportError: cannot import name 'ToolRegistry' from partially
    initialized module 'backend.tools'``. Issue #484.

    By deferring ``agent_tool`` to first-attribute-access via PEP 562,
    ``backend.tools.__init__`` finishes binding all public symbols BEFORE
    the back-edge fires; then ``register_all_tools`` (called after the
    package is fully initialised) can safely ``from .agent_tool import
    AgentTool`` at its call site.
    """
    if name == "AgentTool":
        from .agent_tool import AgentTool as _AgentTool

        return _AgentTool
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    """Make ``AgentTool`` discoverable via ``dir(backend.tools)`` and tab
    completion, matching the pre-fix public surface.
    """
    return sorted({*globals().keys(), "AgentTool"})


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
    # Round 2 (session_search): 跨会话对话原文检索（READ 级）
    registry.register(SessionSearchTool(policy=policy))
    # Round 8 (execute_code): 零上下文 RPC 工具调用（EXEC 级，与 bash 同权限面）
    registry.register(ExecuteCodeTool(registry=registry, policy=policy))
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
    # PR-3: office_archive — sets archived_at, paired with office_restore
    # to undo. Symmetric to OfficeRestoreTool (requires_tool_context=True,
    # doc_id 模式 only). Service layer (`tool_service.archive`) already
    # exists from PR-2; this just exposes it as an LLM-callable tool.
    registry.register(OfficeArchiveTool(policy=policy))
    # Office Parity Batch-1: PDF 三类能力（读文本 / 生成 / 表单读写）+
    # Word 模板两件套（分析 / 填充）—— HTTP 端点已验证能力的 LLM 工具面
    # 镜像。读三件 requires_tool_context=True（无绑定自动隐藏），写三件
    # False（file_path 模式，越界由 path boundary / _enforce_workspace 把守）。
    registry.register(OfficeReadPdfTool(policy=policy))
    registry.register(OfficeGeneratePdfTool(policy=policy))
    registry.register(OfficeReadPdfFormTool(policy=policy))
    registry.register(OfficeFillPdfFormTool(policy=policy))
    registry.register(OfficeAnalyzeWordTemplateTool(policy=policy))
    registry.register(OfficeFillWordTemplateTool(policy=policy))
    # Office Parity Batch-2: office_analyze —— pandas 本地数据分析
    # （describe/计数/聚合/相关性，可选分析报告 xlsx）。读类工具
    # requires_tool_context=True（无绑定自动隐藏）；报告只写源文件同目录
    # 的派生文件名，落点不经 LLM 选择。
    registry.register(OfficeAnalyzeTool(policy=policy))
    # 2026-09-10 journal template subsystem: 期刊模板 4 件套
    # （parse_template / fill_from_content / generate_article / validate）。
    # parse/validate 是 READ（docx 解析与 6 类规则校验）；fill/generate 是
    # WRITE_LOCAL（落盘 docx）。全部 requires_tool_context=True。
    registry.register(OfficeJournalParseTemplateTool(policy=policy))
    registry.register(OfficeJournalFillFromContentTool(policy=policy))
    registry.register(OfficeJournalGenerateArticleTool(policy=policy))
    registry.register(OfficeJournalValidateTool(policy=policy))
    # Round 9 引用体系: office_parse_bibtex（READ，BibTeX → ReferenceSpec）
    registry.register(OfficeBibTexTool(policy=policy))
    # Round 10 格式 Linter: office_lint_word（READ，对照 FormatSpec 校验 docx）
    registry.register(OfficeLintWordTool(policy=policy))
    # Round 12 自动修复: office_repair_word（WRITE_LOCAL，lint→修复→复检）
    registry.register(OfficeRepairWordTool(policy=policy))
    # M2 agent 工具面扩展（移植 claw-code: edit/glob/grep/todo/structured/repl）
    registry.register(EditTool(policy=policy))
    registry.register(GlobSearchTool(policy=policy))
    registry.register(GrepSearchTool(policy=policy))
    # F2 (round5 批次 E): 工作区语义检索（embedding 配置就绪时可用）
    registry.register(CodebaseSearchTool(policy=policy))
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
    # Lazy import here (not at module top) — see __getattr__ docstring
    # above for the cycle this avoids. Safe at runtime because this
    # function is only called AFTER backend.tools.__init__ has fully
    # finished, so the back-edge
    # `backend.core.legacy.agent -> backend.tools` resolves cleanly.
    from .agent_tool import AgentTool

    registry.register(AgentTool(policy=policy))
    # 2026-08-01: 代码探索工具 - 文件结构摘要（解决大代码库 max_iterations_exceeded）
    registry.register(FileSummaryTool(policy=policy))
    # 2026-09-06 对标增强 Phase-1: 一等 git 工具组（读三件免审，commit 走
    # WRITE_LOCAL 审批；只 commit 不 push）+ 工作区检查点（create 只写
    # sage 自有数据目录 → READ；restore 覆盖工作区 → WRITE_LOCAL 审批）。
    registry.register(GitBranchTool(policy=policy))
    registry.register(GitCheckoutTool(policy=policy))
    registry.register(GitStashTool(policy=policy))
    registry.register(GitStatusTool(policy=policy))
    registry.register(GitDiffTool(policy=policy))
    registry.register(GitLogTool(policy=policy))
    # G9: commit message 素材工具（READ）—— diff 摘要 + 既有 message 风格
    registry.register(GitCommitMessageTool(policy=policy))
    registry.register(GitCommitTool(policy=policy))
    registry.register(CheckpointCreateTool(policy=policy))
    registry.register(CheckpointListTool(policy=policy))
    registry.register(CheckpointRestoreTool(policy=policy))
    # 2026-09-06 对标增强 Phase-2: apply_patch —— 多文件原子精确编辑
    # （Codex apply_patch 对标；先整体校验后落盘，任一失败整批不写）。
    registry.register(ApplyPatchTool(policy=policy))
    # G4: symbol_search —— 代码库 Python 符号索引（ast 提取定义处，READ）
    registry.register(SymbolSearchTool(policy=policy))
    # G7: 浏览器自动化 —— CDP 驱动本机 Chrome/Edge（launch=EXEC /
    # navigate=EXTERNAL 逐次审批 / snapshot+screenshot=READ / interact+close=WRITE_LOCAL）
    registry.register(BrowserLaunchTool(policy=policy))
    registry.register(BrowserNavigateTool(policy=policy))
    registry.register(BrowserSnapshotTool(policy=policy))
    registry.register(BrowserInteractTool(policy=policy))
    registry.register(BrowserScreenshotTool(policy=policy))
    registry.register(BrowserCloseTool(policy=policy))
    # Academic search skill: 显式触发技能沉淀（WRITE_LOCAL 写本地 SQLite）
    registry.register(SkillSaveTool(policy=policy))

    # Multimodal tools: TTS / ASR / Image Generation
    registry.register(TextToSpeechTool(policy=policy))
    registry.register(SpeechToTextTool(policy=policy))
    registry.register(ImageGenerationTool(policy=policy))

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
    "SessionSearchTool",
    "ExecuteCodeTool",
    "MemorySaveTool",
    "OfficeListTool",
    "OfficeReadTool",
    "OfficeCreateTool",
    "OfficeUpdateTool",
    "OfficeDeleteTool",
    "OfficeRestoreTool",
    "OfficeArchiveTool",
    "OfficeReadPdfTool",
    "OfficeGeneratePdfTool",
    "OfficeReadPdfFormTool",
    "OfficeFillPdfFormTool",
    "OfficeAnalyzeWordTemplateTool",
    "OfficeFillWordTemplateTool",
    "OfficeAnalyzeTool",
    "OfficeBibTexTool",
    "OfficeLintWordTool",
    "OfficeRepairWordTool",
    "OfficeJournalParseTemplateTool",
    "OfficeJournalFillFromContentTool",
    "OfficeJournalGenerateArticleTool",
    "OfficeJournalValidateTool",
    "EditTool",
    "GlobSearchTool",
    "CodebaseSearchTool",
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
    "GitStashTool",
    "GitStatusTool",
    "GitDiffTool",
    "GitLogTool",
    "GitCommitMessageTool",
    "GitBranchTool",
    "GitCheckoutTool",
    "GitCommitTool",
    "CheckpointCreateTool",
    "CheckpointListTool",
    "CheckpointRestoreTool",
    "ApplyPatchTool",
    "SymbolSearchTool",
    "BrowserLaunchTool",
    "BrowserNavigateTool",
    "BrowserSnapshotTool",
    "BrowserInteractTool",
    "BrowserScreenshotTool",
    "BrowserCloseTool",
    "SkillHotLoader",
    "SkillSaveTool",
    "TextToSpeechTool",
    "SpeechToTextTool",
    "ImageGenerationTool",
    "register_all_tools",
]

"""
工具系统初始化

Phase 3 (startup perf): 顶层不再 eager import 全部 ~104 个 tool 子模块
（≈1.9s）。改用 PEP 562 惰性 `__getattr__`：只在属性首次被访问时才导入
对应子模块。`register_all_tools()` 内部已走 `.tool_bundles` 的显式导入，
不依赖包 `__init__` 的 eager 导出。
"""

import logging
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from backend.domain.network_policy import NetworkPolicy
from backend.domain.scheduler import SchedulerServicePort
from backend.domain.tool_policy import ToolPolicy
from backend.services.todo_service import TodoService  # forward-ref for register_all_tools

from .base import BaseTool, ToolResult, ToolSchema
from .network_config import load_network_policy
from .registry import ToolRegistry

# Phase 3 (startup perf): tool 子模块惰性解析映射。
# key: 导出名（类名）；value: 相对子模块路径（`.` 前缀表示 backend.tools.X）。
_LAZY_TOOL_EXPORTS: Dict[str, str] = {
    "ApplyPatchTool": ".patch_tool",
    "AskUserQuestionTool": ".ask_user_tool",
    "BashOutputTool": ".bash_tool",
    "BashTool": ".bash_tool",
    "BrowserCloseTool": ".browser_tool",
    "BrowserCookiesTool": ".browser_tool",
    "BrowserDownloadsTool": ".browser_tool",
    "BrowserInteractTool": ".browser_tool",
    "BrowserLaunchTool": ".browser_tool",
    "BrowserLoginTool": ".browser_tool",
    "BrowserNavigateTool": ".browser_tool",
    "BrowserScreenshotTool": ".browser_tool",
    "BrowserSnapshotTool": ".browser_tool",
    "CancelScheduledTaskTool": ".schedule_tool",
    "CheckpointCreateTool": ".checkpoint_tool",
    "CheckpointListTool": ".checkpoint_tool",
    "CheckpointRestoreTool": ".checkpoint_tool",
    "CodebaseSearchTool": ".codebase_search_tool",
    "DesignExportTool": ".design_export_tool",
    "DesignGenerateTool": ".design_generate_tool",
    "DesignIterateTool": ".design_iterate_tool",
    "DesignListSystemsTool": ".design_list_systems_tool",
    "DesignListTemplatesTool": ".design_list_templates_tool",
    "DownloadCancelTool": ".download_status_tool",
    "DownloadStatusTool": ".download_status_tool",
    "EditTool": ".edit_tool",
    "ExecuteCodeTool": ".execute_code_tool",
    "FileSummaryTool": ".file_summary_tool",
    "GitBranchTool": ".git_tool",
    "GitCheckoutTool": ".git_tool",
    "GitCommitMessageTool": ".commit_message_tool",
    "GitCommitTool": ".git_tool",
    "GitDiffTool": ".git_tool",
    "GitLogTool": ".git_tool",
    "GitStashTool": ".git_tool",
    "GitStatusTool": ".git_tool",
    "GlobSearchTool": ".search_tools",
    "GrepSearchTool": ".search_tools",
    "HttpDownloadTool": ".download_tool",
    "ImageGenerationTool": ".image_gen_tool",
    "KillShellTool": ".bash_tool",
    "ListDirTool": ".file_tool",
    "ListScheduledTasksTool": ".schedule_tool",
    "MemorySaveTool": ".memory_tool",
    "MemorySearchTool": ".memory_tool",
    "OfficeAnalyzeLatexTemplateTool": ".office_latex_template_tool",
    "OfficeAnalyzePptTemplateTool": ".office_ppt_template_tool",
    "OfficeAnalyzeTool": ".office_analyze_tool",
    "OfficeAnalyzeWordTemplateTool": ".office_template_tool",
    "OfficeArchiveTool": ".office_archive_tool",
    "OfficeAuditLatexPdfTool": ".office_latex_pdf_tool",
    "OfficeAuditLatexTool": ".office_latex_audit_tool",
    "OfficeAuditWordTool": ".office_word_intelligence_tools",
    "OfficeBatchAuditTool": ".office_word_intelligence_tools",
    "OfficeBibTexTool": ".office_bibtex_tool",
    "OfficeCheckLatexComplianceTool": ".office_latex_compliance_tool",
    "OfficeCompileLatexTool": ".office_latex_build_tool",
    "OfficeCreateTool": ".office_create_tool",
    "OfficeDeleteTool": ".office_delete_tool",
    "OfficeExtractLatexProjectTool": ".office_latex_project_tool",
    "OfficeExtractRulesTool": ".office_word_intelligence_tools",
    "OfficeFillLatexTemplateTool": ".office_latex_template_tool",
    "OfficeFillPdfFormTool": ".office_pdf_tool",
    "OfficeFillPptTemplateTool": ".office_ppt_template_tool",
    "OfficeFillWordTemplateTool": ".office_template_tool",
    "OfficeFixWordTool": ".office_word_intelligence_tools",
    "OfficeGeneratePdfTool": ".office_pdf_tool",
    "OfficeJournalFillFromContentTool": ".office_journal_tool",
    "OfficeJournalGenerateArticleTool": ".office_journal_tool",
    "OfficeJournalParseTemplateTool": ".office_journal_tool",
    "OfficeJournalValidateTool": ".office_journal_tool",
    "OfficeLatexdiffTool": ".office_latex_build_tool",
    "OfficeLintWordTool": ".office_lint_tool",
    "OfficeListTool": ".office_tool",
    "OfficeReadLatexTool": ".office_latex_tool",
    "OfficeReadPdfFormTool": ".office_pdf_tool",
    "OfficeReadPdfTool": ".office_pdf_tool",
    "OfficeReadTool": ".office_tool",
    "OfficeRefreshTocTool": ".office_toc_refresh_tool",
    "OfficeRenderAuditTool": ".office_word_intelligence_tools",
    "OfficeRepairWordTool": ".office_repair_tool",
    "OfficeRestoreTool": ".office_restore_tool",
    "OfficeReviseWordTool": ".office_word_intelligence_tools",
    "OfficeUpdateTool": ".office_update_tool",
    "ProjectDiagnoseTool": ".project_diagnose",
    "ReadFileTool": ".file_tool",
    "ReadSageConfigTool": ".config_tool",
    "ReplTool": ".repl_tool",
    "RuntimeExecTool": ".runtime_exec",
    "RuntimeProbeTool": ".runtime_probe",
    "ScheduleTaskTool": ".schedule_tool",
    "SessionSearchTool": ".session_search_tool",
    "SkillHotLoader": ".skill",
    "SkillSaveTool": ".skill_save_tool",
    "SkillTool": ".skill_tool",
    "SpeechToTextTool": ".asr_tool",
    "StructuredOutputTool": ".structured_output_tool",
    "SymbolSearchTool": ".symbol_search_tool",
    "TextToSpeechTool": ".tts_tool",
    "TodoWriteTool": ".todo_tool",
    "UpdateSageConfigTool": ".config_tool",
    "WebFetchTool": ".web_tool",
    "WebSearchTool": ".web_tool",
    "WriteFileTool": ".file_tool",
}


def __getattr__(name: str) -> Any:
    """Lazy attribute access — breaks the ``backend.tools`` circular import.

    Phase 3 (startup perf): 104 个 tool 类名走惰性解析（见 _LAZY_TOOL_EXPORTS）。
    AgentTool 因循环依赖保留特殊处理：先尝试普通 lazy 解析，失败则 fallback
    到 `agent_tool` 子模块。
    """
    # AgentTool 因循环依赖特殊处理
    if name == "AgentTool":
        from .agent_tool import AgentTool as _AgentTool

        globals()["AgentTool"] = _AgentTool
        return _AgentTool

    # Phase 3 (startup perf): 其他 tool 类名走惰性解析
    if name in _LAZY_TOOL_EXPORTS:
        from importlib import import_module

        module_path = _LAZY_TOOL_EXPORTS[name]
        # 相对导入：`.xxx_tool` → `backend.tools.xxx_tool`
        full_path = f"backend.tools{module_path}" if module_path.startswith(".") else module_path
        value = getattr(import_module(full_path), name)
        globals()[name] = value
        return value

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> List[str]:
    """Make tool classes discoverable via ``dir(backend.tools)`` and tab
    completion, matching the pre-fix public surface.
    """
    return sorted(set(globals()) | set(__all__))


def _load_harness_safely():
    """加载 R81 harness 配置；任何未预见异常都回退到全量 bundle。

    ``load_harness_config`` 对坏 YAML 本身已 fail-open；这里再包一层，
    是为了让配置子系统的导入/路径等异常也不能阻断最基础的工具装配。
    无任何 ``harness.yaml`` 时结果是 ``standard``，与历史全量顺序一致。
    """
    try:
        from backend.application.kernel.harness_config import load_harness_config

        from .tool_bundles import bundle_names

        workspace = os.environ.get("SAGE_WORKSPACE") or Path.cwd()
        return load_harness_config(workspace=workspace, known_bundles=bundle_names())
    except Exception:  # noqa: BLE001 —— 装配配置永远不能拖垮工具注册
        logging.getLogger(__name__).warning(
            "harness 配置加载失败，回退 standard 全量装配",
            exc_info=True,
        )
        return None


def register_all_tools(
    registry: ToolRegistry,
    policy: Optional[ToolPolicy] = None,
    network_policy: Optional[NetworkPolicy] = None,
    scheduler_service_getter: Optional[Callable[[], Optional[SchedulerServicePort]]] = None,
    todo_service_getter: Optional[Callable[[], Optional[TodoService]]] = None,
) -> None:
    """按 harness 选择结果注册内置工具到注册表。

    R80 把原先 94 条平铺 ``register(...)`` 收编为 31 个具名 bundle；
    R81 进一步以 ``harness.yaml`` 的四预设/三层合并结果筛选 bundle，
    并删除仅用于过渡对照的 legacy 平铺实现。没有配置文件时固定为
    ``standard``，工具集合、顺序、风险声明与 LLM schema 均保持原样。

    Args:
        registry:   工具注册表
        policy:     M2 工具策略（缺省 ``ToolPolicy()``）；透传给每个内置工具。
        network_policy: 网络策略；``None`` 时从 settings 读。决定三个出网工具
            是否注册 —— 内网/气隙模式下不注册比返回错误更省 token。
        scheduler_service_getter: 定时任务服务延迟获取器。
        todo_service_getter: 待办服务延迟获取器。
    """
    policy = policy or ToolPolicy()
    network_policy = network_policy if network_policy is not None else load_network_policy()

    from .tool_bundles import install_default_bundles

    harness = _load_harness_safely()
    report = install_default_bundles(
        registry,
        policy,
        network_policy,
        scheduler_service_getter,
        todo_service_getter,
        harness=harness,
    )
    logging.getLogger(__name__).info(
        "bundle 装配完成（preset=%s）：已注册 %d 个工具，跳过 %d 个 bundle，失败 %d 个",
        getattr(harness, "preset", "standard"),
        len(report.installed),
        len(report.skipped),
        len(report.failed),
    )


__all__ = [
    "AgentTool",
    "ApplyPatchTool",
    "AskUserQuestionTool",
    "BashOutputTool",
    "BashTool",
    "BaseTool",
    "BrowserCloseTool",
    "BrowserCookiesTool",
    "BrowserDownloadsTool",
    "BrowserInteractTool",
    "BrowserLaunchTool",
    "BrowserLoginTool",
    "BrowserNavigateTool",
    "BrowserScreenshotTool",
    "BrowserSnapshotTool",
    "CancelScheduledTaskTool",
    "CheckpointCreateTool",
    "CheckpointListTool",
    "CheckpointRestoreTool",
    "CodebaseSearchTool",
    "DesignExportTool",
    "DesignGenerateTool",
    "DesignIterateTool",
    "DesignListSystemsTool",
    "DesignListTemplatesTool",
    "DownloadCancelTool",
    "DownloadStatusTool",
    "EditTool",
    "ExecuteCodeTool",
    "FileSummaryTool",
    "GitBranchTool",
    "GitCheckoutTool",
    "GitCommitMessageTool",
    "GitCommitTool",
    "GitDiffTool",
    "GitLogTool",
    "GitStashTool",
    "GitStatusTool",
    "GlobSearchTool",
    "GrepSearchTool",
    "HttpDownloadTool",
    "ImageGenerationTool",
    "KillShellTool",
    "ListDirTool",
    "ListScheduledTasksTool",
    "MemorySaveTool",
    "MemorySearchTool",
    "NetworkPolicy",
    "OfficeAnalyzeLatexTemplateTool",
    "OfficeAnalyzePptTemplateTool",
    "OfficeAnalyzeTool",
    "OfficeAnalyzeWordTemplateTool",
    "OfficeArchiveTool",
    "OfficeAuditLatexPdfTool",
    "OfficeAuditLatexTool",
    "OfficeAuditWordTool",
    "OfficeBatchAuditTool",
    "OfficeBibTexTool",
    "OfficeCheckLatexComplianceTool",
    "OfficeCompileLatexTool",
    "OfficeCreateTool",
    "OfficeDeleteTool",
    "OfficeExtractLatexProjectTool",
    "OfficeExtractRulesTool",
    "OfficeFillLatexTemplateTool",
    "OfficeFillPdfFormTool",
    "OfficeFillPptTemplateTool",
    "OfficeFillWordTemplateTool",
    "OfficeFixWordTool",
    "OfficeGeneratePdfTool",
    "OfficeJournalFillFromContentTool",
    "OfficeJournalGenerateArticleTool",
    "OfficeJournalParseTemplateTool",
    "OfficeJournalValidateTool",
    "OfficeLatexdiffTool",
    "OfficeLintWordTool",
    "OfficeListTool",
    "OfficeReadLatexTool",
    "OfficeReadPdfFormTool",
    "OfficeReadPdfTool",
    "OfficeReadTool",
    "OfficeRefreshTocTool",
    "OfficeRenderAuditTool",
    "OfficeRepairWordTool",
    "OfficeRestoreTool",
    "OfficeReviseWordTool",
    "OfficeUpdateTool",
    "ProjectDiagnoseTool",
    "ReadFileTool",
    "ReadSageConfigTool",
    "ReplTool",
    "RuntimeExecTool",
    "RuntimeProbeTool",
    "ScheduleTaskTool",
    "SchedulerServicePort",
    "SessionSearchTool",
    "SkillHotLoader",
    "SkillSaveTool",
    "SkillTool",
    "SpeechToTextTool",
    "StructuredOutputTool",
    "SymbolSearchTool",
    "TextToSpeechTool",
    "TodoService",
    "TodoWriteTool",
    "ToolPolicy",
    "ToolRegistry",
    "ToolResult",
    "ToolSchema",
    "UpdateSageConfigTool",
    "WebFetchTool",
    "WebSearchTool",
    "WriteFileTool",
    "load_network_policy",
    "register_all_tools",
]

"""
工具系统初始化

提供所有内置工具的注册函数
"""

import logging
import os
from pathlib import Path
from typing import Callable, Optional

from backend.domain.network_policy import NetworkPolicy
from backend.domain.scheduler import SchedulerServicePort
from backend.domain.tool_policy import ToolPolicy
from backend.services.todo_service import TodoService  # forward-ref for register_all_tools

from .ask_user_tool import AskUserQuestionTool
from .asr_tool import SpeechToTextTool
from .base import BaseTool, ToolResult, ToolSchema
from .bash_tool import BashOutputTool, BashTool, KillShellTool
from .browser_tool import (
    BrowserCloseTool,
    BrowserCookiesTool,
    BrowserDownloadsTool,
    BrowserInteractTool,
    BrowserLaunchTool,
    BrowserLoginTool,
    BrowserNavigateTool,
    BrowserScreenshotTool,
    BrowserSnapshotTool,
)
from .checkpoint_tool import CheckpointCreateTool, CheckpointListTool, CheckpointRestoreTool
from .codebase_search_tool import CodebaseSearchTool
from .commit_message_tool import GitCommitMessageTool
from .config_tool import ReadSageConfigTool, UpdateSageConfigTool
from .design_export_tool import DesignExportTool
from .design_generate_tool import DesignGenerateTool
from .design_iterate_tool import DesignIterateTool
from .design_list_systems_tool import DesignListSystemsTool
from .design_list_templates_tool import DesignListTemplatesTool
from .download_status_tool import DownloadCancelTool, DownloadStatusTool
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
from .office_ppt_template_tool import (
    OfficeAnalyzePptTemplateTool,
    OfficeFillPptTemplateTool,
)
from .office_repair_tool import OfficeRepairWordTool
from .office_restore_tool import OfficeRestoreTool
from .office_template_tool import (
    OfficeAnalyzeWordTemplateTool,
    OfficeFillWordTemplateTool,
)
from .office_toc_refresh_tool import OfficeRefreshTocTool
from .office_tool import OfficeListTool, OfficeReadTool
from .office_update_tool import OfficeUpdateTool
from .patch_tool import ApplyPatchTool
from .project_diagnose import ProjectDiagnoseTool
from .registry import ToolRegistry
from .repl_tool import ReplTool
from .runtime_exec import RuntimeExecTool
from .runtime_probe import RuntimeProbeTool
from .schedule_tool import (
    CancelScheduledTaskTool,
    ListScheduledTasksTool,
    ScheduleTaskTool,
)
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
    "OfficeAnalyzePptTemplateTool",
    "OfficeFillPptTemplateTool",
    "OfficeAnalyzeTool",
    "OfficeBibTexTool",
    "OfficeLintWordTool",
    "OfficeRepairWordTool",
    "OfficeRefreshTocTool",
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
    "BrowserDownloadsTool",
    "BrowserCloseTool",
    "BrowserLoginTool",
    "SkillHotLoader",
    "SkillSaveTool",
    "TextToSpeechTool",
    "SpeechToTextTool",
    "ImageGenerationTool",
    "ReadSageConfigTool",
    "UpdateSageConfigTool",
    "ScheduleTaskTool",
    "ListScheduledTasksTool",
    "CancelScheduledTaskTool",
    "register_all_tools",
]

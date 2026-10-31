# ruff: noqa: UP006, UP007, UP035
"""内置工具的 bundle 声明（R80）。

本文件是 ``register_all_tools`` 的**声明式镜像**：原先那 94 条平铺的
``registry.register(...)`` 按域切成具名 bundle，**顺序与旧实现逐项对齐** ——
``BUNDLES`` 的排列顺序就是最终注册顺序，任何换位都会让
``test_tool_bundles_parity.py`` 的快照比对失败。

为什么声明放在 ``backend/tools/`` 而不是内核里：内核
（``backend/application/kernel/tool_install.py``）只提供"顺序 / 门控 / 失败
策略 / 报告"这套机制，不认识任何具体工具。清单属于 tools 层的知识，
两边的依赖方向因此保持单向。

import 全部走 ``.子模块``（而不是 ``from backend.tools import ...``）：
后者在包 ``__init__`` 尚未执行完时是循环，前者不会。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from backend.application.kernel.harness_config import HarnessConfig, select_bundles
from backend.application.kernel.tool_install import (
    InstallReport,
    ToolBundle,
    ToolInstallContext,
    install_bundles,
)

from .ask_user_tool import AskUserQuestionTool
from .asr_tool import SpeechToTextTool
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
from .config_tool import DiagnoseSageConfigTool, ReadSageConfigTool, UpdateSageConfigTool
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
from .ocr_image_tool import OcrImageTool
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
from .skill_save_tool import SkillSaveTool
from .skill_tool import SkillTool
from .structured_output_tool import StructuredOutputTool
from .symbol_search_tool import SymbolSearchTool
from .todo_tool import TodoWriteTool
from .tts_tool import TextToSpeechTool
from .web_tool import WebFetchTool, WebSearchTool

# ===== 安装函数：每个函数体内部的顺序即该 bundle 的注册顺序 =====


def _install_shell(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    ctx.registry.register(BashTool(policy=policy))
    # 后台 shell 生命周期：bash(run_in_background=true) 起的进程由这两个工具
    # 轮询与终止。bash_output 归 READ（只读已捕获输出），kill_shell 归 WRITE。
    ctx.registry.register(BashOutputTool(policy=policy))
    ctx.registry.register(KillShellTool(policy=policy))


def _install_file(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    ctx.registry.register(ReadFileTool(policy=policy))
    ctx.registry.register(WriteFileTool(policy=policy))
    ctx.registry.register(ListDirTool(policy=policy))


def _install_web_search(ctx: ToolInstallContext) -> None:
    ctx.registry.register(WebSearchTool(policy=ctx.policy))


def _install_web_fetch(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    network_policy = ctx.network_policy
    ctx.registry.register(WebFetchTool(policy=policy, network_policy=network_policy))
    ctx.registry.register(HttpDownloadTool(policy=policy, network_policy=network_policy))
    # DL2 (Round 21): 后台下载任务查询/取消（与 http_download 同权限面）
    ctx.registry.register(DownloadStatusTool())
    ctx.registry.register(DownloadCancelTool())


def _install_memory(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    ctx.registry.register(MemorySearchTool(policy=policy))
    # Round 2 (session_search): 跨会话对话原文检索（READ 级）
    ctx.registry.register(SessionSearchTool(policy=policy))


def _install_code_exec(ctx: ToolInstallContext) -> None:
    # Round 8 (execute_code): 零上下文 RPC 工具调用（EXEC 级，与 bash 同权限面）
    ctx.registry.register(ExecuteCodeTool(registry=ctx.registry, policy=ctx.policy))


def _install_memory_write(ctx: ToolInstallContext) -> None:
    ctx.registry.register(MemorySaveTool(policy=ctx.policy))


def _install_office_core(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    ctx.registry.register(OfficeListTool(policy=policy))
    ctx.registry.register(OfficeReadTool(policy=policy))
    # T5: office_create —— 任意路径生成 Office 文档，写工作区外由 M1 权限执行器
    # 的 path_boundary_validator 升级为审批（agent._office_boundary_resolver）。
    ctx.registry.register(OfficeCreateTool(policy=policy))
    # Office CRUD 补全：office_update（原地编辑）/ office_delete（删除），
    # doc_id 模式走工作区绑定，file_path 模式越界同样由 path_boundary_validator
    # 升级为审批（permissions.make_office_path_boundary 覆盖三个工具）。
    ctx.registry.register(OfficeUpdateTool(policy=policy))
    ctx.registry.register(OfficeDeleteTool(policy=policy))
    # PR-2: office_restore —— 把 archived_at 抹掉的「还原」工具。
    ctx.registry.register(OfficeRestoreTool(policy=policy))
    # PR-3: office_archive —— 与 office_restore 成对，撤销最近一次归档。
    ctx.registry.register(OfficeArchiveTool(policy=policy))


def _install_office_pdf(ctx: ToolInstallContext) -> None:
    # Office Parity Batch-1: PDF 三类能力（读文本 / 生成 / 表单读写）。
    policy = ctx.policy
    ctx.registry.register(OfficeReadPdfTool(policy=policy))
    ctx.registry.register(OfficeGeneratePdfTool(policy=policy))
    ctx.registry.register(OfficeReadPdfFormTool(policy=policy))
    ctx.registry.register(OfficeFillPdfFormTool(policy=policy))


def _install_office_template(ctx: ToolInstallContext) -> None:
    # Word / PPT 模板两件套：analyze 枚举版式（READ，无绑定隐藏）；
    # fill 以模板副本另存新文件（WRITE_LOCAL，file_path 模式始终可见）。
    policy = ctx.policy
    ctx.registry.register(OfficeAnalyzeWordTemplateTool(policy=policy))
    ctx.registry.register(OfficeFillWordTemplateTool(policy=policy))
    ctx.registry.register(OfficeAnalyzePptTemplateTool(policy=policy))
    ctx.registry.register(OfficeFillPptTemplateTool(policy=policy))


def _install_office_analysis(ctx: ToolInstallContext) -> None:
    # Office Parity Batch-2: office_analyze —— pandas 本地数据分析。
    ctx.registry.register(OfficeAnalyzeTool(policy=ctx.policy))


def _install_office_journal(ctx: ToolInstallContext) -> None:
    # 2026-09-10 journal template subsystem: 期刊模板 4 件套。
    policy = ctx.policy
    ctx.registry.register(OfficeJournalParseTemplateTool(policy=policy))
    ctx.registry.register(OfficeJournalFillFromContentTool(policy=policy))
    ctx.registry.register(OfficeJournalGenerateArticleTool(policy=policy))
    ctx.registry.register(OfficeJournalValidateTool(policy=policy))


def _install_office_quality(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    # Round 9 引用体系 / Round 10 格式 Linter / Round 12 自动修复 / Round 39 目录页码
    ctx.registry.register(OfficeBibTexTool(policy=policy))
    ctx.registry.register(OfficeLintWordTool(policy=policy))
    ctx.registry.register(OfficeRepairWordTool(policy=policy))
    ctx.registry.register(OfficeRefreshTocTool(policy=policy))


def _install_edit_search(ctx: ToolInstallContext) -> None:
    # M2 agent 工具面扩展（移植 claw-code: edit/glob/grep）
    policy = ctx.policy
    ctx.registry.register(EditTool(policy=policy))
    ctx.registry.register(GlobSearchTool(policy=policy))
    ctx.registry.register(GrepSearchTool(policy=policy))


def _install_agent_surface(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    # F2 (round5 批次 E): 工作区语义检索
    ctx.registry.register(CodebaseSearchTool(policy=policy))
    ctx.registry.register(TodoWriteTool(policy=policy))
    ctx.registry.register(StructuredOutputTool(policy=policy))
    ctx.registry.register(ReplTool(policy=policy))


def _install_runtime(ctx: ToolInstallContext) -> None:
    # 本地开发环境助手：Python 解释器/Node.js 适配器由 register_default_adapters()
    # 在进程启动期注入 —— 必须在 RuntimeProbeTool 之前调用。
    from .adapters import register_default_adapters

    register_default_adapters()
    policy = ctx.policy
    ctx.registry.register(RuntimeProbeTool(policy=policy))
    ctx.registry.register(ProjectDiagnoseTool(policy=policy))
    ctx.registry.register(RuntimeExecTool(policy=policy))


def _install_skill(ctx: ToolInstallContext) -> None:
    # M2 part B: in-loop 技能调用（EXECUTE，M1 审批闸口按模式矩阵拦截）
    ctx.registry.register(SkillTool(policy=ctx.policy))


def _install_ask_user(ctx: ToolInstallContext) -> None:
    # M2 part B: AskUserQuestion（READ，run_loop 分发前特判 + 提问闸口）
    ctx.registry.register(AskUserQuestionTool(policy=ctx.policy))


def _install_subagent(ctx: ToolInstallContext) -> None:
    # M5: in-loop sub-agent tool。延迟 import 是必需的：``agent_tool`` 反向
    # 依赖 ``backend.core.legacy.agent`` → ``backend.tools``，模块级 import
    # 会在包尚未完成绑定时触发 ImportError（issue #484，Python 3.11）。
    from .agent_tool import AgentTool

    ctx.registry.register(AgentTool(policy=ctx.policy))


def _install_file_summary(ctx: ToolInstallContext) -> None:
    # 2026-08-01: 代码探索工具 - 文件结构摘要
    ctx.registry.register(FileSummaryTool(policy=ctx.policy))


def _install_git(ctx: ToolInstallContext) -> None:
    # 2026-09-06 对标增强 Phase-1: 一等 git 工具组（读三件免审，commit 走审批）
    policy = ctx.policy
    ctx.registry.register(GitBranchTool(policy=policy))
    ctx.registry.register(GitCheckoutTool(policy=policy))
    ctx.registry.register(GitStashTool(policy=policy))
    ctx.registry.register(GitStatusTool(policy=policy))
    ctx.registry.register(GitDiffTool(policy=policy))
    ctx.registry.register(GitLogTool(policy=policy))
    # G9: commit message 素材工具（READ）
    ctx.registry.register(GitCommitMessageTool(policy=policy))
    ctx.registry.register(GitCommitTool(policy=policy))


def _install_checkpoint(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    ctx.registry.register(CheckpointCreateTool(policy=policy))
    ctx.registry.register(CheckpointListTool(policy=policy))
    ctx.registry.register(CheckpointRestoreTool(policy=policy))
    # 2026-09-06 对标增强 Phase-2: apply_patch —— 多文件原子精确编辑
    ctx.registry.register(ApplyPatchTool(policy=policy))


def _install_symbol_search(ctx: ToolInstallContext) -> None:
    # G4: symbol_search —— 代码库 Python 符号索引（ast 提取定义处，READ）
    ctx.registry.register(SymbolSearchTool(policy=ctx.policy))


def _install_browser(ctx: ToolInstallContext) -> None:
    # G7: 浏览器自动化 —— CDP 驱动本机 Chrome/Edge
    policy = ctx.policy
    ctx.registry.register(BrowserLaunchTool(policy=policy))
    ctx.registry.register(BrowserNavigateTool(policy=policy))
    ctx.registry.register(BrowserSnapshotTool(policy=policy))
    ctx.registry.register(BrowserInteractTool(policy=policy))
    ctx.registry.register(BrowserScreenshotTool(policy=policy))
    # cookie 桥：导出/管理站点 cookie 凭据档案（WRITE_LOCAL，加密落库）
    ctx.registry.register(BrowserCookiesTool(policy=policy))
    # Round 5 SN3：浏览器内下载跟踪（READ，读事件通道状态表）
    ctx.registry.register(BrowserDownloadsTool(policy=policy))
    ctx.registry.register(BrowserCloseTool(policy=policy))
    # 一键登录：打开可见浏览器 → 用户登录 → 自动保存 cookie（EXTERNAL，blocking）
    ctx.registry.register(BrowserLoginTool(policy=policy))


def _install_skill_save(ctx: ToolInstallContext) -> None:
    # Academic search skill: 显式触发技能沉淀（WRITE_LOCAL 写本地 SQLite）
    ctx.registry.register(SkillSaveTool(policy=ctx.policy))


def _install_multimodal(ctx: ToolInstallContext) -> None:
    policy = ctx.policy
    ctx.registry.register(TextToSpeechTool(policy=policy))
    ctx.registry.register(SpeechToTextTool(policy=policy))
    ctx.registry.register(ImageGenerationTool(policy=policy))
    # 本地 OCR（READ，本地推理；无引擎时 execute 返回可读失败）
    ctx.registry.register(OcrImageTool(policy=policy))


def _install_sage_config(ctx: ToolInstallContext) -> None:
    # read_sage_config 为 READ，update_sage_config 为 WRITE_LOCAL，
    # diagnose_sage_config 为 READ（P119 Config Advisor Phase 2.2）。
    policy = ctx.policy
    ctx.registry.register(ReadSageConfigTool(policy=policy))
    ctx.registry.register(UpdateSageConfigTool(policy=policy))
    ctx.registry.register(DiagnoseSageConfigTool(policy=policy))


def _install_schedule(ctx: ToolInstallContext) -> None:
    # 定时任务派发工具：list 为 READ；schedule / cancel 为 WRITE_LOCAL。
    policy = ctx.policy
    getter = ctx.scheduler_service_getter
    ctx.registry.register(ScheduleTaskTool(policy=policy, service_getter=getter))
    ctx.registry.register(ListScheduledTasksTool(policy=policy, service_getter=getter))
    ctx.registry.register(CancelScheduledTaskTool(policy=policy, service_getter=getter))


def _install_mcp(ctx: ToolInstallContext) -> None:
    # 外部 MCP 服务器（如 draw.io）注册。``critical=False`` 于声明处指定：
    # 注册失败只告警，不拖垮启动 —— 与旧实现的 try/except 等价。
    from backend.mcp import register_mcp_tools

    register_mcp_tools(ctx.registry)


def _install_plugins(ctx: ToolInstallContext) -> None:
    # R90: 只同步用户已显式 start 的进程外插件 tool；这里绝不启动进程。
    # ``critical=False`` 于声明处指定：动态桥接失败不拖垮内置工具装配。
    from backend.plugins.tool_bridge import register_plugin_tools

    register_plugin_tools(ctx.registry)


def _install_todo(ctx: ToolInstallContext) -> None:
    # Todo 持久化管理工具（Task 5-13）：依赖 TodoService（service-getter 延迟解析）。
    from .todo_mgmt_tool import (
        AddTodoTool,
        CompleteTodoTool,
        DeleteTodoTool,
        ListTodosTool,
        UpdateTodoTool,
    )

    policy = ctx.policy
    getter = ctx.todo_service_getter
    ctx.registry.register(AddTodoTool(todo_service_getter=getter, policy=policy))
    ctx.registry.register(ListTodosTool(todo_service_getter=getter, policy=policy))
    ctx.registry.register(CompleteTodoTool(todo_service_getter=getter, policy=policy))
    ctx.registry.register(UpdateTodoTool(todo_service_getter=getter, policy=policy))
    ctx.registry.register(DeleteTodoTool(todo_service_getter=getter, policy=policy))


def _install_design(ctx: ToolInstallContext) -> None:
    # Design Studio tools (Task 13): HTML/CSS 原型与演示文稿生成。
    policy = ctx.policy
    ctx.registry.register(DesignListSystemsTool(policy=policy))
    ctx.registry.register(DesignListTemplatesTool(policy=policy))
    ctx.registry.register(DesignGenerateTool(policy=policy))
    ctx.registry.register(DesignIterateTool(policy=policy))
    ctx.registry.register(DesignExportTool(policy=policy))


#: 内置工具的完整清单。**顺序即注册顺序**，与 R80 之前的平铺实现逐项对齐。
BUNDLES: Tuple[ToolBundle, ...] = (
    ToolBundle("shell", _install_shell),
    ToolBundle("file", _install_file),
    ToolBundle("web_search", _install_web_search, requires=("network.search",)),
    ToolBundle("web_fetch", _install_web_fetch, requires=("network.fetch",)),
    ToolBundle("memory", _install_memory),
    ToolBundle("code_exec", _install_code_exec),
    ToolBundle("memory_write", _install_memory_write),
    ToolBundle("office_core", _install_office_core),
    ToolBundle("office_pdf", _install_office_pdf),
    ToolBundle("office_template", _install_office_template),
    ToolBundle("office_analysis", _install_office_analysis),
    ToolBundle("office_journal", _install_office_journal),
    ToolBundle("office_quality", _install_office_quality),
    ToolBundle("edit_search", _install_edit_search),
    ToolBundle("agent_surface", _install_agent_surface),
    ToolBundle("runtime", _install_runtime),
    ToolBundle("skill", _install_skill),
    ToolBundle("ask_user", _install_ask_user),
    ToolBundle("subagent", _install_subagent),
    ToolBundle("file_summary", _install_file_summary),
    ToolBundle("git", _install_git),
    ToolBundle("checkpoint", _install_checkpoint),
    ToolBundle("symbol_search", _install_symbol_search),
    ToolBundle("browser", _install_browser),
    ToolBundle("skill_save", _install_skill_save),
    ToolBundle("multimodal", _install_multimodal),
    ToolBundle("sage_config", _install_sage_config),
    ToolBundle("schedule", _install_schedule),
    ToolBundle("mcp", _install_mcp, critical=False),
    ToolBundle("plugins", _install_plugins, critical=False),
    ToolBundle("todo", _install_todo),
    ToolBundle("design", _install_design),
)


def bundle_names() -> Tuple[str, ...]:
    """内置 bundle 名清单（顺序与 :data:`BUNDLES` 一致）。"""
    return tuple(bundle.name for bundle in BUNDLES)


def select_bundle_objects(
    config: Optional[HarnessConfig],
) -> Tuple[ToolBundle, ...]:
    """按 R81 harness 选择结果筛出 bundle 对象，并保持声明顺序。"""
    if config is None:
        return BUNDLES
    selected = set(select_bundles(bundle_names(), config))
    return tuple(bundle for bundle in BUNDLES if bundle.name in selected)


def build_context(
    registry: Any,
    policy: Any,
    network_policy: Any,
    scheduler_service_getter: Any = None,
    todo_service_getter: Any = None,
) -> ToolInstallContext:
    """按 ``register_all_tools`` 的入参构造安装上下文（含能力表）。"""
    capabilities: Dict[str, bool] = {
        "network.search": bool(network_policy.search_enabled()),
        "network.fetch": bool(network_policy.fetch_enabled()),
    }
    return ToolInstallContext(
        registry=registry,
        policy=policy,
        network_policy=network_policy,
        scheduler_service_getter=scheduler_service_getter,
        todo_service_getter=todo_service_getter,
        capabilities=capabilities,
    )


def install_default_bundles(
    registry: Any,
    policy: Any,
    network_policy: Any,
    scheduler_service_getter: Any = None,
    todo_service_getter: Any = None,
    *,
    harness: Optional[HarnessConfig] = None,
    strict: bool = True,
) -> InstallReport:
    """按可选 harness 选择安装内置工具，返回 :class:`InstallReport`。

    ``harness=None`` 表示全量安装；这是无配置文件以及配置加载兜底时
    的行为。传入 :class:`HarnessConfig` 时只筛 bundle，不改变 bundle
    内部的工具顺序或网络能力门控。
    """
    ctx = build_context(
        registry, policy, network_policy, scheduler_service_getter, todo_service_getter
    )
    return install_bundles(ctx, select_bundle_objects(harness), strict=strict)

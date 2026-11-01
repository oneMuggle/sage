"""内置工具名的单一来源（防漂移）。

历史教训：profiles.py 曾以字符串字面量引用工具名，两次漂移都到运行期
才暴露 —— 旧名 ``terminal``（工具已改名 ``bash``，PR #381）与拼写错位
``file_read`` / ``file_write``（真实名 read_file / write_file，PR #402
/#404 修复），表现为 UI 选 coder 后 LLM 工具面近乎为空。

本模块是 backend 内置工具名的唯一定义点：

- profiles.py 的种子白名单与 ``EXEC_TOOLS`` 三件套约束从这里组合；
- 启动期校验（main.py lifespan → ``profiles.validate_profile_tools``）
  以 ``ALL_BUILTIN_TOOL_NAMES`` 为已知名集合。

放在 domain 层而非 tools/ 包：``from backend.tools.names import ...``
会先执行 tools 包的 ``__init__``（eager import 全部工具模块，httpx 等
重依赖）；domain 层仅标准库，application（agents/profiles）与 adapters
（tools/__init__.py）都能向内安全引用，模式同 domain/risk.py。

清单语义 = ``register_all_tools`` 的静态注册面。``web_search`` /
``web_fetch`` / ``http_download`` 的注册与否受 NetworkPolicy 门禁，
但名字恒为已知 —— 校验不受网络模式影响。

不在清单内的名字（引用它们的白名单会收到启动告警，仅告警不剔除）：
- ``wiki_search`` / ``wiki_answer``：定义于 tools/wiki_tool.py，当前未注册；
- ``dispatch_subagents`` / ``collect_subagents`` / ``observe_subagents``：
  legacy_routes 编排模式下按会话动态注册；
- ``update_pending_task`` / ``cancel_pending_task`` / ``add_task_to_plan``：
  同上（re-plan 工具族，tools/replan_tool.py，与 dispatch 同一 tool-toggle 门）；
- MCP 工具：外部服务器运行期提供，命名 ``mcp__<server>__<tool>``；
  合法形状的引用（精确名与 ``mcp__*`` / ``mcp__<server>__*`` 通配）
  由本模块下方识别，启动期校验不告警。
- 进程外插件工具（R90）：动态名字 ``plugin__<plugin>__<capability>``
  不在内置清单内；其命名空间前缀、形状识别与 profile 白名单匹配
  （含 R92 受限通配）定义于本模块下方，启动期校验把合法形状的插件
  引用视为已知动态引用，不告警。
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

# 执行三件套：bash 起进程（run_in_background=true 返回 shell_id），
# bash_output 轮询输出，kill_shell 终止。暴露 bash 的白名单必须三件
# 齐备 —— 缺后两件时后台 shell 无法轮询/终止，成为孤儿进程直至退出清理。
EXEC_TOOLS = ("bash", "bash_output", "kill_shell")

# 文件读写与目录（EditTool 的 schema 名是 edit_file）
FILE_TOOLS = ("read_file", "write_file", "list_dir", "edit_file")

# 代码探索三件套（全部 READ，无副作用风险）
CODE_SEARCH_TOOLS = ("grep_search", "glob_search", "file_summary", "codebase_search")

# 出网工具
WEB_SEARCH_TOOLS = ("web_search",)
WEB_FETCH_TOOLS = ("web_fetch", "http_download")
# DL2 (Round 21): 后台下载任务查询/取消（与 http_download 同权限面）
WEB_DL_JOBS_TOOLS = ("download_status", "download_cancel")
WEB_TOOLS = WEB_SEARCH_TOOLS + WEB_FETCH_TOOLS + WEB_DL_JOBS_TOOLS

MEMORY_TOOLS = ("memory_search", "memory_save")

# Round 2 (session_search): 跨会话历史对话原文检索 —— 记忆库存抽取条目，
# 本工具补原始对话的检索入口（对标 hermes session search）。
SESSION_SEARCH_TOOLS = ("session_search",)

# Office CRUD 七件套（PR-3 补 office_archive — soft-delete，与 office_restore 配对）
# + 2026-09 Office Parity Batch-1：把 HTTP 端点已验证的 PDF 三类能力
# （读文本 / 生成 / 表单读写）与 Word 模板两件套（分析 / 填充）接入工具面。
# + 2026-09 Office Parity Batch-2：office_analyze —— pandas 本地数据分析
# （describe/计数/聚合/相关性，可生成分析报告 xlsx）。
OFFICE_TOOLS = (
    "office_list",
    "office_read",
    "office_create",
    "office_update",
    "office_delete",
    "office_restore",
    "office_archive",
    "office_read_pdf",
    "office_generate_pdf",
    "office_read_pdf_form",
    "office_fill_pdf_form",
    "office_analyze_word_template",
    "office_fill_word_template",
    # 2026-09-18 PPT 模板两件套（office-p5a HTTP 能力的 LLM 工具面镜像）：
    # analyze 枚举版式/占位符（READ）；fill 以模板副本另存新 .pptx（WRITE_LOCAL）。
    "office_analyze_ppt_template",
    "office_fill_ppt_template",
    "office_analyze",
    # 2026-09-11 Round 9 引用体系：BibTeX 解析（READ，纯文本、无工作区依赖）
    "office_parse_bibtex",
    # 2026-09-11 Round 10 格式 Linter：对照 FormatSpec 校验 docx（READ）
    "office_lint_word",
    # 2026-11-01 M6 规则包工具：审校/修复/抽取/修订
    "office_audit_word",
    "office_fix_word",
    "office_extract_rules",
    "office_revise_word",
    # 2026-10-31 LaTeX 读取：.tex 项目 → 结构化预览（READ，不编译 TeX）
    "office_read_latex",
    # 2026-10-31 LaTeX 模板：槽位/样式分析（READ）与填充（WRITE_LOCAL）
    "office_analyze_latex_template",
    "office_fill_latex_template",
    # 2026-10-31 LaTeX 源码审校（READ）
    "office_audit_latex",
    # 2026-10-31 PDF 版式/字体/DPI 审计（READ，不修改 PDF）
    "office_audit_latex_pdf",
    # 2026-10-31 投稿合规检查：源码 + 可选 PDF（READ）
    "office_check_latex_compliance",
    # 2026-10-31 LaTeX 可选编译 / 红字版（WRITE_LOCAL）
    "office_compile_latex",
    "office_latexdiff",
    # 2026-10-31 LaTeX 项目 zip 导入（WRITE_LOCAL，安全解压）
    "office_extract_latex_project",
    # 2026-09-12 Round 12 自动修复：lint→修复→复检（WRITE_LOCAL）
    "office_repair_word",
    # 2026-09-18 Round 39 目录真页码：Word COM 刷新 TOC 域（WRITE_LOCAL，
    # 可选通道——需本机 Word + pywin32，缺失时降级为可读理由）
    "office_refresh_toc",
)

# 本地开发环境助手（2026-09-04）：只读探测/诊断两件 + 审批后执行一件。
# primary 只拿 PROBE 两件（READ 类，coordinator 边界）；coder 三件全拿。
RUNTIME_PROBE_TOOLS = ("runtime_probe", "project_diagnose")
RUNTIME_EXEC_TOOLS = ("runtime_exec",)
RUNTIME_TOOLS = RUNTIME_PROBE_TOOLS + RUNTIME_EXEC_TOOLS

# 2026-09-10 期刊模板子系统（journal template）：4 件套（parse / fill / generate / validate）。
# parse 与 validate 是 READ；fill 与 generate 是 WRITE_LOCAL（落盘 docx）。
# 全部 requires_tool_context=True（工作区绑定是路径围栏的根）。
JOURNAL_TOOLS = (
    "office_journal_parse_template",
    "office_journal_fill_from_content",
    "office_journal_generate_article",
    "office_journal_validate",
)

# 一等 git 工具组（2026-09-06 对标增强 Phase-1）：读四件 READ 免审
# （commit_message 为提交素材只读辅助），git_commit 为 WRITE_LOCAL 审批；
# 只 commit 不 push。
GIT_TOOLS = (
    "git_branch",
    "git_checkout",
    "git_commit",
    "git_commit_message",
    "git_diff",
    "git_log",
    "git_stash",
    "git_status",
)

# 工作区检查点（2026-09-06 对标增强 Phase-1）：create/list 只写 sage
# 自有数据目录 → READ；restore 覆盖工作区 → WRITE_LOCAL 审批。
CHECKPOINT_TOOLS = ("checkpoint_create", "checkpoint_list", "checkpoint_restore")

# 多文件原子编辑（2026-09-06 对标增强 Phase-2，Codex apply_patch 对标）：
# 全部补丁先校验后落盘，任一失败整批不写。WRITE_LOCAL 审批。
PATCH_TOOLS = ("apply_patch",)

# 代码库符号索引（2026-09-06 对标增强 Phase-2，G4 务实版）：
# stdlib ast 提取 Python 符号 + 内存倒排索引，按名称/概念搜定义处。READ。
SYMBOL_TOOLS = ("symbol_search",)

# 浏览器自动化（2026-09-06 对标增强 G7）：CDP 驱动本机 Chrome/Edge。
# launch=EXEC / navigate=EXTERNAL（逐次审批）/ snapshot+screenshot=READ /
# interact+close+cookies=WRITE_LOCAL / downloads=READ / login=EXTERNAL（blocking）。
# v1 只给 coder（executor 边界）。
BROWSER_TOOLS = (
    "browser_launch",
    "browser_navigate",
    "browser_snapshot",
    "browser_interact",
    "browser_screenshot",
    "browser_cookies",
    "browser_downloads",
    "browser_close",
    "browser_login",
)

# 技能类（2026-09 academic-search M1）：``skill`` 是循环内调用已有 skill
# （EXECUTE，M1 审批闸口按模式矩阵拦截），``skill_save`` 是显式把跑通的
# 工具调用序列沉淀为 SQLite 草稿（WRITE_LOCAL 写本地文件）。两者都通过
# 启动期白名单校验防止 profile 漂移。
SKILL_TOOLS = ("skill", "skill_save")

# 多模态工具（2026-09-12 multimodal capabilities）：TTS 文本转语音 /
# ASR 语音识别 / 图像生成。全部 EXTERNAL（调用外部 API），requires_tool_context=True。
# 2026-10-31 本地 OCR：ocr_image 为 READ（本地推理，不调用外部 API）。
MULTIMODAL_TOOLS = (
    "text_to_speech",
    "speech_to_text",
    "generate_image",
    "ocr_image",
)

# 循环内编排：子代理委派 / 任务清单 / 结构化输出 / 用户提问
ORCH_TOOLS = ("agent", "todo_write", "structured_output", "ask_user_question")

# Round 8: execute_code —— 子进程 RPC 工具调用（EXEC 级权限面与 bash 等同）
SANDBOX_TOOLS = ("repl", "execute_code")

# 系统自省与配置（2026-09-18 feat/agents-entry-config-query）：
# ``read_sage_config`` READ 自动放行，``update_sage_config`` WRITE_LOCAL 走权限审批。
# 仅赋给 primary 主助手；子代理白名单严禁纳入，防止自我提权或篡改凭证。
# 字段白名单由工具实现内部维护，这里只登记名称。
CONFIG_TOOLS = ("read_sage_config", "update_sage_config", "diagnose_sage_config")

# 定时任务派发（2026-09-19 feat/llm-schedule-tool）：把既有的 SchedulerService
# （APScheduler + JSON 持久化）暴露给 LLM —— 此前只能经 REST API 由前端 UI 创建。
# ``list_scheduled_tasks`` READ 自动放行；``schedule_task`` / ``cancel_scheduled_task``
# WRITE_LOCAL 走权限审批（持久化副作用 + 未来向会话注入消息）。
# 仅赋给 primary 主助手；子代理白名单严禁纳入 —— 防止被委派的子任务自行注册
# 长期定时行为（与 CONFIG_TOOLS 同样的 coordinator-only 边界）。
SCHEDULE_TOOLS = ("schedule_task", "list_scheduled_tasks", "cancel_scheduled_task")

# 待办子系统（2026-09-21 todolist-subsystem）：五个 LLM 工具面（add / list /
# update / complete / delete），均挂 TodoService（SQLite 持久化 + 会话 ID
# 隔离）。与 SCHEDULE_TOOLS 同模式：工具无条件注册（对 LLM 可见），
# ``todo_service_getter`` 在执行期解析 service 是否就绪。
# ``add_todo`` / ``update_todo`` 为 WRITE_LOCAL（持久化副作用）；
# ``list_todos`` / ``complete_todo`` / ``delete_todo`` 也均为 WRITE_LOCAL
# （完成/删除同样改 SQLite）。ToolPolicy 层会按风险分级处理。
TODO_TOOLS = ("add_todo", "list_todos", "update_todo", "complete_todo", "delete_todo")

# Design Studio 工具面（2026-10-13 OpenDesign 集成 Task 13）：五件套。
# 两个目录查询件（list_systems / list_templates）为 READ；三个产件
# （generate / iterate / export）为 WRITE_LOCAL —— generate/iterate 写
# design_projects + design_artifacts 两张 SQLite 表并在工作区落 HTML；
# export 只读回最新产物内容，仍按产件族归 WRITE_LOCAL 以便审批闸口
# 覆盖「把生成物交出工作区」这一动作。
# 全部无条件注册；``get_design_studio()`` 在执行期解析 studio 是否就绪
# （未就绪时返回 design_studio_not_initialized，不静默缺工具）——
# 与 SCHEDULE_TOOLS / TODO_TOOLS 同模式。
DESIGN_TOOLS = (
    "design_list_systems",
    "design_list_templates",
    "design_generate",
    "design_iterate",
    "design_export",
)

#: 全部静态注册的内置工具名（排序去重）。新增内置工具时把名字加进对应
#: 分组即可；tests/unit/test_tool_names.py 会对照 register_all_tools 的
#: 实际注册面校验本清单无遗漏、无多余。
ALL_BUILTIN_TOOL_NAMES = tuple(
    sorted(
        set(EXEC_TOOLS)
        | set(FILE_TOOLS)
        | set(CODE_SEARCH_TOOLS)
        | set(WEB_TOOLS)
        | set(MEMORY_TOOLS)
        | set(SESSION_SEARCH_TOOLS)
        | set(OFFICE_TOOLS)
        | set(JOURNAL_TOOLS)
        | set(RUNTIME_TOOLS)
        | set(GIT_TOOLS)
        | set(CHECKPOINT_TOOLS)
        | set(PATCH_TOOLS)
        | set(SYMBOL_TOOLS)
        | set(BROWSER_TOOLS)
        | set(SKILL_TOOLS)
        | set(MULTIMODAL_TOOLS)
        | set(ORCH_TOOLS)
        | set(SANDBOX_TOOLS)
        | set(CONFIG_TOOLS)
        | set(SCHEDULE_TOOLS)
        | set(TODO_TOOLS)
        | set(DESIGN_TOOLS)
    )
)

# ---------------------------------------------------------------------------
# R90/R92 动态插件工具名字语义（与上面的静态内置清单互不混入）
#
# 桥接层（plugins/tool_bridge.py）发布的名字固定为
# ``plugin__<plugin>__<capability>``。前缀原先在 tool_bridge 与
# tools/permissions 各有一份字面量；R92 起收敛到本模块单一来源，
# profile 白名单的三道判定（registry schema 过滤、agent 并行预检、
# agent 执行边界）也统一走 ``tool_name_in_allowlist()``，防止各写一份
# 精确判定导致口径漂移。R98 起该 matcher 的受限通配分支与权限
# 规则（R96）同口径：只按调用方传入的权威 ``plugin_name`` 结构化
# 命中，不再按完整工具名字符串前缀判断插件归属。
# ---------------------------------------------------------------------------

#: 进程外插件工具的 LLM 命名空间前缀（单一来源）。
PLUGIN_TOOL_PREFIX = "plugin__"


def _is_valid_plugin_name_chars(value: str) -> bool:
    """与 tool_bridge 发布校验同一字符集：ASCII 字母、数字与 ``_.-``。

    手写逐字校验而非 ``re``：domain 纯度测试
    （test_domain_models.TestDomainPurity）只放行白名单内的标准库，
    本模块不为一次字符集判断扩大那张名单。
    """
    if not value:
        return False
    for char in value:
        if (
            "a" <= char <= "z"
            or "A" <= char <= "Z"
            or "0" <= char <= "9"
            or char in "_.-"
        ):
            continue
        return False
    return True


def is_plugin_tool_name(name: Any) -> bool:
    """``name`` 是否呈合法插件工具形状（只判形状，不判是否在运行）。"""
    if not isinstance(name, str) or "*" in name:
        return False
    if not name.startswith(PLUGIN_TOOL_PREFIX):
        return False
    if not _is_valid_plugin_name_chars(name):
        return False
    plugin_segment, separator, capability_segment = name[
        len(PLUGIN_TOOL_PREFIX) :
    ].partition("__")
    return bool(separator and plugin_segment and capability_segment)


def plugin_tool_wildcard_prefix(entry: Any) -> Optional[str]:
    """解析 R92 受限通配，合法时返回待匹配的命名空间前缀。

    只承认 ``plugin__*``（全部插件）与 ``plugin__<plugin>__*``（单个
    插件的全部 capability）；其它含 ``*`` 的写法一律返回 ``None``，
    由调用方按精确字符串处理（匹配不到合法工具名，fail-closed）。
    """
    if not isinstance(entry, str):
        return None
    if entry == PLUGIN_TOOL_PREFIX + "*":
        return PLUGIN_TOOL_PREFIX
    if not entry.startswith(PLUGIN_TOOL_PREFIX) or not entry.endswith("__*"):
        return None
    plugin_segment = entry[len(PLUGIN_TOOL_PREFIX) : -3]
    if not plugin_segment or "*" in plugin_segment:
        return None
    if not _is_valid_plugin_name_chars(plugin_segment):
        return None
    return entry[:-1]


def is_plugin_tool_wildcard(entry: Any) -> bool:
    """``entry`` 是否为 R92 承认的插件工具通配条目。"""
    return plugin_tool_wildcard_prefix(entry) is not None


def plugin_tool_wildcard_for_plugin(plugin_name: Any) -> Optional[str]:
    """由权威插件名派生单个插件的受限通配；非法名字返回 ``None``。

    R95 的审批规则持久化只能走这里：调用方提供的是服务端已
    发布记录中的插件名，不是客户端或 LLM 给出的 pattern。
    """
    if not isinstance(plugin_name, str):
        return None
    if not _is_valid_plugin_name_chars(plugin_name):
        return None
    pattern = f"{PLUGIN_TOOL_PREFIX}{plugin_name}__*"
    return pattern if is_plugin_tool_wildcard(pattern) else None


def plugin_tool_belongs_to_plugin(tool_name: Any, plugin_name: Any) -> bool:
    """完整工具名是否确实落在指定插件的受限命名空间内。"""
    pattern = plugin_tool_wildcard_for_plugin(plugin_name)
    if pattern is None or not is_plugin_tool_name(tool_name):
        return False
    prefix = pattern[:-1]
    return tool_name.startswith(prefix) and len(tool_name) > len(prefix)


def is_plugin_tool_reference(entry: Any) -> bool:
    """``entry`` 是否为合法形状的插件工具引用（精确名或受限通配）。"""
    return is_plugin_tool_name(entry) or is_plugin_tool_wildcard(entry)


# ---------------------------------------------------------------------------
# MCP 工具名字语义（Zotero 可见性修复 ①）
#
# MCP 服务器运行期提供工具，名字由客户端加命名空间前缀：
# ``mcp__<server>__<tool>``。历史上 profile 白名单只认精确名与插件
# 受限通配，导致 ``mcp__*`` 一律被拒 —— Zotero / drawio 等 MCP 工具对
# LLM 完全不可见（drawio 的 prompt 注入因此长期是死代码）。
#
# 口径与插件通配一致：只承认 ``mcp__*``（全部服务器）与
# ``mcp__<server>__*``（单个服务器）两种写法，其余含 ``*`` 的条目不
# 展开（fail-closed）。server 段不允许含 ``__``，保证「按第一个 ``__``
# 切分」的解析无歧义。
# ---------------------------------------------------------------------------

#: MCP 工具的 LLM 命名空间前缀（单一来源）。
MCP_TOOL_PREFIX = "mcp__"


def _is_valid_mcp_server_name(value: str) -> bool:
    """MCP 服务器名允许 ASCII 字母、数字、``_`` 与 ``-``。"""
    if not value:
        return False
    for char in value:
        if (
            "a" <= char <= "z"
            or "A" <= char <= "Z"
            or "0" <= char <= "9"
            or char in "_-"
        ):
            continue
        return False
    return True


def _split_mcp_tool_name(name: str):
    """把 ``mcp__<server>__<tool>`` 拆成 ``(<server>, <tool>)``；非法返回 None。"""
    remainder = name[len(MCP_TOOL_PREFIX) :]
    server_segment, separator, tool_segment = remainder.partition("__")
    if not separator or not server_segment or not tool_segment:
        return None
    if "__" in server_segment or not _is_valid_mcp_server_name(server_segment):
        return None
    return server_segment, tool_segment


def is_mcp_tool_name(name: Any) -> bool:
    """``name`` 是否呈合法 MCP 工具形状（只判形状，不判服务器是否在线）。"""
    if not isinstance(name, str) or "*" in name:
        return False
    if not name.startswith(MCP_TOOL_PREFIX):
        return False
    return _split_mcp_tool_name(name) is not None


def mcp_tool_wildcard_prefix(entry: Any) -> Optional[str]:
    """解析 MCP 受限通配，合法时返回待匹配的命名空间前缀。

    只承认 ``mcp__*``（全部服务器）与 ``mcp__<server>__*``（单个
    服务器）；其它含 ``*`` 的写法返回 ``None``，由调用方按精确字符串
    处理（匹配不到合法工具名，fail-closed）。
    """
    if not isinstance(entry, str):
        return None
    if entry == MCP_TOOL_PREFIX + "*":
        return MCP_TOOL_PREFIX
    if not entry.startswith(MCP_TOOL_PREFIX) or not entry.endswith("__*"):
        return None
    server_segment = entry[len(MCP_TOOL_PREFIX) : -3]
    if not _is_valid_mcp_server_name(server_segment):
        return None
    return entry[:-1]


def is_mcp_tool_wildcard(entry: Any) -> bool:
    """``entry`` 是否为承认的 MCP 工具通配条目。"""
    return mcp_tool_wildcard_prefix(entry) is not None


def is_mcp_tool_reference(entry: Any) -> bool:
    """``entry`` 是否为合法形状的 MCP 工具引用（精确名或受限通配）。"""
    return is_mcp_tool_name(entry) or is_mcp_tool_wildcard(entry)


def mcp_tool_wildcard_matches(tool_name: Any, entry: Any) -> bool:
    """``entry``（MCP 通配）是否命中 ``tool_name``。"""
    prefix = mcp_tool_wildcard_prefix(entry)
    if prefix is None or not is_mcp_tool_name(tool_name):
        return False
    if prefix == MCP_TOOL_PREFIX:
        return True
    return tool_name.startswith(prefix) and len(tool_name) > len(prefix)


def tool_name_in_allowlist(
    tool_name: Any,
    allowed_tools: Optional[Iterable[Any]],
    plugin_name: Optional[str] = None,
) -> bool:
    """profile 白名单单一匹配口径（精确名 + 插件/MCP 受限通配）。

    - ``allowed_tools is None``：无白名单限制（保持既有语义）；
    - 空可迭代对象：不放行任何工具（保持既有语义）；
    - 普通条目精确匹配，不要求插件身份；仅 ``plugin__*`` /
      ``plugin__<plugin>__*`` 与 ``mcp__*`` / ``mcp__<server>__*``
      做通配，其余含 ``*`` 的条目不展开；
    - R98：插件受限通配不再按完整工具名字符串前缀命中。插件名与
      capability 名都可含 ``__``，同一字符串可能对应不同
      结构化身份（``plugin__a__b__c`` 可能是插件 ``a__b`` 的
      工具）；通配命中以调用方给出的权威 ``plugin_name``
      （桥接发布记录）为准——完整工具名确实属于该插件，且
      单插件通配与由权威名重新派生的通配完全一致，与 R96
      ``PermissionRule.matches`` 同口径。身份缺失、非法或
      不匹配时通配不命中（fail-closed），调用方不得按完整
      工具名切分猜测插件名；
    - MCP 工具名自带 ``mcp__<server>__<tool>`` 结构，服务器段就是
      权威身份，无需外部 ``plugin_name``；``mcp__*`` 放行全部
      MCP 工具，``mcp__<server>__*`` 只放行该服务器；
    - 显式白名单下非字符串工具名不放行，坏条目不能放宽整个白名单。
    """
    if allowed_tools is None:
        return True
    if not isinstance(tool_name, str):
        return False
    for entry in allowed_tools:
        # 精确名与 MCP 受限通配互斥（通配必含 ``*``），合并成一个分支
        # 以保持 return 语句数在 ruff PLR0911 上限内。
        if entry == tool_name or mcp_tool_wildcard_matches(tool_name, entry):
            return True
        if not is_plugin_tool_wildcard(entry):
            continue
        if not plugin_tool_belongs_to_plugin(tool_name, plugin_name):
            continue
        if entry == PLUGIN_TOOL_PREFIX + "*":
            return True
        if plugin_tool_wildcard_for_plugin(plugin_name) == entry:
            return True
    return False

__all__ = [
    "ALL_BUILTIN_TOOL_NAMES",
    "BROWSER_TOOLS",
    "CHECKPOINT_TOOLS",
    "CODE_SEARCH_TOOLS",
    "CONFIG_TOOLS",
    "DESIGN_TOOLS",
    "EXEC_TOOLS",
    "FILE_TOOLS",
    "GIT_TOOLS",
    "JOURNAL_TOOLS",
    "MCP_TOOL_PREFIX",
    "MEMORY_TOOLS",
    "MULTIMODAL_TOOLS",
    "OFFICE_TOOLS",
    "ORCH_TOOLS",
    "PATCH_TOOLS",
    "PLUGIN_TOOL_PREFIX",
    "RUNTIME_EXEC_TOOLS",
    "RUNTIME_PROBE_TOOLS",
    "RUNTIME_TOOLS",
    "SANDBOX_TOOLS",
    "SCHEDULE_TOOLS",
    "SKILL_TOOLS",
    "SYMBOL_TOOLS",
    "TODO_TOOLS",
    "WEB_FETCH_TOOLS",
    "WEB_SEARCH_TOOLS",
    "WEB_TOOLS",
    "is_mcp_tool_name",
    "is_mcp_tool_reference",
    "is_mcp_tool_wildcard",
    "is_plugin_tool_name",
    "is_plugin_tool_reference",
    "is_plugin_tool_wildcard",
    "mcp_tool_wildcard_matches",
    "mcp_tool_wildcard_prefix",
    "plugin_tool_belongs_to_plugin",
    "plugin_tool_wildcard_for_plugin",
    "plugin_tool_wildcard_prefix",
    "tool_name_in_allowlist",
]

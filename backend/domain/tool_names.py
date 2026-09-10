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
- ``dispatch_subagents``：legacy_routes 编排模式下按会话动态注册；
- MCP 工具：外部服务器运行期提供。
"""

from __future__ import annotations

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
WEB_TOOLS = WEB_SEARCH_TOOLS + WEB_FETCH_TOOLS

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
    "office_analyze",
)

# 本地开发环境助手（2026-09-04）：只读探测/诊断两件 + 审批后执行一件。
# primary 只拿 PROBE 两件（READ 类，coordinator 边界）；coder 三件全拿。
RUNTIME_PROBE_TOOLS = ("runtime_probe", "project_diagnose")
RUNTIME_EXEC_TOOLS = ("runtime_exec",)
RUNTIME_TOOLS = RUNTIME_PROBE_TOOLS + RUNTIME_EXEC_TOOLS

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
# interact+close=WRITE_LOCAL。v1 只给 coder（executor 边界）。
BROWSER_TOOLS = (
    "browser_launch",
    "browser_navigate",
    "browser_snapshot",
    "browser_interact",
    "browser_screenshot",
    "browser_close",
)

# 技能类（2026-09 academic-search M1）：``skill`` 是循环内调用已有 skill
# （EXECUTE，M1 审批闸口按模式矩阵拦截），``skill_save`` 是显式把跑通的
# 工具调用序列沉淀为 SQLite 草稿（WRITE_LOCAL 写本地文件）。两者都通过
# 启动期白名单校验防止 profile 漂移。
SKILL_TOOLS = ("skill", "skill_save")

# 循环内编排：子代理委派 / 任务清单 / 结构化输出 / 用户提问
ORCH_TOOLS = ("agent", "todo_write", "structured_output", "ask_user_question")

SANDBOX_TOOLS = ("calculator", "repl")

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
        | set(RUNTIME_TOOLS)
        | set(GIT_TOOLS)
        | set(CHECKPOINT_TOOLS)
        | set(PATCH_TOOLS)
        | set(SYMBOL_TOOLS)
        | set(BROWSER_TOOLS)
        | set(SKILL_TOOLS)
        | set(ORCH_TOOLS)
        | set(SANDBOX_TOOLS)
    )
)

__all__ = [
    "ALL_BUILTIN_TOOL_NAMES",
    "BROWSER_TOOLS",
    "CHECKPOINT_TOOLS",
    "CODE_SEARCH_TOOLS",
    "EXEC_TOOLS",
    "FILE_TOOLS",
    "GIT_TOOLS",
    "MEMORY_TOOLS",
    "OFFICE_TOOLS",
    "ORCH_TOOLS",
    "PATCH_TOOLS",
    "RUNTIME_EXEC_TOOLS",
    "RUNTIME_PROBE_TOOLS",
    "RUNTIME_TOOLS",
    "SANDBOX_TOOLS",
    "SKILL_TOOLS",
    "SYMBOL_TOOLS",
    "WEB_FETCH_TOOLS",
    "WEB_SEARCH_TOOLS",
    "WEB_TOOLS",
]

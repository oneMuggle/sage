# Bash 工具优化计划（2026-09-04）

- **状态**：已评审，待实施
- **范围**：main（PR-1 / PR-2）→ 验证后 cherry-pick 到 `release/win7`
- **背景**：2026-09-04 对 main 与 release/win7 的 bash 工具接入现状核查结论 —— 两分支实现文件（`bash_tool.py` / `bash_session.py` / `bash_validation.py` / `shell_resolver.py` / `subprocess_util.py`）byte 级一致，注册、权限链路、会话生命周期、测试均完整接入；问题集中在**分发阻塞、白名单缺口、工具名漂移**三处。

## 1. 现状结论（证据）

**已接好的部分（不需要动）**：

- 三件套无条件注册：`register_all_tools()` 注册 `BashTool` / `BashOutputTool` / `KillShellTool`（`backend/tools/__init__.py:54` 起），仅出网工具受 NetworkPolicy 门禁。
- 权限链路完整：`validate_bash` 已接入 agent 审批组装（main `agent.py:1030`、win7 `agent.py:1024`）与 inproc 适配器（两分支 `inproc_adapter.py:188`）；`bash` 风险等级 EXEC，INTERACTIVE 模式默认询问用户。
- 会话生命周期收口：`main.py:111-116` `_shutdown_bash_sessions()` 退出清理。
- PowerShell 降级提示已注入工具结果（`bash_tool.py:174-175`，`shell_fallback` 字段）。
- 单测齐全：`test_bash_tool` / `test_bash_session` / `test_bash_validation` / `test_shell_resolver` 两分支均有。

**问题部分（本计划要修的）**：

1. bash 在 asyncio 事件循环内同步执行，长命令阻塞整个后端。
2. coder 白名单缺 `bash_output` / `kill_shell`，后台 shell 成孤儿；primary 无任何 shell 能力。
3. 工具名以字符串字面量散落，已两次漂移（`terminal`→`bash`、`file_read`→`read_file`，PR #402/#404 修复）。
4. 超时/输出/会话上限硬编码。

## 2. 已确认决策（2026-09-04）

| # | 决策项 | 结论 |
|---|--------|------|
| D1 | primary 是否接入 bash | **接入 bash / bash_output / kill_shell 三件套**；子代理白名单保持只读不变（`SUBAGENT_TOOL_WHITELIST` 不动） |
| D2 | 交付策略 | **先落 main，验证后 cherry-pick 到 release/win7**（沿用 PR #402→#404 惯例路径） |
| D3 | P2 范围 | 仅**常量可配置化**纳入本轮；前端后台 shell UI 与 win7 真机冒烟记为后续可选 |

## 3. PR-1：行为修复与防漂移（main）

### T1 阻塞工具在事件循环外执行（P0）

**问题**：`run_loop` 主分发点 `backend/core/legacy/agent.py:901` 对所有工具内联同步执行 `tool.execute(**args)`。BashTool 默认超时 120s、上限 600s（`bash_tool.py:61-63`），一条慢命令会阻塞整个 asyncio loop —— 健康检查、看板轮询、其他并发会话全部停摆。现有 executor 特判只覆盖 `agent` / `dispatch_subagents`（`agent.py:872-899`）。`ReplTool` 共用子进程原语，同样阻塞。

**方案**：

- `BaseTool` 增加类属性 `is_blocking: bool = False`（`backend/tools/base.py`）。
- `BashTool` 与 `ReplTool` 声明 `is_blocking = True`；`BashOutputTool` / `KillShellTool` 是快操作，保持 `False`。
- 分发点改为（与现有 `agent` 特判同构）：

  ```python
  if getattr(tool, "is_blocking", False):
      result = await asyncio.get_running_loop().run_in_executor(
          None, functools.partial(tool.execute, **args)
      )
  else:
      result = tool.execute(**args)
  ```

**说明**：
- `run_in_executor` 会复制当前 contextvars（Python 3.7.1+），`ToolExecutionContext` 读取不受影响 —— 与现有 agent 特判注释同一依据（`agent.py:878-886`）。
- `execute_tool`（`agent.py:1084`，含 1110 行的第二处分发）当前**无生产调用方**（仅测试引用），本轮不改代码，仅加注释标注。

**验收**：
- `integration/test_agent_tool_loop.py` 新增用例：run_loop 执行 sleep 类阻塞工具期间，同一 loop 上的心跳协程持续推进。
- `test_bash_tool.py` 断言 `BashTool.is_blocking is True`、`BashOutputTool.is_blocking is False`。

### T2 白名单补全 + primary 三件套 + 存量迁移（P0 + D1）

**问题**：
- 两分支 coder 均为 `tools=["read_file", "write_file", "bash", "calculator"]`：`run_in_background=true` 返回 `shell_id` 后，LLM 没有轮询（`bash_output`）与终止（`kill_shell`）工具，后台进程成为孤儿，直至应用退出才被 `_shutdown_bash_sessions()` 清理。
- D1 决策：primary 增加 bash 三件套。

**方案**（`backend/agents/profiles.py`）：

- coder 种子：`["read_file", "write_file", "bash", "bash_output", "kill_shell", "calculator"]`。
- primary 种子：现有清单尾部追加 `"bash", "bash_output", "kill_shell"`。
- 存量 DB 迁移：新增链式段 `_PRIMARY_TOOLS_BEFORE_BASH`（= 本分支当前种子集合），在 `ensure_default_agents()` 仿照 `_PRIMARY_TOOLS_BEFORE_TODO` 段（`profiles.py:265-270`）追加：`set(tools)` 精确相等才追加三件套，用户自定义白名单一律不动；顺序置于现有 todo 段之后，保持"一段升级后的集合 = 下一段判定集"的互斥链式结构。
  - **实施中发现的既有缺陷**：PR #396 §2 给 primary 种子加了 web_fetch/http_download，但从未落地对应迁移段 —— 沿 agent/todo 链升级的存量 DB 停在 10 工具形状，BEFORE_BASH（12 项）判定永远无法命中。已补 `_PRIMARY_TOOLS_BEFORE_FETCH` 段修复断链（链式迁移单测 `test_legacy_db_primary_full_chain` 捕获）。
- `SUBAGENT_TOOL_WHITELIST`（`backend/tools/agent_tool.py:83`）**不变**。

**验收**：
- 迁移单测三例：旧种子升级追加、已是新种子不重复追加、自定义白名单不动（追加到现有 `test_profiles_intranet_web_access_migration.py` 或新文件）。
- primary 的 LLM schema 含三件套、子代理 schema 不含。

### T3 工具名常量单一来源 + 启动期校验（P1）

**问题**：工具名以字符串字面量散落在 profiles.py，历史两次漂移都是运行期才暴露；两分支 cherry-pick 时靠人工对齐，易漏。

**方案**：

- 新建 `backend/domain/tool_names.py`（仅标准库，遵循 `domain/risk.py` 式的领域纯净性约定）：`ALL_BUILTIN_TOOL_NAMES`、`EXEC_TOOLS = ("bash", "bash_output", "kill_shell")`、`FILE_TOOLS` / `CODE_SEARCH_TOOLS` / `WEB_TOOLS` / `MEMORY_TOOLS` / `OFFICE_TOOLS` / `ORCH_TOOLS` / `SANDBOX_TOOLS` 等常量组。
  - 实施修订：原计划 `backend/tools/names.py`，但 `from backend.tools.names import ...` 会先执行 tools 包的 `__init__`（eager import 全部工具模块，httpx 等重依赖），与 profiles.py 目前不 import tools 层的现状冲突 —— 改放 domain 层，application（agents/profiles）与 adapters（tools/）都能向内安全引用。
- `profiles.py` 的种子白名单（primary/coder）从常量组组合，不写字面量；`ensure_default_agents` 追加 `bash_output`/`kill_shell` 补齐段（见 T2）。
- `main.py` lifespan 在 `ensure_default_agents()`（`main.py:238`）之后新增校验：遍历 repo 全部 profile，白名单中出现 `ALL_BUILTIN_TOOL_NAMES` 之外的名字记 warning。
  - 实施修订：**仅告警，不剔除**。未注册名对 LLM 本就不可见（`get_schemas_for_llm` 只遍历已注册工具），剔除反而会误伤引用 MCP 等动态工具的自定义 profile；漂移信号通过启动日志暴露。

**验收**：`tests/unit/test_tool_names.py` 把 `ALL_BUILTIN_TOOL_NAMES` 钉死在 `register_all_tools` 实际注册面上（一致性双向校验）；`validate_profile_tools` 对未注册名告警计数、合法白名单零告警；全部默认 agent 种子 ⊆ 已知名集合。

### PR-1 实施顺序

1. T1（独立，可先行）
2. T3 的 `names.py` 常量模块（T2 引用其常量）
3. T2 白名单 + 迁移段
4. 全量回归：`pytest backend/tests` + `ruff check`

**预估**：1.5–2 人日。

## 4. PR-2：常量可配置化（P2，按 D3 纳入本轮）

**问题**：`BASH_DEFAULT_TIMEOUT_SECONDS` / `BASH_MAX_TIMEOUT_SECONDS` / `BASH_MAX_OUTPUT_BYTES`（`bash_tool.py:61-66`）与 `MAX_BACKGROUND_SESSIONS`（`bash_session.py`）硬编码。

**方案**：仿 `network_config.py` 的 KV 模式（独立 `SETTINGS_KEY` + `SettingsRepository`，不走 `app_settings` blob）：

- 新建 `backend/tools/bash_config.py`，`load_bash_config()` 返回 dataclass：`timeout_default=120`、`timeout_max=600`、`output_cap=30KB`、`max_sessions=现值`。
- `BashTool` / `BashSessionRegistry` 改读配置；无配置时行为与现状完全一致。

**验收**：settings 缺省 / 合法 / 越界三态单测；既有 bash 全部单测保持绿。

**预估**：0.5–1 人日。

## 5. release/win7 cherry-pick 说明

- **适配而非盲挑**：win7 的 `profiles.py` 没有 web_fetch/http_download 种子与 PR #396 迁移常量 —— T2 的 `_PRIMARY_TOOLS_BEFORE_BASH` 判定集须按 win7 当前种子（无 web 工具）**单独定义**；agent.py 行号有偏移（win7 `validate_bash` 位于 1012/1024）。win7 的 coder 存量种子与 main 相同（PR #404 已修），`_CODER_TOOLS_BEFORE_BASH_OUTPUT` 判定集可直接复用。
- `names.py`、`is_blocking`、`bash_config.py` 与 profiles 解耦的部分可干净落地；`inproc_adapter.py` 两分支一致。
- 流程：PR-1 / PR-2 合入 main 验证后，参照 PR #404 的 cherry-pick 流程出 win7 PR，标题标注 backport 来源。

## 6. 风险与注意事项

- **primary 获得执行能力属行为变更**：INTERACTIVE（默认）模式下 EXEC 会先询问用户，安全网存在；但 AUTO 模式下将直接执行 —— 发布说明需标注。DISCUSS / PLAN 只读门禁与 OFFLINE 网络门禁均不受影响。
- **线程池占用**：`run_in_executor` 用默认 executor（`min(32, cpu+4)` 线程），并发长命令可能占满。后台会话已有 `MAX_BACKGROUND_SESSIONS` 上限；同步 bash 并发暂不设限，观察后再议（如需可加信号量，超出本计划范围）。
- **迁移链顺序敏感**：新段判定集必须是"本分支上一段升级后的精确集合"，与现有两段保持互斥链式；测试须覆盖链式命中路径。
- **ContextVar**：`run_in_executor` 复制上下文，与既有 agent 特判同一机制，无新增风险。

## 7. 后续可选（未纳入本轮）

- **前端后台 shell UI**：流式输出展示 + 终止按钮，替代当前 LLM 轮询 `bash_output` 再转述的模式。
- **win7 真机冒烟**：发布流程加一步 bash 工具实际执行 `echo && dir`，覆盖 Git Bash 探测与 PowerShell 降级路径。
- **`execute_tool` 清理**：main 上无生产调用方，考虑下个清理轮次删除或补齐 API 路由。

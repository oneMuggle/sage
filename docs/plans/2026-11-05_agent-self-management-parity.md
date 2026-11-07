# Sage 智能体自透明 / 自管理能力对等化方案

> 日期：2026-11-05
> 状态：实施中（M0 地基已落地；分支 `feat/agent-self-management-parity`）
> 背景：用户请求「分析当前 sage 项目的自透明和自管理能力……最终能够让用户只通过会话就能完成相关功能、修改配置等，至少应该能在会话中实现代替用户执行所有需要在 UI 界面上执行的操作，参考主流 AI 应用给出优化建议方案」

---

## 1. 背景与目标

### 1.1 现状一句话

Sage 已经有一个**窄而深**的自管理核心（配置 / 编排 / 定时 / 待办 / 记忆 / 技能执行 / 浏览器）与相当扎实的**项目级自透明**（工作区、git、SAGE.md 规则、记忆召回、技能清单），但缺两样关键东西：

1. **运行时自透明缺口** —— 智能体不知道自己是什么版本、这次请求实际走了哪个上游模型、MCP/插件清单是什么、今天花了多少钱、最近哪次调用失败了、当前处于哪个权限模式。
2. **UI 操作对等缺口** —— 绝大多数设置与管理动作只有 UI 能做，**尽管对应的 REST API 早已存在**（`backend/api/` 下 586 个端点）。

### 1.2 目标

| 目标 | 度量 |
|---|---|
| G1 会话内可改任意配置 | 按设置清单计，agent 可调用等价物覆盖率 ≥ 90% |
| G2 会话内可代替 UI 操作 | 按应用命令清单计，UI 操作对等率 ≥ 95% |
| G3 运行时状态自透明 | 一次工具调用内可答出「版本 / 实际模型 / 权限模式 / 今日花费」四问 |
| G4 自修改安全 | 默认模式下所有 WRITE_LOCAL 及以上动作 100% 产生审批记录 |

### 1.3 评估框架

**自透明三档**

- **L2 常态注入** —— 无需调用工具即知（system prompt 里就有）
- **L1 可查询** —— 有专门工具可查
- **L0 不可见** —— 无任何途径获知

**自管理三档**

- **L2 全域可管理** —— 任意操作都能做，且带审批与审计
- **L1 受限可管理** —— 有工具，但覆盖子集或被白名单锁死
- **L0 不可管理** —— 只能 UI/CLI

---

## 2. 现状盘点（附证据）

### 2.1 自透明

#### L2 常态注入 —— 已扎实

| 注入块 | 内容 | 证据 |
|---|---|---|
| `<environment>` | 平台 / 日期 / 工作区 / git 摘要（≤30 条） | `backend/chat/env_context.py:40` |
| `<available-skills>` | 已注册技能清单（≤20 条 / 2000 字符） | `backend/chat/env_context.py:67` |
| `<current-configuration>` | orch 8 键 + general 10 键 + modelSelections | `backend/chat/env_context.py:103` |
| 项目规则 | SAGE.md / CLAUDE.md / AGENTS.md 发现 | `backend/api/legacy_routes.py:1228` |
| 项目上下文 | 项目描述 + instructions + project_materials | `backend/api/legacy_routes.py` |
| 记忆召回 | 跨会话记忆注入 | `backend/api/legacy_routes.py:1660` |

已知缺口：`<current-configuration>` 的 general 白名单**漏了** `llmRetryMaxAttempts` / `llmRetryBaseDelayS` / `llmRetryMaxDelayS`（即 `docs/plans/2026-11-03_llm-retry-config-visibility-and-defaults.md` 记录的可见性问题），且 `endpoints` 整块被刻意排除。

#### L1 可查询 —— 覆盖窄

`read_sage_config`（section: all / orch / agents / general / model_selections / endpoints）、`diagnose_sage_config`（配置 + `OrchRunMetrics.aggregate_recent`）、`runtime_probe`、`project_diagnose`、`memory_search`、`session_search`、`list_scheduled_tasks`、`observe_subagents`。

#### L0 不可见 —— 关键空洞

| # | 不可见的东西 | 影响 |
|---|---|---|
| 1 | 应用版本（`backend.__version__` 不存在） | 报障时无法自述版本；升级后行为差异无从判断 |
| 2 | 本次请求**实际**生效的模型 + 端点 | 注入的是「配置里选了什么」，不是「这次真的走了哪个上游」；smart routing / fallback / 降级后两者不同 |
| 3 | MCP 服务器清单与状态 | 不知道有几个 server、哪些 enabled、暴了哪些工具、连通与否 |
| 4 | 插件清单与运行时状态 | 不知道装了/启用了什么、runtime 是否在跑 |
| 5 | 用量与成本 | `usage_events` / `usage_daily_rollups` 表里有、Prometheus 9 指标也有，但 agent 读不到 |
| 6 | 日志 / 错误 / 近期调用失败 | `sage_*.log`、LLM trace ring（50 条）、audit.jsonl 均为盲区 |
| 7 | 健康检查 / doctor | `backend/cli/doctor.py` 18 项检查仅 CLI 可用 |
| 8 | **当前权限模式** | agent 不知道自己处在 read_only 还是 full_access |
| 9 | 能力目录 | 不知道自己能调哪些工具、哪些 UI 功能存在 |
| 10 | 上下文占用 | 不知道当前会话用了多少 token、余量多少 |

### 2.2 自管理

#### 已有（L1/L2）

| 域 | 工具 | 备注 |
|---|---|---|
| 配置 | `read_sage_config` / `update_sage_config` / `diagnose_sage_config` | 目标枚举：orch / agent / general / endpoint / model_selection，字段硬编码白名单 |
| 定时 | `schedule_task` / `list_scheduled_tasks` / `cancel_scheduled_task` | 复用 `SchedulerService` 单一事实源 |
| 待办 | `add/list/update/complete/delete_todo` | |
| 记忆 | `memory_search` / `memory_save` | |
| 技能 | `skill`（按名执行）/ `skill_save`（存草稿） | **不在默认 profile 白名单 → 默认不可见** |
| 检查点 / 设计 | checkpoint / design_* | |
| 浏览器 | `browser_*` 九件套 + `browser_login` + `browser_cookies` | primary 只拿 `browser_login` |
| 运行 | `runtime_probe` / `project_diagnose` / `runtime_exec` | `runtime_exec` 仅 coder |

#### 缺失（仅 UI / CLI，REST API 却已存在）

| 域 | 缺失动作 | 已存在的 API |
|---|---|---|
| MCP | 增 / 改 / 启停 / 删 / OAuth / 工具白名单 | `backend/api/mcp_routes.py:123-304` |
| 插件 | 安装 / 启停 / runtime start-stop / 配置 / 权限确认 | `backend/api/plugin_routes.py:266-590` |
| 技能 | 列表 / 启停 / 归档 / 钉住 / 删除 / 导入 / 重扫 / 巡检 / 回滚 / 脚本开关 / 技能目录 | `backend/api/legacy_skills_routes.py` + `legacy_skill_draft_routes.py` |
| 会话 | 创建 / 重命名 / 归档 / 分叉 / 压缩 / 删除 | `backend/api/` session 路由组 |
| 项目与规程 | projects / project_materials / playbooks | `backend/api/project_routes.py` 等 |
| Wiki / Zotero | 页面 CRUD / 沉淀 / 同步 | `backend/api/wiki_*.py` / `zotero_routes.py` |
| 全局规则 | 读写 `~/.sage/SAGE.md` | `backend/api/global_rules_routes.py:125-215` |
| 权限 | 规则 / 预设 / 信任策略（**连读都不行**） | `backend/api/permission_routes.py:144-504` |
| 网关 | Telegram / Discord / Slack 配置与解绑 | `backend/api/gateway_routes.py:144-371` |
| 网络 | 出网代理 / 网络策略 / 搜索引擎顺序 | preferences `web_proxy` / `network_policy` / `search_config` |
| OCR | 引擎 / 语言 / 策略 / capabilities / 模型下载 / 批量 / 清理 | `backend/api/ocr_routes.py:79-169` + Electron IPC |
| 更新 | 检查 / 下载 / 安装 / 回滚 / 策略 / 通道 | Electron `updateIpc.ts`（后端仅只读 manifest） |
| 反馈 | 配置 / 同步 / 会话 / 附件 / 搜索 | Electron + `backend/api/feedback_routes.py` |
| 诊断 | 诊断包预览 / 导出 / 日志文件 / 日志级别 / 浏览器健康 | `backend/api/diagnostic_routes.py` + Electron IPC |
| 外观 | 主题 / 字号 / 自定义 CSS | preferences + `backend/api/theme_router.py` |
| 桌宠 | 全生命周期 | Electron `electron/pet/ipc.ts` |
| 端点 | 探测 probe / 上游模型发现 / smart routing 模式写入 | `model_catalog_routes.py:326` / `llm_proxy_routes.py` |
| 偏好 KV | `preferences` 表中除 general 白名单外的全部键 | `backend/data/settings_repo.py:19-127` |

#### 另有两类「物理隔离」的设置

`src/entities/setting/settingsRegistry.ts:88-753` 记录了每个字段的存储后端 / 生效时机 / 可见性。但相当一部分字段根本不落在后端：

- **localStorage**：界面语言、输入历史条数、超长附件 RAG、上次访问 Tab、功能解锁、密度模式
- **Electron 文件**：更新配置、更新提供方、反馈同步、桌宠、演示模式、关闭到托盘
- **仅渲染进程内存**：思考面板展开态

这些要 agent 可管，必须先有后端 ↔ Electron ↔ localStorage 的桥。

### 2.3 必须先修的权限缺陷（已逐条核验）

#### 缺陷 A —— `TOOL_CAPABILITIES` 按名硬编码表不完整，`update_sage_config` 在默认模式下静默放行

- `backend/tools/permissions.py:69-120` 的表只登记了 24 个工具；`update_sage_config` **不在其中**
- `classify_tool`（`permissions.py:120-124`）回退 `DEFAULT_TOOL_CAPABILITY = WRITE`（`permissions.py:112`）
- `_mode_decision`（`permissions.py:426-448`）：`WORKSPACE_WRITE` + `READ|WRITE` → `_allow`，**不触发审批**
- **后果**：智能体可在零用户确认的情况下改 API Key、端点地址、编排预算、重试预算、超时
- **附带效应**：`read_sage_config` / `diagnose_sage_config` 同样未登记 → 在 `READ_ONLY` 模式下被 `_deny`，只读工具被当成写工具拦截
- **意图与实现的背离**：`docs/plans/2026-10-28-enhance-llm-config-tool.md` 明写「保持现有安全级别（WRITE_LOCAL，需要用户审批）」，但因该表未登记此工具，实际从未触发审批

#### 缺陷 B —— `execute_code` / skill 脚本经 RPC 直调工具，绕过 profile 白名单与 `PermissionEnforcer`

- `backend/tools/execute_code_tool.py:326-340` `_serve_rpc`：`registry.get(name)` → `tool.execute(**arguments)`，全程无 enforcer、无 profile 过滤
- **后果**：`sage.call("update_sage_config", ...)` / `sage.call("office_delete", ...)` 可绕开一切审批与白名单

#### 次级缺陷

| # | 缺陷 | 证据 |
|---|---|---|
| C | 双风险模型并存且**数据驱动那套未接线** —— `PermissionEngine`（`backend/adapters/out/permission/permission_engine.py`）在生产代码中零引用，仅 `backend/tests/unit/test_permission.py` import。工具都已声明 `risk`（`config_tool.py:325/441/927`）、registry 也收集了 `declared_risks`，但消费方未接线；真正生效的是按名硬编码表 | grep 全仓核实 |
| D | `office_delete` 登记为 `WRITE` → `WORKSPACE_WRITE` 下无审批删除文档。只有 bash 有破坏性升级网（`_escalate_destructive`），文件删除没有 | `permissions.py:88` vs `:424` |
| E | hex `/chat` 路径未见 profile 过滤 | `backend/api/hex_routes.py` 无工具白名单引用 |
| F | 信任升级设置键不在 `settings_repo.py` 的 KEYS 白名单 → 信任升级功能实际处于关闭状态 | `backend/services/trust_escalation.py:63` vs `backend/data/settings_repo.py:19` |
| G | 无 settings-changed 事件 → agent 改完配置，已打开的 UI 不刷新（`settingsClient.ts:86-89` 只对 preferences 广播了 `sage:setting-changed`，app_settings 无等价广播） | `src/features/manage-settings/settingsStore.ts` |

#### 死工具（已定义未注册）

`wiki_search` / `wiki_answer` / `project_advise` / `project_decompose_tasks` / `project_extract_knowledge` —— `backend/domain/tool_names.py` 文档字符串明确标注「已定义但未注册」。

---

## 3. 主流 AI 应用对标

| 应用 | 自透明做法 | 自管理做法 | 对 Sage 的启示 |
|---|---|---|---|
| **Claude Code** | CLAUDE.md / config 文件即真相；`/status`、`/doctor`、`/config`、`/context` | 配置文件直改；skills / MCP 用 CLI（`claude mcp add`）；hooks | ① 配置即文件 + CLI 化 ② `/status` `/doctor` 是最廉价的高感知自透明入口 |
| **Cursor** | rules 文件 + MCP 服务器面板 | 规则文件编辑 + MCP 配置增删 | MCP 服务器管理是刚需，不是加分项 |
| **ChatGPT** | 记忆功能（用户可见、可删） | Apps / Connectors 管理 | 用户必须能看见并撤销 agent 对自己的写入 —— 「可撤销」是产品底线 |
| **Devin / Manus（computer-use）** | 截图观察 | 直接点击 UI | 兜底手段，精度差、风险高，只适合补最后 5% |
| **Codex CLI** | `AGENTS.md` + 沙箱策略声明 | 显式 diff + 沙箱落盘 | 变更走 diff + 沙箱，而非直接改内部状态 |

**结论**：主流做法是「配置即文件 + CLI 化 + 状态命令 + 显式 diff」，**不是**给 agent 一个能直接改任意内部状态的黑盒。Sage 现有架构（REST API 已齐备、工具层薄）实际处于比主流更有利的位置 —— 缺的是**工具层**，不是后端。

---

## 4. 技术方案

### M0 地基（1 个迭代）—— 不做这层，后面全是风险

| # | 任务 | 落点 |
|---|---|---|
| M0.1 | 补全 `TOOL_CAPABILITIES` 至全部 111 个内置工具；未知工具回退从 `WRITE` 改为 `EXECUTE`（fail-safe 方向统一） | `backend/tools/permissions.py:69-124` |
| M0.2 | `_serve_rpc` 内接 `PermissionEnforcer` + profile 白名单过滤 | `backend/tools/execute_code_tool.py:326` |
| M0.3 | `office_delete` 归 `EXECUTE`（或补破坏性二次确认） | `backend/tools/permissions.py:88` |
| M0.4 | 收敛双风险模型：`PermissionEngine` 要么接进生产取代硬编码表，要么删除 | `backend/adapters/out/permission/permission_engine.py` |
| M0.5 | 新增 `RiskClass.SELF_MODIFY`（改配置 / 装插件 / 改权限 = 高危），`PROMPT` 模式下强制逐次审批，子代理禁用 | `backend/domain/risk.py` |
| M0.6 | `read_sage_config` / `diagnose_sage_config` 显式登记为 `READ`，`update_sage_config` 登记为 `WRITE_LOCAL` | `backend/tools/permissions.py` |
| M0.7 | 清理死工具：注册或删除 `wiki_search` / `wiki_answer` / `project_advise` / `project_decompose_tasks` / `project_extract_knowledge` | `backend/domain/tool_names.py` + `backend/tools/__init__.py` |

### M1 自透明补齐（1–2 个迭代）

| # | 任务 | 落点 |
|---|---|---|
| M1.1 | `sage_self_status`：一次返回 版本 / 实际生效模型+端点 / 权限模式 / 上下文占用 / MCP 清单 / 插件清单 / 今日用量成本 / 健康摘要 | 新工具 + 复用 `backend/chat/env_context.py` 取数逻辑 |
| M1.2 | `read_sage_config` 扩展：加 `version` / `routing` / `preferences` 域 / 实际生效模型 / 权限模式 | `backend/tools/config_tool.py:332` |
| M1.3 | `sage_doctor`：把 `backend/cli/doctor.py` 的 18 项检查暴露为工具 | 新工具，复用 CLI 逻辑 |
| M1.4 | `sage_usage`：读 `usage_events` + `usage_daily_rollups`，返回 token / 花费 / 趋势 | 新工具 |
| M1.5 | slash 命令 `/status` `/doctor` `/config`（对齐 Claude Code） | `src/widgets/chat/slashCommands.ts` |
| ~~M1.6~~ | ~~修 `<current-configuration>` general 白名单漏项（llmRetry* 三项）~~ | `backend/chat/env_context.py` | **2026-11-03 已通过 `_retry_config_lines()` 完成**；删除本条目 |
| M1.7 | 修复缺陷 G：app_settings 变更广播 `sage:setting-changed`，agent 改配置后 UI 自动刷新 | `src/features/manage-settings/settingsStore.ts` + `src/shared/api/settingsClient.ts` |

### M2 设置全域对等（2–3 个迭代）—— 价值最大

**核心思路：不要为每个设置项写一个工具。** 把 19 个 Tab 的设置抽象成一张 **schema 驱动的统一设置工具**。

1. **建立设置清单**（单一事实源）：新增 `backend/domain/settings_manifest.py`，每字段一条记录
   ```
   {key, type, enum?, range?, risk, storage, tab, label, description,
    requires_restart?, secret?}
   ```
   `storage` ∈ `app_settings | preferences | electron | local`
2. **字段元数据复用**：以 `src/entities/setting/settingsRegistry.ts` 为基础补全（当前只覆盖部分字段，`maxOutputTokens` / 主题 / 语言 / 端点等缺失）
3. **统一工具**：`sage_settings`，`action ∈ {list_schema, read, write}`
   - 按 `storage` 路由到对应写入器（app_settings → canonicalizer；preferences → settings_repo；electron → 桥；local → 保留 UI-only 并显式标注）
   - 写操作统一走：diff 预览 → 用户确认 → 应用 → 审计
   - 每字段按 `risk` 分级，secret 字段只允许读 `hasApiKey`，禁止读明文
4. **补齐 electron/local 存储**：新增后端 ↔ Electron 的 app-command 桥（与 M3 共用）

### M3 实体与扩展面对等（2–3 个迭代）

补齐会话 / 项目 / 规程 / Wiki / Zotero / 记忆管理 / 技能 CRUD / MCP 管理 / 插件管理 / 权限规则**读取**。

**令牌膨胀问题**：primary 已持 92 个工具（`backend/agents/profiles.py`），再平铺十几个会撑爆上下文。解法二选一：

- **方案 A（推荐）**：收敛为 `sage_admin` 伞形工具 + `action` 路由，配合既有 harness bundle 预设（standard / focus / headless / dev，`backend/application/kernel/harness_config.py:102`）做渐进披露
- **方案 B**：逐域独立工具，但严格限制各 profile 种子白名单规模

### M4 UI 操作对等与安全加固（2–3 个迭代）

| # | 任务 | 说明 |
|---|---|---|
| M4.1 | **声明式应用命令注册表**：`{command_id, 描述, 风险, 参数 schema, 实现}`。UI 按钮与 agent 工具**由同一份 spec 派生** → 一处实现两处可用，杜绝漂移 | 这是「UI 操作对等」的正解 |
| M4.2 | SSE `ui_action` 事件桥：agent 触发的 UI 侧动作（打开某 Tab、滚动定位、弹出确认）以事件推送。复用 `backend/tools/agent_event_bridge.py` 既有范式 | |
| M4.3 | Electron 主进程动作桥：更新 / 托盘 / 桌宠 / 通知等主进程能力经 IPC 暴露给后端 | |
| M4.4 | 安全加固：写操作 diff 卡片 + 逐次审批；prompt-injection 红队（外部内容不得触发配置写入）；子代理隔离（不得获得 `SELF_MODIFY`）；审计日志 + undo 窗口 | |
| M4.5 | computer-use 兜底：仅覆盖剩余 <5% 无 API 的 UI 操作，显式标注高风险 | |
| M4.6 | win7 双分支同步：`requirements-py38.txt` / pydantic 1.x 适配；双白名单 + 契约测试 | |

### 快速见效项（Quick Wins，约 1 周，可与 M0/M1 并行）

| # | 任务 | 收益 | 状态 |
|---|---|---|---|
| ~~Q1~~ | ~~`skill` / `skill_save` 加入 primary 白名单~~ | 默认即可用技能 | **M0 已落地**（2026-11-05） |
| Q2 | `read_sage_config` 增 version / routing / 实际模型 / 权限模式 | 零成本透明度 | 待实施（属 M1.2） |
| Q3 | `sage_doctor`（复用 CLI doctor 逻辑） | 高感知 | 待实施（属 M1.3） |
| Q4 | `sage_usage` | 成本可见 | 待实施（属 M1.4） |
| Q5 | `/status` `/doctor` `/config` slash | 对标 Claude Code | 待实施（属 M1.5） |
| Q6 | **CI 能力覆盖守卫**：断言「每个设置 Tab 至少一个写操作有 agent 可调用等价物」，新增设置只进 UI 即 CI 红灯 | 防未来漂移（镜像现有 `test_tool_names` / `test_tool_bundles_parity` 模式） | 待实施 |
| ~~Q7~~ | ~~修 `env_context.py` 的 llmRetry* 三项漏项~~ | 已有计划文档覆盖 | **2026-11-03 已完成**（`_retry_config_lines()`） |
| Q8 | 清理 `docs/plans/` 中已完成却未删除的历史计划（如 `2026-10-28-enhance-llm-config-tool.md`），恢复「仅保留进行中计划」的约定 | 文档卫生 | 待实施 |

---

## 5. 实施步骤

### M0 地基（已完成 2026-11-05）

- [x] M0.1 补全 `TOOL_CAPABILITIES` 至全部 111 个内置工具（覆盖守卫 `test_capability_table_covers_every_builtin_tool`）
- [x] M0.2 `_serve_rpc` 静态拒绝面（EXECUTE ∪ SELF_MODIFY ∪ ask_user_question → 错误信息引导主循环直调）
- [x] M0.3 `office_delete` 提级为 `EXECUTE`（同步更新 `test_office_update_delete_registered_as_write_capability` 与 `test_path_boundary_office_delete_outside_workspace_asks`）
- [x] M0.5 `SELF_MODIFY_TOOLS` 集合 + `_mode_decision` 顶部升级审批闸（READ_ONLY deny / WORKSPACE_WRITE ask / PROMPT ask / FULL_ACCESS 放行 / allow 规则仍可放行 / deny 永远胜出）
- [x] M0.6 config 三工具显式登记（`read_sage_config`/`diagnose_sage_config` READ / `update_sage_config` WRITE + SELF_MODIFY）
- [x] Q1 `skill` / `skill_save` 加入 primary 白名单（`*SKILL_TOOLS`）+ `test_primary_profile_includes_skill_tools`
- [x] 新测试文件 `backend/tests/unit/test_tool_capabilities.py`（M0.1/M0.2/M0.3/M0.5/M0.6/Q1 全覆盖）
- [ ] M0.4 收敛 `PermissionEngine` 双模型（推迟，理由见 §9.1）
- [ ] M0.7 清理死工具（推迟，理由见 §9.1）

### M1 自透明补齐

- [x] ~~M1.1 `sage_self_status`~~（2026-11-05 feat/agent-self-transparency：8 维聚合 + `backend/services/self_status.py` + `sage_self_status_tool.py`）
- [x] ~~M1.2 `read_sage_config` 扩展~~（2026-11-05 新增 version / routing / preferences / self 四个只读 section；`_VISIBLE_PREFERENCE_KEYS` 白名单 + JSON 自动解析 + 凭证脱敏）
- [x] ~~M1.3 `sage_doctor`~~（2026-11-05 复用 `backend/cli/doctor.py` 18 项检查，含可选子进程探测）
- [x] ~~M1.4 `sage_usage`~~（2026-11-05 global/session 作用域，today/7d/30d/total 范围，nullable cost 显式标注"未知"）
- [x] ~~M1.5 slash 三命令~~（2026-11-05 `/status` `/doctor` `/config` 均 `mode='prompt'`，指示 LLM 调用对应工具并人类可读呈现）
- [x] ~~M1.6 env_context 漏项~~（2026-11-03 已通过 `_retry_config_lines()` 完成）
- [ ] M1.7 app_settings 变更广播 —— **推迟到 M3**（理由见 §10）

### M2 设置全域对等

- [ ] M2.1 `settings_manifest.py` 单一事实源
- [ ] M2.2 `sage_settings` 统一工具
- [ ] M2.3 preferences 域纳入
- [ ] M2.4 electron/local 存储桥

### M3 实体与扩展面对等

- [ ] M3.1 `sage_admin` 伞形工具 + bundle 渐进披露
- [ ] M3.2 MCP / 插件 / 技能管理动作
- [ ] M3.3 会话 / 项目 / 规程 / Wiki / Zotero / 记忆管理
- [ ] M3.4 权限规则读取（不含修改）

### M4 UI 操作对等与安全加固

- [ ] M4.1 应用命令注册表
- [ ] M4.2 SSE `ui_action` 桥
- [ ] M4.3 Electron 主进程桥
- [ ] M4.4 安全加固（diff 卡片 / 红队 / 审计 / undo）
- [ ] M4.5 computer-use 兜底
- [ ] M4.6 win7 同步

### 其他 Quick Wins

- [ ] Q6 CI 能力覆盖守卫（设置 Tab 至少一个写操作有 agent 等价物）
- [ ] Q8 清理已完成的历史计划文档

> Q2–Q6、M1–M4 待用户批准后续迭代启动。

---

## 6. 验收标准

| 指标 | 定义 | 目标 |
|---|---|---|
| 能力覆盖率 | 按 `settings_manifest` 计，拥有 agent 可调用等价物的设置项占比 | M2 后 ≥ 90%（剩余为纯外观类） |
| UI 操作对等率 | 按应用命令清单计，有 agent 可调用等价物的 UI 顶级操作占比 | M4 后 ≥ 95% |
| 自透明完整度 | 一次工具调用内可回答「版本 / 实际模型 / 权限模式 / 今日花费」 | 4/4 |
| 自修改审批率 | 默认 WORKSPACE_WRITE 模式下产生审批记录的 agent 自修改动作占比 | **当前 0% → 100%** |
| 不可逆动作静默率 | 删除 / 卸载 / 覆盖类动作在无审批无审计时发生的比例 | 0% |
| 工具面膨胀 | primary profile 工具数 | ≤ 100（靠伞形工具收敛，而非平铺） |

---

## 7. 风险与依赖

| 风险 | 说明 | 缓解 |
|---|---|---|
| 密钥面扩大 | 自管理铺开后 agent 能触及更多凭据字段 | secret 字段只读 `hasApiKey`；写需显式确认 + 审计；禁止读明文 |
| 自提权 | agent 改权限模式 / 审批规则 / 信任策略即自我提权 | 归 `SELF_MODIFY`；子代理禁用；`READ_ONLY` 下不可写；改权限模式本身需二次确认 |
| Prompt injection | 外部网页 / 文档内容可能诱导模型改配置 | 写入必须带 diff 卡片 + 用户确认；确认卡显示发起来源；外部内容不得自带确认语义 |
| 破坏性操作 | 删除 / 卸载 / 覆盖不可逆 | 高风险分级 + 二次确认 + undo 窗口 + 审计 |
| 令牌膨胀 | 平铺工具撑爆上下文 | 伞形工具 + harness bundle 渐进披露 |
| 双分支漂移 | main / win7 工具面与白名单不同步 | 双白名单同步 + 契约测试（参照 `backend/tests/unit/test_tool_names.py`、`test_tool_bundles_parity.py`） |
| UI 状态陈旧 | agent 改配置后 UI 不刷新 | M1.7 补广播事件；M4.1 统一命令注册表后天然同源 |
| 能力漂移 | 新增设置只进 UI | Q6 CI 能力覆盖守卫 |

**依赖**：M2 依赖 M0（权限分级）与 M1.7（变更广播）；M3 依赖 M2 的清单机制；M4 依赖 M0.5 的 `SELF_MODIFY` 分级。M0 与 Q1–Q8 可立即启动，无前置依赖。

---

## 8. 文档归档去向

实施完成后按项目文档规范并入：

- 技术手册 → `docs/technical/` 新增一章「智能体自透明与自管理」（编号避让现有 87 行索引中的重号；main 与 win7 分别取号）
- 用户手册 → `docs/user-manual/` 增补「会话内管理 Sage」章节（操作步骤 + 常见问题）

本计划文档在 M0–M4 全部完成后**直接删除**（`docs/plans/` 仅保留进行中计划）。

---

## 9. M0 实施记录（2026-11-05）

### 9.1 与原计划的关键偏离

| 项 | 原计划 | 最终决策 | 原因 |
|---|---|---|---|
| DEFAULT_TOOL_CAPABILITY | 改 EXECUTE | **保持 WRITE 不变** | MCP/编排工具未登记时若按 EXECUTE 每次都要审批；内置全量登记 + `plugin__` 前缀归 EXECUTE 已守住 fail-safe 方向，覆盖守卫把漏登记直接拦为 CI 红灯 |
| M0.5 自管理分级 | 新增 `RiskClass.SELF_MODIFY` | 在 `permissions.py` 新增 `SELF_MODIFY_TOOLS` frozenset + `_mode_decision` 顶部升级审批 | `RiskClass` 消费方为零（仅 `PermissionEngine`，且其自身零生产引用），加枚举零收益；直接加 frozenset 立刻生效 |
| M0.2 RPC 拒绝 | 接 `PermissionEnforcer` + profile 白名单 | 静态策略：`classify_tool(name) is EXECUTE` ∪ `SELF_MODIFY_TOOLS` ∪ `{"ask_user_question"}` | `execute_code` 为 `is_blocking = True`，运行在 executor 线程，`ContextVar` 丢失导致 `PermissionEnforcer` / `ToolExecutionContext` 在该线程不可用；静态策略是唯一安全可行方案 |
| M0.4 收敛双风险模型 | 删除 `PermissionEngine` 或接生产 | **推迟** | `PermissionEngine` 零生产引用、删除需清理 25+ 测试文件、`classify_tool` + `SELF_MODIFY_TOOLS` 已覆盖实际语义 |
| M0.7 清理死工具 | 注册或删除 `wiki_search` 等 | **推迟** | `wiki_tool.py` 仍被 `sources_extractor.py` / `remote_mcp/knowledge.py` 引用，清理需产品决策 |

### 9.2 落地改动清单

- `backend/tools/permissions.py`
  - `TOOL_CAPABILITIES` 由 24 项扩至 111 项（覆盖所有 `ALL_BUILTIN_TOOL_NAMES`）
  - 新增 `SELF_MODIFY_TOOLS: frozenset({"update_sage_config", "schedule_task", "cancel_scheduled_task"})`
  - `_mode_decision` 顶部加自管理升级闸
  - `__all__` 导出 `SELF_MODIFY_TOOLS`
  - 注释更新
- `backend/tools/execute_code_tool.py`
  - 模块 docstring 加 RPC 准入说明
  - 新增 `RPC_FORBIDDEN_TOOLS`、`_rpc_denial_reason()`
  - `_serve_rpc()` 在 `registry.get` 前静态拒绝
- `backend/agents/profiles.py`
  - 导入 `SKILL_TOOLS`
  - `_PRIMARY_SEED_TOOLS` 加入 `*SKILL_TOOLS`（coordinator-only，子代理白名单不含）
- `backend/tests/unit/test_tool_capabilities.py`（新建）
  - M0.1 覆盖守卫
  - M0.3 office_delete EXECUTE
  - M0.5 三种模式矩阵 + 显式规则优先
  - M0.6 config 三工具
  - M0.2 RPC 拒绝面（12 个 EXECUTE 工具 + 自管理 + ask_user_question；READ/WRITE 放行；未知工具保留"工具不存在"错误；非字符串名字拒绝）
- `backend/tests/unit/test_permissions_enforcer.py`
  - `test_office_update_delete_registered_as_write_capability` → office_delete 断言改为 EXECUTE
  - `test_path_boundary_office_delete_outside_workspace_asks` → 工作区内也逐次审批
- `backend/tests/unit/test_profiles_default_tools.py`
  - 新增 `test_primary_profile_includes_skill_tools`

### 9.3 测试结果

- 针对性测试 `test_tool_capabilities.py` + `test_permissions_enforcer.py` + `test_profiles_default_tools.py` + `test_execute_code.py` + `test_tool_names.py` + `test_tool_bundles_parity.py` → **169 passed**
- 全仓 unit 测试 `pytest backend/tests/unit/` → **exit 0**（后台任务 `biq6uasbx` 完成，无回归）

---

## 10. M1 实施记录（2026-11-05）

### 10.1 与原计划的关键偏离

| 项 | 原计划 | 最终决策 | 原因 |
|---|---|---|---|
| M1.1 聚合服务位置 | 直接扩 `sage_self_status` 工具 | 新建 `backend/services/self_status.py` 纯函数模块 | 工具层不应散落对 `mcp.pool` / `PluginLifecycleManager` / `usage_tracker` 的 import；REST 路由 / 未来 SSE / 新工具都可复用 |
| M1.2 `self` 进 `all` | 隐含 | **`all` 不触发自省**，需显式 `section="self"` | `gather_self_status` 聚合 8 维、含多次 LLM/MCP/DB 读取；"查所有配置"时隐式触发会让慢请求雪崩 |
| M1.5 slash 命令实现方式 | 新建 `mode: 'action'` 直接前端执行 | 复用 `mode: 'prompt'` + LLM 调工具 | 工具已是 REST 级聚合入口；LLM 调用后人类可读呈现比硬 UI 更灵活 |
| M1.7 跨进程广播 | 本里程碑落地 | **推迟到 M3** | 需要 backend→Electron IPC→frontend event bus 三进程桥；M3 的 `sage_admin` 统一命令注册表会让广播自然同源，避免双轨 IPC |

### 10.2 落地改动清单

- `backend/services/self_status.py`（新建）
  - 8 维 `_gather_*` 函数（version / effective_model / permission_mode / mcp / plugins / usage / health / context）
  - `gather_self_status()` 聚合入口（fail-open 但 fail 可见）
  - `read_version()` 公开别名（供 `read_sage_config` 复用）
  - 测试友好别名 `get_mcp_pool` / `get_plugin_lifecycle_manager` / `get_usage_summary` / `load_enforcer_from_settings` / `load_llm_config_for_chat`（lazy import + 便于 monkeypatch）
- `backend/tools/self_status_tool.py`（重写）
  - 瘦工具层 —— 只包 `gather_self_status()`，不再直接聚合
  - 失败维度在 `output` 文本里高亮（`⚠ ` 前缀）
- `backend/tools/config_tool.py`
  - `_VALID_READ_SECTIONS` 从 6 项扩到 10 项（+version / +routing / +preferences / +self）
  - 新增 `_VISIBLE_PREFERENCE_KEYS`（23 项白名单）+ `_read_visible_preferences()` 助手
  - `section="all"` 含新三节但**不**含 `self`；`general` 不再重复 `routing`
  - apiKey 脱敏逻辑保持不变（`_redact_settings` 已覆盖新 section）
- `src/widgets/chat/slashCommands.ts`
  - 新增 `/status` / `/doctor` / `/config` 三条（`mode: 'prompt'`，分别调用 `sage_self_status` / `sage_doctor` / `read_sage_config(all)`）
  - 图标选 lucide-react 现成：`Activity` / `Stethoscope` / `Settings`
- `backend/tests/unit/test_self_status_tool.py`（扩展）
  - 16 个测试覆盖服务层 + 工具层
  - 8 个维度逐个 mock + fail-open 验证
  - `gather_self_status` 全绿路径 + 部分失败路径
  - `read_version` 别名正确性
  - 工具层调用 `gather_self_status`，不直接聚合
  - 失败维度在 output 中高亮
- `backend/tests/unit/test_config_tool.py`
  - 新增 7 个 M1.2 测试（routing / version / preferences 白名单 + 脱敏 / self / all 不含 self / 未知 section 拒绝）
- `src/widgets/chat/__tests__/slashCommands.test.ts`
  - 新增 3 个命令注册 + prompt 渲染测试
- `architecture-baseline.json`
  - `backend/agents/profiles.py` 1123 → 1130
  - `backend/tools/permissions.py` 882 → 886
  - `backend/tools/config_tool.py` 980 → 1097
- `backend/services/context_window.py`（新建，CI 红灯修复）
  - 把 `resolve_effective_window`（Task 5 上下文窗口解析级联）从
    `backend.api.chat_request_policy` 下沉到 services 层。原因：M1.4
    `sage_usage_tool` → `usage_tracker` 原本 lazy import
    `backend.api.legacy_routes._resolve_effective_window`，导致
    adapters → tools → services → api 逆向依赖链，`lint-imports`
    hexagonal-architecture 合约红灯。
  - `chat_request_policy.py` 保留 `_resolve_effective_window` 再导出别名，
    存量 import 路径（legacy_routes / main.py / 测试）无感。
- `backend/tools/tool_bundles.py`
  - 新增 `self_status` bundle（`SageSelfStatusTool` / `SageDoctorTool` /
    `SageUsageTool`，全部 READ）；所有 preset 默认选中 → `test_cli_harness.py`
    四处硬编码 bundle 计数 +1 同步（32→33 / 24→25 / 31→32 / 23→24）。

### 10.3 测试结果

- `test_config_tool.py` → **61 passed**（含 7 个 M1.2 新测试）
- `test_tool_bundles_parity.py` 等 11 个 parity 文件 → **114 passed**（baseline 已抬）
- `slashCommands.test.ts` → **14 passed**（含 3 个 M1.5 新测试）
- `test_self_status_tool.py` → **21 passed**（M1.1 扩展 + review-fix 新增）
- **M1 阶段合计 ≥ 202 tests green**（含 overlap：`test_tool_capabilities.py` 与 M0 共享）
- CI 红灯修复后本地复验：`lint-imports` KEPT（1 contract, 0 broken）；
  `test_chat_request_policy` / `test_model_catalog_context` / `test_usage_tracker` /
  `test_self_status_tool` 合计 93 passed；`test_cli_harness.py` 10 passed；
  harness 全家桶（7 文件）78 passed。

### 10.3.1 Code review 修复轮（commit 74ae37680，2026-11-05）

code-reviewer agent 发现 4 HIGH + 2 MEDIUM + 1 LOW 缺陷，全部被 MagicMock
测试替身掩盖（MagicMock 让任意属性访问都成功，掩盖了真实合约不匹配）：

| 级别 | 缺陷 | 修复 |
|---|---|---|
| HIGH | `load_llm_config_for_chat` 返回 **dict** 不是对象；`getattr(config, "model")` 永远 None | `config.get("model")` + 空配置返回 `{"error": "未配置可用的 LLM 端点"}` |
| HIGH | `ServerStatusEntry.since` 是 **float**（time.time 纪元秒）；`.isoformat()` → AttributeError | `datetime.fromtimestamp(since, tz=timezone.utc).isoformat()` |
| HIGH | `Database` 类没有 `execute()`；新建实例还会多开永不关闭的 SQLite 连接 | 改走 `get_database()` 单例 `.get_connection().execute("SELECT 1")`（`_LockedConnection` 内部持锁） |
| HIGH | `estimated_cost_usd` 可能 `None`（模型定价未知）；`:.4f` → TypeError | 复用 `sage_usage_tool._fmt_cost`（None → "未知（模型定价缺失）"） |
| MEDIUM | unresolved session 返回"空结果"而非失败 | `sage_usage` 检测 `{"error": ...}` → `success=False` |
| MEDIUM | `sage_doctor` 的 `include_subprocess_probe` 参数误导（该探测只属于 CLI `run_doctor`，LLM 工具内从未执行） | 删除参数，schema `parameters` 收为 `{}` |
| LOW | `PluginRecord.status/plugin_type` f-string 可能渲染 `PluginStatus.ENABLED` | `getattr(x, "value", x)` 兜底（`use_enum_values=True` 下已为 str，双保险） |

测试同步改用真实合约：LLM config **dict**、真实 `ServerStatusEntry` dataclass
（`since=1700000000.0` float）、`estimated_cost_usd=None` 用例、`get_database`
单例 mock；新增 `test_gather_effective_model_empty_config_is_error` /
`test_gather_health_db_ok` / `test_gather_health_db_failure` /
`test_build_summary_cost_none_path` / `test_sage_usage_unresolved_session_is_failure`
共 5 个测试。

复验：`test_self_status_tool.py` 21 passed、`test_cli_harness.py` +
`test_tool_bundles_parity.py` 25 passed、`slashCommands.test.ts` 14 passed、
ruff 全绿（`UP017` 按 py38 约定 `# noqa`）。

**CI 全绿**：run 42025189740 @ 74ae37680，13/13 必需 job pass
（Architecture / Backend py310 / Backend collect py38 / Dependency audit /
Electron build ubuntu+windows / Electron smoke / Frontend / count-lines /
live-boot / stub-smoke / stub-deep / legacy smoke）。

### 10.4 M1.7 推迟理由（详见 §2.4 escape hatch）

**当前状态**：`update_sage_config` 写入即持久化到 SQLite `settings` 表，但：

- Electron 主进程（settings UI）不监听 backend 写事件 → UI 不实时刷新
- 其他进程（如并行的 worktree 后端）各自读 DB，写入后对其他进程可见（DB 即总线），但 UI 层仍要手动 reload
- Claude 自己改完配置后看到的结果与用户看到的不一致，直到用户刷新或重启

**为什么不在 M1 修**：跨进程广播需要：

1. backend `update_sage_config` 写后触发事件（`asyncio.Queue` 或 WebSocket 推送）
2. Electron 主进程订阅事件 → 通过 `webContents.send` 广播到所有 renderer
3. renderer 的 `useSettingsStore` 订阅 IPC → 触发 React 状态刷新

这是三进程、两套事件总线（backend asyncio + Electron IPC）的桥接工程，与 M3 `sage_admin` 统一命令注册表的"命令即事件源"设计高度重合。在 M1 先做一套 ad-hoc IPC，M3 还要重做 —— 属于"双轨"浪费。

**临时缓解**：M1.5 的 `/config` slash 命令让用户主动查询即可感知变更；`update_sage_config` 工具返回的 output 会列出新值，agent 可直接告诉用户"已改为 X，刷新设置页可见"。

**M3 落地路径**：`sage_admin` 注册表统一所有"管理类命令"（config / permission / schedule / cancel / self_status 等），注册时声明 `broadcast: true` → 框架自动走 backend→Electron→renderer 广播链路；M1.7 的缺口自然被填上。



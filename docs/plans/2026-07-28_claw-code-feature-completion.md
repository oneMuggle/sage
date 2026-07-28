# 参考 claw-code 的功能补全方案

> 创建：2026-07-28 · 状态：待评审 · 类型：跨模块功能补全（多里程碑）

## 1. 背景与目标

### 1.1 参照系

`/home/fz/project/claw-code` 是一个 Claude Code 风格的**终端编码 agent harness**（Rust workspace，11 crates，~115.8k LOC，~1416 个测试）。其强项集中在 **agent harness 核心能力**：

- 55 个可执行工具的完整工具面（文件/搜索/bash/web/git/task/worker/MCP/LSP…）
- 权限安全模型（4 种 permission mode、allow/deny 规则、dispatch 前强制校验、1004 行 bash 静态校验、Linux sandbox、符号链接逃逸检测）
- MCP 硬化（并行发现、per-server 失败隔离、降级模式报告、`mcp__server__tool` 命名空间、stdio 生命周期加固）
- Hooks（PreToolUse/PostToolUse，决策 + 输入重写 + 上下文注入）
- 会话工程（session fork、自动压缩阈值、3-way compact 策略、token/cost 统计）
- 真实子代理线程（Agent 工具 spawn 完整 ConversationRuntime）
- 分层配置（user/project/local 三层合并 + 键级 provenance）

### 1.2 sage 现状定位

sage 是**记忆优先的桌面 AI 助手**（Electron + React + FastAPI），与 claw-code 错位竞争。sage 已领先的领域（**无需补**）：

| 领域 | sage | claw-code |
|---|---|---|
| 调度器 | ✅ 真实 APScheduler + 进化任务 | 🟡 仅 registry 级 stub |
| 技能 | ✅ SKILL.md v2 + agentskills.io 合规 + 热重载 + slash 集成 | 🟡 基础加载/调用 |
| 记忆 | ✅ 三级（工作/情景/语义）+ 向量 + 固化管线 | ⬜ 仅 CLAUDE.md 文件发现 |
| Office/Wiki/进化/主题/i18n/GUI | ✅ | ⬜ 终端产品，无对应物 |

### 1.3 目标

**引入 claw-code 的 "agent harness 核心能力"，不引入终端专属形态**（worker 舰队、tmux trust resolver、ACP、LSP、statusline、vim）。分 7 个里程碑（M0 快速修复 + M1–M6），每个可独立验证、独立走 PR。

## 2. 差距矩阵

| # | 能力 | claw-code | sage 现状 | 动作 | 里程碑 |
|---|---|---|---|---|---|
| G1 | 工具安全：permission mode / bash 校验 / 工作区边界 | ✅ 完整 | ⬜ 仅 ToolPolicy 限额限流，`terminal` 可执行任意命令 | **移植** | M1 |
| G2 | GUI 权限审批（approve/deny + 规则记忆） | 🟡 CLI prompter | ⬜ | **新建（桌面化超越）** | M1 |
| G3 | 工具面：edit_file / glob / grep / TodoWrite / StructuredOutput / REPL | ✅ | ⬜（仅 11 个工具，无精确编辑与搜索工具） | **移植** | M2 |
| G4 | AskUserQuestion（agent 向用户提问） | ✅（CLI） | ⬜ | **新建（GUI 对话框，差异化）** | M2 |
| G5 | Skill 作为 in-loop 工具 | ✅ `execute_skill` | ⬜ `ChatService skills=None`（"P3 接入"） | **修复 + 移植** | M2 |
| G6 | MCP 多服务器配置 + 生命周期 + 降级报告 | ✅ 硬化 | 🟡 仅 drawio 单服务器；lifecycle 状态机是死代码 | **接线 + 移植** | M3 |
| G7 | `/compact` 端到端 + 自动压缩阈值 | ✅ compact.rs | 🟡 前端 slash 存在，后端未端到端接通 | **移植** | M4 |
| G8 | 会话分叉（fork） | ✅ Session::fork | ⬜ | **移植（DB copy-on-write）** | M4 |
| G9 | 编排 E2E：Planner LLM 注入 / lane 创建 API / in-loop Agent 工具 | ✅ execute_agent | 🟡 Planner 默认 `llm_client=None`；API 只读+取消 | **补全** | M5 |
| G10 | Hooks 系统 | 🟡 3 事件 | ⬜ | **移植**（契合"透明可控"） | M6 |
| G11 | Cost/token 用量面板 | ✅ /cost | ⬜ 无用户可见面板 | **移植** | M6 |
| G12 | 项目级指令文件发现（SAGE.md/CLAUDE.md 层级） | ✅ ProjectContext | ⬜（有 workspace 绑定，无指令文件） | **移植** | M6 |
| G13 | Mock LLM parity 测试 harness | ✅ 12 脚本场景 | ⬜ | **移植思路** | M6 |
| Q1 | `wiki_router` 重复注册 | — | ✅ 已删除重复行 + 回归测试 | — | M0 ✅ |
| Q2 | `chat_stream` 裸 RuntimeError | — | ✅ LLMError 分类（Task 11 关闭） | — | M0 ✅ |
| Q3 | `HttpComputeAdapter` 空壳 | — | ✅ 已删除（YAGNI，仅保留 subprocess） | — | M0 ✅ |
| Q4 | `API_MODE` 强制 legacy（hex DI 未完） | — | 🟡 临时回退 | 归入 M2/M5 收尾 | M0 记录 |

**明确不移植**（终端专属 / 与 sage 定位冲突）：Worker 舰队 + trust resolver、ACP/Zed、LSP 工具（若未来转 coding-first 再评估）、PowerShell（terminal 覆盖）、telemetry ClientIdentity 伪装、statusline/vim/键位。Git 工具组列为 P4 可选（开发者用户增值）。

## 3. 涉及的文件与模块

### M0 快速修复
- `backend/main.py`（删重复 wiki_router）
- `backend/core/legacy/llm_client.py`（chat_stream → LLMError 分类）
- `backend/adapters/out/compute/http_adapter.py`（实现或删除）

### M1 工具安全硬化
- 新增 `backend/tools/permissions.py`（PermissionMode 枚举 + PermissionEnforcer，参照 claw `permission_enforcer.rs`）
- 新增 `backend/tools/bash_validation.py`（破坏性命令启发式、只读模式判定，参照 claw `bash_validation.rs`，**Py3.8 重写**）
- 改 `backend/tools/file_tool.py`（工作区边界 + 符号链接逃逸 + 大小上限，参照 claw `file_ops.rs:739`）
- 改 `backend/tools/registry.py`（dispatch 前强制校验钩子）
- 新增前端 `widgets/permission/ApprovalDialog.tsx` + IPC 通道 `sage:permission:ask/answer`
- 设置项：`permissions.default_mode` / `permissions.rules`（扩 settings_repo 白名单）

### M2 工具面扩展
- 新增 `backend/tools/edit_tool.py`、`search_tool.py`（glob/grep）、`todo_tool.py`、`structured_output_tool.py`、`repl_tool.py`（复用 skill_script 沙箱）、`ask_user_tool.py`
- 改 `backend/adapters/out/skill/inproc.py` + `backend/main.py`（SkillPort 接线，消除 `skills=None`）
- 前端：`ApprovalDialog` 泛化为工具交互对话框（AskUserQuestion 复用）

### M3 MCP 多服务器
- 改 `backend/mcp/config.py`（多服务器配置 schema：name/command/args/env/required）
- 接线 `backend/mcp/lifecycle/` 状态机到生产 `McpClient`（或删除并说明）
- 新增降级报告模型（参照 claw `McpDegradedReport`）+ `GET /mcp/status` 路由
- 前端：Settings 新增 MCP 标签页 + 降级状态展示

### M4 会话工程
- 改 `backend/core/legacy/agent.py` + 新增 `backend/chat/compaction.py`（token 估算 + 阈值 + 延续消息，参照 claw `compact.rs`）
- 新增 `POST /sessions/{id}/fork` 路由 + messages 表 copy-on-write
- 前端：会话右键菜单「从此分叉」+ `/compact` 后端接通

### M5 编排 E2E
- 改 `backend/orchestration/planner.py`（默认注入 LLMClient）
- 新增 `POST /orchestration/lanes` 创建端点 + 前端入口
- 新增 `backend/tools/agent_tool.py`（in-loop 子代理 spawn，参照 claw `execute_agent`；子代理独立工具白名单）

### M6 生态扩展
- 新增 `backend/hooks/`（PreToolUse/PostToolUse + decision/updated_input，参照 claw `hooks.rs`）
- 新增用量面板：`backend/services/usage_tracker.py`（per-model 定价表）+ 前端状态卡
- 新增 `backend/chat/project_context.py`（SAGE.md/CLAUDE.md 向上发现 + git 上下文，参照 claw `prompt.rs`）
- i18n 补齐：Office/Orchestration 页硬编码中文
- 新增 `backend/tests/parity/`（mock OpenAI-compatible 服务器 + 脚本场景，参照 claw `mock-anthropic-service`）

## 4. 技术方案要点

### 4.1 权限模型（M1 核心）

```python
class PermissionMode(str, Enum):          # 参照 claw PermissionMode
    READ_ONLY = "read_only"               # 拒所有写/执行
    WORKSPACE_WRITE = "workspace_write"   # 工作区内写，bash 需审批
    PROMPT = "prompt"                     # 逐次 GUI 审批
    FULL_ACCESS = "full_access"           # 全放行（显式 opt-in）
```

- Enforcer 挂在 `ToolRegistry.execute()` dispatch **之前**（claw 的关键设计：拒绝发生在工具执行前）
- bash 静态校验分级：**警告**（破坏性命令高亮）→ 后续版本再升级为**拦截**，避免误杀
- GUI 审批走现有 NDJSON 流：agent 流发 `permission_request` 事件 → 前端对话框 → `sage:invoke permission_answer` → 后端 Future 唤醒。与 M2 AskUserQuestion 共用同一机制
- 规则持久化复用 `settings_repo` 白名单机制（新增 `permission_rules` 键）

### 4.2 AskUserQuestion 的桌面化（M2 差异化）

claw-code 的 CLI 实现是弱项；sage 的 GUI 天然适合：工具调用 → 流内事件 → 前端渲染选项卡片 → 用户选择注入 `role: tool` 结果。**需要 agent loop 支持异步挂起**（等待用户期间释放线程，用 `attach_chat_stream` 模式重连）。这是本方案中设计风险最高的一项，先做 spike。

### 4.3 会话分叉（M4）

messages 表加 `fork_root` / `branch_point` 列，copy-on-write：fork 时仅复制元数据 + 共享历史前缀的只读引用，新分支消息独立追加。避免大对话整表复制。

### 4.4 不移植 hex/legacy 之争

新工具一律先注册到 **legacy registry**（当前默认 API_MODE）；hex 迁移（Q4）完成时批量移植到 SkillPort/ToolPort。避免双线重复劳动。

### 4.5 Win7 LTS 兼容（横切硬约束）

所有后端移植代码**必须** Python 3.8 + pydantic 1.x 兼容：无 `match`、无 `X | Y` 注解、无 `typing.Self`。每个 M 的测试在 `sage-backend`（3.11）与 `sage-backend-py38`（3.8）双环境跑。claw 的 Rust 代码仅作行为参照，不逐行翻译。

## 5. 实施步骤

- [ ] **M0：存量缺陷速修**（~0.5 天，`fix/hygiene-2026-07`）
  - [x] 删除 `main.py:348` 重复 wiki_router + 回归（`backend/tests/api/test_router_registration.py`）
  - [x] `chat_stream` RuntimeError → LLMError 分类（关闭 Task 11；`LLMClient._raise_classified_error` 与 `chat()` 共享分类）
  - [x] HttpComputeAdapter：已删除（YAGNI 决策；仅保留 `adapter: subprocess`，docs 已同步）
  - [ ] 记录 API_MODE hex 回归的收尾条件到 Q4 跟踪项
- [ ] **M1：工具安全硬化**（~3–5 天，`feat/tool-permission-hardening`）⭐ 最高优先
  - [ ] PermissionMode + Enforcer + 单测矩阵（参照 claw path_scope_enforcement）
  - [ ] bash_validation Py3.8 移植 + 破坏性命令警告单测
  - [ ] file_tool 边界/符号链接/大小守卫
  - [ ] GUI 审批对话框 + IPC + e2e（Playwright）
- [ ] **M2：工具面扩展 + Skill 接线**（~4–6 天，`feat/agent-tool-surface`）
  - [ ] AskUserQuestion 异步挂起 spike（先验证，阻塞则降级为同步确认）
  - [ ] edit_file / glob / grep / TodoWrite / StructuredOutput / REPL
  - [ ] SkillPort 接线（消除 skills=None）+ in-loop Skill 工具
- [ ] **M3：MCP 多服务器**（~3–4 天，`feat/mcp-multi-server`）
  - [ ] 多服务器配置 schema + Settings UI 标签页
  - [ ] lifecycle 状态机接线生产客户端 + 降级报告 + `/mcp/status`
  - [ ] 故障演练：drawio + 第二服务器，杀进程验证隔离
- [ ] **M4：会话工程**（~3–4 天，`feat/session-compact-fork`）
  - [ ] compaction 模块 + 自动阈值 + `/compact` 端到端
  - [ ] fork 路由 + DB copy-on-write + 前端入口
- [ ] **M5：编排 E2E**（~4–5 天，`feat/orchestration-e2e`）
  - [ ] Planner LLM 注入 + lane 创建 API + 前端入口
  - [ ] in-loop Agent 工具 + LaneBoard 实时子代理可视化
- [ ] **M6：生态扩展**（~5–8 天，可拆多个分支）
  - [ ] Hooks 系统（Pre/PostToolUse + decision）
  - [ ] 用量/成本面板
  - [ ] SAGE.md/CLAUDE.md 项目指令发现
  - [ ] i18n 补齐 + Mock LLM parity harness

**节奏**：单线程滚动约 3–5 周。M0/M1 可立即开始；M2 依赖 M1 的审批通道（AskUserQuestion 复用 GUI 对话框）。

## 6. 风险评估与依赖

| 风险 | 等级 | 缓解 |
|---|---|---|
| bash 静态校验误杀合法命令 | 中 | M1 先"警告不拦截"，收集样本后再升级；保留 FULL_ACCESS 逃生门 |
| AskUserQuestion 需 agent loop 异步挂起，改动面大 | 高 | M2 首项做 spike；失败则降级为同步阻塞确认（功能在、体验弱） |
| 会话分叉 messages 表膨胀 | 中 | copy-on-write 设计；fork 链深度上限 3 |
| 双分支兼容（Py3.11/pydantic2 vs Py3.8/pydantic1） | 中 | 每 M 双环境 CI；禁用新语法；cherry-pick 时人工核对 |
| hex/legacy 双轨导致工具注册重复劳动 | 低 | 新工具只进 legacy registry，hex 收尾时统一移植（Q4） |
| MCP lifecycle 死代码接线可能暴露设计不匹配 | 中 | M3 先评估接线成本，超 1 天则推倒重写（参照 claw manager，~400 行量级） |
| 权限 GUI 审批阻塞 agent 流的超时语义 | 中 | 审批等待设 5 分钟超时 → 默认 deny + 事件记录 |

**依赖**：
- M2 AskUserQuestion ← M1 GUI 审批通道
- M5 Agent 工具 ← M1 权限模型（子代理工具白名单需要 mode 概念）
- M6 parity harness 建议放最后，覆盖前序 M 的行为回归

## 7. 验证标准（Definition of Done）

每个里程碑：
1. 单测 + 集成测试覆盖 ≥80%，`sage-backend` 与 `sage-backend-py38` 双环境绿
2. 涉及 UI 的 M 附 Playwright e2e 用例
3. CI 全绿 → code-reviewer agent 审查 → 无 CRITICAL/HIGH → 用户 merge
4. 功能点并入 `docs/technical/` 对应章节后删除本文件中已完成项

---

**附：claw-code 参照文件索引**（移植时对照阅读）

| sage 目标 | claw-code 参照 |
|---|---|
| permissions.py | `rust/crates/runtime/src/permission_enforcer.rs`、`permissions.rs` |
| bash_validation.py | `rust/crates/runtime/src/bash_validation.rs`（1004 行） |
| file_tool 守卫 | `rust/crates/runtime/src/file_ops.rs`（:739 符号链接） |
| edit/search/todo 工具 | `rust/crates/runtime/src/file_ops.rs`、`tools/src/lib.rs:3744`（TodoWrite） |
| AskUserQuestion | `tools/src/lib.rs` dispatch :1453 |
| MCP 降级报告 | `rust/crates/runtime/src/mcp.rs`（McpDegradedReport）、`mcp_lifecycle_hardened.rs` |
| compaction | `rust/crates/runtime/src/compact.rs`、`trident.rs` |
| Agent 工具 | `tools/src/lib.rs:4091-4280` |
| hooks | `rust/crates/runtime/src/hooks.rs`（1151 行） |
| 用量统计 | `rust/crates/runtime/src/usage.rs` |
| 项目上下文发现 | `rust/crates/runtime/src/prompt.rs`（:96-409） |
| parity harness | `rust/crates/mock-anthropic-service/`、`rusty-claude-cli/tests/mock_parity_harness.rs` |

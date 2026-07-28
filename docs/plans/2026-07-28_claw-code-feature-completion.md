# claw-code 功能补齐计划（2026-07-28）

## 背景与目标

把 claw-code（Rust Claude-Code 风格 harness）中已验证的安全/执行机制
移植到 sage，适配桌面 GUI 形态。参考实现:

- `claw-code/rust/crates/runtime/src/permission_enforcer.rs` — 先执行许可、后分发
- `claw-code/rust/crates/runtime/src/permissions.rs` — 模式与规则
- `claw-code/rust/crates/runtime/src/bash_validation.rs` — 破坏性命令启发式
- `claw-code/rust/crates/runtime/src/file_ops.rs` — symlink 逃逸检测、尺寸限额

## M1 — 工具安全加固

### 后端（已完成）

- [x] `backend/tools/permissions.py` — PermissionMode / ToolCapability /
      PermissionDecision / PermissionRule / PermissionEnforcer（规则优先级
      deny > allow > ask > 模式矩阵；破坏性命令安全网升级）
- [x] `backend/tools/bash_validation.py` — BashRisk 三档 + 纯函数
      validate_bash（claw bash_validation.rs 实用子集 + Win7 桌面补充规则）
- [x] `backend/tools/file_tool.py` 加固 — 读 5 MiB / 写 10 MiB 硬限额、
      8 KiB NUL 二进制嗅探、WRITE 强制 workspace 边界（realpath 语义，拦
      ../ 穿越 + symlink 逃逸）、READ 不强制边界（读写非对称）
- [x] 执行卡点 — `SageAgent.run_loop` / `execute_tool` 在分发前检查许可；
      拒绝注入 "权限拒绝: <reason>" 错误 ToolResult，循环优雅继续
- [x] `backend/services/permission_gate.py` — ApprovalGate（Future 挂起/
      解析、超时 default-deny、参数脱敏摘要）+ 单例访问器（lifespan 装配）
- [x] `backend/api/permission_routes.py` — GET /api/v1/permissions/pending、
      POST /api/v1/permissions/{request_id}/answer（remember → 规则持久化）
- [x] 流事件 — AgentState.PERMISSION_REQUEST + AgentEvent.permission_request
- [x] settings 白名单 — permission_mode（默认 workspace_write）/
      permission_rules（默认 []）
- [x] 测试 — 单元（enforcer 矩阵 ~24 例、bash ~20 例、file 加固、gate）+
      API 契约 + run_loop 审批/拒绝/超时集成

### 前端（已完成）

- [x] GUI 审批对话框 + IPC + e2e（Playwright） — 消费 permission_request
      流事件，渲染 ApprovalDialog（风险徽章 / 参数预览 / 记住选择），
      POST 应答端点；electron/commands.ts 补 permissions_pending +
      permissions_answer 路由（body selector 防 extra 字段 422）；
      设置页权限模式选择器（preferences KV: permission_mode）；
      tests/electron/permission-approval.spec.ts 走 stub_backend 审批
      gate 全链路（批准/拒绝双路径）

## M2 — agent 工具面扩展

移植 claw-code tool surface 中 sage 缺失的 6 个工具（M2 part A）：

- [x] agent 工具面: edit_file / glob / grep / TodoWrite / StructuredOutput / REPL
      — `edit_tool.py`（精确字符串替换编辑，WRITE，复用 M1 写限额 + workspace
      边界 + 二进制/BOM 嗅探）、`search_tools.py`（glob_search mtime 倒序
      上限 200 / grep_search content·files 双模式 + 非法正则干净报错，READ，
      复用 NUL/BOM 嗅探跳过二进制）、`todo_state.py` + `todo_tool.py`
      （会话级内存桶全量替换语义，READ——agent 内部草稿态无用户数据副作用）、
      `structured_output_tool.py`（会话级载荷存储 + 可选 schema 校验，
      jsonschema 可缺省 → 内置 {type,properties,required,items} 最小校验器，
      READ）、`repl_tool.py`（sys.executable -I 隔离子进程，100 KiB 输出
      截断，超时杀进程，EXECUTE 由 M1 审批矩阵门控）；permissions.py 能力
      分类表 + __init__.py 注册同步扩展
- [x] agent 工具面续: SkillPort 接线 + in-loop Skill 工具 + AskUserQuestion
      （M2 part B）— `_build_chat_service` 关闭 `skills=None` TODO（装配
      InprocSkillAdapter，与 /api/v1/skills* REST 同源）；`skill_tool.py`
      （name=skill，EXECUTE，复用 REST 单例 + execute_command/execute 既有
      执行路径，脚本走 script_runner 沙箱不旁路）；AskUserQuestion 无需
      spike —— 异步 gate 模式已被 M1 ApprovalGate 证明，直接同构复制为
      `question_gate.py`（超时 fail-open-ish 空应答，agent 永不挂起）：
      `ask_user_tool.py` 纯渲染器 + run_loop 分发前特判（校验 question
      非空 / options 2-4 项带 label，发 ask_user_question 事件，await 闸口，
      注入 answers/custom 执行）+ `question_routes.py`（复用 permission
      Origin 守卫）+ QuestionDialog 前端（单选 radio / 多选 checkbox 卡片 +
      "其他"自由文本 + Escape 空提交）+ question-answer.spec.ts E2E

### 实施步骤

- [x] 步骤 1：edit_tool / search_tools / todo_state + todo_tool /
      structured_output_tool / repl_tool 五模块（py3.8 兼容）
- [x] 步骤 2：register_all_tools 注册 + TOOL_CAPABILITIES 分类表扩展
- [x] 步骤 3：单元测试（edit 16 / search 22 / todo 16 / structured 15 /
      repl 23 / 能力表 1）+ run_loop 集成（grep→edit 往返、边界拒绝、
      repl PROMPT 审批）
- [x] 步骤 4：M2 part B（SkillPort 接线 + in-loop Skill 工具 +
      AskUserQuestion）完成。测试: question gate 21 + question routes 13 +
      skill tool 12 + run_loop question flow 6（pytest）；questionState 7 +
      QuestionDialog 12 + useChat 接线 3 + commands guard 4（vitest）；
      question-answer.spec.ts 2 E2E + permission/smoke 回归 4 绿

## 涉及的文件与模块

| 层 | 文件 | 变更 |
| --- | --- | --- |
| 工具域 | backend/tools/permissions.py | 新增（M2: 能力表扩 6 工具） |
| 工具域 | backend/tools/bash_validation.py | 新增 |
| 工具域 | backend/tools/file_tool.py | 加固 |
| 工具域 | backend/tools/edit_tool.py | M2 新增（精确编辑，WRITE） |
| 工具域 | backend/tools/search_tools.py | M2 新增（glob/grep，READ） |
| 工具域 | backend/tools/todo_state.py、todo_tool.py | M2 新增（会话 todo 桶，READ） |
| 工具域 | backend/tools/structured_output_tool.py | M2 新增（结构化输出，READ） |
| 工具域 | backend/tools/repl_tool.py | M2 新增（隔离 REPL，EXECUTE） |
| 工具域 | backend/tools/__init__.py | M2 注册 6 工具 |
| 服务 | backend/services/permission_gate.py | 新增 |
| API | backend/api/permission_routes.py | 新增 |
| Agent | backend/core/legacy/agent.py、agent_state.py | 接线 + 新事件 |
| 存储 | backend/data/settings_repo.py | 白名单扩 2 key |
| 装配 | backend/main.py | lifespan + 路由注册 |
| IPC | electron/commands.ts | permissions_pending / permissions_answer 路由 |
| 状态 | src/entities/permission/permissionState.ts | 新增 zustand store |
| 界面 | src/widgets/permission/ApprovalDialog.tsx | 新增全局审批模态框（App.tsx 挂载） |
| 流事件 | src/features/send-message/useChat.ts、src/shared/api/types.ts | permission_request 接线 + AgentEvent 类型 |
| 设置 | src/pages/settings/GeneralTab.tsx | 权限模式选择器（preferences KV） |
| i18n | src/shared/lib/i18n/zh.ts、en.ts | 对话框 + 设置键 |
| E2E | tests/electron/permission-approval.spec.ts、stub_backend.py | 审批 gate 桩 + Playwright 双路径 |
| 服务 | backend/services/question_gate.py | M2b 新增（UserQuestionGate，ApprovalGate 同构） |
| API | backend/api/question_routes.py | M2b 新增（pending + answer，复用 Origin 守卫） |
| 工具域 | backend/tools/skill_tool.py、ask_user_tool.py | M2b 新增（skill=EXECUTE / ask_user_question=READ 纯渲染器） |
| Agent | backend/core/legacy/agent.py、agent_state.py | M2b ask_user_question 分发前特判 + ASK_USER_QUESTION 事件 |
| 装配 | backend/main.py | M2b skills=InprocSkillAdapter（关闭 skills=None TODO）+ question gate lifespan |
| IPC | electron/commands.ts | M2b questions_pending / questions_answer 路由 |
| 状态 | src/entities/question/questionState.ts | M2b 新增 zustand store |
| 界面 | src/widgets/question/QuestionDialog.tsx | M2b 新增全局提问模态框（App.tsx 挂载） |
| 流事件 | src/features/send-message/useChat.ts、src/shared/api/types.ts | M2b ask_user_question 接线 + UserQuestion 类型 |
| E2E | tests/electron/question-answer.spec.ts、stub_backend.py | M2b 提问 gate 桩 + Playwright 双路径 |

## 风险评估

- **双分支兼容**: 全部新代码通过 py3.8 语法编译验证（release/win7 复用）。
  特别地，`except asyncio.TimeoutError` 保留（py3.8 与内建 TimeoutError 不同源）。
- **行为变更**: READ/list_dir 不再强制 workspace 边界（M3 旧行为有意改为
  claw 读写非对称）；对应旧测试已同步更新。
- **失败模式**: settings/DB 不可用 → 默认 workspace_write enforcer；
  gate 未初始化或超时 → default-deny（fail-closed）。

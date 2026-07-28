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

### 前端（待实施）

- [ ] GUI 审批对话框 — 消费 permission_request 流事件，渲染对话框，
      POST 应答端点（需同步补 electron/commands.ts COMMAND_ROUTES）

## 涉及的文件与模块

| 层 | 文件 | 变更 |
| --- | --- | --- |
| 工具域 | backend/tools/permissions.py | 新增 |
| 工具域 | backend/tools/bash_validation.py | 新增 |
| 工具域 | backend/tools/file_tool.py | 加固 |
| 服务 | backend/services/permission_gate.py | 新增 |
| API | backend/api/permission_routes.py | 新增 |
| Agent | backend/core/legacy/agent.py、agent_state.py | 接线 + 新事件 |
| 存储 | backend/data/settings_repo.py | 白名单扩 2 key |
| 装配 | backend/main.py | lifespan + 路由注册 |

## 风险评估

- **双分支兼容**: 全部新代码通过 py3.8 语法编译验证（release/win7 复用）。
  特别地，`except asyncio.TimeoutError` 保留（py3.8 与内建 TimeoutError 不同源）。
- **行为变更**: READ/list_dir 不再强制 workspace 边界（M3 旧行为有意改为
  claw 读写非对称）；对应旧测试已同步更新。
- **失败模式**: settings/DB 不可用 → 默认 workspace_write enforcer；
  gate 未初始化或超时 → default-deny（fail-closed）。

# Workspace MCP Server — M5a：审批模式 + token 加密

> 上位方案：`docs/plans/2026-09-26-workspace-mcp-server.md` §7.3、§10(M5)
> 依赖：#1639（M4）
> M5 拆分：**M5a**（本文）= 审批 `ask` + DESTRUCTIVE 强制审批 + token 静态加密；
> **M5b**（后续）= Office / 记忆工具。

## 1. 审批

### 1.1 规则

| 工作区 approval | 读类工具 | 写类（write/edit/apply_patch） | run_command | cancel / get_output |
|---|---|---|---|---|
| `auto` | 直接执行 | 直接执行 | `validate_bash` 判 DESTRUCTIVE 时**强制审批**，否则直接执行 | 直接执行 |
| `ask` | 直接执行 | 审批 | 审批 | 直接执行 |

- 审批超时 120 秒 → 拒绝（`APPROVAL_DENIED: timeout`）。
- 审批期间急停 / 撤权 / 轮换 token：批准后执行前**再次**校验，失败返回 `ACCESS_REVOKED`。
- 审批通道不可用（gate 未初始化、主事件循环未知）→ fail-closed：`APPROVAL_UNAVAILABLE`。
- “记住选择”对远程请求无效：工具名使用 `remote_mcp.<tool>` 命名空间，即便被持久化成规则也不会命中 Sage 自身 agent 的工具。

### 1.2 实现

- 复用 `backend/services/permission_gate.py` 的全局 `ApprovalGate`：
  - `ApprovalRequest.create(<真实工具名>, args, risk, message, workspace_root=root)` 以便生成写类 diff 预览，再 `dataclasses.replace(tool_name="remote_mcp.<tool>")`。
  - gate 的 Future 属于**主后端事件循环**；远程工具在监听器线程池里执行，用 `asyncio.run_coroutine_threadsafe(gate.request(...), main_loop)` 提交并阻塞等待。
  - 主循环在管理 API 上用 router 级 async 依赖捕获（监听器只能经管理 API 启动，所以启动前一定已捕获）。
- Telegram 网关已轮询 `gate.pending()` 转发新请求 → 远程审批自动可在 Telegram `/approve` `/deny`。
- 前端：`useRemoteApprovalPoller`（挂在 `App` 的 `ApprovalDialog` 旁）每 3 秒拉 `permissions_pending`，把 `remote_mcp.*` 请求推进 `usePermissionState`（会话键 `__remote_mcp__`），现有 `ApprovalDialog` 负责展示与应答；请求在别处被应答或超时后自动移除。
- 设置页工作区卡片新增“审批：自动 / 每次询问”选择。

## 2. token 静态加密

- 落盘字段由 `token` 改为 `token_enc = secret_box.encrypt_secret(token, account="remote-mcp:<id>")`（Windows DPAPI、macOS keychain、Linux secret-tool；无后端时诚实降级为明文，与其它密钥一致）。
- 内存中保持明文用于常量时间比对。
- 旧文件里的明文 `token` 在加载后立即迁移重写。
- 解密失败（换机器 / 换用户）→ 该工作区 token 重新生成、`enabled=false`、`token_reset=true`，UI 提示“需重新复制地址”，审计 `workspace.token_reset`。

## 3. 测试

- `test_remote_mcp_approval.py`：ask 模式写/命令走审批（批准执行、拒绝不执行）；auto 模式非破坏命令不审批、`rm -rf /` 强制审批；审批中急停 → ACCESS_REVOKED；gate 缺失 → APPROVAL_UNAVAILABLE；请求工具名带 `remote_mcp.` 前缀且有 diff 预览；真实 ApprovalGate + 独立事件循环线程的端到端。
- store：落盘无明文 token（`SAGE_SECRET_SCHEME=test`）、旧明文迁移、解密失败重置并停用、approval 校验。
- 前端：poller 推入 / 移除；设置页审批选择。

# 后台任务收尾 · Phase 3（Windows 持久化 / 流式输出 / Webhook / win7 审批闸）

> 日期：2026-11-06
> 分支：`feat/background-task-phase3`（main）；win7 同步另起分支
> 状态：实施中

## 背景

Phase 0–2 已交付后台任务一等公民全链路（双分支）。剩余四项收尾：

1. **Windows 注册表持久化** —— 当前 `ResurrectedProcess` 仅 POSIX；
   `get_registry()` 在 Windows 上不接持久化。
2. **后台输出流式推送** —— 目前只有轮询式 `bash_output` / `wait_background`，
   UI 无法实时看后台任务输出。
3. **Webhook / Slack 外发** —— 完成通知只在本机弹窗。
4. **win7 M0 SELF_MODIFY 审批闸** —— win7 缺 main 的自管理工具逐次审批，
   `wake_session_at` / `wake_on_background` 仅靠默认 WRITE 兜底。

## 交付拆分（PR）

| PR | 分支 | 内容 |
|---|---|---|
| 1 | main | Windows 注册表持久化 |
| 2 | main | 后台 shell 列表 + 输出流式推送（NDJSON） |
| 3 | main | Webhook / Slack 外发（Electron 轮询器） |
| 4 | win7 | cherry-pick PR 1–3 + py38 适配 |
| 5 | win7 | M0 SELF_MODIFY 审批闸（最小实现 + 评估记录） |

## Item 1: Windows 注册表持久化

### 方案
- `subprocess_util.py`：
  - 新增 `_IS_WINDOWS` 模块常量与 `_windows_process_alive(pid)`：
    `tasklist /FI "PID eq <pid>" /FO CSV /NH` 输出包含 `"<pid>"` → 存活；
    2s TTL 缓存避免 status() 高频 spawn。
  - `ResurrectedProcess.poll()`：`_IS_WINDOWS` 分支走 `_windows_process_alive`；
    POSIX 分支保持 pgid 校验。
- `bash_session.py`：
  - `get_registry()` 去掉 `os.name != "nt"` 门控，两平台都注入 store。
  - `restore()` 去掉 Windows 早退：统一走 `ResurrectedProcess`（内部按平台分支）；
    输出文件身份校验不变（`file_identity` 两平台可用）。
- 语义差异记录：Windows 的 PID 复用检测弱于 POSIX（tasklist 只验存活），
  可接受的降级（taskkill /T 仍能安全终止）。

### 测试
- `test_subprocess_util_resurrect.py` 增加 Windows 分支测试（monkeypatch
  `_IS_WINDOWS=True` + mock `subprocess.run`）：alive / dead / tasklist 失败 fail-closed。
- 恢复路径测试复用 FakeStore（POSIX），Windows 分支由上述单元覆盖。

## Item 2: 后台 shell 列表 + 输出流式推送

### 方案
- 后端新路由 `backend/api/shell_routes.py`：
  - `GET /api/v1/shells` → 列出注册表中 shells（shell_id/command/status/
    started_at/pid）。
  - `GET /api/v1/shells/{shell_id}/stream` → NDJSON：
    每 0.5s `read_increment`，输出事件 `{"type":"output","stream":"stdout|stderr","data":...}`；
    退出时 `{"type":"exit","exit_code":...}` 并结束；未知 id 返回 404。
  - 挂载 main.py。
- Electron：
  - `commandRoutes` 新增 `shell_list`（GET `/api/v1/shells`）。
  - `sage:listen` 识别 `shell-stream-{shellId}` → relay `/api/v1/shells/{id}/stream`
    （复用既有 NDJSON relay）。
- 前端：
  - `ProgressSection` 新增「后台任务」区块（`BackgroundShellsSection`）：
    列表来自 `shell_list`，点击展开 `ShellStreamPanel`。
  - `ShellStreamPanel`：`desktopEvent.listen('shell-stream-{id}')` 累积输出，
    退出后停止；提供关闭按钮。
  - 测试：列表渲染、流事件累积、退出停止。

## Item 3: Webhook / Slack 外发

### 方案
- 扩展现有 `notificationPrefs`（Electron 主进程 JSON，Phase 0 已建）：
  - 新增 `webhookUrl: string`（通用 JSON POST）、`slackWebhookUrl: string`。
- `electron/schedulerNotifications.ts`：
  - poller 对每条通知额外调用 webhook 外发（deps 注入 `deliver`，便于测试）。
  - 通用 POST：`{"type":"sage_notification", "kind","title","body",
    "status","session_id","created_at"}`；Slack：`{"text": "title\nbody"}`。
  - 外发失败只记日志，不重试（下一条通知不阻塞）。
- 设置 UI：`NotificationPrefsCard` 增加两个 URL 输入（保存到同一 JSON）。
- 测试：mock fetch，验证 payload/失败隔离/未配置跳过。

## Item 4: win7 M0 SELF_MODIFY 审批闸（最小实现）

### 方案（win7-only）
- win7 `backend/tools/permissions.py`：
  - 新增 `SELF_MODIFY_TOOLS: FrozenSet[str]`（`update_sage_config`、
    `schedule_task`、`cancel_scheduled_task`、`wake_session_at`、
    `wake_on_background`）。
  - 在 win7 的裁决函数（`_mode_decision` 等价处）加入：READ_ONLY 拒绝、
    WORKSPACE_WRITE/PROMPT 升级为 needs_approval、FULL_ACCESS 放行；
    显式 allow 规则仍可放行（与 main 语义一致）。
- 能力表补齐 win7 已注册的自管理工具（`read/update_sage_config`、
    `list/cancel_scheduled_task`、`wake_session_at` 等）——按 win7 实际
    `ALL_BUILTIN_TOOL_NAMES` 差集补登记。
- 测试：win7 权限执行器增加 SELF_MODIFY 模式矩阵用例；
  不引入 main 的全量 M0 表（评估记录：全量对齐需 M0 提交整体移植，
  涉及 session rules / path boundary 等 win7 未就位能力，另立任务）。

## 实施步骤

- [x] M0: 本 plan 文档
- [ ] M1: Item 1（Windows 持久化）+ 测试
- [ ] M2: Item 2（列表 + 流式）+ 测试
- [ ] M3: Item 3（Webhook）+ 测试
- [ ] M4: main 依次 PR → CI → 合并
- [ ] M5: win7 同步 PR（1–3）
- [ ] M6: win7 M0 闸 PR
- [ ] M7: 全量验证与记忆更新

## 风险

| 风险 | 缓解 |
|---|---|
| tasklist 每次 poll 都 spawn | 2s TTL 缓存 |
| 流式端点持有连接数 | 前端一次只开一个面板；退出自动结束 |
| Webhook 阻塞轮询器 | fire-and-forget + try/catch；5s timeout |
| win7 权限表与实际工具差集漂移 | 测试断言差集为空 |
| win7 M0 最小闸与 main 语义偏差 | 仅实现 SELF_MODIFY 规则，记录未对齐项 |

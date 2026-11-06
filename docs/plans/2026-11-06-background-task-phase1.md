# 后台任务一等公民能力 · Phase 1

> 日期：2026-11-06
> 分支：`feat/background-task-phase1`
> 状态：实施中

## 背景

Phase 0（#2887）已交付：通知偏好、任务栏注意力、定时任务/待办→OS 通知、
`wake_session_at` LLM 工具（A4 Suspend-Resume 暴露给 LLM）。

Phase 0 报告明确指出剩余缺口：

1. **后台 Bash 没有"完成时自动唤醒 agent"语义** —— `wake_on(job_id)` 在
   `domain/wake.py` 与 `WakeStore` 都已就位（COMPLETION kind），但生产路径
   零调用者（grep 仅命中定义与测试）。
2. **后台 Bash 完成时无 OS 通知** —— BashSessionRegistry 进程内内存表，
   退出只在 `bash_output` 被主动轮询时被发现；用户切走后无法感知。
3. **BashSessionRegistry 跨重启丢失** —— 持久化列入 Phase 2（本次不实施）。

Phase 1 目标：把后台 Bash 升级为一等公民 —— agent 可以"把命令挂到后台、
登记完成唤醒、到点自动恢复"，并在完成时推一条 OS 通知。复用 Phase 0 的
通知 drain 端点与 Electron 15s 轮询器。

## 涉及的文件与模块

### 后端
- `backend/tools/bash_session.py`：新增 `_exit_watches` + `register_watcher` +
  daemon 轮询线程（`_ExitWatcherThread`）。
- `backend/services/background_notifications.py`：新模块，bounded deque +
  `push()` / `drain()`。
- `backend/api/scheduled_router.py`：drain 端点追加 `background_tasks` 源。
- `backend/tools/wake_on_background_tool.py`：新 LLM 工具 `wake_on_background`。
- `backend/tools/wait_background_tool.py`：新 LLM 工具 `wait_background`。
- `backend/tools/tool_bundles.py`：注册到 `shell` bundle。
- `backend/domain/tool_names.py`：新增 `BACKGROUND_TASK_TOOLS` 组并入
  `ALL_BUILTIN_TOOL_NAMES`。
- `backend/tools/permissions.py`：`TOOL_CAPABILITIES` 登记
  `wake_on_background`（WRITE）/ `wait_background`（READ）。

### 前端
- 无改动 —— 复用 Phase 0 的 `TaskbarAttentionBridge` 与通知偏好。

### Electron
- 无改动 —— 复用 Phase 0 的轮询器（drain 端点已扩展）。

### 测试
- `backend/tools/__tests__/test_bash_session_watchers.py`（新）
- `backend/tests/unit/test_wake_on_background_tool.py`（新）
- `backend/tests/unit/test_wait_background_tool.py`（新）
- `backend/tests/unit/test_background_notifications.py`（新）
- `backend/tests/unit/test_tool_bundles_parity.py`（快照 +2 工具）

## 技术方案

### T1: BashSessionRegistry 退出观察器

```python
# backend/tools/bash_session.py 新增
_ExitWatch = Callable[[str, Optional[int]], None]  # (shell_id, exit_code)

class BashSessionRegistry:
    def __init__(self, ...):
        ...
        self._exit_watches: Dict[str, List[_ExitWatch]] = {}
        self._exited_seen: set = set()
        self._watcher_thread: Optional[threading.Thread] = None

    def register_watcher(self, shell_id: str, callback: _ExitWatch) -> bool:
        """为 shell_id 登记退出回调。已退出则立即触发一次。返回 True
        表示登记成功；False 表示 shell 不存在。"""
        ...
        # 首次登记启动 daemon 线程
        if self._watcher_thread is None:
            self._watcher_thread = threading.Thread(
                target=self._run_watcher, daemon=True, name="bash-session-watcher"
            )
            self._watcher_thread.start()
        return True

    def _run_watcher(self) -> None:
        """每 5s 扫一次被观察会话，检测 running → exited 转换。"""
        while True:
            try:
                self._poll_watches()
            except Exception:
                logger.exception("exit watcher tick failed")
            time.sleep(5.0)
```

### T2: 后台任务通知队列

```python
# backend/services/background_notifications.py
MAX_BACKGROUND_NOTIFICATIONS = 100

class BackgroundNotificationQueue:
    def push(self, shell_id, command, exit_code, session_id=None) -> None: ...
    def drain(self) -> List[Dict[str, Any]]: ...

def get_background_notification_queue() -> BackgroundNotificationQueue: ...
```

默认回调把 `shell_id`/`command`/`exit_code`/`session_id` 推入队列。

### T3: drain 端点扩展

`GET /api/v1/scheduled/notifications/pending` 追加 `background_tasks` 字段。

### T4: `wake_on_background` 工具

登记 COMPLETION wake（`WakeKind.COMPLETION`，`job_id=shell_id`）；
已退出的 shell 立即转为 TIMER wake（fire_at = now）。

### T5: `wait_background` 工具

轮询 `status()`，上限 60s，返回尾部输出与状态。

### T6: 工具注册与守卫

- `tool_names.py`：新增 `BACKGROUND_TASK_TOOLS = ("wake_on_background", "wait_background")` 并入 `ALL_BUILTIN_TOOL_NAMES`。
- `permissions.py`：`wake_on_background: WRITE`（加入 SELF_MODIFY_TOOLS）/ `wait_background: READ`。
- `tool_bundles.py`：`_install_shell` 注册。
- `test_tool_bundles_parity.py`：ONLINE 115→117 等。

## 实施步骤

- [x] M1: 本 plan 文档
- [x] M2: BashSessionRegistry 退出观察器（T1）+ 单元测试
- [x] M3: 后台任务通知队列（T2）+ 单元 + 集成测试
- [x] M4: drain 端点扩展（T3）+ 单元测试
- [x] M5: `wake_on_background` 工具（T4）+ 测试
- [x] M6: `wait_background` 工具（T5）+ 测试
- [x] M7: 工具注册与守卫（T6）+ parity 快照同步
- [x] M8: 类型检查、ruff、py38 兼容扫描
- [ ] M9: PR → CI → 合并；同步 win7

## 风险评估

| 风险 | 缓解 |
|---|---|
| daemon watcher 线程泄漏 | daemon=True；退出时 `.join(timeout=0.1)` |
| 退出回调阻塞 poller | 每个回调 try/except 隔离 |
| `wait_background` 占住 tool executor 线程 | timeout 上限 60s |
| parity 快照漂移 | M7 一次性同步 |

## 不在范围内

- BashSessionRegistry 持久化（Phase 2）
- 后台任务输出流式推送（独立 plan）
- Webhook / Slack 外发（Phase 3）

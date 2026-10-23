# LLM 定时任务工具（schedule_task / list_scheduled_tasks / cancel_scheduled_task）

> 引入版本：v0.4.9-alpha.4x（feat/llm-schedule-tool, 2026-09-19）
> 相关代码：`backend/tools/schedule_tool.py`、`backend/services/scheduler.py`

## 1. 背景

Sage 的定时任务子系统（`SchedulerService`，APScheduler + JSON 持久化）此前只有一条消费路径：前端 UI 经 REST API（`backend/api/scheduled_router.py`）调用。LLM 在对话中无法创建定时任务——用户想设置"每 5 分钟检查部署状态"，必须离开对话、手填 cron、手选会话、手写内容。

本次将调度能力以三件套工具的形式暴露给 LLM，对齐 Claude Code 的 `CronCreate`/`CronDelete` 与主流 AI 应用的自然语言提醒体验。

## 2. 工具面

| 工具 | 风险 | 作用 |
|------|------|------|
| `schedule_task` | `WRITE_LOCAL` | 创建一次性（`once`）或周期性（`recurring`）任务 |
| `list_scheduled_tasks` | `READ` | 列出**当前会话**的定时任务 |
| `cancel_scheduled_task` | `WRITE_LOCAL` | 按 ID 取消**当前会话**的任务 |

### 2.1 `schedule_task` 参数

| 参数 | 必需性 | 说明 |
|------|--------|------|
| `name` | 必填 | 任务名，≤80 字符 |
| `prompt` | 必填 | 触发时注入会话的内容，≤4000 字符 |
| `schedule_kind` | 必填 | `once` \| `recurring` |
| `cron` | `recurring` 必填 | 5 段 cron（分 时 日 月 周），按**服务器本地时区**解释 |
| `at` | `once` 必填 | ISO-8601 字符串（如 `2026-09-20T15:00:00+08:00`）或 epoch 毫秒整数，须为未来时间 |
| `session_id` | 可选 | 缺省 = 当前对话会话 |

## 3. 设计要点

### 3.1 单一调度事实源

工具**不新建调度器**，而是复用进程内的 `SchedulerService` 单例（`get_scheduler_service()`）。因此 LLM 创建的任务与 UI 创建的任务落在同一 JSON 文件、同一 APScheduler jobstore —— 前端 ScheduledTasks 页立即可见、可编辑、可停用。这是本设计最重要的约束。

### 3.2 会话绑定

目标会话恒取自 `ToolExecutionContext.session_id`（`backend/tools/context.py`）。普通聊天路径在 `backend/api/legacy_routes.py` 的 producer 中始终设置该 ContextVar（无 workspace 绑定时 `binding_generation=0`），故绑定可靠。

**不要求** LLM 传会话 id —— 避免模型幻觉 id 把提醒注入错误会话。显式传入的 `session_id` **必须等于**当前会话，否则一律拒绝（`_resolve_session_id` 返回可读错误）。之所以允许显式传参，只是为了让 LLM 主动指定时得到明确拒绝理由，而非静默忽略——这也是防 prompt injection 借模型之手向他人会话投递消息的关键一环。

拒绝消息**不回显**实际 session_id（`_resolve_session_id` 与 `cancel` 归属校验均如此）。回显真实会话标识符会让被 prompt injection 操纵的模型借"探测-报错"循环枚举有效 session id，为后续针对性注入铺路；仅告知"与当前会话不一致"即可。

### 3.3 时间表达

- `recurring` 用 5 段 cron（croniter + `CronTrigger.from_crontab` 双重校验）。
- `once` 接受 ISO-8601（推荐，可带时区，支持 `Z` 后缀）或 epoch 毫秒整数。无时区信息的 ISO 串按后端本地时区解释。5 段 cron 对一次性提醒表达能力不足，故不强制走 cron。
- `at` **必须有上界**：超出 `datetime` 可表示范围的毫秒值（如 `1e17`）会在 `SchedulerService._validate_schedule` 落盘前被拒。修复前该值先被持久化、再在 `_schedule_job` 抛 `ValueError`，导致任务留在磁盘上但调度失败，且重启时 `_reschedule_all` 抛同一异常使 `SchedulerService` 构造失败（**后端起不来**）。`_reschedule_all` 现已逐条容错：坏条目标记 `missed` 使 UI 可见，其余正常登记。
- **missed 分支不得嵌套获锁**：`_schedule_job` 在一次性任务已过期时走 missed 分支调 `_record_run`。后者内部自行获取 `threading.Lock`（非重入锁），故调用点**不能**再包一层 `with self._lock:` —— 否则后端重启遇到磁盘上已过期的一次性任务时，`__init__ → _reschedule_all → _schedule_job → _record_run` 链会在第二次获锁处**永久死锁**。回归测试 `test_restart_with_expired_once_task_does_not_deadlock` 用合法但已过期的 `at` 锁定此路径（越界值在更早处抛异常，掩盖锁嵌套）。
- **损坏的 recurring cron 不得阻断启动**：`_next_run_for` 对损坏 cron / 缺字段返回 `None`（记 warning），而非抛异常。`_record_run` 会经此计算 `next_run`，若在此抛 `CroniterBadCronError`（继承 `ValueError`），会击穿 `_reschedule_all` 的逐条容错、一路穿透 `__init__` 使后端起不来。回归测试 `test_corrupt_recurring_cron_does_not_block_startup`。

### 3.4 工具错误消息

工具边界（`except Exception`）**不回显原始异常文本**，仅返回固定文案并写 `logger.exception`。异常 str 可能含文件路径（如 `${SAGE_USER_DATA_DIR}/scheduled_tasks.json`）、类名等内部信息，进入 LLM 上下文即为信息泄露。唯一例外是 `SchedulerService` 主动抛出的 `ValidationError`——那是面向用户的校验文案，可安全透传。

### 3.5 风险与可见性

- 三件套**仅赋给 primary** 主助手（对齐 `CONFIG_TOOLS` 的 coordinator-only 边界）。子代理白名单严禁纳入 —— 防止被委派的子任务自行注册长期定时行为。
- 未设 `requires_tool_context=True`：无上下文时工具应**可见并给出可读错误**（便于排障），而非从工具面静默消失。

### 3.6 越权防护

`list` / `cancel` 均按当前会话过滤。`cancel_scheduled_task` 把归属校验**下推到 `SchedulerService.delete_task(task_id, expected_session_id=...)`**，在同一把锁内完成"查归属 + 删"：若 `task.session_id != 当前会话` 抛 `ValidationError`，工具转成"该任务不属于当前会话"的可读拒绝。此前"先 `get_task` 校验 / 再 `delete_task`"的写法在两次获锁之间留有 TOCTOU 窗口——前端 UI 可把任务迁移到别的会话后，本工具仍按旧归属删除。

## 4. 触发语义（未改动）

任务触发仍走 `SchedulerService._fire()` → 向目标 session 的 messages 表插入一条 `role=system` 消息。既有语义保持不变：

- 一次性任务在停机期间错过触发点 → 标记 `missed`，不静默跳过；
- 失败的一次性任务自动禁用（`enabled=False`），不自动重放。

## 5. 防漂移清单

新增内置工具须同步四处，`backend/tests/unit/test_tool_names.py` 与 `test_profiles_default_tools.py` 交叉锁定：

1. `backend/domain/tool_names.py` — `SCHEDULE_TOOLS` 组 + `ALL_BUILTIN_TOOL_NAMES` + `__all__`；
2. `backend/tools/__init__.py` — import + `register_all_tools` 注册；
3. `backend/agents/profiles.py` — primary 种子白名单（`_PRIMARY_SEED_TOOLS`）；
4. 本文件 + `docs/technical/README.md` 索引。

## 6. 测试

`backend/tests/unit/test_schedule_tool.py`（19 用例）覆盖：recurring/once 创建、ISO-8601（含 `Z` 后缀）与 epoch 毫秒解析、无效 cron、过去时间、越界 epoch（须不落盘）、bool 拒收、缺参、无工具上下文、无服务、跨会话 list/schedule 拒绝、同会话显式参数放行、跨会话 cancel 拒绝、未知 ID。

`backend/services/__tests__/test_scheduler.py` 新增/扩充的服务层用例：

- `TestOnceAtRangeGuard`（3 用例）：越界 `at` 落盘前拒绝 + 磁盘脏条目下重启不抛异常 + 已过期一次性任务重启不死锁（`@pytest.mark.timeout(15)` 防回归挂死）。
- `TestLoadEdgeCases::test_corrupt_recurring_cron_does_not_block_startup`：损坏 recurring cron 不阻断启动。
- `TestDeleteTask::test_expected_session_{mismatch_refuses,match_deletes}`：`delete_task(expected_session_id=...)` 原子归属校验（工具消除 TOCTOU 的底座）。

## 7. 后续演进

| 项 | 说明 |
|----|------|
| 自然语言定时 | 已由本工具实质解锁：LLM 自行把"下周三下午3点"换算为 ISO-8601 后调用 |
| 桌面通知 | Electron `Notification`，任务触发/完成时系统级提醒 |
| 用户暂停/恢复 | 后端已有 `suspended` + `WakeScheduler`，需暴露 `POST /chat/stream/{id}/suspend|resume` 与 Task Center UI |
| 统一任务中心 | Task Center 聚合维度纳入"定时任务" |
| 护栏增强 | 最小间隔限制、单会话任务数上限、token 预算熔断 |

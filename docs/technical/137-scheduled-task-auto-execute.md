# 定时任务自动执行（LLM 结果可见）

> 关联：`docs/technical/92-llm-scheduled-task-tool.md`（任务创建工具）、`docs/technical/23-chat-streaming.md`（对话主链路）

## 1. 背景

改造前的定时任务只做**投递**：触发时向目标会话插入一条 `role="system"` 消息。由于
`_HISTORY_ROLES=("user", "assistant")` 会把 system 消息过滤掉，这条记录既不进入
LLM 上下文，也不会产生任何 assistant 回复，`last_status="succeeded"` 只代表
**消息落库成功**。用户看不到 AI 产出，任务的实际价值有限。

本特性把触发语义升级为**跑一轮真实对话**：LLM + 工具 → 持久化 assistant 回复 →
任务列表可回看结果。同时保留原投递行为，供纯提醒场景使用，并让存量任务不产生行为突变。

## 2. 双模式语义

`ScheduledTask.mode` 取值 `"execute" | "deliver"`：

| 模式 | 触发行为 | 默认值来源 |
| --- | --- | --- |
| `execute` | 调用 `ChatService.run_turn_tracked()` 跑一轮对话，assistant 回复写入目标会话 | 新建任务（API / LLM 工具 / 前端表单） |
| `deliver` | 保持历史行为：插入 `role="system"` 提醒消息 | 存量任务（DDL 与 dataclass 双重默认） |

默认值分三处，刻意不同：

| 位置 | 默认 | 理由 |
| --- | --- | --- |
| `ScheduledTask` dataclass（`from_dict`） | `"deliver"` | 读旧行时安全降级，不产生额外 LLM 调用 |
| `scheduled_tasks.mode` DDL | `'deliver'` | 升级瞬间所有存量行为不变 |
| `CreateTaskIn` / `schedule_task` 工具 / 前端表单 | `"execute"` | 新任务默认获得 AI 能力 |

## 3. 总体链路

```
APScheduler 后台线程
  └─ SchedulerService._fire(task)                    backend/services/scheduler.py
       ├─ session 不存在 → 失败
       ├─ mode == "deliver" → message_repo.insert(role="system")
       └─ mode == "execute"
            ├─ executor 未注入 → logger.warning + 降级 deliver
            └─ self._executor(task)                  # 注入的同步 callable
                 └─ make_threadsafe_runner(...)      backend/application/services/scheduled_task_executor.py
                      asyncio.run_coroutine_threadsafe(
                          chat_service.run_turn_tracked(
                              session_id,
                              Message(role=USER, content=task.content),
                              max_iterations=8,
                          ),
                          main_loop,
                      ).result(timeout=300)
```

`_fire()` 在 `finally` 中统一调用 `_record_run()`，把 `status` / `last_error` /
`last_result_message_id` / `last_duration_ms` 写回任务并持久化。

## 4. 六边形边界与依赖注入

契约类型下沉到领域层 `backend/domain/scheduler.py`（`backend.services.scheduler`
保持 re-export，旧导入路径仍可用）：

```python
@dataclass
class ScheduledTask:          # 领域实体：服务层与应用层共用
    ...

@dataclass(frozen=True)
class RunOutcome:
    status: Literal["succeeded", "failed"]
    message_id: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None      # 永远为脱敏固定文案

TaskRunner = Callable[[ScheduledTask], RunOutcome]
```

`backend/services/scheduler.py` **不导入** `ChatService`、LLM 或 agent，只消费上述类型
并提供 `SchedulerService.set_executor(runner) -> None`。

为什么类型必须放在 domain：`backend.application` 位于 import-linter 层级契约中
`backend.services` 之上；若应用层的执行器直接从 `backend.services.scheduler` 导入，
会经该模块的传递依赖（`scheduler.evolution → skills.consolidator → api.legacy_routes`）
触发 `application is not allowed to import backend.api` 违规。下沉到 domain 后，
服务层与应用层都只依赖领域层，契约保持 KEPT。

为什么必须用**后置 setter**：`init_scheduler_service()` 在 lifespan 早段执行，
此时 `ChatService` 还没构建（它依赖 LLM 配置、工具注册、存储等），构造期无法传参。
因此由 `backend/main.py` 在两者都就绪后装配：

```python
# lifespan 开头
main_loop = asyncio.get_running_loop()

# ChatService 装配完成后
_wire_scheduler_executor(app, main_loop)   # → scheduler.set_executor(make_threadsafe_runner(...))
```

`_wire_scheduler_executor()` 在任一依赖缺失时只写 warning 并返回 `False`，不抛异常——
启动期绝不能因装配失败被阻塞，此时 execute 任务自动降级为 deliver。

## 5. 线程安全桥接

APScheduler 的 job 跑在后台线程，而 `ChatService` 是 asyncio 应用：所有 storage、
事件总线、LLM 客户端都绑定主事件循环。桥接模块负责跨越这个边界。

`make_threadsafe_runner(chat_service, main_loop, *, timeout=300, max_iterations=8)`
返回一个**同步** callable：

1. `asyncio.run_coroutine_threadsafe(...)` 把协程投递到 `main_loop`；
2. `.result(timeout=300)` 在调度线程阻塞等待，超时则 `future.cancel()`；
3. 调度阶段抛错（loop 已关闭、签名不匹配）与执行阶段异常一律转换为
   `RunOutcome(status="failed")`，`error` 为固定文案；
4. 用 `time.monotonic()` 记录耗时填入 `duration_ms`。

桥接层属于应用层（`backend/application/services/`），允许依赖 `ChatService`；
`services/scheduler.py` 保持纯净，避免 `import-linter` 的 tools→services 越界。

## 6. ChatService 多轮 ReAct

为让 execute 任务真正“干活”，`ChatService` 增加可选多轮循环：

| 方法 | 语义 |
| --- | --- |
| `run_turn(...)` | 公开签名与返回值不变，内部 `max_iterations=1`，零回归 |
| `run_turn_tracked(..., *, max_iterations=1)` | 同上，额外返回 `(messages, assistant_message_id)` |
| `_chat_once(...)` | 抽出的单次 LLM 调用（metrics / 错误处理 / 空响应重试），单轮与多轮共用 |
| `_run_turn_inner(..., max_iterations)` | 循环：LLM → 落 assistant(tool_calls) → 执行工具 → 回喂 → 再 LLM |

关键点：

- **落库顺序**：先落 `assistant(tool_calls)` 再落 `tool` 结果，保证 `messages` 表里的
  历史顺序符合协议（此前单轮路径是先 tool 后 assistant）。
- **上限**：`max_iterations=8`；现有 `ToolPolicy.max_tool_calls_per_run` 仍是第二道闸，
  预算耗尽时提前终止并返回已有结果。
- **默认 1**：WakeScheduler、hex 路由、Office mention 等既有调用方不受影响；
  仅定时任务显式传 `8`。

## 7. 数据模型与迁移

`ScheduledTask` 新增字段，全部带默认值以保证旧行可读：

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `mode` | `Literal["execute","deliver"]` | `"deliver"` | 执行模式 |
| `last_result_message_id` | `Optional[str]` | `None` | 指向 `messages.id`，用于跳转定位 |
| `last_duration_ms` | `Optional[int]` | `None` | 最近一次执行耗时（毫秒） |

`ScheduledTaskRepository._COLUMNS` 同步增加三列。`backend/data/database.py` 用
`PRAGMA table_info(scheduled_tasks)` + 条件 `ALTER TABLE` 做幂等迁移：

```sql
ALTER TABLE scheduled_tasks ADD COLUMN mode TEXT NOT NULL DEFAULT 'deliver';
ALTER TABLE scheduled_tasks ADD COLUMN last_result_message_id TEXT;
ALTER TABLE scheduled_tasks ADD COLUMN last_duration_ms INTEGER;
```

不新建执行历史表：本轮只保留**最近一次**结果，正文本身就在 `messages` 表里，
靠 id 定位即可，避免冗余存储。分页执行历史留待后续迭代。

## 8. API 契约

`backend/api/scheduled_router.py`：

| 模型 | 字段 | 说明 |
| --- | --- | --- |
| `CreateTaskIn` | `mode: Literal["execute","deliver"] = "execute"` | 新任务默认自动执行 |
| `UpdateTaskIn` | `mode: Optional[...] = None` | PATCH 不传则保持原值 |
| `TaskOut` | `mode` / `last_result_message_id` / `last_duration_ms` | 列表与详情统一透出 |

`_task_to_dict()` 用 `getattr(task, "mode", "deliver")` 兜底，保证任何未升级的
任务对象也不会让响应 500。`POST /scheduled/tasks/{id}/run` 复用既有返回结构，
执行完成后自然带上新字段，不新增端点。

## 9. LLM 工具对齐

`backend/tools/schedule_tool.py`：

- `schedule_task` 新增可选参数 `mode: str = "execute"`，非法值返回
  `success=False, error="mode 必须是 'execute' 或 'deliver'。"`
- 工具描述从「到点提醒」改为「到点自动执行一次对话并返回结果，或仅发送提醒」，
  让模型在用户说“帮我每天查一下…”时倾向 `execute`。
- `list_scheduled_tasks` 的摘要与结构化返回都透出 `mode`，便于模型判断后续操作。

## 10. 前端

| 文件 | 改动 |
| --- | --- |
| `src/shared/api/types/domainEntityTypes.ts` | `ScheduledTaskMode` 类型 + 三个字段 |
| `src/pages/ScheduledTasks.tsx` | 模式徽章（Zap/Bell）、执行中/耗时徽章、「查看结果」按钮 |
| `src/features/scheduled/CreateTaskModal.tsx` | 模式二选一（默认自动执行），编辑时继承原模式 |
| `src/shared/lib/i18n/locales/{zh,en}/settingsAndModels.ts` | `scheduled.mode.*` / `scheduled.view_result*` / `scheduled.executing` / `scheduled.duration_ms` |

交互细节：

- 「查看结果」仅在 `mode === "execute"` 且 `last_result_message_id` 非空时可用；
  deliver 任务按钮置灰，`title` 提示“仅提醒模式没有结果”。
- 点击后：若目标会话不是当前会话，先 `useStore.getState().setCurrentSessionId(...)`，
  再 `requestMessageJump({ messageId })`；`MessageList` 消费跳转请求后滚动并高亮。
- 任务列表沿用既有刷新节奏，不引入实时推送。
- 注意 `t()` **不做插值**，耗时文案用 `.replace('{ms}', String(n))`。

## 11. 失败语义与护栏

| 场景 | 行为 |
| --- | --- |
| executor 未注入 | 降级 deliver 插入 system 消息 + `logger.warning`，**不标记失败** |
| 执行超时（默认 300s） | `RunOutcome(status="failed")`，`error="Execution timed out"`；future 取消 |
| LLM / 工具异常 | `last_status="failed"`，`last_error` 为脱敏固定文案，堆栈只进后端日志 |
| 一次性任务执行失败 | `enabled=False`，**不自动重放**（提交后失败原因可能歧义） |
| 重复触发 | `_running` 集合 + APScheduler `max_instances=1` |
| 成本 | `max_iterations=8` + `max_tool_calls_per_run` 双重上限 |
| 权限 | 继承 `ChatService` 的 `LanePermission`，危险工具仍被门禁拦截 |
| 目标会话不存在 | 现有检查保留，execute / deliver 都拒绝 |

安全约定：`last_error` 绝不写入原始异常文本（可能含路径、类名、URL、凭据），
与 `schedule_tool.py` 的既有做法一致。

## 12. 已知限制

- `ChatService._execute_tool_calls()` 目前不设置 `ToolExecutionContext` ContextVar，
  依赖该上下文的工具在后台执行时可能拿不到 `session_id`。WakeScheduler 同样受影响，
  非本特性引入，后续统一修复。
- 无执行历史分页、无中途取消、无流式查看、无 OS 级推送通知。
- 任务级独立模型 / 工具白名单未实现，执行沿用全局配置。

## 13. 测试覆盖

| 层 | 文件 |
| --- | --- |
| ChatService 多轮 / 单轮回归 | `backend/tests/unit/test_chat_service.py`、`test_hex_empty_response.py` |
| Scheduler 分流 / 降级 / 失败禁用 | `backend/tests/unit/test_scheduler_executor.py` |
| 线程桥接（成功 / 超时 / 异常 / loop 关闭） | `backend/tests/unit/test_scheduler_executor.py` |
| 旧行默认值 / 迁移幂等 / API 往返 | `backend/tests/unit/test_scheduled_task_m3_fields.py`、`backend/tests/test_scheduled_task_repository.py` |
| 装配 | `backend/tests/integration/test_lifespan_wiring.py` |
| 前端列表与表单 | `src/pages/__tests__/ScheduledTasks.mode.test.tsx`、`src/features/scheduled/__tests__/CreateTaskModal.mode.test.tsx` |

## 14. 双分支适配（release/win7）

功能在 `main` 合并后 cherry-pick 到 `release/win7`，需检查：

- Python 3.8：`tuple[...]` 运行时求值与 `X | None` 语法（文件已有
  `from __future__ import annotations` 时注解安全，但 `Literal` 需从 `typing` 导入）；
- pydantic 1.x：`Literal` 字段、`Field(default=...)` 行为与 v2 一致，但
  `conlist` 等约束字段参数名不同（本特性未使用）；
- `asyncio.run_coroutine_threadsafe` / `AbstractEventLoop` 在 3.8 均可用；
- 不修改 `backend/requirements-py38.txt`，不把 main 的依赖升级带入 win7。

# 定时任务自动执行（LLM 结果可见）

> 分支：`feat/scheduled-task-auto-execute`
> 日期：2026-11-06
> 关联文档：`docs/technical/92-llm-scheduled-task-tool.md`、`docs/plans/2026-11-02_scheduled-task-report-rendering.md`

## 1. 背景与目标

### 1.1 现状

Sage 的定时任务触发后只向目标会话插入一条 `role="system"` 消息，**从不调用 LLM**：

| 层 | 现状 | 位置 |
| --- | --- | --- |
| 触发 | `_fire()` 直接 `message_repo.insert(role="system", content=task.content)` | `backend/services/scheduler.py` |
| 消费 | `role="system"` 被 `_HISTORY_ROLES=("user","assistant")` 过滤，永不进入 LLM 上下文 | `backend/chat/event_projection.py` |
| 依赖 | `SchedulerService` 构造只接收 `store_path/message_repo/session_repo/db`，无 ChatService/LLM | `backend/services/scheduler.py` |
| 数据 | `ScheduledTask` / `scheduled_tasks` 表无执行结果字段 | `backend/services/scheduler.py`、`backend/data/database.py` |
| 产品语义 | i18n 把功能定义为「自动发送的消息」 | `src/shared/lib/i18n/locales/zh/settingsAndModels.ts` |

因此 `last_status="succeeded"` 只代表**消息落库成功**，用户看不到任何 AI 产出。

> 注：`2026-11-02_scheduled-task-report-rendering.md` 已修复 system 消息的可见性（前端渲染），但明确保持后端 `role=system` 语义不变；本方案解决的是**执行语义**，两者互补。

### 1.2 目标

对齐主流 AI 应用（ChatGPT Tasks / Claude Code Cron / Perplexity Tasks）的统一语义：

> **触发 = 跑一轮真实对话（LLM + 工具），把输入与输出持久化到目标会话，并可从任务列表回看结果。**

同时保留纯提醒能力，避免老用户行为突变。

### 1.3 成功标准

- 新建定时任务默认「自动执行」，到点后目标会话出现 assistant 回复。
- 任务列表可看到执行状态（成功/失败/耗时）与「查看结果」入口，点击跳转并高亮对应消息。
- 纯提醒模式（`deliver`）行为与现状一致。
- 存量任务升级后默认仍是 `deliver`，不产生额外 LLM 调用。
- 后端 / 前端测试覆盖 ≥ 80%，main 与 release/win7 双分支通过。

## 2. 双模式语义

新增 `ScheduledTask.mode`：

| 模式 | 触发行为 | 默认值来源 |
| --- | --- | --- |
| `execute` | 调用 `ChatService.run_turn_tracked()` 跑一轮对话，assistant 回复写入目标会话 | 新建任务、LLM 工具创建任务 |
| `deliver` | 保持现状：插入 `role="system"` 提醒消息 | 存量任务（迁移默认值） |

- `ScheduledTask.mode` 的 dataclass 默认值为 `"deliver"`，确保 `from_dict()` 读取旧行时安全降级。
- `add_task()` / `CreateTaskIn` 的默认值为 `"execute"`，让新任务默认获得 AI 能力。
- 用户可在创建/编辑表单中切换。

## 3. 技术方案

### 3.1 总体链路

```
APScheduler 后台线程
  └─ SchedulerService._fire(task)
       ├─ mode == "deliver" → 现有 message_repo.insert(system) 行为不变
       └─ mode == "execute" → self._executor(task)            # 注入的同步 callable
                                └─ scheduled_task_executor.make_threadsafe_runner
                                     asyncio.run_coroutine_threadsafe(
                                         chat_service.run_turn_tracked(
                                             session_id,
                                             Message(role=USER, content=task.content),
                                             max_iterations=8,
                                         ),
                                         main_loop,
                                     ).result(timeout=300)
```

### 3.2 六边形边界与依赖注入

- 契约类型放在 `backend/domain/scheduler.py`（`ScheduledTask`、`RunOutcome`、`TaskRunner`），
  `backend/services/scheduler.py` re-export 保持旧导入路径可用：
  ```python
  @dataclass
  class ScheduledTask:
      ...  # 领域实体，服务层与应用层共用

  @dataclass(frozen=True)
  class RunOutcome:
      status: Literal["succeeded", "failed"]
      message_id: Optional[str] = None
      duration_ms: int = 0
      error: Optional[str] = None

  TaskRunner = Callable[[ScheduledTask], RunOutcome]
  ```
  并提供 `set_executor(runner: TaskRunner) -> None`。
- **为什么下沉到 domain**：`backend/application` 在 import-linter 层级中高于
  `backend.services`；执行器若直接从 `backend.services.scheduler` 导入，会经其传递依赖
  （`scheduler.evolution → skills.consolidator → api.legacy_routes`）触发
  `application is not allowed to import backend.api`，契约 BREAK。
- `backend/services/scheduler.py` **不 import** `ChatService` / LLM / agent；应用层执行器只依赖 domain。
- 新增 `backend/application/services/scheduled_task_executor.py`：把 `ChatService` + 主事件循环包装成 `TaskRunner`，负责超时、异常脱敏、耗时统计。该模块属于应用层，允许依赖 `ChatService`。
- `backend/main.py` 在 lifespan 内、`app.state.chat_service = _build_chat_service()` 之后调用：
  ```python
  _main_loop = asyncio.get_running_loop()
  scheduler_service.set_executor(
      make_threadsafe_runner(app.state.chat_service, _main_loop)
  )
  ```
- 装配顺序：`init_scheduler_service()` 在 lifespan 早段（ChatService 尚未装配），因此必须用**后置 setter** 注入，不能构造期传参。

### 3.3 ChatService 多轮 ReAct

`ChatService.run_turn()` 当前为单轮：调用一次 LLM → 执行全部 tool_calls → 落库 → 结束（`chat_service.py` docstring 已预留「P3+ 在末尾加一层循环」）。

改动：

1. `_run_turn_inner()` 增加 `max_iterations: int = 1`，返回 `(messages, assistant_message_id)`。
2. `run_turn()` 保持公开签名不变，返回 `messages`（零回归）。
3. 新增 `run_turn_tracked(..., *, max_iterations: int = 1) -> tuple[List[Message], Optional[str]]`，供定时任务获取 assistant 消息 id。
4. 循环结构（伪代码）：
   ```python
   response = await self._chat_once(history, llm_tools, span, run)
   iterations = 1
   response_persisted = False
   while response.tool_calls:
       # 关键：先落 assistant(tool_calls)，再落 tool 结果，保证 history 顺序正确
       assistant_message_id = await self.storage.append_message(session_id, response)
       response_persisted = True
       budget_exceeded = await self._execute_tool_calls(...)
       if budget_exceeded or iterations >= max_iterations:
           break
       iterations += 1
       history = await self.storage.get_messages(session_id, limit=_DEFAULT_HISTORY_LIMIT)
       response = await self._chat_once(history, llm_tools, span, run)
       response_persisted = False
   if not response_persisted:
       assistant_message_id = await self.storage.append_message(session_id, response)
   ```
5. 把现有「LLM 调用 + metrics + 错误处理 + 空响应重试」抽成 `_chat_once()`，循环与单轮共用，避免逻辑漂移。
6. 单轮路径的落库顺序从「先 tool 后 assistant」改为「先 assistant 后 tool」，修正历史顺序；现有测试若断言调用顺序，按正确语义更新。

**为什么默认 `max_iterations=1`**：所有既有 `run_turn` 调用方（WakeScheduler、hex 路由、Office mention）行为不变；仅定时任务显式传 `8`。

### 3.4 数据模型与迁移

`ScheduledTask` 新增字段（dataclass 默认值保证旧数据可读）：

| 字段 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `mode` | `Literal["execute","deliver"]` | `"deliver"` | 执行模式 |
| `last_result_message_id` | `Optional[str]` | `None` | 指向 `messages.id`，用于跳转定位 |
| `last_duration_ms` | `Optional[int]` | `None` | 最近一次执行耗时 |

- `from_dict()` 对缺失字段使用默认值。
- `ScheduledTaskRepository._COLUMNS` 增加三列。
- `backend/data/database.py` 用现有 `PRAGMA table_info` + 条件 `ALTER TABLE ADD COLUMN` 模式幂等迁移：
  ```sql
  ALTER TABLE scheduled_tasks ADD COLUMN mode TEXT NOT NULL DEFAULT 'deliver';
  ALTER TABLE scheduled_tasks ADD COLUMN last_result_message_id TEXT;
  ALTER TABLE scheduled_tasks ADD COLUMN last_duration_ms INTEGER;
  ```
- **不新建 `scheduled_task_runs` 表**：P1 只保留最近一次结果，正文已在 `messages` 表，靠 id 定位，避免冗余存储。执行历史分页留 P2。

### 3.5 API 契约

`backend/api/scheduled_router.py`：

- `CreateTaskIn` 增加 `mode: Literal["execute","deliver"] = "execute"`。
- `UpdateTaskIn` 增加 `mode: Optional[Literal["execute","deliver"]] = None`。
- `TaskOut` 增加 `mode`、`last_result_message_id`、`last_duration_ms`。
- `_task_to_dict()` 同步透出。
- `POST /scheduled/tasks/{id}/run`：执行完成后返回最新 `TaskOut`（已有返回结构，字段自然扩展）。
- 不新增端点。

### 3.6 LLM 工具对齐

`backend/tools/schedule_tool.py`：

- `schedule_task` 增加可选参数 `mode: Literal["execute","deliver"] = "execute"`。
- 工具描述从「到点自动提醒/自动触发一次对话」改为「到点自动执行一次对话并返回结果，或仅发送提醒」。
- `list_scheduled_tasks` 返回中透出 `mode`，便于模型判断。

### 3.7 前端

| 文件 | 改动 |
| --- | --- |
| `src/shared/api/types/domainEntityTypes.ts` | `ScheduledTask` 增加 `mode`、`last_result_message_id`、`last_duration_ms` |
| `src/pages/ScheduledTasks.tsx` | 列表增加模式徽章、执行状态（成功/失败/执行中）、「查看结果」按钮；创建/编辑表单增加模式单选（默认「自动执行」） |
| `src/features/chat/messageJumpStore.ts` | 复用现有 `requestMessageJump({ messageId, highlightQuery })`，不新增机制 |
| `src/shared/lib/i18n/locales/{zh,en}/settingsAndModels.ts` | 新增 `scheduled.mode.*`、`scheduled.view_result`、`scheduled.executing` 等文案 |

交互：

- 「查看结果」仅当 `mode === 'execute'` 且 `last_result_message_id != null` 时可用。
- 点击后：切换到目标会话 → `requestMessageJump({ messageId: last_result_message_id })` → 高亮定位。
- 任务列表轮询/刷新沿用现有逻辑，不引入实时推送。

### 3.8 失败语义与护栏

| 场景 | 行为 |
| --- | --- |
| `executor` 未注入 | 降级为 `deliver` 插入 system 消息，`logger.warning`，不标记失败 |
| 执行超时（默认 300s） | `RunOutcome(status="failed")`；一次性任务自动禁用（沿用 `_record_run` 语义）；不自动重放 |
| LLM / 工具异常 | `last_status="failed"`，`last_error` 存脱敏固定文案；堆栈只进后端日志 |
| 重复触发 | 现有 `_running` 集合 + APScheduler `max_instances=1` 已覆盖 |
| 成本 | `max_iterations=8` + 现有 `ToolPolicy.max_tool_calls_per_run` 双重上限 |
| 权限 | 执行继承 `ChatService` 的 `LanePermission`，危险工具仍被门禁拦截 |
| 目标会话不存在 | 现有检查保留，execute/deliver 都拒绝 |

**安全**：`last_error` 不落原始异常文本（避免路径/类名/凭据泄露），与 `schedule_tool.py` 现有约定一致。

**已知限制（P1 记录，P2 处理）**：`ChatService._execute_tool_calls()` 不设置 `ToolExecutionContext` ContextVar，依赖 tool-context 的内置工具在后台执行时可能拿不到 `session_id`。WakeScheduler 同样受影响，非本次引入。

## 4. 实施步骤

- [x] **M1：ChatService 多轮 ReAct**
  - [x] 抽出 `_chat_once()`（LLM 调用 + metrics + 错误处理 + 空响应重试），确保单轮行为不变
  - [x] `_run_turn_inner()` 增加 `max_iterations` 并返回 `(messages, assistant_message_id)`
  - [x] 新增 `run_turn_tracked()`
  - [x] 修正 assistant/tool 落库顺序
  - [x] 单测：`max_iterations=1` 行为回归；`>1` 时工具结果回喂并二次调用；达上限停止；`assistant_message_id` 正确返回

- [x] **M2：SchedulerService 执行分支**
  - [x] `RunOutcome` / `TaskRunner` / `set_executor()`
  - [x] `_fire()` 按 `mode` 分流；executor 缺失降级 deliver
  - [x] `_record_run()` 写入 `last_result_message_id` / `last_duration_ms`
  - [x] 新增 `backend/application/services/scheduled_task_executor.py`（线程安全桥接 + 超时 + 异常脱敏）
  - [x] 单测：execute 调用 runner / deliver 不变 / 无 runner 降级 / 超时 / 异常 / 一次性失败禁用
  - [x] 桥接单测：真实 loop 在子线程中跑 runner，覆盖成功/超时/异常/closed-loop

- [x] **M3：数据模型与 API**
  - [x] `ScheduledTask` 三字段 + `to_dict/from_dict`
  - [x] `ScheduledTaskRepository._COLUMNS`
  - [x] `database.py` 幂等迁移
  - [x] `CreateTaskIn/UpdateTaskIn/TaskOut` + `_task_to_dict`
  - [x] `schedule_tool.py` 增加 `mode` 参数与描述
  - [x] 测试：旧行读取默认 deliver、DDL 幂等、API 字段往返、pydantic v1/v2 兼容

- [x] **M4：main.py 装配**
  - [x] lifespan 内捕获主事件循环
  - [x] ChatService 装配后 `scheduler_service.set_executor(...)`
  - [x] 启动日志标注执行器就绪
  - [x] 集成测试：构造 app 后 `app.state.scheduler` 有 executor（或可注入 mock）

- [x] **M5：前端**
  - [x] 类型定义（`ScheduledTaskMode` + 3 字段扩宽）
  - [x] 列表模式徽章 / 状态 / 查看结果（Zap/Bell 图标 + running/duration 徽章 + Eye 按钮）
  - [x] 表单模式选择器（默认自动执行，两按钮切换）
  - [x] 跳转 + 高亮（`requestMessageJump({ messageId })` + 会话切换）
  - [x] i18n 中英（`scheduled.mode.*` / `scheduled.view_result*` / `scheduled.executing` / `scheduled.duration_ms`）
  - [x] Vitest：模式选择、查看结果调用 `requestMessageJump`、deliver 时按钮禁用（`ScheduledTasks.mode.test.tsx` 6 例 + `CreateTaskModal.mode.test.tsx` 4 例）

- [ ] **M6：文档与双分支**
  - [x] `docs/technical/136-scheduled-task-auto-execute.md` + README 索引
  - [x] `docs/user-manual/39-scheduled-tasks.md` + README 索引
  - [ ] main 合并后 cherry-pick 到 `release/win7`，适配 pydantic 1.x / Python 3.8（`Literal` 导入、`tuple[...]` 改 `Tuple[...]`、`asyncio` API 确认）

## 5. 测试计划

### 5.1 后端

| 范围 | 用例 |
| --- | --- |
| ChatService | 单轮回归（LLM 调用次数、落库顺序、事件序列）；多轮工具回喂；max_iterations 上限；tool budget 提前终止；assistant id 返回 |
| SchedulerService | execute 调用 executor；deliver 不调用；runner=None 降级；runner 抛错；超时；一次性任务失败后 `enabled=False`；`max_runs` 语义不变 |
| Executor | 成功返回 message_id + duration；超时 future.cancel；异常脱敏；loop 关闭时降级 |
| Repository / DB | 旧行 `from_dict` 默认 deliver；新增列幂等；upsert/list 往返 |
| API | mode 默认 execute；显式 deliver；TaskOut 字段；更新 mode；pydantic v1 兼容 |
| schedule_tool | mode 透传；默认 execute；跨会话校验不变 |

### 5.2 前端

- 列表渲染模式徽章与状态。
- `查看结果` 仅在满足条件时出现，点击调用 `requestMessageJump`。
- 表单默认「自动执行」，切换后提交 payload 正确。
- 现有 ScheduledTasks 测试不回归。

### 5.3 手工验收

1. 新建 execute 任务（1 分钟后触发），停留在该会话 → 到点出现 USER 提示 + assistant 回复。
2. 切换到其他页面 → 任务列表显示成功 + 耗时 → 点击「查看结果」跳转并高亮。
3. 新建 deliver 任务 → 只出现 system 提醒气泡，无 assistant 回复。
4. 存量任务（升级前创建）→ 仍为 deliver。
5. 关闭后端 LLM 配置 → execute 任务标记失败，`last_error` 为脱敏文案，无堆栈泄露。
6. 一次性任务执行失败 → 自动禁用，不重放。

## 6. 风险评估与依赖

| 风险 | 等级 | 缓解 |
| --- | --- | --- |
| ChatService 核心路径改动引入回归 | HIGH | `max_iterations=1` 默认值与现状等价；先抽 `_chat_once()` 纯重构 + 回归测试，再加循环 |
| 后台线程桥接主 loop 失败（loop 已关闭/未捕获） | HIGH | 启动期捕获；runner 异常统一转 `RunOutcome(failed)`；不抛回 APScheduler |
| 落库顺序变化影响历史渲染 | MEDIUM | 新增顺序断言测试；手工验收查看多轮会话 |
| 长任务占满 APScheduler 线程池 | MEDIUM | `max_instances=1` + 300s 超时；默认 BackgroundScheduler 10 线程 |
| 存量任务行为突变 | MEDIUM | 迁移默认 `deliver`；UI 明确标识模式 |
| win7 pydantic 1.x 兼容 | MEDIUM | 只用基础类型 + `Literal`（v1/v2 均支持）；cherry-pick 后跑 py38 全量 |
| `ToolExecutionContext` 缺失导致工具失败 | LOW | P1 文档标注；P2 统一修复 |

依赖：

- `ChatService.run_turn_tracked` 先于 `scheduled_task_executor` 完成（M1 → M2）。
- `database.py` 迁移先于仓储字段读取（M3 内部顺序）。
- 前端依赖后端 API 字段就绪（M3 → M5）。

## 7. 双分支同步

- 功能在 `main` 完成并合并后，按规则 cherry-pick 到 `release/win7`。
- 适配点：Python 3.8 不支持 `tuple[...]` / `X | None` 运行时求值（`from __future__ import annotations` 可缓解，但 `Literal` 与运行时类型需确认）；pydantic 1.x 的 `Field`/`Literal` 行为。
- 不修改 `backend/requirements-py38.txt`；不把 main 的依赖升级带入 win7。

## 8. 明确不做（YAGNI）

- 不建执行历史表 / 分页查询（P2）
- 不做主动 OS 推送通知（P2；需后端事件 → renderer → `sage:session:notify` 订阅链路）
- 不做任务级独立模型 / 工具白名单（P2）
- 不做可视化 cron 编辑器
- 不做执行中途取消 / 流式查看

## 9. 验收清单

- [ ] 新建任务默认 execute，到点产生 assistant 回复
- [ ] deliver 模式与现状一致
- [ ] 存量任务迁移为 deliver
- [ ] 任务列表可查看结果并跳转高亮
- [ ] 失败/超时/禁用语义正确，无敏感信息泄露
- [ ] 后端 pytest 全绿，覆盖率 ≥ 80%
- [ ] 前端 Vitest 全绿
- [x] 技术文档 + 用户手册已更新
- [ ] main 合并后 win7 cherry-pick 通过

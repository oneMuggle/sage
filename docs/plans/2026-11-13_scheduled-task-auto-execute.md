# 定时任务自动执行模式（Auto-Execute）

**日期**：2026-11-13
**分支**：`feat/scheduled-task-auto-execute`
**状态**：实施中

---

## 背景与目标

### 问题

当前定时任务触发后，内容直接作为 `system` 消息注入目标会话，**不经过 LLM 处理**。用户期望的"自动执行"模式应让内容经过 `ChatService.run_turn()` 完整链路（记忆检索 → 系统提示词构建 → LLM 调用 → 工具调用 → 持久化）。

### 目标

- 支持两种执行模式：
  - **deliver**（默认，当前行为）：内容直接注入会话作为 system 消息
  - **execute**：内容作为 user 消息经过 LLM 处理后写入会话
- 向后兼容：已存在的任务默认 `mode="deliver"`
- 全栈透传：dataclass → API → TypeScript → 前端 UI

---

## 涉及的文件与模块

| 层 | 文件 | 改动 |
|----|------|------|
| Domain | `backend/services/scheduler.py` | 增加 `mode` 字段 + executor 注入 + `_fire()` 分支 |
| API | `backend/api/scheduled_router.py` | `CreateTaskIn` / `TaskOut` 增加 `mode` |
| LLM Tool | `backend/tools/schedule_tool.py` | tool schema 增加 `mode` 参数 |
| Wire-up | `backend/main.py` | 注入 executor 到 scheduler |
| Types | `src/shared/api/types/domainEntityTypes.ts` | `ScheduledTask` / `CreateTaskInput` 增加 `mode` |
| Store | `src/entities/scheduled/taskStore.ts` | 透传 `mode` |
| UI | `src/features/scheduled/CreateTaskModal.tsx` | 增加模式选择 Radio |

---

## 技术方案

### 1. 数据模型扩展

```python
# backend/services/scheduler.py
@dataclass
class ScheduledTask:
    # ... 现有字段
    mode: Literal["execute", "deliver"] = "deliver"  # 新增
```

### 2. Executor 注入

`SchedulerService` 增加 `_executor` 属性和 `set_executor()` 方法。executor 是一个 `Callable[[str, str], Awaitable[None]]`，接受 `(session_id, user_message)` 并调用 `ChatService.run_turn()`。

```python
# backend/services/scheduler.py
class SchedulerService:
    def __init__(self, ...):
        self._executor: Optional[Callable] = None

    def set_executor(self, executor: Callable) -> None:
        self._executor = executor
```

### 3. `_fire()` 分支逻辑

```python
def _fire(self, task: ScheduledTask) -> None:
    if task.mode == "execute" and self._executor:
        # 走 LLM 链路（异步，通过 run_coroutine_threadsafe）
        future = asyncio.run_coroutine_threadsafe(
            self._executor(task.session_id, task.content),
            self._loop
        )
        error = future.result(timeout=5.0)  # 等提交，不等完成
    else:
        # 当前行为：直接 insert system 消息
        self._message_repo.insert(...)
```

### 4. main.py 桥接

```python
# backend/main.py
async def _run_task_as_user_message(session_id: str, content: str) -> None:
    chat_service = get_chat_service()
    # 构造 user message 并调用 run_turn
    ...

scheduler_service.set_executor(_run_task_as_user_message)
```

### 5. 前端 UI

在 `CreateTaskModal.tsx` 增加 Radio 组：

```
○ 直接发送（deliver）—— 内容直接写入会话，不经过 AI 处理
● 自动执行（execute）—— 内容作为用户消息，由 AI 处理后回复
```

---

## 实施步骤

- [x] M1：`ScheduledTask` dataclass 增加 `mode` 字段 + 序列化
- [x] M2：API schema（`CreateTaskIn` / `TaskOut`）增加 `mode`
- [x] M3：LLM tool `schedule_tool.py` 增加 `mode` 参数
- [x] M4：TypeScript 类型 `domainEntityTypes.ts` 增加 `mode`
- [x] M5：Store 透传 + 前端 UI Radio
- [x] M6：`SchedulerService` executor 注入 + `_fire()` 分支
- [x] M7：`main.py` 桥接 `ChatService.run_turn()`
- [x] M8：单元测试覆盖两种模式（后端 14 / 前端 5 通过）

---

## 风险评估

| 风险 | 缓解 |
|------|------|
| APScheduler 线程调用异步 `run_turn()` | 使用 `run_coroutine_threadsafe` 调度到主 loop |
| executor 未注入时 `execute` 模式退化 | `_fire()` 降级为 deliver + 日志 warn |
| 前端旧数据无 `mode` 字段 | 后端默认 `"deliver"`，前端 `?? "deliver"` |
| `run_turn()` 需要 auth token | executor 内部绕过 LLM auth（内部调用） |

---

## 依赖

- `ChatService.run_turn()` 接口稳定
- APScheduler `BackgroundScheduler` 持有 event loop 引用（`main.py` 启动时传入）

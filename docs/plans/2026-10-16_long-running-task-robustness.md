# 长时任务健壮性优化

> 基于 2026-10-15 代码库分析的长时任务瓶颈修复方案

## 背景与目标

### 问题陈述

Sage 项目的长时任务架构整体成熟（四层任务体系、三级取消通道、完整资源限制），但存在以下关键风险：

1. **Evolution 任务无 wall-clock 超时**（P0）：`BaseEvolutionTask.run()` 通过 `loop.run_until_complete(self.run_async())` 运行，无外部超时包裹。若 LLM 调用 hang，APScheduler 线程永久阻塞，影响后续所有定时任务。

2. **WakeScheduler resumer 无超时**（P1）：resumer await 调用 `chat_service.run_turn()`，若挂起则阻塞整个 wake 消费循环。虽注释要求"快速返回"，但无代码级防护。

3. **SubagentRunner watcher 泄漏风险**（P2）：`_run_one` 异常路径若有 bug，watcher 任务的 `finally` 可能不被执行。

4. **scheduled_tasks.json 持久化脆弱**（P1）：JSON 文件无 WAL、无事务、无备份；文件损坏 → 全部定时任务丢失。与编排层 SQLite 仓储技术栈割裂。

### 目标

- **Phase 1**（本次实施）：修复 P0 + P1 低风险项，提升长时任务健壮性
- **Phase 2**（后续 PR）：scheduled_tasks.json → SQLite 迁移（中等成本，独立 PR）

---

## 涉及的文件与模块

### Phase 1 修改文件

| 文件 | 修改内容 |
|---|---|
| `backend/scheduler/evolution.py` | 为 `BaseEvolutionTask.run_async()` 加 wall-clock 超时 |
| `backend/services/scheduler.py` | `_fire_evolution()` 包裹 `asyncio.wait_for()` |
| `backend/orchestration/wake_scheduler.py` | resumer 调用加超时保护 |
| `backend/orchestration/subagent_runner.py` | watcher 任务生命周期加固（用 `asyncio.TaskGroup` 或显式 cancel） |
| `backend/tests/test_evolution_timeout.py` | 新增：Evolution 任务超时测试 |
| `backend/tests/test_wake_scheduler_timeout.py` | 新增：WakeScheduler resumer 超时测试 |
| `backend/tests/test_subagent_runner_watcher.py` | 新增：watcher 生命周期测试 |

### 配置项新增

| 配置 | 默认值 | 说明 |
|---|---|---|
| `SAGE_EVOLUTION_TASK_TIMEOUT_S` | 1800 (30min) | Evolution 任务 wall-clock 超时 |
| `SAGE_WAKE_RESUMER_TIMEOUT_S` | 30 | WakeScheduler resumer 超时 |

---

## 技术方案

### 1. Evolution 任务 wall-clock 超时

**现状**：
```python
# backend/scheduler/evolution.py:43-56
def run(self) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(self.run_async())
    finally:
        loop.close()
```

**改进**：
```python
# backend/scheduler/evolution.py
import os

_EVOLUTION_TASK_TIMEOUT_S = float(
    os.environ.get("SAGE_EVOLUTION_TASK_TIMEOUT_S", "1800")
)

def run(self) -> None:
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            asyncio.wait_for(self.run_async(), timeout=_EVOLUTION_TASK_TIMEOUT_S)
        )
    except asyncio.TimeoutError:
        logger.error(
            f"Evolution task {self.__class__.__name__} timed out after "
            f"{_EVOLUTION_TASK_TIMEOUT_S}s"
        )
        raise
    finally:
        loop.close()
```

**备选方案**：在 `scheduler.py` 的 `_fire_evolution()` 中包裹（更集中）。但当前实现更贴近问题源头，测试更直接。

### 2. WakeScheduler resumer 超时

**现状**：
```python
# backend/orchestration/wake_scheduler.py:119-127
async def _loop(self) -> None:
    await self.tick()  # catch-up
    while True:
        await asyncio.sleep(self.tick_seconds)
        await self.tick()

# tick() 内部：
async def tick(self) -> None:
    for wake in pending_wakes:
        await self.resumer(wake)  # 无超时
```

**改进**：
```python
# backend/orchestration/wake_scheduler.py
import os

_WAKE_RESUMER_TIMEOUT_S = float(
    os.environ.get("SAGE_WAKE_RESUMER_TIMEOUT_S", "30")
)

async def tick(self) -> None:
    for wake in pending_wakes:
        try:
            await asyncio.wait_for(
                self.resumer(wake),
                timeout=_WAKE_RESUMER_TIMEOUT_S
            )
        except asyncio.TimeoutError:
            logger.warning(
                f"Wake resumer for {wake.wake_id} timed out after "
                f"{_WAKE_RESUMER_TIMEOUT_S}s, skipping"
            )
            # fire-once 语义：标记已消费，不重试
```

**注意**：resumer 契约是"快速返回，内部 spawn 长任务"。30s 超时足够覆盖 spawn 开销，但不会阻塞消费循环。

### 3. SubagentRunner watcher 生命周期加固

**现状**：
```python
# backend/orchestration/subagent_runner.py:239-268
if self._interrupt_event is not None:
    async def _watch() -> None:
        await self._interrupt_event.wait()
        child.interrupt()
    watcher = asyncio.create_task(_watch())

try:
    result = await self._run_one(lane, agent_id)
finally:
    if watcher is not None:
        watcher.cancel()
```

**风险**：若 `_run_one` 异常路径有 bug（如未正确传播），`finally` 可能不执行，watcher 泄漏。

**改进方案 A**（推荐，Python 3.11+ TaskGroup）：
```python
# 但项目需支持 py3.8，TaskGroup 不可用
```

**改进方案 B**（兼容 py3.8，显式 cancel + await）：
```python
watcher = None
if self._interrupt_event is not None:
    async def _watch() -> None:
        try:
            await self._interrupt_event.wait()
            child.interrupt()
        except asyncio.CancelledError:
            # 显式捕获，避免 CancelledError 泄漏
            pass

    watcher = asyncio.create_task(_watch())

try:
    result = await self._run_one(lane, agent_id)
finally:
    if watcher is not None:
        watcher.cancel()
        try:
            await watcher  # 等待 cancel 完成，避免泄漏
        except asyncio.CancelledError:
            pass
```

**关键改进**：
1. watcher 内部显式捕获 `CancelledError`
2. `finally` 中 `await watcher` 确保 cancel 完成
3. 即使 `_run_one` 异常，watcher 也会被清理

### 4. Phase 2：scheduled_tasks.json → SQLite（本次不实施）

**方案概要**（后续 PR）：
- 新建 `ScheduledTaskRepository`（SQLite），复用 `OrchRunRepository` 模式
- 迁移脚本：读取 JSON → 写入 SQLite
- 保留 JSON 作为备份（首次启动时若 SQLite 为空，尝试从 JSON 导入）
- 获得 WAL、事务、备份能力

---

## 实施步骤

### Phase 1（本次 PR）

- [x] **步骤 1**：Evolution 任务加 wall-clock 超时
  - 修改 `backend/scheduler/evolution.py`
  - 新增环境变量 `SAGE_EVOLUTION_TASK_TIMEOUT_S`（默认 1800s）
  - 新增测试 `backend/tests/test_evolution_timeout.py`

- [x] **步骤 2**：WakeScheduler resumer 加超时
  - 修改 `backend/orchestration/wake_scheduler.py`
  - 新增环境变量 `SAGE_WAKE_RESUMER_TIMEOUT_S`（默认 30s）
  - 新增测试 `backend/tests/test_wake_scheduler_timeout.py`

- [x] **步骤 3**：SubagentRunner watcher 生命周期加固
  - 修改 `backend/orchestration/subagent_runner.py`
  - watcher 内部显式捕获 `CancelledError`
  - `finally` 中 `await watcher` 确保 cancel 完成
  - 新增测试 `backend/tests/test_subagent_runner_watcher.py`

- [x] **步骤 4**：运行全量测试
  - `pytest backend/tests/` 确保无回归
  - 重点检查 scheduler、orchestration 相关测试
  - 结果：scheduler 28 passed, orchestration 140 passed, 新增 15 passed

- [ ] **步骤 5**：提交 PR
  - Conventional commit: `fix(scheduler): add wall-clock timeouts for long-running tasks`
  - PR description 说明修复的风险点

### Phase 2（后续 PR）

- [ ] scheduled_tasks.json → SQLite 迁移
  - 新建 `ScheduledTaskRepository`
  - 迁移脚本
  - 单元测试 + 集成测试

---

## 风险评估与依赖

### 风险

1. **超时值设置不当**：
   - Evolution 任务 1800s 是否足够？需参考历史执行时间
   - WakeScheduler 30s 是否过短？需确认 resumer 实际耗时
   - **缓解**：环境变量可配，生产环境可调

2. **测试覆盖**：
   - 超时测试需要 mock LLM 调用 hang
   - **缓解**：使用 `asyncio.sleep(9999)` 模拟 hang

3. **py3.8 兼容性**：
   - 不能使用 `asyncio.TaskGroup`（3.11+）
   - **缓解**：使用显式 cancel + await 模式

### 依赖

- 无外部依赖
- 不影响前端
- 不影响 API 契约

---

## 验收标准

1. ✅ Evolution 任务超时时，日志记录错误并抛出 `TimeoutError`，不阻塞后续任务
2. ✅ WakeScheduler resumer 超时时，跳过该 wake 并记录警告，不阻塞消费循环
3. ✅ SubagentRunner watcher 在异常路径下被正确清理，无任务泄漏
4. ✅ 全量测试通过，无回归
5. ✅ 环境变量可配，生产环境可调整超时值

---

## 参考资料

- 代码分析报告：2026-10-15 长时任务运行机制技术分析报告
- 相关文件：
  - `backend/scheduler/evolution.py:43-56`
  - `backend/orchestration/wake_scheduler.py:119-127`
  - `backend/orchestration/subagent_runner.py:239-268`

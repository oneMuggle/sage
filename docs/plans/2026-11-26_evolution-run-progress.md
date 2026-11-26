# 进化任务进度可见与状态持久化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 解决「立即整理记忆」按钮执行中无进度、切页后状态重置且可能重复触发并发执行的问题：把进化任务从「同步 HTTP 请求」改为「服务端持有运行状态 + 前端轮询」，并给记忆反思任务加阶段级进度。

**Architecture:** 后端新增进程内 `EvolutionRunRegistry`（线程安全单例），作为进化任务运行的唯一状态源；手动触发端点改为异步启动（202 + 运行快照），cron 触发与补跑也经同一包装登记状态；记忆反思任务在阶段边界上报进度。前端新增 zustand store（参照 `designStore` 的轮询模式），轮询活在 store 层，组件卸载不丢状态；设置页两个入口（进化面板「立即整理记忆」、记忆设置「立即固化」）都改为读 store。

**Tech Stack:** FastAPI + APScheduler + threading（后端）；React + zustand + vitest（前端）。

**Spec:** 本计划即设计文档（前序会话已完成根因分析：`EvolutionPanel.tsx` 本地 useState + 同步 IPC + 后端无中间状态）。

## Global Constraints

- Python 3.8 运行时兼容（release/win7）：不用 `X | Y` 运行时类型（注解可加 `from __future__ import annotations`）、不用 `match`、不用 `dict[str, ...]` 运行时泛型。
- 后端测试运行环境：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`。
- 前端：`npm run lint`、`npx vitest run <files>`、`npx tsc --noEmit`（或项目既有 check 脚本）。
- 架构棘轮：`backend/scheduler/evolution.py` baseline 2374，当前 2061，本轮新增不得超过 +313 行；新文件不受影响。
- 双分支策略：本 PR 只动 main；win7 同步后续另行 cherry-pick（计划里不包含）。
- 计划文档完成后归档：功能实现后删除本文件，并入 `docs/technical/` 对应章节。

---

## 背景与根因（摘要）

1. **无进度**：`POST /api/v1/scheduled/evolution/{name}/run` 是同步端点，`task.run()` 内联执行（最长 30 分钟），仅在结束时写一条 `evolution_log`；`evolution_log.status` 取值域没有 `running`；任务内部阶段没有任何对外信号。
2. **状态重置**：`EvolutionPanel` 的 `runningTask`/`runMessage` 是组件本地 state，设置页切换 tab 或离开页面即卸载组件。任务本身不会取消（renderer 放弃 promise ≠ 取消请求；Electron main 的 fetch 与后端线程池均继续），但 UI 与任务失联，且按钮恢复可点会重复触发并发执行。
3. **隐藏隐患**：`run_evolution_task_now` 直接 `task.run()`，没有互斥；APScheduler 的 `max_instances=1` 只管 cron 触发的 job。

## 技术方案

### 后端

**新文件 `backend/scheduler/evolution_run_registry.py`** —— 进程内运行状态注册表：

- 每个任务名一条快照：`{run_id, name, state(running|succeeded|failed), trigger, phase, phase_label, progress{}, started_at(ms), finished_at, duration_ms, result, error}`。
- `begin(name, trigger)`：同任务已在 running → 返回 `None`（互斥）；否则生成 run_id 并登记。
- `update(name, run_id, phase, label, progress)`：仅匹配当前 run_id 且 running 时生效（旧线程的迟到上报不会污染新一轮）。
- `finish(name, run_id, result, error)`：写终态；`result` 统一序列化（`as_dict()` / `int` → `{"total": n}` / dict / None）。
- 进程重启即清空 —— 任务本身也随进程终止，不存在悬空 running；前端拿不到状态时回退到进化日志。
- `threading.Lock` 保护；`get_evolution_run_registry()` 单例。

**`backend/services/scheduler.py`**：

- `run_evolution_task_now(name)` 保留同步语义（补跑/运维用），内部改走 `_execute_evolution_task(name, task, trigger="catch_up")`，带互斥。
- 新增 `launch_evolution_task(name, trigger="manual") -> {"run": snapshot, "started": bool}`：已在 running 则直接返回当前快照（`started=False`，幂等 attach）；否则 `begin` + `threading.Thread(daemon=True)` 执行，立即返回。
- 新增 `_execute_evolution_task(name, task, trigger, run_id=None)`：注入进度回调、设置 `trigger` contextvar、执行 `task.run()`、`finish` 登记成功/失败、finally 清除回调。
- `_fire_evolution`（cron）改走同一包装（`trigger="scheduled"`）。
- 新增 `get_evolution_runs()`：`{name: snapshot}`。

**`backend/api/scheduled_router.py`**：

- `GET /scheduled/evolution/tasks` 每项追加 `"run": snapshot | null`。
- `POST /scheduled/evolution/{name}/run` 改为 `status_code=202`，返回 `{"name", "ok": true, "started": bool, "run": snapshot}`；未注册仍 404。

**`backend/scheduler/evolution.py`**：

- `BaseEvolutionTask` 增加 `set_progress_reporter(cb)` / `_report_progress(phase, label, **extra)`（旁路：无回调或回调异常都静默，绝不打断任务）。
- `MemoryReflectionTask` 上报阶段：`collect`（扫描记忆，scanned/recent_scanned/backlog_scanned）→ `group`（分组，groups）→ `dedupe`（启发式去重，deduped）→ `llm`（LLM 合并，llm_done/llm_total/merged/invalidated，逐组更新）→ `finalize`（写入结果）。

**`backend/scheduler/evolution_log.py`**：

- 新增 `contextvars` 的默认 trigger（`set_evolution_trigger` / `reset_evolution_trigger`）；`record_evolution_log` 的 `trigger_type` 改为可选，缺省读 contextvar（默认仍是 `"scheduled"`）。手动触发运行期间任务内部写的日志因此记为 `manual`。

**`backend/scheduler/evolution_maintenance.py`**：

- 补跑循环里先查 `registry.is_running(name)` 再调用，避免与手动运行撞互斥后被误记为失败（2 行）。

### 前端

**新文件 `src/entities/evolution/evolutionRunStore.ts`**（zustand）：

- `runs: Record<string, EvolutionRunSnapshot>`、`error`、`refresh()`、`trigger(name)`。
- 轮询在 store 层：`refresh()` 拉 `scheduled_evolution_tasks`，发现 running 则启动 1200ms 定时器，全部结束后停止；连续 3 次失败停止（避免打爆后端）。组件卸载不影响轮询。
- 观察到 `running → succeeded/failed` 的转换时：`toast.success/error` 提示一次（仅本 session 内观察到 running 的 run 才提示，避免首次挂载把历史结果误报成新完成）。

**`src/widgets/evolution/EvolutionPanel.tsx`**：

- 删除 `runningTask` / `runMessage` 本地 state，改读 store。
- mount 时 `refresh()`（重入恢复）；运行中按钮文案「整理中 · {phase_label}」；任务运行完成时立即刷新最近执行记录（不再等 60s 轮询）。
- 运行中显示阶段清单（扫描记忆 → 分组 → 去重 → LLM 合并 → 写入结果，含 k/N 与已耗时）；完成后在 `evolution-run-result` 展示统计摘要（保持游标过滤）。

**`src/pages/settings/MemoryTab.tsx`**：「立即固化」按钮改走同一 store（`memory_consolidation`），按钮态与结果都从 store 派生。

**`src/shared/api/memoryApi.ts`**：`runEvolutionTask` 改为触发语义（返回 `{started, run}`）；删除同步等待结果的 `runConsolidation`（唯一消费方 MemoryTab 同步改造）。

**`src/shared/api/types/domainEntityTypes.ts`**：新增 `EvolutionRunSnapshot`、`EvolutionTaskStatusEntry`、`EvolutionTaskTriggerResult`。

## 涉及文件清单

| 文件 | 动作 |
|---|---|
| `backend/scheduler/evolution_run_registry.py` | 新增 |
| `backend/services/scheduler.py` | 修改 |
| `backend/api/scheduled_router.py` | 修改 |
| `backend/scheduler/evolution.py` | 修改（BaseEvolutionTask + MemoryReflectionTask） |
| `backend/scheduler/evolution_log.py` | 修改（trigger contextvar） |
| `backend/scheduler/evolution_maintenance.py` | 修改（互斥跳过） |
| `backend/tests/unit/test_evolution_run_registry.py` | 新增 |
| `backend/tests/integration/test_evolution_run_api.py` | 改写为异步契约 |
| `backend/tests/unit/test_memory_reflection_p4.py` | 追加阶段进度用例 |
| `src/entities/evolution/evolutionRunStore.ts` | 新增 |
| `src/entities/evolution/__tests__/evolutionRunStore.test.ts` | 新增 |
| `src/widgets/evolution/EvolutionPanel.tsx` | 改写运行态 |
| `src/widgets/evolution/__tests__/EvolutionPanel.status.test.tsx` | 更新 |
| `src/pages/settings/MemoryTab.tsx` | 改 store |
| `src/shared/api/memoryApi.ts` | 触发语义 |
| `src/shared/api/__tests__/memoryConsolidation.test.ts` | 更新 |
| `src/shared/api/types/domainEntityTypes.ts` | 新增类型 |

## 实施步骤

- [x] **M1 后端注册表**：新增 `evolution_run_registry.py` + 单测（begin 互斥 / update 只认当前 run / finish 终态与耗时 / result 序列化 / 旧 run_id 迟到上报隔离）。
- [x] **M2 后端调度与 API**：`SchedulerService.launch_evolution_task` / `get_evolution_runs`（执行包装抽到 `backend/scheduler/evolution_runner.py`，守住 scheduler.py 800 行棘轮）；cron 与补跑走同一包装；API 改 202 + tasks 携带 run；更新集成测试（异步触发、already_running、失败终态、未知任务 404、无调度器 503）。
- [x] **M3 阶段进度**：`BaseEvolutionTask` 回调 + `MemoryReflectionTask` 五阶段上报；`evolution_log` trigger contextvar；补测试（不注入回调时零副作用；注入后阶段序列正确且游标不外泄）。
- [x] **M4 前端 store**：`evolutionRunStore` + 测试（映射快照、running 驱动轮询、全部结束停轮询、连续失败停止、触发后立即刷新、完成转换只提示一次）。
- [x] **M5 面板与记忆设置改造**：`EvolutionPanel`（重入恢复、阶段清单、完成刷新日志）、`MemoryTab`（store 驱动）、`memoryApi` 触发语义；更新既有测试，`vitest` + `tsc` + `eslint` 全绿。
- [ ] **M6 验证与文档**：本地测试与门禁已过（pytest 206 / vitest 208 文件 1130 用例 / 架构棘轮 / py38 兼容 / 静默异常棘轮）；待 PR 合并后归档：并入 `docs/technical/` 对应章节并删除本计划文件。

## 测试要点

- 后端：`test_evolution_run_api.py` 用 `threading.Event` 卡住 `task.run`，验证「POST 立即返回 running → GET 看到 running → 放行后 GET 看到 succeeded + result」；并发第二次 POST 返回 `started: false` 且 run_id 不变。
- 前端：mock `scheduled_evolution_tasks`，验证组件 mount 时从 running 快照恢复「执行中」按钮并 disabled；`run.result` 渲染为摘要；卸载再挂载（模拟切 tab）状态不丢。
- 回归：`EvolutionPanel.status.test.tsx` 既有状态渲染用例保持通过；MemoryTab 相关用例更新。

## 风险评估与依赖

- **API 契约变更**：`POST .../run` 从「同步返回结果」变为「202 + 快照」，两个前端消费方同步改造；无外部调用方（web 模式复用同一路由表）。
- **线程模型**：后台线程执行 `task.run()` 与 APScheduler worker 线程同模式（已有 cron 先例），SQLite 连接沿用现有线程使用方式；互斥由注册表保证。
- **进程重启**：内存注册表清空，任务随进程终止；前端拿不到 run 快照时回退进化日志，不产生悬空「执行中」。
- **i18n**：store 层完成 toast 先用中文文案（与现有进化面板文案一致），英文环境待后续统一。
- **win7**：本轮只做 main；cherry-pick 时注意 py3.8 兼容（本计划约束已覆盖）。

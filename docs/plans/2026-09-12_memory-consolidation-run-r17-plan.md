# Round 17 批次 B —— 记忆固化手动触发（管理面收口 · 差距 #3 前半）

> 来源：docs/technical/33-self-evolution.md「剩余已知差距」#3——curator/进化任务目前
> 仅 cron 触发（memory_consolidation 每周日 04:30），无手动入口、无前端管理面。
> **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。

## 侦察结论

- `SchedulerService.trigger_evolution_task(name)`（scheduler.py:266）与
  `get_evolution_task_names()`（:274）**已存在但零调用方**——缺的只是 HTTP 面。
- 既有 `POST /scheduled/tasks/{task_id}/run` 走 `run_now`，只查 JSON 持久化的
  用户任务表 `self._tasks`，**到不了** APScheduler 侧的 `evolution/<name>` job。
- `BaseEvolutionTask.run()` 返回任务统计；MemoryConsolidationTask 返回
  `{promoted, decayed, total}`（evolution.py:1072-1076）——可直接透出前端。
- `_fire_evolution` 吞异常记日志；手动触发沿用该语义（失败 → `ok: false`）。

## 改动

### 后端（py3.8 兼容写法，Optional/List/Dict 注解）
- `SchedulerService.run_evolution_task_now(name) -> Optional[Dict[str, Any]]`：
  同步运行并**捕获任务返回值**（区别于吞结果的 trigger_evolution_task）；
  未注册返回 None；异常记日志返回 None。
- `scheduled_router`：
  - `GET /scheduled/evolution/tasks` → `{tasks: [{name, job_id}]}`
  - `POST /scheduled/evolution/{name}/run` → `{name, ok, result}`；未注册 404。

### 前端
- `electron/commands.ts`：`scheduled_evolution_tasks`（GET）+ `scheduled_evolution_run`（POST 路径参数）。
- `memoryApi.runConsolidation()` / `memoryApi.getEvolutionTasks()`（走 invoke + withRetry 惯例）。
- `MemoryTab` 新增「记忆固化」卡：说明文案（每周日 04:30 自动执行；晋升
  高频短期记忆为语义记忆并衰减陈旧记忆）+「立即固化」按钮 + 结果回显
  （晋升 X · 衰减 Y）。卸载守卫（401/未初始化 503 → toast）。

## 测试
- 后端：路由集成测试（Mock SchedulerService）——列表、触发成功透出统计、
  未注册 404、scheduler 未初始化 503。
- 前端：memoryApi 通道参数测试；MemoryTab 固化卡交互测试（点击 → invoke →
  结果回显 / 失败 toast）。

## 不做
- 技能巡检事件驱动增量（差距 #3 后半，另行评估）；
- 记忆固化结果历史查询（evolution log 已有表，管理面后续批次）。

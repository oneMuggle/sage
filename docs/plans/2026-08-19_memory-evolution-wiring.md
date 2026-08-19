# P0 记忆系统 wire-up 修复 (PR-C, evolution + review wiring)

**Date:** 2026-08-19
**Branch:** `fix/memory-evolution-wiring` (基于 `origin/main` @ 331bd737)
**Author:** Claude (主从协作)
**Status:** 计划中

---

## 1. 背景与目标

### 1.1 来源
上一会话对比 Sage 产品内记忆系统与 Claude Code 记忆系统,
发现 Sage 后端有 3 处"代码已写好但生产路径未连线"的缺陷
(`docs/superpowers/ideas/` 暂存)。本次 PR 一次性修复这 3 处
最严重的 P0(都是"用户已付费使用、但功能静默失效")缺陷,
并 cherry-pick 到 `release/win7` LTS 分支。

### 1.2 涉及缺陷

| # | 缺陷 | 现状 | 用户感知影响 |
|---|---|---|---|
| §5.1 | 5 个 evolution 任务(`memory_pruning` / `importance_reevaluation` / `memory_consolidation` / `daily_summary` / `preference_learning`)未排程到 lifespan | `/api/v1/evolution/trigger` 手动触发可用,自动周期调度未启动 | 记忆库无限增长,过期不清理;用户偏好学习无效 |
| §5.2 | `ReviewQueue` 协作对象 `review_service` / `draft_store` 仅在测试手工注入 | 生产 hex/legacy 路径上 `complex_turn` 等触发只入队不产草稿 | "complex_turn 后自动提炼 SKILL" 工作流静默失效 |
| §5.4 | `electron/commands.ts` 缺 `search_memory` / `save_memory` 两个 IPC 桥 | 前端 `memoryApi.ts` 调用 `invoke('search_memory')` 会 404 | 用户无法从 Memory 页面搜索或手动新建记忆(只有列表/删除) |

### 1.3 目标
1. 三个 P0 缺陷全部修复并通过单元 + 集成测试
2. 现有 `ScheduledTask` 用户功能零回归(对 Phase 8 JSON 存储的 `SchedulerService` 兼容性测试)
3. `release/win7` LTS 分支 cherry-pick 同步,CI 5/5 +skip
4. 撰写 `docs/technical/` 技术文档章节 1 篇
5. 新建 project memory 记录本次 PR 决策与产物

---

## 2. 涉及的文件与模块

### 2.1 §5.1 — evolution 任务排程(C 路线)
- `backend/services/scheduler.py` — 扩展 `SchedulerService` 增加 `register_evolution_task()` 方法
- `backend/scheduler/__init__.py` — `create_evolution_tasks` 是唯一的任务工厂,继续作为生成入口
- `backend/scheduler/evolution.py` — 不改 task 类本身,仅确认 `BaseEvolutionTask.run_async()` 接口稳定
- `backend/main.py:182-193` lifespan — 在 `init_scheduler_service().start()` 后追加 evolution 任务注册
- `backend/config.yaml:32-49` evolution 段 — 当前已有结构,无改动
- `backend/tests/integration/test_evolution_scheduler_runs.py` — **新文件**,验证 lifespan 启动后 5 个任务确实排上
- `backend/tests/integration/test_legacy_scheduled_tasks_still_work.py` — **新文件**,验证 Phase 8 `ScheduledTask` 用户功能零回归
- `backend/scheduler/cron.py` — **删除**(替代方案)

### 2.2 §5.2 — ReviewQueue 协作对象早绑
- `backend/skills/review_bootstrap.py` — **新文件**,`bootstrap_review_collaborators()` 函数
- `backend/main.py:267-275` 之前插入一行调用
- `backend/skills/review_queue.py` — 加 setter 方法 `set_review_service()` / `set_draft_store()`(允许多次注入,幂等)
- `backend/skills/review_queue.py:162-170` `start()` 的 idempotent 行为确保:即使 boot 失败,start 一次即可
- `backend/tests/integration/test_review_queue_integration.py` — 加 `test_production_path_produces_draft` 用例

### 2.3 §5.4 — IPC 桥补全
- `electron/commands.ts:165` 之后补 `search_memory` / `save_memory` 两条
- 前端代码 `src/shared/api/memoryApi.ts` 不变(已经引用 invoke,只缺桥)
- 后端 `backend/api/legacy_routes.py:2479` `/memory/search` + `:2490` `/memory/save` 端点不动
- `electron/__tests__/commands.test.ts` — 加 2 个新 case 验证路径拼接

---

## 3. 技术方案

### 3.1 §5.1 — C 路线: 合并到 `SchedulerService`

#### 3.1.1 设计决策
- **唯一 cron runner**:删 `backend/scheduler/cron.py`,所有定时任务都走 `SchedulerService._scheduler: BackgroundScheduler`
- **现有用户** `ScheduledTask` 完全不动:JSON 文件存储、`add_task` API、路线不变
- **新增** `SchedulerService.register_evolution_task(name, task, cron_expr, hour, minute)`:
  - `name`:任务名(如 `"memory_pruning"`),生成 APScheduler job_id 为 `"evolution/" + name`(避开现有 `ScheduledTask.id` 的 `task-XXX` 前缀)
  - `task`:接受 `BaseEvolutionTask` 实例(向后兼容旧 sync 接口 + 接受 `async def`)
  - APScheduler `add_job` 时用 `lambda: self._fire_evolution(name, task)`,**绕过 JSON 持久化**
- **`max_instances=1, coalesce=True, misfire_grace_time=300`** — 复用现有 `_schedule_job` 的现代特性
- **lifespan 顺序**:
  1. `init_scheduler_service(...)` (Phase 8 用户任务)
  2. `scheduler_service.start()` (启动用户任务)
  3. `register_evolution_tasks(scheduler_service, config)` (注册 5 个 evolution 任务,无 start 需要)

#### 3.1.2 接口签名
```python
class SchedulerService:
    def register_evolution_task(
        self,
        name: str,
        task: "BaseEvolutionTask",  # type: ignore[name-defined]
        cron_expr: Optional[str] = None,
        hour: Optional[int] = None,
        minute: Optional[int] = None,
        day_of_week: Optional[int] = None,
    ) -> None:
        """Register an in-process evolution task (no JSON persistence).

        Cron format:
        - cron_expr: 5-field cron (preferred, e.g. "0 3 * * *")
        - hour/minute/(day_of_week): daily/weekly mode (back-compat)
        ...
        """
        if not (cron_expr or (hour is not None and minute is not None)):
            raise ValidationError("register_evolution_task: specify cron_expr or hour+minute")
        trigger = (
            CronTrigger.from_crontab(cron_expr)
            if cron_expr
            else (
                CronTrigger.from_crontab(f"{minute} {hour} * * {day_of_week or '*'}")
            )
        )
        job_id = f"evolution/{name}"
        ...
        self._scheduler.add_job(
            lambda: self._fire_evolution(name, task),
            trigger=trigger,
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
        logger.info("evolution task registered: %s (%s)", name, cron_expr or f"{hour:02d}:{minute:02d}")

    def _fire_evolution(self, name: str, task: "BaseEvolutionTask") -> None:
        try:
            result = task.run()  # BaseEvolutionTask.run() 同步包装 run_async()
            logger.info("evolution task %s completed: %s", name, result)
        except Exception:
            logger.exception("evolution task %s failed", name)
```

注意**不调用 `apscheduler.schedulers.background` 的 `get_job()` 来回查任务**,它通过 BackgroundScheduler 实例 list_jobs() 方法在测试中可见。

#### 3.1.3 lifespan 主程序代码草稿
```python
# 加载 config.yaml 的 evolution 段
import yaml
from pathlib import Path

_cfg_path = Path("backend/config.yaml")
_evo_cfg = {}
if _cfg_path.is_file():
    try:
        _evo_cfg = (yaml.safe_load(_cfg_path.read_text("utf-8")) or {}).get("evolution", {})
    except Exception as exc:
        logger.warning("config.yaml 解析失败, evolution 任务使用默认配置: %s", exc)

# 注册 5 个任务
from backend.scheduler.evolution import create_evolution_tasks

_evo_tasks = create_evolution_tasks(_evo_cfg.get("tasks", {}))
_schedule_map = {
    "daily_summary": ("0 3 * * *",),         # 每天 03:00
    "memory_pruning": ("0 3 * * *",),        # 每天 03:30
    "preference_learning": ("0 2 * * *",),   # 每天 02:00
    "importance_reevaluation": ("0 4 * * 0",),  # 周日 04:00
    "memory_consolidation": ("0 4 * * 0",),  # 周日 04:00
}
for task_name, task_inst in _evo_tasks.items():
    if task_name not in _schedule_map:
        continue
    cron_expr = _schedule_map[task_name][0]
    scheduler_service.register_evolution_task(
        name=task_name,
        task=task_inst,
        cron_expr=cron_expr,
    )
logger.info(
    "Evolution 任务已注册: %d 个 — %s",
    len(_schedule_map),
    list(_schedule_map.keys()),
)
```

### 3.2 §5.2 — ReviewQueue 协作对象早绑

#### 3.2.1 设计决策
- **早绑,fail-fast**:与现有 `init_scheduler_service` / `init_permission_gate` / `init_question_gate` 风格一致
- **协作对象都是 singleton**:ReviewService 自己构造(包 LLMClient 单例)、SkillDraftStore 是 `get_skill_draft_store()` 模块全局,**0 启动成本**
- **`ReviewQueue` 加 2 个 setter**:已经声明 `self.review_service = None` / `self.draft_store = None`,只缺 setter
- **bootstrap 文件** `backend/skills/review_bootstrap.py` 作为 wire-up 入口,被 `main.py` lifespan 在 `init_scheduler_service().start()` 之后、`Hex` 装配之前调用

#### 3.2.2 接口代码草稿
```python
# backend/skills/review_bootstrap.py
"""ReviewQueue 协作对象的启动期装配

所有依赖都是全局 singleton (ReviewService / SkillDraftStore)。
早绑策略与 scheduler_service / permission_gate / question_gate 保持一致
——启动期 fail-fast,不进 online 状态。
"""
import logging
from typing import Any

logger = logging.getLogger(__name__)


def bootstrap_review_collaborators(
    queue: Any = None,
    review_service: Any = None,
    draft_store: Any = None,
) -> None:
    """一次性把 ReviewService + SkillDraftStore 注入到 ReviewQueue。

    在 lifespan 启动期调用一次。生产环境无参,测试可全参注入 mock。
    """
    from backend.skills.review_queue import get_review_queue
    from backend.skills.review_service import get_review_service
    from backend.skills.draft_store import get_skill_draft_store

    if queue is None:
        queue = get_review_queue()
    if review_service is None:
        review_service = get_review_service()
    if draft_store is None:
        draft_store = get_skill_draft_store()

    queue.set_review_service(review_service)
    queue.set_draft_store(draft_store)
    logger.info(
        "ReviewQueue 协作对象已注入: review_service=%s draft_store=%s",
        type(review_service).__name__,
        type(draft_store).__name__,
    )
```

#### 3.2.3 setter 改动
```python
# backend/skills/review_queue.py
def set_review_service(self, review_service: object) -> None:
    """Inject the LLM-driven ReviewService. Idempotent: calling twice with
    the same instance is a no-op; calling with a different instance replaces.
    """
    if self.review_service is not None and self.review_service is not review_service:
        logger.warning(
            "ReviewQueue.review_service re-injected (was=%s, now=%s)",
            type(self.review_service).__name__,
            type(review_service).__name__,
        )
    self.review_service = review_service

def set_draft_store(self, draft_store: object) -> None:
    if self.draft_store is not None and self.draft_store is not draft_store:
        logger.warning(
            "ReviewQueue.draft_store re-injected (was=%s, now=%s)",
            type(self.draft_store).__name__,
            type(draft_store).__name__,
        )
    self.draft_store = draft_store
```

### 3.3 §5.4 — IPC 桥补全

简单的两行映射:
```typescript
// electron/commands.ts (在 delete_memory 行后面)
search_memory: {
  method: 'POST',
  path: () => '/api/v1/memory/search',
  body: (a) => ({
    query: a.query,
    memory_type: a.memoryType,
    limit: a.limit ?? 20,
  }),
},
save_memory: {
  method: 'POST',
  path: () => '/api/v1/memory/save',
  body: (a) => ({
    content: a.content,
    memory_type: a.memoryType,
    importance: a.importance,
    tags: a.tags,
  }),
},
```

后端端点 `POST /api/v1/memory/search` (路由方法:**POST**!虽然 search 是查询操作,但 `legacy_routes.py:2479` 用 `@router.post`)接收 `{query, memory_type, limit}` body 返回 `Memory[]`。`POST /api/v1/memory/save` (legacy_routes.py:2490) 接收 `{content, memory_type, importance, tags}` 返回创建的 `Memory` 对象。

---

## 4. 实施步骤(可独立验证的里程碑)

- [x] M1: 建 feature 分支 `fix/memory-evolution-wiring` (from `origin/main`)
- [ ] M2: §5.4 IPC 桥 — 第一个 commit,因为最简单、改动最小、可独立 verify
- [ ] M3: §5.2 ReviewQueue 协作对象 — 第二个 commit
- [ ] M4: §5.1 Evolution 任务排程(C 路线,合并到 SchedulerService) — 第三个 commit
- [ ] M5: 单元测试覆盖率 ≥ 80%
- [ ] M6: code-reviewer agent 检阅 diff
- [ ] M7: 推送 + 开 PR + 监控 CI 5/5 +skip
- [ ] M8: cherry-pick 到 `release/win7` LTS 分支 + 开 LTS PR
- [ ] M9: 撰写 `docs/technical/40-memory-system-wiring.md` 技术文档章节
- [ ] M10: 写项目记忆 `sage-p0-evolution-wiring-merged-yyyymmdd.md`

---

## 5. 风险评估与依赖

### 5.1 风险
| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| `SchedulerService.register_evolution_task` 改动影响现有用户任务 | 中 | 高(Phase 8 功能回归) | M6 + 单元测试 `test_legacy_scheduled_tasks_still_work` + 集成测试全跑一遍 |
| `BaseEvolutionTask.run()` 同步包装在 BackgroundScheduler daemon thread 中跑会阻塞 worker | 中 | 中(影响下次任务) | 复用现有 `asyncio.new_event_loop()` 模式,单任务最长超时未控——加 timeout=600s |
| `ReviewQueue` 加 setter 引入并发 race(lifespan 期 + 测试 reset) | 低 | 低 | setter 是简单赋值、GIL 保护;测试用 `reset_review_queue()` 时会调用 stop,文档说明 |
| Win7 LTS Py3.8 APScheduler 3.x 版本不兼容 Py3.11 已用 API | 低 | 中(cherry-pick 时检查) | `apscheduler>=3.6` 锁版本,在 `backend/requirements.txt` 注释 |
| `config.yaml` 在打包环境不存在(Electron 资源中可能没有) | 中 | 低 | 已有降级路径:`if _cfg_path.is_file()`,否则用硬编码默认调度 |

### 5.2 依赖
- 测试需要 `tempfile` 临时目录,`pytest` 已配置 — 无新依赖
- `apscheduler` 已在 `backend/requirements.txt` — 无新依赖
- `pyyaml` 已在 — `config.yaml` 解析需要
- win7 LTS Py3.8 兼容性:`apscheduler 3.x` 兼容,`4.x` 不兼容,**锁定 `apscheduler<4`**

### 5.3 与正在进行的其他 PR 的关系
- PR-B (Backend 异常退出自动重启, 已 merge @ 331bd737):无关,本 PR 是 PR-C
- v0.4.6-alpha-win7:本 PR cherry-pick 后发 v0.4.7-alpha.1-win7

---

## 6. 与现有规则的一致性

- [feature-development.md] 本文件即为计划文档
- [code-review.md] M6 由 code-reviewer agent 检阅
- [testing.md] M5 80% 覆盖率
- [git-workflow.md] 三个独立 commit,conventional commits 格式
- [branch-and-release-strategy.md] feature/fix/* → main = squash merge,release/* → master = merge commit --no-ff
- [feature-branch-workflow.md] 本 PR 在 fix/memory-evolution-wiring 分支,合并后自动清理
- [cicd-workflow.md] push + PR + gh run watch → 5/5 +skip
- [python-environment.md] 所有后端命令走 `/home/fz/anaconda3/envs/sage-backend/bin/python`

---

## 7. 退出标准(Definition of Done)

- [ ] 三个 P0 缺陷全部修复,evidence:测试报告
- [ ] 80%+ 单元测试覆盖率,evidence:pytest --cov
- [ ] tsc 0 错误,evidence:`npx tsc --noEmit`
- [ ] ESLint 0 新告警(对 electron/commands.ts),evidence:npm run lint
- [ ] code-reviewer agent Approve
- [ ] main 分支 PR 5/5 +skip
- [ ] release/win7 分支 cherry-pick PR 5/5 +skip
- [ ] 技术文档章节完成
- [ ] 项目记忆完成

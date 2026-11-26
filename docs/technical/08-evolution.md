# Sage - 进化系统

## 8.1 进化系统概述

### 8.1.1 设计理念

进化系统让 Sage 能够:

1. **自我优化** - 从交互中学习，不断改进
2. **适应用户** - 理解用户偏好，个性化服务
3. **知识沉淀** - 将对话中的知识转化为长期记忆

### 8.1.2 进化维度

| 维度     | 方式           | 触发条件    |
| -------- | -------------- | ----------- |
| 记忆进化 | 摘要/压缩/遗忘 | 定时 + 阈值 |
| 偏好学习 | 反馈强化       | 用户评分    |
| 技能进化 | 模式提取       | 对话分析    |
| 响应优化 | RL 风格调整    | 使用统计    |

---

## 8.2 进化架构

### 8.2.1 系统架构

```
┌─────────────────────────────────────────────────────────────────┐
│                       Evolution System                             │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│   ┌─────────────────┐   ┌─────────────────┐                   │
│   │  EvolutionLog   │   │  EvolutionScheduler │               │
│   │   (进化日志)    │   │   (调度器)      │                   │
│   └────────┬────────┘   └────────┬────────┘                   │
│            │                      │                              │
│            ▼                      ▼                              │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                    Evolution Engine                      │  │
│   │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐    │  │
│   │  │ Summarizer│ │ Pruner │ │ Learner │ │Optimizer│    │  │
│   │  │ (摘要)   │ │ (修剪)  │ │ (学习)  │ │ (优化)  │    │  │
│   │  └─────────┘ └─────────┘ └─────────┘ └─────────┘    │  │
│   └─────────────────────────────────────────────────────────┘  │
│                            │                                      │
│                            ▼                                      │
│   ┌─────────────────────────────────────────────────────────┐  │
│   │                    Memory System                         │  │
│   │          (Working / Episodic / Semantic)                │  │
│   └─────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### 8.2.2 进化流程

```
┌─────────────────────────────────────────────────────────────┐
│                     Evolution Cycle                             │
│                                                             │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                  1. Collect                          │   │
│   │   用户反馈 / 对话历史 / 使用统计 / 错误记录          │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                  2. Analyze                          │   │
│   │   模式识别 / 质量评估 / 偏好挖掘                     │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                  3. Optimize                         │   │
│   │   参数调整 / 记忆更新 / 技能优化                     │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│   ┌─────────────────────────────────────────────────────┐   │
│   │                  4. Validate                         │   │
│   │   A/B 测试 / 效果评估 / 回滚机制                     │   │
│   └──────────────────────────┬──────────────────────────┘   │
│                              │                               │
│                              ▼                               │
│                       Next Cycle                               │
└─────────────────────────────────────────────────────────────┘
```

---

## 8.3 进化任务

### 8.3.1 每日摘要

```python
# backend/scheduler/evolution.py
class DailySummaryTask:
    """每日对话摘要任务"""

    def __init__(self, memory_manager, llm_client):
        self.memory = memory_manager
        self.llm = llm_client

    async def run(self):
        """执行每日摘要"""
        logger.info("开始执行每日摘要...")

        # 1. 获取今日所有会话
        sessions = await self._get_today_sessions()

        for session in sessions:
            # 2. 获取会话消息
            messages = await self._get_session_messages(session.id)

            if len(messages) < 3:
                continue

            # 3. 生成摘要
            summary = await self._generate_summary(messages)

            # 4. 保存到情景记忆
            await self.memory.memorize(
                content=summary,
                memory_type="episodic",
                importance=6,  # 每日摘要重要性偏高
                metadata={
                    "type": "daily_summary",
                    "session_id": session.id,
                    "date": self._today()
                }
            )

            # 5. 标记会话已摘要
            await self._mark_summarized(session.id)

        logger.info(f"每日摘要完成，处理 {len(sessions)} 个会话")

    async def _generate_summary(self, messages: List[dict]) -> str:
        """生成对话摘要"""
        # 提取关键信息
        topics = self._extract_topics(messages)
        outcomes = self._extract_outcomes(messages)
        preferences = self._extract_preferences(messages)

        prompt = f"""请总结以下对话的要点:

主题: {topics}
结果: {outcomes}
用户偏好: {preferences}

生成一段简洁的摘要 (100字以内)，突出重点。"""

        result = await self.llm.complete(prompt)
        return result.strip()

    def _extract_topics(self, messages: List[dict]) -> List[str]:
        """提取主题"""
        # 简单关键词提取
        # TODO: 使用 LLM 或关键词提取库
        return []

    def _extract_outcomes(self, messages: List[dict]) -> List[str]:
        """提取结果"""
        return []
```

### 8.3.2 记忆修剪

```python
class MemoryPruningTask:
    """记忆修剪任务 - 清理低价值记忆"""

    def __init__(self, db):
        self.db = db

    async def run(self):
        """执行记忆修剪"""
        logger.info("开始记忆修剪...")

        deleted = 0

        # 1. 删除过期记忆
        deleted += await self._delete_expired()

        # 2. 删除极低价值记忆
        deleted += await self._delete_low_value()

        # 3. 清理孤儿记忆 (无关联会话)
        deleted += await self._delete_orphaned()

        # 4. 超过上限时删除最旧的
        deleted += await self._enforce_limit(limit=1000)

        logger.info(f"记忆修剪完成，删除了 {deleted} 条记忆")
        return deleted

    async def _delete_expired(self) -> int:
        """删除过期记忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM memories_episodic
            WHERE expires_at IS NOT NULL
            AND expires_at < ?
        """, [int(time.time())])
        return cursor.rowcount

    async def _delete_low_value(self) -> int:
        """删除低价值记忆"""
        cursor = self.db.cursor()
        # 删除重要性极低且长时间未访问
        cursor.execute("""
            DELETE FROM memories_episodic
            WHERE importance <= 1
            AND access_count = 0
            AND created_at < ?
        """, [int(time.time()) - 30 * 24 * 3600])  # 30 天
        return cursor.rowcount

    async def _delete_orphaned(self) -> int:
        """删除孤儿记忆"""
        cursor = self.db.cursor()
        cursor.execute("""
            DELETE FROM memories_episodic
            WHERE session_id IS NOT NULL
            AND session_id NOT IN (SELECT id FROM sessions)
        """)
        return cursor.rowcount

    async def _enforce_limit(self, limit: int) -> int:
        """强制限制记忆数量"""
        cursor = self.db.cursor()

        # 获取当前数量
        cursor.execute("SELECT COUNT(*) FROM memories_episodic")
        count = cursor.fetchone()[0]

        if count <= limit:
            return 0

        # 删除最旧、最不重要的记忆
        excess = count - limit
        cursor.execute("""
            DELETE FROM memories_episodic
            WHERE id IN (
                SELECT id FROM memories_episodic
                ORDER BY importance ASC, created_at ASC
                LIMIT ?
            )
        """, (excess,))

        return cursor.rowcount
```

### 8.3.3 偏好学习

```python
class PreferenceLearningTask:
    """偏好学习任务 - 从反馈中学习"""

    def __init__(self, memory_manager, llm_client):
        self.memory = memory_manager
        self.llm = llm_client

    async def run(self):
        """执行偏好学习"""
        # 1. 获取近期反馈
        feedback = await self._get_recent_feedback()

        if not feedback:
            return

        # 2. 分析偏好模式
        preferences = self._analyze_preferences(feedback)

        # 3. 更新用户画像
        await self._update_user_profile(preferences)

    async def _get_recent_feedback(self) -> List[dict]:
        """获取近期反馈"""
        cursor = self.db.cursor()
        cursor.execute("""
            SELECT * FROM messages
            WHERE role = 'user'
            AND content LIKE '%反馈%' OR content LIKE '%评分%'
            ORDER BY created_at DESC
            LIMIT 20
        """)
        return [dict(row) for row in cursor.fetchall()]

    def _analyze_preferences(self, feedback: List[dict]) -> dict:
        """分析偏好"""
        # 简化实现
        # TODO: 使用 LLM 分析
        return {
            "response_length": "medium",
            "tone": "friendly",
            "detail_level": "detailed"
        }

    async def _update_user_profile(self, preferences: dict):
        """更新用户画像"""
        # 保存到语义记忆
        profile_text = "\n".join([
            f"{k}: {v}" for k, v in preferences.items()
        ])

        await self.memory.memorize(
            content=f"用户偏好总结: {profile_text}",
            memory_type="semantic",
            importance=9,  # 偏好很重要
            metadata={"type": "user_profile"}
        )
```

### 8.3.4 重要性重评估

```python
class ImportanceReevaluationTask:
    """重要性重评估任务"""

    def __init__(self, db):
        self.db = db

    async def run(self):
        """执行重评估"""
        cursor = self.db.cursor()

        # 1. 重评估长期未访问的高重要性记忆
        cursor.execute("""
            SELECT * FROM memories_episodic
            WHERE importance >= 7
            AND access_count < 2
            AND created_at < ?
        """, [int(time.time()) - 7 * 24 * 3600])  # 7 天

        for row in cursor.fetchall():
            memory = dict(row)
            # 如果高重要性记忆很少被访问，降低重要性
            new_importance = max(5, memory["importance"] - 1)

            cursor.execute("""
                UPDATE memories_episodic
                SET importance = ?
                WHERE id = ?
            """, [new_importance, memory["id"]])

        # 2. 重评估频繁访问的低重要性记忆
        cursor.execute("""
            SELECT * FROM memories_episodic
            WHERE importance <= 4
            AND access_count >= 5
        """, [])

        for row in cursor.fetchall():
            memory = dict(row)
            # 如果低重要性记忆被频繁访问，提高重要性
            new_importance = min(10, memory["importance"] + 1)

            cursor.execute("""
                UPDATE memories_episodic
                SET importance = ?
                WHERE id = ?
            """, [new_importance, memory["id"]])

        self.db.commit()
```

---

## 8.4 进化调度器

### 8.4.1 Scheduler

```python
# backend/scheduler/cron.py
import asyncio
from datetime import datetime, time
from typing import List, Callable
import logging

logger = logging.getLogger(__name__)

class EvolutionScheduler:
    """进化任务调度器"""

    def __init__(self):
        self.tasks: List[dict] = []
        self.running = False

    def add_task(
        self,
        name: str,
        task: Callable,
        schedule: str  # cron 表达式或 "daily", "weekly"
    ):
        """添加任务"""
        self.tasks.append({
            "name": name,
            "task": task,
            "schedule": schedule,
            "last_run": None
        })

    async def start(self):
        """启动调度器"""
        self.running = True
        logger.info(f"进化调度器启动，共 {len(self.tasks)} 个任务")

        while self.running:
            now = datetime.now()

            for task_info in self.tasks:
                if self._should_run(task_info, now):
                    await self._run_task(task_info)

            # 每分钟检查一次
            await asyncio.sleep(60)

    def _should_run(self, task_info: dict, now: datetime) -> bool:
        """判断是否应该运行"""
        schedule = task_info["schedule"]
        last_run = task_info["last_run"]

        if schedule == "daily":
            # 每天凌晨 3 点
            if now.hour == 3 and now.minute == 0:
                if last_run is None or last_run.date() != now.date():
                    return True

        elif schedule == "weekly":
            # 每周日凌晨 4 点
            if now.weekday() == 6 and now.hour == 4 and now.minute == 0:
                if last_run is None or (now - last_run).days >= 7:
                    return True

        return False

    async def _run_task(self, task_info: dict):
        """运行任务"""
        name = task_info["name"]
        task = task_info["task"]

        logger.info(f"开始执行进化任务: {name}")
        start_time = time.time()

        try:
            await task.run()

            task_info["last_run"] = datetime.now()
            logger.info(f"进化任务完成: {name} ({(time.time() - start_time):.2f}s)")

            # 记录到日志
            await self._log_evolution(name, "success", None)

        except Exception as e:
            logger.error(f"进化任务失败: {name}, {e}")
            await self._log_evolution(name, "failed", str(e))

    async def _log_evolution(
        self,
        task_name: str,
        status: str,
        error: str
    ):
        """记录进化日志"""
        cursor = self.db.cursor()
        cursor.execute("""
            INSERT INTO evolution_log
            (id, evolution_type, description, status, error_message, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(uuid.uuid4()),
            "scheduled",
            f"Task: {task_name}",
            status,
            error,
            int(time.time())
        ))
        self.db.commit()
```

### 8.4.2 初始化调度器

```python
# backend/scheduler/__init__.py
def create_evolution_scheduler(
    memory_manager,
    llm_client,
    db
) -> EvolutionScheduler:
    """创建进化调度器"""
    scheduler = EvolutionScheduler(db)

    # 添加每日任务
    scheduler.add_task(
        name="daily_summary",
        task=DailySummaryTask(memory_manager, llm_client),
        schedule="daily"
    )

    scheduler.add_task(
        name="memory_pruning",
        task=MemoryPruningTask(db),
        schedule="daily"
    )

    scheduler.add_task(
        name="importance_reevaluation",
        task=ImportanceReevaluationTask(db),
        schedule="weekly"
    )

    scheduler.add_task(
        name="preference_learning",
        task=PreferenceLearningTask(memory_manager, llm_client),
        schedule="daily"
    )

    return scheduler
```

---

## 8.5 进化配置

### 8.5.1 配置文件

```yaml
# backend/config.yaml
evolution:
  enabled: true

  tasks:
    daily_summary:
      enabled: true
      time: '03:00'
      min_messages: 3

    memory_pruning:
      enabled: true
      time: '03:30'
      max_memories: 1000
      auto_delete_below: 1

    importance_reevaluation:
      enabled: true
      day: 'sunday'
      time: '04:00'

    preference_learning:
      enabled: true
      time: '02:00'

  thresholds:
    high_importance: 7
    low_importance: 4
    access_count_low: 2
    access_count_high: 5
    days_inactive: 30
```

---

## 8.6 进化日志

### 8.6.1 日志表

```sql
CREATE TABLE evolution_log (
    id TEXT PRIMARY KEY,
    evolution_type TEXT NOT NULL,
    description TEXT NOT NULL,
    before_state TEXT,
    after_state TEXT,
    trigger_type TEXT,
    trigger_condition TEXT,
    status TEXT DEFAULT 'pending',
    error_message TEXT,
    tokens_used INTEGER,
    created_at INTEGER NOT NULL,
    completed_at INTEGER
);
```

### 8.6.2 查询日志

```python
async def get_evolution_history(limit: int = 50) -> List[dict]:
    """获取进化历史"""
    cursor = db.cursor()
    cursor.execute("""
        SELECT * FROM evolution_log
        ORDER BY created_at DESC
        LIMIT ?
    """, (limit,))

    return [dict(row) for row in cursor.fetchall()]
```

---

## 8.7 手动维护任务与运行状态可见性

> 2026-11 新增。解决「立即整理记忆」执行中无进度、切页后按钮状态重置、可重复触发并发执行的问题。

### 8.7.1 问题与设计

此前 `POST /api/v1/scheduled/evolution/{name}/run` 为同步端点，`task.run()` 在请求线程内联执行
（wall-clock 上限 30 分钟，`SAGE_EVOLUTION_TASK_TIMEOUT_S`），仅在结束时写一条 `evolution_log`；
前端运行态是 `EvolutionPanel` 组件本地 `useState`，设置页只渲染当前 tab，切 tab/离开页面即卸载组件 → 状态归零。
任务本身不会因前端放弃等待而取消（Electron 主进程 fetch 与 FastAPI 线程池均继续），
但 UI 与任务失联，按钮恢复可点会造成并发重复执行（APScheduler `max_instances=1` 只约束 cron 触发的实例）。

设计原则（job-owned, not view-owned）：

- 任务所有权归服务端：进程内 `EvolutionRunRegistry` 是运行状态唯一来源；
- 单一状态源 + 可重入恢复：前端任何页面挂载即拉取快照恢复；
- 阶段级进度：任务在阶段边界上报；
- 幂等 / 互斥：同一任务运行中再次触发幂等 attach，不产生第二个实例。

### 8.7.2 后端实现

| 组件 | 位置 | 职责 |
| --- | --- | --- |
| `EvolutionRunRegistry` | `backend/scheduler/evolution_run_registry.py` | 每任务一条快照（running/succeeded/failed）；begin 互斥；update 仅认当前 run_id（旧 run 迟到上报隔离）；finish 归一化 result；线程锁保护；进程重启清空（任务随进程终止，无悬空 running） |
| `run_evolution_task` | `backend/scheduler/evolution_runner.py` | 手动 / cron / 补跑共用执行包装：注入进度回调、登记终态、contextvar 传递 trigger_type |
| `launch_evolution_task` / `get_evolution_runs` | `backend/services/scheduler.py` | 异步启动（daemon 线程）与快照读取 |
| 阶段上报 | `backend/scheduler/evolution.py` | `BaseEvolutionTask._report_progress`（旁路，异常不打断任务）；`MemoryReflectionTask` 五阶段：collect → group → dedupe → llm（k/N）→ finalize |
| trigger_type | `backend/scheduler/evolution_log.py` | `record_evolution_log` 缺省读 contextvar，手动触发运行期间写 `manual` |

API 契约：

```
GET  /api/v1/scheduled/evolution/tasks
     → {tasks: [{name, job_id, run}]}
POST /api/v1/scheduled/evolution/{name}/run   (202)
     → {name, ok, started, run}
     started=false 表示该任务已在运行，本次请求幂等 attach 到当前 run
```

`run` 快照字段：`run_id / name / state(running|succeeded|failed) / trigger / phase /
phase_label / progress{} / started_at（epoch 毫秒） / finished_at / duration_ms / result / error`。

补跑（`evolution_maintenance`）先查 `is_running` 跳过在跑任务，避免撞互斥被误记为失败；
`services/scheduler.py` 保持 800 行架构棘轮内（执行包装抽到独立模块）。

### 8.7.3 前端实现

- `src/entities/evolution/evolutionRunStore.ts`：zustand store，轮询
  `scheduled_evolution_tasks`（1200ms，仅在存在 running 时启动，全部结束停止，连续 3 次失败停止）；
  running → 终态转换 toast 一次；轮询在 store 层，组件卸载不丢状态。
- `EvolutionPanel`：按钮显示「整理中 · 当前阶段」，阶段清单
  （扫描记忆 → 分组 → 去重 → LLM 合并 k/N → 写入结果）+ 已耗时；
  完成后展示统计摘要并立即刷新最近执行记录；挂载时重入恢复。
- `MemoryTab` 的「立即固化」共用同一 store（按钮态与结果均派生）。
- `memoryApi.runEvolutionTask` 为异步触发语义（返回 `{started, run}`），结果经快照轮询获取。

### 8.7.4 测试

- 后端：注册表互斥 / 迟到上报隔离 / 终态与 result 序列化；API 异步契约
  （202、running 快照、already_running attach 同一 run_id、失败终态、404/503）；
  反思任务阶段序列与回调异常吞掉。
- 前端：store 映射 / 轮询启停 / 连续失败停止 / 完成提示一次；
  组件卸载再挂载恢复运行中状态。

---

_文档版本: v1.0_

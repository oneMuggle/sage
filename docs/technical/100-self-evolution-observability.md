# 100 — 自进化可观测性与反馈闭环（P0 三件套）

> **实现日期**：2026-10-26
> **分支**：`feat/self-evolution-observability`（基于 `main` @ 7b3da63e5）
> **范围**：P0-1 进化日志结构化 / P0-2 偏好注入 `user_profile` / P0-3 召回反馈落库 + A/B 变体可比较
>
> 体系总览见 [33-self-evolution.md](./33-self-evolution.md)；
> 记忆三层架构与画像语义见 [39-memory-user-profile.md](./39-memory-user-profile.md)。

---

## 1. 背景

上一轮对 Sage 自进化能力做全面审计，结论是"进化任务照常执行、照常写日志，
但**执行效果既不可度量、也不回流到下一次进化**"。三处断链：

| 编号 | 断链 | 证据 |
| --- | --- | --- |
| P0-1 | 进化日志只有自由文本，无法跨任务比对 | 6 个 `_log_evolution` 各自维护一份近重复 SQL；`tokens_used` 列从无写入点；`MemoryReflectionTask` 算出的 `stats` 算完即丢 |
| P0-2 | 学到的偏好进不了 prompt | `PreferenceLearningTask` 写 `preferences` 表 `pref_*` 键，但 prompt 注入只读 `user_profile`（`backend/adapters/out/memory/adapter.py`）—— 两个存储从未连通 |
| P0-3 | 召回没有反馈信号 | `RecallEvaluator.log_retrieval` 接受 `user_feedback` 参数，但生产调用方从不传；日志是纯内存 list，重启即丢 |

P1/P2（自适应融合权重、偏好学习降级、技能自动审批等）依赖本轮产出的度量数据，
留待下一轮基于真实数据设计。

---

## 2. P0-1 进化日志结构化

### 2.1 数据模型

`evolution_log` 表新增两列（`backend/data/database.py`）：

```sql
ALTER TABLE evolution_log ADD COLUMN duration_ms INTEGER;
ALTER TABLE evolution_log ADD COLUMN metrics_json TEXT;
```

沿用本项目既有的 inline 迁移模式（`CREATE TABLE IF NOT EXISTS` +
`try/except sqlite3.OperationalError` 包裹 `ALTER TABLE ADD COLUMN`）——
这是对抗"两个进程共享同一个 `data/sage.db`"的既有防御，不能省。

### 2.2 统一写入器

新文件 `backend/scheduler/evolution_log.py`：

```python
record_evolution_log(
    db, *,
    evolution_type, description,
    status="success", error_message=None,
    before_state=None, after_state=None,
    trigger_type="scheduled", trigger_condition=None,
    duration_ms=None, metrics=None,
) -> str | None
```

- **best-effort**：写失败只 `logger.warning`，**绝不**让进化任务失败。
  日志缺失可接受，进化中断不可接受。
- `metrics` 以 `json.dumps(..., ensure_ascii=False, default=str)` 存 `metrics_json`；
  非 dict / 空 dict 视为无指标。
- `metrics_json` 超过 4000 字符会被截断并追加 `…(truncated)`，防止单行日志膨胀。
- `duration_ms` 由 `elapsed_ms(started_at)` 计算，用 `time.monotonic()`
  而非 `time.time()` —— 后者会被系统时钟调整影响，可能算出负数或虚高耗时。

### 2.3 6 个 task 收编

`backend/scheduler/evolution.py` 原有 6 处 `_log_evolution`（各自一份近重复 SQL），
统一改为委托 `record_evolution_log`。改造后 `evolution.py` **净减行**
（删 6 份重复 SQL，换成 6 个 3-5 行的委托调用），
因此 `architecture-baseline.json` 中该文件的条目无需下调。

各 task 补齐：

1. **duration_ms** —— task 开始/结束取 `time.monotonic()` 差值。
2. **metrics** —— task 已经在算但没落库的统计量。例：
   `MemoryReflectionTask.run_async` 的 `{"scanned": N, "deduped": N, "merged": N, "invalidated": N}`。

### 2.4 API 层

`backend/api/legacy_models.py` 的 `EvolutionLogResponse` **必须**加两字段：

```python
duration_ms: int | None = None
metrics_json: str | None = None
```

否则 FastAPI 的 pydantic 过滤会把新列**静默丢弃** —— 这是最容易漏的一步。
对应路由的 SELECT 也要补两列，否则永远是 `None`。

---

## 3. P0-2 偏好注入 user_profile

### 3.1 关键约束：hermes 冻结快照语义

`backend/memory/user_profile.py` 的 `add()` **故意不刷新冻结快照**
（源码注释：「写入路径不刷新冻结快照（hermes 语义：保 prefix cache）」）。
这是有意的性能设计 —— 快照重建会让 prefix cache 失效。

因此**不能在进化任务里调 `invalidate()`**。本轮的做法：

- 进化任务把学到的偏好**写入** `user_profile`（不刷新快照）
- 提供**显式**的 `POST /api/v1/memory/profile/refresh` 让用户决定何时刷新
- 进化任务自身**不**触发刷新

既接上了线，又不破坏 cache 语义，且刷新时机对用户可见可控。

### 3.2 写入路径

`PreferenceLearningTask` 原本只写 `memories_semantic` 与 `preferences` 表的
`pref_*` 键，本轮**新增**写 `user_profile` 条目（`category="preference"`）。

`user_profile.add()` 自带安全扫描、category 白名单、importance clamp(1-10)、
去重、200 字上限、environment 溢出修剪 —— 直接复用，不要另写一套。

### 3.3 API

| 路由 | 方法 | 说明 |
| --- | --- | --- |
| `/api/v1/memory/preferences/learned` | GET | 列出已学到的偏好（`preferences` 表 `pref_*` 键） |
| `/api/v1/memory/preferences/learned` | PUT | 手动纠正某条偏好（写 `preferences` + `user_profile`） |
| `/api/v1/memory/profile/refresh` | POST | 显式重建 `user_profile` 冻结快照 |

`PUT /memory/preferences/learned` 的 body 是 `{key, value}`，
`key` 必须以 `pref_` 开头（否则 422），`value` 不能为空。
该路由**同步**写 `user_profile`（同样不 `invalidate`）——
手动纠正立即进冻结快照候选集；若要立刻生效，用户再调 refresh。

> **与原方案的偏差**：原计划用 `extra="forbid"` 的 pydantic body 拒绝多余字段，
> 实际实现用的是裸 `dict` + 手工校验。多余字段被静默忽略（不报错，但也不生效）。

---

## 4. P0-3 召回反馈信号与指标落库

### 4.1 采集点

`backend/adapters/out/memory/adapter.py` 的召回路径早已在做 A/B 权重实验：

| 变体 | 融合权重 |
| --- | --- |
| A | `[0.2, 0.8]`（嵌入器基线） |
| B | `[0.5, 0.5]`（均权对照） |

选路用 `md5(query).hexdigest()[:8] % 2`（奇偶二分），
但**两个变体从未被分别度量过** —— `variant` 没有落到任何地方，也没有反馈信号可比。
本轮在这条路径上：

1. 计算 `query_hash = md5(query).hexdigest()`
2. 写一条 `memory_recall_log`（`variant` / `weights_json` / `result_count` / `session_id`）
3. 反馈由前端通过 `POST /memory/recall/feedback` 回填 `user_feedback` 列

**hash 与 variant 必须同口径**：变体选路取的是同一个 md5 的**前 8 位**，
`query_hash()` 返回完整 hexdigest —— 前 8 位一致，因此 hash 与 variant 永远对得上，
实验可复现。**只存 hash，不存 query 原文**（避免隐私内容落库）。

### 4.2 数据模型

```sql
CREATE TABLE IF NOT EXISTS memory_recall_log (
    id TEXT PRIMARY KEY,
    query_hash TEXT NOT NULL,        -- md5(query)，与 adapter 选变体同口径
    session_id TEXT,
    variant TEXT,                    -- 'A' | 'B'
    weights_json TEXT,               -- '[0.2, 0.8]' 之类
    result_count INTEGER,
    user_feedback TEXT,              -- 'up' | 'down' | NULL
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_recall_log_created
    ON memory_recall_log(created_at);
```

### 4.3 存储层

新文件 `backend/memory/recall_log_store.py`：

| 函数 | 职责 |
| --- | --- |
| `query_hash(query)` | md5 指纹（与 adapter 同口径） |
| `record_recall(db, ...)` | 写一条召回事件，返回 `log_id`（失败返回 `None`） |
| `set_feedback(db, log_id, feedback)` | 回填反馈，仅接受 `'up'` / `'down'` |
| `aggregate_metrics(db)` | 总体指标 + **按变体分组**的对比 |
| `list_recent(db, limit)` | 最近召回事件（供前端展示） |

全部写入路径是 **best-effort**：召回是热路径，写库失败只记日志，绝不阻塞返回。

### 4.4 两个满意度口径

| 字段 | 分母 | 含义 |
| --- | --- | --- |
| `satisfaction_rate` | **全部召回**（`positive / total`） | 与 `RecallEvaluator` 内存路径口径一致，两条路径可直接比较 |
| `feedback_satisfaction_rate` | **有反馈的召回**（`positive / feedback_count`） | 在给了反馈的那些次里，好评占多少 |

分母为 0 时两个率均为 `0.0`（不除零）。A/B 对比用的是
`feedback_satisfaction_rate` —— 因为"哪些召回更值得点赞"只在有反馈的样本里有意义。

### 4.5 API

| 路由 | 方法 | 说明 |
| --- | --- | --- |
| `/api/v1/memory/recall/metrics` | GET | `{metrics, recent}`；`metrics.by_variant` 是 A/B 对比数据 |
| `/api/v1/memory/recall/feedback` | POST | body `{log_id, feedback}`，`feedback` 受 `^(up\|down)$` 约束 |

---

## 5. 前端

### 5.1 组件

| 组件 | 文件 | 职责 |
| --- | --- | --- |
| `EvolutionLog` | `src/widgets/evolution/EvolutionLog.tsx` | 展示 duration + metrics（`parseEvolutionMetrics` 解析 `metrics_json`） |
| `LearnedPreferences` | `src/widgets/evolution/LearnedPreferences.tsx` | 已学偏好列表 + 手动纠正 + 刷新画像快照 |
| `RecallMetrics` | `src/widgets/evolution/RecallMetrics.tsx` | 召回指标 + **A/B 变体对比表** + 👍/👎 反馈入口 |

三个组件都挂在设置页的「进化」tab（`src/pages/settings/Settings.tsx`），
由 `EvolutionPanel` / `LearnedPreferences` / `RecallMetrics` / `EvolutionLog` 依次渲染。

> **与原方案的偏差**：原计划把「已学偏好」与「召回指标」塞进 `EvolutionLog.tsx`，
> 实际拆成两个独立组件 —— `EvolutionLog.tsx` 已有 299 行，混进去会突破单文件职责边界。

### 5.2 A/B 对比结论的判定

`RecallMetrics.tsx` 的 `compareVariants(byVariant)` 是纯函数，便于单测：

- 变体不足 2 个 → 「只有一个变体有数据，暂无对比」
- **任一侧** `feedback_count < 5` → 「反馈量不足」，不给出领先方
- 否则比较两侧 `feedback_satisfaction_rate`，给出领先方与差值（百分点）
- 两侧相等 → 「两个变体的反馈满意度持平」

「任一侧不足 5 条就不下结论」是刻意保守：反馈量不足时任何"哪个更好"的判断都是噪音。
变体名按字母序定位 A/B（`by_variant` 的键序来自 SQL `GROUP BY`，不保证）。

### 5.3 IPC 路由

`electron/commandRoutes/memory.ts` 新增 5 条（`/api/v1/memory/*` 路由按项目约定归此文件）：

| IPC 命令 | HTTP |
| --- | --- |
| `get_learned_preferences` | `GET /api/v1/memory/preferences/learned` |
| `update_learned_preference` | `PUT /api/v1/memory/preferences/learned` |
| `refresh_user_profile` | `POST /api/v1/memory/profile/refresh` |
| `get_recall_metrics` | `GET /api/v1/memory/recall/metrics?limit=N` |
| `submit_recall_feedback` | `POST /api/v1/memory/recall/feedback` |

body 键按 `CommandRoute` 约定做 camelCase → snake_case 转换
（`logId` → `log_id`）；body 函数的**输出**不做反向转换。

---

## 6. 测试

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/test_evolution_log_structured.py` | P0-1：`record_evolution_log` 的 metrics 序列化 / 截断 / best-effort 失败语义 |
| `backend/tests/test_preference_injection.py` | P0-2：偏好写入 `user_profile` 且**不**触发 `invalidate`；refresh 端点才刷新 |
| `backend/tests/test_recall_feedback_persistence.py` | P0-3：召回落库、hash/variant 同口径、反馈回填、两个率的分母 |
| `src/widgets/evolution/__tests__/RecallMetrics.test.ts` | `compareVariants`（7 例）+ `findVariantWeights`（4 例） |
| `src/widgets/evolution/__tests__/EvolutionLog.p137.test.ts` | `parseEvolutionMetrics`（5 例，含非法 JSON / 非对象 / 中文） |
| `src/pages/settings/__tests__/Settings.anchor.test.tsx` | 新组件挂载不破坏设置页 tab 链路 |

---

## 7. 验证

```bash
# 后端
/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/ -q
/home/fz/anaconda3/envs/sage-backend/bin/ruff check backend/

# import-linter（必须 cd backend 才能找到 pyproject.toml）
cd backend && PYTHONPATH=.. lint-imports

# 架构 ratchet
node scripts/architecture-check.mjs

# 前端
npm run build
npx vitest run src/widgets/evolution src/pages/settings
```

> **架构门禁的本地陷阱**：`scripts/architecture-check.mjs` 会遍历整个仓库根，
> 包括 gitignore 的 `data/` 运行时目录。Chrome 会在 `data/browser-ephemeral/*/`
> 下造 `SingletonCookie` 悬空符号链接，`statSync` 跟随它会抛 ENOENT 使脚本崩溃。
> CI 上 `data/` 不存在所以不复现。绕开：跑门禁前把 `data/browser-ephemeral` 临时移开。
> （脚本本身应改用 `lstatSync` 或捕获 ENOENT —— 与本功能无关，另开修复。）

---

## 8. 相关文件

| 文件 | 说明 |
| --- | --- |
| `backend/scheduler/evolution_log.py` | 统一进化日志写入器（新增） |
| `backend/memory/recall_log_store.py` | 召回事件流存储（新增） |
| `backend/scheduler/evolution.py` | 6 个 task 收编 + duration/metrics |
| `backend/data/database.py` | `evolution_log` 加 2 列 + `memory_recall_log` 建表 |
| `backend/api/legacy_memory_routes.py` | 5 条新路由 |
| `backend/api/legacy_models.py` | `EvolutionLogResponse` 加 2 字段 |
| `backend/memory/recall_eval.py` | 持久化路径 + 指标聚合 |
| `backend/adapters/out/memory/adapter.py` | 召回路径落库 |
| `electron/commandRoutes/memory.ts` | 5 条 IPC 路由 |
| `src/widgets/evolution/RecallMetrics.tsx` | A/B 对比 UI（新增） |
| `src/widgets/evolution/LearnedPreferences.tsx` | 已学偏好 UI（新增） |
| `src/widgets/evolution/EvolutionLog.tsx` | duration + metrics 展示 |
| `src/pages/settings/Settings.tsx` | 进化 tab 挂载新组件 |
| `architecture-baseline.json` | `backend/data/database.py` 2062 → 2100（只升不降） |

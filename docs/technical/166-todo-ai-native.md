# 166 · 待办 AI 原生

> 本章描述 Sage 个人待办子系统（`todos` 表 + `/api/v1/todos` + agent 工具 + 提醒调度器）的实现，以及围绕它的 AI 增强：对话提炼、每日简报、每周回顾。面向需要修改待办行为、排查提醒或扩展工具的开发者。
>
> **本章已被 [178 · 待办交互升级与工作日志 / 日报周报](./178-todo-worklog-report.md) 部分超越**：待办侧新增详情编辑、三态循环、拖拽排序与拖拽嵌套；简报 / 周回顾升级为可存档的「日报 / 周报」，并新增「工作日志」事实层（`work_logs` 表）。本章保留仍然有效的待办表结构、提醒调度、对话提炼与全文检索内容。

## 1. 背景与定位

待办是 Sage 内的个人任务台账：SQLite 持久化、按用户维度本地存储、与项目/专家/会话存在弱关联。它取代了「把任务散落在对话里」的状态，把可执行项沉淀成可查询、可提醒、可回顾的结构化记录。

「AI 原生」在本子系统里体现为三条互相独立的链路：

| 链路 | 依赖 | 触发方式 | 是否落库 |
| --- | --- | --- | --- |
| 对话提炼待办 | LLM | 用户在聊天头部点「提取待办」 | 否，确认后才批量落库 |
| 每日简报 / 每周回顾 | LLM | 用户在待办页点「日报」/「周报」（前端已改名，原为「简报」/「周回顾」，见 178 章） | 旧端点只读统计后生成文本；新日报 / 周报会并存档 |
| 快速录入自然语言解析 | 纯本地规则 | 快捷键 `N` / 命令面板 / `?quickadd=1` | 是 |

其中「快速录入」刻意**不依赖 LLM**：常见的中文时间/优先级/标签表达由前端纯规则解析，离线可用、零延迟、零成本。LLM 只用在「需要理解一整段对话」的提炼场景。

需要和另一个容易混淆的组件区分：`backend/tools/todo_tool.py` 里的 `TodoWriteTool` 是**会话内**的临时任务清单（内存、全量替换、刷新即失），与本子系统的 `todos` 表无关。Agent 操作持久化待办用的是下一节的 5 个工具。

## 2. 数据模型

### 2.1 `todos` 表

主表定义在 `backend/data/database.py`，建表语句如下（节选字段顺序）：

```sql
CREATE TABLE IF NOT EXISTS todos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    priority TEXT DEFAULT 'medium',
    effective_urgency TEXT,
    due_at TEXT,
    completed_at TEXT,
    project_tag TEXT,
    project_id TEXT,
    tags TEXT,
    reminder_offsets TEXT,
    reminder_fired_offsets TEXT,
    source_type TEXT,
    source_ref TEXT,
    specialist_id TEXT,
    snooze_count INTEGER DEFAULT 0,
    is_recurring INTEGER DEFAULT 0,
    recurrence_rule TEXT,
    parent_id INTEGER,
    reminder_24h_fired INTEGER DEFAULT 0,
    reminder_1h_fired INTEGER DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_id) REFERENCES todos(id) ON DELETE SET NULL
)
```

字段语义：

| 字段 | 说明 |
| --- | --- |
| `status` | `pending` / `in_progress` / `completed` / `cancelled`。完成/取消有专用端点，`PUT` 的 `status` 只允许 `pending`/`in_progress`/`cancelled` |
| `priority` | `high` / `medium` / `low`，默认 `medium` |
| `effective_urgency` | 调度器每次扫描重算的紧急度：`critical` / `urgent` / `normal`，用于通知分级 |
| `due_at` / `completed_at` / `created_at` / `updated_at` | 统一存 **naive 本地时间** ISO 字符串；带时区的输入在服务层归一到本地 |
| `tags` | JSON 数组字符串（如 `["工作","论文"]`），空则 `NULL`；上限 10 个、单标签 32 字符 |
| `reminder_offsets` | 自定义提醒档位：到期前多少分钟的整数数组，上限 5 个、每个 1–10080 分钟 |
| `reminder_fired_offsets` | 自定义档位已触发的书签（JSON 数组），避免重复提醒 |
| `source_type` / `source_ref` | 来源标注。对话提炼落库时为 `chat` / `session_id` |
| `specialist_id` | 专家专属待办归属；`NULL` 表示全局待办 |
| `snooze_count` | 被推迟次数，用于徽标与周回顾「拖延」统计 |
| `is_recurring` / `recurrence_rule` | 循环任务标志与 5 字段 cron 表达式 |
| `parent_id` | 子任务指向父任务，**最多两级** |
| `reminder_24h_fired` / `reminder_1h_fired` | 24h/1h 两档提醒的闩锁位，仅调度器读写，**不进入 API 模型** |

索引（全部 `IF NOT EXISTS`）：`idx_todos_status(status)`、`idx_todos_due_at(due_at)`、`idx_todos_project_tag(project_tag)`、`idx_todos_parent_id(parent_id)`。

外键选 `ON DELETE SET NULL` 而非默认 `NO ACTION`：项目被 `ProjectRepo.remove` 硬删除时，关联待办应降级为独立项，而不是因 `PRAGMA foreign_keys=ON` 抛 `IntegrityError`。

### 2.2 迁移方式

`todos` **没有编号的 schema_version**，与记忆子系统的版本化迁移不同。这里采用幂等 DDL：

1. `CREATE TABLE IF NOT EXISTS todos (...)` 建新库；
2. `CREATE INDEX IF NOT EXISTS ...` 建索引；
3. 对旧库执行 `PRAGMA table_info(todos)`，缺失的列逐条 `ALTER TABLE todos ADD COLUMN ...`：
   - `tags`、`reminder_offsets`、`reminder_fired_offsets`、`source_type`、`source_ref`、`specialist_id` → `TEXT`
   - `snooze_count` → `INTEGER DEFAULT 0`

代码注释按阶段记录了列来源（阶段 1：`tags`；阶段 1b：`reminder_offsets`/`reminder_fired_offsets`；阶段 2：`source_type`/`source_ref`；阶段 3：`specialist_id`/`snooze_count`），便于追溯。启动时随后调用 `ensure_todos_fts_schema(conn)` 与 `backfill_todos_fts(conn)`（见 §6）。

### 2.3 子任务约束

`parent_id` 实现两级结构，服务层强制：

- 父任务必须是已存在的**顶层**行（`parent.parent_id is not None` 时拒绝，报「subtask depth exceeds 2 levels」）；
- 不允许自引用；
- 已有子任务的行不能反过来挂到别人下面。

`todos` 表自引用外键同样是 `ON DELETE SET NULL`，删父任务后子任务保留为顶层。

## 3. Agent 工具

5 个工具定义在 `backend/tools/todo_mgmt_tool.py`，在 `tool_bundles.py` 的 `"todo"` bundle 中注册。均通过注入的 service getter **懒获取** `TodoService`；未初始化时返回 `success=False`，错误文案为「待办服务未初始化，无法执行本操作。」。

| 工具 | 风险级别 | 参数 | 返回 `content` |
| --- | --- | --- | --- |
| `add_todo` | `WRITE_LOCAL` | `title`(必填)、`description`、`due_at`、`priority`(high/medium/low)、`project_tag`、`recurrence_rule`(cron)、`parent_id`、`tags[]`、`reminder_offsets[]`、`specialist_id` | `{id, title, status}`，`output` 为完整 Todo |
| `list_todos` | `READ` | `status`(pending/in_progress/completed/cancelled/all，默认 pending)、`project_tag`、`priority`、`include_completed`(默认 false)、`limit`(默认 50) | `{todos:[{id,title,status,priority,due_at,project_tag}], count}` |
| `complete_todo` | `WRITE_LOCAL` | `todo_id`(必填) | `{id, status, completed_at}`，`output` 为 Todo |
| `update_todo` | `WRITE_LOCAL` | `todo_id`(必填) + `title`/`description`/`due_at`/`priority`/`project_tag`/`status`(pending/in_progress/cancelled)/`parent_id`/`tags`/`reminder_offsets`/`specialist_id` | `{id, title, status}`，`output` 为 Todo |
| `delete_todo` | `WRITE_LOCAL` | `todo_id`(必填) | `{deleted: true, todo_id}` |

约定：

- 自然语言时间由 LLM 转成 ISO8601 后传给 `add_todo`，工具本身不解析中文时间；
- 完成循环任务（`is_recurring` 且带 `recurrence_rule`）时，`complete_todo` 会顺带生成下一次实例（见 §7 fail-open 策略）；
- `update_todo` 的 `tags`/`reminder_offsets` 为覆盖语义：传空数组即清空；`specialist_id` 传 `null` 清空。

## 4. 提醒与调度

调度器在 `backend/scheduler/todo_reminder.py`，使用 APScheduler `BackgroundScheduler`，默认每 15 分钟（`SCAN_INTERVAL_MINUTES = 15`）扫描一次，启动后延迟 0.5 秒做首扫（`STARTUP_SCAN_DELAY_SECONDS`）。

### 4.1 提醒分级

每轮扫描先重算 `effective_urgency`，再按档位触发：

| 档位 | 触发条件 | 标题 / 紧急度 | 去重机制 |
| --- | --- | --- | --- |
| 24 小时 | `pending`/`in_progress`，`due_at` 在 (now, now+24h]，`reminder_24h_fired=0` | 「📋 待办提醒」/ `normal` | 闩锁 `reminder_24h_fired` |
| 1 小时 | `due_at` 在 (now, now+1h]，`reminder_1h_fired=0` | 「⚠️ 待办即将到期」/ `urgent` | 闩锁 + 注册一次性精确提醒 |
| 精确提醒 | 到期前 5 分钟（`PRECISE_LEAD_MINUTES`） | 「⏰ 待办紧急」/ `critical` | `DateTrigger` 一次性 |
| 已逾期 | `due_at < now` 且未完成 | 「❌ 待办已逾期」/ `critical` | 内存节流，同一任务 1 小时（`OVERDUE_REPEAT_HOURS`）内不重复 |
| 自定义档位 | `reminder_offsets` 中某个偏移到达 `due_at - offset` | 「🔔 待办提醒」/ `normal` | `reminder_fired_offsets` 书签去重 |

`effective_urgency` 计算规则：无截止时间 → `normal`；距今 < 1 小时 → `critical`；距今 < 24 小时 → `urgent`；其余 → `normal`；高优先级且 24 小时内到期提升为 `critical`。

闩锁重置：`update_todo` 在 `due_at`/`status`/`reminder_offsets` 变化时清空 `reminder_fired_offsets`，并在 `due_at`/`status` 变化时把 `reminder_24h_fired`、`reminder_1h_fired` 归零，使改期后的任务能重新提醒。这也解释了 snooze 为什么能重新触发提醒（§4.3）。

### 4.2 通知投递

调度器不直接弹系统通知，而是把提醒推入**有界双端队列**（`MAX_PENDING_NOTIFICATIONS = 100`）。前端通过 `GET /api/v1/scheduled/notifications/pending` 排空该队列（字段 `todo_reminders`），Electron 主进程以固定间隔轮询，再转成 OS 通知——这样应用最小化到托盘时仍能提醒。

> 轮询间隔以实现为准：`electron/schedulerNotifications.ts` 的 `SCHEDULER_NOTIFICATION_POLL_MS = 4_000`，即 **4 秒**。文件头注释与后端注释里写的「每 15 秒」是过时描述。

### 4.3 推迟（snooze）

`POST /api/v1/todos/{id}/snooze`，请求 `{minutes}`，范围 `1..10080`（7 天）。逻辑：

1. 基准时间 = `max(due_at, now)`（无 `due_at` 则用 `now`）；
2. 新的 `due_at = 基准 + minutes`；
3. `snooze_count = COALESCE(snooze_count, 0) + 1`；
4. 走 `update_todo` 更新 `due_at`，从而重置提醒闩锁，改期后到点会重新提醒。

前端在待办行的右键菜单提供「10 分钟后 / 1 小时后 / 明天」三档；`snooze_count >= 2` 时行内显示 `×N` 徽标（悬浮提示「已推迟 N 次」）。周回顾会把推迟次数 ≥2 的任务列入「拖延提醒」。

### 4.4 每日简报

`GET /api/v1/todos/brief` → `{content}`。以 `startup_summary`（逾期数 / 今日到期 / 未来 7 天 / 高优先级 / 各状态计数）为输入，由 `todo_ai.generate_daily_brief` 调用 LLM 生成**至多 3 条**建议，失败时回退为模板文本。未配置 LLM 返回 503，其他生成失败返回 502。

P3.5 起该端点改走 `report_ai.build_report_context`（`backend/api/todo_router.py:420`），把**工作日志摘要**并入 `summary["worklogs"]` —— 只看待办会漏掉「没建待办但确实干了」的那部分工作。工作日志服务缺席时该段为空，不报错。生成文本仍由 `todo_ai.generate_daily_brief` 产出。

### 4.5 每周回顾

`GET /api/v1/todos/weekly-review` → `{content}`。输入为：本周统计、最近 50 条已完成（按 `created_at` 降序）、至多 20 条高优先级待办、至多 5 条被推迟任务。LLM 输出 Markdown，包含「完成情况 / 拖延提醒 / 下周建议」三部分，总长 ≤300 字符。

P3.5 起该端点同样改走 `report_ai.build_report_context`（`backend/api/todo_router.py:447`）：`stats["worklogs"]` 注入工作日志摘要，且「本周完成」换成报告引擎口径的**窗口内真正完成项**。生成文本仍由 `todo_ai.generate_weekly_review` 产出。

## 5. 智能视图与热力图

### 5.1 智能视图

视图是 `GET /todos?view=` 的语义糖，实现集中在 `backend/services/todo_filters.py`（单一真相源）。`view` **优先于** `status`：

| `view` | 语义 |
| --- | --- |
| `all` | 仅未完成（`status IN ('pending','in_progress')`） |
| `today` | 今日到期（未完成，`due_at` 落在今天 00:00:00–23:59:59） |
| `week` | 未来 7 天内到期（未完成，`due_at <= now+7d`，**无下界，包含已逾期**） |
| `completed` | `status = 'completed'` |

注意 `view=all` 与 `status=all` 不是一回事：`status=all` 是文档化的「包含已完成」逃生口，路由层会把它转换成 `include_completed=True`（否则按等值匹配会查出 0 行）；而 `view=all` 仍是只看未完成。

无任何视图/状态过滤且 `include_completed=false` 时，默认只返回 `pending`/`in_progress`。排序由 `sort_by`（`due_at`/`priority`/`created_at`，默认 `due_at`）+ `sort_order`（`asc`/`desc`，默认 `asc`）控制；`due_at` 排序对空值做 `(due_at IS NULL), due_at` 处理，避免空值抢占头部。

其它过滤：`tag` 走 `tags LIKE '%"tag"%'`（在 JSON 数组字符串里按带引号的整段匹配）；`specialist_id` 精确匹配；`priority` 精确匹配；`q` 见 §6。分页为 `limit`(1..500，默认 50)+`offset`，响应里的 `total` 是**过滤后匹配总数**而非当前页长度。

### 5.2 完成热力图

`GET /api/v1/todos/heatmap?days=91`，`days` 夹在 `7..366`。服务层按 `DATE(completed_at)` 聚合完成数，对区间内空缺日期补 0，返回：

```json
{ "days": [{ "date": "2026-11-01", "count": 3 }], "total": 42, "max": 7 }
```

前端 `TodoHeatmap` 固定取最近 91 天（13 周），渲染成 7 行（周日→周六）× N 周的 GitHub 风格网格，按「当日完成数 / 区间最大值」分 5 个色阶（0–4），并在标题处显示「近 91 天完成 N 条」。

## 6. 全文检索

### 6.1 FTS5 表与索引

- 虚表：`CREATE VIRTUAL TABLE IF NOT EXISTS todos_fts USING fts5(title, description)`。
- 采用**独立内容表**（非 external-content），`rowid` 显式设为 `todos.id`。
- 索引侧用 `jieba.cut_for_search` 分词后以空格连接（`_segment_for_index`），对中文更友好。
- 启动时 `backfill_todos_fts` 对比 `todos_fts` 行数与 `todos` 行数，不一致就整表重建（`force=True` 可强制）。

FTS 重建失败只记 warning、不阻断启动——搜索会降级到 LIKE。

### 6.2 写入同步

`backend/services/todo_fts.py` 提供 `upsert_todo_fts`（先按 rowid 删再插）、`delete_todo_fts`。服务层在 `create_todo`、`update_todo`（标题或描述变化时）、`delete_todo` 后显式调用——没有用 SQL 触发器，同步逻辑集中在 Python 侧。

### 6.3 查询与回退

`GET /todos?q=` 上限 200 字符。`apply_search_filter` 的分支：

| 情况 | 生成的 SQL 片段 |
| --- | --- |
| `q` 为空 | 不过滤 |
| FTS 正常匹配到 id | `AND id IN (?, ?, ...)` |
| FTS 正常但零匹配 | `AND 0=1` |
| FTS 不可用/抛错（`match_ids` 返回 `None`） | `AND (title LIKE ? OR description LIKE ?)` |

`match_ids` 用 `tokenize_for_search(q)` 生成 FTS5 查询串后执行 `SELECT rowid FROM todos_fts WHERE todos_fts MATCH ?`，任何异常返回 `None`，从而触发 LIKE 降级。

`tokenize_for_search` 的语义要点：查询侧用 `jieba.cut`（精确模式），把词用 **`" OR "`** 连接（例如 `"用户" OR "喜欢"`），是**按词 OR** 的宽松匹配，而不是按空格隐式 AND。想让结果更聚焦，应在应用侧按相关性筛选，而不是指望 FTS 的 AND 语义。

## 7. 关键设计决策

- **Fail-open 优先于强一致**：FTS 建表/回填失败、循环实例生成失败都只告警不抛出，主流程照常。待办是高频写入的本地台账，可用性优先于搜索/循环的完备性。
- **两级子任务 + `ON DELETE SET NULL`**：两级足以覆盖「任务-子步骤」，避免任意深度树的 UI 与递归成本；父被删时子任务降级为顶层而非级联删除。
- **闩锁 vs 内存节流**：24h/1h/自定义档位用 DB 列（闩锁/书签）去重，进程重启后仍生效；逾期提醒用内存节流，避免每分钟刷库，重启后允许再提醒一次是可接受的。
- **自定义档位用书签而非删除**：`reminder_offsets` 保留原始配置，`reminder_fired_offsets` 单独记已触发项；改期时清书签即可重新排程，不必重建配置。
- **naive 本地时间约定**：`due_at` 等时间列统一存本地无时区 ISO，带时区输入在服务层归一；前端解析器（`parseQuickTodo`）也输出同格式，避免跨层时区漂移。
- **提炼不落库**：`POST /todos/extract` 只返回候选（`{title, due_at, priority, tags}`，至多 10 条），由用户在弹窗里勾选/改标题后调 `POST /todos/batch/create`（单次上限 20）落库，并带 `source_type='chat'`、`source_ref=session_id` 以便溯源。
- **800 行棘轮的产物**：`todo_service.py` 把搜索、导出、循环、统计、洞察、标签、过滤、AI 拆分到 `todo_fts`/`todo_export`/`todo_recurrence`/`todo_stats`/`todo_insights`/`todo_tags`/`todo_filters`/`todo_ai` 等模块，主服务只保留编排与校验。
- **py38 兼容**：`release/win7` 共用逻辑，类型标注避免 PEP 604/585，统一用 `typing.Optional/List/Dict`；pydantic v1/v2 差异通过既有兼容层处理。

## 8. 相关文件

后端：

| 文件 | 职责 |
| --- | --- |
| `backend/data/database.py` | `todos` 建表/索引/幂等迁移；`todos_fts` 建表与回填 |
| `backend/api/todo_router.py` | `/api/v1/todos` 全部端点、请求/响应模型 |
| `backend/services/todo_service.py` | 编排与校验（三态更新、子任务、闩锁重置） |
| `backend/services/todo_filters.py` | 视图/排序/过滤 SQL 的单一真相源 |
| `backend/services/todo_fts.py` | FTS 同步、匹配、LIKE 降级 |
| `backend/services/todo_ai.py` | 对话提炼、每日简报、每周回顾（LLM） |
| `backend/services/todo_stats.py` | 统计、启动摘要、完成热力图 |
| `backend/services/todo_insights.py` | snooze、拖延统计 |
| `backend/services/todo_tags.py` | 标签清洗/序列化/聚合 |
| `backend/services/todo_export.py` | Markdown / JSON 导出 |
| `backend/services/todo_recurrence.py` | 循环任务下一次实例生成 |
| `backend/memory/chinese_tokenizer.py` | `tokenize_for_search`（jieba，OR 连接） |
| `backend/scheduler/todo_reminder.py` | 提醒扫描、分级、通知队列 |
| `backend/api/asr_router.py` | `POST /api/v1/asr/transcribe`（快速录入语音） |
| `backend/api/scheduled_router.py` | `GET /scheduled/notifications/pending` 排空通知 |
| `backend/tools/todo_mgmt_tool.py` | 5 个 agent 工具 |
| `backend/tools/tool_bundles.py` | `"todo"` bundle 注册 |

前端 / Electron：

| 文件 | 职责 |
| --- | --- |
| `src/shared/api/todoClient.ts` | IPC→HTTP 客户端方法集 |
| `src/pages/TodoPage.tsx` | 页面骨架、快捷键、搜索防抖、批量操作 |
| `src/pages/todo/TodoToolbar.tsx` | 搜索/视图/标签/专家/优先级/排序 |
| `src/pages/todo/TodoCreateForm.tsx` | 创建表单（提醒预设、标签、专家归属） |
| `src/pages/todo/TodoQuickAdd.tsx` | 自然语言快速录入 + 语音 |
| `src/pages/todo/parseQuickTodo.ts` | 纯规则中文 NL 解析 |
| `src/pages/todo/TodoHeatmap.tsx` | 91 天完成热力图 |
| `src/pages/todo/TodoRowEditor.tsx` | 行内编辑、snooze 菜单、徽标 |
| `src/pages/todo/TodoSubtaskTree.tsx` | 两级子任务渲染 |
| `src/pages/todo/TodoReportDialog.tsx` | 日报 / 周报弹窗（取代原 `TodoAiDialog.tsx`，见 178 章） |
| `src/pages/chat/TodoExtractDialog.tsx` | 对话提炼候选确认弹窗 |
| `electron/commandRoutes/settings.ts` | 待办相关 IPC 路由表 |
| `electron/schedulerNotifications.ts` | 轮询 `/scheduled/notifications/pending` 并转发 OS 通知 |

**延伸阅读**：[178 · 待办交互升级与工作日志 / 日报周报](./178-todo-worklog-report.md) —— 本章的后继章节，描述待办交互升级（P0/P1）、工作日志捕获子系统（P2）与日报 / 周报双源聚合与存档（P3）。

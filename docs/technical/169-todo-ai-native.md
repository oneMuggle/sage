# 169 — 待办事项 AI 原生能力

> 文档编号：169
> 代码范围：`backend/services/todo_*`、`backend/api/todo_router.py`、`backend/api/asr_router.py`、`backend/scheduler/todo_reminder.py`、`backend/tools/todo_mgmt_tool.py`、`src/pages/todo/*`、`src/pages/TodoPage.tsx`、`src/entities/todo/todoStore.ts`、`electron/commandRoutes/settings.ts`、`electron/schedulerNotifications.ts`
> 运行基线：release/win7（Python 3.8.10 + pydantic 1.10.13）
>
> **本章已被 [182 · 待办交互升级与工作日志 / 日报周报](./182-todo-worklog-report.md) 部分超越**：待办侧新增详情编辑、三态循环、拖拽排序与拖拽嵌套；简报 / 周回顾升级为可存档的「日报 / 周报」，并新增「工作日志」事实层（`work_logs` 表）。本章保留仍然有效的待办表结构、提醒调度、对话提炼与全文检索内容。

## 1. 概述与边界

待办子系统是 Sage 桌面端的本地单用户待办清单，数据存放在应用 SQLite 的 `todos` 表。它并不是「所有操作都交给模型」，而是按能力选择实现方式：

| 能力 | 实现方式 | 是否需要模型服务 |
| --- | --- | --- |
| 待办增删改查、子任务、标签、重复任务 | `TodoService` + REST + Electron IPC | 否 |
| 自然语言快速录入 | 前端纯规则解析 `parseQuickTodo` | 否 |
| 语音录入 | `MediaRecorder` + `POST /api/v1/asr/transcribe` | 需要 ASR 配置 |
| 从对话提炼待办 | LLM 结构化输出 | 是 |
| AI 每日简报 / 周回顾 | LLM 基于统计生成文本 | 是 |
| 到期提醒 | APScheduler + 系统通知 | 否 |

需要明确的边界：

- 没有独立的「AI 自动拆解」或「AI 自动分类」服务。对话提炼时，标题、截止时间、优先级、标签由同一次 LLM 调用一次性给出；本地快速录入完全由规则解析，不调用 LLM。
- 数据不离开本机数据库；没有云端同步、多用户协作或跨设备合并。
- 系统通知依赖 Electron 主进程运行（可最小化到托盘）。应用完全退出后不会触发通知。

数据与调用链：

```
React（TodoPage / TodoExtractDialog / TodoQuickAdd）
  → todoClient（invoke）
  → electron/commandRoutes/settings.ts（todo_* 命令表）
  → FastAPI /api/v1/todos
  → TodoService → SQLite（todos / todos_fts）
```

AI 调用链：

```
todo_ai._client() → build_llm_client_from_settings().complete(prompt)
```

提醒链路：

```
APScheduler（15 分钟扫描 + 精确一次性触发器）
  → 后端有界内存队列
  → GET /api/v1/scheduled/notifications/pending
  → Electron 主进程轮询（SCHEDULER_NOTIFICATION_POLL_MS = 4_000）
  → OS 通知
```

## 2. 数据模型与存储

### 2.1 `todos` 表

建表位于 `backend/data/database.py`（`CREATE TABLE IF NOT EXISTS todos`）：

| 列 | 类型 / 默认值 | 说明 |
| --- | --- | --- |
| `id` | INTEGER PK AUTOINCREMENT | 主键 |
| `title` | TEXT NOT NULL | 标题 |
| `description` | TEXT | 描述 |
| `status` | TEXT DEFAULT `'pending'` | `pending` / `in_progress` / `completed` / `cancelled` |
| `priority` | TEXT DEFAULT `'medium'` | `high` / `medium` / `low` |
| `effective_urgency` | TEXT | 调度扫描刷新：`critical` / `urgent` / `normal` |
| `due_at` | TEXT | 截止时间，naive 本地 ISO8601 |
| `completed_at` | TEXT | 完成时间 |
| `project_tag` | TEXT | 用户填写的项目标签 |
| `project_id` | TEXT | 自动关联的 `projects.id`（字符串主键） |
| `tags` | TEXT | JSON 数组字符串，如 `["工作","论文"]` |
| `reminder_offsets` | TEXT | 自定义提醒档位的 JSON 分钟数组 |
| `reminder_fired_offsets` | TEXT | 已触发的自定义档位书签 |
| `source_type` | TEXT | 来源类型，如 `chat` |
| `source_ref` | TEXT | 来源引用，如会话 ID |
| `specialist_id` | TEXT | 专家归属（对应 agents.id，无数据库外键） |
| `snooze_count` | INTEGER DEFAULT 0 | 被推迟次数 |
| `is_recurring` | INTEGER DEFAULT 0 | 是否重复任务 |
| `recurrence_rule` | TEXT | 5 字段 cron 表达式 |
| `parent_id` | INTEGER | 父待办 ID，最多两级 |
| `reminder_24h_fired` | INTEGER DEFAULT 0 | 24 小时提醒书签 |
| `reminder_1h_fired` | INTEGER DEFAULT 0 | 1 小时提醒书签 |
| `created_at` | TEXT NOT NULL | 创建时间 |
| `updated_at` | TEXT NOT NULL | 更新时间 |

外键与索引：

- `FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL`
- `FOREIGN KEY (parent_id) REFERENCES todos(id) ON DELETE SET NULL`
- `idx_todos_status`、`idx_todos_due_at`、`idx_todos_project_tag`、`idx_todos_parent_id`

`ON DELETE SET NULL` 是有意为之：项目或父待办被硬删除后，待办保留为独立条目，避免 `PRAGMA foreign_keys=ON` 下删除项目直接触发 `IntegrityError`。

### 2.2 存储约定

- **时间**：所有时间字段为 naive 本地时间 ISO8601（`YYYY-MM-DDTHH:mm:ss`）。写入带时区的 `due_at` 时会归一到本地 naive；前端快速录入直接生成 naive ISO。
- **标签**：`todo_tags.normalize_tags` 去空白、去重、剔除 `"` `\` `%` `_`，单标签截断到 32 字符，最多 10 个；空列表序列化为 `NULL`。过滤使用 `tags LIKE '%"tag"%'`，因此清洗必须剔除 LIKE 特殊字符。
- **提醒档位**：`reminder_offsets` 只接受 1–10080 分钟（7 天）、最多 5 档、自动去重；空列表存 `NULL`。
- **任务层级**：`parent_id` 指向顶层待办；创建和更新都拒绝第三级（父的 `parent_id` 必须为空）。
- **紧急性**：`effective_urgency` 由扫描刷新：无 `due_at` → `normal`；1 小时内 → `critical`；24 小时内 → `urgent`；其余 → `normal`；高优先级且 24 小时内 → `critical`。

### 2.3 幂等迁移

旧库通过 `PRAGMA table_info(todos)` 检查缺失列并 `ALTER TABLE ADD COLUMN` 补齐 `tags`、`reminder_offsets`、`reminder_fired_offsets`、`source_type`、`source_ref`、`specialist_id`、`snooze_count`。补列完成后执行：

1. `ensure_todos_fts_schema(conn)`：创建 `todos_fts`；
2. `backfill_todos_fts(conn)`：行数不一致时全量回填。

### 2.4 全文搜索

`todos_fts` 是独立存储内容的 FTS5 虚表（`USING fts5(title, description)`），`rowid = todos.id`，不使用触发器：

- 写入/更新/删除通过 `backend/services/todo_fts.py` 显式同步；
- 建索引前用 jieba 分词（`_segment_for_index`）；
- 启动时若 `todos` 与 `todos_fts` 行数不一致，强制重填；
- FTS5 不可用时静默降级：搜索走 `LIKE`，不影响主表读写。

查询路径：`todo_fts.match_ids` 返回命中的 ID 集合；命中时 SQL 追加 `id IN (...)`；分词/查询失败返回 `None`，降级 `LIKE`；查询词有效但无命中时返回空集合，最终条件为 `AND 0=1`（不再退化为全量返回）。

## 3. 服务层结构与业务规则

`backend/services/todo_service.py` 是编排与持久化入口（791 行，逼近 800 行架构棘轮），其余职责拆到同目录子模块：

| 模块 | 职责 |
| --- | --- |
| `todo_service.py` | `Todo` 模型、CRUD、筛选编排、批量操作、导出入口、项目自动关联 |
| `todo_fts.py` | FTS 同步、MATCH 查询、LIKE 降级 |
| `todo_filters.py` | list/count 共用的 WHERE 片段、智能视图、排序白名单 |
| `todo_tags.py` | 标签清洗、序列化、解析、聚合 |
| `todo_recurrence.py` | cron 解析与下一实例生成 |
| `todo_export.py` | JSON / Markdown 导出内容 |
| `todo_stats.py` | 启动摘要、统计、完成热力图 |
| `todo_insights.py` | 推迟（snooze）与多次推迟查询 |
| `todo_ai.py` | 对话提炼、每日简报、周回顾 |

### 3.1 写入与更新

- **创建**：校验标题；`parent_id` 必须存在且为顶层；`due_at` 归一；写入后同步 FTS；`project_tag` 变化时 `_auto_link_project` 先按 `projects.name` 精确匹配，再退化为 `LIKE`，命中则写 `project_id`。
- **更新**：REST 层用 `model_dump(exclude_unset=True)` 保留三态——缺省=不动、显式值=覆盖、显式 `null`=清空；`title` 显式 `null` 会抛 `ValueError`（列 NOT NULL）。
- **父子关系**：更新拒绝自引用、拒绝挂到非顶层待办、拒绝让已有子任务的行变成子任务。
- **提醒书签**：改动 `reminder_offsets` / `due_at` / `status` 会清空 `reminder_fired_offsets`；改动 `due_at` 或 `status` 同时重置 24h/1h 两个 latch，使重排期或重新打开的任务能再次提醒。
- **FTS 同步**：`title` / `description` 变化后重新 upsert。
- **完成**：`POST /todos/{id}/complete` 置 `completed` 与 `completed_at`，然后尝试生成下一次重复实例（失败只记 warning，不影响本次完成）。
- **取消**：置 `cancelled`；`UpdateTodoIn` 的 `status` 枚举不包含 `completed`，完成只能走 complete 端点。

### 3.2 列表与筛选

`list_todos` / `count_todos` 共用 `todo_filters.apply_common_filters`，保证分页与总数口径一致：

- `view` 优先于 `status`：
  - `all`：`pending` + `in_progress`；
  - `today`：今日 00:00–23:59 到期；
  - `week`：未完成且 `due_at <= now + 7d`，**没有下界**，因此包含已逾期项；
  - `completed`：已完成。
- `status=all` 等价于 `include_completed=true`；默认只返回未完成。
- `tag` 使用 `tags LIKE '%"tag"%'`；`specialist_id` 精确匹配。
- 排序只允许白名单表达式：`due_at`（无日期排最后）、`priority`（`high → medium → low`）、`created_at`。
- 响应中的 `total` 是匹配总数，不是当前页长度。
- `limit` 默认 50、上限 500；`offset >= 0`。

### 3.3 批量操作

- `batch/create`：`items` 非空、最多 20 条。`create_many` 对列表逐条调用 `create_todo`，单条失败会中断并返回 400；此前已提交的条目不会回滚。
- `batch/complete`：`ids` 非空、最多 500 条。逐条完成，返回 `{completed, missing}`；不存在的 ID 只进入 `missing`，不影响其余行。
- `batch/delete`：同样逐条删除，返回实际删除数 `{deleted}`。
- 三次批量操作都**不是单事务**，每条服务调用各自提交。

### 3.4 重复任务

`todo_recurrence.spawn_next_recurrence` 用 `CronTrigger.from_crontab(recurrence_rule)` 计算下一次触发时间，基准取 `max(due_at, now)`。新实例继承标题、描述、优先级、项目标签、cron 规则、父任务、标签和提醒档位；解析失败或生成失败只记 warning。只有任务被完成时才生成下一实例，未完成的任务不会提前排队。

### 3.5 推迟、统计与导出

- `snooze`：分钟数 1–10080；有 `due_at` 时后移，无 `due_at` 时从当前时间起算；`snooze_count` 自增，并重置提醒书签。
- 启动摘要：逾期、今日到期、未来 7 天、高优先级、未完成总数、今日完成数。
- 统计端点：总数、按状态分布、按优先级分布、逾期数、今日到期数、今日完成数。
- 热力图：默认 91 天（范围 7–366，含今天），按 `DATE(completed_at)` 聚合，缺失日期补 0，返回 `{days, total, max}`。
- 导出：`export_todos` 以 `limit=1000000` 按 `due_at` 升序读取，再交给 `todo_export.build_export`；JSON 为待办数组，Markdown 为复选框清单（`# Sage 待办导出`）。桌面端导出按钮固定传 `include_completed=true`。

## 4. HTTP API 与桌面端 IPC

路由由 `build_router(get_service)` 构建，在 `backend/main.py` 以 `prefix="/api/v1"` 挂载。请求模型使用 `extra="forbid"`，未知字段返回 422。

| 方法 | 路径（前缀 `/api/v1`） | 说明 |
| --- | --- | --- |
| GET | `/todos` | 列表；参数见下 |
| POST | `/todos` | 创建，返回 201 |
| GET | `/todos/summary` | 启动摘要（逾期/今日/7 天/高优先级） |
| GET | `/todos/stats` | 聚合统计 |
| GET | `/todos/tags` | 标签及计数（降序） |
| GET | `/todos/export` | `format=json\|md`、`include_completed` |
| POST | `/todos/batch/complete` | 批量完成，上限 500 |
| POST | `/todos/batch/delete` | 批量删除，上限 500 |
| POST | `/todos/batch/create` | 批量创建，上限 20 |
| POST | `/todos/extract` | 会话提炼候选，不落库 |
| GET | `/todos/brief` | AI 每日简报 |
| GET | `/todos/weekly-review` | AI 周回顾（含推迟统计） |
| GET | `/todos/heatmap` | `days=7..366`，默认 91 |
| POST | `/todos/{id}/snooze` | 推迟 `minutes=1..10080` |
| GET | `/todos/{id}` | 单条查询 |
| PUT | `/todos/{id}` | 局部更新（三态语义） |
| DELETE | `/todos/{id}` | 删除，返回 204 |
| POST | `/todos/{id}/complete` | 完成并尝试生成重复实例 |
| POST | `/todos/{id}/cancel` | 取消 |

`GET /todos` 查询参数：

| 参数 | 默认 / 范围 | 说明 |
| --- | --- | --- |
| `status` | 无；`pending\|in_progress\|completed\|cancelled\|all` | `all` 等价包含已完成 |
| `project_tag` | 无 | 精确匹配 |
| `priority` | 无；`high\|medium\|low` | 精确匹配 |
| `include_completed` | `false` | 是否包含已完成 |
| `sort_by` | `due_at`；`due_at\|priority\|created_at` | 排序白名单 |
| `sort_order` | `asc`；`asc\|desc` | 排序方向 |
| `limit` / `offset` | 50 / 0；`1..500` / `>=0` | 分页 |
| `q` | 无；≤200 字符 | FTS5 搜索，失败降级 LIKE |
| `tag` | 无；≤50 字符 | 多标签精确过滤 |
| `view` | 无；`all\|today\|week\|completed` | 智能视图，优先于 `status` |
| `specialist_id` | 无；≤100 字符 | 专家归属过滤 |

静态路径（`summary`、`stats`、`tags`、`export`、`batch/*`、`extract`、`brief`、`weekly-review`、`heatmap`）都注册在 `/todos/{id}` 之前，避免被路径参数吞掉。

错误约定：

- 422：查询参数或请求体校验失败；
- 400：批量 ID 为空/超上限、批量创建为空/超上限、父子关系非法、清空 `title`；
- 404：目标待办不存在；
- 503：服务未初始化；AI 端点未配置 LLM；
- 502：LLM 上游调用失败（`待办提炼失败` / `生成简报失败` / `生成周回顾失败`）；
- 204：删除成功。

桌面端 IPC 命令表位于 `electron/commandRoutes/settings.ts`，`src/shared/api/todoClient.ts` 逐项映射：`todo_list`、`todo_create`、`todo_get`、`todo_update`、`todo_delete`、`todo_complete`、`todo_cancel`、`todo_summary`、`todo_stats`、`todo_tags`、`todo_batch_complete`、`todo_batch_delete`、`todo_export`、`todo_extract`、`todo_batch_create`、`todo_brief`、`todo_weekly_review`、`todo_heatmap`、`todo_snooze`。`todo_update` 与 `todo_snooze` 在构造请求体时会剔除 `id`——两个请求模型都声明了 `extra="forbid"`，而 `id` 只存在于 URL 路径。

P2 / P3 又在同一张表上追加了工作日志与报告两组命令：`worklog_list`、`worklog_summary`、`worklog_create`、`worklog_update`、`worklog_delete`、`worklog_confirm`、`worklog_dismiss`、`worklog_extract`、`report_generate`、`report_list`、`report_get`。完整说明见 182 章。

语音转写独立挂在 `/api/v1/asr/transcribe`：请求 `{audio_base64, format: webm|wav|ogg|mp3|m4a, language?}`，返回 `{text}`；音频上限 25MB，ASR 未配置返回 409，格式/大小非法返回 400，上游失败返回 502。临时文件处理完即删除。

## 5. 提醒调度与通知投递

`backend/scheduler/todo_reminder.py` 使用 APScheduler 的混合调度：

| 常量 | 值 | 含义 |
| --- | --- | --- |
| `SCAN_INTERVAL_MINUTES` | 15 | 周期扫描间隔 |
| `PRECISE_LEAD_MINUTES` | 5 | 到期前精确提醒提前量 |
| `OVERDUE_REPEAT_HOURS` | 1 | 逾期提醒内存节流窗口 |
| `MAX_PENDING_NOTIFICATIONS` | 100 | 未消费通知上限（`deque(maxlen=...)`） |
| `STARTUP_SCAN_DELAY_SECONDS` | 0.5 | 启动一次性扫描延迟 |

启动时注册两个作业：15 分钟一次的 `IntervalTrigger`，以及延迟 0.5 秒的启动扫描（补发应用关闭期间到期的提醒）。周期扫描流程：

1. `refresh_effective_urgency()` 刷新紧急性；
2. 24 小时提醒：命中 `reminder_24h_fired=0` 的任务，发通知并写 latch；
3. 1 小时提醒：发通知、写 latch，并注册一个 `due_at - 5min` 的一次性 `DateTrigger`；若触发时间已过，改为 10 秒后执行；
4. 逾期提醒：无数据库 latch，用内存字典按任务节流，每小时最多一次；重启可能重复一次；
5. 自定义档位：对配置了 `reminder_offsets` 的任务逐档判断 `now >= due_at - offset`，用 `reminder_fired_offsets` 记录已触发档位，每档只触发一次。

通知写入有界内存队列，`get_pending_notifications()` 一次性排空。`GET /api/v1/scheduled/notifications/pending` 同时排空六类队列：`scheduled_tasks`、`todo_reminders`、`background_tasks`、`goal_notifications`、`project_health`、`orch_runs`。Electron 主进程的 `startSchedulerNotificationPoller` 合并六路队列、过滤无标题条目；默认间隔为 `SCHEDULER_NOTIFICATION_POLL_MS = 4_000`（4 秒），上一轮未完成时跳过本轮，异常只记日志不中断轮询。`scheduled_router.py` 中仍保留「每 15s 轮询」的旧注释，实际间隔以常量为准。

## 6. AI 能力

### 6.1 从对话提炼待办

入口：聊天页头部的「提取待办」按钮（`data-testid="chat-extract-todos"`）打开 `TodoExtractDialog`。

流程：

1. `todoClient.extractFromSession(sessionId)` → `POST /todos/extract`；
2. `todo_ai.extract_todos` 读取会话：指定 `message_ids` 时最多取前 80 条，否则取该会话最近 80 条后反转为时间正序；
3. 每条消息最多取 2000 字符，整段预算 12000 字符；
4. 调用 `build_llm_client_from_settings().complete(prompt)`，要求只返回 JSON 数组；
5. `_parse_candidates` 容错解析（剥离代码栅栏），清洗标题、`due_at`、优先级、标签，最多 10 条；没有可提炼项返回空数组。

提炼结果**不落库**。用户在弹窗中勾选、可改标题后确认，前端调用 `batch/create`，并为每条附带 `source_type="chat"`、`source_ref=sessionId`，形成回到会话的反向链接。

### 6.2 每日简报

`GET /todos/brief` 以启动摘要（逾期、今日到期、未来 7 天、高优先级、今日完成）为输入，要求模型用中文给出最多 3 条、总长 ≤120 字的行动建议；空响应时返回固定兜底文案。

P3.5 起该端点改走 `report_ai.build_report_context`（`backend/api/todo_router.py:420`），把**工作日志摘要**并入 `summary["worklogs"]` —— 只看待办会漏掉「没建待办但确实干了」的那部分工作。工作日志服务缺席时该段为空，不报错。生成文本仍由 `todo_ai.generate_daily_brief` 产出。

前端弹窗已由 `TodoReportDialog` 取代原 `TodoAiDialog`（打开即生成，可重新生成），详见 182 章。

### 6.3 周回顾

`GET /todos/weekly-review` 组装四类输入：

- `get_todo_stats()` 的统计；
- 已完成待办（`status=completed`，按 `created_at` 倒序取 50 条）的标题；
- 未完成高优先级待办（取 20 条）的标题；
- 推迟次数 ≥2 的未完成任务（取 5 条），格式为 `标题（推迟 N 次）`。

模型返回 Markdown，要求包含「完成情况」「拖延提醒」「下周建议」三个小标题、总长 ≤300 字。这里没有独立的「推迟建议引擎」，建议来自周回顾提示词。

P3.5 起该端点同样改走 `report_ai.build_report_context`（`backend/api/todo_router.py:447`）：`stats["worklogs"]` 注入工作日志摘要，且「本周完成」换成报告引擎口径的**窗口内真正完成项**。生成文本仍由 `todo_ai.generate_weekly_review` 产出。

### 6.4 本地自然语言快速录入

`src/pages/todo/parseQuickTodo.ts` 是纯规则解析，无网络、无 LLM。支持：

- 日期：今天/明天/后天/大后天；周X/星期X/礼拜X（可带 下/本/这）；M月D日（已过则顺延到明年）；
- 时间：`HH点`、`HH点半`、`HH点MM分`、`HH:MM`、`HH：MM`，可带凌晨/上午/中午/下午/傍晚/晚上；
- 优先级：`!高` / `!中` / `!低`（也接受 `!high` / `!medium` / `!low`）；
- 标签：`#标签`，最多 10 个、每个 ≤32 字符。

默认规则：只有日期时取当天 18:00；只有时间时取今天该时刻，已过则顺延到明天；无法识别的内容保留在标题中。解析结果生成 naive 本地 ISO，与后端 `due_at` 存储约定一致。输入时实时显示日期/优先级/标签预览。

### 6.5 语音录入

`TodoQuickAdd` 用 `MediaRecorder` 录音（最长 60 秒），转 base64 后调用 `asrClient.transcribe(base64, 'webm', 'zh')`，把识别文本追加到输入框，再走同一套本地解析。录音权限失败、环境不支持、ASR 未配置或转写失败都会以 toast 显示错误；录音仅用于本次转写，后端处理完删除临时文件。

## 7. 前端页面、组件与状态

### 7.1 页面入口

- 左侧栏「待办」→ `/todos`；
- 命令面板「添加待办」→ `/todos?quickadd=1`，页面消费后清除该参数，避免刷新重开；
- 页面内快捷键 `N`：无修饰键、焦点不在 `input` / `textarea` / `select` / `contentEditable` 时打开快速录入。

### 7.2 主要组件

| 组件 | 职责 |
| --- | --- |
| `src/pages/TodoPage.tsx` | 页面编排：加载、搜索防抖、批量选择、导出、AI 弹窗、热力图、子任务模式切换 |
| `src/pages/todo/TodoCreateForm.tsx` | 标题常显；「更多选项」展开描述、优先级、截止、项目标签、多标签、提醒预设（1440/60/10 分钟）、专家归属 |
| `src/pages/todo/TodoQuickAdd.tsx` | 一句话录入：实时解析预览、语音按钮、回车创建 |
| `src/pages/todo/parseQuickTodo.ts` | 规则解析器 |
| `src/pages/todo/TodoToolbar.tsx` | 搜索、智能视图、标签下拉、专家下拉、优先级、排序、清除 |
| `src/pages/todo/TodoRowEditor.tsx` | 行内编辑标题、循环切换优先级、日期弹层、标签 chips、来源/专家 chip、推迟徽标、提醒计数、添加子任务、取消、二次确认删除、右键菜单 |
| `src/pages/todo/TodoSubtaskTree.tsx` | 按 `parent_id` 构树、折叠、完成进度 |
| `src/pages/todo/TodoHeatmap.tsx` | 91 天、7 行网格、按全区间最大值分 4 档着色 |
| `src/pages/todo/TodoReportDialog.tsx` | 日报 / 周报弹窗（取代原 `TodoAiDialog.tsx`，见 182 章），打开即生成，可重新生成 |
| `src/pages/chat/TodoExtractDialog.tsx` | 对话提炼候选、勾选、改标题、批量创建 |
| `src/widgets/chat/TodoListSection.tsx` / `src/widgets/todo/TodoItem.tsx` | 聊天内待办列表与条目展示 |

### 7.3 状态管理

`src/entities/todo/todoStore.ts`（zustand）提供 `load`、`setParams`、`create`、`update`、`delete`、`complete`、`cancel`、`batchComplete`、`batchDelete`、`snooze`、`loadSummary`。批量完成/删除各发一个后端请求，然后按当前筛选条件重新加载；单项操作在成功后更新本地列表并刷新摘要。

搜索由页面维护输入值，300ms 防抖后把 `q` 合入列表参数，实际匹配在后端 FTS 完成。列表存在子任务时渲染 `TodoSubtaskTree`，否则渲染扁平列表。搜索无结果时显示「没有匹配的待办」，否则显示无待办空状态。

## 8. 智能体工具

`backend/tools/tool_bundles.py:_install_todo` 注册五个工具，使用延迟解析的 `TodoService` getter，服务未初始化时返回友好错误：

| 工具名 | 风险级别 | 能力 |
| --- | --- | --- |
| `add_todo` | `WRITE_LOCAL` | 标题、描述、`due_at`、优先级、项目标签、cron 规则、父任务、标签、提醒档位、专家归属 |
| `list_todos` | `READ` | 状态、项目标签、优先级、是否包含已完成、数量上限 |
| `complete_todo` | `WRITE_LOCAL` | 按 ID 完成 |
| `update_todo` | `WRITE_LOCAL` | 更新标题/描述/截止/优先级/项目标签/状态/父任务/标签/提醒档位/专家归属 |
| `delete_todo` | `WRITE_LOCAL` | 按 ID 删除 |

`list_todos` 的筛选能力比 REST 窄：不支持 `q`、`tag`、`view`、`specialist_id`、排序和分页偏移。工具直接调用服务层，不经过 HTTP/IPC；返回给模型的列表只包含 `id`、`title`、`status`、`priority`、`due_at`、`project_tag`。

## 9. 与其他子系统的关系

- **项目**：`project_tag` 可自动关联 `projects` 表并写 `project_id`；项目删除时待办保留（`ON DELETE SET NULL`）。
- **专家**：`specialist_id` 引用 agents.id，用于专家专属待办、创建时归属、工具栏过滤；数据库层没有外键约束。
- **会话**：从对话提炼的待办带 `source_type="chat"` 与 `source_ref=会话 ID`，行内显示来源 chip；提炼读取的是会话消息仓库，不读取记忆子系统。
- **编排**：待办没有对编排引擎的硬依赖；编排/智能体通过已注册的待办工具写入，通知则与 `orch_runs` 等队列共用同一个 Electron 轮询端点。
- **记忆**：待办数据不进入记忆表或语义 FTS，也不参与记忆召回；两套子系统目前只在 UI 层共存，没有数据耦合。
- **通知**：待办提醒与定时任务、后台任务、目标终态、项目健康、编排 run 共用 `GET /scheduled/notifications/pending` 与同一个桌面通知轮询器。

## 10. 测试覆盖

后端：

- `backend/tests/integration/test_todo_api.py`：CRUD、子任务与两级限制、搜索、分页与过滤、批量完成/删除、导出 JSON/Markdown、排序校验、PUT 三态、统计与摘要路由不被 `/{id}` 吞掉、服务未初始化 503；
- `backend/tests/unit/test_todo_service.py`、`test_todo_service_phase0.py`：服务层行为；
- `test_todo_phase1.py`、`test_todo_phase1b.py`：智能视图、自定义提醒、快速录入相关后端行为；
- `test_todo_phase3.py`：专家归属、推迟、热力图；
- `test_todo_reminder.py`、`test_todo_notify.py`：扫描、latch、精确触发器、通知队列；
- `test_todo_ai.py`：提炼解析、简报、周回顾；
- `test_todo_mgmt_tool.py`、`test_todo_tool.py`：智能体工具；
- `test_database_todo_migration.py`：旧库补列与 FTS 回填。

前端：

- `src/pages/__tests__/TodoPage.test.tsx`、`TodoPage.p171.test.ts`；
- `src/pages/todo/__tests__/parseQuickTodo.test.ts`、`TodoQuickAdd.test.tsx`、`TodoReportDialog.test.tsx`、`TodoHeatmap.test.tsx`、`TodoRowEditor.contextMenu.test.tsx`；
- `src/entities/todo/__tests__/todoStore.test.ts`、`todoStore.p156.test.ts`；
- `src/shared/api/__tests__/todoClient.test.ts`、`todoClient.p177.test.ts`；
- `src/pages/chat/__tests__/TodoExtractDialog.test.tsx`；
- `src/features/send-message/__tests__/chatStreamStoreTodos.test.ts`；
- `src/widgets/todo/__tests__/TodoItem.test.tsx`、`TodoItem.contextMenu.test.tsx`；
- `src/widgets/chat/__tests__/TodoListSection.test.tsx`。

当前没有覆盖真实 OS 通知与麦克风硬件的端到端测试。

## 11. 已知限制与未完成

- **LLM 兜底自然语言解析未实现**：快速录入只有本地规则解析；没有「规则失败后调用模型」的设置开关或调用路径。
- **批量操作非原子**：批量完成/删除逐条提交；批量创建中途失败时，先前条目已落库并返回 400。
- **通知轮询为 4 秒**：`SCHEDULER_NOTIFICATION_POLL_MS = 4_000`；`scheduled_router.py` 的注释仍写 15 秒，属于过期注释。
- **专家过滤未贯通 IPC**：`TodoListParams` 与后端 `/todos` 都支持 `specialist_id`，但 `electron/commandRoutes/settings.ts` 的 `todo_list` 没有序列化该参数，桌面端工具栏的专家下拉实际不会改变结果。
- **重复任务缺少页面编辑入口**：`recurrence_rule` 只存在于类型、REST、工具和服务层；前端创建/编辑表单没有 cron 输入。且只有完成任务才会生成下一实例，没有「跳过本次」「停止重复」操作。
- **对话提炼有输入窗口**：最多 80 条消息、每条 2000 字符、总预算 12000 字符、最多 10 条候选；不与已有待办查重，重复提炼可能产生重复项。
- **提醒依赖应用运行**：应用退出后没有 OS 级定时通知；逾期提醒仅内存节流，重启后可能重复一次。
- **FTS 是可选增强**：FTS5 或 jieba 不可用时退化为 `LIKE`，搜索能力仍可用但中文分词效果下降。
- **层级上限两级**：第三级创建/更新会被拒绝，没有更深的子任务树。
- **导出固定包含已完成**：页面导出按钮传 `include_completed=true`；需要仅导出未完成时只能直接调用 API。
- **服务文件接近棘轮**：`todo_service.py` 791 行，新增逻辑应继续拆入子模块。
- **模块加载**：win7 的 `backend/__init__.py` 会安装 `backend/compat/win7/pydantic_compat.py`，使 pydantic 1.10 能执行 `model_dump(exclude_unset=True)` 等 v2 风格调用；改动请求/响应模型时需同时验证两个分支。

**延伸阅读**：[182 · 待办交互升级与工作日志 / 日报周报](./182-todo-worklog-report.md) —— 本章的后继章节，描述待办交互升级（P0/P1）、工作日志捕获子系统（P2）与日报 / 周报双源聚合与存档（P3）。

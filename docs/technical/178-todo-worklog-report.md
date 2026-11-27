# 178 · 待办交互升级与工作日志 / 日报周报

## 1. 概览

本章描述 2026-11-27 交付的待办子系统一轮升级（P0–P3），它把「待办」从**单一的事务清单**扩展成**「计划 + 事实 + 汇报」三层结构**：

| 层     | 记什么                       | 载体                     | 对应期 |
| ------ | ---------------------------- | ------------------------ | ------ |
| 计划层 | 要做什么、什么状态、什么顺序 | `todos` 表               | P0/P1  |
| 事实层 | 实际做了什么、进展、阻塞     | `work_logs` 表（P2 新增） | P2     |
| 汇报层 | 聚合成可直接发出去的日报周报 | `reports` 表（P3 新增）   | P3     |

**为什么需要中间层**：改造前的 `GET /todos/brief` 与 `GET /todos/weekly-review` 只读 `todos` 表，因此只能回答「待办完成情况」，回答不了「我今天干了什么」。缺的不是报告生成器，而是**记录事实的工作日志实体**。这个判断与主流 AI 应用的形态一致 —— Async Standup / DailyBot 的标准做法是「三个固定问题（昨天 / 今天 / 阻塞）→ AI 汇总」，而不是「读任务表生成摘要」。

四期交付概览：

| 期  | 主题               | 关键交付                                                                                                  |
| --- | ------------------ | ---------------------------------------------------------------------------------------------------------- |
| P0  | 交互欠账清零       | 详情面板可编辑描述/标签/项目/提醒/负责人；行首按钮三态循环；工具栏状态筛选                                 |
| P1  | 拖拽排序与拖拽嵌套 | `todos.sort_order` 列 + `POST /todos/{id}/move` + 原生 HTML5 DnD 三区落点判定                               |
| P2  | 工作日志捕获子系统 | `work_logs` 表 + 9 个 REST 端点 + 8 条 IPC + `add_worklog` / `list_worklogs` agent 工具 + 收件箱面板        |
| P3  | 日报 / 周报        | `reports` 表 + 双源聚合 + AI/模板双模式生成 + 3 个 REST 端点 + 3 条 IPC + `TodoReportDialog` 弹窗           |

---

## 2. P0 — 交互欠账清零

### 2.1 状态机

后端 `Todo.status` 一直是四态（`pending / in_progress / completed / cancelled`），但**前端从未暴露 `in_progress`**：行首圆形按钮只有「标记完成」一种动作。P0 补上状态机的前端一侧。

状态常量与循环规则集中在 `backend/services/todo_status.py`：

| 常量              | 值            | 含义                             |
| ----------------- | ------------- | -------------------------------- |
| `PENDING`         | `pending`     | 未开始                           |
| `IN_PROGRESS`     | `in_progress` | 进行中                           |
| `COMPLETED`       | `completed`   | 已完成                           |
| `CANCELLED`       | `cancelled`   | 已取消（不在循环内）             |
| `ACTIVE_STATUSES` | 前两者        | 「仍在进行中」的集合，用于默认视图 |
| `CYCLE_ORDER`     | 前三者        | 行内循环的点击顺序               |

- `next_cycle_status(status)` —— 行内点击的下一步状态；`completed` 回到 `pending`（三态循环），`cancelled` 不参与循环。
- `completion_timestamp(status, now)` —— 进入 `completed` 时补 `completed_at`；离开 `completed` 时清空。
- `apply_completion_stamp(updates, now)` —— 服务层在 `PUT /todos/{id}` 落库前统一盖章，避免每个调用点各写一遍。

前端：`TodoRowEditor` 行首圆形按钮按 `CYCLE_ORDER` 循环，`in_progress` 行有独立视觉标识（半填充圆环）。

### 2.2 详情面板

`TodoCreateForm` 与详情面板共用一套字段组件，避免「新建表单能填、编辑时不能填」：

- `src/pages/todo/TodoFields.tsx` —— 字段控件与取值/回填逻辑（描述、标签、项目、提醒档位、优先级）。
  - `TodoFieldsValue` —— 面板内部的值形状。
  - `TodoFieldsField` —— `'description' | 'dueAtLocal' | 'projectTag' | 'tagsText'`。
  - `parseTagsText(text)` —— 逗号/空格分隔标签 → `string[]`，受 `MAX_TAGS` / `MAX_TAG_LENGTH` 约束。
  - `EMPTY_TODO_FIELDS` —— 初始值常量。
  - `PRIORITY_CONFIG` / `REMINDER_PRESETS` —— 优先级与提醒档位的可选项表。
- `src/pages/todo/TodoDetailPanel.tsx` —— 展开式详情面板。`todoToFieldsValue(todo)` 负责模型 → 表单值转换；提交时靠 `sameTags` / `sameNumbers` 判断「没改就别发」，避免无谓写库。
- 提交语义：`blur` 或 `Ctrl+Enter` 提交，`Esc` 取消。

### 2.3 状态筛选

`TodoToolbar` 增加状态下拉，与既有「智能视图」（今天 / 本周 / 已完成）**互斥** —— 选了具体状态就清掉 `view`，选了视图就清掉 `status`。此前 `handleViewChange` 会主动 `delete next.status`，把状态维度整个抹掉。

---

## 3. P1 — 拖拽排序与拖拽嵌套

### 3.1 数据模型

`todos` 表新增一列（幂等迁移，`backend/data/database.py`）：

```sql
ALTER TABLE todos ADD COLUMN sort_order REAL DEFAULT 0
CREATE INDEX IF NOT EXISTS idx_todos_sort_order ON todos(sort_order)
```

用 `REAL` 而非 `INTEGER` 是为了**中点插入**：把新行放到两个已有行之间时，取中值即可，不必重排全表。

### 3.2 排序服务：`backend/services/todo_order.py`

拖拽排序的全部规则集中在这一个模块里，`todo_service.py` 只做委托（该文件逼近 800 行棘轮顶，新逻辑一律另起模块）。

| 函数 / 类                   | 职责                                                                                              |
| --------------------------- | ------------------------------------------------------------------------------------------------- |
| `next_sort_order(...)`      | 给新行分配落在末尾的 `sort_order`                                                                   |
| `_midpoint(a, b)`           | 中点插入；相邻差过小时触发 renormalize                                                               |
| `_insert_index(...)`        | 在同层序列里定位插入位                                                                             |
| `_layer_rows(...)`          | 取同层（同一 `parent_id`）的行                                                                      |
| `_validate_dest_parent(...)` | 校验目标父级合法（父必须是顶层、不能自拖、不能拖进自己的子孙）                                       |
| `move(...)`                 | 移动主入口，返回重排后的受影响行                                                                     |
| `TodoOrderError`            | 校验失败抛出的业务异常                                                                               |

**精度耗尽缓解**：同层相邻 `sort_order` 差小于阈值时，对该层做一次 renormalize（按 1024 步长重排），保证中长期可用。这是**服务端强制执行**的，不依赖前端正确性。

### 3.3 REST 端点

```
POST /api/v1/todos/{todo_id}/move
```

请求体 `MoveTodoIn`：

| 字段               | 类型                    | 语义                                            |
| ------------------ | ----------------------- | ----------------------------------------------- |
| `position`         | `before` \| `after`     | 相对参照行落位                                  |
| `reference_id`     | `int \| null`           | 参照待办；为 `null` 时追加到目标层末尾           |
| `target_parent_id` | `int \| null` \| 省略  | **三态**：省略 = 跟随参照行所在层；`null` = 强制回顶层；给 id = 成为该待办的子任务 |

`target_parent_id` 的三态是 P1 的关键设计 —— 拖到行中间要留在同层、拖到行左缘要变子任务、拖到列表末尾要回顶层，这三种意图无法用一个 `null` 表达。

**端点注册顺序**：`/todos/{todo_id}/move` 必须注册在 `/todos/{todo_id}` 之前，否则字面量路径 `move` 会被整数路径参数吞掉（422）。

### 3.4 前端拖拽

项目**未安装任何 DnD 库**（`@dnd-kit` 曾在 PR #1356 被移除），房内风格是原生 HTML5 DnD。P1 沿用该风格，拆成「纯函数 + React 绑定」两层：

- `src/shared/lib/dnd/todoDrag.ts` —— 全部落点判定与顺序计算，**不依赖 React**，可直接单测：
  - `computeDropZone(clientX, rect, allowNest)` —— 按行内横向位置三等分：左 1/3 = `nested`、中 1/3 = `before`、右 1/3 = `after`（`NEST_ZONE_RATIO` / `BEFORE_ZONE_RATIO`）。
  - `canNestInto(...)` / `isValidDropTarget(...)` —— 过滤非法目标（不能拖进自己的子孙、层级上限两层）。
  - `buildMoveRequest(targetId, zone)` —— 落点 → `MoveTodoIn` 形状。
  - `sortByManualOrder(todos)` —— 按 `sort_order` 排；缺失时按 id 兜底。
  - `applyOptimisticMove(todos, req)` —— 乐观更新本地数组。
  - `SORT_STEP = 1024` —— 与服务端步长一致。
- `src/pages/todo/useTodoDrag.ts` —— React 绑定：返回 `handleFor(todo)` / `rowFor(todo)` 两个绑定器。
  - 仅**拖柄**（`GripVertical`）`draggable`，行本身不可拖 —— 避免与行内点击、文本选择冲突。
  - 只有 `sort_by === 'manual'` 时拖柄可用；其他排序下禁用。

`TodoPage` 默认以 `{ sort_by: 'manual' }` 加载列表（拖拽排序的前提是列表本身就是手工序），并把 `useTodoDrag` 的 `enabled` 绑定到 `params.sort_by === 'manual'`。树形视图下「前 / 后」只允许同层重排，「变成子任务」两种视图都允许。

失败回滚与 toast 在 `src/entities/todo/todoStore.ts` 的 `moveTodo` 内完成。

---

## 4. P2 — 工作日志捕获子系统

### 4.1 数据模型

`work_logs` 表（`backend/data/database.py`）：

```sql
CREATE TABLE IF NOT EXISTS work_logs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id    TEXT,
    content       TEXT NOT NULL,
    kind          TEXT NOT NULL DEFAULT 'progress',
    progress_text TEXT,
    blocker       TEXT,
    todo_id       INTEGER,
    project_id    TEXT,
    project_tag   TEXT,
    source_type   TEXT NOT NULL DEFAULT 'chat',
    source_ref    TEXT,
    status        TEXT NOT NULL DEFAULT 'pending',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL,
    FOREIGN KEY (todo_id)   REFERENCES todos(id)    ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
)
```

枚举取值：

| 字段          | 取值                                       | 含义                             |
| ------------- | ------------------------------------------ | -------------------------------- |
| `kind`        | `progress` / `done` / `blocker` / `next`   | 日志类别（对应站会三问 + 下一步） |
| `source_type` | `chat` / `manual` / `agent`                | 来源                             |
| `status`      | `pending` / `confirmed` / `dismissed`       | 待确认 / 已确认 / 已忽略          |

`kind` 的四个取值直接对应主流站会工具的三个固定问题：`done`（昨天做完了什么）、`progress`（今天在做什么）、`blocker`（卡在哪），外加 `next`（下一步）。

**`status` 是报告口径的闸门**：只有 `confirmed` 的记录进入统计与报告正文；LLM 抽取出的候选一律先落 `pending`，人工确认后才算数。

### 4.2 服务层：`backend/services/worklog_service.py`

| 方法                                          | 职责                                                      |
| --------------------------------------------- | --------------------------------------------------------- |
| `create_worklog(...)`                         | 建记录（校验 kind / source_type / todo / project 存在性） |
| `update_worklog(id, **fields)`                | 改内容                                                    |
| `delete_worklog(id)`                          | 删记录                                                    |
| `confirm_worklog(id)` / `dismiss_worklog(id)` | 状态迁移                                                  |
| `get_worklog(id)` / `list_worklogs(...)`      | 读单条 / 分页读（日期窗、kind、status、项目过滤）         |
| `count_worklogs(...)`                         | 计数                                                      |
| `list_pending(limit)`                         | 收件箱：待确认候选                                        |
| `summarize(date_from, date_to, ...)`          | **只统计已确认**的快照 `{"total", "by_kind", "sessions"}` |

模块级单例 `get_worklog_service()` / `init_worklog_service(db)` 与 `todo_service` 同款：装配根注入，工具层按需取用。

日期窗按**本地日历日**过滤 —— `_day_lower_bound` / `_day_upper_bound` 把 `YYYY-MM-DD` 展开成当天 `[00:00:00, 23:59:59.999999]` 区间，而不是用 UTC 切分。

### 4.3 AI 抽取：`backend/services/worklog_ai.py`

- `WorklogCandidate` —— 候选结构：`content` / `kind` / `progress_text` / `blocker`。
- 候选抽取从一段会话文本里抽出日志候选，**不落库**，由前端确认后再 `create`。
- 预算控制沿用 `todo_ai.py` 的模式（消息条数上限、单条字符上限、总字符预算），避免长会话把上下文撑爆。

会话文本的加载统一走 `backend/services/conversation_excerpt.py` 的 `load_conversation_excerpt(...)`。

### 4.4 LLM 客户端装配：`backend/services/llm_endpoint.py`

`todo_ai` / `worklog_ai` / `report_ai` 三处都要「拿到配置好的 LLM 客户端」，且未配置时要抛**同一个**异常类型，路由层才能统一映射 503：

```python
class LLMNotConfiguredError(RuntimeError): ...


def build_ai_client() -> Any:
    from backend.orchestration.llm_factory import build_llm_client_from_settings

    client = build_llm_client_from_settings()
    if client is None:
        raise LLMNotConfiguredError("LLM 未配置，请先在 设置 → 模型 中完成配置")
    return client
```

`llm_factory` 的导入放在函数内（延迟导入），否则模块加载期就会把 `backend.orchestration` 的依赖链拉进来。

### 4.5 REST 端点：`backend/api/worklog_router.py`

| 方法   | 路径                           | 说明                             |
| ------ | ------------------------------ | -------------------------------- |
| GET    | `/worklogs`                    | 分页列表                         |
| GET    | `/worklogs/summary`            | 时间窗统计快照（只算 confirmed） |
| POST   | `/worklogs/extract`            | 从会话抽候选（不落库）           |
| POST   | `/worklogs`                    | 手工建记录（202 Accepted）       |
| GET    | `/worklogs/{worklog_id}`       | 单条详情                         |
| PUT    | `/worklogs/{worklog_id}`       | 编辑内容                         |
| DELETE | `/worklogs/{worklog_id}`       | 删除（250）                      |
| POST   | `/worklogs/{worklog_id}/confirm` | 确认，状态转 `confirmed`       |
| POST   | `/worklogs/{worklog_id}/dismiss` | 忽略，状态转 `dismissed`       |

**端点顺序**：`/worklogs/summary` 与 `/worklogs/extract` 必须注册在 `/worklogs/{worklog_id}` 之前，否则字面量路径被整数路径参数吞掉（422）。

`UpdateWorklogIn` **不含 `status`** —— 状态迁移只走 `/confirm` 与 `/dismiss` 两个显式端点，避免「编辑正文」意外改变一条记录是否进报告。配合 `exclude_unset=True`，「键缺席 = 不动该列」与「显式 null = 清空」两种语义在 Pydantic v1 / v2 下保持一致。

### 4.6 agent 工具

`backend/tools/worklog_mgmt_tool.py` 提供两个工具：

| 工具            | 作用                                |
| --------------- | ----------------------------------- |
| `add_worklog`   | 让 agent 在对话中直接记一条工作日志 |
| `list_worklogs` | 让 agent 回查窗口内的工作日志       |

工具名注册在 `backend/domain/tool_names.py`，并加入 `backend/tools/tool_bundles.py` 的工具包。`backend/adapters/out/tool/inproc_adapter.py` 同步了工具入参 schema。

### 4.7 前端

- `src/shared/api/worklogClient.ts` —— `list` / `summary` / `create` / `update` / `delete` / `confirm` / `dismiss` / `extractFromSession`。
- `src/pages/todo/TodoWorklogPanel.tsx` —— 工作日志面板，**收件箱 + 已确认日志流 + 手动添加**三块。
  - 按日分组（`groupByDay`），日期键 `YYYY-MM-DD`，组头显示 `2026-11-27`。
  - 收件箱里的候选各有「确认 / 忽略」两个动作 —— **人工确认才进报告**。
- `TodoPage` 顶部加**分段控件**：`待办` / `工作日志`，状态写在 URL 查询参数 `?tab=logs`，可直接分享到某个具体面板。

---

## 5. P3 — 日报 / 周报

### 5.1 数据模型

`reports` 表：

```sql
CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    report_type  TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end   TEXT NOT NULL,
    content      TEXT NOT NULL,
    stats_json   TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL
)
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at)
```

`report_type` 取 `daily` / `weekly`。`stats_json` 存**生成时刻的统计快照** —— 这是刻意的设计：报告是**存档件**，不是实时视图。之后工作日志再改，昨天生成的日报不会跟着变。

### 5.2 双源聚合：`backend/services/report_ai.py`

报告的两个来源：

1. **工作日志**（`work_logs`）—— 已确认的记录，按 `kind` 归类成「做完了 / 在做 / 阻塞 / 下一步」。
2. **待办表**（`todos`）—— 时间窗内完成的、高优先级未完成的、已逾期的。

关键函数：

| 函数                                     | 职责                                                 |
| ---------------------------------------- | ---------------------------------------------------- |
| `build_report_context(...)`              | 汇聚两个来源 → 上下文 dict                           |
| `digest_for_period(...)`                 | 按时间窗产出工作日志 digest（工作日志段的薄封装）      |
| `render_template(context)`               | 纯模板渲染（LLM 不可用时的降级路径）                 |
| `_prompt(context)`                       | 构造 LLM prompt                                      |
| `today_period()` / `week_period(days=7)` | 默认时间窗（日 = 今天；周 = 近 7 天含今天）           |
| `_todo_titles(conn, sql, params)`        | 把查询结果拍平成标题列表                             |

**双模式生成**：

- 配了 LLM → 走 AI 润色，产出更自然的分组叙述。
- 没配 LLM 或调用失败 → **fail-open**，降级为纯模板汇总（工作日志 + 未完成待办列表），不报错。

### 5.3 服务层：`backend/services/report_service.py`

| 方法                              | 职责                                      |
| --------------------------------- | ----------------------------------------- |
| `create_report(...)`              | 落库一份报告（正文 + 统计快照一起冻结）    |
| `get_report(id)`                  | 单条详情                                  |
| `list_reports(report_type, ...)`  | 分页列表                                  |
| `count_reports(report_type)`      | 计数                                      |
| `default_title(type, start, end)` | 默认标题，如 `日报 · 2026-11-27`          |

`REPORT_TYPES = ("daily", "weekly")`；日期参数统一经 `_normalize_day` 归一为 `YYYY-MM-DD`。

### 5.4 REST 端点：`backend/api/report_router.py`

| 方法 | 路径                | 说明                                 |
| ---- | ------------------- | ------------------------------------ |
| POST | `/reports/generate` | 聚合 → 生成 → **存档**（201 Created） |
| GET  | `/reports`          | 分页列表（可按 `report_type` 过滤）   |
| GET  | `/reports/{id}`     | 单条详情                             |

请求体 `GenerateReportIn`：

| 字段           | 类型                   | 说明                           |
| -------------- | ---------------------- | ------------------------------ |
| `report_type`  | `daily` \| `weekly`    | 缺省 `daily`                   |
| `period_start` | `YYYY-MM-DD`（可空）   | 缺省按类型取默认窗             |
| `period_end`   | `YYYY-MM-DD`（可空）   | 同上                           |
| `title`        | 字符串（可空，≤200）   | 缺省用 `default_title`          |

`extra = "forbid"` —— 多传字段直接 422。**生成即存档**：一次调用完成「聚合 → 生成 → 落库」，返回的 `report` 就是已经存好的那条记录。

端点顺序同样有讲究：`/reports/generate` 注册在 `/reports/{report_id}` 之前。

### 5.5 IPC 与前端

**IPC 命令**（`electron/commandRoutes/settings.ts`）：

| 命令               | 位置  | 用途             |
| ------------------ | ----- | ---------------- |
| `todo_move`        | :383  | 拖拽移动（P1）   |
| `worklog_list`     | :400  | 工作日志分页列表 |
| `worklog_summary`  | :437  | 时间窗统计快照   |
| `worklog_create`   | :457  | 建记录           |
| `worklog_update`   | :461  | 编辑记录         |
| `worklog_delete`   | :472  | 删除记录         |
| `worklog_confirm`  | :476  | 确认候选         |
| `worklog_dismiss`  | :480  | 忽略候选         |
| `worklog_extract`  | :484  | 从会话抽候选     |
| `report_generate`  | :490  | 生成并存档报告   |
| `report_list`      | :511  | 报告列表         |
| `report_get`       | :528  | 报告详情         |

> **IPC 参数名用 snake_case**：`electron/invoke.ts` 的 `camelToSnakeKeys` 只作用于 **body**，而 `route.body?.(args)` 收到的是**原始 args**。渲染进程必须传 `report_type` / `period_start` / `period_end` / `title`，否则后端 `GenerateReportIn`（`extra="forbid"`）会 422。

**前端弹窗** `src/pages/todo/TodoReportDialog.tsx` —— 四块布局：

1. **时间窗** —— 起止日期 + 「生成并存档」。
2. **历史抽屉** —— 已存档报告列表，点一条即回看。
3. **统计块** —— 生成时刻冻结的统计切片（工作日志条数 / 涉及会话 / 完成待办 / 未完成 / 高优先级 / 已逾期）+ 「AI 生成」/「模板生成」徽章。
4. **正文预览** —— Markdown 渲染。

页脚三个动作：复制（`copyToClipboard`）、导出 Markdown（`downloadMarkdownFile`，文件名如 `日报-2026-11-27.md` / `周报-2026-11-21_2026-11-27.md`）、关闭。

**打开时不自动生成** —— 免得每开一次弹窗就往库里塞一条记录；改为加载历史并预览最近一份存档，用户点「生成并存档」才落库。

入口在 `TodoPage` 页头：`日报` / `周报` 两个按钮（`data-testid="todo-report-daily"` / `todo-report-weekly`），仅在「待办」分段可见。

### 5.6 与旧简报端点的关系

`GET /todos/brief` 与 `GET /todos/weekly-review` 的**端点签名不变**，但内部实现已升级：两者都改走 `report_ai.build_report_context`，把**工作日志摘要并入输入**，再交给原有的 `todo_ai.generate_daily_brief` / `generate_weekly_review` 生成文本（`backend/api/todo_router.py:420,447`）。因此旧简报现在也能看到「没建待办但确实干了」的那部分工作。旧的两条 IPC 命令（`todo_brief` / `todo_weekly_review`）与 `todoClient.dailyBrief` / `weeklyReview` 作为**已测公开 API 保留**，不删除。

前端旧的 `TodoAiDialog`（"简报"弹窗）被 `TodoReportDialog` 取代并删除；"简报"→"日报"、"周回顾"→"周报"的改名在前端原地完成。

---

## 6. 迁移与兼容

| 事项                    | 做法                                                                                   |
| ----------------------- | -------------------------------------------------------------------------------------- |
| `sort_order` 列         | 幂等迁移：`ALTER TABLE` 前先查 `PRAGMA table_info`，已存在则跳过                       |
| `work_logs` / `reports` 表 | `CREATE TABLE IF NOT EXISTS`，启动时随 `database.py` 的建表流程执行                  |
| 既有 `todos` 数据       | `sort_order` 缺省 `0`；`sortByManualOrder` 对缺失值按 id 兜底，不会错乱                |
| py38 / pydantic 1.x     | win7 分支用 `Optional[...]` / `List[...]`，禁 PEP 604 / PEP 585 写法                   |
| IPC manifest            | 每次改 IPC 必跑 `npm run ipc:manifest`，并更新 `electron/__tests__/commands.test.ts`    |

---

## 7. 测试矩阵

| 层     | 文件                                                          | 覆盖点                                                    |
| ------ | ------------------------------------------------------------- | --------------------------------------------------------- |
| pytest | `backend/tests/unit/test_todo_status.py`                      | 三态循环、完成时刻盖章                                    |
| pytest | `backend/tests/unit/test_todo_move_order.py`                  | move 端点全场景（前后落位 / 嵌套 / 非法目标 / 同层重排）  |
| pytest | `backend/tests/unit/test_worklog_service.py`                  | CRUD / confirm / dismiss / 时间窗 / 快照只算 confirmed    |
| pytest | `backend/tests/unit/api/test_worklog_router.py`               | 9 端点的状态码与响应体                                    |
| pytest | `backend/tests/unit/test_worklog_mgmt_tool.py`                | agent 工具入参与返回值                                    |
| pytest | `backend/tests/unit/test_report_service.py`                   | 存档 / 列表 / 详情                                        |
| pytest | `backend/tests/unit/test_report_ai.py`                        | 双源聚合 / 模板降级 / 快照冻结                            |
| pytest | `backend/tests/unit/api/test_report_router.py`                | 3 端点                                                    |
| vitest | `src/shared/lib/dnd/__tests__/todoDrag.P1.test.ts`            | 三区落点判定、非法目标过滤、乐观更新                      |
| vitest | `src/pages/todo/__tests__/TodoP0.statusDetail.test.tsx`       | 三态循环 / 详情提交 / 状态筛选                             |
| vitest | `src/pages/todo/__tests__/TodoWorklogPanel.test.tsx`          | 收件箱确认、已确认流、手动添加                             |
| vitest | `src/pages/todo/__tests__/TodoReportDialog.test.tsx`          | 历史预览 / 生成并存档 / 失败内联 / 统计快照 / 复制导出      |
| vitest | `src/pages/__tests__/TodoPage.test.tsx`                       | 页头入口、分段控件、工作日志分段                          |

架构棘轮：`node scripts/architecture-check.mjs` —— 新增文件均登记进 `architecture-baseline.json`，`src/shared/api/types.ts` 因多一行 `export *` 由 943 上调至 944。

---

## 8. 相关文档

- [待办 AI 原生](./166-todo-ai-native.md) —— 待办的数据模型、工具、提醒、视图与全文检索（本章的前置章节）
- [API 接口](./10-api.md) —— REST 端点与 IPC 的通用约定
- [前端架构](./09-frontend.md) —— FSD 分层与组件约定
- [错误处理](./14-error-handling.md) —— 降级策略与错误分类

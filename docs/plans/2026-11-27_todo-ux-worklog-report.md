# 待办事项交互欠账清零 + 工作日志 / 日报周报辅助（方案与实施计划）

- **日期**：2026-11-27
- **分支**：`feat/todo-ux-worklog-report`（worktree `.worktrees/feat-todo-ux-worklog-report`，基于 `origin/main`）
- **状态**：方案已定稿，待实施
- **相关历史**：`docs/plans/2026-11-16_todo-ai-native-roadmap.md`（阶段 0/1a/1b/2/3 已全部交付并双分支合并；本计划是其**补欠账 + 新增工作日志维度**的延续，不是重做）

---

## 1. 背景与目标

### 1.1 用户诉求原文

> 分析 sage 当前的待办相关模块，待办事项中，不能编辑已有待办的详情，也不能拖动待办事项改变顺序，或者将其中一个待办拖动到另外一个待办中作为子待办，待办也需要至少三个状态（未开始 / 进行中 / 已完成），此外，我还希望将待办扩展一下功能，能够让我在日常中通过对话记录工作、进度、需要完成的事等等，后续我可以根据这些信息整理完成的工作和未完成的工作，就类似一个日报周报的辅助工具，参考主流 AI 应用，给出优化建议方案。

### 1.2 目标

| # | 目标 | 归属期 |
|---|------|--------|
| G1 | 待办详情可编辑（不只是标题） | P0 |
| G2 | 待办可拖拽改变顺序 | P1 |
| G3 | 待办可拖到另一待办下成为子待办 | P1 |
| G4 | 待办支持「未开始 / 进行中 / 已完成」三态 | P0 |
| G5 | 日常对话即可记录工作 / 进度 / 待办 | P2 |
| G6 | 基于记录产出「已完成 / 未完成」日报周报 | P3 |

### 1.3 主流 AI 应用对标结论

| 能力 | 对标产品 | 关键设计 | Sage 采纳 |
|---|---|---|---|
| 状态机 | Linear / Todoist | 状态是**一等公民**，行内点击即流转 | 三态循环按钮（P0） |
| 拖拽排序 | Linear / Notion / Todoist | 拖柄（grip）+ 位置指示线，落点即写序 | 独立拖柄 + 中点插入（P1） |
| 拖拽嵌套 | Notion / Linear | 拖到行左缘 → 变子项；右缘 → 之后 | 三区判定（左=嵌套/中=前/右=后）（P1） |
| 行内属性编辑 | Notion / Linear | 属性就地展开编辑，Enter 提交 | 详情面板展开行（P0） |
| 每日站会 | Async Standup / DailyBot / Standups | 三个固定问题（昨天/今天/阻塞）→ AI 汇总 | 工作日志 kind = progress/blocker（P2） |
| 对话→行动项 | ChatGPT Tasks / Notion Meeting Notes / Todoist MCP | 从会话自动提取候选，**人工确认后落库** | 抽取为 pending 待确认（P2） |
| 报告留存 | Notion / Standups | 生成的报告可存档、可回看 | `reports` 表存档（P3） |

**核心洞察**：用户描述的「日报周报辅助」在主流产品里的标准形态是 **Standup 三问 + AI 汇总**，而不是「读待办表生成摘要」。Sage 现有的 `/todos/brief` 与 `/todos/weekly-review` 只读 `todos` 表，**没有记录"当天做了什么"的中间层**，所以无法产出真正的日报。缺的不是报告生成器，而是**工作日志（worklog）这一层实体**。

---

## 2. 现状核查（逐条纠正用户前提）

> 以下结论基于 `origin/main` @ `4f71ae6d3` 的实际代码核查，附 file:line 证据。

### 2.1 诉求 (a)「不能编辑已有待办的详情」→ **部分不成立**

- 标题行内编辑**已存在**：`src/pages/todo/TodoRowEditor.tsx:352-381`（按钮 ↔ input 切换，Enter/blur 提交、Esc 取消，`data-testid="todo-title-edit-input"`）。
- 后端 `PUT /todos/{id}` 也已支持 `description`（`backend/services/todo_service.py:71-85` 的 `_UPDATABLE_FIELDS` 含 `description`）。
- **真正缺失的是「详情面板」**：描述、项目、标签、提醒档位、负责人这些字段没有任何行内入口，只能通过"新建表单"录入后无法再改；`description` 在 UI 上只以一个 📝 emoji 提示存在（`TodoRowEditor.tsx:383-388`），点击无反应。
- 结论：**不是"能不能编辑"，而是"没有详情编辑入口"**。P0 交付一个展开式详情面板。

### 2.2 诉求 (b)「不能拖动待办事项改变顺序」→ **完全成立，且是硬缺口**

- `todos` 表 **26 列中没有任何排序列**（`backend/data/database.py:2507-2540`），索引只有 `status / due_at / project_tag / parent_id`（`:2543-2546`）。
- 后端排序是**固定白名单**：`backend/services/todo_filters.py:21-25` 的 `SORT_EXPRS` 只有 `due_at / priority / created_at`；前端下拉同构（`src/pages/todo/TodoToolbar.tsx:39-43`）。
- 前端 store 是**扁平数组无序状态**：`src/entities/todo/todoStore.ts`（178 行，`create` 直接 push 到末尾）。
- 项目**未安装任何 DnD 库**（`@dnd-kit` 在 PR #1356 被刻意移除），房内风格是**原生 HTML5 DnD**（参考 `src/widgets/chat/PendingQueuePanel.tsx:118-153`、`src/pages/settings/PromptTemplatesTab.tsx:504-512`）。
- 结论：需要**新增 `sort_order` 列 + 新增排序表达式 + 新增拖拽交互**三层全做。

### 2.3 诉求 (c)「不能拖动到另一个待办中作为子待办」→ **数据层齐备，只缺拖拽入口**

- `todos.parent_id` 已存在，FK `ON DELETE SET NULL`（`database.py:2533-2534`）。
- 服务层两级校验已实现：`create_todo` 校验父存在 + 父必须是顶层（`backend/services/todo_service.py:149-207`，`"subtask depth exceeds 2 levels"`）。
- API `CreateTodoIn/UpdateTodoIn` 已含 `parent_id`；agent 工具 `todo_mgmt_tool.py` 已支持。
- 前端已有「＋ 子任务」行内输入（`TodoRowEditor.tsx:550-563`）、树形渲染 `TodoSubtaskTree.tsx`、批量创建子任务 `handleAddSubtask`（`src/pages/TodoPage.tsx:228-233`）。
- 结论：**唯一缺的是「拖到某行上 → 变子任务」的入口**。P1 只需补这条交互 + 一个保序的 `move` 端点。

### 2.4 诉求 (d)「待办需要至少三个状态」→ **后端已支持，前端从未暴露**

- 后端 `Todo.status` 已是四态 `pending / in_progress / completed / cancelled`（`todo_service.py:88-110`）；列表过滤 SQL 已用 `status IN ('pending','in_progress')`（`todo_filters.py:48/54/61/66`）。
- agent 工具侧 `VALID_TODO_STATUSES = ("pending","in_progress","completed")`（`backend/tools/todo_tool.py`）——三态在工具层**已存在**。
- **前端**：`TodoRowEditor.tsx:329-338` 的圆形按钮**只有"标记完成"一种动作**；`UpdateTodoInput.status` 类型是 `'pending' | 'in_progress' | 'cancelled'`（`src/shared/api/types/templateAndTaskTypes.ts:439`）但 UI 无任何路径写入 `in_progress`；`TodoToolbar` 也**没有状态筛选下拉**（且 `handleViewChange` 会主动 `delete next.status`，`:63-68`）。
- 结论：**纯前端欠账**。P0 补三态循环 + 状态筛选。

### 2.5 诉求 (e)「对话记录工作 → 日报周报」→ **中间层完全缺失**

- 已有 `POST /todos/extract`（`backend/services/todo_ai.py:137`）：从会话消息抽**候选待办**，**不落库**（需人工确认）。只覆盖"要做的事"，不覆盖"做过什么 / 进度 / 阻塞"。
- 已有 `GET /todos/brief`（`todo_ai.py:173`）与 `GET /todos/weekly-review`（`:190`）：**输入全部来自 `todos` 表统计**，因此只能回答"待办完成情况"，无法回答"我今天干了什么"。
- 已有 `backend/chat/recap.py`（243 行）：产出 progress/decisions/next_steps，但**手动触发、不持久化、会话内作用域**——不能当日报存档。
- 结论：需要**新增 worklog 实体（方案 B）**，把"对话 → 工作日志 → 日报/周报"补成完整三段式。

### 2.6 现状小结

| 诉求 | 核查结论 | 实际工作量 |
|---|---|---|
| (a) 编辑详情 | 标题可编辑，**详情面板缺失** | 前端为主（新建 `TodoFields.tsx` 共享字段组件） |
| (b) 拖拽排序 | **完全缺失** | 后端加列 + 排序表达式 + 前端 DnD |
| (c) 拖拽嵌套 | 数据层齐备，**缺入口** | 前端 DnD + 一个 `move` 端点 |
| (d) 三态 | 后端已支持，**前端未暴露** | 纯前端 |
| (e) 日报周报 | **中间层缺失** | 新增 worklog + report 两个子系统 |

---

## 3. 方案选型

### 3.1 工作日志存储：三个候选

| 方案 | 描述 | 优点 | 缺点 | 结论 |
|---|---|---|---|---|
| **A. 单表扩展** `todos` 加 `log_kind` 列 | 用 `todos` 表同时装"待办"和"日志" | 不加表 | 语义污染：日志无 `due_at`/`priority`/`parent_id` 语义；`todos` 已 26 列；report 查询要 `WHERE log_kind IS NULL` 处处防漏；FTS 表要同步过滤 | ❌ |
| **B. 独立工作日志子系统** ✅ | 新表 `work_logs` + `worklog_service.py` + `worklog_ai.py` | 语义干净；独立字段（kind/session_id/progress/blocker）；可独立演进；report 生成只查两张表；避开 `todo_service.py` 791 行棘轮 | 多一张表 + 一套 API/工具/前端 | ✅ **采纳** |
| **C. 事件溯源** 单一事件流 | 所有 todo/log 变更都是事件 | 审计能力强 | 远超当前需求；查询复杂；迁移成本高 | ❌ |

**采纳 B**，理由：① 用户诉求本质是两类不同实体（要做的事 vs 已做的事），塞一张表会让所有既有查询都要加 `AND kind='todo'` 条件，是典型的语义污染；② 双轨存储让日报生成逻辑清晰——`work_logs`（做了什么）+ `todos`（未完成什么）两个来源，恰好对应用户说的"整理完成的工作和未完成的工作"；③ 新表独立演进，不动 `todo_service.py`（已在 791/800 行棘轮边缘）。

### 3.2 排序语义：全局手工顺序 + `sort_order` 列 ✅（已确认）

- `sort_order REAL DEFAULT 0` —— 用 **REAL 中点分配**（在相邻两值之间取中点），避免每次移动都重写整表。REAL 精度耗尽（相邻差 < 1e-9）时触发**局部重排**（renormalize）。
- 子任务与顶层各自排序（索引 `idx_todos_sort_order ON todos(parent_id, sort_order)`），`parent_id` 用 `COALESCE(parent_id, 0)` 归一以让顶层共享同一序列。
- 「手动」排序为排序下拉的一个选项；**只有选中「手动」时拖柄可用**，否则拖拽禁用并提示原因（避免"拖了没反应"的困惑）。这是主流产品（Notion / Todoist）的通行做法。

### 3.3 子任务层级：维持两级 ✅（已确认）

后端已硬校验两级，P1 拖拽嵌套遵循同一约束：
- 拖到**顶层行**左缘 → 成为其子任务；
- 拖到**子任务行**左缘 → **禁止**（会超两层），拖拽时该行不显示"变子任务"指示区；
- 拖到子任务行右/中 → 只在子任务**同级**重排（保持父不变）。

### 3.4 状态交互：行内三态循环 ✅（已确认）

- 行首圆形按钮：`pending → in_progress → completed → pending`（循环）。
- `completed` 已有绿色 ✓ 静态展示；`in_progress` 用**半圆/环形进度图标**（蓝色）展示。
- `cancelled` 保留在行尾 ✗ 按钮（显式动作，非循环态）。
- 「标记完成」动作仍可从**右键菜单**直达（`contextMenu.todo.complete`），保持既有路径。

### 3.5 树形视图拖拽：仅同级重排 ✅（已确认）

`TodoSubtaskTree.tsx` 渲染两层树，跨层级拖拽会让"缩进层级 ↔ parent_id"双向同步复杂化且易错。规则：

- 树形视图内：仅允许**同级重排**（拖子任务到另一子任务前后 / 顶层到顶层前后）；
- **嵌套（变子任务）只在扁平列表视图可用**，拖到目标行左缘触发；
- 树形视图的拖柄仍可拖，但落区只有"前/后"，无"变子任务"。

### 3.6 报告入口：原地升级既有「AI 简报 / 周回顾」 ✅（已确认）

不新增页头按钮，避免工具栏膨胀：
- `「简报」` → **`「日报」`**：内部引擎换成新的 report 引擎（双来源：work_logs + todos）；
- `「周回顾」` → **`「周报」`**：同上，时间窗改为最近 7 天；
- 两个弹窗内加**时间窗选择器**（今天 / 昨天 / 最近 7 天 / 自定义区间）。

---

## 4. 第 1 节：数据模型与 API 契约

### 4.1 `todos` 表新增列（P1）

```sql
-- 幂等迁移（沿用 database.py:2556-2576 的既有回填模式）
ALTER TABLE todos ADD COLUMN sort_order REAL DEFAULT 0;
CREATE INDEX IF NOT EXISTS idx_todos_sort_order ON todos(parent_id, sort_order);
```

`Todo` 模型新增 `sort_order: float = 0.0`；`TodoOut` 返回该字段。

### 4.2 `work_logs` 表（P2）

```sql
CREATE TABLE IF NOT EXISTS work_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT,                -- 来源会话（可空：手动记录）
    content TEXT NOT NULL,          -- 工作内容（做了什么）
    kind TEXT NOT NULL DEFAULT 'progress',  -- progress=进展 / done=完成 / blocker=阻塞 / next=下一步
    progress_text TEXT,             -- 进度说明（可选）
    blocker TEXT,                   -- 阻塞说明（kind=blocker 时）
    todo_id INTEGER,                -- 关联的待办（可空）
    project_id TEXT,
    project_tag TEXT,
    source_type TEXT DEFAULT 'chat',  -- chat=对话抽取 / manual=手动录入 / agent=agent 工具
    source_ref TEXT,                -- 消息 id 列表 / session id
    status TEXT NOT NULL DEFAULT 'pending',  -- pending=待确认 / confirmed=已确认 / dismissed=已忽略
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (todo_id) REFERENCES todos(id) ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);
CREATE INDEX IF NOT EXISTS idx_work_logs_created ON work_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_work_logs_status ON work_logs(status);
CREATE INDEX IF NOT EXISTS idx_work_logs_kind ON work_logs(kind);
```

**双轨存储的关键点**：`work_logs.status='pending'` 的行是"待确认候选"（对话抽取产物），`confirmed` 的是正式记录（进日报）。未确认的行**绝不进报告**。

### 4.3 `reports` 表（P3）

```sql
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    report_type TEXT NOT NULL,       -- daily=日报 / weekly=周报
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    content TEXT NOT NULL,           -- Markdown 正文
    stats_json TEXT,                 -- 统计快照 JSON
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reports_created ON reports(created_at);
```

### 4.4 API 契约

#### P0 — 无新增端点（复用 `PUT /todos/{id}`）

```
PUT /api/v1/todos/{todo_id}
{ "description": "...", "status": "in_progress", "tags": [...], ... }
```

`UpdateTodoIn.status` 类型扩为 `'pending' | 'in_progress' | 'completed' | 'cancelled'`（前端类型同步）。

#### P1 — 新增移动端点

```
POST /api/v1/todos/{todo_id}/move
{
  "target_parent_id": null | int,   -- null = 顶层；int = 成为该 todo 的子任务
  "position": "before" | "after",    -- 相对同层参照物
  "before_id": int | null            -- 参照物 id：落点在其之前(before)或之后(after)
}
→ 200 { "todo": TodoOut, "affected": int }
```

语义说明：
- `target_parent_id` = 落点所在父级（`null` = 顶层）；
- `before_id` = 同层参照物；`position='before'` 表示插到 `before_id` 之前，`'after'` 表示插到之后；
- 若只给 `before_id` 不给 `target_parent_id`，服务端以 `before_id` 的 `parent_id` 推断；
- 服务端做**全部合法性校验**：父存在、父是顶层（两级上限）、不拖到自己/自己的子孙、参照物同层。

> ⚠️ **路由顺序**：`/todos/{todo_id}/move` 插在 `todo_router.py:319-335` 的 `/todos/batch/*` 之后、`:437` 的 `/todos/{todo_id}` 之前即可（FastAPI 按注册顺序匹配，`{todo_id}` 是路径参数，不会吞掉 `/move` 后缀，但保持"先具体后泛化"的既有约定更安全）。

#### P2 — 工作日志端点

```
GET    /api/v1/worklogs?status=&kind=&from=&to=&limit=&offset=
POST   /api/v1/worklogs                       { content, kind, todo_id?, project_tag?, source_type?, source_ref? }
PUT    /api/v1/worklogs/{id}                  （编辑）
DELETE /api/v1/worklogs/{id}
POST   /api/v1/worklogs/{id}/confirm          pending → confirmed
POST   /api/v1/worklogs/{id}/dismiss          pending → dismissed
POST   /api/v1/worklogs/extract               { session_id } → { candidates: [...] }（LLM 抽取，不落库）
```

#### P3 — 报告端点

```
POST /api/v1/reports/generate
{ "report_type": "daily" | "weekly", "period_start": "YYYY-MM-DD", "period_end": "YYYY-MM-DD", "title": "可选" }
→ 201 { "report": ReportOut }

GET  /api/v1/reports?report_type=&limit=
GET  /api/v1/reports/{id}
```

**并且**：升级既有 `GET /todos/brief` 与 `GET /todos/weekly-review` 的内部实现 —— 改为调用新的 report 引擎（双来源），保持端点与响应模型 `AiTextOut` 不变（前端/IPC 不用大改）。

### 4.5 IPC 映射（新增命令）

| 命令 | 端点 |
|---|---|
| `todo_move` | `POST /todos/{id}/move` |
| `worklog_list` | `GET /worklogs` |
| `worklog_create` | `POST /worklogs` |
| `worklog_update` | `PUT /worklogs/{id}` |
| `worklog_delete` | `DELETE /worklogs/{id}` |
| `worklog_confirm` | `POST /worklogs/{id}/confirm` |
| `worklog_dismiss` | `POST /worklogs/{id}/dismiss` |
| `worklog_extract` | `POST /worklogs/extract` |
| `report_generate` | `POST /reports/generate` |
| `report_list` | `GET /reports` |
| `report_get` | `GET /reports/{id}` |

改动 IPC 后**必须**执行 `npm run ipc:manifest` 重生成 manifest，并同步更新 `electron/__tests__/commands.test.ts`（在棘轮基线里）。

### 4.6 Agent 工具（P2）

在既有 todo 工具包中新增两个 LLM 工具：
- `add_worklog(content, kind='progress', todo_id?, project_tag?)` —— 供 agent 在对话中随手记录工作；
- `list_worklogs(from?, to?, kind?)` —— 供 agent 回答"我这两天做了什么"。

---

## 5. 第 2 节：前端交互设计

### 5.1 P0：详情可编辑 + 三态循环 + 状态筛选

**5.1.1 抽出共享字段组件 `src/pages/todo/TodoFields.tsx`**

把 `TodoCreateForm.tsx`（278 行）里的字段块抽成可复用组件：
- `DescriptionField`（多行文本，blur / Ctrl+Enter 提交）
- `TagsField`（chip 输入）
- `ProjectTagField`
- `ReminderOffsetsField`
- `SpecialistField`

`TodoCreateForm` 与新的行内详情面板共用同一套，保证"建的时候能填、事后能改"字段完全一致。

**5.1.2 行内详情面板**

- `TodoRowEditor` 的 📝 指示器改为**可点击按钮**，点击在行下方**就地展开**详情面板（非模态，不跳页）。
- 面板内容：描述（textarea）、标签、项目、提醒档位、负责人。
- 提交时机：描述 `blur` 或 `Ctrl+Enter`；chip 类即时提交（切换即 PATCH）。
- 面板内 `Escape` 收起。
- 复用 `ContextMenu` 的 `enabled` 开关模式，避免与右键菜单打架。

**5.1.3 三态循环**

行首圆形按钮改为：
- `pending`：空心圆（hover 显示 ▶ 提示）
- `in_progress`：蓝色半填充圆（`CircleDot`/`Loader` 图标）
- `completed`：绿色实心 ✓
- 点击循环 `pending → in_progress → completed → pending`

实现细节：
- 组件加 `cycleStatus` 回调，`TodoPage` 调 `todoStore.update(id, { status })`。
- `UpdateTodoInput.status` 类型加 `'completed'`（当前缺）。
- `completed` 行仍是灰底+删除线；`in_progress` 行加**左侧 2px 主色竖条**标识（视觉上一眼可辨）。

**5.1.4 状态筛选**

`TodoToolbar` 增加状态下拉（全部 / 未开始 / 进行中 / 已完成 / 已取消），复用既有 `TodoListParams.status`（后端 `apply_common_filters` 已支持 `status` 精确过滤，`todo_filters.py:62-64`）。

> ⚠️ 注意 `handleViewChange`（`TodoToolbar.tsx:63-68`）会 `delete next.status` —— 视图与状态互斥的现有语义保持不变：选了智能视图就清状态筛选，反之亦然。

### 5.2 P1：拖拽排序 + 拖拽嵌套

**5.2.1 拖柄**

- 行**末尾**新增 `GripVertical` 拖柄（`opacity-0 group-hover:opacity-100`，与既有行尾按钮一致）。
- **只有拖柄是 `draggable`**（不是整行）—— 避免与行内文本选中、按钮点击冲突。这是主流产品的通行做法。
- 排序依据**非「手动」**时拖柄禁用（`cursor-not-allowed` + title 说明）。

**5.2.2 落点判定（三区）**

拖动时对目标行计算鼠标 X 相对该行宽度的位置：

| 区域 | 判定 | 视觉反馈 | 结果 |
|---|---|---|---|
| 左 1/3 | `x < 1/3` | 左侧出现 ▸ 缩进标记 | 变为该行的**子任务** |
| 中 1/3 | `1/3 ≤ x < 2/3` | 目标行**上/下**插入指示线 | 插到目标行**之前** |
| 右 1/3 | `x ≥ 2/3` | 目标行**下**插入指示线 | 插到目标行**之后** |

- 树形视图：只有"前/后"两区（左区不显示嵌套提示）。
- 子任务行的左区禁用嵌套（两级上限），改为提示「已达两层上限」。

**5.2.3 落点算法**

- 前端维护本地"幽灵行"（dragover 时插入占位），松手后调用 `POST /todos/{id}/move`。
- 服务端用**中点分配**写 `sort_order`：
  - 插入到最前：`new = first.sort_order - 1024`
  - 插入到最后：`new = last.sort_order + 1024`
  - 插入到两行之间：`new = (prev + next) / 2`
  - 相邻差 < `1e-9` → 触发同层 `renormalize`（重排为 1024 步长）后再写。
- **乐观更新 + 失败回滚**：前端先按落点重排本地数组，失败则回滚原数组并 toast 提示。

**5.2.4 store 改造**

`todoStore` 增加：
- `moveTodo(id, targetParentId, position, beforeId)` action：乐观重排 → 调 API → 失败回滚。

排序依据为「手动」时，列表请求带 `sort_by=manual`（新增排序表达式，`todo_filters.py:21-25` 加 `"manual": "COALESCE(parent_id, 0), sort_order"`）。

> ⚠️ `TodoListParams.sort_by` 类型是闭合联合 `'due_at' | 'priority' | 'created_at'`（`templateAndTaskTypes.ts:477`），需扩 `'manual'`。

### 5.3 P2：工作日志面板

- `TodoPage` 顶部加**分段控件**（Segmented Control）：`待办 / 工作日志` 两个 tab，用 URL query `?tab=logs` 可直达（与既有 `?quickadd=1` 风格一致）。
- `src/pages/todo/TodoWorklogPanel.tsx`：
  - **待确认收件箱**（顶部，`status=pending`）：每条一行，显示抽取摘要 + 「确认 / 编辑 / 忽略」三按钮；
  - **日志流**（按天分组）：kind 徽标（进展/完成/阻塞/下一步，不同颜色）、关联待办 chip、项目 chip、来源会话深链（跳回该会话）；
  - **手动添加**：输入框 + kind 选择器。
- 对话中自动捕获：聊天消息流结束后，检测到工作类语句 → 调 `POST /worklogs/extract` → 候选进收件箱（**不自动入库**，对齐"人工确认"原则）。

### 5.4 P3：日报 / 周报

- 页头 `「简报」` → `「日报」`，`「周回顾」` → `「周报」`（原地改名，图标不变）。
- `src/pages/todo/TodoReportDialog.tsx`：
  - 时间窗选择器（今天 / 昨天 / 最近 7 天 / 自定义）；
  - **统计块**（今日完成 N / 新增待办 N / 阻塞 N / 关联会话 N）；
  - **Markdown 预览**（渲染 + 源码切换）；
  - 「复制」/「导出 .md」/「存档」三按钮；
  - 历史抽屉：列出已存档报告，点开查看；同类型同区间已存在 → 提示覆盖确认。

---

## 6. 实施步骤（四期）

> 格式：`- [ ]` 勾选，随实施推进更新。

### P0 — 交互欠账清零

- [ ] 步骤 P0.1：抽 `src/pages/todo/TodoFields.tsx`（描述/标签/项目/提醒/负责人），`TodoCreateForm` 改用它
- [ ] 步骤 P0.2：`TodoRowEditor` 加可展开详情面板（📝 → 按钮，blur/Ctrl+Enter 提交）
- [ ] 步骤 P0.3：行首圆形按钮改三态循环（`pending → in_progress → completed`），`in_progress` 视觉标识
- [ ] 步骤 P0.4：类型扩展 `UpdateTodoInput.status` 加 `'completed'`；`Todo` 加 `status` 渲染分支
- [ ] 步骤 P0.5：`TodoToolbar` 加状态筛选下拉（与智能视图互斥）
- [ ] 步骤 P0.6：vitest 覆盖（三态循环 / 详情提交 / 状态筛选）+ pytest 覆盖 `PUT /todos/{id}` 改 status
- [ ] 步骤 P0.7：ruff / tsc / vitest / pytest 全绿

### P1 — 拖拽排序与拖拽嵌套

- [ ] 步骤 P1.1：`database.py` 加 `sort_order REAL DEFAULT 0` + `idx_todos_sort_order`（幂等迁移）
- [ ] 步骤 P1.2：新模块 `backend/services/todo_order.py`（中点分配 / renormalize / 同层取序）
- [ ] 步骤 P1.3：`todo_filters.py` 的 `SORT_EXPRS` 加 `"manual"`
- [ ] 步骤 P1.4：`POST /todos/{todo_id}/move` 端点（**注册在 `/todos/{todo_id}` 之前**）+ 全部合法性校验
- [ ] 步骤 P1.5：`Todo` / `TodoOut` 加 `sort_order`；`TodoListParams.sort_by` 加 `'manual'`
- [ ] 步骤 P1.6：前端 `GripVertical` 拖柄（仅拖柄 draggable）+ 三区落点判定 + 幽灵行指示
- [ ] 步骤 P1.7：`todoStore.moveTodo` 乐观更新 + 失败回滚 + toast
- [ ] 步骤 P1.8：IPC `todo_move` + `npm run ipc:manifest` + `commands.test.ts` 更新
- [ ] 步骤 P1.9：pytest（move 端点全场景）+ vitest（拖拽判定纯函数）全绿

### P2 — 工作日志捕获子系统

- [ ] 步骤 P2.1：`database.py` 建 `work_logs` 表 + 索引
- [ ] 步骤 P2.2：`backend/services/worklog_service.py`（CRUD + confirm/dismiss + 时间窗查询）
- [ ] 步骤 P2.3：`backend/services/worklog_ai.py`（LLM 抽取候选，不落库；沿用 `todo_ai.py` 的预算控制模式）
- [ ] 步骤 P2.4：`backend/api/worklog_router.py`（8 个端点）
- [ ] 步骤 P2.5：agent 工具 `add_worklog` / `list_worklogs`
- [ ] 步骤 P2.6：IPC 8 命令 + manifest
- [ ] 步骤 P2.7：前端 `TodoWorklogPanel.tsx`（收件箱 + 日志流 + 手动添加）+ `TodoPage` 分段控件
- [ ] 步骤 P2.8：pytest + vitest 全绿

### P3 — 日报 / 周报

- [ ] 步骤 P3.1：`database.py` 建 `reports` 表
- [ ] 步骤 P3.2：`backend/services/report_service.py`（存档 / 列表 / 详情）
- [ ] 步骤 P3.3：`backend/services/report_ai.py`（双来源汇总 → LLM Markdown；未配置 LLM → 降级纯模板）
- [ ] 步骤 P3.4：`backend/api/report_router.py`（3 个端点）
- [ ] 步骤 P3.5：升级 `/todos/brief` 与 `/todos/weekly-review` 内部实现（端点签名不变）
- [ ] 步骤 P3.6：IPC 3 命令 + manifest
- [ ] 步骤 P3.7：前端 `TodoReportDialog.tsx`（时间窗 + 统计块 + Markdown 预览 + 复制/导出/存档 + 历史抽屉）
- [ ] 步骤 P3.8：`「简报」→「日报」`、`「周回顾」→「周报」` 原地改名
- [ ] 步骤 P3.9：pytest + vitest 全绿

### 收尾

- [ ] 更新 `architecture-baseline.json`（新增文件行数、`database.py` 行数变化）
- [ ] 技术文档 `docs/technical/` 新增章节 + README 目录
- [ ] 用户手册 `docs/user-manual/` 新增章节 + README 目录
- [ ] cherry-pick 到 `release/win7`（py38 / pydantic 1.x 适配：`Optional[...]` / `List[...]`，禁 PEP 604/585）
- [ ] 双分支 PR + CI 绿

---

## 7. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| `sort_order` REAL 精度耗尽 | 排序错乱 | 相邻差 < `1e-9` 触发同层 renormalize（1024 步长）；服务端强制执行 |
| 拖拽与行内点击/文本选择冲突 | 误触发 | 仅拖柄 draggable；`dragstart` 时阻止默认；行首复选框与按钮 `draggable=false` |
| 拖拽后端校验失败（父是子任务 / 自拖） | 顺序错乱 | 前端落点计算即过滤非法目标；服务端二次校验并回滚 |
| `todo_service.py` 791/800 行触棘轮 | CI 红 | **新逻辑一律放新模块**（`todo_order.py` / `worklog_*` / `report_*`），`todo_service.py` 只加委托 |
| LLM 抽取误记工作日志 | 报告失真 | 候选进 `pending`，**人工确认后才进报告**；未确认行不进统计 |
| LLM 未配置 | 日报生成失败 | fail-open：降级为**纯模板**汇总（工作日志 + 未完成待办列表），不报错 |
| 对话抽取开销 | 响应变慢 | 沿用 `todo_ai.py` 的预算常量（`MAX_MESSAGES=80` / `MAX_MESSAGE_CHARS=2000` / 总预算 12000 字符），后台异步触发 |
| 双分支语法漂移 | win7 CI 红 | 写 py38 兼容代码（`Optional`/`List`，禁 `X \| None` / `list[int]`）；win7 用 `sage-backend-py38` 跑测 |
| IPC manifest 未重生成 | 运行期命令缺失 | 每次改 IPC 后必跑 `npm run ipc:manifest`，并更新 `commands.test.ts` |
| 前端文件超 800 行 | 棘轮红 | `TodoRowEditor.tsx` 568 行已近上限 → **详情面板拆到独立 `TodoDetailPanel.tsx`**，行内编辑逻辑留在行组件 |

---

## 8. 验收标准

### P0
1. 任意待办行点击 📝 可展开详情面板，描述 blur/Ctrl+Enter 保存并持久化；
2. 行首圆形按钮依次点击，状态按 `未开始 → 进行中 → 已完成 → 未开始` 循环，`in_progress` 行有可见标识；
3. 工具栏状态筛选可选「进行中」，列表只显示进行中项；
4. `pytest backend/tests/{unit,integration}/*todo*` 全绿；`npx vitest run src/pages/__tests__/TodoPage.test.tsx` 全绿。

### P1
5. 拖柄可拖动，行落点出现插入指示线，松手后顺序持久化（刷新后不变）；
6. 拖到另一行左缘 → 该行成为其子任务，树形视图正确显示；
7. 拖到子任务行左缘被拒绝并提示两层上限；
8. `POST /todos/{id}/move` 覆盖：移到顶层 / 成为子任务 / 前插 / 后插 / 非法父 / 自拖 / 越层，各返回预期（400/404/200）；
9. 「手动」排序为默认时刷新顺序保持。

### P2
10. 对话后可抽取工作日志候选 → 收件箱可确认/编辑/忽略；
11. 确认后的日志出现在按天分组的日志流，带 kind 徽标与来源会话深链；
12. 未确认的候选**不出现在**报告统计中。

### P3
13. 「日报」弹窗能按时间窗生成 Markdown，含「已完成 / 未完成」两段；
14. 「周报」同上，覆盖 7 天；
15. 报告可存档、列表可查、可复制 / 导出 `.md`；
16. LLM 未配置时降级为模板汇总，不报错。

---

## 9. 实施注意事项（棘轮 / 双分支）

1. **架构棘轮**：`backend/data/database.py` 当前基线 2840 行 —— 加表加列后会增长，需同步更新 `architecture-baseline.json`。新增文件必须登记。
2. **文件行数**：`backend/services/todo_service.py` 791/800 —— 只允许加委托调用（≤8 行），其余逻辑进新模块。
3. **双分支**：main（Python 3.10 / pydantic 2.x）与 release/win7（Python 3.8 / pydantic 1.x）都要交付。代码写 py38 兼容语法，main 上同样能跑（子集写法）。
4. **测试环境**：main 用 `sage-backend`；win7 用 `sage-backend-py38`。worktree 内**不要**往共享环境装包。
5. **前端测试**：worktree 无 `node_modules` → 软链主仓库 `node_modules`。
6. **IPC**：改完必跑 `npm run ipc:manifest`。
7. **worktree 路径陷阱**：Bash 工具的 cwd 不会持久切到 worktree，所有命令用绝对路径。

---

## 10. 附录：关键代码位置索引

| 关注点 | 位置 |
|---|---|
| `todos` 表 DDL | `backend/data/database.py:2507-2540` |
| `todos` 索引 | `backend/data/database.py:2543-2546` |
| 幂等列回填模式 | `backend/data/database.py:2556-2576` |
| `Todo` 模型 | `backend/services/todo_service.py:88-110` |
| `_UPDATABLE_FIELDS` | `backend/services/todo_service.py:71-85` |
| `create_todo`（父校验 / 两级上限） | `backend/services/todo_service.py:149-207` |
| `update_todo` | `backend/services/todo_service.py:320` |
| 排序白名单 | `backend/services/todo_filters.py:21-25` |
| 状态/视图过滤 | `backend/services/todo_filters.py:42-66` |
| 待办路由（19 端点） | `backend/api/todo_router.py:212-489` |
| LLM 抽取（不落库） | `backend/services/todo_ai.py:137` |
| AI 简报 | `backend/services/todo_ai.py:173` |
| 周回顾 | `backend/services/todo_ai.py:190` |
| 会话 recap（不持久） | `backend/chat/recap.py` |
| 行内标题编辑 | `src/pages/todo/TodoRowEditor.tsx:352-381` |
| 状态按钮（仅"完成"） | `src/pages/todo/TodoRowEditor.tsx:329-338` |
| 📝 指示器（不可点） | `src/pages/todo/TodoRowEditor.tsx:383-388` |
| 行尾 ＋ 子任务 | `src/pages/todo/TodoRowEditor.tsx:550-563` |
| 行尾操作区 | `src/pages/todo/TodoRowEditor.tsx:513-546` |
| 工具栏（无状态筛选） | `src/pages/todo/TodoToolbar.tsx:39-68` |
| 树形渲染 | `src/pages/todo/TodoSubtaskTree.tsx` |
| store（扁平无序） | `src/entities/todo/todoStore.ts` |
| 类型定义 | `src/shared/api/types/templateAndTaskTypes.ts:384-518` |
| 原生 DnD 参考（重排） | `src/widgets/chat/PendingQueuePanel.tsx:118-153` |
| 原生 DnD 参考（指示线） | `src/pages/settings/PromptTemplatesTab.tsx:504-512` |
| IPC 映射 | `electron/commandRoutes/settings.ts:233-366` |
| 既有路线图（四阶段已交付） | `docs/plans/2026-11-16_todo-ai-native-roadmap.md` |

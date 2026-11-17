# 待办事项（备忘录）AI 原生升级路线图

- **日期**：2026-11-16
- **分支**：`feat/todo-ai-native-foundation`（基于 `release/win7`，完成后 cherry-pick 到 main）
- **状态**：进行中（阶段 0 实施中）

## 1. 背景与目标

### 1.1 现状

Sage 的「待办事项」已具备：SQLite `todos` 表、REST API（`/api/v1/todos`）、
5 个 agent 工具（add/list/complete/update/delete）、提醒调度器
（24h/1h/到期 + 精确 5 分钟触发器，Electron 每 15s 轮询转系统通知）、
整页 UI（表单创建、筛选/排序、批量操作、子任务树渲染）。

### 1.2 与主流 AI 应用的差距

| 能力 | ChatGPT Tasks | Apple 提醒 | Todoist / TickTick | Notion AI / flomo | Sage 现状 |
|---|---|---|---|---|---|
| 自然语言录入 | ✅ | ✅ Siri | ✅ | ✅ | ❌ 纯表单 |
| 从对话提炼行动项 | ✅ | ❌ | ❌ | ✅ | ❌ |
| 系统通知提醒 | ✅ | ✅ | ✅ | 部分 | ✅ 已有 |
| 重复任务 | ✅ | ✅ | ✅ | ❌ | ⚠️ 字段存在但从不生成下一实例 |
| 子任务 | ❌ | ✅ | ✅ | ✅ | ⚠️ 有渲染树，无创建/API 入口 |
| 全文搜索 | ✅ | ✅ | ✅ | ✅ | ⚠️ 仅前端当前页过滤 |
| 每日/每周回顾 | ❌ | ❌ | ✅ 统计 | ✅ AI 总结 | ⚠️ 仅计数统计 |
| 语音录入 | ✅ | ✅ | ✅ | ❌ | ⚠️ 有 ASR 工具，未接入 |

结论：提醒管道与 agent 工具层已打通，缺的是**基础功能欠账**与**AI 原生交互层**。
采用增量演进（不新建备忘录子系统），分四阶段交付。

### 1.3 目标

1. 阶段 0 清空欠账：重复规则落地、子任务打通、后端全文搜索、批量端点、导出。
2. 阶段 1 补基础体验：快速录入（命令面板 + 快捷键）、本地 NL 解析、多标签、
   智能视图（今天/近 7 天/全部/已完成）、自定义提醒、语音录入。
3. 阶段 2 AI 原生层：对话→待办提炼、AI 每日简报、周回顾、LLM 兜底解析。
4. 阶段 3（可选）：项目/专家专属待办、完成热力图、snooze 智能建议。

## 2. 涉及的文件与模块

### 后端

| 文件 | 改动 |
|---|---|
| `backend/data/database.py` | `todos_fts` FTS5 表创建 + 幂等回填；阶段 0 后续迁移新列 |
| `backend/services/todo_service.py` | 重复实例生成、parent_id、FTS 同步与搜索、批量方法、导出 |
| `backend/api/todo_router.py` | `q` 搜索参数、`parent_id` 字段、批量端点、导出端点 |
| `backend/tools/todo_mgmt_tool.py` | `add_todo` / `update_todo` 支持 `parent_id` |
| `backend/tests/{unit,integration}/*todo*` | 覆盖新增行为 |

### 前端

| 文件 | 改动 |
|---|---|
| `src/shared/api/todoClient.ts` / `types.ts` | `q`/`parent_id`/批量/导出客户端方法 |
| `src/entities/todo/todoStore.ts` | 批量方法、搜索参数透传 |
| `src/pages/TodoPage.tsx` | 后端搜索、批量走新端点、导出按钮、子任务创建入口 |
| `src/pages/todo/TodoToolbar.tsx` | 搜索改后端（防抖） |
| `src/pages/todo/TodoRowEditor.tsx` | 行内「添加子任务」 |
| `src/pages/__tests__/TodoPage.test.tsx` 等 | 覆盖新增行为 |

## 3. 技术方案

### 3.1 重复任务落地

`TodoService.complete_todo` 完成时若 `is_recurring` 且 `recurrence_rule` 存在：

- 用 APScheduler `CronTrigger.from_crontab(rule)` 计算下一次触发时间；
- 以原行字段（title/description/priority/project_tag/parent_id/recurrence_rule）
  创建新实例，`due_at` = 下一次触发时间，`status='pending'`；
- cron 非法/计算失败 → 记录 warning，跳过生成，**不影响本次完成操作**（fail-open）；
- 无 `due_at` 的循环待办以 `now` 为基准计算。

### 3.2 子任务打通

- `CreateTodoIn` / `UpdateTodoIn` 增加 `parent_id: Optional[int]`；
- `TodoService.create_todo` 接受 `parent_id`；`_UPDATABLE_FIELDS` 加入
  `parent_id`（显式 `None` 清除父子关系，FK 已 `ON DELETE SET NULL`）；
- 校验：父行必须存在；`parent_id != 自身 id`；父行必须是顶层（最大两级）；
- agent 工具 schema 同步增加 `parent_id`；
- 前端行内「＋子任务」内联输入（仅顶层行展示），创建后刷新列表。

### 3.3 后端全文搜索（FTS5）

复用记忆子系统的成熟模式（独立存内容 FTS5 表 + jieba 分词 + Python 侧显式同步，
不用触发器——external-content 模式曾导致 malformed，禁止重蹈覆辙）：

- `todos_fts USING fts5(title, description)`，写入时 jieba `cut_for_search` 分词；
- 服务层在 create / update（title/description 变化时）/ delete 三个入口显式同步；
- 启动时幂等回填：FTS 行数 ≠ todos 行数时全量重建；
- `GET /todos?q=...`：`id IN (SELECT rowid FROM todos_fts WHERE todos_fts MATCH ?)`，
  继续叠加状态/优先级/项目过滤；FTS 不可用（构建缺失/损坏）→ LIKE 降级；
- 查询侧分词用精确模式（memory 的 `tokenize_for_search` 同款），多 token 以
  空格连接（FTS5 隐式 AND）。

### 3.4 批量端点

- `POST /todos/batch/complete` body `{ids: [int]}` → `{completed, missing}`；
- `POST /todos/batch/delete` body `{ids: [int]}` → `{deleted}`；
- 服务层单事务执行；`ids` 非空、上限 500；
- 前端批量操作由串行 N 请求改为单请求。

### 3.5 导出

- `GET /todos/export?format=json|md&include_completed=true|false`
  → JSON envelope `{filename, format, content}`（IPC 管道统一 `res.json()`，
  渲染层组装 Blob 触发下载；与初版"HTTP attachment"的差异：Electron IPC
  无法透传二进制/文件头，envelope 方案对本地桌面端等价且更简单）；
- JSON：`TodoOut` 数组；Markdown：带复选框与元数据的清单；
- 前端 PageHeader 增加导出按钮，Blob 下载。

> 实现备注：`todo_service.py` 触达 800 行架构棘轮上限后，未豁免而是按
> 单一职责拆出 `backend/services/todo_fts.py`（FTS 同步/搜索）、
> `todo_export.py`（导出）、`todo_recurrence.py`（循环实例），
> 服务层保留委托与业务规则；测试同步拆出 `test_todo_service_phase0.py`。

### 3.6 兼容约束

- release/win7：Python 3.8 + pydantic 1.x —— 禁用 PEP 604（`X | None`）、
  PEP 585（`list[int]`），使用 `Optional[...]` / `List[...]`；
- 新增依赖：无（jieba、APScheduler 均为项目既有依赖）；
- 迁移全部走幂等 `CREATE TABLE IF NOT EXISTS` / `ALTER TABLE` 模式。

## 4. 实施步骤（阶段 0）

- [x] 步骤 0.1：`todos_fts` 表创建 + 幂等回填（database.py）
- [x] 步骤 0.2：TodoService 搜索（`todo_fts.match_ids`）+ create/update/delete FTS 同步 + LIKE 降级
- [x] 步骤 0.3：`q` 参数接入 list/count + API 测试
- [x] 步骤 0.4：重复任务生成（complete 时建下一实例）+ 单测
- [x] 步骤 0.5：`parent_id` 打通（API/服务/工具/校验）+ 单测
- [x] 步骤 0.6：批量端点 + 前端切换 + 测试
- [x] 步骤 0.7：导出端点 + 前端按钮 + 测试
- [x] 步骤 0.8：前端搜索改后端（防抖）+ 子任务创建入口 + vitest
- [x] 步骤 0.9：pytest / vitest / ruff / py38 兼容检查全绿，提交 PR

### 阶段 1（后续 PR）

- [x] 命令面板快速录入 + 应用内快捷键（N / ⌘命令面板「快速添加待办」/ `?quickadd=1`）
- [x] 本地中文自然语言解析（日期/时间/优先级/标签）与预览确认（`parseQuickTodo`，纯规则无 LLM）
- [x] `tags` 多标签字段与筛选（JSON 数组列 + `/todos/tags` 聚合 + 工具栏标签下拉；渲染层行内 chips）
- [x] 智能视图：今天 / 近 7 天 / 全部 / 已完成（后端 `view` 参数，`todo_filters.py` 单一真相源）
- [x] 自定义提醒档位（`reminder_offsets` 分钟数组 + `reminder_fired_offsets` 书签 + 调度器按档位扫描；创建表单多选 chips、行内铃铛计数）
- [x] ASR 语音录入（`POST /api/v1/asr/transcribe`：base64 音频 → 临时文件 → `ASRCapability`；快速录入弹窗麦克风录音 60s 上限，未配置 ASR 返回 409）

### 阶段 2（后续 PR）

- [ ] 对话→待办提炼（选中消息/会话 → LLM structured output → 确认弹窗 → 批量创建 + `source_type`/`source_ref` 反向链接）
- [ ] LLM 兜底 NL 解析（设置开关）
- [ ] AI 每日简报（启动摘要 + LLM 三条重点建议，走既有通知通道）
- [ ] 周回顾（定时任务生成摘要页/Tab）

### 阶段 3（可选，按需再议）

- [ ] 项目/专家专属待办
- [ ] 完成热力图
- [ ] snooze 行为统计与智能建议

## 5. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| FTS5 在旧版 SQLite 不可用或损坏 | 搜索不可用 | 启动探测 + LIKE 降级（memory 同款策略） |
| cron 规则非法导致完成操作失败 | 核心动作被阻 | fail-open：仅跳过实例生成并告警 |
| 子任务层级失控 | UI 递归/数据环 | 限制两级 + 自引用校验 + FK SET NULL |
| LLM 提炼误建待办（阶段 2） | 数据脏 | 候选清单强制用户确认后才落库 |
| 双分支漂移 | win7/main 行为不一致 | 阶段 0 完成后按项目惯例 cherry-pick main |

## 6. 验收标准（阶段 0）

1. `pytest backend/tests/unit/test_todo_service.py backend/tests/unit/test_todo_mgmt_tool.py backend/tests/integration/test_todo_api.py` 全绿（sage-backend-py38）；
2. `npx vitest run src/pages/__tests__/TodoPage.test.tsx src/entities/todo` 全绿；
3. `ruff check backend` 无新增违规；
4. 重复待办完成后自动出现下一实例；子任务可由 UI/API/工具创建；
5. 搜索命中标题或描述中的中文关键词；导出 JSON/Markdown 可下载。

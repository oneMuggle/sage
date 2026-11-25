# 158 — 项目健康监控与 AI 辅助规程定制

> 2026-11-14 M1–M3：主动告警推送 / 对话式规程定制 / 定时健康检查
> 2026-11-15 M4：项目健康看板 UI 打磨（纯前端）

## 背景

- 述职报告中描述了 Sage 的项目管理能力：项目纳管、进度监控与提醒、四类参考模板、5 层级 + 34 阶段。
- 原有 `ProjectAdvisor` 已支持逾期检测，但缺少主动推送；`PlaybookAuthorPanel` 只能一次性生成；
  定时健康检查也未真正挂到调度器。
- 用户需求：除了预定义的 4 类模板，**让用户用 AI 对话式地定义项目阶段**，以适配实际项目管理需要。

本里程碑分三期落地：**M1 主动告警**、**M2 对话式规程定制**、**M3 定时健康检查**。

---

## M1：主动告警推送

### 后端

**新增 `backend/services/project_health_monitor.py`**

| 符号 | 用途 |
|------|------|
| `SEVERITY_OK / WARNING / CRITICAL` | 严重度常量 |
| `CRITICAL_OVERDUE_DAYS = 7` | 逾期 ≥ 7 天升级至 critical |
| `NOTIFY_INTERVAL_SECONDS = 86400` | 同项目 + 同严重度 24 小时节流 |
| `ProjectHealthNotificationQueue` | 内存队列 + SQLite `project_health_notifications`（`push`/`pending`/`ack`） |
| `ProjectHealthMonitor` | `scan_all(limit)` 扫描活跃项目；`push_alerts(summaries)` 节流推送；`summarize(project_id)` 单项目摘要 |
| `ProjectHealthSummary` | dataclass，`to_dict()` 返回 `{project_id, project_name, severity, total_milestones, ..., overdue:[OverdueMilestone]}` |
| `reset_throttle()` | 仅测试用，清空节流缓存 |

**修改 `backend/api/project_routes.py`**

- `GET /api/v1/projects/health-check` → `listProjectsHealth` → 返回 `{checked, severities, summaries}`
- `POST /api/v1/projects/{project_id}/health-check` → `checkProjectHealth` → 触发单项目扫描并推一条桌面通知

### 前端

- **新增 `src/pages/governance/sections/HealthSummaryCard.tsx`**：单项目健康卡（按严重度变色，逾期条目红色）。
- 在 `OverviewSection.tsx:363` 以 `<HealthSummaryCard projectId={project.id} />` 形式挂载。
- **新增类型**：`ProjectHealthSummary`、`ProjectsHealthCheckResult`、`OverdueMilestone`（`projectApiTypes.ts`）。
- **新增 API 方法**：`projectApi.checkProjectHealth()`、`projectApi.listProjectsHealth()`。

### Electron 桌面通知

- `electron/main.ts` 注册 IPC `projects_health_check` / `projects_list_health_check` → 路由到 `project_health_monitor`；
  推送桌面通知（`Notification`），标题 `项目风险提醒`，body 含逾期天数。

---

## M2：对话式规程定制

### 后端

| 模块 | 关键职责 |
|------|----------|
| `backend/data/playbook_author_conversation_repo.py` | `PlaybookAuthorConversationRepository`（`get/save/update`）；`playbook_author_conversations` 表 |
| `backend/data/migrations.py`（新增 v14 迁移） | 建 `playbook_author_conversations(id TEXT PK, project_id TEXT, messages_json TEXT, current_spec_json TEXT, status TEXT, created_at, updated_at)` |
| `backend/services/playbook_conversation_author.py` | `PlaybookConversationAuthor`：`start(project) / send_message / rollback / commit`；`MAX_TURNS=10`；种子 `reference_draft()`；`deterministic_update()` 处理中期检查/延期/结题等关键词 |
| `backend/services/playbook_inference.py` | `infer_from_directory()`、`infer_from_git_history()`、`infer_project_stages()`、`inferred_spec()`；编号目录匹配 + git 关键词分桶 |

**数据形状**（合成）

```jsonc
// playbook_author_conversations.messages_json
[{"role": "assistant", "content": "已根据项目生成草案…", "turn_index": 0,
  "playbook_snapshot": <PlaybookSpec | null>, "created_at": 1763100000000}]

// PlaybookSpec（草案）
{"schema_version": "1.0", "id": "inferred-proj-1", "name": "示例课题 规程（推断）",
 "applies_to": {"project_types": ["research"], "sub_types": []},
 "stages": [{"id": "stage-1", "label": "开题", "order": 1,
             "artifacts": [{"id": "proposal", "label": "开题报告", "required": true,
                            "match": {"globs": ["**/开题报告*"], "min_bytes": 0, "min_count": 1}}]}],
 ...}
```

### 前端

- **新增 `src/features/playbook/PlaybookConversationAuthor.tsx`**：侧栏对话式面板
  - 展开 → 启动对话 → 显示种子草案
  - 输入框 → 多轮迭代（LLM 不可用时降级为规则草案）
  - 「撤销上一步」「确认绑定」「从项目目录推断」三个按钮
  - 推断结果需用户点击「绑定推断结果」才生效，不自动绑定

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/v1/playbook/author/{project_id}/conversation` | 开始新对话 |
| POST | `/api/v1/playbook/author/{project_id}/conversation/{cid}/message` | 发送消息 |
| POST | `/api/v1/playbook/author/{project_id}/conversation/{cid}/rollback` | 回退一轮 |
| POST | `/api/v1/playbook/author/{project_id}/conversation/{cid}/commit` | 提交绑定 |
| POST | `/api/v1/playbook/author/{project_id}/infer` | 从目录/git 推断 |
| POST | `/api/v1/playbook/author/{project_id}/bind-inferred` | 绑定推断结果 |

---

## M3：定时健康检查

### 后端

**新增 `backend/services/project_health_scheduler.py`**

```python
class ProjectHealthScheduler:
    def check_all_projects(self) -> HealthReport  # scan_all + push_alerts + 汇总
    def run_check(self) -> dict                    # sync 回调，失败返回 {"error": True}
    def register_to_scheduler(scheduler_service, cron_expr=DEFAULT_CRON)
    def latest_report(self) -> Optional[HealthReport]
```

- `DEFAULT_CRON = "0 9 * * *"`（每天 09:00）
- `TASK_NAME = "project_health_check"`
- Python 3.8 兼容：使用 `from __future__ import annotations` 与 `typing.Dict/List/Optional`

**修改 `backend/main.py` `_deferred_startup_init()`**

```python
# ── 项目健康定时检查（每天 09:00） ──
try:
    from backend.services.project_health_scheduler import get_project_health_scheduler
    get_project_health_scheduler().register_to_scheduler(scheduler_service)
except Exception:
    logger.exception("project health scheduler registration failed (ignored)")
```

### 前端

- **新增 `src/features/project-health/HealthDashboard.tsx`**：全局项目健康看板
  - 顶部：风险/关注/正常计数 + 重新检查按钮
  - 中部：4 个风险等级过滤按钮（全部/风险/关注/正常）
  - 下部：项目列表（按严重度圆点 + 名称 + 阶段 + 里程碑进度 + 逾期数）
  - 空态 / 错误态 / 无匹配提示三态完备
- **挂载点**：`src/pages/ProjectsOverview.tsx` 搜索栏下方、项目列表上方

> 2026-11-15 M4 对看板做了视觉升级（3 张指标卡 / 按严重度分组 / 逾期徽标），最终形态以下节为准。

---

## M4：项目健康看板 UI 打磨（2026-11-15）

> 纯前端改造：不改后端 API、请求/响应类型与路由；严重度与逾期仍由 `ProjectHealthMonitor` 判定。

### 共享 severity token

**新增 `src/shared/lib/healthSeverity.tsx`**：把严重度 → 图标 / 颜色 / 文案收敛为共享常量，`HealthDashboard` 与 `HealthSummaryCard` 共用同一套。

| `severity` | `label` | `stateLabel` | 图标（lucide） | 圆点 / 文字色 | 卡片底 / 描边 | 逾期徽标 |
|---|---|---|---|---|---|---|
| `critical` | 风险 | 存在风险 | `AlertTriangle` | `bg-rose-500` / `text-rose-500` | `bg-rose-500/10` / `border-rose-500/25` | `bg-rose-500/15 text-rose-500` |
| `warning` | 关注 | 需要关注 | `AlertCircle` | `bg-amber-500` / `text-amber-500` | `bg-amber-500/10` / `border-amber-500/25` | `bg-amber-500/15 text-amber-500` |
| `ok` | 正常 | 一切正常 | `CheckCircle2` | `bg-emerald-500` / `text-emerald-500` | `bg-emerald-500/10` / `border-emerald-500/25` | `bg-emerald-500/15 text-emerald-500` |

- `SEVERITY_ORDER = ['critical', 'warning', 'ok']`：指标卡与分组列表都按风险优先排列。
- 配色注意：rose / amber / emerald 取自 Tailwind 默认调色板（`tailwind.config.js` 未覆盖这三档），**不随主题或暗色模式变化**；其余样式使用语义 token（`border-border`、`bg-ui-card`、`text-text`、`text-text-muted`、`bg-bg-muted`、`bg-bg-hover`、`text-primary`、`text-text-inverse`）。

### 三张指标卡

`HealthDashboard` 顶部把原先的纯文本统计换成 3 张等宽指标卡（`grid grid-cols-3`），顺序固定为 风险 → 关注 → 正常。

| 指标卡 | 指标名 | 数值含义（单位） | 取值来源 | 颜色语义 |
|---|---|---|---|---|
| `critical` | 风险 | 严重度为 critical 的**项目数**（个） | `ProjectsHealthCheckResult.severities.critical` | 玫红 `rose-500` + `AlertTriangle` |
| `warning` | 关注 | 严重度为 warning 的**项目数**（个） | `severities.warning` | 琥珀 `amber-500` + `AlertCircle` |
| `ok` | 正常 | 严重度为 ok 的**项目数**（个） | `severities.ok` | 翠绿 `emerald-500` + `CheckCircle2` |

- `severities` 由 `GET /api/v1/projects/health-check`（`list_projects_health`）一次性聚合，**不随筛选器变化**——切到「风险」筛选后三张卡仍显示全量计数。
- 卡片结构：左侧图标（16px），右侧上方为大号数字（`text-lg font-semibold tabular-nums`），下方为等级名（`text-ui-2xs text-text-muted`）；卡片本身带对应等级的浅色底与描边。
- 无障碍：另有一份 `sr-only` 文本「风险 X · 关注 Y · 正常 Z」供读屏器读取。

### 按严重度分组

- 分组只发生在渲染层，数据仍是后端按 `(严重度等级, 逾期条数降序)` 排好的 `summaries` 数组。
- `filter === 'all'` 时按 `SEVERITY_ORDER` 分成 风险 / 关注 / 正常 三组，**空组不渲染**。
- 组标题（圆点 + 组名 + 项目数）**仅在「全部」视图且存在 ≥ 2 个非空组时显示**；选中单个等级筛选时列表直接平铺，不显示组标题。
- 每条项目行：严重度圆点 + 项目名（超长截断）+ 阶段标签（`project_stage` 非空时）+ `已完成/总数 里程碑`，右侧再跟逾期徽标或状态词；行 hover 时出现描边与背景高亮（`transition-colors`）。

### 逾期徽标

- **判定**（后端 `ProjectHealthMonitor.summarize`）：里程碑 `due_date` 非空、`status != "completed"`、日期可解析，且 `due_date` 早于今天 → 计入逾期，`days_overdue = 今天 - due_date`；逾期条目按天数降序存入 `summary.overdue`。
- **看板行内徽标**：`summary.overdue.length > 0` 时显示「逾期 N 项」（N = 逾期里程碑条数），样式为圆角胶囊（`rounded-full px-2 py-0.5 font-medium`）。
- **颜色固定用 critical 色板**（`bg-rose-500/15 text-rose-500`），与项目自身严重度无关——关注级项目只要存在逾期，徽标同样为玫红。
- 无逾期时，徽标位置改显该等级的 `stateLabel`（存在风险 / 需要关注 / 一切正常），文字色随等级。

### 严重度判定规则

`ProjectHealthMonitor.summarize` 的判定顺序（自上而下，命中即停）：

| 条件 | 严重度 |
|---|---|
| 最久逾期里程碑 ≥ `CRITICAL_OVERDUE_DAYS`（= 7）天 | `critical`（风险） |
| 存在逾期（1~6 天）**或**存在 `blocked` 状态的里程碑 | `warning`（关注） |
| 既无逾期也无阻塞 | `ok`（正常） |

- 扫描范围：`scan_all(limit=100)` 仅取 `status == "active"` 的项目；结果按严重度等级、再按逾期条数降序返回。
- 因此「关注」不一定有逾期：仅里程碑阻塞、没有任何逾期时同样判为 warning。

### 交互与状态

| 状态 | 表现 |
|---|---|
| 首次加载 | 列表位置显示 3 行骨架占位（`h-9 animate-pulse rounded-md bg-bg-muted/60`）；「重新检查」按钮文案为「检查中…」且图标旋转 |
| 刷新（已有数据） | 保留现有行，仅「重新检查」按钮禁用并显示「检查中…」 |
| 空态 | 「暂无活跃项目需要检查。」 |
| 错误态 | 「健康检查失败：<错误信息>」（玫红文字） |
| 筛选无匹配 | 「没有符合该风险等级的项目。」 |
| 筛选器 | 4 个胶囊按钮：全部 / 风险 / 关注 / 正常；选中态 `bg-primary text-text-inverse`，带 `transition-colors` 与 `aria-pressed` |
| 刷新 | 「重新检查」重新调用 `listProjectsHealth()`；该接口只读、不推通知 |

### 单项目健康卡增强（HealthSummaryCard）

- 卡片按 `summary.severity` 取共享 token 上色；标题栏图标随等级切换（`AlertTriangle` / `AlertCircle` / `CheckCircle2`），右侧显示 `stateLabel`。
- 新增里程碑进度条：`completed_milestones / total_milestones` 换算百分比（`Math.round`），`total_milestones === 0` 时不渲染。
- 非 ok 且存在逾期时，最多列出 3 条「里程碑标题 + 逾期 N 天」胶囊；超过 3 条追加「…还有 N 项」（N = `overdue.length - 3`）。
- 非 ok 但无逾期（即阻塞导致）时，显示「有 N 个里程碑处于阻塞状态」+ `AlertTriangle`。
- ok 时显示「所有里程碑进度正常」+ `CheckCircle2`。
- 数据来源仍是 `POST /api/v1/projects/{project_id}/health-check`。

### 顾问卡视觉对齐（ProjectAdvisorCard）

同一轮把 `ProjectAdvisorCard` 的按钮从描边样式改为无边框 / 胶囊（`rounded-full`）样式，统一 hover 态，并把健康分数与严重度配色对齐到 emerald / amber / orange / rose。**按钮集合与交互结构保持不变**（未改为下拉菜单）。

### 相关 UI 测试

| 文件 | 覆盖点 |
|---|---|
| `src/features/project-health/__tests__/HealthDashboard.test.tsx` | 指标卡计数与项目行、按等级筛选、空态 / 无匹配 / 错误态、重新检查 |
| `src/pages/governance/__tests__/HealthSummaryCard.test.tsx` | ok 态、逾期列表、「…还有 N 项」折叠、阻塞提示、错误态、切换项目重新拉取 |
| `src/features/project-type/__tests__/ProjectAdvisorCard.p190.test.ts` | 顾问卡交互 |

---

## 测试覆盖

| 文件 | 测试数 |
|------|--------|
| `backend/tests/unit/test_project_health_monitor.py` | 20 |
| `backend/tests/unit/test_project_health_scheduler.py` | 8 |
| `backend/tests/unit/test_playbook_conversation_author.py` | 11 |
| `backend/tests/unit/test_playbook_inference.py` | 8 |
| `src/features/playbook/__tests__/PlaybookConversationAuthor.test.tsx` | 6 |
| `src/features/project-health/__tests__/HealthDashboard.test.tsx` | 6 |

全部通过：pytest 47 passed / vitest 16 passed / tsc 0 error。

---

## 与双分支的关系

- 本里程碑所有新模块均保持 Python 3.8 兼容（`from __future__ import annotations`、`typing.Dict/List/Optional`、无 PEP 604 联合类型）。
- 后续 cherry-pick 到 `release/win7` 时，仅需适配 pydantic v1（`project_health_monitor.py` 无 pydantic 模型；`playbook_conversation_author.py` 使用纯 dataclass 与 dict）。
- 新表 `playbook_author_conversations` 在 v14 迁移中，win7 分支也使用同一份 `migrations.py`。

---

## 用户手册

见 [`docs/user-manual/51-project-health-ai-stages.md`](../user-manual/51-project-health-ai-stages.md)。

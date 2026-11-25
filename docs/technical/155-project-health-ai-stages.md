# 155 — 项目健康监控与 AI 辅助规程定制

> 2026-11-14 M1–M3：主动告警推送 / 对话式规程定制 / 定时健康检查

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

---

## 看板 UI 形态与严重度判定（2026-11-15 UI 美化）

> 纯前端视觉改造，后端 API、类型定义、路由均未变更。看板数据仍来自
> `GET /api/v1/projects/health-check`（只读，不推通知，最多扫描 100 个活跃项目）。

### 共享严重度 token

**`src/shared/lib/healthSeverity.tsx`** 提供 `SEVERITY_TOKENS` 与 `SEVERITY_ORDER`，
`HealthDashboard` 与 `HealthSummaryCard` 共用；`ProjectAdvisorCard` 未直接引用该常量，
但调色板与之一致。

| severity | label | stateLabel | Icon（lucide） | dot / text | softBg | border | badge |
|----------|-------|-----------|----------------|------------|--------|--------|-------|
| `critical` | 风险 | 存在风险 | `AlertTriangle` | `bg-rose-500` / `text-rose-500` | `bg-rose-500/10` | `border-rose-500/25` | `bg-rose-500/15 text-rose-500` |
| `warning` | 关注 | 需要关注 | `AlertCircle` | `bg-amber-500` / `text-amber-500` | `bg-amber-500/10` | `border-amber-500/25` | `bg-amber-500/15 text-amber-500` |
| `ok` | 正常 | 一切正常 | `CheckCircle2` | `bg-emerald-500` / `text-emerald-500` | `bg-emerald-500/10` | `border-emerald-500/25` | `bg-emerald-500/15 text-emerald-500` |

`SEVERITY_ORDER = ['critical', 'warning', 'ok']`。颜色直接使用 Tailwind 调色板类
（rose / amber / emerald），未使用项目语义 token（`--color-error` / `--color-warning`
/ `--color-success`）。

### 三张指标卡

- 看板头部：`HeartPulse` 图标 + 标题「项目健康」+ 右侧「重新检查」按钮（加载中显示
  「检查中…」并让 `RefreshCw` 旋转）。
- 下方 `grid grid-cols-3` 渲染三张指标卡，顺序固定为 **风险 → 关注 → 正常**
  （`SEVERITY_ORDER`）。每张卡包含：该等级图标、大号计数（`text-lg font-semibold
  tabular-nums`）、等级名（`text-ui-2xs text-text-muted`），背景/边框/文字取对应 token 的
  `softBg` / `border` / `text`。
- **计数来源是后端返回的 `severities` 字段**（对本次扫描到的全部活跃项目按等级聚合），
  不是前端对列表做 `filter` 后的长度。因此切换筛选按钮不会改变三张卡的数字。
- 另有一段 `sr-only` 文本「风险 X · 关注 Y · 正常 Z」供读屏使用。

### 按严重度分组

- 先按当前筛选（`all` / 单个等级）过滤，再按 `SEVERITY_ORDER` 分桶并丢弃空组，
  因此列表顺序恒为 风险组 → 关注组 → 正常组。组内沿用后端返回顺序
  （`scan_all` 先按严重度 critical → warning → ok，同等级内逾期条数多的在前）。
- **组标题只在筛选为「全部」且存在多于一个非空组时渲染**：组名 + 淡色数量
  `(n)`，前缀为对应颜色的圆点。单选某个等级、或全部项目同属一个等级时不显示组标题。
- 每行：严重度圆点 + 项目名（超长截断）+ 可选阶段 chip（`bg-bg-muted`）；右侧为
  「已完成/总数 里程碑」（`tabular-nums`），以及逾期徽标或状态句。行悬停时加
  `hover:border-border hover:bg-bg-hover` 与 `transition-colors`。

### 逾期徽标

- 判定：`summary.overdue.length > 0` 时，行右侧渲染圆角徽标，文案为
  **「逾期 N 项」**（N = 逾期里程碑条数），样式固定取 `critical` 的
  `badge`（`bg-rose-500/15 text-rose-500`，`rounded-full`）。
- 该徽标**始终用 critical 红色系**，不随所在行的严重度变化（即便行本身是关注级）。
- 无逾期时，右侧改显当前等级的 `stateLabel`（存在风险 / 需要关注 / 一切正常），
  并取该等级文字色。

### 严重度与「逾期」的判定规则（后端 `ProjectHealthMonitor.summarize`）

- **逾期判定**：里程碑有可解析为 `YYYY-MM-DD` 的 `due_date`、状态不为 `completed`，
  且 `today - due_date > 0` 才算逾期；当天到期（差值为 0）不算。`days_overdue`
  即该差值，逾期列表按天数降序排列。
- **严重度判定**（`max_overdue` = 最长逾期天数）：
  - `max_overdue >= CRITICAL_OVERDUE_DAYS`（7 天）→ `critical`（风险）
  - 否则只要存在任一逾期或存在 `blocked` 里程碑 → `warning`（关注）
  - 否则 → `ok`（正常）
- 因此单有阻塞里程碑（无逾期）只会落到「关注」，不会升级为「风险」。

### 单项目健康卡（`HealthSummaryCard`）

- 卡片边框/底色取严重度 token，标题图标取该等级的 `Icon`，右上角显示 `stateLabel`
  （加载中为「检查中…」）。
- `total_milestones > 0` 时显示「里程碑进度」进度条与「已完成/总数 · 百分比」。
- 非 `ok` 且存在逾期时，最多列出前 3 条逾期里程碑，每条带「逾期 N 天」红色 pill；
  超出部分折叠为「…还有 N 项」。
- 非 `ok` 但无逾期时，显示 `AlertTriangle` +「有 N 个里程碑处于阻塞状态」。
- `ok` 时显示 `CheckCircle2` +「所有里程碑进度正常」。

### 列表状态

- 加载中：3 行 `animate-pulse` 骨架占位 + `sr-only`「正在检查项目健康状态…」。
- 无活跃项目：「暂无活跃项目需要检查。」
- 筛选无匹配：「没有符合该风险等级的项目。」
- 请求失败：「健康检查失败：<错误信息>」。

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

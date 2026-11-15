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

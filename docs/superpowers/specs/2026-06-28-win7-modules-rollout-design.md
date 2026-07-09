---
name: win7-modules-rollout
description: win7 同步 main 缺失的 9 大模块实施总览 spec（i18n→主题编辑器→Scheduler→Orchestration→Sider DnD→Welcome→Nav-history→/btw→Phase5 titlebar）
metadata:
  type: spec
  status: design
  author: brainstorm-session-2026-06-28
  related_specs:
    - 2026-06-25-aionui-inspired-ui-design.md
  related_plans:
    - 2026-06-28-win7-sync-phase9.md
---

# win7 Modules Rollout Design Spec

## 1. Goal

让 `release/win7` 分支与 `main` 在用户感知的功能能力上**完全对齐** — 当前 main 独有的 9 大模块（i18n、主题编辑器、Scheduler、Orchestration、Sider DnD、Welcome、Nav-history、/btw、Phase5 titlebar）全部在 win7 上以**与 main 一致的接口和 UX** 实现。差异收敛到零（结构性基础设施层面），保持 win7 LTS 维护路径独立。

## 2. Win7 上下文

### 2.1 双分支架构（CLAUDE.md 强制）
- `release/win7`：**LTS 分支**，服务 Win7 SP1 用户到 2027-12-13
- `main`：主开发分支
- 双分支**不合并**，仅 cherry-pick 安全补丁和关键 bug 修复
- win7 后端：Python 3.8 + pydantic 1.x（与 main 的 3.11 + pydantic 2.x 独立）
- win7 electron：21.4.4（locked for Win7 兼容）

### 2.2 win7 现有能力（基线快照，2026-06-28）
- **前端框架**：React 18.2 + Vite + TypeScript ✅
- **状态管理**：Zustand 4.4.7 ✅
- **路由**：react-router-dom 6.20 ✅
- **DnD 依赖**：@dnd-kit/{core, sortable, utilities} ✅（已装）
- **后端框架**：FastAPI 0.85 + uvicorn + SQLAlchemy + SQLite ✅
- **后端架构**：hexagonal（adapters / ports / application / domain）✅
- **orchestration 目录骨架**：`backend/orchestration/` 存在但为空
- **后端服务**：`backend/services/` 空

### 2.3 win7 主要缺失能力（main 有 win7 没有）
9 大模块，共约 200+ main 独有文件（其中 126 前端、80+ 后端）

### 2.4 为什么需要这个 spec
- 之前 sync（phase 1-9）只 cherry-pick 了**正交修复**和**纯构建/CI 改进**
- 9 大模块涉及**架构层面**新基础设施（i18n、状态机、IPC 桥）
- 必须先 spec 再 plan 再实现，避免重做

## 3. 与 main 的差异

| 模块 | main 实现 | win7 取舍 | 偏差点 |
|---|---|---|---|
| **i18n** | react-i18next + i18next-browser-languagedetector | **自研** React Context + JSON 字典 + Zustand | 不引入 i18next 依赖；接口形状对齐 |
| **主题编辑器** | CodeMirror 6 + themeCssValidator + atomic JSON | 同 main，加 py3.8 适配 | 同 |
| **Scheduler** | APScheduler 3.10.4 + scheduled_router | 同 main | py3.8 验证 |
| **Orchestration** | 22 文件 orchestration 包 + DB tables + Router | 同 main，**全部重写** | pydantic 1.x model 适配 |
| **Sider DnD** | @dnd-kit + useSiderSections + 持久化 | 同 main | 同 |
| **Welcome** | Hero + InputCard + QuickActionBar | 同 main | i18n 适配 |
| **Nav-history** | NavHistoryProvider + useNavigationHistory | 同 main | 同 |
| **/btw** | BtwState + useBtwCommand + AtFileMenu | 同 main | i18n 适配 |
| **Phase5 titlebar** | WindowControls + IPC + 跨平台 | 同 main | electron 21.4.4 兼容验证 |

**核心原则**：以 main 为**参照**，但代码用 win7 idioms 写（不复用 main 库）。

## 4. 接口契约（全局）

### 4.1 通用约定

```typescript
// src/shared/types/i18n.ts
export type Locale = 'zh-CN' | 'en-US';
export interface I18nContextValue {
  locale: Locale;
  setLocale: (l: Locale) => void;
  t: (key: string, params?: Record<string, string | number>) => string;
}
```

```python
# backend/api/v1/schemas.py (新文件)
from pydantic import BaseModel, Field  # pydantic 1.x 语法

class ApiResponse(BaseModel):
    success: bool
    data: Optional[Any] = None
    error: Optional[str] = None
```

### 4.2 错误处理模式

```typescript
// 前端：所有 IPC 调用必须 narrow error
const result = await window.electronAPI.theme.save(payload);
if (!result.success) {
  setError(result.error);
  return;
}
```

```python
# 后端：所有 routes 返回统一 envelope
@router.get("/list", response_model=ApiResponse[List[Theme]])
async def list_themes() -> ApiResponse:
    try:
        themes = theme_storage.load_themes()
        return ApiResponse(success=True, data=themes)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"themes.json read failed: {e}")
```

## 5. 组件清单（按模块分组）

### 5.1 Module 1: i18n framework
- `src/shared/lib/i18n/I18nProvider.tsx` — Provider 组件
- `src/shared/lib/i18n/useI18n.ts` — hook
- `src/shared/lib/i18n/formatMessage.ts` — 格式化函数
- `src/shared/lib/i18n/__tests__/{I18nProvider,useI18n,formatMessage}.test.tsx` — 单测
- `src/shared/i18n/zh-CN.json` — 中文
- `src/shared/i18n/en-US.json` — 英文
- `src/entities/i18n/store.ts` — Zustand locale store
- `src/shared/types/i18n.ts` — 类型

### 5.2 Module 2: 主题编辑器
- `backend/services/theme_storage.py` — atomic JSON 存储
- `backend/api/theme_router.py` — REST endpoints（/list /save /get/{id} /delete/{id}）
- `src/widgets/theme/ThemeProvider.tsx`
- `src/widgets/theme/CssThemeModal.tsx`
- `src/widgets/theme/CodeMirrorThemeEditor.tsx`
- `src/widgets/theme/ThemeSelector.tsx`
- `src/widgets/theme/ThemeGallery.tsx`
- `src/widgets/theme/backgroundInjector.ts` — CSS vars 注入
- `src/shared/api-client/themeCssClient.ts` — IPC client
- `electron/preload.ts` — 暴露 theme API
- `electron/main.ts` — 注册 IPC handlers
- `package.json` — 加 CodeMirror 依赖（py3.8 验证 + main 同款）

### 5.3 Module 3: Scheduler
- `backend/services/scheduler.py` — APScheduler 包装
- `backend/api/scheduled_router.py`
- `backend/data/scheduled_tasks.json` — 持久化（gitkeep）
- `backend/requirements.txt` — 加 APScheduler==3.10.4
- `src/widgets/scheduled/CronExpressionPicker.tsx`
- `src/widgets/scheduled/CreateTaskModal.tsx`
- `src/widgets/scheduled/ScheduledList.tsx`
- `src/entities/scheduled/taskStore.ts` — Zustand
- `src/shared/api-client/scheduledClient.ts`
- `src/pages/Scheduled.tsx` — 路由

### 5.4 Module 4: Orchestration
- `backend/orchestration/{models,planner,router,executor,heartbeat,lane_board,permission,ultragoal_store,policy_engine,approval_tokens,events,registry}.py`
- `backend/api/orchestration_router.py`
- `backend/data/database.py` — 加 4 张 orchestration 表 + 索引
- `src/pages/Orchestration.tsx`
- `src/widgets/orchestration/{Board,Lane,Task,Agent}.tsx`
- `src/entities/orchestration/{boardStore,teamRegistry}.ts`

### 5.5 Module 5: Sider DnD
- `src/widgets/sidebar/SiderSection.tsx`
- `src/widgets/sidebar/ConversationsSection.tsx`
- `src/widgets/sidebar/SortableSessionList.tsx`
- `src/widgets/sidebar/SortableSessionItem.tsx`
- `src/widgets/sidebar/siderOrder.ts` — 纯函数 + 26 单测
- `src/features/sidebar/useSiderSections.ts`
- `src/features/sidebar/useStoredSiderOrder.ts`

### 5.6 Module 6: Welcome
- `src/pages/Welcome.tsx`
- `src/widgets/welcome/{WelcomeHero,WelcomeInputCard,QuickActionBar,AssistantRecommendations}.tsx`
- `src/features/welcome/useTypewriterPlaceholder.ts`
- `src/entities/welcome/recommendations.ts` — mock data

### 5.7 Module 7: Nav-history
- `src/features/nav-history/NavHistoryProvider.tsx`
- `src/features/nav-history/useNavigationHistory.ts`
- `src/widgets/layout/TitlebarActions.tsx`
- `src/app/AppProviders.tsx` — 集成

### 5.8 Module 8: /btw
- `src/features/chat/BtwState.ts` — Zustand
- `src/features/chat/useBtwCommand.ts`
- `src/features/chat/useAtFileQuery.ts`
- `src/widgets/chat/BtwOverlay.tsx`
- `src/widgets/chat/AtFileMenu.tsx`
- `src/shared/api-client/fileSearchClient.ts`

### 5.9 Module 9: Phase5 Titlebar
- `src/widgets/layout/WindowControls.tsx`
- `src/widgets/layout/WindowControlsBridge.ts` — interface
- `src/shared/api-client/windowControlsClient.ts`
- `electron/preload.ts` — 加 windowControls
- `electron/main.ts` — 加 IPC handlers
- `src/entities/layout/platform.ts` — 平台检测

## 6. 数据流（关键场景示例）

### 6.1 用户切换主题

```
User clicks "Ocean" in ThemeGallery
  → ThemeSelector.onSelect({ preset: 'ocean' })
  → ThemeProvider state.theme = 'ocean'
  → backgroundInjector.inject('--color-bg: #...')
    → document.documentElement.style 更新 CSS vars
  → 所有组件因 CSS vars 变化重渲染
  → 异步：themeCssClient.save({ preset: 'ocean' })
    → IPC bridge → main process → backend/api/theme_router.py
    → backend/services/theme_storage.py atomic write to themes.json
```

### 6.2 用户创建定时任务

```
User fills CronExpressionPicker → "0 9 * * *"
  → CreateTaskModal.onSubmit({ cron, name, action: 'chat.send' })
  → scheduledClient.create(payload)
  → IPC bridge → main process → /api/v1/scheduled/tasks (POST)
  → backend/api/scheduled_router.create_task
    → APScheduler.add_job(cron, callback=send_chat_message)
    → backend/data/scheduled_tasks.json atomic write
  → 返回 task_id → taskStore.add(task) → ScheduledList 重渲染
```

### 6.3 Orchestration 5-lane workflow

```
User submits ultragoal on Orchestration page
  → Orchestration.tsx.onSubmit
  → Planner.break_down(ultragoal)
    → TaskRegistry 注册 5 个 task
    → LaneRegistry 分配 5 个 lane（capability-based dispatch）
  → Executor 启动后台 worker
  → HeartbeatMonitor 每 30s 检查 lane 健康
  → LaneBoard 实时更新 lane 状态（active / stalled / completed）
  → 所有 lane 完成 → TeamRegistry.markComplete
```

## 7. 测试策略

### 7.1 单元测试（每个模块）
- 目标覆盖率 ≥80%（与 CLAUDE.md testing.md 一致）
- 前端：vitest，每个组件 + hook + 纯函数
- 后端：pytest，每个 module + 路由 + service

### 7.2 集成测试
- API 端到端测试（pytest + httpx AsyncClient）
- 组件 mount 集成（vitest + Testing Library）

### 7.3 E2E（Playwright）
- 每个模块至少 1 个关键路径
- 总览 E2E 在 week 8 回归：9 模块全部联动

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| APScheduler 3.10 py3.8 兼容问题 | 中 | M3 延期 | spike 1 天；备选 `schedule` 库 |
| Orchestration 22 文件工期低估 | 高 | M4 +1 周 | 用 main 测试文件做模板；提前对齐 pydantic 1.x |
| CodeMirror bundle size | 低 | M2 性能 | lazy import + code splitting |
| @dnd-kit 与 win7 现有 Sider 冲突 | 中 | M5 延期 | spike 1 天；如冲突重写适配层 |
| i18n 自研 vs i18next 偏离 | 低 | 后续 cherry-pick 文档翻译键需适配 | 自研层加 key alias 兼容 |
| Phase5 titlebar macOS 行为差异 | 中 | M9 延期 | spike 跨平台验证 |
| 总工期超 8 周 | 中 | 后续延期 | week 4 review 调整优先级；M4 可拆为 M4a 后端 / M4b 前端 |

## 9. DoD 清单（总览）

- ✅ 9 个模块独立 spec 文件已 commit 到 `docs/superpowers/specs/`
- ✅ 9 个模块独立 plan 文件已 commit 到 `docs/superpowers/plans/`
- ✅ 每个模块在 `feat/win7-<module>` 分支上 CI 绿
- ✅ 9 个模块全部 merge 到 release/win7 + push
- ✅ pre-push hook 通过
- ✅ 用户 review 通过（每个 PR）
- ✅ pytest + vitest 总覆盖率 ≥80%
- ✅ win7 与 main 功能能力 100% 对齐（用户视角）

## 10. 实施步骤预览

### Week 1 — Foundation
- M1: i18n framework（4 天）
- M2: 主题编辑器（3 天，依赖 M1）

### Week 2 — Scheduler
- M3: Scheduler 后端 + 前端（5 天，依赖 M1）

### Week 3-4 — Orchestration
- M4: Orchestration 后端 22 文件（8 天，依赖 M1）
- M4: Orchestration 前端（3 天）

### Week 5 — Sider DnD
- M5: Sider DnD + 集成测试（4 天，依赖 M1）

### Week 6 — Welcome + Nav-history
- M6: Welcome Screen（3 天，依赖 M1+M2）
- M7: Nav-history（2 天，无依赖）

### Week 7 — /btw + Phase5
- M8: /btw Overlay（3 天，依赖 M1）
- M9: Phase5 Titlebar（3 天，依赖 M7）

### Week 8 — 跨模块回归
- Cross-module E2E + Win7 全量回归（2-3 天）

每个模块的详细 plan 在子 spec 中展开。

## 11. 跨模块协调机制

- **总览 spec**（本文档）：9 模块的实施顺序、依赖图、DoD
- **子 spec**：每模块独立 100-300 行，含完整接口契约
- **每周 rollout review**：用户回顾本周完成模块，调整下周的优先级
- **CHANGELOG.md**：每模块完成后在 [Unreleased] 段添加条目

## 12. 验收关卡

### 12.1 单模块验收
- spec + plan 已 commit
- 模块在独立分支上 CI 绿
- code-review agent 通过（无 critical/high）
- 用户 review 通过
- CHANGELOG.md 已更新

### 12.2 总体验收（Week 8）
- 9 模块全部 merge 到 release/win7 + push
- pytest + vitest 总覆盖率 ≥80%
- 跨模块 E2E 通过
- 与 main 功能能力 100% 对齐

## 13. 参考

- 项目级 CLAUDE.md：`/home/fz/project/sage/.claude/CLAUDE.md`（双分支策略、Python 环境、测试要求）
- main 设计参考：`docs/superpowers/specs/2026-06-25-aionui-inspired-ui-design.md`
- 历史同步记录：`/home/fz/.claude/projects/-home-fz-project-sage/memory/sage-win7-sync-progress.md`
- 9 模块的 main 实现：所有相关 main commits（详见 `git log main`）

---

**Spec 状态**：✅ 设计完成，待用户最终审阅后转入 writing-plans 阶段。

**下一步**：用户 review 本 spec 文件 → 确认后启动 M1 (i18n framework) 的独立 spec + plan。
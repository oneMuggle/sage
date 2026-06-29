---
name: win7-m5-sider-dnd
description: win7 Sider DnD 实施 spec — byte-for-byte port from main,把 Sidebar.tsx 拆为 SiderSection + ConversationsSection + @dnd-kit 排序 + 持久化 + 3 个 placeholder sections
metadata:
  type: spec
  status: design
  parent_spec: 2026-06-28-win7-modules-rollout-design.md §5.5
  source_commits_main: "01a54e8..e616bb2 (19 commits)"
  date: 2026-06-29
---

# win7 M5 Sider DnD Design Spec

## 1. Goal

把 `release/win7` 当前单文件 `src/widgets/layout/Sidebar.tsx`(149 行,所有 sidebar 逻辑混在一起)重构为符合 main 形态的**多组件 Sider 架构**:

- 抽出 `SiderSection` 容器(可折叠/可拖动/统一标题样式)
- 抽出 `ConversationsSection`(集成 @dnd-kit 排序的会话列表)
- 加 `useSiderSections` hook(管理 section 顺序 + 折叠状态)
- 加 `siderOrder` 纯函数 + `useStoredSiderOrder` 持久化 hook
- 加 3 个 placeholder sections(CronJob/Project/Team)
- Sidebar.tsx 重构为装配组件
- 集成 i18n(用 M1 自研 I18nProvider)

完成后,win7 与 main 的 Sider DnD 行为**用户视角 100% 对齐**。

## 2. Context

### 2.1 双分支 win7 现状 (2026-06-29)

| 项 | win7 | main |
|---|---|---|
| Sidebar.tsx | 单文件 149 行 | 装配式, 用 SiderSection 等 |
| @dnd-kit/core | ✅ 6.3.1 | ✅ 6.3.1 |
| @dnd-kit/sortable | ✅ 8.0.0 | ✅ 8.0.0 |
| @dnd-kit/utilities | ✅ 3.2.2 | ✅ 3.2.2 |
| M1 i18n | ✅ 已实现 | ✅ 自研同款 |
| M3 Scheduler | ✅ ScheduledTasks 页面 (CronJobSection 未接入 Sidebar) | ✅ CronJobSection 接入 |
| M4 Orchestration | ✅ | ✅ |
| SiderSection | ❌ | ✅ |
| ConversationsSection | ❌ | ✅ |
| SortableSessionItem/List | ❌ | ✅ |
| siderOrder.ts | ❌ | ✅ |
| useSiderSections | ❌ | ✅ |
| useStoredSiderOrder | ❌ | ✅ |
| placeholder sections (CronJob/Project/Team) | ❌ | ✅ |
| SiderSection.test | ❌ (7c76327 删除) | ✅ |
| sections-integration.test | ❌ (7c76327 删除) | ✅ |
| Sidebar.new-chat.test | ❌ (7c76327 删除) | ✅ |

### 2.2 关键历史决策

**7c76327 (win7 phase 9)**:主动删除 5 个测试文件(其中 3 个 M5 相关 + 2 个 M6 Welcome 相关)。
原 commit message: *"win7 does not implement Phase 1-7 i18n infrastructure, Welcome screen, or SiderSection components. The corresponding test files imported ../../shared/lib/i18n and other modules that don't exist in win7, causing pre-existing vitest failures."*

**当前合理性已变**:
- i18n 已在 win7 实现 → 3 个 M5 相关测试可恢复并 active
- Welcome (M6) 仍未实现 → 2 个 M6 相关测试恢复时用 `describe.skip` 包裹 + TODO 注释留 M6 处理

### 2.3 实施策略:byte-for-byte port

- 不重新设计,直接照搬 main 的实现 + 测试
- 唯一适配:i18n keys(`t('sidebar.section.conversations')` 等),`Sidebar.tsx` 中硬编码中文替换为 i18n
- 严格保持 main 的 commit 顺序与 message 格式(便于将来双向 cherry-pick)

## 3. Source commits on main (19 个,按时间顺序)

| # | Commit | Phase | 内容 |
|---|---|---|---|
| 1 | `1962e48` | deps | build(deps): add @dnd-kit/core, @dnd-kit/sortable, @dnd-kit/utilities — **SKIP, win7 已有** |
| 2 | `01a54e8` | T1 | test(dnd): scaffold siderOrder pure function tests |
| 3 | `6072f50` | T2 | feat(dnd): implement siderOrder pure functions |
| 4 | `1c6ed22` | T3 | test(dnd): extend siderOrder coverage to 26 tests |
| 5 | `43f436f` | T3-style | style(dnd): reformat siderOrder function signatures |
| 6 | `d2c4411` | T4 | test(dnd): scaffold useStoredSiderOrder hook tests |
| 7 | `29ca1bb` | T5 | feat(dnd): implement useStoredSiderOrder hook |
| 8 | `e1a812a` | T6 | test(dnd): extend useStoredSiderOrder coverage to 18 tests |
| 9 | `b971b92` | T7 | feat(dnd): add SortableSessionItem wrapper with drag handle |
| 10 | `627f968` | T8 | feat(session): add SortableSessionList with dnd-kit context |
| 11 | `9a96a73` | T9 | feat(sider): add useSiderSections hook with persisted order + collapsed |
| 12 | `1408657` | T10 | test(sider): cover useSiderSections hydrate / toggle / reorder |
| 13 | `fa3bcc1` | T11 | feat(sider): add ConversationsSection with sortable session list and tests |
| 14 | `d66d6af` | T12 | feat(sidebar): add placeholder CronJob/Project/Team sections |
| 15 | `d67ea88` | T13 | feat(sidebar): add barrel index for sidebar exports |
| 16 | `69cd656` | T14 | fix(dnd): align drag handle with session title using flex layout |
| 17 | `de986f4` | T14-style | style(sidebar): lint cleanup for SiderSection and ConversationsSection |
| 18 | `de0445c` | T15 | fix(sidebar): limit conversations section height to 50vh |
| 19 | `904d492` | T15-style | style(sidebar): fix import ordering in SiderSection.test.tsx |
| 20 | `e616bb2` | T16 | fix(sidebar): integrate CronJobSection with SiderSection + fix I18nProvider in Chat tests |

**有效 commit 数**:19 (skip 1962e48)

### 3.1 测试恢复 (来自 7c76327 删除的 5 个)

| 文件 | 处理 |
|---|---|
| `src/widgets/sidebar/SiderSection.test.tsx` | ✅ 完整恢复 + active |
| `src/widgets/sidebar/__tests__/sections-integration.test.tsx` | ✅ 完整恢复 + active |
| `src/widgets/layout/__tests__/Sidebar.new-chat.test.tsx` | ✅ 完整恢复 + active |
| `src/pages/__tests__/Chat.welcome-routing.test.tsx` | ⚠️ 恢复 + `describe.skip` + TODO for M6 |
| `src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx` | ⚠️ 恢复 + `describe.skip` + TODO for M6 |

## 4. 接口契约

### 4.1 siderOrder.ts (pure functions)

```typescript
// src/widgets/sidebar/siderOrder.ts

/** 重新排序 section */
export function reorder<T>(items: T[], fromIndex: number, toIndex: number): T[];

/** 切换折叠状态 */
export function toggleCollapsed(collapsed: Record<string, boolean>, sectionId: string): Record<string, boolean>;

/** 从 localStorage 读取顺序,降级到默认 */
export function loadOrder(stored: string[] | null, defaultOrder: readonly string[]): string[];

/** 持久化到 localStorage */
export function saveOrder(order: string[]): string; // JSON string

/** 从 localStorage 读取 collapsed map */
export function loadCollapsed(stored: string | null): Record<string, boolean>;

/** 持久化 collapsed map */
export function saveCollapsed(collapsed: Record<string, boolean>): string;
```

**测试**:26 个(覆盖 reorder 边界、JSON parse 失败降级、empty input)

### 4.2 useStoredSiderOrder hook

```typescript
// src/features/sidebar/useStoredSiderOrder.ts

interface UseStoredSiderOrderOptions {
  storageKey: string;
  defaultOrder: readonly string[];
}

interface UseStoredSiderOrderReturn {
  order: string[];
  setOrder: (next: string[]) => void;
  reset: () => void;
}

export function useStoredSiderOrder(opts: UseStoredSiderOrderOptions): UseStoredSiderOrderReturn;
```

**测试**:18 个(覆盖 initial load、persist、reset、storage 异常)

### 4.3 useSiderSections hook

```typescript
// src/features/sidebar/useSiderSections.ts

interface SiderSectionConfig {
  id: string;
  title: ReactNode; // 接受 i18n key 解析后的 string
}

interface UseSiderSectionsReturn {
  order: string[];
  collapsed: Record<string, boolean>;
  toggleCollapsed: (sectionId: string) => void;
  reorder: (fromIndex: number, toIndex: number) => void;
  isCollapsed: (sectionId: string) => boolean;
}

export function useSiderSections(
  sections: readonly SiderSectionConfig[],
  storageKey?: string,
): UseSiderSectionsReturn;
```

**测试**:覆盖 hydrate / toggle / reorder 的所有 path

### 4.4 SiderSection 组件

```typescript
// src/widgets/sidebar/SiderSection.tsx

interface SiderSectionProps {
  title: string; // i18n-resolved
  collapsed: boolean;
  onToggleCollapsed: () => void;
  children: ReactNode;
  dragHandleProps?: DragHandleProps; // 来自 useSortable
  testId?: string;
}

export function SiderSection(props: SiderSectionProps): JSX.Element;
```

**行为**:
- 渲染标题 + 折叠/展开箭头 + 拖动手柄
- `collapsed=true` 时只显示标题,不渲染 children
- 拖动时显示视觉反馈(transform / shadow)

### 4.5 ConversationsSection 组件

```typescript
// src/widgets/sidebar/ConversationsSection.tsx

interface ConversationsSectionProps {
  collapsed: boolean;
  onToggleCollapsed: () => void;
}

export function ConversationsSection(props: ConversationsSectionProps): JSX.Element;
```

**内部**:DndContext + SortableContext + SortableSessionList + 新对话按钮

### 4.6 SortableSessionItem / List

```typescript
// src/widgets/session/SortableSessionItem.tsx
interface SortableSessionItemProps extends SessionItemProps {
  // 透传 useSortable 的 transform/transition 给 drag handle
}
export function SortableSessionItem(props: SortableSessionItemProps): JSX.Element;

// src/widgets/session/SortableSessionList.tsx
interface SortableSessionListProps {
  sessions: Session[];
  currentSessionId: string | null;
  onSelect: (id: string) => void;
  onDelete: (id: string) => void;
  onReorder?: (newOrder: string[]) => void;
}
export function SortableSessionList(props: SortableSessionListProps): JSX.Element;
```

### 4.7 Placeholder sections

```typescript
// src/widgets/sidebar/sections/{CronJobSection,ProjectSection,TeamSection}.tsx
// 每个都是简单组件:用 SiderSection 包裹 + 标题 + "Coming soon" placeholder 文案
```

### 4.8 i18n keys (新增)

```typescript
// src/shared/lib/i18n/zh.ts (追加)
'sider.section.conversations': '对话',
'sider.section.cronjobs': '定时任务',
'sider.section.projects': '项目',
'sider.section.teams': '团队',
'sider.section.collapse': '折叠',
'sider.section.drag_handle': '拖动以重排',
'sider.placeholder.coming_soon': '即将推出',
'sider.conversations.empty': '还没有对话',
'sider.conversations.recent': '最近对话',
'sider.cronjobs.placeholder': '定时任务面板将集成在主窗口',
'sider.projects.placeholder': '项目面板将在 Phase 4 提供',
'sider.teams.placeholder': '团队面板将在 Phase 6 提供',
'sider.action.new_chat': '+ 新对话',

// src/shared/lib/i18n/en.ts (对应英文)
'sider.section.conversations': 'Conversations',
'sider.section.cronjobs': 'Scheduled Tasks',
'sider.section.projects': 'Projects',
'sider.section.teams': 'Teams',
'sider.section.collapse': 'Collapse',
'sider.section.drag_handle': 'Drag to reorder',
'sider.placeholder.coming_soon': 'Coming soon',
'sider.conversations.empty': 'No conversations yet',
'sider.conversations.recent': 'Recent',
'sider.cronjobs.placeholder': 'CronJob panel will integrate in main window',
'sider.projects.placeholder': 'Projects panel coming in Phase 4',
'sider.teams.placeholder': 'Teams panel coming in Phase 6',
'sider.action.new_chat': '+ New Chat',
```

## 5. 文件清单(新增 / 修改)

### 5.1 新增

```
src/widgets/sidebar/
├── SiderSection.tsx                          (P5)
├── ConversationsSection.tsx                   (P5)
├── siderOrder.ts                             (P2)
├── index.ts                                  (P5, barrel)
├── SiderSection.test.tsx                     (P7, 恢复)
├── __tests__/
│   └── sections-integration.test.tsx         (P7, 恢复)
└── sections/
    ├── CronJobSection.tsx                    (P5)
    ├── ProjectSection.tsx                    (P5)
    └── TeamSection.tsx                       (P5)

src/widgets/session/
├── SortableSessionItem.tsx                   (P3)
└── SortableSessionList.tsx                   (P3)

src/features/sidebar/
├── useStoredSiderOrder.ts                    (P2)
└── useSiderSections.ts                       (P4)

src/widgets/sidebar/
├── siderOrder.test.ts                        (P2, 26 tests)
├── SiderSection.test.tsx                     (P7, 恢复)
└── __tests__/sections-integration.test.tsx   (P7, 恢复)

src/features/sidebar/
├── useStoredSiderOrder.test.ts               (P2, 18 tests)
└── useSiderSections.test.ts                  (P4)

src/widgets/sidebar/ConversationsSection.test.tsx  (P5)
src/widgets/session/SortableSessionItem.test.tsx  (P3)
src/widgets/session/SortableSessionList.test.tsx  (P3)

src/widgets/layout/__tests__/
└── Sidebar.new-chat.test.tsx                 (P7, 恢复)

src/pages/__tests__/
└── Chat.welcome-routing.test.tsx             (P7, 恢复 + describe.skip)

src/widgets/welcome/__tests__/
└── WelcomeInputCard.test.tsx                 (P7, 恢复 + describe.skip)
```

### 5.2 修改

```
src/widgets/layout/Sidebar.tsx                (P6, 重构用 SiderSection 装配)
src/shared/lib/i18n/{zh,en}.ts                (P5, 加 sider.* keys)
src/shared/lib/i18n/zh.ts (TranslationKey type) (P5)
src/pages/__tests__/{Chat.auto-scroll,Chat.config-warning}.test.tsx  (P6, I18nProvider wrap)
src/widgets/layout/__tests__/Sidebar.tsx     (P6, 任何已有测试)
```

## 6. 数据流(关键场景)

### 6.1 用户拖动 sessions 重排

```
User drags session B above session A in ConversationsSection
  → DndContext.onDragEnd({ active: B, over: A })
  → SortableSessionList.handleReorder
  → useSiderSections.reorder(fromIndex, toIndex)
  → siderOrder.reorder(order, fromIndex, toIndex) → newOrder
  → useStoredSiderOrder.setOrder(newOrder) → localStorage.setItem
  → Zustand store.sessions 重新排序
  → SortableContext 重渲染
```

### 6.2 用户折叠 ConversationsSection

```
User clicks 折叠箭头
  → SiderSection onToggleCollapsed
  → useSiderSections.toggleCollapsed('conversations')
  → siderOrder.toggleCollapsed(collapsedMap, 'conversations') → newMap
  → useStoredSiderOrder.setCollapsed(newMap) → localStorage
  → collapsed state 更新 → SiderSection 隐藏 children
```

## 7. 测试策略

### 7.1 单元测试 (per file)

- `siderOrder.test.ts`: 26 tests (per main, T3 commit)
- `useStoredSiderOrder.test.ts`: 18 tests (per main, T6 commit)
- `useSiderSections.test.ts`: hydrate / toggle / reorder paths
- `SortableSessionItem.test.tsx`: drag handle, sort transform
- `SortableSessionList.test.tsx`: DndContext integration, reorder callback
- `SiderSection.test.tsx`: 渲染 / 折叠 / 拖动手柄 (恢复)

### 7.2 集成测试

- `sections-integration.test.tsx`: 4 sections 装配 + 持久化往返 (恢复)
- `Sidebar.new-chat.test.tsx`: 触发 new chat 流程 (恢复)

### 7.3 恢复的 M6 测试 (skipped)

- `Chat.welcome-routing.test.tsx`: 包裹 `describe.skip('M6: Welcome 尚未实现,跳过', () => { ... })`
- `WelcomeInputCard.test.tsx`: 同上

### 7.4 覆盖率目标

- 新增代码 ≥ 80% (per testing.md)
- 整体维持 ≥ 80%

## 8. 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| @dnd-kit 类型与 React 18.2 兼容问题 | 低 | P3 延期 | 已在 main 验证过,win7 React 版本相同,直接 port |
| i18n key 缺失导致 TypeScript 编译错误 | 中 | P5 阻断 | 在 P5 阶段同时更新 zh.ts + en.ts + TranslationKey 类型 |
| SessionItem 改动影响现有测试 | 中 | P6 调试 | 先跑现有 Sidebar.test / Chat 测试作为基线,逐 commit 验证 |
| 持久化到 localStorage 在 vitest jsdom 下行为差异 | 低 | P2 测试 | jsdom 25+ 支持 localStorage,无需 mock |
| Sidebar 重构破坏 M3 ScheduledTasks 入口 | 低 | UX 退步 | ScheduledTasks 路由保持,仅 Sidebar 视觉重排 |

## 9. DoD

- ✅ 19 个 commit 全部落 `feat/win7-m5-sider-dnd`
- ✅ 5 个 phase 9 删除的测试文件按策略恢复(3 active + 2 skipped)
- ✅ 8 个 sider.* i18n keys 在 zh.ts + en.ts + TranslationKey 中对齐
- ✅ Sidebar.tsx 重构后保持原功能(nav items / sessions / footer)
- ✅ `npm run lint` 0 errors
- ✅ `tsc --noEmit` 0 errors
- ✅ `vitest` 全过(含恢复的测试 + 新测试)
- ✅ `pytest` 仍全过(M5 无后端改动,只需回归)
- ✅ `pre-push hook` 通过
- ✅ PR 创建,base = `release/win7`,CI 全绿
- ✅ CHANGELOG.md [Unreleased] 添加 M5 条目

## 10. 实施阶段

### Week 1 — 7 phases (预计 1 session 完成核心,后续 session 收尾)

| Phase | Commit 数 | 内容 | 估计时间 |
|---|---|---|---|
| 1: 准备 | 1 | spec + plan + branch | 5 min |
| 2: 纯函数基础 | 6 | siderOrder + useStoredSiderOrder + 44 tests | 30 min |
| 3: 排序组件 | 2 | SortableSessionItem + List | 20 min |
| 4: sections hook | 2 | useSiderSections + tests | 20 min |
| 5: section 容器 + placeholder | 3 | SiderSection + ConversationsSection + 3 placeholder + barrel + tests | 30 min |
| 6: Sidebar 重构 + i18n | 4 | Sidebar.tsx + i18n keys + Chat 测试 wrap | 30 min |
| 7: 测试恢复 + 收尾 | 1 | 5 个 phase 9 测试恢复 + style fixup | 15 min |
| 8: CHANGELOG + push + PR | 1 | CHANGELOG + 验证 + 推 + 开 PR | 10 min |
| **总计** | **19** | | **~2.5 hours** |

## 11. 验收关卡

- spec + plan 已 commit
- 19 commits 全部落 `feat/win7-m5-sider-dnd`
- 5 个 phase 9 删除的测试按策略恢复
- CI: Frontend (TypeScript) / Electron build (ubuntu/windows) / Electron smoke 全绿
- Backend CI skipping (win7 分支)
- `pre-push hook` 通过
- 用户 review 通过
- CHANGELOG.md 已更新

## 12. 参考

- **父 spec**: `docs/superpowers/specs/2026-06-28-win7-modules-rollout-design.md` §5.5
- **M1 i18n spec**: `docs/superpowers/specs/2026-06-28-win7-i18n-framework-design.md`
- **main M5 source commits**: `git log origin/main 01a54e8^..e616bb2`
- **win7 phase 9 测试删除**: commit `7c76327`
- **前序 M4**: `[[sage-m4-orchestration-merged]]`
- **CLAUDE.md**: `/home/fz/project/sage/.claude/CLAUDE.md` (双分支策略、Python 环境、测试要求)

# 27 — Sider DnD (Phase 2)

## Overview

侧边栏(`Sidebar.tsx`)从单文件硬编码列表重构为**可拖拽 + 可折叠分组**架构:

- 4 个分组(`conversations` / `cron` / `project` / `team`)按用户偏好顺序排列,持久化到 localStorage
- `conversations` 分组内的会话支持**拖拽重排**(`@dnd-kit/sortable`)
- 每个分组可独立**折叠/展开**(`chevron` 切换)
- 拖拽手柄 / 折叠图标 / 分组标题全部走 i18n

> 本文档是 M5 (Sider DnD) 模块的"事后归档"——原始 spec 在
> `docs/superpowers/specs/2026-06-29-win7-sider-dnd-design.md`。
> 实施以 main 侧 `01a54e8..e616bb2` 19 个 commit 为蓝本 byte-for-byte port 到
> `release/win7`(`@5e946de..@c0adf77`)。

## Architecture

### 文件分布(共 12 个新增/重构)

```
src/shared/lib/dnd/
├── siderOrder.ts                          # 纯函数(6 个),无 React/DOM 依赖
├── siderOrder.test.ts                     # 26 tests
├── useStoredSiderOrder.ts                 # hook: 绑定 localStorage ↔ session 顺序
└── useStoredSiderOrder.test.ts            # 18 tests

src/widgets/sidebar/
├── useSiderSections.ts                    # hook: 4 分组的 order + collapsed
├── useSiderSections.test.ts               # hydrate / toggle / reorder 覆盖
├── SiderSection.tsx                       # 容器组件(可折叠/可重排/统一标题)
├── SiderSection.test.tsx                  # 渲染 + 折叠 + 拖动手柄测试
├── index.ts                               # barrel 导出
├── __tests__/
│   └── sections-integration.test.tsx      # 4 分组装配 + 持久化往返
└── sections/
    ├── ConversationsSection.tsx           # 集成 SortableSessionList
    ├── ConversationsSection.test.tsx      # 排序回调 + 新对话按钮测试
    ├── CronJobSection.tsx                 # 真实数据:scheduled taskStore
    ├── ProjectSection.tsx                 # placeholder(coming soon)
    └── TeamSection.tsx                    # placeholder(coming soon)

src/widgets/session/
├── SortableSessionItem.tsx                # drag handle wrapper(useSortable)
├── SortableSessionList.tsx                # DndContext + SortableContext
└── __tests__/
    └── SortableSessionList.test.tsx       # DndContext 集成 + reorder 回调

src/widgets/layout/
├── Sidebar.tsx                            # 重构:装配 4 分组 + 2 hook 驱动
└── __tests__/
    └── Sidebar.new-chat.test.tsx          # 新对话按钮触发 createSession
```

### 分层职责

| 层 | 关注点 | 代表文件 |
|---|---|---|
| **Pure functions** | 不可变、零依赖、纯计算 | `siderOrder.ts` |
| **State hooks** | 桥接 React state ↔ localStorage,自动 reconcile | `useStoredSiderOrder.ts` / `useSiderSections.ts` |
| **UI 容器** | 视觉骨架,无业务数据 | `SiderSection.tsx` |
| **业务 sections** | 注入数据 + 集成排序 | `ConversationsSection.tsx` / `CronJobSection.tsx` / placeholder |
| **装配** | hook + 路由 + 子组件组合 | `Sidebar.tsx` |

## Storage(localStorage)

**两个独立 storage key**(互相不耦合):

| Key | Shape | 写入方 | 内容 |
|---|---|---|---|
| `sage:sider:order:v1` | `string[]`(JSON) | `useStoredSiderOrder` | 4 个 section key 的显示顺序(`['conversations', 'cron', 'project', 'team']`) |
| `sage:sider:sections:v1` | `{ order: string[], collapsed: string[] }` | `useSiderSections` | 同上 + 每分组折叠标记 |

**`:v1` 后缀**:未来 schema 升级的 escape hatch——若破坏性改动,可换 `:v2` 配合 migrate 工具。
当前两层都用了 `:v1`,main 和 win7 完全一致。

### 容错策略(均由两个 hook 内置)

| 失败场景 | 降级行为 |
|---|---|
| localStorage 抛错(隐私模式 / quota) | 静默忽略,UI 仍可用 |
| JSON parse 失败 | 返回默认 order `['conversations', 'cron', 'project', 'team']` |
| 旧值里出现未知 section id | reconcile 时丢弃(只保留当前 defaultOrder 中存在的) |
| 新增 section id(用户升级后) | 追加到默认顺序尾部 |
| `collapsed` 里有非 defaultOrder 的 key | 过滤掉 |

## i18n keys(7 个,zh + en 全部对齐)

| Key | zh | en | 用途 |
|---|---|---|---|
| `sider.section.conversations` | 会话 | Conversations | conversations 分组标题 |
| `sider.section.cron` | 定时任务 | Scheduled Tasks | cron 分组标题 |
| `sider.section.project` | 项目 | Projects | project 分组标题 |
| `sider.section.team` | 团队 | Team | team 分组标题 |
| `sider.drag_handle` | 拖拽排序 | Drag to reorder | sortable item 的 drag handle aria-label |
| `sider.collapse` | 折叠 | Collapse | SiderSection 折叠态 aria-label |
| `sider.expand` | 展开 | Expand | SiderSection 展开态 aria-label |

> 注:CronJobSection 标题在源码中实际用 `t('scheduled.title')`,而非 `sider.section.cron`。
> 这是 main 的原本行为,win7 保持一致。

## Data Flow

### 拖拽重排 conversations

```
User drags session B above A
  → @dnd-kit DndContext.onDragEnd({ active: B, over: A })
  → SortableSessionList.handleReorder
  → onOrderChange(newOrder) 传给 ConversationsSection
  → Sidebar.tsx 把 newOrder[0] 在旧/新数组中的 index 算出来
  → useStoredSiderOrder.reorder(oldIndex, newIndex)
  → reorderSiderIds(order, from, to)  → 新 SiderOrder
  → setOrder → useEffect 触发 localStorage.setItem('sage:sider:order:v1', JSON)
  → orderedItems 重排序(useMemo) → SortableSessionList 重渲染
```

### 折叠 conversations 分组

```
User clicks 折叠箭头
  → SiderSection onToggleCollapsed (props 透传)
  → Sidebar.tsx toggleCollapsed('conversations')
  → useSiderSections.toggleCollapsed(key)
  → setState({ ..., collapsed: [...prev.collapsed, key] })
  → useCallback 内部 writeSectionsState → localStorage.setItem
  → collapsed Set 重建 → 下一渲染时 collapsed.has(key) 命中
  → SiderSection 不渲染 children(返回 <header> only)
```

### 加载时的 reconcile

```
Sidebar mount
  → useSiderSections(defaultOrder): readSectionsState
      - 读 'sage:sider:sections:v1' 失败 → fallback = { order: defaultOrder, collapsed: [] }
      - 成功但 JSON 损坏 → fallback
      - 成功 → reconcile storedOrder 与 defaultOrder:
          * 保留仍在 default 中的(按 stored 顺序)
          * 追加 default 中新出现的(按 default 顺序)
          * 丢弃 stored 中已不存在的
  → useStoredSiderOrder({ storageKey, items, getId }):
      - 读 'sage:sider:order:v1',reconcile 同上规则
      - items id 集合变化时(useEffect on idsKey)自动 reconcile
```

## Tests

| 测试文件 | 覆盖目标 | 数量 |
|---|---|---|
| `siderOrder.test.ts` | 6 个 pure functions(边界 / JSON 错误 / 越界) | 26 |
| `useStoredSiderOrder.test.ts` | initial load / persist / reset / storage 异常 | 18 |
| `useSiderSections.test.ts` | hydrate / toggle / reorder | 12 |
| `SiderSection.test.tsx` | 渲染 / 折叠 / 拖动手柄 | 多组 |
| `ConversationsSection.test.tsx` | 排序回调 / 新对话按钮 | 多组 |
| `__tests__/sections-integration.test.tsx` | 4 分组装配 + 持久化往返 | 多组 |
| `__tests__/Sidebar.new-chat.test.tsx` | 新对话 → createSession | 多组 |
| `__tests__/SortableSessionList.test.tsx` | DndContext 集成 | 多组 |

**跳过但保留**:win7 同步 M5 时恢复了 phase 9 误删的 2 个 M6 测试,包裹在
`describe.skip` 内,等 M6 实施时再激活:

- `src/pages/__tests__/Chat.welcome-routing.test.tsx`
- `src/widgets/welcome/__tests__/WelcomeInputCard.test.tsx`

## Win7 Adaptations(M5 同步时与 main 的差异)

| 项 | main | win7 |
|---|---|---|
| 新对话点击 | navigate to `/welcome` 后选 | `createSession()` 直接跳到 `/chat`(M6 尚未实施) |
| 项目/团队分组 | 占位符 | 占位符(与 main 一致) |
| 实施方式 | 原始 commit 链 | byte-for-byte port + 上述 1 处适配 |
| i18n | 自研 I18nProvider | 同款(M1 已同步) |
| `@dnd-kit/*` 版本 | core 6.3.1 / sortable 8.0.0 / utilities 3.2.2 | 同款(win7 早已具备) |

## Reference

- **父 spec**:`docs/superpowers/specs/2026-06-28-win7-modules-rollout-design.md` §5.5
- **本模块 spec**:`docs/superpowers/specs/2026-06-29-win7-sider-dnd-design.md`
- **本模块 plan**:`docs/superpowers/plans/2026-06-29-win7-sider-dnd-impl.md`
- **main source commits**:`01a54e8..e616bb2` (19 commits)
- **win7 merge commit**:`c0adf77` (PR #77, 28 commits via 5 forward cherry-picks)
- **前序模块**:`26-packaging-matrix.md` (M4 已合并,本模块承接)
- **后续模块**:M6 Welcome(待启动)

# 110 — 会话列表滚动、分页与归档

> main #2655 / win7 #2662（2026-10-29 ~ 10-30）。本文档由
> `docs/plans/2026-10-29_session-list-scroll-and-manual-archive.md` 归档而来，
> 记录最终实现与两个分支的差异。

## Overview

侧栏会话列表此前存在四个叠加问题：

1. **列表被裁剪**：`SiderSection` 只设置了 `maxHeight`，但 UX-IA R3 重构时移除了内层 `overflow-y-auto`，外层 `motion.div` 的 `overflow-hidden` 把超出部分直接裁掉——约十几条会话后无法滚动查看。
2. **接口硬上限 100 条**：`GET /sessions` 默认 `limit=100`，前端无分页，第 101 条起的会话永远拉不到；`VIRTUALIZE_THRESHOLD=120` 因此永远不可达。
3. **手动归档链路三层断开**：前端无入口、IPC `session_update` 丢弃 `isArchived`、后端 `SessionUpdate` 无 `is_archived` 字段——只能自动归档，且调用 `setArchived` 会静默无效。
4. **归档会话不可见**：仓储 `list()` 固定 `WHERE is_archived = 0`，没有查询归档的接口，侧栏归档视图永远为空。

## 方案选择：独立滚动面板（方案 B）

对比过两种方案：

| 维度 | A：虚拟化绑定外层滚动 | B：独立滚动面板（采纳） |
|---|---|---|
| 滚动语义 | 全侧栏一条滚动条 | 会话列表一条，其他分区常驻 |
| 虚拟化改造 | 需 `scrollMargin` + 偏移重算 | 自有滚动容器 / 面板顶部偏移 0 |
| 折叠动画兼容 | 动画期间偏移错误，行会跳 | 高度重排，虚拟化器自动响应 |
| 空间分配 | 会话多时顶走项目/Git 分区 | 其他分区常驻，会话区吃剩余高度 |

最终结构：

```
Sidebar nav (flex col, overflow-y-auto 仅兜底)
├── SiderSection project   maxHeight=30vh + 内层 overflow-y-auto
├── SiderSection conversations  fill（flex-1 min-h-[120px]）
│   └── 滚动面板 overflow-y-auto（列表唯一滚动容器）
│       ├── SessionList（<120 条）
│       └── VirtualSessionList（scrollElementRef 绑定该面板）
└── SiderSection git（天然高度）
```

- `SiderSection` 提供两种明确语义：`fill`（flex 填充 + 内层滚动，不播放高度动画）与 `boundedScroll`（`maxHeight` + `overflow-y-auto`），删除了「只钳高度不滚动」的中间态。
- `VirtualSessionList` 通过 `scrollElementRef` 绑定分区面板。列表是面板内容第一项，偏移为 0，**不需要 `scrollMargin`**；独立使用时仍保留自建滚动容器。

## 分页

- `sessionApi.list({ limit, offset, archived })` 只下发显式参数；无参调用保持 `invoke('list_sessions')` 原形状。
- store 新增 `sessionsHasMore` / `sessionsLoadingMore` / `loadMoreSessions()`：
  - 滚动距底 240px 触发；单飞行锁 + 按 id 去重；
  - `loadSessions()` 刷新时按 `max(100, 已加载条数)` 拉取，避免已滚动加载的页被重置。
- 超过 120 条进入虚拟化分支（分页修好后该分支首次真正可达）。

## 归档链路

### 后端

| 层 | 变更 |
|---|---|
| `SessionUpdate`（legacy + hex） | 新增 `is_archived: Optional[bool]`；PATCH 映射为 0/1 |
| `SessionRepository.list()` | 新增 `archived` 参数：None/False → 未归档；True → 仅已归档 |
| `Session.to_dict()` | 补 `is_archived` 序列化 |
| `GET /sessions`（legacy + hex） | 新增 `archived=true` 查询参数 |
| `StoragePort.list_sessions` | 新增 `archived` 参数（sage_core 与 backend/ports 两份 Protocol） |
| `SessionService.list_sessions` | 透传 `archived` 后 in-mem 分页切片 |
| `SqliteStorageAdapter` / `MemoryStorageAdapter` | 支持归档过滤；memory 适配器新增 `archived` 状态与 `is_archived` 更新 |
| `sqlite_adapter.update_session` | 字段白名单补 `is_archived` |

### IPC 与前端

- `electron/commandRoutes/sessions.ts`：`list_sessions` 透传 `archived`；`session_update` 透传 `isArchived`。
- `SessionItem`：hover 操作区新增归档/恢复按钮；`running/suspended` 禁用归档（与 `archive_stale` 策略一致）；归档条目隐藏置顶。
- `ConversationsSection`：归档视图按需拉取（局部 `archivedSessions`，不污染全局 store），支持分页、恢复、删除、清空；自动归档 sweep 有新增时 toast「已自动归档 N 个会话」。

## 分支差异与注意事项

- **win7 基线**：`architecture-baseline.json` 按 win7 实测值补账（`session_repo.py` 1121、`electron/__tests__/commands.test.ts` 1210；`electron/main.ts` 保持 2942）。
- **pydantic v1 / py3.8**：仅使用 `Optional[bool]`，无 PEP 604/585；`check_py38_compat.py` 0 违规。
- memory 适配器的主分支版本无 `title_attempts` 字段（win7 有），cherry-pick 时按各分支现状适配，不强行对齐。

## 测试

- 后端：`test_session_archive_sweep.py`（仓储过滤/分页）、`test_session_manual_archive.py`（HTTP 归档契约）、`test_session_service.py`、`test_memory_storage_adapter.py`（memory + sqlite 适配器归档过滤）。
- 前端：`ConversationsSection.test.tsx`（归档视图/恢复/分页触底）、`SessionItem.archive.test.tsx`、`store.test.ts`（分页追加/去重）、`sessionApi.test.ts`、`Sidebar.two-stage.test.tsx`（滚动结构）。
- Electron：`commands.test.ts`（archived 查询串 / is_archived body）。
- CI：main 与 win7 全绿，win7 侧 py3.8 后端 10m45s、Frontend 16m43s。

## 关键文件

```
backend/api/{legacy_models,legacy_session_routes,hex_routes}.py
backend/application/services/session_service.py
backend/data/session_repo.py
backend/adapters/out/storage/{sqlite,memory}_adapter.py
packages/sage-core/sage_core/repositories/storage.py
backend/ports/storage.py
electron/commandRoutes/sessions.ts
src/shared/api/sessionApi.ts
src/shared/lib/store.ts
src/widgets/sidebar/SiderSection.tsx
src/widgets/sidebar/sections/ConversationsSection.tsx
src/widgets/layout/Sidebar.tsx
src/widgets/session/{SessionItem,SessionList,VirtualSessionList}.tsx
```

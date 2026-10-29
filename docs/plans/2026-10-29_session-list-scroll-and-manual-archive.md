# 会话列表滚动与手动归档优化方案

> 状态：待实施（2026-10-29）
> 分支策略：先在 `main` 实施，再按双分支规则 cherry-pick 到 `release/win7`（需 py3.8 / pydantic v1 适配，本方案不引入 v2-only 语法）。

## 1. 背景与目标

用户反馈：侧栏会话列表在会话数量较多时无法滚动查看更多会话；且只能自动归档，不能手动归档。

经代码排查，这不是单一缺陷，而是四条链路叠加的问题：

| 编号 | 问题 | 影响 |
|---|---|---|
| P1 | 会话分区高度被 `maxHeight` 裁剪且无滚动条 | 约 10 条以上会话即不可见、不可达 |
| P2 | 列表接口硬上限 100 条，前端无分页 | 第 101 条起的会话永远拉不到 |
| P3 | 手动归档 UI → IPC → 后端 PATCH 三层断开 | 只能自动归档，手动入口不存在且 API 是死代码 |
| P4 | 归档会话无任何查询接口、不可见不可恢复 | 「归档」视图永远为空，「清空归档」永远禁用 |

目标：

1. 会话列表随侧栏单一滚动容器自然滚动，任意数量会话都能查看。
2. 会话列表支持分页加载（滚动到底自动加载下一页）。
3. 会话条目支持手动归档 / 恢复归档，与自动归档行为一致。
4. 归档视图可查看、可恢复、可清空，形成完整闭环。

非目标：不改会话排序规则（仍由后端 SQL 决定）；不做跨会话批量选择归档（后续如有需要再加）。

## 2. 根因分析

### P1：`maxHeight` 裁剪导致列表不可滚动

- `src/widgets/sidebar/sections/ConversationsSection.tsx:238` 给 `SiderSection` 传 `maxHeight="50vh"`。
- `src/widgets/sidebar/SiderSection.tsx:126-149`：UX-IA R3 批次 B-3 移除了内层 `overflowY: auto`（为了消除三层嵌套滚动），但保留了 `maxHeight` 内联样式，外层 `motion.div` 仍是 `overflow-hidden`。
- 结果：内容超过 50vh 的部分被直接裁剪，外层 `nav#sidebar-scroll`（`Sidebar.tsx:582`）也因分区高度被钳制而无法补偿。
- 同类问题也存在于 `SidebarProjectList.tsx:153`（`maxHeight="30vh"`）——项目列表超过 30vh 同样被裁剪。
- 另外 `VIRTUALIZE_THRESHOLD = 120`（`ConversationsSection.tsx:15`）高于列表上限 100（P2），所以虚拟化分支在生产中**永远不可达**，属于死代码。

### P2：列表接口硬上限 100 条

- 每页默认 `limit=100, offset=0`：`backend/api/legacy_session_routes.py:108`。
- Electron 路由默认值同为 100：`electron/commandRoutes/sessions.ts:20-28`。
- 前端 `store.loadSessions()`（`src/shared/lib/store.ts:234-241`）调用 `list_sessions` 时不传参数，也没有任何分页/追加逻辑。
- 因此 `sessions` 最多只会有 100 条（还会被 P1 再裁掉大半）。

### P3：手动归档链路三层断开

1. **前端无入口**：`SessionItem.tsx` 只有导出 / 置顶 / 删除按钮，没有归档按钮；`sessionApi.setArchived()`（`sessionApi.ts:207`）只有测试在调用，产品代码零调用。
2. **IPC 丢弃字段**：`electron/commandRoutes/sessions.ts:209-221` 的 `session_update.body()` 只透传 `title` / `is_pinned`，`isArchived` 被静默丢弃，PATCH body 变成 `{}`。
3. **后端模型无字段**：`backend/api/legacy_models.py:23-28` 与 `backend/api/hex_routes.py:463-470` 的 `SessionUpdate` 都只有 `title` / `is_pinned`；`legacy_session_routes.py:176-192` 的 PATCH handler 也只映射这两个字段。

即使调用 `setArchived`，也是「静默成功」——不报错、不生效，排查成本极高。

### P4：归档会话不可见、不可恢复

- `SessionRepository.list()`（`backend/data/session_repo.py:175-192`）固定 `WHERE is_archived = 0`，且没有任何 `include_archived` / `archived_only` 参数或独立接口。
- 前端 `ConversationsSection` 的「归档」开关（R51）过滤的是内存里的 `sessions`，而那些数据永远不含归档会话 —— 切过去永远是空列表，`archivedCount` 永远为 0，`purge-archived` 按钮永远 `disabled`。
- 没有取消归档的路径；自动归档后的会话对用户来说等于「消失」，只能靠清空全部归档删除（而且按钮还是灰的）。

## 3. 技术方案

### 3.1 滚动与布局：会话分区改为独立滚动面板（方案 B，已采纳）

对比过两种方案后选择「独立滚动面板」：

| 维度 | A：虚拟化绑定外层滚动 | B：独立滚动面板（采纳） |
|---|---|---|
| 滚动语义 | 整个侧栏一条滚动条 | 会话列表一条滚动条，其他分区常驻 |
| 虚拟化改造 | 需 `scrollMargin` + 偏移重算 + 行定位平移 | 自有滚动容器原样保留，改动小 |
| 折叠动画兼容 | 动画期间偏移错误，行会跳 | 高度重排，虚拟化器自动响应尺寸变化 |
| 空间分配 | 会话多时顶走项目/Git 分区 | 其他分区常驻，会话区吃剩余高度 |
| 分组吸顶 | 绝对定位导致 sticky 失效，需自绘 | 面板内原生 sticky 可用 |
| 测试成本 | 高（偏移测量无法在 jsdom 验证） | 低（布局类名断言 + 现有测试基本不动） |

B 偏离了 UX-IA R3 的「单一滚动容器」原则，但形成的是**兄弟滚动面板**（会话区 + 按需的项目区），不是 R3 反对的父子两层嵌套；且会话区的空间比原来的 50vh 更大，同时保持其他分区可达。

实施要点：

1. `SiderSection` 提供两种明确语义，删除现在「只钳高度不滚动」的中间态：
   - `fill`：分区为 `flex-1 min-h-0 flex flex-col`，内层列表 `overflow-y-auto`（会话分区）；
   - `boundedScroll`：`maxHeight` + 内层 `overflow-y-auto`（项目分区恢复原行为，`30vh`）。
   - `fill` 分区不使用 motion 高度动画（flex 子项与 `height: auto` 动画冲突），折叠即时生效；其他分区保留动画。审计快照同步更新。
2. `Sidebar` 的 `nav` 改为 `flex flex-col overflow-hidden`；conversations 分区 wrapper 加 `flex-1 min-h-0`；给会话区设 `min-height`（如 120px），并保留 nav `overflow-y-auto` 作为极端小窗口的最后防线。
3. `ConversationsSection` 去掉 `maxHeight`，搜索栏/归档工具条固定，列表放在分区自己的滚动面板里：
   - 面板 `flex-1 min-h-0 overflow-y-auto`，是会话列表唯一的滚动容器；
   - `SessionList` 直接在面板内自然滚动；
   - `VirtualSessionList` 通过 `scrollElementRef` 绑定该面板作为滚动元素。列表是面板内容的第一项，偏移为 0，不需要 `scrollMargin`；独立使用时仍保留自建滚动容器（`maxHeight` 生效）。
4. 保留 `VIRTUALIZE_THRESHOLD = 120`，分页修好后该分支才真正可达；两种渲染器同处一个滚动面板，切换不改变滚动模型。

> 备选方案 A（若产品后续坚持「全侧栏一条滚动条」）：移除全部 `maxHeight`，`VirtualSessionList` 通过 Context 拿到 `nav` 滚动元素，用 `scrollMargin`（`offsetTop` 计算）+ `ResizeObserver` 重算绑定外层滚动。代价见上表，实施风险主要在折叠动画期间的偏移抖动。

### 3.2 分页加载

后端已支持 `limit/offset`，补齐前端与参数传递：

1. `sessionApi.list(opts?: { limit?: number; offset?: number; archived?: boolean })`，透传到 `list_sessions`。
2. store 增加：`sessionsHasMore`、`sessionsLoadingMore`、`loadMoreSessions()`；`loadSessions()` 重置为第一页。追加时按 `id` 去重。
3. 触发方式：`nav#sidebar-scroll` 滚动到接近底部（或列表末尾放 1px sentinel + `IntersectionObserver`）→ 调 `loadMoreSessions()`；单飞行锁防止并发重复请求。
4. 刷新语义：删除 / 归档 / 重命名后刷新时，`limit = max(pageSize, 已加载条数)`，避免用户已滚动加载的页被重置回 50/100 条。
5. 页大小定为 100（与现有默认一致），后端无需改动。

### 3.3 手动归档链路

按「前端 → IPC → 后端」三层补齐：

1. **后端模型**：`legacy_models.py` 与 `hex_routes.py` 的 `SessionUpdate` 增加 `is_archived: Optional[bool] = None`；`legacy_session_routes.update_session`（及 hex handler / `SessionService`）映射 `is_archived` → 1/0。
2. **IPC**：`electron/commandRoutes/sessions.ts` 的 `session_update.body()` 增加 `if (a.isArchived != null) body.is_archived = a.isArchived;`。
3. **UI**：`SessionItem` hover 操作区增加归档按钮（`Archive` 图标），`running/suspended` 状态下禁用（与 `archive_stale` 的跳过策略保持一致）；点击调用 `sessionApi.setArchived(id, true)` 后 `updateSession(id, { is_archived: true })`，默认视图下条目立即消失，toast「已归档」。
4. `ConversationsSection` 透传 `onArchive` 回调；i18n 增加 `session.archive` / `session.unarchive` / `session.archived_toast`。

### 3.4 归档视图闭环

1. **后端**：`GET /sessions` 增加 `archived: Optional[bool] = None` 查询参数：
   - 缺省 / `False` → 只返回未归档（保持现有调用方行为不变）；
   - `True` → 只返回已归档；
   - `SessionRepository.list()` 增加同名参数拼接 WHERE，默认行为不变。
   - 说明：hex 路径（`API_MODE=hex`，非生产默认）的 `SessionService.list_sessions` 仍只返回未归档会话；hex 的归档过滤随后续 parity 补齐（PATCH `is_archived` 已同步支持）。
2. **前端**：`ConversationsSection` 打开「归档」开关时按需拉取归档列表（`sessionApi.list({ archived: true, limit: 100 })`，必要时同样支持加载更多），维护局部 `archivedSessions` 状态，不污染全局 `sessions`（命令面板等调用方不受影响）。
3. 归档条目提供「恢复」按钮：`setArchived(id, false)` → 从局部列表移除 → `onRefreshSessions()`；「清空全部归档」按钮在归档列表加载完成后按实际数量启用。
4. 自动归档 sweep 成功后若归档数 > 0，给出轻量 toast（如「已自动归档 N 个会话」），避免会话无声消失。

## 4. 涉及文件

| 层 | 文件 | 变更 |
|---|---|---|
| 后端 | `backend/api/legacy_models.py` | `SessionUpdate` 增加 `is_archived` |
| 后端 | `backend/api/legacy_session_routes.py` | PATCH 映射 `is_archived`；GET 增加 `archived` 参数 |
| 后端 | `backend/api/hex_routes.py` / `backend/application/services/session_service.py` | 同口径 parity |
| 后端 | `backend/data/session_repo.py` | `list()` 增加 `archived` 过滤参数 |
| IPC | `electron/commandRoutes/sessions.ts` | `session_update` 透传 `isArchived`；`list_sessions` 透传 `archived` |
| 前端 | `src/shared/api/sessionApi.ts` | `list()` 支持 limit/offset/archived |
| 前端 | `src/shared/lib/store.ts` | 分页状态 + `loadMoreSessions()` |
| 前端 | `src/widgets/sidebar/SiderSection.tsx` | 增加 `fill` / `boundedScroll` 两种语义，删除「只钳高度不滚动」中间态 |
| 前端 | `src/widgets/sidebar/sections/ConversationsSection.tsx` | 去 maxHeight、独立滚动面板、归档视图按需拉取、滚动加载 |
| 前端 | `src/widgets/sidebar/sections/SidebarProjectList.tsx` | 恢复 `boundedScroll`（30vh + 内层滚动） |
| 前端 | `src/widgets/layout/Sidebar.tsx` | nav 改为 flex 布局不滚动，conversations wrapper `flex-1 min-h-0` |
| 前端 | `src/widgets/session/VirtualSessionList.tsx` | 通过 `scrollElementRef` 绑定分区滚动面板（列表位于面板顶部，无 `scrollMargin`）；保留独立使用时的自建滚动容器 |
| 前端 | `src/widgets/session/SessionItem.tsx` | 归档 / 恢复按钮 |
| 前端 | `src/shared/lib/i18n/locales/{zh,en}/...` | 归档相关文案 |

## 5. 实施步骤

- [x] M1 滚动修复：`SiderSection` 去掉 `maxHeight` 裁剪；`ConversationsSection` / `SidebarProjectList` 去参数；回归验证长列表在单一滚动容器内可达。
- [x] M2 分页：`sessionApi.list` 参数化 + store 追加加载 + 滚动触底加载 + 单飞行锁；验证 >100 条会话可完整加载。
- [x] M3 手动归档链路：后端模型/路由、IPC 透传、`SessionItem` 归档按钮（运行中禁用）、store 原地更新。
- [x] M4 归档视图闭环：`GET /sessions?archived=true`、按需拉取归档列表、恢复按钮、清空归档可用、自动归档 toast。
- [x] M5 布局落地：`SiderSection` 的 `fill` / `boundedScroll` 语义、会话分区独立滚动面板、项目分区内层滚动、小窗口 `min-height` 验证；`>120` 条时验证虚拟列表滚动、分组头、高亮正确。
- [ ] M6 测试补齐与 CI 全绿；cherry-pick 到 `release/win7` 并跑 py3.8 兼容检查。

## 6. 测试与验证

- 后端单测：`SessionRepository.list(archived=...)`；PATCH `is_archived`（归档/恢复/404）；GET `archived=true`。
- Electron：`commands.test.ts` 校验 `session_update` body 带 `is_archived`、`list_sessions` 带 `archived` 参数。
- 前端：`SessionItem` 归档按钮（含 running 禁用）；`ConversationsSection` 归档视图拉取/恢复/清空；分页触底加载；`VirtualSessionList` 外层滚动容器；更新 `SiderSection.test.tsx` 审计快照。
- 手工验证：造 150+ 条会话 → 侧栏滚动到底可见全部、无裁剪；手动归档条目从默认视图消失、在归档视图出现并可恢复；自动归档后归档视图可见。
- 门禁：ruff、tsc、eslint、vitest 全量、pytest 相关子集；win7 侧 `py38-compat` 检查。

## 7. 风险与依赖

| 风险 | 说明 | 缓解 |
|---|---|---|
| 小窗口会话区过小 | 项目分区 30vh + 其他分区挤压会话区高度 | 会话区 `min-height`；项目分区可折叠；nav `overflow-y-auto` 兜底 |
| `scrollMargin` 抖动（仅备选方案 A） | 分区折叠动画会影响列表偏移 | 仅在改选 A 时需要：`ResizeObserver` 重算 + 动画结束后校正 |
| 分页与删除/归档竞态 | offset 分页在并发变更下可能漏条/重条 | 追加时按 id 去重；刷新时按已加载条数拉取 |
| 归档会话仍在运行 | 手动归档运行中会话会导致提醒/流不可见 | UI 禁用 `running/suspended` 归档（与自动归档策略一致） |
| win7 分支差异 | pydantic v1 模型字段与 py3.8 语法 | 仅用 `Optional[bool]` 等 v1 兼容写法；cherry-pick 后跑 py38 检查 |

## 8. 双分支同步

1. 在 `main` 建 `fix/session-list-scroll-archive` 分支实施并合并。
2. cherry-pick 到 `release/win7`，`SessionUpdate` 使用 pydantic v1 写法；不修改 `requirements*.txt`。
3. 两个分支分别按各自 architecture-baseline / coverage 阈值跑门禁。

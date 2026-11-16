# 启动分层就绪与后台自检（Progressive Readiness）

## 背景与目标

PR #2976 / #2981 / #2985 / #3002 把约 20 个非关键服务移出 lifespan 关键路径，
并把大量重依赖（docx/openpyxl/pandas/sqlite_vec/tools 导出）改为惰性导入，
冷启动显著变快。但随之暴露出一类体验问题：

1. **"就绪"只有一档**：`GET /health/proof` 只证明进程存活与归属正确，
   不代表数据库/会话/聊天/MCP 等模块可用；懒模块首次被请求时才导入，
   成败与耗时全局不可见。
2. **感知断点**：`backend:starting` 事件在渲染层订阅之前发出、`did-finish-load`
   不重放，冷启动时横幅大概率丢失；会话列表没有 loading 态，
   `sessions.length === 0` 直接显示"尚无会话"，与真实空态不可区分——
   用户把"还在加载"误判为"程序出错/数据丢失"。
3. **关键路径仍重**：ChatService 装配中 `register_all_tools()` 全量导入
   100+ 工具，且 `pool.ensure_discovered()` 同步阻塞（每服务器默认 30s
   超时，最坏 35s+）直接推迟 `yield`。
4. **不可观测**：`last-run.json` 只记录到 `first_paint`，没有
   backend_spawned / backend_ready / sessions_loaded，无法回答
   "窗口出现后会话列表多久可用"。

目标：保留懒加载，把"就绪"从全局布尔升级为**分层就绪（L0–L3）+ 逐模块状态 +
后台自检**，让用户始终知道"现在能用什么、还在加载什么、什么坏了"。

参考的主流实践：GOAT ADR-0025（progressive single-flight startup：
`launching → restoringLocalState → connectingServices → ready`，
ready ≠ 所有可选服务健康，逐子系统发布终态，禁止把初始空数组当空数据）、
Claude Code 三段式引导 + ready 后 deferred prefetch、Cherry Studio 渐进渲染
（防闪烁延迟 + 骨架 + 稳定快照）、opencode 启动状态机（每阶段定时器，
超时展示部分应用而非无限 splash）。

## 非目标

- 不改 `include_router` 为按需挂载（路由静态挂载保留，惰性继续用 PEP 562 模式）。
- 不引入 SSE/WebSocket 推送，沿用 500ms–1s 轮询 + IPC 广播。
- 不做 uvicorn preload / multi-worker。
- 不重构 deferred 为完全并发的依赖图（只做状态上报 + 单体任务保留）。
- 不做 LLM 联网探活（避免启动期产生 API 调用/费用），只做配置存在性检查。

## 就绪分层

| 层级 | 定义 | 模块 |
| --- | --- | --- |
| L0 外壳 | 窗口出现、Layout/侧栏骨架可见 | （既有 first-paint 放行，不改） |
| L1 最小可用 | 可浏览历史：db、记忆、会话/设置/模型目录路由 | database, memory, sessions |
| L2 对话可用 | 可发消息：ChatService、LLM 端点已配置 | chat_service, llm |
| L3 完整就绪 | 后台服务全部到达终态（ready/degraded/failed 均算终态） | mcp（逐服务器）, scheduler, todo, review_queue, wake_scheduler, gateways, design_studio, multi_agent, storage, arena |

## 技术方案

### 1. 后端 StartupRegistry（新模块 `backend/services/startup_status.py`）

进程级单例，纯内存、线程安全（`threading.Lock`），不做 IO：

```python
STATE_PENDING / STATE_WARMING / STATE_READY / STATE_DEGRADED / STATE_FAILED

MODULE_LAYERS: Dict[str, int]  # 模块 → 层级（1/2/3）

class StartupStatusRegistry:
    def declare(self, name: str, layer: Optional[int] = None) -> None
    def mark(self, name: str, state: str, detail: Optional[Dict[str, Any]] = None) -> None
    def snapshot(self) -> Dict[str, Any]

def get_startup_status() -> StartupStatusRegistry  # 单例
def mark_module(name: str, state: str, detail: Optional[Dict[str, Any]] = None) -> None
def declare_all_modules() -> None
```

`snapshot()` 输出：

```json
{
  "status": "warming",            // warming | ready | degraded
  "phase": "L1",                  // 已完整到达的最高层
  "boot_ms": 2345,
  "modules": {
    "database": {"state": "ready", "layer": 1, "elapsed_ms": 812, "detail": null}
  },
  "warmup": {"done": 4, "total": 12}
}
```

分层判定：L1 完成 = 所有 layer≤1 模块 ready；L2 完成 = 所有 layer≤2 ready；
L3 完成 = 所有已声明模块均为终态（ready/degraded/failed 都算终态）。
`status`：未到 L3 为 `warming`；到达 L3 且存在 degraded/failed 为 `degraded`；
否则 `ready`。

### 2. `GET /health/ready`（公开路径）

- 加入 `backend/api/local_auth.py` 的 `_PUBLIC_PATHS`（与 `/health` 同级的
  低开销探测；只读内存快照，不做 IO，保持 `/health` 的 P99 约束）。
- 返回 `snapshot()` 内容。

### 3. 关键路径与懒加载改动

- **MCP 发现后台化**：`register_mcp_tools(registry)` 改为
  `pool.track_registry(registry)` + `pool.ensure_synced()` 后立刻返回，
  首次发现由 daemon 线程执行（新增 `McpServerPool.start_background_discovery()`）。
  `_discover_record` 在服务器 READY 时已通过 `_register_server_tools`
  向已跟踪 registry 扇出工具，因此工具会在后台陆续出现，无需重启。
  `validate_profile_tools` 已把 `mcp__*` 视为动态引用（仅告警），安全。
- **MemoryAdapter 复用**：lifespan 已建 `app.state.memory_port`，
  `_build_chat_service` 增加 `memory_port=None` 参数复用之，避免二次
  VectorStore 初始化。
- 关键路径各阶段 `mark` 状态：database / memory / sessions / chat_service /
  llm（配置存在性）。
- deferred 各服务（scheduler/todo/review_queue/wake_scheduler/gateways/
  design_studio/multi_agent/arena）在现有 try/except 中上报
  warming → ready 或 degraded。
- `mcp` 模块由 deferred 中的 `_watch_mcp_discovery()` 协程轮询
  `pool.status_report()`（1s 间隔、60s 上限），把逐服务器状态写入
  detail，全部终态后标记 ready/degraded。
- `storage` 模块：检查用户数据目录磁盘剩余空间（<500MB 记 degraded）。

### 4. Electron 主进程

- 新增 IPC：
  - `sage:backend-lifecycle`（invoke）→ `{ lifecycle, generation }` 快照，
    修复"事件先于订阅丢失"的竞态。
  - `sage:backend-startup-status`（invoke）→ 最近一次 `/health/ready` 快照。
  - `sage:boot:stage`（send，白名单 `sessions_loaded` / `messages_loaded` /
    `settings_loaded`）→ `markBootStage(stage)`。
- 新增阶段标记：`backend_spawned`（spawn 后）、`backend_ready`
  （waitForBackend 成功处）。
- 后端 ready 后启动 `/health/ready` 轮询（1s，L3+3s 或 120s 上限停止；
  每次快照广播 `backend:startup-status`；后端重连后重启轮询）。
- preload 暴露 `getBackendLifecycle()` / `getBackendStartupStatus()` /
  `reportBootStage(stage)`；类型写入 `src/shared/types/electron-api.d.ts`。

### 5. 前端

- **会话列表三态**：`store` 增加 `sessionsLoading` / `sessionsError`；
  `loadSessions` 单飞去重、失败写错误；`ConversationsSection` 增加
  loading 骨架（≥160ms 防闪烁后出现，`data-testid="sessions-loading"`）、
  错误 + 重试（`sessions-error-retry`）；仅 `!loading && !error` 时显示空态。
- **恢复上次会话**：`AppStartupRestore` 恢复成功后若仍在 `/welcome`
  则 `navigate('/chat')`（深链不受影响）。
- **启动状态指示**：`src/shared/lib/startupStatus.ts`（订阅
  `backend:startup-status` + 初始快照）；`StartupStatusIndicator` 组件
  在 Layout 渲染：warming 时显示"正在加载会话与后台服务（n/m）"，
  degraded 时常驻"N 项功能降级"并可展开逐模块详情，L3 且无降级时隐藏。
- **业务埋点**：首次 `list_sessions` 成功 → `performance.mark` +
  `reportBootStage('sessions_loaded')`；首次 `get_messages` 成功 →
  `messages_loaded`；settings 加载完成 → `settings_loaded`。

### 6. 文档

- 新增 `docs/technical/159-startup-progressive-readiness.md`，README 索引补行。
- 用户手册补"启动状态提示"说明。
- 实现完成后删除本计划文件（并入技术手册，按仓库文档规范）。

## 涉及文件

| 文件 | 改动 |
| --- | --- |
| `backend/services/startup_status.py` | 新增：注册表 + 快照 |
| `backend/main.py` | declare/mark 各阶段；`_watch_mcp_discovery`；磁盘检查；`/health/ready` |
| `backend/api/local_auth.py` | `_PUBLIC_PATHS` 加 `/health/ready` |
| `backend/mcp/pool.py` | `start_background_discovery()` |
| `backend/mcp/tool.py` | `register_mcp_tools` 非阻塞化 |
| `electron/main.ts` | IPC、阶段标记、`/health/ready` 轮询与广播 |
| `electron/preload.ts` | 新桥方法 |
| `src/shared/types/electron-api.d.ts` | 类型 |
| `src/shared/lib/store.ts` | sessionsLoading/sessionsError/单飞/埋点 |
| `src/shared/lib/startupStatus.ts` | 新增：启动状态订阅 |
| `src/widgets/layout/Sidebar.tsx` | 透传三态与重试 |
| `src/widgets/sidebar/sections/ConversationsSection.tsx` | 骨架/错误/空态 |
| `src/widgets/system/BackendStatusBanner.tsx` | 挂载时查 lifecycle 快照 |
| `src/widgets/system/StartupStatusIndicator.tsx` + CSS | 新增：状态指示 |
| `src/widgets/layout/Layout.tsx` | 挂载状态指示 |
| `src/App.tsx` | 恢复后回跳 `/chat`、settings 埋点 |
| `architecture-baseline.json` | main.py / electron/main.ts 行数补账（按本分支实测） |

## 实施步骤

### M1 感知修复（P0）

- [ ] `store.loadSessions` 单飞 + `sessionsLoading` / `sessionsError` + 首次成功埋点
- [ ] `ConversationsSection` loading 骨架（防闪烁）/ 错误重试 / 空态三态
- [ ] `Sidebar` 透传三态
- [ ] `AppStartupRestore` 恢复后从 `/welcome` 回跳 `/chat`
- [ ] Electron `sage:backend-lifecycle` + preload + 类型 + Banner 挂载查询
- [ ] 前端测试：store 三态/单飞、会话区骨架与错误、Banner 快照

### M2 分层就绪（P1）

- [ ] `startup_status.py` + 单元测试（状态机/分层判定/快照）
- [ ] `/health/ready` + `local_auth` 白名单 + 端点测试
- [ ] 关键路径 mark（database/memory/sessions/chat_service/llm）
- [ ] deferred 各服务的 mark 与 degraded 语义
- [ ] MCP 后台发现（pool + tool.py）+ 单元测试（不阻塞、扇出）
- [ ] `_watch_mcp_discovery` + 磁盘 `storage` 检查
- [ ] `_build_chat_service(memory_port=...)` 复用，消除双构造
- [ ] Electron `/health/ready` 轮询 + `backend:startup-status` + 快照 getter
- [ ] 阶段标记 `backend_spawned` / `backend_ready` / `sage:boot:stage`
- [ ] 前端 `startupStatus` + `StartupStatusIndicator` + 测试
- [ ] `messages_loaded` / `settings_loaded` 埋点

### M3 文档与收尾

- [ ] 技术手册 §159 + README 索引 + 用户手册条目
- [ ] architecture-baseline 实测补账（区分 win7/main 基线）
- [ ] 全量相关测试：后端 pytest（相关子集 + 全量）、前端 vitest、ruff、py38 gate
- [ ] 删除本计划文件，提交 PR（→ release/win7，合并后 cherry-pick main）

## 验收标准

1. 后端 ready 后，`GET /health/ready` 在 L1 阶段返回 database/memory/sessions
   均为 ready；MCP 慢服务器不阻塞 `/health` 与 `/health/ready` 响应。
2. 冷启动窗口出现后，侧栏在数据返回前显示骨架而非"尚无会话"；
   后端排队期间无"空列表"误导；失败时显示重试。
3. `backend:starting` 竞态下 Banner 仍显示"后端服务正在启动…"。
4. 有上次会话时冷启动直接恢复到 `/chat`（深链行为不变）。
5. 后台服务加载过程中侧栏状态指示显示进度，全部完成后自动消失；
   存在降级模块时常驻并可查看逐模块详情。
6. `last-run.json` 包含 backend_spawned → backend_ready → first_paint →
   sessions_loaded 的完整瀑布。
7. 既有测试不回归（后端环境性存量失败除外）；ruff / py38 gate / 架构棘轮通过。

## 风险评估与依赖

| 风险 | 评估 | 缓解 |
| --- | --- | --- |
| MCP 后台发现导致首条消息缺少 MCP 工具 | 中 | READY 后扇出已有设计；状态指示明示 MCP 加载中；失败可重试 |
| 后台线程在测试环境留进程 | 中 | daemon 线程 + 既有 shutdown_all；单测用 mock client 不 spawn |
| `/health/ready` 增加轮询开销 | 低 | 只读内存、1s 间隔、L3 后停止 |
| py38 兼容 | 中 | 禁用 PEP 604/585；`typing.Dict/List/Optional` |
| 架构棘轮行数红线 | 低 | 按分支实测更新 `architecture-baseline.json` |
| 事件丢失类竞态复发 | 低 | 一律提供"快照查询 + 事件订阅"双通道 |

## 回滚策略

- 后端：`/health/ready` 为独立端点；mark 调用失败时注册表保持默认态，
  不影响启动（所有 mark 包裹 try/except 或 mark 本身不抛）。
- MCP 后台化：保留 `ensure_discovered()` 同步 API，必要时一行切回。
- 前端：三态与状态指示为增量 UI，无数据路径变更。

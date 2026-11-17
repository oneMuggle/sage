# 启动分层就绪与后台自检（Progressive Readiness）

> 懒加载加速了冷启动，但"启动完成"不再是一个瞬间：窗口出现、会话可用、
> 对话可用、后台服务就绪是四个不同的时间点。本文档描述如何把"就绪"从
> 一个全局布尔值升级为**分层就绪（L0–L3）+ 逐模块状态 + 后台自检**，
> 让用户始终知道"现在能用什么、还在加载什么、什么坏了"。

---

## 1. 背景

PR #2976 / #2981 / #2985 / #3002 把约 20 个非关键服务移出 lifespan 关键
路径、把重依赖改为惰性导入，冷启动显著变快。随之暴露的四类问题：

1. `/health/proof` 只证明进程存活与归属正确，不代表任何业务模块可用；
   懒模块首次被请求时才导入，成败不可见。
2. `backend:starting` 事件在 renderer 订阅之前发出、页面加载后不重放，
   冷启动时状态横幅丢失；会话列表没有 loading 态，空数组直接渲染成
   "尚无会话"，与真实空态不可区分——用户误判为程序出错/数据丢失。
3. ChatService 装配中 `register_all_tools()` 全量导入 100+ 工具，且
   `pool.ensure_discovered()` 同步阻塞（每服务器默认 30s 超时），直接
   推迟 uvicorn 开始收请求。
4. `last-run.json` 只记录到 `first_paint`，无法回答"窗口出现后会话列表
   多久可用"。

## 2. 层级模型

| 层级 | 定义 | 模块 |
| --- | --- | --- |
| L0 外壳 | 窗口出现、Layout/侧栏骨架可见 | 既有 first-paint 放行 |
| L1 最小可用 | 可浏览历史：数据库/记忆/会话路由 | database, memory, sessions |
| L2 对话可用 | 可发消息：ChatService 装配完成、LLM 端点已配置 | chat_service, llm |
| L3 完整就绪 | 后台服务全部到达终态（ready/degraded/failed 均算终态） | mcp（逐服务器）, scheduler, todo, review_queue, wake_scheduler, gateways, design_studio, multi_agent, arena, storage |

`phase` = 已完整到达的最高层；所有模块终态后固定为 `L3`，此时
`status` 为 `ready`（无降级）或 `degraded`（存在 degraded/failed）。

## 3. 后端

### 3.1 StartupRegistry（`backend/services/startup_status.py`）

进程级单例、纯内存、`threading.Lock` 保护、零 IO：

- 状态机：`pending → warming → ready | degraded | failed`；
- 每个模块记录 `state / layer / started_at / finished_at / detail`；
- `snapshot()` 输出（毫秒整数）：

```json
{
  "status": "warming",
  "phase": "L1",
  "boot_ms": 2345,
  "modules": {
    "database": {"state": "ready", "layer": 1, "elapsed_ms": 812, "detail": null}
  },
  "warmup": {"done": 4, "total": 15}
}
```

`mark_module()` 吞掉一切异常——状态上报永远不得反噬启动流程。

### 3.2 `GET /health/ready`

- **需要本地授权**（与其它 API 一致，Electron 轮询时注入
  `X-Sage-Local-Authorization`）：快照的 `detail` 含逐模块错误原文
  （命令路径、磁盘余量等），因此**不**加入 `_PUBLIC_PATHS`；
  `/health`、`/health/proof` 仍保持公开的低开销探针。
- 只读内存快照、不触碰 SQLite；Electron supervisor 以 1s 间隔轮询，
  渲染层不直接访问该端点。

### 3.3 上报点

关键路径（`yield` 之前）：

| 模块 | 时机 |
| --- | --- |
| database | lifespan 开始 `warming`；`init_db()` + 回填/种子完成后 `ready` |
| sessions | 与 database 同步 `ready`（路由在模块导入期静态挂载） |
| memory | `MemoryAdapter` 构造前 `warming`，构造后 `ready` |
| chat_service | `_build_chat_service` 前 `warming`，装配完成 `ready`；异常 `failed` |
| llm | 装配后探测 endpoint 配置（不发网络请求）：已配置 `ready`；未配置 `ready + detail.configured=false` |

deferred 后台任务（`yield` 之后）：scheduler / todo / review_queue /
wake_scheduler / gateways / design_studio / multi_agent / arena 各自
`warming → ready|degraded`；`_finalize_pending_modules()` 在 deferred
结束时把仍未终态的模块标为 degraded，保证 L3 可达。**`mcp` 例外**：它由
独立的后台观察协程负责（自身保证 90s 内终态），不被 finalize 提前改写。
注册表同时拒绝"终态 → warming"回退，避免 phase 从 L3 倒退。

首次安装**未配置 LLM** 是正常状态而非降级：`llm` 与 `design_studio`
分别以 `ready + detail.configured=false` 上报，不产生"功能降级"假警报。

### 3.4 MCP 后台发现

- `register_mcp_tools(registry)` 不再同步 `ensure_discovered()`：
  先 `track_registry` + `ensure_synced`，再
  `McpServerPool.start_background_discovery()` 启动 daemon 线程，立即返回。
- 服务器到达 READY 时 `_discover_record` 调 `_register_server_tools`，
  向所有已跟踪 registry 扇出工具——与 REST 动态添加服务器同一机制，
  无重启、无二次注册。
- `_watch_mcp_discovery()` 协程（deferred）每 1s 读取
  `pool.status_report()`，把逐服务器状态写入 `mcp` 模块 detail；
  全部终态（ready/failed/disabled）时标记 ready/degraded；90s 上限。
- 风险兜底：首条消息可能早于 MCP 工具就绪（状态条会提示"MCP 服务
  加载中"）；`validate_profile_tools` 把 `mcp__*` 视为动态引用，仅告警。

### 3.5 磁盘自检

`deferred` 开始时 `shutil.disk_usage(用户数据目录)`：剩余 <500MB 记
`storage=degraded`，否则 ready。

## 4. Electron Supervisor

### 4.1 启动瀑布（`last-run.json`）

新增阶段：`backend_spawned`（spawn 后）、`backend_ready`
（`/health/proof` 通过处）、`sessions_loaded` / `messages_loaded` /
`settings_loaded`（渲染层经 `sage:boot:stage` 上报，主进程白名单校验）。
组合 `window_shown` / `first_paint` 即可得到完整启动瀑布。

### 4.2 就绪状态轮询（`electron/startupStatus.ts`）

- 后端 ready 后 1s 间隔 GET `/health/ready`（带本地授权头），广播
  `backend:startup-status`；L3 后再保持 3s 收尾即停；120s 硬上限；
  后端自动重启重连后重新开始。
- 轮询周期带 epoch：停止/重启后 in-flight 请求的过期结果会被丢弃；
  L3 收尾定时器为模块级，重启不会残留旧定时器杀掉新周期。
- 后端停止/重启/永久失败时立即停止轮询并清空快照。
- `sage:backend-startup-status`（invoke）返回最近一次快照——与事件
  订阅互补，避免"事件先于订阅"竞态。

### 4.3 IPC 通道

| 通道 | 类型 | 用途 |
| --- | --- | --- |
| `sage:backend-lifecycle` | invoke | `{lifecycle, generation}` 快照（Banner 竞态兜底） |
| `sage:backend-startup-status` | invoke | 最近一次 `/health/ready` 快照 |
| `backend:startup-status` | event | 逐模块 warmup 进度广播 |
| `sage:boot:stage` | send | 渲染层阶段埋点（白名单） |

## 5. 前端

### 5.1 会话列表三态

`store` 新增 `sessionsLoading`（初始 `true`）与 `sessionsError`；
`loadSessions` 单飞去重（Sidebar 挂载与 `backend:ready` 重放会并发触发）。
`ConversationsSection`：

- loading：超过 160ms 防闪烁阈值后显示骨架（`sessions-loading`）；
- error：`sessions-error` + 重试按钮（`sessions-error-retry`）；
- empty：仅 `!loading && !error` 时显示"尚无会话"。

### 5.2 启动状态指示

`StartupStatusIndicator`（挂载于 Layout，`EndpointStatusBanner` 下方）：

- warming：`正在加载后台服务（done/total）` + 细进度条；
- L3 且无降级：自动隐藏；
- L3 且存在降级：常驻 `N 项功能降级：<模块名>`，悬停显示逐模块状态。

数据源：挂载时 `getBackendStartupStatus()` 初始快照 +
`backend:startup-status` 事件。Web 模式无桥时静默不显示。

### 5.3 其他感知修复

- `BackendStatusBanner` 先订阅事件、再查 `getBackendLifecycle()` 快照，
  冷启动不再丢失"后端服务正在启动…"。
- `AppStartupRestore` 恢复上次会话后，若仍停留在 `/welcome` 则回跳
  `/chat`（深链 `?session=` 行为不变）。恢复期间用户已明确"新建会话"
  （`startupRestoreGuard.suppressStartupSessionRestore()`，由
  `createSession` / Sidebar 新建入口触发）或在欢迎页输入框打字时，
  尊重用户动作、不回跳。

## 6. 验证

| 项 | 位置 |
| --- | --- |
| 注册表状态机/分层判定 | `backend/tests/unit/test_startup_status.py` |
| `/health/ready` 形状与公开路径 | `backend/tests/integration/test_health.py`、`backend/tests/test_web_auth.py` |
| MCP 后台发现（不阻塞 + 扇出 + 幂等） | `backend/tests/unit/mcp/test_mcp_pool.py::TestBackgroundDiscovery` |
| `/health/ready` 轮询解析 | `electron/__tests__/startupStatus.test.ts` |
| 会话三态 / 骨架防闪烁 | `src/shared/lib/__tests__/store.test.ts`、`ConversationsSection.test.tsx` |
| Banner 快照兜底 | `src/widgets/system/__tests__/BackendStatusBanner.lifecycle-snapshot.test.tsx` |
| 状态指示 warming/降级/隐藏 | `src/widgets/system/__tests__/StartupStatusIndicator.test.tsx` |

## 7. 约束与兼容

- **py38**：新增后端代码不使用 PEP 604/585，`scripts/check_py38_compat.py` 通过。
- **`/health` P99**：`/health/ready` 与 `/health` 一样只读内存，不引入 IO。
- **Web 模式**：无 electronAPI 桥时状态指示与 lifecycle 快照均静默降级。
- **架构棘轮**：`backend/main.py`、`electron/main.ts` 等行数上限已按本分支实测更新。

## 8. 后续可选项

- router 层惰性化（按 `/health/ready` 实测数据决定是否必要）。
- LLM 端点联网探活（避免启动期 API 调用，当前只做配置存在性检查）。
- deferred 服务拆分并发依赖图（当前保留单体任务，仅逐项上报状态）。

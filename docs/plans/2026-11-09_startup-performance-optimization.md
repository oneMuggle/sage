# Sage 启动性能优化方案

> 创建日期: 2026-11-09
> 分支: `feat/startup-performance-optimization`
> 状态: Phase 1-3 + 启动阻塞修复已完成，Phase 4-6 待实施

## 背景与目标

Sage 当前启动时间 **50-90 秒**(冷启动),远超主流 AI 桌面应用(ChatGPT/Claude Desktop 2-5秒,Cursor 3-8秒)。
核心瓶颈是 Python 后端冷启动:conda 环境加载 + FastAPI 模块导入 + 数据库初始化 + 非关键服务串行启动。

**目标**: 生产环境首屏时间 < 10 秒(用户可交互),完整就绪 < 30 秒。

## 当前启动流程(现状)

### Electron 主进程(main.ts)

```
t=0s    app.whenReady()
t=0.1s  createSplashWindow()
t=0.2s  spawnBackend() → Python 子进程
t=0.2s  waitForBackend() 开始轮询 /health/proof (间隔 500ms, 超时 90s)
        ↓
        [Python 后端冷启动 50-90s]
        ↓
t=50-90s 后端就绪 → backendLifecycle = 'ready'
t=50-90s createMainWindow() → 加载前端
t=51-91s closeSplashWindow() → 用户看到 UI
```

**问题**: 用户要等 50-90 秒才能看到任何 UI(splash 除外)。

### Python 后端(main.py lifespan)

```
t=0s      uvicorn 启动 → 模块导入(30+ routers)
t=5-15s   模块导入完成 → lifespan() 开始
t=15-20s  db.init_db() 完成(有 _elapsed_db 日志)
t=20-40s  scheduler / evolution / syncer 等非关键服务串行初始化
t=40-60s  lifespan yield → 接受请求
```

**测量点**: `[sage-startup]` 日志前缀,`_startup_t0 = time.monotonic()`。

## 优化方案(按优先级)

### Phase 1: 并行启动前端(用户体验立即提升)

**原理**: 当前架构是"后端就绪 → 创建主窗口",优化为"立即创建主窗口 → 后台等后端"。

**改动范围**: `electron/main.ts`

```typescript
// 当前: sequential
const ready = await waitForBackend();  // 阻塞 50-90s
createMainWindow();                     // 用户终于看到 UI

// 优化: parallel
createMainWindow();                     // 立即显示 UI(带加载态)
const ready = await waitForBackend();   // 后台等待
if (ready) mainWindow.send('sage:event:backend:ready');
```

**前端改动**: `BackendStatusBanner` 组件已有"starting..."状态,需确保初始状态为"connecting"。

**预期收益**:
- 用户感知启动时间: 50-90s → **2-3s**(看到 UI,后端在后台加载)
- 对开发环境:**同样有效**(改 electron/ 时不再等后端)

**实施步骤**:
- [x] 1.1 修改 `app.whenReady()` 流程:先 `createMainWindow()` 再 `waitForBackend()`
- [x] 1.2 主窗口初始加载态:显示"连接后端..."占位符（BackendStatusBanner 已有 starting 状态）
- [x] 1.3 后端就绪后发 `sage:event:backend:ready` IPC（已有 backend:starting/backend:ready 事件）
- [x] 1.4 前端监听事件:清除加载态,触发数据刷新（BackendStatusBanner 已监听所有事件）

---

### Phase 2: 延迟加载非关键服务(后端启动提速 30-40%)

**原理**: `lifespan()` 中串行初始化大量非关键服务(scheduler、evolution、syncer、webhook),
这些服务在首屏渲染完成前不需要就绪。

**改动范围**: `backend/main.py` lifespan 函数

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # 关键路径:只加载首屏必需的
    db.init_db()                          # 必须
    await init_auth()                     # 必须
    
    # 非关键服务:fire-and-forget
    asyncio.create_task(init_scheduler())
    asyncio.create_task(init_evolution_tasks())
    
    yield  # 立即接受请求
    
    # cleanup...
```

**预期收益**:
- 后端启动时间: 50-90s → **15-25s**(只加载核心 API)
- 对开发环境:**有效**(uvicorn --reload 也会受益)

**实施步骤**:
- [x] 2.1 分析 lifespan 各步骤耗时(已有 `[sage-startup]` 日志,需补全)
- [x] 2.2 识别非关键服务:scheduler / evolution / syncer / webhook / zotero
- [x] 2.3 用 `asyncio.create_task()` 包裹非关键初始化（`_deferred_startup_init` async fn, yield 后 `create_task` 启动）
- [x] 2.4 测试:确保首屏 API(聊天、会话列表)在延迟服务未就绪时仍可用

---

### Phase 3: Python 导入优化(后端启动提速 15-25%)

**原理**: `main.py` 顶部导入 30+ routers,部分 router 导入重模块(如 `zotero` 导入 PDF 解析库)。

**改动范围**: `backend/main.py` + 各 router 文件

```python
# 当前:顶部导入所有 router
from backend.api.zotero_routes import router as zotero_router  # 导入 PDF 解析库

# 优化:延迟导入
def get_zotero_router():
    from backend.api.zotero_routes import router  # 使用时才加载
    return router

# 或者:路由级延迟挂载
@app.get("/api/zotero/...")
async def zotero_endpoint():
    from backend.api.zotero_routes import handler  # 请求时才加载
    return await handler()
```

**更激进**: 使用 FastAPI 的 `include_router` 延迟挂载。

```python
# 非关键 router 在 lifespan yield 后挂载
async def mount_deferred_routers():
    from backend.api.zotero_routes import router as zotero_router
    app.include_router(zotero_router, prefix="/api/zotero")

asyncio.create_task(mount_deferred_routers())
```

**预期收益**:
- 模块导入时间: 10-15s → **3-5s**
- 对开发环境:**有效**(import 缓存,二次启动更快)

**实施步骤**:
- [x] 3.1 用 `python -X importtime -m backend.main` 测量各模块导入耗时
- [x] 3.2 识别重模块:`backend.tools` 包（1.90s）、`backend.core.legacy.agent` 链、`backend.wiki.mcp_server`、office/pandas 链
- [x] 3.3 对重模块改用延迟导入（PEP 562 惰性导出 + 调用点解析，见下方实测结果）
- [x] 3.4 测试:确保首屏不依赖的 API 延迟加载不影响核心功能（回归 + 冒烟见下方）

---

### Phase 4: uvicorn 预加载模式(后端启动提速 10-20%)

**原理**: 默认 uvicorn 在 worker 进程加载应用,预加载模式在主进程加载,减少重复导入。

**改动范围**: `electron/main.ts` spawnBackend()

```typescript
// 当前
spawn('uvicorn', ['backend.main:app', '--host', '127.0.0.1', '--port', '8765']);

// 优化:加 --preload
spawn('uvicorn', ['backend.main:app', '--host', '127.0.0.1', '--port', '8765', '--preload']);
```

**注意**: `--preload` 在单 worker 时效果有限(已默认预加载),多 worker 时收益明显。
Sage 当前是单 worker,此优化收益较小,但无副作用。

**预期收益**:
- 单 worker:**5-10%**
- 对开发环境:**无影响**(dev 模式不用 uvicorn)

**实施步骤**:
- [ ] 4.1 spawnBackend() 加 `--preload` flag
- [ ] 4.2 测试:确保预加载不破坏 conda wrapper pid 检测

---

### Phase 5: PyInstaller 打包(长期,后端启动提速 40-60%)

**原理**: conda 环境启动开销大(激活环境 + 加载 site-packages),PyInstaller 打包后直接运行可执行文件。

**改动范围**: 新增 `scripts/build-backend.sh` + `electron/main.ts`

```bash
# 打包
pyinstaller --onefile --name sage-backend backend/main.py

# 运行(不再需要 conda)
./dist/sage-backend
```

**预期收益**:
- 启动时间: 50-90s → **5-15s**
- 对开发环境:**无影响**(dev 仍用 conda)

**实施步骤**:
- [ ] 5.1 编写 `scripts/build-backend.sh`
- [ ] 5.2 测试 PyInstaller 打包所有依赖(特别是 Cython 扩展)
- [ ] 5.3 electron-builder 配置:打包 `dist/sage-backend` 到 resources
- [ ] 5.4 spawnBackend() 改用 `resources/sage-backend` 而非 `conda run`
- [ ] 5.5 回退方案:dev 模式仍用 conda,生产用 PyInstaller

**风险**:
- PyInstaller 打包 Python 3.10 + Cython 可能有兼容性问题
- 打包体积增加 ~50MB(嵌入 Python 运行时)
- 需要为 Win7 / macOS 分别打包

---

### Phase 6: Service Worker 缓存(二次启动加速)

**原理**: 前端静态资源走 Service Worker 缓存,二次启动时前端秒开。

**改动范围**: `src/sw.ts` + `vite.config.ts`

**预期收益**:
- 二次启动前端加载: 2-3s → **< 1s**
- 对开发环境:**无影响**(dev 模式不用 SW)

**实施步骤**:
- [ ] 6.1 引入 `vite-plugin-pwa`
- [ ] 6.2 配置 SW 缓存策略:Cache-First for assets, Network-First for API
- [ ] 6.3 测试:清除缓存后仍可用,更新时自动失效

---

## 优先级与时间线

| Phase | 预期收益 | 实施难度 | 对 dev 环境 | 时间线 |
|-------|---------|---------|------------|--------|
| **Phase 1** 并行启动前端 | 用户体验 50-90s → 2-3s | 低 | ✅ 有效 | 1-2天 |
| **Phase 2** 延迟加载非关键服务 | 后端 50-90s → 15-25s | 中 | ✅ 有效 | 3-5天 |
| **Phase 3** Python 导入优化 | 后端再减 15-25% | 中 | ✅ 有效 | 2-3天 |
| **Phase 4** uvicorn --preload | 后端再减 5-10% | 低 | ❌ 无影响 | 0.5天 |
| **Phase 5** PyInstaller 打包 | 后端 50-90s → 5-15s | 高 | ❌ 无影响 | 1-2周 |
| **Phase 6** Service Worker | 二次启动前端 < 1s | 中 | ❌ 无影响 | 3-5天 |

**推荐实施顺序**: Phase 1 → 2 → 3 → 4(短期,1-2周) → Phase 5(长期,2-3周) → Phase 6(可选)

**预期总收益**: 50-90s → **5-10s**(Phase 1-4 完成后)

## 测量与验证

### 实测结果（2026-11-09，Linux / sage-backend conda 环境）

后端单独启动（`-m backend.main`），worktree 端口 8892：

| 阶段 | 耗时 | 说明 |
| --- | --- | --- |
| 模块导入完成 | t=8.1s | 30+ router 顶层导入（Phase 3 目标） |
| `db.init_db()` | t=8.2s | 仅 +0.1s |
| **lifespan startup complete (before yield)** | **t=13.4s** | **优化后关键路径** |
| deferred init 完成 | t=13.5s | 非关键服务全部就绪（yield 后 ~0.1s） |

关键路径构成（13.4s 中约 5.3s 在 lifespan 内）：DB 初始化 → 备份恢复 → 孤儿清理 → 回填 → 种子数据 → 目录发现 → SecretBox 迁移 → 陈旧 run 恢复 → 审批上下文 → agent profiles → stream registry → scheduler 构造 → gates → orchestration observability → ChatService 装配 → harness recorder → 浏览器清扫。

**核心 API 可用性**（deferred init 前后均验证 200）：`/health`、`/api/v1/sessions`、`/api/v1/memory/list`、`/api/v1/todos`、`/api/v1/orchestration/board`。

**回归测试**：`backend/tests/` 中 scheduler/wake/arena/evolution/todo/review/design/gateway/orchestration/agent/permission_gate/question_gate/harness 相关子集 —— `2463 passed, 1 failed`。唯一失败 `test_curator_provenance.py::TestScheduleRegistration::test_factory_creates_task` 经 stash 对照确认为 **pre-existing 测试间污染**（原始 HEAD 代码同样 `1 failed, 2463 passed`）。

### Electron 端到端实测（2026-11-09，Linux，worktree，冷启动）

启动配置：Vite :1547，Electron 配 `SAGE_PYTHON`（绕开 conda wrapper pid mismatch）+ 独立 `SAGE_USER_DATA_DIR=/tmp/sage-measure/userdata`、`SAGE_LOG_DIR=/tmp/sage-measure`、`SAGE_DB_PATH=/tmp/sage-measure/db/sage.db`。

**Electron 主进程阶段（自 T0=process_start）：**

| 标记 | 自 T0 | 说明 |
| --- | --- | --- |
| `app_ready` | 0.7s | 主进程 ready |
| `window_created` | 21.1s | `createMainWindow()` 调用 |
| `window_shown` | **24.1s** | **用户首次看到主窗口**（含 "backend starting" 横幅） |
| `first_paint` | 61.0s | 渲染层首帧 |
| `main: backend ready` | **73.8s** | health 200，前端可交互 |

**后端关键路径（自模块加载起）：**

| 区间 | 耗时 | 说明 |
| --- | --- | --- |
| `t=0.0s` → `module load begin` | 0.0s | spawnBackend 启动 Python 子进程 |
| `t=0.0s` → `all module imports complete` | **34.5s** | **Python 顶层导入（冷缓存，Phase 3 目标）** |
| `t=34.5s` → `db.init_db() complete` | +1.9s | DB 初始化 |
| `t=36.7s` → `lifespan startup complete (before yield)` | +14.4s | **Phase 2 优化后的关键路径** |
| `t=51.1s` → `所有非关键服务初始化完成` | +0.2s | deferred init 完成（yield 后） |

**关键对比（优化前后）：**

| 指标 | 优化前（估算） | 优化后 | 变化 |
| --- | --- | --- | --- |
| 用户首次看到 UI | ~80s（等后端 ready 后才 createMainWindow） | **24.1s** | **3.3× 更快** |
| 后端关键路径就绪 | 50-90s（串行初始化） | **51.1s** 自模块加载起 / **14.4s** 自 db.init_db | 关键路径压到 lifespan 内 14.4s |
| 完全就绪（后端 ready） | ~90s | **73.8s** | 节省 ~16s |

**关键发现**：
1. **Python 导入 34.5s 是当前最大瓶颈**（占后端启动的 67%）—— 独立烟雾测试仅 8.1s 因为磁盘已热；桌面端通过 Electron spawn 走冷路径，导入时间 4×。Phase 3 是下一优先级。
2. **`runDoctorCheck()` 阻塞窗口创建 21.1s** —— 它当时在 `registerIpcHandlers()` 里同步 await；doctor 自己还要再起两个 Python 冷启动，跑满 20s 上限仍是 `status: "timeout"`（`main: doctor check complete | {'status':'timeout','elapsed_ms':20107}`），把 `createMainWindow()` 一起拖到 21.1s。
   > 更正：早前版本把这一项归因于 `startAgentBrowserHost()` 是错的 —— 内置浏览器 host 只在 Win7 启用，Linux 上 `embeddedBrowserEnabled` 为 false，不参与启动链路。
3. **Phase 1 并行启动工作正常** —— 窗口在 24.1s 即出现，前端显示 "backend starting" 横幅，后端在 73.8s 时 ready。用户不再面对空白 80s。
4. **Phase 2 延迟初始化工作正常** —— lifespan 关键路径 14.4s（vs 原始 50-90s 总启动），deferred init 在 yield 后 0.2s 内完成全部非关键服务。
5. **首次请求重试** —— 窗口出现后（24.1s）后端尚未就绪，前端自动重试（"请求失败，第 1 次重试"…），后端 ready 后恢复。`BackendStatusBanner` 显示连接中状态，符合预期。

### 启动阻塞修复与复测（2026-11-09 第二轮）

第一轮实测暴露三个与 Phase 1 目标冲突的问题，均已修复并复测：

| # | 问题 | 根因 | 修复 |
| --- | --- | --- | --- |
| 1 | `window_created` 要等 21.1s | `runDoctorCheck()` 在 `registerIpcHandlers()` 里同步 await，doctor 自己再起两个 Python 冷启动，跑满 20s 上限仍 `status: "timeout"` | 抽出 `runStartupDoctorCheck()`，在 `waitForBackend()` 之后 / SKIP_BACKEND 分支里 `kickStartupDoctorCheck()` 异步跑 |
| 2 | 假的 `backend health timeout` + 整轮 auto-retry | `isPortStillBoundByPid()` 外层只给 200ms，内层 `execFileSync` 自带 500ms 超时；冷启动 IO 压力下必然超预算，旧代码 `return false` 直接判失败 | 预算 200ms → 1500ms，且失败降级为 `warn` + 500ms 后 `continue` 重试（ownershipToken 已证明后端归属） |
| 3 | 主窗口出现后白屏 ~70s | 3s 兜底在 dev 模式必然先于 `ready-to-show` 触发；dev 下 Vite 要按需 transform 整个模块图（实测 70s+） | 主窗口改「有内容才显示」：`ready-to-show` 或渲染层 `first-paint` 任一满足才 `show()` + 关启动屏；兜底放宽到 dev 120s / 打包 15s。**不用 `dom-ready`**（实测早于首帧 2.6s，等于把白屏放回来） |

**复测结果（同一 worktree，Linux，冷启动）**

| 标记 | 修复前 | 修复后 | 说明 |
| --- | --- | --- | --- |
| `window_created` | 21.1s | **0.5s** | doctor 移出关键路径 |
| `window_shown` | 24.1s（白屏） | **27.5s（有内容）** | 触发源 `ready-to-show`；白屏消失 |
| `first_paint` | 61.0s | **28.2s** | 同机负载不同，仅作参考 |
| `backend ready` | 73.8s | 28.7s | 同上 |
| 假 `backend health timeout` | 1 次（紧接着 auto-retry 成功） | **0 次** | 端口重校验改为重试 |
| doctor check | 阻塞启动 20.1s | 后端就绪后 20.1s 异步 | 不再影响启动 |

两次运行都在同一台机器（另一 worktree 同时在跑 vitest，load average 21 → 8），绝对耗时不可跨轮比较；可比较的是**顺序与相对关系**：修复后 `window_created` 紧贴 `app_ready`，`window_shown` 与 `first_paint` 只差 0.7s（IPC/rAF 延迟），且窗口显示早于后端就绪（Phase 1 目标达成）。

**遗留（不在本次范围）**：

- doctor 的 20s 上限（`electron/doctor.ts: DEFAULT_TIMEOUT_MS = 20_000`）在冷缓存下必然超时 → `DOCTOR_LAST_FILE` 永远是 `status: "timeout"` 且无 summary，救援工具读不到有效报告。现在它已不阻塞启动，可以把上限提到 60s+ 让诊断真正产出结果。
- dev 模式 Vite 冷 transform 整个模块图（实测 60-76s）是**仅开发环境**的耗时；打包版走静态资源不受影响。若要进一步优化开发体验，需要 Vite 预热（`optimizeDeps.entries` / 预构建）。

### Phase 3 实测结果（2026-11-09，Linux / sage-backend conda 环境）

同一台机器、同一解释器，`python -X importtime -c "import backend.main"` 热缓存对照
（测量窗口内 load average 3.0–7.5，绝对值只可在同一窗口内比较）：

| 指标 | 基线（origin/main 代码） | Phase 3 后 | 变化 |
| --- | --- | --- | --- |
| `import backend.main` 累计 | 6.54s / 7.47s | **5.00s / 5.22s** | **−25%** |
| `sys.modules` 数量 | 2725 | **2471** | −254 个模块 |
| 后端 `/health` 就绪（独立启动，load 7.5） | — | 11.2s | — |

**移出导入关键路径的重模块**（导入完成后 `sys.modules` 探针）：

| 模块 | 基线 | Phase 3 后 |
| --- | --- | --- |
| `backend.tools`（~104 个 tool 子模块） | eager | 惰性（包导入 1.90s → 0.02s） |
| `backend.core.legacy.agent` | 加载 | **未加载**（首次聊天请求时解析） |
| `backend.tools.browser_tool` / `office_tool` | 加载 | **未加载** |
| `backend.wiki.mcp_server` | 加载 | **未加载**（`backend.wiki` 累计 736ms → 368ms） |

**改动清单**：

1. `backend/tools/__init__.py` — PEP 562 `__getattr__` + `_LAZY_TOOL_EXPORTS` 映射导出 104 个 tool 类；`register_all_tools()` 仍走 `tool_bundles` 显式导入。
2. `backend/core/lazy.py`（新增）— `load_attr()`：调用点惰性解析并缓存回调用方 `globals()`（函数体内的 `LOAD_GLOBAL` 不触发模块 `__getattr__`）；`module_getattr()`：PEP 562 `__getattr__` 的共用实现。
3. `backend/core/__init__.py` — 同样惰性导出，打断包初始化链。
4. `backend/api/legacy_routes.py`、`backend/api/legacy_chat_routes.py`、`backend/orchestration/subagent_runner.py` — `SageAgent` / `validate_against_schema` 改为调用点解析；同时保留模块级 `__getattr__`，使既有 `patch("...SageAgent")` 测试桩继续生效。
5. `backend/wiki/__init__.py` — 可选 MCP Server 导出惰性化。
6. `backend/main.py`、`backend/api/chat_stream_state.py`、`backend/data/database.py`、`backend/chat/attachment_resolver.py` — deferred imports（P3-1 jieba 预热 / P3-2 office 重模块）。

**回归验证**：

| 检查 | 结果 |
| --- | --- |
| `ruff check backend/` | All checks passed |
| `scripts/check_py38_compat.py` | 0 violations（win7 Python 3.8 兼容） |
| 单元测试（subagent_runner / session / watcher / chat_dispatcher / retry_resilience / m3 memory attribution） | 86 passed, 1 failed（pre-existing，见下） |
| 集成测试（patch `legacy_routes.SageAgent` 等）：sessions_crud / chat_agent_id / chat_errors / legacy_routes_execution_mode / auto_checkpoint | 25 passed, 7 skipped |
| 集成测试：chat_stream / attachment_injection_legacy / legacy_routes_step_persistence / project_context_injection / skip_workspace_binding / chat_title_generation | 40 passed |
| 冒烟：`/health`、`/api/v1/sessions`、`/api/v1/memory/list?page_size=1`、`/api/v1/todos` | 全部 200 |

唯一失败 `test_retry_resilience.py::test_run_lane_accepts_backoff_penetrates_mock_patch_wrapper`
在 origin/main 主 checkout 上同样失败（本环境 Python 3.10 下 `inspect.signature(AsyncMock)`
抛 `TypeError: 'Mock' object is not subscriptable` → `func_accepts_kwarg` 返回 False），
**pre-existing，与本 Phase 改动无关**。

**遗留**：热缓存下 5.0–5.2s 已达 Phase 3 目标区间（3–5s）上沿；冷缓存 Electron spawn
路径（基线 34.5s）的端到端降幅需在 Phase 4/5 完成后整体复测。

### 启动时间测量点

1. **Electron 主进程**:`logger.info('main: process started', { pid })` (已有)
2. **后端模块导入**:`[sage-startup] t=Xs module import complete`(需补充)
3. **后端 lifespan 完成**:`[sage-startup] t=Xs lifespan startup complete`(已有)
4. **前端首屏渲染**:`console.time('first-paint')` in `src/main.tsx`(需补充)
5. **用户可交互时间**:`sage:event:backend:ready` IPC 时间戳(Phase 1 后)

### 验证方法

```bash
# 冷启动测试(清除所有缓存)
rm -rf ~/.config/sage/cache
time npm run electron:dev

# 热启动测试(保留缓存)
time npm run electron:dev

# 后端启动时间
grep "\[sage-startup\]" ~/.config/sage/logs/*.log | tail -20
```

## 风险与回退

| 风险 | 概率 | 影响 | 回退方案 |
|------|------|------|---------|
| Phase 1: 前端依赖后端就绪 | 低 | 中 | 回退到 sequential 启动 |
| Phase 2: 延迟服务影响首屏 | 中 | 低 | 回退到串行初始化 |
| Phase 3: 延迟导入破坏路由 | 低 | 高 | 保留顶部导入,只优化重模块 |
| Phase 5: PyInstaller 兼容性 | 高 | 高 | 回退到 conda 启动 |

## 备注

**对开发环境的影响**:
- Phase 1-3 对 dev 环境**有效**(改 electron/ 或后端代码时受益)
- Phase 4-6 对 dev 环境**无影响**(dev 不用 uvicorn/PyInstaller/SW)
- 开发者 90% 时间改前端/后端,不改 electron/,此时 Vite HMR / uvicorn --reload 已足够快
- **最痛场景**: 改 electron/ 主进程代码 → 需完全重启 Electron → 等后端冷启动 50-90s
- Phase 1 解决此痛点:改 electron/ 后立即看到 UI,后端在后台加载

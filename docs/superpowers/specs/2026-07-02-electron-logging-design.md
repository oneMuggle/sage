# Electron 桌面日志 — Design Spec

- **Date:** 2026-07-02
- **Branch:** `feat/electron-logging` (基于 `origin/main`),cherry-pick 到 `release/win7`
- **Status:** Draft,待用户 review
- **Author:** Claude (brainstorming with user)

## 1. 背景与目标

### 1.1 问题

`release/win7` 分支的产物(NSIS 安装的 `.exe`)安装到 Windows 7 SP1 x64 物理机后**双击无任何反应**:
- 进程不出现窗口
- 没有错误弹窗
- 没有崩溃 dump
- 用户(也包括维护者)无任何线索可排查

经过代码审查,发现关键的盲区在 **Electron 主进程**:打包后的 `.exe` 是 GUI 子系统 + `windowsHide: true`,`console.log/error` 全部写入一个用户看不到的 stderr。`electron/logger.ts` 当前只输出到 `console.*`,**没有文件持久化**。`electron/main.ts` 在 `app.whenReady()` 之前的代码(包含 GPU flags 设置、disableHardwareAcceleration、app.commandLine.appendSwitch 等)在 Win7 上本身就可能 throw,而这些 throw 当前无法捕获。

后端的可观测性(`/metrics`、`audit.jsonl`、OTel tracing)已经完善,但**与桌面壳无关**——它解决的是 backend 行为,不是 Electron 启动问题。

### 1.2 目标

为 Sage 桌面壳(Electron 主进程 + 渲染进程)加入**结构化、持久化、可由用户自助获取**的日志系统:

1. **全生命周期覆盖** — 从 `main.ts` 第 1 行到 `app.quit()`,任何阶段的日志都写入文件
2. **Win7 用户自助取日志** — 三个 UI 入口(菜单 / 设置页 / 启动失败对话框),无需 DevTools
3. **NDJSON 结构化** — 每行一个 JSON 对象,人类可读 + 机读友好
4. **自动轮转** — 每天一个文件,保留 7 天,单文件 ≤10MB
5. **跨进程聚合** — 渲染进程通过 IPC 把日志也写入主进程的同一个文件

### 1.3 非目标 (YAGNI)

- 不接入外部日志聚合(Sentry / OTLP / Datadog)—— Win7 用户无上报后台
- 不做日志上传 / 分享 UI—— 用户自行通过邮件 / 工单附带
- 不做日志内嵌加密—— `audit.jsonl` 已不加密,日志同理
- 不做 web 模式的日志配套—— web 模式有浏览器 DevTools
- 不替换后端 `audit.jsonl` —— 后端可观测性独立完善
- 不做 log 搜索 UI—— 用户用 grep / 文本编辑器
- 不做崩溃 dump 上报—— 用户自行抓日志

## 2. 用户故事

- **US-1**:作为 Win7 用户,双击 Sage.exe 后程序无反应。我希望看到一个明确的对话框说「启动失败」并提供 「打开日志目录」 按钮。
- **US-2**:作为 Win7 用户,我想在「设置」页面看到日志目录路径、最近 7 天的日志文件列表、大小和修改时间。
- **US-3**:作为维护者,我想查看 Win7 用户反馈的 `.ndjson` 文件,用 grep / 文本编辑器快速找到 `level=error` 的行,定位 backend 启动失败 / 渲染进程白屏 / preload 加载失败等具体原因。
- **US-4**:作为开发,我想在 dev 模式下保留 stdout 输出,同时文件也写日志,方便本地调试。
- **US-5**:作为用户,我想点 「清理旧日志」 按钮立即释放磁盘,不必等自动清理。

## 3. 架构

### 3.1 数据流概览

```
┌──────────────────────────────────────────────────────────────────┐
│  src/ (React renderer)                                           │
│    └─ shared/log/client.ts  ── IPC ──┐                           │
│         (debug/info/warn/error)       │                          │
│                                       ▼                          │
│  electron/main.ts ────► electron/logger.ts ───► electron-log     │
│                              (NDJSON 格式化)     (4.x 兼容 Win7)  │
│                                       │                          │
│                                       ▼                          │
│                       app.getPath('userData')/logs/               │
│                       sage-YYYY-MM-DD.ndjson (保留 7 天)          │
└──────────────────────────────────────────────────────────────────┘

三条 UI 入口:
  [1] 菜单 帮助 → 打开日志目录 / 复制日志路径 (主进程 Menu)
  [2] 设置页 /settings → 诊断与日志卡片 (renderer + IPC)
  [3] 启动失败对话框 (dialog.showMessageBox)
```

### 3.2 启动生命周期与日志捕获点

```
[1] 用户双击 .exe
        │
        ▼
[2] dist-electron/electron/main.js 第 1-3 行
     (新代码) const { logger } = require('./logger')
              logger.info('main: process started', {pid, argv, electronVer, platform})
        │
        ▼
[3] app.disableHardwareAcceleration() / commandLine.appendSwitch(...)
     → 任何 throw 都被 process.on('uncaughtException') 捕获 → logger.error
        │
        ▼
[4] app.whenReady().then(async () => {
        ├─ spawnBackend()  →  logger.info('main: spawning backend', {cmd, args, envKeys})
        │     └─ proc.stdout/stderr 'data' → logger.debug/info('backend: ...', {source: 'backend'})
        ├─ waitForBackend() → logger.debug('main: health check', {url, attempt, elapsedMs})
        │     └─ 30s 超时 → logger.error + dialog.showMessageBox (启动失败对话框)
        ├─ registerIpcHandlers() → logger.info('main: ipc handlers registered', {count})
        └─ createMainWindow()  → logger.info('main: window created', {width, height, url})
              └─ loadFile/loadURL catch → logger.error + dialog.showMessageBox
   })
        │
        ▼
[5] Renderer 启动 (React)
        ├─ React error boundary → window.electronAPI.log('error', ...)
        ├─ 关键 fetch 失败 → window.electronAPI.log('warn', ...)
        └─ 主进程 IPC handler (sage:log:write) → logger (source='renderer')
        │
        ▼
[6] app.on('before-quit') / window-all-closed
        └─ logger.info('main: shutting down', {reason})
```

**关键设计点 — 第 1 行就初始化**: 现有 `console.log` 在打包后丢到虚空。新的 logger 必须在 `main.ts` 第 2-3 行就初始化,**早于** `app.disableHardwareAcceleration()` —— 后者在 Win7 上本身就可能 throw。

## 4. 文件 / 模块设计

### 4.1 新增文件

| 文件 | 角色 | 估计行数 |
|---|---|---|
| `electron/logger.ts` | **重写**:包 electron-log,导出 `logger.{debug,info,warn,error}(msg, meta?)`,写入 NDJSON | ~80 |
| `electron/logPaths.ts` | 单例函数 `getLogDir()` / `getCurrentLogFile()`,封装 `app.getPath('userData')/logs/` | ~30 |
| `electron/logRotate.ts` | 启动时清理 >7 天的旧文件;单文件 >10MB 切分 | ~50 |
| `electron/ipc/logIpc.ts` | `registerLogIpc(ipcMain)`,注册 `sage:log:write` / `sage:log:list-files` / `sage:log:open-dir` / `sage:log:copy-path` / `sage:log:cleanup` / `sage:log:set-level` | ~80 |
| `electron/showStartupFailureDialog.ts` | 启动失败对话框:3 个按钮(打开日志目录 / 重试 / 退出) | ~60 |
| `electron/menu.ts` | `buildApplicationMenu(logDir)`,加 「帮助 → 打开日志目录 / 复制日志路径」 | ~50 |
| `src/shared/log/client.ts` | renderer 端 logger,通过 `window.electronAPI.log(level, msg, meta)` 转发 | ~40 |
| `src/shared/log/levels.ts` | 共享 `LogLevel` 类型 + 默认级别常量 | ~15 |
| `src/widgets/settings/DiagnosticsCard.tsx` | 设置页 「诊断与日志」 卡片 UI | ~120 |
| `src/widgets/settings/__tests__/DiagnosticsCard.test.tsx` | 卡片单测 | ~80 |
| `electron/__tests__/logger.test.ts` | NDJSON 格式 / 跨天切文件 / 级别过滤 / meta 序列化 | ~120 |
| `electron/__tests__/logRotate.test.ts` | 7 天保留 / 跨月边界 / 空目录 | ~50 |
| `electron/__tests__/logIpc.test.ts` | handler 调用 / source 字段 / rate limit | ~80 |
| `electron/__tests__/showStartupFailureDialog.test.ts` | dialog 内容 / 按钮回调 / logger 先于 dialog | ~50 |
| `src/shared/log/__tests__/client.test.ts` | fire-and-forget / meta 透传 / electronAPI 缺失 noop | ~30 |

### 4.2 改动文件(最小 diff)

| 文件 | 改动 |
|---|---|
| `electron/main.ts` | (1) 第 1-3 行初始化 logger;(2) ~10 处 `console.log/error` 改为 `logger.*`;(3) 启动失败路径调 `showStartupFailureDialog()`;(4) 调 `buildApplicationMenu(logDir)`;(5) 调 `logRotate.cleanupOlderThan(7)` |
| `electron/preload.ts` | 暴露 `electronAPI.log / listLogFiles / openLogDir / copyLogPath / cleanupLogs / setLogLevel` |
| `src/pages/Settings.tsx` | 引入 `DiagnosticsCard`,放在 「关于」 之上 |
| `src/widgets/layout/ErrorBoundary.tsx` | `console.error` → `clientLogger.error` |
| `package.json` | 加 `electron-log@^4.4.8`(兼容 Node 16 / Electron 21) |

### 4.3 NDJSON 行结构

每行一个 JSON 对象,严格符合 NDJSON spec,UTF-8 无 BOM:

```json
{"ts":"2026-07-02T10:23:11.456Z","level":"info","source":"main","msg":"backend ready","meta":{"port":8765}}
{"ts":"2026-07-02T10:23:11.789Z","level":"warn","source":"main","msg":"backend health slow","meta":{"attempt":3,"elapsedMs":1500}}
{"ts":"2026-07-02T10:23:12.123Z","level":"error","source":"renderer","msg":"React error boundary","meta":{"componentStack":"..."}}
```

| 字段 | 说明 |
|---|---|
| `ts` | ISO 8601 UTC,毫秒精度 |
| `level` | `debug` / `info` / `warn` / `error` |
| `source` | `main` / `renderer` / `preload` / `backend`(主进程转发 stdout/stderr) |
| `msg` | 人类可读消息 |
| `meta` | 可选对象,JSON-safe(number/string/bool/null/array/object);不可序列化值 fallback 为字符串 `"[unserializable]"` |

### 4.4 文件路径与命名

| 平台 | 路径 |
|---|---|
| Windows | `%APPDATA%/sage/logs/sage-YYYY-MM-DD.ndjson` |
| macOS (dev) | `~/Library/Application Support/sage/logs/sage-YYYY-MM-DD.ndjson` |
| Linux (dev) | `~/.config/sage/logs/sage-YYYY-MM-DD.ndjson` |

按本地日期切换;单文件预计 <500KB/天,硬上限 10MB(超过切 `.1` 后缀,新文件继续)。

### 4.5 electron-log transport 配置

| transport | 用途 | level |
|---|---|---|
| `console` | dev 下打到 stdout | `debug` (dev) / `info` (prod) |
| `file` | NDJSON 到 logs/sage-YYYY-MM-DD.ndjson | `info`(默认),可被 `SAGE_LOG_LEVEL` 覆盖 |
| crash dump | electron-log 内建 | `error`(自动启用) |

**环境变量**:
- `SAGE_LOG_LEVEL` — 覆盖默认级别,默认 `info`
- `SAGE_LOG_DIR` — 测试时重定向到临时目录

### 4.6 IPC 协议(单一通道族)

```typescript
// preload.ts 暴露
window.electronAPI = {
  // 现有方法保留
  log: (level: LogLevel, msg: string, meta?: Record<string, unknown>) =>
    ipcRenderer.invoke('sage:log:write', { level, msg, meta }),

  listLogFiles: () => ipcRenderer.invoke('sage:log:list-files'),
  openLogDir:   () => ipcRenderer.invoke('sage:log:open-dir'),
  copyLogPath:  () => ipcRenderer.invoke('sage:log:copy-path'),
  cleanupLogs:  () => ipcRenderer.invoke('sage:log:cleanup'),
  setLogLevel:  (level: LogLevel) => ipcRenderer.invoke('sage:log:set-level', { level }),
};

// 持久化: 写入 app.getPath('userData')/config.json(logLevel 字段)。
// 启动优先级: env SAGE_LOG_LEVEL → config.json → 默认 'info'。
```

**Rate limit**: 同一 renderer senderId 每秒最多 100 条;超出丢弃,每分钟打 1 条 `logger.warn('renderer log rate limited', { senderId, dropped })`。

### 4.7 启动失败对话框

**触发条件**(任一即触发):
| 触发点 | 条件 |
|---|---|
| `waitForBackend` | 30s 超时 |
| `mainWindow.loadFile/loadURL` | catch 到错误 |
| `process.on('uncaughtException')` | 任何未捕获异常 |

**对话框内容**:
```
┌─────────────────────────────────────────┐
│  ❌ Sage 启动失败                       │
├─────────────────────────────────────────┤
│  {错误摘要}                              │
│                                         │
│  错误详情已写入日志,请点击下方按钮      │
│  获取日志文件并附在反馈中。              │
│                                         │
│  [打开日志目录]  [重试]  [退出]         │
└─────────────────────────────────────────┘
```

- 弹窗前 logger.error **必须** 先写一行(`main: startup failed, showing dialog`)
- 「重试」: 重新跑 `waitForBackend`(给用户一次机会,如临时端口占用)
- 「退出」: `app.quit()`

## 5. 错误处理矩阵

| 场景 | 失败点 | 处理 |
|---|---|---|
| 日志目录创建失败 | `mkdirSync` | 退化为 stderr only + 第 1 条 `logger.error('log dir unavailable', {err})`,**不阻塞**应用启动 |
| electron-log 内部 throw | `log.info(...)` | 包 try/catch,fallback 到 `console.error` |
| Renderer IPC 调用失败 | `electronAPI.log` reject | client 端 `.catch(() => {})` 静默 |
| meta 含循环引用 | `JSON.stringify` throw | 捕获后用 `safeStringify` fallback:深度遍历,不可序列化值替换为字符串 |
| 主进程崩溃前未刷盘 | electron-log 默认同步写 | `process.on('uncaughtException')` 同步写一行 + exit |
| 日志文件被占用(杀毒软件) | `appendFileSync` throw | 跳过本条 + `console.error` |
| 用户磁盘满 | 写文件 throw | 同上,不阻塞应用 |

## 6. 测试策略

**单元测试**(vitest,覆盖率 ≥80%):

| 文件 | 验证 |
|---|---|
| `electron/__tests__/logger.test.ts` | NDJSON 行格式 / 跨天切文件 / 级别过滤 / meta 序列化(含循环引用)/ 文件路径正确 |
| `electron/__tests__/logRotate.test.ts` | 7 天保留 / 跨月边界 / 空目录 / 权限缺失降级 |
| `electron/__tests__/logIpc.test.ts` | handler 调用写入 / source 字段正确 / rate limit 触发丢弃 |
| `electron/__tests__/showStartupFailureDialog.test.ts` | dialog 内容 / 按钮回调 / logger 先于 dialog 写入 |
| `src/shared/log/__tests__/client.test.ts` | fire-and-forget / meta 透传 / electronAPI 缺失 noop |
| `src/widgets/settings/__tests__/DiagnosticsCard.test.tsx` | 列表渲染 / 按钮触发 IPC / level change 持久化 |

**集成测试**(vitest + 真实 fs 临时目录):
- `electron/__tests__/integration/logFlow.test.ts` — 启动 → 写日志 → 重启 → 跨天切文件 → 清理 7 天前

**手动验证清单**(Win7 真机):
- [ ] 安装 `.exe` 到 Win7 SP1 x64
- [ ] 启动应用
- [ ] 检查 `%APPDATA%/sage/logs/sage-YYYY-MM-DD.ndjson` 存在且含首条 `main: process started`
- [ ] 触发后端不响应(改 PORT)→ 看到失败对话框
- [ ] 点 「打开日志目录」 → 资源管理器打开 logs/ 目录
- [ ] 设置页能看到日志文件列表(文件名/大小/时间)
- [ ] 关闭应用 → 第 2 天再次启动 → 看到 2 个文件(昨天的 + 今天的)

## 7. 分支同步

**符合项目 "双分支长期共存" 策略**(`docs/technical/21-win7-lts.md`):

**Phase 1**: 在 `feat/electron-logging` 分支开发,目标 `main`:
1. PR → main,等 CI 全绿(Frontend TS + Electron build x2 + Electron smoke + Backend Ruff)
2. 合并到 main

**Phase 2**: Cherry-pick 到 `release/win7`:
1. 单 commit cherry-pick,commit message 加 `(cherry picked from main commit XXX)`
2. 验证 Python 3.8 + Electron 21 兼容性(`electron-log@^4.4.8` 已确认兼容 Node 16.20.2)
3. 跑 `ci.yml` 的 py38 backend job + electron build job

**禁止**(项目级 CLAUDE.md 红线):
- ❌ 不在 release/win7 上修改 `backend/requirements.txt`
- ❌ 不合并两个分支
- ❌ 不删除 release/win7

## 8. 风险

| 风险 | 缓解 |
|---|---|
| electron-log 4.x 在 Electron 21 兼容性 | CI 必跑(electron build + smoke);如失败,降级到自研 B 方案 |
| Win7 低配机器 HDD 上 IO 性能 | 单次 `appendFileSync` <1ms,接受 |
| 用户隐私数据(api_key 等)写入日志 | 调用方契约:logger 永不接收 api_key / token;code review checklist 加这一条 |
| 大量调试日志占磁盘 | 自动 7 天保留 + 单文件 10MB 上限 + 手动清理按钮 |
| Win7 self-hosted runner 不可用,真机验证只能人工 | docs/technical/21-win7-lts.md § 3 「Win7 启动验证」已有人工步骤清单 |

## 9. 实施里程碑(供 writing-plans 参考)

1. **M1** — 安装 `electron-log` + 写 `electron/logger.ts` + 替换 main.ts 的 console.*(~10 处)+ main.ts 顶部初始化 + 单元测试
2. **M2** — `electron/logPaths.ts` + `logRotate.ts` + 集成测试
3. **M3** — `electron/ipc/logIpc.ts` + `preload.ts` + `src/shared/log/{client,levels}.ts` + Renderer ErrorBoundary 接入 + 单元测试
4. **M4** — `electron/menu.ts` + 菜单接入 + `electron/showStartupFailureDialog.ts` + 启动失败路径接入 + 单元测试
5. **M5** — `src/widgets/settings/DiagnosticsCard.tsx` + Settings 页面接入 + 卡片单测
6. **M6** — 文档(`docs/technical/29-electron-logging.md`)+ 用户手册 + Win7 真机人工验证清单 PR
7. **M7** — Cherry-pick 到 `release/win7`,跑 py38 CI,合并

## 10. 验收标准

- [ ] `npm run typecheck:electron` 通过
- [ ] `npm run typecheck` 通过(前端 TS)
- [ ] `npm run lint` 通过
- [ ] `npm run test:run` 通过,新增测试覆盖率 ≥80%
- [ ] `electron:dev` 模式下,devtools 看到 console + `%APPDATA%/sage/logs/sage-*.ndjson` 同步有内容
- [ ] `electron:build` 产物能跑(在 macOS / Linux dev 验证)
- [ ] Win7 启动失败 → 看到对话框 → 点 「打开日志目录」 → 资源管理器打开
- [ ] cherry-pick 到 release/win7 后,ci.yml py38 job + electron build job 全绿
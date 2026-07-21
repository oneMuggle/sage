# Win7 + Electron 21 兼容性

> Sage 桌面端的 Win7 兼容栈。Phase 0-3 (2026-06-13) 从 Tauri 2.1.1 迁移到 Electron 21.4.4，Phase 4 接入 CI 矩阵与轻量烟测，Phase 5 留作 release 前真机验证。

---

## 1. 为什么放弃 Tauri

Tauri 2.x 通过 `webview2-com` crate 绑定到 Microsoft Edge WebView2 运行时，而 WebView2 的系统要求是 **Windows 10 v1803+ / Windows 11 / Server 2016+**。Win7 SP1 不在 WebView2 支持矩阵里：

- 即使 NSIS 安装器把 WebView2 bootstrapper (`embedBootstrapper`，~1.8MB) 嵌入安装包，bootstrapper 在 Win7 上运行时会直接报 "OS not supported"
- **Tauri 文档中提到的 "Windows 7 support" 实指 bootstrapper 安装机制的兼容，不是 Tauri 本身能在 Win7 上跑** —— 这一点容易误读
- 关键证据（已通过 GitHub API 验证）：
  - `tauri-apps/tauri@tauri-v2.1.1` 与 fork `oneMuggle/tauri@v2.1.1-win7-cve-patched` 的 `crates/tauri/Cargo.toml` features 段均**没有 `windows7-compat` 这个 feature**
  - 双方 `[target.cfg(windows).dependencies]` 都是 `webview2-com = "0.33"`，这是 COM 接口绑定，本质即 WebView2
- 结论：Tauri 在 Win7 上**根本不可能**运行，所有 Cargo 版本钉死都救不了 OS 层硬依赖

## 2. 为什么选 Electron 21.4.4

候选栈评估（按 Win7 真实可行性排序）：

| 候选                | 渲染引擎          | Win7 真实状态                                               | 复用 React/TS       | 工作量   | 结论              |
| ------------------- | ----------------- | ----------------------------------------------------------- | ------------------- | -------- | ----------------- |
| **Electron 21.4.4** | 自带 Chromium 106 | ✅ Electron 21 是最后一版官方支持 Win7（22+ 砍 Win7/8/8/1） | 🟡 仅 IPC shim 替换 | 14-21 天 | **强推**          |
| NW.js 0.69.x        | 自带 Chromium 108 | ✅ 同上                                                     | 🟡 同上             | 14-21 天 | 备选              |
| PyQt5 + QtWebEngine | Qt Chromium 87    | ✅ 但前端要全重写                                           | ❌                  | 30-50 天 | 不推荐（YAGNI）   |
| Wails v1            | MSHTML/IE11       | 🟡 能跑但渲染质量差                                         | ❌                  | 21-30 天 | 不推荐（IE 引擎） |

**关键事实**：

- Electron 21 自带 Chromium 106 + Node 16.20.2，**不依赖系统 WebView** —— Win7 真能跑
- Electron 22 起官方 changelog 砍掉 Win7/8/8.1 支持（详见 Electron breaking-changes）
- `app.disableHardwareAcceleration()` + `--no-sandbox` + `--disable-gpu` 是 Win7 已知可行配置

## 3. 架构对比

### 3.1 旧 Tauri 2.1.1 架构

```
┌─────────────────┐       ┌──────────────────────┐       ┌──────────────┐
│ React Renderer  │ ─IPC─→│ Tauri Main (Rust)    │ ─HTTP→│ FastAPI      │
│ (Vite + WRY)    │       │ + WRY runtime        │       │ (Python)     │
└─────────────────┘       │ + webview2-com 0.33  │       └──────────────┘
                          └──────────────────────┘
                          ❌ webview2-com 要求 Win10+
```

### 3.2 新 Electron 21 架构

```
┌─────────────────┐       ┌──────────────────────┐       ┌──────────────┐
│ React Renderer  │ ─IPC─→│ Electron Main (Node) │ ─HTTP→│ FastAPI      │
│ (Vite +         │       │ + BrowserWindow      │       │ (Python)     │
│  contextBridge) │       │ + FastAPI subprocess │       │              │
└─────────────────┘       │ + NDJSON relay       │       └──────────────┘
                          └──────────────────────┘
                          ✅ 自带 Chromium 106，无系统 WebView 依赖
```

### 3.3 IPC 桥接契约（不变）

| 旧 (Tauri)                                                   | 新 (Electron)                                                                                  | 说明                      |
| ------------------------------------------------------------ | ---------------------------------------------------------------------------------------------- | ------------------------- |
| `import { invoke } from '@tauri-apps/api/core'`              | `import { invoke } from '@/lib/tauriInvoke'` → 内部委托 `window.electronAPI.invoke`            | shim 签名不变，下游零改动 |
| `import { listen, UnlistenFn } from '@tauri-apps/api/event'` | `import { listen, UnlistenFn } from '@/lib/tauriEvent'` → 内部委托 `window.electronAPI.listen` | 同上                      |
| `ipcRenderer.invoke('sage:invoke', ...)`                     | `ipcRenderer.invoke('sage:invoke', {cmd, args})`                                               | 主进程转发到 backend      |
| `webContents.send('sage:event:{event}', payload)`            | 同名                                                                                           | Phase 2 实现 NDJSON relay |

**测试影响**：所有 `vi.mock('@/lib/tauriInvoke')` / `vi.mock('@/lib/tauriEvent')` 不变，3 个 `.test.ts` 文件零修改全数通过（21 files / 99 tests）。

## 4. Win7 Launch Flags 详解

`electron/main.ts` 在 `app.whenReady()` 之前设置 7 个 Chromium 开关：

| Flag                                      | 作用                     | Win7 必要性                                                     |
| ----------------------------------------- | ------------------------ | --------------------------------------------------------------- |
| `app.disableHardwareAcceleration()`       | 禁用 GPU 硬件加速        | Win7 GPU 驱动在 V8/Blink 下崩溃频繁，回退软件合成更稳定         |
| `--no-sandbox`                            | 禁用 chrome-sandbox      | Win7 无 SUID chrome-sandbox helper (chmod 4755)，不关会拒绝启动 |
| `--disable-gpu`                           | 强制 CPU 合成路径        | Win7 D3D11 驱动常导致 Electron GPU 进程崩溃                     |
| `--disable-software-rasterizer`           | 关闭 Skia 软件光栅       | 与 Win7 老 GPU 驱动 DLL 冲突                                    |
| `--in-process-gpu`                        | GPU 单进程模式           | Win7 多进程模型比单进程崩溃率高                                 |
| `--disable-features=VizDisplayCompositor` | 跳过 Chromium Viz 合成器 | Viz 需要完整 D3D11，Win7 D3D11 残缺                             |
| `--js-flags=--max-old-space-size=2048`    | V8 堆上限 2GB            | 4GB-RAM Win7 系统 chat 流式时不会 OOM-kill                      |

每个开关的 rationale 在 `electron/main.ts` 行内注释完整记录。

## 5. CI 流水线（Phase 4）

`.github/workflows/ci.yml` 包含 5 个 job：

| Job              | Runner                         | 作用                                                        |
| ---------------- | ------------------------------ | ----------------------------------------------------------- |
| `backend`        | ubuntu-latest                  | Python lint + mypy + pytest（hex + legacy 双轨） + coverage |
| `frontend`       | ubuntu-latest                  | TS lint + typecheck + vitest + vite build                   |
| `desktop-build`  | ubuntu-latest + windows-latest | electron-builder 矩阵：Linux AppImage / Windows NSIS        |
| `electron-smoke` | windows-latest                 | playwright-electron 轻量烟测（`SAGE_SKIP_BACKEND=1`）       |
| `all-green`      | ubuntu-latest                  | 强门禁：backend + frontend + electron-smoke 全部 success    |

> **2026-06-23 更新**: Win7 LTS release 拆出独立 workflow `release-win7.yml` (在 `release/win7` 分支), 不再走本表中的 main release。详见 [`31-win7-lts.md` §9](./31-win7-lts.md)。

### 5.1 轻量烟测覆盖

`tests/electron/smoke.spec.ts` 跑 2 个测试（`npx playwright test`）：

1. **Electron 启动 + IPC bridge**：
   - Electron 主进程能启动（无 SUID 错误）
   - BrowserWindow 出现 + DOMContentLoaded
   - `window.electronAPI.invoke` 和 `window.electronAPI.listen` 都是函数（preload.ts 加载成功）
   - 前端 HTML body 渲染非空（不是白屏）
   - 截图保存到 `tests/electron/screenshots/smoke-launch.png`（CI artifact 供 review）

2. **invoke IPC 往返**：
   - 调用 `window.electronAPI.invoke('definitely_not_a_real_command')`
   - 期望主进程抛 "Unknown IPC command" —— 证明 bridge 真的走通了 main 进程

### 5.2 SAGE_SKIP_BACKEND 环境变量

`electron/main.ts` 读 `process.env.SAGE_SKIP_BACKEND === '1'`：

- 跳过 `spawnBackend()` + 30s `/health` 等待
- 直接 `createMainWindow()`
- 用于 CI 烟测（runner 没有 sage-backend conda env）+ 本地手动调试

## 6. Win7 部署前置（README 已同步）

Win7 SP1 x64 系统装 Sage 前**必须**：

1. **KB3033929**（SHA-2 代码签名支持，2016 年发布）
   - 不打则 Sage.exe 启动被拒（"丢失 MSVCP140.dll" 或 "未签名" 错误）
   - Win7 SP1 默认不打此补丁
   - 自动通过 Windows Update 更新即可
2. **KB3140245**（TLS 1.2 SChannel 默认开启，2016 年发布）
   - **非必需**（Electron 用 Chromium BoringSSL，Python 用 rustls，都不依赖 SChannel）
   - 但用户若用 IE/Edge legacy 访问 HTTPS 站点会失败
3. **x64 only**：Electron 21 不支持 Win7 32-bit

## 7. Phase 5 真机烟测 SOP（release 前执行）

> 用户确认：Phase 5 延后到 release 前执行。Phase 4 CI 轻量烟测为常驻回归护栏。
>
> **自动化脚本位置**：[`scripts/win7-smoke/`](../../../scripts/win7-smoke/) — 5 步 PowerShell 脚本 + README 编排说明。
> 用户在自己 Win7 VM（手动 / SSH / WinRM 任一通道）跑脚本，结果以 `*-result.json` 形式回收。

### 7.1 准备

- VirtualBox 7.x（或 VMware Player，免费）
- 镜像：`cn_windows_7_ultimate_x64_dvd_x15-66043.iso`（MSDN 官方）
- 必备补丁：装完系统后**只打 KB3033929**（验证 SHA-2 签名支持）
- **故意不打 KB3140245**（验证 rustls/BoringSSL 不依赖 SChannel）
- VM 配置：4 vCPU / 4GB RAM / 启用 VT-x / 网络 NAT 或 Host-Only
- 打完 KB3033929 + VirtualBox Guest Additions 后**立即打快照** `win7-baseline`，每次烟测前恢复

### 7.2 自动化烟测矩阵（5 步 PowerShell）

[`scripts/win7-smoke/`](../../../scripts/win7-smoke/) 提供 5 步脚本，对应下表：

| Step        | 脚本                | 验证内容                                                  | 期望耗时 |
| ----------- | ------------------- | --------------------------------------------------------- | -------- |
| 1. Deploy   | `deploy.ps1`        | OS 版本 + KB3033929 + 后端端口 + Ollama 端口 + 安装包存在 | ~30s     |
| 2. Install  | `install.ps1`       | NSIS 静默安装 + Sage.exe 存在 + 注册表项存在              | ~1-2 min |
| 3. Launch   | `launch-test.ps1`   | Sage.exe 启动 < 10s + 主窗口出现 + 后端 /health + 截图    | ~30s     |
| 4. Ollama   | `verify-ollama.ps1` | Ollama /api/tags + /api/generate + 后端 /chat 链路        | ~30s     |
| 5. Teardown | `teardown.ps1`      | NSIS 卸载 + 日志收集到 smoke-results/Sage-logs/           | ~30s     |

**PASS 准则**：5 步全部 PASS，且 Launch 步骤截图肉眼确认非白屏、xyflow 节点连线可见。

### 7.3 手动烟测流程（不跑脚本时）

```
Step 1 [基线恢复]   VirtualBox → win7-baseline 快照恢复
Step 2 [网络]       VM 内 ping host 通
Step 3 [Ollama]     host 启 ollama serve，VM 内 curl http://<host-ip>:11434/api/tags 通
Step 4 [安装]       拷贝 Sage-Setup-X.Y.Z.exe 到 VM，双击安装（UAC "是"）
Step 5 [首次启动]   桌面双击 Sage 图标
                    观察项：
                    - 主窗口 3 秒内出现（白屏超 10s = FAIL）
                    - xyflow 节点连线能拖动
                    - react-markdown 渲染代码块带高亮
                    - 状态栏显示 "后端已连接"（端口 8765 健康检查）
Step 6 [IPC 测试]   在 Sage UI 点 "新建会话" → 后端日志应见 POST /sessions
Step 7 [Ollama 联调] 在 Sage 输入消息 → 应调用 Ollama → 流式输出
Step 8 [关闭]       关闭窗口 → Python 子进程应自动结束
Step 9 [回归]      重启 Sage → 设置应保留
```

### 7.4 PASS 准则

- ✅ 主窗口 < 10s 出现
- ✅ xyflow / markdown / 代码高亮全部渲染
- ✅ FastAPI 子进程启动 + 端口 8765 可访问
- ✅ Ollama 调用成功（即使 1.5B 模型 CPU 慢，至少首 token 出来）
- ✅ 二次启动设置保留
- ✅ 卸载干净（无残留文件/注册表）

### 7.5 FAIL 升级路径

| 失败位置                       | 升级动作                                                                                 |
| ------------------------------ | ---------------------------------------------------------------------------------------- |
| 启动白屏 / Chromium 106 不兼容 | 收集 `electron --enable-logging` 输出，确认是 v8 Win32 调用还是 GPU 驱动问题             |
| Ollama 调用超时                | host 防火墙阻挡 11434 → VM 改 Host-Only + host 加规则                                    |
| 安装器 UAC 失败                | NSIS 改 `perMachine: true` + admin 启动安装                                              |
| Electron 主进程崩溃            | 加 `--disable-software-rasterizer --disable-dev-shm-usage` 启动参数                      |
| 脚本某 step FAIL               | 见 [`scripts/win7-smoke/README.md §4`](../../../scripts/win7-smoke/README.md) 排错速查表 |

## 8. 文件与目录速查

### 8.1 新增（Phase 0-4）

| 路径                           | 作用                                                         |
| ------------------------------ | ------------------------------------------------------------ |
| `electron/main.ts`             | Electron 主进程（spawn backend + IPC handlers + Win7 flags） |
| `electron/preload.ts`          | contextBridge API（window.electronAPI）                      |
| `electron-builder.yml`         | NSIS Win7 打包配置                                           |
| `tsconfig.electron.json`       | Node target CommonJS                                         |
| `playwright.config.ts`         | Playwright Electron 烟测配置                                 |
| `tests/electron/smoke.spec.ts` | 轻量烟测 2 个 case                                           |
| `tests/electron/global.d.ts`   | 测试侧 electronAPI 类型 augment                              |
| `src/types/electron-api.d.ts`  | Window.electronAPI 类型声明（renderer 侧）                   |
| `src/lib/tauriInvoke.ts`       | 改写为 electronAPI 薄包装                                    |
| `src/lib/tauriEvent.ts`        | 改写为 electronAPI 薄包装                                    |
| `build/icon.ico`               | 从归档 tauri icons 复制（Phase 6 重新生成 SVG）              |

### 8.2 归档（保留 history）

| 路径                                           | 内容                                              |
| ---------------------------------------------- | ------------------------------------------------- |
| `archive/src-tauri-2026-06-13-win7-migration/` | 原 Tauri 2.1.1 全部代码（`git mv`，history 保留） |

### 8.3 已删除

| 路径                                                                       | 原作用                         | 删除原因   |
| -------------------------------------------------------------------------- | ------------------------------ | ---------- |
| `.github/workflows/ci-win7.yml`                                            | Tauri Win7 自托管 runner job   | Tauri 移除 |
| `.github/workflows/release-win7.yml`                                       | Tauri Win7 NSIS release        | Tauri 移除 |
| `scripts/patch-webkit2js.mjs`                                              | webkit2gtk-4.0 JSC regex patch | Tauri 移除 |
| `docs/technical/20-win7-tauri-compat.md`                                   | Tauri Win7 配置                | 替换为本章 |
| `docs/superpowers/plans/2026-06-13-tauri-2.1.1-zeroize-edition2024-fix.md` | Tauri 零碎 plan                | Tauri 移除（原 plan 已按 `feature-development.md` 规则归档删除）|

### 8.4 不动

- `src/`（React 业务组件，仅替换 IPC shim import 路径）
- `backend/`（FastAPI，0 改动）
- `vite.config.ts`（仅加 `base: './'` + watch.ignored）

## 9. 迁移阶段总览

| Phase   | 任务                                                         | 工作量 | 状态          |
| ------- | ------------------------------------------------------------ | ------ | ------------- |
| Phase 0 | 拆除 Tauri 残骸（归档 + 删 win7 workflow + 删 docs）         | 半天   | ✅ 2026-06-13 |
| Phase 1 | 引入 Electron 21.4.4 + electron-builder                      | 2-3 天 | ✅ 2026-06-13 |
| Phase 2 | 前端 IPC shim 适配层（tauriInvoke/tauriEvent → electronAPI） | 1 天   | ✅ 2026-06-13 |
| Phase 3 | Win7 兼容性微调（7 个 Chromium 启动开关）                    | 半天   | ✅ 2026-06-13 |
| Phase 4 | CI 矩阵调整 + playwright-electron 轻量烟测                   | 1-2 天 | ✅ 2026-06-13 |
| Phase 5 | Win7 真机烟测（release 前执行）                              | 2-3 天 | ⏳ 延后       |
| Phase 6 | 文档归档（本章 + 其他章 Tauri 描述清理）                     | 半天   | ✅ 2026-06-13 |

## 10. 风险登记

| 风险                                                    | 严重度 | 概率 | 缓解                                                                                       |
| ------------------------------------------------------- | ------ | ---- | ------------------------------------------------------------------------------------------ |
| Electron 21.4.4 已 2022 年 EOL，Chromium 106 有已知 CVE | HIGH   | 中   | 限制外网访问；定期 `npm audit`；锁 `electron@^21.4.4`                                      |
| Win7 SChannel 不支持 TLS 1.3 → 公网 LLM API 受限        | LOW    | 低   | Sage 用本地 Ollama，无此场景；Python rustls 自带 TLS 1.2/1.3                               |
| Win7 GPU 驱动与 Chromium 106 兼容问题                   | MEDIUM | 中   | Phase 5 真机验证；FAIL 收集 `electron --enable-logging`                                    |
| Electron 21 内嵌 Node 16.20 与 npm 生态包兼容           | LOW    | 低   | 锁 Node 16.20.2（Electron 21 默认）                                                        |
| Phase 5 真机烟测未执行前 release                        | MEDIUM | 中   | 强制 Phase 5 在 release tag 前执行（CI `release.yml` 可加 pre-job 检查最近 Win7 烟测时间） |

## 11. 参考链接

- Electron 21 官方 Win7 支持说明：[Electron breaking-changes](https://github.com/electron/electron/blob/main/docs/breaking-changes.md)
- WebView2 系统要求：[Microsoft Learn](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/system-requirements)
- Win7 KB3033929：[Microsoft Update Catalog](https://www.catalog.update.microsoft.com/Search.aspx?q=KB3033929)
- electron-builder NSIS 文档：[electron-builder JSON schema](https://www.electron.build/configuration/nsis)
- playwright-electron API：[Playwright docs](https://playwright.dev/docs/api/class-electron)

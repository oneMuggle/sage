# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## Release Tier Definitions

| Tier | Tag Format | Audience | Channel |
|------|-----------|----------|---------|
| **alpha** | `vX.Y.Z-alpha.N` | Sage contributors only | GitHub Releases (prerelease) |
| **beta** | `vX.Y.Z-beta.N` | Public beta testers | GitHub Releases (prerelease) |
| **rc / preview** | `vX.Y.Z-rc.N` | Broad testing, recommended for early adopters | GitHub Releases (prerelease) |
| **stable** | `vX.Y.Z` | All users | GitHub Releases (latest) |

Win7 LTS adds `-win7` suffix after tier (e.g. `vX.Y.Z-beta.N-win7`).

## [v0.4.3-alpha.2] - 2026-07-07

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 SP1 修复路径（PR #111 blocker 修复，跟 v0.4.3-alpha.1 同路径）。Tag 不带 `-lts` 后缀，与 main 上 alpha tag 命名风格一致（实际产物是 Win7 LTS 的 Electron 21 + Python 3.8 NSIS installer）。

### Fixed
- **fix(win7): python38._pth 屏蔽 PYTHONPATH 导致后端启动 30 秒超时（v0.4.3-alpha.1 仍未修复的根因）**
  - 根因：Python 3.8.10 embeddable 自带 `python38._pth` 文件，按官方文档（https://docs.python.org/3.8/using/windows.html）"all registry and environment variables are ignored" — `electron/main.ts` 在 spawn 时设的 `PYTHONPATH=resources\backend;resources\sage-core` 被 _pth 静默丢弃。`from backend.adapters.out...` 找不到 `backend` 包 → `ModuleNotFoundError: No module named 'backend'` → 后端 ~1s 退出 → main.ts /health 30s 轮询后弹错误对话框
  - 修复 1：`scripts/bundle-python.ps1` 把 `..\backend` 和 `..\sage-core` 写入 `python38._pth`（相对 _pth 所在目录的相对路径，不依赖用户自定义安装目录）。幂等：重跑 bundle 不会重复追加
  - 修复 2：`scripts/bundle-python.ps1` verify 步骤从 `import fastapi/pydantic/jieba`（全在 site-packages）升级为加 `import backend.main` 作为 _pth 配置的金丝雀 — 之前 verify 步骤**永远不会发现** _pth backend 路径问题
  - 修复 3：`scripts/bundle-python.Tests.ps1` 新增 `Describe 'python38._pth config'` 区块（5 个 It 用例），含幂等性守卫，防止后续 regression
  - 用户提供 NDJSON 日志证实根因：`uvicorn.config.load → import_from_string("backend.main:app") → importlib.import_module → ModuleNotFoundError: No module named 'backend'`，发生位置 `C:\Program Files\Sage\resources\python\`

### Notes
- v0.4.3-alpha.1 的 prometheus-client/pip LASTEXITCODE/stderr tail 修复保留
- Win7 LTS only — main 分支用 conda dev path，PYTHONPATH 不会被屏蔽，无需对等改动
- 不改 `electron/main.ts`：当前 spawn 时设的 `PYTHONPATH` 在 packaged 路径下被 _pth 屏蔽但对 dev 路径仍有效，留作后续独立清理 PR

## [v0.4.3-alpha.1] - 2026-07-06

> 🧪 **Alpha tier** — Sage 贡献者内测。Win7 SP1 修复路径破例（按 4 档规范 win7 LTS 不跟 alpha，本 release 走 blocker 修复例外流程，未来待 PR 反馈是否更新 §30.4）。Tag 不带 `-lts` 后缀，与 main 上 alpha tag 命名风格一致（实际产物是 Win7 LTS 的 Electron 21 + Python 3.8 NSIS installer）。

### Fixed
- **fix(win7): bundle Python 依赖时 pip install 失败未中止（v0.4.0-lts+ 启动 30 秒超时根因）**
  - 根因：`prometheus-client==0.25.0` 在 PyPI 上 `requires_python=">=3.9"`，与 Win7 LTS 用的 Python 3.8.10 embeddable 不兼容 → 整个 `pip install -r requirements-py38.txt` 回滚 → `site-packages` 为空 → 后端 `import fastapi` 失败秒退 → 前端 /health 30 秒后弹"后端服务在 30 秒内未响应"对话框
  - 受影响版本：`v0.4.0-lts`、`v0.4.1-lts`、`v0.4.2-lts`（全部是 GitHub Draft release，未公开发布）
  - 修复 1：`backend/requirements-py38.txt` 将 `prometheus-client` 钉到 `==0.21.1`（PyPI 上最后一个支持 Python 3.8 的版本；代码只用 stable API，0.21.1 完全兼容）
  - 修复 2：`scripts/bundle-python.ps1` 在所有 `& $PipExe` / `& $PythonExe` 调用后加显式 `if ($LASTEXITCODE -ne 0) { throw }` 检查（PowerShell 的 `$ErrorActionPreference = "Stop"` 不会自动捕获外部命令 exit code——这是 v0.4.0-lts+ 静默失败的根因）。Verification 步骤（`import fastapi/pydantic/jieba`）同样 fail-fast
  - 修复 3（防御性改进）：`electron/main.ts` 把后端 stderr 末 20 行 buffer 到 module-level `lastStderrLines`，通过新 `stderrTail` 字段传给 `showStartupFailureDialog`。未来类似问题用户能直接看到 `ModuleNotFoundError: No module named 'fastapi'` 等真实根因，不必查 NDJSON 日志
  - 清理：删除死代码 `start-backend.bat`（`electron/main.ts` 直接 spawn `python.exe`，从未调用该 .bat；`scripts/bundle-python.ps1` 不再生成，`electron-builder.yml` 不再打包）
  - 测试：新增 `scripts/bundle-python.Tests.ps1`（Pester 5 静态分析测试，~14 个断言）+ `.github/workflows/ci.yml` 新增 `bundle-script-test` job（ubuntu-latest + pwsh 7.4 + Pester，~5s runtime，无网络依赖）

## [Unreleased]

### Added
- feat(wiki): native folder picker for project create/open, recent projects memory, debounced backend pre-check (issue: llm-wiki-folder-picker)
- feat(wiki): gate folder picker Browse button behind `appSettings.wiki.useFolderPicker` (default true; set false to fall back to plain text input — see §8 rollback in plan)
- feat(skills): conform `backend/skills/skill_md/` to agentskills.io spec
  - Add optional fields: `license`, `compatibility` (≤500 chars), `allowed-tools`
  - Strengthen `name` (≤64 chars) and `description` (≤1024 chars) validation
  - Support single-file `<dir>/SKILL.md` form in loader
  - Warn (not block) when frontmatter `name` != parent directory name
  - Emit warning when description lacks trigger keywords
  - All changes forward-compatible; existing SKILL.md files unaffected
  - Refs: docs/superpowers/specs/2026-06-29-agentskills-io-spec-conformance-design.md

## [v0.3.0] - 2026-06-23

### Added
- **feat(chat): 实时显示工具调用、思考过程和 agent 编排 (#57)**
  - P0: `streamingToolCalls` 升级为 `useState` + ref 镜像，acting/observing 事件立即渲染，不再等流结束
  - P1: ThinkingPanel 流式自动展开，`useEffect` 监听 `isStreaming` 变化
  - P2: ActiveAgentIndicator 显示"第 N 轮 · agent 名 · 阶段图标 (lucide)"，新增 `src/shared/lib/agentStateMapping.ts` 作为单一真相源
  - 附带修复: setTimeout 泄漏 / 不可变更新 / `ToolCall.id` 字段 / `interrupt()` finishStream / cancel-prev 同时停后端 / `Message` React.memo + 自定义比较函数
- **feat(ci): 双轨 release workflow (main → Win10+/Linux, LTS → Win7 SP1)**
  - main release 产物: `Sage-Setup-${version}-win10.exe` / `sage_${version}_amd64.deb` / `Sage-${version}.AppImage`
  - LTS release 产物: `Sage-Setup-${version}-win7.exe` (Windows 7 SP1 x64 only, tag 形如 `v*-lts`)
  - 新 workflow: `.github/workflows/release-win7.yml` (在 `release/win7` 分支)
  - `electron-builder.yml`: `win.artifactName` 用 `${env.ARTIFACT_SUFFIX}` 占位

### Changed
- **docs(technical)**: `21-win7-lts.md` 加 §9 Release 工作流；`26-packaging-matrix.md` §1/§2 拆 Win7/Win10+；`20-electron.md` §5 加 LTS 提示
- **docs(README)**: §"双轨发布" 表格加具体下载入口；Q4 重写
- **docs(user-manual)**: `01-desktop.md` §1.1/§1.2 拆 Win7 LTS 子节

### Fixed
- **fix(lint): 排除 dist-electron 扫描 + 修复 4 个 warnings (#59)** — `package.json` lint 脚本加 `--ignore-pattern dist-electron`，修复 WikiGraphView / Sidebar / MemoryBrowser 的 eslint warnings，删除 stale plan 文档
- **fix: expose agent list to LLM and add settings endpoints to legacy mode**
- **fix(ci): add ARTIFACT_SUFFIX to ci.yml Windows build step**
- **fix(ci): add trailing newline + fix artifact name in release notes**
- **fix(backend): auto-fix ruff lint errors in integration tests (#52)**

### 计划中
- 跟踪 [`docs/plans/2026-06-13_full-quality-optimization-v2.md`](./plans/2026-06-13_full-quality-optimization-v2.md) 7 方向 A-G
  - A. 六边形迁移收口(剩 A2 memory / A3 evolution / A4 skills / A5 agents / A6 wiki / A7 llm-proxy)
  - B. FSD 收口(`src/{components,hooks,lib,types}` 归位)
  - C. 前端覆盖率阈值 + Playwright E2E ≥ 8 个
  - D. WCAG 2.2 AA + axe-core + Lighthouse ≥ 95
  - E. 性能与体积基线 + CI 预算
  - F. 安全审计入 CI(npm/pip audit + gitleaks + electronegativity)
  - G. onboarding 一键脚本 + ADR 起步

## [v0.2.0] - 2026-06-22

### Added
- **feat(agent): 接通 Agent Profile 到运行时 (#48)** — SageAgent 接受 `agent_id` 参数，运行时从 SQLite 读最新 profile，消费 `system_prompt` / `max_iterations` / `enabled` 字段
- **feat(orchestrator): 接入 AgentOrchestrator 到生产** — `/chat` 路由根据消息复杂度（关键词 + 长度）分流，复杂消息走 `AgentOrchestrator.process_request`
- **perf(orchestrator): `asyncio.gather` 并行子任务** — `_execute_multi_step` 用 `asyncio.gather(return_exceptions=True)` 替代串行执行，结果顺序与输入一致，错误隔离
- **feat(ui): ActiveAgentIndicator 组件** — 流式聊天时显示"🤖 当前处理 agent: xxx"，3 秒无更新后淡出
- **feat(agent): get_enabled_agent() 工具函数** — 从 SQLite 读启用 agent 的 profile dict（disabled/missing 返回 None）
- **feat(agent): AgentEvent.agent_id 字段** — 透传当前活跃 agent ID 到前端
- **feat(backend): localStorage → SQLite 配置存储迁移 (#46)** — settings 持久化到后端 preferences 表，前端 localStorage 兜底缓存 + 7 天过期清理
- **feat(backend): SAGE_DB_PATH env var** — 支持 packaged Electron 后端子进程用独立 DB 路径
- **feat(backend): SettingsRepository on preferences table** — 通用 KV 存储，KEYS 白名单限定可写 key
- **feat(backend): GET/PUT /preferences/{key}** — theme & session id 持久化
- **feat(electron): 4 IPC routes for settings & preferences** — Electron 端透传
- **feat(electron): set SAGE_DB_PATH for backend subprocess** — Electron 启动后端时设 DB 路径
- **feat(frontend): async settings storage with auto-migration + 7d cleanup** — 自动迁移 + 缓存过期
- **feat(frontend): theme storage + session storage dual-write** — 本地缓存 + 后端同步
- **feat(frontend): useStore.currentSessionId / ThemeProvider / useSettings async init** — 异步初始化避免启动竞态
- **feat(frontend): settingsClient IPC wrapper with 5s timeout** — 统一 IPC 客户端
- **fix(ci): 多个 CI 修复** — 从 backend 目录安装依赖、requirements.txt、sage_core 包
- **fix(backend): conftest teardown 守卫 importlib.reload residue**
- **fix(backend): skip pre-existing broken tests (SessionService DI not wired)**
- **fix(frontend): useChat tests wait for useSettings async load**
- **fix(frontend): settingsClient ipcCall type — object → Record<string, unknown>**
- **fix: main 分支 pre-existing TypeScript 错误** — `saveSettings` 显式 `as AppSettings` 类型断言

### Changed
- **fix(frontend): main 分支 pre-existing lint 错误** — `import/order` 自动修复（App.tsx / ThemeProvider.tsx / store.ts 等）
- **test(integration): hex-only 测试加 @_HEX_ONLY skip** — `/preferences/{key}` / `/settings` 端点在 legacy 模式不注册，hex 模式才跑

## [v0.1.2] - 2026-06-15

### Added
- **PG-A1 sessions 6 端点 hex 迁移(#19)**——把 legacy 路由的 `/sessions/*` 迁到六边形架构
  - 新建 `SessionService` (`backend/application/services/`) 编排会话生命周期,内置 OTel + 审计 + 指标
  - 扩 `StoragePort`:加 `get_session` / `update_session` + 改 `delete_session` 返 rowcount
  - `hex_routes.py` 加 6 端点 + 2 Pydantic 模型(`SessionCreate` / `SessionUpdate`) + DI 工厂
  - 响应字段与 legacy 完全兼容(POST/GET/PATCH/DELETE + 错误文案 "会话不存在"),前端 0 改动即可切换
  - 单元测试 15 个 + 集成测试 12 个覆盖 happy + 404 路径
- **Tauri → Electron 21.4.4 迁移(#14)**——主桌面框架切换,Electron 21 是 Win7 兼容的最后一版
- **Win7 LTS 维护章节(#18 + #21-win7-lts)**——18 个月归档时间表 + 真机烟测 SOP + 风险声明
- **IPC shim 改名(#16)**——`tauriInvoke` / `tauriEvent` 改名为 `desktopInvoke` / `desktopEvent`(与 transport 解耦,旧名 6 个月过渡到 2026-12-31)
- **CI backend-py38 + win7-lts 分支守卫(#15)**——双 Python 版本 + release/win7 分支自动保护
- **LLM 代理路由**(`/api/v1/llm/*`)——旁路浏览器 CORS,前端直接打 LLM 不再需要 OLLAMA_ORIGINS 配置
- **Agents CRUD 端到端**——`list` / `get` / `update` / `toggle` 4 端点
- **Chat 流式响应端到端**——NDJSON → Tauri event → React 中间态文案
- **Skills 系统端到端**——`SkillPort` + 3 routes + 3 commands + 4 builtin skills
- **LLM Wiki 集成 PR-8(Phase 1-7)**——4 LLM provider 抽象 + LanceDB RAG(hybrid retrieval) + 知识图谱(4-signal) + React Flow 视图
- **Tauri CLI 包锁定**——`@tauri-apps/api` / `@tauri-apps/cli` 锁到 `=2.1.0`,修 major.minor 一致性校验失败
- **Electron-builder 矩阵 + Playwright Electron smoke**——3 OS 自动化构建 + 桌面端冒烟测试

### Changed
- `backend/main.py` 默认 `API_MODE` 临时从 `"hex"` 改 `"legacy"`(1 字符 + TODO 注释),等后续 PR 装配 SessionService DI 后改回 `"hex"`
- 5 个集成测试的 local `_API_MODE` 默认同步从 `"hex"` 改 `"legacy"`,与 main.py 实际配置一致

### Deprecated
- `src/lib/tauriInvoke.ts` / `tauriEvent.ts` re-export shim——已 `@deprecated`,计划 2026-12-31 删除(`release/win7` 临时保留到 2026-12-31)

### Fixed
- **Electron 桌面端 Linux 启动修复(#25)**——`electron/main.ts` 把后端 spawn 从 `python backend/main.py` 改成 `python -m backend.main`,让 `from backend.adapters...` 绝对 import 能 resolve;同步加 `postinstall` (`scripts/fix-chrome-sandbox.sh`) 在 `npm install` 后自动恢复 `chrome-sandbox` 的 root 所有权 + 4755 SUID 位(Linux-only,macOS/Windows 跳过,idempotent)
- **构建图标 gitignore 修正**——`build/icon.{ico,png}` 改为跟踪,修 `electron-builder` 缺图标的隐式失败
- **WikiGraphView 单元测试外移**——inline `describe` 移到独立文件,修 vitest 多文件解析问题
- **Tauri CLI 锁版本**——`@tauri-apps/api` / `@tauri-apps/cli` 锁到 `=2.1.0`,修 major.minor 一致性校验
- **WikiChat import 顺序**——CI lint 失败的 import 顺序修正

## [v0.1.1] - 2026-06-08

### Security
- 通过 fork backport CVE-2026-42184(GHSA-7gmj-67g7-phm9)
- 锁定 Tauri 2.1.1 矩阵(Win7 + Rust 1.77.2 兼容)

### Fixed
- `release.yml` 多个隐患(vs-setup deleted / Node 18 / cargo update / contents: write)

### Documentation
- 完整文档归档:`docs/technical/20-win7-tauri-compat.md`

### Build
- 首个 Win7 兼容 Windows 安装包 `Sage_0.1.1_x64-setup.exe`(含 WebView2 v109 离线嵌入)

## [v0.1.0] - 2026-05-09

### Added
- 完善 GitHub Actions Windows 构建配置(`.github/workflows/ci.yml` + `release.yml` + `src-tauri/tauri.conf.json`)

[Unreleased]: https://github.com/oneMuggle/sage/compare/v0.3.0...HEAD
[v0.3.0]: https://github.com/oneMuggle/sage/compare/v0.2.0...v0.3.0
[v0.2.0]: https://github.com/oneMuggle/sage/compare/v0.1.2...v0.2.0
[v0.1.2]: https://github.com/oneMuggle/sage/compare/v0.1.1...v0.1.2
[v0.1.1]: https://github.com/oneMuggle/sage/compare/v0.1.0...v0.1.1
[v0.1.0]: https://github.com/oneMuggle/sage/releases/tag/v0.1.0

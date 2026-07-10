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

> 🧪 **Alpha tier** — Sage 贡献者内测。PEP 604/585 → typing.* 跨平台兼容同步(原 Win7 LTS fix PR #112 现在 main 也对齐)。Win10+Linux+Mac 验证用版本。

### Changed
- **fix(backend): mass-rewrite PEP 604/585 annotations → typing.*** — 193 个文件 (backend/ + packages/sage-core/) 同步 Win7 LTS 的 Py3.8 兼容性重写。Main (Py3.11) 上纯属 stylistic 改动,功能不变。release/win7 上是必需的运行兼容性修复
- **fix(scripts): py38_compat_rewrite.py** — 新增 AST-based 重写工具 + 一个 follow-up 修复(typing import 只插入到模块顶部,不合并到中间位置的旧 import)

## [v0.4.4-alpha.1] - 2026-07-09

> 🧪 **Alpha tier** — Sage 贡献者内测。LLM Wiki **NDJSON 流式架构** (PR-114+115+116) 上线,9 个 followup 清理 (PR-118+120+122+124),Win7 LTS 同步 (PR-117+119+121+123)。流式 chat/ingest + 6 stage 进度 + sticky progress auto-dismiss + empty retrieval UX + HTTPException status 保留 + 5 个路由层集成测试 + LLMContext dataclass 抽象 + GraphData 序列化方法 + llmConfig 集成 useSettings。

### Added
- **feat(wiki): LLM Wiki NDJSON 流式架构 (PR-114+115+116)** — `/api/v1/wiki/{chat,ingest}/stream` NDJSON 端点,Electron main `relayNdjsonToEvent` 拆分到 IPC channel,前端 `useWikiChatStream` / `useWikiIngest` hooks
- feat(wiki): 6 stage ingest 进度 (`started` → `copy_source` → `step1_analyze` → `step2_write` → `embedding` → `completed`)
- feat(wiki): `LLMContext` dataclass 抽象 (`llm_call` + `llm_stream_call` + `http_post`) + `make_llm_context` 工厂,4 路由共享
- feat(wiki): `GraphData.to_dict()` / `from_dict()` 方法,dedupe 序列化
- feat(wiki): `lastQueryHadNoResults` 状态 + "未在 wiki 中找到相关内容" UX
- feat(wiki): ingest 进度条 4s 自动 dismiss (sticky progress UX)
- feat(wiki): `DEFAULT_EMBED_MODEL` 常量 (`'text-embedding-3-small'`)
- feat(wiki): `_http_exception_from_llm` helper,3 LLM-using 路由保留 upstream status code
- test(wiki): `/ingest/stream` 路由层 5 个集成测试

### Fixed
- fix(wiki): temp .md file leak in `/ingest/stream` — `_stream_with_cleanup` async generator wrapper + try/finally
- fix(wiki): `useWikiChatStream` / `useWikiIngest` unlisten 时 `{streamId}` 透传到 `sage:unlisten` (修 abort leak)

### Documentation
- docs(wiki): 25-llm-wiki-integration.md 新增 "流式架构" section (10 章节) 描述 PR-114+115+116 架构 (PR-125)

## [Unreleased] — for changes after v0.4.5-alpha.1

### Added

### Fixed

### Changed

## [v0.4.5-alpha.1] - 2026-07-10

> 🧪 **Alpha tier** — Sage 贡献者内测。**spawn conda ENOENT 修复 + main-branch Python bundling** (PR #130, 6 commits / 8 files / +914 -75)。修复了 main 分支 Windows NSIS installer 因缺 Python bundling 步骤导致 end-user 启动时抛"a javascript error occurred in the main process"的根因。Resolver + bundling 双层修复，新 resolver 函数 13 个 vitest cases 覆盖全分支。

### Added
- feat(wiki): native folder picker for project create/open, recent projects memory, debounced backend pre-check (issue: llm-wiki-folder-picker)
- feat(release): main-branch Python bundling (`scripts/bundle-python-main.ps1`) — wraps Python 3.11 embeddable + `backend/requirements.txt` (main, pydantic 2.x) + `packages/sage-core` into the same `resources/` tree that `electron-builder.yml` extraResources expects. Mirrors `scripts/bundle-python.ps1` (Win7 LTS, Py 3.8), with main-branch-specific fixes cherry-picked from release/win7 LTS commits 4cea570 / 2689cb8 / a20c061 / 973d44c (python311._pth `..` path import + `import backend.main` canary + `LASTEXITCODE` guards + no dead `start-backend.bat` + precise `resources/` cleanup).
- feat(electron): `electron/backendLauncher.ts` — pure-function resolver that picks the right Python launcher (dev conda / SAGE_PYTHON override raw-python / packaged Win / packaged Linux / macOS unsupported / unknown platform). Replaces the inline `if (pyLauncher)` branch in `electron/main.ts#spawnBackend()` so the decision is unit-testable.

### Fixed
- **fix(electron): packaged Win installer crashed with "spawn conda ENOENT" at startup** — root cause was two-layer, fixed in this PR + review pass:
  1. **Resolver layer** (`electron/main.ts` + new `electron/backendLauncher.ts`): previously `spawnBackend()` fell back to `spawn('conda', ...)` whenever bundled Python didn't exist. End-user Windows machines have no `conda`, so this surfaced as an opaque main-process JavaScript crash that buried the real cause. The resolver now refuses to call `conda` in `app.isPackaged` mode and instead surfaces a clear "Python 后端未找到 (安装包可能损坏)" dialog pointing users to the GitHub releases page to reinstall; macOS / unknown-platform packaged builds short-circuit to informative dialogs.
  2. **CI layer** (`.github/workflows/release.yml`): previously the main release workflow was missing the `bundle-python` step that `release-win7.yml` had since the Win7 LTS split. `release.yml` now calls `pwsh scripts/bundle-python-main.ps1` on the Windows runner before `electron-builder`, so main-branch releases produce a self-contained installer.
  3. **Hardening** (review pass after PR was opened): spawn-backend now has a `'error'` handler so AV/ACL/ENOEXEC failures don't crash the main process; the second misleading "30s 后端超时" dialog is suppressed when the broken-installer dialog already fired (`reportedBrokenInstaller` sentinel); `SAGE_PYTHON=python3` override no longer produces a broken `python3 run -n ...` spawn (the resolver now distinguishes conda-style vs raw-python commands).
  4. **`electron-builder.yml` extraResources trimmed**: dropped the dead `resources/start-backend.bat` entry (main.ts spawns `python.exe` directly via the resolver, never invokes the .bat — same cleanup release/win7 applied in 973d44c).
  - **Known follow-up**: Linux Python bundling (Ubuntu AppImage / deb) is still missing. No Python "embeddable" distribution exists for Linux; needs `python-build-standalone` or PyInstaller — out of scope for this bug-fix PR.
  - **13 new vitest cases** cover both packaged branches + dev branch + SAGE_PYTHON override (incl. a regression guard that `python3` override does NOT emit conda-flavoured args).
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

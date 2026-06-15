# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### 计划中
- 跟踪 [`docs/plans/2026-06-13_full-quality-optimization-v2.md`](./plans/2026-06-13_full-quality-optimization-v2.md) 7 方向 A-G
  - A. 六边形迁移收口(剩 A2 memory / A3 evolution / A4 skills / A5 agents / A6 wiki / A7 llm-proxy)
  - B. FSD 收口(`src/{components,hooks,lib,types}` 归位)
  - C. 前端覆盖率阈值 + Playwright E2E ≥ 8 个
  - D. WCAG 2.2 AA + axe-core + Lighthouse ≥ 95
  - E. 性能与体积基线 + CI 预算
  - F. 安全审计入 CI(npm/pip audit + gitleaks + electronegativity)
  - G. onboarding 一键脚本 + ADR 起步

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

[Unreleased]: https://github.com/oneMuggle/sage/compare/v0.1.2...HEAD
[v0.1.2]: https://github.com/oneMuggle/sage/compare/v0.1.1...v0.1.2
[v0.1.1]: https://github.com/oneMuggle/sage/compare/v0.1.0...v0.1.1
[v0.1.0]: https://github.com/oneMuggle/sage/releases/tag/v0.1.0

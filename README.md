# Sage

**本地优先的记忆型 AI 桌面助手 —— 能按格式要求直接交稿的 Office 写作代理**

> Win10+/macOS/Linux 主线 + Windows 7 SP1 长期维护分支 · Electron + Python · MIT

[![Latest Release](https://img.shields.io/github/v/release/oneMuggle/sage?include_prereleases&label=release)](https://github.com/oneMuggle/sage/releases)
[![CI](https://github.com/oneMuggle/sage/actions/workflows/ci.yml/badge.svg)](https://github.com/oneMuggle/sage/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](./LICENSE)

---

## Sage 能做什么

| | 能力 | 说明 |
|---|---|---|
| 📝 | **Office 全链路** | 对话生成 / 修订 Word、Excel、PPT、PDF；版式即配置（FormatSpec）、格式 Linter 与一键自动修复、GB/T 7714 / APA 引用体系、目录域、期刊模板；改前快照可回滚。详见 [用户手册 §9](./docs/user-manual/09-office.md) |
| 🧠 | **持久记忆** | 工作 / 情景 / 语义三层记忆 + 用户画像，跨会话记住偏好与上下文；所有记忆本地存储、可查看可删除。详见 [记忆系统](./docs/04-memory.md) |
| 🛠️ | **编码与本地代理** | 文件读写 / patch / bash / git / LSP 级符号搜索 / 浏览器 / 子代理并行编排；危险操作需人工审批 |
| 🧩 | **技能与 MCP** | `SKILL.md` 技能（含 paper-writing / report-writing 等内置技能）、多 MCP 服务器接入、Prompt 模板库与斜杠命令 |
| 📚 | **知识库** | 本地 Wiki + RAG 服务 + 浏览器剪藏扩展，`@` 引用文件 / 文档 / 表格进入对话 |
| 📱 | **远程网关** | Telegram 远程对话与审批：手机上批准桌面代理的操作。详见 [Telegram 网关](./docs/technical/32-telegram-gateway.md) |
| 🔄 | **人类在环的自演化** | 代理可从错误中提出改进，但必须经人审批后生效，全程可审计、可回滚 |
| 🔌 | **可插拔更新源** | GitHub / Gitee / GitLab / 通用 HTTP 更新源，token 经系统钥匙串加密 |

设计原则见 [PHILOSOPHY.md](./PHILOSOPHY.md)：记忆优先 · 渐进式自演化 · 透明可控 · 简单胜于复杂。

---

## 快速开始

### 直接安装（推荐）

| 平台 | 下载 |
|---|---|
| Windows 10+ / macOS / Linux | <https://github.com/oneMuggle/sage/releases/latest> |
| Windows 7 SP1 x64（LTS，完全离线） | <https://github.com/oneMuggle/sage/releases?q=tag%3Av*-lts> |

安装后首次启动会进入引导页：填写一个 OpenAI 兼容端点（或本地模型地址）即可开始对话。

### 从源码运行

环境要求：Node.js ≥ 18、Python ≥ 3.11（主线）/ 3.8（win7 分支）。

```bash
git clone https://github.com/oneMuggle/sage.git
cd sage
npm install                                 # 前端 + Electron 依赖
cd backend && pip install -r requirements.txt && cd ..
cp .env.example .env                        # 按需填写模型端点 / API Key

# 终端 1：Python 后端（默认 :8765）
python -m backend.main
# 终端 2：Electron + Vite 开发模式
npm run electron:dev
```

更多命令：`npm run typecheck` / `npm run lint` / `npm run test:run` / `bash scripts/pytest.sh`；多分支并行开发见 [`scripts/worktree.sh`](./scripts/worktree.sh)。

---

## 双轨发布

Sage 维护两条独立的 GitHub Release 通道：

| 通道 | 触发分支 | 目标平台 | 产物 | Electron | Python | 状态 |
| --- | --- | --- | --- | --- | --- | --- |
| **main release** | `main` | Win10+ / Linux / macOS | `Sage-Setup-${version}-win10.exe` / `sage_${version}_amd64.deb` / `Sage-${version}.AppImage` | 21.4.4 | 3.11+ | ✅ 主线持续迭代 |
| **LTS release** | `release/win7` | **Windows 7 SP1 x64**（完全离线部署） | `Sage-Setup-${version}-win7.exe` | 21.4.4（冻结） | 3.8 | ⚠️ 仅 hotfix，2027-12-13 EOL |

**预发布档位**（main 与 win7 LTS 同步）：

| 档位 | tag 格式 | 适合谁 | GitHub Release 标记 |
|---|---|---|---|
| alpha | `vX.Y.Z-alpha.N` | Sage 贡献者 | `prerelease` |
| beta | `vX.Y.Z-beta.N` | 公开测试者 | `prerelease` |
| rc / preview | `vX.Y.Z-rc.N` | 早期采用者 | `prerelease` |
| stable | `vX.Y.Z` | 全量用户 | `latest` |

Win7 LTS 派生 tag 追加 `-lts` 后缀。完整分级规则见 [`docs/technical/30-release-tiers.md`](./docs/technical/30-release-tiers.md)，打包矩阵见 [`docs/technical/26-packaging-matrix.md`](./docs/technical/26-packaging-matrix.md)，Win7 风险声明见 [`docs/technical/31-win7-lts.md`](./docs/technical/31-win7-lts.md)。

---

## 架构一览

```
┌──────────────────────────────────────────────────────────┐
│  桌面客户端  Electron 21 + React 18 + Vite 5 (src/, electron/) │
│  · FSD 分层前端  · preload IPC 白名单  · 自动更新  · 托盘        │
├──────────────────────────────────────────────────────────┤
│  Python 后端  FastAPI (backend/)  —— 六边形架构               │
│  · Agent 编排 / 子代理  · 工具注册表 + 权限  · 技能 (SKILL.md)   │
│  · 记忆系统 (工作/情景/语义)  · Office 引擎  · MCP 客户端       │
│  · 消息网关 (Telegram)  · 调度器  · 自演化 (人审批)             │
├──────────────────────────────────────────────────────────┤
│  数据层  SQLite (会话/记忆/审计)  +  ChromaDB (向量)  —— 全部本地 │
└──────────────────────────────────────────────────────────┘
```

| 目录 | 内容 |
|---|---|
| `src/` | React 渲染层（`app / pages / widgets / features / entities / shared`） |
| `electron/` | 主进程：后端启动与守护、更新管理、IPC、日志、托盘 |
| `backend/` | Python 后端：`agents / tools / skills / memory / office / mcp / gateway / orchestration …` |
| `packages/` | `sage-core`、`drawio-mcp-server` |
| `services/rag-service` · `extension/wiki-clipper` | 独立 RAG 服务 · 浏览器剪藏扩展 |
| `docs/` | 核心设计（01–14）、技术专题（`technical/`）、用户手册（`user-manual/`）、进行中计划（`plans/`） |
| `tests/` · `e2e/` · `backend/tests/` | Vitest / Playwright（stub & live）/ pytest |

---

## 配置

| 项 | 位置 |
|---|---|
| 环境变量 | `.env`（模板 `.env.example`）：模型端点、API Key、端口 |
| 后端配置 | `backend/config.yaml` + `backend/config/`（设置规范化见 [`docs/technical/32-settings-canonicalization.md`](./docs/technical/32-settings-canonicalization.md)） |
| 应用内设置 | 设置面板：端点管理、更新源、主题、权限、记忆策略 |
| 打包 | `electron-builder.yml`、`tsconfig.electron.json` |

---

## 常见问题

**Q: 记忆系统不工作？**
检查 `EMBEDDING_MODEL` 配置与 ChromaDB 是否安装（`pip show chromadb`）；可在设置 → 诊断中运行 Sage Doctor（[手册 §11](./docs/user-manual/11-sage-doctor.md)）。

**Q: Windows 7 下无法运行 / 哪里下载 Win7 版？**
main release 自 2026-06-23 起不再支持 Win7。请从 [LTS release](https://github.com/oneMuggle/sage/releases?q=tag%3Av*-lts) 下载 `Sage-Setup-${version}-win7.exe`，前置需安装 KB3033929（SHA-2 签名），仅 x64。

**Q: 端口被占用？**
后端默认 `8765`、Vite 默认 `1420`，通过 `.env` 中 `PYTHON_BACKEND_PORT` / `VITE_DEV_PORT` 修改。

**Q: 安装包为什么 100MB+？**
Electron 自带 Chromium 与打包的 Python 运行时。这是为了 Win7 LTS 与完全离线部署付出的体积代价。

**Q: 记忆占用过多空间？**
设置 → 记忆策略中调整保留期或手动触发修剪；进化系统会定期摘要归档。

---

## 文档索引

| 文档 | 说明 |
|---|---|
| [docs/README.md](./docs/README.md) | 全部文档导航 |
| [02 系统架构](./docs/02-architecture.md) · [18 六边形架构](./docs/technical/18-hexagonal.md) | 整体架构与分层约束 |
| [04 记忆系统](./docs/04-memory.md) · [39 用户画像](./docs/technical/39-memory-user-profile.md) | 三层记忆、检索、画像 |
| [05 Agent 引擎](./docs/05-agent.md) · [27 多代理编排](./docs/technical/27-multi-agent-orchestration.md) | 对话引擎、工具执行、子代理 |
| [24 技能系统](./docs/technical/24-skills-system.md) · [34 MCP 多服务器](./docs/technical/34-mcp-multi-server.md) | 技能与 MCP |
| [用户手册 09 Office](./docs/user-manual/09-office.md) · [54 Office 对标追踪](./docs/technical/54-office-parity-tracking.md) | Office 能力 |
| [15 质量门禁](./docs/technical/15-quality-gates.md) · [CONTRIBUTING.md](./CONTRIBUTING.md) | 贡献流程、CI、pre-commit |
| [CHANGELOG.md](./CHANGELOG.md) | 变更记录 |

---

## 项目状态

**Beta**：核心功能（对话、记忆、Office、技能、MCP、更新）已稳定迭代并有 CI / e2e 门禁；API 与配置格式在 1.0 前仍可能调整。欢迎通过 Issue / PR 参与，贡献指南见 [CONTRIBUTING.md](./CONTRIBUTING.md)。

## License

MIT

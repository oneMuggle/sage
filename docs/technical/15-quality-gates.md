# 15. 质量门禁（Quality Gates）

**最后更新**：2026-09-23（按 ci.yml 现状全量事实核对重写；上一版 2026-06-05 为 P0 末快照，其中 tauri-smoke、tauri 构建等 Tauri 时代内容已随主线迁移失效）

## 15.1 概述

Sage 项目使用四层质量门禁：

1. **本地 pre-commit**：自动 lint/format（不阻塞）
2. **本地 pre-push**：双端测试冒烟（失败阻塞）
3. **CI（GitHub Actions）**：完整 lint + type + test + coverage + 专项检查（必须全绿）
4. **覆盖率门槛**：后端 ≥80% 强门禁；前端 thresholds 棘轮（2026-09 起生效）

## 15.2 CI 工作流与 Job 清单

`.github/workflows/ci.yml`（触发：push 到 `main`/`develop`/`release/win7`，PR 指向 `main`/`develop`/`release/**`）：

| Job | 职责 | 触发条件 |
| --- | --- | --- |
| `architecture-check` | `scripts/architecture-check.mjs`——单文件行数棘轮（基线 `architecture-baseline.json`，新文件 >800 行即红；基线键 POSIX 规范化，Windows 亦可跑） | 每次 push/PR |
| `count-lines` | 行数统计 | 每次 push/PR |
| `dependency-audit` | npm audit + pip-audit（只读报告，Critical/High 由聚合门禁执行）+ **environment.yml ↔ requirements.txt 漂移校验**（`scripts/check_env_yml_drift.py`，2026-09 新增） | main/develop 及其 PR |
| `backend` (Python) | ruff → import-linter（六边形 KEPT）→ mypy（domain/ports）→ pytest `-n auto` + **coverage ≥ 80% 强门禁** → hex 主路径回归 | 每次 push/PR |
| `backend-py38` (Win7 LTS) | 同上但用 `requirements-py38.txt` 钉版（Python 3.8） | 仅 `release/win7` 分支与指向它的 PR |
| `frontend` (TypeScript) | eslint --cache → tsc → vitest --coverage（**thresholds 棘轮**）→ build | 每次 push/PR |
| `electron-build` (ubuntu/windows 矩阵) | electron-builder 打包 | 每次 push/PR |
| `electron-smoke` | playwright-electron 启动冒烟 | 每次 push/PR |
| `backend-legacy` | API_MODE=legacy 兜底冒烟 | **非阻塞**（continue-on-error 安全网） |
| `backend-windows-unit` | Windows 基线单测 | **非阻塞** |
| `all-checks` | 聚合门禁：backend + frontend + electron-smoke + architecture-check 全 success 才通过 | 强门禁 |

独立 workflow：

| Workflow | 职责 |
| --- | --- |
| `e2e-pr-gate.yml` | PR 到 main：stub-smoke / stub-deep / live-boot 三层（stub 并行，live 等两者全绿） |
| `e2e-nightly.yml` | 夜间全量 E2E |
| `release.yml` / `release-win7.yml` | tag 触发发行（win7 侧仅 `-win7` 后缀 tag） |
| `pr-label-check.yml` | 指向 `release/v*` 的 PR 必须带 `fix:`/`hotfix:` label |
| `ci-rerun.yml` | PR 的 pull_request 事件被静默丢弃时手动补跑全量验证（round45 OPS） |

## 15.3 本地 Git Hooks（lefthook）

`lefthook.yml` 定义 3 个 hook：

### pre-commit（并行，不阻塞）

- backend：ruff check --fix + ruff format（仅 staged Python 文件）
- frontend：eslint --fix + prettier --write（仅 staged TS/TSX）

### pre-push（串行，可能阻塞）

- backend 与 frontend 测试冒烟

### post-merge

- 依赖安装同步

> 早期版本曾硬编码个人 conda 路径（`/home/fz/...`），现已修正；如本机 hook 失败优先检查 conda env `sage-backend` 是否存在。

## 15.4 工具链版本

| 工具 | 版本 | 配置 | 备注 |
| --- | --- | --- | --- |
| Python | 3.11（main）/ 3.8（win7 LTS） | `backend/environment.yml` + `requirements-py38.txt` | conda env `sage-backend` / `sage-backend-py38`；两套钉版为**有意的兼容分叉**，勿单独改一侧 |
| Node | CI 钉 22.12 | `.github/workflows/*` | 本地 24.x 亦可 |
| pytest | 7.4.4 | `backend/pytest.ini` | + asyncio 0.23.3 / cov 5.0.0 / xdist 3.6.1 / timeout 2.3.1 |
| ruff | 0.4.4 | `backend/ruff.toml` | target py311（win7 侧运行期兼容靠 `# noqa` 注释约定，如 UP038/B905/UP017） |
| mypy | 1.8.0 | — | 仅 domain/ports |
| import-linter | 2.11 | `backend/pyproject.toml` | 六边形分层（api→adapters→application→ports→domain） |
| vitest | 3.2.7 | `vite.config.ts` | + coverage-v8 thresholds（见 15.5） |
| knip | 6.37 | `knip.json` | 死代码/死依赖检测（本地工具，`npm run knip`；export 级存量未接 CI） |
| eslint | 9.39.4 | `eslint.config.js` | flat config + FSD 边界 |
| lefthook | 1.6 | `lefthook.yml` | 3 hooks |

## 15.5 覆盖率（2026-09-23 现状）

| 模块 | 门禁 | 来源 |
| --- | --- | --- |
| 后端（main） | **≥ 80% 强门禁**（`--cov-fail-under=80`，xdist 合并） | `ci.yml` backend job |
| 后端（win7，py38） | **≥ 80% 强门禁** | `ci.yml` backend-py38 job |
| 前端 | **thresholds 棘轮**：statements 60 / branches 79 / functions 65 / lines 60 | `vite.config.ts`（#1406，基线实测 61.81/80.58/67.09/61.81，留 ~2pt 余量只防断崖） |

> 2026-06-05 P0 末的后端基线为 43%；现 ≥80% 已达成并成为强门禁。分模块历史表（agent.py 62% 等）已过时，不再罗列。

## 15.6 已知遗留

| ID | 描述 | 状态 |
| --- | --- | --- |
| 2026-09 新增 | 前端覆盖率 thresholds 已生效（#1406） | ✅ |
| 2026-09 新增 | environment.yml 漂移校验已挂 dependency-audit（#1410） | ✅ |
| 2026-09 新增 | knip 已落地，export 级存量（unused exports ~123 / types ~226）未接 CI，消化后再收紧 | ⏳ |
| 长期 | `electron/main.ts` 2539 行，IPC registrar 拆分待并行会话收口后进行 | ⏳ |

## 15.7 常见问题

### Q: hook 慢怎么办？

A: pre-commit 并行执行且不阻塞合并；完整覆盖率、mypy、三平台构建都在 CI。

### Q: 怎么跳过 hook？

A: 紧急情况 `git commit --no-verify` / `git push --no-verify`。**不推荐日常使用**。

### Q: CI 跑多久？

A: 快信号（Architecture/count-lines）秒级；Frontend ~5 min；Electron build ~4 min；e2e 门禁 ~4.5 min（stub 并行 + live 串联）；Backend 全量（含 coverage ≥80%）为关键路径长杆，约 15-25 min。

### Q: Backend job 在每天早上 7-8 点（北京）容易红？

A: 历史问题已修——todo 分桶测试曾因 UTC 23 点跨日每天定时红（R97 冻结时钟方案修复）。再遇类似"每天固定时段红"的测试，优先怀疑本地时区/日期边界，造数应钳制当日或注入时钟。

## 15.8 贡献者快速上手

```bash
# 1. 后端环境（conda）
conda env create -f backend/environment.yml
conda activate sage-backend

# 2. 前端依赖
npm install

# 3. 激活 Git hooks
npx lefthook install

# 4. 验证环境
cd backend && pytest -q
cd .. && npm run test:run && npm run lint && npm run typecheck

# 5. 本地死代码自检（可选）
npm run knip
```

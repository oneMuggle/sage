# 15. 质量门禁（Quality Gates）

**最后更新**：2026-06-05
**阶段**：P0 完工
**适用版本**：Sage 全栈质量优化 v0.1

## 15.1 概述

Sage 项目使用四层质量门禁：

1. **本地 pre-commit**：自动修复 lint/format（不阻塞）
2. **本地 pre-push**：跑测试冒烟（失败阻塞）
3. **CI（GitHub Actions）**：完整 lint + type + test + coverage（必须全绿）
4. **覆盖率门槛**：CI 失败条件（逐步收紧）

## 15.2 CI 工作流

`.github/workflows/ci.yml` 定义 4 个 job：

| Job | 职责 | 触发条件 |
|-----|------|----------|
| `backend` | ruff + mypy + pytest + coverage (XML 上传 Codecov) | 每次 push/PR |
| `frontend` | eslint + tsc + vitest + build + coverage | 每次 push/PR |
| `tauri-smoke` | `npx tauri --version` 环境探针 | 每次 push/PR (矩阵: ubuntu/windows/macos) |
| `all-green` | 聚合 backend + frontend，任一失败则 fail | 强门禁 |

## 15.3 本地 Git Hooks（lefthook）

`.lefthook.yml` 定义 3 个 hook：

### pre-commit（并行，不阻塞）
- `backend-lint`：ruff check --fix（仅 staged Python 文件）
- `backend-format`：ruff format（仅 staged Python 文件）
- `frontend-lint`：eslint --fix（仅 staged TS/TSX）
- `frontend-format`：prettier --write（仅 staged TS/TSX）

### pre-push（串行，可能阻塞）
- `backend-test`：pytest -x --no-cov（快速冒烟）
- `frontend-test`：vitest run --no-coverage

### post-merge
- `deps-install`：npm install（保持依赖同步）

> **注意**：hook 中的 ruff 路径硬编码为 `/home/fz/anaconda3/envs/sage-backend/bin/ruff`，与项目 CLAUDE.md 一致。其他贡献者若 conda 路径不同，需修改 lefthook.yml（已记为 P1 改进项）。

## 15.4 工具链版本

| 工具 | 版本 | 配置文件 | 备注 |
|------|------|----------|------|
| Python | 3.11 | `backend/environment.yml` | conda env `sage-backend` |
| Node | 25 | `package.json` engines | 通过 nvm 管理 |
| pytest | 7.4.4 | `backend/pytest.ini` | + pytest-asyncio 0.23.3 + pytest-cov 5.0.0 |
| respx | 0.21.1 | `backend/requirements.txt` | LLM HTTP mock |
| ruff | 0.4.4 | `backend/ruff.toml` | 1277→0 违规（自动修复 + 25 条 ignore） |
| mypy | 1.8.0 | `backend/mypy.ini` | strict 仅作用于 domain/ports（P2 启用） |
| import-linter | 2.11 | `backend/pyproject.toml`（待 P2） | 依赖图边界 |
| vitest | 4.1.8 | `vite.config.ts` | + @testing-library/react 16.3.2 |
| eslint | 9.39.4 | `eslint.config.js` | flat config + react-hooks + react-refresh + import |
| prettier | 3.8.3 | `.prettierrc` | 105 文件已格式化 |
| lefthook | 1.6.22 | `lefthook.yml` | 3 hooks 激活 |

## 15.5 覆盖率现状（2026-06-05 P0 末）

| 模块 | 当前覆盖率 | 目标 | 状态 |
|------|------------|------|------|
| 后端整体 | **43%** | ≥ 80% | 🔴 P1 推进 |
| `core/agent.py` | 62% | ≥ 90% | 🟡 P1 PG1.1 |
| `core/llm_client.py` | 67% | ≥ 90% | 🟡 P1 PG1.3 |
| `core/orchestrator.py` | 21% | ≥ 90% | 🔴 P1 PG1.2 |
| `api/routes.py` | 68% | ≥ 85% | 🟡 P1 PG1.4 |
| `tools/*.py` | TBD | ≥ 85% | 🟡 P1 PG1.5 |
| `skills/builtin/*.py` | 19~27% | ≥ 70% | 🔴 P1 PG1.6 |
| `scheduler/*.py` | 14~18% | ≥ 60% | 🔴 P1 |
| `memory/*.py` | 24~28% | ≥ 60% | 🔴 P1 |
| 前端 | TBD | ≥ 60% | 🟡 P0-T8 末测 |

**当前覆盖门槛**：`--cov-fail-under=0`（不阻塞，但报告生成）。P1 期间分模块逐步收紧到目标。

## 15.6 P0 已知遗留（P1 收尾）

| ID | 描述 | 位置 | 优先级 |
|----|------|------|--------|
| PG0-1 | lefthook 硬编码 conda 路径 | `lefthook.yml` | 中 |
| PG0-2 | 8 条 ESLint 违规（import/order + no-unused-vars + react-hooks/deps） | `src/hooks/useKnowledge.ts:87`, `src/lib/api.ts:118`, `src/pages/Skills.tsx:20`, `src/widgets/Sidebar.tsx`, `src/components/memory/MemoryBrowser.tsx` | 中 |
| PG0-3 | 后端覆盖率 43% → 80% 提升 | 见 15.5 表 | 高（P1 主线） |
| PG0-4 | import-linter 尚未配置（需先有 domain/ports） | `backend/pyproject.toml` | 低（P2 启用） |
| PG0-5 | CI 中 tauri-smoke 仅作环境探针，非强门禁 | `.github/workflows/ci.yml` | 低（P3 收紧） |

## 15.7 常见问题

### Q: hook 慢怎么办？

A: pre-commit 钩子并行执行；pre-push 仅跑快速冒烟（无覆盖率）。完整覆盖率、mypy、Tauri build 都在 CI 跑。

### Q: 怎么跳过 hook？

A: 紧急情况下 `git commit --no-verify` / `git push --no-verify`。**不推荐日常使用**。

### Q: 在另一台机器上 hook 失败？

A: 大概率是 conda 路径不一致。修改 `lefthook.yml` 中的 `/home/fz/anaconda3/envs/sage-backend/bin/` 前缀为你的路径。

### Q: CI 跑多久？

A: backend 约 3-4 分钟（conda 安装 + 测试），frontend 约 2-3 分钟（npm ci + 测试 + build），tauri-smoke 约 1-2 分钟。总计 ≤ 8 分钟（与 spec 一致）。

## 15.8 贡献者快速上手

新贡献者克隆仓库后：

```bash
# 1. 安装 conda env
conda env create -f backend/environment.yml
conda activate sage-backend

# 2. 安装 npm deps
npm install

# 3. 激活 Git hooks
npx lefthook install

# 4. 跑一遍全测验证环境
cd backend && pytest
npm run test:run
npm run lint
npm run typecheck
```

全部通过即可开始开发。

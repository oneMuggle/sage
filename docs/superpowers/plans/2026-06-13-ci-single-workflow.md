# Plan B: CI 单 workflow 改造（backend-py38 守卫）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `.github/workflows/ci.yml` 单文件内增加 `backend-py38` job（仅 `release/win7` 触发），保持 `backend` job（main 触发，Python 3.10+）作为 `backend-modern`，互不干扰。

**Architecture:** 用 `if: github.ref == 'refs/heads/release/win7'` / `if: github.ref == 'refs/heads/main'` 分支守卫。两个 backend job 共用 `all-green` aggregator。

**Tech Stack:** GitHub Actions, conda-incubator/setup-miniconda@v3, Python 3.8 (win7) / 3.10+ (main)

**前提事实**：

- PR #13 (commit `a00b6b2`) 已把 `release/**` 加进 PR 触发条件（line 7）
- 现有 ci.yml 5 job：`backend` / `frontend` / `desktop-build` / `electron-smoke` / `all-green`
- 现有 `backend` job 跑 Python 3.10 + `sage-backend` conda env（line 27-28）
- `desktop-build` 已用 2 OS 矩阵（ubuntu/windows）跑 electron-builder（line 132）
- `electron-smoke` 已用 Playwright-Electron 跑烟测（line 200-231）

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `.github/workflows/ci.yml` | Modify | 加 `backend-py38` job + 守卫 + 触发条件更新 |
| `backend/requirements-py38.txt` | Create | Python 3.8 专用依赖列表（钉死版本） |

---

## Task 1: 建 feature 分支

**Files:** 无

- [ ] **Step 1: 切换到 main 并更新**

```bash
cd /home/fz/project/sage
git switch main
git pull --rebase origin main
```

- [ ] **Step 2: 建 feature 分支**

```bash
git switch -c ci/backend-py38-guard
```

- [ ] **Step 3: 验证状态干净**

```bash
git status
```

Expected: `nothing to commit, working tree clean`

---

## Task 2: 加 backend-py38 job（仅 win7 触发）

**Files:**
- Modify: `.github/workflows/ci.yml`（在 `backend` job 之前加 `backend-py38` job）

- [ ] **Step 1: 在 `backend` job 之前插入 `backend-py38`**

打开 `.github/workflows/ci.yml`，在 `jobs:` 关键字后第一个 job（即 `# ========== Backend: ...` 注释之前）插入：

```yaml
  # ========== Backend (Win7): Python 3.8 兼容性 ==========
  # - 仅 release/win7 触发（保护 win7 钉死的 Python 3.8 兼容性）
  # - 用独立 conda env sage-backend-py38 隔离 main 的 sage-backend
  # - 钉死依赖版本（backend/requirements-py38.txt）
  # - coverage 强门禁 ≥ 80%
  backend-py38:
    name: Backend (Python 3.8, Win7 LTS)
    if: github.ref == 'refs/heads/release/win7'
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Setup Miniconda + Python 3.8
        uses: conda-incubator/setup-miniconda@v3
        with:
          python-version: '3.8'
          channels: conda-forge

      - name: Create py38 env
        shell: bash -el {0}
        run: |
          conda create -n sage-backend-py38 python=3.8 -y
          conda run -n sage-backend-py38 pip install --upgrade pip

      - name: Install backend deps (py38, locked)
        shell: bash -el {0}
        run: |
          conda run -n sage-backend-py38 pip install -r backend/requirements-py38.txt
          conda run -n sage-backend-py38 pip install ruff mypy import-linter

      - name: Ruff check
        shell: bash -el {0}
        run: |
          conda run -n sage-backend-py38 ruff check backend/

      - name: Pytest (py38, hex mode) with coverage
        shell: bash -el {0}
        run: |
          conda run -n sage-backend-py38 bash -c "cd backend && pytest --cov --cov-report=xml --cov-report=term --cov-fail-under=80"

      - name: Upload coverage
        if: always()
        uses: codecov/codecov-action@v4
        with:
          file: backend/coverage.xml
          flags: backend-py38
          fail_ci_if_error: false

```

Expected: yaml 格式正确（`backend-py38:` 与 `backend:` 缩进一致）

- [ ] **Step 2: 验证 yaml 语法**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml').read()); print('valid YAML')"
```

Expected: `valid YAML`

- [ ] **Step 3: 验证 `if:` 守卫正确**

```bash
grep -A 2 "backend-py38:" .github/workflows/ci.yml | head -5
```

Expected: 看到 `if: github.ref == 'refs/heads/release/win7'`

---

## Task 3: 改 backend job 守卫（仅 main 触发）

**Files:**
- Modify: `.github/workflows/ci.yml`（`backend` job）

- [ ] **Step 1: 加 `if:` 守卫到 `backend` job**

找到 `backend:` job，在 `name:` 之后加 `if:` 守卫：

```yaml
  backend:
    name: Backend (Python)
    if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/develop'
    runs-on: ubuntu-latest
```

Expected: `backend` job 改为只跑 main / develop

- [ ] **Step 2: 验证守卫**

```bash
grep -B 1 -A 3 "^  backend:" .github/workflows/ci.yml | head -10
```

Expected: 看到 `if: github.ref == 'refs/heads/main' || github.ref == 'refs/heads/develop'`

---

## Task 4: 更新 PR / push 触发条件

**Files:**
- Modify: `.github/workflows/ci.yml`（line 4-5）

- [ ] **Step 1: 把 release/win7 加进 push 触发**

找到 line 4-5：

```yaml
  push:
    branches: [main, develop]
```

改为：

```yaml
  push:
    branches: [main, develop, release/win7]
```

- [ ] **Step 2: 验证 PR 触发条件**

```bash
grep -A 3 "pull_request:" .github/workflows/ci.yml | head -5
```

Expected: 看到 `branches: [main, develop, release/**]`（line 7 已有）

- [ ] **Step 3: 验证最终触发条件**

```bash
sed -n '3,9p' .github/workflows/ci.yml
```

Expected: push 有 `[main, develop, release/win7]`，PR 有 `[main, develop, release/**]`

---

## Task 5: 更新 all-green aggregator

**Files:**
- Modify: `.github/workflows/ci.yml`（line 236-251）

- [ ] **Step 1: 更新 needs 列表 + 检查条件**

找到 `all-green` job，把：

```yaml
  all-green:
    name: All Checks
    needs: [backend, frontend, electron-smoke]
    runs-on: ubuntu-latest
    if: ${{ always() }}
    steps:
      - name: Check all jobs passed
        run: |
          if [ "${{ needs.backend.result }}" != "success" ] || \
             [ "${{ needs.frontend.result }}" != "success" ] || \
             [ "${{ needs.electron-smoke.result }}" != "success" ]; then
            echo "One or more required jobs failed"
            exit 1
          fi
          echo "All required checks passed"
```

改为：

```yaml
  all-green:
    name: All Checks
    needs: [backend, backend-py38, frontend, electron-smoke]
    runs-on: ubuntu-latest
    if: ${{ always() }}
    steps:
      - name: Check all required jobs passed
        run: |
          set -e
          # 必过项：frontend + electron-smoke
          [ "${{ needs.frontend.result }}" = "success" ]
          [ "${{ needs.electron-smoke.result }}" = "success" ]
          # backend job：main 走 backend，win7 走 backend-py38（用 || 兜底）
          if [ "${{ needs.backend.result }}" != "success" ] && [ "${{ needs.backend-py38.result }}" != "success" ]; then
            echo "No backend job succeeded"
            exit 1
          fi
          echo "All required checks passed"
```

- [ ] **Step 2: 验证 yaml 语法**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml').read()); print('valid YAML')"
```

Expected: `valid YAML`

---

## Task 6: 加 backend/requirements-py38.txt 锁版本

**Files:**
- Create: `backend/requirements-py38.txt`

- [ ] **Step 1: 复制 requirements.txt 作基线**

```bash
cp backend/requirements.txt backend/requirements-py38.txt
```

- [ ] **Step 2: 钉死 win7 兼容版本**

用 Edit 工具改 `backend/requirements-py38.txt`，把表头加注释 + 钉死 Python 3.8 兼容版本：

```text
# Win7 LTS branch — Python 3.8 兼容依赖列表
#
# 任何 main 上升级的依赖**不**自动同步到这里
# 升级需走 cherry-pick PR + Win7 兼容性测试
#
# Python 3.8 兼容关键约束：
# - pydantic 钉 1.x（2.x 要求 3.9+）
# - fastapi 钉 0.85+（与 pydantic 1.x 兼容）
# - 其他依赖跟随 backend/requirements.txt 但带 == 版本
```

然后逐行加 `==` 版本号（**示例**，按实际 `requirements.txt` 内容调整）：

```text
fastapi==0.85.0
uvicorn[standard]==0.18.3
pydantic==1.10.2
# ...
```

- [ ] **Step 3: 验证文件存在**

```bash
ls -la backend/requirements-py38.txt
```

Expected: 文件存在，~30+ 行

- [ ] **Step 4: 验证 backend-py38 job 引用此文件**

```bash
grep "requirements-py38" .github/workflows/ci.yml
```

Expected: 看到 1 行匹配

---

## Task 7: 本地验证 yaml

**Files:** 无（仅验证）

- [ ] **Step 1: yaml 完整验证**

```bash
python3 -c "
import yaml
with open('.github/workflows/ci.yml') as f:
    doc = yaml.safe_load(f)
print('jobs:', list(doc['jobs'].keys()))
"
```

Expected: jobs 列表包含 `['backend-py38', 'backend', 'frontend', 'desktop-build', 'electron-smoke', 'all-green']`

- [ ] **Step 2: 验证 if 守卫数量**

```bash
grep -c "^    if:" .github/workflows/ci.yml
```

Expected: 看到至少 2 行 `if:`（backend-py38 和 backend 各一个）

- [ ] **Step 3: 验证 trigger**

```bash
sed -n '1,10p' .github/workflows/ci.yml
```

Expected: 看到 push 和 PR 触发条件

---

## Task 8: 提交 PR

**Files:** 暂存所有变更

- [ ] **Step 1: 检查状态**

```bash
git status
```

Expected: 看到 `.github/workflows/ci.yml` (M) 和 `backend/requirements-py38.txt` (A)

- [ ] **Step 2: 暂存**

```bash
git add .github/workflows/ci.yml backend/requirements-py38.txt
```

- [ ] **Step 3: 提交**

```bash
git commit -m "ci(workflows): 加 backend-py38 job + 分支守卫 win7 LTS 强门禁

- backend-py38 job：仅 release/win7 触发，钉死 Python 3.8 + 锁版本
- backend job：守卫 main / develop，跳过 win7
- 触发条件：push 加 release/win7；PR 已有 release/**
- all-green aggregator：兼容双 backend job（main 走 backend，win7 走 backend-py38）
- 加 backend/requirements-py38.txt 钉死 win7 依赖版本

验证矩阵：
- push to main: backend (py3.10) + frontend + desktop-build + electron-smoke + all-green
- push to release/win7: backend-py38 (py3.8) + frontend + desktop-build + electron-smoke + all-green
- PR to release/**: 同 push

Refs: docs/superpowers/specs/2026-06-13-electron-branch-strategy-design.md#6"
```

- [ ] **Step 4: 推 + 开 PR**

```bash
git push -u origin ci/backend-py38-guard
gh pr create --title "ci: add backend-py38 job + branch guard for Win7 LTS" --body "见 commit message"
```

Expected: PR URL 输出

---

## Self-Review Checklist (执行前)

- [ ] Task 1-8 全部步骤可执行（无占位符）
- [ ] YAML 缩进正确（GitHub Actions 严格 2 空格缩进）
- [ ] `if: github.ref` 守卫逻辑正确（main / win7 互斥）
- [ ] `all-green` needs 列表含两个 backend job
- [ ] `backend/requirements-py38.txt` 版本钉死（不与 main 共享）
- [ ] PR 触发条件 `release/**` 已存在（line 7）

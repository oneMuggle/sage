# Sage 项目 Claude 约束

> 本文件由用户授权写入，作为项目级 Claude Code 运行约束。优先级高于全局默认。

## Python 后端环境（强制）

**项目后端 Python 依赖安装在 conda 虚拟环境 `sage-backend` 中**，
不要使用系统 `python3` / `pip` 安装或运行后端代码，否则会报
`ModuleNotFoundError: No module named 'fastapi'` 等错误。

### 环境路径

```
/home/fz/anaconda3/envs/sage-backend
```

### 激活方式（二选一）

```bash
# 方式 1：直接调用解释器（推荐，用于脚本/CI）
/home/fz/anaconda3/envs/sage-backend/bin/python ...

# 方式 2：先激活再使用（用于交互式 shell）
conda activate sage-backend
```

### 启动后端

```bash
# 端口由 backend/main.py 中 PYTHON_BACKEND_PORT 控制，默认 8765
conda activate sage-backend && cd /home/fz/project/sage && python backend/main.py

# 或前台带 reload（开发用）
conda activate sage-backend && cd /home/fz/project/sage && \
  python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765
```

健康检查：`curl http://127.0.0.1:8765/health`

### 重新安装依赖（仅限在 sage-backend 环境中）

```bash
/home/fz/anaconda3/envs/sage-backend/bin/pip install -r /home/fz/project/sage/backend/requirements.txt
```

## 前端环境

Node.js 已通过 nvm 安装：`/home/fz/.nvm/versions/node/v25.9.0/bin/node`

```bash
# 安装依赖（如尚未安装）
cd /home/fz/project/sage && npm install

# 开发服务器（端口由 vite.config.ts 锁定为 1420，Tauri 默认）
cd /home/fz/project/sage && npm run dev   # http://localhost:1420

# 生产构建
cd /home/fz/project/sage && npm run build
```

## 端口约定

| 服务           | 端口 | 备注                                                                  |
| -------------- | ---- | --------------------------------------------------------------------- |
| 前端 (Vite)    | 1420 | `vite.config.ts` 默认;worktree 用 `VITE_DEV_PORT` 环境变量覆盖         |
| 后端 (FastAPI) | 8765 | `backend/main.py` 默认;worktree 用 `PYTHON_BACKEND_PORT` 环境变量覆盖  |
| Electron 桌面  | —    | Electron 21.4.4 已装                                                   |

## 并行开发（Git Worktree）

当需要同时持有多个 `feat/*` / `fix/*` 分支、或与 `release/win7` 维护工作并行 cherry-pick 时,
**优先使用** `scripts/worktree.sh new <branch>` 开 worktree,而不是反复 `git switch`。

每个 worktree 自动分配独立端口对(主目录 8765/1420 → worktree A 8766/1421 → worktree B 8767/1422 ...),
通过 `set -a && source .env.local && set +a` 让端口生效。

完整用法、`.claude/worktrees/` agent 隔离边界、故障排查见
[`docs/technical/47-git-worktree-workflow.md`](../docs/technical/47-git-worktree-workflow.md)。

⚠️ **不要** 在 worktree 里装包到共享 `sage-backend` 环境——会污染 main。如需临时依赖,
worktree 内用 `python -m venv .venv` 隔离。

## Electron 桌面构建

| 命令 | 用途 |
| --- | --- |
| `npm run electron:dev` | 桌面端开发模式（自动启 Vite + 后端 Python 子进程） |
| `npm run electron:build` | 桌面端生产构建 |

## 双分支长期共存策略（强制）

项目采用 **main + release/win7 双分支长期共存**架构,两个分支各自独立演进,**严禁删除或合并 release/win7 分支**。

### 分支定位

| 分支 | 用途 | 技术栈 | EOL |
|------|------|--------|-----|
| `main` | 主开发分支 | Electron 21.4.4 + Python 3.11 + Chromium 106 | 持续维护 |
| `release/win7` | Win7 LTS 维护分支 | Electron 21.4.4 + Python 3.8 + Chromium 106 | **2027-12-13** |

### 核心规则

1. **release/win7 分支不可删除**:此分支服务 Windows 7 SP1 用户,直到 2027-12-13 EOL 后方可归档
2. **不主动合并**:两个分支独立演进,main 的新功能不强制同步到 release/win7;release/win7 的 Win7 特定修复不合并回 main
3. **按需 cherry-pick**:安全补丁或关键 bug 修复可以 cherry-pick 到另一分支,但需手动解决冲突并测试
4. **依赖版本独立**:
   - main 使用 `backend/requirements.txt`(Python 3.11,pydantic 2.x)
   - release/win7 使用 `backend/requirements-py38.txt`(Python 3.8,pydantic 1.x)
   - **不要**将 main 的依赖升级自动同步到 release/win7
5. **CI 隔离**:
   - main 触发 `.github/workflows/ci.yml` 和 `.github/workflows/release.yml`
   - release/win7 触发 `.github/workflows/ci.yml`(py38 测试)和 `.github/workflows/release-win7.yml`
6. **标签规则**:
   - main:普通版本标签 `v*`(如 `v0.2.0`)
   - release/win7:LTS 标签 `v*-lts`(如 `v0.2.1-lts`)

### Python 3.8 环境(仅 release/win7 分支)

在 release/win7 分支上工作时,后端使用 Python 3.8 环境:

```bash
# conda 环境
conda activate sage-backend-py38

# 或直接调用
/home/fz/anaconda3/envs/sage-backend-py38/bin/python
```

**注意**:不要将 Python 3.11 的依赖安装到 py38 环境,也不要在 main 分支上使用 py38 环境。

### Claude 操作约束

- **禁止**执行 `git branch -D release/win7` 或 `git push origin --delete release/win7`
- **禁止**将 release/win7 合并到 main(`git merge release/win7`)
- **禁止**在 main 分支上修改 `backend/requirements-py38.txt`
- **禁止**在 release/win7 分支上修改 `backend/requirements.txt`
- 如需在两个分支间同步代码,**必须**使用 cherry-pick 并手动验证兼容性

## 后端启动契约与 SAGE_LOCAL_AUTH_TOKEN（2026-09 事件后置入）

后端是 FastAPI + `LocalAuthMiddleware` 守护的本地服务（默认 8765）。
中间件要求每个非公开请求带 `Authorization: Bearer ${SAGE_LOCAL_AUTH_TOKEN}`，
缺/不匹配 → 401 `{"detail":"本地授权凭据无效或缺失"}`。

### 两种启动模式必须保持 token 一致

| 模式 | 谁启动后端 | token 来源 | 何时使用 |
|---|---|---|---|
| **正常模式**（推荐） | Electron `spawnBackend()` | Electron mint 随机 token，通过 spawn env 注入到子进程 | `npm run dev` + `./node_modules/.bin/electron --no-sandbox .` |
| **SKIP_BACKEND 模式** | 外部进程（开发者手启 / CI fixture） | 启动前 **必须** 由调用方设置 `SAGE_LOCAL_AUTH_TOKEN=<shared>`，Electron 与后端读同一个值 | 调试、CI、隔离验证 |

### 禁止的反模式（导致本次 401 事件）

- ❌ 手动 `python backend/main.py` 而 Electron 处于正常模式 → 后端用 `secrets.token_urlsafe(32)` 自生成 token，与 Electron 注入的不匹配 → 三页全 401
- ❌ 启动后端时忘了 export `SAGE_LOCAL_AUTH_TOKEN`（SKIP_BACKEND 模式）→ 同上
- ❌ 用 `SAGE_SKIP_BACKEND=1` 启动 Electron 但不传 token → 启动期会 `logger.warn` 提醒，但请求时仍 401

### 正常模式启动顺序（按 `.claude/skills/run-desktop/SKILL.md`）

```bash
# 1. Vite (后台)
npm run dev
# 2. Electron（自带 spawnBackend，自动注入匹配的 token）
./node_modules/.bin/electron --no-sandbox .
```

**正常模式启动顺序**任选其一（`package.json` 的 `electron:dev` 已带 `--no-sandbox`，2026-09 后），效果等价：

- 一键式：`npm run electron:dev`（自动跑 `build:electron` + `electron --no-sandbox .`）
- 分步式：`npm run dev` + `./node_modules/.bin/electron --no-sandbox .`（Vite 和 Electron 在各自 shell，便于独立看日志）

**不要**手启后端让 Electron 走 SKIP_BACKEND 模式（除非真的需要）。

### SKIP_BACKEND 模式启动顺序（仅调试/必要时）

```bash
# 1. 选一个固定 token（必须双方一致）
export SAGE_LOCAL_AUTH_TOKEN="sage-dev-shared-$(date +%s)"

# 2. 启动后端（用同一 shell 让 env 生效）
conda activate sage-backend && python -m backend.main &

# 3. 启动 Electron
SAGE_SKIP_BACKEND=1 SAGE_LOCAL_AUTH_TOKEN="$SAGE_LOCAL_AUTH_TOKEN" \
  ./node_modules/.bin/electron --no-sandbox .
```

### 401 时怎么快速诊断

1. `curl http://127.0.0.1:8765/health` — 应 200。如果失败 → 后端根本没启
2. 找 Electron pid（`pgrep -f 'electron/dist/electron' | head -1`），再找后端 pid（`pgrep -f 'backend.main'`）
3. 比对两者 environ 中 `SAGE_LOCAL_AUTH_TOKEN`：

   ```bash
   for p in $(pgrep -f 'electron/dist/electron' | head -1) $(pgrep -f 'backend.main'); do
     grep -z '^SAGE_LOCAL_AUTH_TOKEN=' /proc/$p/environ 2>/dev/null \
       | tr '\0' '\n' | sed 's/^/    pid='$p' /'
   done
   ```

   两个 sha256 前缀不一致 → token 失配，重启桌面端
4. **不要**把 raw token 贴进日志或聊天（项目安全规范）

### 启动期 token 失配检测（2026-09 后已加）

SKIP_BACKEND 模式下，`electron/main.ts` 在 `createMainWindow()` 之后会
fire-and-forget 启动 `probeBackendAuthForSkipBackend()`，打
`/api/v1/memory/list?page_size=1` 验证 token 是否被后端接受。

- 200 → 一切正常，静默
- 401 → 发 `backend:auth-failed` IPC，`BackendStatusBanner` 统一显示诊断
  「后端授权凭据失效（HTTP 401）。请重启 Sage 桌面端恢复」

## 默认任务规范

- 任何涉及后端 Python 代码的运行/调试/测试，**必须**使用 `sage-backend` conda 环境。
- **正常模式**：先启前端 `npm run dev`（Vite, 端口 1420），再启 `./node_modules/.bin/electron --no-sandbox .`（Electron 自带 `spawnBackend()`，不需要也不应该手启后端）。
- **仅当确实需要 SKIP_BACKEND 模式**（调试后端、CI fixture 等）：参考上方"SKIP_BACKEND 模式启动顺序"，并保证两边 token 一致。
- 端口冲突时优先修改后端端口 `PYTHON_BACKEND_PORT`，不要改前端默认端口。

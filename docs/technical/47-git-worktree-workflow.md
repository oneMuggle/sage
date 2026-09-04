# Git Worktree 并行开发工作流

> Sage 在 main + release/win7 双分支长期共存策略下，开发者经常需要同时跑多个 `feat/*` / `fix/*` 分支。
> 本文档配套 `scripts/worktree.sh` helper，说明如何用 Git Worktree 实现"不切分支、不丢改动"的并行开发。

## 1. 为什么需要 Worktree

### 1.1 痛点

| 痛点 | 单一工作区的表现 | Worktree 的解决 |
|---|---|---|
| 切分支丢未提交改动 | `git switch feat-x` 会挡住未保存改动，必须 stash / commit / 丢弃三选一 | 改动锁在自己的 worktree 里，互不干扰 |
| 同时跑两个分支的 E2E | 必须 stash + switch，启动慢、上下文断 | 每个 worktree 独立跑后端 + 前端 |
| 端口冲突 | 默认 8765 / 1420 同时只允许一个进程占 | 每 worktree 分配独立端口对 |
| npm / pip 依赖冲突 | 两个分支不同依赖版本要切换 | 每个 worktree 独立 `node_modules`（现状是 npm，每个 worktree 各自 `npm install`） |
| 半成品分支 commit 进度受挫 | 想保留半成品切换 debug 又不想污染 log | 半成品留在自己 worktree 里，继续开新 worktree |

### 1.2 适用场景

- 同时持有两个未完成的 `feat/*` / `fix/*` 分支
- Win7 (release/win7) 与 main 双分支维护期间需要并行 cherry-pick
- 长时间跑后台任务（如监控脚本、bundled python 启动）时切分支不打断
- 多个 agent 子任务并发（参见 `42-chat-multi-agent-orchestration.md` 中的 `worktree` 隔离维度）

### 1.3 不适用场景

- 单一小改动（走标准 PR 流程即可）
- 调试完即扔的临时验证（直接 `git switch` + 完成即合并更轻量）

---

## 2. 核心原理（精简版）

Git Worktree = **同一个 `.git/` 仓库下挂多个工作区**，每个工作区有自己的 HEAD、暂存区、reflog，但共享所有 commit 对象与分支指针表。

- 物理上：每个 worktree 目录里的 `.git` 是一个文本文件，指向 `.git/worktrees/<name>/` 元数据子目录
- 共享：`objects/`、`refs/heads/`、`refs/remotes/`、`config`
- 独立：`HEAD`、Index、工作区文件、未提交改动、`logs/HEAD`

约束：**同一分支不能同时在两个 worktree checkout**——所以 helper 会先 `git worktree list --porcelain` 检查冲突。

详细原理见 `git-worktree(1)` 手册。

---

## 3. 端口分配机制

### 3.1 默认端口

| 服务 | 默认端口 | 来源 |
|---|---|---|
| 后端 (FastAPI) | **8765** | `backend/main.py:777` 读 `PYTHON_BACKEND_PORT` 环境变量 |
| 前端 (Vite) | **1420** | `vite.config.ts` 读 `VITE_DEV_PORT`（2026-09-04 改造） |
| Electron | 同后端 | `electron/main.ts:68` 读 `PYTHON_BACKEND_PORT` |

`backend/main.py` 和 `electron/main.ts` **早已支持环境变量覆盖**——本次基础设施建设的唯一代码改动是把 `vite.config.ts` 的硬编码 `port: 1420` 改成 `Number(process.env.VITE_DEV_PORT ?? 1420)`，并保留 `strictPort: true` 保证端口冲突时快速失败。

### 3.2 Worktree 端口分配

`scripts/worktree.sh new` 扫描 `.worktrees/*/.env.local`，取已用端口最大值 +1 写入新 worktree 的 `.env.local`。例：

```
.worktrees/
├── feat-agent-profile-migration/.env.local  → PYTHON_BACKEND_PORT=8766 VITE_DEV_PORT=1421
├── fix-cite-collapse/.env.local             → PYTHON_BACKEND_PORT=8767 VITE_DEV_PORT=1422
```

**重要**：进入 worktree 后必须 `source .env.local` 才能让端口生效：

```bash
cd .worktrees/feat-agent-profile-migration
set -a && source .env.local && set +a   # 导出所有 PYTHON_BACKEND_PORT / VITE_DEV_PORT
npm run dev                              # vite 现在会监听 :1421
```

否则 vite 会落到默认 1420，与其他 worktree 撞端口。

### 3.3 端口冲突排查

- `strictPort: true` 让 vite 启动失败时立即报错，不会"自动换端口"——这是想要的
- `electron/main.ts` 启动后端时如果端口被占，会 `EADDRINUSE` 失败——helper 报的端口是建议值，但用户能在 `.env.local` 改成其他空闲端口

---

## 4. 日常用法

### 4.1 创建 worktree

```bash
# 从当前 HEAD 切新分支
scripts/worktree.sh new feat/my-feature

# 显式指定基分支
scripts/worktree.sh new feat/my-feature --base main
scripts/worktree.sh new feat/my-feature --base release/win7

# 复用已有分支
# （helper 检测到分支存在则走 git worktree add <dir> <branch>，不创建新分支）
scripts/worktree.sh new feat/my-existing-feature
```

### 4.2 启动开发

```bash
cd .worktrees/feat-my-feature
set -a && source .env.local && set +a

# 首次需要
npm install
/home/fz/anaconda3/envs/sage-backend/bin/pip install -r backend/requirements.txt  # 共享环境已装可跳过

# 启动前端
npm run dev    # http://localhost:1421

# 启动后端
conda activate sage-backend && python -m backend.main  # http://localhost:8766
```

### 4.3 查看所有 worktree 与端口

```bash
scripts/worktree.sh ports
# PATH                                                         BACKEND    FRONTEND
# ------------------------------------------------------------ ---------- ----------
# /home/fz/project/sage/.worktrees/feat-agent-profile-migration 8766      1421
# /home/fz/project/sage/.worktrees/fix-cite-collapse            8767      1422
# Main checkout defaults: backend=8765 frontend=1420
```

`scripts/worktree.sh list` 等价于 `git worktree list`，会同时显示主目录和历史 sibling-dir worktree。

### 4.4 移除 worktree

```bash
scripts/worktree.sh remove feat/my-feature
# 1. 删除 .worktrees/feat-my-feature/
# 2. 如果分支名以 feat/fix/refactor/hotfix 开头且没有未合并 commit，自动 git branch -D
```

如要保留分支：

```bash
git worktree remove .worktrees/feat-my-feature
git branch -d feat/my-feature   # 小写 -d，未合并会拒绝
```

### 4.5 清理

```bash
scripts/worktree.sh clean
# 1. git worktree prune       清理幽灵 worktree（手动 rm 后的元数据）
# 2. rmdir .worktrees/*/      删空目录
```

手动 `rm -rf` 的 worktree 会让 `git worktree list` 显示 `prunable`，跑 `clean` 即修复。

---

## 5. 双分支（main + release/win7）场景

Sage 项目的 `release/win7` 是 LTS 维护分支，到 2027-12-13 前独立演进。Worktree 适合 Win7 修复流程：

```bash
# 在主目录的 main 上
scripts/worktree.sh new fix/win7-reasoning-dedup --base release/win7
cd .worktrees/fix-win7-reasoning-dedup
set -a && source .env.local && set +a
# 编辑代码...专门为 Win7 测试 (Python 3.8 / pydantic 1.x)
conda activate sage-backend-py38
python -m backend.main
# ...
```

**注意**：
- 不要在 Win7 worktree 里装 main 的依赖——共用 `sage-backend` 会污染，Win7 用 `sage-backend-py38`
- 不要把 Win7 worktree 里的 commit merge 回 main，反之亦然——按需 cherry-pick

---

## 6. 与现有 .claude/worktrees/ 的关系

`.claude/worktrees/` 是 Claude Code agent 子任务的隔离目录（参见 `42-chat-multi-agent-orchestration.md`），脚本 `scripts/worktree.sh` **不管理**此目录——它由 Claude Code 内部 lifecycle 管控。

两套机制并存：
- 开发者手动：`scripts/worktree.sh` → `.worktrees/`
- Agent 自动：Claude Code → `.claude/worktrees/`

两者互不干扰，`.gitignore` 同时忽略两个目录。

---

## 7. CI 与 Electron 集成

### 7.1 CI

CI 流水线（`release.yml` / `release-win7.yml`）继续在 `main` / `release/win7` 分支上跑，不走 worktree。每个 worktree 内部可以本地跑：

```bash
# 在 .worktrees/feat-X/ 内
./node_modules/.bin/vitest run tests/vite-config.test.ts    # 端口冲突风险低
npm run test:run -- --no-coverage                            # 同上
./scripts/pytest.sh                                          # 用 conda 共享环境即可
```

CI 上跑 E2E 测试不会受影响。

### 7.2 Electron 桌面端

**同一台机器只建议跑一个 Electron 实例**（端口冲突问题），但可以多个 worktree 跑后端 + Vite：

| 模式 | 多 worktree 兼容？ | 推荐场景 |
|---|---|---|
| 后端 + Vite | ✅ 端口已分配 | 日常开发 |
| 后端 + Vite + Electron | ⚠️ Electron 用 `SAGE_LOCAL_AUTH_TOKEN` + 后端端口，但 **Electron 内部打包流程会独占端口做 live reload** | 单一 worktree 测桌面端 |
| 多个 Electron 同时 | ❌ 物理上只能一个窗口实例 | 不可行 |

如需在多个 worktree 测桌面端：分别跑后端 + Vite，把 Electron 关掉，测 web 模式或 PR 集成测试。

---

## 8. 故障排查

| 症状 | 原因 | 修复 |
|---|---|---|
| `fatal: 'feat-x' is already checked out` | 同分支被另一 worktree 占用 | `git worktree list` 找到占用方，先移除 |
| vite 启动报 `Port 1421 is already in use` | 忘 `source .env.local` 或端口被外部进程占用 | `lsof -i:1421` 查占用方；或改 `.env.local` |
| `.env.local` 不存在 | worktree 是手动建的，绕过 helper | `cp .worktrees/其他/.env.local .` 或重新 `scripts/worktree.sh remove` + `new` |
| `git worktree list` 显示 `prunable` | 手动 `rm -rf` worktree 目录 | `scripts/worktree.sh clean` 跑 `git worktree prune` |
| worktree 在 sibling-dir 不在 `.worktrees/` | 历史约定（PR #402 之前） | 保持不动，新 worktree 用 helper |
| 后端 conda 环境装包污染 `sage-backend` | worktree A 临时 `pip install` 新包到共享 `sage-backend` | 改用 worktree 内 `python -m venv .venv` 隔离 |

---

## 9. 文件清单

| 文件 | 作用 |
|---|---|
| `scripts/worktree.sh` | helper 脚本（new / list / ports / remove / clean） |
| `vite.config.ts` | 端口改为 `VITE_DEV_PORT` 环境变量驱动 |
| `backend/main.py` | 已支持 `PYTHON_BACKEND_PORT`（未改动） |
| `electron/main.ts` | 已支持 `PYTHON_BACKEND_PORT`（未改动） |
| `.gitignore` | `.worktrees/` 已忽略（未改动） |
| `docs/technical/47-git-worktree-workflow.md` | 本文档 |

---

## 10. 参考

- Git 官方手册 `git-worktree(1)`
- 项目级 `CLAUDE.md` §「双分支长期共存策略」
- `docs/technical/30-release-tiers.md` §「Win7 LTS 派生」
- `docs/technical/42-chat-multi-agent-orchestration.md` §「worktree 隔离」
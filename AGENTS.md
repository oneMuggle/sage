# AGENTS.md —— AI 会话 / 贡献者协作规范

> 面向在本仓库工作的 AI 会话与贡献者的操作规范。保持一屏内必读 + 指针；
> 深层设计见 §指针，不在本文重复。

## 核心原则

1. **spec 先行**：功能批次先有方案文档（`docs/plans/`），后写代码。
2. **单一所有者**：每个 worktree / 分支只属于一个会话。开工前确认目标
   文件没有其他会话的未合并改动（`git log origin/main -- <path>`）。
3. **基线棘轮**：架构基线（`architecture-baseline.json`）与 knip 报告
   只增不减——新增违规即红，存量消化靠批次，不靠一次性大扫除。
4. **真实门禁**：本地 hook 是冒烟，**CI 才是权威门禁**。未引导的
   worktree 推送用 `--no-verify` 绕过本地假警报是可接受的（PR CI 会
   跑完整套件），但必须在 PR 描述里说明。
5. **不发 Main checkout 的 WIP**：主 checkout（`E:\...\sage`）可能带有
   其他会话的暂存现场——一律在 `.worktrees/<名>` 的独立 worktree 工作。

## 命令表

| 场景 | 命令 |
| --- | --- |
| 开工检查（分支落后检测） | `node scripts/check-branch-freshness.mjs` |
| 前端测试 | `npx vitest run`（CI 同款；全量 ~5 min） |
| 后端测试 | `cd backend && pytest -q`（conda env `sage-backend`） |
| win7 线测试 | conda env `sage-backend-py38` + `requirements-py38.txt` |
| 死代码检测 | `npm run knip` |
| 类型检查 | `npm run typecheck` + `npm run typecheck:electron` |
| 仓库清理 | `node scripts/clean.mjs`（dry-run）→ `--yes` 执行 |
| 零 check-run 排查 | `GET /contents/<workflow>?ref=<base>` 看 `on:` 块有无 `paths-ignore` |
| 人工重跑某分支全量验证 | `gh workflow run ci-rerun.yml --ref <分支> -f ref=<分支> -f target=<main\|release/win7>` |

## 并行会话协作规则（血泪沉淀，违反必踩坑）

1. **push/PR 前先 `git fetch` 并确认 base 未移动**。base 移动后 PR 的
   合并提交会带入他人改动——红 PR 先查「是不是 base 变了」（实例：
   #1381 曾因基线被外部更新而红）。
2. **PR 零 check-run 先查 `paths-ignore`，别急着怀疑平台**。`release/win7` 的
   `ci.yml` 曾给 `pull_request` 挂 `paths-ignore: docs/**`，而 win7 分支保护要
   5 个必需 check——纯文档 PR 被整条 workflow 跳过、**一个 check-run 都不产生**，
   于是永远 `mergeable_state=blocked`。这与「事件被丢弃」在 API 上表象完全一样
   （零 run、零 check-run），极易误判。close+reopen、换新分支重开、推新提交触发
   `synchronize`、ci-rerun 补跑**全部无效**（都不改变 changed files 集合）。
   已于 #1886 移除 `pull_request` 上的过滤（`push` 侧保留）。判据：同一仓库
   main 基的文档 PR 从来没出过这问题 → 就是分支配置差异。详见
   [§7.3 事实零](./docs/plans/2026-10-01_ux-ia-round3-panel-slot.md)。
3. **`workflow_dispatch` 的 check-run 不参与 PR 分支保护判定**，所以 ci-rerun
   补跑**不能**让红/卡住的 PR 恢复可合并，它只是对某分支做一次等价于 ci.yml
   的人工验证。同理 `gh workflow run` 的 `--ref`（决定 run 挂哪个 ref、check 记
   到哪个 SHA，且决定用哪个分支的 workflow 文件版本）与 `-f ref=`（workflow 输入，
   决定 checkout 哪个分支）**两个都要给**，漏 `--ref` 会静默跑到 main 上、白烧
   一轮 py38。
4. **类型再导出（barrel `export type {...}`）在运行时不存在**——
   清理它们不可能引起运行时回归；值导出则相反，删前必须 grep 全仓
   引用（含目录式 import）。
5. **py38 兼容（release/win7 线）**：`zip(strict=)`、PEP604 isinstance、
   `datetime.UTC`、构造期 `asyncio.Lock()` 都是雷。修复惯例见
   `backend/requirements-py38.txt` 注释与 #1228 惯例。
6. **MSYS/Git Bash 路径转换**：`rev:path` 参数会被转坏——脚本里用
   `MSYS_NO_PATHCONV=1`，或把文件写到实盘路径再处理。

## 已知已修复的坑（勿重复踩，保留案例）

- vitest API server 51204 端口僵尸阻断（R121/#1542 已 `api: false` 根治）
- architecture-check 在 Windows 失效（基线键路径分隔符，#1381 内修复）
- todo 分桶测试每日 UTC 23 点定时红（R97 冻结时钟方案修复）
- ci-rerun 不可 dispatch / 永远验证 main（#1507/#1511 修复）
- win7 `ci.yml` 的 `pull_request` paths-ignore 致纯文档 PR 永不建 run（#1886 修复）
- 会话持久 cwd 指向已删除的 worktree → 一切命令 spawn ENOENT，极易误判为
  杀软拦截（R41 期实证：重建同名空目录即恢复）。规程：清理 worktree 前，
  先把 shell 持久 cwd 移回主检出
- Windows 时钟粒度 ~15.6ms：测试内 `sleep(0.01)` 不足以隔开先后时间戳
  （todo 测试 R39/#1597 对齐 0.02；同族用例新增时直接用 ≥0.02）
- 新合入的"分支新鲜度门禁"：落后 main 较多的分支 CI 不触发——把最新 main
  merge 进分支再推即恢复（R42 期实证）

## 指针

- [设计哲学](./PHILOSOPHY.md) · [对齐标准](./PARITY.md) · [贡献流程](./CONTRIBUTING.md)
- [质量门禁](./docs/technical/15-quality-gates.md) · [win7 LTS](./docs/technical/31-win7-lts.md)
- Arena 移植验收：[docs/verification/2026-09-19-aren-card-port.md](./docs/verification/2026-09-19-aren-card-port.md)

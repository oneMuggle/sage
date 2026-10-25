# R105 批次计划 —— architecture-check 失败输出补修复指引（流程 DX）

日期：2026-09-23 ｜ worktree：`.worktrees/feat-r105-scan`（基于 origin/main a5a0d035）

## 背景

`architecture-baseline.json` 棘轮门禁在本会话内三次红掉 main（r94 两文件、
r98 database.py、r101 database.py）——均为并发 PR 合法增长文件后不知道/忘了
拨基线。当前失败输出只列违规清单，不含"怎么修"，每次都需要迭代一轮 CI 才
能定位。

## 批次内容

`scripts/architecture-check.mjs` 失败分支各补一段 Fix 提示（仅 console.error
文案，不改判定逻辑与退出码）：

- **BASELINED files that have grown** → 提示：若增长是有意的，把
  `architecture-baseline.json` 中该文件条目更新为新行数（附本批违规文件的
  目标行数清单），并明确"不得调低既有条目"（棘轮单向性）；否则缩回基线尺寸。
- **NEW files exceeding maxFileLines** → 提示：重构到 800 行以内；若为既有
  存量大文件无法在本 PR 拆分，按当前行数加入 baseline。

## 验证矩阵

- 本机 node 实跑两条路径：
  - clean 路径：`All files within limits (69 baselined, ...)` 不受影响；
  - 失败路径：临时把一条基线改为 1 → hint 输出含具体目标行数（1010）与
    "do not lower existing entries"，exit 1；验证后基线文件还原。

## 影响面

- CI-only 脚本，无 win7 影响面；无生产代码改动。

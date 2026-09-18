# 编码代理对标差距分析·第三十轮：run 级耗时与上限提示（BU16）

- **状态**：批次 A 交付中（分支 `feat-parity-r30-batch-a`，基线 origin/main 87d7de3f = #1178）
- **上游文档**：round21（BU11 run 墙钟上限）、round25（RD15 上限设置透出）、round29（BU15 任务级实时耗时）
- **对标对象**：Claude Code（整任务实时计时）、Devin（会话计时 + 上限提示）
- **编号约定**：延续 BU 系

## 0. 结论速览

BU15 给了任务级实时计时，但进度行没有 run 级时钟——用户设了
`runWallClockLimitMinutes`（round25 透出）却看不到"已运行多久 / 离上限多远"。
本轮在任务树进度行加 run 级耗时（in-flight 实时 tick、终态冻结为总时长），
设置上限时并显"· 上限 Y 分钟"。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU16 | 进度行无 run 级耗时/上限提示 | TaskTreeSection 仅任务级 elapsed | Devin 会话计时 | **P3** |

## 2. 设计（批次 A：BU16）

- **渲染**：进度行 `完成 X/Y` 后追加 `· 已运行 <elapsed>`（数据源
  board.dispatchedAt；in-flight 时随 BU15 的 tick 更新，allDone 后自然冻结）；
  `useSettings().settings.orch?.runWallClockLimitMinutes > 0` 时再显
  `· 上限 Y 分钟`。
- **格式**：复用 formatElapsed（<60s 秒 / <1h 分秒 / 时分）。
- **测试**：TaskTreeSection 3 例（in-flight 显示并计时 / 上限提示渲染 /
  终态冻结不消失且无数值跳动）。

## 3. 批次 A 实施与验证记录

- **TaskTreeSection**：进度行 `data-testid="task-tree-run-elapsed"`
  `已运行 <elapsed>`（数据源 board.dispatchedAt；tick 条件扩为
  running>0 或 queued>0，allDone 后停表冻结）；上限 >0 时并显
  `· 上限 Y 分钟`（round25 设置键）。formatElapsed 复用 BU15。
- **测试基建**：useSettings mock 改 vi.hoisted + vi.fn（可 mockReturnValue
  覆盖 orch 键），默认返回值保持既有用例兼容。
- **测试**：+2 例（in-flight 计时与上限提示 / 终态冻结且无上限不提示），
  文件 16 例全绿。
- 验证：`tsc --noEmit` 干净；eslint 改动文件零告警。后端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：PR #1183（squash `dd679abe`，2026-09-19 merge，CI 12 项全绿）。
- **win7 对齐**：随四轮合并 PR #1186（squash `ee61fbb1`，2026-09-19 merge，
  真 py38 必过项全绿；win7 基底 vitest 16 例本地全绿）。
- **回填分支**：`docs/r28-31-backfill`（本提交）。

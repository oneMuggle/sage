# 编码代理对标改进·双分支交付总账（Round 7-36 索引）

> 本文件是对标改进循环（差距分析 → worktree → 方案文档 → 实施 → PR → CI
> 绿 → merge → win7 对齐 → 清理 → §回填）的交付总账。每轮详情见同目录
> `*coding-agent-parity-round*.md`；本文件只做导航与经验沉淀。

## 1. 交付轮次索引（main PR / win7 PR / squash SHA）

| 轮 | 主题（编号系） | main | win7 |
| --- | --- | --- | --- |
| R7-R16 | 预算/取消归因/回放/collect（BU1-6/RV1-3/BD1-5 等） | 各轮 PR | 各轮对齐 PR |
| R17 | BD6 collect 超时部分聚合 | #966 段 | ✓ |
| R18 | BD7 快照 aggregate + 稳定性 | #986 段 | ✓ |
| R19 | BU8 头部消耗进度行 | #1032 段 | ✓ |
| R20 | BU9/BU10 任务树消耗可见性 | #1044 段 | ✓ |
| R21 | BU11 run 墙钟上限 | #1051 段 | ✓ |
| R22 | RD14 重派链上限 + BU12 | #1049 段 | ✓ |
| R23 | RT23 usage_events.task_id 归因 | #1049（代码随 #998 链路合并） | #1055 `51038fea` |
| R24 | BU13 per-task 消耗 + duration_ms | #1088 `76311cc5` | #1094 `3d88507e` |
| R25 | RD15 编排守门键透出设置页 | #1099 `648a4aa7` | #1104 `9ed8c28c` |
| R26 | RD16 worktree 隔离开关 + scratchRoot | #1113 `04b9f3c7` | #1117 `f1d91758` |
| R27 | RV4 单任务重试（task_ids 子集） | #1150 `8d9b307c` | #1154 `bfb8bd03` |
| R28 | BU14/BD8 守门状态透出 | #1160 `f4548baf` | #1186 `ee61fbb1`（四轮合并） |
| R29 | BU15 running 实时计时 | #1169 `ce5df32c` | 同上 |
| R30 | BU16 run 级耗时 + 上限提示 | #1183 `dd679abe` | 同上 |
| R31 | BU17 聚合块消耗标注 | #1188 `9ae4c6db` | 同上 |
| R32 | RT24 orch_tasks 用量/时长持久化 | #1195 `28a83c7c` | #1200 `297f0655` |
| R33 | RD18 级联跳过根因徽章 | #1208 `e879461b` | 并行 #1245 已交付同款 |
| R34 | BU18 聚合头部剩余额度/已运行分钟 | #1253 `5c9f28f8` | #1258 `4b0eb562` |
| R35 | RD19 Drawer 消耗/时长统计 | #1265 `e3f1d7a1` | #1268 `fbbb2886` |
| R36 | BU20 聚合块时长标注 | #1276 `a9d06741` | #1277 `f5477f33` |
| R37 | 交付总账（本文件） | #1283 `4cc8b3e6` | 文档无需对齐 |
| R38 | BU21 聚合头部消耗速率 | #1287 `4ea6258a` | #1289 `7811674f` |
| R40 | OPS1 审计门自动化前置 | #1297 `b684fcd7` | 定时 workflow 属 main（scheduled 仅默认分支），无 win7 侧 |
| R42 | RD21 run 触顶原因横幅 | #1306 `58d7b19e` | #1312 `ce086aff` |
| R43 | RD20 历史 run 恢复增强（RT24 字段 + endedAt） | #1376 `ed3d546d` | #1379 `a7124d15` |
| R44 | OPS1 扩展：audit-watch 覆盖 main 生产路径 | #1389 `4da49ab8` | 定时 workflow 属 main，无 win7 侧 |
| R45 | OPS2 CI 事件去重流程化（ci-rerun + SOP §4.2） | #1395 `5f329e7a` | #1399 `2f83510b` |
| R46 | RT25 usage_events 任务归因复合索引 | #1409 `6a177ae3` | #1413 `0738247d` |
| R47 | OPS3 doctor 探针瞬时超时重试 | #1436 `1fa169a3` | #1441 `f7eddc8f` |

§回填记录：R23 `#1084`、R24 `#1096`、R25 `#1108`、R26 `#1141`、R27 `#1157`、
R28-31 `#1193`、R32 `#1203`、R33 `#1250`、R34 `#1261`、R35 `#1272`、
R36 `#1281`、R38 `#1291`、R42 `#1316`、R43 `#1384`、R45 本 PR。


## 2. 过程经验（diff-patch / 双分支交付）

1. **diff-patch 对齐三坑**（R23 实证，见该轮 §5）：PEP 604 语法护栏、
   迁移调用必须位于建表之后、win7-only 代码（如 get_connection 代理身份
   绑定）会被 main 侧 hunk 静默冲掉。**结论：能干净 cherry-pick 就不用
   diff-patch**；diff-patch 后必须 diff 回 release/win7 基线复核。
2. **命名空间**：多会话并行的分支/回填命名会发生碰撞（R36 的
   `docs/r36-backfill` 撞名），回填类分支用 `docs/rXX-parity-backfill`
   等带域前缀命名。
3. **事件投递限流**：高频 push 可能触发 GitHub 对 PR 事件的静默丢弃
   （R28 win7 PR 约 2 小时未触发 CI）。缓解：合并多轮内容为单个 PR 减
   事件量；workflow_dispatch 可作分支级验证（注意 job 的 if 语义）；
   push 恢复后补真 pull_request CI。
4. **shell cwd 失效**：worktree 删除会让常驻 shell 的 cwd 失效，spawn
   ENOENT 易误诊为 bash.exe 损坏（R18/R36 各一次）。先用 Write 工具重建
   失效目录即可恢复，无需重装 Git。

## 3. 后续优化建议（候选项，非承诺）

1. **聚合头部速率感知**：BU8/BU18 行可加"近 5 分钟消耗速率"趋势，帮助
   conductor 提前一轮判断触顶（数据源 usage_events 窗口聚合）。
2. **orch_tasks 历史视图**：RT24 已持久化 used_tokens/duration_ms，若
   历史编排 UI 回归（Wave 4 曾移除），可直接消费 `GET /orch/runs` 详情。
3. **win7 审计门自动化**：新 advisory 出现时自动开 issue + 策略草稿
   （本次 anyio 两条为人工响应），减少 win7 PR 阻塞窗口。
4. **CI 事件去重**：批量轮次合并交付时，考虑 wait-for-CI 串行化，避免
   并发 run 相互取消（concurrency 组按 ref）。

—— 本账本由对标循环维护，随轮次追加。

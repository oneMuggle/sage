# 编码代理对标差距分析·第十三轮：重派与收集的韧性补全（2026-09-12）

- **状态**：批次 A 已交付（分支 `feat-parity-r13-batch-a`，基线 origin/main d500ce73 = #651）
- **上游文档**：round12（BD 系后台派发/收集已交付 #648/#650）、round10（retry_of 重派已交付）——本轮补全两者交界处的两个边角
- **对标对象**：Claude Code（TaskOutput 非阻塞快照）、Devin（重派不连带判死下游）
- **编号约定**：延续 RD/BD 系
- **方法**：拓扑分层（build_waves）与级联闭包的边界行为核验，附 file:line

## 0. 结论速览

round10 的 `retry_of` 与 round12 的 `collect` 交付后，交界处仍有两个边角：

1. **RD13 重派任务可能被同批级联判死**：conductor 同批派发 `[t1, t2(retry_of=t1)]` 且计划中 t2.depends_on=t1 时——t1 在第一波失败 → 波间闭包把依赖它的 t2 直接标 `blocked_by_failed:` failed，重派根本不执行。跨批重派无此问题（build_waves 忽略批外依赖，`topology.py:63-67`），但同批场景真实存在。
2. **BD3 collect 只会"傻等"**：`collect_subagents` 只有等待语义——conductor 想"先看看现在各任务到哪了"必须阻塞到全部完成。Claude Code 的 TaskOutput 有非阻塞形态。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| RD13 | 同批重派被级联闭包连带判死 | 波间闭包（newly_failed → downstream_closure）；deps 含已 failed 的 retry 源 | Devin 重派独立执行 | **P1** |
| BD3 | collect 缺非阻塞快照形态 | CollectSubagentsTool（仅等待语义） | Claude Code TaskOutput 非阻塞 | P2 |
| — | 已具备：build_waves 忽略批外依赖（`topology.py:63-67`，跨批重派天然安全）、retry_of 解析守卫、shield 等待 | — | — | 不再建设 |

## 2. 设计（批次 A：RD13+BD3）

- **RD13**：`deps_by_id` 构建完成后，对 `state.retry_of` 非空的任务剥离指向重派源的依赖（仅此一个 dep；其余依赖保留波次语义）——重派任务作为独立根执行，不被源的失败连带。
- **BD3**：dispatcher 增 `background_snapshot()`（`{status: none|running|completed, tasks: [{task_id, status, output_preview, error}]}`）；`collect_subagents` 增 `wait` 参数（默认 true；false = 立即返回快照）。
- py3.8 纪律照旧；前端零改动。

## 3. 批次 A 实施与验证记录

（实施后回填）

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

（各批次 PR 号与双分支交付号于交付后回填）

# 编码代理对标差距分析·第十一轮：编排 run 级 token 预算守门（2026-09-12）

- **状态**：批次 A 已交付（分支 `feat/parity-r11-batch-a`，基线 origin/main c02255df = #638）
- **上游补记**：第十轮 docs 回填 #639 merge 时 Backend job 尚在跑（门禁偏差）——main `2dd5ea21` 合并后 CI 已补验**全绿**（All Checks success；Backend job 103353305849 success，py38 按预期 skip），第十轮据此正式收官
- **上游文档**：round10（失败任务机制级重派已交付）——本轮从"失败恢复"转到**成本治理**维度；与会话/skills/gateway（hermes 系列）、office、update-providers、memory/embedding 各并行工作流无交叠
- **对标对象**：Devin（ACU 预算硬上限）、Claude Code（/cost 可见性 + 环境级花费护栏）
- **编号约定**：本轮用 **BU 系**（BUDget）
- **方法**：usage 记账链（usage_events 表 / usage_tracker / O3 子代理会话归因）逐点核验，附 file:line

## 0. 结论速览

O3（round6）打通了子代理用量归因（usage_events.session_id 含编排子代理），C1（round8 C1）让 run 可回溯——但**没有任何消费方把"这个 run 花了多少"变成"超了就停"**：

1. **BU1 无预算配置**：`OrchSettings`（`orch_settings.py:29-53`）有并发/重试/超时/聚合字符等各类上限，唯独没有花费/token 预算——失控的编排 run（LLM 死循环式互相触发）没有花钱刹车。
2. **BU2 无运行时守门**：dispatcher 对任务终态后的累计消耗零感知（`chat_dispatcher.py` 无 usage 引用），唯一护栏是任务级 wall-clock 超时（O2）——超时管"单任务卡死"，管不住"每个任务都正常但跑飞了"。
3. **BU3 无可见性**：聚合文本/事件不携带消耗信息，conductor 与用户都看不到"已花多少"。

记账侧已就绪：usage_events 落库含 session_id/total_tokens/created_at（`database.py:776-791`，session+created_at 索引在），子代理经 O3 归因到 run 的 session——**只差预算键与守门执行**。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| BU1 | 无 run 级预算配置 | `orch_settings.py:29-53`（无预算键） | Devin ACU 上限 | **P1** |
| BU2 | 无运行时守门（超预算不停） | `chat_dispatcher.py` 全文无 usage 引用 | Devin 预算触顶收口 | **P1** |
| BU3 | 消耗不可见于聚合 | `_aggregate` 头部无用量行 | Claude Code /cost | P2 |
| — | 已具备：usage_events 持久化 + session 索引、O3 子代理归因、session_summary 聚合范式（`usage_tracker.py:384-455`）、任务级墙钟超时 O2 | — | — | 不再建设 |

## 2. 设计（批次 A：BU1-BU3）

- **BU1**：`OrchSettings.run_token_budget: int = 0`（0 = 关闭，默认关闭保持现状）+ `_RAW_KEYS["runTokenBudget"]`（int 守卫复用既有分支）。
- **BU2**：`usage_tracker.session_usage_since(session_id, since_ms)`（SUM(total_tokens) WHERE session_id AND created_at >= since_ms，SQL 故障 fail-open 返 0 + warning——守门是护栏不是正确性依赖）。`ChatDispatcher`：`_run_one` 每任务终态后（emit 之后）守门——`settings.run_token_budget > 0` 且 `session_usage_since(session_id, _first_dispatch_at) > budget` → 置 `_budget_exceeded` + `self._cancelled.set()`（queued 任务经既有 merged 通道收口 cancelled、running 任务软中断）+ 一次 WARNING 日志。`dispatch()` 入口：`_budget_exceeded` 已置位 → `ValueError("budget_exceeded: …")`（conductor 下一批派发立即收到明确工具错误）。
- **BU3**：`_aggregate` 头部在超预算时追加 `⚠ 已触发 token 预算上限（>N tokens），剩余任务已停止。`（随工具结果进 conductor 上下文与前端卡片）。
- 窗口口径：run 首次派发时间戳 `_first_dispatch_at`（ms）起的该 session 全部用量——串行 run（单会话同时一个 run）下等价于 run 用量；并发双 run 属既知近似（记录于文档）。
- py3.8 纪律照旧；前端零改动。

## 3. 批次 A 实施与验证记录（2026-09-12）

- **BU1**：`OrchSettings.run_token_budget: int = 0` + `_RAW_KEYS["runTokenBudget"]`（int 守卫复用既有分支，0 = 关闭）。
- **BU2**：`usage_tracker.session_usage_since(session_id, since_ms)`（`_SQLITE_LOCK` 内 SUM(total_tokens)，窗口过滤，fail-open 返 0）；`ChatDispatcher._check_run_budget()`——每任务终态（`_run_one` finally emit 后）调用：预算 >0 且 `_first_dispatch_at`（秒制 → ×1000 转毫秒窗口起点）以来累计超限 → 置 `_budget_exceeded` + `_cancelled.set()`（queued 经既有 merged 守卫收口、running 软中断）+ WARNING；`dispatch()` 入口 `_budget_exceeded` 已置位 → `ValueError("budget_exceeded: …")`（conductor 下一批收到明确工具错误并被告知直接汇总）。
- **BU3**：`_aggregate` 头部追加 `⚠ 已触发 run 级 token 预算上限（>N tokens）…`（随工具结果进 conductor 上下文与前端卡片）。
- 测试：`test_chat_dispatcher_budget.py` 5 例（窗口过滤/跨会话隔离 + fail-open + 超限收口与聚合标注 + 拒绝后续批次 + 关闭零影响 + 未超限 noop）；usage 相关 72 passed；dispatcher 回归全绿（唯一失败 `test_reports_explicit_runtime_and_package_root` 为本地 Windows 基线既有）；ruff 全过；收集 6744 零错误。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

| 批次 | main | win7 |
| --- | --- | --- |
| A（run 级 token 预算守门） | PR #642（squash cf3b4fbb） | PR #643（cherry-win7-r11，squash 2a0d5390） |

win7 对齐说明：usage_tracker 冲突按"保留 win7 侧"解决——win7 尚未同步 main 的 `_upsert_daily_rollup`（属未 cherry-pick 的其他主线特性），仅加入本批的 `session_usage_since`，避免静默带入半套未同步代码。本地 ruff 全过 + budget 5 例/usage 48 例绿后由 CI（含 py3.8 job）终验，squash merge（#643）。

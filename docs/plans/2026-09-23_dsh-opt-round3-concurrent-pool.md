# DSH 对标优化·第三轮：声明式并行工具调度（B2）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r3-concurrent-pool`，基线 origin/main e45dc7be）
- **系列定位**：`dsh-opt` 对标系列第 3 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round1（SE1，main #1421 / win7 #1425）、
  round2（SE2，main #1435 / win7 #1445）
- **对标对象**：DeepSeek Harness 工具调度器——并发安全性由工具**自声明**
  （`isConcurrencySafe`），并发安全的调用进有界滚动池，非安全的形成
  exclusive 屏障，事件/结果严格按模型顺序提交，对 LLM 与 UI 透明。

## 0. 结论速览

sage 现状是"批级全有全无"：`_is_parallel_eligible`（agent.py:651）要求
整批全部 READ + 无钩子 + 全部预审放行，任一不满足整批回退串行。
典型损失：`[read_file, edit_file, read_file]` 三连中两个 READ 被一个
WRITE 拖成全串行。本轮改为**声明式分组调度**：

1. `BaseTool.concurrency_safe: Optional[bool]`——`True` 显式声明可并发；
   缺省回落 `risk == READ`（与现行判定同口径，零注册成本）；
2. 批次按模型顺序**切成连续分组**：连续的 safe 调用合并为并发池
   （有界，≤8 并发），unsafe/需审批/特殊工具成为串行屏障——相邻调用
   因果顺序严格保持（write → read 不会被重排）；
3. 事件与消息仍按模型顺序产出，对 LLM 与前端完全透明（沿用 L6 契约）；
4. 有 pre_tool_use 钩子时整批仍回退串行（钩子 deny/modify 是顺序语义，
   与现状一致）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| B2 | 并行调度全有全无，WRITE 夹 READ 即全串行 | agent.py:651 `_is_parallel_eligible` 全批判定 | dsh：per-tool 声明 + 滚动池 + 屏障 | **P2** |

## 2. 设计（批次 A：B2）

- **声明**：`BaseTool.concurrency_safe: Optional[bool] = None`；解析规则
  `_resolve_concurrency_safe(tool) = tool.concurrency_safe if not None else
  (tool.risk == RiskClass.READ)`。显式 `False` 可压制误标 READ 的工具。
- **分组**：`_plan_execution_groups(tool_calls, enforcer, hooks, used) ->
  List[Tuple[str, list]]`，元素为 `("pool", [tc...])` / `("serial", [tc])`：
  - 钩子非空 → 整批单个 serial 组序列（等价现状回退）；
  - pool-eligible 判定（逐条）：工具存在、safe 解析为 True、非阻塞、
    非特殊工具（ask_user/agent/dispatch_subagents）、args 可解析为 dict、
    profile 白名单内、enforcer 预检免审放行、组预算足够；
  - 连续 eligible 合并进当前 pool 组（池上限 8，超出开新组），否则 flush
    当前组并落一个 serial 组。
- **执行**：pool 组复用既有 `_run_one` / 中心超时 / `asyncio.gather`
  机制（新增 `asyncio.Semaphore(8)` 有界化）；预算按组整批预扣，不足时
  该组降级为逐个 serial（让 per-call 预算守卫语义保持）；repeat 守卫/
  M6 钩子/审批流仅在 serial 组生效（与现行"并行只读批次不拦截"口径
  一致，且 pool 组全部零副作用）。

## 3. 批次 A 实施与验证记录

- **声明**：`BaseTool.concurrency_safe: Optional[bool] = None`
  （backend/tools/base.py），`True` 显式入池 / `False` 显式压制 /
  `None` 回落 `risk == READ` —— 存量 96 个工具零注册成本，语义与 L6
  同口径。
- **判定抽取**：`_is_pool_eligible_call(tc, enforcer)`（特殊工具 / 存在性
  / safe 解析 / 非阻塞 / args dict / 免审放行）；`_is_parallel_eligible`
  改为复用该谓词（对外语义不变，既有测试零改动通过）。
- **规划器**：`_plan_execution_groups`——批级预检（中断/钩子/白名单）
  不过即全串行；否则按模型顺序扫批：连续 eligible 合并池组（上限
  `_PARALLEL_POOL_SIZE = 8`，满员开新池而非降级），不 eligible 即串行
  屏障；预算入池逐条预扣，耗尽后落 serial（保持 per-call
  tool_budget_exceeded 事件语义）。
- **run_loop 集成**：`if _is_parallel_eligible(...)` 大块改为组循环——
  pool 组走既有 gather/中心超时/按原序提交机制；serial 组即原串行管线
  （预算/复读守卫/参数校验/M6 钩子/审批流全部仅在串行路径生效，与
  L6"并行只读批次不拦截"口径一致）。
- **测试**：+12 例（`test_agent_execution_groups.py`：全池 / write 屏障
  切分 / 显式压制与升级 / 钩子全串行 / 审批屏障 / 预算降级 / 池上限
  开新池 / 单调用 / 白名单全串行 / L6 语义一致性 / run_loop 混合批次
  顺序保持）。测试替身必须显式 `concurrency_safe=None`——MagicMock
  未声明属性自动生成 truthy 子 mock，会绕过回落判定（已在模块
  docstring 记录该坑）。
- **验证**：新测 12 例 + 既有回归 44 例全绿（loop_guards /
  parallel_interrupt / risk）；ruff 全过；py38 护栏（compat_rewrite
  --check 0 变更 + AST 3.8）通过；棘轮 baseline 同步（agent.py 2323）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
- **历史轮次回填（随本轮合入）**：
  - R1 win7：PR #1425（squash `8194fc78`，2026-09-23 merge，py38 全量
    套件 20m32s 绿；win7 适配 4 项见该 PR 描述）。
  - R2 main：PR #1435（squash `e45dc7be`，2026-09-23 merge；首轮
    legacy smoke 抓出 retreat 用例毫秒撞钟 flake，已加固）。
  - R2 win7：PR #1445（squash SHA 待 merge 后回填于总账）。

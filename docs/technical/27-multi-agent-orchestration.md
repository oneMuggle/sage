# 27. 多 Agent 编排层（M1：typed 化）

> 本章节描述 Sage 多 Agent 协调层的 typed 化设计。
> 增量于 [`22-agents-crud.md`](./22-agents-crud.md)、[`24-skills-system.md`](./24-skills-system.md) 等运行时模块；
> 整体方案见 [`../plans/2026-06-26_multi-agent-optimization-from-claw-code.md`](../plans/2026-06-26_multi-agent-optimization-from-claw-code.md)（如仍存在则参考）。
> M1 落地于 `feat/multi-agent-v2` 分支，2026-06-27。

## 1. 背景

Sage 已有 `backend/orchestration/` 共 11 个模块约 2376 行 Python
（planner / router / executor / lane_registry / task_registry / team_registry /
heartbeat / permission / events / models / __init__）。

但决策、报告、审批逻辑仍散落在 router / executor 内部，**无结构化审计**。
本章节（M1）落地 3 个核心 typed 模块，把"决策 / 报告 / 审批"三件事从字符串描述
升级为 typed 事件，可被事件流落盘 + 可重放。

## 2. 设计参考

| 参考 | 来源 | 用途 |
|---|---|---|
| `rust/crates/runtime/src/policy_engine.rs` | claw-code | `PolicyDecisionEvent` typed event + priority 排序 |
| `rust/crates/runtime/src/report_schema.rs` | claw-code | Report schema v1 + canonical content hash + projection lineage |
| `rust/crates/runtime/src/approval_tokens.rs` | claw-code | Approval token + actor/scope/expiry/one-time 校验 |
| `docs/g004-events-reports-contract.md` | claw-code | 事件契约（typed event vs prose） |

## 3. 模块清单

### 3.1 `backend/orchestration/policy_engine.py`

```text
PolicyDecisionKind  :: enum(RETRY, REBASE, MERGE, ESCALATE, STALE_CLEANUP, APPROVAL)
PolicyContext       :: dataclass(lane_id, task_id, attempt, failure_class,
                                  heartbeat_status, lane_status, action, branch,
                                  repo, commit, crossed_branches, force_push,
                                  upstream_reconciled, workspace_mismatch)
PolicyDecision      :: dataclass(rule_name, priority, kind, explanation)
PolicyDecisionEvent :: dataclass(同上 + lane_id, decided_at, approval_token_id)
PolicyEngine        :: class — evaluate / evaluate_with_events
```

**12 条决策规则**（实现 + 单测覆盖）：

| # | rule_name | 触发条件 | kind | priority |
|---|---|---|---|---|
| 1 | `retry_on_test_failure` | failure_class=Test ∧ attempt≤3 | retry | 20 |
| 2 | `retry_on_compile_failure` | failure_class=Compile ∧ attempt≤3 | retry | 21 |
| 3 | `rebase_on_branch_divergence` | failure_class=BranchDivergence | rebase | 15 |
| 4 | `escalate_on_trust_gate` | failure_class=TrustGate | escalate | 5 |
| 5 | `escalate_on_repeated_failure` | attempt≥3 | escalate | 10 |
| 6 | `stale_cleanup_on_heartbeat_dead` | heartbeat_status=dead | stale_cleanup | 8 |
| 7 | `stale_cleanup_on_transport_dead` | heartbeat_status=transport_dead | stale_cleanup | 7 |
| 8 | `merge_on_lane_green_and_reconciled` | lane_status=green ∧ upstream_reconciled | merge | 30 |
| 9 | `approval_for_force_push` | force_push=true | approval | 1 |
| 10 | `approval_for_cross_branch_merge` | crossed_branches=true | approval | 1 |
| 11 | `escalate_on_prompt_delivery` | failure_class=PromptDelivery | escalate | 3 |
| 12 | `stale_cleanup_on_workspace_mismatch` | workspace_mismatch=true | stale_cleanup | 2 |

**关键不变量**：

- `evaluate_with_events` 返回 `(decisions, events)`，priority 升序
- approval 决策必须携带 `approval_token_id`（`apt_<hex>` 占位，真实 token 由 `ApprovalTokenStore` 发放）
- 非 approval 决策的 `approval_token_id` 必须为 `None`

### 3.2 `backend/orchestration/report_schema.py`

```text
AssertionType       :: enum(FACT, HYPOTHESIS, NEGATIVE_EVIDENCE)
Assertion           :: dataclass(type, statement, confidence, source_ref)
ProjectionRef       :: dataclass(view, source_hash, downgrade_reason)
ReviewReport        :: dataclass(canonical_id, lane_id, reviewer_id,
                                  assertions, projection_lineage,
                                  redaction_provenance, schema_version,
                                  content_hash, created_at)
```

**关键不变量**：

- `schema_version` 锁定 `"1.0"`，构造时校验
- `content_hash` = SHA256 over canonical payload（不含 `content_hash` 自身、`created_at`、`projection_lineage`）
- `projection_lineage` 是"指针"而非内容：仅校验 `source_hash == content_hash`，不参与 hash
- `redaction_provenance` 显式记录缺失字段的原因（`compatibility` / `redaction` / `source_absence`）
- `Assertion.confidence` ∈ [0.0, 1.0]；`statement` 非空
- 负向证据是一等公民（`AssertionType.NEGATIVE_EVIDENCE`）

**使用协议**：

```python
# 1. 构造（lineage 临时为空）
report = ReviewReport(canonical_id, lane_id, reviewer_id, assertions, [])

# 2. 追加 projection，pin source_hash
report.projection_lineage.append(
    ProjectionRef(view="ops_full", source_hash=report.content_hash)
)

# 3. 显式校验
report.validate()  # raises ValueError if lineage 不一致
```

### 3.3 `backend/orchestration/approval_tokens.py`

```text
DenyReason          :: enum(NOT_FOUND, REVOKED, EXPIRED, EXHAUSTED,
                             ACTOR_MISMATCH, ACTION_MISMATCH,
                             REPO_MISMATCH, BRANCH_MISMATCH,
                             COMMIT_MISMATCH)
ApprovalToken       :: dataclass(token_id, approver, policy_exception,
                                  action, scope_repo, scope_branch,
                                  scope_commit, issued_at, expires_at,
                                  max_uses, consumed_count, revoked)
TokenUseResult      :: dataclass(granted, token_id, reason, message)
ApprovalTokenStore  :: class — issue / get / revoke / list_active / consume
```

**8 项 consume 校验门**（顺序敏感）：

1. token 存在
2. 未 revoke
3. 未过期（`now < expires_at`）
4. `consumed_count < max_uses`（在 `_lock` 内自增，保证原子性）
5. actor 严格 == approver
6. action 严格 == token.action
7. repo 严格 == scope_repo
8. branch 严格 == scope_branch
9. commit 严格 == scope_commit（仅当 `scope_commit` 非 None 时）

**线程安全**：`threading.Lock` 保护 issue / revoke / max_uses 自增路径，
确保并发场景下 max_uses 不被超额消耗。

**`scope_commit` 语义**：

- `scope_commit=None`：不绑定具体 commit（适用于"启动任意 commit"场景）
- `scope_commit="abc123"`：调用方必须提供完全一致的 commit

## 4. 事件流契约

M1 的 3 个模块都遵守 claw-code 的"事件契约"原则：

| 概念 | 实现 |
|---|---|
| typed event name | `PolicyDecisionKind`、`DenyReason`、`AssertionType` 均为 enum |
| structured payload | dataclass + `to_dict()` JSON 序列化 |
| provenance | `PolicyDecisionEvent.lane_id` + `decided_at` |
| ordering / dedup | `priority` 升序 + `decided_at` 毫秒时间戳 |
| canonical identity | `ApprovalToken.token_id`、`ReviewReport.content_hash` |

## 5. 测试覆盖

| 测试文件 | 测试数 | 覆盖 |
|---|---|---|
| `test_policy_engine.py` | 26 | 12 条规则 + 优先级排序 + approval token id 携带 |
| `test_report_schema.py` | 21 | hash 稳定性 / projection lineage / redaction / JSON round-trip |
| `test_approval_tokens.py` | 23 | 8 项 consume 校验 + 并发 max_uses |
| **合计** | **70** | 全部通过；M1 未触动既有 orchestration 测试 |

## 6. 与下游模块的集成路径（M2+ 规划）

| 集成点 | 计划阶段 | 说明 |
|---|---|---|
| `router.py` 注入 PolicyEngine | M2 | `router.dispatch()` 前先 `engine.evaluate_with_events` |
| `executor.py` 写入 ReviewReport | M2 | lane.green 前由 reviewer lane 产出 v1 report |
| `lane_registry.py` 接受 ApprovalToken | M2 | 越权动作（force_push / cross_branch_merge）必须先消费 token |
| `events.py` 增加 `branch.*` / `ship.*` 事件 | M2 | 双分支协调 + ship gate |
| `.omx/ultragoal/` 目录 | M3 | leader-owned goal，worker 只读 |
| `board.json` 增加 `lane_freshness` | M4 | UI 可判断 board 是否过期 |

## 7. 设计取舍

| 决策 | 选择 | 备选 | 理由 |
|---|---|---|---|
| Policy engine 状态 | 无状态 | 缓存上次决策 | 决策应可重放；状态会污染语义 |
| Approval store 后端 | 内存 dict | SQLite / Redis | M1 阶段不需要持久化；线程锁够用 |
| Report hash 算法 | SHA256 | BLAKE2 | 行业标准，工具链支持广 |
| Projection lineage 参与 hash | 否 | 是 | 避免自引用（hash 改变 → source_hash 失效） |
| 失败分类粒度 | 12 类 | 8 类 | 与 claw-code 对齐，方便 cross-check |

## 8. 参考

- 设计方案：`docs/plans/2026-06-26_multi-agent-optimization-from-claw-code.md`
- claw-code 参考：`/home/fz/project/claw-code/rust/crates/runtime/src/`
- claw-code 事件契约：`docs/g004-events-reports-contract.md`

## 9. 集成落地（M2）

M2 把 M1 的能力**接入**现有 router / executor 运行时，并补齐 claw-code 同款事件。

### 9.1 事件扩展（`backend/orchestration/events.py`）

| 新事件 | 用途 |
|---|---|
| `lane.reconciled` | 跨 lane 资源冲突已对账 |
| `lane.superseded` | 新 lane 替代旧 lane |
| `lane.review.submitted` | Reviewer 提交 ReviewReport v1 |
| `branch.stale_against_main` | feature 分支落后 main |
| `branch.workspace_mismatch` | worktree 路径与 scope_path 不符 |
| `ship.prepared` | Director 进入 ship gate |
| `ship.commits_selected` | 已选定要 ship 的 commits |
| `ship.merged` | 合并完成 |
| `ship.pushed_main` | 推送 main 成功 |

分组常量：`BRANCH_EVENTS`、`SHIP_EVENTS`（`frozenset[LaneEvent]`）。

### 9.2 Router 集成（`backend/orchestration/router.py`）

`Router.__init__` 新增 2 个可选参数（向后兼容）：

```python
Router(
    lane_registry, agent_registry,
    strategy=DispatchStrategy.CAPABILITY_BASED,
    policy_engine=None,    # M2
    token_store=None,      # M2
)
```

新增方法：

| 方法 | 行为 |
|---|---|
| `dispatch_with_policy(task, ctx)` | 先 policy 评估，再 `route_task`；返回 `(decision, events)` |
| `try_dispatch_privileged(task, token_id, actor, ctx)` | policy 评估 + approval 校验 + token 消费；返回 `(decision, events, deny_reason)` |

**关键不变量**：
- `route_task` 行为完全不变（既有 7 个 router 测试 0 回归）
- `policy_engine=None` → `dispatch_with_policy` 等价于 `route_task`
- `token_store=None` + approval 决策 → 拒绝并返回 `token_store_unavailable`

### 9.3 Executor 集成（`backend/orchestration/executor.py`）

新增方法：

```python
def submit_with_report(
    self,
    lane_id: str,
    task_id: str,
    assertions: list[Assertion],
    reviewer_id: str = "system",
) -> ReviewReport:
    """构造 ReviewReport v1，emit lane.review.submitted 事件。"""
```

事件 metadata 包含 `canonical_id` / `content_hash` / `reviewer_id` / `assertion_count`，
下游消费者可重哈希验证而不必重读全文。

### 9.4 M2 测试覆盖

| 测试文件 | 测试数 | 覆盖 |
|---|---|---|
| `test_events_extended.py` | 17 | 9 个新事件 + 2 个分组常量 + payload 序列化 + 向后兼容 |
| `test_router_policy_integration.py` | 13 | dispatch_with_policy + try_dispatch_privileged（含越权拒绝） |
| `test_executor_review_report.py` | 11 | ReviewReport 构造 + 事件 emit + 向后兼容 |
| **M2 合计** | **41** | 全部通过 |

### 9.5 M2 累计测试（与 M1 合计）

| 模块 | 测试数 |
|---|---|
| M1 三个核心模块 | 70 |
| M2 集成落地 | 41 |
| 既有 orchestration 测试（无回归）| 102 |
| **累计** | **213** |

## 10. 后续里程碑

| 阶段 | 内容 | 预计周期 |
|---|---|---|
| M3 | `.omx/ultragoal/` leader-owned goal + worker 写入拦截 | 0.5 周 |
| M4 | board.json `lane_freshness` + 前端 projection 选择 | 1 周 |
| M5 | 端到端 5-lane 工作流测试（plan → 5 lane → 1 red → retry → green → ship） | 1 周 |

## 11. Ultragoal + Leader-Only Guard（M3）

参考 claw-code `.omx/ultragoal/` 模式，落地**目标层级 + 写权限分离**。

### 11.1 数据模型

```text
Ultragoal       :: dataclass(goal_id, title, objective, acceptance_criteria,
                             parent_goal_id, status, sub_goal_ids, metadata)
LedgerEntry     :: dataclass(entry_id, timestamp, actor, action, goal_id,
                             before, after, evidence_refs)
Checkpoint      :: dataclass(checkpoint_id, goal_id, created_at, actor,
                             evidence, summary, terminal)
```

### 11.2 不变量

- `Ultragoal.acceptance_criteria` ≥ 1 条非空字符串
- `status ∈ {"active", "complete", "superseded"}`
- `action ∈ {"create", "update", "checkpoint", "supersede", "complete"}`
- `goal_id` 全局唯一（重复创建抛 `DuplicateGoalId`）
- 更新不存在的 goal_id 抛 `GoalNotFound`

### 11.3 UltragoalGuard — leader-only 写入

```text
UltragoalGuard.assert_can_write(actor, method) :: raise WorkerWriteDenied
UltragoalGuard.create_goal(actor, ...)         :: 委托 store，但先 assert
UltragoalGuard.update_goal(goal_id, actor, ...)
UltragoalGuard.checkpoint(goal_id, actor, ...)
UltragoalGuard.complete(goal_id, actor, evidence=...)
```

**关键不变量**：

- 所有 mutator 必须 `actor == leader_actor`，否则 `WorkerWriteDenied`
- 每次拒绝都写入 `worker-write-rejected.log`
- workers 可直接读 `UltragoalStore.get_goal(...)`，**只写被 guard 拦截**

### 11.4 文件布局（当 `persist_dir` 设置时）

```
.omx/ultragoal/
├── goals.json                       # 完整快照
├── ledger.jsonl                     # append-only 审计
├── check-<goal_id>-<seq>.json       # 每个 checkpoint 独立文件
└── worker-write-rejected.log        # 每次拒绝一行
```

加载时（`UltragoalStore(persist_dir=...)` 自动 reload）：
1. `goals.json` → 重建 in-memory 字典
2. `ledger.jsonl` → 重建 ledger 列表
3. `worker-write-rejected.log` → 重建拒绝列表
4. `check-*.json` 文件名 → 重建 `_checkpoint_seq`

### 11.5 M3 测试覆盖

| 测试类 | 用例数 | 覆盖 |
|---|---|---|
| `TestUltragoalDataclass` | 5 | dataclass shape + validation |
| `TestLedgerEntryDataclass` | 2 | dataclass shape + action validation |
| `TestCheckpointDataclass` | 1 | dataclass shape |
| `TestStoreCRUD` | 6 | CRUD + DuplicateGoalId + GoalNotFound |
| `TestLedgerAppendOnly` | 4 | 每次写入落 ledger |
| `TestGuard` | 7 | leader 通过 / worker 拒绝 + 拒绝日志 |
| `TestFilePersistence` | 4 | reload / jsonl / checkpoint 文件 / rejection log |
| **M3 合计** | **29** | 全部通过 |

### 11.6 M3 累计测试（M1 + M2 + M3）

| 模块 | 测试数 |
|---|---|
| M1 typed policy/report/token | 70 |
| M2 events + router/executor 集成 | 41 |
| M3 ultragoal + guard | 29 |
| 既有 orchestration（无回归）| 102 |
| **累计** | **242** |

## 12. 后续里程碑

| 阶段 | 内容 | 预计周期 |
|---|---|---|
| M4 | board.json `lane_freshness` + 前端 projection 选择 | 1 周 |
| M5 | 端到端 5-lane 工作流测试（plan → 5 lane → 1 red → retry → green → ship） | 1 周 |

## 13. Board Freshness + Capability Negotiation（M4）

参考 claw-code `LaneBoard` + `g004-events-reports-contract.md` 的 capability
negotiation 模式，落地 **per-lane freshness** 和 **typed projection 协议**。

### 13.1 数据模型

```text
LaneFreshness      :: dataclass(lane_id, last_heartbeat_at, age_ms, level, reasons)
                      level ∈ {"fresh", "stale", "dead"}
FreshnessSummary   :: dataclass(total, fresh, stale, dead, overall_level)
                      overall_level = worst-of-three
BoardEntry         :: dataclass(lane_id, task_id, agent_id, status,
                                 freshness, last_event_at, last_event_type,
                                 heartbeat_status)
LaneBoardSnapshot  :: dataclass(schema_version, generated_at, generated_by,
                                 active, blocked, finished, freshness_summary)

CapabilityManifest :: dataclass(emitter, schema_versions, field_families,
                                 projection_views, redaction_policy,
                                 fixture_suite_version)
ProjectionRequest  :: dataclass(consumer, requested_view, accepted_field_families,
                                 max_schema_version)
BoardProjection    :: dataclass(parent_content_hash, parent_schema_version, view,
                                 entries, downgrade_for_compatibility,
                                 redaction_provenance)
```

### 13.2 Freshness 阈值

| `age_ms` | `level` | reason |
|---|---|---|
| `None` (无 heartbeat) | dead | `no_heartbeat_observed` |
| `≥ 300_000` (≥ 5min) | dead | `age_exceeds_stale_threshold` |
| `≥ 30_000` (≥ 30s) | stale | `age_exceeds_fresh_threshold` |
| `< 30_000` | fresh | （无） |

与 `heartbeat.py` 默认 `stalled_after=300s` / `dead_after=600s` 对齐。

### 13.3 Capability Negotiation 协议

```
producer.LaneBoardBuilder
   |
   | emit CapabilityManifest (默认 schema_version="board@1.0",
   |                          views=["ui_minimal", "ops_full"],
   |                          field_families=[lifecycle, branch_health, ship])
   v
consumer (frontend.react / electron.main / mcp.daemon)
   |
   | send ProjectionRequest(consumer, requested_view, accepted_field_families,
   |                        max_schema_version)
   v
producer.LaneBoardSnapshot.project(request) -> BoardProjection
```

**关键不变量**：

- `requested_view` 必须出现在 `manifest.projection_views`，否则 `UnsupportedViewError`
- `max_schema_version` < producer schema_version 时，投影记录
  `downgrade_for_compatibility=[...]`
- 每个被 omitempty 的字段必须出现在 `redaction_provenance`
- **`lane_id` 永远保留**（跨引用 invariant，不允许 redaction）
- 视图 → 字段族映射：
  - `ui_minimal` = `lifecycle`
  - `ops_full` = `lifecycle + branch_health + ship`
  - 其它视图 = `accepted_field_families`（默认 `lifecycle`）

### 13.4 M4 测试覆盖

| 测试类 | 用例数 | 覆盖 |
|---|---|---|
| `TestLaneFreshness` | 5 | fresh/stale/dead 阈值 + 边界 + 无 heartbeat |
| `TestFreshnessSummary` | 3 | 计数 + worst-of-three overall_level |
| `TestLaneBoardBuilder` | 4 | 分组 + entry 含 freshness + to_dict |
| `TestCapabilityManifest` | 1 | default_for_board_v1 |
| `TestProjection` | 6 | view 校验 / lane_id 保留 / downgrade / redaction |
| **M4 合计** | **19** | 全部通过 |

### 13.5 M4 累计测试（M1 + M2 + M3 + M4）

| 模块 | 测试数 |
|---|---|
| M1 typed policy / report / token | 70 |
| M2 events + router/executor 集成 | 41 |
| M3 ultragoal + guard | 29 |
| M4 board freshness + capability | 19 |
| 既有 orchestration（无回归）| 102 |
| **累计** | **261** |

## 14. 后续里程碑

| 阶段 | 内容 | 预计周期 |
|---|---|---|
| M5 | 端到端 5-lane 工作流测试（plan → 5 lane → 1 red → retry → green → ship） | 1 周 |

## 15. 端到端 5-Lane 工作流（M5）

新增 `backend/tests/integration/test_e2e_5lane_workflow.py`，**一次测试**串起 M1-M4 全部模块。

### 15.1 14 个验证断言

| # | 验证点 | 涉及模块 |
|---|---|---|
| 1 | Director 创建 ultragoal `g-5lane` | M3 (UltragoalGuard) |
| 2 | 5 个 lane dispatch 全成功 | M2 (Router) |
| 3 | lane-3 触发 retry policy | M1 (PolicyEngine) |
| 4 | 4 个成功 lane + 1 个 retry 后 lane 都产出 ReviewReport | M1+M2 (Report + Executor) |
| 5 | 5 个 checkpoint + 1 complete 落入 ultragoal | M3 (UltragoalStore) |
| 6 | ledger 含 7 条 entry (1 create + 5 checkpoint + 1 update) | M3 |
| 7 | LaneBoardBuilder 聚合 5 个 finished lanes | M4 |
| 8 | freshness_summary.total=5, dead=5 (无 heartbeat) | M4 |
| 9 | ui_minimal projection 只含 lifecycle 字段 | M4 |
| 10 | ops_full projection 含 freshness + no redaction | M4 |
| 11 | 版本不匹配触发 downgrade_for_compatibility | M4 |
| 12 | worker 写入 ultragoal 100% 拦截 + 落拒绝日志 | M3 |
| 13 | 越权动作 (force_push) bogus token 拒绝 | M1+M2 |
| 14 | ReviewReport 同输入产生同 content_hash（幂等） | M1 |

### 15.2 e2e 测试结构

```python
class TestFiveLaneEndToEndWorkflow:
    @pytest.mark.asyncio
    async def test_full_pipeline_5_lanes_with_retry(self, tmp_path):
        # 1. Setup
        # 2. Director 创建 goal
        # 3. Router + Executor + PolicyEngine + TokenStore
        # 4. Dispatch 5 lanes
        # 5. Execute: 4 success + 1 retry
        # 6. Director complete
        # 7. Ledger 审计
        # 8. LaneBoard snapshot
        # 9-11. 三种 projection
        # 12. Worker denial
        # 13. Token isolation
        # 14. Report 幂等
```

### 15.3 M5 累计测试（M1 + M2 + M3 + M4 + M5）

| 模块 | 测试数 |
|---|---|
| M1 typed policy / report / token | 70 |
| M2 events + router/executor 集成 | 41 |
| M3 ultragoal + guard | 29 |
| M4 board freshness + capability | 19 |
| M5 e2e 5-lane workflow | 1 |
| 既有 orchestration（无回归）| 102 |
| **累计** | **262** |

### 15.4 完整套件结果

```
backend/tests/ → 1372 passed, 57 skipped, 33 xfailed, 71 xpassed, 20 warnings
                  ↑ 0 failure
```

## 16. 总结：M1–M5 闭环

| 阶段 | 范围 | 测试 |
|---|---|---|
| M1 | 3 个 typed 模块（policy / report / token） | 70 |
| M2 | events 扩展 + router/executor 集成 | 41 |
| M3 | ultragoal + leader-only guard | 29 |
| M4 | board freshness + capability negotiation | 19 |
| M5 | 端到端 5-lane 工作流 | 1 |
| **累计** | **5 个 milestone 全部完成** | **160 + 102 = 262** |

**核心成果**：

- ✅ 4 个 claw-code 同款 typed 模块（policy / report / token / ultragoal）+ 1 个 lane_board
- ✅ 9 个新事件（lane.reconciled / lane.superseded / branch.* / ship.* / lane.review.submitted）
- ✅ 14 个 typed dataclass / 3 个 guard / 1 个 capability manifest
- ✅ 端到端验证：5-lane → retry → review → checkpoint → projection

下一步建议：
- commit + push + PR
- 后续可在 main / release/win7 双分支上 cherry-pick 关键 typed 模块
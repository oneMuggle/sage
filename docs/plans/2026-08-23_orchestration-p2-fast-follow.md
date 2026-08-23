# 编排 P2 fast-follow 五项收尾计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox syntax.

**Goal:** 清掉编排 P2 批次终审 triage 遗留的 5 项 fast-follow（全部为小改动，一个 agent 一次交付）。

**Architecture:** 前端两项（类型拆分 + store 测试）、后端两项（聚合提示 + 错误文案）、hygiene 一项（孤儿模块下线）。

**Tech Stack:** 同 P2 主批次。

**Spec:** 出处 = main @ 59266332 技术手册 `docs/technical/42-chat-multi-agent-orchestration.md` §16.6「已知限制与延后项」。

## Global Constraints

- 与主批次完全相同：sage-backend 环境测试、py3.8 兼容、降级铁律、ruff/tsc 全绿、conventional commits。
- 分支 `feat/orchestration-p2-followup`（自 main 59266332 切出），按任务分组少量 commit，单 PR。

---

### Task 1: LaneBoardSnapshot TS 类型拆分（ui_minimal 信封）

**背景**：`BoardProjection.to_dict()`（lane_board.py）返回 `{parent_content_hash, parent_schema_version, view, entries, downgrade_for_compatibility, redaction_provenance}`，与 ops_full 快照是两种不同信封；现 TS 类型把 ui_minimal 响应描述成"快照+附加字段"，调用方会拿到 undefined。

**Files:**
- Modify: `src/shared/api/types.ts`（新增 `BoardProjectionEnvelope` 类型）
- Modify: `src/shared/api/orchestrationClient.ts`（getBoard 重载）
- Modify: `src/shared/api/index.ts`（桶导出）
- Test: `src/shared/api/__tests__/orchestrationClient.test.ts`

**Interfaces:**
- Produces:
```typescript
export interface BoardProjectionEnvelope {
  parent_content_hash: string;
  parent_schema_version: string;
  view: string;
  entries: Array<Record<string, unknown>>;
  downgrade_for_compatibility: string[];
  redaction_provenance: Record<string, string>;
}
```
- getBoard 重载：
```typescript
async getBoard(view?: 'ops_full'): Promise<LaneBoardSnapshot>;
async getBoard(view: 'ui_minimal'): Promise<BoardProjectionEnvelope>;
```
实现体单一方法内部 cast。

**Steps:**
1. types.ts 加 BoardProjectionEnvelope；index.ts 桶导出。
2. orchestrationClient.getBoard 改 TS 重载。
3. vitest 补 ui_minimal 用例断言返回形态透传。
4. `npx tsc --noEmit` + `npx vitest run src/shared/api/__tests__/orchestrationClient.test.ts` 绿。
5. Commit: `fix(frontend): 拆分 board 快照与投影两种信封类型（getBoard 重载）`

---

### Task 2: laneBoardStore 降级分支直接单测

**Files:**
- Create: `src/entities/orchestration/__tests__/laneBoardStore.test.ts`

**Steps:**
1. 新建 store 测试（参考 Orchestration.test.tsx 的 mock invoke 模式）三用例：
   - getBoard reject + listLanes 成功 → lanes 正常、boardSummary === null
   - listLanes reject → error 置位、lanes 空
   - load 成功 → boardSummary 来自快照 freshness_summary
2. `npx vitest run src/entities/orchestration/__tests__/laneBoardStore.test.ts` 绿。
3. Commit: `test(frontend): laneBoardStore board 失败降级分支直接单测`

---

### Task 3: 同批 followup 静默降级对 conductor 可见

**背景**：无效/自指 followup 只进后端日志，conductor 可能误以为拿到了续聊上下文。

**Files:**
- Modify: `backend/orchestration/chat_dispatcher.py`
- Test: `backend/tests/unit/test_chat_dispatcher.py`

**Interfaces:**
- `ChatTaskState` 加 `followup_degraded: bool = False`。

**Steps:**
1. 失败测试：dispatch 含无效 followup_of 任务 → 聚合 markdown 该子任务块含「followup 已降级为新任务」；自指场景同样命中。
2. 实现：路由段降级时置 `state.followup_degraded = True`；`_aggregate` 对该 state 的 block 尾部追加 `\n[注意] followup 已降级为新任务（父任务不存在/未完成/自指），本次结果不含续聊上下文。`
3. 定向 pytest 绿 + ruff + py38 compile。
4. Commit: `feat(orchestration): followup 降级在聚合中对 conductor 可见`

---

### Task 4: 非法 run_id 友好错误文案

**背景**：构造期 ValueError 原始串经 StreamRegistry 下发，前端不可读。

**Files:**
- Modify: `backend/api/legacy_routes.py`（multi 分支 dispatcher 构造段包 try/except ValueError → 重抛可读文案）
- Test: `backend/tests/unit/`（集成构造成本高时允许退化为直接单测包装逻辑）

**裁决（预记录）**：不静默降级 single——非法 run_id 是客户端 bug（resume 流传回脏值），拒绝语义必须保留，只改文案可读性。

**Steps:**
1. 失败测试 → 2. 实现：构造段 try/except ValueError，重抛 `ValueError(f"编排启动失败：run_id 格式非法（应为 orch-* 标识符），请刷新后重试。原始信息: {exc}")` → 3. pytest + ruff + py38 compile → 4. Commit: `fix(orchestration): 非法 run_id 错误文案可读化（保留拒绝语义）`

---

### Task 5: BlackboardRepo 孤儿模块下线

**Files:**
- Delete: `backend/data/blackboard_repo.py`、`backend/tests/unit/test_data_blackboard_repo.py`
- Modify: barrel 导出如有则摘除

**Steps:**
1. 引用面终检 grep `BlackboardRepo|blackboard_repo` 全仓（排除 __pycache__）——预期仅剩模块自身 + 其测试；有其他生产引用 → STOP 报告。
2. git rm 两文件。
3. `pytest tests/unit -q -k "blackboard"` 无残留 + ruff + `python -c "import backend.main"`。
4. Commit: `refactor(data): 下线零调用方孤儿模块 BlackboardRepo`

---

### Task 6: 文档同步

§16.6 划掉已收口四项，补「2026-08-23 fast-follow 波已收口」。并入最后一个 commit 或单独 docs commit。

## 合并与同步

- push 开 PR（base main）→ CI + review → squash 合并 → cherry-pick 到 release/win7（py38 定向验证同上批流程）。

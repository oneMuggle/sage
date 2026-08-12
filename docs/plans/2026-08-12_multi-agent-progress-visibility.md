# Multi-Agent 编排进度可视化

> 历史口径备注:本计划实施完成后,文档将删除,核心内容并入 `docs/technical/27-multi-agent-orchestration.md` 的"进度可视化"小节(若该章节暂无此小节,在 §4 末尾新增)。

## 背景与目标

### 现象

用户在 Sage 客户端发起一个会被拆解为多子任务的请求(例如「我需要学习量化交易,先搜集相关资料后,整理一份学习资料和操作指南,以便我学习和上手」),从用户视角观察到:

1. 子任务进行中时,右侧 progress 栏显示「等待输入...」误导用户以为空闲
2. 任务拆解的瞬间,没有任何「已拆解为 N 个子任务,等待结果中…」的自然语言公告
3. 子任务陆续完成时,UI 仅显示完成计数,没有「已收到 X/N,等待 N-X 个」之类的进度文字
4. 主 LLM (conductor) 在收到部分子任务结果后可能直接生成最终回复,聚合结果是"足够就用",**用户体验上感觉"任务没跑完就汇总了"**

注:这里说的"等待输入"是 Sage 前端 **`ProgressSection.tsx:37`** 的占位文案(`!isLoading && !stateLabel → "等待输入..."`),不是 Claude Code 客户端的 UI 状态。

### 根因(经过代码确认)

1. **后端 `chat_dispatcher.py` 聚合 markdown 不带进度头**:`_aggregate()` (L220-233) 只把子任务结果串起来,conductor 看不到"6 个子任务里目前只回 2 个"。
2. **后端 `task_plan` 事件之后没有独立的 `task_progress` 初始化事件**:前端 `taskBoard` 初始状态是 `statuses: {}`,UI 无法一眼看出"共 N 个,当前 0 个完成"。
3. **前端 `ProgressSection.tsx` 状态机未接入 `taskBoard`**:只看 `isLoading` 和 `streamingState`,编排进行中也会显示"等待输入..."。
4. **`TaskTreeSection.tsx` 仅显示计数,无自然语言公告**:没有"已拆解 N 个"标题文案。

### 验收标准

修复后,用户在多 agent 编排时会看到:

| 阶段 | UI 表现 |
|---|---|
| 1. 任务规划完毕 | 「已拆解为 N 个子任务,等待结果中…」+ 任务树(全 queued `○`) |
| 2. 子任务并行执行中 | 「编排任务 X/N 完成 · K 个进行中」+ 任务树 (running `◐`) |
| 3. 部分子任务完成 | 「编排任务 X/N 完成 · K 个进行中」+ 完成子任务展示 `output_preview` |
| 4. 全部完成 | 「编排任务 N/N 完成」+ 全 `✓` |
| 5. 任意时刻 | **不再显示**"等待输入..."(除非 taskBoard 为空且不在 loading) |

conductor 收到的子任务聚合 markdown 第一行是「已收到 X/N 子任务结果,等待剩余 N-X 个」之类的 header,让 LLM 决策时知道还没齐。

## 涉及的文件与模块

### 后端

| 文件 | 模块 | 改动 |
|---|---|---|
| `backend/orchestration/chat_dispatcher.py` | `ChatDispatcher._aggregate()` | 聚合 markdown 前加进度 header |
| `backend/api/legacy_routes.py` | `/chat/stream` producer | `task_plan` 之后 emit `task_progress` 初始化事件 |
| `backend/tests/unit/test_chat_dispatcher.py` | 单元测试 | 新增 partial / complete 场景断言 |

### 前端

| 文件 | 模块 | 改动 |
|---|---|---|
| `src/shared/api/types.ts` | `AgentEvent` 类型 | 新增 `task_progress` 变体 |
| `src/shared/api/llmStream.ts` | NDJSON 解析 | 新增 `task_progress` 解析分支 |
| `src/features/send-message/useChat.ts` | chat reducer | 接入 `task_progress` reducer + `TaskBoard.progress` 字段 |
| `src/widgets/chat/progress/TaskTreeSection.tsx` | 任务树组件 | 头部加"已拆解 N 个子任务"文案 |
| `src/widgets/chat/progress/ProgressSection.tsx` | 进度面板 | 有 taskBoard 时不显示"等待输入..." |
| `src/widgets/chat/__tests__/TaskTreeSection.test.tsx` | vitest | 新增 assimilation 断言 |
| `src/widgets/chat/__tests__/ProgressSection.test.tsx` | vitest | 新增状态机断言 |

### 协议

新增一个 SSE 事件:

```typescript
type TaskProgressEvent = {
  state: 'task_progress';
  run_id: string;
  total: number;
  done: number;
  running: number;
  queued: number;
  failed: number;
};
```

任务板状态扩展:

```typescript
interface TaskBoard {
  runId: string;
  plan: PlanItem[];
  statuses: Record<string, TaskStatusEvent>;
  progress?: {
    total: number;
    done: number;
    running: number;
    queued: number;
    failed: number;
  };
}
```

## 技术方案

### 阶段 1:后端 P0(P0-1 + P0-2)

**P0-1: 聚合 markdown 头部进度摘要**

`chat_dispatcher.py:_aggregate()` 在拼接每个子任务结果 **之前**,先加一段带 X/N 信息的 header。让 conductor 看到"还没齐":

```python
def _aggregate(self, states: List[ChatTaskState]) -> str:
    total = len(states)
    done = sum(1 for s in states if s.status == 'done')
    failed = sum(1 for s in states if s.status == 'failed')
    in_flight = total - done - failed

    header = (
        f"## 子任务进度摘要\n\n"
        f"- 已收到 {done}/{total} 子任务结果"
        f"{f'({failed} 失败)' if failed else ''}"
        f"{f',{in_flight} 个仍在并行运行' if in_flight else ''}。\n"
        f"- 提醒:在剩余 {in_flight if in_flight else 0} 个子任务未完成前,"
        f"本次回答只能基于当前结果。conductor 应当在所有子任务完成后"
        f"才能给出最终汇总。\n\n"
    )

    blocks = []
    for state in states:
        # 现有逻辑不变
        ...
    return header + "\n\n".join(blocks)
```

**P0-2: `task_progress` 事件**

`legacy_routes.py:L1765`(`task_plan` 入队之后)再 emit 一次:

```python
await entry.queue.put({
    "state": "task_progress",
    "run_id": run_id,
    "total": len(plan_tasks),
    "done": 0,
    "running": 0,
    "queued": len(plan_tasks),
    "failed": 0,
})
```

**注**:`task_status` 事件已经覆盖 done/running/queued/failed 状态切换,`task_progress` 主要是**初始化**与**整盘概览**。前端也可在每次 `task_status` 流入后**实时聚合**出一个 progress 快照,不必每次都等后端单独 emit。但独立的初始化事件确保前端 UI 在子任务跑之前就有 total 数字。

### 阶段 2:前端 P1(P1-1 + P1-2)

**P1-1: `ProgressSection.tsx` 状态机调整**

```tsx
// 旧:
{!isLoading && !stateLabel && <span className="text-muted">等待输入...</span>}

// 新:
{!isLoading && !stateLabel && !taskBoard && (
  <span className="text-muted">等待输入...</span>
)}
{taskBoard && taskBoard.progress && (
  <span className="text-primary">
    编排任务 {taskBoard.progress.done}/{taskBoard.progress.total} 完成
    {taskBoard.progress.running > 0 && (
      <> · {taskBoard.progress.running} 个进行中</>
    )}
    {taskBoard.progress.failed > 0 && (
      <span className="text-error ml-1">
        ({taskBoard.progress.failed} 失败)
      </span>
    )}
  </span>
)}
```

**P1-2: `TaskTreeSection.tsx` 头部**

```tsx
<div className="text-xs text-text-secondary">
  已拆解为 {total} 个子任务,等待结果中…
</div>
<div className="text-xs text-text-secondary">
  完成 {doneCount}/{total}
</div>
```

### 阶段 3:验证测试

| 测试 | 文件 | 断言 |
|---|---|---|
| `test_aggregate_includes_progress_header_when_partial` | `test_chat_dispatcher.py` | 3 子任务中 1 done + 2 running,return 字符串首行含 "已收到 1/3" |
| `test_aggregate_no_pending_section_when_all_done` | `test_chat_dispatcher.py` | 3 子任务全 done,header 不含 "仍在并行运行" |
| `test_legacy_routes_emits_task_progress_after_task_plan` | `test_chat_orchestration_stream.py` | events 流中 `task_progress` 在 `task_plan` 之后第一个 |
| `test_TaskTreeSection_shows_decomposition_narrative` | `TaskTreeSection.test.tsx` | plan=3,渲染含 "已拆解为 3 个子任务" |
| `test_ProgressSection_no_waiting_input_when_taskBoard_present` | `ProgressSection.test.tsx` | isLoading=false,streamingState=null,但 taskBoard 有内容 → 文本不含 "等待输入" |

## 实施步骤

- [x] 步骤 1: 写计划文档(本文件)
- [ ] 步骤 2: 建 feature 分支 `feat/multi-agent-progress-visibility`
- [ ] 步骤 3: P0-1 — 后端 `_aggregate()` 头部进度摘要
- [ ] 步骤 4: P0-2 — 后端 `task_progress` 事件 + 类型 + reducer
- [ ] 步骤 5: P1 — 前端 `ProgressSection` + `TaskTreeSection` UI 状态机
- [ ] 步骤 6: 补 5 个测试 + 跑全量 CI(Python 3200+ / vitest 1100+ / TS 0)
- [ ] 步骤 7: push / PR / CI / AI code review / 等绿灯
- [ ] 步骤 8: 用户 merge → 清理分支 → 文档归档到 `docs/technical/27-multi-agent-orchestration.md` 新增"进度可视化"小节
- [ ] 步骤 9: 删除本计划文档

## 风险评估与依赖

### 风险

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| conductor 看到 header 后行为异常(可能拒绝回答) | 中 | 高 | header 措辞需谨慎,测试 1-2 轮 LLM 行为;并 fallback 仅在 partial 时显示,全完成时省略 |
| `task_progress` 事件流太密集造成 UI 抖动 | 低 | 低 | reducer 用 `useRef` 缓存 + setState 节流 |
| 老 run/task 状态泄漏 | 低 | 中 | useChat.ts 已有 `runId` 严格匹配检查,本改动复用同一逻辑 |
| `dispatch_subagents` 的 maxItems=4 与用户期待 6 个子任务的"拆解多次"语义不一致 | 高 | 低 | 用户在 prompt 里"量化学习"那次实际是 LLM 自动多调了几次 dispatch_subagents,这是设计如此,不在本次范围,但要在计划里标注 |

### 依赖

- **无新依赖**:仅修改现有模块
- **前端 bundle 影响**:无(Types 仅扩展,组件仅改文案)
- **向后兼容**: `task_progress` 事件老客户端忽略(状态机写入会失败但不影响后续); `task_plan` 依旧先于 `task_status` 到达,前端 taskBoard 初始化路径不变

### 测试覆盖

- 单元测试: `test_chat_dispatcher.py` (2 new) + `test_chat_orchestration_stream.py` (1 new)
- 前端 vitest: `TaskTreeSection.test.tsx` (1 new) + `ProgressSection.test.tsx` (1 new)
- 集成: 跑 `test_chat_orchestration_stream.py` 全量验证 SSE 事件流顺序

### 文档归档

完成后:

1. 本文件 `docs/plans/2026-08-12_multi-agent-progress-visibility.md` 删除
2. 在 `docs/technical/27-multi-agent-orchestration.md` 末尾新增:

```markdown
## §27.X 进度可视化

SSE 事件协议:
- `task_plan` — 计划先行(已有)
- `task_progress` — 整盘概览(总/完成/运行/队列/失败)
- `task_status` — 单任务状态切换(已有)

聚合 markdown 头:conductor 拿到子任务结果时,第一行固定是「已收到 X/N 子任务结果…」
形式的进度摘要,让 LLM 知道还没齐,避免"够用就汇总"。

前端任务板:
- `TaskBoard.progress` 字段:total/done/running/queued/failed 五元组
- `ProgressSection` 显示"编排任务 X/N 完成",有 taskBoard 时不显示"等待输入"
- `TaskTreeSection` 头部显示"已拆解为 N 个子任务,等待结果中…"
```

3. 同步到 win7 LTS:`cherry-pick` 此 PR 到 `release/win7`

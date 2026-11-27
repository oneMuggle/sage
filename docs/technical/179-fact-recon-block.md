# 事实侦察区块（FactReconBlock）

> 2026-11-27 新增。此前「事实侦察」只以三行滚动文本混在规划时间线里，用户无法核对侦察到的事实是否**正确、完整**。本特性把侦察结果提升为独立可折叠区块。

## 背景与根因

lite scout 阶段产出的侦察事实，原先只做两件事：

1. 注入 Planner 的上下文；
2. 作为 `plan_progress` 事件的 `text` 单行下发。

前端 `PlanningTimeline` 对每个阶段只渲染 `stage.lines.slice(-3)` 且每行 `truncate` —— 于是用户永远只能看到**最后三行、每行被截断**的过程文本，事实正文从未到达前端。信息链断在「scout 产出 → 前端展示」这一段。

本特性补两条链路：

```
scout 事实 ──→ plan_progress.detail.facts ──→ 前端实时（流式中）
            └─→ client_meta.scout_facts ──→ DB ──→ 前端回读（刷新后）
```

## 后端

### 解析器 `backend/orchestration/scout_facts.py`

lite scout 返回的是自由文本，解析器**保守**处理，原则是「宁可整行进正文，绝不丢内容」：

| 常量 | 值 | 作用 |
| --- | --- | --- |
| `SCOUT_FACTS_MAX_ITEMS` | 12 | 事实条数上限，超出则 `truncated=True` |
| `SCOUT_FACT_MAX_CHARS` | 4000 | 单条事实正文上限。与上游 lite scout 原始文本的截断上限（`SCOUT_FACTS_MAX_CHARS`）**同值**，因此单条事实在生产路径上永不触发裁剪；常量仅对其它调用方传入的任意 raw 兜底 |
| `SCOUT_SOURCE_MAX_CHARS` | 120 | 单条来源标注上限 |
| `SCOUT_MIN_BODY_CHARS` | 6 | 正文短于此长度视为噪声，不单列 |
| `SCOUT_CLIENT_META_MAX_BYTES` | 32768 | 整个 client_meta 序列化上限（32 KiB） |

- `parse_scout_facts(raw)` → `list[dict]`：切分 bullet 行，正文与来源标注拆开；拆不出的整行进 `text`。
- `to_detail(raw)` → `{"facts": [{"text", "source"}], "fact_count": int, "truncated": bool}`。
- `build_client_meta_json(detail)` → JSON 字符串；事实为空或超过 32 KiB 时返回 `None`（不落库）。

> `plan_progress` 的 `detail` 序列化上限 `MAX_PROGRESS_DETAIL_BYTES` 同为 **32768**，与 `SCOUT_CLIENT_META_MAX_BYTES` 同口径 —— 落库能存下的载荷，实时下发也一定能送达，避免「实时看不到、刷新后却有」的不一致。

### 注入点 `backend/orchestration/plan_preflight.py`

两处 lite scout 路径设置 `result["scout_facts_detail"]`：

- 复杂任务降级到 lite scout 的 `_fallback_scout_lite`（约 317–322 行）；
- medium 复杂度路径（约 406–409 行）。

两处都通过 `run_planning_stage(..., detail_result=lambda facts: _scout_facts_detail(facts))` 把结构化事实挂到 `plan_progress` 事件的 `detail` 上。

**scout_deep 成功路径刻意不设 `scout_facts_detail`** —— 深度调研有自己的 `ResearchSummaryCard` 展示，两条路径不重复渲染。

### 落库 `backend/api/legacy_routes.py`

- `scout_facts_detail` 在 preflight 结束后从 `preflight_context` 中 pop（不进入 Planner 的 LLM 上下文，也不进入任何 prompt）。
- 首条 assistant 行（`step_done`）与最终 assistant 行的 `client_meta` 写入 `scout_facts`；两者都用 `scout_facts_client_meta_written` 标志位保证**只写一次**。
- 用户中断且首个 `step_done` 尚未发生时，同一份 `client_meta` 挂到 **cancelled partial 行** —— 否则刷新后该轮没有任何气泡能渲染「事实侦察」区块。
- `client_meta` 是 `messages` 表的 JSON-in-TEXT 列，**纯展示用**，不进入 LLM 上下文，无需数据库迁移。

## 前端

### 类型 `src/shared/api/types/chatAndEventTypes.ts`

```ts
export interface ScoutFact {
  text: string;    // 事实正文（原文，去掉 bullet 前缀）
  source: string;  // 来源标注（无则空串）
}

export interface ScoutFactsMeta {
  facts: ScoutFact[];
  fact_count: number;
  truncated?: boolean;
}
```

`MessageDisplayMeta` 新增可选字段 `scout_facts?: ScoutFactsMeta`。

### reducer `src/features/send-message/planProgress.ts`

- `PlanStageState` 新增 `facts?: ScoutFact[]` 与 `factsTruncated?: boolean`。
- `parseScoutFacts(detail)` 解析 `detail.facts`：只认数组 + 逐项 `text` 为字符串，非法项丢弃；**正文不截断**（用户的诉求正是核对事实是否完整）。
- **分阶段限额**（`limitsFor`）：scout 放宽到 60 行 / 500 字符（其过程行成为「侦察过程」二级折叠内容），其余阶段维持 20 行 / 240 字符不变。
- 防御性兜底：事实条数 ≤ 60、正文 ≤ 4000 字符（与后端 `SCOUT_FACT_MAX_CHARS` 对齐）、来源 ≤ 120 字符（正常载荷不会触发）。
- `factsTruncated` **单调合并**：后续事件缺失 `truncated` 字段时不会把已置位的 `true` 抹掉。

### 组件 `src/widgets/chat/FactReconBlock.tsx`

结构参考主流 AI 应用：

| 元素 | 参考 |
| --- | --- |
| 折叠头「事实侦察 · N 条事实 · 12.3s」 | Claude Code「Thought for 8s」、Perplexity Steps 手风琴 |
| 逐条事实 + 来源 chip | ChatGPT Deep Research 的 activity steps + sources |
| 二级折叠「侦察过程（N）」 | ChatGPT Deep Research 的 activity steps |

关键行为：

- **正文完整换行显示（`whitespace-pre-wrap`），绝不截断** —— 用户要核对事实是否被截断/遗漏。
- **展开策略**：用户手动切换优先于自动策略（`manual !== null ? manual : auto`）。auto 一经 scout 启动即**锁定为展开**（`autoOpened` 状态位）—— facts 只在 `done` 事件才到达，若此刻自动收起，用户会看到「刚填满就收起」，与核对事实的目标相悖。落库回读态（刷新后）不触发自动展开，默认折叠。
- **数据源优先级**：实时 store（scout 阶段的 `facts` + `lines`）> 落库回读的 `client_meta.scout_facts`。
- **作用域守卫**：实时数据只在 `messageId === streamingMessageId` 时消费 —— 否则每条历史气泡都会重复渲染该区块。
- **无数据不渲染**：既无实时 scout 阶段、也无落库清单时返回 `null`（不出现空盒子）。

### 集成 `src/widgets/chat/Message.tsx` / `PlanningTimeline.tsx`

- `Message.tsx` 在 `PlanningTimeline` 之后注入 `<FactReconBlock persistedFacts={message.client_meta?.scout_facts} />`（仅 assistant 气泡）。
- `PlanningTimeline.tsx` **不再渲染 scout 阶段的过程行**（`stage.stage !== 'scout'`）—— scout 的过程行移交「事实侦察」区块的二级折叠，避免同一内容出现两处。

## 生命周期

| 时点 | 行为 |
| --- | --- |
| `startStream` | `planProgress` 槽位清空（新一轮不残留） |
| 流式进行中 | scout `done` 事件带 `detail.facts` → reducer 存入 `PlanStageState.facts` → 区块实时更新 |
| `finishStream` / `clearStream` | `planProgress` 清空 → 实时数据消失，回落到落库清单 |
| 会话刷新 | 后端 `get_messages` 返回带 `client_meta` 的 assistant 行 → 区块重新显示落库清单 |

`useChat.ts` 在流结束时 `void useStore.getState().loadMessages(sid)`，服务端行（含 `client_meta`）替换本地消息，因此落库事实跨刷新存活。

## 已知边界

- 只覆盖 **lite scout**；`scout_deep` 走 `ResearchSummaryCard`，不重复渲染。
- 只做**展示**，不做逐条标注回流到 Planner（用户确认过的范围决策）。
- 事实条数上限 12 条由后端设定，超出时前端显示「事实条数超过展示上限，仅显示前 N 条」提示。

## 测试

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/unit/test_scout_facts.py` | 解析器：bullet 切分、来源拆分、上限、截断标记、单条 4000 字正文完整保留、32 KiB 兜底（18 例） |
| `backend/tests/orchestration/test_plan_progress.py` | `detail` 随 `done` 下发、`detail_result` 异常降级、超 32 KiB 丢弃、预算内保留（6 例） |
| `backend/tests/orchestration/test_plan_preflight_progress.py` | medium 路径带 `scout_facts_detail`；scout_deep 成功路径**不带**（2 例） |
| `backend/tests/integration/test_scout_facts_client_meta.py` | `client_meta` 落库与只写一次（3 例） |
| `src/features/send-message/__tests__/planProgress.test.ts` | reducer：事实解析、非法项丢弃、正文不截断（4000 字边界）、分阶段限额、截断标记单调透传（20 例） |
| `src/widgets/chat/__tests__/FactReconBlock.test.tsx` | 折叠/展开、计数、全文不截断、来源 chip、实时优先、手动覆盖自动、作用域守卫、过程二级折叠、截断提示（12 例） |
| `src/widgets/chat/__tests__/Message.factRecon.test.tsx` | 气泡集成：assistant 渲染、user 不渲染、无数据不渲染（3 例） |

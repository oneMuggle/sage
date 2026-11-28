# 事实侦察区块化实施计划（可折叠「事实侦察」区块）

> 2026-11-27 · 分支 `feat/fact-recon-block`（worktree `.worktrees/feat-fact-recon-block`，基线 `origin/main` @ `1fb6c3a53`）
> 配套设计：见本文件「设计取舍」节（brainstorming 阶段已与用户确认三项范围决策）

## 1. 背景与目标

### 现状问题

用户提问后，Sage 会在拆解前跑一轮「事实侦察」（lite scout）。当前前端只在气泡内以
**三行滚动**显示侦察过程，用户既看不全、也无法核对：

1. `src/widgets/chat/PlanningTimeline.tsx:92` 对每个阶段只渲染 `stage.lines.slice(-3)`，
   且每行 `truncate` —— 超过三行的侦察轨迹直接被丢弃。
2. 更严重的是：**侦察到的事实清单（`scout_facts`）根本没有到达前端**。
   `plan_preflight` 只把事实注入 Planner 的上下文，前端拿到的仅是
   `_scout_event_to_progress` 映射出的过程轨迹（thinking / 工具名 / "工具返回结果"）。
3. `PlanningTimeline` 仅在 `streamingMessageId === messageId` 时渲染 ——
   流式结束、答案成型（用户最需要拿事实与答案对照的时刻）整块消失。

### 目标

把「事实侦察」升级为一个**可折叠/展开的独立区块**，让用户能：

- 看全侦察到的**事实清单**（每条一句话 + 来源），不被行数截断；
- 展开查看**侦察过程轨迹**（二级折叠）；
- 在答案生成完毕后**仍能回看**这些事实，用于核验答案的正确性与完整性。

### 范围决策（用户已确认）

| 决策点 | 结论 |
|---|---|
| 内容范围 | 事实清单 + 侦察过程（过程作为二级折叠） |
| 反馈机制 | 纯展示，不做逐条标注、不回流到 planner |
| 覆盖范围 | 只做 lite scout；scout_deep 继续用既有 `ResearchSummaryCard` |

## 2. 根因定位（已逐行核对）

| 位置 | 事实 |
|---|---|
| `src/widgets/chat/PlanningTimeline.tsx:92` | `stage.lines.slice(-3)` + `truncate` → "三行滚动"的直接来源 |
| `src/features/send-message/planProgress.ts:28-29` | `MAX_LINES_PER_STAGE = 20`、`MAX_TEXT_LENGTH = 240` |
| `backend/orchestration/plan_preflight.py:74` | `SCOUT_FACTS_MAX_CHARS = 4000`（事实仅注入 Planner） |
| `backend/orchestration/plan_preflight.py:508` | `_scout_event_to_progress` 只映射过程事件，**不映射事实** |
| `backend/orchestration/plan_progress.py` | `emit_plan_progress` 已有 `detail` 字段，但 `run_planning_stage` 未使用 |
| `src/shared/api/types/chatAndEventTypes.ts:800` | `PlanProgressItem.detail?: Record<string, unknown>` —— **协议形状无需变更** |
| `backend/data/session_repo.py:442,511` | `messages.client_meta` 是 JSON-in-TEXT 列，回读已解析为 dict |
| `backend/api/legacy_routes.py:2636-2653` | 首条 assistant 行的 `memory_refs` / `rag_citations` 挂载先例（R38 / R81 flag 模式） |

**关键推论**：事实的"不可见"是**链路缺失**而非"渲染截断"，必须打通
`scout 事实 → plan_progress.detail → 前端` 以及 `scout 事实 → client_meta 落库 → 前端` 两条链路。

## 3. 涉及文件与模块

### 后端

| 文件 | 改动 |
|---|---|
| `backend/orchestration/scout_facts.py`（新增） | 事实文本 → 结构化清单的保守解析器 |
| `backend/orchestration/plan_progress.py` | `run_planning_stage` 增 `detail_result` 参数；detail 体积守卫 |
| `backend/orchestration/plan_preflight.py` | 两处 lite scout 调用点挂 `detail_result`（facts 实时下发） |
| `backend/api/legacy_routes.py` | preflight 后回填 `scout_facts_client_meta_json`；首条 assistant 行落库 `client_meta` |

### 前端

| 文件 | 改动 |
|---|---|
| `src/shared/api/types/chatAndEventTypes.ts` | `ScoutFact` / `ScoutFactsMeta` 类型；`MessageDisplayMeta.scout_facts` |
| `src/features/send-message/planProgress.ts` | `PlanStageState.facts`；scout 阶段行上限 20→60、文本 240→500 |
| `src/widgets/chat/FactReconBlock.tsx`（新增） | 可折叠事实区块组件 |
| `src/widgets/chat/Message.tsx` | 注入 `FactReconBlock` |
| `src/widgets/chat/PlanningTimeline.tsx` | scout 阶段不再渲染 lines（内容移交新块） |

### 文档

| 文件 | 改动 |
|---|---|
| `docs/technical/183-fact-recon-block.md`（新增） | 技术说明 |
| `docs/user-manual/64-fact-recon-block.md`（新增） | 用户手册 |
| `docs/technical/README.md` / `docs/user-manual/README.md` | 目录表补一行 |

## 4. 技术方案

### 4.1 数据契约

```ts
// src/shared/api/types/chatAndEventTypes.ts
export interface ScoutFact {
  /** 事实正文（原文，去掉 bullet 前缀；来源标注已拆出到 source） */
  text: string;
  /** 来源标注（无则空串） */
  source: string;
}

export interface ScoutFactsMeta {
  facts: ScoutFact[];
  fact_count: number;
  /** 事实条数超过展示上限时为 true */
  truncated?: boolean;
}
```

`MessageDisplayMeta.scout_facts?: ScoutFactsMeta` —— `client_meta` 已在库中定义为
"仅用于会话气泡回显，不参与 LLM 上下文"，语义完全吻合，无需 DB 迁移。

### 4.2 后端 · 事实解析（保守策略）

`backend/orchestration/scout_facts.py`：

```
parse_scout_facts(raw: str) -> list[ScoutFact]
```

规则（**宁可不拆，也绝不丢信息或臆造**）：

1. 按行切分、去空行；
2. 剥 bullet 前缀：`- ` / `* ` / `• ` / `1. ` / `1) ` / `① `；
3. 行尾来源标注仅在**形态明确且剩余正文非空**时拆出：
   `（来源：X）` / `(来源: X)` / `[来源: X]` / 结尾 `来源：X`；
   来源长度 ≤ 120 字符，否则视为正文（`source` 留空）；
4. 首行若以 `：` / `:` 结尾且后续存在事实行 → 视为引导句跳过；
5. 无 bullet 时整段按行切；仍只有一行 → 整段作为**一条**事实（不丢内容）；
6. 条数上限 `SCOUT_FACTS_MAX_ITEMS = 12`，超出置 `truncated=True`（侦察本身 ≤10 条，
   上限只是防御）。

**保守性验证点**：拆不出来就整行进 `text`，绝不因为"解析不出结构"而丢行。

### 4.3 后端 · 实时下发

`run_planning_stage` 增可选参数：

```python
detail_result: Optional[Callable[[Any], Dict[str, Any]]] = None
```

done 事件改为 `detail=detail_result(result)`（缺省 `{}`）。
lite scout 两处调用点（`_fallback_scout_lite` 与 medium 主路径）挂：

```python
detail_result=lambda facts: scout_facts.to_detail(facts)  # {"facts": [...], "fact_count": n}
```

`emit_plan_progress` 的 `detail` 增加体积守卫（序列化 > 32 KiB 则丢弃 detail 并记 warning ——
与 `client_meta` 落库预算同口径），避免 detail 撑爆 NDJSON 行。

### 4.4 后端 · 落库

`legacy_routes.chat_stream_create`：

1. 在 mode 判定之后、`if mode == "multi":` 之前声明
   `scout_facts_client_meta_json: Optional[str] = None` 与
   `scout_facts_client_meta_written = False`（**必须在 preflight 之前声明**，
   否则会覆盖 preflight 回填的值）；
2. preflight 返回后，若 `scout_facts` 非空 → 解析 → `json.dumps` → 32 KiB 守卫（同 user 消息）；
3. 落库挂载沿用 R38/R81 的 flag 模式：
   - `step_done` 的 assistant 行：`client_meta=(json if not written else None)`，写后置 `written=True`；
   - 终稿行：同样条件（单步 run 无 `STEP_DONE`，此时首条即终稿行）。

挂**首条** assistant 行的理由：规划期的事实块渲染在第一个气泡里，落库到同一行 →
刷新后位置不变，不会"跳到别的气泡"。

### 4.5 前端 · reducer

`planProgress.ts`：

- `PlanStageState` 增 `facts?: ScoutFact[]`；
- `reducePlanProgress`：`item.stage === 'scout'` 且 `item.detail?.facts` 为数组时，
  解析为 `facts` 存入阶段状态（只认数组 + 逐项 `text` 为字符串，非法项丢弃）；
- scout 阶段 `lines` 上限 20 → 60，`MAX_TEXT_LENGTH` 240 → 500（与后端 `MAX_PROGRESS_TEXT` 对齐）；
- 其余阶段行为不变。

### 4.6 前端 · 组件

`src/widgets/chat/FactReconBlock.tsx`：

```
props: { sessionId, messageId, persistedFacts?: ScoutFactsMeta | null }
```

- **数据源优先级**：实时 store（scout 阶段 `facts` + 过程 `lines`）> 持久化 `persistedFacts`；
- **渲染**：
  - 折叠头：`事实侦察 · N 条事实 · 12.3s` + chevron 按钮（`aria-expanded`）；
  - 展开体：有序列表，序号 + 事实正文（**完整换行显示，不截断**）+ 来源 chip（弱化色）；
  - 底部二级折叠：`侦察过程（N）` → 过程行列表（thinking / 工具调用 / 结果）；
- **展开态策略**：scout 一旦启动过就锁定为自动展开（facts 只在 `done` 事件到达，
  完成瞬间收起会让用户看到「刚填满就收起」）；落库回读态默认折叠；
  用户手动切换后以用户选择为准（`manual !== null ? manual : auto`）。

**主流应用对照**（设计取舍来源）：

| 应用 | 做法 | 本方案取用 |
|---|---|---|
| ChatGPT Deep Research | activity steps 实时可见 + 独立 Sources 面板 | 侦察过程实时可见 + 事实清单独立成块 |
| Claude Code | "Thought for 8s" 可折叠摘要 | 折叠头显示条数与耗时，点击展开全文 |
| Manus | 步骤卡片可展开查看细节 | 事实清单逐条展开，不截断 |
| Perplexity | Steps 手风琴 | 侦察过程作为二级折叠，避免与主块争夺注意力 |

### 4.7 前端 · 集成

- `Message.tsx`：`isAssistant` 时渲染
  `<FactReconBlock sessionId messageId persistedFacts={message.client_meta?.scout_facts} />`；
- `PlanningTimeline.tsx`：scout 阶段**不再**渲染 `lines`（内容已由新块承载），其余阶段不变。

### 4.8 生命周期（为何刷新后仍在）

1. 流式中：store 的 `planProgress` → 新块实时渲染；
2. 流结束：`useChat.ts` 末尾 `loadMessages(sid)` 以服务端为准刷新 → 落库的
   `client_meta.scout_facts` 回到消息对象 → 新块继续渲染；
3. 再次进入会话：从 DB 读回 `client_meta` → 同样渲染。

## 5. 实施步骤（里程碑）

- [x] **M0 计划**：本文档（`docs/plans/2026-11-27_fact-recon-block.md`）
- [x] **M1 后端解析器**：`scout_facts.py` + 单测（`backend/tests/unit/test_scout_facts.py`）
- [x] **M2 后端协议**：`plan_progress.detail_result` + detail 体积守卫 + 单测
- [x] **M3 后端下发**：preflight 两处挂 `detail_result` + 单测（done 事件含 facts）
- [x] **M4 后端落库**：`legacy_routes` 首条 assistant 行 `client_meta.scout_facts` + 单测
- [x] **M5 前端类型 + reducer**：`ScoutFact` / `ScoutFactsMeta` / `PlanStageState.facts` + vitest
- [x] **M6 前端组件**：`FactReconBlock.tsx` + vitest（折叠/展开/来源/回落/无障碍）
- [x] **M7 前端集成**：`Message.tsx` 注入 + `PlanningTimeline` scout 去重 + vitest
- [x] **M8 文档**：技术 183 / 用户手册 64 + 两份 README 目录
- [ ] **M9 验收**：`sage-backend` 跑 pytest；前端 vitest + typecheck + `npm run verify:pre-push`
- [ ] **M10 合并**：PR → main（CI 绿）→ 合并 → cherry-pick 到 `release/win7` + py38 适配
- [ ] **M11 归档**：功能点并入技术/用户手册后删除本计划文件

## 6. 测试策略

| 层 | 用例要点 |
|---|---|
| 后端单测 | 解析：bullet 剥离、来源拆分、无来源、无 bullet 整段、引导句跳过、超长行、条数上限；`detail_result` done 事件载荷；`client_meta` 落库与回读 |
| 前端 vitest | reducer：`detail.facts` 解析、非法项丢弃、scout 行上限 60/文本 500；组件：折叠头计数、展开显示全文不截断、来源 chip、过程二级折叠、实时优先于持久化、无数据不渲染、`aria-expanded` |
| 回归 | 既有 `PlanningTimeline.test.tsx`（scout lines 不再渲染需调整断言）、`planProgress.test.ts`（行数/截断断言需调整） |

## 7. 风险与依赖

| 风险 | 缓解 |
|---|---|
| 侦察输出格式由 LLM 自由发挥，解析不稳定 | 保守解析：拆不出就整行保留；测试覆盖多种畸形输入 |
| `client_meta` 32 KiB 上限 | 事实条数 ≤ 12、单条正文截断上限内；超限丢弃展示元数据不影响消息落库 |
| 事实挂错气泡（用户找不到） | 挂首条 assistant 行 + 与实时渲染位置一致；刷新后位置不变 |
| 首条 assistant 行不是规划所在气泡 | 规划发生在 run 之前，第一个气泡即规划气泡；`step_done` 只切后续气泡 |
| `preflight_context` 作用域 | 在 mode 分支**之前**声明回填变量，避免覆盖与 UnboundLocal |
| win7（Python 3.8）兼容 | 不用 `str.removeprefix`（3.9+）、不用 `X | Y` 运行时注解（配 `from __future__ import annotations`）；typing 用 `Dict/List/Optional` |
| 双分支棘轮 | win7 侧数值（覆盖率/架构基线）按分支实测，勿直接复制 main 数值 |

## 8. 双分支同步

1. main：实现 → 测试 → PR → CI 绿 → squash 合并；
2. `release/win7`：cherry-pick → py38 适配（类型注解、`removeprefix`）→ 跑 py38 测试 → PR → 合并；
3. 两侧 `docs/technical` / `docs/user-manual` 编号**各自按分支实际最大值 +1**（不共用 main 编号）。

## 9. 附：不做的事（明确排除）

- 不做逐条事实标注 / 点赞 / 反馈回流到 planner；
- 不改 `scout_deep` 的 `ResearchSummaryCard`；
- 不改 scout 的提示词与推理策略（只做展示层与传输层）；
- 不做数据库迁移（`client_meta` 已有）。

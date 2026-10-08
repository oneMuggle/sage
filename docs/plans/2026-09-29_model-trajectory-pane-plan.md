# F3 模型轨迹查看器（Trajectory Tab）实施方案

> 对标 ZCode `ModelTrajectoryPane`：完整模型轨迹——时间线、搜索、工具 payload、角色样式。
> 批次：循环㉕（2026-09-29）。分支 `feat/model-trajectory-pane`，基线 b61bede74。

## 0. 定位与边界

- **纯前端批次**：轨迹数据全部来自前端 messages store（`src/shared/lib/store.ts:82`
  Message 已含 role/content/created_at/model/provider/tool_calls/reasoning_content/
  step_index/finish_reason/generation_stats/memory_refs/activated_skills/compact_info）。
  **不新增后端端点**——`session_events` 查询 API 留待 DSH-Rxx legacy_routes 拆分收口后
  另批接入（现 API 层正在逐日重构，避开前线）。
- 与既有组件的关系：EventTimeline（orch run 事件）覆盖「编排运行」粒度；
  ToolCallCard（Message.tsx 内）覆盖单条消息内嵌工具卡。本批补齐「整段会话的模型轨迹」
  视图：会话级时间线 + 跨消息搜索 + 集中 payload 查看。

## 1. 数据派生 `src/features/chat/useConversationTrajectory.ts`

输入 `sessionId: string | null`，从 `useStore((s) => s.messages)` 派生：

```ts
export interface TrajectoryEntry {
  messageId: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  /** 预览文本：content 去空白换行折叠、TRUNC 60 字符截断 */
  preview: string;
  createdAt: number;
  stepIndex?: number | null;
  model?: string;
  provider?: string;
  finishReason?: string | null;
  /** 终稿统计（assistant 且有 generation_stats 时） */
  totalTokens?: number;
  latencyMs?: number;
  toolCallCount: number;   // tool_calls 解析后条数
  reasoningPreview?: string; // reasoning_content 折叠 60 字符
  hasMemoryRefs: boolean;
  hasSkills: boolean;
  hasCompactInfo: boolean;
}
```

- 过滤：`session_id` 匹配；排除 `subtype === 'topic_separator'`；保留 tool/system
  角色（轨迹完整性优先）。
- `tool_calls` 解析沿用 `Message.tsx:486` 先例：数组直接用，字符串 JSON.parse（失败记 0）。
- 导出 `TRAJECTORY_PREVIEW_MAX_CHARS = 60`。
- memo 依赖 `[messages, sessionId]`。

## 2. 组件 `src/widgets/chat/TrajectoryPane.tsx`

- 搜索框（`data-testid="trajectory-search"`）：大小写不敏感子串匹配 preview +
  reasoning_preview + tool_call 名称；空串显示全部。
- 条目行（`data-testid="trajectory-entry"`）：角色徽标（user=蓝 / assistant=绿 /
  tool=琥珀 / system=灰，沿用 tailwind 语义色）、preview、辅助行
  （HH:MM:SS · model · step · N tools · tokens · latency）。
- 点击条目展开详情块（`data-testid="trajectory-detail"`）：完整 reasoning_content、
  每个 tool_call 的 name/args(JSON.stringify)/result 截断 500 字符、finish_reason、
  compact/skills/memory 摘要。
- 空态：「暂无轨迹」；无命中：「无匹配轨迹」。
- 点击条目同时 `requestMessageJump(messageId)`（复用 messageJumpStore，与 U1 一致）
  ——定位到消息本体。
- 滚动定位：消息跳转由既有 requestMessageJump 通道承担，面板不做滚动同步。

## 3. RightPanel 接线（最小侵入）

- `rightPanelStore.ts`：`RightPanelTab` 与 `VALID_TABS` 追加 `'trajectory'`
  （localStorage VALID 校验自动兼容旧值，无需迁移）。
- `RightPanel.tsx`：`RIGHT_PANEL_TABS` 插入 `'trajectory'`（outline 之后）；
  `TAB_LABELS.trajectory = '轨迹'`；内容区 switch 增加
  `<TrajectoryPane sessionId={sessionId} />` 分支。

## 4. 测试

| 文件 | 用例 |
| --- | --- |
| `src/features/chat/__tests__/useConversationTrajectory.test.ts` | 轮次/角色派生、topic_separator 排除、tool_calls 字符串解析、60 字符截断、跨会话过滤、null 会话空态、stats 字段透传 |
| `src/widgets/chat/__tests__/TrajectoryPane.test.tsx` | 渲染条目、搜索过滤（命中/不命中）、点击展开详情、点击触发 requestMessageJump、空态 |
| `src/widgets/chat/__tests__/RightPanel.test.tsx` | 追加：轨迹 Tab 渲染（mock 消息 → trajectory-entry 出现） |

## 5. 验收

- `npm run typecheck` 0 错误；改动文件 eslint 0；全量 vitest 0 failed。
- 不触碰 backend/、legacy_routes、Message.tsx（避让并行）。
- win7 对齐随 merge 后 cherry-pick（无 py 依赖，预期零冲突）。

# 右侧面板 Round 1 计划——P0 四件套：状态全局化 / 自动唤起+内联卡片 / 上下文持久化 / 全屏+宽度档位

> 日期: 2026-09-18
> 目标分支: main（release/win7 对齐：面板三文件两分支一致，仅 Chat.tsx 有 39 行差异，PR 合并后 cherry-pick）
> 前序分析: 会话内 UI 差距分析（对标 Claude Artifacts / ChatGPT Canvas / Cursor Agent Panel）

## 背景与差距

右侧面板（`src/widgets/chat/RightPanel.tsx`）做工扎实（四 Tab、可拖宽、push/overlay 双模式、memo），
但对比主流 AI 应用有三个结构性差距：

| 差距 | 现状 | 主流做法 |
| --- | --- | --- |
| 被动 | 产物产出后面板无任何反应，用户必须自己知道去点 | Claude/ChatGPT 创建产物即自动展开，关闭时有未读提示 |
| 脱节 | 对话流与产物零关联，消息里的工具调用看不到产出的文件 | 消息内联产物卡片，点击直达预览 |
| 无沉淀 | 重开面板永远落"进度"Tab；最宽 600px 无全屏；无宽度档位 | 上下文记忆 + 全屏 + 档位是三家标配 |

另有工程隐患：面板开合状态散落在 `Chat.tsx` useState（自动唤起需要跨组件写状态，useState 做不到）；
`selected` artifact 不随 sessionId 清理（切会话可能停留在上一会话的产物详情）。

## 方案（四个批次，同分支顺序交付）

### 批次 A（P0-1 基建）：rightPanelStore + 产物列表 store 化

1. `src/features/right-panel/rightPanelStore.ts` — 新 zustand store（项目无 persist 中间件
   用例，沿用手工 localStorage 模式）：
   - `open: boolean`（持久化 `right-panel-open`，迁移读取旧值）
   - `tab: Tab`（持久化 `right-panel-tab`，非法值回落 progress）——Tab 类型移到本文件
   - `maximized: boolean`（不持久化，会话级）
   - `selectedArtifactId: string | null`（不持久化）
   - `seenArtifactCount: Record<sessionId, number>`（未读徽标基线，不持久化）
   - 动作：`setOpen/toggle/setTab/setMaximized/selectArtifact/clearSelectedArtifact/markArtifactsSeen`
   - `selectArtifact(id)` = open + tab:'artifacts' + selectedArtifactId
   - 模块函数 `maybeAutoOpenArtifactPanel(sid)`：sid === useStore.currentSessionId
     且 localStorage `right-panel-auto-open` !== '0' 且面板关着 → open 到产物 Tab
2. `src/features/artifacts/artifactListStore.ts` — 产物列表上抬为 store
   （`bySession: Record<sid, Artifact[]>` + inflight 去重）；`useArtifacts` 重写为
   store 的 hook 封装，对外 API（`{ artifacts, loading, refresh }`）不变，
   RightPanel 与 MessageList 共享同一次请求。
3. `Chat.tsx` 删除 `rightPanelOpen` useState，改读 store；快捷键逻辑不动。

### 批次 B（P0-2）：自动唤起 + 未读徽标 + 消息内联产物卡片

1. `orchestrationEvents.applyOrchestrationEventToBoard` 的 `artifact_created` 分支
   （`bumpArtifactEvent(sid)` 旁）调 `maybeAutoOpenArtifactPanel(sid)` —— 主路径与
   重接路径共用；后台会话只 bump 不打扰（侧栏已有 📎N）。
2. `RightPanelToggle` 加 `unseenCount` prop：面板关着且有未读产物时渲染红点。
   Chat 计算 `counts[currentSessionId] - seen[currentSessionId]`；面板打开即
   `markArtifactsSeen`。
3. `MessageList` 加 `sessionId` prop，内部用 useArtifacts 建
   `tool_call_id → Artifact[]` 映射，传 `artifactsByToolCall` 给 Message；
   `Message` 在命中的工具卡片下渲染 `📄 name` chip，点击
   `selectArtifact(artifact.id)`（直达产物 Tab 预览）。`Artifact.tool_call_id`
   已存在于数据模型，零后端改动。

### 批次 C（P0-3）：上下文持久化 + 跨会话清理

- Tab 持久化在批次 A store 内已含；本批次收尾：
  - `RightPanel` 对 sessionId 变化 useEffect → `clearSelectedArtifact()`（修脏状态 bug）。
  - `ArtifactViewer` 返回按钮 → `clearSelectedArtifact()`。
  - 重开面板时若 store.selectedArtifactId 仍有效则直接落产物详情（已有语义，补测试固化）。

### 批次 D（P0-4）：全屏最大化 + 宽度档位 + 手柄热区

1. `useResizablePanel` 增加 `applyWidth(next)` 返回：clamp + 立即持久化（拖拽路径不变）。
2. `RightPanel` push 模式 maximized 时：面板 `absolute inset-0 z-20`（内容行容器加
   relative），宽度样式忽略；Esc 退出最大化；overlay（窄屏）不提供最大化。
   resize 手柄在最大化时隐藏。
3. `PanelHeader`（列表态与详情态都）加最大化/还原按钮（Maximize2/Minimize2）；
   产物 Tab 加自动唤起开关按钮（Bell/BellOff，读写 `right-panel-auto-open`）。
4. 宽度档位：header 右侧 S/M/L 三档（320/440/560，走 `applyWidth`）+ 拖拽手柄
   双击回落默认 320。手柄热区 `w-1` → `w-1.5` 并补 `role="separator"` +
   方向键 ±32px（a11y）。

## 不做（本轮明确排除）

- 版本历史 / 面板内编辑 / diff 确认（P1，需后端或 SplitDiff 接线，独立轮次）
- Markdown 渲染切换、CSV 分页（P1 预览升级批次）
- overlay 模式遮罩与点外关闭（P2 打磨批次）
- 自动唤起的全局设置页入口（先用面板 header 的 Bell 开关，够用且就近）

## 验收

- 单测：rightPanelStore（持久化/迁移/selectArtifact 副作用/markSeen/自动唤起守卫）、
  RightPanel（最大化渲染/会话切换清 selected）、PanelHeader（最大化+Bell）、
  Message 内联 chip（命中渲染/点击 selectArtifact）、orchestrationEvents
  （当前会话自动开、后台会话不开）、useResizablePanel（applyWidth clamp+持久化）。
- 回归：既有 RightPanel/PanelHeader/ArtifactsSection/Message* 测试全绿；
  tsc / eslint / vitest 全绿。
- 交互验收（手测路径）：关面板让 agent 写文件 → toggle 红点亮起（或直接自动展开）；
  消息工具卡片下出现产物 chip → 点击直达预览；重开面板回到上次 Tab；
  最大化铺满内容行、Esc 退出；S/M/L 档位生效且重启保留。

## Win7 对齐

面板三文件（RightPanel/RightPanelToggle/useResizablePanel）两分支完全一致；
`orchestrationEvents.ts`/`MessageList.tsx`/`Message.tsx` 待实施时比对。
预期：main PR 合并后， cherry-pick 到 `release/win7` 分支开对齐 PR（本仓库惯例，
参考 round24：main #1088 → win7 #1094）。

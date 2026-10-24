# 2026-10-24 会话历史自动展开优化

## 背景与目标

当前切换到已完成/失败的会话时，历史消息默认折叠（窗口截断到最近 60 条 + 回合级折叠），
用户需要手动点击"加载更早消息"和展开每个回合才能看到完整历史。

**目标**：非 running 状态的会话（completed/failed/idle/suspended）切换到后自动展示全部消息，
回合默认展开；running 状态的会话保持当前截断+折叠行为（避免流式更新时频繁重渲染）。

## 涉及的文件

| 文件 | 改动 |
|------|------|
| `src/widgets/chat/MessageList.tsx` | 新增 `runStatus` prop，切换会话时按状态决定初始 windowSize |
| `src/widgets/chat/TurnGroup.tsx` | 新增 `defaultExpanded` prop，控制回合初始展开状态 |
| `src/pages/Chat.tsx` | 透传 `runStatus` 给 MessageList |

## 技术方案

### 1. MessageList: 基于 runStatus 决定初始窗口

- 新增 prop `runStatus?: 'idle' | 'running' | 'failed' | 'suspended' | 'completed'`
- 切换会话 effect: `runStatus !== 'running'` → windowSize = messages.length, 否则 WINDOW_STEP
- runStatus 变化 effect: running → completed 时自动展开到全部

### 2. TurnGroup: defaultExpanded 透传

- 新增 prop `defaultExpanded?: boolean`
- `useState(defaultExpanded ?? false)` 替代硬编码 false

### 3. MessageList → TurnGroup 透传 defaultExpanded

- MessageList 根据 `runStatus !== 'running'` 计算 defaultExpanded 传给每个 TurnGroup

### 4. Chat.tsx 透传 runStatus

- `<MessageList runStatus={currentSession?.run_status} .../>`

## 实施步骤

- [x] 步骤 1: MessageList 新增 `runStatus` prop + 切换/状态变化 effect
- [x] 步骤 2: TurnGroup 新增 `defaultExpanded` prop
- [x] 步骤 3: MessageList 透传 defaultExpanded 给 TurnGroup
- [x] 步骤 4: Chat.tsx 透传 runStatus
- [x] 步骤 5: 更新测试 (15/15 通过, 含 4 个新增 R96 测试)

## 风险评估

- **性能**: 超长会话(>500 条)一次性渲染可能慢。实际场景大部分 <200 条，可接受
- **流式中断**: running → completed 状态变化时自动展开，无遗漏
- **回合折叠**: defaultExpanded 仅影响初始挂载，用户手动操作后不再受控

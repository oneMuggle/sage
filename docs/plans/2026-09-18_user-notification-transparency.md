# 2026-09-18 用户通知透明度增强方案

> 分支：`feat/user-notification-transparency`
> 状态：进行中

## 背景

分析发现以下"幕后操作"对用户不可见，违反 PHILOSOPHY.md §3"所有自动化行为可审计"承诺：

1. **技能自动激活（A16）**：用户消息匹配 `when_to_use` 后，技能 body 静默注入 system prompt，用户完全不知情
2. **技能显式调用（`/skill args`）**：slash 执行后无反馈 toast
3. **自动上下文压缩（M4）**：达到阈值后静默压缩，代码注释明确承认"本里程碑不向前端推送压缩状态"
4. **历史截断**：每请求组装时静默丢弃最早消息

## 目标

补齐这三类操作的用户可见性，遵循 `memory_used` 事件模式（已有先例）。

## 技术方案

### 事件设计

复用现有 `AgentEvent` 流事件机制（后端 → queue → 前端 SSE），新增两个 state：

| 新 state | 触发时机 | 载荷 | 前端展示 |
|---|---|---|---|
| `skill_activated` | `_skill_activation_block()` 返回非空 + 显式 `/skill` 调用 | `{skills: [{name, triggers_matched}]}` | 用户消息下方可展开 chip，类似 `memory_used` |
| `compact_triggered` | `_maybe_auto_compact_session()` 实际执行了压缩 | `{before, after, removed}` | 特殊系统消息气泡（非普通 assistant 气泡） |

### 修改范围

#### 后端

| 文件 | 改动 |
|------|------|
| `backend/application/services/chat_service.py` | `_skill_activation_block()` 改为返回 `(block, activated_names)`；`run_turn` 内推 `skill_activated` 事件到 entry queue |
| `backend/api/legacy_routes.py` | `_maybe_auto_compact_session()` 改为返回 `(removed_count, after)` 或 None；producer 内压缩后推 `compact_triggered` 事件到 entry queue；legacy path 也推 `skill_activated` |
| `backend/api/legacy_session_routes.py` | 手动 `/compact` 成功时推 `compact_triggered` 事件（保持现有 toast 不变，事件给其他客户端同步） |

#### 前端

| 文件 | 改动 |
|------|------|
| `src/shared/api/types.ts` | `AgentState` 联合加 `'skill_activated' \| 'compact_triggered'`；`AgentEvent` 加 `skills` / `compact` 字段；`Message` 加 `activated_skills` / `compact_info` 字段 |
| `src/shared/lib/agentStateMapping.ts` | 两个新 state 均返回 `null`（不进气泡占位） |
| `src/shared/lib/llmStream.ts` | reducer 处理 `skill_activated` → 写 `activated_skills` 到当前用户消息；处理 `compact_triggered` → 插入特殊系统消息 |
| `src/shared/lib/store.ts` | `Message` 类型加字段 |
| `src/widgets/chat/Message.tsx` | 用户消息下方渲染"⚡ N 个技能已激活"可展开 chip（复用 memory_used 的视觉样式） |
| `src/widgets/chat/CompactNotice.tsx` | **新建**：特殊系统消息组件，显示"📦 上下文已压缩：X → Y 条（移除 Z 条）"，带"查看归档"按钮 |
| `src/widgets/chat/ChatInput.tsx` | `/skill` 显式调用成功后加 `toast.info()` |
| `src/shared/lib/i18n/zh.ts` + `en.ts` | 新增翻译键 |

### 铁律

- 所有新事件 **fail-safe**：任何异常只跳过事件，绝不影响对话主流程
- 不改变现有 `memory_used` 行为
- 不改变压缩算法本身
- 不改变技能激活逻辑本身
- 仅"在已有操作后追加事件推送"

## 实施步骤

- [x] T1: `types.ts` 扩展 AgentState + AgentEvent + Message 类型
- [x] T2: `agentStateMapping.ts` 加新 state 处理
- [x] T3: 后端 `_skill_activation_block` 返回激活技能名列表
- [x] T4: 后端 `chat_service.py` 推 `skill_activated` 事件
- [x] T5: 后端 `_maybe_auto_compact_session` 返回压缩结果
- [x] T6: 后端 `legacy_routes.py` 推 `compact_triggered` + `skill_activated` 事件
- [x] T7: 前端 `useChat.ts` reducer 处理新事件（+ 补齐 memory_used 事件消费）
- [x] T8: `Message.tsx` 渲染 `compact_info` 系统消息
- [x] T9: `Message.tsx` 渲染 `skill_activated` chip
- [x] T10: `ChatInput.tsx` 加显式技能调用 toast
- [x] T11: i18n 翻译键补齐
- [x] T12: 单元测试

## 风险评估

| 风险 | 缓解 |
|------|------|
| 新事件干扰现有流处理 | 严格 fail-safe，所有推送 try/except 隔离 |
| `assertNever` 编译期检查 | 两个 switch 都加新 case，不会触发 |
| legacy 路径和 hex 路径行为不一致 | 两个路径都加事件推送 |

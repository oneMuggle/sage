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
| `src/features/send-message/useChat.ts` | SSE 处理：`skill_activated` → 写 `activated_skills` 到当前用户消息；`compact_triggered` → 插入特殊系统消息（含运行时载荷校验） |
| `src/shared/lib/store.ts` | `Message` 类型加字段；`mergeLoadedMessages` 按 `compact_info` 去重 |
| `src/widgets/chat/Message.tsx` | 用户消息下方渲染"⚡ N 个技能已激活"可展开 chip（复用 memory_used 的视觉样式）；续接行上方渲染压缩横幅 |
| `src/widgets/chat/CompactBanner.tsx` | **新建**：压缩通知横幅组件，文案由 `compact_info` 推导；系统消息与续接行共用 |
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
- [~] T4: 后端 `chat_service.py` 推 `skill_activated` 事件 —— **不适用**（见下方"修复轮次"说明）
- [x] T5: 后端 `_maybe_auto_compact_session` 返回压缩结果
- [x] T6: 后端 `legacy_routes.py` 推 `compact_triggered` + `skill_activated` 事件
- [x] T7: 前端 `useChat.ts` reducer 处理新事件（+ 补齐 memory_used 事件消费）
- [x] T8: `Message.tsx` 渲染 `compact_info` 系统消息
- [x] T9: `Message.tsx` 渲染 `skill_activated` chip
- [x] T10: `ChatInput.tsx` 加显式技能调用 toast
- [x] T11: i18n 翻译键补齐
- [x] T12: 单元测试

## 修复轮次（2026-09-18，合并 #1122 后安全审查）

初版合并后经安全审查代理复查，发现 6 项缺陷，本轮全部修复。

### 为何 T4 无法达成

hex `/chat` 端点（`hex_routes.py`）**非流式**；前端聊天流**完全**由
`legacy_routes.py` 供给。`chat_service.py` 里算出的 `activated_skill_names`
没有可投递的流，属死变量。故"hex 路径推 `skill_activated`"是**不可实现**的目标，
初版把它标成 `[x]` 不实。技能激活通知**只能**在 legacy 路径交付。

### 缺陷与修法

| # | 严重度 | 缺陷 | 修法 |
|---|--------|------|------|
| 1 | MEDIUM | legacy 路径技能激活**永不生效** —— `getattr(agent, "skills", None)` 恒 `None`（`SageAgent` 无该属性），`_skill_activation_block()` 立即返回空 | 改用 `await asyncio.to_thread(_get_skill_adapter)` 取真实技能端口 |
| 2 | MEDIUM | `triggers_matched` 恒为空数组 —— `_matches()` 把命中塌缩成 bool，生产端硬编码 `[]` | `_matches` 返回命中短语 tuple；`AutoActivationResult.matches`（`field(default_factory=dict)`）透传；前端 chip 展开可见 |
| 3 | MEDIUM | 前端不校验 SSE 载荷，伪造/畸形数据可进入气泡文案 | `useChat.ts` 加运行时窄化，不合规即丢弃事件并记 warn |
| 4 | LOW | 压缩计数口径不一（`after = before - removed + 1`，续接摘要占一行） | 三处统一为「before → after 条（removed 条历史已合并为摘要）」 |
| 5 | LOW | R38 三个字段不持久化 —— 刷新后 chip / 横幅全丢 | `messages` 表加 `activated_skills` / `compact_info` / `memory_refs` 三列（JSON-in-TEXT） |
| 6 | LOW | reattach 期间已发生的事件不再即时显示 | **由 #5 覆盖**：`finishReattach` → `loadMessages` 从 DB 恢复三者。数据不丢，仅即时性下降 |

### 持久化设计（#5）

- **写入端**：`activated_skills` 挂 user 行；`compact_info` 挂压缩续接 assistant 行；
  `memory_refs` 挂本轮**首条** assistant 行（与前端把 chip 挂首个流式气泡一致）。
- **迁移**：`CREATE TABLE` 直接含三列（新库即真实 schema）；老库走条件
  `ALTER TABLE ADD COLUMN`，并用 `except sqlite3.OperationalError` 兜底并发
  TOCTOU（两个 worktree 共用同一 `data/sage.db` 时后到者不再启动失败）。
- **读路径**：`Message.to_dict()` 解析为结构化值，形状不符降级 `None`（脏数据不炸整批）。
- **fork**：`_insert_forked_message_row` 同步复制三列，避免子会话丢通知。
- **去重**：实时合成通知（role=system）与持久化续接行（role=assistant）role/content
  均不同，原计数去重无法命中 → `mergeLoadedMessages` 增加按 `compact_info` 深度相等的剔除规则。
- **渲染**：新增 `CompactBanner` 组件，文案完全由 `compact_info` 推导（不读
  `message.content`，因续接行 content 是 LLM 摘要正文）；续接行保留 assistant 气泡
  （摘要正文 / Thinking / copy / regenerate / delete 全部保留），横幅置于其上方。

### 已知边界（不在本轮范围）

- `session_lineage.py` 的搬运路径同样丢 `activated_skills` 等新列（此前也丢
  `step_index` / `segment_id` / `subtype`）；整组修复会改动消息排序语义，单独跟进。
- hex 侧 `session_service.py::_message_to_dict` 未覆盖三列；`API_MODE` 默认
  `legacy`，生产无影响。

## 风险评估

| 风险 | 缓解 |
|------|------|
| 新事件干扰现有流处理 | 严格 fail-safe，所有推送 try/except 隔离 |
| `assertNever` 编译期检查 | 两个 switch 都加新 case，不会触发 |
| legacy 路径和 hex 路径行为不一致 | 两个路径都加事件推送 |

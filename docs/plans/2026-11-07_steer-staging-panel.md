# 插话暂存区（Steer Staging Panel）

## 背景与目标

Sage 的"插话"(steer) 目前在 UI 上表现为：发送后立刻以 user 气泡进入聊天区，无撤回入口、无消费反馈。实际体验与主流 AI 工具（DSH 等）的"输入框上方暂存、AI 接收前可撤回、接收后消失"不一致。

同时存在 P0 缺陷：`_ACTIVE_STREAMS` 在流开始时注册，但 `agent._run_loop_active` 要等编排模式分类（一次独立 LLM 调用，1–3 秒）之后才置 True。该窗口内插话会命中 409 `not_running`，前端静默降级为**排队**，本轮结束后队列自动发出——用户感知为"插话变成了下一轮的新消息"。

目标：

1. 插话进入输入框上方暂存区，AI 接收前可点 X 撤回。
2. AI 接收（消费）后暂存项消失，并按默认策略落入聊天历史（保留 `subtype='steering'` 徽标）。
3. 修复 409 窗口：窗口期插话缓存进队列，而不是降级为排队。
4. 流结束仍有未消费插话时，转为排队消息，避免丢字。

## 涉及文件

**后端**

- `backend/core/legacy/agent.py` — 队列结构化、注入/撤回/排空、消费事件、窗口标志
- `backend/core/legacy/agent_state.py` — 新增 `STEER_CONSUMED`
- `backend/api/legacy_chat_routes.py` — `/chat/steer` 返回 id、新增 `/chat/steer/cancel`、落库时机

**前端**

- `src/shared/api/types/chatAndEventTypes.ts` — `steer_consumed` 事件类型
- `src/shared/api/chatApi.ts` — `steer` 返回 messageId、新增 `cancelSteer`
- `src/features/send-message/chatStreamStore.ts` — 每会话 `pendingSteer`
- `src/features/send-message/useChat.ts` — 暂存/消费/流末转队列
- `src/widgets/chat/PendingSteerPanel.tsx` — 新增暂存面板
- `src/pages/Chat.tsx` — 挂载面板
- `src/shared/lib/i18n/locales/{zh,en}/chatSteerStaging.ts` — 文案（独立模块，避免 `chatAndSider.ts` 触碰架构棘轮行数上限）

**测试**

- `backend/tests/unit/test_chat_steer.py`
- `src/features/send-message/__tests__/useChat.delivery.test.ts`
- `src/features/send-message/__tests__/chatStreamStore.*.test.ts`
- `src/widgets/chat/__tests__/PendingSteerPanel.test.tsx`（新增）

## 技术方案

### 后端

1. `_pending_user_messages` 元素由 `str` 改为 `{"id": str, "text": str}`；新增 `_accepts_steer` 标志。
2. `inject_user_message(content, message_id=None) -> str | None`：判据从 `_run_loop_active` 改为 `_accepts_steer`；成功返回 id，失败返回 `None`。
3. `cancel_user_message(message_id) -> bool`：命中则从 deque 移除并返回 `True`，否则 `False`。
4. `_drain_pending_user_messages() -> list[dict]`：排空并返回 `{id, text}` 列表。
5. `run_loop` 迭代顶部排空后，若存在 id，yield `AgentEvent(state=STEER_CONSUMED, steer_info={"ids": [...], "messages": [...]})`，并由 `_persist_consumed_steers(items, session_id)` 在此刻落库（`subtype='steering'`）。
6. `/chat/steer` 返回 `{"ok": true, "message_id": "..."}`，不再在发送时落库。
7. 新增 `POST /chat/steer/cancel`：入参 `{stream_id, message_id}`，返回 `{removed: bool}`；stream 不存在 → 404。
8. `_accepts_steer` 生命周期：
   - 创建 agent 并注册 `_ACTIVE_STREAMS` 后置 `True`（分类之前）
   - run 结束 / 取消 / 异常 finally 中置 `False`
   - 未进入 `run_loop` 即失败的路径也要置 `False`
9. `AgentState` 增加 `STEER_CONSUMED`。

### 前端

1. `chatStreamStore` 每个 session slot 新增 `pendingSteer: PendingSteerItem[]`，类型 `{id: string; content: string; createdAt: number}`；新增 `addSteer` / `removeSteer` / `clearSteers`。
2. `chatApi.steer` 返回值由 `boolean` 改为 `{messageId: string} | null`；新增 `cancelSteer(streamId, messageId): Promise<boolean>`。
3. `useChat.deliverWhileBusy` 的 steer 分支：成功 → `addSteer`（不再 `echoSteering`）；失败仍回退 `enqueue`。
4. 事件分发：`evt.state === 'steer_consumed'` → 逐 id 移除暂存项 + `addMessage` 落聊天区（按 id 幂等，避免与撤回竞态重复）。
5. 流终止（`done` / `failed`）：剩余 `pendingSteer` 转为 `pendingQueue` 后清空，toast 提示"本轮已结束，插话转为排队"。
6. 新增 `PendingSteerPanel`：仅在 `pendingSteer.length > 0` 时渲染；每条显示截断内容 + X 撤回；撤回调用 `cancelSteer`，`removed=false` 时按"已送达"处理。
7. `Chat.tsx` 在 `PendingQueuePanel` 与 `ChatInput` 之间挂载。
8. i18n 新增 `chat.steer_pending_title`、`chat.steer_pending_hint`、`chat.steer_pending_cancel`（独立 `chatSteerStaging.ts` 模块）。

### 数据流

```
用户 Enter → useChat.deliverWhileBusy
  → chatApi.steer → { message_id }
  → store.addSteer                 暂存区出现 chip
  → (X) chatApi.cancelSteer        removed=true → 移除；false → 按已送达处理
  → run_loop 迭代边界 drain
  → 落库 + yield steer_consumed
  → 前端移除 chip + 落聊天区
```

## 实施步骤

- [x] 1. 后端：deque 结构化 + `inject_user_message` / `cancel_user_message` / `_drain_pending_user_messages`
- [x] 2. 后端：`STEER_CONSUMED` 事件 + 消费时落库
- [x] 3. 后端：`_accepts_steer` 窗口修复 + `/chat/steer/cancel` + `/chat/steer` 返回 id
- [x] 4. 前端：事件类型 + `chatApi`
- [x] 5. 前端：`chatStreamStore` 的 `pendingSteer`
- [x] 6. 前端：`useChat` 暂存 / 消费 / 流末转队列
- [x] 7. 前端：`PendingSteerPanel` + `Chat.tsx` 挂载 + i18n
- [x] 8. 测试：后端 cancel/consume/window，前端 store/delivery/面板
- [x] 9. 验证：ruff、pytest（19/19 + 关联 98/98）、vitest（1144/1144）、tsc、ipc:manifest（384 命令）
- [ ] 10. 提交 PR 并 cherry-pick 到 `release/win7`（py38 / pydantic 1.x 适配）

## 风险评估

- **竞态**：撤回与消费同刻发生 → cancel 返回 `false`，前端按"已送达"处理；聊天区按 id 去重。
- **编排模式**：`steerActiveOrchTask` 走 run-control 端点（非 `/chat/steer`），v1 不改；暂存区仅覆盖单 agent 路径。
- **持久化语义**：落库从"发送时"移到"消费时"；进程崩溃时未消费插话不落库（视为未送达，可接受）。
- **兼容性**：`chatApi.steer` 返回类型变更，需同步更新调用点与既有测试。
- **双分支**：win7 为 Python 3.8 / pydantic 1.x，cherry-pick 后需按分支环境验证。

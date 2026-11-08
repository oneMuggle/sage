# 插话暂存区（Steer Staging Panel）

> 面向开发者：把「AI 运行中发送的消息」从即时气泡改为可撤回暂存条，修复 409 窗口缺陷，并补充消费回执事件。
> 相关章节：[23 Chat 流式响应端到端](./23-chat-streaming.md)、[27 多 Agent 编排层](./27-multi-agent-orchestration.md)。

## 1. 概念分层

| 场景 | 路径 | 备注 |
| --- | --- | --- |
| 单 agent 运行中插话 | `POST /chat/steer` → `_pending_user_messages` → `STEER_CONSUMED` | 本章节范围 |
| 编排模式插话（`steerActiveOrchTask`） | run-control 端点 | v1 不改，暂存区不覆盖 |
| 空闲时发送 | `enqueueChat` 走排队路径 | 不变 |

## 2. 后端实现

### 2.1 数据结构（`backend/core/legacy/agent.py`）

```python
# 由 str 升级为 dict，携带 id
_pending_user_messages: deque[{"id": str, "text": str}]
_accepts_steer: bool  # 替代原先的 _run_loop_active 判定
```

| 方法 | 行为 |
| --- | --- |
| `begin_accept_steer()` | 打开窗口（在 `_ACTIVE_STREAMS` 注册之后、编排分类之前调用） |
| `end_accept_steer()` | 关闭窗口，清空队列 |
| `inject_user_message(content, message_id=None) -> Optional[str]` | 判据改为 `_accepts_steer`；成功返回 id，失败返回 `None` |
| `cancel_user_message(message_id) -> bool` | 命中则从 deque 过滤移除；用 `clear()+extend()` 原地重建，避免与并发 `drain()` 在旧 deque 上竞争 |
| `_drain_pending_user_messages() -> List[Dict]` | `popleft` 并规范化 `{id: str(item.get("id") or uuid4()), text: item["text"]}` |
| `_persist_consumed_steers(items, session_id)` | 逐条 `message_repo.save(DbMessage(..., subtype="steering", created_at=int(time.time())))` |

### 2.2 消费事件（`agent_state.py`）

`AgentState.STEER_CONSUMED = "steer_consumed"` 插入 `AWAITING_STEP_CONFIRM` 与 `DONE` 之间（状态总数变为 17）。`AgentEvent.steer_info: Optional[Dict]` 在 `to_dict()` 中非空时序列化。

`run_loop` 每次迭代顶部：

```python
_steer_items = self._drain_pending_user_messages()
if _steer_items:
    messages.extend(
        {"role": "user", "content": f"【用户补充】{item['text']}"}
        for item in _steer_items
    )
    self._persist_consumed_steers(_steer_items, session_id)
    yield AgentEvent(
        state=AgentState.STEER_CONSUMED, iteration=i,
        agent_id=self.agent_id,
        steer_info={"ids": [item["id"] for item in _steer_items]},
    )
```

### 2.3 API（`backend/api/legacy_chat_routes.py`）

| 方法 | 路径 | 返回 |
| --- | --- | --- |
| POST | `/api/v1/chat/steer` | `{"ok": true, "message_id": "<uuid>"}`；窗口关闭 → 409 `not_running`（不再降级为排队） |
| POST | `/api/v1/chat/steer/cancel` | `{"removed": bool}`；stream 不存在 → 404 `stream_not_found` |

pydantic v1 兼容模型：

```python
class CancelSteerRequest(BaseModel):
    stream_id: str
    message_id: str
```

### 2.4 409 窗口修复

旧逻辑：`_run_loop_active` 在编排分类完成后才置 True，窗口期 1–3 秒内 `inject_user_message` 返回 `None` → 前端静默降级为排队。

新逻辑：`_accepts_steer` 在 `_ACTIVE_STREAMS` 注册后立即置 True，覆盖整个窗口；分类结束不会改变语义。

## 3. 前端实现

### 3.1 状态（`chatStreamStore.ts`）

每会话 slot 新增 `pendingSteer: PendingSteerItem[]`，`PendingSteerItem = {id, content, createdAt}`。

| Action | 行为 |
| --- | --- |
| `addSteer(sessionId, item)` | 追加到 `pendingSteer` |
| `removeSteer(sessionId, id)` | 按 id 过滤 |
| `clearSteers(sessionId)` | 清空 |
| `takeAllSteers(sessionId)` | 返回当前数组并清空（流末转队列用） |

### 3.2 流转（`useChat.ts`）

| 触发 | 处理 |
| --- | --- |
| 忙碌中发送 | `chatApi.steer` 成功 → `addSteer`（不再 `echoSteering`）；失败 → `enqueueChat` 回退 |
| `steer_consumed` 事件 | 逐 id 调 `removeSteer` + `addMessage` 落聊天区（按 id 幂等，避免与撤回竞态重复） |
| 流结束 | `takeAllSteers` → 逐条 `enqueueChat`；剩余插话按队列顺序发出 |
| 用户点 X 撤回 | `cancelSteer(streamId, id)` → `removed=true` 移除；`removed=false` 按「已送达」处理 |

`steeringAnchorId()` 决定暂存条渲染锚点，确保面板位于 `PendingQueuePanel` 与 `ChatInput` 之间。

### 3.3 暂存面板（`PendingSteerPanel.tsx`）

- 仅 `pendingSteer.length > 0` 时渲染；
- 每条显示截断内容 + X 按钮；
- i18n 键独立在 `chatSteerStaging.ts`（避免 `chatAndSider.ts` 触碰 800 行架构棘轮）。

| 键 | 中文 |
| --- | --- |
| `chat.steer_pending_title` | 待生效 |
| `chat.steer_pending_hint` | AI 在下一个边界读取；点 X 可在送达前撤回 |
| `chat.steer_pending_cancel` | 撤回插话 |

### 3.4 数据流

```
用户 Enter → useChat.deliverWhileBusy
  → chatApi.steer → { message_id }
  → store.addSteer                 暂存区出现 chip
  → (X) chatApi.cancelSteer        removed=true → 移除；false → 按已送达处理
  → run_loop 迭代边界 drain
  → 落库 + yield steer_consumed
  → 前端移除 chip + 落聊天区
```

## 4. 测试

| 文件 | 覆盖 |
| --- | --- |
| `backend/tests/unit/test_chat_steer.py` | cancel/consume/window 共 19 例 |
| `backend/tests/unit/test_agent_state_transitions.py` | 17 状态顺序（含 steer_consumed） |
| `src/features/send-message/__tests__/useChat.delivery.test.ts` | 暂存/消费/流末转队列 |
| `src/widgets/chat/__tests__/PendingSteerPanel.test.tsx` | 面板渲染与撤回 |

## 5. 兼容与风险

| 风险 | 缓解 |
| --- | --- |
| 撤回与消费同时发生 | cancel 返回 `false`，前端按「已送达」处理；聊天区按 id 去重 |
| 持久化语义变更 | 落库从「发送时」移到「消费时」；进程崩溃时未消费插话不落库（视为未送达） |
| `chatApi.steer` 返回类型变更 | 调用点与既有测试同步更新 |
| win7 同步 | py38 / pydantic 1.x 通过 auto_sync + architecture-baseline 冲突解决落地（PR #2942） |

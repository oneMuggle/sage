# 上下文隔离：话题分段 + 滑动窗口 + 智能话题检测

> 日期：2026-09-17
> 状态：设计中
> 分支：`feat/context-isolation`

---

## 1. 背景与目标

### 问题

Sage 当前以 `session_id` 为上下文唯一边界。同一会话内切换话题时，旧话题的历史消息、WorkingMemory、会话摘要仍全部注入 LLM 请求，导致模型回答新话题时"串"到旧内容。

### 根因

1. **无话题分段**：历史消息是扁平列表，没有"话题分隔点"概念
2. **超大窗口不截断**：128k 模型的历史预算约 111k token，旧话题远未触及截断线
3. **记忆全量注入**：`MemoryManager.get_context(session_id)` 不区分话题段，旧话题提取的 facts 一并注入

### 目标

同一会话内支持话题隔离，让用户在切换话题时获得干净的上下文：

- **方案 A（显式分隔）**：用户可手动创建话题分隔点，分隔点前的消息不送入 LLM
- **方案 B（滑动窗口）**：全局设置"最大历史轮数"，超出部分即使 token 预算允许也截断
- **方案 C（智能检测）**：自动检测话题跳转，给出轻量提示并可选择性隔离

---

## 2. 核心概念：话题分段（Topic Segment）

```
┌─────────────────────────────────────────────┐
│              Session (session_id)            │
│                                              │
│  ┌────────────────────┐                      │
│  │ Segment 0 (旧话题)  │  ← 不参与 LLM 请求  │
│  │  消息 1~8           │                      │
│  └────── separator ────┘  ← 显式/自动分隔点   │
│  ┌────────────────────┐                      │
│  │ Segment 1 (当前)    │  ← 活跃段，送 LLM    │
│  │  消息 9~12          │                      │
│  └────────────────────┘                      │
└─────────────────────────────────────────────┘
```

- 每条消息新增 `segment_id`（整数，从 0 递增）
- 分隔点是一条特殊的 `system` 消息（`subtype=topic_separator`）
- 活跃段 = 最后一条分隔点之后的消息
- LLM 请求只包含活跃段内的历史

---

## 3. 数据层改动

### 3.1 messages 表新增字段

```sql
ALTER TABLE messages ADD COLUMN segment_id INTEGER DEFAULT 0;
ALTER TABLE messages ADD COLUMN subtype TEXT DEFAULT NULL;
```

- `segment_id`：`INTEGER`，默认 0。该消息属于第几个话题段
- `subtype`：`TEXT`，可选。分隔消息为 `topic_separator`，普通消息为 NULL

### 3.2 分隔消息格式

```python
{
    "role": "system",
    "content": "[上下文已在此处重置]",
    "subtype": "topic_separator",
    "segment_id": 1,
    "session_id": "...",
    "created_at": "2026-09-17T14:30:00Z"
}
```

### 3.3 MessageRepository 扩展

- `get_by_session(session_id, limit)` 返回时包含 `segment_id` 和 `subtype`
- 新增 `get_active_segment(session_id) -> List[Message]`：只返回活跃段的消息
- 新增 `advance_segment(session_id) -> int`：插入分隔消息，返回新 segment_id
- 新增 `retreat_segment(session_id) -> bool`：撤销最近一次自动分隔（方案 C 回退用）

---

## 4. 方案 A：显式分隔

### 4.1 前端交互

聊天输入框旁新增"新话题"按钮（图标：🔄 或分叉图标）：

- 点击后发送 `context_reset: true` 到后端
- 后端收到后先调用 `advance_segment(session_id)`，再处理当条消息
- 前端在聊天面板渲染分割线（旧消息仍可见可滚动）

### 4.2 后端 API 扩展

`ChatRequest` 新增字段：

```python
context_reset: bool = False  # 默认 False
```

`chat_stream_create` 处理逻辑：

```python
if data.context_reset:
    message_repo.advance_segment(data.session_id)
    memory_manager.clear_working_memory(data.session_id)
```

### 4.3 历史加载改动

`db_rows_to_history` 增加分段感知：

```python
def db_rows_to_history(rows, active_segment_only=True):
    if active_segment_only:
        # 从后往前找最后一条 separator
        separator_idx = -1
        for i in range(len(rows) - 1, -1, -1):
            if getattr(rows[i], 'subtype', None) == 'topic_separator':
                separator_idx = i
                break
        rows = rows[separator_idx + 1:]
    # 原有逻辑：过滤 role、strip reasoning_content 等
```

---

## 5. 方案 B：滑动窗口

### 5.1 全局设置项

`SettingsRepository` 新增 key：

```python
context_turn_limit: Optional[int] = None  # None = 无限制（仅受 token 预算）
```

设置页新增滑块：

- 选项：`无限制 / 3 轮 / 5 轮 / 8 轮 / 10 轮 / 15 轮 / 20 轮`
- 默认值：`无限制`
- 存储：`SettingsRepository().set("context_turn_limit", value)`

### 5.2 轮数截断逻辑

在 `history_context.py` 中新增：

```python
def apply_turn_limit(
    messages: List[Dict[str, str]],
    turn_limit: Optional[int],
) -> Tuple[List[Dict[str, str]], int]:
    """在 token 截断之后，进一步按轮数截断。一轮 = 1 user + 1 assistant。"""
    if turn_limit is None or turn_limit <= 0:
        return messages, 0
    user_count = 0
    cutoff = len(messages)
    for i in range(len(messages) - 1, -1, -1):
        if messages[i]["role"] == "user":
            user_count += 1
            if user_count > turn_limit:
                cutoff = i + 1
                break
    return messages[cutoff:], len(messages) - cutoff
```

### 5.3 管线集成

在 `build_request_messages` 内部，token 截断之后追加：

```python
# 1. Token 截断（现有）
messages, omitted = truncate_history(history, budget_tokens)

# 2. 轮数截断（新增）
turn_limit = settings_repo.get_int("context_turn_limit")
messages, turn_omitted = apply_turn_limit(messages, turn_limit)
omitted += turn_omitted
```

### 5.4 按会话动态设定的评估

当前阶段：仅全局设置。后续如需按会话动态调整，扩展点：
- Session 表加 `turn_limit_override` 字段
- `ChatRequest` 加 `turn_limit` 覆盖参数
- 优先级：请求级 > 会话级 > 全局

**本轮不实施**，留接口扩展点。

---

## 6. 方案 C：智能话题检测

### 6.1 检测时机

在 `chat_stream_create` 中，历史加载之后、请求组装之前：

```python
if not data.context_reset and settings_repo.get_bool("auto_topic_detection", True):
    is_new_topic = detect_topic_shift(data.message, recent_history)
    if is_new_topic:
        message_repo.advance_segment(data.session_id)
        emit_topic_shifted_event(stream_id)
```

### 6.2 检测算法（两层，轻量）

**第一层：关键词/规则快速通道（<1ms）**

```python
QUICK_NEW_TOPIC_SIGNALS = [
    "换个话题", "另一个问题", "新话题",
    "不相关的", "另外", "顺便问",
    "new topic", "unrelated question", "by the way", "switching to",
]
```

命中任一 → 直接判定为新话题。

**第二层：嵌入相似度 fallback（<50ms）**

- 用已有嵌入器（`backend/embeddings/`）计算当前用户输入与最近 3 条 assistant 回复的嵌入
- 取平均余弦相似度，低于阈值（默认 0.35）→ 判定为新话题
- 阈值可配置：`topic_detection_similarity_threshold`

**设计原则**：
- 保守判定：宁可漏判也不误判
- 可全局关闭：`auto_topic_detection` 设置项，默认开启

### 6.3 前端轻量提示

收到 `topic_shifted` SSE 事件后，聊天区顶部显示可关闭提示条：

```
┌──────────────────────────────────────────────────┐
│ 💡 检测到新话题，已自动隔离旧上下文  [恢复完整上下文] │
└──────────────────────────────────────────────────┘
```

- "恢复完整上下文" 按钮：调用 `retreat_segment` 撤销本次自动分隔
- 提示条 10 秒后自动消失

### 6.4 误判回退

- `retreat_segment`：将最近的分隔消息 `subtype` 改回 NULL，合并两个 segment
- 回退窗口：提示条可见期间（10 秒内）

---

## 7. 记忆层改动

### 7.1 WorkingMemory 按 segment 作用域

`backend/memory/working.py`：

- `WorkingMemory.add(entry, session_id, segment_id)` 增加 `segment_id` 参数
- `WorkingMemory.get_context(session_id, segment_id)` 只返回当前 segment 的 entries
- 新增 `WorkingMemory.clear_segment(session_id, segment_id)`

### 7.2 MemoryManager 适配

- `get_context(session_id, segment_id)` 增加 segment 参数（可选，向后兼容）
- `extract_and_store_memory` 传入当前 `segment_id`

### 7.3 会话摘要（SessionSummaryStore）

- 分隔点触发时，对旧 segment 生成一次性摘要并固化到 DB
- 新 segment 从空白开始累积摘要

---

## 8. 压缩（Compaction）与分段的交互

- `should_compact` 和 `compact_messages` 只作用于**活跃段**内的消息
- 旧 segment 的消息不参与压缩（已不可见于 LLM）
- 旧段消息保留在 DB 中供用户滚动查看

---

## 9. 文件改动清单

| 文件 | 改动类型 | 说明 |
|---|---|---|
| `backend/db/migrations/` | 新增 | messages 表新增 `segment_id`, `subtype` 字段 |
| `backend/db/message_repository.py` | 修改 | 新增 `advance_segment`, `retreat_segment`, `get_active_segment` |
| `backend/chat/history_context.py` | 修改 | `db_rows_to_history` 增加分段感知; 新增 `apply_turn_limit` |
| `backend/api/legacy_routes.py` | 修改 | `ChatRequest` 新增 `context_reset`; 分隔逻辑 |
| `backend/data/settings_repo.py` | 修改 | 新增 `context_turn_limit`, `auto_topic_detection`, `topic_detection_threshold` |
| `backend/memory/working.py` | 修改 | 增加 `segment_id` 维度 |
| `backend/memory/manager.py` | 修改 | `get_context` 增加 `segment_id` 参数 |
| `backend/chat/compaction.py` | 修改 | 压缩范围限制为活跃段 |
| `backend/chat/topic_detection.py` | 新增 | 轻量话题检测模块 |
| `src/shared/api/types.ts` | 修改 | `ChatConfig` 新增 `contextReset` |
| `src/shared/api/chatApi.ts` | 修改 | 传递 `contextReset` 标志 |
| `src/components/chat/` | 修改 | 分隔线 UI + 话题切换提示条 + 新话题按钮 |
| `src/components/settings/` | 修改 | 新增上下文设置项 |
| `electron/` | 修改 | IPC 桥接 `contextReset` 标志 |

---

## 10. 实施步骤

### Phase 1：数据层 + 方案 A（显式分隔）

- [ ] 1.1 数据库迁移：messages 表新增 `segment_id`, `subtype`
- [ ] 1.2 `MessageRepository` 新增 `advance_segment`, `retreat_segment`, `get_active_segment`
- [ ] 1.3 `ChatRequest` 新增 `context_reset` 字段
- [ ] 1.4 `chat_stream_create` 处理 `context_reset` 逻辑
- [ ] 1.5 `db_rows_to_history` 增加分段感知
- [ ] 1.6 前端：新话题按钮 + 分隔线 UI
- [ ] 1.7 单元测试：分段隔离的正确性

### Phase 2：方案 B（滑动窗口）

- [ ] 2.1 `SettingsRepository` 新增 `context_turn_limit` key
- [ ] 2.2 新增 `apply_turn_limit` 函数
- [ ] 2.3 管线集成：在 `truncate_history` 后追加轮数截断
- [ ] 2.4 前端设置页：轮数限制滑块
- [ ] 2.5 单元测试：轮数截断边界情况

### Phase 3：方案 C（智能话题检测）

- [ ] 3.1 新增 `backend/chat/topic_detection.py`
- [ ] 3.2 集成到 `chat_stream_create`
- [ ] 3.3 SSE 事件 `topic_shifted` 通知前端
- [ ] 3.4 前端：话题切换提示条 + "恢复完整上下文"按钮
- [ ] 3.5 记忆层适配：WorkingMemory + MemoryManager 增加 segment_id
- [ ] 3.6 单元测试：话题检测的规则通道 + 嵌入相似度

### Phase 4：压缩与集成

- [ ] 4.1 `compaction.py` 限制压缩范围为活跃段
- [ ] 4.2 集成测试：三层机制协同工作
- [ ] 4.3 E2E 测试：完整的用户场景

---

## 11. 风险与约束

| 风险 | 缓解措施 |
|---|---|
| 数据库迁移影响现有数据 | `segment_id` 默认 0，所有旧消息归入 Segment 0 |
| 话题检测误判 | 保守阈值 + 用户可撤销 + 可全局关闭 |
| 轮数限制过激导致丢失关键上下文 | 默认"无限制"，用户主动调小 |
| 记忆层改动影响面大 | `segment_id` 可选参数，旧调用方不传则行为不变 |
| 前端 UI 复杂度 | 分阶段交付，Phase 1 只交付按钮+分割线 |

---

## 12. 不在范围内

- ❌ 旧段消息的后台归档/清理
- ❌ 按会话动态设定轮数限制（留接口，不实施）
- ❌ 跨 segment 的 memory 搜索/引用
- ❌ 话题检测的 LLM 调用（用嵌入 + 规则，保持低延迟）

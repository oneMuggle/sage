# LLM 思考过程展示功能实施计划

## 背景与目标

### 为什么需要这个功能

当前 Sage 对话界面只展示 LLM 的最终回答内容，用户无法了解 AI 的推理过程。
现代 LLM（如 Claude、GPT-o1/o3、DeepSeek-R1）支持 `reasoning_content`/`thinking` 字段，
返回 AI 的思考过程。展示这一过程可以：

1. **增强透明度**：让用户理解 AI 是如何得出结论的
2. **建立信任**：可见的推理过程提升用户对回答的信心
3. **调试辅助**：当回答有问题时，思考过程有助于定位问题

### 目标

- 全链路支持 LLM thinking/reasoning 内容：后端解析 → 流式事件 → 前端渲染 → 数据库持久化
- 支持实时流式展示（逐 token 显示思考过程）
- UI 采用折叠面板，默认收起，点击展开查看完整思考过程
- 历史消息加载时仍可查看之前的 thinking 内容

---

## 涉及的文件与模块

### 后端 (Python)

| 文件 | 改动 |
|------|------|
| `backend/core/legacy/llm_client.py` | `LLMResponse` 增加 `reasoning_content` 字段，解析响应时提取 |
| `backend/core/legacy/agent_state.py` | `AgentState` 增加 `REASONING` 状态，`AgentEvent` 增加 `reasoning` 字段 |
| `backend/core/legacy/agent.py` | `run_loop()` yield reasoning 事件 |
| `backend/data/database.py` | 数据库迁移：messages 表加 `reasoning_content TEXT` 列 |
| `backend/data/session_repo.py` | `Message` dataclass 增加 `reasoning_content` 字段 |

### 前端 (TypeScript/React)

| 文件 | 改动 |
|------|------|
| `src/shared/lib/store.ts` | `Message` 类型增加 `reasoning_content?: string` |
| `src/shared/api/api.ts` | `AgentEvent` 类型增加 `reasoning?: string`，`AgentState` 增加 `'reasoning'` |
| `src/features/send-message/useChat.ts` | 处理 reasoning 事件，独立累积 thinking 内容 |
| `src/widgets/chat/Message.tsx` | 增加可折叠的 ThinkingPanel 组件 |

### 测试文件

| 文件 | 内容 |
|------|------|
| `backend/tests/unit/test_llm_client.py` | 测试 reasoning_content 解析 |
| `backend/tests/unit/test_agent_state.py` | 测试 AgentEvent 序列化 |
| `src/widgets/chat/__tests__/Message.test.tsx` | 测试 ThinkingPanel 渲染 |
| `src/features/send-message/__tests__/useChat.test.ts` | 测试 reasoning 事件处理 |

---

## 技术方案

### 1. LLM 响应解析

不同 LLM 提供商返回 thinking 内容的字段名不同：

| 提供商 | 字段名 | 示例 |
|--------|--------|------|
| Anthropic Claude | `reasoning_content` | Claude 3.5+ extended thinking |
| OpenAI o1/o3 | `reasoning` 或 `reasoning_content` | o1-preview, o3-mini |
| DeepSeek | `reasoning_content` | DeepSeek-R1 |
| 其他兼容 OpenAI 格式的 | `reasoning_content`（约定） | 大多数 |

**解析策略**：优先尝试 `reasoning_content`，再尝试 `reasoning`，都没有则为 `None`。

```python
# llm_client.py LLMResponse 新增
@dataclass
class LLMResponse:
    content: str = ""
    reasoning_content: str | None = None  # 新增
    model: str = ""
    # ... 其他字段不变

# chat() 方法解析
msg_data = choice.get("message", {})
content = msg_data.get("content", "")
# 提取 reasoning_content（多提供商兼容）
reasoning = msg_data.get("reasoning_content") or msg_data.get("reasoning")
```

### 2. Agent 事件流扩展

```python
# agent_state.py
class AgentState(str, Enum):
    IDLE = "idle"
    THINKING = "thinking"      # 已有：表示"LLM 正在思考"阶段
    REASONING = "reasoning"    # 新增：携带实际 reasoning 内容的 chunk
    CONTENT_DELTA = "content_delta"
    ACTING = "acting"
    OBSERVING = "observing"
    DONE = "done"
    FAILED = "failed"

@dataclass
class AgentEvent:
    state: AgentState
    iteration: int = 0
    content: str | None = None
    reasoning: str | None = None  # 新增：reasoning 内容
    # ... 其他字段不变
```

### 3. Agent 循环改造

```python
# agent.py run_loop() 改造
async def run_loop(self, messages, max_iterations=5, llm_config=None):
    for i in range(max_iterations):
        yield AgentEvent(state=AgentState.THINKING, iteration=i)
        
        response: LLMResponse = await self.llm_client.chat(messages)
        
        # 新增：如果有 reasoning 内容，yield reasoning 事件
        if response.reasoning_content:
            yield AgentEvent(
                state=AgentState.REASONING,
                iteration=i,
                reasoning=response.reasoning_content,
            )
        
        if not response.tool_calls:
            yield AgentEvent(
                state=AgentState.DONE,
                iteration=i,
                content=response.content,
            )
            return
        # ... 后续工具调用逻辑不变
```

### 4. 数据库迁移

```python
# database.py init_db() 添加迁移逻辑
# 对于已有数据库，检查并迁移
cursor.execute("PRAGMA table_info(messages)")
columns = [row["name"] for row in cursor.fetchall()]
if "reasoning_content" not in columns:
    cursor.execute("ALTER TABLE messages ADD COLUMN reasoning_content TEXT")
```

### 5. 前端类型扩展

```typescript
// store.ts Message 类型
export interface Message {
  id: string;
  session_id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  reasoning_content?: string;  // 新增
  created_at: number;
  // ... 其他字段不变
}

// api.ts AgentEvent 类型
export type AgentState =
  | 'idle' | 'thinking' | 'reasoning' | 'acting' | 'observing' 
  | 'content_delta' | 'done' | 'failed';  // reasoning 新增

export interface AgentEvent {
  state: AgentState;
  iteration: number;
  content?: string;
  reasoning?: string;  // 新增
  // ... 其他字段不变
}
```

### 6. 流式状态管理改造

```typescript
// useChat.ts 改造
const [streaming, setStreaming] = useState<{
  messageId: string;
  content: string;
  reasoning: string;  // 新增：累积的 reasoning 内容
  state: AgentEvent['state'] | null;
} | null>(null);

// onEvent 处理
onEvent: (evt) => {
  // reasoning 事件：累积到 reasoning 字段
  if (evt.state === 'reasoning' && evt.reasoning) {
    setStreaming(prev => 
      prev && prev.messageId === assistantId
        ? { ...prev, reasoning: prev.reasoning + evt.reasoning }
        : prev
    );
  }
  // content_delta / done 事件：累积到 content（原有逻辑不变）
  if (evt.content && evt.content.length > 0) {
    appendContent(evt.content);
  }
  // ... 其他逻辑不变
}
```

### 7. ThinkingPanel 组件设计

```tsx
// Message.tsx 新增 ThinkingPanel 组件
function ThinkingPanel({ reasoning }: { reasoning: string }) {
  const [isExpanded, setIsExpanded] = useState(false);
  
  return (
    <div className="mb-2 border border-border/50 rounded-radius-sm overflow-hidden">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-bg-subtle hover:bg-bg-hover transition-colors text-left"
      >
        <Brain className="w-4 h-4 text-primary" />
        <span className="text-xs font-medium text-text-secondary">
          思考过程 ({reasoning.length} 字)
        </span>
        <ChevronDown 
          className={`w-4 h-4 ml-auto transition-transform ${isExpanded ? 'rotate-180' : ''}`} 
        />
      </button>
      {isExpanded && (
        <div className="px-3 py-2 bg-bg-subtle/50 border-t border-border/50 text-xs text-text-secondary leading-relaxed max-h-60 overflow-y-auto">
          {reasoning}
        </div>
      )}
    </div>
  );
}

// 在 Message 组件中使用
{isAssistant && message.reasoning_content && (
  <ThinkingPanel reasoning={message.reasoning_content} />
)}
```

---

## 实施步骤

### Phase 1: 后端基础设施

- [ ] **步骤 1.1**: 修改 `LLMResponse`，增加 `reasoning_content` 字段
- [ ] **步骤 1.2**: 修改 `LLMClient.chat()`，解析响应中的 reasoning 内容
- [ ] **步骤 1.3**: 编写单元测试 `test_llm_client_reasoning.py`
- [ ] **步骤 1.4**: 修改 `AgentState`，增加 `REASONING` 枚举值
- [ ] **步骤 1.5**: 修改 `AgentEvent`，增加 `reasoning` 字段
- [ ] **步骤 1.6**: 修改 `SageAgent.run_loop()`，yield reasoning 事件

### Phase 2: 数据库持久化

- [ ] **步骤 2.1**: 修改 `database.py`，messages 表添加 `reasoning_content` 列
- [ ] **步骤 2.2**: 添加数据库迁移逻辑（兼容已有数据库）
- [ ] **步骤 2.3**: 修改 `session_repo.py` 的 `Message` dataclass
- [ ] **步骤 2.4**: 修改 `MessageRepository.save()` 保存 reasoning_content

### Phase 3: 前端类型与状态

- [ ] **步骤 3.1**: 修改 `store.ts` 的 `Message` 类型，增加 `reasoning_content`
- [ ] **步骤 3.2**: 修改 `api.ts` 的 `AgentState` 和 `AgentEvent` 类型
- [ ] **步骤 3.3**: 修改 `useChat.ts`，处理 reasoning 事件并累积内容

### Phase 4: UI 渲染

- [ ] **步骤 4.1**: 创建 `ThinkingPanel` 组件（折叠面板）
- [ ] **步骤 4.2**: 在 `Message.tsx` 中集成 ThinkingPanel
- [ ] **步骤 4.3**: 流式 overlay 扩展：streaming 状态增加 reasoning 字段
- [ ] **步骤 4.4**: 样式调整（Tailwind 类名）

### Phase 5: 测试与验证

- [ ] **步骤 5.1**: 编写后端单元测试（reasoning 解析、事件序列化）
- [ ] **步骤 5.2**: 编写前端单元测试（ThinkingPanel 渲染、useChat reasoning 处理）
- [ ] **步骤 5.3**: 端到端验证：启动应用，发送消息，检查 thinking 展示

---

## 风险评估与依赖

### 风险

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| LLM 提供商不返回 reasoning | thinking 面板不显示 | 代码做好空值判断，UI gracefully hide |
| 数据库迁移失败 | 已有数据丢失 | 迁移前备份，迁移逻辑做幂等检查 |
| 流式 reasoning 内容过长 | UI 卡顿 | 限制最大展示长度，虚拟滚动 |
| Electron IPC relay 不识别新字段 | reasoning 丢失 | 检查 relay.ts 是否需要适配 |

### 依赖

- 当前使用的 LLM API 必须支持返回 `reasoning_content` 或 `reasoning` 字段
- Electron relay (`electron/relay.ts`) 已支持 NDJSON 全字段转发（无需改动）

---

## 验证方法

### 后端验证

```bash
# 运行单元测试
conda activate sage-backend
pytest backend/tests/unit/test_llm_client.py -v
pytest backend/tests/unit/test_agent_state.py -v

# 启动后端，手动测试
python backend/main.py
curl http://127.0.0.1:8765/health
```

### 前端验证

```bash
# 运行测试
npm run test -- --testPathPattern="Message|useChat"

# 启动开发服务器
npm run dev

# 或使用 Tauri 桌面端
npm run tauri dev
```

### 端到端验证

1. 启动应用（后端 + 前端）
2. 配置支持 reasoning 的 LLM（如 Claude 3.5 + extended thinking）
3. 发送一条需要推理的消息（如数学题、逻辑问题）
4. 观察：
   - 流式过程中是否实时显示思考内容
   - 完成后 thinking 面板是否可折叠
   - 刷新页面后 thinking 内容是否仍可见
5. 检查数据库：`SELECT reasoning_content FROM messages WHERE ...`

---

## 关键文件路径汇总

### 需要修改的文件

```
backend/core/legacy/llm_client.py
backend/core/legacy/agent_state.py
backend/core/legacy/agent.py
backend/data/database.py
backend/data/session_repo.py
src/shared/lib/store.ts
src/shared/api/api.ts
src/features/send-message/useChat.ts
src/widgets/chat/Message.tsx
```

### 需要新建的测试文件

```
backend/tests/unit/test_llm_client_reasoning.py
src/widgets/chat/__tests__/ThinkingPanel.test.tsx
```

---

## 计划文档位置

本计划文档应保存到项目：`docs/plans/2026-06-17_llm-thinking-display.md`

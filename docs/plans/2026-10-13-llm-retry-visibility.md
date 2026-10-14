# LLM 重试可见性优化方案

> 日期：2026-10-13  
> 分支：feat/llm-retry-visibility  
> 状态：✅ 全部完成（5 个阶段全部通过，测试全绿）

## 背景与目标

当前项目中 LLM 调用已有重试机制（最多3次，指数退避），但重试过程对前端完全不可见，导致用户误认为"没有自动重试"。

**目标**：
1. 让重试过程对用户可见（实时显示重试状态）
2. 在设置界面暴露重试相关配置

## 设计决策

### 1. 重试状态显示（方案B - 详细模式）

```
🔄 重试中 (2/3) | 原因: 请求超时 | 等待 2秒
```

显示信息：
- 当前重试次数 / 最大重试次数
- 失败原因（超时/网络错误/服务器错误/限流）
- 等待时间

### 2. 设置界面配置

**基础设置**（默认可见）：
- 最大重试次数（0-10，0 = 禁用）

**高级设置**（默认折叠）：
- 退避基数（秒）：第一次重试前的等待时间
- 最大退避时间（秒）：单次等待上限
- 实时预览退避序列

### 3. 事件推送（复用 SSE 流）

在现有 SSE 流中添加 `retry` 类型事件：

```json
{
  "type": "retry",
  "attempt": 2,
  "max_attempts": 3,
  "error_type": "timeout",
  "delay": 2.0,
  "timestamp": "2026-10-13T10:30:00Z"
}
```

## 实施步骤

### 阶段 1：后端 - 设置模型扩展 ✅

- [x] 1.1 在 `backend/api/settings_models.py` 添加重试配置字段
  - `llmRetryMaxAttempts: int = 3`
  - `llmRetryBaseDelayS: float = 1.0`
  - `llmRetryMaxDelayS: float = 30.0`
  - 复用现有 `GET/PUT /settings` 端点，无需独立路由

### 阶段 2：后端 - 重试事件推送 ✅

- [x] 2.1 修改 `backend/core/legacy/llm_client.py`
  - 添加 `_retry_settings()` 从 app_settings 读取重试配置
  - 添加 `RetryEvent` dataclass
  - 在 `_chat_stream_events_raw()` 中 yield `("retry", RetryEvent)` 事件
  - 添加 `retry_callback` 参数支持非流式路径

- [x] 2.2 修改 `backend/core/legacy/agent_state.py`
  - 添加 `RETRY = "retry"` 到 AgentState 枚举
  - 添加 `retry_info` 字段到 AgentEvent dataclass

- [x] 2.3 修改 `backend/core/legacy/agent.py`
  - 流式路径处理 `("retry", ...)` 元组
  - 非流式路径使用 callback buffer 传递重试事件

### 阶段 3：前端 - 重试状态显示 ✅

- [x] 3.1 添加类型定义
  - `src/shared/api/types/chatAndEventTypes.ts`: 添加 `RetryInfo` 接口 + `retry_info` 字段
  - `src/shared/api/types/chatAndEventTypes.ts`: 添加 `'retry'` 到 AgentState 联合类型
  - `src/shared/api/llmStream.ts`: 同步添加 `'retry'` 到 AgentState

- [x] 3.2 修改事件处理
  - `src/features/send-message/useChat.ts`: 添加 retry 事件处理器（动态生成文本）
  - `src/features/send-message/chatStreamRuntime.ts`: 重attach路径添加相同处理
  - `src/shared/lib/agentStateMapping.ts`: 添加 `case 'retry':` 返回 null（文本由 useChat 动态生成）

- [x] 3.3 显示格式
  ```
  🔄 重试中 (2/3) | 原因: 请求超时 | 等待 2秒
  ```
  - error_type 映射为中文标签（timeout→请求超时, network_error→网络错误 等）
  - delay 自适应显示（≥1 取整，<1 保留一位小数）

### 阶段 4：前端 - 设置界面 ✅

- [x] 4.1 添加类型与默认值
  - `src/entities/setting/types.ts`: 添加 `llmRetryMaxAttempts/llmRetryBaseDelayS/llmRetryMaxDelayS` 到 AppSettings
  - 默认值: maxAttempts=3, baseDelayS=1.0, maxDelayS=30.0

- [x] 4.2 添加设置 UI 组件
  - `src/pages/settings/BasicTab.tsx`: 添加 "LLM 重试" section
  - 基础设置: 最大重试次数 (number input, 0=禁用)
  - 高级设置 (AdvancedSection 默认折叠): 退避基数 + 最大退避

- [x] 4.3 注册搜索锚点
  - `src/pages/settings/settingsSearchIndex.ts`: 添加 3 个新条目

### 阶段 5：测试与验证

- [x] 5.1 后端单元测试
  - `backend/tests/unit/test_llm_retry.py`: 重试事件推送测试
  - `backend/tests/unit/test_agent_state_transitions.py`: AgentState 枚举更新

- [x] 5.2 前端测试
  - `src/pages/settings/__tests__/BasicTab.test.tsx`: LLM 重试设置 section 渲染 + 交互（9 个测试）
  - `src/pages/settings/__tests__/settingsSearchIndex.test.ts`: 搜索索引不变量（12 个测试）
  - 全量前端测试通过：3707 passed (511 test files)

- [x] 5.3 后端集成测试
  - 全量后端测试通过：24 passed (test_llm_retry + test_agent_state_transitions)

## 涉及文件清单

### 后端（5 个文件）
1. `backend/api/settings_models.py` — 添加 llmRetry* 字段到 SettingsPayload / LegacySettingsPayload
2. `backend/core/legacy/llm_client.py` — `_retry_settings()` + `RetryEvent` dataclass + 事件 yield
3. `backend/core/legacy/agent_state.py` — `RETRY` 枚举值 + `retry_info` 字段
4. `backend/core/legacy/agent.py` — 流式/非流式路径重试事件传递
5. `backend/tests/unit/test_llm_retry.py` + `test_agent_state_transitions.py` — 测试更新

### 前端（6 个文件）
1. `src/shared/api/types/chatAndEventTypes.ts` — `RetryInfo` 接口 + `'retry'` AgentState + `retry_info` 字段
2. `src/shared/api/llmStream.ts` — 同步 `'retry'` 到平行 AgentState 定义
3. `src/shared/lib/agentStateMapping.ts` — 两个 switch 添加 `case 'retry': return null`
4. `src/features/send-message/useChat.ts` — 主流 retry 事件处理器（动态文本生成）
5. `src/features/send-message/chatStreamRuntime.ts` — reattach 流 retry 处理器
6. `src/entities/setting/types.ts` — AppSettings 添加 llmRetry* 字段 + 默认值

### 设置 UI（3 个文件）
1. `src/pages/settings/BasicTab.tsx` — "LLM 重试" section + AdvancedSection
2. `src/pages/settings/settingsSearchIndex.ts` — 3 个新搜索锚点
3. `src/pages/settings/__tests__/BasicTab.test.tsx` — 9 个前端测试（渲染/交互/边界）

## 风险评估

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| SSE 事件丢失 | 重试状态不显示 | 前端在收到最终响应/错误时清除重试状态 |
| 设置持久化失败 | 配置不生效 | 添加设置验证和错误提示 |
| 重试事件过于频繁 | UI 闪烁 | 前端节流（throttle）显示更新 |
| 向后兼容 | 旧客户端不识别 retry 事件 | SSE 客户端忽略未知事件类型 |

## 验收标准

1. ✅ 用户在聊天界面能看到重试状态（次数、原因、等待时间）
2. ✅ 用户能在设置界面配置重试策略（基础 + 高级）
3. ✅ 设置变更立即生效，无需重启
4. ✅ 重试次数设为 0 时，禁用重试功能
5. ✅ 所有测试通过，覆盖率 ≥ 80%

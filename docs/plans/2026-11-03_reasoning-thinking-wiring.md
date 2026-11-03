# 思考过程参数透传（reasoningEffort / thinkingBudget）

> 状态：进行中
> 分支：`feat/reasoning-thinking-wiring`（基于 `release/win7`）
> 创建：2026-11-03

## 背景与目标

用户反馈：在 win7 安装包中使用非流式输出时看不到思考过程。

经过诊断（见 `.worktrees/diag-win7-reasoning/`）发现：

- **后端链路完整**：`legacy_routes.py` → `llm_client.py` 已正确接收并注入 `reasoning_effort` / `thinking_budget` 到上游请求体；producer 也正确将 `AgentState.REASONING` 切成 `reasoning_delta` + `reasoning_final` 上 wire 并落库。
- **前端断链**：`chatApi.ts:139-140` 始终发送 `reasoningEffort: null` / `thinkingBudget: null`，因为：
  1. `EndpointConfig` 没有这两个字段
  2. `DEFAULT_ENDPOINT` 没有默认值
  3. `storage.ts` 的 `ENDPOINT_KEYS` 白名单没有它们（会被 `sanitizeForBackend` 静默丢弃）
  4. `useChat.ts` 构造 `ChatConfig` 时没有从 endpoint 读取
  5. 设置注册表没有 `reasoning_effort` / `thinking_budget` 键

**根因**：上游模型从未被请求进入思考模式（参数全是 null），所以不会产生 `reasoning_content`，前端没有东西可显示。

**目标**：把 `reasoningEffort` / `thinkingBudget` 作为 per-endpoint 配置暴露出来，让用户可以在端点编辑器里配置，并完整透传到后端。

## 涉及的文件与模块

### 前端

| 文件 | 改动 |
|------|------|
| `src/entities/setting/types.ts` | `EndpointConfig` 增加 `reasoningEffort` / `thinkingBudget`；`DEFAULT_ENDPOINT` 增加默认值 |
| `src/entities/setting/storage.ts` | `ENDPOINT_KEYS` 白名单加入 `reasoningEffort` / `thinkingBudget` |
| `src/pages/settings/EndpointsTab.tsx` | 表单新增 reasoningEffort select + thinkingBudget number input |
| `src/shared/lib/i18n/locales/{zh,en}/settingsUi.ts` | 新增字段标签 / 选项 / 提示文案 |
| `src/features/send-message/useChat.ts` | ChatConfig 构造读取 endpoint 的 reasoningEffort / thinkingBudget |
| `src/shared/api/types/chatAndEventTypes.ts` | 无需改动（`ChatConfig` 已有这两个可选字段） |

### 后端

| 文件 | 改动 |
|------|------|
| `backend/data/settings_canonicalizer.py` | `LEGAL_ENDPOINT_KEYS` 加两键；`ALIASES` 加 snake 别名；新增 `validate_reasoning_effort` / `validate_thinking_budget`；`validate_endpoint_payload` 调用之；`classify_settings_validation_error` 分类 |
| `backend/api/settings_models.py` | `EndpointPayload` 加两个 Optional 字段 |
| `backend/tools/config_tool.py` | `_ALLOWED_ENDPOINT_FIELDS` 加两键 |
| `backend/tests/contract/test_settings_schema_parity.py` | 端点键集期望 9 → 11 字段 |
| `backend/api/legacy_routes.py` | 无需改动（已正确接收） |
| `backend/core/legacy/llm_client.py` | 无需改动（已正确注入请求体） |

> **后端不可省略**：`strip_unknown_fields` 会按 `LEGAL_ENDPOINT_KEYS` 剥离未知端点字段，
> `validate_settings_shape` 对未知端点字段直接报 400。后端不加白名单 →
> 前端保存端点配置 400（且 `saveSettings` 的 catch 静默吞掉，用户看到"改了没生效"）。

## 技术方案

### Per-endpoint 配置
不同端点（OpenAI o1 vs Anthropic vs DeepSeek）使用不同的参数名和值域，所以把
`reasoningEffort` / `thinkingBudget` 放在 `EndpointConfig` 上比全局更合适。

- `reasoningEffort`: `'low' | 'medium' | 'high' | null` — 对应 OpenAI `reasoning_effort`
- `thinkingBudget`: `number | null` — 对应 Anthropic `thinking.budget_tokens` / DeepSeek `thinking_budget`

### 自动检测（可选增强，本次不实现）
根据 modelId 启发式推断默认值（o1/o3/gpt-5/deepseek-reasoner → `medium`）。
留作后续增强。

### 数据流
```
用户配置 EndpointsTab → EndpointConfig.reasoningEffort/thinkingBudget
  → localStorage (endpoints[])
  → sanitizeForBackend 白名单放行
  → 后端 /api/v1/settings 保存
  → useChat 读取 chatEndpoint → 填入 ChatConfig.reasoningEffort/thinkingBudget
  → chatApi.chatStream invoke body
  → Electron relay camelToSnake → 后端 legacy_routes.py
  → llm_config.reasoning_effort / thinking_budget
  → LLMConfig → 上游请求体
```

## 实施步骤

- [x] M1: `EndpointConfig` 类型 + `DEFAULT_ENDPOINT` + `ENDPOINT_KEYS` 白名单
- [x] M2: 后端 `LEGAL_ENDPOINT_KEYS` + `ALIASES` + 值校验器 + `EndpointPayload` + `config_tool` 白名单
- [x] M3: `EndpointsTab.tsx` 表单增加 reasoningEffort select + thinkingBudget input（含中英文案）
- [x] M4: `useChat.ts` ChatConfig 构造读取 endpoint 字段
- [x] M5: 集成测试验证端到端透传
- [ ] M6: commit + push → PR → CI 绿 → cherry-pick 到 main

### 关键设计决策

1. **per-endpoint 而非全局**：不同上游（OpenAI o1/o3/5 vs Gemini 2.5）参数名与值域不同，
   挂在 `EndpointConfig` 上更贴合。
2. **值域语义**
   - `reasoningEffort`: `'low' | 'medium' | 'high' | null` → OpenAI `reasoning_effort`
   - `thinkingBudget`: `number | null` → Gemini `thinking_budget`
     - `null` = 不发送该键（上游用默认思考预算）
     - `0` = 显式关闭思考
     - `N > 0` = token 上限
     - `-1` = 动态预算（与 `LLMConfig.thinking_budget` 语义一致，UI 不产出）
3. **relay snake 往返**：Electron `camelToSnakeKeys` 会把端点内 camelCase 键整体转 snake，
   后端 `ALIASES` 必须登记 `reasoning_effort` / `thinking_budget`，否则翻不回 camel → 400。
   契约测试 `test_legal_keys_survive_relay_snake_roundtrip` 会机械拦截这类遗漏。

## 风险评估

1. **Pydantic v1/v2 差异**：`EndpointPayload` 两个字段都是 `Optional[...] = None`，
   v1/v2 行为一致，无需条件分支。
2. **cherry-pick 到 main**：前端 + 后端 8 个文件两分支高度一致，冲突概率低。
3. **向后兼容**：新增字段都是 optional，旧 endpoint 配置缺字段 → `null` → 行为不变
   （不下发该键）。
4. **sanitizeForBackend / strip_unknown_fields 双重陷阱**：前端 `ENDPOINT_KEYS` 与后端
   `LEGAL_ENDPOINT_KEYS` **都**要加，漏任一侧字段都会被静默丢弃（前端）或 400（后端）。
5. **契约测试**：端点键集硬编码在 `test_settings_schema_parity.py`，新增字段必须同步改，
   否则 CI 立刻红。

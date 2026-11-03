# 端点思考参数透传（reasoningEffort / thinkingBudget）

> 日期：2026-11-03
> 分支：main + release/win7（两分支同编号）
> 方案：per-endpoint 配置 + 前端/后端双白名单 + Electron relay snake 往返
> 关联：§125 思考过程展示档位（本参数决定上游是否产出思考内容，§125 决定前端如何渲染）

## 1. 定位与目标

Sage 支持在**端点级别**配置上游模型的思考参数，让不同端点（OpenAI o1/o3、Anthropic、
DeepSeek、Gemini 2.5）分别使用各自合适的推理强度与思考预算。

| 参数 | 类型 | 上游映射 | 说明 |
| --- | --- | --- | --- |
| `reasoningEffort` | `'low' \| 'medium' \| 'high' \| null` | OpenAI `reasoning_effort` | 推理强度档位 |
| `thinkingBudget` | `number \| null` | Anthropic `thinking.budget_tokens` / DeepSeek `thinking_budget` / Gemini `thinking_budget` | 思考 token 上限 |

### 1.1 背景与根因

用户反馈 win7 非流式输出看不到思考过程。诊断结论：**后端链路完整**
（`legacy_routes.py` → `llm_client.py` 已正确把参数注入上游请求体，producer 也正确把
`AgentState.REASONING` 切成 `reasoning_delta` / `reasoning_final` 上 wire 并落库），
**断点在前端**——`chatApi` 始终发送 `reasoningEffort: null` / `thinkingBudget: null`，
因为 5 处前端配置缺字段：

1. `EndpointConfig` 没有这两个字段
2. `DEFAULT_ENDPOINT` 没有默认值
3. `storage.ts` 的 `ENDPOINT_KEYS` 白名单没有它们（被 `sanitizeForBackend` 静默丢弃）
4. `useChat.ts` 构造 `ChatConfig` 时没有从 endpoint 读取
5. 设置注册表没有对应键

上游模型从未被请求进入思考模式 → 不产生 `reasoning_content` → 前端无内容可显示。

## 2. 数据流

```
EndpointsTab 表单
  → EndpointConfig.reasoningEffort / thinkingBudget
  → localStorage (endpoints[])
  → storage.ts ENDPOINT_KEYS 白名单放行（sanitizeForBackend）
  → 后端 /api/v1/settings（LEGAL_ENDPOINT_KEYS + ALIASES + 校验器）
  → useChat 读取 chatEndpoint → ChatConfig
  → chatApi.chatStream invoke body
  → Electron relay camelToSnake
  → backend/api/legacy_routes.py
  → llm_config.reasoning_effort / thinking_budget
  → LLMConfig → 上游请求体
```

## 3. 文件清单

### 3.1 前端

| 文件 | 职责 |
| --- | --- |
| `src/entities/setting/types.ts` | `EndpointConfig` 增加两个可选字段；`DEFAULT_ENDPOINT` 默认 `null` |
| `src/entities/setting/storage.ts` | `ENDPOINT_KEYS` 白名单加入两键 |
| `src/pages/settings/EndpointsTab.tsx` | 表单：reasoningEffort select + thinkingBudget number input |
| `src/shared/lib/i18n/locales/{zh,en}/settingsUi.ts` | 字段标签 / 选项 / 提示文案 |
| `src/features/send-message/useChat.ts` | 构造 `ChatConfig` 时从 endpoint 读取两字段 |

### 3.2 后端

| 文件 | 职责 |
| --- | --- |
| `backend/data/settings_canonicalizer.py` | `LEGAL_ENDPOINT_KEYS` 加两键；`ALIASES` 加 snake 别名；`validate_reasoning_effort` / `validate_thinking_budget`；`classify_settings_validation_error` 分类 |
| `backend/api/settings_models.py` | `EndpointPayload` 加两个 Optional 字段 |
| `backend/tools/config_tool.py` | `_ALLOWED_ENDPOINT_FIELDS` 加两键 |
| `backend/tests/contract/test_settings_schema_parity.py` | 端点键集期望 9 → 11 字段 |

`legacy_routes.py` 与 `llm_client.py` **无需改动**（原本已正确接收与注入）。

## 4. 值域语义

- `reasoningEffort`
  - `null` → 不下发 `reasoning_effort`
  - `'low' | 'medium' | 'high'` → 原样下发
- `thinkingBudget`
  - `null` → 不发送该键（上游使用默认思考预算）
  - `0` → 显式关闭思考（Gemini `thinking_budget=0` 语义）
  - `N > 0` → 思考 token 上限
  - `-1` → 动态预算（与 `LLMConfig.thinking_budget` 语义一致，UI 不产出该值）

空输入框在 UI 层归一为 `null`，不是 `0`——避免"清空输入框"意外关闭思考。

## 5. 关键约束

### 5.1 双白名单陷阱（决定性）

字段必须**同时**加进两侧白名单：

| 侧 | 白名单 | 漏加的后果 |
| --- | --- | --- |
| 前端 | `storage.ts` `ENDPOINT_KEYS`（`sanitizeForBackend`） | 静默丢弃，保存后字段消失 |
| 后端 | `settings_canonicalizer.py` `LEGAL_ENDPOINT_KEYS` | `validate_settings_shape` 直接 400，且前端 `saveSettings` 的 catch 静默吞掉 → 用户看到「改了没生效」 |

### 5.2 Electron relay snake 往返

Electron relay 的 `camelToSnakeKeys` 会把端点内 camelCase 键整体转为 snake。后端
`ALIASES` 必须登记 `reasoning_effort` / `thinking_budget` 才能翻回 camel，否则 400。
契约测试 `test_legal_keys_survive_relay_snake_roundtrip` 机械拦截此类遗漏。

### 5.3 契约测试

端点键集硬编码在 `test_settings_schema_parity.py`。新增端点字段必须同步更新期望值，
否则 CI 立即失败——这是刻意的反漂移设计。

### 5.4 向后兼容

两个字段均为 optional，旧端点配置缺字段 → `null` → 不下发 → 行为与改造前一致。

## 6. 测试

| 测试 | 覆盖 |
| --- | --- |
| `backend/tests/unit/test_reasoning_params.py` | canonicalizer 白名单/别名/校验器 + 透传 |
| `src/entities/setting/__tests__/reasoningParams.test.ts` | 前端 `sanitizeForBackend` 白名单放行 |
| `src/features/send-message/__tests__/useChat.reasoning.test.ts` | `ChatConfig` 构造从 endpoint 取值 |
| `backend/tests/contract/test_settings_schema_parity.py` | 端点键集一致性（9 → 11）+ snake 往返 |

## 7. 实施记录

- win7 PR #2831（squash `19800d4aa` → `release/win7`）
- main PR #2834（squash `25fb7b6fe` → `main`，cherry-pick 同步）
- 两分支适配差异：类型注解风格（`Optional[...]` vs `str | None`）；main 侧主 chunk 增长
  触发 bundle 预算棘轮上调至 1.85MB（详见 `scripts/check-bundle-size.mjs` 注释）；
  win7 侧实测未超限，预算保持不动。

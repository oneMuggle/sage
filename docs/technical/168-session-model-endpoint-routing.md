# 168 · 会话模型与端点路由

会话级模型覆盖（model override）允许每个会话锁定自己的模型。本文说明为什么「只换模型名」在多端点配置下必然出错，以及前端 `useChat` 与后端 `llm_factory` 各自如何完成「模型 + 凭据」的成对路由。

## 1. 背景与问题现象

会话级模型覆盖由 `SessionModelPicker` 写入，存放在 `preferences` 表的 KV 项 `session_model_overrides` 中，结构是 JSON 映射 `{session_id: model_id}`。它是**只覆盖模型名**的设计：请求发往哪个端点，由全局 `modelSelections.chatModel.endpointId` 决定。

单端点配置下这个设计是成立的——反正只有一个端点，模型和凭据天然一致。一旦配置了多个端点，就出现下面的失败链：

```
会话选择 MiniMax-M3.1-Flash（该模型属于 MiniMax 端点）
        │
请求仍带全局 DeepSeek 端点的凭据（api_key / base_url）
        │
DeepSeek 上游不认识 MiniMax 模型 → HTTP 502（前端表现为持续重试）
```

典型症状：

- 某个会话固定失败并反复重试（上游 502），新建会话或把模型切回全局值才恢复；
- 「端点测试」页正常——它直接用该端点自己的凭据发请求，从不经过会话覆盖；
- 后端日志出现类似 `producer LLM config: model=MiniMax-M3.1-Flash`，但 `base_url` 仍是另一个厂商的地址。

根因不是模型名没生效，而是**模型与凭据没有一起切**。

## 2. 根因：模型与凭据必须成对路由

一个「可用的 LLM 请求」是四元组，四项必须同属一个端点：

| 字段 | 权威来源 | 说明 |
| --- | --- | --- |
| `model` | 会话覆盖 / profile / 全局选择 | 上游模型 id |
| `api_key` | 端点 `EndpointConfig.apiKey` | 本地 `ollama` / `openai-compatible` 端点允许为空串 |
| `base_url` | 端点 `EndpointConfig.baseUrl` | 上游地址 |
| `provider` | 端点 `protocol`（后端）/ URL 启发式（前端） | `openai-compatible` → `custom`；`ollama` / `anthropic` / `gemini` 各自对应 |

旧实现把 `model` 和其余三项拆成两个独立决策：

- **前端**：`useChat` 先用 `resolveEndpoint(modelSelections.chatModel, endpoints)` 取凭据，再单独往 `ChatConfig` 里写 `model`；
- **后端**：`load_llm_config_for_chat` 用 `load_llm_config_from_settings()` 取全局端点凭据，再把 `model` 换成会话覆盖值。

只要覆盖模型属于另一个端点，这个四元组就被拆散。代码里把它固化成了一句注释——`SessionModelPicker.tsx` 头部的「只切模型不改端点（端点恒取全局选择）」。多端点场景下这个假设不成立：切换模型必须连带切换凭据。

## 3. 端到端链路

### 3.1 存储形态：只存 model id，不存 endpoint id

| 层 | 位置 | 行为 |
| --- | --- | --- |
| 后端路由 | `backend/api/legacy_session_routes.py` | `GET /api/v1/sessions/{id}/model` 返回 `{"session_id", "model"}`；`PUT` 接收 `SessionModelOverride{model: str}`，空串表示清除 |
| 持久化 | `SettingsRepository`（`preferences` 表 KV） | 键 `session_model_overrides`，值为 `json.dumps({session_id: model_id})` |
| 读取 | `llm_factory.load_session_model_overrides()` | 任何异常返回空 dict；只保留非空 `str → 非空 str` 的条目，畸形条目静默丢弃 |
| IPC | `electron/commandRoutes/sessions.ts` | `session_get_model` / `session_set_model` 映射到上述 REST 路径 |
| 前端 API | `src/shared/api/sessionApi.ts` | `getModelOverride(sessionId): Promise<string \| null>` / `setModelOverride(...)`；写成功后广播 `SESSION_MODEL_OVERRIDE_EVENT` |

关键设计：**存的只是模型 id**。端点不落库，而是在每次发请求时用 `app_settings.endpoints[].discoveredModels[].id` 反查。这样端点被删除、改地址或重新发现模型后，覆盖会自动跟随当前配置，不会出现悬空的 endpoint id。

### 3.2 前端路径（桌面端主路径）

`src/features/send-message/useChat.ts` 在发送前完成解析：

1. `sessionApi.getModelOverride(sid)` 读取会话覆盖；读取失败按「跟随全局」处理（fail-open）；
2. `resolveEffectiveChatModel(selection, endpoints, override)` 返回 `{endpoint, modelId}`：

| 情形 | 结果 |
| --- | --- |
| 无覆盖，或覆盖值等于全局 `modelId` | 全局端点 + 全局模型 |
| 覆盖模型能在某个端点 `discoveredModels` 中找到 | 该端点 + 覆盖模型（**即使与全局同端点也替换 model id**） |
| 覆盖模型在全部端点中都找不到 | 回退全局选择（fail-open） |

3. 由解析结果构造 `ChatConfig`：`apiKey` / `apiUrl` 取自生效端点，`model` 取生效模型，`provider` 由 `inferProviderFromBaseUrl(baseUrl)` 推导，`reasoningEffort` / `thinkingBudget` 等仍是端点级配置；
4. `chatApi.chatStream` 经 IPC `agent_chat_stream` POST `/api/v1/chat/stream`，把 `apiKey` / `apiUrl` / `model` 原样透传。

`resolveEffectiveChatModel` 与 `findEndpointForModel` 位于 `src/shared/lib/effectiveChatModel.ts`。同一份解析结果同时供 `ChatInput.tsx` 做视觉能力判定，并通过 `subscribeSessionModelOverrideChanged` 在会话内切换模型后立即刷新——请求凭据、`ChatRequest.model` 与「是否支持视觉」必须来自同一次解析，否则会出现「已切到多模态模型，输入框仍提示不支持图片」。

> 注意：`SessionModelPicker.tsx` 头部那句「只切模型不改端点」的注释是历史遗留，与现行实现相反。实际行为是切换模型会连带切换端点凭据。

### 3.3 后端路径（兜底与非桌面调用方）

`backend/api/legacy_routes.py` 的 `/chat/stream`（以及 `legacy_chat_routes.py` 的 `/chat`）按请求是否自带凭据二选一：

```python
if data.api_key and data.api_url:
    # 直接用请求里的凭据，不读会话覆盖
else:
    llm_config = load_llm_config_for_chat(session_id=..., profile_model=..., ...)
```

这解释了为什么「双保险」缺一不可：

- 桌面端前端几乎总会带 `apiKey` / `apiUrl`，因此**前端解析才是主路径**，后端 `load_llm_config_for_chat` 根本不会被调用；
- 本地 `ollama` / 无鉴权端点的 `apiKey` 是空串，`data.api_key` 为假值，请求会落到后端解析分支；
- 非桌面调用方（网关、脚本、其他 API 客户端）通常不带凭据，同样走后端分支。

`load_llm_config_for_chat` 的解析顺序：

1. `base = load_llm_config_from_settings()`：按全局 `modelSelections.chatModel` 解析出 `api_key` / `base_url` / `model` / `endpoint_id`；
2. `override = resolve_chat_model(session_id, profile_model)`：会话覆盖优先；其次 profile 声明的模型（`gpt-4` / `gpt-3.5-turbo` / `gpt-4-turbo-preview` 等种子占位值视为未设置）；都没有返回 `None`；
3. 若 `override` 存在且与 `base["model"]` 不同：
   - `find_endpoint_for_model(override)` 遍历 `app_settings.endpoints`，匹配 `discoveredModels[].id`，收集候选端点；
   - 候选中有 `apiKey` 的优先，否则取第一个；
   - 若命中的端点 id 与当前 `endpoint_id` 不同，**整体替换** `api_key` / `base_url` / `endpoint_id` / `provider`（`protocol` 映射为 `ollama` / `anthropic` / `gemini` / `custom`）；
   - 无论是否换端点，`merged["model"] = override`；
   - 找不到任何端点时只改模型名、保留原凭据（fail-open，记 info 日志）；
4. 最后叠加 `apply_auto_routing_overlay`：仅当 `routing.mode == "auto"` 且用户没有显式选择（`resolve_chat_model` 返回 `None`）时，按任务类型在同一 `endpoint_id` 内重选模型。

同一函数还被两处复用：

- `backend/gateway/base.py::_resolve_llm`：无注入工厂时直接 `load_llm_config_for_chat(session_id=...)` 构造 `LLMClient`；
- `backend/services/self_status.py`：用同一解析结果对外报告「实际生效模型」。

### 3.4 两条路径的一致性约定

前端与后端各自独立实现了同一套规则，必须保持同步：

| 规则 | 前端 | 后端 |
| --- | --- | --- |
| 同名模型多端点时优先有 `apiKey` 的端点 | `findEndpointForModel` | `find_endpoint_for_model` |
| 覆盖模型在同端点也要替换 model id | `resolveEffectiveChatModel` | `merged["model"] = override`（凭据不变） |
| 反查不到端点 → 回退全局 | 返回全局端点 + 全局模型 | 只改模型名，保留全局凭据 |
| 覆盖值等于全局模型 → 视同未覆盖 | `override === globalModelId` 提前返回 | 仅在 `override != merged.get("model")` 时重解析 |

## 4. 关键设计决策

| 决策 | 理由与代价 |
| --- | --- |
| 会话只存 `model_id`，不存 `endpoint_id` | 端点可被删除、改地址、重新发现模型；存 id 会产生悬空引用。代价是运行时必须反查，并要处理「同名模型出现在多个端点」的仲裁。 |
| 模型与凭据原子切换 | `model` / `api_key` / `base_url` / `provider` 是一个整体，单独替换任意一项都会把请求发到错误的上游，表现为 502 或鉴权失败。 |
| 同名模型优先选有 `apiKey` 的端点 | 本地无鉴权端点（ollama / LM Studio）常与远端重名；选无 key 的那个会把远端模型打到本地服务。 |
| fail-open，而不是阻断发送 | 找不到端点或读取覆盖失败时沿用全局配置。宁可按全局模型发出（用户至少能看到回复），也不把「未知覆盖」变成空选择或硬错误。 |
| 显式选择高于自动路由 | `apply_auto_routing_overlay` 在 `resolve_chat_model` 非空时直接返回原配置。用户手动锁定模型后，目录路由不得再改。 |
| 自动路由限定在同一 `endpoint_id` 内 | 路由引擎若跨端点选模型，会再次制造「模型与凭据错配」。拿不到 `endpoint_id` 时直接跳过路由。 |
| 同端点覆盖也必须替换 model id | 早期前端只在「端点不同」时才应用覆盖，导致「切到同一端点另一个模型」被静默丢弃。现行实现无条件替换模型，仅凭据按端点是否变化决定是否重取。 |
| 视觉能力判定复用同一份解析 | 请求凭据、`ChatRequest.model`、vision 能力必须同源；否则会按全局模型误报「不支持视觉」或错误剔除 `vision` 能力。 |

## 5. 相关文件

**前端**

| 文件 | 职责 |
| --- | --- |
| `src/shared/lib/effectiveChatModel.ts` | `findEndpointForModel` / `resolveEffectiveChatModel`；覆盖变更事件 `SESSION_MODEL_OVERRIDE_EVENT` 与订阅辅助 |
| `src/features/send-message/useChat.ts` | 发送前读取会话覆盖、解析生效端点、构造 `ChatConfig` |
| `src/widgets/chat/SessionModelPicker.tsx` | 会话内模型切换 UI；切换前提示历史截断风险 |
| `src/widgets/chat/ChatInput.tsx` | 复用生效模型做视觉能力判定，并订阅覆盖变更事件 |
| `src/shared/api/sessionApi.ts` | `getModelOverride` / `setModelOverride`（IPC `session_get_model` / `session_set_model`） |
| `src/shared/api/chatApi.ts` | 把 `apiKey` / `apiUrl` / `model` 透传给 `agent_chat_stream` |
| `src/features/send-message/chatStreamRuntime.ts` | `inferProviderFromBaseUrl`：按 `baseUrl` 推导 provider |
| `electron/commandRoutes/sessions.ts` | IPC 到 REST 的路由映射 |

**后端**

| 文件 | 职责 |
| --- | --- |
| `backend/orchestration/llm_factory.py` | `SESSION_MODEL_OVERRIDES_KEY` / `load_session_model_overrides` / `find_endpoint_for_model` / `resolve_chat_model` / `load_llm_config_for_chat` / `apply_auto_routing_overlay` |
| `backend/api/legacy_session_routes.py` | `GET` / `PUT /api/v1/sessions/{id}/model` |
| `backend/api/legacy_routes.py` | `POST /api/v1/chat/stream`：请求自带凭据则直接用，否则走 `load_llm_config_for_chat` |
| `backend/api/legacy_chat_routes.py` | `POST /api/v1/chat`：同样的二选一逻辑 |
| `backend/gateway/base.py` | `_resolve_llm`：网关侧复用 `load_llm_config_for_chat(session_id=...)` |
| `backend/services/self_status.py` | 对外报告经路由 overlay 后的「实际生效模型」 |
| `backend/data/settings_repo.py` | 注册 `session_model_overrides` KV 键 |
| `backend/api/legacy_models.py` | `ChatRequest.api_key` / `api_url` / `model` / `endpoint_id` 字段定义 |

**测试**

| 文件 | 覆盖点 |
| --- | --- |
| `backend/tests/unit/test_llm_factory.py` | `TestFindEndpointForModel`（5 例：设置不可用 / 模型不存在 / 优先带 key / 全无 key 取首个 / 跳过无模型端点）；`TestLoadLLMConfigForChatWithSessionOverride`（4 例：跨端点切凭据 / 同端点不切 / 模型找不到保留 base / 无覆盖用全局） |
| `backend/tests/unit/test_session_model_override.py` | `resolve_chat_model` 三级优先级与占位值过滤、overrides fail-safe 与畸形条目过滤、REST 往返（写入 strip / 空串清除） |
| `src/shared/lib/__tests__/effectiveChatModel.test.ts` | 无覆盖 / 跨端点覆盖 / 同端点覆盖（回归）/ 未知覆盖回退 / 覆盖等于全局 / 空选择 |

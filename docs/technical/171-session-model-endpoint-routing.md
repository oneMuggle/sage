# 171 会话模型覆盖与端点路由

> 相关代码：`backend/orchestration/llm_factory.py`、`backend/api/legacy_session_routes.py`、
> `backend/api/legacy_chat_routes.py`、`backend/api/legacy_routes.py`、
> `src/shared/lib/effectiveChatModel.ts`、`src/features/send-message/useChat.ts`、
> `src/shared/api/sessionApi.ts`、`src/widgets/chat/SessionModelPicker.tsx`、
> `src/widgets/chat/ChatInput.tsx`

## 1. 背景

会话级模型覆盖允许用户在某一个会话里固定使用某个模型，而不影响全局设置和其他会话。
早期实现把这条语义简化成「只切模型不改端点」：请求仍然携带全局 `modelSelections.chatModel`
所属端点的凭据（例如 DeepSeek 的 `apiKey` / `baseUrl`），只把请求体里的 `model` 换成会话覆盖的
模型名（例如 MiniMax 的模型）。在多端点场景下，上游端点不认识另一个供应商的模型名，
表现为持续重试或 HTTP 502，而单独测试该端点本身是正常的。

修复后的语义：**会话覆盖的模型属于哪个端点，请求就必须携带那个端点的凭据**；同一个端点内
换模型只替换 `model`，跨端点换模型则同时替换 `apiKey` / `baseUrl` / `provider`。
前端与后端各实现了一层解析，正常的桌面端聊天以前端解析结果为准，后端解析用于未携带端点
凭据的调用方（见 §7）。

## 2. 覆盖数据的来源与优先级

### 2.1 存储

- 存储位置：preferences KV，键名为 `session_model_overrides`，值为 JSON 映射
  `{session_id: model_id}`。常量定义在 `backend/orchestration/llm_factory.py`
  （`SESSION_MODEL_OVERRIDES_KEY`），该键已在 `backend/data/settings_repo.py` 的
  可写白名单中。
- 读取：`load_session_model_overrides()`。任何读取失败（DB 不可用、值不是 dict）返回空映射；
  逐条过滤非 `str → 非空 str` 的畸形条目，不做整体失败。
- 写入：`PUT /api/v1/sessions/{session_id}/model`，处理器
  `backend/api/legacy_session_routes.py::set_session_model`。
  - 模型名会 `strip()`；传空串（或非字符串）表示**清除**覆盖，回到全局选择。
  - 整体读取 → 修改 → 写回，写入失败返回 HTTP 500，不做部分写入。
- 读取端点：`GET /api/v1/sessions/{session_id}/model` 返回
  `{"session_id": ..., "model": <str|null>}`。

前端通过 Electron IPC `session_get_model` / `session_set_model` 访问上述 REST 端点
（`electron/commandRoutes/sessions.ts`），封装在 `src/shared/api/sessionApi.ts` 的
`getModelOverride()` / `setModelOverride()`。`setModelOverride()` 成功后广播
`SESSION_MODEL_OVERRIDE_EVENT`（`sage:session-model-override-changed`），供 `ChatInput`
等只读消费方立即刷新视觉能力判定。

### 2.2 优先级

后端 `resolve_chat_model(session_id, profile_model)` 的三级优先级：

| 优先级 | 来源 | 说明 |
|---|---|---|
| 1 | 会话覆盖 `session_model_overrides[session_id]` | 用户在会话内显式选择，最高优先 |
| 2 | profile 的 `model_config.model` | 仅当不是种子占位值 `gpt-4` / `gpt-3.5-turbo` / `gpt-4-turbo-preview` 时生效 |
| 3 | `None` | 表示沿用全局 `app_settings.modelSelections` |

前端只读取会话覆盖，不读取 profile：`useChat` 在发送时调用
`sessionApi.getModelOverride(sid)`，读取失败时按「跟随全局」处理（fail-open）。

### 2.3 写入入口

| 入口 | 行为 |
|---|---|
| `SessionModelPicker` | 手动路由模式下写覆盖；`routing.mode === "auto"` 时渲染建议性路由面板，**绝不写覆盖** |
| `Welcome` 新建会话 | 创建会话后，若选择了具体模型（非 `AUTO_MODEL_ID`）则写入覆盖 |
| 会话内切换 | `sessionApi.setModelOverride()` → 渲染进程广播覆盖变更事件 |

## 3. 前端解析链路

主路径在 `src/features/send-message/useChat.ts::sendMessage()`：

1. 读取会话覆盖：`sessionModelOverride = await sessionApi.getModelOverride(sid)`；
   异常时保持 `null`。
2. 解析实际生效模型：
   `resolveEffectiveChatModel(settings.modelSelections.chatModel, settings.endpoints, sessionModelOverride)`
   （`src/shared/lib/effectiveChatModel.ts`）。
3. 用解析结果的端点凭据与模型 id 构建 `ChatConfig`。

`resolveEffectiveChatModel()` 的判定：

| 情形 | 返回 |
|---|---|
| 无覆盖，或覆盖模型与全局模型相同 | 全局端点 + 全局模型 |
| 覆盖模型在某个端点的 `discoveredModels[].id` 中命中 | 该端点 + 覆盖模型 |
| 覆盖模型与全局模型同属一个端点 | 仍是该端点，但模型 id 替换为覆盖值 |
| 覆盖模型在所有端点都找不到 | 回退全局端点 + 全局模型（fail-open） |
| 全局选择为空 | 端点 `undefined`、模型空串 |

端点查找由同文件的 `findEndpointForModel()` 完成：按 `endpoint.discoveredModels` 精确匹配
模型 id；同一模型出现在多个端点时，**优先选择有 `apiKey` 的端点**，都没有时取第一个匹配项。

构建 `ChatConfig` 时（`useChat`）：

- `sendEndpoint = effectiveEndpoint ?? chatEndpoint`，其中 `chatEndpoint` 是全局
  `modelSelections.chatModel` 对应的端点；
- `apiKey` / `apiUrl` 取 `sendEndpoint`，`model` 取解析后的模型 id；
- `provider` 由 `sendEndpoint.baseUrl` 推断（`inferProviderFromBaseUrl`）；
- 视觉能力 `capabilities` 通过 `resolveVisionSupport(effectiveEndpoint, chatModelId, catalog)`
  判定，保证「覆盖到多模态模型」时输入框不会按全局文本模型误报不支持视觉。

`ChatInput` 复用同一个 `resolveEffectiveChatModel()`：它独立调用
`sessionApi.getModelOverride(effectiveSessionId)`，并订阅
`subscribeSessionModelOverrideChanged()`，在会话内切换模型后无需重挂组件即可刷新视觉判定。

> 注意：发送前的「端点/模型是否已配置」校验仍以全局 `chatModel` 为准
> （`useChat` 中的 `chatEndpoint?.baseUrl` 与 `settings.modelSelections.chatModel.modelId`），
> 解析后的 `effectiveEndpoint` 只决定实际请求参数；见 §9。

## 4. 后端解析链路

### 4.1 全局端点基线

`load_llm_config_from_settings()` 解析全局端点：

1. 若 `modelSelections.chatModel.endpointId` 指向存在的端点，取该端点；模型取
   `selection.modelId`，缺省回退该端点第一个 `discoveredModels[].id`，再缺省 `gpt-3.5-turbo`。
2. 否则取 `endpoints` 中第一个带非空 `apiKey` 的端点。
3. 协议必须在 `anthropic` / `gemini` / `ollama` / `openai-compatible` 白名单内，
   且要有 `baseUrl`；否则返回 `None`。

返回 dict 包含 `provider`（固定 `"custom"`）、`api_key`、`base_url`、`model`、
`temperature`、`endpoint_id`（用于用量归属），以及可选的 `max_tokens`（全局
`maxOutputTokens`，夹紧到 512–32768）。

### 4.2 会话覆盖重解析

`load_llm_config_for_chat(session_id, profile_model, profile_max_tokens, task_type)`：

```
base = load_llm_config_from_settings()
override = resolve_chat_model(session_id, profile_model)

if override and override != base["model"]:
    owning = find_endpoint_for_model(override)
    if owning and owning.id != base["endpoint_id"]:
        切换 api_key / base_url / endpoint_id
        provider = 由 owning.protocol 映射
    base["model"] = override
```

关键点：

- `find_endpoint_for_model(model_id)` 读取 `app_settings` 并经 `to_camel` 归一化，
  遍历 `endpoints[].discoveredModels` 精确匹配；多个命中时优先有 `apiKey` 的端点，
  否则取第一个。设置不可用或模型未命中返回 `None`。
- 只有「命中端点且端点 id 与全局不同」才替换凭据；同一端点内换模型只改 `model`。
- 协议到 provider 的映射：`ollama → ollama`、`anthropic → anthropic`、
  `gemini → gemini`、其余（含 `openai-compatible`）→ `custom`。
- 切换时记录一条 `INFO` 日志（只打印端点 id 前 8 位）。
- `profile_max_tokens` 作为次高优先级覆盖 `max_tokens`；等于占位默认 4096 时忽略。
- 最后调用 `apply_auto_routing_overlay()`（见 §4.3）。

### 4.3 自动路由的交互

`apply_auto_routing_overlay(cfg, task_type, session_id, profile_model)`：

- `routing.mode` 不是字面量 `"auto"`（缺省/未知都按 manual）→ 原样返回；
- 存在显式选择（`resolve_chat_model` 返回会话覆盖或 profile 模型）→ 原样返回，
  即**用户选择优先于自动路由**；
- `cfg` 没有非空字符串 `endpoint_id` → 原样返回，避免跨端点借用凭据；
- 否则用 `resolve_routed_chat_model(task_type, context_length, endpoint_id)` 在**同一端点**
  的模型目录内重选模型，只替换 `model`，不动凭据。

`/chat/stream` 的生产者除了在 `load_llm_config_for_chat` 内部应用该 overlay，
还在调用点显式应用一次，以覆盖「请求自带端点配置」的路径（`legacy_routes.py`）。
非流式 `/chat` 的请求自带配置路径不额外应用 overlay。

## 5. 端点路由判定汇总

| 判定项 | 依据 |
|---|---|
| 模型属于哪个端点 | `endpoints[].discoveredModels[].id` 精确匹配 |
| 同名模型多个端点 | 优先非空 `apiKey`，否则第一个 |
| 是否切换凭据 | 仅当命中端点 id 与当前端点 id 不同 |
| 请求中的 `model` | 始终使用会话/profile 覆盖值 |
| 端点 id 用途 | `endpoint_id` 用于用量归属与自动路由的端点作用域 |
| 协议校验 | 仅 `anthropic` / `gemini` / `ollama` / `openai-compatible` 可用 |

## 6. 无匹配时的回退

| 层 | 情形 | 行为 |
|---|---|---|
| 前端 | 读取覆盖失败 | 视为无覆盖，使用全局选择 |
| 前端 | 覆盖模型不在任何端点 | 回退全局端点 + 全局模型 |
| 后端 | 覆盖模型未命中端点 | 保留全局凭据，只替换 `model`（fail-open，可能仍被上游拒绝） |
| 后端 | 全局无可用端点 | `load_llm_config_for_chat` 返回 `None`，调用方降级 |
| 后端 | `session_model_overrides` 损坏 | 空映射；畸形条目逐条丢弃 |
| 后端 | auto 路由无结果 / 无端点作用域 | 保留原配置 |

## 7. 请求路径上的「双保险」边界

`/chat`（`legacy_chat_routes.py`）与 `/chat/stream` 生产者（`legacy_routes.py`）的配置来源：

```
if data.api_key and data.api_url:
    llm_config = 由请求字段直接构建（api_key / base_url / model / temperature / provider）
else:
    llm_config = load_llm_config_for_chat(session_id=..., profile_model=..., ...)
```

因此：

- 当请求携带 `api_key` 与 `api_url` 时，后端**不会**调用 `load_llm_config_for_chat`，
  也就不会按会话覆盖重新选择端点；此时请求里的 `apiKey` / `apiUrl` / `model` 原样生效。
- 桌面端主聊天路径始终把解析后的有效端点凭据放进 `ChatConfig`，所以正常请求走的是
  「请求自带配置」分支，**前端解析是主路径**。
- 后端重解析实际兜底的是未携带端点凭据的调用方（旧客户端、部分测试/CLI、`apiKey` 为空的
  本地端点等），不是「前端漏读覆盖」时的纠错层。

流式生产者还会对两种来源统一应用 `apply_auto_routing_overlay`；请求自带配置时若缺少
`endpoint_id`，生产者会从持久化的全局 `chatModel.endpointId` 兜底写入，用于用量归属。

## 8. 测试覆盖

| 测试文件 | 覆盖内容 |
|---|---|
| `backend/tests/unit/test_llm_factory.py` | `TestFindEndpointForModel`（5 项：设置不可用、未知模型、多端点优先 apiKey、都无 key 取第一个、忽略无模型端点）+ `TestLoadLLMConfigForChatWithSessionOverride`（4 项：跨端点切凭据、同端点不切、未知模型 fail-open、无覆盖用全局） |
| `backend/tests/unit/test_session_model_override.py` | `resolve_chat_model` 优先级与占位值、覆盖映射的 fail-safe/畸形过滤、`load_llm_config_for_chat` 的模型覆盖、REST 读写往返（含 strip 与空串清除） |
| `backend/tests/unit/test_llm_factory_auto_routing.py` | overlay 只在 auto 模式生效、按端点作用域路由、显式会话覆盖优先、无 endpoint id 不路由 |
| `backend/tests/integration/test_chat_stream.py` | 请求自带 `api_key`/`api_url` 时配置透传给 `run_loop`；overlay 在生产者调用点生效；请求不带凭据时走设置路径 |
| `src/shared/lib/__tests__/effectiveChatModel.test.ts` | 6 种解析情形（无覆盖、跨端点、同端点、未知模型、覆盖等于全局、空选择） |
| `src/features/send-message/__tests__/useChat.test.ts` | 同端点会话覆盖进入实际发出的 `agent_chat_stream` 请求体 |
| `src/widgets/chat/__tests__/ChatInput.ocrFallback.test.tsx` | 视觉能力按会话覆盖模型判定、覆盖变更事件触发原地刷新 |
| `src/widgets/chat/__tests__/SessionModelPicker.test.tsx` | 覆盖读取/展示/写入；auto 模式不写覆盖 |

后端跨端点用例通过 mock `resolve_chat_model` 驱动，尚未有「真实覆盖记录 + `/chat/stream`
端到端」的集成用例。

## 9. 已知限制

1. **依赖 `discoveredModels`**：端点识别只认 `endpoints[].discoveredModels` 里的模型 id。
   用户手工输入的模型或尚未发现目录的端点无法被定位，此时 fail-open 保留全局凭据 + 覆盖模型，
   仍可能得到 502。
2. **后端不是前端漏读的纠错层**：请求一旦携带 `api_key` 与 `api_url`，后端不重解析会话覆盖
   （见 §7）。后端双保险只对未带端点凭据的调用方有效。
3. **发送前置校验仍看全局**：`useChat` 在解析覆盖前就检查全局 `chatEndpoint?.baseUrl` 与
   `settings.modelSelections.chatModel.modelId`。若全局未配置而仅设置了会话覆盖，会被提前
   报错「未选择对话模型 / 未配置 API 地址」。
4. **用量归属可能不准**：`ChatConfig` 不携带 `endpointId`，请求自带配置时后端按持久化的全局
   `chatModel.endpointId` 记录 `endpoint_id`。会话覆盖跨端点时，实际请求走新端点，但用量归属
   可能仍记到全局端点。
5. **`/btw` 旁路不跟随覆盖**：`chatStreamRuntime.askBtw()` 固定使用全局 `chatEndpoint` 与
   全局 `chatModel`，不读取会话覆盖。
6. **自动路由模式不写覆盖**：`SessionModelPicker` 在 `routing.mode === "auto"` 时只展示
   建议性路由，真正的选型在服务端按 `task_type` 发生；手动与自动两种模式不能同时施加会话覆盖。
7. **注释与行为已脱节**：`SessionModelPicker.tsx` 顶部仍写着「只切模型不改端点(端点恒取全局选择)」，
   `test_session_model_override.py` 的 `test_chat_config_keeps_endpoint_overrides_model`
   注释也写着「端点恒取全局」；这两处描述的是修复前语义，实际跨端点切换逻辑以 §4.2 为准。

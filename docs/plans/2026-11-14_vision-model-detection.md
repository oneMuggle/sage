# 多模态视觉能力判定修复

> 状态：进行中（2026-11-14 起草）
> 分支：`fix/vision-model-detection`
> 工作区：`.worktrees/fix-vision-model-detection/`

## 1. 背景与目标

### 现象

配置支持视觉的对话模型（如 `claude-3-5-sonnet`、`gpt-4.1`、`gemini-2.5-pro`、`qwen2.5-vl-72b` 等）后，
设置/聊天输入区仍显示「当前对话模型不支持视觉识别，请配置视觉理解模型或更换支持视觉的对话模型」警告横幅，
且图片上传按钮被禁用。

### 根因

`ChatInput.tsx:160-168` 把 `endpoint.discoveredModels` 当作视觉能力的**唯一真相源**。
而 `discoveredModels` 的 `capabilities` 字段由前端 `inferCapabilities` 在端点测试连接时根据 model id
**字符串子串匹配**推导，存在以下问题：

1. **双重实现不一致**：
   - `src/entities/endpoint/providerRegistry.ts:116`（**生产路径**）—— 仅识别 `vision` / `4o` 两个 marker；
   - `src/features/manage-endpoints/api.ts:371`（几乎未使用）—— 覆盖约 20 个 marker。
2. **前后端语义相反**：后端 `backend/core/legacy/agent.py:960-964` 的语义是
   「未知=支持 vision」（fail-safe），前端则是「未知=不支持」。
3. **未对接权威数据源**：model-catalog `getEffective().capabilities`（含 `user_override > service_probe
   > imported_snapshot > builtin > unknown` 多层解析）已存在但未被消费。
4. **误判外溢**：`useChat.ts:464` 把同样的误判结果写入 `ChatRequest.capabilities`，
   后端 `legacy_routes.py:836-847` 用 `"vision" in data.capabilities` 覆盖自己的启发式，
   最终在 `agent.py:1026` 抛 `VisionNotAvailableError` —— 前端警告 + 后端报错同源。

### 目标

- 多模态模型**不再被误判为不支持 vision**；
- 视觉能力判定按权威度分层：**`user_override > service_probe > catalog builtin > 后端启发式 > 未知视为支持**；
- 消除两份 `inferCapabilities` 实现，归一到单一来源；
- 保留「明确 `false`」的强否定路径（用户手动覆盖 / 服务探测确认不支持时），不破坏 OCR fallback 的合法场景。

## 2. 涉及文件与模块

### 前端

| 文件 | 修改 |
|---|---|
| `src/entities/endpoint/providerRegistry.ts` | 删除窄版 `inferCapabilities`，改为引用宽版 |
| `src/shared/lib/modelCapabilities.ts` | **新增**：抽出的宽版 `inferCapabilities`（合并两份实现 + 扩充主流 VL 家族 marker） |
| `src/shared/lib/visionCapability.ts` | **新增**：`resolveVisionSupport(endpoint, modelId, catalog)` 分层解析函数，返回 `'supported' \| 'unsupported' \| 'unknown'` |
| `src/widgets/chat/ChatInput.tsx` | 消费新的分层解析；`'unknown'` 按支持处理 |
| `src/features/send-message/useChat.ts` | 同步分层解析；`capabilities` 字段仅传递**明确**的 vision 判定 |
| `src/widgets/chat/__tests__/ChatInput.ocrFallback.test.tsx` | 更新 fixture，覆盖「明确 false / 未知 / 明确 true」三种态 |

### 后端（不动）

后端 `agent.py:960-964` 已是「未知=支持」的 fail-safe 语义，
`legacy_routes.py:836-847` 的 override 逻辑保留 —— 本次只在前端把 `capabilities` 字段按新语义填值：
- `unknown` 或 `supported`：传 `['chat', 'vision']`（维持旧行为）
- `unsupported`：传 `['chat']`

### 不涉及的改动

- 不新增 UI 入口暴露 model-catalog `setOverride`（结构性修正留后续 PR）
- 不改 model-catalog API 与后端 provider 启发式
- 不改 `SessionModelPicker`（已走 catalog-first，不判 vision）

## 3. 技术方案

### 3.1 单一 `inferCapabilities` 实现

抽出到 `src/shared/lib/modelCapabilities.ts`，合并：
- `api.ts:371` 的宽版 marker（约 20 个）
- `providerRegistry.ts:116` 的 embedding 短路
- 补充：`gpt-4o`（当前靠 `4o` 命中但易误判）、`gpt-4.1`、`claude-4-sonnet`/`claude-4-opus`/`claude-4-haiku`、`qwen-vl`、`qwen2-vl`、`qwen2.5-vl`、`glm-4v`、`glm-4.5-v`、`internvl2`、`minicpm-v`、`llama-3.2-vision` 等主流家族
- 明确 negative marker：`text-embedding-*`、`bge-*`、`rerank-*`、`whisper-*`、`dall-e-*`、`tts-*`、`asr-*`、`imagen-*`、`veo-*`、`claude-2`、`claude-instant`

### 3.2 分层视觉解析 `resolveVisionSupport`

输入：`(endpoint: EndpointConfig, modelId: string | null, catalog?: EffectiveModel | null)`
输出：`'supported' | 'unsupported' | 'unknown'`

```
1. catalog?.capabilities?.vision === true    → 'supported'
2. catalog?.capabilities?.vision === false   → 'unsupported'
3. catalog 缺失 / 字段缺失 → 查 endpoint.discoveredModels.find(m => m.id === modelId)
   3.1 命中 + caps 含 'vision'              → 'supported'
   3.2 命中 + caps 不含 'vision'             → 'unsupported'
   3.3 未命中（模型未在发现列表）             → 'unknown'
```

`ChatInput` / `useChat` 消费时：
- `'unsupported'` → 显示警告 / 传 `['chat']`
- `'supported' | 'unknown'` → 不显示警告 / 传 `['chat', 'vision']`

这与后端 `agent.py` 的 fail-safe 完全对齐。

### 3.3 catalog 数据源接入

`ChatInput` / `useChat` 增加一次性 `useEffect`，当 `(chatEndpointId, chatModelId)` 变化时调用
`getEffective(endpointId, modelId)`。404 / 网络错误 → null（等同未知）。
- 失败/离线时保留 `discoveredModels` 回退路径；
- 不在 `getEffective` 返回前阻塞渲染（初始态按 `'unknown'` 处理，与 fail-safe 一致）。

## 4. 实施步骤

- [x] M1. 抽出 `src/shared/lib/modelCapabilities.ts`（合并两份实现 + 扩充 marker）
- [x] M2. 新增 `src/shared/lib/visionCapability.ts`（`resolveVisionSupport` 分层解析）
- [x] M3. `providerRegistry.ts` / `manage-endpoints/api.ts` 改为引用共享 `inferCapabilities`
- [x] M4. `ChatInput.tsx` 接入分层解析（含 catalog 读取）；`unknown` 按支持
- [x] M5. `useChat.ts` 同步分层解析；`capabilities` 字段只在明确 `unsupported` 时剔除 `'vision'`
- [x] M6. 单元测试：`modelCapabilities.test.ts`（marker 覆盖主流多模态 + 负样本）
- [x] M7. 单元测试：`visionCapability.test.ts`（分层优先级 + 三态输出）
- [x] M8. 更新 `ChatInput.ocrFallback.test.tsx` fixture，覆盖三种态
- [x] M9. 在 worktree 内跑 `npm run build` 通过 + `vitest` 相关测试通过
- [ ] M10. commit + push，开 PR → main
- [ ] M11. cherry-pick → release/win7 并适配（如有冲突）

## 5. 风险评估与依赖

### 风险

| 风险 | 等级 | 缓解 |
|---|---|---|
| 新 marker 列表覆盖过宽，误把纯文本模型判为 vision | 低 | 仍由后端 `agent.py:960-964` 二次校验；`'unknown'` 按支持，与后端一致 |
| catalog 读取失败 → 回退到 `discoveredModels` 的窄推断 | 中 | M2 的分层解析已处理：回退路径与现有行为一致；catalog 成功时即修正 |
| 测试 fixture 与现状差异导致回归 | 低 | M6-M8 专门覆盖，并在 M9 跑全量相关测试验证 |

### 依赖

- model-catalog `getEffective` API 已稳定，无新增后端改动；
- `EffectiveModel.capabilities` 字段类型 `Record<string, boolean> | null | undefined` 已存在（`src/entities/model-catalog/types.ts:57`）。

### 不在本次范围

- UI 入口暴露手动覆盖 vision 能力（依赖 `setOverride`）；
- 后端 provider 启发式扩充；
- 后端 `legacy_routes.py:836-847` 的 frontend-overrides-backend 逻辑改造。

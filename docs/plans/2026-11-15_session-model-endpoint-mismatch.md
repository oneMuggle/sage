# 会话模型-端点路由失配修复

> **日期**：2026-11-15
> **状态**：进行中
> **分支**：`fix/session-model-endpoint-mismatch`

## 背景与目标

### 问题现象

会话 `fdd98b39-1b5c-44ef-90fa-dd4d25409487` 持续重试，端点测试页正常。

### 根因分析

| 层 | 问题 |
|---|---|
| **设计假设** | `SessionModelPicker.tsx` 第 4 行注释："只切模型不改端点(端点恒取全局选择)"。在多端点场景下此假设失效 |
| **前端** | `useChat.ts:499-502`：构建 `ChatConfig` 时始终用全局 `modelSelections.chatModel` 的端点凭据（DeepSeek），忽略会话模型覆盖 |
| **后端** | `load_llm_config_for_chat`：用全局 DeepSeek 凭据 + 会话覆盖的 model 名（MiniMax-M3.1-Flash）→ DeepSeek 不认识 MiniMax 模型 → HTTP 502 |

### 数据流

```
用户会话选择 MiniMax-M3.1-Flash
  ↓
session_model_overrides[fdd98b39] = "MiniMax-M3.1-Flash"
  ↓ (发聊天请求)
前端 useChat.ts:
  chatEndpoint = resolveEndpoint(modelSelections.chatModel, endpoints)  // 仍取 DeepSeek!
  config = { apiKey: deepseekKey, apiUrl: deepseekUrl, model: "deepseek-flash" }  // 不读 override
  ↓ (invoke 到后端)
后端 legacy_routes.py:
  data.api_key = "sk-..." (DeepSeek key)
  data.model = "deepseek-flash" (全局 model，不是 override)
  ↓
load_llm_config_for_chat(session_id):
  base = load_llm_config_from_settings()  // DeepSeek 凭据
  override = resolve_chat_model(session_id)  // "MiniMax-M3.1-Flash"
  merged["model"] = override  // 只改 model，凭据仍是 DeepSeek!
  ↓
请求 DeepSeek URL + model=MiniMax-M3.1-Flash → 502
```

### 目标

当会话模型覆盖指向不同端点时，请求必须路由到正确的端点凭据。

## 涉及的文件与模块

### 后端

| 文件 | 改动 |
|---|---|
| `backend/orchestration/llm_factory.py` | `load_llm_config_for_chat` 增加端点重解析逻辑 |

### 前端

| 文件 | 改动 |
|---|---|
| `src/features/send-message/useChat.ts` | 构建 `ChatConfig` 时考虑会话模型覆盖 |

## 技术方案

### 后端修复（双保险）

在 `load_llm_config_for_chat` 中：

1. 读 `session_model_overrides[session_id]` 获取会话模型
2. 若覆盖的模型与全局 `modelSelections.chatModel.modelId` 不同：
   - 遍历 `app_settings.endpoints` 查找包含该模型的端点
   - 用该端点的凭据（apiKey/baseUrl/provider）替换 base
3. 找不到时保留原逻辑（fail-open）

### 前端修复

在 `useChat.ts` 中构建 `ChatConfig` 时：

1. 读取当前会话的模型覆盖（通过 `session_model_overrides`）
2. 若有覆盖，在所有 endpoints 中查找包含该模型的 endpoint
3. 用该 endpoint 的凭据构建 `ChatConfig`

## 实施步骤

- [x] M1：后端 `llm_factory.py` 新增 `find_endpoint_for_model` 辅助函数
- [x] M2：后端 `load_llm_config_for_chat` 增加端点重解析逻辑
- [x] M3：前端 `useChat.ts` 读取会话模型覆盖并重解析端点
- [x] M4：添加单元测试覆盖新逻辑（后端 9 个新测试全部通过）
- [ ] M5：验证修复（手动测试 + 日志确认）

## 风险评估

| 风险 | 缓解措施 |
|---|---|
| 同一模型名出现在多个端点 | 优先选择有 apiKey 的端点；都无 key 时选第一个 |
| 会话覆盖的模型在所有端点都找不到 | 保留原行为（fail-open），日志 warning |
| 前端未读取到 session_model_overrides | 后端有双保险修复 |

## 依赖

- 无新依赖
- 无需数据库迁移（`session_model_overrides` 结构不变）

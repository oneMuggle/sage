# 2026-10-28 max-output-tokens 输出长度可配置

> Feature: `feat/add-max-output-tokens` | Worktree: `.claude/worktrees/fix-max-output-tokens`

## 1. 背景与目标

当前 Sage 每次 LLM 调用请求体都写死 `max_tokens: 4096`（`backend/core/legacy/llm_client.py:246` 默认值），前端"设置"页面中没有任何字段能改变这个值。
用户反馈：回答总在 ~4096 token 处被截断并显示"回答达到长度上限，已被截断"。

**目标**：新增全局设置项 `maxOutputTokens`，使该值可控，覆盖主聊天链路（/chat、/chat/stream）的 LLM 输出上限，并保留智能体 `profile.model_config.max_tokens` 的兜底语义。

## 2. 涉及的文件与模块

### 后端
| 文件 | 修改 |
|---|---|
| `backend/api/settings_models.py` | `SettingsPayload` / `LegacySettingsPayload` 加 `maxOutputTokens: Optional[int]` |
| `backend/orchestration/llm_factory.py` | `load_llm_config_from_settings()` 读设置并写入 `max_tokens`；`load_llm_config_for_chat()` 支持 profile `max_tokens` 兜底 |
| `backend/api/legacy_models.py` | `ChatRequest` 可选加 `max_tokens` 字段（前端直传时优先） |
| `backend/api/legacy_routes.py` | `/chat/stream` producer 的 `llm_config` 组装读取 profile.max_tokens 与全局 maxOutputTokens |
| `backend/api/legacy_chat_routes.py` | `/chat` 同上 |

### 前端
| 文件 | 修改 |
|---|---|
| `src/entities/setting/types.ts` | `AppSettings` 加 `maxOutputTokens: number` 与默认值 |
| `src/pages/settings/ModelsTab.tsx` | 新增"最大输出长度"输入框（范围 512–32768，步长 512） |
| `src/shared/lib/store.ts` | `defaultAppSettings` 加 `maxOutputTokens: 4096` |

## 3. 技术方案

### 3.1 取值优先级（从高到低）

聊天链路 `llm_config.max_tokens` 取值：

1. `ChatRequest.max_tokens`（前端显式传入，目前未传 → None）
2. 当前 agent `profile.model_config.max_tokens`（仅当 profile 已加载，且非默认 4096 时）
3. 全局设置 `app_settings.maxOutputTokens`（新加）
4. `LLMConfig` 默认值 `4096`

`load_llm_config_for_chat(session_id, profile_model)` 需升级为同时接受 `profile_max_tokens: Optional[int]`，按优先级合并。

非聊天路径（planner / title_generator / wiki）维持原状，各自有自己的输出预算语义（planner 走 1_000_000 domain budget，wiki 用 300），不混用全局值。

### 3.2 上下文窗口约束

`max_tokens` 不应超过 `context_window - prompt_tokens`，否则上游 vLLM 会返回 400（`prompt+max_tokens > max_model_len`）。
实现：在 `legacy_routes.py` 组装 `llm_config["context_window"]` 的同时，clamp `max_tokens = min(max_tokens, max(context_window - 500, 512))`。

### 3.3 前端 UI

`src/pages/settings/ModelsTab.tsx` 在"最大上下文长度"下方新增：

- 标签："最大输出长度"
- 描述："单次回答允许生成的最大 token 数；设为较大值可让模型输出更长的内容，但会占用更多上下文窗口"
- `<input type="number" min="512" max="32768" step="512" value={settings.maxOutputTokens} />`
- 同步写入 `settings.maxOutputTokens`

## 4. 实施步骤（可独立验证的里程碑）

- [x] **M1 后端设置层**：`SettingsPayload` / `LegacySettingsPayload` 加 `maxOutputTokens` 字段；默认 4096
- [x] **M2 后端组装**：`load_llm_config_from_settings()` 读设置写入 `max_tokens`；`load_llm_config_for_chat()` 接受 profile max_tokens 兜底
- [x] **M3 路由层**：`/chat` 与 `/chat/stream` 组装 `llm_config` 时调用新的 `resolve_max_output_tokens`，并注入 profile `max_tokens`；`context_window` 已知时 clamp `max_tokens ≤ window − 512`；`measure_request_reserve` 输出预算同步
- [x] **M4 前端设置**：`AppSettings` 加 `maxOutputTokens` 字段，默认 4096；`storage.ts` `TOP_KEYS` 透传；`settings_canonicalizer` `LEGAL_TOP_KEYS` + `ALIASES` 白名单放行；`ModelsTab` 加 UI 控件（范围 512–32768，步长 512）；`settingsSearchIndex` 登记搜索项
- [x] **M5 测试**：
  - 后端新增 `test_max_output_tokens.py`（11 项：优先级 / 夹紧 / 类型校验 / LLMConfig 落地）
  - 契约 `test_settings_schema_parity` 期望集合同步
  - 前端 `ModelsTab.test.tsx` 新增输入渲染 + onChange 回写断言
  - 全量回归：前端 439 / 后端 settings 169 / chat 17 / 新增 11 全部通过
- [x] **M6 文档**：计划文档自身已勾选；settings 相关文档章节（`docs/technical/101-llm-error-classification-retry.md` 不涉及）—— 无独立章节可挂，本次新增字段在代码与测试中已充分记录

## 5. 风险评估与依赖

| 风险 | 处理 |
|---|---|
| 用户把 `maxOutputTokens` 调到极大，请求被上游拒绝（prompt+max > max_model_len） | 加 clamp 逻辑：`min(max_tokens, context_window - 500)` |
| 旧客户端 PUT /settings 没带该字段 | `Optional[int] = None`，None 视为使用默认 4096 |
| profile 已存在但没 `model_config.max_tokens` | 兜底到 4096，与旧行为一致 |
| 双分支 main + release/win7 需保持 | win7 的 pydantic 1.x 差异：`Optional[int] = None` 两版本同语法；canonicalizer 已处理 |

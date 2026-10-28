# 增强 LLM 配置工具：支持 endpoints 和 modelSelections 完整 CRUD

## 背景与目标

当前 Sage 的 LLM 配置工具（`read_sage_config` / `update_sage_config`）只能修改编排参数、智能体配置和通用设置，**无法修改 API 端点配置（endpoints）和模型选择配置（modelSelections）**。这些配置需要用户通过前端设置页面手动修改。

本次增强让 LLM 能够在会话中辅助用户完成所有配置操作，包括：
- 新增/删除/修改 API 端点（endpoints）
- 修改各任务类型的模型绑定（modelSelections）

**安全策略**：
- 保持现有安全级别（WRITE_LOCAL，需要用户审批）
- 完整 CRUD 能力（新增、删除、修改 endpoints）

## 涉及的文件与模块

### 修改的文件

1. **`backend/tools/config_tool.py`**（核心实现）
   - 添加 `_ALLOWED_ENDPOINT_FIELDS` 白名单
   - 添加 `_ALLOWED_MODEL_SELECTION_FIELDS` 白名单
   - 添加 `_validate_endpoint_updates()` 验证函数
   - 添加 `_validate_model_selection_updates()` 验证函数
   - 扩展 `ReadSageConfigTool.execute()` 支持 `section="endpoints"`
   - 扩展 `UpdateSageConfigTool.execute()` 支持 `target="endpoint"` 和 `target="model_selection"`
   - 添加 `_handle_endpoint_action()` 辅助方法（处理 list/get/create/update/delete）
   - 添加 `_handle_model_selection_update()` 辅助方法

2. **`backend/tests/unit/test_config_tool_enhanced.py`**（新增测试）
   - 测试 endpoint CRUD 操作
   - 测试 model_selection 更新和引用完整性检查
   - 测试白名单拦截（越权字段）
   - 测试 apiKey 脱敏

### 复用的现有模块

- `backend.data.settings_repo.SettingsRepository` - 配置持久化
- `backend.services.secret_box` - apiKey 透明加密/解密
- `backend.data.settings_canonicalizer.LEGAL_ENDPOINT_KEYS` - endpoint 字段白名单参考
- `backend.data.settings_canonicalizer.LEGAL_MODEL_SELECTION_KEYS` - model_selection 字段白名单参考

## 技术方案

### 1. 扩展 `update_sage_config` 工具的 target 类型

在现有 `orch` / `agent` / `general` 基础上，新增两个 target：

#### 1.1 `target="endpoint"` - 端点 CRUD 操作

**参数设计**：
```python
{
  "target": "endpoint",
  "action": "list" | "get" | "create" | "update" | "delete",
  "endpoint_id": "xxx",  # get/update/delete 时必填
  "updates": {  # create/update 时必填
    "name": "OpenAI",
    "baseUrl": "https://api.openai.com/v1",
    "apiKey": "sk-...",  # 写入时自动加密
    "protocol": "openai-compatible",
    "modelId": "gpt-4",
    # ... 其他 LEGAL_ENDPOINT_KEYS 字段
  }
}
```

**白名单**：
```python
_ALLOWED_ENDPOINT_FIELDS = {
    "id", "name", "baseUrl", "apiKey", "protocol",
    "modelId", "localModelPath", "discoveredModels", "lastDiscoveredAt",
}
```

**校验逻辑**：
- `protocol` ∈ {"openai-compatible", "anthropic", "gemini", "ollama"}
- `baseUrl` 必须是合法 URL（create/update 时必填）
- `apiKey` 写入时经 SecretBox 透明加密（无需特殊处理）
- `id` 在 create 时自动生成（若未提供），update/delete 时必须匹配现有 endpoint

#### 1.2 `target="model_selection"` - 模型绑定修改

**参数设计**：
```python
{
  "target": "model_selection",
  "task_type": "chatModel" | "visionModel" | "embeddingModel" | "ttsModel" | "asrModel" | "imageGenModel",
  "updates": {
    "endpointId": "xxx",
    "modelId": "gpt-4"
  }
}
```

**白名单**：
```python
_ALLOWED_MODEL_SELECTION_FIELDS = {"endpointId", "modelId"}
```

**校验逻辑**：
- `task_type` 必须 ∈ LEGAL_MODEL_SELECTIONS_KEYS
- `endpointId` 必须在现有 endpoints 中存在（引用完整性检查）
- `modelId` 必须在指定 endpoint 的 `discoveredModels` 中（若存在，仅警告不阻断）

### 2. 扩展 `read_sage_config` 工具

在 `section` 枚举中添加 `"endpoints"`，支持单独查询 endpoints 配置（脱敏后）。

### 3. 安全与脱敏

- **apiKey 脱敏**：`read_sage_config` 返回 endpoints 时，`_redact_settings()` 已自动将 apiKey 替换为 `***`
- **写入加密**：`SettingsRepository.set_json()` 调用 `wrap_settings_json()` 透明加密 apiKey
- **审批机制**：`UpdateSageConfigTool` 风险级别为 `WRITE_LOCAL`，修改 endpoints/modelSelections 同样需要用户审批
- **审计日志**：修改后触发 `settings_changed` 事件（与前端设置页修改一致）

### 4. 配置生效

- **即时生效**：所有配置修改立即写入数据库，下次任务启动时读取最新配置
- **不影响已运行任务**：已启动的 run 使用启动时的配置快照

## 实施步骤

- [x] 步骤 1：添加白名单常量和验证函数
- [x] 步骤 2：添加辅助方法 `_handle_endpoint_action()` 和 `_handle_model_selection_update()`
- [x] 步骤 3：扩展 `UpdateSageConfigTool.execute()` 支持新 target
- [x] 步骤 4：扩展 `ReadSageConfigTool` 支持 `section="endpoints"`
- [x] 步骤 5：编写单元测试（23 个测试全通过）
- [ ] 步骤 6：本地验证（启动后端，使用工具修改配置，验证前端同步）
- [ ] 步骤 7：提交 commit 并推送
- [ ] 步骤 8：创建 PR 并等待 CI

## 风险评估

1. **安全风险**：低。复用现有白名单和加密机制，不引入新的攻击面
2. **兼容性风险**：低。纯新增功能，不影响现有 API
3. **数据一致性风险**：中。model_selection 的 endpointId 引用完整性检查可防止悬空引用
4. **测试覆盖**：需要充分的单元测试覆盖 CRUD 操作和边界情况

## 依赖

- 无外部依赖
- 复用现有 `SettingsRepository` 和 `SecretBox` 基础设施

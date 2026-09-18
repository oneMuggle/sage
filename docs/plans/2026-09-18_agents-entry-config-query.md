# 侧边栏 Agent 入口补全与 Sage 自身配置查询/修改工具实现计划

> **状态**：进行中（2026-09-18 创建）
> **分支**：`feat/agents-entry-config-query`
> **Worktree**：`.worktrees/feat-agents-entry-config-query`（backend:8792 / frontend:1447）

## 1. Context（背景与目标）

### 背景与问题
1. **侧边栏入口缺失（UI 阻断）**：
   前端代码中已实现完整的 `/agents` 页面（`src/pages/Agents.tsx`）及编辑表单（`EditAgentForm.tsx`），支持配置所有 Agent（含 primary、coder、reviewer、writer）的迭代上限、模型和系统提示词。但在 `src/widgets/layout/Sidebar.tsx` 的导航菜单中遗漏了该项，导致用户无法通过界面找到入口。
2. **会话中无法查询真实参数（LLM 缺乏自省能力）**：
   用户在对话中询问 LLM 当前系统参数（如 lane 迭代上限、子代理迭代上限、各 Agent 迭代上限）时，LLM 回复的往往是默认值或训练先验，因为这些动态配置并未注入到会话的 system prompt 中，且系统没有提供自省工具。
3. **无法通过自然语言修改参数**：
   用户期望能够在对话中直接让 Sage 调整自身配置（例如"将主助手最大迭代步数设为 20"或"将子代理迭代上限改为 10"）。

### 目标与交付成果
1. **UI 入口修复**：在侧边栏「更多」菜单中加入「智能体」（`/agents`）导航项。
2. **自省与配置工具**：
   - `read_sage_config`：查询当前系统的实际配置（orch 编排上限、各 Agent 迭代上限与属性、通用设置、当前模型选择等），自动对 API Key 等敏感凭据脱敏。
   - `update_sage_config`：安全地按字段白名单修改部分系统参数（如 `max_lane_iterations`, `max_subagent_iterations`, agent 的 `max_iterations`, 通用 `temperature` 等），声明为 `RiskClass.WRITE_LOCAL`，接入权限审批机制。
3. **主助手能力声明**：在主助手（primary）的工具列表及 prompt 中注册新工具，让 LLM 能够准确查询和应用配置变更。

---

## 2. 涉及的关键文件清单

### 前端文件
- `src/widgets/layout/Sidebar.tsx`：在 `moreNavItems` 中追加 `/agents` 导航配置。
- `src/widgets/layout/__tests__/Sidebar.test.tsx`：更新侧边栏菜单项数量与高亮断言。

### 后端文件
- `backend/domain/tool_names.py`：在 `BUILTIN_TOOL_NAMES` 中登记 `read_sage_config` 与 `update_sage_config`。
- `backend/tools/config_tool.py`（新建）：实现 `ReadSageConfigTool` 与 `UpdateSageConfigTool`。
- `backend/tools/__init__.py`：在 `register_all_tools()` 中完成工具实例化与注册。
- `backend/agents/profiles.py`：
  - 将两个工具加入 `_PRIMARY_SEED_TOOLS` 白名单。
  - 在主助手 prompt 结尾注入工具能力说明。
- `backend/domain/risk.py` / `tests/unit/test_risk.py`：为新工具声明风险类别（READ / WRITE_LOCAL）。

### 测试文件
- `backend/tests/unit/test_config_tool.py`（新建）：测试工具读取、脱敏、白名单校验及更新逻辑。

---

## 3. 技术方案设计

### 3.1 侧边栏入口设计
在 `src/widgets/layout/Sidebar.tsx` 的 `moreNavItems` 中添加：
```typescript
{ path: '/agents', label: t('sidebar.nav.agents'), icon: Bot }
```
- 图标采用 `lucide-react` 的 `Bot`。
- 文案复用已有 i18n 键 `sidebar.nav.agents`（中文："智能体"，英文："Agents"）。

### 3.2 工具 1：`read_sage_config`（配置查询）
- **风险等级**：`RiskClass.READ`（只读，自动放行）。
- **参数 Schema**：
  - `section` (string, enum: `["all", "orch", "agents", "general", "model_selections"]`，必填)。
- **核心逻辑**：
  - 调用 `SettingsRepository().get_json("app_settings")` 获取全局配置。
  - 调用 `AgentRepository().list_all()` 获取所有智能体配置（包括每个 agent 的 `max_iterations`）。
  - **敏感字段脱敏**：任何涉及 `apiKey`、`token` 的字段一律置为 `"***"` 或移除。
  - 返回字典结构，同时附带一段易于人类和 LLM 理解的格式化文字摘要。

### 3.3 工具 2：`update_sage_config`（配置修改）
- **风险等级**：`RiskClass.WRITE_LOCAL`（本地状态修改，触发标准权限审批流程）。
- **安全白名单拦截**：
  - **允许修改的项**：
    - `orch` 编排参数：`maxConcurrentSubagents`, `maxAggregateChars`, `maxSubagentResultChars`, `maxRetries`, `maxLaneIterations`, `maxSubagentIterations`, `runTokenBudget`, `subagentApprovalMode`。
    - `agent` 参数：指定 `agent_id` 的 `max_iterations` (1~50), `temperature`, `system_prompt`, `description`, `name`, `enabled`。
    - `general` 参数：`temperature`, `streaming`, `autoMemory`, `confirmDelete`, `timezone`。
  - **严禁修改的项（直接拒绝并报错）**：
    - 任何 `endpoints` 的 `apiKey`, `baseUrl`, `protocol`（防止凭证泄露或 SSRF）。
    - 任何 Agent 的 `tools` 列表（防止 LLM 越权自我提权）。
    - 文件系统关键路径如 `scratchRoot`, `worktreeIsolation`。
- **参数 Schema**：
  - `target` (string, enum: `["orch", "agent", "general"]`，必填)。
  - `agent_id` (string, 可选，当 `target="agent"` 时必填)。
  - `updates` (object, 包含要更新的键值对，必填)。
- **核心逻辑**：
  - 检查字段白名单，若包含越权字段则直接返回错误。
  - 修改 `orch`/`general` 时，与原 `app_settings` 做 deep merge 并保存。
  - 修改 `agent` 时，调用 `AgentRepository().update(agent_id, updates)`。
  - 返回修改成功通知，包含修改前后的值对比。

### 3.4 主助手集成与权限隔离
- 子代理（Subagents）通过 `SUBAGENT_TOOL_WHITELIST` 进行严格隔离，**严禁注册 `update_sage_config`**，保持子代理专注纯任务执行。
- 在 `backend/agents/profiles.py` 中为 `primary` 注入这两个工具，并在 system prompt 末尾明确说明其可用性。

---

## 4. 实施步骤（里程碑）

- [x] **步骤 1：前端侧边栏入口补齐**
  - 在 `src/widgets/layout/Sidebar.tsx` 中添加 `/agents` 项。
  - 运行侧边栏相关 vitest 单测并修复/更新断言。
- [x] **步骤 2：登记工具名与风险等级**
  - 在 `backend/domain/tool_names.py` 增加常量。
  - 在 `tests/unit/test_tool_names.py` 与 `tests/unit/test_risk.py` 补充登记。
- [x] **步骤 3：编写后端工具测试（TDD）**
  - 新建 `backend/tests/unit/test_config_tool.py`，覆盖读取、脱敏、白名单拦截、参数修改及非法字段防护。
- [x] **步骤 4：实现 `backend/tools/config_tool.py`**
  - 实现 `ReadSageConfigTool` 与 `UpdateSageConfigTool`。
  - 在 `backend/tools/__init__.py` 注册工具。
  - orch/general 写入前复用 `validate_settings_payload`，拒绝非法时区和 endpoint 语义值。
- [x] **步骤 5：注入主助手 Profile 与 Prompt**
  - 在 `backend/agents/profiles.py` 中向 `_PRIMARY_SEED_TOOLS` 添加工具名，并追加配置管理说明文本。
- [x] **步骤 6：全量验证**
  - 运行 pytest 测试新工具。
  - 运行前端 vitest 测试。

---

## 5. 验证方式

1. **单元测试验证**：
   - 后端：`pytest backend/tests/unit/test_config_tool.py`
   - 工具名锁：`pytest backend/tests/unit/test_tool_names.py backend/tests/unit/test_risk.py`
   - 前端：`npm run test:run src/widgets/layout/__tests__/Sidebar.*`
2. **端到端交互验证**：
   - 前端打开侧边栏，点击「更多」->「智能体」，确认正常跳转到 `/agents` 并展示主助手及其他 agent 列表。
   - 在对话中向主助手发送："请查询当前系统的编排迭代上限和主助手迭代上限"，验证其正确调用 `read_sage_config` 并返回真实配置。
   - 在对话中发送："请把主助手最大迭代次数改成 18"，验证其触发 `update_sage_config`，修改后查询确认已变为 18，且 Agents 管理页同步生效。

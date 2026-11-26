# 规则抽取草稿审阅 + AI 精炼

> 2026-11-25。把「从文档抽取规则」从单向落库改为三阶段工作流：**抽取预览 → AI 精炼 → 确认落盘**。抽取结果先进入草稿（不写数据库），用户逐条勾选/编辑、用自然语言指令让 AI 增删改规则（每条建议需逐条接受），最后批量提交。核心动机：一次性自动抽取永远无法覆盖全部规则，用户需要补充和修正的低门槛路径。

---

## 1. 背景与问题

改造前 `POST /api/v1/rules/extract` 返回扁平的 `Rule` 列表，前端 `RulesSubtabs` 直接建组 + 逐条 `createRule()` 落库。问题：

| # | 问题 | 影响 |
|---|------|------|
| P1 | 抽取即落库，无预检 | 错误规则混入，用户需事后逐条修改 |
| P2 | 无置信度展示 | 用户不知道哪些规则可信 |
| P3 | 冲突只以 warning 返回，无交互解决 | 用户只能手动删改 |
| P4 | 只能用表单修改（regex/params） | 门槛高，尤其是结构化参数 |
| P5 | 漏抽的规则只能从零手写 | 无法增量补充 |
| P6 | `_spec_to_rule()` 把 kind/params 扁平化为 ai_prompt 字符串 | 丢失结构化知识，无法做参数级编辑 |

对标：Grammarly 的置信度色标 + 逐条接受/拒绝、Cursor 的 diff 审查、ChatGPT Canvas 的文档+侧边对话、Google Docs 建议模式。

---

## 2. 数据模型

### 2.1 Rule 新增字段（v22 迁移）

`office_rules` 表新增三列（均可为空，向后兼容）：

| 列 | 类型 | 含义 |
|----|------|------|
| `structured_params` | TEXT (JSON) | 抽取引擎的原始结构化参数，如 `{"cjk_font":"宋体","size_pt":12}` |
| `confidence` | REAL | 抽取置信度 0–1 |
| `source_excerpt` | TEXT | 来源摘录，如"模板统计 156/164 段" |

`rule_repo.py` 负责 JSON 序列化/反序列化；`Rule` pydantic 模型新增同名可选字段。

### 2.2 草稿模型（不落库）

`POST /api/v1/rules/extract/draft` 返回 `DraftRuleItem`：

```json
{
  "temp_id": "draft_0",
  "name": "正文字体",
  "kind": "style.font",
  "params": {"cjk_font": "宋体", "size_pt": 12},
  "category": "style",
  "severity": "warning",
  "confidence": 0.95,
  "source_excerpt": "模板统计 156/164 段",
  "conflict_group": null,
  "suggested_check_mode": "ai",
  "suggested_ai_prompt": "检查文档是否满足规则「正文字体」……",
  "suggested_type": "format",
  "suggested_scope": "body",
  "description": ""
}
```

`temp_id`（`draft_N`）是草稿内临时标识，AI 精炼的 modify/delete 用它定位目标；提交时丢弃，由 `create_rule()` 生成正式 id。

---

## 3. API

| 端点 | 用途 |
|------|------|
| `POST /rules/extract/draft` | 抽取到草稿（复用 `extract_word_rules_async`，不写库）返回 `DraftRuleItem[] + conflicts + warnings` |
| `POST /rules/extract/commit` | 批量落库：`group_name`（或 `target_group_id` 追加到已有组）+ `CommitRuleItem[]`，返回 `{group_id, rules_created}` |
| `POST /rules/refine` | 自然语言指令 → 结构化动作列表（需 LLM 已配置，否则 503） |

旧的 `POST /rules/extract`（抽取即返回 Rule 列表）保留，兼容其他调用方。

---

## 4. AI 精炼引擎（`backend/office/rule_refine_llm.py`）

### 4.1 流程

```
用户指令 + 当前草稿规则(JSON)
  → LLM 返回 JSON 数组（add / modify / delete / explain）
  → normalize_actions() 确定性校验
  → 动作列表返回前端 → 用户逐条接受/拒绝
```

### 4.2 动作协议

| type | 载荷 | 前端行为 |
|------|------|----------|
| `add` | `rule: {name, kind, params, severity, description, ai_prompt, type, scope}` | 追加草稿规则（选中态，标记 dirty） |
| `modify` | `temp_id` + `patch`（白名单键：name/params/severity/description/ai_prompt/type/scope） | 显示 before→after diff |
| `delete` | `temp_id` | 删除线展示 |
| `explain` | `explanation` | 纯文字回答，无接受/拒绝 |

### 4.3 确定性校验（不信任 LLM）

- `modify`/`delete` 的 `temp_id` 必须存在于当前草稿，否则丢弃并计数（`refine_action_rejected` warning）
- `patch` 只允许白名单键；非法枚举值（severity/type/scope）被剥除；剥空则整条丢弃
- `add` 必须有非空 name；type/scope/severity 非法时回退默认值；ai_prompt 缺省时合成
- 最多 20 条动作；LLM 调用失败/解析失败均降级为空动作 + warning，不抛错

**关键设计**：任何 AI 建议都要用户显式接受才应用到草稿；草稿确认前不进数据库。LLM 是建议者，不是执行者。

---

## 5. 前端结构

```
RulesSubtabs.tsx          「从本文档抽取」→ extractDraft() → 打开草稿弹层
  └─ RuleExtractionDraft.tsx       双栏弹层：左规则列表 / 右 AI 精炼
       ├─ RuleDraftCard.tsx        单条草稿：置信度色标(🟢≥80% 🟡50-79% 🔴<50%)、
       │                           参数摘要、来源摘录、勾选、改名、删除
       ├─ RuleConflictResolver.tsx 冲突组并排对比，勾选保留版本
       └─ RuleRefinePanel.tsx      AI 对话：输入指令 → 动作 diff 卡片
            └─ RuleDiffCard.tsx    add 绿 + / modify 红删绿增 / delete 红 −
                                   / explain 纯文本；逐条 接受/拒绝 + 全部接受

ruleDraftStore.ts (zustand + persist)
  rules: DraftRule[]（selected 默认 = confidence ≥ 0.5，dirty 标记已编辑）
  applyRefineAction() 把已接受的 add/modify/delete 原子应用到草稿
  localStorage 持久化（key `sage-rule-draft-v1`，仅 rules/conflicts/warnings/
  sourceName/workspacePath；isOpen/loading/error 不持久化 → 刷新后面板不弹，
  规则页显示「继续编辑上次草稿」横幅，用户主动恢复）
```

提交时前端把草稿映射为 `CommitRuleItem`（含 structured_params/confidence/source_excerpt），成功后 bump `reloadKey` 并聚焦新组。面板打开时并行拉取已有规则组列表，Footer 的「提交到」选择器可指定追加目标：同名规则自动跳过（merge 预览显示"将新增 N 条，跳过 M 条同名"），`确认落盘` 按钮计数随之调整为实际新增数。

### 5.1 Phase 3 增强（同一面板内）

| 功能 | 实现 |
|------|------|
| 置信度筛选 | 工具栏下拉（全部/高≥0.8/中0.5-0.8/低<0.5），仅影响列表展示 |
| 批量选择 | 全选 / 全不选 / 仅选高置信度（`selectByConfidence(0.8)`） |
| 手动添加规则 | 行内表单（名称必填 + severity + 说明），`addRule()` 以 confidence=1.0、来源"手动添加"入草稿 |
| 每条规则 AI 修改 | RuleDraftCard 的「AI 修改」把预填指令（`修改规则「X」：`）写入 store `pendingInstruction`，右侧精炼面板消费后聚焦输入框 |
| 提交到已有组 | `target_group_id` + 同名跳过合并预览（不做覆盖/更新，避免误改已有规则） |

---

## 6. 关键取舍

| 决策 | 理由 |
|------|------|
| 草稿持久化到 localStorage、不做服务端草稿 | 避免草稿生命周期/清理问题；刷新/重启不丢未完成审阅。持久化范围排除 isOpen（刷新后不弹窗，用横幅提示恢复） |
| commit 未包事务 | SQLite 本地单用户，部分失败概率低；失败时 toast 报错、组保留可手动清理。后续可加整组回滚 |
| 追加到已有组时同名跳过（不覆盖） | 覆盖会静默改写用户已有规则；跳过 + 预览计数最保守可预期，覆盖/更新留作显式操作 |
| AI 精炼同时提供全局侧栏与逐条快捷入口 | 全局对话处理跨规则指令（"去掉页边距相关的规则"）；逐条「AI 修改」只预填指令、仍走同一对话，逻辑不分叉 |
| 手动添加规则 confidence=1.0 | 用户亲自编写即最高可信度；"仅选高置信度"批量操作天然包含手动规则 |
| 新增字段全部可空 | 旧数据无需回填，规则包导入导出保持向后兼容（`parseRulePack` 忽略未知字段） |

---

## 7. 测试

| 层 | 覆盖 |
|----|------|
| `backend/tests/unit/office/test_rule_refine_llm.py` | 解析容错（markdown 围栏）、temp_id/patch 校验、add 默认值、LLM 失败/解析失败降级 |
| `backend/tests/integration/test_rules_routes.py` | draft 不落库、commit 持久化 metadata、追加到已有组、404、refine 503/动作校验 |
| `src/features/office/rules/__tests__/RuleRefinePanel.test.tsx` | 指令→diff→接受应用/拒绝不变 |
| `src/features/office/rules/__tests__/RulesSubtabs.test.tsx` | 抽取打开草稿、低置信度默认不选、提交仅含选中项、错误展示、加载态、持久化草稿恢复横幅 |
| `src/features/office/rules/__tests__/RuleExtractionDraft.phase3.test.tsx` | 置信度筛选、仅选高置信度、手动添加规则、已有组同名跳过合并预览与提交载荷 |

---

## 8. 已知限制

- 追加到已有组按**规则名**判重（改名后视为新规则）；不做规则内容的深度 diff
- 筛选项只影响展示，不改变选中状态（配合"仅选高置信度"使用）
- 精炼对话历史不持久化（刷新后仅草稿数据保留）
- i18n：新增面板文案为中文硬编码，未接入 zh/en 字典

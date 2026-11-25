# 文档规则抽取优化方案：AI 辅助补充与编辑

> 状态：**草案** | 日期：2026-11-25 | 分支：`feat/rule-extraction-refine`

## 1. 背景与目标

### 1.1 现状问题

当前规则抽取是一个**单向流水线**：点击"从本文档抽取" → 自动生成规则组 → 逐条写入数据库。
用户没有机会在落盘前审阅、筛选、修正抽取结果。具体问题：

| # | 问题 | 影响 |
|---|------|------|
| P1 | 抽取结果直接落盘，无法预检 | 错误规则混入，用户需逐条手动修 |
| P2 | 无置信度展示 | 用户不知道哪些规则靠谱、哪些需要关注 |
| P3 | 冲突只弹 toast，无法交互解决 | 用户只能手动删改，不知道冲突原因 |
| P4 | 无法用自然语言调整规则 | 用户必须理解 regex/params 才能修改 |
| P5 | 无法增量补充 | 漏抽的规则只能从零手写 |
| P6 | 结构化知识（kind/params）被扁平化为 ai_prompt | 丢失精度，无法做结构化编辑 |

### 1.2 目标

**让用户在 AI 辅助下，高效地获得一份精确、完整的规则集。**

核心原则：
- **先审后存**：抽取结果先展示草稿，用户确认后再落盘
- **AI 辅助编辑**：自然语言指令修改规则，降低门槛
- **增量迭代**：支持多次抽取合并、手动补充、AI 润色

### 1.3 主流 AI 应用参考

| 产品 | 设计模式 | 可借鉴点 |
|------|----------|----------|
| **Grammarly** | 逐条建议 + 置信度色标 + 一键接受/拒绝 | 规则列表的置信度可视化 + 批量操作 |
| **Cursor (Code AI)** | Diff 视图 + 逐块 Accept/Reject | 规则修改的前后对比 |
| **Notion AI** | 选中文本 → AI 操作菜单 → 内联修改 | 选中规则 → "AI 修改" → 对话式微调 |
| **ChatGPT Canvas** | 文档 + 侧边对话 → AI 按指令修改文档 | 规则列表 + 侧边对话 → AI 按指令增删改 |
| **Google Docs 建议模式** | 追踪修改 + 逐条接受/拒绝 | 批量操作 + 逐条操作并存 |

## 2. 方案设计

### 2.1 整体架构：三阶段工作流

```
┌──────────────┐    ┌──────────────────┐    ┌──────────────┐
│  ① 抽取预览  │ →  │  ② AI 辅助精炼   │ →  │  ③ 确认落盘   │
│  Draft Review │    │  AI Refinement   │    │  Commit       │
└──────────────┘    └──────────────────┘    └──────────────┘
```

**① 抽取预览（Draft Review）**
- 抽取结果展示为**草稿规则列表**（不写数据库）
- 每条规则显示：名称、分类、参数值、置信度色标、来源摘录
- 用户可勾选/取消、手动编辑参数、删除不需要的规则
- 冲突规则高亮并排展示，用户选择保留哪个

**② AI 辅助精炼（AI Refinement）**
- 侧边打开对话面板，用户用自然语言指令修改规则集
- 支持的指令类型：
  - **补充**：`"加上：参考文献格式采用 GB/T 7714"` → AI 生成新规则
  - **修改**：`"正文字体改成宋体 小四"` → AI 修改现有规则参数
  - **删除**：`"去掉页边距相关的规则"` → AI 标记删除
  - **合并**：`"把两个字体规则合并成一个"` → AI 合并
  - **解释**：`"这条规则的置信度为什么这么低？"` → AI 解释来源
- 每次 AI 操作展示为 diff 卡片，用户逐条 Accept/Reject

**③ 确认落盘（Commit）**
- 显示最终规则清单摘要（N 条规则，M 条修改，K 条新增）
- 用户确认后批量写入数据库
- 支持"保存为草稿"（下次继续编辑）

### 2.2 详细交互设计

#### 2.2.1 抽取预览页

```
┌─────────────────────────────────────────────────────┐
│  📄 从《论文格式规范.docx》抽取到 15 条规则          │
│  [全部接受] [全部拒绝] [发送给 AI 精炼 →]            │
├─────────────────────────────────────────────────────┤
│                                                     │
│  ☑ 🟢 正文字体          style.font                 │
│    字体：宋体 (CJK) / Times New Roman (Latin)       │
│    字号：小四 (12pt)                                 │
│    置信度：95%  来源：模板统计（156/164 段）          │
│    [编辑] [删除] [AI 修改]                           │
│                                                     │
│  ☑ 🟡 行间距            style.paragraph             │
│    间距：固定值 20pt                                  │
│    置信度：72%  来源：模板统计（118/164 段）          │
│    ⚠️ 与"段前段后间距"存在潜在冲突                   │
│    [编辑] [删除] [AI 修改]                           │
│                                                     │
│  ☐ 🔴 首行缩进          style.paragraph             │
│    缩进：2 字符 (0.85cm)                              │
│    置信度：45%  来源：LLM 推测                       │
│    ⚠️ 置信度低：仅 12/164 段符合，建议人工确认        │
│    [编辑] [删除] [AI 修改]                           │
│                                                     │
│  ── 冲突组 ─────────────────────────────────        │
│                                                     │
│  ⚠️ 页面边距冲突（2 条规则）                         │
│  ┌─────────────────┬──────────────────┐             │
│  │ A: 上2.54 下2.54 │ B: 上3.0 下3.0   │             │
│  │ 左3.17 右3.17    │ 左2.5 右2.5      │             │
│  │ 置信度 88%       │ 置信度 65%       │             │
│  │ [保留 A]         │ [保留 B]         │             │
│  └─────────────────┴──────────────────┘             │
│                                                     │
│  [+ 手动添加规则]                                    │
└─────────────────────────────────────────────────────┘
```

**置信度色标**：
- 🟢 ≥80%：高置信度，可直接接受
- 🟡 50–79%：中等置信度，建议检查
- 🔴 <50%：低置信度，需要人工确认

**默认勾选策略**：
- 🟢 自动勾选
- 🟡 自动勾选但高亮
- 🔴 默认不勾选，提示用户审查

#### 2.2.2 AI 辅助精炼面板

```
┌────────────────────────────────────┬──────────────────┐
│  规则草稿 (15)                     │  💬 AI 精炼       │
│                                    │                  │
│  ☑ 正文字体: 宋体 小四             │  输入指令...       │
│  ☑ 行间距: 固定 20pt              │  ┌──────────────┐│
│  ☑ 标题字体: 黑体 三号             │  │ 用户:        ││
│  ...                               │  │ "加上参考文献 ││
│                                    │  │  格式要求"   ││
│                                    │  └──────────────┘│
│                                    │  ┌──────────────┐│
│                                    │  │ AI 建议:     ││
│                                    │  │ + 参考文献格式││
│                                    │  │   type:citation│
│                                    │  │   pattern:    ││
│                                    │  │   "GB/T 7714" ││
│                                    │  │ [接受] [拒绝] ││
│                                    │  └──────────────┘│
│                                    │                  │
│                                    │  ┌──────────────┐│
│                                    │  │ 用户:        ││
│                                    │  │ "行间距改成  ││
│                                    │  │  1.5倍行距"  ││
│                                    │  └──────────────┘│
│                                    │  ┌──────────────┐│
│                                    │  │ AI 建议:     ││
│                                    │  │ ~ 行间距:     ││
│                                    │  │ - 固定 20pt  ││
│                                    │  │ + 1.5倍行距  ││
│                                    │  │ [接受] [拒绝] ││
│                                    │  └──────────────┘│
│                                    │                  │
│  [+ 手动添加]                      │  [全部接受]       │
│  [发送给 AI →]                     │  [确认落盘 →]     │
└────────────────────────────────────┴──────────────────┘
```

**AI 指令类型识别**（后端 LLM 驱动）：

| 用户说 | AI 操作 | Diff 展示 |
|--------|---------|-----------|
| "加上 XXX 规则" | 新增规则 | `+ 新规则卡片` |
| "把 XXX 改成 YYY" | 修改现有规则 | `~ 修改前后对比` |
| "去掉 XXX" | 删除规则 | `- 删除线` |
| "这两条合并" | 合并规则 | `~ 合并后结果` |
| "为什么这条置信度低" | 解释（不修改） | 文字说明 |
| "按这个模板重新检查一遍" | 批量修正 | 多条 diff |

#### 2.2.3 快捷操作菜单

每条规则上的"AI 修改"按钮展开快捷菜单：

```
┌─────────────────────────┐
│  🤖 AI 快捷操作         │
├─────────────────────────┤
│  修改参数值...           │
│  合并到其他规则...       │
│  拆分规则...            │
│  提升/降低置信度...      │
│  解释这条规则           │
│  从原文重新抽取...       │
│  ─────────────────────  │
│  自由输入指令...         │
└─────────────────────────┘
```

### 2.3 后端改动

#### 2.3.1 新增 API

**POST `/api/v1/rules/extract/draft`** — 抽取到草稿（不落库）

```python
# 请求
{
    "workspace_path": str,
    "file_path": str,
    "file_type": "template" | "spec",
    "use_llm": bool
}

# 响应 — 保留完整结构化信息
{
    "draft_id": "draft_xxx",
    "rules": [
        {
            "temp_id": "rule_0",        # 草稿内临时 ID
            "name": "正文字体",
            "kind": "style.font",       # 保留结构化 kind
            "params": {                 # 保留结构化参数
                "cjk_font": "宋体",
                "latin_font": "Times New Roman",
                "size_pt": 12
            },
            "category": "style",
            "severity": "warning",
            "confidence": 0.95,
            "source_excerpt": "模板统计 156/164 段",
            "conflict_group": null,
            "suggested_check_mode": "ai",
            "suggested_ai_prompt": "正文应使用宋体..."
        }
    ],
    "conflicts": [...],
    "warnings": [...]
}
```

**POST `/api/v1/rules/refine`** — AI 精炼指令

```python
# 请求
{
    "draft_id": "draft_xxx",
    "instruction": "把行间距改成1.5倍行距",
    "current_rules": [...]    # 当前草稿状态
}

# 响应 — 结构化 diff
{
    "actions": [
        {
            "type": "modify",
            "temp_id": "rule_3",
            "before": {"params": {"line_spacing": "fixed_20pt"}},
            "after": {"params": {"line_spacing": "multiple_1.5"}},
            "explanation": "将行间距从固定 20pt 改为 1.5 倍行距"
        }
    ]
}
```

**POST `/api/v1/rules/extract/commit`** — 确认落盘

```python
# 请求
{
    "draft_id": "draft_xxx",
    "group_name": "论文格式规范",
    "rules": [...],           # 最终确认的规则列表
    "target_group_id": null   # null = 新建组; 非 null = 合并到已有组
}
```

#### 2.3.2 保留结构化数据

关键改动：**不再在 `_spec_to_rule()` 中丢失 kind/params**。

方案：在 `Rule` 模型上新增 `structured_params` JSON 字段（可选），
存储抽取引擎的结构化参数。当 `check_mode=regex` 时用 `pattern`，
当 `check_mode=ai` 时用 `ai_prompt`，但 `structured_params` 始终保留
原始抽取结果，供前端编辑和 AI 精炼使用。

```python
# backend/office/rule_models.py
class Rule(BaseModel):
    # ... 现有字段 ...
    structured_params: Optional[dict] = None  # 新增：抽取引擎结构化参数
    confidence: Optional[float] = None        # 新增：置信度
    source_excerpt: Optional[str] = None      # 新增：来源摘录
```

#### 2.3.3 AI 精炼引擎

新建 `backend/office/rule_refine_llm.py`：

- 接收当前规则列表 + 用户自然语言指令
- 构造 prompt：将规则列表序列化为结构化 JSON，要求 LLM 返回操作列表
- 每个操作包含 type（add/modify/delete/merge/explain）+ 目标 rule temp_id + 变更内容
- 严格的 JSON schema 约束 + 参数校验（复用 `validate_llm_params()`）
- 返回结构化 diff，前端渲染为 Accept/Reject 卡片

### 2.4 前端改动

#### 2.4.1 新增组件

| 组件 | 路径 | 职责 |
|------|------|------|
| `RuleExtractionDraft` | `src/features/office/rules/RuleExtractionDraft.tsx` | 抽取预览页主容器 |
| `RuleDraftCard` | `src/features/office/rules/RuleDraftCard.tsx` | 单条规则草稿卡片 |
| `RuleConflictResolver` | `src/features/office/rules/RuleConflictResolver.tsx` | 冲突解决面板 |
| `RuleRefinePanel` | `src/features/office/rules/RuleRefinePanel.tsx` | AI 精炼对话面板 |
| `RuleDiffCard` | `src/features/office/rules/RuleDiffCard.tsx` | AI 修改 diff 展示 |
| `ruleDraftStore` | `src/features/office/rules/ruleDraftStore.ts` | Zustand 草稿状态管理 |

#### 2.4.2 修改现有组件

| 组件 | 改动 |
|------|------|
| `RulesSubtabs.tsx` | "从本文档抽取" 按钮改为打开 `RuleExtractionDraft` 而非直接落盘 |
| `RuleDetailPanel.tsx` | 增加 `structured_params` 编辑区 + "AI 修改"按钮 |
| `OfficeSpecLibrary.tsx` | 抽取预览流程统一复用 `RuleExtractionDraft` |

#### 2.4.3 状态管理

```typescript
// ruleDraftStore.ts
interface RuleDraft {
  tempId: string;
  rule: Rule;
  confidence: number;
  sourceExcerpt: string;
  selected: boolean;     // 用户是否选择保留
  dirty: boolean;        // 是否被修改过
  pendingDiff?: DiffAction;  // AI 建议的待确认修改
}

interface DraftState {
  draftId: string | null;
  rules: RuleDraft[];
  conflicts: Conflict[];
  chatHistory: ChatMessage[];
  phase: 'review' | 'refine' | 'commit';
}
```

## 3. 实施步骤

### Phase 1：抽取预览（MVP）

> 目标：先审后存，解决 P1/P2/P3

- [x] **M1** 后端：新增 `POST /api/v1/rules/extract/draft` 接口，返回草稿格式
- [x] **M2** 后端：Rule 模型增加 `structured_params` / `confidence` / `source_excerpt` 字段 + DB 迁移
- [x] **M3** 前端：新建 `RuleExtractionDraft` 组件 — 草稿规则列表 + 置信度色标
- [x] **M4** 前端：新建 `RuleDraftCard` — 单条规则展示 + 勾选/编辑/删除
- [x] **M5** 前端：新建 `RuleConflictResolver` — 冲突并排展示 + 选择保留
- [x] **M6** 前端：修改 `RulesSubtabs.tsx` — "从本文档抽取" → 打开预览而非直接落盘
- [x] **M7** 前端：新建 `ruleDraftStore` — Zustand 草稿状态管理
- [x] **M8** 后端：新增 `POST /api/v1/rules/extract/commit` — 批量落盘
- [x] **M9** 集成测试 + 手动验证

### Phase 2：AI 辅助精炼

> 目标：自然语言修改规则，解决 P4/P5

- [x] **M10** 后端：新建 `rule_refine_llm.py` — AI 精炼引擎
- [x] **M11** 后端：新增 `POST /api/v1/rules/refine` 接口
- [x] **M12** 前端：新建 `RuleRefinePanel` — 侧边对话面板
- [x] **M13** 前端：新建 `RuleDiffCard` — Accept/Reject diff 展示
- [ ] **M14** 前端：RuleDraftCard 增加"AI 修改"快捷菜单
- [ ] **M15** 前端：手动添加规则表单（支持自然语言 → 结构化规则转换）
- [x] **M16** 集成测试 + LLM 输出质量验证

### Phase 3：增量迭代

> 目标：支持已有规则组的增量更新，解决 P6

- [ ] **M17** 后端：支持 `target_group_id` — 抽取到已有规则组 + diff 合并
- [ ] **M18** 前端：已有规则组的"重新抽取 + 对比"流程
- [ ] **M19** 前端：规则草稿保存/恢复（localStorage 持久化）
- [ ] **M20** 前端：批量操作优化（全选/反选/按置信度筛选）

## 4. 涉及的文件与模块

### 后端

| 文件 | 改动类型 |
|------|----------|
| `backend/api/rules_routes.py` | 修改：新增 draft/refine/commit 端点 |
| `backend/office/rule_models.py` | 修改：Rule 增加字段 |
| `backend/data/migrations/v17_office_rules.py` | 参考：新迁移脚本 |
| `backend/office/rule_refine_llm.py` | 新增：AI 精炼引擎 |
| `backend/office/word_rule_extract.py` | 小改：抽取结果增加 confidence/source 透传 |
| `backend/office/word_rulepack_models.py` | 小改：WordRuleSpec 增加 confidence 字段 |

### 前端

| 文件 | 改动类型 |
|------|----------|
| `src/features/office/rules/RuleExtractionDraft.tsx` | 新增 |
| `src/features/office/rules/RuleDraftCard.tsx` | 新增 |
| `src/features/office/rules/RuleConflictResolver.tsx` | 新增 |
| `src/features/office/rules/RuleRefinePanel.tsx` | 新增 |
| `src/features/office/rules/RuleDiffCard.tsx` | 新增 |
| `src/features/office/rules/ruleDraftStore.ts` | 新增 |
| `src/features/office/rules/RulesSubtabs.tsx` | 修改 |
| `src/features/office/rules/RuleDetailPanel.tsx` | 修改 |
| `src/shared/api/officeRulesApi.ts` | 修改：新增 draft/refine/commit 调用 |

## 5. 风险评估

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| LLM 精炼指令理解错误 | 中 | 所有 AI 操作都需用户 Accept，不自动应用；严格 JSON schema + 参数校验 |
| 草稿状态丢失（页面刷新） | 低 | localStorage 持久化草稿；Phase 3 支持服务端草稿 |
| DB 迁移影响现有规则 | 低 | 新增字段均为 Optional，向后兼容 |
| 抽取到已有组的 diff 合并复杂 | 中 | Phase 3 实现，先用"新建组"模式 |
| AI 精炼延迟（LLM 调用） | 低 | 流式返回 + 加载态；精炼不阻塞手动编辑 |

## 6. 与现有功能的关系

- **Spec Library**（OfficeSpecLibrary）：Phase 1 复用 `RuleExtractionDraft` 组件，
  统一两个抽取入口的预览体验
- **规则审计**（AI Audit）：抽取预览不影响审计流程；审计结果中的规则来源
  标记保持不变
- **Rule Pack 导入导出**：`structured_params` / `confidence` 作为可选字段导出，
  不影响跨版本兼容

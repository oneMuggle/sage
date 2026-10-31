# 项目规程（Playbook）：可配置、可核验、可分享的项目管理方案

> 日期：2026-10-31
> 状态：已实施 P0/P1（2026-10-31；技术细节见 `docs/technical/115-project-playbook.md`）
> 分支：`feat/project-playbook`
> 前置阅读：`docs/plans/2026-10-29_project-management-simplification.md`、`docs/plans/2026-10-27_project-governance-ai.md`、`docs/plans/2026-10-12_ai-project-enhancements.md`
> 对标：Claude Projects / ChatGPT Projects / Cursor Rules / Claude Code Skills / Notion 项目模板 / Linear-Jira 工作流 / GitHub Issue Forms / DMPTool / PRISMA / OSF

---

## 1. 背景与目标

### 1.1 用户诉求

同一个 Sage 项目里，不同性质的项目应当有不同的管理方式：

- **科研课题**：开题 → 实施 → 结题，每个阶段有不同文档要求（开题报告、伦理审批、原始数据、结题报告、经费决算……）；
- **代码工程**：规划设计 → 研发 → 测试 → 发布 → 维护，每个阶段有不同的工程产物（ADR、测试报告、发布日志……）；
- **公文案卷**：立卷 → 编制 → 签发，对目录层级和版式有硬性要求。

用户希望：

1. **AI 辅助确定规则**：不用自己从零设计目录层级、阶段划分和文档清单；
2. **AI 按规则给管理建议**：知道"现在该做什么、缺什么、下一步是什么"；
3. **经用户批准后自动归类与识别阶段**：扫描现有文件，判断处在哪个阶段、本阶段资料是否完整；
4. **规则可导出、可分享**：一份规程可以在用户之间传递、复用、二次修改。

### 1.2 现状能力盘点（2026-10-31 代码实测）

| 能力 | 现状 | 位置 |
|---|---|---|
| 项目注册与类型 | `projects` 表：path/name/type/sub_type/stage/vcs_mode/bootstrap_state | `backend/data/database.py:960` |
| 两级类型检测 | coding/research/business/personal + 20 个子类型，确定性信号打分 | `backend/services/project_type_detector.py`、`project_subtypes.py` |
| 形态蓝图 | 四类项目各自的目录、阶段、规则包、推荐里程碑、SAGE.md 提示 | `backend/services/project_archetype_scaffold.py:39`、`src/features/project-type/archetypeBlueprints.ts:43` |
| 一键脚手架 | 创建类型化目录、SAGE.md、默认约束、默认里程碑 | `POST /projects/{id}/scaffold` |
| AI 初始化 | 画像 + LLM 分析 → SAGE.md/规则/里程碑/git init 建议，逐项 apply | `POST /projects/{id}/bootstrap/preview|apply` |
| 规则（约束） | category/content/trigger_pattern/priority，注入 system prompt | `project_constraint_repo.py`、`chat/project_context.py:481` |
| 里程碑 | stage/status/parent_id/due_date，可按阶段统计 | `project_milestone_repo.py` |
| 项目资料 / 画像 | 资料池 + 语义检索 + AI 记忆 | `project_material_repo.py`、`memory/project-profile` |
| 工作区扫描 | 资产台账、Office/科研产物识别、SAGE.md 读写、检查点 | `project_workspace_inspector.py` |
| 进度顾问 | 健康分 + 风险 + 建议，30 分钟缓存，确定性降级 | `project_advisor.py` |
| 前端项目页 | 3 Tab（概览/知识/设置），AI 初始化面板、形态卡片、顾问卡 | `src/pages/ProjectGovernance.tsx` |

**结论：地基完整，缺的是"项目方法论"这一层。**

### 1.3 差距（本方案要解决的）

1. **蓝图是一次性的**：目录/阶段/规则只在脚手架时使用，之后不参与治理；用户看不到"这个阶段应该有哪些文件"。
2. **阶段是手填的**：`project_stage` 只有一个下拉框，没有阶段进入/退出条件，没有识别与推进建议。
3. **没有完整性模型**：后端没有项目级 checklist；无法回答"开题材料齐了吗"。
4. **规则不可移植**：约束模板只能单条导入，没有"整套管理方案"的导出/导入。
5. **AI 建议与项目方法论脱节**：顾问只看里程碑数量、Git 状态，不知道"当前阶段应当交付什么"。

### 1.4 成功指标

| 指标 | 现状 | 目标 |
|---|---|---|
| 项目绑定规程的比例 | 0 | ≥ 60%（新建项目 90 天内） |
| 完整性检查每周使用率 | 0 | ≥ 30% 活跃项目 |
| 阶段识别建议被确认率 | 无 | ≥ 70% |
| 管理建议采纳率（含阶段推进、补文档） | 无埋点 | ≥ 30% |
| 规程导出 → 他人导入成功率 | 无 | ≥ 90%（同版本 Sage） |
| 默认界面新增术语负担 | — | 只出现"项目规程 / 阶段 / 待补材料"三个词 |

---

## 2. 对标主流 AI 应用与工具

| 产品 / 标准 | 规则载体 | 阶段模型 | 完整性校验 | AI 辅助 | 可分享 | 可借鉴点 | 缺口 |
|---|---|---|---|---|---|---|---|
| Claude Projects | 项目 instructions + knowledge | 无 | 无 | 有 | 弱 | 项目级上下文隔离 | 无方法论 |
| ChatGPT Projects | 同上 | 无 | 无 | 有 | 弱 | 同上 | 同上 |
| Cursor Rules / AGENTS.md / CLAUDE.md | 版本化 Markdown 规则文件 | 无 | 无 | 生成规则 | **强**（随仓库） | 声明式、可移植、按路径触发 | 无阶段/文档要求 |
| Claude Code Skills（SKILL.md） | 打包的过程性知识 + 资源 | 无 | 无 | 按需调用 | 强 | 规程可打包成 skill 分发 | 无项目状态 |
| Notion 项目模板 | 模板页 + 数据库 | 状态字段 | 复选框 | 弱 | 强（模板中心） | 模板复制、清单化 | 非本地、无文件核验 |
| Linear / Jira 工作流 | 项目模板 + 状态机 | **强**（状态 + 必填字段） | 必填字段 | 弱 | 中 | 阶段门禁、自动化 | 不面向本地文件 |
| GitHub Issue Forms | YAML schema | 无 | **强**（required 字段） | 无 | 强 | 模式校验、导入即校验 | 仅表单 |
| DMPTool（科研数据管理计划） | 结构化问卷 | 无 | 按资助方清单 | 有 | 强 | 学科/资助方定制问卷 | 仅数据管理 |
| PRISMA / PRISMA-ScR | 报告清单 | 无 | **强**（条目勾选） | 无 | 强 | 权威 checklist | 仅报告 |
| OSF Registrations | 注册表单 | 阶段 | 必填项 | 弱 | 强 | 阶段化提交 | 云端 |

**结论**：主流 AI 应用擅长"可移植的规则文件 + AI 生成"，主流项目管理工具擅长"阶段状态机 + 必填项校验"，科研工具擅长"权威清单"。Sage 的机会是把三者合成一个**本地优先、AI 辅助编写、用户批准后执行**的规程系统，并复用已有的项目/文件/会话底座。

---

## 3. 设计原则

1. **结构化优先，AI 增强**：规程是版本化的 JSON 规格（可校验、可 diff、可导出），LLM 只负责"帮你写"和"帮你判断内容"，不承担唯一事实源。
2. **确定性降级**：没有 LLM 时，阶段识别与完整性检查仍可基于文件扫描完成，端点不 5xx（沿用 bootstrap/advisor 的既有做法）。
3. **批准后执行**：识别阶段、创建目录/文档骨架、归类文件、导入规则，全部先预览再执行；**永不静默移动用户文件**。
4. **渐进披露**：默认只显示"当前阶段 + 完成度 + 缺什么 + 下一步"；编辑规程收进高级设置。
5. **单一事实源**：阶段/目录/规则/里程碑的权威定义只在规程中；约束和里程碑是规程的"投影"，按内容 hash 幂等同步，不反向污染。
6. **可移植**：导出文件不依赖 Sage 内部 ID，只含规程定义 + 可选空目录骨架 + 可选文档模板；人类可读版本与 Agent 可读版本同时提供。
7. **不重复造轮子**：复用 `ProjectProfiler`、`ProjectAnalysisAgent`、`ProjectRuleGenerator`、`project_advisor`、约束/里程碑仓库、检查点与安全写文件原语。

---

## 4. 方案对比与推荐

### 4.1 三种路径

| 路径 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A. 扩展现有蓝图 | 在 `archetypeBlueprints`/`project_archetype_scaffold` 里给每个阶段加文档要求，前端直接读取 | 改动最小，1–2 天 | 静态、不可编辑、不可导出；前后端两份蓝图易漂移；无法承载用户自定义规程 |
| B. 独立 Playbook 子系统（推荐） | 新增版本化规程规格 + 项目绑定快照 + 审计引擎 + AI 编写 + 导入导出 | 可定制、可核验、可分享；与现有能力正交；为后续"规程市场"留口 | 需要新表、新 API、新 UI，工作量最大 |
| C. 纯 AI 顾问模式 | 为每个项目生成一份 Markdown "管理手册"，让 LLM 对照手册判断 | 实现快、灵活 | 结果不确定、不可审计、难导出复用、无法离线核验 |

### 4.2 推荐：B（结构化内核 + C 的 AI 能力）

- **内核**：Playbook 规格 + 确定性审计器（可离线、可测试、可导出）。
- **AI 层**：AI 定制规程、内容级完整性判断、阶段歧义裁决、建议措辞。
- **兼容层**：现有 `archetypeBlueprints` 转为"内置规程的展示投影"，前端逐步改为从后端 `GET /playbooks` 拉取，消除双份漂移。
- **演进路径**：A 作为 P0 的临时展示（卡片先读内置规程），B 的规格与审计器在 P0 同步落地，避免二次返工。

---

## 5. 规程规格（Playbook Spec）

### 5.1 设计目标

- 表达：阶段流水线、每阶段目录与文档要求、内容检查项、规则、推荐里程碑、建议动作。
- 可校验：JSON Schema 级校验（字段、必填、版本）。
- 可 diff：导入时按 `id` 对比阶段/条目，生成变更预览。
- 可移植：不引用 Sage 内部 ID；路径使用项目根相对路径；不包含用户内容。

### 5.2 示例（科研课题，合成数据）

```json
{
  "schema_version": "1.0",
  "id": "cn-research-grant",
  "name": "科研课题（开题 · 实施 · 结题）",
  "description": "面向国家/省部级科研课题与学位论文的开题—实施—结题全周期管理",
  "applies_to": {
    "project_types": ["research"],
    "sub_types": ["grant_proposal", "academic_paper", "lab_experiment"]
  },
  "directory_layout": [
    { "path": "01_开题", "required": true, "purpose": "开题报告、任务书、伦理审批" },
    { "path": "02_实施/数据", "required": true, "purpose": "原始数据、实验记录、代码" },
    { "path": "03_成果", "required": true, "purpose": "论文、专利、软件著作权" },
    { "path": "04_结题", "required": true, "purpose": "结题报告、经费决算、验收材料" }
  ],
  "stages": [
    {
      "id": "proposal",
      "label": "开题",
      "order": 1,
      "objective": "明确研究问题、假设、技术路线与可行性",
      "artifacts": [
        {
          "id": "proposal_report",
          "label": "开题报告",
          "required": true,
          "match": {
            "globs": ["**/开题报告*.{doc,docx,pdf,md}"],
            "min_bytes": 2048,
            "max_age_days": 365
          },
          "content_checks": [
            {
              "id": "research_question",
              "label": "包含研究问题与科学假设",
              "type": "keyword_or_llm",
              "keywords": ["研究问题", "假设", "技术路线"],
              "llm_prompt": "判断这份开题报告是否明确写出研究问题、科学假设与技术路线，输出 {pass: boolean, reason: string}"
            }
          ],
          "missing_action": {
            "type": "create_doc_stub",
            "payload": { "path": "01_开题/开题报告.md", "template": "research_proposal" }
          }
        },
        {
          "id": "ethics_approval",
          "label": "伦理审批件",
          "required_when": "project.contains_human_subjects",
          "match": { "globs": ["**/伦理*审批*", "**/IRB*.pdf"] }
        }
      ],
      "exit_criteria": [
        { "id": "proposal_finalized", "label": "开题报告已定稿", "type": "artifact", "artifact_id": "proposal_report" },
        { "id": "literature_matrix", "label": "文献对比矩阵已建立", "type": "manual" }
      ],
      "rules": [
        { "template_key": "citation_strict", "priority": "high" },
        {
          "content": "开题阶段的所有文献论断必须绑定 .bib 或项目资料中的条目，禁止编造 DOI",
          "category": "academic",
          "trigger_pattern": "01_开题/**"
        }
      ],
      "recommended_milestones": [
        { "title": "完成开题报告初稿", "due_offset_days": 14 },
        { "title": "开题答辩通过", "due_offset_days": 45 }
      ]
    },
    {
      "id": "execution",
      "label": "实施",
      "order": 2,
      "objective": "按技术路线完成研究，确保数据可复现",
      "artifacts": [
        { "id": "raw_data", "label": "原始数据", "required": true, "match": { "globs": ["02_实施/数据/**/*.{csv,parquet,xlsx,json}"] } },
        { "id": "experiment_log", "label": "实验记录", "required": true, "match": { "globs": ["**/实验记录*.{md,docx}"] } }
      ],
      "exit_criteria": [
        { "id": "data_reproducible", "label": "数据与脚本可复现", "type": "artifact", "artifact_id": "raw_data" }
      ],
      "rules": [
        { "content": "所有实验必须记录随机种子、超参数与均值±标准差", "category": "research", "trigger_pattern": "02_实施/**" }
      ]
    },
    {
      "id": "closure",
      "label": "结题",
      "order": 3,
      "objective": "形成成果、完成验收与经费决算",
      "artifacts": [
        { "id": "final_report", "label": "结题报告", "required": true, "match": { "globs": ["04_结题/**/*.{doc,docx,pdf}"] } },
        { "id": "budget_statement", "label": "经费决算表", "required": true, "match": { "globs": ["**/经费*决算*"] } },
        { "id": "outputs", "label": "成果材料", "required": true, "match": { "globs": ["03_成果/**/*"], "min_count": 1 } }
      ],
      "exit_criteria": [],
      "rules": []
    }
  ],
  "global_rules": [
    { "content": "所有交付物命名遵循『阶段_类型_版本_日期』，如『开题_报告_v2_20261031』", "category": "naming", "priority": "medium" }
  ],
  "todos": [
    { "title": "建立文献库目录与 .bib 文件", "stage": "proposal", "suggested": true }
  ],
  "ai_guidance": {
    "stage_hint": "当用户处于『开题』阶段时，优先提醒研究问题、假设、文献与伦理四件事；不要提前催结题材料。",
    "completeness_tone": "用事实和证据说明缺什么，给出一个可执行动作，不要泛泛而谈。"
  },
  "meta": {
    "author": "Sage 内置",
    "license": "CC-BY-4.0",
    "homepage": "",
    "created_at": "2026-10-31"
  }
}
```

### 5.3 字段语义

| 字段 | 说明 |
|---|---|
| `schema_version` | 规格版本；导入时做兼容校验 |
| `applies_to` | 与现有 `project_type` / `project_sub_type` 对齐，用于"推荐规程" |
| `directory_layout` | 目录要求；`required=false` 时只提示不扣分 |
| `stages[].artifacts` | 阶段文档要求。`match.globs` 支持 `**`、`{a,b}`；`min_bytes`、`min_count`、`max_age_days` 为存在性/时效性阈值；`required_when` 为可选条件（MVP 仅支持少量内置条件） |
| `content_checks` | 内容级检查：`keyword`（确定性）、`llm`（AI 判断，带确定性关键词兜底）、`manual`（用户勾选） |
| `exit_criteria` | 阶段退出条件：artifact 满足 / manual 勾选 / milestone 完成 |
| `rules` | 阶段规则；`template_key` 引用现有约束模板，或内联 `content`；应用时写入 `project_constraints` |
| `recommended_milestones` | 阶段里程碑建议；`due_offset_days` 相对阶段进入时间 |
| `ai_guidance` | 注入 AI 的系统提示片段，让顾问建议贴合该方法论 |
| `meta` | 作者、许可证、来源，供分享时展示 |

**MVP 明确不支持**：任意脚本/表达式求值（安全风险）、远程 URL 依赖、二进制模板内容内嵌（只用模板 ID）。

---

## 6. 核心机制

### 6.1 项目绑定与快照

- 项目绑定规程时，把规格**完整快照**存入 `project_playbooks`（而不是只存 ID），保证内置规程升级不会改变用户项目的行为。
- 记录 `source`：`builtin:<id>@<version>` / `imported:<sha256>` / `custom`，以及 `parent_playbook_id` 以便追溯。
- 用户可编辑快照（项目级定制），编辑后 `source` 变为 `custom`，但仍可"同步内置更新"（diff 预览后合并）。
- 绑定是幂等的：重复绑定同一版本不产生新记录。

### 6.2 完整性审计（确定性内核）

`ProjectPlaybookAuditor.audit(project, playbook)`：

1. **扫描**：复用 `project_profiler` 的安全扫描（排除 `.git`、`node_modules`、虚拟环境、敏感文件；路径 `resolve()` 后必须位于项目根或 `allowed_paths` 内）。
2. **存在性**：按 `globs` 匹配；统计数量、大小、最近修改时间。
3. **时效性**：`max_age_days`；并记录"是否在进入当前阶段之后修改过"。
4. **内容性**：
   - `keyword`：抽取文本（md/txt/docx/xlsx/pptx/pdf 复用 `project_workspace_inspector` 的提取器）后做关键词命中；
   - `llm`：仅在用户点"AI 检查"时调用，结果缓存（文件 hash + prompt hash）；
   - `manual`：用户勾选，存 `playbook_state`。
5. **目录与规则**：目录是否存在；规则是否已投影到约束（按内容 hash 匹配）。
6. **汇总**：每阶段 `required_total / required_done / waived`，项目整体完成度。

**评分口径**（公开、可解释）：

```
阶段完成度 = 0.5 × 必需要素完成率
           + 0.3 × 退出条件完成率
           + 0.2 × 阶段里程碑完成率
```

`waived`（用户豁免）计入完成，但审计报告单列"已豁免 N 项"。

### 6.3 阶段识别

识别不是"猜"，而是三路证据加权 + 用户确认：

| 证据 | 来源 | 权重 |
|---|---|---|
| 阶段退出条件达成 | 审计器 | 0.5 |
| 阶段目录/产物的最近活动 | 文件 mtime 分布 | 0.2 |
| 里程碑与阶段匹配度 | `project_milestones.stage` | 0.2 |
| 会话与资料主题（可选） | 最近会话标题、资料标题（关键词） | 0.1 |

- **确定性结果**：取"完成度 ≥ 70% 且下一个阶段尚未开始"的最晚阶段作为候选；如果当前阶段尚未达标但下一阶段有明显活动，输出"可能提前进入下一阶段"的提示。
- **LLM 裁决**：证据冲突或候选置信度 < 0.6 时，把证据清单交给 `ProjectAnalysisAgent`，要求输出候选阶段 + 理由，禁止输出证据之外的事实。
- **永远不自动切换**：UI 显示"检测到可能已进入『实施』阶段（3 条证据）[确认推进] [保持当前] [稍后提醒]"。确认后写入 `stage_history`（from/to/at/evidence/confirmed_by=user）。
- **回退**：允许用户手动回退阶段，记录在历史中，不删除数据。

### 6.4 AI 定制规程

两种入口，产出都是**符合 schema 的规程草稿**：

1. **问卷式**（推荐，稳定）：
   - 项目性质（已有类型/子类型自动带入）
   - 资助方 / 学校 / 期刊或行业模板（可选，自由文本）
   - 必须交付的成果（多选 + 自定义）
   - 时间节点（阶段截止日期）
   - 是否已有目录结构（审计器自动扫描并展示）
   - LLM 生成草稿 + 每条要素的"为什么"；
2. **对话式**：用户在聊天里描述"我是做 XX 的课题，学校要求……"，AI 用工具生成草稿并进入同一个编辑器。

**关键约束**：

- LLM 输出必须通过 schema 校验；失败时回退到"内置规程 + 用户问卷映射"的确定性结果；
- 生成内容里不允许出现项目中的真实敏感数据；
- 草稿不自动绑定，用户必须在编辑器中确认。

### 6.5 建议与动作

建议统一为类型化动作，全部先预览后执行：

| 动作 | 执行内容 | 风险级别 |
|---|---|---|
| `create_folder` | 创建规程要求的目录 | 低（不存在才建） |
| `create_doc_stub` | 创建文档骨架（Markdown/Office 模板），写入模板标题与章节 | 低（不覆盖已有文件） |
| `apply_rules` | 把阶段规则幂等写入 `project_constraints` | 低（内容 hash 去重） |
| `seed_milestones` | 创建阶段推荐里程碑 | 低（去重） |
| `set_stage` | 推进/回退阶段（需确认） | 中（写历史，可回退） |
| `add_todo` | 把缺失项转为待办（带 `project_id`） | 低 |
| `classify_files` | **建议**把文件归入规程目录（逐文件 diff） | 高（移动文件需逐项确认；MVP 只建议不执行） |
| `link_material` | 把阶段文档登记为项目资料 / 关联 Wiki 页 | 低 |
| `ignore_7d` | 忽略该建议 7 天 | 低 |

- 每条建议包含：标题、证据（文件路径/缺失项/里程碑/阶段）、理由、动作、优先级、置信度。
- `ProjectAdvisor` 的上下文采集追加 `playbook_audit` 摘要；确定性规则引擎在无 LLM 时按审计结果直接产出上述动作。
- 顾问缓存指纹加入 `playbook_id + stage + audit_hash`。

### 6.6 导出、导入与分享

**导出格式（原生）**：`.sageplaybook.json`

```json
{
  "format": "sage.playbook",
  "schema_version": "1.0",
  "exported_at": "2026-10-31T12:00:00Z",
  "exporter": { "app": "Sage", "version": "0.6.0-alpha.x" },
  "playbook": { "...": "第 5 节规格" },
  "scaffold": {
    "include": true,
    "directories": ["01_开题", "02_实施/数据", "03_成果", "04_结题"],
    "documents": [
      { "path": "01_开题/开题报告.md", "template_id": "research_proposal", "content_kind": "stub" }
    ]
  },
  "integrity": { "sha256": "..." }
}
```

- **隐私默认**：`scaffold.documents` 只含空骨架/模板标题，**不含用户实际内容**；导出对话框明确提示。
- **人类可读版**：`规程手册.md`——阶段表、每阶段清单、目录树、规则清单，可直接打印或放进 Wiki。
- **Agent 可读版**：`AGENTS.md` 片段 / `CLAUDE.md` 片段——目录约定 + 阶段规则 + 命名规范，让其他 AI 工具读到同一套方法论（对标 Cursor Rules / Claude Code Skills 的生态习惯）。
- **导入**：文件选择 → schema 校验 → 与当前规程 diff（新增/修改/删除的阶段与条目）→ 冲突策略（替换 / 合并保留本地 / 另存为新规程）→ 可选同时创建骨架目录与文档（逐项勾选）→ 绑定。
- **版本兼容**：`schema_version` 主版本不兼容时拒绝导入并给出原因；次版本向前兼容。
- **分享边界**：MVP 只支持"文件级分享"（用户自行通过网盘/邮件传递）；不在本期做云端规程市场。

### 6.7 与现有能力的投影关系

| 现有能力 | 规程中的角色 | 投影规则 |
|---|---|---|
| `project_constraints` | 阶段/全局规则 | 按 `(project_id, normalized_content)` 幂等写入；删除规程条目不自动删约束，只在审计中标记"孤立" |
| `project_milestones` | 阶段推荐里程碑 / 退出条件 | 按 `title + stage` 去重；完成状态反哺阶段识别 |
| `project_materials` | 阶段文档可登记为资料 | 只建议 `link_material`，不自动搬运 |
| Wiki | 规程手册可写入 Wiki 页面 | P2 起提供"导入手册到 Wiki" |
| Todo | 缺失项可转为待办 | 使用 `todos.project_id`，不新建待办体系 |
| SAGE.md | 规程的"总纲"摘要 | 可选把阶段规则摘要写入 SAGE.md 的"项目管理"小节（需确认） |
| 检查点 | 应用规程前自动快照 | 复用 `project_workspace_inspector` 的检查点能力 |

---

## 7. 数据模型与 API

### 7.1 数据库（SQLite，幂等迁移）

```sql
CREATE TABLE IF NOT EXISTS project_playbooks (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,              -- 快照版本号，递增
  source TEXT NOT NULL,                  -- builtin:<id>@<ver> | imported:<sha> | custom
  parent_id TEXT,                        -- 来源快照/内置规程 id，便于追溯
  spec_json TEXT NOT NULL,               -- 完整规格快照
  spec_hash TEXT NOT NULL,               -- sha256(canonical_json)
  created_at INTEGER NOT NULL,
  active INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_playbooks_project ON project_playbooks(project_id, active);

ALTER TABLE projects ADD COLUMN playbook_state TEXT;  -- JSON：当前阶段、阶段历史、豁免项、忽略建议、手动勾选
```

- 只保留每个项目的最新 N 个快照（默认 20），更早的随项目删除由外键级联。
- `projects.playbook_state` 与 `bootstrap_state` 分离，避免语义混杂。

### 7.2 API（前缀 `/api/v1`）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/playbooks/builtin` | 内置规程列表（摘要） |
| GET | `/playbooks/builtin/{id}` | 内置规程完整规格 |
| GET | `/projects/{id}/playbook` | 当前绑定规程 + 状态摘要 |
| POST | `/projects/{id}/playbook/preview` | 预览绑定/更换/同步内置更新的 diff |
| PUT | `/projects/{id}/playbook` | 绑定或更新快照（幂等） |
| POST | `/projects/{id}/playbook/author/preview` | AI 定制规程草稿（问卷/对话） |
| GET | `/projects/{id}/playbook/audit` | 完整性审计（确定性；`?ai=1` 触发 LLM 内容检查） |
| POST | `/projects/{id}/playbook/stage/confirm` | 确认推进/回退阶段（写历史） |
| POST | `/projects/{id}/playbook/actions/apply` | 批量执行用户勾选的动作（幂等） |
| GET | `/projects/{id}/playbook/export` | 导出（`format=json|md|agents`；`include_scaffold=true|false`） |
| POST | `/playbooks/import/preview` | 导入校验 + diff |
| POST | `/playbooks/import` | 确认导入（冲突策略：replace/merge/save_as_new） |
| DELETE | `/playbooks/imported/{sha}` | 删除导入的全局规程（P2，规程库） |

**契约约定**：

- 所有端点遵循现有错误格式；项目不存在 404，目录缺失 410（`project_path_missing`）。
- `audit` 永远返回 200；LLM 不可用时 `llm_available=false` 并返回确定性结果。
- `actions/apply` 返回 `{applied[], skipped[], errors[]}`，逐项幂等（沿用 `bootstrap/apply` 的结构）。
- 所有写动作前创建检查点（`create_doc_stub` / `apply_rules` / `seed_milestones` 批量执行时一次快照）。

### 7.3 后端模块（新增）

```
backend/services/playbook_spec.py        # 规格校验、规范化、hash、版本兼容
backend/services/playbook_library.py     # 内置规程注册表 + 导入导出信封
backend/services/playbook_auditor.py     # 文件扫描 + 完整性 + 阶段识别
backend/services/playbook_author.py      # LLM 定制 + 确定性降级
backend/services/playbook_actions.py     # 动作执行（目录/骨架/规则/里程碑）
backend/api/playbook_routes.py           # 路由
backend/data/playbook_repo.py            # 快照 CRUD + 状态读写
```

内置规程数据建议放在 `backend/services/playbook_builtin/`（每份一个 JSON 文件，便于评审与 diff），由 `playbook_library` 加载并校验；前端不再维护第二份 `archetypeBlueprints` 的文档要求。

### 7.4 前端模块（新增）

```
src/features/playbook/PlaybookCard.tsx           # 项目主页卡片（阶段条 + 完成度 + 缺失项）
src/features/playbook/PlaybookStageStepper.tsx   # 阶段流水线与推进确认
src/features/playbook/PlaybookChecklist.tsx      # 分阶段清单（含证据、豁免、转待办）
src/features/playbook/PlaybookEditor.tsx         # 结构化编辑器（阶段/文档/规则/里程碑）
src/features/playbook/PlaybookAuthorWizard.tsx   # AI 定制问卷
src/features/playbook/PlaybookImportDialog.tsx   # 导入 + diff + 冲突策略
src/features/playbook/PlaybookExportDialog.tsx   # 格式选择 + 隐私提示
src/shared/api/playbookApi.ts                    # API 封装 + wire 类型
electron/commandRoutes/playbooks.ts             # IPC → REST 映射
src/shared/lib/i18n/locales/{zh,en}/playbook.ts  # 文案
```

---

## 8. 前端信息架构

### 8.1 项目主页（概览 Tab）

```
┌ 项目：XX 课题   [科研] [实施阶段]                          … ┐
│ /home/user/projects/xx                                      │
│                                                             │
│ 项目规程：科研课题（开题·实施·结题）  v3 · 内置            │
│ ● 开题 ✓ —— ● 实施（进行中 72%）—— ○ 结题                  │
│ ┌ 本阶段待补 ──────────────────────────────┐                │
│ │ ⚠ 原始数据目录为空           [创建目录]  │                │
│ │ ⚠ 实验记录缺失               [生成骨架]  │                │
│ │ ✓ 开题报告（已定稿）                     │                │
│ │ ? 伦理审批（不适用，已豁免）             │                │
│ └──────────────────────────────────────────┘                │
│ [检查完整性] [AI 检查内容] [导出规程] [更换规程]             │
└─────────────────────────────────────────────────────────────┘
```

- 阶段条默认展示；点击阶段可查看该阶段清单（只读）。
- "检查完整性"打开结果抽屉；确定性结果即时返回，AI 内容检查异步可取消。
- 缺失项动作按钮内联；批量操作用"下一步"卡片。
- 不出现"PID/DSL/globs"等实现术语（高级编辑器里例外）。

### 8.2 设置 Tab

- 新增"项目规程与阶段"区块：当前规程、来源/版本、最后检查时间、编辑/更换/同步更新/导出/解绑。
- 保留现有 `project_stage` 下拉，但改为由规程驱动的阶段选择（无规程时回退旧行为）。

### 8.3 项目列表与右键菜单

- 右键新增："检查项目完整性"（打开详情页并聚焦规程卡）。
- 导出："导出项目管理规程…"。
- 工作台"高级"折叠区可提供"批量检查所选项目"（P2，可选）。

### 8.4 规程编辑器

- 左栏阶段列表（拖拽排序），右栏当前阶段表单（目标、必需文档、匹配规则、内容检查、退出条件、规则、里程碑）。
- 顶部"从内置开始" / "AI 重新生成" / "查看 JSON"（高级）。
- 所有修改先存草稿，点击"保存为新版本"才生成快照；离开前提示未保存。

---

## 9. 分阶段实施

### P0 — 内核与只读体验（3–5 天）

- [x] `playbook_spec.py`：规格 dataclass + 校验 + canonical hash + 版本兼容
- [x] 内置规程：科研（开题/实施/结题）、代码工程（规划/研发/测试/发布/维护）两份 JSON
- [x] `project_playbooks` 表 + `projects.playbook_state` 迁移 + `playbook_repo`
- [x] `playbook_auditor.py`：目录/产物存在性、时效性、关键词检查、完成度汇总（无 LLM）
- [x] API：builtin 列表/详情、绑定/预览、audit（确定性）
- [x] 前端：`PlaybookCard` + 阶段条 + 清单（只读）+ 设置区展示
- [x] 导出 JSON（含空目录骨架）与人类可读 Markdown
- [x] 单测：规格校验、glob 匹配、完成度、路径越界、无 LLM 降级
- [x] 文档：技术文档新增章节；用户手册"项目规程"一节

**验收**：科研项目绑定内置规程后，项目主页能看到"当前阶段 + 完成度 + 缺失项"，导出的 JSON 可在另一台机器上打开并通过校验。

### P1 — 可操作与可分享（4–6 天）

- [x] `create_folder` / `create_doc_stub` / `apply_rules` / `seed_milestones` 动作 + 批量预览/执行
- [x] 缺失项一键转 Todo（带 `project_id`）
- [x] 导入：校验 + diff + 冲突策略（replace/merge/save_as_new）
- [x] 阶段识别（确定性三路证据）+ 确认/回退 API + 阶段历史
- [x] 右键菜单入口 + 导入/导出对话框（隐私提示）
- [x] 应用动作前自动检查点
- [x] 集成测试：导入→绑定→审计→执行→阶段确认全链路
- [ ] 双分支适配检查（py3.8 / pydantic v1）

**验收**：用户 A 导出的规程，用户 B 导入后一键创建同构目录与文档骨架，审计结果一致；阶段识别给出证据且需确认才生效。

### P2 — AI 深度参与（5–7 天）

- [x] `playbook_author.py`：问卷式 AI 定制 + 确定性降级 + schema 校验重试
- [x] 内容级 LLM 检查（同步执行、失败降级、关键词兜底）
- [x] 阶段歧义 LLM 裁决（证据约束 prompt）
- [ ] `ProjectAdvisor` 接入审计摘要与规程 `ai_guidance`；建议带 `playbook_ref`
- [x] 导出 `AGENTS.md` / `CLAUDE.md` 片段（Wiki 手册写入待做）
- [ ] 规程编辑器（结构化表单 + JSON 高级视图 + 保存新版本）
- [ ] 前端文案 i18n（zh/en 键对齐）

**验收**：无 LLM 环境全链路可用；有 LLM 时 AI 定制的规程通过校验率 ≥ 95%，内容检查结果带证据且可人工推翻。

### P3 — 规程生态（按需）

- [ ] 更多内置规程：学位论文、基金申报、公文案卷、个人知识库
- [ ] 全局"规程库"页面：管理导入/自建规程、导出合集
- [ ] 评分模板/权威 checklist 映射（PRISMA、DMP 模板）作为内置数据
- [x] 文件归类建议（逐文件 diff，仍然只建议不自动移动）
- [ ] 规程市场/云端分享（明确超出本地优先边界，需单独评审）

---

## 10. 测试与验收

| 层 | 覆盖 |
|---|---|
| 单元 | 规格校验与版本兼容；glob（含中文路径、`**`、`{a,b}`）；完成度口径；`required_when`；豁免；阶段识别权重；路径越界；导入 diff |
| 后端集成 | 绑定→审计→动作→确认阶段；导入→绑定→导出 round-trip；无 LLM 降级；重复执行幂等；检查点创建 |
| 前端组件 | 阶段条/清单/证据展示；缺失项动作确认；导入冲突策略；编辑器保存新版本；i18n 键 parity |
| E2E | 科研项目绑定规程 → 创建骨架 → 完整性从 0%→100% → 导出 → 另建项目导入 → 结果一致 |
| 质量门 | 覆盖率 ≥ 80%；新文件纳入 architecture baseline；双分支 CI 全绿 |

---

## 11. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| glob/命名习惯差异导致误判"缺失" | 用户不信任 | 证据透明（实际扫描到的文件）；支持手动豁免；匹配规则可视化编辑 |
| 自动移动/归类文件造成数据丢失 | 严重 | MVP 只建议不移动；逐文件确认；执行前检查点 |
| 导入恶意路径（`../`、绝对路径） | 安全 | schema 校验拒绝绝对路径与 `..`；所有创建限制在项目根内；复用 `validate_workspace` |
| 导出泄露用户内容 | 隐私 | 默认只导出规程与空骨架；导出前显式提示；无内容模板 |
| 内置规程与学校/资助方要求不一致 | 价值下降 | AI 定制 + 自定义编辑；规程只做推荐不强制；豁免机制 |
| LLM 输出不合规 | 功能失败 | schema 校验 + 重试 + 确定性降级；草稿必须用户确认 |
| 规程升级改变旧项目行为 | 回归 | 绑定快照；默认不自动同步；同步需 diff 确认 |
| 项目阶段与里程碑 `stage` 枚举漂移 | 数据不一致 | 规程阶段 id 与 `GET /config/types` 建立映射；未命中回退标签展示 |
| win7 Python 3.8 / pydantic 1.x | 无法构建 | 不用新语法；schema 用 `class Config`；只依赖标准库 json/glob |
| 范围过大 | 半成品 | P0 可独立发布；每阶段单独 PR/可回滚 |

---

## 12. release/win7 对齐注意

- 后端保持 Python 3.8 语法：`typing.List/Dict/Optional`，无海象/`match`/PEP 604 联合类型；
- Pydantic 1.x：新 schema 用 `class Config: extra = "forbid"`，不用 v2-only API；
- 不新增原生依赖；glob 使用标准库 `glob`/`fnmatch` 或自写小匹配器（避免 `pathspec` 等新依赖）；
- 文件匹配统一用 POSIX 风格路径，在 Windows 上做 `\` → `/` 归一化；
- 前端只用现有 Radix/React 组件，不引入新 UI 依赖；
- 文档编号按 win7 当前最大编号顺延；冲突按既有 cherry-pick 经验处理。

---

## 13. 待确认决策（已给推荐）

| # | 决策点 | 选项 | 推荐 |
|---|---|---|---|
| D1 | 首批覆盖范围 | 科研优先 / 科研+代码 / 四类全上 | **科研 + 代码**（P0），其余 P3 |
| D2 | 自动化边界 | 只建议 / 建议+批准后创建目录与骨架 / 允许自动移动文件 | **建议 + 批准后创建目录/骨架/规则/里程碑；MVP 不移动文件** |
| D3 | 本次交付程度 | 仅方案文档 / 方案 + 实施计划 / 直接实施 P0 | **方案（本文档）→ 评审 → writing-plans 出实施计划** |
| D4 | 分享形态 | 仅原生 JSON / JSON + Markdown / 再加 AGENTS.md 片段 | **三者都要**（JSON 为权威，后两者为可读/生态） |
| D5 | 规程存储 | 只存内置 ID / 项目级快照 / 快照+版本历史 | **项目级快照 + 最近 20 版** |

---

## 14. 明确不做（YAGNI）

- 不做云端规程市场、账号体系与在线评分；
- 不做多人实时协作编辑规程；
- 不执行规程中的任意脚本/表达式（只支持声明式匹配与动作）；
- 不自动移动/重命名用户已有文件（只给建议）；
- 不替代学校的官方申报系统或 DMPTool，只做本地辅助；
- 不新增独立的待办/资料/文档存储（复用 Todo、Materials、Office、Wiki）；
- 不在本期做代码符号级文档抽取（Wiki 已有，独立演进）；
- 不把现有蓝图/脚手架删除——改为内置规程的兼容投影。

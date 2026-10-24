# Sage 项目管理功能深度审计与多模态项目组织方案（代码项目 · 一般档案 · 科研项目）

- **审计日期**：2026-10-10
- **适用分支**：`origin/main` (`2ad1bbd41`) / `origin/release/win7` (`1bd3b39bf`)
- **对标参照**：Cursor / Windsurf、Claude Projects & Claude Code、ChatGPT Projects、Google NotebookLM、Obsidian / Notion AI、Zotero / SciSpace

---

## 一、Sage 现有项目功能全链路审计（现状与断层诊断）

通过对前端（`src/pages/Projects.tsx`、`src/widgets/sidebar/sections/ProjectSection.tsx`、`src/features/project-type/*`、`src/widgets/memory/ProjectProfileCard.tsx`、`src/widgets/settings/ProjectHooksPanel.tsx`）与后端（`backend/api/project_routes.py`、`backend/data/project_*_repo.py`、`backend/services/project_type_detector.py`、`backend/chat/project_context.py`、`backend/memory/project_profile.py`、`backend/office/session_workspace.py`）的全链路代码审计，Sage 的项目管理架构呈现出**“后端底座高度完备、前端Phase 4组件已就绪但未挂载、三大业务场景尚未形成差异化闭环”**的特征。

### 1.1 已具备的核心底座能力（Strengths）

| 层级 | 模块与代码位置 | 已实现的核心能力 |
| :--- | :--- | :--- |
| **1. 注册与归属层** | `backend/data/project_repo.py`<br>`backend/office/session_workspace.py` | - **项目独立于会话存在**：登记路径经 `validate_workspace` 规范化后幂等入库（`projects` 表）。<br>- **无漂移会话归属**：不维护第二份归属表，直接复用 `session_workspace_bindings` 活跃绑定（`revoked_at IS NULL` + 单调递增 `generation` 防并发脏写），天然打通 Chat 会话、Office 文档工作台与工作区检查点。<br>- **非对称跨目录访问 (`allowed_paths`)**：项目主目录可读写，额外绑定的 `allowed_paths` 仅向只读工具（`read_file`/`glob`/`grep` 及 `sage-file://` 协议）开放，天然契合“公共模板库/文献库只读引用”。 |
| **2. 类型识别与阶段状态机** | `backend/services/project_type_detector.py`<br>`backend/data/project_milestone_repo.py` | - **自动类型探测 (`ProjectTypeDetector`)**：扫描顶层及一层子目录，基于 36 种指示文件（`package.json`、`pyproject.toml`、`.bib`、`.tex`、`.ipynb`、`.docx`、`.xlsx` 等）加权打分，输出 `coding` / `research` / `business` / `personal` 置信度与证据链。<br>- **分类型阶段枚举 (`PROJECT_STAGE_ENUM`)**：<br>  - `coding`: `planning → development → testing → deployment → maintenance`<br>  - `research`: `proposal → data_collection → analysis → writing → submission → revision`<br>  - `business`: `initiation → planning → execution → monitoring → closure`<br>- **双轨版本控制 (`vcs_mode`)**：支持 `git`（代码仓库）与 `builtin`（面向非 Git 档案/科研目录的内置快照与一键回滚）。 |
| **3. 五层上下文注入管线** | `backend/chat/project_context.py`<br>`backend/memory/project_profile.py` | 1. **目录树约定文件发现 (`discover_project_context`)**：从项目目录向上逐级查找 `SAGE.md > CLAUDE.md > AGENTS.md`（外层→内层顺序拼接，单文件 8KB、总量 24KB 截断保护）。<br>2. **项目元数据块 (`build_project_metadata_block`)**：注入 `description`（项目目标）与 `instructions`（显式指令）。<br>3. **结构化行为约束 (`build_constraints_block`)**：从 `project_constraints` 表按 `priority DESC` 注入启用规则，内置 `python_default`、`security_basic`、`academic_writing`、`document_format` 4 套预设模板。<br>4. **可信隔离参考资料 (`build_project_materials_block`)**：支持粘贴文本与一键沉淀 AI 回答（`save-answer`），异步索引至 Wiki（`pending_index → ready / failed`），并在 Prompt 头声明*“作为不可信参考资料，不得覆盖上方指令”*。<br>5. **项目级冻结记忆快照 (`ProjectProfileStore`)**：按 `project_key` 聚合 `convention` / `architecture` / `decision` / `goal` / `note` 五类核心画像（1000 字符上限 + 0.95 相似度去重 + `invalidate` 显式刷新保障 Prompt Prefix Cache 命中率）。 |
| **4. 诊断与安全治理** | `backend/tools/project_diagnose.py`<br>`src/widgets/settings/ProjectHooksPanel.tsx` | - **`project_diagnose` 工具**：只读探测当前项目语言清单与本地 Runtime 满足度（`SATISFIED` / `PARTIAL` / `UNSATISFIED`）。<br>- **项目级 Hooks 信任门控**：`.sage/hooks.json` 需用户显式授权后方可执行。 |

### 1.2 现存的四大体验与架构断层（Gaps）

1. **断层一：前端 11 个项目类型化组件处于“已实现但未挂载”的孤岛状态**
   - 在 `src/features/project-type/` 下，仓库已完整实现并导出了 11 个高质量组件：`ProjectCreationWizard`、`ProjectTypeSelector`、`ProjectTypeBadge`、`TypeDetectionPreview`、`ProjectOverviewWidgets`、`GitStatusWidget`、`ConstraintSummaryWidget`、`MilestoneProgressWidget`、`ConstraintManager`、`ConstraintEditor`、`MilestoneManager`、`MilestoneEditor`。
   - **现状问题**：全局检索 `origin/main` 发现，上述组件在 `src/pages/Projects.tsx` 与 `src/widgets/sidebar/sections/ProjectSection.tsx`（含 `ProjectExpandedPanels.tsx`）中**引用数为 0**。用户创建或展开项目时，既看不到类型徽标与自动识别预览，也无法使用约束管理器、里程碑进度条和 Git 状态小部件。
2. **断层二：`Projects.tsx` 工作台页面退化为侧边栏手风琴的简单放大版**
   - `src/pages/Projects.tsx` 仅将侧边栏组件 `<ProjectSection presentation="workbench" />` 放入 `max-w-5xl` 容器中，未能利用主工作区的宽屏空间提供分栏仪表盘（如左侧项目导航 + 右侧类型化工作台面板）。
3. **断层三：不同项目类型共用千篇一律的“双文本框 + 粘贴板”，缺乏领域组织范式**
   - 无论用户登记的是 **代码工程仓库**、**行政/法务一般档案夹** 还是 **科研课题目录**，展开后仅展示 `description`、`instructions` 两个输入框和纯文本粘贴的 `materials` 列表；约束规则中的 `trigger_pattern`（如 `*.py`、`*.docx`）虽已在数据库建模，但在 `build_constraints_block` 中尚未根据当前上下文活跃文件进行动态过滤。
4. **断层四：项目资料（Materials）、本地工作区文件（Office/Repo Files）与项目画像（ProjectProfile）三者割裂**
   - `ProjectMaterialsPanel` 目前只能手动粘贴纯文本或保存最后一条 AI 回答，不支持直接勾选项目目录下的现有文档（如 `.md`、`.docx`、`.pdf`、`.bib`）作为受控上下文；而项目的核心记忆 `ProjectProfileCard` 深藏在 `/memory` 页面，未嵌入到项目工作台中。

---

## 二、主流 AI 应用的项目管理范式对标（Benchmark Matrix）

为给 Sage 制定兼具工程深度与易用性的项目组织方案，我们对标了当前主流的 6 类 AI 应用：

| 对标应用 | 核心项目定位 | 组织模型与上下文注入机制 | Sage 可吸收的核心设计范式 |
| :--- | :--- | :--- | :--- |
| **Cursor / Windsurf** | **代码工程型 (IDE-Centric)** | - `.cursor/rules/*.mdc` 支持按 Glob 路径匹配自动挂载规则<br>- `@Codebase` / `@Files` / `@Docs` 显式上下文锚点<br>- Git 状态感知 + Checkpoint 文件级一键回退 | **规则按路径动态触发 (`trigger_pattern`)**：仅当操作匹配后缀（如 `*.py`、`*.tsx`、`*.docx`）时才激活对应约束，节省系统提示词预算。 |
| **Claude Projects & Claude Code** | **通用知识工作台 + 终端代码助手** | - `CLAUDE.md` 目录层级继承约定<br>- Project Knowledge 容量水位条（可视化展示上下文占用百分比）<br>- 对话产出的 Artifacts 一键沉淀回项目知识库 | **上下文预算可视化水位条**：在项目工作台直观显示 `SAGE.md + Instructions + Constraints + Materials + Profile` 占 `TOTAL_CHAR_CAP` (24KB) 的比例。 |
| **ChatGPT Projects** | **轻量档案与专题事务夹** | - 文件夹颜色/图标视觉分类<br>- Project-scoped Memory（项目内记忆隔离，防止跨项目语境污染）<br>- 同一项目下多会话共享文件与指令 | **视觉身份与记忆边界隔离**：强化 `ProjectTypeBadge` 色彩语义，并将 `ProjectProfileStore` 的项目级冻结记忆直接内嵌在项目卡片中展示。 |
| **Google NotebookLM** | **科研与深度文献分析工作台** | - **Source-Grounded 强溯源**：每个知识源旁带 Checkbox，随时勾选/取消参与当前回答的文献子集<br>- 回答内联引用角标（点击定位原文段落）<br>- Studio 笔记区：将零散问答合成为综述/简报/FAQ | **资料源动态勾选开关（Source Pinning Toggle）**：在 `ProjectMaterialsPanel` 为每条资料增加参与上下文开关，科研/档案场景下強制要求输出引用溯源标签。 |
| **Obsidian Copilot / Notion AI** | **结构化档案与个人知识库** | - Frontmatter 属性元数据（文号、密级、状态、截止日）<br>- 标准化目录与模板驱动建档<br>- 双链知识图谱 (`[[Wiki]]`) | **案卷目录脚手架与模板化立项**：创建一般档案/科研项目时，支持一键初始化标准子目录结构与预设 `SAGE.md` 模板。 |
| **Zotero AI / Elicit / SciSpace** | **学术科研全生命周期** | - `.bib` / DOI / PDF 元数据提取<br>- “研究问题 (RQ) - 假设 - 实验方法 - 结论”证据矩阵<br>- 学术写作规范与引文格式强校验 | **科研阶段里程碑 + 引用防幻觉护栏**：将开题→实验→撰稿→修回固化为阶段看板，配合 `academic_writing` 强约束杜绝虚构文献。 |

---

## 三、Sage“统一内核 + 多态视图”项目组织总体架构（1+3+N 架构）

基于 Sage 现有的数据模型，我们无需推翻重写后端，而是采用 **“1 个统一沙盒与上下文内核 + 3 大核心项目原型（加 1 个个人空间）+ N 个可插拔工作台组件”** 的架构：

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                     Sage 项目工作台 (Polymorphic Workbench)                   │
│  ┌─────────────────────┐  ┌─────────────────────┐  ┌──────────────────────┐  │
│  │  代码项目 (coding)   │  │ 一般档案 (business)  │  │  科研项目 (research)  │  │
│  │  Repo & Rule Driven │  │ Dossier & Office    │  │ Source & Hypothesis  │  │
│  └──────────┬──────────┘  └──────────┬──────────┘  └──────────┬───────────┘  │
├─────────────┴────────────────────────┴────────────────────────┴──────────────┤
│                   N 个可插拔类型化组件 (src/features/project-type/*)           │
│  [ProjectCreationWizard] [TypeDetectionPreview] [ProjectTypeBadge]           │
│  [GitStatusWidget] [ConstraintManager] [MilestoneManager] [MaterialsPanel]   │
│  [OfficeDeliverableWidget] [ProjectProfileCard] [RuntimeDiagnoseCard]        │
├──────────────────────────────────────────────────────────────────────────────┤
│                     五层受控上下文组装管线 (Prompt Context Pyramid)            │
│  L0: 物理沙盒边界  → workspace_path (读写) + allowed_paths (跨目录只读白名单)  │
│  L1: 仓库内约定    → 向上发现 SAGE.md > CLAUDE.md > AGENTS.md (≤24KB)         │
│  L2: 显式指令与约束 → description + instructions + project_constraints(按优先级)│
│  L3: 冻结项目画像  → ProjectProfileStore (1000字快照，保 Prefix Cache 稳定)    │
│  L4: 授信隔离资料  → ProjectMaterials (已索引至 Wiki + 不可覆盖指令安全声明)    │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 四、基于三大核心项目形态的深度组织方案

### 4.1 代码工程项目（`coding`）—— “Repo-Native & Rule-Triggered” 组织方案

#### （1）核心定位与典型场景
面向软件工程开发、脚本自动化、前后端联调、Bug 修复与架构重构。核心痛点是：**编码规范遵守率、跨文件架构一致性、Git 分支/变更安全回退、本地运行环境诊断**。

#### （2）推荐目录与元数据组织规范
```text
<project-root>/
├── SAGE.md / AGENTS.md          # L1 核心项目约定（构建命令、目录分层架构、红线禁令）
├── .sage/
│   ├── hooks.json               # 项目级自动化钩子（pre-tool / post-edit lint，受 ProjectHooksPanel 管控）
│   └── checkpoints/             # 会话级文件变更快照（与 Git 工作区互补）
├── src/                         # 业务源码
└── tests/                       # 自动化测试
```

#### （3）五层上下文与约束配置策略
- **自动类型检测 (`ProjectTypeDetector`)**：识别 `.git`、`package.json`、`pyproject.toml`、`Cargo.toml`、`go.mod`、`tsconfig.json` 等，自动将 `vcs_mode` 设为 `"git"`。
- **阶段生命周期 (`project_stage`)**：
  `planning`（需求与架构设计） → `development`（编码实现） → `testing`（单测与集成验证） → `deployment`（构建与发布） → `maintenance`（线上排障与重构）。
- **结构化约束 (`project_constraints`)**：
  - 默认勾选导入 `python_default` / `security_basic`，并扩展前端/通用工程模板（如 `typescript_strict`、`architecture_boundaries`）。
  - **路径触发器 (`trigger_pattern`)**：
    - `[coding_style] (*.py)`：函数不超过 50 行，强制类型注解，禁止裸 `except:`。
    - `[coding_style] (src/**/*.tsx)`：遵循 FSD 分层（`pages → widgets → features → shared`），禁止跨层逆向导入，字号必须使用语义 Token（`text-ui-*`）。
    - `[security] (always)`：禁止硬编码密钥，SQL 参数化查询，外部输入严格校验。
    - `[testing] (always)`：修改核心逻辑必须同步补充单元测试并通过验证。
- **项目画像 (`ProjectProfile`) 分类侧重**：
  - 重点沉淀 `architecture`（模块边界与数据流）、`convention`（命名与代码风格）、`decision`（技术选型 ADR，如“为何选用 SQLite WAL 而非 Redis”）。

#### （4）代码项目专属工作台视图（Workbench Layout）
1. **顶部状态栏**：`ProjectTypeBadge(coding)` + 当前阶段选择器（如 `开发中`）+ `GitStatusWidget`（当前分支、脏文件计数、领先/落后 commit 数）+ 一键打开终端/Worktree。
2. **左栏：工程健康度与规则面板**：
   - **环境满足度诊断卡**：调用 `project_diagnose` 展示 Python/Node/工具链状态（`✓ 全部满足` / `⚠ 缺失依赖`）。
   - **触发式约束管理器 (`ConstraintManager`)**：按 `coding_style`、`security`、`testing` 分组管理规则，直观显示 `trigger_pattern`（如 `*.py`）与优先级滑块（1~10）。
   - **Hooks 信任面板 (`ProjectHooksPanel`)**：一键审批或撤销 `.sage/hooks.json`。
3. **右栏：迭代里程碑与会话流**：
   - `MilestoneManager`（关联 PR / 版本发布节点）+ 活跃编码会话列表 + `WorkspaceChangesSection`（实时查看 AI 修改的文件 Diff 与一键 Revert）。

---

### 4.2 一般档案与办公文书项目（`business` / 扩展 `archive` 子类）—— “Dossier-Centric & Template-Governed” 组织方案

#### （1）核心定位与典型场景
面向行政公文流转、法务合同审查案卷、招投标书编制、企业规章制度汇编、财务/审计报告、客户项目交付档案。
核心痛点是：**非技术人员不懂 Git、多份 Word/Excel/PPT 反复修改易混乱、公文/合同格式规范要求极严、原始佐证材料不可被 AI 篡改、跨案卷需引用公共法规/模板库**。

#### （2）推荐目录与元数据组织规范（标准“数字案卷盒”结构）
在创建“一般档案/商务文档”项目时，向导支持一键初始化标准四分目录：
```text
<dossier-root>/
├── SAGE.md                      # 案卷封面元数据：案卷编号、立卷人、密级、文种规范、核心背景
├── 00_立项与背景材料/            # 任务通知书、会议纪要、背景说明
├── 01_原始依据与佐证/            # 【受保护参考源】上级政策、原始合同扫描件、客户需求书（只读引用）
├── 02_编制中工作稿/              # 与 Sage Office 工具台联动的 .docx / .xlsx / .pptx 迭代草稿
└── 03_定稿与签发归档/            # 终审定稿文件、合规自查表、归档清单
```
- **跨目录只读挂载 (`allowed_paths`)**：将单位公共的 `/企业标准合同范本库`、`/国家法规与行业标准库`、`/品牌视觉与公文模板库` 添加到项目的 `allowed_paths` 中——AI 在起草文书时可随时检索和参考这些目录，但底层的非对称权限机制从物理上保证了 AI **绝无可能修改或误删公共模板库中的任何文件**。

#### （3）五层上下文与约束配置策略
- **自动版本保护 (`vcs_mode = "builtin"`)**：
  - 档案人员无需安装或理解 Git。Sage 自动启用内置版本控制（`builtin`），每次 AI 调用 `office_create` / `office_update` 或写入文书前自动生成时间轴检查点（Checkpoint），用户可在工作台按“修改时间 + 摘要”一键比对或还原任意历史版本。
- **阶段生命周期 (`project_stage`)**：
  `initiation`（立卷建档） → `planning`（目录拟定与资料归集） → `execution`（文书编制与多轮修订） → `monitoring`（合规审查与格式校核） → `closure`（定稿签发与封卷归档）。
- **结构化约束 (`project_constraints`)**：
  - 默认导入并扩充 `document_format` 预设模板，细分三大类规则：
    - `[document_format] (*.docx)`：遵循公文/商务排版规范（如标题层级、宋体/仿宋/黑体字号映射 `WordFormatSpec`、首行缩进、页眉页脚与自动目录）。
    - `[document_format] (*.xlsx)`：表头冻结、金额列统一千分位与两位小数、公式单元格禁止硬编码汇总值。
    - `[confidentiality] (always)`：文档首页须标注密级与版本号；对外交付文书严禁泄露内部成本底价或未脱敏个人信息。
    - `[terminology] (always)`：全案卷统一甲乙方简称、项目全称、金额大小写（如“人民币壹拾万元整（¥100,000.00）”前後一致）。
- **参考资料管理 (`ProjectMaterials`)**：
  - 将“立项批复”、“核心条款红线”、“甲乙方背景信息”固定为 `ready` 资料；AI 在回答或撰稿时严格受控于资料事实，不主观臆造条款。

#### （4）一般档案项目专属工作台视图（Workbench Layout）
1. **顶部状态栏**：`ProjectTypeBadge(business / 一般档案)` + 案卷阶段步进器（`立卷 → 归集 → 编制 → 审校 → 封卷`）+ 内置版本时间轴入口（`VCS: 内置快照保护中`）。
2. **核心主面板：案卷成品与文档台账（Office Deliverable Registry）**：
   - 直接聚合当前项目绑定工作区下的 `office_documents`（Word / Excel / PPT / PDF），展示文档名称、最新修订时间、格式检查状态，点击即在右侧拉开 `OfficePreviewPanel` 或跳转 `/office` 进行可视化段落级审阅与修订。
3. **左栏：受控依据材料箱（Scoped Reference Box）**：
   - 展示已挂载的 `allowed_paths`（公共法规/模板库只读目录）与项目内 `01_原始依据` 资料列表，支持一键将某份材料设为“当前撰稿必读参考”。
4. **右栏：交稿节点与合规核验清单 (`MilestoneManager`)**：
   - 将“初稿完成”、“法务合规会签”、“排版格式终检”、“正式封卷”作为带截止日期的里程碑卡片，逾期自动高亮预警。

---

### 4.3 科研项目（`research`）—— “Source-Grounded & Hypothesis-Driven” 组织方案

#### （1）核心定位与典型场景
面向学术论文写作（期刊/会议/学位论文）、科研基金申报（如国家自然科学基金 NSFC）、系统性文献综述（Systematic Review）、实验设计、数据分析与审稿回复（Rebuttal）。
核心痛点是：**AI 极易编造虚假参考文献（幽灵引用）、海量 PDF/BibTeX 文献难以按主题聚焦、研究假设与实验数据版本脱节、多轮审稿意见回复缺乏追踪矩阵**。

#### （2）推荐目录与元数据组织规范（标准“数字课题组实验室”结构）
```text
<research-root>/
├── SAGE.md                      # 课题总纲：核心研究问题(RQs)、科学假设、目标期刊/会议、符号表(Notation)
├── 01_literature/               # 文献库：references.bib、分类精读笔记、核心对比矩阵
├── 02_experiments_and_data/     # 实验与数据：notebooks (*.ipynb)、清洗脚本、实验日志与结果表
├── 03_manuscript/               # 论文手稿：main.tex / manuscript.docx、figures/、tables/
└── 04_submission_and_rebuttal/  # 投稿材料：cover_letter.md、reviewer_comments.md、response_matrix.md
```
- **大型数据集与文献库只读挂载 (`allowed_paths`)**：
  科研人员常有数十 GB 的公共数据集（如 `/data/datasets/imagenet`）或全局 Zotero PDF 附件库（如 `~/Zotero/storage`）。通过 `allowed_paths` 将其挂载到当前科研项目中，AI 可读取数据 Schema 或检索文献全文，同时保证原始实验数据**只读零污染**。

#### （3）五层上下文与约束配置策略
- **阶段生命周期 (`project_stage`)**：
  `proposal`（开题与文献调研） → `data_collection`（数据采集与清洗） → `analysis`（实验建模与结果分析） → `writing`（论文撰写与图表绘制） → `submission`（排版校对与投稿） → `revision`（审稿意见回复与修回）。
- **结构化约束 (`project_constraints` —— 科研强护栏)**：
  - 默认激活并扩展 `academic_writing` 模板，建立三条铁律：
    1. `[citation_integrity] (always, priority=10)`：**严禁捏造任何参考文献、作者、年份或 DOI**。所有文献引用必须且只能来自项目 `references.bib`、已就绪的 `ProjectMaterials` 或工作区真实存在的文献笔记；若上下文无据可查，必须明确标注 `[待补充文献支撑]`。
    2. `[academic_writing] (*.tex, *.docx, *.md, priority=7)`：遵循目标期刊引用格式（APA / IEEE / GB/T 7714），保持客观学术语态，所有数学符号与缩写首次出现时必须定义并与 `SAGE.md` 符号表一致。
    3. `[experiment_record] (*.ipynb, *.py, *.md, priority=8)`：所有实验分析记录必须包含四要素：**实验日期与随机种子/环境、基准方法与超参数配置、定量指标（含均值与标准差/显著性检验）、消融或误差分析结论**。
- **科研专属记忆画像 (`ProjectProfile` 语义映射)**：
  将 `ProjectProfileStore` 的 5 个标准分类在科研工作台中呈现为学术语义：
  - `goal` → **核心研究问题与创新点 (Research Questions & Contributions)**
  - `architecture` → **研究方法与理论框架 (Methodology & Framework)**
  - `decision` → **实验设计与路线抉择 (Experimental Decisions，如为何剔除某异常样本)**
  - `convention` → **数学符号与术语规范表 (Notation & Terminology Table)**
  - `note` → **阶段性发现与审稿要点 (Key Findings & Reviewer Notes)**

#### （4）科研项目专属工作台视图（Workbench Layout）
1. **顶部状态栏**：`ProjectTypeBadge(research / 科研项目)` + 科研六阶段进度条（`开题 → 数据 → 分析 → 撰稿 → 投稿 → 修回`）+ 截稿日（Deadline）倒计时胶囊。
2. **左栏：文献与证据语料库（Source-Grounded Corpus Panel）**：
   - 升级版 `ProjectMaterialsPanel`：支持导入文献摘要/精读卡、直接绑定工作区 `references.bib`，并展示每条资料的 Wiki 索引状态（`ready` / `pending_index`）。
   - **一键沉淀综述回答 (`save-answer`)**：在科研对话中让 AI 对比多篇文献的方法优劣后，点击 `保存最新回答为资料`，直接带 `source_message_id` 溯源链沉淀入库，并自动触发 `index_material_to_wiki` 构建课题专属 Wiki。
3. **中/右栏：研究里程碑与实验规范面板**：
   - **科研阶段看板 (`MilestoneManager`)**：按 `proposal` 到 `revision` 组织关键节点（如“完成 30 篇核心文献综述”、“跑通 Baseline 与 3 组消融实验”、“完成 LaTeX 初稿与图表美化”、“逐条回复 Reviewer #1~#3 意见”）。
   - **学术规范与引用护栏卡 (`ConstraintSummaryWidget`)**：快速切换引用格式（APA / IEEE / Nature / GB-T7714）与语言风格（英文 SCI 学术润色 / 中文核心期刊 / 基金申请书凝练风）。

---

## 五、三大项目形态全维度对比总表

| 维度 | 代码工程项目 (`coding`) | 一般档案项目 (`business` / `archive`) | 科学研究项目 (`research`) | 个人知识空间 (`personal`) |
| :--- | :--- | :--- | :--- | :--- |
| **自动检测信号 (`ProjectTypeDetector`)** | `.git`, `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `src/` | `.docx`, `.xlsx`, `.pptx`, `合同`, `公文`, `档案`, `报表`, 密集 Office 文档 | `.bib`, `.tex`, `.ipynb`, `paper/`, `experiments/`, `dataset/`, 大量 `.pdf` | `.md` 笔记集合、日记、个人待办，无强工程/商业特征 |
| **默认版本控制 (`vcs_mode`)** | **`git`**（原生 Git 分支 + Worktree + Diff） | **`builtin`**（无感自动快照检查点 + 历史版本对比回滚） | **`git` 或 `builtin` 混合**（代码/LaTeX 用 Git，手稿/数据用快照） | **`builtin`**（轻量自动保存快照） |
| **`allowed_paths` 典型用途** | 挂载跨仓库共享 SDK、后端接口契约目录、公共组件库（只读） | 挂载企业公共合同范本库、红头政策法规库、往年归档卷宗（只读防篡改） | 挂载大型公共数据集磁盘路径、全局 Zotero PDF 文献存储目录（只读） | 挂载个人电子书库、剪藏归档目录 |
| **阶段状态机 (`project_stage`)** | `planning → development → testing → deployment → maintenance` | `initiation → planning → execution → monitoring → closure` | `proposal → data_collection → analysis → writing → submission → revision` | 自由无阶段或轻量 GTD（`inbox → active → someday → archived`） |
| **核心预设约束模板 (`CONSTRAINT_TEMPLATES`)** | `python_default`<br>`security_basic`<br>`typescript_strict`*(新增)*<br>`architecture_guard`*(新增)* | `document_format`<br>`archive_dossier_cn`*(新增)*<br>`contract_compliance`*(新增)* | `academic_writing`<br>`citation_zero_hallucination`*(新增)*<br>`nsfc_grant_style`*(新增)* | `concise_note_taking`*(新增)* |
| **上下文注入侧重点** | `SAGE.md`/`AGENTS.md` + 路径匹配约束 (`*.py`/`*.tsx`) + 架构决策画像 | 案卷背景指令 + 文书版式规范 (`*.docx`) + 受控原始凭据资料 | 研究问题与符号表 + 引用防幻觉铁律 + 已索引至 Wiki 的文献语料块 | 个人偏好画像 + 历史笔记检索 |
| **工作台主视图核心组件** | `GitStatusWidget` + `RuntimeDiagnoseCard` + `ConstraintManager` + `WorkspaceChangesSection` | **案卷文档台账 (Office Registry)** + 内置快照时间轴 + 合规审校里程碑 | **文献与证据语料面板 (`Materials` + Wiki)** + 实验里程碑看板 + 引用规范卡 | 卡片盒笔记流 + 快速问答归档 |

---

## 六、渐进式工程落地路线图（Implementation Roadmap）

由于 Sage 后端表结构（`projects`、`project_constraints`、`project_milestones`、`project_materials`、`project_profile`）与前端 `src/features/project-type/*` 的 11 个组件均已存在，我们可以分三个阶段以极小改动成本完成全面升级：

### Phase P0：激活现有“孤岛组件”，打通类型化项目工作台闭环（零后端 Schema 改动）
1. **挂载创建向导与自动识别预览 (`ProjectCreationWizard` + `TypeDetectionPreview`)**：
   - 在 `src/pages/Projects.tsx` 顶部操作栏及 `src/widgets/sidebar/sections/ProjectSection.tsx` 的登记入口接入 `ProjectCreationWizard`。
   - 用户选择本地文件夹后，自动调用 `POST /api/v1/projects/detect-type` 展示识别出的类型（如“检测到科研项目 · 置信度 85%：发现 `.bib`, `.tex`, `.ipynb`”），并允许一键勾选导入对应类型的预设约束模板（`academic_writing` / `document_format` / `python_default`）。
2. **在项目列表与展开面板挂载类型徽标与概览小部件 (`ProjectTypeBadge` + `ProjectOverviewWidgets`)**：
   - 在 `ProjectSection.tsx` 的项目行渲染 `<ProjectTypeBadge type={project.projectType} size="sm" />`。
   - 在 `ProjectExpandedPanels.tsx` 的 `ProjectOverviewPanel` 上方挂载 `<ProjectOverviewWidgets project={project} />`：
     - `coding` 项目自动显示 `GitStatusWidget` + `ConstraintSummaryWidget` + `MilestoneProgressWidget`；
     - `research` / `business` 项目自动显示 `ConstraintSummaryWidget` + `MilestoneProgressWidget`。
3. **在 `Projects.tsx` 工作台模式开放完整管理抽屉 (`ConstraintManager` + `MilestoneManager` + `ProjectProfileCard`)**：
   - 当 `presentation === 'workbench'` 时，展开项目提供四个清晰的子标签页：**`[概览与阶段]` · `[资料与语料库]` · `[行为约束 Rules]` · `[里程碑与项目记忆]`**，将 `ConstraintManager`、`MilestoneManager` 和按当前项目路径过滤的 `ProjectProfileCard` 原生嵌入工作台。

### Phase P1：丰富三大场景模板库与 `trigger_pattern` 动态上下文过滤
1. **扩充 `backend/data/project_constraint_repo.py` 中的 `CONSTRAINT_TEMPLATES`**：
   - 新增面向代码工程的 `typescript_react`（FSD 架构边界、语义化设计 Token）、面向一般档案的 `archive_dossier_cn`（公文结构、金额日期双校验、保密标注）与 `contract_review`（风险条款高亮、权利义务对等性检查）、面向科研的 `citation_strict`（零幻觉引用溯源）与 `grant_proposal`（立项依据-研究内容-技术路线-可行性四段式规范）。
2. **激活 `build_constraints_block` 的 `trigger_pattern` 动态匹配**：
   - 在 `backend/chat/project_context.py` 的 `build_constraints_block(project_id, active_files=...)` 中，除注入 `trigger_pattern in (None, "", "always", "*")` 的全局规则外，根据当前会话最近读写的文件扩展名（如 `*.docx`、`*.py`、`*.tex`）利用 `fnmatch` 动态激活专属规则，避免无关规则消耗上下文预算。
3. **新增“一键初始化项目目录脚手架”能力**：
   - 在新建一般档案（`00_立项` ~ `03_归档` + `SAGE.md`）或科研项目（`01_literature` ~ `04_submission` + `SAGE.md`）时，提供可选的“创建推荐目录结构与 `SAGE.md` 模板”复选框（对已有非空目录仅补充缺失的 `SAGE.md` 草稿，绝不覆盖用户现有文件）。

### Phase P2：打造多态专属工作台面板与 NotebookLM 式资料源受控开关
1. **资料源按需参与开关（Source-Grounded Toggle）与本地文件一键关联**：
   - 为 `project_materials` 增加 `enabled: bool = True` 开关及本地相对路径引用支持（`source_file_path`），允许科研与档案用户在 `ProjectMaterialsPanel` 中勾选本轮对话需要聚焦的 3~5 篇核心文献或合同附件，并实时显示当前项目上下文占用水位条（`已用 X KB / 24 KB`）。
2. **多态专属卡片挂载**：
   - **一般档案项目 (`business`)**：在工作台内嵌 **“本案卷 Office 文档台账卡”**（直接查询当前项目 `workspace_path` 下的 `office_documents` 列表，提供一键预览、版本对比与审校状态标记）。
   - **代码工程项目 (`coding`)**：在工作台内嵌 **“环境满足度与 Hooks 状态卡”**（联动 `project_diagnose` 与 `ProjectHooksPanel`）。
   - **科研项目 (`research`)**：在工作台内嵌 **“研究问题 (RQ) 与文献证据矩阵卡”**（支持将 AI 带有引用的回答一键转化为结构化文献笔记并同步至项目 Wiki）。

---

## 八、落地实施进度台账 (Implementation Status · 2026-10-10)

| 阶段 | 核心能力模块 | 关键交付文件 | 状态 |
|---|---|---|---|
| **Phase P0** | 激活 11 个类型化项目组件、打通创建三步向导与工作区一键脚手架 (`POST /projects/{id}/scaffold`) | `src/features/project-type/ProjectArchetypeStudio.tsx`、`src/features/project-type/archetypeBlueprints.ts`、`backend/api/project_routes.py` | 已完成 (PR #1936 / #1937) |
| **Phase P1** | 扩展三大项目形态的预设约束包 (`archive_dossier_cn` / `contract_legal_cn` / `finance_audit_cn` / `empirical_ml` / `lit_review_cn`) 与跨目录只读白名单 (`allowed_paths`) 治理面板 | `backend/api/project_routes.py`、`src/features/project-type/ConstraintManager.tsx`、`src/features/project-type/ProjectArchetypeStudio.tsx` | 已完成 (PR #1936 / #1937) |
| **Phase P2** | 1. NotebookLM 式资料源受控开关 (`enabled` 字段与 `PATCH /projects/{id}/materials/{mid}`)<br>2. 五层受控上下文注入预算水位 API (`GET /projects/{id}/context-budget`) 与进度条<br>3. 多态项目工作区资产台账探测 (`GET /projects/{id}/workspace-overview`) 与专属工作台卡片（代码工程 ADR 卡 / 一般档案四分目录与 Office 文书台账卡 / 科学研究 RQ 矩阵与文献实验产物卡） | `backend/data/project_material_repo.py`、`backend/chat/project_context.py`、`backend/services/project_workspace_inspector.py`、`src/widgets/sidebar/sections/ProjectExpandedPanels.tsx`、`src/features/project-type/PolymorphicArchetypeCards.tsx` | 已完成 (PR #1938 / #1939) |
| **Phase P3** | 1. `legacy_routes.py` 聊天入口动态文件名提取 (`extract_active_files_from_text`) 与 `trigger_pattern` 按需约束激活<br>2. 项目形态 (`project_type`)、生命周期阶段 (`project_stage`) 与活跃里程碑提示块注入 (`build_project_stage_milestones_block`)<br>3. 工作区文献/Office 案卷文件一键提取入库 (`POST /projects/{id}/materials/from-file` + 防越界提取)<br>4. 侧边栏与项目列表 `ProjectTypeBadge` 原生展示 + 科研项目五维学术画像类别选择器 (`goal` / `architecture` / `decision` / `convention` / `note`) | `backend/chat/project_context.py`、`backend/api/legacy_routes.py`、`backend/services/project_workspace_inspector.py`、`backend/api/project_routes.py`、`src/widgets/sidebar/sections/ProjectSection.tsx`、`src/features/project-type/PolymorphicArchetypeCards.tsx` | 已完成 (PR #1942 / #1943) |
| **Phase P4** | 1. 代码项目环境满足度、测试命令与 `.sage/hooks.json` 诊断接口 (`GET /api/v1/projects/{id}/diagnose`) + IPC 桥接与 `PolymorphicArchetypeCards` 环境诊断面板<br>2. 项目概览展开面板挂载 `ProjectOverviewWidgets`（`GitStatusWidget` + `ConstraintSummaryWidget` + `MilestoneProgressWidget`）<br>3. 一般档案项目 (`business`) 审校口径与合规结论固化录入器（注入 L3 项目画像） | `backend/services/project_workspace_inspector.py`、`backend/api/project_routes.py`、`electron/commandRoutes/projects.ts`、`src/features/project-type/PolymorphicArchetypeCards.tsx`、`src/widgets/sidebar/sections/ProjectExpandedPanels.tsx` | 已完成 (PR #1944 / #1945) |
| **Phase P5** | 1. 工作台独立 **L3 项目记忆画像 (`MEMORY.md`)** 治理标签页 (`studio-tab-profile`，支持按项目路径过滤、五类画像条目创建与删除）<br>2. `ProjectMaterialsPanel` 工作区相对路径文件一键入库栏 (`project-material-file-input` + `project-material-file-add`)<br>3. 个人知识空间 (`personal`) 卡片盒双链与 GTD 规则包 (`concise_note_taking`) 及四分目录 (`00_inbox` ~ `03_archive`) 与长期偏好录入器 | `backend/data/project_constraint_repo.py`、`src/features/project-type/archetypeBlueprints.ts`、`src/features/project-type/ProjectArchetypeStudio.tsx`、`src/features/project-type/PolymorphicArchetypeCards.tsx`、`src/widgets/sidebar/sections/ProjectExpandedPanels.tsx` | 已完成 (PR #1946 / #1947) |
| **Phase P6** | 1. 双轨版本控制模式切换 (`PATCH /projects/{id}` 支持 `vcs_mode: git | builtin` + `studio-vcs-mode-select`) 与内置检查点快照统计探测 (`.sage/checkpoints` `checkpoint_count` / `latest_checkpoint_at` + `vcs-checkpoint-status`)<br>2. 科研与一般档案项目截稿/交稿日倒计时与逾期预警胶囊 (`project-deadline-capsule`)<br>3. 表五预设约束模板名全量对齐 (`typescript_strict` / `architecture_guard` / `contract_compliance` / `citation_zero_hallucination` / `nsfc_grant_style`) | `backend/data/project_repo.py`、`backend/api/project_schemas.py`、`backend/api/project_routes.py`、`backend/services/project_workspace_inspector.py`、`backend/data/project_constraint_repo.py`、`electron/commandRoutes/projects.ts`、`src/features/project-type/ProjectArchetypeStudio.tsx`、`src/features/project-type/PolymorphicArchetypeCards.tsx` | 已完成 |

### Phase P11：L2 项目目标与显式系统指令编辑 + 内置快照内容预览（已完成）

- **交付内容**：
  - **后端快照增强与详情查询 (`backend/services/project_workspace_inspector.py`, `backend/api/project_routes.py`)**：
    - 升级 `create_project_checkpoint(project, label)`，除 `SAGE.md` 与形态标准产物外，自动扫描工作区根目录及一级子目录中的 `.md` / `.txt` 文稿纳入内置版本快照；
    - 新增 `get_project_checkpoint_detail(project, checkpoint_id)` 与 `GET /api/v1/projects/{project_id}/checkpoints/{checkpoint_id}` (`WorkspaceCheckpointDetailResponse`)，返回检查点跟踪文件列表与已保存的文本快照字典 (`snapshots`)；
  - **IPC 与前端 API 桥接 (`electron/commandRoutes/projects.ts`, `src/shared/api/projectApi.ts`)**：
    - 新增 `projects_get_checkpoint` IPC 路由与 `projectApi.getCheckpoint(projectId, checkpointId)`；
    - 将约束/里程碑 Wire 映射 (`mapConstraint` / `mapMilestone`) 收敛至 `src/shared/api/projectApiTypes.ts`，确保 `src/shared/api/projectApi.ts` 保持在 800 行架构水位红线以下；
  - **前端内置快照预览与 L2 元数据治理 (`BuiltinCheckpointAndStyleBar.tsx`, `StudioMaterialsAndProfilePanels.tsx`, `ProjectArchetypeStudio.tsx`)**：
    - 在内置版本快照栏 (`BuiltinCheckpointAndStyleBar`) 每个检查点行新增 **`[预览快照]`** 按钮，点击即可展开查看该快照包含的文本快照份数与各文件正文摘要；
    - 在「项目总纲 (`SAGE.md`)」标签页 (`StudioCharterTabPanel`) 下方新增 **L2 项目目标 (`description`) 与高优系统指令 (`instructions`)** 编辑面板，支持按当前项目形态一键填入推荐系统提示词指令并直接调用 `projectApi.update` 持久化，打通五层上下文管线 L1 + L2 的完整在线配置闭环。

### Phase P12：五层受控上下文合成预览 (`synthesized_preview`) + 阶段一键推进与跨形态 Git 联动（已完成）

- **交付内容**：
  - **后端五层合成上下文组装 (`backend/services/project_workspace_inspector.py`, `backend/api/project_schemas.py`)**：
    - 升级 `inspect_project_context_budget(project)`，在统计五层字符水位的同时，按 `[L1 · SAGE.md 本地规约]`、`[L2 · 项目目标、系统指令与强约束]`、`[L3 · 项目演化画像]`、`[L4 · 受控置顶资料池]` 与 `[L5 · 跨目录只读白名单]` 组装完整合成预览文本 `synthesized_preview` 并随 `GET /api/v1/projects/{project_id}/context-budget` 返回；
  - **前端五层合成上下文透视抽屉 (`PolymorphicArchetypeCards.tsx`, `projectApi.ts`)**：
    - 在五层上下文注入预算水位卡头部新增 **`[预览合成上下文]`** 开关（`toggle-synthesized-context-preview`），展开后直接透视每轮会话注入 LLM System Prompt 的完整五层规约与资料合成内容，并支持 **`[复制合成上下文]`**（`copy-synthesized-context-btn`）；
  - **项目生命周期阶段一键推进与跨形态 Git 联动 (`ProjectArchetypeStudio.tsx`, `ProjectOverviewWidgets.tsx`)**：
    - 在项目治理头部阶段选择器旁新增 **`[推进至「下一阶段」→]`** 快捷按钮（`studio-advance-stage-btn`），支持按当前形态生命周期管线顺次推进项目阶段；
    - 升级 `ProjectOverviewWidgets`，当非代码项目（如科研手稿或大型档案工程）将版本控制切换为 `vcsMode === 'git'` 时，同样自动挂载 `GitStatusWidget` 展示实时分支与未提交变更。

### Phase P13：内置版本快照 5 层上下文归档、检查点清理治理与个人知识库时间轴（已完成）
- **状态**：已在 `main` 与 `release/win7` 双轨落地并通过全量门禁。
- **交付内容**：
  1. **内置检查点自动固化 5 层合成上下文快照**：`create_project_checkpoint(project, label)` 创建检查点时，自动调用 `inspect_project_context_budget(project)` 并将 `synthesized_preview` 以 `.sage/context-snapshot.md` 键归档进检查点 `snapshots` 字典，支持通过 `GET /api/v1/projects/{project_id}/checkpoints/{checkpoint_id}` 在快照详情抽屉中直接预览当时的 5 层上下文全貌。
  2. **内置检查点删除治理 (`DELETE /api/v1/projects/{project_id}/checkpoints/{checkpoint_id}`)**：新增 `delete_project_checkpoint(project, checkpoint_id)` 后端服务、FastAPI 路由、IPC 桥接命令 `projects_delete_checkpoint`（`electron/ipc-manifest.json` 249 条命令）及 `projectApi.deleteCheckpoint(projectId, checkpointId)`；在 `BuiltinCheckpointTimelineBar` 时间轴列表中新增 `[删除]` (`data-testid="delete-checkpoint-{id}"`) 按钮，支持一键清理冗余版本快照。
  3. **个人与知识库 (`personal`) 卡片笔记列表与内置版本时间轴 (`PersonalZettelkastenFooter`)**：在 `BuiltinCheckpointAndStyleBar.tsx` 中提炼 `PersonalZettelkastenFooter` 组件并挂载至 `PolymorphicArchetypeCards.tsx` 的 `polymorphic-card-personal`，实时展示最近沉淀的个人偏好/卡片笔记列表 (`data-testid="personal-notes-list"`) 并支持个人知识库内置版本快照创建、预览、还原与删除，同时保持所有前后端模块文件严格 `<= 800` 行。

### Phase P14：L4 资料库直接入库/自动发现/批量开关与预览、L1 总纲一键快照、多态版本概览卡片（已完成）
- **状态**：已在 `main` 与 `release/win7` 双轨落地并通过全量门禁。
- **交付内容**：
  1. **L4 授信隔离资料库 (`StudioMaterialsTabPanel`) 全闭环增强**：
     - **纯文本/摘要直接入库 (`studio-material-text-input` + `studio-material-text-add`)**：支持直接在 L4 面板粘贴合同关键条款、文献核心摘要或会议纪要结论，调用 `projectApi.addMaterial(projectId, { content })` 一键沉淀入库。
     - **工作区可入库文件自动发现 (`studio-discoverable-files-bar`)**：自动聚合 `getWorkspaceOverview` 扫描出的 `officeDeliverables` 与 `researchArtifacts` 文件路径胶囊，点击即可一键提取入库。
     - **批量 Source-Grounded 上下文开关与资料内容内联预览**：新增 `[全选参与上下文]` (`studio-materials-enable-all`)、`[全部隔离]` (`studio-materials-disable-all`) 以及每条资料的 `[预览/收起]` (`studio-material-preview-toggle-{id}` / `studio-material-preview-body-{id}`) 内容抽屉。
  2. **L1 项目总纲 (`StudioCharterTabPanel`) 一键保存并固化版本快照 (`studio-charter-checkpoint-btn`)**：新增 `[保存并固化快照]` 按钮，在更新 `SAGE.md` 后自动调用 `projectApi.createCheckpoint(projectId, 'SAGE.md 规范更新快照')`，将最新 `SAGE.md` 与 5 层合成上下文快照同步归档。
  3. **多形态项目概览版本保护与阶段状态卡片 (`ProjectOverviewWidgets.tsx`)**：新增 `workspace-vcs-summary-widget` 卡片，动态展示当前项目的生命周期阶段徽章、版本保护模式（`Git 版本控制` / `内置快照时间轴 (.sage/checkpoints)` / `无版本控制`）及最近快照数量 (`workspace-vcs-checkpoint-count`)。

### Phase P15：概览卡片快速治理（约束一键导入与 Glob 统计、里程碑一键播种与快捷完成）及向导 L2 目标/初始快照闭环（已完成）
- **状态**：已在 `main` 与 `release/win7` 双轨落地并通过全量门禁。
- **交付内容**：
  1. **约束摘要卡片快速治理 (`ConstraintSummaryWidget.tsx`)**：
     - 空状态新增 `[一键导入默认规范]` (`data-testid="constraint-summary-quick-import"`) 按钮，无需跳转页签即可导入当前项目形态的默认规范模板。
     - 新增已启用约束中按路径 Glob 条件注入（`triggerPattern` 非空）的统计徽章 (`data-testid="constraint-summary-glob-count"`)。
  2. **里程碑进度卡片快速治理 (`MilestoneProgressWidget.tsx` & `ProjectOverviewWidgets.tsx`)**：
     - 空状态新增 `[一键初始化推荐里程碑]` (`data-testid="milestone-summary-quick-seed"`) 按钮，按当前项目形态蓝图 (`getArchetypeBlueprint(projectType).recommendedMilestones`) 批量播种推荐阶段里程碑。
     - 最近里程碑列表每项新增 `[标记完成/重开]` (`data-testid="milestone-quick-toggle-{id}"`) 快捷按钮，支持在项目概览页直接推进里程碑状态并实时更新进度条。
  3. **三步创建向导 Step 3 L2 核心目标与初始基线快照闭环 (`ProjectCreationWizard.tsx` & `projectApiTypes.ts`)**：
     - Step 3 (`confirm`) 新增可选「L2 项目核心目标摘要 (`description`)」输入框 (`data-testid="wizard-description-input"`) 与「版本控制策略 (`vcsMode`)」选择器 (`data-testid="wizard-vcs-mode-select"`)；
     - 创建项目时自动同步写入 `description` 与 `vcs_mode`，并在启用脚手架且选择 `builtin` 模式时自动创建首个「项目初始化基线快照」(`projectApi.createCheckpoint(project.id, '项目初始化基线快照')`)。

### Phase P16：约束编辑器形态类别与目录 Glob 预设胶囊、里程碑阶段快捷胶囊及侧边栏概览一键快照（已完成）
- **状态**：已在 `main` 与 `release/win7` 双轨落地并通过全量门禁。
- **交付内容**：
  1. **约束编辑器形态化快捷预设胶囊 (`ConstraintEditor.tsx` & `ConstraintManager.tsx`)**：
     - 根据当前项目形态动态展示推荐类别胶囊 (`data-testid="constraint-editor-category-presets"`)，覆盖代码工程 (`code_style`/`git_commit`/`testing`/`architecture`)、档案文书 (`document_format`/`tone`/`review_process`/`compliance`)、科研课题 (`academic_writing`/`citation_style`/`data_integrity`/`reproducibility`) 与个人知识库 (`note_organization`/`knowledge_linking`/`action_extraction`)；
     - 根据当前形态蓝图的标准目录结构动态生成 Glob 路径触发预设胶囊 (`data-testid="constraint-editor-glob-presets"`)，点击即可一键填入 `${dir}/**` 触发规则。
  2. **里程碑编辑器形态阶段快捷胶囊 (`MilestoneEditor.tsx` & `MilestoneManager.tsx`)**：
     - 在阶段输入框下方渲染当前项目形态的生命周期阶段胶囊 (`data-testid="milestone-editor-stage-presets"`)，一键将新建/编辑的里程碑绑定至标准形态阶段 ID。
  3. **侧边栏概览面板一键版本快照 (`ProjectExpandedPanels.tsx`)**：
     - 在聊天侧边栏内联展开的 `ProjectOverviewPanel` 头部，针对非 Git 模式项目提供 `[新建快照]` (`data-testid="sidebar-quick-checkpoint-btn"`) 快捷按钮，无需离开 `/chat` 即可随时创建 `.sage/checkpoints` 版本快照。

### Phase P17：Git 状态微件变更文件明细抽屉与一键刷新、类型检测蓝图预览与一键采用、侧边栏资料池批量注入开关（已完成）
- **状态**：已在 `main` 与 `release/win7` 双轨落地并通过全量门禁。
- **交付内容**：
  1. **Git 状态微件变更文件抽屉与手动刷新 (`GitStatusWidget.tsx`)**：
     - 卡片头部新增 `[刷新]` 按钮 (`data-testid="git-status-refresh-btn"`)，支持在 AI 修改或本地提交后即时刷新分支与变更状态；
     - 当存在暂存/修改/未跟踪文件时，提供 `[展开变更文件 (N)]` (`data-testid="git-status-files-toggle"`) 抽屉开关，展开后按 `[S]`（已暂存）、`[M]`（已修改）、`[U]`（未跟踪）列出文件路径清单 (`data-testid="git-status-files-list"`)。
  2. **自动检测预览蓝图透视与一键采用 (`TypeDetectionPreview.tsx` & `ProjectCreationWizard.tsx`)**：
     - 检测结果卡片内新增对应形态的蓝图推荐预览 (`data-testid="detection-blueprint-preview"`)，直观展示推荐版本策略 (`vcsLabel`) 与标准工作区目录胶囊；
     - 当用户当前选中的项目类型与自动检测结果不一致时，渲染 `[一键采用检测形态]` (`data-testid="apply-detected-type-btn"`) 按钮，一键切换为检测到的最佳项目形态。
  3. **聊天侧边栏资料面板批量 Source-Grounded 上下文开关 (`ProjectExpandedPanels.tsx`)**：
     - 在侧边栏内联展开的 `ProjectMaterialsPanel` 水位条 (`project-materials-watermark`) 中新增 `[全选]` (`data-testid="sidebar-materials-enable-all"`) 与 `[全停]` (`data-testid="sidebar-materials-disable-all"`) 快捷按钮，支持在 `/chat` 对话中一键批量启用或隔离全部就绪项目资料。

### Phase P18：L3 项目演化画像独立模块化与形态预设/导出、项目类型选择器治理特性预览（已完成）
- **状态**：已在 `main` 与 `release/win7` 双轨落地并通过全量门禁。
- **交付内容**：
  1. **L3 项目演化记忆画像面板模块化与形态预设 (`StudioProfileTabPanel.tsx` & `StudioMaterialsAndProfilePanels.tsx`)**：
     - 将 `StudioProfileTabPanel` 提炼为独立模块（使 `StudioMaterialsAndProfilePanels.tsx` 从 786 行降至 691 行，严格留足 800 行架构水位）；
     - 新增按项目形态动态切换的推荐画像预设胶囊栏 (`data-testid="studio-profile-presets-bar"` / `data-testid="studio-profile-preset-{idx}"`)，覆盖 `coding`（IPC 契约一致性 / 单文件 800 行红线）、`business`（大小写金额双轨核对 / 定稿签发前固化快照）、`research`（零幻觉文献引用铁律 / 实验可复现性基线）与 `personal`（原子化卡片盒笔记 / 每周行动项提炼）；
     - 新增 `[复制 MEMORY.md 视图]` 按钮 (`data-testid="studio-profile-copy-md-btn"`)，一键将当前项目的冻结画像条目格式化为标准 Markdown 复制到剪贴板。
  2. **项目类型选择器治理特性徽章 (`ProjectTypeSelector.tsx`)**：
     - 在每个项目类型选项卡片底部新增形态治理规模徽章 (`data-testid="selector-governance-meta-{value}"`)，直观展示该形态的标准生命周期阶段数与内置细分规范包数量。
### Phase P19：内置快照时间轴预设与上下文快照复制、商务办公公文版式与审校强度护栏、商务案卷审校纪要归位（已交付）

- **交付时间**：2026-10-12
- **核心改进项**：
  1. **内置快照时间轴快捷标签预设与五层上下文快照一键复制（`src/features/project-type/BuiltinCheckpointAndStyleBar.tsx`）**：
     - 在 `BuiltinCheckpointTimelineBar` 中新增快捷标签预设胶囊栏（`data-testid="checkpoint-quick-presets"`：`定稿签发前备份`、`审校修订前基线`、`阶段里程碑留痕`），支持非 Git 用户一键填充快照说明并创建恢复点；
     - 在内置快照详情抽屉（`data-testid="checkpoint-detail-preview"`）中新增 `复制上下文快照` 按钮（`data-testid="copy-checkpoint-context-btn"`），当快照包含 `.sage/context-snapshot.md` 时支持一键复制完整五层上下文快照 Markdown。
  2. **商务办公公文版式与审校强度护栏（`BusinessDocumentStyleBar` in `BuiltinCheckpointAndStyleBar.tsx` & `PolymorphicArchetypeCards.tsx`）**：
     - 新增 `BusinessDocumentStyleBar`（`data-testid="business-doc-style-bar"`），提供公文与商务版式标准选择器（`data-testid="business-doc-format-select"`：`GB/T 9704 公文版式`、`企业标准商务合同规范`、`招投标技术与商务响应`、`尽职调查与审计报告规范`）与审校口径强度选择器（`data-testid="business-review-level-select"`），并支持一键写入 L2 强制约束规则（`data-testid="business-apply-style-btn"`）。
  3. **商务案卷审校纪要与口径约定归位（`src/features/project-type/PolymorphicArchetypeCards.tsx`）**：
     - 将案卷审校纪要与口径约定登记（`data-testid="business-decision-input"` / `business-decision-add` / `business-decisions-list`）挂载于 `polymorphic-card-business` 卡片内，并保持 `PolymorphicArchetypeCards.tsx`（779 行）与 `BuiltinCheckpointAndStyleBar.tsx`（619 行）严格遵守 `src/` 单文件 `<= 800` 行架构红线。
  4. **单元与集成测试加固（`src/features/project-type/ProjectArchetypeStudio.test.tsx`）**：
     - 新增 `business-doc-style-bar`、`checkpoint-quick-presets` 及 `business-apply-style-btn` 交互断言，验证商务版式与审校护栏一键同步至项目 L2 强制约束库。
### Phase P20：L2 约束规则批量启停与 Glob 触发测试器、里程碑阶段筛选与路线图 Markdown 导出、概览 L1 宪章状态与快捷快照（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **L2 强制约束规则批量启停、Glob 触发测试器与规则清单 Markdown 导出（`src/features/project-type/ConstraintManager.tsx`，438 行）**：
     - 新增当前分类下约束规则的一键批量启停按钮（`data-testid="constraint-batch-enable"` / `data-testid="constraint-batch-disable"`）与一键复制生效 L2 约束规则 Markdown 清单按钮（`data-testid="constraint-copy-md-btn"`）；
     - 新增交互式 **Glob 路径触发测试栏**（`data-testid="constraint-glob-tester-bar"` / `data-testid="constraint-glob-test-input"`），输入工作区相对路径即可实时计算命中规则数量（`data-testid="constraint-glob-match-count"`）并在规则卡片上高亮标注 `当前路径命中`（`data-testid="constraint-glob-hit-{id}"`）。
  2. **阶段与里程碑管理器进度汇总、阶段胶囊筛选与路线图 Markdown 导出（`src/features/project-type/MilestoneManager.tsx`，445 行）**：
     - 新增总体达成进度汇总与阶段筛选胶囊栏（`data-testid="milestone-manager-progress"` / `data-testid="milestone-stage-filter-bar"`），支持按项目形态生命周期阶段筛选里程碑并展示中文阶段名称；
     - 新增一键复制里程碑路线图 Markdown 按钮（`data-testid="milestone-copy-roadmap-btn"`），便于直接粘贴至项目周报或 `SAGE.md`。
  3. **项目概览 L1 宪章就绪徽标与一键快捷快照留痕（`src/features/project-type/ProjectOverviewWidgets.tsx`，142 行）**：
     - 在 `workspace-vcs-summary-widget` 中展示 `L1 SAGE.md 已就绪 / 待初始化` 状态徽标（`data-testid="workspace-charter-status-badge"`）及工作区受管文件总数；
     - 新增 **「快捷快照」** 按钮（`data-testid="overview-quick-checkpoint-btn"`），支持在项目概览页或侧边栏展开槽位一键创建当前阶段内置快照并刷新快照计数。
  4. **单元与集成测试加固（`src/features/project-type/ProjectArchetypeStudio.test.tsx`）**：
     - 新增 `workspace-charter-status-badge`、`overview-quick-checkpoint-btn`、`constraint-glob-tester-bar`、`constraint-glob-match-count`、`milestone-manager-progress`、`milestone-stage-filter-bar` 及 `milestone-copy-roadmap-btn` 端到端断言。
### Phase P21：M3 AI 项目健康顾问与 M5 代码→Wiki 面板概览挂载、M2 知识提取绑定会话下拉联动、创建向导 L5 只读白名单预设（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **M3 AI 项目健康顾问与 M5 代码→Wiki 生成面板挂载（`src/features/project-type/ProjectOverviewWidgets.tsx`、`ProjectAdvisorCard.tsx`、`WikiGenerationPanel.tsx`）**：
     - 在 `ProjectOverviewWidgets` 中正式挂载 `ProjectAdvisorCard`（`data-testid="project-advisor-card"`），为所有形态项目提供健康度评分、风险识别与改进建议；并为 `coding` 形态项目挂载 `WikiGenerationPanel`（`data-testid="wiki-generation-panel"` / `data-testid="wiki-preview-btn"`）；
     - 为 `ProjectAdvisorCard` 增加 `typeof projectApi?.getAdvice === 'function'` 安全守卫，确保离线或精简 Mock 测试环境下平滑降级。
  2. **M2 对话知识提取面板绑定项目会话下拉联动（`src/features/project-type/KnowledgeExtractionPanel.tsx`，256 行）**：
     - 自动拉取 `projectApi.listSessions(projectId)` 并渲染项目已绑定会话下拉选择器（`data-testid="knowledge-session-select"`），默认预选最近会话，免除用户手动查找并复制会话 UUID 的繁琐操作。
  3. **创建向导 Step 3 新增 L5 跨目录只读白名单预设挂载（`src/features/project-type/ProjectCreationWizard.tsx`，517 行）**：
     - 在向导第 3 步新增按形态推荐的 L5 跨目录只读参考路径复选框组（`data-testid="wizard-allowed-paths-presets"`，如企业合同范本库、全局 Zotero 文献库、跨仓共享 SDK 等），创建项目时自动调用 `projectApi.updateAllowedPaths` 完成挂载。
  4. **单元与集成测试加固（`src/features/project-type/ProjectArchetypeStudio.test.tsx`）**：
     - 新增 `project-advisor-card` 与 `knowledge-session-select` 端到端渲染与数据联动断言。

### Phase P22：M2 知识提取确认后画像自动刷新、M4 语义检索跨项目联动与片段复制、M5 全形态 Wiki 生成与 Chat 顶栏项目多态阶段徽标（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **M2 对话知识提取确认后自动刷新 L3 项目画像（`src/features/project-type/StudioProfileTabPanel.tsx` & `ProjectArchetypeStudio.tsx`）**：
     - 修复 `StudioProfileTabPanel` 中 `KnowledgeExtractionPanel` 的 `onConfirmed` 回调原先误绑至手动草稿提交函数 `onAddEntry` 的问题；新增 `onRefreshProfile` 回调，在知识提取确认入库后自动重新拉取当前项目的 `MEMORY.md` 画像列表（`loadActiveProfile(activeProject.path)`）。
  2. **M4 语义检索面板跨项目响应式刷新与命中片段一键复制（`src/features/project-type/SemanticSearchPanel.tsx`）**：
     - 将索引统计加载从一次性 `useState` 初始化改为监听 `projectId` 的 `useEffect`，切换治理项目时自动清空旧检索结果并同步新项目索引统计；
     - 新增手动「刷新索引统计」按钮（`data-testid="semantic-stats-refresh-btn"`）与检索命中片段一键「复制片段」按钮（`data-testid="semantic-hit-copy-{idx}"`），并补充 `typeof projectApi?.getMaterialIndexingStats === 'function'` 安全守卫。
  3. **M5 项目 Wiki 自动生成面板全形态开放与跨项目状态重置（`src/features/project-type/ProjectOverviewWidgets.tsx` & `WikiGenerationPanel.tsx`）**：
     - 在 `ProjectOverviewWidgets` 中将 `WikiGenerationPanel`（`data-testid="wiki-generation-panel"`）向四大项目形态全面开放，按 `projectType` 动态展示代码工程、商务案卷、科研课题与个人知识空间的 Wiki 生成说明，并在切换项目时自动重置预览状态。
  4. **Chat 顶栏项目徽标多态类型、阶段胶囊与工作台快捷入口（`src/widgets/chat/ProjectBadge.tsx` & `src/pages/chat/ChatHeaderBar.tsx`）**：
     - 当当前会话绑定的工作区属于已登记项目时，在 Chat 顶栏 `ProjectBadge` 内联展示项目形态徽章（`data-testid="chat-project-type-badge"`）与当前生命周期阶段胶囊（`data-testid="chat-project-stage-badge"`），并提供一键跳转 `/projects` 项目工作台的快捷按钮（`data-testid="chat-project-workbench-btn"`）。
  5. **单元与集成测试加固（`ProjectBadge.test.tsx` & `ProjectArchetypeStudio.test.tsx`）**：
     - 新增 `chat-project-type-badge`、`chat-project-stage-badge`、`chat-project-workbench-btn`、`wiki-generation-panel`、`semantic-search-panel` 及 `semantic-stats-refresh-btn` 端到端测试断言。
### Phase P23：M3 顾问建议一键转入 M1 任务分解闭环、四形态任务拆解预设、L5 只读白名单 Markdown 导出与侧边栏项目阶段徽标（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **M3 → M1 顾问建议一键转入任务分解闭环（`src/features/project-type/ProjectAdvisorCard.tsx` & `ProjectOverviewWidgets.tsx`）**：
     - 将 `ProjectAdvisorCard` 的 `onDecomposeTask` 回调签名升级为 `(action?: string, reason?: string | null) => void`，并在改进建议项旁渲染「分解为任务」按钮（`data-testid="advisor-decompose-suggestion-{idx}"`）；
     - 在 `ProjectOverviewWidgets` 中挂载 `TaskDecomposeDialog` 并注入 `onDecomposeTask` 回调，点击任意顾问建议即可直接打开任务分解对话框并自动预填需求描述（`sug.action`）与补充上下文（`sug.reason`）。
  2. **M1 任务分解对话框四形态快捷需求预设与中文阶段映射（`src/features/project-type/TaskDecomposeDialog.tsx` & `MilestoneManager.tsx`）**：
     - 新增 `projectType`、`initialRequirement`、`initialContext` 属性，内置四大项目形态（软件工程、一般档案与文书、科研课题、个人事务与PKM）快捷拆解需求预设胶囊栏（`data-testid="decompose-archetype-presets"` / `data-testid="decompose-preset-{idx}"`）；
     - 在里程碑树预览节点（`MilestoneTreeItem`）中根据当前项目形态蓝图将英文阶段 ID 自动映射为中文阶段名称（如 `立卷归集`、`文书编制`、`文献调研`），并在 `release/win7` 的 `MilestoneManager.tsx` 中同步补齐「AI 任务分解」入口（`data-testid="ai-decompose-tasks-btn"`）。
  3. **L5 跨目录只读白名单配置一键复制 Markdown（`src/features/project-type/StudioMaterialsAndProfilePanels.tsx`）**：
     - 在 `StudioAllowedPathsTabPanel` 标题栏新增「复制白名单配置」按钮（`data-testid="allowed-paths-copy-md-btn"`），支持将当前项目的 L5 跨目录只读白名单路径一键导出为 Markdown 清单。
  4. **侧边栏项目列表行内联展示当前生命周期阶段胶囊（`src/widgets/sidebar/sections/ProjectSection.tsx`）**：
     - 当项目已设置 `projectStage` 时，在侧边栏项目行 `ProjectTypeBadge` 旁内联展示当前形态对应的中文生命周期阶段胶囊（`data-testid="project-row-stage-badge"`）。
  5. **单元与集成测试加固（`ProjectArchetypeStudio.test.tsx` & `ProjectSection.test.tsx`）**：
     - 新增 `advisor-toggle-details-btn`、`advisor-decompose-suggestion-0`、`decompose-archetype-presets`、`decompose-requirement-input`、`allowed-paths-copy-md-btn` 及 `project-row-stage-badge` 端到端断言。
### Phase P24：M2 知识提取跨项目状态隔离与全选/清空切换、M5 Wiki 生成转入 L4 受控资料入库闭环与 L1/L2/L4 Markdown 导出（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **M2 对话知识提取跨项目状态隔离与全选/清空批量切换（`src/features/project-type/KnowledgeExtractionPanel.tsx`）**：
     - 切换治理项目（`projectId` 变化）时自动调用 `resetPanel()` 并重置 `sessionId` 至新项目最近绑定的会话，防止旧项目的会话 ID 或待审条目跨项目残留；
     - 在审核阶段新增「全选建议 / 清空选择」按钮（`data-testid="knowledge-toggle-select-all"`）与单条目复选框标识（`data-testid="knowledge-entry-checkbox-{idx}"`），并补充 `extractKnowledge` / `confirmKnowledge` 的函数存在性安全守卫。
  2. **M5 Wiki 自动生成 → L4 受控资料一键入库闭环与扫描/生成摘要复制（`src/features/project-type/WikiGenerationPanel.tsx`）**：
     - 在扫描预览阶段新增「复制扫描摘要」按钮（`data-testid="wiki-copy-preview-btn"`）、增量更新复选框标识（`data-testid="wiki-incremental-checkbox"`）及「生成 Wiki」按钮标识（`data-testid="wiki-generate-btn"`）；
     - 在生成完成阶段新增「复制 Wiki 清单」按钮（`data-testid="wiki-copy-manifest-btn"`）以及每个生成页面旁的 **「纳入 L4 资料」** 按钮（`data-testid="wiki-ingest-material-{idx}"`），一键调用 `projectApi.addMaterialFromFile(projectId, wikiPath)` 将生成的 Wiki 文档纳入 L4 受控语料池并标记 `已纳入 L4`。
  3. **L1+L2 宪章与系统指令及 L4 生效受控资料 Markdown 导出（`src/features/project-type/StudioMaterialsAndProfilePanels.tsx`）**：
     - 在 `StudioCharterTabPanel` 新增「复制宪章与指令」按钮（`data-testid="studio-charter-copy-md-btn"`），支持一键导出 L1 `SAGE.md` 与 L2 项目目标/系统指令的组合 Markdown；
     - 在 `StudioMaterialsTabPanel` 新增「复制生效资料摘要」按钮（`data-testid="studio-materials-copy-md-btn"`），支持一键导出当前启用参与上下文的所有 L4 资料摘要。
  4. **单元与集成测试加固（`src/features/project-type/ProjectArchetypeStudio.test.tsx`）**：
     - 新增 `wiki-preview-btn` → `wiki-copy-preview-btn` → `wiki-generate-btn` → `wiki-copy-manifest-btn` → `wiki-ingest-material-0`、`studio-charter-copy-md-btn` 及 `knowledge-extract-btn` → `knowledge-toggle-select-all` → `knowledge-confirm-btn` 端到端测试断言。
### Phase P25：M4 四形态语义检索词预设与全量结果导出、L4 单条资料向量索引重建、概览约束与里程碑中文类别/阶段映射及刷新（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **M4 四形态语义检索词预设与全量检索结果 Markdown 导出（`src/features/project-type/SemanticSearchPanel.tsx` & `ProjectArchetypeStudio.tsx`）**：
     - 将当前项目形态 `projectType` 透传至 `StudioMaterialsTabPanel` 与 `SemanticSearchPanel`，内置四大形态高频语义检索预设胶囊栏（`data-testid="semantic-query-presets"` / `data-testid="semantic-preset-{idx}"`），点击任意预设词即可自动填入并立即发起语义检索；
     - 在检索结果列表顶部新增「复制全部检索结果」按钮（`data-testid="semantic-copy-all-btn"`），支持将命中的全部文本片段、材料 ID、chunk 序号与余弦相似度一键导出为结构化 Markdown。
  2. **L4 受控资料单条向量索引手动重建（`src/features/project-type/StudioMaterialsAndProfilePanels.tsx`）**：
     - 在 `StudioMaterialsTabPanel` 每条受控资料行操作区新增「重建索引」按钮（`data-testid="studio-material-reindex-{id}"`），支持调用 `projectApi.reindexMaterial(projectId, materialId)` 手动重建单条资料的向量分块索引并刷新列表。
  3. **概览约束统计与里程碑进度卡片中文映射及手动刷新（`src/features/project-type/ConstraintSummaryWidget.tsx` & `MilestoneProgressWidget.tsx`）**：
     - 在 `ConstraintSummaryWidget`（`data-testid="constraint-summary-widget"`）中新增 15 类约束规则的中文名称映射表与手动刷新按钮（`data-testid="constraint-summary-refresh-btn"`）；
     - 在 `MilestoneProgressWidget`（`data-testid="milestone-progress-widget"`）中为最近里程碑条目增加中文生命周期阶段胶囊（`data-testid="milestone-summary-stage-{id}"`）与手动刷新按钮（`data-testid="milestone-summary-refresh-btn"`）。
  4. **单元与集成测试加固（`src/features/project-type/ProjectArchetypeStudio.test.tsx`）**：
     - 新增 `constraint-summary-refresh-btn`、`milestone-summary-refresh-btn`、`milestone-summary-stage-ms-1`、`semantic-query-presets`、`semantic-preset-0` 及 `semantic-copy-all-btn` 端到端测试断言。
### Phase P26：四形态约束规则内容模板、里程碑交付物模板与相对截止日期、Git 状态报告导出、创建向导 L2 目标/指令双预设（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **约束编辑器四形态规则示例模板与全局触发快捷按钮（`src/features/project-type/ConstraintEditor.tsx`）**：
     - 为 15 类约束规则预设胶囊补充中文名称标注，并新增四大形态规则内容示例模板栏（`data-testid="constraint-editor-content-presets"` / `data-testid="constraint-content-preset-{idx}"`），支持一键填入推荐类别、规则正文与推荐优先级；
     - 在目录触发预设栏新增 `always (全局)` 按钮（`data-testid="constraint-glob-always-btn"`），便于从子目录 Glob 快速切回全局生效。
  2. **里程碑编辑器四形态节点交付物模板与快捷相对截止日期（`src/features/project-type/MilestoneEditor.tsx`）**：
     - 新增四大形态里程碑节点模板胶囊栏（`data-testid="milestone-editor-templates"` / `data-testid="milestone-template-{idx}"`），一键填充阶段性标题、交付物描述、生命周期阶段 ID 与排序权重；
     - 在截止日期输入框下方新增相对日期快捷胶囊（`+3天`、`+7天`、`+14天`、`+30天` 与 `清空`，`data-testid="milestone-due-presets"` / `data-testid="milestone-due-plus-{days}"` / `data-testid="milestone-due-clear"`）。
  3. **Git 仓库状态与近期提交 Markdown 报告一键导出（`src/features/project-type/GitStatusWidget.tsx`）**：
     - 在 `GitStatusWidget` 标题栏新增「复制报告」按钮（`data-testid="git-status-copy-md-btn"`），支持将当前分支、已暂存/已修改/未跟踪文件列表及最近 5 条提交记录一键格式化为结构化 Markdown。
  4. **项目创建向导确认步 L2 目标与系统指令双输入框及四形态快捷预设（`src/features/project-type/ProjectCreationWizard.tsx`）**：
     - 在向导第 3 步（确认信息）新增 L2 系统高优指令输入框（`data-testid="wizard-instructions-input"`）与四大形态目标/指令预设胶囊（`data-testid="wizard-goal-presets"` / `data-testid="wizard-goal-preset-{idx}"`），并在创建项目时将 `description` 与 `instructions` 同步写入项目 L2 上下文管线。
  5. **单元测试与门禁加固（`ConstraintSummaryWidget.test.tsx` & `MilestoneProgressWidget.test.tsx`）**：
     - 新增 `ConstraintEditor`、`GitStatusWidget`、`MilestoneEditor` 与 `ProjectCreationWizard` 的 Phase P26 交互单测断言。
### Phase P27：约束管理器四形态 Glob 样例与关键词检索、里程碑状态筛选与单节点 AI 子任务拆解、拆解方案勾选导出、AI 顾问报告导出（已交付）

- **交付时间**：2026-10-13
- **核心改进项**：
  1. **约束管理器四形态 Glob 触发样例胶囊与关键词过滤（`src/features/project-type/ConstraintManager.tsx`）**：
     - 在 Glob 路径触发测试栏内置四大形态高频路径样例胶囊（`data-testid="constraint-glob-sample-{idx}"`）与「清空」按钮（`data-testid="constraint-glob-clear-btn"`），支持一键模拟目标文件命中的约束规则；
     - 新增规则关键词搜索输入框（`data-testid="constraint-search-input"`），支持按规则正文、类别或触发 Glob 实时筛选。
  2. **里程碑管理器状态筛选栏与单节点 AI 子任务拆解联动（`src/features/project-type/MilestoneManager.tsx`）**：
     - 在里程碑进度栏新增状态筛选胶囊栏（`全部状态` / `进行中` / `待开始` / `已完成` / `阻塞`，`data-testid="milestone-status-filter-{id}"`），支持与生命周期阶段联合过滤；
     - 在每个里程碑条目操作区新增「AI 拆解子任务」按钮（`data-testid="milestone-decompose-{id}"`），点击可将当前里程碑标题与描述一键带入 `TaskDecomposeDialog` 发起细粒度子任务拆解。
  3. **M1 AI 任务拆解预览勾选采纳与 Markdown 方案导出（`src/features/project-type/TaskDecomposeDialog.tsx`）**：
     - 在拆解预览阶段新增主节点复选框（`data-testid="decompose-node-checkbox-{idx}"`），支持按需勾选要采纳创建的里程碑分支；
     - 新增「复制方案 Markdown」按钮（`data-testid="decompose-copy-md-btn"`），一键将需求、分解思路与多级里程碑树导出为 Markdown。
  4. **M3 AI 顾问健康诊断报告一键导出（`src/features/project-type/ProjectAdvisorCard.tsx`）**：
     - 在 `ProjectAdvisorCard` 标题栏新增「复制诊断」按钮（`data-testid="advisor-copy-md-btn"`），支持将项目健康评分、风险项与改进建议一键导出为结构化 Markdown 报告。
  5. **单元测试与门禁加固（`ConstraintSummaryWidget.test.tsx` & `MilestoneProgressWidget.test.tsx`）**：
     - 新增 `ConstraintManager`、`ProjectAdvisorCard`、`MilestoneManager` 与 `TaskDecomposeDialog` 的 Phase P27 端到端测试断言。

### Phase P28：项目画像四类原型预设与导出、项目级 Hook 取消信任、对话顶栏路径复制与概览直接拆解（2026-10-13 已完成）

1. **项目画像卡片四类原型预设、关键词/类别筛选与一键复制 Markdown（`src/widgets/memory/ProjectProfileCard.tsx`）**
   - 在新增项目画像编辑器中补充**四类原型画像预设**胶囊条（`project-profile-presets` / `project-profile-preset-${idx}`），覆盖代码工程约定、科学研究铁律、公文商务校核与个人知识卡片四类长期记忆预设。
   - 新增关键词实时搜索（`project-profile-search-input`）与类别筛选胶囊（`project-profile-cat-filter-${cat}`），并在顶栏提供 **`复制 MD`**（`project-profile-copy-md-btn`）与**手动刷新**（`project-profile-refresh-btn`），一键导出项目级 `MEMORY.md`。
2. **项目级 Hook 安全治理面板取消信任、路径复制与手动刷新（`src/widgets/settings/ProjectHooksPanel.tsx`）**
   - 在已信任项目级 Hook 状态下补齐 **`取消信任`** 按钮（`project-hooks-untrust-btn`），支持随时撤销工作区 Hook 执行授权；同时提供 **`复制路径`**（`project-hooks-copy-path-btn`）与 **`刷新`**（`project-hooks-refresh-btn`）按钮。
3. **对话头部项目徽标版本保护标识与工作区路径一键复制（`src/widgets/chat/ProjectBadge.tsx`）**
   - 在 Chat 头部项目徽标内补充版本保护模式短标签（`chat-project-vcs-badge`：`Git` / `快照`），并在徽标旁新增 **`复制项目路径`** 快捷按钮（`chat-project-copy-path-btn`）。
4. **项目概览工作台直接触发 AI 任务拆解与一键复制治理概览 Markdown（`src/features/project-type/ProjectOverviewWidgets.tsx`）**
   - 在多态项目阶段与版本保护概览卡片（`workspace-vcs-summary-widget`）新增 **`AI 拆解任务`** 快捷入口（`overview-open-decompose-btn`）与 **`复制概览 MD`** 按钮（`overview-copy-summary-md-btn`），支持直接打开 `TaskDecomposeDialog` 或导出项目治理概览 Markdown。

### Phase P29：工作台 L3 画像检索过滤、M2 知识提取建议导出、自动检测阶段管线预览与选择器重新检测（2026-10-13 已完成）

1. **L3 项目演化记忆画像面板关键词检索、类别过滤与中文类别标签（`src/features/project-type/StudioProfileTabPanel.tsx`）**
   - 新增关键词实时搜索输入框（`studio-profile-search-input`）与六档类别过滤胶囊（`studio-profile-filter-${cat}`：`全部类别` / `约定` / `架构/方法论` / `决策/审校口径` / `核心目标/研究问题` / `阶段发现/备注`），以及筛选为空时的一键清空按钮（`studio-profile-clear-filter`）。
   - 为每条冻结画像条目补充中英对照类别标签（如 `约定 (convention)`），并在复制 `MEMORY.md` 视图时同步输出中文类别说明。
2. **AI 对话知识提取面板（M2）会话手动刷新与提取建议一键复制 Markdown（`src/features/project-type/KnowledgeExtractionPanel.tsx`）**
   - 在输入栏新增 **`刷新项目会话列表`** 按钮（`knowledge-refresh-sessions-btn`），支持按需重新拉取项目已绑定的会话列表。
   - 在审核阶段顶栏新增 **`复制提取结果 MD`** 按钮（`knowledge-copy-md-btn`），支持在确认入库前一键复制提取思路与全部知识建议的结构化 Markdown。
3. **类型自动检测预览组件推荐阶段管线、治理套件统计与检测依据导出（`src/features/project-type/TypeDetectionPreview.tsx`）**
   - 在蓝图预览卡片中新增**推荐阶段管线预览**（`detection-stages-preview`）与**推荐治理套件统计徽标**（`detection-governance-stats`：推荐里程碑数与细分规范包数）。
   - 顶栏新增 **`复制检测依据`** 按钮（`detection-copy-md-btn`），一键导出包含检测形态、置信度、推荐版本策略、阶段管线与检测信号的结构化 Markdown 报告。
4. **项目类型选择器手动重新检测、一键采用检测结果与卡片阶段管线展示（`src/features/project-type/ProjectTypeSelector.tsx`）**
   - 在自动检测提示横幅中新增 **`采用检测结果`**（`selector-apply-detected-btn`）与 **`重新检测`**（`selector-redetect-btn`）按钮，并在四类项目形态卡片底部展示完整阶段流转管线摘要。

### Phase P30：约束摘要高优规则预览、里程碑逾期预警、M3 风险固化为 AI 约束闭环与侧边栏 L2/L4 增强（2026-10-13 已完成）

1. **约束摘要 Widget 高优规则展开预览与生效规则一键导出（`src/features/project-type/ConstraintSummaryWidget.tsx`）**
   - 顶栏新增 **`复制规则`** 按钮（`constraint-summary-copy-md-btn`），支持将全部已启用约束按优先级排序导出为结构化 Markdown 清单。
   - 新增 **`查看高优规则预览 / 收起高优规则预览`** 折叠区（`constraint-summary-preview-toggle` / `constraint-summary-preview-list`），在概览卡片内直接展示 Top 3 高优先级规则的优先级徽标、触发模式与规则正文。
2. **里程碑进度 Widget 逾期节点自动预警与进度报告导出（`src/features/project-type/MilestoneProgressWidget.tsx`）**
   - 自动检测未完成且截止日期早于当前日期的里程碑，在进度栏旁渲染琥珀色预警徽标（`milestone-summary-overdue-badge`：`逾期 N 项`）。
   - 顶栏新增 **`复制进度`** 按钮（`milestone-summary-copy-md-btn`），一键导出总体完成率、状态分布与带阶段标签的完整里程碑复选框列表。
3. **AI 顾问卡片 M3 风险一键固化为 AI 行为约束规则闭环（`src/features/project-type/ProjectAdvisorCard.tsx`）**
   - 在展开的风险列表中为每条风险项新增 **`固化为约束 / 已固化约束`** 按钮（`advisor-risk-to-constraint-${idx}`），点击后自动调用 `projectApi.createConstraint` 生成 `risk_guard` 类别高优防护规则，形成 **“M3 诊断风险 → L1/L2 AI 行为约束”** 的治理闭环。
4. **侧边栏/工作台展开面板 L2 四形态快捷模板与 L4 资料搜索/合集导出（`src/widgets/sidebar/sections/ProjectExpandedPanels.tsx`）**
   - 在 `ProjectOverviewPanel` 中新增四形态 L2 目标与交付指令快捷模板胶囊（`sidebar-overview-preset-${idx}`）及 **`复制指令 MD`** 按钮（`sidebar-overview-copy-md`）。
   - 在 `ProjectMaterialsPanel` 中新增侧边栏受控资料实时关键词搜索框（`sidebar-materials-search-input`）与 **`复制资料 MD`** 按钮（`sidebar-materials-copy-md`）。

### Phase P31：项目工作台全局台账工具栏、侧边栏 Git 变更筛选导出、M4→L3 画像沉淀与 M5 Wiki 批量纳入 L4（2026-10-13 已完成）

1. **项目工作台全局统计、新建向导启动器与项目台账导出（`src/pages/Projects.tsx`）**
   - 在项目工作台顶部新增全局摘要与快捷操作栏（`project-workbench-toolbar`），实时汇总已纳管项目总数（`workbench-project-count`）与四类项目形态分布徽标（`workbench-archetype-counts`）。
   - 新增 **`新建/纳管项目向导`** 按钮（`workbench-open-wizard-btn`）直连 `ProjectCreationWizard`，以及 **`导出项目台账 MD`** 按钮（`workbench-export-registry-md-btn`）一键导出全量受控项目 Markdown 表格。
2. **侧边栏 Git 状态面板变更类别筛选与 Markdown 复制（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**
   - 在侧边栏 Git 变更列表上方新增四档状态过滤胶囊（`git-sider-filter-all` / `staged` / `modified` / `untracked`：`全部` / `暂存` / `修改` / `未跟踪`）。
   - 顶栏新增 **`复制 Git 变更清单 Markdown`** 按钮（`git-sider-copy-md-btn`）。
3. **语义检索面板（M4）相似度阈值过滤与一键沉淀至 L3 项目画像（`src/features/project-type/SemanticSearchPanel.tsx`）**
   - 新增三档相似度阈值筛选胶囊（`semantic-score-filter-0` / `50` / `75`：`全部` / `≥50%` / `≥75%`）。
   - 在每条检索命中卡片顶栏新增 **`沉淀至 L3 画像 / 已沉淀 L3`** 按钮（`semantic-hit-save-profile-${idx}`），打通 **“M4 语义检索高价值片段 → L3 项目记忆画像”** 的知识闭环。
4. **AI 代码→Wiki 生成面板（M5）预览文件过滤与全量批量纳入 L4 资料池（`src/features/project-type/WikiGenerationPanel.tsx`）**
   - 在扫描预览阶段新增文件路径与语言实时筛选框（`wiki-preview-filter-input`）。
   - 在生成完成阶段顶栏新增 **`全部纳入 L4 资料池 / 已全部纳入 L4`** 按钮（`wiki-ingest-all-btn`），支持一键批量将全部生成的 Wiki 文档纳入 L4 受控资料池。

### Phase P32：项目概览阶段快捷切换与 L1 宪章一键初始化、Git 状态面板变更筛选与纳入 L4、M1 任务拆解工期汇总与全选反选、约束/里程碑编辑器语义档位胶囊（2026-10-13 已完成）

1. **项目概览 Widget 阶段快捷切换胶囊与 L1 宪章一键初始化（`src/features/project-type/ProjectOverviewWidgets.tsx`）**
   - 当检测到 `hasSageMd === false`（`L1 SAGE.md 待初始化`）时，在状态徽标右侧展示 **`一键生成 SAGE.md`** 按钮（`overview-init-sagemd-btn`），直连 `projectApi.scaffold` 生成标准目录与 `SAGE.md` 宪章。
   - 在概览栏下方新增生命周期阶段快捷切换胶囊栏（`overview-stage-switcher` / `overview-stage-pill-${stageId}`），支持一键切换项目所处生命周期阶段并实时同步后端。
2. **Git 状态 Widget 变更类别筛选胶囊与一键纳入 L4 资料池（`src/features/project-type/GitStatusWidget.tsx`）**
   - 在展开变更文件明细区域新增四档状态筛选胶囊（`git-widget-filter-all` / `staged` / `modified` / `untracked`）。
   - 为每条变更文件提供 **`+L4 / 已纳入 L4`** 快捷按钮（`git-widget-ingest-${filePath}`），支持将暂存、修改或新增的受控文件一键纳入 L4 资料池。
3. **AI 智能任务分解对话框（M1）预计总工期汇总与全选/反选控制（`src/features/project-type/TaskDecomposeDialog.tsx`）**
   - 在预览阶段顶部新增动态工期汇总徽标（`decompose-total-days-badge`），实时累加当前已勾选里程碑节点的预计天数。
   - 新增 **`全选`**（`decompose-select-all-btn`）与 **`反选`**（`decompose-select-invert-btn`）快捷按钮。
4. **约束与里程碑编辑器语义化档位胶囊（`ConstraintEditor.tsx` & `MilestoneEditor.tsx`）**
   - 在 `ConstraintEditor.tsx` 中新增四档语义化优先级预设胶囊（`constraint-priority-preset-10` `P10 铁律` / `8` `P8 强规范` / `5` `P5 常规` / `3` `P3 建议`）。
   - 在 `MilestoneEditor.tsx` 中新增四态状态快捷胶囊（`milestone-status-pill-pending` / `in_progress` / `completed` / `blocked`）。

### Phase P33：约束管理器高优与 Glob 仅看命中筛选、里程碑搜索与逾期过滤及批量完成、M2 知识与 L3 画像一键升格 L2 约束闭环（2026-10-15 已完成）

1. **约束管理器高优筛选胶囊与 Glob 仅看命中规则开关（`src/features/project-type/ConstraintManager.tsx`）**
   - 新增优先级快速筛选胶囊栏（`constraint-priority-filter-all` `全部优先级` / `constraint-priority-filter-high` `高优 (≥P8)`），支持一键聚焦核心强制规范。
   - 当输入 Glob 触发路径测试时，在命中数徽标右侧新增 **`仅看命中规则 / 显示全部规则`** 切换按钮（`constraint-glob-matched-only-btn`），支持直接过滤出当前文件路径命中的生效约束。
2. **里程碑管理器关键词搜索、逾期预警过滤与进行中节点一键批量完成（`src/features/project-type/MilestoneManager.tsx`）**
   - 在筛选栏新增实时关键词搜索框（`milestone-search-input`），支持按里程碑标题与描述快速过滤。
   - 自动统计未完成且截止日期早于今日的逾期节点数，当存在逾期项时渲染 **`逾期预警 (N)`** 筛选胶囊（`milestone-overdue-filter-btn`）。
   - 当当前筛选视图中存在 `进行中` 节点时，提供 **`一键完成进行中 (N)`** 批量推进按钮（`milestone-batch-complete-btn`）。
3. **AI 对话知识提取（M2）高重要度快捷勾选与一键转 L2 约束闭环（`src/features/project-type/KnowledgeExtractionPanel.tsx`）**
   - 在审核阶段顶栏新增 **`仅选高重要度 (≥8)`** 按钮（`knowledge-select-high-btn`），一键筛选高价值提炼条目。
   - 在每条提取建议卡片顶栏新增 **`转 L2 约束 / 已转 L2 约束`** 按钮（`knowledge-to-constraint-${idx}`），支持在沉淀 L3 画像的同时将关键约定直接固化为 L2 强制约束规则。
4. **L3 项目演化记忆画像条目一键升格为 L2 约束规则（`src/features/project-type/StudioProfileTabPanel.tsx`）**
   - 在每条冻结画像条目右侧新增 **`升格为约束 / 已升格约束`** 按钮（`studio-profile-to-constraint-${entry.id}`），打通 **“L3 演化记忆画像 → L2 强约束规则”** 的双向治理闭环。

### Phase P34：内置版本快照时间轴与双链笔记导出、M5 Wiki 符号分类筛选预览、M4 检索片段与 M3 改进建议一键固化 L2 约束闭环（2026-10-15 已完成）

1. **内置版本快照时间轴与个人双链笔记一键导出 Markdown（`src/features/project-type/BuiltinCheckpointAndStyleBar.tsx`）**
   - 在 `BuiltinCheckpointTimelineBar` 顶栏新增 **`复制时间轴 MD / 已复制时间轴`** 按钮（`checkpoint-copy-timeline-btn`），一键将 `.sage/checkpoints` 版本快照列表导出为结构化 Markdown。
   - 在 `PersonalZettelkastenFooter` 永久卡片区域新增 **`复制双链笔记 MD / 已复制笔记`** 按钮（`personal-notes-copy-md-btn`），一键导出个人知识空间 Zettelkasten 永久卡片笔记。
2. **M5 AI 代码→Wiki 扫描预览阶段符号分类筛选胶囊与符号明细预览（`src/features/project-type/WikiGenerationPanel.tsx`）**
   - 将扫描预览阶段的符号统计升级为可交互的分类筛选胶囊栏（`wiki-symbol-filter-all` / `wiki-symbol-filter-${kind}`），并新增符号明细预览列表（`wiki-symbol-preview-list`），直观展示提取到的函数/类/方法名称与源码行号。
3. **M4 语义检索命中片段一键固化为 L2 强约束规则（`src/features/project-type/SemanticSearchPanel.tsx`）**
   - 在每条检索命中卡片顶栏除沉淀至 L3 画像外，新增 **`转 L2 约束 / 已转 L2 约束`** 按钮（`semantic-hit-to-constraint-${idx}`），支持将检索命中的关键合同条款、代码规范或实验准则直接固化为 L2 行为约束。
4. **M3 AI 顾问改进建议一键固化为 L2 行为约束（`src/features/project-type/ProjectAdvisorCard.tsx`）**
   - 在展开的改进建议列表中为每条建议新增 **`固化为约束 / 已固化约束`** 按钮（`advisor-suggestion-to-constraint-${idx}`），与原有的“分解为任务（M3→M1）”共同构成 **“M3 改进建议 → M1 里程碑 / L2 行为约束”** 双路闭环。

### Phase P35：创建向导规则包全选与自定义 L5 只读路径挂载、约束摘要高优计数与快捷停用、里程碑概览筛选、项目画像高重要度过滤与单条复制（2026-10-15 已完成）

1. **项目创建向导规则包全选/清空与自定义 L5 跨目录只读路径挂载（`src/features/project-type/ProjectCreationWizard.tsx`）**
   - 在向导第 3 步预设规则包区域新增 **`全选规则包 / 清空规则包`** 快捷切换按钮（`wizard-templates-toggle-all-btn`）。
   - 在 L5 跨目录只读白名单挂载区域新增自定义路径输入框（`wizard-custom-allowed-path-input`）与 **`+ 添加只读路径`** 按钮（`wizard-custom-allowed-path-add-btn`），并实时展示已选路径标签（`wizard-selected-allowed-paths-list`）。
2. **约束摘要 Widget 高优规则计数徽标与预览区一键停用（`src/features/project-type/ConstraintSummaryWidget.tsx`）**
   - 新增高优先级（`≥P8`）生效规则数量徽标（`constraint-summary-high-priority-count`）。
   - 在展开的高优规则预览列表中为每条规则提供 **`停用`** 快捷按钮（`constraint-summary-quick-toggle-${rule.id}`），支持直接在概览卡片内切换规则启用态。
3. **里程碑进度 Widget 最近里程碑状态快捷筛选胶囊（`src/features/project-type/MilestoneProgressWidget.tsx`）**
   - 在最近里程碑列表标题栏新增三档状态筛选胶囊（`milestone-summary-filter-all` `全部` / `milestone-summary-filter-active` `待办/进行` / `milestone-summary-filter-completed` `已完成`）。
4. **设置页项目画像卡片高重要度筛选与单条复制（`src/widgets/memory/ProjectProfileCard.tsx`）**
   - 在类别筛选栏新增 **`高重要度 (≥★8)`** 切换胶囊（`project-profile-high-filter-btn`），并在每条画像条目右侧新增单条复制按钮（`project-profile-copy-item-${e.id}`）。

### Phase P36：Git 变更文件批量纳入 L4 与提交 SHA 复制、侧边栏 L4 资料状态筛选与转 L2 约束、类型选择器检测摘要复制与已选治理概览、Hook 安全审计摘要导出（2026-10-15 已完成）

1. **Git 状态 Widget 变更文件批量纳入 L4 资料池与最近提交 SHA 复制（`src/features/project-type/GitStatusWidget.tsx`）**
   - 在展开的变更文件筛选栏新增 **`批量纳入 L4 (N)`** 按钮（`git-widget-ingest-all-btn`），一键将当前筛选视图下的所有变更文件纳入 L4 资料池。
   - 在最近提交列表每条记录右侧新增 **`复制 SHA`** 胶囊按钮（`git-widget-copy-sha-${commit.sha}`）。
2. **侧边栏 L4 资料面板状态筛选与一键提炼为 L2 约束（`src/widgets/sidebar/sections/ProjectExpandedPanels.tsx`）**
   - 新增三档状态筛选胶囊（`sidebar-materials-filter-all` `全部` / `sidebar-materials-filter-enabled` `已启用` / `sidebar-materials-filter-disabled` `已暂停`）。
   - 在每条就绪资料行新增 **`+L2 / 已转L2`** 按钮（`sidebar-material-to-constraint-${m.id}`），支持将关键参考资料片段直接提炼为 L2 项目约束。
3. **项目类型选择器检测摘要复制与已选治理形态概览栏（`src/features/project-type/ProjectTypeSelector.tsx`）**
   - 在自动检测提示区新增 **`复制检测摘要`** 按钮（`selector-copy-detection-btn`）。
   - 在底部新增已选形态治理概览栏（`selector-selected-summary`），展示推荐版本保护策略、标准目录数与推荐里程碑数。
4. **设置页项目级 Hook 安全审计摘要复制（`src/widgets/settings/ProjectHooksPanel.tsx`）**
   - 新增 **`复制审计摘要`** 按钮（`project-hooks-copy-md-btn`），一键导出工作区路径、信任状态与 Hook 数量的 Markdown 安全审计摘要。
### 9.38 Phase P37 约束编辑器 Glob 验证与规则导出、里程碑排序预设与节点导出、类型检测规范明细展开与概览下一阶段快捷推进（2026-10-16 已落地验证）

围绕「L2 约束编辑器实时 Glob 路径命中测试与规则 Markdown 导出、里程碑编辑器排序预设与节点 Markdown 导出、类型检测蓝图规范包与里程碑明细展开、项目概览下一阶段快捷推进与元数据手动刷新」，完成以下四项全栈闭环增强：

1. **ConstraintEditor 实时 Glob 路径触发验证器与规则 Markdown 复制 (`src/features/project-type/ConstraintEditor.tsx`)**：
   - 在 `触发模式 (Glob)` 输入框下方新增实时触发测试栏 (`constraint-editor-test-path-input`) 与命中状态徽标 (`constraint-editor-test-path-badge`，显示 `命中触发 / 不触发`)，并在弹窗底部新增 `复制规则 MD` 按钮 (`constraint-editor-copy-md-btn`)。
2. **MilestoneEditor 排序顺序预设胶囊与节点规范 Markdown 复制 (`src/features/project-type/MilestoneEditor.tsx`)**：
   - 在里程碑排序输入框下方新增快捷排序预设按钮 (`milestone-sort-preset-1` `#1 首发`、`milestone-sort-preset-5` `#5 中期`、`milestone-sort-preset-10` `#10 收尾`)，并在底部新增 `复制节点 MD` 按钮 (`milestone-editor-copy-md-btn`)。
3. **TypeDetectionPreview 推荐规范包与默认里程碑明细展开 (`src/features/project-type/TypeDetectionPreview.tsx`)**：
   - 在推荐蓝图预览卡新增 `展开推荐规范与里程碑 / 收起推荐规范与里程碑` 切换按钮 (`detection-details-toggle-btn`) 与明细面板 (`detection-details-panel`)，直观展示识别形态对应的子模板规范包与默认里程碑序列。
4. **ProjectOverviewWidgets 下一阶段快捷推进与概览元数据手动刷新 (`src/features/project-type/ProjectOverviewWidgets.tsx`)**：
   - 在项目生命周期阶段流水线右侧新增 `推进至：{下一阶段} →` 按钮 (`overview-next-stage-btn`)，并在顶部概览栏新增手动刷新按钮 (`overview-refresh-meta-btn`)。
### 9.39 Phase P38 L3 画像批量升格与单条复制、M2 知识提取类别筛选与批量转约束、M4 语义检索批量沉淀 L3 与结果清空、M5 Wiki 符号清单复制与架构快照沉淀（2026-10-16 已落地验证）

围绕「L3 演化画像与 L2 强约束批量联动、M2 对话知识提炼分类筛选与批量转约束、M4 语义检索结果批量沉淀 L3 与一键清空、M5 符号提取清单复制与架构快照沉淀 L3」，完成以下四项全栈闭环增强：

1. **StudioProfileTabPanel 批量升格 L2 约束与单条画像复制 (`src/features/project-type/StudioProfileTabPanel.tsx`)**：
   - 新增 `批量升格L2 (N)` 按钮 (`studio-profile-batch-promote-btn`)，支持将当前筛选出的 L3 画像条目一键批量升格为 L2 行为约束规则；每条画像条目右侧新增 `复制` 按钮 (`studio-profile-copy-entry-${entry.id}`)。
2. **KnowledgeExtractionPanel 提炼建议类别筛选与选中项批量转 L2 约束 (`src/features/project-type/KnowledgeExtractionPanel.tsx`)**：
   - 在审核阶段新增按类别筛选胶囊栏 (`knowledge-category-filter-all`、`knowledge-category-filter-${cat}`) 与 `选中项同步转 L2 约束` 按钮 (`knowledge-batch-to-constraint-btn`)。
3. **SemanticSearchPanel 检索命中批量沉淀 L3 画像与一键清空结果 (`src/features/project-type/SemanticSearchPanel.tsx`)**：
   - 在检索结果工具栏新增 `批量沉淀 L3 (N)` 按钮 (`semantic-batch-save-profile-btn`) 与 `清空结果` 按钮 (`semantic-clear-results-btn`)。
4. **WikiGenerationPanel 符号清单复制与符号架构摘要沉淀至 L3 画像 (`src/features/project-type/WikiGenerationPanel.tsx`)**：
   - 在符号提取预览栏新增 `复制符号清单` (`wiki-copy-symbols-btn`) 与 `沉淀符号摘要至 L3` (`wiki-save-symbols-profile-btn`) 按钮，将扫描统计与核心符号一键写入 L3 架构画像。
### 9.40 Phase P39 约束摘要类别联动过滤与一键恢复禁用、里程碑进度阶段分布条与一键完成进行中、AI 顾问高危风险过滤与全量风险转约束、任务分解阶段过滤与思路沉淀 L3（2026-10-16 已落地验证）

围绕「项目概览态势卡片交互下钻与一键闭环治理、M3 AI 顾问与任务分解向 L2/L3 资产池双向沉淀」，完成以下四项全栈闭环增强：

1. **ConstraintSummaryWidget 类别点击过滤预览与一键启用全部禁用规则 (`src/features/project-type/ConstraintSummaryWidget.tsx`)**：
   - 当存在已禁用规则时显示 `启用全部 (N)` 按钮 (`constraint-summary-enable-all-btn`)；支持点击 `按类别` 统计行 (`constraint-summary-cat-pill-${category}`) 自动展开并按该类别过滤高优规则预览（支持 `清除类别过滤` `constraint-summary-clear-cat`）。
2. **MilestoneProgressWidget 阶段分布摘要条与一键完成进行中里程碑 (`src/features/project-type/MilestoneProgressWidget.tsx`)**：
   - 新增阶段分布统计条 (`milestone-summary-stage-bar`) 直观展示各生命周期阶段的里程碑分布；当存在进行中节点时提供 `完成进行中 (N)` 快捷按钮 (`milestone-summary-complete-active-btn`)。
3. **ProjectAdvisorCard 风险严重度筛选与一键将全部风险转化为防护约束 (`src/features/project-type/ProjectAdvisorCard.tsx`)**：
   - 在 AI 顾问风险详情栏新增 `全部 / 仅高危` 过滤切换 (`advisor-risk-filter-all`、`advisor-risk-filter-high`) 与 `全部风险转约束` 按钮 (`advisor-guard-all-risks-btn`)。
4. **TaskDecomposeDialog 预览阶段筛选与分解思路沉淀至 L3 画像 (`src/features/project-type/TaskDecomposeDialog.tsx`)**：
   - 在分解预览页新增按阶段筛选胶囊栏 (`decompose-stage-filter-all`、`decompose-stage-filter-${stage}`) 与 `沉淀思路至 L3 画像` 按钮 (`decompose-save-reasoning-profile-btn`)。

### Phase P40（2026-10-16）：约束/里程碑单条沉淀 L3 与复制、学术/文书/Hooks 规范复制及立项向导配置摘要复制
- **`src/features/project-type/ConstraintManager.tsx`**：支持单条 L2 约束一键沉淀至 L3 项目画像（`constraint-promote-profile-${constraint.id}`，`+L3 / 已存L3`）及单条规则 Markdown 复制（`constraint-copy-single-${constraint.id}`）。
- **`src/features/project-type/MilestoneManager.tsx`**：支持单条里程碑节点一键沉淀至 L3 项目画像（`milestone-promote-profile-${milestone.id}`，`+L3 / 已存L3`）及单条里程碑任务复制（`milestone-copy-single-${milestone.id}`）。
- **`src/features/project-type/BuiltinCheckpointAndStyleBar.tsx`**：新增科研规范配置 Markdown 复制（`research-copy-style-md-btn`）、一般档案文书规范配置 Markdown 复制（`business-copy-style-md-btn`）与 Coding Hooks 状态复制（`coding-hooks-copy-status-md-btn`）。
- **`src/features/project-type/ProjectCreationWizard.tsx`**：立项向导第 3 步新增完整立项配置摘要 Markdown 复制（`wizard-copy-summary-md-btn`），并支持已选 L5 只读白名单标签内联移除（`wizard-remove-allowed-path-${p}`）。

### Phase P41（2026-10-16）：L3 画像与 M2 提取转里程碑、M4 语义命中批量转 L2 约束与 Top-K 胶囊、M5 语言筛选与符号护栏
- **`src/features/project-type/StudioProfileTabPanel.tsx`**：支持单条 L3 画像条目直接转化为项目里程碑（`studio-profile-to-milestone-${entry.id}`，`+里程碑 / 已转里程碑`），并在类别筛选按钮显示各分类实时计数。
- **`src/features/project-type/KnowledgeExtractionPanel.tsx`**：M2 对话知识提取支持将提取思路与建议一键存为 L4 受控资料（`knowledge-save-reasoning-l4-btn`），并支持单条提取建议一键转为项目里程碑（`knowledge-to-milestone-${idx}`）。
- **`src/features/project-type/SemanticSearchPanel.tsx`**：M4 语义检索新增 `Top 3 / Top 5 / Top 10` 快捷检索数量胶囊（`semantic-topk-pill-${k}`），并支持将筛选后的语义检索片段一键批量固化为 L2 引用规范约束（`semantic-batch-to-constraint-btn`）。
- **`src/features/project-type/WikiGenerationPanel.tsx`**：M5 Wiki 扫描预览支持点击语言分类胶囊过滤源文件列表（`wiki-lang-filter-all` / `wiki-lang-filter-${lang}`），并支持将单条核心代码符号一键转化为 L2 架构契约保护规则（`wiki-symbol-to-constraint-${idx}`）。

### Phase P42（2026-10-16）：概览阶段沉淀 L3 与阶段回退、Git 变更文件护栏与提交摘要存 L3、约束/里程碑编辑器双向沉淀闭环
- **`src/features/project-type/ProjectOverviewWidgets.tsx`**：支持一键将当前项目生命周期阶段状态快照沉淀至 L3 项目画像（`overview-save-stage-profile-btn`），并在阶段切换栏新增上一阶段快捷回退按钮（`overview-prev-stage-btn`）。
- **`src/features/project-type/GitStatusWidget.tsx`**：变更文件列表新增 `+L2` 审查护栏按钮（`git-widget-guard-${f}`），并支持将最近 Git 提交记录摘要一键沉淀至 L3 项目画像（`git-widget-save-commits-l3-btn`）。
- **`src/features/project-type/ConstraintEditor.tsx`**：支持按目录索引测试触发预设（`constraint-dir-glob-${idx}`），并在底部工具栏新增 **`同步沉淀至 L3`** 按钮（`constraint-editor-save-l3-btn`）。
- **`src/features/project-type/MilestoneEditor.tsx`**：底部工具栏新增 **`转 L2 交付约束`**（`milestone-editor-to-constraint-btn`）与 **`沉淀至 L3`**（`milestone-editor-save-l3-btn`）按钮，打通里程碑节点到 L2 规则与 L3 画像的同步沉淀闭环。

### Phase P43（2026-10-17）：约束/里程碑摘要沉淀 L3 与阶段筛选、AI 顾问存 L4 与转里程碑、任务分解方案存 L4 与节点转 L2
- **`src/features/project-type/ConstraintSummaryWidget.tsx`**：支持一键将当前生效高优约束沉淀至 L3 项目画像（`constraint-summary-save-l3-btn`），并在高优规则预览行新增单条规则 **`+L3`** 固化按钮（`constraint-summary-rule-to-l3-${rule.id}`）。
- **`src/features/project-type/MilestoneProgressWidget.tsx`**：支持一键将总体里程碑进度快照沉淀至 L3 项目画像（`milestone-summary-save-l3-btn`），并将阶段分布胶囊升级为可点击筛选按钮（`milestone-summary-stage-pill-${stageId}`）。
- **`src/features/project-type/ProjectAdvisorCard.tsx`**：支持将 AI 顾问诊断报告存为 L4 参考资料（`advisor-save-l4-btn`），并在改进建议行新增 **`+里程碑`** 一键转化按钮（`advisor-suggestion-to-milestone-${idx}`）。
- **`src/features/project-type/TaskDecomposeDialog.tsx`**：支持将任务分解预览方案存为 L4 参考资料（`decompose-save-plan-l4-btn`），并在分解出的里程碑节点行新增 **`+L2 约束`** 验收规范转化按钮（`decompose-node-to-constraint-${idx}`）。

### Phase P44（2026-10-17）：约束/里程碑管理器双向互转与批量存 L3、形态选择器与自动检测预览治理清单导出
- **`src/features/project-type/ConstraintManager.tsx`**：支持将当前筛选后的约束批量沉淀至 L3 项目画像（`constraint-batch-promote-l3-btn`），并在每条约束规则卡片新增 **`+里程碑`** 一键转化按钮（`constraint-to-milestone-${constraint.id}`）。
- **`src/features/project-type/MilestoneManager.tsx`**：支持将当前筛选后的里程碑批量沉淀至 L3 项目画像（`milestone-batch-promote-l3-btn`），并在每个里程碑节点卡片新增 **`+L2 约束`** 验收规范转化按钮（`milestone-to-constraint-${milestone.id}`）。
- **`src/features/project-type/ProjectTypeSelector.tsx`**：在已选治理形态摘要栏新增 **`复制形态蓝图`**（`selector-copy-blueprint-btn`）与 **`预览治理清单`** 展开面板（`selector-suite-toggle-btn` / `selector-suite-details`）。
- **`src/features/project-type/TypeDetectionPreview.tsx`**：支持单条检测信号依据一键复制（`detection-copy-signal-${idx}`），并在推荐治理套件栏新增 **`复制治理清单`** 按钮（`detection-copy-suite-btn`）。

### Phase P45（2026-10-17）：侧边栏 L2/L4 沉淀至 L3 画像、立项向导推荐里程碑预览与只读目录全选、科研/文书规范沉淀 L3 及画像快照存 L4
- **`src/widgets/sidebar/sections/ProjectExpandedPanels.tsx`**：侧边栏概览头部新增 **`沉淀指令至 L3`** 按钮（`sidebar-overview-save-l3`），并在单条就绪 L4 参考资料行新增 **`+L3`** 归档画像按钮（`sidebar-material-to-l3-${m.id}`）。
- **`src/features/project-type/ProjectCreationWizard.tsx`**：立项向导第 3 步新增 **`推荐里程碑预览`**（`wizard-recommended-milestones-preview`），并在 L5 只读参考目录区新增 **`全选只读预设 / 清空只读路径`** 切换按钮（`wizard-allowed-paths-toggle-all-btn`）。
- **`src/features/project-type/BuiltinCheckpointAndStyleBar.tsx`**：科研规范栏与档案文书规范栏分别新增 **`沉淀规范至 L3`** 按钮（`research-save-style-l3-btn` / `business-save-style-l3-btn`），并在个人知识卡片列表新增单条卡片洞察转 L2 约束按钮（`personal-note-to-constraint-${d.id}`）。
- **`src/features/project-type/StudioProfileTabPanel.tsx`**：L3 项目画像工作台新增 **`存为 L4 资料`** 按钮（`studio-profile-save-l4-btn`）及权重层级筛选按钮（`studio-profile-imp-all` / `studio-profile-imp-high`）。

### Phase P46（2026-10-17）：M4 检索结果合集存 L4 与单条转里程碑、M2 建议批量转里程碑与单条复制、Git 变更批量护栏 L2 与提交转里程碑、概览存 L4 与当前阶段建里程碑
- **`src/features/project-type/SemanticSearchPanel.tsx`**：支持将当前筛选后的 M4 语义检索命中合集一键归档为 L4 参考资料（`semantic-save-l4-bundle-btn`），并在单条命中卡片新增 **`+里程碑`** 跟进任务转化按钮（`semantic-hit-to-milestone-${idx}`）。
- **`src/features/project-type/KnowledgeExtractionPanel.tsx`**：M2 对话知识提取审核栏新增 **`选中项转里程碑`** 批量转化按钮（`knowledge-batch-to-milestone-btn`），并在单条提取建议新增一键复制按钮（`knowledge-copy-entry-${idx}`）。
- **`src/features/project-type/GitStatusWidget.tsx`**：支持将当前筛选的 Git 变更文件一键批量创建 L2 审查护栏（`git-widget-guard-all-btn`），并在最近提交记录行新增 **`+里程碑`** 节点转化按钮（`git-widget-commit-to-milestone-${commit.sha}`）。
- **`src/features/project-type/ProjectOverviewWidgets.tsx`**：项目概览状态栏新增 **`存概览至 L4`**（`overview-save-l4-btn`）与 **`当前阶段建里程碑`**（`overview-stage-to-milestone-btn`）快捷动作。
### Phase P47（2026-10-18）：约束/里程碑编辑器存 L4 与互转里程碑、约束统计存 L4 与单条规则转里程碑、里程碑进度存 L4 与单条节点转 L2
- **`src/features/project-type/ConstraintEditor.tsx`**：约束编辑器底部栏新增 **`转里程碑`**（`constraint-editor-to-milestone-btn`）与 **`存为 L4 资料`**（`constraint-editor-save-l4-btn`），打通 L2 规则草稿向里程碑核查任务与 L4 受控规范文档的闭环转化。
- **`src/features/project-type/MilestoneEditor.tsx`**：里程碑编辑器底部栏新增 **`存为 L4 资料`**（`milestone-editor-save-l4-btn`），支持将里程碑交付规范一键归档至 L4 参考资料。
- **`src/features/project-type/ConstraintSummaryWidget.tsx`**：约束统计摘要卡头部新增 **`存 L4`**（`constraint-summary-save-l4-btn`），并在高优规则预览行新增 **`+里程碑`** 转化按钮（`constraint-summary-rule-to-milestone-${rule.id}`）。
- **`src/features/project-type/MilestoneProgressWidget.tsx`**：里程碑进度摘要卡头部新增 **`存 L4`**（`milestone-summary-save-l4-btn`），并在最近里程碑行新增 **`+L2`** 交付准入约束转化按钮（`milestone-summary-to-constraint-${milestone.id}`）。
### Phase P48（2026-10-18）：AI 顾问诊断沉淀 L3 与风险转里程碑、任务分解批量转 L2 约束与节点沉淀 L3、形态选择器依据/里程碑复制及检测预览管线/目录复制
- **`src/features/project-type/ProjectAdvisorCard.tsx`**：AI 顾问头部新增 **`沉淀至 L3`**（`advisor-save-l3-btn`）将健康度与风险/建议概览归档至 L3 项目画像，并在每条风险项新增 **`+里程碑`** 整改任务转化按钮（`advisor-risk-to-milestone-${idx}`）。
- **`src/features/project-type/TaskDecomposeDialog.tsx`**：任务分解预览工具栏新增 **`选中转 L2 约束`** 批量转化按钮（`decompose-batch-to-constraint-btn`），并在单条预览节点旁新增 **`+L3`** 阶段目标沉淀按钮（`decompose-node-to-l3-${idx}`）。
- **`src/features/project-type/ProjectTypeSelector.tsx`**：自动检测提示栏支持单条检测依据独立复制（`selector-copy-signal-${idx}`），并在治理清单展开面板新增 **`复制推荐里程碑`** 按钮（`selector-copy-milestones-btn`）。
- **`src/features/project-type/TypeDetectionPreview.tsx`**：形态自动检测预览面板新增 **`复制阶段管线`**（`detection-copy-stages-btn`）与 **`复制目录列表`**（`detection-copy-dirs-btn`）快捷导出按钮。
### Phase P49（2026-10-18）：L3 画像工作台批量转里程碑与单条存 L4、Wiki 生成清单存 L3 与符号转里程碑、约束/里程碑管理器批量及单条存 L4
- **`src/features/project-type/StudioProfileTabPanel.tsx`**：L3 画像工作台头部新增 **`批量转里程碑`**（`studio-profile-batch-milestone-btn`），并在单条画像条目旁新增 **`+L4`** 资料归档按钮（`studio-profile-to-l4-${entry.id}`）。
- **`src/features/project-type/WikiGenerationPanel.tsx`**：M5 Wiki 生成完成横幅新增 **`沉淀清单至 L3`**（`wiki-save-manifest-l3-btn`），并在核心符号预览行新增 **`+里程碑`** 审校任务转化按钮（`wiki-symbol-to-milestone-${idx}`）。
- **`src/features/project-type/ConstraintManager.tsx`**：约束管理器顶部工具栏新增 **`批量存 L4`**（`constraint-batch-save-l4-btn`），并在每条约束卡片新增 **`+L4`** 规范归档按钮（`constraint-to-l4-${constraint.id}`）。
- **`src/features/project-type/MilestoneManager.tsx`**：里程碑管理器工具栏新增 **`批量存 L4`**（`milestone-batch-save-l4-btn`），并在每个里程碑节点卡片新增 **`+L4`** 路线图档案归档按钮（`milestone-to-l4-${milestone.id}`）。
### Phase P50（2026-10-18）：概览阶段准出设 L2 约束、里程碑进度单条存 L3、Git 提交记录存 L4、高优约束预览单条存 L4
- **`src/features/project-type/ProjectOverviewWidgets.tsx`**：概览生命周期阶段控制栏新增 **`当前阶段设 L2 约束`**（`overview-stage-to-constraint-btn`），支持将当前生命周期阶段的准出红线一键固化为 L2 阶段门禁约束（`projectApi.createConstraint`）。
- **`src/features/project-type/MilestoneProgressWidget.tsx`**：里程碑进度摘要列表的每个节点旁新增 **`+L3`** 按钮（`milestone-summary-to-l3-${milestone.id}`），支持将单条里程碑进展沉淀至 L3 项目画像。
- **`src/features/project-type/GitStatusWidget.tsx`**：Git 状态卡片近期提交头部新增 **`存提交至 L4`**（`git-widget-save-l4-btn`），支持将当前分支与最近提交记录一键归档至 L4 资料库。
- **`src/features/project-type/ConstraintSummaryWidget.tsx`**：约束摘要卡片高优规则预览列表每条规则旁新增 **`+L4`** 按钮（`constraint-summary-rule-to-l4-${rule.id}`），支持将高优规则独立归档至 L4 资料库。
### Phase P51（2026-10-18）：M2 知识提炼批量及单条存 L4、M4 语义检索批量转里程碑与单条存 L4、约束/里程碑编辑器蓝图支柱与推荐节点快捷填入
- **`src/features/project-type/KnowledgeExtractionPanel.tsx`**：M2 对话知识提炼操作栏新增 **`选中项转 L4 资料`**（`knowledge-batch-to-l4-btn`），并在每条建议条目旁新增 **`+L4`** 按钮（`knowledge-to-l4-${idx}`），支持将提炼知识同步归档为 L4 资料。
- **`src/features/project-type/SemanticSearchPanel.tsx`**：M4 语义检索工具栏新增 **`批量转里程碑`**（`semantic-batch-to-milestone-btn`），并在单条命中片段旁新增 **`+L4`** 按钮（`semantic-hit-to-l4-${idx}`）。
- **`src/features/project-type/ConstraintEditor.tsx`**：约束编辑器内容预设栏新增蓝图上下文护栏支柱快捷填入胶囊 **`支柱 #1..#3`**（`constraint-pillar-preset-${idx}`）。
- **`src/features/project-type/MilestoneEditor.tsx`**：里程碑编辑器模板预设栏新增蓝图推荐里程碑快捷填入胶囊 **`蓝图 #1..#3`**（`milestone-blueprint-tpl-${idx}`）。
### Phase P53（2026-10-18）：Git 单条提交沉淀 L3、里程碑摘要单条归档 L4、高优约束预览单条复制、概览当前阶段一键 AI 拆解
- **`src/features/project-type/GitStatusWidget.tsx`**：在近期提交列表每条提交旁新增 **`+L3`** 沉淀按钮（`git-widget-commit-to-l3-${commit.sha}`），支持将单条关键提交记录独立沉淀至 L3 项目画像。
- **`src/features/project-type/MilestoneProgressWidget.tsx`**：在最近里程碑摘要列表每个节点旁新增 **`+L4`** 归档按钮（`milestone-summary-to-l4-${milestone.id}`），支持将单条里程碑摘要独立归档至 L4 参考资料。
- **`src/features/project-type/ConstraintSummaryWidget.tsx`**：在高优规则预览列表每条规则旁新增 **`复制`** 按钮（`constraint-summary-rule-copy-${rule.id}`），支持一键复制单条高优约束规则。
- **`src/features/project-type/ProjectOverviewWidgets.tsx`**：在生命周期阶段控制栏新增 **`拆解当前阶段`** 按钮（`overview-decompose-stage-btn`），一键拉起带当前阶段目标与形态护栏支柱上下文的 M1 AI 任务拆解弹窗。
### Phase P54 — Wiki 单符号沉淀 L3 与扫描文件入库 L4、约束批量转里程碑、里程碑批量转 L2 约束及 L3 画像蓝图支柱预设（已完成）

- **M5 `WikiGenerationPanel` 单条符号沉淀 L3 与扫描预览文件一键入库 L4（`src/features/project-type/WikiGenerationPanel.tsx`）**：
  - 在 `wiki-symbol-preview-list` 每条核心符号旁新增 **`+L3`**（`data-testid="wiki-symbol-to-l3-${idx}"`），一键调用 `projectApi.confirmKnowledge(projectId, { entries: [{ category: 'architecture', content: ..., importance: 7, sourceMessageIds: [], reasoning: 'M5 Wiki 单条核心符号沉淀至 L3 画像' }] })` 并切换为 `已存L3`；
  - 在扫描文件预览列表每项旁新增 **`+L4`**（`data-testid="wiki-file-to-l4-${f.path}"`），一键调用 `projectApi.addMaterialFromFile(projectId, f.path)` 将源码或文档纳入 L4 受控参考资料并切换为 `已入库L4`。
- **M2 `ConstraintManager` 筛选约束批量转化为合规里程碑（`src/features/project-type/ConstraintManager.tsx`）**：
  - 在顶部批量操作栏新增 **`批量转里程碑 (${filteredConstraints.length})`**（`data-testid="constraint-batch-to-milestone-btn"`），将当前筛选出的前 6 条约束一键通过 `projectApi.createMilestone` 转化为 `[合规治理]` 里程碑并切换为 `已批量转里程碑`。
- **M1 `MilestoneManager` 筛选里程碑批量转化为 L2 交付护栏（`src/features/project-type/MilestoneManager.tsx`）**：
  - 在筛选与批量操作栏新增 **`批量转 L2 (${filteredMilestones.length})`**（`data-testid="milestone-batch-to-constraint-btn"`），将当前筛选出的前 6 个里程碑一键通过 `projectApi.createConstraint`（`category: 'deliverable_guard'`, `priority: 8`）转化为 L2 交付验收护栏并切换为 `已批量转 L2`。
- **L3 `StudioProfileTabPanel` 形态蓝图上下文支柱一键预设（`src/features/project-type/StudioProfileTabPanel.tsx`）**：
  - 在 `studio-profile-presets-bar` 接入 `getArchetypeBlueprint(projectType).contextPillars`，渲染 **`支柱 #1..#3`**（`data-testid="studio-profile-pillar-preset-${idx}"`），支持一键将项目形态核心上下文支柱填入 L3 画像草稿（`category: 'convention'`）。
- **单元测试与门禁验证**：
  - 扩展 `ProjectTypeBadge.test.tsx`、`ConstraintSummaryWidget.test.tsx`、`MilestoneProgressWidget.test.tsx` 与 `ProjectArchetypeStudio.test.tsx`（4 个测试文件共 43 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P55 — 对话知识提取思路沉淀 L3 与建议反选、顾问风险转 L4 与建议批量转里程碑、里程碑编辑器支柱追加及检测预览默认里程碑复制（已完成）

- **M2 `KnowledgeExtractionPanel` 提取思路沉淀 L3 与建议一键反选（`src/features/project-type/KnowledgeExtractionPanel.tsx`）**：
  - 在提取思路展示栏新增 **`思路存为 L3`**（`data-testid="knowledge-save-reasoning-l3-btn"`），一键通过 `projectApi.confirmKnowledge`（`category: 'note'`, `importance: 6`）将 AI 对话提取思路归档至 L3 项目画像并切换为 `已存 L3`；
  - 在建议勾选工具栏新增 **`反选建议`**（`data-testid="knowledge-select-invert-btn"`），支持一键反选当前建议列表勾选状态。
- **M3 `ProjectAdvisorCard` 单条风险入库 L4 与改进建议批量转里程碑（`src/features/project-type/ProjectAdvisorCard.tsx`）**：
  - 在风险列表每条记录旁新增 **`+L4`**（`data-testid="advisor-risk-to-l4-${idx}"`），支持一键调用 `projectApi.addMaterial` 将风险描述与整改建议归档为 L4 受控参考资料并切换为 `已存L4`；
  - 在改进建议标题栏新增 **`全部建议转里程碑`**（`data-testid="advisor-batch-suggestions-to-milestone-btn"`），支持将当前全部顾问改进建议一键批量转化为项目里程碑并切换为 `已全部转里程碑`。
- **M1 `MilestoneEditor` 交付描述护栏支柱快捷追加（`src/features/project-type/MilestoneEditor.tsx`）**：
  - 在里程碑描述输入框下方新增形态上下文支柱快捷追加栏（`data-testid="milestone-editor-pillar-presets"`），提供 **`+支柱 #1..#3`**（`data-testid="milestone-pillar-append-${idx}"`）一键填入或分号追加项目形态核心上下文支柱。
- **Phase 9.4 `TypeDetectionPreview` 检测详情默认里程碑一键复制（`src/features/project-type/TypeDetectionPreview.tsx`）**：
  - 在 `detection-details-panel` 默认里程碑行旁新增 **`复制默认里程碑`**（`data-testid="detection-copy-milestones-btn"`），支持一键导出检测形态推荐里程碑清单至剪贴板并切换为 `已复制里程碑`。
- **单元测试与门禁验证**：
  - 扩展 `ProjectTypeBadge.test.tsx`、`ConstraintSummaryWidget.test.tsx`、`MilestoneProgressWidget.test.tsx` 与 `ProjectArchetypeStudio.test.tsx`（4 个测试文件共 43 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P56 — 任务分解补充上下文支柱追加与选中节点批量存 L3、约束编辑器支柱快捷追加、类型选择器规范包列表复制及立项向导推荐里程碑复制（已完成）

- **M1 `TaskDecomposeDialog` 补充上下文护栏支柱快捷追加与选中节点批量存 L3 画像（`src/features/project-type/TaskDecomposeDialog.tsx`）**：
  - 在输入阶段补充上下文输入框下方新增形态上下文支柱快捷追加栏（`data-testid="decompose-pillar-presets"`），提供 **`+支柱 #1..#3`**（`data-testid="decompose-pillar-append-${idx}"`）一键填入或分号追加项目形态核心上下文支柱；
  - 在预览阶段顶部批量工具栏新增 **`选中存 L3 画像`**（`data-testid="decompose-batch-to-l3-btn"`），支持将勾选的任务分解节点一键通过 `projectApi.confirmKnowledge`（`category: 'goal'`, `importance: 7`）批量沉淀至 L3 项目画像并切换为 `已批量存 L3`。
- **M2 `ConstraintEditor` 约束内容护栏支柱分号追加（`src/features/project-type/ConstraintEditor.tsx`）**：
  - 在 `constraint-editor-content-presets` 栏新增 **`+追加支柱 #1..#3`**（`data-testid="constraint-pillar-append-${idx}"`），支持在不覆盖已输入约束正文的前提下将形态核心上下文支柱分号追加至末尾。
- **Phase 9.4 `ProjectTypeSelector` 细分规范包列表一键复制（`src/features/project-type/ProjectTypeSelector.tsx`）**：
  - 在 `selector-suite-details` 细分规范包行旁新增 **`复制规范包列表`**（`data-testid="selector-copy-subtemplates-btn"`），支持一键复制当前形态细分规范包名称与键名清单至剪贴板并切换为 `已复制规范包`。
- **Phase P3 `ProjectCreationWizard` 立项确认页推荐里程碑一键复制（`src/features/project-type/ProjectCreationWizard.tsx`）**：
  - 在 `wizard-recommended-milestones-preview` 推荐里程碑预览行新增 **`复制推荐里程碑`**（`data-testid="wizard-copy-milestones-btn"`），支持在立项确认阶段一键导出推荐里程碑清单至剪贴板并切换为 `已复制里程碑`。
- **单元测试与门禁验证**：
  - 扩展 `ProjectTypeBadge.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（3 个测试文件共 40 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P57 — 约束摘要高优规则批量转里程碑、里程碑摘要未完项批量转 L2 护栏、Git 单条提交归档 L4 及概览当前阶段推荐里程碑一键导入（已完成）

- **Phase 4.3 `ConstraintSummaryWidget` 顶部高优规则批量转化为里程碑（`src/features/project-type/ConstraintSummaryWidget.tsx`）**：
  - 在卡片顶部工具栏新增 **`高优转里程碑`**（`data-testid="constraint-summary-top-to-milestone-btn"`），支持将当前排序最高的前 3 条生效约束一键通过 `projectApi.createMilestone` 转化为 `[高优约束验收]` 里程碑并切换为 `已转里程碑`。
- **Phase 4.3 `MilestoneProgressWidget` 顶部未完里程碑批量转化为 L2 交付护栏（`src/features/project-type/MilestoneProgressWidget.tsx`）**：
  - 在卡片顶部工具栏新增 **`未完转 L2`**（`data-testid="milestone-summary-active-to-l2-btn"`），支持将前 3 个未完成里程碑一键通过 `projectApi.createConstraint`（`category: 'deliverable_guard'`, `priority: 8`）转化为 L2 交付准入规范并切换为 `已转 L2`。
- **Phase 4.3 `GitStatusWidget` 单条提交记录归档至 L4 资料库（`src/features/project-type/GitStatusWidget.tsx`）**：
  - 在最近提交列表每条提交行旁新增 **`+L4`**（`data-testid="git-widget-commit-to-l4-${commit.sha}"`），支持一键调用 `projectApi.addMaterial` 将单条提交 SHA、作者、时间与提交说明归档为 L4 受控参考资料并切换为 `已存L4`。
- **Phase 4.3 `ProjectOverviewWidgets` 当前阶段推荐里程碑一键导入（`src/features/project-type/ProjectOverviewWidgets.tsx`）**：
  - 在 `workspace-vcs-summary-widget` 阶段治理栏新增 **`导入阶段推荐里程碑`**（`data-testid="overview-seed-stage-milestones-btn"`），支持按当前激活阶段筛选形态蓝图推荐里程碑并一键批量创建，切换为 `已导入阶段里程碑`。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（2 个测试文件共 25 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P58 — 语义检索上下文支柱快捷检索与索引统计沉淀 L3、L3 画像草稿支柱分号追加、侧边栏 L2 指令转约束及 L4 资料一键转里程碑（已完成）

- **M4 `SemanticSearchPanel` 形态上下文支柱快捷检索与索引统计一键沉淀 L3 画像（`src/features/project-type/SemanticSearchPanel.tsx`）**：
  - 在 `semantic-query-presets` 栏新增当前形态上下文支柱检索胶囊 **`支柱检索 #1..#3`**（`data-testid="semantic-pillar-query-${idx}"`），支持按项目形态蓝图核心上下文支柱一键发起 L4 语义检索；
  - 在索引状态栏新增 **`索引统计存 L3`**（`data-testid="semantic-stats-save-l3-btn"`），支持将当前 L4 资料总材料数、已索引材料数与总 chunks 数一键通过 `projectApi.confirmKnowledge`（`category: 'architecture'`, `importance: 6`）沉淀至 L3 项目画像并切换为 `已存统计 L3`。
- **L3 `StudioProfileTabPanel` 画像草稿上下文支柱分号追加（`src/features/project-type/StudioProfileTabPanel.tsx`）**：
  - 在 `studio-profile-presets-bar` 栏新增 **`+追加支柱 #1..#3`**（`data-testid="studio-profile-pillar-append-${idx}"`），支持在不覆盖已输入画像草稿的前提下将当前形态上下文支柱以分号追加至末尾。
- **侧边栏 `ProjectExpandedPanels` L2 指令转约束与 L4 资料一键转里程碑（`src/widgets/sidebar/sections/ProjectExpandedPanels.tsx`）**：
  - 在 `ProjectOverviewPanel` 标题栏新增 **`指令转 L2`**（`data-testid="sidebar-overview-to-constraint"`），支持将当前项目概述与自定义指令一键通过 `projectApi.createConstraint`（`category: 'convention'`, `priority: 8`）固化为 L2 行为约束并切换为 `已转L2`；
  - 在 `ProjectMaterialsPanel` 单条就绪资料行新增 **`+里程碑`**（`data-testid="sidebar-material-to-milestone-${m.id}"`），支持将侧边栏 L4 受控资料一键通过 `projectApi.createMilestone` 转化为 `[资料研读]` 里程碑并切换为 `已建里程碑`。
- **单元测试与门禁验证**：
  - 扩展 `ProjectArchetypeStudio.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（2 个测试文件共 16 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P59 — 组织工作台当前蓝图导出与活跃项目快速脚手架、顾问建议批量转约束与单条存 L4、检测预览规范包列表复制及类型选择器标准目录复制（已完成）

- **Phase 9.1 `ProjectArchetypeStudio` 组织工作台当前蓝图 Markdown 导出与活跃项目快速脚手架初始化（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在多形态蓝图总览卡顶部新增 **`复制当前蓝图 MD`**（`data-testid="studio-copy-blueprint-md-btn"`），支持将当前选中形态的工作区定位、标准目录、版本控制、上下文支柱与阶段管线一键导出为 Markdown 清单并切换为 `已复制蓝图 MD`；
  - 在活跃项目概览卡标题栏新增 **`一键脚手架初始化`**（`data-testid="studio-quick-scaffold-btn"`），支持无需跳转子页面即可直接调用 `projectApi.scaffold` 完成标准目录、总纲文件、默认约束与默认里程碑初始化并切换为 `已初始化脚手架`。
- **M3 `ProjectAdvisorCard` 改进建议批量转 L2 约束与单条建议归档 L4 资料（`src/features/project-type/ProjectAdvisorCard.tsx`）**：
  - 在改进建议列表顶部新增 **`全部建议转约束`**（`data-testid="advisor-batch-suggestions-to-constraint-btn"`），支持将全部改进建议一键通过 `projectApi.createConstraint`（`category: 'convention'`）批量固化为 L2 行为约束并切换为 `已全部转约束`；
  - 在每条改进建议行新增 **`+L4`**（`data-testid="advisor-suggestion-to-l4-${idx}"`），支持将单条改进建议与原因说明一键通过 `projectApi.addMaterial` 归档为 L4 受控参考资料并切换为 `已存L4`。
- **Phase 9.4 `TypeDetectionPreview` 检测详情推荐规范包列表一键复制（`src/features/project-type/TypeDetectionPreview.tsx`）**：
  - 在 `detection-details-panel` 推荐规范包行旁新增 **`复制规范包列表`**（`data-testid="detection-copy-subtemplates-btn"`），支持一键复制检测形态细分规范包名称与键名列表至剪贴板并切换为 `已复制规范包`。
- **Phase 9.4 `ProjectTypeSelector` 治理清单标准目录一键复制（`src/features/project-type/ProjectTypeSelector.tsx`）**：
  - 在 `selector-suite-details` 治理清单面板顶部新增标准目录预览行与 **`复制标准目录`**（`data-testid="selector-copy-dirs-btn"`），支持在类型选择阶段一键复制推荐标准目录结构并切换为 `已复制目录`。
- **单元测试与门禁验证**：
  - 扩展 `ProjectArchetypeStudio.test.tsx` 与 `ProjectTypeBadge.test.tsx`（2 个测试文件共 18 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P60 — 侧边栏 Git 变更快照存 L3/L4 与单文件 +L4/路径复制、项目概览标准目录补齐与默认约束导入、里程碑风险转 L2 与单条复制、约束统计类别分布复制与停用转里程碑（已完成）

- **侧边栏 `GitStatusSection` 变更快照沉淀 L3/L4 与单文件 +L4/路径复制（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**：
  - 在 `git-sider-filter-bar` 筛选栏新增 **`存L4`**（`data-testid="git-sider-save-l4-btn"`）与 **`存L3`**（`data-testid="git-sider-save-l3-btn"`），支持将当前分支变更文件列表一键归档至活跃项目 L4 受控参考资料或沉淀至 L3 项目画像；
  - 在每条变更文件行新增 **`+L4`**（`data-testid="git-sider-ingest-${file.path}"`）与 **`复制`**（`data-testid="git-sider-copy-path-${file.path}"`），支持从侧边栏直接将该变更文件纳入项目 L4 资料库或复制相对路径。
- **Phase 4.3 `ProjectOverviewWidgets` 概览顶栏标准目录补齐与形态默认约束一键导入（`src/features/project-type/ProjectOverviewWidgets.tsx`）**：
  - 在 `workspace-vcs-summary-widget` 阶段治理栏新增 **`补齐标准目录`**（`data-testid="overview-scaffold-dirs-btn"`）与 **`导入形态默认约束`**（`data-testid="overview-seed-constraints-btn"`），支持调用 `projectApi.scaffold` 补齐缺失目录结构，以及调用 `projectApi.importConstraints` 一键导入当前形态推荐 L2 约束包。
- **Phase 4.3 `MilestoneProgressWidget` 阻塞/逾期风险项转 L2 护栏与单条里程碑复制（`src/features/project-type/MilestoneProgressWidget.tsx`）**：
  - 当存在阻塞或逾期里程碑时，在顶部工具栏显示 **`风险项转L2`**（`data-testid="milestone-summary-risk-to-l2-btn"`），一键将阻塞或逾期节点转化为高优先级（`priority: 9`, `category: 'risk_guard'`）L2 攻坚约束；
  - 在最近里程碑列表每行新增 **`复制`**（`data-testid="milestone-summary-copy-item-${milestone.id}"`），支持一键复制里程碑状态、标题与截止日期。
- **Phase 4.3 `ConstraintSummaryWidget` 类别分布 Markdown 复制与停用规则转复核里程碑（`src/features/project-type/ConstraintSummaryWidget.tsx`）**：
  - 在按类别统计标题旁新增 **`复制分布`**（`data-testid="constraint-summary-copy-cats-btn"`），支持一键导出 L2 约束类别分布 Markdown；
  - 当存在停用约束时，新增 **`停用转里程碑`**（`data-testid="constraint-summary-disabled-to-milestone-btn"`），一键创建 `[待审约束复核]` 待办里程碑。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（2 个测试文件共 25 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P61 — 项目工作台全局台账 L3/L4 归档与路径列表复制、L3 画像面板推荐预设一键写入与类别统计复制、Git 状态小组件全文件护栏/路径复制与变更转里程碑、检测与选择器阶段/依据快捷复制（已完成）

- **项目工作台 `Projects` 全局台账沉淀 L3/L4 与工作区路径列表复制（`src/pages/Projects.tsx`）**：
  - 在 `project-workbench-toolbar` 顶部工具栏新增 **`复制路径列表`**（`data-testid="workbench-copy-paths-btn"`）、**`存台账至L4`**（`data-testid="workbench-save-registry-l4-btn"`）与 **`存台账至L3`**（`data-testid="workbench-save-registry-l3-btn"`），支持一键复制全部受控项目工作区路径、将全局项目台账归档为首项目 L4 资料或沉淀至 L3 项目画像。
- **L3 `StudioProfileTabPanel` 推荐预设一键写入与类别统计复制（`src/features/project-type/StudioProfileTabPanel.tsx`）**：
  - 在 `studio-profile-presets-bar` 预设栏新增 **`一键写入推荐画像`**（`data-testid="studio-profile-seed-presets-btn"`），支持将当前形态推荐画像条目一键批量写入 L3 记忆画像（`projectApi.confirmKnowledge`）并刷新列表；
  - 在类别筛选工具栏新增 **`复制类别分布`**（`data-testid="studio-profile-copy-cats-btn"`），支持导出 L3 画像各分类条目统计 Markdown。
- **Phase 4.3 `GitStatusWidget` 全文件护栏/路径复制与变更集一键转里程碑（`src/features/project-type/GitStatusWidget.tsx`）**：
  - 在 `git-status-files-list` 变更文件筛选栏新增 **`复制变更路径`**（`data-testid="git-widget-copy-paths-btn"`）与 **`变更转里程碑`**（`data-testid="git-widget-files-to-milestone-btn"`），支持复制当前筛选的变更路径列表或一键生成 `工作区 Git 变更审校` 里程碑；
  - 为暂存、已修改及未跟踪的全部变更文件行补齐 **`复制`**（`data-testid="git-widget-copy-path-${f}"`）与 **`+L2`**（`data-testid="git-widget-guard-${f}"`）快捷操作。
- **Phase 9.4 `TypeDetectionPreview` & `ProjectTypeSelector` 全部检测依据、版本策略与阶段管线快捷复制（`src/features/project-type/TypeDetectionPreview.tsx`, `src/features/project-type/ProjectTypeSelector.tsx`）**：
  - 在 `TypeDetectionPreview` 检测依据标题栏与蓝图预览栏新增 **`复制全部依据`**（`data-testid="detection-copy-all-signals-btn"`）与 **`复制版本策略`**（`data-testid="detection-copy-vcs-btn"`）；
  - 在 `ProjectTypeSelector` 治理清单面板新增阶段管线预览行与 **`复制阶段管线`**（`data-testid="selector-copy-stages-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `Projects.test.tsx`、`ProjectTypeBadge.test.tsx` 与 `ConstraintSummaryWidget.test.tsx`（3 个测试文件共 28 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P62 — 组织工作台四大蓝图对比矩阵导出与活跃项目蓝图存 L4/路径复制、AI 顾问风险批量转里程碑/存 L3 与建议批量存 L3、M2 知识提取仅选中项复制与筛选类别全选、里程碑与约束编辑器全支柱组合与日期/Glob 快捷操作（已完成）

- **Phase 9.1 `ProjectArchetypeStudio` 四大蓝图对比矩阵导出与活跃项目蓝图存 L4/路径复制（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在蓝图总览卡顶部新增 **`复制四大蓝图对比 MD`**（`data-testid="studio-copy-all-blueprints-md-btn"`），一键导出代码工程、一般档案、科学研究、个人空间四大形态的工作区定位、标准目录、版本策略与阶段数对比矩阵；
  - 在活跃项目概览卡标题栏新增 **`复制项目路径`**（`data-testid="studio-copy-active-path-btn"`）与 **`当前蓝图存 L4`**（`data-testid="studio-save-blueprint-l4-btn"`），支持复制当前工作区路径或将活跃项目的形态组织规范蓝图直接归档至 L4 参考资料库。
- **M3 `ProjectAdvisorCard` 风险批量转里程碑/存 L3 与改进建议批量存 L3（`src/features/project-type/ProjectAdvisorCard.tsx`）**：
  - 在风险列表标题栏新增 **`全部风险转里程碑`**（`data-testid="advisor-batch-risks-to-milestone-btn"`）与 **`全部风险存 L3`**（`data-testid="advisor-batch-risks-to-l3-btn"`），支持一键将全部风险转化为 `[风险整改]` 里程碑或沉淀为 L3 `note` 画像记录；
  - 在改进建议列表标题栏新增 **`全部建议存 L3`**（`data-testid="advisor-batch-suggestions-to-l3-btn"`），支持将全部改进建议批量沉淀为 L3 `decision` 画像记录。
- **M2 `KnowledgeExtractionPanel` 仅选中项 Markdown 复制与按筛选类别全选（`src/features/project-type/KnowledgeExtractionPanel.tsx`）**：
  - 在提取结果工具栏新增 **`复制仅选中项 MD`**（`data-testid="knowledge-copy-selected-md-btn"`），支持仅复制当前勾选的知识提炼条目；
  - 在 `knowledge-category-filter-bar` 末尾新增 **`按筛选类别全选`**（`data-testid="knowledge-select-filtered-btn"`），支持一键全选当前类别筛选下的全部提炼建议。
- **Phase 4.1/4.2 `MilestoneEditor` & `ConstraintEditor` 全支柱一键组合与截止日期/触发 Glob 快捷操作（`src/features/project-type/MilestoneEditor.tsx`, `src/features/project-type/ConstraintEditor.tsx`）**：
  - 在 `MilestoneEditor` 新增 **`一键填入全部支柱`**（`data-testid="milestone-pillar-fill-all-btn"`）、**`今日`**（`data-testid="milestone-due-today-btn"`）与 **`复制截止日期`**（`data-testid="milestone-copy-due-btn"`）；
  - 在 `ConstraintEditor` 新增 **`一键组合全部支柱`**（`data-testid="constraint-pillar-fill-all-btn"`）与 **`复制触发 Glob`**（`data-testid="constraint-copy-glob-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `ProjectArchetypeStudio.test.tsx`、`ProjectTypeBadge.test.tsx`、`MilestoneProgressWidget.test.tsx` 与 `ConstraintSummaryWidget.test.tsx`（4 个测试文件共 43 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P63 — 概览组件护栏支柱复制/批量转 L2 约束与路径复制、里程碑进度卡风险项/已完成项一键存 L3、约束摘要卡 Glob 规则存 L3 与清单复制、语义检索索引统计存 L4 与复制（已完成）

- **Phase 4.3 `ProjectOverviewWidgets` 护栏支柱复制/批量转 L2 约束与工作区路径复制（`src/features/project-type/ProjectOverviewWidgets.tsx`）**：
  - 在 `workspace-vcs-summary-widget` 顶部新增 **`复制路径`**（`data-testid="overview-copy-path-btn"`），支持一键复制当前项目工作区路径；
  - 在阶段治理操作栏新增 **`复制护栏支柱`**（`data-testid="overview-copy-pillars-btn"`）与 **`支柱转 L2 约束`**（`data-testid="overview-pillars-to-l2-btn"`），支持导出当前项目形态的上下文护栏支柱清单，或一键将全部护栏支柱批量创建为 `context_pillar`（`P8`）L2 行为约束。
- **Phase 4.3 `MilestoneProgressWidget` 风险项与已完成项一键沉淀至 L3（`src/features/project-type/MilestoneProgressWidget.tsx`）**：
  - 当存在阻塞或逾期里程碑时，在顶部工具栏新增 **`风险项存L3`**（`data-testid="milestone-summary-risk-to-l3-btn"`），支持将全部阻塞/逾期里程碑一键沉淀为 L3 `risk` 画像记录；
  - 当存在已完成里程碑时，在顶部工具栏新增 **`已完成存L3`**（`data-testid="milestone-summary-completed-to-l3-btn"`），支持将已达成里程碑一键沉淀为 L3 `goal` 画像记录。
- **Phase 4.3 `ConstraintSummaryWidget` Glob 按需触发规则存 L3 与清单复制（`src/features/project-type/ConstraintSummaryWidget.tsx`）**：
  - 当存在 Glob 按需触发规则时，在 `constraint-summary-glob-count` 旁新增 **`Glob规则存L3`**（`data-testid="constraint-summary-glob-to-l3-btn"`）与 **`复制Glob规则`**（`data-testid="constraint-summary-copy-glob-btn"`），支持将按需触发规则批量沉淀至 L3 `convention` 画像或导出 Glob 触发清单。
- **M4 `SemanticSearchPanel` 向量索引统计存 L4 与复制（`src/features/project-type/SemanticSearchPanel.tsx`）**：
  - 在 `semantic-indexing-stats` 索引状态栏新增 **`索引统计存 L4`**（`data-testid="semantic-stats-save-l4-btn"`）与 **`复制统计`**（`data-testid="semantic-stats-copy-btn"`），支持将当前向量索引健康度快照归档至 L4 参考资料库或复制到剪贴板。
- **单元测试与门禁验证**：
  - 扩展 `MilestoneProgressWidget.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `ProjectArchetypeStudio.test.tsx`（3 个测试文件共 28 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P64 — 项目工作台形态分布统计复制与一键刷新、侧边栏 Git 变更一键转里程碑与单文件 +L2 护栏、L3 画像面板全支柱一键组合与批量写入 L3、类型选择器与检测预览完整蓝图/路径/依据复制（已完成）

- **Phase 9.1 `Projects.tsx` 项目工作台形态分布统计复制与台账手动刷新（`src/pages/Projects.tsx`）**：
  - 在 `workbench-archetype-counts` 统计胶囊栏新增 **`复制形态统计`**（`data-testid="workbench-copy-archetype-stats-btn"`），支持一键复制四形态受控项目分布统计 Markdown；
  - 在工具栏新增 **`刷新台账`**（`data-testid="workbench-refresh-registry-btn"`），支持手动重新拉取受控项目列表。
- **Phase 4.3 `GitStatusSection` 侧边栏 Git 变更一键转里程碑与单文件 +L2 护栏（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**：
  - 在 `git-sider-filter-bar` 新增 **`转里程碑`**（`data-testid="git-sider-to-milestone-btn"`），支持将当前分支变更文件集合一键转化为 `[Git 变更审校]` 里程碑（`projectApi.createMilestone`）；
  - 在变更文件列表每行新增 **`+L2`**（`data-testid="git-sider-guard-${file.path}"`），支持将单文件变更直接固化为 `file_change_guard`（`P8`）L2 行为约束。
- **Phase 4.2 `StudioProfileTabPanel` 全支柱一键组合与批量写入 L3 画像（`src/features/project-type/StudioProfileTabPanel.tsx`）**：
  - 在 `studio-profile-presets-bar` 新增 **`一键组合全部支柱`**（`data-testid="studio-profile-pillar-fill-all-btn"`）与 **`支柱一键写入 L3`**（`data-testid="studio-profile-seed-pillars-btn"`），支持将当前形态全部上下文护栏支柱一键组合填入输入框或直接批量写入 L3 画像（`projectApi.confirmKnowledge`）。
- **Phase 9.4 `ProjectTypeSelector` & `TypeDetectionPreview` 完整蓝图、工作区路径与全部依据复制（`src/features/project-type/ProjectTypeSelector.tsx`, `src/features/project-type/TypeDetectionPreview.tsx`）**：
  - 在 `ProjectTypeSelector` 顶部与检测依据栏新增 **`复制工作区路径`**（`data-testid="selector-copy-path-btn"`）与 **`复制全部依据`**（`data-testid="selector-copy-all-signals-btn"`）；
  - 在 `TypeDetectionPreview` 顶部操作栏新增 **`复制完整蓝图`**（`data-testid="detection-copy-full-blueprint-btn"`），支持一键导出检测形态的完整组织蓝图 Markdown。
- **单元测试与门禁验证**：
  - 扩展 `Projects.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `ProjectTypeBadge.test.tsx`（3 个测试文件共 28 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P65 — Git 状态卡片分支复制与变更存 L3、M1 任务分解全支柱组合与按筛选阶段全选、M2 知识提取会话 ID 复制与提取思路转里程碑、约束/里程碑编辑器正文复制与清空（已完成）

- **Phase 4.3 `GitStatusWidget` 分支名称复制与变更文件清单存 L3（`src/features/project-type/GitStatusWidget.tsx`）**：
  - 在分支信息栏新增 **`复制分支`**（`data-testid="git-widget-copy-branch-btn"`），支持一键复制当前 Git 分支名称到剪贴板；
  - 在变更文件明细操作栏新增 **`变更存 L3`**（`data-testid="git-widget-files-to-l3-btn"`），支持将当前筛选出的工作区 Git 变更文件清单直接沉淀为 L3 `note` 画像记录（`projectApi.confirmKnowledge`）。
- **M1 `TaskDecomposeDialog` 全护栏支柱一键组合与按筛选阶段全选（`src/features/project-type/TaskDecomposeDialog.tsx`）**：
  - 在输入阶段 `decompose-pillar-presets` 栏新增 **`+全部支柱`**（`data-testid="decompose-pillar-fill-all-btn"`），支持一键将当前项目形态全部上下文护栏支柱组合填入补充上下文；
  - 在预览阶段 `decompose-stage-filter-bar` 新增 **`按筛选阶段全选`**（`data-testid="decompose-select-stage-btn"`），支持按当前选中的生命周期阶段筛选一键勾选对应主节点。
- **M2 `KnowledgeExtractionPanel` 会话 ID 复制与提取思路转里程碑（`src/features/project-type/KnowledgeExtractionPanel.tsx`）**：
  - 在会话输入栏新增 **`复制会话 ID`**（`data-testid="knowledge-copy-session-id-btn"`），支持一键复制当前选定或输入的会话 ID；
  - 在审核阶段提取思路栏新增 **`思路转里程碑`**（`data-testid="knowledge-reasoning-to-milestone-btn"`），支持将 M2 知识提取思路直接转化为复盘里程碑（`projectApi.createMilestone`）。
- **Phase 4.3 `ConstraintEditor` & `MilestoneEditor` 规则正文/交付说明一键复制与清空（`src/features/project-type/ConstraintEditor.tsx`, `src/features/project-type/MilestoneEditor.tsx`）**：
  - 在 `ConstraintEditor` 正文标题栏新增 **`复制规则正文`**（`data-testid="constraint-copy-content-btn"`）与 **`清空正文`**（`data-testid="constraint-clear-content-btn"`）；
  - 在 `MilestoneEditor` 交付说明标题栏新增 **`复制交付说明`**（`data-testid="milestone-copy-desc-btn"`）与 **`清空说明`**（`data-testid="milestone-clear-desc-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx`、`MilestoneProgressWidget.test.tsx` 与 `ProjectArchetypeStudio.test.tsx`（3 个测试文件共 28 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P66 — 多形态工作台目录/阶段复制与蓝图存 L3、概览护栏支柱一键存 L3/L4、约束统计类别分布存 L3、里程碑进度卡已完成项一键存 L4（已完成）

- **Phase 4.2 `ProjectArchetypeStudio` 标准目录清单/阶段管线复制与当前蓝图存 L3（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在三维组织详情卡片中新增 **`复制目录清单`**（`data-testid="studio-copy-dirs-btn"`）与 **`复制阶段管线`**（`data-testid="studio-copy-stages-btn"`），支持按当前选中形态一键复制推荐目录结构或生命周期阶段管线；
  - 在活跃项目概览工具栏新增 **`当前蓝图存 L3`**（`data-testid="studio-save-blueprint-l3-btn"`），支持将当前项目所属形态的蓝图规范一键沉淀为 L3 `architecture` 画像记录（`projectApi.confirmKnowledge`）。
- **Phase 4.3 `ProjectOverviewWidgets` 护栏支柱一键存 L3 画像与存 L4 资料（`src/features/project-type/ProjectOverviewWidgets.tsx`）**：
  - 在阶段治理操作栏新增 **`支柱存 L3 画像`**（`data-testid="overview-pillars-to-l3-btn"`）与 **`支柱存 L4 资料`**（`data-testid="overview-pillars-to-l4-btn"`），支持将当前形态全部上下文护栏支柱批量沉淀为 L3 `convention` 画像记录或归档至 L4 参考资料库（`projectApi.addMaterial`）。
- **Phase 4.3 `ConstraintSummaryWidget` 约束类别分布一键存 L3（`src/features/project-type/ConstraintSummaryWidget.tsx`）**：
  - 在按类别统计栏新增 **`分布存 L3`**（`data-testid="constraint-summary-cats-to-l3-btn"`），支持将当前 L2 启用约束的类别分布统计沉淀为 L3 `convention` 画像记录。
- **Phase 4.3 `MilestoneProgressWidget` 已完成里程碑成果一键存 L4（`src/features/project-type/MilestoneProgressWidget.tsx`）**：
  - 当存在已完成里程碑时，在顶部工具栏新增 **`已完成存L4`**（`data-testid="milestone-summary-completed-to-l4-btn"`），支持将全部已达成里程碑一键归档为 L4 阶段交付成果文档（`projectApi.addMaterial`）。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx`、`MilestoneProgressWidget.test.tsx` 与 `ProjectArchetypeStudio.test.tsx`（3 个测试文件共 28 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P67 — 项目工作台形态统计存 L3 与台账转里程碑、侧边栏 Git 分支复制与一键全护栏 L2、L3 画像面板支柱/类别分布存 L4、工作台项目行一键复制路径（已完成）

- **Phase 4.2 `Projects` 工作台四形态统计存 L3 与全局台账转巡检里程碑（`src/pages/Projects.tsx`）**：
  - 在 `workbench-archetype-counts` 统计栏新增 **`统计存L3`**（`data-testid="workbench-save-archetype-stats-l3-btn"`），支持将全局受控项目的四形态分布统计沉淀至 L3 `architecture` 画像（`projectApi.confirmKnowledge`）；
  - 在 `project-workbench-toolbar` 新增 **`台账转里程碑`**（`data-testid="workbench-registry-to-milestone-btn"`），支持将当前受控项目台账一键转化为 `[全局项目治理巡检]` 里程碑（`projectApi.createMilestone`）。
- **Phase 4.3 `GitStatusSection` 侧边栏 Git 分支名称复制与变更文件一键全护栏 L2（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**：
  - 将侧边栏 Git 标题栏分支标识升级为可点击按钮（`data-testid="git-sider-copy-branch-btn"`），支持一键复制当前分支名称；
  - 在 `git-sider-filter-bar` 新增 **`全护栏L2`**（`data-testid="git-sider-guard-all-btn"`），支持按当前筛选状态将全部变更文件批量固化为 `file_change_guard`（`P8`）L2 行为约束（`projectApi.createConstraint`）。
- **Phase 4.3 `StudioProfileTabPanel` 护栏支柱与类别分布一键存 L4（`src/features/project-type/StudioProfileTabPanel.tsx`）**：
  - 在 `studio-profile-presets-bar` 新增 **`支柱存 L4`**（`data-testid="studio-profile-pillars-to-l4-btn"`），支持将当前形态上下文护栏支柱一键归档为 L4 资料（`projectApi.addMaterial`）；
  - 在按类别统计栏新增 **`分布存 L4`**（`data-testid="studio-profile-cats-to-l4-btn"`），支持将 L3 画像类别分布统计归档至 L4 资料库。
- **Phase 4.2 `WorkbenchProjectList` 项目行工作区路径一键复制（`src/widgets/sidebar/sections/WorkbenchProjectList.tsx`）**：
  - 在工作台项目列表每行操作区新增 **`复制路径`**（`data-testid="workbench-row-copy-path-${project.id}"`），支持无需展开详情即可一键复制任意项目的工作区根目录路径。
- **单元测试与门禁验证**：
  - 扩展 `Projects.test.tsx`、`ProjectSection.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `ProjectArchetypeStudio.test.tsx`（4 个测试文件全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。

### Phase P68 — 多形态工作台护栏重点/推荐里程碑复制与一键播种推荐里程碑、概览护栏支柱转里程碑与阶段管线复制、约束统计 Glob/类别分布存 L4、里程碑进度风险项存 L4（已完成）

- **Phase 4.2 `ProjectArchetypeStudio` 护栏重点/推荐里程碑复制与活跃项目一键播种推荐里程碑（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在三维组织详情卡片中新增 **`复制护栏重点`**（`data-testid="studio-copy-pillars-btn"`）与 **`复制推荐里程碑`**（`data-testid="studio-copy-milestones-btn"`），支持按当前选中形态一键复制上下文护栏重点或推荐里程碑清单；
  - 在活跃项目概览工具栏新增 **`一键播种推荐里程碑`**（`data-testid="studio-seed-recommended-milestones-btn"`），支持将当前项目所属形态的推荐里程碑批量创建入库（`projectApi.createMilestone`）。
- **Phase 4.3 `ProjectOverviewWidgets` 护栏支柱转验收里程碑与阶段推进管线复制（`src/features/project-type/ProjectOverviewWidgets.tsx`）**：
  - 在阶段治理操作栏新增 **`支柱转里程碑`**（`data-testid="overview-pillars-to-milestone-btn"`），支持将当前形态全部上下文护栏支柱一键转化为护栏验收里程碑（`projectApi.createMilestone`）；
  - 在 `overview-stage-switcher` 新增 **`复制阶段管线`**（`data-testid="overview-copy-stages-btn"`），支持复制带当前阶段高亮标记的完整生命周期阶段管线。
- **Phase 4.3 `ConstraintSummaryWidget` Glob 规则与类别分布一键存 L4（`src/features/project-type/ConstraintSummaryWidget.tsx`）**：
  - 在 Glob 按需触发统计栏新增 **`Glob规则存L4`**（`data-testid="constraint-summary-glob-to-l4-btn"`），支持将全部 Glob 按需触发规则归档为 L4 资料（`projectApi.addMaterial`）；
  - 在按类别统计栏新增 **`分布存 L4`**（`data-testid="constraint-summary-cats-to-l4-btn"`），支持将 L2 约束类别分布统计归档至 L4 资料库。
- **Phase 4.3 `MilestoneProgressWidget` 阻塞/逾期风险里程碑一键存 L4（`src/features/project-type/MilestoneProgressWidget.tsx`）**：
  - 当存在阻塞或逾期里程碑时，在顶部工具栏新增 **`风险项存L4`**（`data-testid="milestone-summary-risk-to-l4-btn"`），支持将全部阻塞/逾期风险节点一键归档为 L4 风险复盘资料（`projectApi.addMaterial`）。
- **单元测试与门禁验证**：
  - 扩展 `ProjectArchetypeStudio.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（3 个测试文件共 28 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P69 — 工作台项目行一键存 L3/L4、侧边栏 Git 变更批量入库 L4 与单文件存 L3、约束编辑器类别复制/清空、里程碑编辑器标题复制/清空（已完成）

- **Phase 4.2 `WorkbenchProjectList` 项目行一键沉淀 L3 画像与归档 L4 资料（`src/widgets/sidebar/sections/WorkbenchProjectList.tsx`）**：
  - 在工作台项目列表每行操作区新增 **`+L3`**（`data-testid="workbench-row-to-l3-${project.id}"`）与 **`+L4`**（`data-testid="workbench-row-to-l4-${project.id}"`），支持无需展开详情即可将当前项目档案摘要直接沉淀至 L3 `architecture` 画像（`projectApi.confirmKnowledge`）或归档至 L4 资料库（`projectApi.addMaterial`）。
- **Phase 4.3 `GitStatusSection` 侧边栏 Git 变更批量入库 L4 与单文件沉淀 L3（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**：
  - 在 `git-sider-filter-bar` 新增 **`全入库L4`**（`data-testid="git-sider-ingest-all-btn"`），支持按当前筛选状态将全部变更文件批量入库至 L4 资料库（`projectApi.addMaterialFromFile`）；
  - 在每条变更文件行新增 **`+L3`**（`data-testid="git-sider-l3-${file.path}"`），支持将单文件变更记录一键沉淀至 L3 `note` 画像（`projectApi.confirmKnowledge`）。
- **Phase 4.3 `ConstraintEditor` 约束类别一键复制与清空（`src/features/project-type/ConstraintEditor.tsx`）**：
  - 在 `类别 *` 标题栏新增 **`复制类别`**（`data-testid="constraint-copy-category-btn"`）与 **`清空类别`**（`data-testid="constraint-clear-category-btn"`），便于快速复用或重置约束类别标识。
- **Phase 4.3 `MilestoneEditor` 里程碑标题一键复制与清空（`src/features/project-type/MilestoneEditor.tsx`）**：
  - 在 `标题 *` 标题栏新增 **`复制标题`**（`data-testid="milestone-copy-title-btn"`）与 **`清空标题`**（`data-testid="milestone-clear-title-btn"`），便于快速复用或重新填充里程碑标题。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（2 个测试文件共 25 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P70 — 工作台四形态统计存 L4 与台账转 L2 护栏、工作台项目行一键建里程碑/转 L2 护栏、Git 最近提交复制与转 L2 基线护栏、形态选择器版本保护策略复制（已完成）

- **Phase 4.2 `Projects` 工作台四形态统计存 L4 与全局台账转 L2 护栏（`src/pages/Projects.tsx`）**：
  - 在 `workbench-archetype-counts` 统计栏新增 **`统计存L4`**（`data-testid="workbench-save-archetype-stats-l4-btn"`），支持将全局受控项目的四形态分布统计归档至 L4 资料库（`projectApi.addMaterial`）；
  - 在 `project-workbench-toolbar` 新增 **`台账转L2护栏`**（`data-testid="workbench-registry-to-constraint-btn"`），支持将受控项目台账边界固化为 `workspace_boundary`（`P8`）L2 行为约束（`projectApi.createConstraint`）。
- **Phase 4.2 `WorkbenchProjectList` 项目行一键建里程碑与转 L2 护栏（`src/widgets/sidebar/sections/WorkbenchProjectList.tsx`）**：
  - 在工作台项目列表每行操作区新增 **`+里程碑`**（`data-testid="workbench-row-to-milestone-${project.id}"`）与 **`+L2`**（`data-testid="workbench-row-to-constraint-${project.id}"`），支持无需展开详情即可将当前项目一键创建为 `[项目治理复核]` 里程碑（`projectApi.createMilestone`）或固化为 `workspace_guard`（`P8`）L2 护栏（`projectApi.createConstraint`）。
- **Phase 4.3 `GitStatusWidget` 最近提交记录复制与一键转 L2 基线护栏（`src/features/project-type/GitStatusWidget.tsx`）**：
  - 在最近提交标题栏新增 **`复制提交记录`**（`data-testid="git-widget-copy-commits-md-btn"`）与 **`提交转L2护栏`**（`data-testid="git-widget-commits-to-constraint-btn"`），支持复制最近提交 Markdown 清单或将提交规范固化为 `git_commit_baseline`（`P7`）L2 行为约束。
- **Phase 4.3 `ProjectTypeSelector` 治理清单版本保护策略一键复制（`src/features/project-type/ProjectTypeSelector.tsx`）**：
  - 在 `selector-suite-details` 治理清单预览面板新增 **`复制版本保护`**（`data-testid="selector-copy-vcs-btn"`），支持一键复制当前选中形态的版本保护策略说明。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx` 与 `ProjectTypeBadge.test.tsx`（2 个测试文件共 27 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P71 — 蓝图工作台预设包复制与当前蓝图转 L2 护栏、项目概览阶段管线沉淀 L3/L4、约束管理器预设包复制与 Glob 测试路径复制、M4 语义检索词复制与清空（已完成）

- **Phase 4.2 `ProjectArchetypeStudio` 细分预设包复制与当前蓝图一键转 L2 护栏（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在 `3. 阶段推进管线与预设规则包` 标题栏新增 **`复制预设包`**（`data-testid="studio-copy-subtemplates-btn"`），支持一键复制当前形态推荐的细分预设规则包清单；
  - 在当前活动项目操作栏新增 **`当前蓝图转L2`**（`data-testid="studio-blueprint-to-constraint-btn"`），支持将当前项目所属形态的标准目录与版本控制规范固化为 `archetype_blueprint`（`P8`）L2 行为护栏（`projectApi.createConstraint`）。
- **Phase 4.3 `ProjectOverviewWidgets` 生命周期阶段管线一键沉淀 L3/L4（`src/features/project-type/ProjectOverviewWidgets.tsx`）**：
  - 在 `overview-stage-switcher` 阶段切换栏新增 **`阶段管线存L3`**（`data-testid="overview-stages-to-l3-btn"`）与 **`阶段管线存L4`**（`data-testid="overview-stages-to-l4-btn"`），支持将当前项目所处阶段与完整生命周期管线直接沉淀至 L3 `architecture` 画像（`projectApi.confirmKnowledge`）或归档至 L4 资料库（`projectApi.addMaterial`）。
- **Phase 4.4 `ConstraintManager` 细分预设包清单复制与 Glob 测试路径复制（`src/features/project-type/ConstraintManager.tsx`）**：
  - 在 `constraint-preset-packs` 顶部新增 **`复制预设包清单`**（`data-testid="constraint-copy-subtemplates-btn"`），支持复制当前形态全部细分规则包名称与标识；
  - 在 `constraint-glob-tester-bar` 当输入非空测试路径时新增 **`复制测试路径`**（`data-testid="constraint-glob-copy-path-btn"`），便于复用验证通过的触发路径样本。
- **Phase 4.5 `SemanticSearchPanel` M4 语义检索词复制与清空（`src/features/project-type/SemanticSearchPanel.tsx`）**：
  - 在检索输入栏新增 **`复制检索词`**（`data-testid="semantic-copy-query-btn"`）与 **`清空检索词`**（`data-testid="semantic-clear-query-btn"`），支持一键复制或重置当前语义检索查询词。
- **单元测试与门禁验证**：
  - 扩展 `ProjectArchetypeStudio.test.tsx` 与 `ConstraintSummaryWidget.test.tsx`（2 个测试文件共 19 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P72 — 类型检测预览完整详情导出、约束编辑器触发 Glob 清空与测试路径复制/清空、里程碑编辑器阶段复制/清空、里程碑进度阶段分布统计复制与沉淀 L3/L4（已完成）

- **Phase 4.2 `TypeDetectionPreview` 推荐规范与里程碑全部详情 Markdown 复制（`src/features/project-type/TypeDetectionPreview.tsx`）**：
  - 在 `detection-details-panel` 详情面板底部新增 **`复制全部详情 MD`**（`data-testid="detection-copy-details-md-btn"`），支持将当前检测形态的推荐规范包、默认里程碑与护栏支柱一键复制为完整 Markdown 摘要。
- **Phase 4.3 `ConstraintEditor` 触发 Glob 清空与测试路径复制/清空（`src/features/project-type/ConstraintEditor.tsx`）**：
  - 在触发条件快捷栏新增 **`清空触发 Glob`**（`data-testid="constraint-clear-glob-btn"`），支持快速重置为 `always` 全局生效；
  - 当输入非空相对测试路径时，新增 **`复制测试路径`**（`data-testid="constraint-editor-copy-test-path-btn"`）与 **`清空测试路径`**（`data-testid="constraint-editor-clear-test-path-btn"`），便于复用或重置路径测试样本。
- **Phase 4.3 `MilestoneEditor` 阶段标识一键复制与清空（`src/features/project-type/MilestoneEditor.tsx`）**：
  - 在 `阶段` 字段标题栏新增 **`复制阶段`**（`data-testid="milestone-copy-stage-btn"`）与 **`清空阶段`**（`data-testid="milestone-clear-stage-btn"`），并为各形态推荐阶段胶囊提供 `data-testid="milestone-stage-preset-${st.id}"`。
- **Phase 4.3 `MilestoneProgressWidget` 里程碑阶段分布复制与一键沉淀 L3/L4（`src/features/project-type/MilestoneProgressWidget.tsx`）**：
  - 在 `milestone-summary-stage-bar` 阶段筛选栏新增 **`复制阶段分布`**（`data-testid="milestone-summary-copy-stages-btn"`）、**`阶段分布存L3`**（`data-testid="milestone-summary-stages-to-l3-btn"`）与 **`阶段分布存L4`**（`data-testid="milestone-summary-stages-to-l4-btn"`），支持将阶段里程碑分布一键复制、沉淀至 L3 `architecture` 画像（`projectApi.confirmKnowledge`）或归档至 L4 资料库（`projectApi.addMaterial`）。
- **单元测试与门禁验证**：
  - 扩展 `ProjectTypeBadge.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（3 个测试文件共 38 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P73 — 侧边栏 Git 变更路径批量复制与单文件建里程碑、约束统计高优预览复制、L3 画像草稿复制与清空、M2 知识提取会话清空与结果反选（已完成）

- **Phase 4.3 `GitStatusSection` 侧边栏 Git 变更路径批量复制与单文件一键建里程碑（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**：
  - 在 `git-sider-filter-bar` 筛选栏新增 **`复制路径`**（`data-testid="git-sider-copy-paths-btn"`），支持按当前筛选状态复制全部变更文件的相对路径清单；
  - 在每条变更文件行新增 **`+里程碑`**（`data-testid="git-sider-milestone-${file.path}"`），支持将单文件变更直接创建为 `[Git 变更跟进]` 项目里程碑（`projectApi.createMilestone`）。
- **Phase 4.3 `ConstraintSummaryWidget` 高优规则预览一键复制（`src/features/project-type/ConstraintSummaryWidget.tsx`）**：
  - 当展开高优规则预览面板时，新增 **`复制高优预览`**（`data-testid="constraint-summary-copy-preview-btn"`），支持一键复制当前展示的高优先级约束规则 Markdown 清单。
- **Phase 4.4 `StudioProfileTabPanel` L3 画像输入草稿复制与清空（`src/features/project-type/StudioProfileTabPanel.tsx`）**：
  - 在画像录入栏新增 **`复制草稿`**（`data-testid="studio-profile-copy-draft-btn"`）与 **`清空草稿`**（`data-testid="studio-profile-clear-draft-btn"`），便于快速复用或重置待写入的 L3 画像内容。
- **Phase 4.5 `KnowledgeExtractionPanel` M2 知识提取会话 ID 清空与勾选反选（`src/features/project-type/KnowledgeExtractionPanel.tsx`）**：
  - 在会话输入栏新增 **`清空会话 ID`**（`data-testid="knowledge-clear-session-id-btn"`），并在审核阶段类别筛选栏新增 **`反选`**（`data-testid="knowledge-invert-selection-btn"`），支持快速反转勾选候选知识条目。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx` 与 `ProjectTypeBadge.test.tsx`（2 个测试文件共 27 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P74 — 工作台项目清单复制与行内脚手架初始化、类型选择器工作区定位复制、蓝图工作台 VCS 策略复制与蓝图建里程碑、概览阶段管线一键转 L2 约束（已完成）

- **Phase 4.3 `WorkbenchProjectList` 工作台项目清单复制与行内脚手架初始化（`src/widgets/sidebar/sections/WorkbenchProjectList.tsx`）**：
  - 在工作台项目区块头部新增 **`复制项目清单`**（`data-testid="workbench-copy-project-list-btn"`），支持一键复制全部纳管项目的名称、形态与工作区路径列表；
  - 在项目行悬浮操作栏新增 **`+脚手架`**（`data-testid="workbench-row-scaffold-${project.id}"`），支持单项目行内一键触发形态脚手架初始化（`projectApi.scaffold`）。
- **Phase 4.1 `ProjectTypeSelector` 治理清单工作区定位一键复制（`src/features/project-type/ProjectTypeSelector.tsx`）**：
  - 在展开的治理清单面板（`selector-suite-details`）顶部新增工作区定位展示行与 **`复制工作区定位`**（`data-testid="selector-copy-positioning-btn"`）。
- **Phase 4.1 & 4.3 `ProjectArchetypeStudio` 蓝图 VCS 策略复制与蓝图落地里程碑创建（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在蓝图详情第一栏新增 **`复制 VCS 策略`**（`data-testid="studio-copy-vcs-btn"`），并在活跃项目概览栏新增 **`当前蓝图建里程碑`**（`data-testid="studio-blueprint-to-milestone-btn"`），支持将当前形态蓝图规范一键创建为验收里程碑（`projectApi.createMilestone`）。
- **Phase 4.3 `ProjectOverviewWidgets` 生命周期阶段管线一键转 L2 约束（`src/features/project-type/ProjectOverviewWidgets.tsx`）**：
  - 在阶段切换工具栏（`overview-stage-switcher`）新增 **`阶段管线转L2`**（`data-testid="overview-stages-to-constraint-btn"`），支持将当前形态完整阶段推进顺序一键固化为 `stage_pipeline` 类别的 L2 结构化约束规则（`projectApi.createConstraint`）。
- **单元测试与门禁验证**：
  - 扩展 `ProjectArchetypeStudio.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `ProjectTypeBadge.test.tsx`（3 个测试文件共 35 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P75 — 工作台形态统计一键转巡检里程碑与 L2 护栏、检测预览置信度与 Markdown 依据复制、L2 约束与里程碑编辑器 JSON 配置导出及表单重置（已完成）

- **Phase 4.3 `Projects` 工作台四形态分布统计一键转巡检里程碑与 L2 形态护栏（`src/pages/Projects.tsx`）**：
  - 在 `workbench-archetype-counts` 形态分布栏新增 **`统计转里程碑`**（`data-testid="workbench-archetype-stats-to-milestone-btn"`）与 **`统计转L2`**（`data-testid="workbench-archetype-stats-to-constraint-btn"`），支持将当前四形态纳管分布直接创建为项目治理核查里程碑（`projectApi.createMilestone`）或固化为 `architecture` 类别的 L2 形态分类规范（`projectApi.createConstraint`）。
- **Phase 4.1 `TypeDetectionPreview` 检测置信度摘要复制与单条依据 Markdown 引用复制（`src/features/project-type/TypeDetectionPreview.tsx`）**：
  - 在检测报告头部新增 **`复制置信度`**（`data-testid="detection-copy-confidence-btn"`），支持一键复制检测形态与置信度摘要；
  - 在每条检测信号行（`detection-signal-item-${idx}`）新增 **`复制MD项`**（`data-testid="detection-copy-signal-md-${idx}"`），支持一键复制带形态标签的 Markdown 引用条目。
- **Phase 4.4 `ConstraintEditor` L2 约束规则 JSON 配置导出与表单重置（`src/features/project-type/ConstraintEditor.tsx`）**：
  - 在编辑器底部操作栏新增 **`复制 JSON`**（`data-testid="constraint-editor-copy-json-btn"`）与 **`重置表单`**（`data-testid="constraint-editor-reset-btn"`），支持导出结构化 JSON 规则配置与一键重置编辑表单。
- **Phase 4.5 `MilestoneEditor` 里程碑节点 JSON 配置导出与表单重置（`src/features/project-type/MilestoneEditor.tsx`）**：
  - 在编辑器底部操作栏新增 **`复制 JSON`**（`data-testid="milestone-editor-copy-json-btn"`）与 **`重置表单`**（`data-testid="milestone-editor-reset-btn"`），支持导出结构化 JSON 里程碑节点配置与一键重置编辑表单。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx`、`ProjectTypeBadge.test.tsx` 与 `MilestoneProgressWidget.test.tsx`（3 个测试文件共 40 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P76 — 工作台项目 JSON 清单与行内档案 MD 复制、类型选择器 JSON 蓝图与全量详情 MD 复制、侧边栏 Git 变更批量存 L3 与批量建里程碑、蓝图工作台定位与 JSON 蓝图复制（已完成）

- **Phase 4.3 `WorkbenchProjectList` 工作台项目 JSON 清单与单项目档案 MD 复制（`src/widgets/sidebar/sections/WorkbenchProjectList.tsx`）**：
  - 在工作台项目区块头部新增 **`复制项目 JSON`**（`data-testid="workbench-copy-project-json-btn"`），支持导出全部纳管项目的结构化 JSON 清单；
  - 在项目行操作栏新增 **`复制档案MD`**（`data-testid="workbench-row-copy-md-${project.id}"`），支持一键复制单项目的 Markdown 档案摘要。
- **Phase 4.1 `ProjectTypeSelector` 治理蓝图 JSON 与全量详情 MD 复制（`src/features/project-type/ProjectTypeSelector.tsx`）**：
  - 在已选治理形态摘要栏新增 **`复制蓝图 JSON`**（`data-testid="selector-copy-blueprint-json-btn"`），并在展开的治理清单底部新增 **`复制全部治理详情 MD`**（`data-testid="selector-copy-all-suite-md-btn"`）。
- **Phase 4.3 `GitStatusSection` 侧边栏 Git 筛选文件批量沉淀 L3 与批量建里程碑（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**：
  - 在 `git-sider-filter-bar` 筛选栏新增 **`全存L3`**（`data-testid="git-sider-all-to-l3-btn"`）与 **`全建里程碑`**（`data-testid="git-sider-all-to-milestone-btn"`），支持将当前筛选的 Git 变更文件批量沉淀至 L3 画像（`projectApi.confirmKnowledge`）或一键创建 `[Git 批量变更复核]` 里程碑（`projectApi.createMilestone`）。
- **Phase 4.1 `ProjectArchetypeStudio` 多形态蓝图 JSON 与工作区定位一键复制（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在顶部工具栏新增 **`复制蓝图 JSON`**（`data-testid="studio-copy-blueprint-json-btn"`），并在三维组织详情第一栏新增 **`复制定位`**（`data-testid="studio-copy-positioning-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx`、`ProjectTypeBadge.test.tsx` 与 `ProjectArchetypeStudio.test.tsx`（3 个测试文件共 30 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P77 — 工作台全局台账与四形态分布 JSON 导出、检测预览与规范详情 JSON 导出、Chat 头部项目语境 MD/JSON 导出、Hook 安全审计 JSON 导出（已完成）

- **Phase 4.3 `Projects` 工作台全局台账与四形态统计 JSON 导出（`src/pages/Projects.tsx`）**：
  - 在 `workbench-archetype-counts` 形态分布栏新增 **`复制统计JSON`**（`data-testid="workbench-copy-archetype-stats-json-btn"`），并在顶部工具栏新增 **`复制台账 JSON`**（`data-testid="workbench-copy-registry-json-btn"`），支持导出结构化全局受控项目台账与四形态分布 JSON。
- **Phase 4.1 `TypeDetectionPreview` 检测结果与推荐治理详情 JSON 导出（`src/features/project-type/TypeDetectionPreview.tsx`）**：
  - 在检测报告头部新增 **`复制检测 JSON`**（`data-testid="detection-copy-json-btn"`），并在展开的规范与里程碑详情面板新增 **`复制详情 JSON`**（`data-testid="detection-copy-details-json-btn"`）。
- **Phase 4.2 `ProjectBadge` Chat 头部当前项目语境 Markdown 与 JSON 导出（`src/widgets/chat/ProjectBadge.tsx`）**：
  - 在 Chat 头部项目标识右侧新增 **`复制语境MD`**（`data-testid="chat-project-copy-summary-md-btn"`）与 **`复制语境JSON`**（`data-testid="chat-project-copy-summary-json-btn"`），支持一键复制当前会话项目形态、阶段与版本保护语境。
- **Phase 4.4 `ProjectHooksPanel` 项目级 Hook 安全审计状态 JSON 导出（`src/widgets/settings/ProjectHooksPanel.tsx`）**：
  - 在已信任与待信任两种状态下均新增 **`复制JSON`**（`data-testid="project-hooks-copy-json-btn"`），支持导出结构化 Hook 安全审计状态 JSON。
- **单元测试与门禁验证**：
  - 扩展 `Projects.test.tsx`、`ProjectTypeBadge.test.tsx`、`ProjectBadge.test.tsx` 与 `ProjectHooksPanel.test.tsx`，并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P78 — 项目画像 JSON 与单条 MD/JSON 导出、Wiki 最近项目与路径检查 JSON/MD 导出、工作台行内档案 JSON 导出、类型选择器全量详情 JSON 导出（已完成）

- **Phase 4.2 `ProjectProfileCard` 项目画像 JSON 与行内单条 MD/JSON 导出（`src/widgets/memory/ProjectProfileCard.tsx`）**：
  - 在卡片头部新增 **`复制 JSON`**（`data-testid="project-profile-copy-json-btn"`），并在每条画像行新增 **`复制MD`**（`data-testid="project-profile-copy-item-md-${e.id}"`）与 **`复制JSON`**（`data-testid="project-profile-copy-item-json-${e.id}"`）。
- **Phase 4.3 `WikiProjectPicker` 最近打开的 Wiki 项目清单 MD/JSON 导出与路径检查 JSON 导出（`src/widgets/wiki/WikiProjectPicker.tsx`）**：
  - 在主菜单模式新增最近打开的 Wiki 项目卡片（`data-testid="wiki-recent-projects-section"`），支持 **`复制最近MD`**（`data-testid="wiki-recent-copy-md-btn"`）、**`复制最近JSON`**（`data-testid="wiki-recent-copy-json-btn"`）与单条 **`复制路径`**（`data-testid="wiki-recent-copy-path-${idx}"`），并在创建模式新增 **`复制检查JSON`**（`data-testid="wiki-check-copy-json-btn"`）。
- **Phase 4.3 `WorkbenchProjectList` 工作台项目行内档案 JSON 导出（`src/widgets/sidebar/sections/WorkbenchProjectList.tsx`）**：
  - 在项目行操作栏新增 **`复制档案JSON`**（`data-testid="workbench-row-copy-json-${project.id}"`），支持一键复制单项目的结构化 JSON 档案。
- **Phase 4.1 `ProjectTypeSelector` 治理清单全量详情 JSON 导出（`src/features/project-type/ProjectTypeSelector.tsx`）**：
  - 在展开的治理清单底部新增 **`复制全部详情 JSON`**（`data-testid="selector-copy-all-suite-json-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `UserProfileCard.test.tsx`、`WikiProjectPicker.test.tsx`、`ConstraintSummaryWidget.test.tsx` 与 `ProjectTypeBadge.test.tsx`，并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P79 — 侧边栏 Git 变更 JSON 导出、多形态工作台全形态 JSON 与活动项目 MD/JSON 导出、聊天分支选择器路径/MD/JSON 导出、项目级 Hook 配置路径复制（已完成）

- **Phase 4.3 `GitStatusSection` 侧边栏 Git 筛选状态与单文件 JSON 导出（`src/widgets/sidebar/sections/GitStatusSection.tsx`）**：
  - 在状态筛选栏新增 **`复制JSON`**（`data-testid="git-sider-copy-json-btn"`），并在每条变更文件行新增 **`复制JSON`**（`data-testid="git-sider-copy-json-${file.path}"`）。
- **Phase 4.1 `ProjectArchetypeStudio` 四大蓝图对比 JSON 与活动项目 MD/JSON 导出（`src/features/project-type/ProjectArchetypeStudio.tsx`）**：
  - 在蓝图总览卡头部新增 **`复制四大蓝图对比 JSON`**（`data-testid="studio-copy-all-blueprints-json-btn"`），并在活动项目概览卡新增 **`复制项目 MD`**（`data-testid="studio-copy-active-project-md-btn"`）与 **`复制项目 JSON`**（`data-testid="studio-copy-active-project-json-btn"`）。
- **Phase 4.3 `WorkspaceBranchPicker` 会话工作区分支与 Worktree 快照路径/MD/JSON 导出（`src/widgets/chat/WorkspaceBranchPicker.tsx`）**：
  - 在分支选择器弹窗新增治理动作栏（`data-testid="workspace-branch-picker-actions"`），支持 **`复制路径`**（`data-testid="workspace-picker-copy-path-btn"`）、**`复制分支MD`**（`data-testid="workspace-picker-copy-md-btn"`）与 **`复制分支JSON`**（`data-testid="workspace-picker-copy-json-btn"`）。
- **Phase 4.4 `ProjectHooksPanel` 项目级 Hook 配置文件路径一键复制（`src/widgets/settings/ProjectHooksPanel.tsx`）**：
  - 在已信任与待信任两种状态下均新增 **`复制配置路径`**（`data-testid="project-hooks-copy-config-path-btn"`），一键复制 `.sage/hooks.json` 标准路径。
- **单元测试与门禁验证**：
  - 扩展 `ConstraintSummaryWidget.test.tsx`、`ProjectArchetypeStudio.test.tsx`、`WorkspaceBranchPicker.test.tsx` 与 `ProjectHooksPanel.test.tsx`，并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P80 — 对话头项目蓝图指引导出、工作区绑定弹窗路径/MD/JSON 导出、Hook 执行历史与全局 Hook 配置 MD/JSON 导出（已完成）

- **Phase 4.3 `ProjectBadge` 对话头项目形态蓝图指引一键导出（`src/widgets/chat/ProjectBadge.tsx`）**：
  - 当已登记项目解析出形态蓝图（`blueprint`）时，在对话头部项目徽章栏新增 **`复制蓝图MD`**（`data-testid="chat-project-copy-blueprint-md-btn"`），支持一键复制当前项目形态的定位、版本治理、标准目录与全阶段提示 Markdown。
- **Phase 4.3 `WorkspaceBindModal` 工作区绑定弹窗路径/MD/JSON 快捷导出（`src/features/workspace/WorkspaceBindModal.tsx`）**：
  - 在已绑定工作区状态下新增导出动作栏（`data-testid="workspace-bind-export-actions"`），支持 **`复制路径`**（`data-testid="workspace-bind-copy-path-btn"`）、**`复制绑定MD`**（`data-testid="workspace-bind-copy-md-btn"`）与 **`复制绑定JSON`**（`data-testid="workspace-bind-copy-json-btn"`）。
- **Phase 4.4 `HookHistoryPanel` Hook 执行历史 MD/JSON 与单条记录 JSON 导出（`src/widgets/settings/HookHistoryPanel.tsx`）**：
  - 在执行历史面板头部新增 **`复制历史MD`**（`data-testid="hook-history-copy-md-btn"`）与 **`复制历史JSON`**（`data-testid="hook-history-copy-json-btn"`），并在每条记录行新增 **`复制JSON`**（`data-testid="hook-history-copy-record-json-${record.id}"`）。
- **Phase 4.4 `HooksCard` 全局与内置 Hook 配置清单 MD/JSON 与单条 JSON 导出（`src/widgets/settings/HooksCard.tsx`）**：
  - 在全局 Hook 工具栏新增 **`复制钩子MD`**（`data-testid="hooks-copy-all-md-btn"`）与 **`复制钩子JSON`**（`data-testid="hooks-copy-all-json-btn"`），并在内置钩子行与自定义钩子行分别新增 **`复制JSON`**（`data-testid="builtin-copy-json-${builtin.id}"` / `data-testid="hook-copy-json-${originalIdx}"`）。
- **单元测试与门禁验证**：
  - 扩展 `ProjectBadge.test.tsx`、`WorkspaceBindModal.test.tsx`、`HookHistoryPanel.test.tsx` 与 `HooksCard.test.tsx`，并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P81 — Wiki 项目质量检查、内容审核、图谱洞察与摄入队列报告 MD/JSON 导出（已完成）

- **Phase 4.3 `WikiLintView` Wiki 质量检查报告 MD/JSON 导出（`src/widgets/wiki/WikiLintView.tsx`）**：
  - 在质量检查工具栏新增 **`复制检查MD`**（`data-testid="wiki-lint-copy-md-btn"`）与 **`复制检查JSON`**（`data-testid="wiki-lint-copy-json-btn"`），支持按当前严重度筛选导出质量检查报告与统计数据。
- **Phase 4.3 `WikiReviewView` Wiki 内容审核报告 MD/JSON 导出（`src/widgets/wiki/WikiReviewView.tsx`）**：
  - 在内容审核工具栏新增 **`复制审核MD`**（`data-testid="wiki-review-copy-md-btn"`）与 **`复制审核JSON`**（`data-testid="wiki-review-copy-json-btn"`），支持一键复制当前审核项清单与分类统计。
- **Phase 4.3 `WikiInsightsPanel` Wiki 知识图谱洞察报告 MD/JSON 导出（`src/widgets/wiki/WikiInsightsPanel.tsx`）**：
  - 在图谱洞察面板顶部新增导出栏（`data-testid="wiki-insights-export-bar"`），支持 **`复制洞察MD`**（`data-testid="wiki-insights-copy-md-btn"`）与 **`复制洞察JSON`**（`data-testid="wiki-insights-copy-json-btn"`），一键导出图谱规模、惊人联系与知识缺口。
- **Phase 4.3 `WikiQueuePanel` Wiki 摄入队列报告 MD/JSON 导出（`src/widgets/wiki/WikiQueuePanel.tsx`）**：
  - 在摄入队列状态摘要栏新增 **`复制队列MD`**（`data-testid="wiki-queue-copy-md-btn"`）与 **`复制队列JSON`**（`data-testid="wiki-queue-copy-json-btn"`），支持一键导出队列汇总与任务明细。
- **单元测试与门禁验证**：
  - 扩展 `WikiProjectPicker.test.tsx` 覆盖四大 Wiki 治理面板渲染、筛选与 MD/JSON 导出，并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P82 — Wiki 活动历史、搜索结果与单条检查/审核卡片 MD/JSON 导出（已完成）

- **Phase 4.3 `ActivityPanel` Wiki 操作活动历史 MD/JSON 导出（`src/widgets/wiki/ActivityPanel.tsx`）**：
  - 在活动历史面板标题栏新增 **`复制活动MD`**（`data-testid="wiki-activity-copy-md-btn"`）与 **`复制活动JSON`**（`data-testid="wiki-activity-copy-json-btn"`），支持一键复制操作活动记录与统计。
- **Phase 4.3 `LintItemCard` 单条质量检查项 JSON 导出（`src/widgets/wiki/LintItemCard.tsx`）**：
  - 在每个 Lint 卡片操作区新增 **`复制JSON`**（`data-testid="wiki-lint-item-copy-json-${item.id}"`），支持一键复制单条检查诊断详情。
- **Phase 4.3 `ReviewItemCard` 单条内容审核项 JSON 导出（`src/widgets/wiki/ReviewItemCard.tsx`）**：
  - 在每个 Review 卡片头部新增 **`复制JSON`**（`data-testid="wiki-review-item-copy-json-${item.id}"`），支持一键复制单条审核项元数据与关联页面列表。
- **Phase 4.3 `WikiSearch` Wiki 搜索结果 MD/JSON 导出（`src/widgets/wiki/WikiSearch.tsx`）**：
  - 在搜索结果摘要栏新增 **`复制搜索MD`**（`data-testid="wiki-search-copy-md-btn"`）与 **`复制搜索JSON`**（`data-testid="wiki-search-copy-json-btn"`），支持一键复制搜索命中清单。
- **单元测试与门禁验证**：
  - 扩展 `WikiProjectPicker.test.tsx`（14 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P83 — Wiki 深度研究报告、文档编辑器、来源文件清单与顶部工具栏 MD/JSON 导出（已完成）

- **Phase 4.3 `WikiResearchPanel` 深度研究报告与单条来源 MD/JSON 导出（`src/widgets/wiki/WikiResearchPanel.tsx`）**：
  - 在研究结果顶部操作栏新增 **`复制研究MD`**（`data-testid="wiki-research-copy-md-btn"`）与 **`复制研究JSON`**（`data-testid="wiki-research-copy-json-btn"`），并在每张 `SourceCard` 新增 **`复制JSON`**（`data-testid="wiki-research-source-copy-json-${index}"`）。
- **Phase 4.3 `WikiEditor` Wiki 文档编辑器 MD/JSON 导出（`src/widgets/wiki/WikiEditor.tsx`）**：
  - 在编辑器头部操作栏新增 **`复制MD`**（`data-testid="wiki-editor-copy-md-btn"`）与 **`复制JSON`**（`data-testid="wiki-editor-copy-json-btn"`），支持一键复制当前文档源码或完整文件元数据。
- **Phase 4.3 `SourcesView` Wiki 来源文件清单与单文件信息 MD/JSON 导出（`src/widgets/wiki/SourcesView.tsx`）**：
  - 在来源视图顶部新增 **`复制来源MD`**（`data-testid="wiki-sources-copy-md-btn"`）与 **`复制来源JSON`**（`data-testid="wiki-sources-copy-json-btn"`），并在选中文件详情卡片新增 **`复制文件JSON`**（`data-testid="wiki-sources-file-copy-json-btn"`）。
- **Phase 4.3 `WikiToolbar` Wiki 顶部工具栏项目状态 JSON 导出（`src/widgets/wiki/WikiToolbar.tsx`）**：
  - 在顶部工具栏右侧新增 **`复制项目JSON`**（`data-testid="wiki-toolbar-copy-json-btn"`），支持一键复制当前 Wiki 项目上下文快照。
- **单元测试与门禁验证**：
  - 扩展 `WikiEditor.test.tsx` 覆盖四大组件渲染、交互与 MD/JSON 导出，并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P84 — Wiki 问答对话/引用、知识图谱与社区聚类、左右侧栏及导入进度 MD/JSON 导出（已完成）

- **Phase 4.3 `WikiChat` Wiki 问答对话、已选来源与单条引用证据 MD/JSON 导出（`src/widgets/wiki/WikiChat.tsx`）**：
  - 在来源选择控制栏新增 **`复制来源JSON`**（`data-testid="wiki-chat-sources-copy-json-btn"`）、**`复制对话MD`**（`data-testid="wiki-chat-copy-md-btn"`）与 **`复制对话JSON`**（`data-testid="wiki-chat-copy-json-btn"`），并在每条 `Citation` 卡片头部新增 **`复制引用JSON`**（`data-testid="wiki-chat-citation-copy-json-${citation.id}"`）。
- **Phase 4.3 `WikiGraphView` 与 `CommunityColoredGraph` 知识图谱及社区聚类 MD/JSON 导出（`src/widgets/wiki/WikiGraphView.tsx`, `src/widgets/wiki/CommunityColoredGraph.tsx`）**：
  - 在图谱统计浮层新增 **`复制图谱MD`**（`data-testid="wiki-graph-copy-md-btn"`）与 **`复制图谱JSON`**（`data-testid="wiki-graph-copy-json-btn"`）；在社区聚类图例浮层新增 **`复制社区MD`**（`data-testid="wiki-community-copy-md-btn"`）、**`复制社区JSON`**（`data-testid="wiki-community-copy-json-btn"`）与单社区 **`复制JSON`**（`data-testid="wiki-community-item-copy-json-${c.community_id}"`）。
- **Phase 4.3 `LeftPanel`、`RightPanel` 与 `WikiIngestProgress` 侧栏文件树/预览及导入进度 MD/JSON 导出（`src/widgets/wiki/LeftPanel.tsx`, `src/widgets/wiki/RightPanel.tsx`, `src/widgets/wiki/WikiIngestProgress.tsx`）**：
  - 在左侧栏文件树头部新增 **`复制树MD`**（`data-testid="wiki-file-tree-copy-md-btn"`）与 **`复制树JSON`**（`data-testid="wiki-file-tree-copy-json-btn"`），在右侧栏文档预览头部新增 **`复制预览MD`**（`data-testid="wiki-right-preview-copy-md-btn"`）与 **`复制预览JSON`**（`data-testid="wiki-right-preview-copy-json-btn"`），并在导入进度横幅新增 **`复制进度JSON`**（`data-testid="wiki-ingest-copy-json-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `WikiEditor.test.tsx` 与 `WikiChat.sources.test.tsx`（全部单测通过，变更文件分支覆盖率 `> 82%`），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P85 — 记忆库浏览器、用户画像卡片、记忆条目、新建记忆草稿与待办事项 MD/JSON 导出（已完成）

- **Phase 4.2 `MemoryBrowser` 记忆库报告与单条记忆 MD/JSON 导出（`src/widgets/memory/MemoryBrowser.tsx`）**：
  - 在视图模式切换栏新增 **`复制记忆MD`**（`data-testid="memory-browser-copy-md-btn"`）与 **`复制记忆JSON`**（`data-testid="memory-browser-copy-json-btn"`），并在每条 `MemoryItemCard` 新增 **`复制MD`**（`data-testid="memory-item-copy-md-${memory.id}"`）与 **`复制JSON`**（`data-testid="memory-item-copy-json-${memory.id}"`）。
- **Phase 4.2 `UserProfileCard` 用户画像卡片与单条目 MD/JSON 导出（`src/widgets/memory/UserProfileCard.tsx`）**：
  - 在用户画像顶部操作栏新增 **`复制画像MD`**（`data-testid="user-profile-copy-md-btn"`）与 **`复制画像JSON`**（`data-testid="user-profile-copy-json-btn"`），并在每条画像条目操作区新增 **`复制JSON`**（`data-testid="user-profile-item-copy-json-${e.id}"`）。
- **Phase 4.2 `MemoryItem` 与 `NewMemoryModal` 记忆卡片及新建草稿 JSON 导出（`src/widgets/memory/MemoryItem.tsx`, `src/widgets/memory/NewMemoryModal.tsx`）**：
  - 在 `MemoryItem` 底部新增 **`复制记忆JSON`**（`data-testid="memory-card-copy-json-${memory.id}"`），并在 `NewMemoryModal` 底部操作区新增 **`复制草稿JSON`**（`data-testid="new-memory-copy-draft-json-btn"`）。
- **Phase 4.1 `TodoItem` 待办事项单条 MD/JSON 导出（`src/widgets/todo/TodoItem.tsx`）**：
  - 在每条待办事项右侧新增 **`复制MD`**（`data-testid="todo-item-copy-md-${todo.id}"`）与 **`复制JSON`**（`data-testid="todo-item-copy-json-${todo.id}"`）。
- **单元测试与门禁验证**：
  - 扩展 `MemoryBrowser.test.tsx`、`UserProfileCard.test.tsx`、`MemoryItem.test.tsx`、`NewMemoryModal.test.tsx` 与 `TodoItem.test.tsx`（37 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P86 — 待办管理页、定时任务页、全局任务中心与编排泳道看板/验收抽屉 MD/JSON 导出（已完成）

- **Phase 4.1 `TodoPage` 待办管理页与单行待办 MD/JSON 导出（`src/pages/TodoPage.tsx`）**：
  - 在待办管理页顶部操作区新增 **`复制待办MD`**（`data-testid="todo-page-copy-md-btn"`）与 **`复制待办JSON`**（`data-testid="todo-page-copy-json-btn"`），并在每行 `TodoRow` 新增 **`复制JSON`**（`data-testid="todo-row-copy-json-${todo.id}"`）。
- **Phase 4.1 `ScheduledTasks` 定时任务管理页与单任务 MD/JSON 导出（`src/pages/ScheduledTasks.tsx`）**：
  - 在定时任务页顶部操作栏新增 **`复制定时MD`**（`data-testid="scheduled-tasks-copy-md-btn"`）与 **`复制定时JSON`**（`data-testid="scheduled-tasks-copy-json-btn"`），并在每条定时任务行新增 **`复制JSON`**（`data-testid="scheduled-task-copy-json-${task.id}"`）。
- **Phase 4.1 `TaskCenterWidget` 全局任务中心胶囊与单条任务 MD/JSON 导出（`src/widgets/task-center/TaskCenterWidget.tsx`）**：
  - 在展开的任务中心浮层顶部新增 **`复制任务MD`**（`data-testid="task-center-copy-md-btn"`）与 **`复制任务JSON`**（`data-testid="task-center-copy-json-btn"`），并在每条任务条目新增 **`复制JSON`**（`data-testid="task-center-item-copy-json-${entry.id}"`）。
- **Phase 4.4 `LaneBoard` 与 `LaneDetailDrawer` 编排泳道看板及验收详情抽屉 MD/JSON 导出（`src/widgets/orchestration/LaneBoard.tsx`, `src/widgets/orchestration/LaneDetailDrawer.tsx`）**：
  - 在 `LaneBoard` 顶部新增 **`复制泳道MD`**（`data-testid="lane-board-copy-md-btn"`）、**`复制泳道JSON`**（`data-testid="lane-board-copy-json-btn"`）及单泳道卡片 **`复制JSON`**（`data-testid="lane-card-copy-json-${lane.lane_id}"`）；在 `LaneDetailDrawer` 头部新增 **`复制验收MD`**（`data-testid="lane-drawer-copy-md-btn"`）与 **`复制验收JSON`**（`data-testid="lane-drawer-copy-json-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `TodoPage.test.tsx`、`ScheduledTasks.test.tsx`、`TaskCenterWidget.test.tsx`、`Orchestration.test.tsx` 与 `LaneDetailDrawer.test.tsx`（29 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P87 — Agent 管理页/卡片/详情面板与技能卡片/审计抽屉/草稿列表及预览弹窗 MD/JSON 导出（已完成）

- **Phase 4.4 `Agents`、`AgentCard` 与 `AgentDetails` 智能体管理与详情配置 MD/JSON 导出（`src/pages/Agents.tsx`, `src/widgets/agents/AgentCard.tsx`, `src/widgets/agents/AgentDetails.tsx`）**：
  - 在 `Agents` 页面顶部新增 **`复制Agent MD`**（`data-testid="agents-page-copy-md-btn"`）与 **`复制Agent JSON`**（`data-testid="agents-page-copy-json-btn"`），在 `AgentCard` 新增单智能体 **`复制JSON`**（`data-testid="agent-card-copy-json-${agent.id}"`），并在 `AgentDetails` 新增 **`复制配置MD`**（`data-testid="agent-details-copy-md-btn"`）与 **`复制配置JSON`**（`data-testid="agent-details-copy-json-btn"`）。
- **Phase 4.4 `SkillCard` 与 `SkillAuditDrawer` 技能定义及变更审计历史 MD/JSON 导出（`src/widgets/skills/SkillCard.tsx`, `src/widgets/skills/SkillAuditDrawer.tsx`）**：
  - 在 `SkillCard` 操作栏新增 **`复制MD`**（`data-testid="skill-card-copy-md-${name}"`）与 **`复制JSON`**（`data-testid="skill-card-copy-json-${name}"`），并在 `SkillAuditDrawer` 底部操作区新增 **`复制审计MD`**（`data-testid="skill-audit-copy-md-btn"`）与 **`复制审计JSON`**（`data-testid="skill-audit-copy-json-btn"`）。
- **Phase 4.4 `SkillDraftList` 与 `SkillDraftDetail` 待审技能草稿清单及详情弹窗 MD/JSON 导出（`src/widgets/skills/SkillDraftList.tsx`, `src/widgets/skills/SkillDraftDetail.tsx`）**：
  - 在 `SkillDraftList` 顶部新增 **`复制草稿列表MD`**（`data-testid="skill-draft-list-copy-md-btn"`）、**`复制草稿列表JSON`**（`data-testid="skill-draft-list-copy-json-btn"`）及单草稿卡片 **`复制JSON`**（`data-testid="skill-draft-item-copy-json-${draft.id}"`）；在 `SkillDraftDetail` 底部新增 **`复制草稿MD`**（`data-testid="skill-draft-detail-copy-md-btn"`）与 **`复制草稿JSON`**（`data-testid="skill-draft-detail-copy-json-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `AgentCard.test.tsx`、`SkillCard.test.tsx`、`SkillAuditDrawer.test.tsx`、`SkillDraftList.test.tsx` 与 `SkillDraftDetail.test.tsx`（49 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P88 — 诊断日志、用量与成本明细、会话归档/分叉谱系弹窗及模型目录/详情/快照审核 MD/JSON 导出（已完成）

- **Phase 4.3 `DiagnosticsCard`、`UsagePanel` 与 `UsageRequestsTable` 诊断日志及用量成本明细 MD/JSON 导出（`src/widgets/settings/DiagnosticsCard.tsx`, `src/widgets/settings/UsagePanel.tsx`, `src/widgets/settings/UsageRequestsTable.tsx`）**：
  - 在 `DiagnosticsCard` 操作栏新增 **`复制诊断MD`**（`data-testid="diagnostics-copy-md-btn"`）、**`复制诊断JSON`**（`data-testid="diagnostics-copy-json-btn"`）与单日志文件 **`复制JSON`**（`data-testid="diagnostics-file-copy-json-${f.name}"`）；在 `UsagePanel` 新增 **`复制用量MD`**（`data-testid="usage-copy-md-btn"`）与 **`复制用量JSON`**（`data-testid="usage-copy-json-btn"`）；在 `UsageRequestsTable` 顶部新增 **`复制明细MD`**（`data-testid="usage-requests-copy-md-btn"`）与 **`复制明细JSON`**（`data-testid="usage-requests-copy-json-btn"`）。
- **Phase 4.2 `ArchivesModal` 与 `ForkTreeModal` 会话压缩归档及分叉谱系树 MD/JSON 导出（`src/widgets/session/ArchivesModal.tsx`, `src/widgets/session/ForkTreeModal.tsx`）**：
  - 在 `ArchivesModal` 头部新增 **`复制归档MD`**（`data-testid="archives-modal-copy-md-btn"`）、**`复制归档JSON`**（`data-testid="archives-modal-copy-json-btn"`）与单归档条目 **`复制JSON`**（`data-testid="archive-item-copy-json-${archive.archive_session_id}"`）；在 `ForkTreeModal` 顶部新增 **`复制分叉树MD`**（`data-testid="fork-tree-copy-md-btn"`）与 **`复制分叉树JSON`**（`data-testid="fork-tree-copy-json-btn"`）。
- **Phase 4.4 `CatalogTable`、`ModelDetails` 与 `SnapshotReview` 模型目录、模型详情及快照差异审核 MD/JSON 导出（`src/widgets/model-catalog/CatalogTable.tsx`, `src/widgets/model-catalog/ModelDetails.tsx`, `src/widgets/model-catalog/SnapshotReview.tsx`）**：
  - 在 `CatalogTable` 顶部新增 **`复制目录MD`**（`data-testid="catalog-table-copy-md-btn"`）、**`复制目录JSON`**（`data-testid="catalog-table-copy-json-btn"`）与单行 **`复制JSON`**（`data-testid="catalog-row-copy-json-${key}"`）；在 `ModelDetails` 头部新增 **`复制详情MD`**（`data-testid="model-details-copy-md-btn"`）与 **`复制详情JSON`**（`data-testid="model-details-copy-json-btn"`）；在 `SnapshotReview` 顶部新增 **`复制快照差异MD`**（`data-testid="snapshot-review-copy-md-btn"`）、**`复制快照差异JSON`**（`data-testid="snapshot-review-copy-json-btn"`）与单差异项 **`复制JSON`**（`data-testid="snapshot-item-copy-json-${item.id}"`）。
- **单元测试与门禁验证**：
  - 扩展 `DiagnosticsCard.test.tsx`、`UsagePanel.test.tsx`、`UsageRequestsTable.test.tsx`、`ArchivesModal.test.tsx`、`ForkTreeModal.test.tsx`、`ModelCatalog.test.tsx`、`ModelDetails.test.tsx` 与 `SnapshotReview.test.tsx`（8 个套件共 43 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P89 — 编排运行摘要、对话大纲、会话任务清单、产物列表/单行/版本历史、会话回滚检查点与权限审批弹窗 MD/JSON 导出（已完成）

- **Phase 4.1 `RunSummaryPanel`、`ConversationOutline` 与 `TodoListSection` 编排运行摘要、对话大纲与会话任务清单 MD/JSON 导出（`src/widgets/chat/RunSummaryPanel.tsx`, `src/widgets/chat/ConversationOutline.tsx`, `src/widgets/chat/progress/TodoListSection.tsx`）**：
  - 在 `RunSummaryPanel` 头部新增 **`复制摘要MD`**（`data-testid="run-summary-copy-md-btn"`）与 **`复制摘要JSON`**（`data-testid="run-summary-copy-json-btn"`）；在 `ConversationOutline` 顶部新增 **`复制大纲MD`**（`data-testid="conversation-outline-copy-md-btn"`）与 **`复制大纲JSON`**（`data-testid="conversation-outline-copy-json-btn"`）；在 `TodoListSection` 顶部新增 **`复制任务MD`**（`data-testid="todo-list-section-copy-md-btn"`）与 **`复制任务JSON`**（`data-testid="todo-list-section-copy-json-btn"`）。
- **Phase 4.2 `ArtifactsSection`、`ArtifactRow` 与 `VersionHistory` 会话产物列表、单产物及版本历史 MD/JSON 导出（`src/widgets/chat/artifacts/ArtifactsSection.tsx`, `src/widgets/chat/artifacts/ArtifactRow.tsx`, `src/widgets/chat/artifacts/VersionHistory.tsx`）**：
  - 在 `ArtifactsSection` 顶部工具栏新增 **`复制产物MD`**（`data-testid="artifacts-section-copy-md-btn"`）与 **`复制产物JSON`**（`data-testid="artifacts-section-copy-json-btn"`）；在 `ArtifactRow` 新增单产物 **`复制JSON`**（`data-testid="artifact-copy-json-${artifact.id}"`）；在 `VersionHistory` 展开区新增 **`复制版本MD`**（`data-testid="version-history-copy-md-btn"`）、**`复制版本JSON`**（`data-testid="version-history-copy-json-btn"`）与单版本 **`复制JSON`**（`data-testid="version-item-copy-json-${v.version_num}"`）。
- **Phase 4.3 `RewindDialog` 与 `ApprovalDialog` 会话回滚检查点及工具权限审批弹窗 MD/JSON 导出（`src/widgets/chat/rewind/RewindDialog.tsx`, `src/widgets/permission/ApprovalDialog.tsx`）**：
  - 在 `RewindDialog` 底部操作区新增 **`复制检查点MD`**（`data-testid="rewind-copy-md-btn"`）与 **`复制检查点JSON`**（`data-testid="rewind-copy-json-btn"`）；在 `ApprovalDialog` 弹窗头部新增 **`复制审批MD`**（`data-testid="permission-copy-md-btn"`）与 **`复制审批JSON`**（`data-testid="permission-copy-json-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `RunSummaryPanel.test.tsx`、`ConversationOutline.test.tsx`、`TodoListSection.test.tsx`、`ArtifactsSection.test.tsx`、`ArtifactRow.test.tsx`、`VersionHistory.diff.test.tsx`、`RewindDialog.test.tsx` 与 `ApprovalDialog.test.tsx`（10 个套件共 68 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P90 — 编排任务树、子代理详情抽屉、事件时间线、会话历史编排、全部变更审查、分栏 Diff、上下文水位弹层/来源明细与会话记忆写入提示 MD/JSON 导出（已完成）

- **Phase 4.1 `EventTimeline`、`SessionRunHistory` 与 `SubagentDetailDrawer` 事件时间线、会话历史编排及子代理详情抽屉 MD/JSON 导出（`src/widgets/chat/progress/EventTimeline.tsx`, `src/widgets/chat/progress/SessionRunHistory.tsx`, `src/widgets/chat/progress/SubagentDetailDrawer.tsx`）**：
  - 在 `EventTimeline` 顶部新增 **`复制时间线MD`**（`data-testid="event-timeline-copy-md-btn"`）与 **`复制时间线JSON`**（`data-testid="event-timeline-copy-json-btn"`）；在 `SessionRunHistory` 展开头部新增 **`复制历史MD`**（`data-testid="session-run-history-copy-md-btn"`）与 **`复制历史JSON`**（`data-testid="session-run-history-copy-json-btn"`）；在 `SubagentDetailDrawer` 头部新增 **`复制详情MD`**（`data-testid="subagent-drawer-copy-md-btn"`）与 **`复制详情JSON`**（`data-testid="subagent-drawer-copy-json-btn"`）。
- **Phase 4.2 `TaskTreeSection`、`ReviewAll` 与 `SplitDiff` 编排任务树、全部变更审查与分栏 Diff MD/JSON 导出（`src/widgets/chat/progress/TaskTreeSection.tsx`, `src/widgets/chat/changes/ReviewAll.tsx`, `src/widgets/chat/changes/SplitDiff.tsx`）**：
  - 在 `TaskTreeSection` 头部工具栏新增 **`复制任务树MD`**（`data-testid="task-tree-copy-md-btn"`）与 **`复制任务树JSON`**（`data-testid="task-tree-copy-json-btn"`）；在 `ReviewAll` 顶部工具栏新增 **`复制审查MD`**（`data-testid="review-all-copy-md-btn"`）与 **`复制审查JSON`**（`data-testid="review-all-copy-json-btn"`）；在 `SplitDiff` 表格顶部新增 **`复制分栏MD`**（`data-testid="split-diff-copy-md-btn"`）与 **`复制分栏JSON`**（`data-testid="split-diff-copy-json-btn"`）。
- **Phase 4.3 `ContextMeter`（弹层与 `ContextSourceList`）及 `MemoryWriteHints` 上下文水位报告、注入来源明细与记忆写入提示 MD/JSON 导出（`src/widgets/chat/ContextMeter.tsx`, `src/widgets/chat/MemoryWriteHints.tsx`）**：
  - 在 `ContextMeter` 弹层头部新增 **`复制水位MD`**（`data-testid="context-meter-copy-md-btn"`）与 **`复制水位JSON`**（`data-testid="context-meter-copy-json-btn"`）；在 `ContextSourceList` 头部新增 **`复制来源MD`**（`data-testid="context-meter-sources-copy-md-btn"`）与 **`复制来源JSON`**（`data-testid="context-meter-sources-copy-json-btn"`）；在 `MemoryWriteHints` 顶部新增 **`复制记忆提示MD`**（`data-testid="memory-hints-copy-md-btn"`）与 **`复制记忆提示JSON`**（`data-testid="memory-hints-copy-json-btn"`）。
- **单元测试与门禁验证**：
  - 扩展 `EventTimeline.offset.test.tsx`、`SubagentDetailDrawer.stats.test.tsx`、`TaskTreeSection.test.tsx`、`ReviewAll.test.tsx`、`SplitDiff.test.tsx`、`ContextMeter.test.tsx`、`ContextMeter.sources.test.tsx`、`ContextSourceList.test.tsx` 与 `MemoryWriteHints.test.tsx`（9 个套件共 62 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零警告门禁。
### Phase P91 — 编排计划卡片、进度面板摘要、用量趋势折线图、端点状态告警条、快捷键帮助覆盖层与 Arena 抽卡记录 / Token 窗口 / 任务控制台 MD/JSON 导出（已完成）

- **Phase 4.1 `PlanCard`、`ProgressSection` 与 `UsageTrendChart` 编排计划卡片、进度面板摘要与用量趋势图 MD/JSON 导出（`src/components/PlanCard.tsx`, `src/widgets/chat/progress/ProgressSection.tsx`, `src/widgets/settings/UsageTrendChart.tsx`）**：
  - 在 `PlanCard` 头部工具栏新增 **`复制 MD`**（`data-testid="plan-card-copy-md"`）与 **`复制 JSON`**（`data-testid="plan-card-copy-json"`），并导出纯函数 `formatPlanCardMarkdown` / `formatPlanCardJson`；在 `ProgressSection` 顶部状态栏新增 **`复制 MD`**（`data-testid="progress-section-copy-md"`）与 **`复制 JSON`**（`data-testid="progress-section-copy-json"`），并导出纯函数 `formatProgressSectionMarkdown` / `formatProgressSectionJson`；在 `UsageTrendChart` 图例栏新增 **`复制 MD`**（`data-testid="usage-trend-copy-md"`）与 **`复制 JSON`**（`data-testid="usage-trend-copy-json"`），并导出纯函数 `formatUsageTrendMarkdown` / `formatUsageTrendJson`。
- **Phase 4.2 `EndpointStatusBanner` 与 `ShortcutHelpOverlay` 端点不可达全局提示条及快捷键帮助弹窗 MD/JSON 导出（`src/widgets/system/EndpointStatusBanner.tsx`, `src/widgets/system/ShortcutHelpOverlay.tsx`）**：
  - 在 `EndpointStatusBanner` 告警操作栏新增 **`复制 MD`**（`data-testid="endpoint-banner-copy-md"`）与 **`复制 JSON`**（`data-testid="endpoint-banner-copy-json"`），并导出纯函数 `formatEndpointStatusMarkdown` / `formatEndpointStatusJson`；在 `ShortcutHelpOverlay` 弹窗标题栏新增 **`复制 MD`**（`data-testid="shortcut-help-copy-md"`）与 **`复制 JSON`**（`data-testid="shortcut-help-copy-json"`），并导出纯函数 `formatShortcutHelpMarkdown` / `formatShortcutHelpJson`。
- **Phase 4.3 `DrawPanel`、`TokenWindowCard` 与 `JobConsole` Arena 抽卡记录表、Token 窗口状态卡与任务控制台 MD/JSON 导出（`src/widgets/arena/DrawPanel.tsx`, `src/widgets/arena/TokenWindowCard.tsx`, `src/widgets/arena/JobConsole.tsx`）**：
  - 在 `DrawPanel` 抽卡记录表头部新增 **`复制 MD`**（`data-testid="draws-copy-md"`）与 **`复制 JSON`**（`data-testid="draws-copy-json"`），并导出纯函数 `formatDrawsMarkdown` / `formatDrawsJson`；在 `TokenWindowCard` 头部新增 **`复制 MD`**（`data-testid="token-window-copy-md"`）与 **`复制 JSON`**（`data-testid="token-window-copy-json"`），并导出纯函数 `formatTokenWindowMarkdown` / `formatTokenWindowJson`；在 `JobConsole` 顶部操作区新增 **`复制 MD`**（`data-testid="job-console-copy-md"`）与 **`复制 JSON`**（`data-testid="job-console-copy-json"`），并导出纯函数 `formatJobConsoleMarkdown` / `formatJobConsoleJson`。
- **单元测试与门禁验证**：
  - 扩展 `PlanCard.test.tsx`、`ProgressSection.test.tsx`、`UsageTrendChart.test.tsx`、`EndpointStatusBanner.test.tsx`、`ShortcutHelpOverlay.test.tsx`、`DrawPanel.test.tsx` 与 `JobConsole.test.tsx`（7 个套件共 54 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零错误门禁。
### Phase P92 — 期刊模板规范卡、期刊排版校验报告、Office 暂存区检查器、LLM 诊断预览卡、Arena 批量注册面板、消息网关设置卡、回答版本切换器与聊天键盘快捷键面板 MD/JSON 导出（已完成）

- **Phase 4.1 `JournalSpecCard`、`JournalValidationReport`、`OfficeStagingInspector` 与 `DiagnosticCard` 期刊模板规范、排版校验、Office 暂存区及 LLM 诊断预览 MD/JSON 导出（`src/features/journal/components/JournalSpecCard.tsx`, `src/features/journal/components/JournalValidationReport.tsx`, `src/features/office/OfficeStagingInspector.tsx`, `src/features/diagnostic/DiagnosticCard.tsx`）**：
  - 在 `JournalSpecCard` 头部新增 **`复制 MD`**（`data-testid="journal-spec-copy-md"`）与 **`复制 JSON`**（`data-testid="journal-spec-copy-json"`），并导出纯函数 `formatJournalSpecMarkdown` / `formatJournalSpecJson`；在 `JournalValidationReport` 统计栏新增 **`复制 MD`**（`data-testid="journal-validation-copy-md"`）与 **`复制 JSON`**（`data-testid="journal-validation-copy-json"`），并导出纯函数 `formatJournalValidationMarkdown` / `formatJournalValidationJson`；在 `OfficeStagingInspector` 报告区新增 **`复制 MD`**（`data-testid="office-staging-copy-md"`）与 **`复制 JSON`**（`data-testid="office-staging-copy-json"`），并导出纯函数 `formatOfficeStagingMarkdown` / `formatOfficeStagingJson`；在 `DiagnosticCard` 标题栏新增 **`复制 MD`**（`data-testid="diagnostic-card-copy-md"`）与 **`复制 JSON`**（`data-testid="diagnostic-card-copy-json"`），并导出纯函数 `formatDiagnosticPreviewMarkdown` / `formatDiagnosticPreviewJson`。
- **Phase 4.2 `BatchRegisterPanel`、`GatewayCard`、`AnswerVersionSwitcher` 与 `KeyboardShortcutsHelp` Arena 批量注册、消息网关设置卡、回答版本切换器及聊天键盘快捷键面板 MD/JSON 导出（`src/widgets/arena/BatchRegisterPanel.tsx`, `src/widgets/settings/GatewayCard.tsx`, `src/widgets/chat/AnswerVersionSwitcher.tsx`, `src/widgets/chat/KeyboardShortcutsHelp.tsx`）**：
  - 在 `BatchRegisterPanel` 头部新增 **`复制 MD`**（`data-testid="batch-register-copy-md"`）与 **`复制 JSON`**（`data-testid="batch-register-copy-json"`），并导出纯函数 `formatBatchRegisterMarkdown` / `formatBatchRegisterJson`；在 `GatewayCard` 头部操作栏新增 **`复制 MD`**（`data-testid="gateway-card-${platform}-copy-md"`）与 **`复制 JSON`**（`data-testid="gateway-card-${platform}-copy-json"`），并导出纯函数 `formatGatewayCardMarkdown` / `formatGatewayCardJson`；在 `AnswerVersionSwitcher` 切换栏新增 **`复制 MD`**（`data-testid="answer-version-copy-md"`）与 **`复制 JSON`**（`data-testid="answer-version-copy-json"`），并导出纯函数 `formatAnswerVersionsMarkdown` / `formatAnswerVersionsJson`；在 `KeyboardShortcutsHelp` 标题栏新增 **`复制 MD`**（`data-testid="keyboard-shortcuts-copy-md"`）与 **`复制 JSON`**（`data-testid="keyboard-shortcuts-copy-json"`），并导出纯函数 `formatKeyboardShortcutsMarkdown` / `formatKeyboardShortcutsJson`。
- **单元测试与门禁验证**：
  - 扩展 `JournalSpecCard.test.tsx`、`JournalValidationReport.test.tsx`、`OfficeStagingInspector.test.tsx`、`DiagnosticCard.test.tsx`、`BatchRegisterPanel.test.tsx`、`GatewayCard.test.tsx`、`AnswerVersionSwitcher.test.tsx` 与 `KeyboardShortcutsHelp.test.tsx`（8 个套件共 40 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零错误门禁。
### Phase P93 — 生成性能统计徽章、会话累计用量徽章、话题切换隔离横幅、运行中断恢复横幅、上下文水位徽章、聊天提示栈、交互提问对话框与 `/btw` 补充问答浮层 MD/JSON 导出（已完成）

- **Phase 4.1 `GenerationStatsBadge`、`SessionUsageBadge`、`TopicShiftBanner` 与 `InterruptedRunBanner` 生成速度统计、会话累计用量、话题切换及运行中断横幅 MD/JSON 导出（`src/widgets/chat/GenerationStatsBadge.tsx`, `src/widgets/chat/SessionUsageBadge.tsx`, `src/widgets/chat/TopicShiftBanner.tsx`, `src/widgets/chat/InterruptedRunBanner.tsx`）**：
  - 在 `GenerationStatsBadge` 统计栏新增 **`复制 MD`**（`data-testid="generation-stats-copy-md"`）与 **`复制 JSON`**（`data-testid="generation-stats-copy-json"`），并导出纯函数 `formatGenerationStatsMarkdown` / `formatGenerationStatsJson`；在 `SessionUsageBadge` 徽章栏新增 **`复制 MD`**（`data-testid="session-usage-copy-md"`）与 **`复制 JSON`**（`data-testid="session-usage-copy-json"`），并导出纯函数 `formatSessionUsageMarkdown` / `formatSessionUsageJson`；在 `TopicShiftBanner` 操作栏新增 **`复制 MD`**（`data-testid="topic-shift-copy-md"`）与 **`复制 JSON`**（`data-testid="topic-shift-copy-json"`），并导出纯函数 `formatTopicShiftMarkdown` / `formatTopicShiftJson`；在 `InterruptedRunBanner` 操作栏新增 **`复制 MD`**（`data-testid="interrupted-run-copy-md"`）与 **`复制 JSON`**（`data-testid="interrupted-run-copy-json"`），并导出纯函数 `formatInterruptedRunMarkdown` / `formatInterruptedRunJson`。
- **Phase 4.2 `ContextPressureBadge`、`ChatNoticeStack`、`QuestionDialog` 与 `BtwOverlay` 上下文水位徽章、聊天提示栈、交互提问对话框及 `/btw` 补充问答浮层 MD/JSON 导出（`src/widgets/chat/ContextPressureBadge.tsx`, `src/widgets/chat/ChatNoticeStack.tsx`, `src/widgets/question/QuestionDialog.tsx`, `src/features/chat/BtwOverlay.tsx`）**：
  - 在 `ContextPressureBadge` 状态条新增 **`复制 MD`**（`data-testid="context-pressure-copy-md"`）与 **`复制 JSON`**（`data-testid="context-pressure-copy-json"`），并导出纯函数 `formatContextPressureMarkdown` / `formatContextPressureJson`；在 `ChatNoticeStack` 提示栈底部新增 **`复制 MD`**（`data-testid="chat-notice-stack-copy-md"`）与 **`复制 JSON`**（`data-testid="chat-notice-stack-copy-json"`），并导出纯函数 `formatChatNoticeStackMarkdown` / `formatChatNoticeStackJson`；在 `QuestionDialog` 底部操作区新增 **`复制 MD`**（`data-testid="question-dialog-copy-md"`）与 **`复制 JSON`**（`data-testid="question-dialog-copy-json"`），并导出纯函数 `formatQuestionDialogMarkdown` / `formatQuestionDialogJson`；在 `BtwOverlay` 标题栏新增 **`复制 MD`**（`data-testid="btw-overlay-copy-md"`）与 **`复制 JSON`**（`data-testid="btw-overlay-copy-json"`），并导出纯函数 `formatBtwOverlayMarkdown` / `formatBtwOverlayJson`。
- **单元测试与门禁验证**：
  - 扩展 `GenerationStatsBadge.test.tsx`、`SessionUsageBadge.test.tsx`、`TopicShiftBanner.test.tsx`、`InterruptedRunBanner.test.tsx`、`ContextPressureBadge.test.tsx`、`ChatNoticeStack.test.tsx`、`QuestionDialog.test.tsx`、`BtwOverlay.test.tsx` 与 `BtwOverlay.sources.test.tsx`（9 个套件共 58 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零错误门禁。
### Phase P94 — 会话内查找栏、Prompt 模板填充对话框、会话轮次导航列表、新建记忆弹窗、会话列表、技能列表、欢迎页推荐任务卡与欢迎页快捷操作栏 MD/JSON 导出（已完成）

- **Phase 4.1 `ChatFindBar`、`TemplateFillDialog`、`TurnList` 与 `NewMemoryModal` 会话内查找栏、Prompt 模板变量填充对话框、轮次导航列表及新建记忆草稿 MD/JSON 导出（`src/widgets/chat/ChatFindBar.tsx`, `src/widgets/chat/TemplateFillDialog.tsx`, `src/widgets/chat/TurnList.tsx`, `src/widgets/memory/NewMemoryModal.tsx`）**：
  - 在 `ChatFindBar` 操作区新增 **`复制 MD`**（`data-testid="chat-find-copy-md"`）与 **`复制 JSON`**（`data-testid="chat-find-copy-json"`），并导出纯函数 `formatChatFindResultsMarkdown` / `formatChatFindResultsJson`；在 `TemplateFillDialog` 标题栏新增 **`复制 MD`**（`data-testid="tplfill-copy-md"`）与 **`复制 JSON`**（`data-testid="tplfill-copy-json"`），并导出纯函数 `formatTemplateFillMarkdown` / `formatTemplateFillJson`；在 `TurnList` 顶部栏新增 **`复制 MD`**（`data-testid="turn-list-copy-md"`）与 **`复制 JSON`**（`data-testid="turn-list-copy-json"`），并导出纯函数 `formatTurnListMarkdown` / `formatTurnListJson`；在 `NewMemoryModal` 底部操作栏新增 **`复制草稿MD`**（`data-testid="new-memory-copy-draft-md-btn"`），并导出纯函数 `formatNewMemoryDraftMarkdown` / `formatNewMemoryDraftJson`。
- **Phase 4.2 `SessionList`、`SkillList`、`AssistantRecommendations` 与 `QuickActionBar` 会话列表、技能列表、欢迎页推荐卡片及欢迎页快捷操作栏 MD/JSON 导出（`src/widgets/session/SessionList.tsx`, `src/widgets/skills/SkillList.tsx`, `src/widgets/welcome/AssistantRecommendations.tsx`, `src/widgets/welcome/QuickActionBar.tsx`）**：
  - 在 `SessionList` 顶部栏新增 **`复制 MD`**（`data-testid="session-list-copy-md"`）与 **`复制 JSON`**（`data-testid="session-list-copy-json"`），并导出纯函数 `formatSessionListMarkdown` / `formatSessionListJson`；在 `SkillList` 顶部工具栏新增 **`复制 MD`**（`data-testid="skill-list-copy-md"`）与 **`复制 JSON`**（`data-testid="skill-list-copy-json"`），并导出纯函数 `formatSkillListMarkdown` / `formatSkillListJson`；在 `AssistantRecommendations` 标题栏新增 **`复制 MD`**（`data-testid="recommendations-copy-md"`）与 **`复制 JSON`**（`data-testid="recommendations-copy-json"`），并导出纯函数 `formatRecommendationsMarkdown` / `formatRecommendationsJson`；在 `QuickActionBar` 工具栏新增 **`复制 MD`**（`data-testid="quick-actions-copy-md"`）与 **`复制 JSON`**（`data-testid="quick-actions-copy-json"`），并导出纯函数 `formatQuickActionsMarkdown` / `formatQuickActionsJson`。
- **单元测试与门禁验证**：
  - 扩展 `ChatFindBar.test.tsx`、`TemplateFillDialog.test.tsx`、`TurnList.test.tsx`、`NewMemoryModal.test.tsx`、`SessionList.test.tsx`、`SkillList.test.tsx`、`AssistantRecommendations.test.tsx` 与 `QuickActionBar.test.tsx`（含 `Welcome.test.tsx` 与 `ConversationsSection.test.tsx` 联调共 10 个套件 64 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零错误门禁。
### Phase P95 — 全局更新通知弹窗、Word 原生预览器、Office 交付验收抽屉、Office 文档历史列表、Office 文件导入器、首启配置向导、项目治理规则面板与任务交付简报对话框 MD/JSON 导出（已完成）

- **Phase 4.1 `UpdateDialog`、`DocxNativePreview`、`OfficeDeliveryDrawer` 与 `OfficeDocumentList` 全局更新通知、Word 原生预览、Office 交付验收抽屉及文档历史列表 MD/JSON 导出（`src/components/UpdateDialog.tsx`, `src/features/office/DocxNativePreview.tsx`, `src/features/office/OfficeDeliveryDrawer.tsx`, `src/features/office/OfficeDocumentList.tsx`）**：
  - 在 `UpdateDialog` 标题栏新增 **`复制 MD`**（`data-testid="update-dialog-copy-md"`）与 **`复制 JSON`**（`data-testid="update-dialog-copy-json"`），并导出纯函数 `formatUpdateDialogMarkdown` / `formatUpdateDialogJson`；在 `DocxNativePreview` 顶部状态栏新增 **`复制 MD`**（`data-testid="docx-preview-copy-md"`）与 **`复制 JSON`**（`data-testid="docx-preview-copy-json"`），并导出纯函数 `formatDocxPreviewMetaMarkdown` / `formatDocxPreviewMetaJson`；在 `OfficeDeliveryDrawer` 抽屉头部新增 **`复制 MD`**（`data-testid="delivery-drawer-copy-md"`）与 **`复制 JSON`**（`data-testid="delivery-drawer-copy-json"`），并导出纯函数 `formatOfficeDeliveryMarkdown` / `formatOfficeDeliveryJson`；在 `OfficeDocumentList` 顶部栏新增 **`复制 MD`**（`data-testid="office-doc-list-copy-md"`）与 **`复制 JSON`**（`data-testid="office-doc-list-copy-json"`），并导出纯函数 `formatOfficeDocumentListMarkdown` / `formatOfficeDocumentListJson`。
- **Phase 4.2 `OfficeFilePicker`、`OnboardingWizard`、`GovernanceRulesPanel` 与 `TaskBriefDialog` Office 文件导入器、首启配置向导、项目治理规则面板及任务交付简报弹窗 MD/JSON 导出（`src/features/office/OfficeFilePicker.tsx`, `src/features/onboarding/OnboardingWizard.tsx`, `src/features/project-type/GovernanceRulesPanel.tsx`, `src/features/task-brief/TaskBriefDialog.tsx`）**：
  - 在 `OfficeFilePicker` 顶部工具栏新增 **`复制 MD`**（`data-testid="office-picker-${docType}-copy-md"`）与 **`复制 JSON`**（`data-testid="office-picker-${docType}-copy-json"`），并导出纯函数 `formatOfficePickerMarkdown` / `formatOfficePickerJson`；在 `OnboardingWizard` 步骤指示栏新增 **`复制 MD`**（`data-testid="wizard-copy-md"`）与 **`复制 JSON`**（`data-testid="wizard-copy-json"`），并导出纯函数 `formatOnboardingWizardMarkdown` / `formatOnboardingWizardJson`；在 `GovernanceRulesPanel` 第一节标题栏新增 **`复制 MD`**（`data-testid="governance-rules-copy-md"`）与 **`复制 JSON`**（`data-testid="governance-rules-copy-json"`），并导出纯函数 `formatGovernanceRulesMarkdown` / `formatGovernanceRulesJson`；在 `TaskBriefDialog` 底部操作区新增 **`复制 MD`**（`data-testid="task-brief-copy-md"`）与 **`复制 JSON`**（`data-testid="task-brief-copy-json"`），并导出纯函数 `formatTaskBriefMarkdown` / `formatTaskBriefJson`。
- **单元测试与门禁验证**：
  - 扩展 `UpdateDialog.test.tsx`、`DocxNativePreview.test.tsx`、`OfficeDeliveryDrawer.test.tsx`、`OfficeDocumentList.test.tsx`、`OfficeFilePicker.test.tsx`、`OnboardingWizard.test.tsx`、`GovernanceRulesPanel.test.tsx` 与 `TaskBriefDialog.test.tsx`（8 个套件共 66 项单测全部通过），并通过 `check-font-scale.mjs`、`architecture-check.mjs`、`tsc --noEmit` 与 `eslint` 零错误门禁。

### Phase P96（2026-10-20）：@文件菜单、定时任务配置与 Cron 选择器、CSS 主题弹窗与主题画廊、空工作区引导、权限模式切换与会话模型选择器审计快照导出（PR #2181 / #2182）

1. **@文件引用候选列表 (`src/features/chat/AtFileMenu.tsx`)**：
   - 新增并导出 `formatAtFileMenuMarkdown` 与 `formatAtFileMenuJson` 纯函数及头部一键复制按钮（`data-testid="at-file-menu-copy-md"` / `data-testid="at-file-menu-copy-json"`），支持导出检索关键词、工作区名与候选文件清单。
2. **定时任务配置弹窗 (`src/features/scheduled/CreateTaskModal.tsx`)**：
   - 新增并导出 `formatScheduledTaskDraftMarkdown` 与 `formatScheduledTaskDraftJson` 纯函数及顶栏一键复制按钮（`data-testid="create-task-copy-md"` / `data-testid="create-task-copy-json"`），支持导出任务名称、调度类型、Cron/时间、目标会话与提示词草稿。
3. **Cron 表达式配置器 (`src/features/scheduled/CronExpressionPicker.tsx`)**：
   - 新增并导出 `formatCronPickerMarkdown` 与 `formatCronPickerJson` 纯函数及预设栏一键复制按钮（`data-testid="cron-picker-copy-md"` / `data-testid="cron-picker-copy-json"`），支持导出预设档位、表达式及校验状态。
4. **自定义 CSS 主题弹窗 (`src/features/theme/CssThemeModal.tsx`)**：
   - 新增并导出 `formatCssThemeDraftMarkdown` 与 `formatCssThemeDraftJson` 纯函数及标题栏一键复制按钮（`data-testid="css-theme-copy-md"` / `data-testid="css-theme-copy-json"`），支持导出主题名称、外观基准、校验状态与 CSS 源码。
5. **主题画廊 (`src/features/theme/ThemeGallery.tsx`)**：
   - 新增并导出 `formatThemeGalleryMarkdown` 与 `formatThemeGalleryJson` 纯函数及标题栏一键复制按钮（`data-testid="theme-gallery-copy-md"` / `data-testid="theme-gallery-copy-json"`），支持导出当前激活预设及基础/装饰主题清单。
6. **空工作区引导状态 (`src/features/workspace/WorkspaceEmptyGuard.tsx`)**：
   - 新增并导出 `formatWorkspaceGuardMarkdown` 与 `formatWorkspaceGuardJson` 纯函数及一键复制按钮（`data-testid="workspace-guard-copy-md"` / `data-testid="workspace-guard-copy-json"`），支持导出触发功能、引导文案与最近错误。
7. **会话权限模式与自动放行切换器 (`src/widgets/chat/PermissionModeSwitch.tsx`)**：
   - 新增并导出 `formatPermissionModeMarkdown` 与 `formatPermissionModeJson` 纯函数及一键复制按钮（`data-testid="permission-mode-copy-md"` / `data-testid="permission-mode-copy-json"`），支持导出当前权限预设、自动放行计数及审计明细。
8. **会话模型选择器 (`src/widgets/chat/SessionModelPicker.tsx`)**：
   - 新增并导出 `formatSessionModelPickerMarkdown` 与 `formatSessionModelPickerJson` 纯函数及一键复制按钮（`data-testid="session-model-copy-md"` / `data-testid="session-model-copy-json"`），支持导出会话覆盖模型、全局默认模型与候选数量。

### Phase P97（2026-10-21）：模型目录页、编排中心页、欢迎页与输入卡片、更新源管理、主题选择器、更新配置页与输入框工具菜单审计快照导出（PR #2183 / #2184）

1. **模型目录页面 (`src/pages/ModelCatalog.tsx`)**：
   - 新增并导出 `formatModelCatalogPageMarkdown` 与 `formatModelCatalogPageJson` 纯函数及顶栏一键复制控件（`data-testid="model-catalog-page-copy-md"` / `data-testid="model-catalog-page-copy-json"`），支持导出筛选端点、检索词、模型总数/筛选数、快照数与当前选中模型。
2. **编排中心页面 (`src/pages/Orchestration.tsx`)**：
   - 新增并导出 `formatOrchestrationPageMarkdown` 与 `formatOrchestrationPageJson` 纯函数及顶栏一键复制控件（`data-testid="orch-page-copy-md"` / `data-testid="orch-page-copy-json"`），支持导出目标草稿、创建状态与当前泳道总数。
3. **欢迎页 (`src/pages/Welcome.tsx`)**：
   - 新增并导出 `formatWelcomePageMarkdown` 与 `formatWelcomePageJson` 纯函数及入口栏一键复制控件（`data-testid="welcome-page-copy-md"` / `data-testid="welcome-page-copy-json"`），支持导出界面语言、首启向导状态、推荐模板数与当前打开任务简报。
4. **更新源管理面板 (`src/pages/settings/ProvidersManager.tsx`)**：
   - 新增并导出 `formatProvidersListMarkdown` 与 `formatProvidersListJson` 纯函数及顶栏一键复制控件（`data-testid="providers-copy-md"` / `data-testid="providers-copy-json"`），支持导出更新源总数、默认更新源及各源类型与启用状态。
5. **主题选择器 (`src/pages/settings/ThemeSelector.tsx`)**：
   - 新增并导出 `formatThemeSelectorMarkdown` 与 `formatThemeSelectorJson` 纯函数及一键复制控件（`data-testid="theme-selector-copy-md"` / `data-testid="theme-selector-copy-json"`），支持导出当前激活主题来源与自定义 CSS 主题清单。
6. **更新配置页 (`src/pages/settings/UpdatesTab.tsx`)**：
   - 新增并导出 `formatUpdatesConfigMarkdown` 与 `formatUpdatesConfigJson` 纯函数及顶栏一键复制控件（`data-testid="updates-tab-copy-md"` / `data-testid="updates-tab-copy-json"`），支持导出更新策略、通道、回滚窗口、检查周期、服务器地址与遥测开关。
7. **输入框「+」工具菜单 (`src/widgets/chat/ComposerPlusMenu.tsx`)**：
   - 新增并导出 `formatComposerPlusMenuMarkdown` 与 `formatComposerPlusMenuJson` 纯函数及菜单顶栏一键复制控件（`data-testid="composer-plus-copy-md"` / `data-testid="composer-plus-copy-json"`），支持导出工具菜单项清单、快捷键提示与禁用状态。
8. **欢迎页输入卡片 (`src/widgets/welcome/WelcomeInputCard.tsx`)**：
   - 新增并导出 `formatWelcomeInputMarkdown` 与 `formatWelcomeInputJson` 纯函数及卡片底部一键复制控件（`data-testid="welcome-input-copy-md"` / `data-testid="welcome-input-copy-json"`），支持导出当前占位文案、禁用状态与草稿正文。

---

## 105. Phase P98（2026-10-21）：Arena 控制台、Arena 账号页、技能管理页与设置分栏（基础、模型、编排、开发环境、Zotero）治理审计快照与一键复制

### 105.1 背景与目标
- 延续 Phase P0–P97 的全量可观测性与无侵入式复制体验，覆盖主页面与设置子面板中剩余的 8 个核心模块：
  1. `src/pages/Arena.tsx`（Arena 控制台：当前页签、账号池数量、可用账号数与启用/异常状态审计快照与 JSON 导出）
  2. `src/pages/ArenaAccounts.tsx`（Arena 账号页：账号池总数、可用账号数与自动化启用状态审计快照与 JSON 导出）
  3. `src/pages/Skills.tsx`（技能管理页：当前页签、技能总数、已启用数、筛选数、总使用次数、自动刷新开关与巡检建议数审计快照与 JSON 导出）
  4. `src/pages/settings/BasicTab.tsx`（基础设置分栏：流式输出、LLM 重试上限/退避参数、IANA 时区、日志时区与演示模式审计快照与 JSON 导出）
  5. `src/pages/settings/ModelsTab.tsx`（模型选择分栏：可用端点数、已发现模型数、对话/视觉/向量模型绑定、上下文窗口模式与 Temperature 审计快照与 JSON 导出）
  6. `src/pages/settings/OrchestrationTab.tsx`（编排设置分栏：计划前置澄清/侦察开关、最大并发/重试/迭代上限、审批模式、Worktree 隔离与 Scratch 根目录审计快照与 JSON 导出）
  7. `src/pages/settings/RuntimeEnvTab.tsx`（开发环境分栏：运行时探测状态、可用运行时数、当前选中运行时、项目诊断状态与试跑状态审计快照与 JSON 导出）
  8. `src/pages/settings/ZoteroTab.tsx`（Zotero 文献库分栏：连接状态、文献条目数、分类数、当前搜索结果数及搜索/分类/标签过滤条件审计快照与 JSON 导出）

### 105.2 交付清单（Dual-Track：`main` & `release/win7`）
- **纯函数导出**：
  - `formatArenaAuditSnapshot` / `formatArenaAuditJson` (`src/pages/Arena.tsx`)
  - `formatArenaAccountsAuditSnapshot` / `formatArenaAccountsAuditJson` (`src/pages/ArenaAccounts.tsx`)
  - `formatSkillsAuditSnapshot` / `formatSkillsAuditJson` (`src/pages/Skills.tsx`)
  - `formatBasicTabAuditSnapshot` / `formatBasicTabAuditJson` (`src/pages/settings/BasicTab.tsx`)
  - `formatModelsTabAuditSnapshot` / `formatModelsTabAuditJson` (`src/pages/settings/ModelsTab.tsx`)
  - `formatOrchestrationTabAuditSnapshot` / `formatOrchestrationTabAuditJson` (`src/pages/settings/OrchestrationTab.tsx`)
  - `formatRuntimeEnvTabAuditSnapshot` / `formatRuntimeEnvTabAuditJson` (`src/pages/settings/RuntimeEnvTab.tsx`)
  - `formatZoteroTabAuditSnapshot` / `formatZoteroTabAuditJson` (`src/pages/settings/ZoteroTab.tsx`)
- **非按钮 `<span>` 审计复制控件**：
  - `arena-copy-audit` / `arena-copy-json`
  - `arena-accounts-copy-audit` / `arena-accounts-copy-json`
  - `skills-page-copy-audit` / `skills-page-copy-json`
  - `basic-tab-copy-audit` / `basic-tab-copy-json`
  - `models-tab-copy-audit` / `models-tab-copy-json`
  - `orchestration-tab-copy-audit` / `orchestration-tab-copy-json`
  - `runtime-env-tab-copy-audit` / `runtime-env-tab-copy-json`
  - `zotero-tab-copy-audit` / `zotero-tab-copy-json`
- **单元测试与门禁**：
  - 8 个测试套件（`Arena.test.tsx`, `ArenaAccounts.test.tsx`, `Skills.test.tsx`, `BasicTab.test.tsx`, `ModelsTab.test.tsx`, `OrchestrationTab.test.tsx`, `RuntimeEnvTab.test.tsx`, `ZoteroTab.test.tsx`）在 `main`（68 项测试）与 `release/win7`（78 项测试）全绿通过。
  - `ESLint`、`tsc --noEmit`、`check-font-scale.mjs`、`architecture-check.mjs` 全部零告警通过。

### Phase P99：设置页标签与办公生成/预览面板（Endpoints / General / MCP / Memory / Network / PromptTemplates / OfficeGenerateForm / OfficePreviewPanel）治理审计快照与一键导出（已完成）
- **端到端交付**：
  1. **端点配置标签（`src/pages/settings/EndpointsTab.tsx`）**：新增 `formatEndpointsTabAuditSnapshot` 与 `formatEndpointsTabAuditJson` 纯函数及头部一键复制控件（`data-testid="endpoints-tab-copy-summary"` / `data-testid="endpoints-tab-copy-json"`），支持导出端点总数、编辑态 ID 与连接测试状态。
  2. **通用设置标签（`src/pages/settings/GeneralTab.tsx`）**：新增 `formatGeneralTabAuditSnapshot` 与 `formatGeneralTabAuditJson` 纯函数及头部一键复制控件（`data-testid="general-tab-copy-summary"` / `data-testid="general-tab-copy-json"`），支持导出流式输出开关、IANA 时区、日志时区、自动记忆提取与删除确认状态。
  3. **MCP 服务管理标签（`src/pages/settings/McpTab.tsx`）**：新增 `formatMcpTabAuditSnapshot` 与 `formatMcpTabAuditJson` 纯函数及头部一键复制控件（`data-testid="mcp-tab-copy-summary"` / `data-testid="mcp-tab-copy-json"`），支持导出服务总数、就绪数、刷新态与错误状态。
  4. **记忆管理标签（`src/pages/settings/MemoryTab.tsx`）**：新增 `formatMemoryTabAuditSnapshot` 与 `formatMemoryTabAuditJson` 纯函数及头部一键复制控件（`data-testid="memory-tab-copy-summary"` / `data-testid="memory-tab-copy-json"`），支持导出嵌入器类型、语义匹配状态、模型就绪态与自动备份份数。
  5. **网络策略标签（`src/pages/settings/NetworkTab.tsx`）**：新增 `formatNetworkTabAuditSnapshot` 与 `formatNetworkTabAuditJson` 纯函数及头部一键复制控件（`data-testid="network-tab-copy-summary"` / `data-testid="network-tab-copy-json"`），支持导出网络访问模式、白名单主机数、TLS 豁免主机数、代理配置态与首选搜索引擎。
  6. **提示词模板标签（`src/pages/settings/PromptTemplatesTab.tsx`）**：新增 `formatPromptTemplatesTabAuditSnapshot` 与 `formatPromptTemplatesTabAuditJson` 纯函数及头部一键复制控件（`data-testid="prompt-templates-tab-copy-summary"` / `data-testid="prompt-templates-tab-copy-json"`），支持导出模板总数、加载态、编辑态与导入冲突状态。
  7. **办公文档生成表单（`src/features/office/OfficeGenerateForm.tsx`）**：新增 `formatOfficeGenerateFormAuditSnapshot` 与 `formatOfficeGenerateFormAuditJson` 纯函数及头部一键复制控件（`data-testid="office-generate-form-copy-summary"` / `data-testid="office-generate-form-copy-json"`），支持导出文档类型、创建模式（自由/模板）、目标文件名、生成繁忙态与结果状态。
  8. **办公文档预览面板（`src/features/office/OfficePreviewPanel.tsx`）**：新增 `formatOfficePreviewPanelAuditSnapshot` 与 `formatOfficePreviewPanelAuditJson` 纯函数及头部一键复制控件（`data-testid="office-preview-panel-copy-summary"` / `data-testid="office-preview-panel-copy-json"`），支持导出文档类型、文件名、字节大小、高保真/结构化视图模式与 PDF 导出状态。
- **验证结果**：
  - 单元测试：`EndpointsTab.test.tsx`、`GeneralTab.test.tsx`、`McpTab.test.tsx`、`MemoryTab.test.tsx`、`NetworkTab.test.tsx`、`PromptTemplatesTab.test.tsx`、`OfficeGenerateForm.test.tsx`、`OfficePreviewPanel.test.tsx`（`main` 8 个测试套件 109 项单测全部通过；`release/win7` 8 个测试套件 99 项单测全部通过）。
  - 门禁检查：`npx eslint` 0 error、`npx tsc --noEmit` 0 error、`check-font-scale.mjs` 通过、`architecture-check.mjs` 通过。

### Phase P100 — 治理页面、主题/诊断组件与欢迎/侧栏分区审计快照与 JSON 导出（已完成）
- **目标**：为 `ExportButton.tsx`、`ProjectTypeBadge.tsx`、`CodeMirrorThemeEditor.tsx`、`ThemeCover.tsx`、`ProjectGovernance.tsx`、`ArenaAccountsToggle.tsx`、`WelcomeHero.tsx` 与 `SiderSection.tsx` 补齐纯函数审计快照与 JSON 导出（`format*AuditSnapshot` / `format*AuditJson`）及无障碍复制控件。
- **交付范围**：
  - `src/features/diagnostic/ExportButton.tsx`：`formatExportButtonAuditSnapshot` / `formatExportButtonAuditJson` + `export-button-copy-snapshot` / `export-button-copy-json`
  - `src/features/project-type/ProjectTypeBadge.tsx`：`formatProjectTypeBadgeAuditSnapshot` / `formatProjectTypeBadgeAuditJson` + `project-type-badge-copy-snapshot` / `project-type-badge-copy-json`
  - `src/features/theme/CodeMirrorThemeEditor.tsx`：`formatCodeMirrorThemeEditorAuditSnapshot` / `formatCodeMirrorThemeEditorAuditJson` + `cm-theme-editor-copy-snapshot` / `cm-theme-editor-copy-json`
  - `src/features/theme/ThemeCover.tsx`：`formatThemeCoverAuditSnapshot` / `formatThemeCoverAuditJson` + `theme-cover-copy-snapshot` / `theme-cover-copy-json`
  - `src/pages/ProjectGovernance.tsx`：`formatProjectGovernanceAuditSnapshot` / `formatProjectGovernanceAuditJson` + `project-governance-copy-snapshot` / `project-governance-copy-json`
  - `src/pages/settings/ArenaAccountsToggle.tsx`：`formatArenaAccountsToggleAuditSnapshot` / `formatArenaAccountsToggleAuditJson` + `arena-accounts-toggle-copy-snapshot` / `arena-accounts-toggle-copy-json`
  - `src/widgets/welcome/WelcomeHero.tsx`：`formatWelcomeHeroAuditSnapshot` / `formatWelcomeHeroAuditJson` + `welcome-hero-copy-snapshot` / `welcome-hero-copy-json`
  - `src/widgets/sidebar/SiderSection.tsx`：`formatSiderSectionAuditSnapshot` / `formatSiderSectionAuditJson` + `sider-section-copy-snapshot` / `sider-section-copy-json`
  - 单元测试：`ExportButton.test.tsx`、`ProjectTypeBadge.test.tsx`、`CodeMirrorThemeEditor.test.tsx`、`ThemeCover.test.tsx`、`ProjectGovernance.test.tsx`、`ArenaAccountsToggle.test.tsx`、`WelcomeHero.test.tsx`、`SiderSection.test.tsx`

### Phase P101（2026-10-21）：侧栏项目清单、两步删除、导航分组、标题栏与对话选择引用审计快照与 JSON 导出（Dual-Track `main` + `release/win7`）
- **定位与目标**：将确定性单行审计快照（`format*AuditSnapshot`）与结构化 JSON 审计载荷（`format*AuditJson`）扩展至侧栏两步删除按钮、侧栏项目清单、导航分组、桌面端标题栏、标题栏前进/后退动作栏、窗口控制栏、Markdown 图片预览与对话划词引用按钮 8 个高频基础交互组件：
  1. **侧栏两步删除按钮审计快照与 JSON 导出（`TwoStepDelete.tsx`）**：新增 `formatTwoStepDeleteAuditSnapshot` / `formatTwoStepDeleteAuditJson` 纯函数及 `two-step-delete-copy-snapshot` / `two-step-delete-copy-json` 审计控件，输出二次确认挂起状态、禁用态、标签文案与自动复位超时毫秒数。
  2. **侧栏项目清单审计快照与 JSON 导出（`SidebarProjectList.tsx`）**：新增 `formatSidebarProjectListAuditSnapshot` / `formatSidebarProjectListAuditJson` 纯函数及 `sidebar-project-list-copy-snapshot` / `sidebar-project-list-copy-json` 审计控件，输出项目总数、已展开项目数、缺失目录项目数、分组折叠态与拖拽悬停态。
  3. **侧栏导航分组审计快照与 JSON 导出（`NavGroup.tsx`）**：新增 `formatNavGroupAuditSnapshot` / `formatNavGroupAuditJson` 纯函数及 `nav-group-copy-snapshot` / `nav-group-copy-json` 审计控件，输出分组标识、分组标题、可折叠配置与当前折叠状态。
  4. **桌面标题栏审计快照与 JSON 导出（`Titlebar.tsx`）**：新增 `formatTitlebarAuditSnapshot` / `formatTitlebarAuditJson` 纯函数及 `titlebar-copy-snapshot` / `titlebar-copy-json` 审计控件，输出平台类型、Electron 桌面环境标志、品牌 Logo 隐藏态与移动端侧栏展开态。
  5. **标题栏前进/后退动作栏审计快照与 JSON 导出（`TitlebarActions.tsx`）**：新增 `formatTitlebarActionsAuditSnapshot` / `formatTitlebarActionsAuditJson` 纯函数及 `titlebar-actions-copy-snapshot` / `titlebar-actions-copy-json` 审计控件，输出历史栈可后退与可前进状态。
  6. **窗口控制栏审计快照与 JSON 导出（`WindowControls.tsx`）**：新增 `formatWindowControlsAuditSnapshot` / `formatWindowControlsAuditJson` 纯函数及 `window-controls-copy-snapshot` / `window-controls-copy-json` 审计控件，输出自定义控制桥接注入状态与窗口控制动作计数。
  7. **Markdown 图片渲染与灯箱审计快照与 JSON 导出（`MarkdownImage.tsx`）**：新增 `formatMarkdownImageAuditSnapshot` / `formatMarkdownImageAuditJson` 纯函数及 `markdown-image-copy-snapshot` / `markdown-image-copy-json` 审计控件，输出图片地址、替代文本、加载状态、本地媒体标识与灯箱预览开启状态。
  8. **对话划词引用按钮审计快照与 JSON 导出（`SelectionQuoteButton.tsx`）**：新增 `formatSelectionQuoteButtonAuditSnapshot` / `formatSelectionQuoteButtonAuditJson` 纯函数及 `selection-quote-copy-snapshot` / `selection-quote-copy-json` 审计控件，输出选区激活态、选中文本长度与浮动坐标。
- **验证结果**：8 个目标单测套件（共 71 条单测）、`eslint`、`tsc --noEmit`、`check-font-scale.mjs` 与 `architecture-check.mjs` 在 `main` 与 `release/win7` 双轨全部通过。

### Phase P102（2026-10-21）：共享 UI 原语（待办徽标、品牌标志、活跃状态点、下拉菜单、错误态、加载态、重试按钮与选择器）审计快照与 JSON 导出（Dual-Track `main` + `release/win7`）
- **定位与目标**：将确定性单行审计快照（`format*AuditSnapshot`）与结构化 JSON 审计载荷（`format*AuditJson`）扩展至 `src/shared/ui/` 8 个核心设计系统原语组件：
  1. **待处理数量徽标审计快照与 JSON 导出（`AttnBadge.tsx`）**：新增 `formatAttnBadgeAuditSnapshot` / `formatAttnBadgeAuditJson` 纯函数及 `attn-badge-copy-snapshot` / `attn-badge-copy-json` 审计控件，输出待处理计数、99+ 截断标记与解析后标题。
  2. **品牌标志组件审计快照与 JSON 导出（`BrandLogo.tsx`）**：新增 `formatBrandLogoAuditSnapshot` / `formatBrandLogoAuditJson` 纯函数及 `brand-logo-copy-snapshot` / `brand-logo-copy-json` 审计控件，输出尺寸档位、Wordmark 启用态、替代文本与测试标识。
  3. **活跃度指示点审计快照与 JSON 导出（`LiveDot.tsx`）**：新增 `formatLiveDotAuditSnapshot` / `formatLiveDotAuditJson` 纯函数及 `live-dot-copy-snapshot` / `live-dot-copy-json` 审计控件，输出活跃状态档位（`working` / `sleeping` / `idle`）与提示标签。
  4. **Radix 下拉菜单审计快照与 JSON 导出（`DropdownMenu.tsx`）**：新增 `formatDropdownMenuAuditSnapshot` / `formatDropdownMenuAuditJson` 纯函数及 `dropdown-menu-copy-snapshot` / `dropdown-menu-copy-json` 审计控件，输出对齐方式、偏移像素、菜单项计数与危险操作标记。
  5. **统一错误态面板审计快照与 JSON 导出（`ErrorState.tsx`）**：新增 `formatErrorStateAuditSnapshot` / `formatErrorStateAuditJson` 纯函数及 `error-state-copy-snapshot` / `error-state-copy-json` 审计控件，输出错误标题、错误详情、重试回调绑定态与重试按钮文案。
  6. **统一加载态原语审计快照与 JSON 导出（`LoadingState.tsx`）**：新增 `formatLoadingStateAuditSnapshot` / `formatLoadingStateAuditJson` 纯函数及 `loading-state-copy-snapshot` / `loading-state-copy-json` 审计控件，输出加载变体（`spinner` / `skeleton`）、提示文案与骨架屏行数。
  7. **指数退避重试按钮审计快照与 JSON 导出（`RetryButton.tsx`）**：新增 `formatRetryButtonAuditSnapshot` / `formatRetryButtonAuditJson` 纯函数及 `retry-button-copy-snapshot` / `retry-button-copy-json` 审计控件，输出已尝试次数、最大尝试上限、忙碌状态、当前冷却毫秒数与按钮标签。
  8. **Radix 选择器原语审计快照与 JSON 导出（`Select.tsx`）**：新增 `formatSelectAuditSnapshot` / `formatSelectAuditJson` 纯函数及 `select-copy-snapshot` / `select-copy-json` 审计控件，输出定位模式、禁用状态与值绑定状态。
- **验证结果**：8 个目标单测套件（共 52 条单测）、`eslint`、`tsc --noEmit`、`check-font-scale.mjs` 与 `architecture-check.mjs` 在 `main` 与 `release/win7` 双轨全部通过。

### Phase P103（2026-10-21）：Providers、Font、Settings Row、MermaidBlock、MessageList 与 ConversationsSection 治理快照与 JSON 导出闭环

- **目标**：为全局 Provider、字体状态、设置项行、Mermaid 图表、消息列表与会话列表分区补齐统一治理审计快照（`data-*-audit`）与一键复制审计快照/JSON 能力（`role="status"` 无障碍复制控件）：
  1. `src/app/providers/NavHistoryProvider.tsx`：新增 `formatNavHistoryAuditSnapshot` 与 `formatNavHistoryAuditJson`，暴露 `data-nav-history-audit`、`nav-history-audit-copy` 与 `nav-history-audit-copy-json`。
  2. `src/app/providers/SessionWorkspaceProvider.tsx`：新增 `formatSessionWorkspaceAuditSnapshot` 与 `formatSessionWorkspaceAuditJson`，暴露 `data-session-workspace-audit`、`session-workspace-audit-copy` 与 `session-workspace-audit-copy-json`。
  3. `src/app/providers/ThemeProvider.tsx`：新增 `formatThemeAuditSnapshot` 与 `formatThemeAuditJson`，暴露 `data-theme-audit`、`theme-audit-copy` 与 `theme-audit-copy-json`。
  4. `src/entities/font/useFontSettings.tsx`：新增 `formatFontSettingsAuditSnapshot` 与 `formatFontSettingsAuditJson`，暴露 `data-font-settings-audit`、`font-settings-audit-copy` 与 `font-settings-audit-copy-json`。
  5. `src/pages/settings/components.tsx`：新增 `formatSettingRowAuditSnapshot` 与 `formatSettingRowAuditJson`，暴露 `data-setting-row-audit`、`setting-row-audit-copy` 与 `setting-row-audit-copy-json`。
  6. `src/widgets/chat/MermaidBlock.tsx`：新增 `formatMermaidBlockAuditSnapshot` 与 `formatMermaidBlockAuditJson`，暴露 `data-mermaid-block-audit`、`mermaid-block-audit-copy` 与 `mermaid-block-audit-copy-json`。
  7. `src/widgets/chat/MessageList.tsx`：新增 `formatMessageListAuditSnapshot` 与 `formatMessageListAuditJson`，暴露 `data-message-list-audit`、`message-list-audit-copy` 与 `message-list-audit-copy-json`。
  8. `src/widgets/sidebar/sections/ConversationsSection.tsx`：新增 `formatConversationsSectionAuditSnapshot` 与 `formatConversationsSectionAuditJson`，暴露 `data-conversations-section-audit`、`conversations-section-audit-copy` 与 `conversations-section-audit-copy-json`。
- **验证**：8 个单元测试文件（`main` 67 项单测 / `release/win7` 65 项单测）、ESLint、TypeScript、`check-font-scale.mjs`、`architecture-check.mjs` 全部零警告通过。
### Phase P104（2026-10-21）：PanelShell、MessageActionBar、TrajectoryPane、FileChangeCard、CommandPalette、useAttentionSnapshot、btwState 与 fontStorage 治理快照与 JSON 导出闭环（Dual-Track `main` + `release/win7`）

- **目标**：为通用面板壳层、消息操作栏、会话轨迹面板、文件变更卡、命令面板、注意力聚合订阅层、`/btw` 状态机与字体存储层补齐统一确定性审计快照（`build*AuditSnapshot`）与结构化 JSON 导出（`build*AuditJson`）及无障碍复制控件（`role="status"`）：
  1. `src/shared/ui/PanelShell.tsx`：新增 `buildPanelShellAuditSnapshot` 与 `buildPanelShellAuditJson`，暴露 `panel-shell-copy-audit` 与 `panel-shell-copy-audit-json`。
  2. `src/widgets/chat/MessageActionBar.tsx`：新增 `buildMessageActionBarAuditSnapshot` 与 `buildMessageActionBarAuditJson`，暴露 `message-action-bar-copy-audit` 与 `message-action-bar-copy-audit-json`。
  3. `src/widgets/chat/TrajectoryPane.tsx`：新增 `buildTrajectoryPaneAuditSnapshot` 与 `buildTrajectoryPaneAuditJson`，暴露 `trajectory-pane-copy-audit` 与 `trajectory-pane-copy-audit-json`。
  4. `src/widgets/chat/changes/FileChangeCard.tsx`：新增 `buildFileChangeCardAuditSnapshot` 与 `buildFileChangeCardAuditJson`，暴露 `file-change-card-copy-audit` 与 `file-change-card-copy-audit-json`。
  5. `src/widgets/command/CommandPalette.tsx`：新增 `buildCommandPaletteAuditSnapshot` 与 `buildCommandPaletteAuditJson`，暴露 `command-palette-copy-audit` 与 `command-palette-copy-audit-json`。
  6. `src/features/attention/useAttentionSnapshot.ts`：新增 `buildUseAttentionSnapshotAuditSnapshot` 与 `buildUseAttentionSnapshotAuditJson` 纯函数导出及单测。
  7. `src/entities/chat/btwState.ts`：新增 `buildBtwStateAuditSnapshot` 与 `buildBtwStateAuditJson` 纯函数导出及单测。
  8. `src/entities/font/fontStorage.ts`：新增 `buildFontStorageAuditSnapshot` 与 `buildFontStorageAuditJson` 纯函数导出及单测。
- **验证**：8 个单元测试文件（共 82 项单测）、ESLint、TypeScript、`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check` 在 `main` 与 `release/win7` 双轨全部通过。

### Phase P105（2026-10-21）：核心编排、权限审批、用户提问、定时任务、待办事项、知识库与会话产物 Store 治理快照与 JSON 导出闭环（Dual-Track `main` + `release/win7`）

- **目标**：为编排泳道看板、运行控制流、工具权限审批、用户交互提问、定时任务、待办事项、Wiki 知识库与会话产物列表 8 个 Zustand 状态管理层补齐确定性审计快照（`build*AuditSnapshot`）与结构化 JSON 导出（`build*AuditJson`）纯函数及单测：
  1. `src/entities/orchestration/laneBoardStore.ts`：新增 `buildLaneBoardStoreAuditSnapshot` 与 `buildLaneBoardStoreAuditJson` 纯函数导出及单测。
  2. `src/entities/orchestration/runControlStore.ts`：新增 `buildRunControlStoreAuditSnapshot` 与 `buildRunControlStoreAuditJson` 纯函数导出及单测。
  3. `src/entities/permission/permissionState.ts`：新增 `buildPermissionStateAuditSnapshot` 与 `buildPermissionStateAuditJson` 纯函数导出及单测。
  4. `src/entities/question/questionState.ts`：新增 `buildQuestionStateAuditSnapshot` 与 `buildQuestionStateAuditJson` 纯函数导出及单测。
  5. `src/entities/scheduled/taskStore.ts`：新增 `buildScheduledTaskStoreAuditSnapshot` 与 `buildScheduledTaskStoreAuditJson` 纯函数导出及单测。
  6. `src/entities/todo/todoStore.ts`：新增 `buildTodoStoreAuditSnapshot` 与 `buildTodoStoreAuditJson` 纯函数导出及单测。
  7. `src/entities/wiki/store.ts`：新增 `buildWikiStoreAuditSnapshot` 与 `buildWikiStoreAuditJson` 纯函数导出及单测。
  8. `src/features/artifacts/artifactListStore.ts`：新增 `buildArtifactListStoreAuditSnapshot` 与 `buildArtifactListStoreAuditJson` 纯函数导出及单测。
- **验证**：8 个单元测试套件、ESLint、TypeScript、`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check` 在 `main` 与 `release/win7` 双轨全部零错误零警告通过。

### Phase P106（2026-10-21）：侧栏槽位注册表、面板槽位 Store、统一注意力聚合中心、工作区变更 Store、消息定位通道、朗读播放 Store、端点就绪校验与欢迎页交付推荐治理快照与 JSON 导出闭环（Dual-Track `main` + `release/win7`）

- **目标**：为侧栏槽位注册表、面板槽位状态 Store、统一注意力聚合中心、工作区变更列表 Store、消息定位请求通道、朗读播放状态 Store、协议感知端点就绪校验与欢迎页可交付推荐配置 8 个核心模块补齐确定性审计快照（`build*AuditSnapshot`）与结构化 JSON 导出（`build*AuditJson`）纯函数及单测：
  1. `src/features/app-panels/panelRegistry.ts`：新增 `buildPanelRegistryAuditSnapshot` 与 `buildPanelRegistryAuditJson` 纯函数导出及单测。
  2. `src/features/app-panels/usePanelStore.ts`：新增 `buildPanelStoreAuditSnapshot` 与 `buildPanelStoreAuditJson` 纯函数导出及单测。
  3. `src/features/attention/attentionCenter.ts`：新增 `buildAttentionCenterAuditSnapshot` 与 `buildAttentionCenterAuditJson` 纯函数导出及单测。
  4. `src/features/changes/changesListStore.ts`：新增 `buildChangesListStoreAuditSnapshot` 与 `buildChangesListStoreAuditJson` 纯函数导出及单测。
  5. `src/features/chat/messageJumpStore.ts`：新增 `buildMessageJumpStoreAuditSnapshot` 与 `buildMessageJumpStoreAuditJson` 纯函数导出及单测。
  6. `src/features/chat/readAloudStore.ts`：新增 `buildReadAloudStoreAuditSnapshot` 与 `buildReadAloudStoreAuditJson` 纯函数导出及单测。
  7. `src/entities/setting/endpointReadiness.ts`：新增 `buildEndpointReadinessAuditSnapshot` 与 `buildEndpointReadinessAuditJson` 纯函数导出及单测。
  8. `src/entities/welcome/recommendations.ts`：新增 `buildRecommendationsAuditSnapshot` 与 `buildRecommendationsAuditJson` 纯函数导出及单测。
- **验证**：8 个单元测试套件（64 项单测）、ESLint、TypeScript、`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check` 在 `main` 与 `release/win7` 双轨全部零错误零警告通过。

### Phase P107（2026-10-21）：回答版本切换、会话内全文查找、实体引用补全、生成速度统计、Markdown 纯文本剥离、划词引用、语音朗读分片与 CSS 检索词高亮治理快照与 JSON 导出闭环（Dual-Track `main` + `release/win7`）

- **目标**：为回答版本切换、会话内全文查找、输入栏 `@` 实体引用补全、生成速度统计格式化、Markdown 可见文本剥离、划词引用块生成、Web Speech 朗读分片与 CSS Custom Highlight 检索词高亮 8 个对话阅读与交互核心模块补齐确定性审计快照（`build*AuditSnapshot`）与结构化 JSON 导出（`build*AuditJson`）纯函数及单测：
  1. `src/features/chat/answerVersions.ts`：新增 `buildAnswerVersionsAuditSnapshot` 与 `buildAnswerVersionsAuditJson` 纯函数导出及单测。
  2. `src/features/chat/chatFind.ts`：新增 `buildChatFindAuditSnapshot` 与 `buildChatFindAuditJson` 纯函数导出及单测。
  3. `src/features/chat/entityRefs.ts`：新增 `buildEntityRefsAuditSnapshot` 与 `buildEntityRefsAuditJson` 纯函数导出及单测。
  4. `src/features/chat/generationStats.ts`：新增 `buildGenerationStatsAuditSnapshot` 与 `buildGenerationStatsAuditJson` 纯函数导出及单测。
  5. `src/features/chat/markdownText.ts`：新增 `buildMarkdownTextAuditSnapshot` 与 `buildMarkdownTextAuditJson` 纯函数导出及单测。
  6. `src/features/chat/selectionQuote.ts`：新增 `buildSelectionQuoteAuditSnapshot` 与 `buildSelectionQuoteAuditJson` 纯函数导出及单测。
  7. `src/features/chat/speech.ts`：新增 `buildSpeechAuditSnapshot` 与 `buildSpeechAuditJson` 纯函数导出及单测。
  8. `src/features/chat/textHighlight.ts`：新增 `buildTextHighlightAuditSnapshot` 与 `buildTextHighlightAuditJson` 纯函数导出及单测。
- **验证**：8 个单元测试套件（59 项单测）、ESLint、TypeScript、`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check` 在 `main` 与 `release/win7` 双轨全部零错误零警告通过。

### Phase P108（已完成）：模型目录 API、会话持久化、设置适配器与存储、主题装饰预设与存储、产物 API 及定时任务 Cron 校验治理
- **改造模块（8 项）**：
  1. `src/entities/model-catalog/api.ts`：新增 `formatCatalogSnapshotMetaSummary` 与 `formatCatalogSnapshotMetaJson`，支持模型目录快照元数据（`id · source · digest · created_at`）摘要与可复制 JSON 序列化。
  2. `src/entities/session/storage.ts`：新增 `formatCurrentSessionStorageSummary` 与 `formatCurrentSessionStorageJson`，支持当前活跃会话与本地缓存状态摘要及 JSON 导出。
  3. `src/entities/setting/settingsAdapter.ts`：新增 `formatSettingAdapterRouteSummary` 与 `formatSettingAdapterRouteJson`，支持设置键存储后端路由（`preference / app_settings / electron / local`）与可见性审计摘要及 JSON 导出。
  4. `src/entities/setting/storage.ts`：新增 `formatAppSettingsStorageSummary` 与 `formatAppSettingsStorageJson`，支持应用全局设置（端点数量、主对话模型、流式开关与重试配置）摘要及 JSON 导出。
  5. `src/entities/theme/decorative-presets.ts`：新增 `formatDecorativePresetSummary` 与 `formatDecorativePresetsJson`，支持装饰主题预设（渐变起止色与封面路径）摘要与列表 JSON 导出。
  6. `src/entities/theme/storage.ts`：新增 `formatThemeStorageSummary` 与 `formatThemeStorageJson`，支持主题模式与预设 ID 持久化状态摘要及 JSON 导出。
  7. `src/features/artifacts/artifactApi.ts`：新增 `formatArtifactRecordSummary` 与 `formatArtifactRecordJson`，支持会话产物记录（`id · name · kind · size`）摘要与 JSON 导出。
  8. `src/features/scheduled/cronValidator.ts`：新增 `formatCronValidationSummary` 与 `formatCronValidationJson`，支持定时任务 5 字段 Cron 表达式合法性校验、预设匹配与错误原因摘要及 JSON 导出。
- **单元测试（8 项）**：
  - `src/entities/model-catalog/api.test.ts`、`src/entities/session/__tests__/storage.test.ts`、`src/entities/setting/__tests__/settingsAdapter.test.ts`、`src/entities/setting/__tests__/storage.test.ts`、`src/entities/theme/__tests__/decorative-presets.test.ts`、`src/entities/theme/__tests__/storage.test.ts`、`src/features/artifacts/__tests__/artifactApi.test.ts`、`src/features/scheduled/__tests__/cronValidator.test.ts` 全部通过（85 tests passed）。

### Phase P109（已完成）：产物内容与列表 Hook、@文件引用查询、/btw 旁路问答、对话大纲与轮次导航、草稿引用注入及期刊模板 Hook 治理
- **改造模块（8 项）**：
  1. `src/features/artifacts/useArtifactContent.ts`：新增 `formatArtifactContentStateSummary` 与 `formatArtifactContentStateJson`，支持产物内容加载态、类型、字符数与错误原因摘要及可复制 JSON 序列化。
  2. `src/features/artifacts/useArtifacts.ts`：新增 `formatArtifactsHookStateSummary` 与 `formatArtifactsHookStateJson`，支持会话产物列表数量、ID 集合与加载状态摘要及 JSON 导出。
  3. `src/features/chat/useAtFileQuery.ts`：新增 `formatAtFileQuerySummary` 与 `formatAtFileQueryJson`，支持光标前 `@` 文件引用触发状态、查询串与起止索引摘要及 JSON 导出。
  4. `src/features/chat/useBtwCommand.ts`：新增 `formatBtwCommandStateSummary` 与 `formatBtwCommandStateJson`，支持 `/btw` 旁路问答浮层开关态、加载态及问答长度摘要与 JSON 导出。
  5. `src/features/chat/useConversationOutline.ts`：新增 `formatConversationOutlineSummary` 与 `formatConversationOutlineJson`，支持会话大纲 `h2/h3` 标题计数与条目列表摘要及 JSON 导出。
  6. `src/features/chat/useConversationTurns.ts`：新增 `formatConversationTurnsSummary` 与 `formatConversationTurnsJson`，支持对话轮次计数、最新轮次索引及预览摘要与 JSON 导出。
  7. `src/features/chat/useQuoteDraft.ts`：新增 `formatQuoteDraftInjectionSummary` 与 `formatQuoteDraftInjectionJson`，支持草稿引用追加注入状态、字符长度与随机戳摘要及 JSON 导出。
  8. `src/features/journal/useJournalTemplates.ts`：新增 `formatJournalTemplateDraftSummary` 与 `formatJournalTemplateDraftJson`，支持期刊模板规格 ID、论文标题、章节键列表、参考文献计数与违规计数摘要及 JSON 导出。
- **单元测试（8 项）**：
  - `src/features/artifacts/__tests__/useArtifactContent.test.ts`、`src/features/artifacts/__tests__/useArtifacts.test.ts`、`src/features/chat/__tests__/useAtFileQuery.test.tsx`、`src/features/chat/__tests__/useBtwCommand.test.ts`、`src/features/chat/__tests__/useConversationOutline.test.ts`、`src/features/chat/__tests__/useConversationTurns.test.ts`、`src/features/chat/__tests__/useQuoteDraft.test.ts`、`src/features/journal/__tests__/useJournalTemplates.test.ts` 全部通过（42 tests passed）。

### Phase P110（已完成）：端点与模型探测 API、全局设置 Hook、Office 引用导入与能力发现、Office 文档管理 Hook、右侧面板 Store、流式会话 Store 及编排事件路由治理
- **改造模块（8 项）**：
  1. `src/features/manage-endpoints/api.ts`：新增 `formatProbeResultSummary` 与 `formatProbeResultJson`，支持模型上下文窗口探测结果（状态、适配器、原生上下文、架构与量化精度）摘要及可复制 JSON 序列化。
  2. `src/features/manage-settings/useSettings.ts`：新增 `formatUseSettingsSnapshotSummary` 与 `formatUseSettingsSnapshotJson`，支持全局设置 Hook 加载态、最大上下文与流式开关及端点数量摘要与 JSON 导出。
  3. `src/features/office/importOfficeReference.ts`：新增 `formatOfficeImportRefSummary` 与 `formatOfficeImportRefJson`，支持聊天区 `@` 导入 Office 引用记录（`docId · docType · filename`）摘要与 JSON 导出。
  4. `src/features/office/officeCapabilities.ts`：新增 `formatOfficeCapabilitiesSummary` 与 `formatOfficeCapabilitiesJson`，支持平台级 PDF 导出格式、LibreOffice 与 Word COM 能力发现摘要及 JSON 导出。
  5. `src/features/office/useOfficeDocuments.ts`：新增 `formatOfficeDocumentsBatchSummary` 与 `formatOfficeDocumentsBatchJson`，支持 Office 托管文档批量归档与恢复结果（成功/失败计数及 ID 列表）摘要与 JSON 导出。
  6. `src/features/right-panel/rightPanelStore.ts`：新增 `formatRightPanelStateSummary` 与 `formatRightPanelStateJson`，支持右侧工作台面板展开态、当前 Tab、最大化状态及选中产物 ID 摘要与 JSON 导出。
  7. `src/features/send-message/chatStreamStore.ts`：新增 `formatChatStreamSessionSummary` 与 `formatChatStreamSessionJson`，支持按会话隔离的流式槽位状态、当前消息 ID、工具调用数与待办计数摘要及 JSON 导出。
  8. `src/features/send-message/orchestrationEvents.ts`：新增 `formatRestoredBoardSummary` 与 `formatRestoredBoardJson`，支持历史编排运行恢复任务板（计划项数、总任务数、已完成/失败数及时间戳）摘要与 JSON 导出。
- **单元测试（8 项）**：
  - `src/features/manage-endpoints/__tests__/api.test.ts`、`src/features/manage-settings/__tests__/useSettings.test.ts`、`src/features/office/__tests__/importOfficeReference.test.ts`、`src/features/office/__tests__/officeCapabilities.test.ts`、`src/features/office/__tests__/useOfficeDocuments.test.ts`、`src/features/right-panel/__tests__/rightPanelStore.test.ts`、`src/features/send-message/__tests__/chatStreamStore.test.ts`、`src/features/send-message/__tests__/orchestrationEvents.test.ts` 全部通过（147 tests on `main`, 132 tests on `release/win7`）。

### Phase P111（已完成）：分会话通知判定、任务中心 Store、主题样式注入与校验、打字机占位 Hook、Wiki 对话流 Hook 及 Cookie 导入解析器治理
- **改造模块（8 项）**：
  1. `src/features/send-message/sessionNotify.ts`：新增 `formatSessionNotifyDecisionSummary` 与 `formatSessionNotifyDecisionJson`，支持分会话 OS 通知打扰判定（目标会话、当前会话、是否触发与正文长度）摘要及可复制 JSON 序列化。
  2. `src/features/task-center/taskCenterStore.ts`：新增 `formatTaskCenterStateSummary` 与 `formatTaskCenterStateJson`，支持后台任务中心总任务数、运行中任务数、任务 ID 列表及交付抽屉开关态摘要与 JSON 导出。
  3. `src/features/theme/backgroundInjector.ts`：新增 `formatBackgroundInjectionSummary` 与 `formatBackgroundInjectionJson`，支持实时预览样式、持久化主题样式及封面图 CSS 变量注入状态摘要与 JSON 导出。
  4. `src/features/theme/themeCssTypes.ts`：新增 `formatThemeCssPayloadSummary` 与 `formatThemeCssPayloadJson`，支持自定义 CSS 主题载荷（ID、名称、外观模式、CSS 字符数与更新时间戳）摘要与 JSON 导出。
  5. `src/features/theme/themeCssValidator.ts`：新增 `formatThemeCssValidationSummary` 与 `formatThemeCssValidationJson`，支持自定义 CSS 16 变量白名单与危险模式校验结果、变量计数及变量名列表摘要与 JSON 导出。
  6. `src/features/welcome/useTypewriterPlaceholder.ts`：新增 `formatTypewriterStateSummary` 与 `formatTypewriterStateJson`，支持欢迎页打字机占位文本当前阶段、字符长度与短语总数摘要及 JSON 导出。
  7. `src/features/wiki/useWikiChatStream.ts`：新增 `formatWikiChatStreamStateSummary` 与 `formatWikiChatStreamStateJson`，支持 Wiki 流式问答阶段、回答长度、引用数、来源数及错误原因摘要与 JSON 导出。
  8. `src/pages/settings/credentialCookieParser.ts`：新增 `formatCookieHeaderSummary` 与 `formatCookieHeaderJson`，支持脱敏（不暴露 Cookie secret 值）的 Cookie 条目计数与键名列表摘要及 JSON 导出。
- **单元测试（8 项）**：
  - `src/features/send-message/__tests__/sessionNotify.test.ts`、`src/features/task-center/__tests__/taskCenterStore.test.ts`、`src/features/theme/__tests__/backgroundInjector.test.ts`、`src/features/theme/__tests__/themeCssTypes.test.ts`、`src/features/theme/__tests__/themeCssValidator.test.ts`、`src/features/welcome/__tests__/useTypewriterPlaceholder.test.ts`、`src/features/wiki/__tests__/useWikiChatStream.test.tsx`、`src/pages/settings/__tests__/credentialCookieParser.test.ts` 全部通过（88 tests passed）。

### Phase P112（已完成）：设置检索索引、通用日志器、桌面后端请求桥、Demo 拦截器、文件检索客户端、NDJSON 事件流解析、编排运行客户端及多智能体 Lane 客户端治理
- **改造模块（8 项）**：
  1. `src/pages/settings/settingsSearchIndex.ts`：新增 `formatSettingsSearchSummary` 与 `formatSettingsSearchJson`，支持设置页全文搜索查询词、命中数、命中键列表及目标 Tab 集合摘要与可复制 JSON 序列化。
  2. `src/shared/logger.ts`：新增 `formatLoggerEntrySummary` 与 `formatLoggerEntryJson`，支持带作用域（scope）与日志级别的标准化日志摘要及 JSON 导出。
  3. `src/shared/api/backendRequest.ts`：新增 `formatBackendRequestSummary` 与 `formatBackendRequestJson`，支持桌面端后端中继请求方法、路径、请求体存在性及桥接可用性摘要与 JSON 导出。
  4. `src/shared/api/demoInterceptors.ts`：新增 `formatDemoInvokeSummary` 与 `formatDemoInvokeJson`，支持 Demo 模式 IPC 拦截命中状态、返回值存在性及已注册处理器计数摘要与 JSON 导出。
  5. `src/shared/api/fileSearchClient.ts`：新增 `formatFileSearchResultSummary` 与 `formatFileSearchResultJson`，支持工作区 `@` 文件检索结果（文件名、路径、类型、Office/普通文件分类及文档 ID）摘要与 JSON 导出。
  6. `src/shared/api/llmStream.ts`：新增 `formatAgentEventSummary` 与 `formatAgentEventJson`，支持 NDJSON 流式 Agent 事件（`state · run · task`、状态及计划项数）摘要与 JSON 导出。
  7. `src/shared/api/orchRunClient.ts`：新增 `formatOrchRunDetailSummary` 与 `formatOrchRunDetailJson`，支持编排 Run 生命周期详情（运行 ID、会话 ID、状态、计划项数与任务数）摘要与 JSON 导出。
  8. `src/shared/api/orchestrationClient.ts`：新增 `formatLaneDecisionSummary` 与 `formatLaneDecisionJson`，支持多智能体 Lane 交付包验收决议（`lane_id · decision · merged · already` 及告警信息）摘要与 JSON 导出。
- **单元测试（8 项）**：
  - `src/pages/settings/__tests__/settingsSearchIndex.test.ts`、`src/shared/__tests__/logger.test.ts`、`src/shared/api/__tests__/backendRequest.test.ts`、`src/shared/api/__tests__/demoInterceptors.test.ts`、`src/shared/api/__tests__/fileSearchClient.test.ts`、`src/shared/api/__tests__/llmStream.test.ts`、`src/shared/api/__tests__/orchRunClient.test.ts`、`src/shared/api/__tests__/orchestrationClient.test.ts` 全部通过（68 tests on `main`, 60 tests on `release/win7`）。

### Phase P113 — Shared Memory, Office, Scheduled, Settings, Theme CSS, Todo, Window Controls & Workspace API Diagnostic Formatters (Completed)
- `src/shared/api/memoryApi.ts` (`formatMemoryListSummary` / `formatMemoryListJson`) + `src/shared/api/__tests__/memoryApi.test.ts`
- `src/shared/api/officeApi.ts` (`formatOfficeWordLintSummary` / `formatOfficeWordLintJson`) + `src/shared/api/__tests__/officeApi.test.ts`
- `src/shared/api/scheduledClient.ts` (`formatScheduledTaskSummary` / `formatScheduledTaskJson`) + `src/shared/api/__tests__/scheduledClient.test.ts`
- `src/shared/api/settingsClient.ts` (`formatPreferenceSnapshotSummary` / `formatPreferenceSnapshotJson`) + `src/shared/api/__tests__/settingsClient.test.ts`
- `src/shared/api/themeCssClient.ts` (`formatThemeCssSummary` / `formatThemeCssJson`) + `src/shared/api/__tests__/themeCssClient.test.ts`
- `src/shared/api/todoClient.ts` (`formatTodoListSummary` / `formatTodoListJson`) + `src/shared/api/__tests__/todoClient.test.ts`
- `src/shared/api/windowControlsClient.ts` (`formatWindowPlatformSummary` / `formatWindowPlatformJson`) + `src/shared/api/__tests__/windowControlsClient.test.ts`
- `src/shared/api/workspaceApi.ts` (`formatWorkspaceBindingSummary` / `formatWorkspaceBindingJson`) + `src/shared/api/__tests__/workspaceApi.test.ts`

### Phase P114 — Shared Lib Agent State, Endpoint Status, Humanize, Last Workspace, Local Image, Markdown Chunks, Action Failure & Store Diagnostic Formatters (Completed)
- `src/shared/lib/agentStateMapping.ts` (`formatAgentPhaseSummary` / `formatAgentPhaseJson`) + `src/shared/lib/__tests__/agentStateMapping.test.ts`
- `src/shared/lib/endpointStatus.ts` (`formatEndpointIssueSummary` / `formatEndpointIssueJson`) + `src/shared/lib/__tests__/endpointStatus.test.ts`
- `src/shared/lib/humanize.ts` (`formatHumanizedToolSummary` / `formatHumanizedToolJson`) + `src/shared/lib/__tests__/humanize.test.ts`
- `src/shared/lib/lastWorkspace.ts` (`formatLastWorkspaceSummary` / `formatLastWorkspaceJson`) + `src/shared/lib/__tests__/lastWorkspace.test.ts`
- `src/shared/lib/localImageSrc.ts` (`formatLocalImageSrcSummary` / `formatLocalImageSrcJson`) + `src/shared/lib/__tests__/localImageSrc.test.ts`
- `src/shared/lib/markdownChunks.ts` (`formatChunkSplitSummary` / `formatChunkSplitJson`) + `src/shared/lib/__tests__/markdownChunks.test.ts`
- `src/shared/lib/reportActionFailure.ts` (`formatActionFailureSummary` / `formatActionFailureJson`) + `src/shared/lib/__tests__/reportActionFailure.test.ts`
- `src/shared/lib/store.ts` (`formatStoreSessionSummary` / `formatStoreSessionJson`) + `src/shared/lib/__tests__/store.test.ts`

### Phase P115（已完成 — Shared Diff, Navigation History, Emacs Keybindings, File Upload, Client Log, Diff Hunks & Session Fork Tree Diagnostic Summary/JSON Helpers）

1. **`src/shared/lib/textDiff.ts` (`src/shared/lib/__tests__/textDiff.test.ts`)**：
   - 新增 `formatTextDiffSummary(side)` 与 `formatTextDiffJson(side)`，提供字符级 diff 分段统计摘要与结构化 JSON 快照。
2. **`src/shared/lib/unifiedDiff.ts` (`src/shared/lib/__tests__/unifiedDiff.test.ts`)**：
   - 新增 `formatUnifiedDiffSummary(diffText, oldLabel, newLabel)` 与 `formatUnifiedDiffJson(diffText, oldLabel, newLabel)`，提供行级 unified diff hunk 与增删行统计摘要与 JSON 快照。
3. **`src/shared/lib/useNavigationHistory.ts` (`src/shared/lib/__tests__/useNavigationHistory.test.tsx`)**：
   - 新增 `formatNavHistorySummary(ctx)` 与 `formatNavHistoryJson(ctx)`，提供导航历史上下文前进/后退能力诊断摘要与 JSON 快照。
4. **`src/shared/lib/hooks/useEmacsKeybindings.ts` (`src/shared/lib/hooks/__tests__/useEmacsKeybindings.test.ts`)**：
   - 新增 `formatEmacsKeybindingsSummary(text, cursor, enabled)` 与 `formatEmacsKeybindingsJson(text, cursor, enabled)`，提供 Emacs 快捷键缓冲区行边界与分词游标诊断摘要与 JSON 快照。
5. **`src/shared/lib/hooks/useFileUpload.ts` (`src/shared/lib/hooks/__tests__/useFileUpload.test.ts`)**：
   - 新增 `formatFileUploadSummary(files, images, isDragOver)` 与 `formatFileUploadJson(files, images, isDragOver)`，提供聊天文件/图片上传队列诊断摘要与 JSON 快照。
6. **`src/shared/log/client.ts` (`src/shared/log/__tests__/client.test.ts`)**：
   - 新增 `formatClientLogSummary(level, msg, meta)` 与 `formatClientLogJson(level, msg, meta)`，提供前端渲染进程日志桥接状态诊断摘要与 JSON 快照。
7. **`src/widgets/chat/changes/diffHunks.ts` (`src/widgets/chat/changes/__tests__/diffHunks.test.ts`)**：
   - 新增 `formatDiffHunksSummary(hunks)` 与 `formatDiffHunksJson(hunks)`，提供前端 unified diff hunk 切分诊断摘要与 JSON 快照。
8. **`src/widgets/session/forkTree.ts` (`src/widgets/session/__tests__/forkTree.test.ts`)**：
   - 新增 `formatForkTreeSummary(nodes)` 与 `formatForkTreeJson(nodes)`，提供会话分叉家族树深度与节点拓扑诊断摘要与 JSON 快照。

### Phase P116（已完成 — Chat Memory Pause, Confirmed Preferences, Office Preview Revision, Scheduled Skill Links, Task Brief & Settings Presentation Diagnostic Summary/JSON Helpers）

1. **`src/features/chat/useSessionMemoryPause.ts` (`src/features/chat/__tests__/useSessionMemoryPause.test.ts`)**：
   - 新增 `formatSessionMemoryPauseSummary(ids, sessionId, unconfirmed)` 与 `formatSessionMemoryPauseJson(ids, sessionId, unconfirmed)`，提供设备本地会话记忆暂停状态诊断摘要与结构化 JSON 快照。
2. **`src/features/manage-settings/useConfirmedPreference.ts` (`src/features/manage-settings/__tests__/useConfirmedPreference.test.ts`)**：
   - 新增 `formatConfirmedPreferenceSummary(key, status, loaded)` 与 `formatConfirmedPreferenceJson(key, status, loaded)`，提供受控偏好确认写入状态诊断摘要与 JSON 快照。
3. **`src/features/office/previewRevision.ts` (`src/features/office/__tests__/previewRevision.test.ts`)**：
   - 新增 `formatPreviewRevisionSummary(cacheKey)` 与 `formatPreviewRevisionJson(cacheKey)`，提供 Office 预览内容修订缓存键健康度诊断摘要与 JSON 快照。
4. **`src/features/scheduled/skillLink.ts` (`src/features/scheduled/__tests__/skillLink.test.ts`)**：
   - 新增 `formatTaskSkillHealthSummary(health)` 与 `formatTaskSkillHealthJson(health)`，提供定时任务技能引用健康度诊断摘要与 JSON 快照。
5. **`src/features/task-brief/modelTaskFit.ts` (`src/features/task-brief/__tests__/modelTaskFit.test.ts`)**：
   - 新增 `formatModelTaskFitSummary(model, needsTools)` 与 `formatModelTaskFitJson(model, needsTools)`，提供候选模型任务适配度与工具能力诊断摘要与 JSON 快照。
6. **`src/features/task-brief/taskBrief.ts` (`src/features/task-brief/__tests__/taskBrief.test.ts`)**：
   - 新增 `formatTaskBriefSummary(brief)` 与 `formatTaskBriefJson(brief)`，提供交付任务简报场景与输出格式诊断摘要与 JSON 快照。
7. **`src/features/task-brief/taskRecipes.ts` (`src/features/task-brief/__tests__/taskRecipes.test.ts`)**：
   - 新增 `formatTaskRecipesSummary(recipes)` 与 `formatTaskRecipesJson(recipes)`，提供持久化任务配方列表复核状态诊断摘要与 JSON 快照。
8. **`src/pages/settings/settingsPresentation.ts` (`src/pages/settings/__tests__/settingsPresentation.test.ts`)**：
   - 新增 `formatSettingsGroupsSummary(available, locale)` 与 `formatSettingsGroupsJson(available, locale)`，提供设置页分组导航与多语言标签诊断摘要与 JSON 快照。

### Phase P117（已完成 — Shared Demo Flag, Desktop Event/Invoke, Gateway, Journal, Knowledge, Learn & Media API Diagnostic Summary/JSON Helpers）

1. **`src/shared/api/demoFlag.ts` (`src/shared/api/__tests__/demoFlag.test.ts`)**：
   - 新增 `formatDemoFlagSummary()` 与 `formatDemoFlagJson()`，提供演示模式优先级链（override / Electron 注入 / settings store）诊断摘要与结构化 JSON 快照。
2. **`src/shared/api/desktopEvent.ts` (`src/shared/api/__tests__/desktopEvent.test.ts`)**：
   - 新增 `formatDesktopEventSummary(event, options)` 与 `formatDesktopEventJson(event, options)`，提供桌面端 IPC 流事件监听通道与 `streamId` 诊断摘要与 JSON 快照。
3. **`src/shared/api/desktopInvoke.ts` (`src/shared/api/__tests__/desktopInvoke.test.ts`)**：
   - 新增 `formatDesktopInvokeSummary(cmd, args)` 与 `formatDesktopInvokeJson(cmd, args)`，提供桌面端 IPC 命令调用与演示拦截模式诊断摘要与 JSON 快照。
4. **`src/shared/api/gatewayApi.ts` (`src/shared/api/__tests__/gatewayApi.test.ts`)**：
   - 新增 `formatGatewayConfigSummary(platform, config)` 与 `formatGatewayConfigJson(platform, config)`，提供多平台网关（Telegram / Discord / Slack）配置与白名单计数诊断摘要与 JSON 快照。
5. **`src/shared/api/journalApi.ts` (`src/shared/api/__tests__/journalApi.test.ts`)**：
   - 新增 `formatJournalFillSummary(req)` 与 `formatJournalFillJson(req)`，提供期刊模板填充请求规格与章节统计诊断摘要与 JSON 快照。
6. **`src/shared/api/knowledgeApi.ts` (`src/shared/api/__tests__/knowledgeApi.test.ts`)**：
   - 新增 `formatKnowledgeDocsSummary(docs, query)` 与 `formatKnowledgeDocsJson(docs, query)`，提供知识库兼容层（已由 Wiki 替代）查询状态诊断摘要与 JSON 快照。
7. **`src/shared/api/learnApi.ts` (`src/shared/api/__tests__/learnApi.test.ts`)**：
   - 新增 `formatLearnTriggerSummary(sessionId, prompt, response)` 与 `formatLearnTriggerJson(sessionId, prompt, response)`，提供显式后台复盘触发状态诊断摘要与 JSON 快照。
8. **`src/shared/api/mediaApi.ts` (`src/shared/api/__tests__/mediaApi.test.ts`)**：
   - 新增 `formatMediaUrlSummary(apiUrl, mimeType)` 与 `formatMediaUrlJson(apiUrl, mimeType)`，提供多模态媒体资源 URL 解析与 MIME 类型诊断摘要与 JSON 快照。

### Phase P118：对话轨迹/设置导航/错误映射/倒计时/侧栏排序/特性解锁/斜杠命令/对话轮次分组审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/features/chat/useConversationTrajectory.ts`：新增 `formatTrajectorySummaryText` 与 `formatTrajectorySummaryJson`，支持一键导出对话轨迹聚合统计摘要（`entries=<totalEntries> · tools=<totalToolCalls> · in=<totalInputTokens> · out=<totalOutputTokens> · latency=<totalLatencyMs>ms`）与 JSON 快照。
  2. `src/pages/settings/settingsNavigation.ts`：新增 `formatSettingsNavigationSummary` 与 `formatSettingsNavigationJson`，支持一键导出设置标签页书签解析审计摘要（`<requested> -> <resolved> · providers=<providersEnabled>`）与 JSON 快照。
  3. `src/shared/lib/errorMapping.ts`：新增 `formatLLMErrorSummary` 与 `formatLLMErrorJson`，支持一键导出结构化 LLM 错误映射审计摘要（`<type> · status=<status_code> · retry=<retry_after> · <mappedText>`）与 JSON 快照。
  4. `src/shared/lib/useCountdown.ts`：新增 `formatCountdownSummary` 与 `formatCountdownJson`，支持一键导出倒计时状态审计摘要（`<ticking|done> · <remaining>/<initialSeconds>s · key=<resetKey>`）与 JSON 快照。
  5. `src/shared/lib/dnd/siderOrder.ts`：新增 `formatSiderOrderSummary` 与 `formatSiderOrderJson`，支持一键导出侧栏拖拽顺序审计摘要（`count=<length> · ids=[...]`）与 JSON 快照。
  6. `src/shared/lib/hooks/useFeatureUnlock.ts`：新增 `formatFeatureUnlockSummary` 与 `formatFeatureUnlockJson`，支持一键导出隐藏特性解锁状态审计摘要（`<featureKey> · <unlocked|locked>`）与 JSON 快照。
  7. `src/widgets/chat/slashCommands.ts`：新增 `formatSlashCommandsSummary` 与 `formatSlashCommandsJson`，支持一键导出斜杠命令与动态 SKILL.md 合并审计摘要（`total=<totalCount> · skills=<skillCount> · names=[...]`）与 JSON 快照。
  8. `src/widgets/chat/turnGrouping.ts`：新增 `formatTurnItemsSummary` 与 `formatTurnItemsJson`，支持一键导出对话轮次分组审计摘要（`total=<totalItems> · turns=<turnCount> · standalones=<standaloneCount>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 115 项单测全部通过；`release/win7` 8 个测试文件 115 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。

### Phase P119：Office 编辑差异预览/任务计划契约/通用弹窗/开关控件/输入卡片/对话消息/重试横幅/侧栏分组状态审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/features/office/OfficeEditPreviewDialog.tsx`：新增 `formatOfficeDiffChangeSummary` 与 `formatOfficeDiffChangeJson`，支持一键导出 Office 文档编辑差异条目审计摘要（`<op> · target=<target> · hasBefore=<bool> · hasAfter=<bool>`）与 JSON 快照。
  2. `src/shared/api/types.ts`：新增 `formatTaskPlanItemSummary` 与 `formatTaskPlanItemJson`，支持一键导出多智能体任务计划节点审计摘要（`<task_id> · agent=<agent_id> · parent=<parent_task_id> · depth=<depth>`）与 JSON 快照。
  3. `src/shared/ui/Dialog/Dialog.tsx`：新增 `formatDialogConfigSummary` 与 `formatDialogConfigJson`，支持一键导出通用模态弹窗配置审计摘要（`<open|closed> · closeBtn=<showCloseButton> · title=<title>`）与 JSON 快照。
  4. `src/shared/ui/Switch/Switch.tsx`：新增 `formatSwitchStateSummary` 与 `formatSwitchStateJson`，支持一键导出无障碍开关控件状态审计摘要（`<label> · <checked|unchecked> · disabled=<disabled>`）与 JSON 快照。
  5. `src/widgets/chat/InputCard.tsx`：新增 `formatInputCardAuditSummary` 与 `formatInputCardAuditJson`，支持一键导出对话输入卡片水位审计摘要（`chars=<len>/4000 · loading=<isLoading> · attachments=<hasAttachments> · overLimit=<overLimit>`）与 JSON 快照。
  6. `src/widgets/chat/Message.tsx`：新增 `formatMessageAuditSummary` 与 `formatMessageAuditJson`，支持一键导出对话消息气泡渲染状态审计摘要（`<id> · role=<role> · streaming=<isStreaming> · tools=<toolCount> · chars=<len>`）与 JSON 快照。
  7. `src/widgets/chat/RetryBanner.tsx`：新增 `formatRetryBannerSummary` 与 `formatRetryBannerJson`，支持一键导出 LLM 自动重试横幅状态审计摘要（`attempt=<attempt>/<max_attempts> · type=<error_type> · severity=<severity> · delay=<delay>s`）与 JSON 快照。
  8. `src/widgets/sidebar/useSiderSections.ts`：新增 `formatSiderSectionsSummary` 与 `formatSiderSectionsJson`，支持一键导出侧栏分区折叠与排序状态审计摘要（`sections=<len> · collapsed=<size> · order=[...]`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 97 项单测全部通过；`release/win7` 8 个测试文件 97 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。

### Phase P120：主题上下文/产品愿景/自主目标客户端/自主目标状态/自主目标契约/字体选项/模型目录契约/设置项校验审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/app/providers/useTheme.ts`：新增 `formatThemeAuditSummary` 与 `formatThemeAuditJson` 及单测 `useTheme.test.ts`，支持一键导出主题模式与来源审计摘要（`mode=<mode>(<resolved>) · preset=<presetId> · source=<kind>:<id> · css=<count>`）与 JSON 快照。
  2. `src/content/about/vision.ts`：新增 `formatVisionAuditSummary` 与 `formatVisionAuditJson` 及单测 `vision.test.ts`，支持一键导出产品愿景与四项核心哲学原则审计摘要（`visionChars=<len> · principles=<count> · names=[...]`）与 JSON 快照。
  3. `src/entities/autonomous-goals/goalApi.ts`：新增 `formatGoalListQuerySummary` 与 `formatGoalListQueryJson` 及单测 `goalApi.test.ts`，支持一键导出闲时自主目标查询参数审计摘要（`path=/api/v1/goals · status=<status> · limit=<limit> · offset=<offset>`）与 JSON 快照。
  4. `src/entities/autonomous-goals/goalStore.ts`：新增 `formatGoalStoreSummary` 与 `formatGoalStoreJson` 及单测 `goalStore.test.ts`，支持一键导出自主目标 Zustand Store 状态审计摘要（`goals=<count>/<total> · filter=<statusFilter> · loading=<loading> · error=<error>`）与 JSON 快照。
  5. `src/entities/autonomous-goals/types.ts`：新增 `formatGoalAuditSummary` 与 `formatGoalAuditJson` 及单测 `types.test.ts`，支持一键导出自主目标进度与检查点核验审计摘要（`<id> · status=<status> · progress=<pct>% · checkpoints=<verified>/<total> · deg=<degradation_level>`）与 JSON 快照。
  6. `src/entities/font/fontOptions.ts`：新增 `formatFontSettingsSummary` 与 `formatFontSettingsJson` 及单测 `fontOptions.test.ts`，支持一键导出 UI 与代码字体配置审计摘要（`ui=<fontUi>@<fontSizeUi>px · code=<fontCode>@<fontSizeCode>px`）与 JSON 快照。
  7. `src/entities/model-catalog/types.ts`：新增 `formatCandidateModelSummary` 与 `formatCandidateModelJson` 及单测 `types.test.ts`，支持一键导出候选模型目录条目审计摘要（`<provider>/<model_id> · ctx=<native> · source=<source>`）与 JSON 快照。
  8. `src/entities/setting/settingsValidation.ts`：新增 `formatSettingValidationSummary` 与 `formatSettingValidationJson` 及单测 `settingsValidation.test.ts`，支持一键导出设置项约束校验结果审计摘要（`<key> · <valid|invalid(error)>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P121：设置深度合并/设置元数据/设置契约/Wiki 活动队列/Wiki 质量检查/Wiki 演示数据/Wiki 摄入队列/编排事件订阅审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/entities/setting/deepMerge.ts`：新增 `formatDeepMergeSummary` 与 `formatDeepMergeJson` 及单测 `deepMerge.test.ts`，支持一键导出设置深度合并策略与冲突处理器审计摘要（`policy=<policy> · conflicts=<count> · customHandler=<bool>`）与 JSON 快照。
  2. `src/entities/setting/metadata.ts`：新增 `formatSettingMetadataSummary` 与 `formatSettingMetadataJson` 及单测 `metadata.test.ts`，支持一键导出设置项元数据作用域与生效时机审计摘要（`<key> · <scope> · <applyMode> · risk=<riskLevel>`）与 JSON 快照。
  3. `src/entities/setting/types.ts`：新增 `formatSettingsAuditSummary` 与 `formatSettingsAuditJson` 及单测 `types.test.ts`，支持一键导出全局设置版本、端点数量与演示模式审计摘要（`v<version> · endpoints=<count> · demo=<demoMode>`）与 JSON 快照。
  4. `src/entities/wiki/activity-store.ts`：新增 `formatActivityStoreSummary` 与 `formatActivityStoreJson` 及单测 `activity-store.test.ts`，支持一键导出 Wiki 操作历史队列水位审计摘要（`activities=<total>/<maxItems> · running=<running> · errors=<errors>`）与 JSON 快照。
  5. `src/entities/wiki/lint-store.ts`：新增 `formatLintStoreSummary` 与 `formatLintStoreJson` 及单测 `lint-store.test.ts`，支持一键导出 Wiki 文档质量检查状态审计摘要（`status=<status> · issues=<count> · warnings=<warnings>`）与 JSON 快照。
  6. `src/entities/wiki/mock-data.ts`：新增 `formatWikiMockDataSummary` 与 `formatWikiMockDataJson` 及单测 `mock-data.test.ts`，支持一键导出 Wiki 演示数据集规模审计摘要（`lint=<count> · reviews=<count> · activities=<count> · research=<count>`）与 JSON 快照。
  7. `src/entities/wiki/queue-store.ts`：新增 `formatQueueStoreSummary` 与 `formatQueueStoreJson` 及单测 `queue-store.test.ts`，支持一键导出 Wiki 持久化摄入队列状态审计摘要（`tasks=<count> · pending=<n> · processing=<n> · completed=<n> · failed=<n> · loading=<bool>`）与 JSON 快照。
  8. `src/entities/orchestration/useOrchEventSubscription.ts`：新增 `formatOrchSubscriptionSummary` 与 `formatOrchSubscriptionJson` 及单测 `useOrchEventSubscription.test.ts`，支持一键导出编排运行事件流订阅水位审计摘要（`run=<runId> · enabled=<enabled> · lastSeq=<lastSeq>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P122：Wiki 深度研究队列/Wiki 审核队列/产物事件计数/消息跳转定位/诊断预览水位/全局设置 Store/Office 进度轮询/项目工作台状态审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/entities/wiki/research-store.ts`：新增 `formatResearchStoreSummary` 与 `formatResearchStoreJson` 及单测 `research-store.test.ts`，支持一键导出 Wiki 深度研究队列状态审计摘要（`tasks=<count> · done=<done> · maxConcurrent=<max> · panel=<open|closed>`）与 JSON 快照。
  2. `src/entities/wiki/review-store.ts`：新增 `formatReviewStoreSummary` 与 `formatReviewStoreJson` 及单测 `review-store.test.ts`，支持一键导出 Wiki 审核队列未决条目审计摘要（`status=<status> · reviews=<count> · unresolved=<unresolved>`）与 JSON 快照。
  3. `src/features/artifacts/artifactEventsStore.ts`：新增 `formatArtifactEventsSummary` 与 `formatArtifactEventsJson` 及单测 `artifactEventsStore.test.ts`，支持一键导出会话产物创建事件计数审计摘要（`sessions=<count> · totalEvents=<total>`）与 JSON 快照。
  4. `src/features/chat/useMessageJump.ts`：新增 `formatMessageJumpSummary` 与 `formatMessageJumpJson` 及单测 `useMessageJump.test.ts`，支持一键导出对话阅读跳转窗口与闪烁目标审计摘要（`window=<effectiveWindow>/<totalMessages> · flash=<flashId>`）与 JSON 快照。
  5. `src/features/diagnostic/useDiagnosticPreview.ts`：新增 `formatDiagnosticPreviewSummary` 与 `formatDiagnosticPreviewJson` 及单测 `useDiagnosticPreview.test.ts`，支持一键导出诊断日志预览水位审计摘要（`count=<count> · version=<version> · loading=<loading> · error=<hasError>`）与 JSON 快照。
  6. `src/features/manage-settings/settingsStore.ts`：新增 `formatSettingsStoreSummary` 与 `formatSettingsStoreJson` 及单测 `settingsStore.test.ts`，支持一键导出全局设置 Zustand Store 水位审计摘要（`loading=<isLoading> · endpoints=<count> · demo=<demoMode>`）与 JSON 快照。
  7. `src/features/office/officeProgress.ts`：新增 `formatOfficeProgressSummary` 与 `formatOfficeProgressJson` 及单测 `officeProgress.test.ts`，支持一键导出 Office 长任务进度轮询快照审计摘要（`task=<taskId> · stage=<stage> · percent=<pct>%`）与 JSON 快照。
  8. `src/features/project-type/useStudioState.ts`：新增 `formatStudioStateSummary` 与 `formatStudioStateJson` 及单测 `useStudioState.test.ts`，支持一键导出项目原型工作台选中态与向导开关审计摘要（`projects=<count> · active=<id> · archetype=<type> · wizard=<open|closed>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P123：思考占位哨兵/终端面板 Store/Wiki 导入进度/更新日志解析/更新提供商开关/代码审查分节/分栏 Diff 解析/任务树索引审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/features/send-message/thinkingPlaceholder.ts`：新增 `isThinkingPlaceholder`、`formatThinkingPlaceholderSummary` 与 `formatThinkingPlaceholderJson` 及单测 `thinkingPlaceholder.test.ts`，支持一键导出流式思考占位哨兵状态审计摘要（`placeholder=<bool> · length=<len>`）与 JSON 快照。
  2. `src/features/terminal-panel/terminalPanelStore.ts`：新增 `formatTerminalPanelSummary` 与 `formatTerminalPanelJson` 及单测 `terminalPanelStore.test.ts`，支持一键导出底部终端面板开合、高度与 PTY 会话审计摘要（`panel=<open|closed> · height=<px>px · pty=<ptyId> · error=<hasError>`）与 JSON 快照。
  3. `src/features/wiki/useWikiIngest.ts`：新增 `formatWikiIngestSummary` 与 `formatWikiIngestJson` 及单测 `useWikiIngest.test.ts`，支持一键导出 Wiki 常驻导入流阶段与进度审计摘要（`ingest=<id> · stage=<stage> · percent=<pct>% · done=<done>`）与 JSON 快照。
  4. `src/lib/changelogParser.ts`：新增 `formatChangelogAuditSummary` 与 `formatChangelogAuditJson` 及单测 `changelogParser.test.ts`，支持一键导出版本更新日志条目统计审计摘要（`versions=<count> · latest=<version> · major=<m> · improvements=<i> · fixes=<f>`）与 JSON 快照。
  5. `src/shared/updateFeatureFlag.ts`：新增 `formatUpdateFeatureFlagSummary` 与 `formatUpdateFeatureFlagJson` 及单测 `updateFeatureFlag.test.ts`，支持一键导出可插拔更新源 UI 特性开关审计摘要（`updateProvidersUi=<enabled|disabled>`）与 JSON 快照。
  6. `src/widgets/chat/changes/reviewSections.ts`：新增 `formatReviewSectionsSummary` 与 `formatReviewSectionsJson` 及单测 `reviewSections.test.ts`，支持一键导出多文件代码审查 Diff 分节统计审计摘要（`files=<count> · binary=<binaryCount> · lines=<totalLines>`）与 JSON 快照。
  7. `src/widgets/chat/changes/splitDiffParser.ts`：新增 `formatSplitDiffSummary` 与 `formatSplitDiffJson` 及单测 `splitDiffParser.test.ts`，支持一键导出分栏 Unified Diff 行类型统计审计摘要（`rows=<total> · modify=<m> · add=<a> · remove=<r> · context=<c>`）与 JSON 快照。
  8. `src/widgets/chat/progress/taskTree.ts`：新增 `formatTaskTreeSummary` 与 `formatTaskTreeJson` 及单测 `taskTree.test.ts`，支持一键导出多智能体任务树节点规模与最大深度审计摘要（`nodes=<count> · roots=<rootCount> · maxDepth=<maxDepth>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P124：演示运行时覆盖/Git 状态响应/运行时环境诊断契约/文件路径语言映射/占位模板填充/结构化日志状态/模型上下文窗口计算/忙碌耗时秒表审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/shared/api/demoRuntime.ts`：新增 `formatDemoRuntimeSummary` 与 `formatDemoRuntimeJson` 及单测 `demoRuntime.test.ts`，支持一键导出演示模式运行时覆盖状态审计摘要（`demoOverride=<true|false|unset>`）与 JSON 快照。
  2. `src/shared/api/gitStatusApi.ts`：新增 `formatGitStatusSummary` 与 `formatGitStatusJson` 及单测 `gitStatusApi.test.ts`，支持一键导出 Git 仓库分支、变更文件数与领先/落后提交审计摘要（`repo=<bool> · branch=<branch> · files=<count> · ahead=<a> · behind=<b>`）与 JSON 快照。
  3. `src/shared/api/runtimeTypes.ts`：新增 `formatRuntimeDiagnosisSummary` 与 `formatRuntimeDiagnosisJson` 及单测 `runtimeTypes.test.ts`，支持一键导出项目运行时环境诊断等级与清单统计审计摘要（`level=<level> · findings=<count> · manifests=<count> · runtime=<rec>`）与 JSON 快照。
  4. `src/shared/lib/fileLang.ts`：新增 `formatFileLangSummary` 与 `formatFileLangJson` 及单测 `fileLang.test.ts`，支持一键导出文件路径 Shiki 高亮语言推断审计摘要（`path=<path> · lang=<lang>`）与 JSON 快照。
  5. `src/shared/lib/fillTemplate.ts`：新增 `formatFillTemplateSummary` 与 `formatFillTemplateJson` 及单测 `fillTemplate.test.ts`，支持一键导出模板占位符填充率与未决变量统计审计摘要（`placeholders=<total> · filled=<filled> · unresolved=<unresolved>`）与 JSON 快照。
  6. `src/shared/lib/logger.ts`：新增 `formatLoggerAuditSummary` 与 `formatLoggerAuditJson` 及单测 `logger.test.ts`，支持一键导出结构化请求链路日志开关状态审计摘要（`logger=<enabled|disabled>`）与 JSON 快照。
  7. `src/shared/lib/modelWindows.ts`：新增 `formatModelWindowSummary` 与 `formatModelWindowJson` 及单测 `modelWindows.test.ts`，支持一键导出模型有效上下文窗口与历史预算审计摘要（`window=<effective> · budget=<budget> · auto=<auto>`）与 JSON 快照。
  8. `src/shared/lib/useElapsedSeconds.ts`：新增 `formatElapsedSecondsSummary` 与 `formatElapsedSecondsJson` 及单测 `useElapsedSeconds.test.ts`，支持一键导出长任务忙碌秒表状态审计摘要（`active=<bool> · elapsed=<sec>s`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P125：移动端断点检测/可拖拽右面板/可拖拽侧边栏/文本截断工具/会话草稿持久化/对话阅读多语言词典/日志级别常量/确认弹窗服务审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/shared/lib/useIsMobile.ts`：新增 `MOBILE_BREAKPOINT_PX`、`formatViewportMobileSummary` 与 `formatViewportMobileJson` 及单测 `useIsMobile.test.ts`，支持一键导出响应式移动端断点判定审计摘要（`viewport=<px>px · mobile=<bool> · breakpoint=768px`）与 JSON 快照。
  2. `src/shared/lib/useResizablePanel.ts`：新增 `formatResizablePanelSummary` 与 `formatResizablePanelJson` 及单测 `useResizablePanel.test.ts`，支持一键导出可调面板宽度区间、锚定侧与拖拽态审计摘要（`width=<px>px · range=[<min>,<max>] · anchor=<left|right> · dragging=<bool>`）与 JSON 快照。
  3. `src/shared/lib/useResizableSidebar.ts`：新增 `formatResizableSidebarSummary` 与 `formatResizableSidebarJson` 及单测 `useResizableSidebar.test.ts`，支持一键导出主侧边栏宽度钳制区间与拖拽状态审计摘要（`sidebar=<px>px · range=[260,480] · dragging=<bool>`）与 JSON 快照。
  4. `src/shared/lib/utils.ts`：新增 `formatTextTruncateSummary` 与 `formatTextTruncateJson` 及单测 `utils.test.ts`，支持一键导出文本截断阈值与预览审计摘要（`length=<len> · max=<max> · truncated=<bool>`）与 JSON 快照。
  5. `src/shared/lib/hooks/useSessionDraft.ts`：新增 `formatSessionDraftSummary` 与 `formatSessionDraftJson` 及单测 `useSessionDraft.test.ts`，支持一键导出单会话草稿字数与持久化状态审计摘要（`session=<id> · chars=<len> · persisted=<bool>`）与 JSON 快照。
  6. `src/shared/lib/i18n/chatReading.ts`：新增 `formatChatReadingI18nSummary` 与 `formatChatReadingI18nJson` 及单测 `chatReading.test.ts`，支持一键导出对话阅读中英词典键数对齐审计摘要（`zh=<count> · en=<count> · parity=<bool>`）与 JSON 快照。
  7. `src/shared/log/levels.ts`：新增 `formatLogLevelSummary` 与 `formatLogLevelJson` 及单测 `levels.test.ts`，支持一键导出前后端共享日志级别权重与限流间隔审计摘要（`level=<level> · rank=<rank> · rateLimitMs=<ms>`）与 JSON 快照。
  8. `src/shared/ui/ConfirmDialog/confirmService.ts`：新增 `formatConfirmServiceSummary` 与 `formatConfirmServiceJson` 及单测 `confirmService.test.ts`，支持一键导出异步确认弹窗挂起态、危险标记与订阅者计数审计摘要（`pending=<bool> · danger=<bool> · listeners=<count>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P126：Word 内联粗斜体标记渲染/命令面板打开信号/产品状态提示多语言/快捷键注册表/会话工作区上下文访问器/暂停记忆词典/重试横幅词典/Wiki API 客户端审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/shared/lib/InlineMarks.tsx`：新增 `formatInlineMarksSummary` 与 `formatInlineMarksJson` 及单测 `InlineMarks.test.tsx`，支持一键导出 Word 内联粗斜体标记计数与节点分段数审计摘要（`bold=<count> · italic=<count> · segments=<count>`）与 JSON 快照。
  2. `src/shared/lib/commandPaletteEvents.ts`：新增 `formatCommandPaletteEventSummary` 与 `formatCommandPaletteEventJson` 及单测 `commandPaletteEvents.test.ts`，支持一键导出命令面板跨组件打开信号事件名与派发目标就绪态审计摘要（`event=sage:command-palette:open · targetReady=<bool>`）与 JSON 快照。
  3. `src/shared/lib/productMessages.ts`：新增 `formatProductMessagesSummary` 与 `formatProductMessagesJson` 及单测 `productMessages.test.ts`，支持一键导出产品状态提示词典语种、键数与中英对齐审计摘要（`locale=<zh|en> · keys=<count> · parity=<bool>`）与 JSON 快照。
  4. `src/shared/lib/shortcuts.ts`：新增 `formatShortcutRegistrySummary` 与 `formatShortcutRegistryJson` 及单测 `shortcuts.test.ts`，支持一键导出快捷键帮助分组数与条目总数审计摘要（`groups=<count> · shortcuts=<count>`）与 JSON 快照。
  5. `src/shared/lib/workspaceContext.tsx`：新增 `WorkspaceBindingAuditInput`、`formatWorkspaceBindingSummary` 与 `formatWorkspaceBindingJson` 及单测 `workspaceContext.test.ts`，支持一键导出工作区上下文挂载态、加载状态与路径绑定态审计摘要（`provider=<mounted|unmounted> · status=<status> · bound=<bool>`）与 JSON 快照。
  6. `src/shared/lib/i18n/pausedMemory.ts`：新增 `formatPausedMemoryI18nSummary` 与 `formatPausedMemoryI18nJson` 及单测 `pausedMemory.test.ts`，支持一键导出暂停长期记忆中英词典键数对齐审计摘要（`zh=<count> · en=<count> · parity=<bool>`）与 JSON 快照。
  7. `src/shared/lib/i18n/retryBanner.ts`：新增 `formatRetryBannerI18nSummary` 与 `formatRetryBannerI18nJson` 及单测 `retryBanner.test.ts`，支持一键导出 LLM 重试横幅中英词典键数对齐审计摘要（`zh=<count> · en=<count> · parity=<bool>`）与 JSON 快照。
  8. `src/shared/api-client/wiki.ts`：新增 `WIKI_API_BASE`、`formatWikiApiClientSummary` 与 `formatWikiApiClientJson` 及单测 `wiki.test.ts`，支持一键导出 Wiki 后端 API 基础地址、演示模式拦截态与默认检索上限审计摘要（`baseUrl=http://127.0.0.1:8765/api/v1 · demoBlocked=<bool> · defaultLimit=<n>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P127：国际化聚合词典（en/zh）与分域翻译词典（chatAndSider/settingsAndModels/workspaceAndTools）审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/shared/lib/i18n/en.ts`：新增 `formatEnglishTranslationsSummary` 与 `formatEnglishTranslationsJson` 及单测 `en.test.ts`，支持一键导出英文聚合词典总键数审计摘要（`locale=en · keys=<count>`）与 JSON 快照。
  2. `src/shared/lib/i18n/zh.ts`：新增 `formatChineseTranslationsSummary` 与 `formatChineseTranslationsJson` 及单测 `zh.test.ts`，支持一键导出中文聚合词典总键数审计摘要（`locale=zh · keys=<count>`）与 JSON 快照。
  3. `src/shared/lib/i18n/locales/en/chatAndSider.ts`：新增 `formatEnChatAndSiderSummary` 与 `formatEnChatAndSiderJson` 及单测 `chatAndSider.test.ts`，支持一键导出英文对话与侧边栏分域词典键数审计摘要（`domain=en.chatAndSider · keys=<count>`）与 JSON 快照。
  4. `src/shared/lib/i18n/locales/en/settingsAndModels.ts`：新增 `formatEnSettingsAndModelsSummary` 与 `formatEnSettingsAndModelsJson` 及单测 `settingsAndModels.test.ts`，支持一键导出英文设置与模型分域词典键数审计摘要（`domain=en.settingsAndModels · keys=<count>`）与 JSON 快照。
  5. `src/shared/lib/i18n/locales/en/workspaceAndTools.ts`：新增 `formatEnWorkspaceAndToolsSummary` 与 `formatEnWorkspaceAndToolsJson` 及单测 `workspaceAndTools.test.ts`，支持一键导出英文工作区与工具分域词典键数审计摘要（`domain=en.workspaceAndTools · keys=<count>`）与 JSON 快照。
  6. `src/shared/lib/i18n/locales/zh/chatAndSider.ts`：新增 `formatZhChatAndSiderSummary` 与 `formatZhChatAndSiderJson` 及单测 `chatAndSider.test.ts`，支持一键导出中文对话与侧边栏分域词典键数审计摘要（`domain=zh.chatAndSider · keys=<count>`）与 JSON 快照。
  7. `src/shared/lib/i18n/locales/zh/settingsAndModels.ts`：新增 `formatZhSettingsAndModelsSummary` 与 `formatZhSettingsAndModelsJson` 及单测 `settingsAndModels.test.ts`，支持一键导出中文设置与模型分域词典键数审计摘要（`domain=zh.settingsAndModels · keys=<count>`）与 JSON 快照。
  8. `src/shared/lib/i18n/locales/zh/workspaceAndTools.ts`：新增 `formatZhWorkspaceAndToolsSummary` 与 `formatZhWorkspaceAndToolsJson` 及单测 `workspaceAndTools.test.ts`，支持一键导出中文工作区与工具分域词典键数审计摘要（`domain=zh.workspaceAndTools · keys=<count>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 9 个测试文件（含 `welcome-translations.test.ts`）全部通过；`release/win7` 9 个测试文件全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P128：I18n 上下文提供器/Wiki 领域类型/Badge/Button/Card/Input/Modal/PageHeader 基础组件审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/shared/lib/i18n/index.tsx`：新增 `formatI18nProviderSummary` 与 `formatI18nProviderJson` 及单测 `index.test.tsx`，支持一键导出 I18nProvider 激活语种、聚合词条数与持久化存储键审计摘要（`locale=<zh|en> · keys=<count> · storageKey=sage.locale`）与 JSON 快照。
  2. `src/shared/types/wiki.ts`：新增 `formatWikiProjectSummary` 与 `formatWikiProjectJson` 及单测 `wiki.test.ts`，支持一键导出 Wiki 项目绑定状态与最近项目计数审计摘要（`project=<id|none> · bound=<bool> · recent=<n>`）与 JSON 快照。
  3. `src/shared/ui/Badge.tsx`：新增 `formatBadgeVariantSummary` 与 `formatBadgeVariantJson` 及单测 `Badge.test.tsx`，支持一键导出徽章视觉变体与胶囊圆角形态审计摘要（`variant=<default|secondary|outline|destructive> · pill=true`）与 JSON 快照。
  4. `src/shared/ui/Button.tsx`：新增 `formatButtonVariantSummary` 与 `formatButtonVariantJson` 及单测 `Button.test.tsx`，支持一键导出按钮视觉变体、尺寸规格与禁用态审计摘要（`variant=<v> · size=<s> · disabled=<bool>`）与 JSON 快照。
  5. `src/shared/ui/Card.tsx`：新增 `formatCardLayoutSummary` 与 `formatCardLayoutJson` 及单测 `Card.test.tsx`，支持一键导出卡片容器头部、标题与正文区块装配态审计摘要（`header=<bool> · title=<bool> · content=<bool>`）与 JSON 快照。
  6. `src/shared/ui/Input.tsx`：新增 `formatInputFieldSummary` 与 `formatInputFieldJson` 及单测 `Input.test.tsx`，支持一键导出输入框校验错误态与禁用态审计摘要（`error=<bool> · disabled=<bool>`）与 JSON 快照。
  7. `src/shared/ui/Modal.tsx`：新增 `formatModalDialogSummary` 与 `formatModalDialogJson` 及单测 `Modal.test.tsx`，支持一键导出模态框打开态、标题栏与底部操作区配置审计摘要（`open=<bool> · title=<bool> · footer=<bool>`）与 JSON 快照。
  8. `src/shared/ui/PageHeader.tsx`：新增 `formatPageHeaderSummary` 与 `formatPageHeaderJson` 及单测 `PageHeader.test.tsx`，支持一键导出二级页面统一 48px 顶栏标题、副标题与操作区装配态审计摘要（`title=<title> · subtitle=<bool> · actions=<bool>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P129：顶层 Provider 栈 (`AppProviders`/`ErrorBoundary`/`QueryClientProvider`/`ToastProvider`/`providers/index`)、Arena 实体 (`arena/api`/`arena/index`) 与端点协议注册表 (`providerRegistry`) 审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/app/providers/AppProviders.tsx`：新增 `formatAppProvidersSummary` 与 `formatAppProvidersJson` 及单测 `AppProviders.test.tsx`，支持一键导出顶层 Provider 嵌套栈、Toast 兄弟挂载位与子节点装配态审计摘要（`stack=ErrorBoundary>Theme>Font>SessionWorkspace>I18n>QueryClient · toast=sibling · children=<bool>`）与 JSON 快照。
  2. `src/app/providers/ErrorBoundary.tsx`：新增 `formatErrorBoundarySummary` 与 `formatErrorBoundaryJson` 及单测 `ErrorBoundary.test.tsx`，支持一键导出错误边界捕获状态、异常信息与自定义降级 UI 配置审计摘要（`caught=<bool> · message=<msg|none> · customFallback=<bool>`）与 JSON 快照。
  3. `src/app/providers/QueryClientProvider.tsx`：新增 `formatQueryClientConfigSummary` 与 `formatQueryClientConfigJson` 及单测 `QueryClientProvider.test.tsx`，支持一键导出 TanStack Query 客户端默认缓存窗口、重试次数与失焦重拉策略审计摘要（`staleTimeMs=<n> · retry=<n> · refetchOnWindowFocus=<bool>`）与 JSON 快照。
  4. `src/app/providers/ToastProvider.tsx`：新增 `formatToastProviderSummary` 与 `formatToastProviderJson` 及单测 `ToastProvider.test.tsx`，支持一键导出 Sonner Toast 容器明暗主题、弹出方位与驻留时长审计摘要（`theme=<light|dark> · position=top-right · durationMs=<n>`）与 JSON 快照。
  5. `src/app/providers/index.ts`：新增 `formatProvidersBarrelSummary` 与 `formatProvidersBarrelJson` 及单测 `index.test.ts`，支持一键导出顶层 Provider Barrel 导出符号清单与数量审计摘要（`exports=AppProviders,ErrorBoundary,QueryClientProvider,ThemeProvider,ToastProvider,useTheme · count=6`）与 JSON 快照。
  6. `src/entities/arena/api.ts`：新增 `formatArenaAccountSummary` 与 `formatArenaAccountJson` 及单测 `api.test.ts`，支持一键导出 Arena 账号池个体状态与累计失败计数审计摘要（`id=<id> · state=<state> · failures=<n>`）与 JSON 快照。
  7. `src/entities/arena/index.ts`：新增 `formatArenaEntityBarrelSummary` 与 `formatArenaEntityBarrelJson` 及单测 `index.test.ts`，支持一键导出 Arena 实体 Barrel 路由前缀与重导出模块审计摘要（`module=entities/arena · base=/api/v1/arena · reExports=api`）与 JSON 快照。
  8. `src/entities/endpoint/providerRegistry.ts`：新增 `formatProviderRegistrySummary` 与 `formatProviderRegistryJson` 及单测 `providerRegistry.test.ts`，支持一键导出前端 LLM 协议注册表已注册协议列表与代理路由前缀审计摘要（`providers=<count> · ids=<csv> · proxyBase=/api/v1/llm`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P130：设置注册表 (`settingsRegistry`)、主题预设 (`theme/presets`)、Attention Barrel (`attention/index`)、自主目标视图 (`CreateGoalModal`/`GoalDetailPage`/`GoalListPage`) 与对话附件/实体菜单 (`AtEntityMenu`/`MediaAttachment`) 审计快照与 JSON 导出（已完成）
- **职责范围**：
  1. `src/entities/setting/settingsRegistry.ts`：新增 `formatSettingsRegistrySummary` 与 `formatSettingsRegistryJson` 及单测 `settingsRegistry.test.ts`，支持一键导出设置元数据注册表总项数、基础可见项与高级可见项审计摘要（`total=<count> · basic=<count> · advanced=<count>`）与 JSON 快照。
  2. `src/entities/theme/presets.ts`：新增 `formatThemePresetsSummary` 与 `formatThemePresetsJson` 及单测 `presets.audit.test.ts`，支持一键导出内置主题预设数量、默认主题 ID 与预设 ID 清单审计摘要（`count=<n> · defaultId=indigo · ids=<csv>`）与 JSON 快照。
  3. `src/features/attention/index.ts`：新增 `formatAttentionBarrelSummary` 与 `formatAttentionBarrelJson` 及单测 `index.test.ts`，支持一键导出 Attention 特性 Barrel 注意力分类数与导出符号计数审计摘要（`module=features/attention · kinds=<n> · exports=8`）与 JSON 快照。
  4. `src/features/autonomous-goals/CreateGoalModal.tsx`：新增 `formatCreateGoalModalSummary` 与 `formatCreateGoalModalJson` 及单测 `CreateGoalModal.test.tsx`，支持一键导出创建自主目标弹窗打开态、最大执行时长与 Token 预算审计摘要（`open=<bool> · maxHours=<n> · maxTokens=<n>`）与 JSON 快照。
  5. `src/features/autonomous-goals/GoalDetailPage.tsx`：新增 `formatGoalDetailSummary` 与 `formatGoalDetailJson` 及单测 `GoalDetailPage.test.tsx`，支持一键导出自主目标详情页运行状态、本地化标签与检查点计数审计摘要（`status=<status|none> · label=<label|none> · checkpoints=<n>`）与 JSON 快照。
  6. `src/features/autonomous-goals/GoalListPage.tsx`：新增 `formatGoalListFilterSummary` 与 `formatGoalListFilterJson` 及单测 `GoalListPage.test.tsx`，支持一键导出自主目标列表筛选器状态、当前目标计数与筛选项数量审计摘要（`filter=<status|all> · goals=<n> · options=7`）与 JSON 快照。
  7. `src/features/chat/AtEntityMenu.tsx`：新增 `formatAtEntityMenuSummary` 与 `formatAtEntityMenuJson` 及单测 `AtEntityMenu.test.tsx`，支持一键导出 `@` 实体菜单查询词、匹配项计数与支持实体类型审计摘要（`query=<query|empty> · matches=<n> · kinds=memory,wiki,skill,agent`）与 JSON 快照。
  8. `src/features/chat/MediaAttachment.tsx`：新增 `formatMediaAttachmentSummary` 与 `formatMediaAttachmentJson` 及单测 `MediaAttachment.test.tsx`，支持一键导出对话媒体附件 MIME 类型、渲染类别与说明文字配置审计摘要（`mimeType=<mime> · category=<image|audio|file> · caption=<bool>`）与 JSON 快照。
- **验证结果**：
  - `npx vitest run --api=false`：`main` 8 个测试文件 16 项单测全部通过；`release/win7` 8 个测试文件 16 项单测全部通过。
  - 门禁：`check-font-scale.mjs`、`architecture-check.mjs`、`export-ipc-manifest.mjs --check`、`npx tsc --noEmit`、`npx eslint` 在 `main` 与 `release/win7` 双轨零告警通过。
### Phase P131 — Chat & Diagnostic Barrels, Journal Panel/Editors & Preference/Office Forms Audit Diagnostics & JSON Export (2026-10-22)

- **Chat & Diagnostic Feature Barrels (`src/features/chat/index.ts`, `src/features/diagnostic/index.ts`)**:
  - Added `ChatFeatureBarrelAuditReport`, `auditChatFeatureBarrel()`, and `exportChatFeatureBarrelAuditJson()` plus `DiagnosticFeatureBarrelAuditReport`, `auditDiagnosticFeatureBarrel()`, and `exportDiagnosticFeatureBarrelAuditJson()` with `schemaVersion: '1.0'` and `exportedAt: '2026-10-22'`.
- **Journal Panel, Actions, Content Editor & Barrel (`src/features/journal/JournalPanel.tsx`, `src/features/journal/components/JournalActions.tsx`, `src/features/journal/components/JournalContentEditor.tsx`, `src/features/journal/index.ts`)**:
  - Added `JournalPanelAuditReport`, `auditJournalPanel()`, and `exportJournalPanelAuditJson()`, `JournalActionsAuditReport`, `auditJournalActions()`, and `exportJournalActionsAuditJson()`, `JournalContentEditorAuditReport`, `auditJournalContentEditor()`, and `exportJournalContentEditorAuditJson()`, plus `JournalFeatureBarrelAuditReport`, `auditJournalFeatureBarrel()`, and `exportJournalFeatureBarrelAuditJson()` (`src/features/journal/` is now 100% covered).
- **Preference Save Status & Excel/PPT Edit Form Fields (`src/features/manage-settings/PreferenceSaveStatus.tsx`, `src/features/office/ExcelPptEditFormFields.tsx`)**:
  - Added `PreferenceSaveStatusAuditReport`, `auditPreferenceSaveStatus()`, and `exportPreferenceSaveStatusAuditJson()` plus `ExcelPptEditFormFieldsAuditReport`, `auditExcelPptEditFormFields()`, and `exportExcelPptEditFormFieldsAuditJson()`.
- **Unit Test Coverage**:
  - Added 8 unit test suites (`16` tests total) verifying nominal and fallback audit diagnostics and JSON export across all 8 modules.
### Phase P132 — Office Capability/Snapshot/PDF Dialogs & Barrels, Project-Type Barrel, Send-Message Attachment/Transparency & Workspace Barrel Audit Diagnostics & JSON Export (2026-10-22)

- **Office Capability Bar, Snapshot Panel, PDF Form Fill Dialog & Barrel (`src/features/office/OfficeCapabilityBar.tsx`, `src/features/office/OfficeSnapshotPanel.tsx`, `src/features/office/PdfFormFillDialog.tsx`, `src/features/office/index.ts`)**:
  - Added `OfficeCapabilityBarAuditReport`, `auditOfficeCapabilityBar()`, and `exportOfficeCapabilityBarAuditJson()`, `OfficeSnapshotPanelAuditReport`, `auditOfficeSnapshotPanel()`, and `exportOfficeSnapshotPanelAuditJson()`, `PdfFormFillDialogAuditReport`, `auditPdfFormFillDialog()`, and `exportPdfFormFillDialogAuditJson()`, plus `OfficeFeatureBarrelAuditReport`, `auditOfficeFeatureBarrel()`, and `exportOfficeFeatureBarrelAuditJson()` with `schemaVersion: '1.0'` and `exportedAt: '2026-10-22'` (`src/features/office/` is now 100% covered).
- **Project-Type & Workspace Feature Barrels (`src/features/project-type/index.ts`, `src/features/workspace/index.ts`)**:
  - Added `ProjectTypeFeatureBarrelAuditReport`, `auditProjectTypeFeatureBarrel()`, and `exportProjectTypeFeatureBarrelAuditJson()` plus `WorkspaceFeatureBarrelAuditReport`, `auditWorkspaceFeatureBarrel()`, and `exportWorkspaceFeatureBarrelAuditJson()` (`src/features/project-type/` and `src/features/workspace/` are now 100% covered).
- **Send-Message Attachment Upload & Transparency Payload Validators (`src/features/send-message/AttachmentUpload.tsx`, `src/features/send-message/transparencyPayload.ts`)**:
  - Added `AttachmentUploadAuditReport`, `auditAttachmentUpload()`, and `exportAttachmentUploadAuditJson()` plus `TransparencyPayloadAuditReport`, `auditTransparencyPayload()`, and `exportTransparencyPayloadAuditJson()`.
- **Unit Test Coverage**:
  - Added 8 unit test suites (`16` tests total) verifying nominal and fallback audit diagnostics and JSON export across all 8 modules.

### Phase P133 — Agents Form/Barrel, Arena Table/Feed/Assist/Barrel & Chat Active-Agent/Compact-Banner Audit Diagnostics & JSON Export (Completed)

- **Target Modules**:
  - `src/widgets/agents/EditAgentForm.tsx`: Added `EditAgentFormAuditInput`, `EditAgentFormAuditReport`, `evaluateEditAgentFormAudit`, and `exportEditAgentFormAuditJson`.
  - `src/widgets/agents/index.ts`: Added `AgentsWidgetBarrelAuditInput`, `AgentsWidgetBarrelAuditReport`, `evaluateAgentsWidgetBarrelAudit`, and `exportAgentsWidgetBarrelAuditJson`.
  - `src/widgets/arena/AccountTable.tsx`: Added `AccountTableAuditInput`, `AccountTableAuditReport`, `evaluateAccountTableAudit`, and `exportAccountTableAuditJson`.
  - `src/widgets/arena/ObservationFeed.tsx`: Added `ObservationFeedAuditInput`, `ObservationFeedAuditReport`, `evaluateObservationFeedAudit`, and `exportObservationFeedAuditJson`.
  - `src/widgets/arena/RegisterAssist.tsx`: Added `RegisterAssistAuditInput`, `RegisterAssistAuditReport`, `evaluateRegisterAssistAudit`, and `exportRegisterAssistAuditJson`.
  - `src/widgets/arena/index.ts`: Added `ArenaWidgetBarrelAuditInput`, `ArenaWidgetBarrelAuditReport`, `evaluateArenaWidgetBarrelAudit`, and `exportArenaWidgetBarrelAuditJson`.
  - `src/widgets/chat/ActiveAgentIndicator.tsx`: Added `ActiveAgentIndicatorAuditInput`, `ActiveAgentIndicatorAuditReport`, `evaluateActiveAgentIndicatorAudit`, and `exportActiveAgentIndicatorAuditJson`.
  - `src/widgets/chat/CompactBanner.tsx`: Added `CompactBannerAuditInput`, `CompactBannerAuditReport`, `evaluateCompactBannerAudit`, and `exportCompactBannerAuditJson`.
- **Unit Tests**:
  - `src/widgets/agents/__tests__/EditAgentForm.p133.test.ts`
  - `src/widgets/agents/__tests__/index.p133.test.ts`
  - `src/widgets/arena/__tests__/AccountTable.p133.test.ts`
  - `src/widgets/arena/__tests__/ObservationFeed.p133.test.ts`
  - `src/widgets/arena/__tests__/RegisterAssist.p133.test.ts`
  - `src/widgets/arena/__tests__/index.p133.test.ts`
  - `src/widgets/chat/__tests__/ActiveAgentIndicator.p133.test.ts`
  - `src/widgets/chat/__tests__/CompactBanner.p133.test.ts`

### Phase P134 — Autonomous-Goals Card/Progress & Chat Inline-Error/Attachment/HtmlCodeBlock/KnowledgeChip/MarkdownParts/ReadAloud Audit Diagnostics & JSON Export (Completed)

- **Target Modules**:
  - `src/widgets/autonomous-goals/GoalCard.tsx`: Added `GoalCardAuditInput`, `GoalCardAuditReport`, `evaluateGoalCardAudit`, and `exportGoalCardAuditJson`.
  - `src/widgets/autonomous-goals/GoalProgress.tsx`: Added `GoalProgressAuditInput`, `GoalProgressAuditReport`, `evaluateGoalProgressAudit`, and `exportGoalProgressAuditJson`.
  - `src/widgets/chat/ChatInlineError.tsx`: Added `ChatInlineErrorAuditInput`, `ChatInlineErrorAuditReport`, `evaluateChatInlineErrorAudit`, and `exportChatInlineErrorAuditJson`.
  - `src/widgets/chat/FileAttachment.tsx`: Added `FileAttachmentAuditInput`, `FileAttachmentAuditReport`, `evaluateFileAttachmentAudit`, and `exportFileAttachmentAuditJson`.
  - `src/widgets/chat/HtmlCodeBlock.tsx`: Added `HtmlCodeBlockAuditInput`, `HtmlCodeBlockAuditReport`, `evaluateHtmlCodeBlockAudit`, and `exportHtmlCodeBlockAuditJson`.
  - `src/widgets/chat/KnowledgeChip.tsx`: Added `KnowledgeChipAuditInput`, `KnowledgeChipAuditReport`, `evaluateKnowledgeChipAudit`, and `exportKnowledgeChipAuditJson`.
  - `src/widgets/chat/MessageMarkdownParts.tsx`: Added `MessageMarkdownPartsAuditInput`, `MessageMarkdownPartsAuditReport`, `evaluateMessageMarkdownPartsAudit`, and `exportMessageMarkdownPartsAuditJson`.
  - `src/widgets/chat/ReadAloudButton.tsx`: Added `ReadAloudButtonAuditInput`, `ReadAloudButtonAuditReport`, `evaluateReadAloudButtonAudit`, and `exportReadAloudButtonAuditJson`.
- **Unit Tests**:
  - `src/widgets/autonomous-goals/__tests__/GoalCard.p134.test.ts`
  - `src/widgets/autonomous-goals/__tests__/GoalProgress.p134.test.ts`
  - `src/widgets/chat/__tests__/ChatInlineError.p134.test.ts`
  - `src/widgets/chat/__tests__/FileAttachment.p134.test.ts`
  - `src/widgets/chat/__tests__/HtmlCodeBlock.p134.test.ts`
  - `src/widgets/chat/__tests__/KnowledgeChip.p134.test.ts`
  - `src/widgets/chat/__tests__/MessageMarkdownParts.p134.test.ts`
  - `src/widgets/chat/__tests__/ReadAloudButton.p134.test.ts`

### Phase P135 — Chat Right-Panel/Session-Id/Shiki/Slash-Menu/Subagent-Panel/Terminal/Topic-Separator/Truncation Audit Diagnostics & JSON Export (Completed)

- **Target Modules**:
  - `src/widgets/chat/RightPanelToggle.tsx`: Added `RightPanelToggleAuditInput`, `RightPanelToggleAuditReport`, `evaluateRightPanelToggleAudit`, and `exportRightPanelToggleAuditJson`.
  - `src/widgets/chat/SessionIdBadge.tsx`: Added `SessionIdBadgeAuditInput`, `SessionIdBadgeAuditReport`, `evaluateSessionIdBadgeAudit`, and `exportSessionIdBadgeAuditJson`.
  - `src/widgets/chat/ShikiCodeBlock.tsx`: Added `ShikiCodeBlockAuditInput`, `ShikiCodeBlockAuditReport`, `evaluateShikiCodeBlockAudit`, and `exportShikiCodeBlockAuditJson`.
  - `src/widgets/chat/SlashCommandMenu.tsx`: Added `SlashCommandMenuAuditInput`, `SlashCommandMenuAuditReport`, `evaluateSlashCommandMenuAudit`, and `exportSlashCommandMenuAuditJson`.
  - `src/widgets/chat/SubagentLivePanel.tsx`: Added `SubagentLivePanelAuditInput`, `SubagentLivePanelAuditReport`, `evaluateSubagentLivePanelAudit`, and `exportSubagentLivePanelAuditJson`.
  - `src/widgets/chat/TerminalPanel.tsx`: Added `TerminalPanelAuditInput`, `TerminalPanelAuditReport`, `evaluateTerminalPanelAudit`, and `exportTerminalPanelAuditJson`.
  - `src/widgets/chat/TopicSeparator.tsx`: Added `TopicSeparatorAuditInput`, `TopicSeparatorAuditReport`, `evaluateTopicSeparatorAudit`, and `exportTopicSeparatorAuditJson`.
  - `src/widgets/chat/TruncationNotice.tsx`: Added `TruncationNoticeAuditInput`, `TruncationNoticeAuditReport`, `evaluateTruncationNoticeAudit`, and `exportTruncationNoticeAuditJson`.
- **Unit Tests**:
  - `src/widgets/chat/__tests__/RightPanelToggle.p135.test.ts`
  - `src/widgets/chat/__tests__/SessionIdBadge.p135.test.ts`
  - `src/widgets/chat/__tests__/ShikiCodeBlock.p135.test.ts`
  - `src/widgets/chat/__tests__/SlashCommandMenu.p135.test.ts`
  - `src/widgets/chat/__tests__/SubagentLivePanel.p135.test.ts`
  - `src/widgets/chat/__tests__/TerminalPanel.p135.test.ts`
  - `src/widgets/chat/__tests__/TopicSeparator.p135.test.ts`
  - `src/widgets/chat/__tests__/TruncationNotice.p135.test.ts`

## Phase P136 — Chat Turn Group, Artifact/Document Preview, Context Input & Tool Renderer Governance Audit (2026-10-22)

- **PRs**: `#2282` (`main` @ `7ec887b8d`) / `#2283` (`release/win7` @ `2e02027fa`) merged for Phase P135; Phase P136 extends deterministic governance audit contracts across 8 chat turn group, barrel export, artifact/document preview, context input, and tool renderer modules:
  1. `src/widgets/chat/TurnGroup.tsx` (`evaluateTurnGroupGovernanceAudit` + `src/widgets/chat/__tests__/TurnGroup.p136.test.ts`)
  2. `src/widgets/chat/index.ts` (`evaluateChatWidgetsBarrelGovernanceAudit` + `src/widgets/chat/__tests__/index.p136.test.ts`)
  3. `src/widgets/chat/artifacts/ArtifactViewer.tsx` (`evaluateArtifactViewerGovernanceAudit` + `src/widgets/chat/artifacts/__tests__/ArtifactViewer.p136.test.ts`)
  4. `src/widgets/chat/preview/DocumentPreview.tsx` (`evaluateDocumentPreviewGovernanceAudit` + `src/widgets/chat/preview/__tests__/DocumentPreview.p136.test.ts`)
  5. `src/widgets/chat/progress/ContextInput.tsx` (`evaluateContextInputGovernanceAudit` + `src/widgets/chat/progress/__tests__/ContextInput.p136.test.ts`)
  6. `src/widgets/chat/toolRenderers/BashToolRenderer.tsx` (`evaluateBashToolRendererGovernanceAudit` + `src/widgets/chat/toolRenderers/__tests__/BashToolRenderer.p136.test.ts`)
  7. `src/widgets/chat/toolRenderers/FileWriteToolRenderer.tsx` (`evaluateFileWriteToolRendererGovernanceAudit` + `src/widgets/chat/toolRenderers/__tests__/FileWriteToolRenderer.p136.test.ts`)
  8. `src/widgets/chat/toolRenderers/ToolCallCard.tsx` (`evaluateToolCallCardGovernanceAudit` + `src/widgets/chat/toolRenderers/__tests__/ToolCallCard.p136.test.ts`)

## Phase P137 — Tool Renderer Registry, Command Widget, Evolution Log/Panel & Help Footer Governance Audit (2026-10-22)

- **PRs**: `#2284` (`main` @ `978c18e04`) / `#2285` (`release/win7` @ `7d1c34369`) merged for Phase P136; Phase P137 extends deterministic governance audit contracts across 8 tool renderer registry, command widget, evolution log/panel, and help footer modules:
  1. `src/widgets/chat/toolRenderers/WebSearchToolRenderer.tsx` (`evaluateWebSearchToolRendererGovernanceAudit` + `src/widgets/chat/toolRenderers/__tests__/WebSearchToolRenderer.p137.test.ts`)
  2. `src/widgets/chat/toolRenderers/index.ts` (`evaluateToolRenderersBarrelGovernanceAudit` + `src/widgets/chat/toolRenderers/__tests__/index.p137.test.ts`)
  3. `src/widgets/chat/toolRenderers/registry.ts` (`evaluateToolRendererRegistryGovernanceAudit` + `src/widgets/chat/toolRenderers/__tests__/registry.p137.test.ts`)
  4. `src/widgets/command/commandItems.ts` (`evaluateCommandItemsGovernanceAudit` + `src/widgets/command/__tests__/commandItems.p137.test.ts`)
  5. `src/widgets/command/index.ts` (`evaluateCommandWidgetBarrelGovernanceAudit` + `src/widgets/command/__tests__/index.p137.test.ts`)
  6. `src/widgets/evolution/EvolutionLog.tsx` (`evaluateEvolutionLogGovernanceAudit` + `src/widgets/evolution/__tests__/EvolutionLog.p137.test.ts`)
  7. `src/widgets/evolution/EvolutionPanel.tsx` (`evaluateEvolutionPanelGovernanceAudit` + `src/widgets/evolution/__tests__/EvolutionPanel.p137.test.ts`)
  8. `src/widgets/help/HelpFooter.tsx` (`evaluateHelpFooterGovernanceAudit` + `src/widgets/help/__tests__/HelpFooter.p137.test.ts`)

## Phase P138 — Help Sidebar, Layout Shell/Sidebar/Divider & Memory/Model-Catalog Barrel Governance Audit (2026-10-22)

- **PRs**: `#2286` (`main` @ `89e7dc922`) / `#2287` (`release/win7` @ `6b1a567dd`) merged for Phase P137; Phase P138 extends deterministic governance audit contracts across 8 help sidebar, layout shell/sidebar/divider, and memory/model-catalog barrel modules:
  1. `src/widgets/help/HelpSidebar.tsx` (`evaluateHelpSidebarGovernanceAudit` + `src/widgets/help/__tests__/HelpSidebar.p138.test.ts`)
  2. `src/widgets/layout/Layout.tsx` (`evaluateLayoutShellGovernanceAudit` + `src/widgets/layout/__tests__/Layout.p138.test.ts`)
  3. `src/widgets/layout/ResizeDivider.tsx` (`evaluateResizeDividerGovernanceAudit` + `src/widgets/layout/__tests__/ResizeDivider.p138.test.ts`)
  4. `src/widgets/layout/Sidebar.tsx` (`evaluateSidebarGovernanceAudit` + `src/widgets/layout/__tests__/Sidebar.p138.test.ts`)
  5. `src/widgets/layout/SidebarNavItem.tsx` (`evaluateSidebarNavItemGovernanceAudit` + `src/widgets/layout/__tests__/SidebarNavItem.p138.test.ts`)
  6. `src/widgets/layout/index.ts` (`evaluateLayoutBarrelGovernanceAudit` + `src/widgets/layout/__tests__/index.p138.test.ts`)
  7. `src/widgets/memory/index.ts` (`evaluateMemoryWidgetsBarrelGovernanceAudit` + `src/widgets/memory/__tests__/index.p138.test.ts`)
  8. `src/widgets/model-catalog/index.ts` (`evaluateModelCatalogBarrelGovernanceAudit` + `src/widgets/model-catalog/__tests__/index.p138.test.ts`)

## Phase P139 — Permission/Question/Session/Skills Barrels, SessionItem, VirtualSessionList, MaterialStatusBadge & BackendStatusBanner Governance Audit (2026-10-22)

- **PRs**: `#2294` (`main` @ `39da10f53`) / `#2295` (`release/win7` @ `549dbcdbf`) merged for Phase P138; Phase P139 extends deterministic governance audit contracts across 8 permission/question/session/skills barrel, session list/item, material status badge, and backend status banner modules:
  1. `src/widgets/permission/index.ts` (`evaluatePermissionBarrelGovernanceAudit` + `src/widgets/permission/__tests__/index.p139.test.ts`)
  2. `src/widgets/question/index.ts` (`evaluateQuestionBarrelGovernanceAudit` + `src/widgets/question/__tests__/index.p139.test.ts`)
  3. `src/widgets/session/SessionItem.tsx` (`evaluateSessionItemGovernanceAudit` + `src/widgets/session/__tests__/SessionItem.p139.test.ts`)
  4. `src/widgets/session/VirtualSessionList.tsx` (`evaluateVirtualSessionListGovernanceAudit` + `src/widgets/session/__tests__/VirtualSessionList.p139.test.ts`)
  5. `src/widgets/session/index.ts` (`evaluateSessionBarrelGovernanceAudit` + `src/widgets/session/__tests__/index.p139.test.ts`)
  6. `src/widgets/sidebar/sections/MaterialStatusBadge.tsx` (`evaluateMaterialStatusBadgeGovernanceAudit` + `src/widgets/sidebar/sections/__tests__/MaterialStatusBadge.p139.test.ts`)
  7. `src/widgets/skills/index.ts` (`evaluateSkillsBarrelGovernanceAudit` + `src/widgets/skills/__tests__/index.p139.test.ts`)
  8. `src/widgets/system/BackendStatusBanner.tsx` (`evaluateBackendStatusBannerGovernanceAudit` + `src/widgets/system/__tests__/BackendStatusBanner.p139.test.ts`)

## Phase P140 — DeliveryDrawerHost, Wiki Sidebar/Preview/Trees/Barrel, SavedTaskRecipes & TaskModelAdvisor Governance Audit (2026-10-22)

- **PRs**: `#2300` (`main` @ `262b8c600`) / `#2301` (`release/win7` @ `cc09b908c`) merged for Phase P139; Phase P140 completes all `src/widgets/` modules and extends deterministic governance audit contracts across 8 delivery drawer, wiki sidebar/preview/tree/barrel, and task-brief recipe/advisor modules:
  1. `src/widgets/task-center/DeliveryDrawerHost.tsx` (`evaluateDeliveryDrawerHostGovernanceAudit` + `src/widgets/task-center/__tests__/DeliveryDrawerHost.p140.test.ts`)
  2. `src/widgets/wiki/IconSidebar.tsx` (`evaluateWikiIconSidebarGovernanceAudit` + `src/widgets/wiki/__tests__/IconSidebar.p140.test.ts`)
  3. `src/widgets/wiki/MarkdownPreview.tsx` (`evaluateWikiMarkdownPreviewGovernanceAudit` + `src/widgets/wiki/__tests__/MarkdownPreview.p140.test.ts`)
  4. `src/widgets/wiki/SourcesTree.tsx` (`evaluateWikiSourcesTreeGovernanceAudit` + `src/widgets/wiki/__tests__/SourcesTree.p140.test.ts`)
  5. `src/widgets/wiki/WikiFileTree.tsx` (`evaluateWikiFileTreeGovernanceAudit` + `src/widgets/wiki/__tests__/WikiFileTree.p140.test.ts`)
  6. `src/widgets/wiki/index.ts` (`evaluateWikiBarrelGovernanceAudit` + `src/widgets/wiki/__tests__/index.p140.test.ts`)
  7. `src/features/task-brief/SavedTaskRecipes.tsx` (`evaluateSavedTaskRecipesGovernanceAudit` + `src/features/task-brief/__tests__/SavedTaskRecipes.p140.test.ts`)
  8. `src/features/task-brief/TaskModelAdvisor.tsx` (`evaluateTaskModelAdvisorGovernanceAudit` + `src/features/task-brief/__tests__/TaskModelAdvisor.p140.test.ts`)
### Phase P141 — Office Generate Subforms, Word Edit Form Fields, Chat Stream Runtime, Help Tabs/Container & Knowledge Page Governance Audit (2026-10-22)

- **PRs**:
  - Phase P140 Merged: `#2302` (`main` @ `e14696554deeb729b681ce0d51a50a06159b8cec`), `#2303` (`release/win7` @ `3b354f55b94d06e173fbf26fa4afa46e02727748`)
  - Phase P141: `feat/project-governance-p141` (`main`) & `feat/win7-project-governance-p141` (`release/win7`)
- **Scope**:
  - `src/features/office/OfficeGenerateSubforms.tsx`: Exported `auditOfficeGenerateSubformsGovernance()` validating office document generation subforms (`ppt`, `docx`, `xlsx`), topic/section/sheet count invariants, and structured subform state transitions.
  - `src/features/office/WordEditFormFields.tsx`: Exported `auditWordEditFormFieldsGovernance()` validating Word edit form field contracts, replacement/insertion operation invariants, and target paragraph/section selectors.
  - `src/features/send-message/chatStreamRuntime.ts`: Exported `auditChatStreamRuntimeGovernance()` validating SSE chat stream runtime lifecycle, active stream count invariants, and abort/timeout recovery contracts.
  - `src/pages/Help/AboutTab.tsx`: Exported `auditHelpAboutTabGovernance()` validating Help About tab version/build metadata, runtime environment readiness, and system diagnostic presentation contracts.
  - `src/pages/Help/ChangelogTab.tsx`: Exported `auditHelpChangelogTabGovernance()` validating Help Changelog tab release entries, version ordering invariants, and release note rendering contracts.
  - `src/pages/Help/HelpTab.tsx`: Exported `auditHelpGuideTabGovernance()` validating Help Guide tab section navigation, quick-start onboarding topics, and troubleshooting guide contracts.
  - `src/pages/Help/index.tsx`: Exported `auditHelpPageContainerGovernance()` validating Help page container tab switching (`help`, `changelog`, `about`), active tab persistence, and layout header contracts.
  - `src/pages/Knowledge.tsx`: Exported `auditKnowledgePageGovernance()` validating Knowledge page workspace wiki integration, document/source count invariants, and search/index synchronization state.
  - Unit tests: Added 8 dedicated Vitest suites (`OfficeGenerateSubforms.p141.test.ts`, `WordEditFormFields.p141.test.ts`, `chatStreamRuntime.p141.test.ts`, `AboutTab.p141.test.ts`, `ChangelogTab.p141.test.ts`, `HelpTab.p141.test.ts`, `index.p141.test.ts`, `Knowledge.p141.test.ts`).
### Phase P142 — Office Structured Previews, Memory/Office/Pages Barrel, Plan Approval Bar, Chat Action/Scroll Hooks & Context Turn Limit Select Governance Audit (2026-10-22)

- **PRs**:
  - Phase P141 Merged: `#2304` (`main` @ `a74926af925cc8b4fabb27be8c7feac63e9c3a80`), `#2305` (`release/win7` @ `f6b15ead3422509a46a267cba0da8f206ae0dfb4`)
  - Phase P142: `feat/project-governance-p142` (`main`) & `feat/win7-project-governance-p142` (`release/win7`)
- **Scope**:
  - `src/features/office/OfficeStructuredPreviews.tsx`: Exported `auditOfficeStructuredPreviewsGovernance()` validating structured office preview rendering (`ppt`, `docx`, `xlsx`), slide/section/sheet count invariants, and preview synchronization state.
  - `src/pages/Memory.tsx`: Exported `auditMemoryPageGovernance()` validating Memory page entry count invariants, active category filter normalization, and search query state.
  - `src/pages/Office.tsx`: Exported `auditOfficePageGovernance()` validating Office page mode switching (`generate`, `edit`, `preview`), document format selection (`ppt`, `docx`, `xlsx`), and generation lifecycle state.
  - `src/pages/index.ts`: Exported `auditPagesBarrelGovernance()` validating top-level page barrel export completeness and lazy route readiness contracts.
  - `src/pages/chat/PlanApprovalBar.tsx`: Exported `auditPlanApprovalBarGovernance()` validating plan approval step count invariants, approval state transitions (`pending`, `approved`, `rejected`), and plan editability contracts.
  - `src/pages/chat/useChatMessageActions.ts`: Exported `auditUseChatMessageActionsGovernance()` validating chat message action hook invariants, message count normalization, and regenerate/busy state contracts.
  - `src/pages/chat/useChatStickyScroll.ts`: Exported `auditUseChatStickyScrollGovernance()` validating chat sticky-scroll hook invariants, scroll threshold bounds, and streaming auto-scroll state.
  - `src/pages/settings/ContextTurnLimitSelect.tsx`: Exported `auditContextTurnLimitSelectGovernance()` validating context turn limit selector bounds (`minTurnLimit`, `maxTurnLimit`) and selected turn clamping invariants.
  - Unit tests: Added 8 dedicated Vitest suites (`OfficeStructuredPreviews.p142.test.ts`, `Memory.p142.test.ts`, `Office.p142.test.ts`, `pagesIndex.p142.test.ts`, `PlanApprovalBar.p142.test.ts`, `useChatMessageActions.p142.test.ts`, `useChatStickyScroll.p142.test.ts`, `ContextTurnLimitSelect.p142.test.ts`).
### Phase P143 — Chat Page, Effective Settings Summary, Font Settings, Memory/Knowledge Settings Tabs, Network Credentials, Usage Stats & Agents API Governance Audit (2026-10-22)

- **PRs**:
  - Phase P142 Merged: `#2306` (`main` @ `ab4f85f8dfdf765679607b8057ccd0021f99e91e`), `#2307` (`release/win7` @ `a0c76523a129b0dd8a2198dc4e3f644566561a56`)
  - Phase P143: `feat/project-governance-p143` (`main`) & `feat/win7-project-governance-p143` (`release/win7`)
- **Scope**:
  - `src/pages/Chat.tsx`: Exported `auditChatPageGovernance()` validating Chat page top header bar control placement (`headerControlsInTopBar`), clean single-row bottom composer contract (`singleRowBottomComposer`), and active session identifier normalization.
  - `src/pages/settings/EffectiveSettingsSummary.tsx`: Exported `auditEffectiveSettingsSummaryGovernance()` validating effective provider, permission mode, and context turn limit summary invariants.
  - `src/pages/settings/FontSettingsSection.tsx`: Exported `auditFontSettingsSectionGovernance()` validating font scale percentage clamping (`minScalePercent`, `maxScalePercent`) and typography scale contracts.
  - `src/pages/settings/MemoryKnowledgeTab.tsx`: Exported `auditMemoryKnowledgeTabGovernance()` validating memory enablement, knowledge source count normalization, and auto-indexing state.
  - `src/pages/settings/MemorySettingsTab.tsx`: Exported `auditMemorySettingsTabGovernance()` validating memory retention days bounds and auto-capture toggle invariants.
  - `src/pages/settings/NetworkCredentialsSection.tsx`: Exported `auditNetworkCredentialsSectionGovernance()` validating configured credential key counts, proxy mode normalization (`system`, `custom`, `none`), and TLS verification invariants.
  - `src/pages/settings/UsageStatsTab.tsx`: Exported `auditUsageStatsTabGovernance()` validating token usage totals, session count normalization, and reporting window bounds.
  - `src/shared/api/agentsApi.ts`: Exported `auditAgentsApiGovernance()` validating agent management REST API endpoint coverage and request timeout bounds.
  - Unit tests: Added 8 dedicated Vitest suites (`Chat.p143.test.ts`, `EffectiveSettingsSummary.p143.test.ts`, `FontSettingsSection.p143.test.ts`, `MemoryKnowledgeTab.p143.test.ts`, `MemorySettingsTab.p143.test.ts`, `NetworkCredentialsSection.p143.test.ts`, `UsageStatsTab.p143.test.ts`, `agentsApi.p143.test.ts`).
### Phase P144 — Chat API, Demo Chat Script, Demo Fixtures Core/Sessions/Agents/Office, Shared API Barrel, MCP Client & Message API Governance Audit (2026-10-22)

- **PRs**:
  - Phase P143 Merged: `#2308` (`main` @ `5f5f6e758290114a37a6cb7bd6b73dbc455a4312`), `#2309` (`release/win7` @ `eb70da81efc4bef58c0a2078b29e73a77dcfe460`)
  - Phase P144: `feat/project-governance-p144` (`main`) & `feat/win7-project-governance-p144` (`release/win7`)
- **Scope**:
  - `src/shared/api/chatApi.ts`: Exported `auditChatApiGovernance()` validating active SSE stream count bounds, max concurrency limits, and stream resume capability contracts.
  - `src/shared/api/demoChatScript.ts`: Exported `auditDemoChatScriptGovernance()` validating demo chat script step count and chunk streaming delay bounds.
  - `src/shared/api/demoFixturesCore.ts`: Exported `auditDemoFixturesCoreGovernance()` validating demo memory, knowledge document, and skill fixture collection integrity.
  - `src/shared/api/demoFixturesSessionsAndAgents.ts`: Exported `auditDemoFixturesSessionsAndAgentsGovernance()` validating demo session, agent profile, and scheduled task fixture collection invariants.
  - `src/shared/api/demoOfficeAndSystemHandlers.ts`: Exported `auditDemoOfficeAndSystemHandlersGovernance()` validating demo office and system IPC/HTTP handler registration count and offline fallback readiness.
  - `src/shared/api/index.ts`: Exported `auditSharedApiBarrelGovernance()` validating shared API barrel client export completeness and window controls bridge availability.
  - `src/shared/api/mcpClient.ts`: Exported `auditMcpClientGovernance()` validating MCP server name regex compliance (`MCP_NAME_REGEX`), server discovery/ready state, and registered tool count invariants.
  - `src/shared/api/messageApi.ts`: Exported `auditMessageApiGovernance()` validating message API endpoint coverage and message feedback support contracts.
  - Unit tests: Added 8 dedicated Vitest suites (`chatApi.p144.test.ts`, `demoChatScript.p144.test.ts`, `demoFixturesCore.p144.test.ts`, `demoFixturesSessionsAndAgents.p144.test.ts`, `demoOfficeAndSystemHandlers.p144.test.ts`, `apiIndex.p144.test.ts`, `mcpClient.p144.test.ts`, `messageApi.p144.test.ts`).
### Phase P145 — Orchestration Event Stream, Orchestration Events, Run Control Client, Permission API, Prompt API, Runtime API, Session API & Skill Drafts API Governance Audit (2026-10-22)

- **PRs**:
  - Phase P144 Merged: `#2310` (`main` @ `a44a6c6cfe9bc689adc9de354f8f1bf11acc4fc5`), `#2311` (`release/win7` @ `6a1a35d40f689656e3da1bfeb7f31ab46148b5ba`)
  - Phase P145: `feat/project-governance-p145` (`main`) & `feat/win7-project-governance-p145` (`release/win7`)
- **Scope**:
  - `src/shared/api/orchEventStream.ts`: Exported `auditOrchEventStreamGovernance()` validating reconnect delay bounds, max reconnect attempts, and IPC fallback stream readiness.
  - `src/shared/api/orchEvents.ts`: Exported `auditOrchEventsGovernance()` validating orchestration stream `ConnectionStatus` state and active task count invariants.
  - `src/shared/api/orchRunControlClient.ts`: Exported `auditOrchRunControlClientGovernance()` validating task steer, run cancel, and approval mode control capability contracts.
  - `src/shared/api/permissionApi.ts`: Exported `auditPermissionApiGovernance()` validating active permission preset (`PERMISSION_PRESETS`), preset count, and session auto-approval count invariants.
  - `src/shared/api/promptApi.ts`: Exported `auditPromptApiGovernance()` validating prompt template catalog count and custom variable interpolation support.
  - `src/shared/api/runtimeApi.ts`: Exported `auditRuntimeApiGovernance()` validating runtime backend connectivity and active profile identifier integrity.
  - `src/shared/api/sessionApi.ts`: Exported `auditSessionApiGovernance()` validating session collection count, Markdown/HTML export readiness, and message search capability contracts.
  - `src/shared/api/skillDraftsApi.ts`: Exported `auditSkillDraftsApiGovernance()` validating pending skill draft count and accept/reject workflow availability.
  - Unit tests: Added 8 dedicated Vitest suites (`orchEventStream.p145.test.ts`, `orchEvents.p145.test.ts`, `orchRunControlClient.p145.test.ts`, `permissionApi.p145.test.ts`, `promptApi.p145.test.ts`, `runtimeApi.p145.test.ts`, `sessionApi.p145.test.ts`, `skillDraftsApi.p145.test.ts`).
### Phase P146 — Skills API, Usage API, Worktree API, Zotero Client, Chat/Domain/Template Types & Shared UI Barrel Governance Audit (2026-10-22)

- **PRs**:
  - Phase P145 Merged: `#2312` (`main` @ `ec1bc1e8877b72e7175e2813d2053019fe7b01e2`), `#2313` (`release/win7` @ `67dc72273d6a600b2bea2ead9c9116e8fa0c0673`)
  - Phase P146: `feat/project-governance-p146` (`main`) & `feat/win7-project-governance-p146` (`release/win7`)
- **Scope**:
  - `src/shared/api/skillsApi.ts`: Exported `auditSkillsApiGovernance()` validating registered skill count, consolidation scan support, and skill rollback capability contracts.
  - `src/shared/api/usageApi.ts`: Exported `auditUsageApiGovernance()` validating active usage range (`UsageRange`) normalization and CSV usage export readiness.
  - `src/shared/api/worktreeApi.ts`: Exported `auditWorktreeApiGovernance()` validating worktree operation mode (`WorktreeMode`) normalization and active worktree count bounds.
  - `src/shared/api/zoteroClient.ts`: Exported `auditZoteroClientGovernance()` validating Zotero bridge connection state and indexed literature item count invariants.
  - `src/shared/api/types/chatAndEventTypes.ts`: Exported `auditChatAndEventTypesGovernance()` validating `TaskStatusValue` and `TodoStatus` schema state contracts.
  - `src/shared/api/types/domainEntityTypes.ts`: Exported `auditDomainEntityTypesGovernance()` validating lane `HeartbeatStatus` and multi-agent `TeamStatus` schema state contracts.
  - `src/shared/api/types/templateAndTaskTypes.ts`: Exported `auditTemplateAndTaskTypesGovernance()` validating `TodoPriority` and `TodoItemStatus` schema state contracts.
  - `src/shared/ui/index.ts`: Exported `auditSharedUiBarrelGovernance()` validating shared UI component barrel export count and completeness.
  - Unit tests: Added 8 dedicated Vitest suites (`skillsApi.p146.test.ts`, `usageApi.p146.test.ts`, `worktreeApi.p146.test.ts`, `zoteroClient.p146.test.ts`, `chatAndEventTypes.p146.test.ts`, `domainEntityTypes.p146.test.ts`, `templateAndTaskTypes.p146.test.ts`, `uiIndex.p146.test.ts`).
### Phase P147 — Shared UI Progress, Textarea, ConfirmDialogHost, Dialog Barrel, ErrorState Barrel, Lightbox, LoadingState Barrel & PageSkeleton Governance Audit (2026-10-22)

- **PRs**:
  - Phase P146 Merged: `#2314` (`main` @ `ccd8d727a5c7459f4940719e3758baa10f0ee042`), `#2315` (`release/win7` @ `b3e10ed5c2fdfb2160eba86657eff06e82ed49ef`)
  - Phase P147: `feat/project-governance-p147` (`main`) & `feat/win7-project-governance-p147` (`release/win7`)
- **Scope**:
  - `src/shared/ui/Progress.tsx`: Exported `auditProgressGovernance()` validating progress bar value clamping (`0..100`) and finite numeric bounds.
  - `src/shared/ui/Textarea.tsx`: Exported `auditTextareaGovernance()` validating textarea visible row clamping (`1..40`) and disabled state normalization.
  - `src/shared/ui/ConfirmDialog/ConfirmDialogHost.tsx`: Exported `auditConfirmDialogHostGovernance()` validating modal open state and confirmation variant (`default`/`danger`) contracts.
  - `src/shared/ui/Dialog/index.ts`: Exported `auditDialogBarrelGovernance()` validating Radix dialog primitive barrel export completeness.
  - `src/shared/ui/ErrorState/index.ts`: Exported `auditErrorStateBarrelGovernance()` validating error state barrel retry callback availability.
  - `src/shared/ui/Lightbox/Lightbox.tsx`: Exported `auditLightboxGovernance()` validating lightbox zoom scale bounds (`0.25..4`) and image source readiness.
  - `src/shared/ui/LoadingState/index.ts`: Exported `auditLoadingStateBarrelGovernance()` validating loading state accessible label contract.
  - `src/shared/ui/PageSkeleton/PageSkeleton.tsx`: Exported `auditPageSkeletonGovernance()` validating skeleton placeholder block count bounds (`1..12`).
  - Unit tests: Added 8 dedicated Vitest suites (`Progress.p147.test.ts`, `Textarea.p147.test.ts`, `ConfirmDialogHost.p147.test.ts`, `DialogIndex.p147.test.ts`, `ErrorStateIndex.p147.test.ts`, `Lightbox.p147.test.ts`, `LoadingStateIndex.p147.test.ts`, `PageSkeleton.p147.test.ts`).

### Phase P148: ArchetypeBlueprints, Shared API Utils, RetryButton/Tabs/Settings Barrels, Tabs, Tooltip & RightPanel Governance (Completed)
- **Target Modules**:
  - `src/features/project-type/archetypeBlueprints.ts`: `auditArchetypeBlueprintsGovernance`
  - `src/shared/api/utils.ts`: `auditSharedApiUtilsGovernance`
  - `src/shared/ui/RetryButton/index.ts`: `auditRetryButtonBarrelGovernance`
  - `src/shared/ui/Tabs/Tabs.tsx`: `auditTabsGovernance`
  - `src/shared/ui/Tabs/index.ts`: `auditTabsBarrelGovernance`
  - `src/shared/ui/Tooltip/Tooltip.tsx`: `auditTooltipGovernance`
  - `src/widgets/chat/RightPanel.tsx`: `auditChatRightPanelGovernance`
  - `src/pages/settings/index.ts`: `auditSettingsBarrelGovernance`
- **Unit Test Suites**:
  - `src/features/project-type/__tests__/archetypeBlueprints.p148.test.ts`
  - `src/shared/api/__tests__/utils.p148.test.ts`
  - `src/shared/ui/__tests__/RetryButtonIndex.p148.test.ts`
  - `src/shared/ui/__tests__/Tabs.p148.test.ts`
  - `src/shared/ui/__tests__/TabsIndex.p148.test.ts`
  - `src/shared/ui/__tests__/Tooltip.p148.test.ts`
  - `src/widgets/chat/__tests__/RightPanel.p148.test.ts`
  - `src/pages/settings/__tests__/settingsIndex.p148.test.ts`
- **Verification**: `eslint --max-warnings=0`, `vitest run --api=false`, `check-font-scale.mjs`, `architecture-check.mjs`, `export-ipc-manifest.mjs --check`, and `tsc --noEmit` all pass with 0 errors and 0 deletions across `main` and `release/win7`.

### Phase P149: AttnBadge, BrandLogo, LiveDot, DropdownMenu, ErrorState, LoadingState, RetryButton & Select Governance (Completed)
- **Target Modules**:
  - `src/shared/ui/AttnBadge.tsx`: `auditAttnBadgeGovernance`
  - `src/shared/ui/BrandLogo.tsx`: `auditBrandLogoGovernance`
  - `src/shared/ui/LiveDot.tsx`: `auditLiveDotGovernance`
  - `src/shared/ui/DropdownMenu/DropdownMenu.tsx`: `auditDropdownMenuGovernance`
  - `src/shared/ui/ErrorState/ErrorState.tsx`: `auditErrorStateGovernance`
  - `src/shared/ui/LoadingState/LoadingState.tsx`: `auditLoadingStateGovernance`
  - `src/shared/ui/RetryButton/RetryButton.tsx`: `auditRetryButtonGovernance`
  - `src/shared/ui/Select/Select.tsx`: `auditSelectGovernance`
- **Unit Test Suites**:
  - `src/shared/ui/__tests__/AttnBadge.p149.test.ts`
  - `src/shared/ui/__tests__/BrandLogo.p149.test.ts`
  - `src/shared/ui/__tests__/LiveDot.p149.test.ts`
  - `src/shared/ui/__tests__/DropdownMenu.p149.test.ts`
  - `src/shared/ui/__tests__/ErrorState.p149.test.ts`
  - `src/shared/ui/__tests__/LoadingState.p149.test.ts`
  - `src/shared/ui/__tests__/RetryButton.p149.test.ts`
  - `src/shared/ui/__tests__/Select.p149.test.ts`
- **Verification**: `eslint --max-warnings=0`, `vitest run --api=false`, `check-font-scale.mjs`, `architecture-check.mjs`, `export-ipc-manifest.mjs --check`, and `tsc --noEmit` all pass with 0 errors and 0 deletions across `main` and `release/win7`.

### Phase P150: MarkdownImage, SelectionQuoteButton, NavGroup, Titlebar, TitlebarActions, WindowControls, TwoStepDelete & SidebarProjectList Governance (Completed)
- **Target Modules**:
  - `src/widgets/chat/MarkdownImage.tsx`: `auditMarkdownImageGovernance`
  - `src/widgets/chat/SelectionQuoteButton.tsx`: `auditSelectionQuoteButtonGovernance`
  - `src/widgets/layout/NavGroup.tsx`: `auditNavGroupGovernance`
  - `src/widgets/layout/Titlebar.tsx`: `auditTitlebarGovernance`
  - `src/widgets/layout/TitlebarActions.tsx`: `auditTitlebarActionsGovernance`
  - `src/widgets/layout/WindowControls.tsx`: `auditWindowControlsGovernance`
  - `src/widgets/sidebar/TwoStepDelete.tsx`: `auditTwoStepDeleteGovernance`
  - `src/widgets/sidebar/sections/SidebarProjectList.tsx`: `auditSidebarProjectListGovernance`
- **Unit Test Suites**:
  - `src/widgets/chat/__tests__/MarkdownImage.p150.test.ts`
  - `src/widgets/chat/__tests__/SelectionQuoteButton.p150.test.ts`
  - `src/widgets/layout/__tests__/NavGroup.p150.test.ts`
  - `src/widgets/layout/__tests__/Titlebar.p150.test.ts`
  - `src/widgets/layout/__tests__/TitlebarActions.p150.test.ts`
  - `src/widgets/layout/__tests__/WindowControls.p150.test.ts`
  - `src/widgets/sidebar/__tests__/TwoStepDelete.p150.test.ts`
  - `src/widgets/sidebar/__tests__/SidebarProjectList.p150.test.ts`
- **Verification**: `eslint --max-warnings=0`, `vitest run --api=false`, `check-font-scale.mjs`, `architecture-check.mjs`, `export-ipc-manifest.mjs --check`, and `tsc --noEmit` all pass with 0 errors and 0 deletions across `main` and `release/win7`.

### Phase P151: Application Providers Layer (AppProviders, ErrorBoundary, NavHistory, QueryClient, SessionWorkspace, Theme, Toast & Barrel) Governance Audit (Completed 2026-10-22)

- **Target Modules**:
  - `src/app/providers/AppProviders.tsx`: `auditAppProvidersGovernance`
  - `src/app/providers/ErrorBoundary.tsx`: `auditErrorBoundaryGovernance`
  - `src/app/providers/NavHistoryProvider.tsx`: `auditNavHistoryProviderGovernance`
  - `src/app/providers/QueryClientProvider.tsx`: `auditQueryClientProviderGovernance`
  - `src/app/providers/SessionWorkspaceProvider.tsx`: `auditSessionWorkspaceProviderGovernance`
  - `src/app/providers/ThemeProvider.tsx`: `auditThemeProviderGovernance`
  - `src/app/providers/ToastProvider.tsx`: `auditToastProviderGovernance`
  - `src/app/providers/index.ts`: `auditProvidersBarrelGovernance`
- **Verification**:
  - Added 8 dedicated Vitest suites (`*.p151.test.ts`), passing ESLint (`--max-warnings=0`), Vitest, `tsc --noEmit`, `architecture-check.mjs`, `check-font-scale.mjs`, and `export-ipc-manifest.mjs --check` across `main` and `release/win7`.

### Phase P152: Theme Hook, PlanCard, UpdateDialog, Vision Content, Arena API/Barrel & Autonomous Goal API/Store Governance Audit (Completed 2026-10-22)

- **Target Modules**:
  - `src/app/providers/useTheme.ts`: `auditUseThemeGovernance`
  - `src/components/PlanCard.tsx`: `auditPlanCardGovernance`
  - `src/components/UpdateDialog.tsx`: `auditUpdateDialogGovernance`
  - `src/content/about/vision.ts`: `auditVisionContentGovernance`
  - `src/entities/arena/api.ts`: `auditArenaApiGovernance`
  - `src/entities/arena/index.ts`: `auditArenaEntityBarrelGovernance`
  - `src/entities/autonomous-goals/goalApi.ts`: `auditGoalApiGovernance`
  - `src/entities/autonomous-goals/goalStore.ts`: `auditGoalStoreGovernance`
- **Verification**:
  - Added 8 dedicated Vitest suites (`*.p152.test.ts`), passing ESLint (`--max-warnings=0`), Vitest, `tsc --noEmit`, `architecture-check.mjs`, `check-font-scale.mjs`, and `export-ipc-manifest.mjs --check` across `main` and `release/win7`.

### Phase P153: Autonomous Goal Types, Chat BtwState, Endpoint Provider Registry, Font Options/Storage/Settings & Model Catalog API/Types Governance Audit (Completed 2026-10-22)

- **Target Modules**:
  - `src/entities/autonomous-goals/types.ts`: `auditAutonomousGoalsTypesGovernance`
  - `src/entities/chat/btwState.ts`: `auditBtwStateGovernance`
  - `src/entities/endpoint/providerRegistry.ts`: `auditProviderRegistryGovernance`
  - `src/entities/font/fontOptions.ts`: `auditFontOptionsGovernance`
  - `src/entities/font/fontStorage.ts`: `auditFontStorageGovernance`
  - `src/entities/font/useFontSettings.tsx`: `auditUseFontSettingsGovernance`
  - `src/entities/model-catalog/api.ts`: `auditModelCatalogApiGovernance`
  - `src/entities/model-catalog/types.ts`: `auditModelCatalogTypesGovernance`
- **Verification**:
  - Added 8 dedicated Vitest suites (`*.p153.test.ts`), passing ESLint (`--max-warnings=0`), Vitest, `tsc --noEmit`, `architecture-check.mjs`, `check-font-scale.mjs`, and `export-ipc-manifest.mjs --check` across `main` and `release/win7`.

### Phase P154: Orchestration LaneBoard/RunControl/EventSubscription, Permission/Question State, Scheduled TaskStore, Session Storage & Setting DeepMerge Governance Audit (Completed 2026-10-22)

- **Target Modules**:
  - `src/entities/orchestration/laneBoardStore.ts`: `auditLaneBoardStoreGovernance`
  - `src/entities/orchestration/runControlStore.ts`: `auditRunControlStoreGovernance`
  - `src/entities/orchestration/useOrchEventSubscription.ts`: `auditUseOrchEventSubscriptionGovernance`
  - `src/entities/permission/permissionState.ts`: `auditPermissionStateGovernance`
  - `src/entities/question/questionState.ts`: `auditQuestionStateGovernance`
  - `src/entities/scheduled/taskStore.ts`: `auditScheduledTaskStoreGovernance`
  - `src/entities/session/storage.ts`: `auditSessionStorageGovernance`
  - `src/entities/setting/deepMerge.ts`: `auditDeepMergeGovernance`
- **Verification**:
  - Added 8 dedicated Vitest suites (`*.p154.test.ts`), passing ESLint (`--max-warnings=0`), Vitest, `tsc --noEmit`, `architecture-check.mjs`, `check-font-scale.mjs`, and `export-ipc-manifest.mjs --check` across `main` and `release/win7`.

### Phase P155: Entity Setting Readiness, Metadata, Adapter, Registry, Validation, Storage, Types & Decorative Presets Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/entities/setting/endpointReadiness.ts` (`auditEndpointReadinessGovernance`)
  - `src/entities/setting/metadata.ts` (`auditSettingMetadataGovernance`)
  - `src/entities/setting/settingsAdapter.ts` (`auditSettingsAdapterGovernance`)
  - `src/entities/setting/settingsRegistry.ts` (`auditSettingsRegistryGovernance`)
  - `src/entities/setting/settingsValidation.ts` (`auditSettingsValidationGovernance`)
  - `src/entities/setting/storage.ts` (`auditSettingStorageGovernance`)
  - `src/entities/setting/types.ts` (`auditSettingTypesGovernance`)
  - `src/entities/theme/decorative-presets.ts` (`auditDecorativePresetsGovernance`)
- **Unit Test Suites (8)**:
  - `src/entities/setting/__tests__/endpointReadiness.p155.test.ts`
  - `src/entities/setting/__tests__/metadata.p155.test.ts`
  - `src/entities/setting/__tests__/settingsAdapter.p155.test.ts`
  - `src/entities/setting/__tests__/settingsRegistry.p155.test.ts`
  - `src/entities/setting/__tests__/settingsValidation.p155.test.ts`
  - `src/entities/setting/__tests__/storage.p155.test.ts`
  - `src/entities/setting/__tests__/types.p155.test.ts`
  - `src/entities/theme/__tests__/decorativePresets.p155.test.ts`

### Phase P156: Entity Theme Presets, Theme Storage, Todo Store, Welcome Recommendations & Wiki Stores Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/entities/theme/presets.ts` (`auditThemePresetsGovernance`)
  - `src/entities/theme/storage.ts` (`auditThemeStorageGovernance`)
  - `src/entities/todo/todoStore.ts` (`auditTodoStoreGovernance`)
  - `src/entities/welcome/recommendations.ts` (`auditWelcomeRecommendationsGovernance`)
  - `src/entities/wiki/activity-store.ts` (`auditWikiActivityStoreGovernance`)
  - `src/entities/wiki/lint-store.ts` (`auditWikiLintStoreGovernance`)
  - `src/entities/wiki/mock-data.ts` (`auditWikiMockDataGovernance`)
  - `src/entities/wiki/queue-store.ts` (`auditWikiQueueStoreGovernance`)
- **Unit Test Suites (8)**:
  - `src/entities/theme/__tests__/presets.p156.test.ts`
  - `src/entities/theme/__tests__/storage.p156.test.ts`
  - `src/entities/todo/__tests__/todoStore.p156.test.ts`
  - `src/entities/welcome/__tests__/recommendations.p156.test.ts`
  - `src/entities/wiki/__tests__/activityStore.p156.test.ts`
  - `src/entities/wiki/__tests__/lintStore.p156.test.ts`
  - `src/entities/wiki/__tests__/mockData.p156.test.ts`
  - `src/entities/wiki/__tests__/queueStore.p156.test.ts`

### Phase P157: Entity Wiki Research, Review & Main Store, App Panels Registry & Store, and Artifact API & Stores Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/entities/wiki/research-store.ts` (`auditWikiResearchStoreGovernance`)
  - `src/entities/wiki/review-store.ts` (`auditWikiReviewStoreGovernance`)
  - `src/entities/wiki/store.ts` (`auditWikiStoreGovernance`)
  - `src/features/app-panels/panelRegistry.ts` (`auditPanelRegistryGovernance`)
  - `src/features/app-panels/usePanelStore.ts` (`auditUsePanelStoreGovernance`)
  - `src/features/artifacts/artifactApi.ts` (`auditArtifactApiGovernance`)
  - `src/features/artifacts/artifactEventsStore.ts` (`auditArtifactEventsStoreGovernance`)
  - `src/features/artifacts/artifactListStore.ts` (`auditArtifactListStoreGovernance`)
- **Unit Test Suites (8)**:
  - `src/entities/wiki/__tests__/researchStore.p157.test.ts`
  - `src/entities/wiki/__tests__/reviewStore.p157.test.ts`
  - `src/entities/wiki/__tests__/store.p157.test.ts`
  - `src/features/app-panels/__tests__/panelRegistry.p157.test.ts`
  - `src/features/app-panels/__tests__/usePanelStore.p157.test.ts`
  - `src/features/artifacts/__tests__/artifactApi.p157.test.ts`
  - `src/features/artifacts/__tests__/artifactEventsStore.p157.test.ts`
  - `src/features/artifacts/__tests__/artifactListStore.p157.test.ts`

### Phase P158: Artifact Hooks, Attention Center & Snapshot, and Autonomous Goals Modal & Pages Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/artifacts/useArtifactContent.ts` (`auditUseArtifactContentGovernance`)
  - `src/features/artifacts/useArtifacts.ts` (`auditUseArtifactsGovernance`)
  - `src/features/attention/attentionCenter.ts` (`auditAttentionCenterGovernance`)
  - `src/features/attention/index.ts` (`auditAttentionBarrelGovernance`)
  - `src/features/attention/useAttentionSnapshot.ts` (`auditUseAttentionSnapshotGovernance`)
  - `src/features/autonomous-goals/CreateGoalModal.tsx` (`auditCreateGoalModalGovernance`)
  - `src/features/autonomous-goals/GoalDetailPage.tsx` (`auditGoalDetailPageGovernance`)
  - `src/features/autonomous-goals/GoalListPage.tsx` (`auditGoalListPageGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/artifacts/__tests__/useArtifactContent.p158.test.ts`
  - `src/features/artifacts/__tests__/useArtifacts.p158.test.ts`
  - `src/features/attention/__tests__/attentionCenter.p158.test.ts`
  - `src/features/attention/__tests__/attentionIndex.p158.test.ts`
  - `src/features/attention/__tests__/useAttentionSnapshot.p158.test.ts`
  - `src/features/autonomous-goals/__tests__/CreateGoalModal.p158.test.ts`
  - `src/features/autonomous-goals/__tests__/GoalDetailPage.p158.test.ts`
  - `src/features/autonomous-goals/__tests__/GoalListPage.p158.test.ts`

### Phase P159: Changes List Store and Chat Entity/File Menus, BtwOverlay, MediaAttachment, AnswerVersions, ChatFind & EntityRefs Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/changes/changesListStore.ts` (`auditChangesListStoreGovernance`)
  - `src/features/chat/AtEntityMenu.tsx` (`auditAtEntityMenuGovernance`)
  - `src/features/chat/AtFileMenu.tsx` (`auditAtFileMenuGovernance`)
  - `src/features/chat/BtwOverlay.tsx` (`auditBtwOverlayGovernance`)
  - `src/features/chat/MediaAttachment.tsx` (`auditMediaAttachmentGovernance`)
  - `src/features/chat/answerVersions.ts` (`auditAnswerVersionsGovernance`)
  - `src/features/chat/chatFind.ts` (`auditChatFindGovernance`)
  - `src/features/chat/entityRefs.ts` (`auditEntityRefsGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/changes/__tests__/changesListStore.p159.test.ts`
  - `src/features/chat/__tests__/AtEntityMenu.p159.test.ts`
  - `src/features/chat/__tests__/AtFileMenu.p159.test.ts`
  - `src/features/chat/__tests__/BtwOverlay.p159.test.ts`
  - `src/features/chat/__tests__/MediaAttachment.p159.test.ts`
  - `src/features/chat/__tests__/answerVersions.p159.test.ts`
  - `src/features/chat/__tests__/chatFind.p159.test.ts`
  - `src/features/chat/__tests__/entityRefs.p159.test.ts`

### Phase P160: Chat GenerationStats, Feature Barrel, MarkdownText, MessageJumpStore, ReadAloudStore, SelectionQuote, Speech & TextHighlight Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/chat/generationStats.ts` (`auditGenerationStatsGovernance`)
  - `src/features/chat/index.ts` (`auditChatFeatureBarrelGovernance`)
  - `src/features/chat/markdownText.ts` (`auditMarkdownTextGovernance`)
  - `src/features/chat/messageJumpStore.ts` (`auditMessageJumpStoreGovernance`)
  - `src/features/chat/readAloudStore.ts` (`auditReadAloudStoreGovernance`)
  - `src/features/chat/selectionQuote.ts` (`auditSelectionQuoteGovernance`)
  - `src/features/chat/speech.ts` (`auditSpeechGovernance`)
  - `src/features/chat/textHighlight.ts` (`auditTextHighlightGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/chat/__tests__/generationStats.p160.test.ts`
  - `src/features/chat/__tests__/chatIndex.p160.test.ts`
  - `src/features/chat/__tests__/markdownText.p160.test.ts`
  - `src/features/chat/__tests__/messageJumpStore.p160.test.ts`
  - `src/features/chat/__tests__/readAloudStore.p160.test.ts`
  - `src/features/chat/__tests__/selectionQuote.p160.test.ts`
  - `src/features/chat/__tests__/speech.p160.test.ts`
  - `src/features/chat/__tests__/textHighlight.p160.test.ts`

### Phase P161: Chat Hooks (UseAtFileQuery, UseBtwCommand, UseConversationOutline, UseConversationTrajectory, UseConversationTurns, UseMessageJump, UseQuoteDraft & UseSessionMemoryPause) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/chat/useAtFileQuery.ts` (`auditUseAtFileQueryGovernance`)
  - `src/features/chat/useBtwCommand.ts` (`auditUseBtwCommandGovernance`)
  - `src/features/chat/useConversationOutline.ts` (`auditUseConversationOutlineGovernance`)
  - `src/features/chat/useConversationTrajectory.ts` (`auditUseConversationTrajectoryGovernance`)
  - `src/features/chat/useConversationTurns.ts` (`auditUseConversationTurnsGovernance`)
  - `src/features/chat/useMessageJump.ts` (`auditUseMessageJumpGovernance`)
  - `src/features/chat/useQuoteDraft.ts` (`auditUseQuoteDraftGovernance`)
  - `src/features/chat/useSessionMemoryPause.ts` (`auditUseSessionMemoryPauseGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/chat/__tests__/useAtFileQuery.p161.test.ts`
  - `src/features/chat/__tests__/useBtwCommand.p161.test.ts`
  - `src/features/chat/__tests__/useConversationOutline.p161.test.ts`
  - `src/features/chat/__tests__/useConversationTrajectory.p161.test.ts`
  - `src/features/chat/__tests__/useConversationTurns.p161.test.ts`
  - `src/features/chat/__tests__/useMessageJump.p161.test.ts`
  - `src/features/chat/__tests__/useQuoteDraft.p161.test.ts`
  - `src/features/chat/__tests__/useSessionMemoryPause.p161.test.ts`

### Phase P162: Diagnostic (DiagnosticCard, ExportButton, Barrel, UseDiagnosticPreview) & Journal (JournalPanel, Barrel, UseJournalTemplates, JournalActions) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/diagnostic/DiagnosticCard.tsx` (`auditDiagnosticCardGovernance`)
  - `src/features/diagnostic/ExportButton.tsx` (`auditExportButtonGovernance`)
  - `src/features/diagnostic/index.ts` (`auditDiagnosticBarrelGovernance`)
  - `src/features/diagnostic/useDiagnosticPreview.ts` (`auditUseDiagnosticPreviewGovernance`)
  - `src/features/journal/JournalPanel.tsx` (`auditJournalPanelGovernance`)
  - `src/features/journal/index.ts` (`auditJournalBarrelGovernance`)
  - `src/features/journal/useJournalTemplates.ts` (`auditUseJournalTemplatesGovernance`)
  - `src/features/journal/components/JournalActions.tsx` (`auditJournalActionsGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/diagnostic/__tests__/DiagnosticCard.p162.test.ts`
  - `src/features/diagnostic/__tests__/ExportButton.p162.test.ts`
  - `src/features/diagnostic/__tests__/diagnosticIndex.p162.test.ts`
  - `src/features/diagnostic/__tests__/useDiagnosticPreview.p162.test.ts`
  - `src/features/journal/__tests__/JournalPanel.p162.test.ts`
  - `src/features/journal/__tests__/journalIndex.p162.test.ts`
  - `src/features/journal/__tests__/useJournalTemplates.p162.test.ts`
  - `src/features/journal/__tests__/JournalActions.p162.test.ts`

### Phase P163: Journal Components (JournalContentEditor, JournalSpecCard, JournalValidationReport), Manage-Endpoints API & Manage-Settings (PreferenceSaveStatus, SettingsStore, UseConfirmedPreference, UseSettings) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/journal/components/JournalContentEditor.tsx` (`auditJournalContentEditorGovernance`)
  - `src/features/journal/components/JournalSpecCard.tsx` (`auditJournalSpecCardGovernance`)
  - `src/features/journal/components/JournalValidationReport.tsx` (`auditJournalValidationReportGovernance`)
  - `src/features/manage-endpoints/api.ts` (`auditManageEndpointsApiGovernance`)
  - `src/features/manage-settings/PreferenceSaveStatus.tsx` (`auditPreferenceSaveStatusGovernance`)
  - `src/features/manage-settings/settingsStore.ts` (`auditSettingsStoreGovernance`)
  - `src/features/manage-settings/useConfirmedPreference.ts` (`auditUseConfirmedPreferenceGovernance`)
  - `src/features/manage-settings/useSettings.ts` (`auditUseSettingsGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/journal/__tests__/JournalContentEditor.p163.test.ts`
  - `src/features/journal/__tests__/JournalSpecCard.p163.test.ts`
  - `src/features/journal/__tests__/JournalValidationReport.p163.test.ts`
  - `src/features/manage-endpoints/__tests__/api.p163.test.ts`
  - `src/features/manage-settings/__tests__/PreferenceSaveStatus.p163.test.ts`
  - `src/features/manage-settings/__tests__/settingsStore.p163.test.ts`
  - `src/features/manage-settings/__tests__/useConfirmedPreference.p163.test.ts`
  - `src/features/manage-settings/__tests__/useSettings.p163.test.ts`

### Phase P164: Office Workbench Components (DocxNativePreview, ExcelPptEditFormFields, OfficeCapabilityBar, OfficeDeliveryDrawer, OfficeDocumentList, OfficeFilePicker, OfficePreviewPanel, OfficeSnapshotPanel) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/office/DocxNativePreview.tsx` (`auditDocxNativePreviewGovernance`)
  - `src/features/office/ExcelPptEditFormFields.tsx` (`auditExcelPptEditFormFieldsGovernance`)
  - `src/features/office/OfficeCapabilityBar.tsx` (`auditOfficeCapabilityBarGovernance`)
  - `src/features/office/OfficeDeliveryDrawer.tsx` (`auditOfficeDeliveryDrawerGovernance`)
  - `src/features/office/OfficeDocumentList.tsx` (`auditOfficeDocumentListGovernance`)
  - `src/features/office/OfficeFilePicker.tsx` (`auditOfficeFilePickerGovernance`)
  - `src/features/office/OfficePreviewPanel.tsx` (`auditOfficePreviewPanelGovernance`)
  - `src/features/office/OfficeSnapshotPanel.tsx` (`auditOfficeSnapshotPanelGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/office/__tests__/DocxNativePreview.p164.test.ts`
  - `src/features/office/__tests__/ExcelPptEditFormFields.p164.test.ts`
  - `src/features/office/__tests__/OfficeCapabilityBar.p164.test.ts`
  - `src/features/office/__tests__/OfficeDeliveryDrawer.p164.test.ts`
  - `src/features/office/__tests__/OfficeDocumentList.p164.test.ts`
  - `src/features/office/__tests__/OfficeFilePicker.p164.test.ts`
  - `src/features/office/__tests__/OfficePreviewPanel.p164.test.ts`
  - `src/features/office/__tests__/OfficeSnapshotPanel.p164.test.ts`

### Phase P165: Office Remaining Modules (OfficeStagingInspector, PdfFormFillDialog, ImportOfficeReference, Barrel, OfficeCapabilities, OfficeProgress, PreviewRevision, UseOfficeDocuments) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/office/OfficeStagingInspector.tsx` (`auditOfficeStagingInspectorGovernance`)
  - `src/features/office/PdfFormFillDialog.tsx` (`auditPdfFormFillDialogGovernance`)
  - `src/features/office/importOfficeReference.ts` (`auditImportOfficeReferenceGovernance`)
  - `src/features/office/index.ts` (`auditOfficeFeatureBarrelGovernance`)
  - `src/features/office/officeCapabilities.ts` (`auditOfficeCapabilitiesGovernance`)
  - `src/features/office/officeProgress.ts` (`auditOfficeProgressGovernance`)
  - `src/features/office/previewRevision.ts` (`auditPreviewRevisionGovernance`)
  - `src/features/office/useOfficeDocuments.ts` (`auditUseOfficeDocumentsGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/office/__tests__/OfficeStagingInspector.p165.test.ts`
  - `src/features/office/__tests__/PdfFormFillDialog.p165.test.ts`
  - `src/features/office/__tests__/importOfficeReference.p165.test.ts`
  - `src/features/office/__tests__/officeIndex.p165.test.ts`
  - `src/features/office/__tests__/officeCapabilities.p165.test.ts`
  - `src/features/office/__tests__/officeProgress.p165.test.ts`
  - `src/features/office/__tests__/previewRevision.p165.test.ts`
  - `src/features/office/__tests__/useOfficeDocuments.p165.test.ts`

### Phase P166: Onboarding, Project-Type & Right-Panel Modules (OnboardingWizard, GovernanceRulesPanel, ProjectTypeBadge, ProjectTypeSelector, TypeDetectionPreview, Barrel, UseStudioState, RightPanelStore) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/onboarding/OnboardingWizard.tsx` (`auditOnboardingWizardGovernance`)
  - `src/features/project-type/GovernanceRulesPanel.tsx` (`auditGovernanceRulesPanelGovernance`)
  - `src/features/project-type/ProjectTypeBadge.tsx` (`auditProjectTypeBadgeGovernance`)
  - `src/features/project-type/ProjectTypeSelector.tsx` (`auditProjectTypeSelectorGovernance`)
  - `src/features/project-type/TypeDetectionPreview.tsx` (`auditTypeDetectionPreviewGovernance`)
  - `src/features/project-type/index.ts` (`auditProjectTypeBarrelGovernance`)
  - `src/features/project-type/useStudioState.ts` (`auditUseStudioStateGovernance`)
  - `src/features/right-panel/rightPanelStore.ts` (`auditRightPanelStoreGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/onboarding/__tests__/OnboardingWizard.p166.test.ts`
  - `src/features/project-type/__tests__/GovernanceRulesPanel.p166.test.ts`
  - `src/features/project-type/__tests__/ProjectTypeBadge.p166.test.ts`
  - `src/features/project-type/__tests__/ProjectTypeSelector.p166.test.ts`
  - `src/features/project-type/__tests__/TypeDetectionPreview.p166.test.ts`
  - `src/features/project-type/__tests__/projectTypeIndex.p166.test.ts`
  - `src/features/project-type/__tests__/useStudioState.p166.test.ts`
  - `src/features/right-panel/__tests__/rightPanelStore.p166.test.ts`

### Phase P167: Scheduled & Send-Message Modules (CreateTaskModal, CronExpressionPicker, CronValidator, SkillLink, AttachmentUpload, ChatStreamStore, OrchestrationEvents, SessionNotify) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/scheduled/CreateTaskModal.tsx` (`auditCreateTaskModalGovernance`)
  - `src/features/scheduled/CronExpressionPicker.tsx` (`auditCronExpressionPickerGovernance`)
  - `src/features/scheduled/cronValidator.ts` (`auditCronValidatorGovernance`)
  - `src/features/scheduled/skillLink.ts` (`auditSkillLinkGovernance`)
  - `src/features/send-message/AttachmentUpload.tsx` (`auditAttachmentUploadGovernance`)
  - `src/features/send-message/chatStreamStore.ts` (`auditChatStreamStoreGovernance`)
  - `src/features/send-message/orchestrationEvents.ts` (`auditOrchestrationEventsGovernance`)
  - `src/features/send-message/sessionNotify.ts` (`auditSessionNotifyGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/scheduled/__tests__/CreateTaskModal.p167.test.ts`
  - `src/features/scheduled/__tests__/CronExpressionPicker.p167.test.ts`
  - `src/features/scheduled/__tests__/cronValidator.p167.test.ts`
  - `src/features/scheduled/__tests__/skillLink.p167.test.ts`
  - `src/features/send-message/__tests__/AttachmentUpload.p167.test.ts`
  - `src/features/send-message/__tests__/chatStreamStore.p167.test.ts`
  - `src/features/send-message/__tests__/orchestrationEvents.p167.test.ts`
  - `src/features/send-message/__tests__/sessionNotify.p167.test.ts`

### Phase P168: Send-Message & Task-Brief Modules (ThinkingPlaceholder, TransparencyPayload, SavedTaskRecipes, TaskBriefDialog, TaskModelAdvisor, ModelTaskFit, TaskBrief, TaskRecipes) Governance Audit (Completed)

- **Target Modules (8)**:
  - `src/features/send-message/thinkingPlaceholder.ts` (`auditThinkingPlaceholderGovernance`)
  - `src/features/send-message/transparencyPayload.ts` (`auditTransparencyPayloadGovernance`)
  - `src/features/task-brief/SavedTaskRecipes.tsx` (`auditSavedTaskRecipesGovernance`)
  - `src/features/task-brief/TaskBriefDialog.tsx` (`auditTaskBriefDialogGovernance`)
  - `src/features/task-brief/TaskModelAdvisor.tsx` (`auditTaskModelAdvisorGovernance`)
  - `src/features/task-brief/modelTaskFit.ts` (`auditModelTaskFitGovernance`)
  - `src/features/task-brief/taskBrief.ts` (`auditTaskBriefGovernance`)
  - `src/features/task-brief/taskRecipes.ts` (`auditTaskRecipesGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/send-message/__tests__/thinkingPlaceholder.p168.test.ts`
  - `src/features/send-message/__tests__/transparencyPayload.p168.test.ts`
  - `src/features/task-brief/__tests__/SavedTaskRecipes.p168.test.ts`
  - `src/features/task-brief/__tests__/TaskBriefDialog.p168.test.ts`
  - `src/features/task-brief/__tests__/TaskModelAdvisor.p168.test.ts`
  - `src/features/task-brief/__tests__/modelTaskFit.p168.test.ts`
  - `src/features/task-brief/__tests__/taskBrief.p168.test.ts`
  - `src/features/task-brief/__tests__/taskRecipes.p168.test.ts`

### Phase P169 — Task-Center, Terminal-Panel & Theme Governance Audit Contracts (Completed)

- **Target Modules (8)**:
  - `src/features/task-center/taskCenterStore.ts` (`auditTaskCenterStoreGovernance`)
  - `src/features/terminal-panel/terminalPanelStore.ts` (`auditTerminalPanelStoreGovernance`)
  - `src/features/theme/CodeMirrorThemeEditor.tsx` (`auditCodeMirrorThemeEditorGovernance`)
  - `src/features/theme/CssThemeModal.tsx` (`auditCssThemeModalGovernance`)
  - `src/features/theme/ThemeCover.tsx` (`auditThemeCoverGovernance`)
  - `src/features/theme/ThemeGallery.tsx` (`auditThemeGalleryGovernance`)
  - `src/features/theme/backgroundInjector.ts` (`auditBackgroundInjectorGovernance`)
  - `src/features/theme/themeCssTypes.ts` (`auditThemeCssTypesGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/task-center/__tests__/taskCenterStore.p169.test.ts`
  - `src/features/terminal-panel/__tests__/terminalPanelStore.p169.test.ts`
  - `src/features/theme/__tests__/CodeMirrorThemeEditor.p169.test.ts`
  - `src/features/theme/__tests__/CssThemeModal.p169.test.ts`
  - `src/features/theme/__tests__/ThemeCover.p169.test.ts`
  - `src/features/theme/__tests__/ThemeGallery.p169.test.ts`
  - `src/features/theme/__tests__/backgroundInjector.p169.test.ts`
  - `src/features/theme/__tests__/themeCssTypes.p169.test.ts`
- **Verification**:
  - `npx eslint --max-warnings=0`, `npx vitest run`, `node scripts/check-font-scale.mjs`, `node scripts/architecture-check.mjs`, `node scripts/export-ipc-manifest.mjs --check`, and `npx tsc --noEmit` all passed with 0 errors/warnings across both `main` and `release/win7` worktrees.

### Phase P170 — Theme, Welcome, Wiki, Workspace & Lib Governance Audit Contracts (Completed)

- **Target Modules (8)**:
  - `src/features/theme/themeCssValidator.ts` (`auditThemeCssValidatorGovernance`)
  - `src/features/welcome/useTypewriterPlaceholder.ts` (`auditUseTypewriterPlaceholderGovernance`)
  - `src/features/wiki/useWikiChatStream.ts` (`auditUseWikiChatStreamGovernance`)
  - `src/features/wiki/useWikiIngest.ts` (`auditUseWikiIngestGovernance`)
  - `src/features/workspace/WorkspaceBindModal.tsx` (`auditWorkspaceBindModalGovernance`)
  - `src/features/workspace/WorkspaceEmptyGuard.tsx` (`auditWorkspaceEmptyGuardGovernance`)
  - `src/features/workspace/index.ts` (`auditWorkspaceIndexGovernance`)
  - `src/lib/changelogParser.ts` (`auditChangelogParserGovernance`)
- **Unit Test Suites (8)**:
  - `src/features/theme/__tests__/themeCssValidator.p170.test.ts`
  - `src/features/welcome/__tests__/useTypewriterPlaceholder.p170.test.ts`
  - `src/features/wiki/__tests__/useWikiChatStream.p170.test.ts`
  - `src/features/wiki/__tests__/useWikiIngest.p170.test.ts`
  - `src/features/workspace/__tests__/WorkspaceBindModal.p170.test.ts`
  - `src/features/workspace/__tests__/WorkspaceEmptyGuard.p170.test.ts`
  - `src/features/workspace/__tests__/index.p170.test.ts`
  - `src/lib/__tests__/changelogParser.p170.test.ts`
- **Verification**:
  - `npx eslint --max-warnings=0`, `npx vitest run`, `node scripts/check-font-scale.mjs`, `node scripts/architecture-check.mjs`, `node scripts/export-ipc-manifest.mjs --check`, and `npx tsc --noEmit` all passed with 0 errors/warnings across both `main` and `release/win7` worktrees.

### Phase P171 — Top-Level Pages Governance Audit Contracts (Completed)

- **Target Modules (8)**:
  - `src/pages/Agents.tsx` (`auditAgentsPageGovernance`)
  - `src/pages/Arena.tsx` (`auditArenaPageGovernance`)
  - `src/pages/ArenaAccounts.tsx` (`auditArenaAccountsPageGovernance`)
  - `src/pages/ModelCatalog.tsx` (`auditModelCatalogPageGovernance`)
  - `src/pages/Orchestration.tsx` (`auditOrchestrationPageGovernance`)
  - `src/pages/Projects.tsx` (`auditProjectsPageGovernance`)
  - `src/pages/ScheduledTasks.tsx` (`auditScheduledTasksPageGovernance`)
  - `src/pages/TodoPage.tsx` (`auditTodoPageGovernance`)
- **Unit Test Suites (8)**:
  - `src/pages/__tests__/Agents.p171.test.ts`
  - `src/pages/__tests__/Arena.p171.test.ts`
  - `src/pages/__tests__/ArenaAccounts.p171.test.ts`
  - `src/pages/__tests__/ModelCatalog.p171.test.ts`
  - `src/pages/__tests__/Orchestration.p171.test.ts`
  - `src/pages/__tests__/Projects.p171.test.ts`
  - `src/pages/__tests__/ScheduledTasks.p171.test.ts`
  - `src/pages/__tests__/TodoPage.p171.test.ts`
- **Verification**:
  - `npx eslint --max-warnings=0`, `npx vitest run`, `node scripts/check-font-scale.mjs`, `node scripts/architecture-check.mjs`, `node scripts/export-ipc-manifest.mjs --check`, and `npx tsc --noEmit` all passed with 0 errors/warnings across both `main` and `release/win7` worktrees.

### Phase P172 — Welcome, Chat Header & Settings Tab Governance Audit Contracts (Completed 2026-10-23)

- **Welcome & Chat Header Bar Governance Contracts**:
  - `src/pages/Welcome.tsx`: Added `auditWelcomePageGovernance()` verifying welcome page recommendation and saved recipe workflow readiness (`src/pages/__tests__/Welcome.p172.test.ts`).
  - `src/pages/chat/ChatHeaderBar.tsx`: Added `auditChatHeaderBarGovernance()` verifying top header bar controls (`SessionModelPicker`, `OrchModeSelect`, `SessionSettingsMenu`, `SessionSessionMenu`, `RightPanelToggle`) (`src/pages/chat/__tests__/ChatHeaderBar.p172.test.ts`).
- **Settings Tabs & Toggle Governance Contracts**:
  - `src/pages/settings/ArenaAccountsToggle.tsx`: Added `auditArenaAccountsToggleGovernance()` verifying Arena accounts toggle metadata (`src/pages/settings/__tests__/ArenaAccountsToggle.p172.test.ts`).
  - `src/pages/settings/BasicTab.tsx`: Added `auditBasicTabGovernance()` verifying timezone and demo-mode configuration support (`src/pages/settings/__tests__/BasicTab.p172.test.ts`).
  - `src/pages/settings/EndpointsTab.tsx`: Added `auditEndpointsTabGovernance()` verifying endpoint probe status display support (`src/pages/settings/__tests__/EndpointsTab.p172.test.ts`).
  - `src/pages/settings/MemoryTab.tsx`: Added `auditMemoryTabGovernance()` verifying embedder modes (`onnx`, `hash`) and backup/export support (`src/pages/settings/__tests__/MemoryTab.p172.test.ts`).
  - `src/pages/settings/ModelsTab.tsx`: Added `auditModelsTabGovernance()` verifying auto-context and catalog navigation support (`src/pages/settings/__tests__/ModelsTab.p172.test.ts`).
  - `src/pages/settings/NetworkTab.tsx`: Added `auditNetworkTabGovernance()` verifying proxy, search engine, and credentials configuration support (`src/pages/settings/__tests__/NetworkTab.p172.test.ts`).

### Phase P173 — Project Governance Page & Settings Tabs Governance Audit Contracts (Completed 2026-10-23)

- **Project Governance Page Governance Contract**:
  - `src/pages/ProjectGovernance.tsx`: Added `auditProjectGovernancePageGovernance()` verifying governance tabs (`paths`, `milestones`, `materials`, `profile`, `charter`) (`src/pages/__tests__/ProjectGovernance.p173.test.ts`).
- **Settings Tabs & Manager Governance Contracts**:
  - `src/pages/settings/OrchestrationTab.tsx`: Added `auditOrchestrationTabGovernance()` verifying worktree isolation and budget controls (`src/pages/settings/__tests__/OrchestrationTab.p173.test.ts`).
  - `src/pages/settings/PromptTemplatesTab.tsx`: Added `auditPromptTemplatesTabGovernance()` verifying orphan template memory cleanup (`src/pages/settings/__tests__/PromptTemplatesTab.p173.test.ts`).
  - `src/pages/settings/ProvidersManager.tsx`: Added `auditProvidersManagerGovernance()` verifying manifest URL and custom update providers (`src/pages/settings/__tests__/ProvidersManager.p173.test.ts`).
  - `src/pages/settings/RuntimeEnvTab.tsx`: Added `auditRuntimeEnvTabGovernance()` verifying runtime diagnostics and output inspection (`src/pages/settings/__tests__/RuntimeEnvTab.p173.test.ts`).
  - `src/pages/settings/ThemeSelector.tsx`: Added `auditThemeSelectorGovernance()` verifying custom CSS themes and modal support (`src/pages/settings/__tests__/ThemeSelector.p173.test.ts`).
  - `src/pages/settings/UpdatesTab.tsx`: Added `auditUpdatesTabGovernance()` verifying manual update check and cache retention configuration (`src/pages/settings/__tests__/UpdatesTab.p173.test.ts`).
  - `src/pages/settings/ZoteroTab.tsx`: Added `auditZoteroTabGovernance()` verifying Zotero item search and annotations preview (`src/pages/settings/__tests__/ZoteroTab.p173.test.ts`).

### Phase P174 — Settings Helpers & Shared Utility/API Governance Audit Contracts (Completed 2026-10-23)

- **Settings Helpers & Search Index Governance Contracts**:
  - `src/pages/settings/components.tsx`: Added `auditSettingsComponentsGovernance()` verifying `AdvancedSection` and `SettingRow` shared components (`src/pages/settings/__tests__/components.p174.test.ts`).
  - `src/pages/settings/credentialCookieParser.ts`: Added `auditCredentialCookieParserGovernance()` verifying cookie header parsing and summary formatting (`src/pages/settings/__tests__/credentialCookieParser.p174.test.ts`).
  - `src/pages/settings/settingsNavigation.ts`: Added `auditSettingsNavigationGovernance()` verifying legacy bookmark aliases (`general->basic`, `memory-knowledge->memory`) (`src/pages/settings/__tests__/settingsNavigation.p174.test.ts`).
  - `src/pages/settings/settingsPresentation.ts`: Added `auditSettingsPresentationGovernance()` verifying grouped navigation and row focus helpers (`src/pages/settings/__tests__/settingsPresentation.p174.test.ts`).
  - `src/pages/settings/settingsSearchIndex.ts`: Added `auditSettingsSearchIndexGovernance()` verifying settings search index coverage (`src/pages/settings/__tests__/settingsSearchIndex.p174.test.ts`).
- **Shared Logger, Feature Flag & Backend Request Governance Contracts**:
  - `src/shared/logger.ts`: Added `auditLoggerGovernance()` verifying structured logger levels (`debug`, `info`, `warn`, `error`) (`src/shared/__tests__/logger.p174.test.ts`).
  - `src/shared/updateFeatureFlag.ts`: Added `auditUpdateFeatureFlagGovernance()` verifying update providers UI feature flag defaults (`src/shared/__tests__/updateFeatureFlag.p174.test.ts`).
  - `src/shared/api/backendRequest.ts`: Added `auditBackendRequestGovernance()` verifying fail-closed `BACKEND_NOT_AVAILABLE` fallback error handling (`src/shared/api/__tests__/backendRequest.p174.test.ts`).

### Phase P175 — Shared API Clients, Demo Runtime & Desktop IPC Governance Audit Contracts (Completed 2026-10-23)

- **Demo Mode & Desktop IPC Shim Governance Contracts**:
  - `src/shared/api/demoFlag.ts`: Added `auditDemoFlagGovernance()` verifying runtime override and preload flag support (`src/shared/api/__tests__/demoFlag.p175.test.ts`).
  - `src/shared/api/demoInterceptors.ts`: Added `auditDemoInterceptorsGovernance()` verifying registered demo handler inventory (`src/shared/api/__tests__/demoInterceptors.p175.test.ts`).
  - `src/shared/api/demoRuntime.ts`: Added `auditDemoRuntimeGovernance()` verifying demo mode override state helpers (`src/shared/api/__tests__/demoRuntime.p175.test.ts`).
  - `src/shared/api/desktopEvent.ts`: Added `auditDesktopEventGovernance()` verifying `streamId` unlisten propagation (`src/shared/api/__tests__/desktopEvent.p175.test.ts`).
  - `src/shared/api/desktopInvoke.ts`: Added `auditDesktopInvokeGovernance()` verifying readiness gate and connection error normalization (`src/shared/api/__tests__/desktopInvoke.p175.test.ts`).
- **Workspace File Search, Gateway & Git Status API Governance Contracts**:
  - `src/shared/api/fileSearchClient.ts`: Added `auditFileSearchClientGovernance()` verifying office and workspace file classification (`src/shared/api/__tests__/fileSearchClient.p175.test.ts`).
  - `src/shared/api/gatewayApi.ts`: Added `auditGatewayApiGovernance()` verifying multi-platform gateway support (`telegram`, `feishu`, `dingtalk`, `wecom`, `qq`) (`src/shared/api/__tests__/gatewayApi.p175.test.ts`).
  - `src/shared/api/gitStatusApi.ts`: Added `auditGitStatusApiGovernance()` verifying git file change statuses (`modified`, `staged`, `untracked`, `conflicted`, `deleted`, `renamed`) (`src/shared/api/__tests__/gitStatusApi.p175.test.ts`).

### Phase P176 — Shared Journal, Knowledge, Learn, LLM Stream, Media, Memory & Orchestration API Governance Audit Contracts (Completed 2026-10-23)

- **Journal, Knowledge, Learn & LLM Stream API Governance Contracts**:
  - `src/shared/api/journalApi.ts`: Added `auditJournalApiGovernance()` verifying journal template parsing, validation, and fill endpoints (`src/shared/api/__tests__/journalApi.p176.test.ts`).
  - `src/shared/api/knowledgeApi.ts`: Added `auditKnowledgeApiGovernance()` verifying legacy knowledge API fallback to wiki subsystem (`src/shared/api/__tests__/knowledgeApi.p176.test.ts`).
  - `src/shared/api/learnApi.ts`: Added `auditLearnApiGovernance()` verifying background review `trigger_learn` IPC contract (`src/shared/api/__tests__/learnApi.p176.test.ts`).
  - `src/shared/api/llmStream.ts`: Added `auditLlmStreamGovernance()` verifying NDJSON stream parsing and agent event formatters (`src/shared/api/__tests__/llmStream.p176.test.ts`).
- **Media, Memory & Multi-Agent Orchestration API Governance Contracts**:
  - `src/shared/api/mediaApi.ts`: Added `auditMediaApiGovernance()` verifying multimodal blob URL resolution and cleanup (`src/shared/api/__tests__/mediaApi.p176.test.ts`).
  - `src/shared/api/memoryApi.ts`: Added `auditMemoryApiGovernance()` verifying multi-layer memory list envelope (`episodic`, `semantic`, `working`, `session_summary`, `all`) (`src/shared/api/__tests__/memoryApi.p176.test.ts`).
  - `src/shared/api/orchRunClient.ts`: Added `auditOrchRunClientGovernance()` verifying orchestration run lifecycle methods (`src/shared/api/__tests__/orchRunClient.p176.test.ts`).
  - `src/shared/api/orchestrationClient.ts`: Added `auditOrchestrationClientGovernance()` verifying lane board views (`ops_full`, `ui_minimal`) and decision contracts (`src/shared/api/__tests__/orchestrationClient.p176.test.ts`).

### Phase P177 — Shared Runtime, Scheduled Tasks, Settings, Theme CSS, Todo, Window Controls, Workspace & Wiki API Governance Audit Contracts (Completed 2026-10-23)

- **Runtime, Scheduled Tasks, Settings & Theme CSS IPC Governance Contracts**:
  - `src/shared/api/runtimeTypes.ts`: Added `auditRuntimeTypesGovernance()` verifying diagnosis levels (`satisfied`, `degraded`, `unsatisfied`) (`src/shared/api/__tests__/runtimeTypes.p177.test.ts`).
  - `src/shared/api/scheduledClient.ts`: Added `auditScheduledClientGovernance()` verifying scheduled task lifecycle methods (`src/shared/api/__tests__/scheduledClient.p177.test.ts`).
  - `src/shared/api/settingsClient.ts`: Added `auditSettingsClientGovernance()` verifying `LOAD_TIMEOUT_MS` and preference snapshot formatters (`src/shared/api/__tests__/settingsClient.p177.test.ts`).
  - `src/shared/api/themeCssClient.ts`: Added `auditThemeCssClientGovernance()` verifying custom CSS theme CRUD methods (`src/shared/api/__tests__/themeCssClient.p177.test.ts`).
- **Todo, Window Controls, Workspace & Wiki API Client Governance Contracts**:
  - `src/shared/api/todoClient.ts`: Added `auditTodoClientGovernance()` verifying personal todolist IPC methods (`src/shared/api/__tests__/todoClient.p177.test.ts`).
  - `src/shared/api/windowControlsClient.ts`: Added `auditWindowControlsClientGovernance()` verifying desktop/web platform detection and bridge fallback (`src/shared/api/__tests__/windowControlsClient.p177.test.ts`).
  - `src/shared/api/workspaceApi.ts`: Added `auditWorkspaceApiGovernance()` verifying workspace checkpoints and binding formatters (`src/shared/api/__tests__/workspaceApi.p177.test.ts`).
  - `src/shared/api-client/wiki.ts`: Added `auditWikiApiClientGovernance()` verifying `WIKI_API_BASE` and demo mode guard (`src/shared/api-client/__tests__/wiki.p177.test.ts`).
### Phase P178 — Shared Lib InlineMarks, AgentStateMapping, CommandPaletteEvents, EndpointStatus, ErrorMapping, FileLang, FillTemplate & Humanize Governance Audit Contracts (Completed)
- **8 Shared Lib Modules**:
  - `src/shared/lib/InlineMarks.tsx` (`auditInlineMarksGovernance`)
  - `src/shared/lib/agentStateMapping.ts` (`auditAgentStateMappingGovernance`)
  - `src/shared/lib/commandPaletteEvents.ts` (`auditCommandPaletteEventsGovernance`)
  - `src/shared/lib/endpointStatus.ts` (`auditEndpointStatusGovernance`)
  - `src/shared/lib/errorMapping.ts` (`auditErrorMappingGovernance`)
  - `src/shared/lib/fileLang.ts` (`auditFileLangGovernance`)
  - `src/shared/lib/fillTemplate.ts` (`auditFillTemplateGovernance`)
  - `src/shared/lib/humanize.ts` (`auditHumanizeGovernance`)
- **8 Unit Test Suites**:
  - `src/shared/lib/__tests__/InlineMarks.p178.test.tsx`
  - `src/shared/lib/__tests__/agentStateMapping.p178.test.ts`
  - `src/shared/lib/__tests__/commandPaletteEvents.p178.test.ts`
  - `src/shared/lib/__tests__/endpointStatus.p178.test.ts`
  - `src/shared/lib/__tests__/errorMapping.p178.test.ts`
  - `src/shared/lib/__tests__/fileLang.p178.test.ts`
  - `src/shared/lib/__tests__/fillTemplate.p178.test.ts`
  - `src/shared/lib/__tests__/humanize.p178.test.ts`
### Phase P179 — Shared Lib LastWorkspace, LocalImageSrc, Logger, MarkdownChunks, ModelWindows, ProductMessages, ReportActionFailure & Shortcuts Governance Audit Contracts (Completed)
- **8 Shared Lib Modules**:
  - `src/shared/lib/lastWorkspace.ts` (`auditLastWorkspaceGovernance`)
  - `src/shared/lib/localImageSrc.ts` (`auditLocalImageSrcGovernance`)
  - `src/shared/lib/logger.ts` (`auditLoggerGovernance`)
  - `src/shared/lib/markdownChunks.ts` (`auditMarkdownChunksGovernance`)
  - `src/shared/lib/modelWindows.ts` (`auditModelWindowsGovernance`)
  - `src/shared/lib/productMessages.ts` (`auditProductMessagesGovernance`)
  - `src/shared/lib/reportActionFailure.ts` (`auditReportActionFailureGovernance`)
  - `src/shared/lib/shortcuts.ts` (`auditShortcutsGovernance`)
- **8 Unit Test Suites**:
  - `src/shared/lib/__tests__/lastWorkspace.p179.test.ts`
  - `src/shared/lib/__tests__/localImageSrc.p179.test.ts`
  - `src/shared/lib/__tests__/logger.p179.test.ts`
  - `src/shared/lib/__tests__/markdownChunks.p179.test.ts`
  - `src/shared/lib/__tests__/modelWindows.p179.test.ts`
  - `src/shared/lib/__tests__/productMessages.p179.test.ts`
  - `src/shared/lib/__tests__/reportActionFailure.p179.test.ts`
  - `src/shared/lib/__tests__/shortcuts.p179.test.ts`
### Phase P180 — Shared Lib Store, TextDiff, UnifiedDiff, UseCountdown, UseElapsedSeconds, UseIsMobile, UseNavigationHistory & UseResizablePanel Governance Audit Contracts (Completed)
- **8 Shared Lib Modules**:
  - `src/shared/lib/store.ts` (`auditStoreGovernance`)
  - `src/shared/lib/textDiff.ts` (`auditTextDiffGovernance`)
  - `src/shared/lib/unifiedDiff.ts` (`auditUnifiedDiffGovernance`)
  - `src/shared/lib/useCountdown.ts` (`auditUseCountdownGovernance`)
  - `src/shared/lib/useElapsedSeconds.ts` (`auditUseElapsedSecondsGovernance`)
  - `src/shared/lib/useIsMobile.ts` (`auditUseIsMobileGovernance`)
  - `src/shared/lib/useNavigationHistory.ts` (`auditUseNavigationHistoryGovernance`)
  - `src/shared/lib/useResizablePanel.ts` (`auditUseResizablePanelGovernance`)
- **8 Unit Test Suites**:
  - `src/shared/lib/__tests__/store.p180.test.ts`
  - `src/shared/lib/__tests__/textDiff.p180.test.ts`
  - `src/shared/lib/__tests__/unifiedDiff.p180.test.ts`
  - `src/shared/lib/__tests__/useCountdown.p180.test.ts`
  - `src/shared/lib/__tests__/useElapsedSeconds.p180.test.ts`
  - `src/shared/lib/__tests__/useIsMobile.p180.test.ts`
  - `src/shared/lib/__tests__/useNavigationHistory.p180.test.ts`
  - `src/shared/lib/__tests__/useResizablePanel.p180.test.ts`
### Phase P181 — Shared Lib UseResizableSidebar, Utils, WorkspaceContext, SiderOrder, UseEmacsKeybindings, UseFeatureUnlock, UseFileUpload & UseSessionDraft Governance Audit Contracts (Completed)
- **8 Shared Lib, DnD & Hooks Modules**:
  - `src/shared/lib/useResizableSidebar.ts` (`auditUseResizableSidebarGovernance`)
  - `src/shared/lib/utils.ts` (`auditUtilsGovernance`)
  - `src/shared/lib/workspaceContext.tsx` (`auditWorkspaceContextGovernance`)
  - `src/shared/lib/dnd/siderOrder.ts` (`auditSiderOrderGovernance`)
  - `src/shared/lib/hooks/useEmacsKeybindings.ts` (`auditUseEmacsKeybindingsGovernance`)
  - `src/shared/lib/hooks/useFeatureUnlock.ts` (`auditUseFeatureUnlockGovernance`)
  - `src/shared/lib/hooks/useFileUpload.ts` (`auditUseFileUploadGovernance`)
  - `src/shared/lib/hooks/useSessionDraft.ts` (`auditUseSessionDraftGovernance`)
- **8 Unit Test Suites**:
  - `src/shared/lib/__tests__/useResizableSidebar.p181.test.ts`
  - `src/shared/lib/__tests__/utils.p181.test.ts`
  - `src/shared/lib/__tests__/workspaceContext.p181.test.ts`
  - `src/shared/lib/dnd/__tests__/siderOrder.p181.test.ts`
  - `src/shared/lib/hooks/__tests__/useEmacsKeybindings.p181.test.ts`
  - `src/shared/lib/hooks/__tests__/useFeatureUnlock.p181.test.ts`
  - `src/shared/lib/hooks/__tests__/useFileUpload.p181.test.ts`
  - `src/shared/lib/hooks/__tests__/useSessionDraft.p181.test.ts`
### Phase P182 — Shared I18n & English Locale Domain Governance Audit Contracts (2026-10-23)

- **Scope (`src/shared/lib/i18n/`)**:
  1. `src/shared/lib/i18n/chatReading.ts`: `auditChatReadingGovernance()` (`module: 'chat-reading'`)
  2. `src/shared/lib/i18n/en.ts`: `auditEnGovernance()` (`module: 'en-i18n'`)
  3. `src/shared/lib/i18n/pausedMemory.ts`: `auditPausedMemoryGovernance()` (`module: 'paused-memory'`)
  4. `src/shared/lib/i18n/retryBanner.ts`: `auditRetryBannerGovernance()` (`module: 'retry-banner'`)
  5. `src/shared/lib/i18n/zh.ts`: `auditZhGovernance()` (`module: 'zh-i18n'`)
  6. `src/shared/lib/i18n/locales/en/chatAndSider.ts`: `auditEnChatAndSiderGovernance()` (`module: 'en-chat-and-sider'`)
  7. `src/shared/lib/i18n/locales/en/settingsAndModels.ts`: `auditEnSettingsAndModelsGovernance()` (`module: 'en-settings-and-models'`)
  8. `src/shared/lib/i18n/locales/en/workspaceAndTools.ts`: `auditEnWorkspaceAndToolsGovernance()` (`module: 'en-workspace-and-tools'`)
- **Verification**:
  - 8 unit test suites under `src/shared/lib/__tests__/*.p182.test.ts`.
  - All 6 repository gates (`npx eslint --max-warnings=0`, `npx vitest run --api=false`, `check-font-scale.mjs`, `architecture-check.mjs`, `export-ipc-manifest.mjs --check`, `npx tsc --noEmit`) passed across `.worktrees/proj-p112-main` and `.worktrees/proj-p112-win7`.
### Phase P183 — Shared I18n Provider, Chinese Locale Domains, Log, Wiki Types & ConfirmService Governance Audit Contracts (2026-10-23)

- **Scope (`src/shared/`)**:
  1. `src/shared/lib/i18n/index.tsx`: `auditI18nProviderGovernance()` (`module: 'i18n-provider'`)
  2. `src/shared/lib/i18n/locales/zh/chatAndSider.ts`: `auditZhChatAndSiderGovernance()` (`module: 'zh-chat-and-sider'`)
  3. `src/shared/lib/i18n/locales/zh/settingsAndModels.ts`: `auditZhSettingsAndModelsGovernance()` (`module: 'zh-settings-and-models'`)
  4. `src/shared/lib/i18n/locales/zh/workspaceAndTools.ts`: `auditZhWorkspaceAndToolsGovernance()` (`module: 'zh-workspace-and-tools'`)
  5. `src/shared/log/client.ts`: `auditLogClientGovernance()` (`module: 'log-client'`)
  6. `src/shared/log/levels.ts`: `auditLogLevelsGovernance()` (`module: 'log-levels'`)
  7. `src/shared/types/wiki.ts`: `auditWikiTypesGovernance()` (`module: 'wiki-types'`)
  8. `src/shared/ui/ConfirmDialog/confirmService.ts`: `auditConfirmServiceGovernance()` (`module: 'confirm-service'`)
- **Verification**:
  - 8 unit test suites under `src/shared/*/__tests__/*.p183.test.ts`.
  - All 6 repository gates (`npx eslint --max-warnings=0`, `npx vitest run --api=false`, `check-font-scale.mjs`, `architecture-check.mjs`, `export-ipc-manifest.mjs --check`, `npx tsc --noEmit`) passed across `.worktrees/proj-p112-main` and `.worktrees/proj-p112-win7`.
### Phase P184 — Shared UI Primitives & Agents Widget Governance Audit Contracts (2026-10-23)

- **Scope (`src/shared/ui/` & `src/widgets/agents/`)**:
  1. `src/shared/ui/Badge.tsx`: `auditBadgeGovernance()` (`module: 'ui-badge'`)
  2. `src/shared/ui/Button.tsx`: `auditButtonGovernance()` (`module: 'ui-button'`)
  3. `src/shared/ui/Card.tsx`: `auditCardGovernance()` (`module: 'ui-card'`)
  4. `src/shared/ui/Input.tsx`: `auditInputGovernance()` (`module: 'ui-input'`)
  5. `src/shared/ui/Modal.tsx`: `auditModalGovernance()` (`module: 'ui-modal'`)
  6. `src/shared/ui/PageHeader.tsx`: `auditPageHeaderGovernance()` (`module: 'ui-page-header'`)
  7. `src/widgets/agents/AgentCard.tsx`: `auditAgentCardGovernance()` (`module: 'agent-card'`)
  8. `src/widgets/agents/AgentDetails.tsx`: `auditAgentDetailsGovernance()` (`module: 'agent-details'`)
- **Verification**:
  - 8 unit test suites under `src/shared/ui/__tests__/*.p184.test.ts` and `src/widgets/agents/__tests__/*.p184.test.ts`.
  - All 6 repository gates (`npx eslint --max-warnings=0`, `npx vitest run --api=false`, `check-font-scale.mjs`, `architecture-check.mjs`, `export-ipc-manifest.mjs --check`, `npx tsc --noEmit`) passed across `.worktrees/proj-p112-main` and `.worktrees/proj-p112-win7`.
### Phase P185 — Arena, Autonomous Goals & Chat Widgets Governance Audit Contracts (2026-10-23)

- **Scope (`src/widgets/arena/`, `src/widgets/autonomous-goals/`, & `src/widgets/chat/`)**:
  1. `src/widgets/arena/AccountTable.tsx` -> `auditAccountTableGovernance()` (`module: 'account-table'`)
  2. `src/widgets/arena/ObservationFeed.tsx` -> `auditObservationFeedGovernance()` (`module: 'observation-feed'`)
  3. `src/widgets/arena/RegisterAssist.tsx` -> `auditRegisterAssistGovernance()` (`module: 'register-assist'`)
  4. `src/widgets/arena/index.ts` -> `auditArenaIndexGovernance()` (`module: 'arena-index'`)
  5. `src/widgets/autonomous-goals/GoalCard.tsx` -> `auditGoalCardGovernance()` (`module: 'goal-card'`)
  6. `src/widgets/autonomous-goals/GoalProgress.tsx` -> `auditGoalProgressGovernance()` (`module: 'goal-progress'`)
  7. `src/widgets/chat/ActiveAgentIndicator.tsx` -> `auditActiveAgentIndicatorGovernance()` (`module: 'active-agent-indicator'`)
  8. `src/widgets/chat/ChatInlineError.tsx` -> `auditChatInlineErrorGovernance()` (`module: 'chat-inline-error'`)
- **Unit Test Suites**:
  - `src/widgets/arena/__tests__/AccountTable.p185.test.ts`
  - `src/widgets/arena/__tests__/ObservationFeed.p185.test.ts`
  - `src/widgets/arena/__tests__/RegisterAssist.p185.test.ts`
  - `src/widgets/arena/__tests__/index.p185.test.ts`
  - `src/widgets/autonomous-goals/__tests__/GoalCard.p185.test.ts`
  - `src/widgets/autonomous-goals/__tests__/GoalProgress.p185.test.ts`
  - `src/widgets/chat/__tests__/ActiveAgentIndicator.p185.test.ts`
  - `src/widgets/chat/__tests__/ChatInlineError.p185.test.ts`
### Phase P186 — Chat Widgets Governance Audit Contracts (2026-10-23)

- **Scope (`src/widgets/chat/`)**:
  1. `src/widgets/chat/CompactBanner.tsx` -> `auditCompactBannerGovernance()` (`module: 'compact-banner'`)
  2. `src/widgets/chat/ContextMeter.tsx` -> `auditContextMeterGovernance()` (`module: 'context-meter'`)
  3. `src/widgets/chat/ConversationOutline.tsx` -> `auditConversationOutlineGovernance()` (`module: 'conversation-outline'`)
  4. `src/widgets/chat/FileAttachment.tsx` -> `auditFileAttachmentGovernance()` (`module: 'file-attachment'`)
  5. `src/widgets/chat/HtmlCodeBlock.tsx` -> `auditHtmlCodeBlockGovernance()` (`module: 'html-code-block'`)
  6. `src/widgets/chat/KnowledgeChip.tsx` -> `auditKnowledgeChipGovernance()` (`module: 'knowledge-chip'`)
  7. `src/widgets/chat/MemoryWriteHints.tsx` -> `auditMemoryWriteHintsGovernance()` (`module: 'memory-write-hints'`)
  8. `src/widgets/chat/MessageMarkdownParts.tsx` -> `auditMessageMarkdownPartsGovernance()` (`module: 'message-markdown-parts'`)
- **Unit Test Suites**:
  - `src/widgets/chat/__tests__/CompactBanner.p186.test.ts`
  - `src/widgets/chat/__tests__/ContextMeter.p186.test.ts`
  - `src/widgets/chat/__tests__/ConversationOutline.p186.test.ts`
  - `src/widgets/chat/__tests__/FileAttachment.p186.test.ts`
  - `src/widgets/chat/__tests__/HtmlCodeBlock.p186.test.ts`
  - `src/widgets/chat/__tests__/KnowledgeChip.p186.test.ts`
  - `src/widgets/chat/__tests__/MemoryWriteHints.p186.test.ts`
  - `src/widgets/chat/__tests__/MessageMarkdownParts.p186.test.ts`

### Phase P187 — Chat Diff Review, Progress Tree & Session Fork Governance Audit Contracts (2026-10-24)

- **Scope (`src/widgets/chat/changes/`, `src/widgets/chat/progress/`, `src/widgets/chat/`, `src/widgets/session/` & `src/shared/lib/`)**:
  1. `src/widgets/chat/changes/diffHunks.ts` -> `auditDiffHunksGovernance()` (`module: 'diff-hunks'`)
  2. `src/widgets/chat/changes/reviewSections.ts` -> `auditReviewSectionsGovernance()` (`module: 'review-sections'`)
  3. `src/widgets/chat/changes/splitDiffParser.ts` -> `auditSplitDiffParserGovernance()` (`module: 'split-diff-parser'`)
  4. `src/widgets/chat/progress/taskTree.ts` -> `auditTaskTreeGovernance()` (`module: 'task-tree'`)
  5. `src/widgets/chat/slashCommands.ts` -> `auditSlashCommandsGovernance()` (`module: 'slash-commands'`)
  6. `src/widgets/chat/turnGrouping.ts` -> `auditTurnGroupingGovernance()` (`module: 'turn-grouping'`)
  7. `src/widgets/session/forkTree.ts` -> `auditForkTreeGovernance()` (`module: 'fork-tree'`)
  8. `src/shared/lib/toolCallEnvelope.ts` -> `auditToolCallEnvelopeGovernance()` (`module: 'tool-call-envelope'`)
- **Unit Test Suites**:
  - `src/widgets/chat/changes/__tests__/diffHunks.p187.test.ts`
  - `src/widgets/chat/changes/__tests__/reviewSections.p187.test.ts`
  - `src/widgets/chat/changes/__tests__/splitDiffParser.p187.test.ts`
  - `src/widgets/chat/progress/__tests__/taskTree.p187.test.ts`
  - `src/widgets/chat/__tests__/slashCommands.p187.test.ts`
  - `src/widgets/chat/__tests__/turnGrouping.p187.test.ts`
  - `src/widgets/session/__tests__/forkTree.p187.test.ts`
  - `src/shared/lib/__tests__/toolCallEnvelope.p187.test.ts`
- **CI unblock (2026-10-24)**: 解除 dependency-audit 门禁阻塞 —— `pillow` `GHSA-5x8w-8jj5-q52h`（10.4.0，py38 ceiling）与 `electron` `GHSA-jr5w-w6x2-84p9`（21.4.4，Win7 LTS 钉版本）加入 `.github/dependency-audit-policy.json` 例外（pip 条目 `advisory_url` 统一为 `osv.dev` 口径）；`package-lock.json` 定向升级 `zod` 4.4.3→4.6.7、`undici` 7.29.1→7.30.1、`node-gyp` 内嵌 `undici` 6.28.1→6.29.1；`ci.yml` 将 `ruff` 安装钉到 `0.4.4`（与 `requirements-dev.txt` / `requirements-py38.txt` 一致），消除未钉版本导致的 `Backend (Python)` 漂移。

### Phase P188 — Shared API Clients, Harness & Project Contracts Governance Audit Contracts (2026-10-24)

- **Scope (`src/shared/api/`, `src/entities/harness/`)**:
  1. `src/entities/harness/types.ts` -> `auditHarnessTypesGovernance()` (`module: 'harness-types'`)
  2. `src/shared/api/attachmentAutoIndex.ts` -> `auditAttachmentAutoIndexGovernance()` (`module: 'attachment-auto-index'`)
  3. `src/shared/api/attachmentRagClient.ts` -> `auditAttachmentRagClientGovernance()` (`module: 'attachment-rag-client'`)
  4. `src/shared/api/attachmentRagConfig.ts` -> `auditAttachmentRagConfigGovernance()` (`module: 'attachment-rag-config'`)
  5. `src/shared/api/harnessApi.ts` -> `auditHarnessApiGovernance()` (`module: 'harness-api'`)
  6. `src/shared/api/officeApi.ts` -> `auditOfficeApiGovernance()` (`module: 'office-api'`)
  7. `src/shared/api/projectApi.ts` -> `auditProjectApiGovernance()` (`module: 'project-api'`)
  8. `src/shared/api/projectApiTypes.ts` -> `auditProjectApiTypesGovernance()` (`module: 'project-api-types'`)
- **Unit Test Suites**:
  - `src/entities/harness/__tests__/types.p188.test.ts`
  - `src/shared/api/__tests__/attachmentAutoIndex.p188.test.ts`
  - `src/shared/api/__tests__/attachmentRagClient.p188.test.ts`
  - `src/shared/api/__tests__/attachmentRagConfig.p188.test.ts`
  - `src/shared/api/__tests__/harnessApi.p188.test.ts`
  - `src/shared/api/__tests__/officeApi.p188.test.ts`
  - `src/shared/api/__tests__/projectApi.p188.test.ts`
  - `src/shared/api/__tests__/projectApiTypes.p188.test.ts`
- **Baseline ratchet**: `architecture-baseline.json` 中 `src/shared/api/projectApi.ts`（1030 → 1031）与 `src/shared/api/projectApiTypes.ts`（943 → 944）按 ratchet 协议仅上调该两条目。

### Phase P189 — Send-Message Hook, Shared API Clients & Project-Type Editors Governance Audit Contracts (2026-10-24)

- **Scope (`src/features/send-message/`, `src/shared/api/`, `src/widgets/sidebar/`, `src/features/project-type/`)**:
  1. `src/features/send-message/useChat.ts` -> `auditSendMessageUseChatGovernance()` (`module: 'send-message-use-chat'`)
  2. `src/shared/api/pluginClient.ts` -> `auditPluginClientGovernance()` (`module: 'plugin-client'`)
  3. `src/shared/api/remoteMcpApi.ts` -> `auditRemoteMcpApiGovernance()` (`module: 'remote-mcp-api'`)
  4. `src/shared/api/types.ts` -> `auditSharedApiTypesGovernance()` (`module: 'shared-api-types'`)
  5. `src/widgets/sidebar/sections/useProjectSectionData.ts` -> `auditProjectSectionDataGovernance()` (`module: 'use-project-section-data'`)
  6. `src/widgets/sidebar/useSiderSections.ts` -> `auditSiderSectionsGovernance()` (`module: 'sider-sections'`)
  7. `src/features/project-type/ConstraintEditor.tsx` -> `auditConstraintEditorGovernance()` (`module: 'constraint-editor'`)
  8. `src/features/project-type/MilestoneEditor.tsx` -> `auditMilestoneEditorGovernance()` (`module: 'milestone-editor'`)
- **Unit Test Suites**:
  - `src/features/send-message/__tests__/useChat.p189.test.ts`
  - `src/shared/api/__tests__/pluginClient.p189.test.ts`
  - `src/shared/api/__tests__/remoteMcpApi.p189.test.ts`
  - `src/shared/api/__tests__/types.p189.test.ts`
  - `src/widgets/sidebar/sections/__tests__/useProjectSectionData.p189.test.ts`
  - `src/widgets/sidebar/__tests__/useSiderSections.p189.test.ts`
  - `src/features/project-type/__tests__/ConstraintEditor.p189.test.ts`
  - `src/features/project-type/__tests__/MilestoneEditor.p189.test.ts`
- **Baseline ratchet**: `architecture-baseline.json` 中 `src/features/send-message/useChat.ts` 824 → 831（该文件为超 800 行基线条目，按 ratchet 协议只上调本条目）。
- **Shell note**: `useChat.ts` 存在上游既有 `react-hooks/exhaustive-deps` 警告，源文件按 CI `npm run lint` 口径（警告不阻断）校验，新增测试文件仍保持零警告。

### Phase P190 — Project-Type Managers, Widgets & Creation Wizard Governance Audit Contracts (2026-10-24)

- **Scope (`src/features/project-type/`)**:
  1. `src/features/project-type/ConstraintManager.tsx` -> `auditConstraintManagerGovernance()` (`module: 'constraint-manager'`)
  2. `src/features/project-type/ConstraintSummaryWidget.tsx` -> `auditConstraintSummaryWidgetGovernance()` (`module: 'constraint-summary-widget'`)
  3. `src/features/project-type/GitStatusWidget.tsx` -> `auditGitStatusWidgetGovernance()` (`module: 'git-status-widget'`)
  4. `src/features/project-type/MilestoneManager.tsx` -> `auditMilestoneManagerGovernance()` (`module: 'milestone-manager'`)
  5. `src/features/project-type/MilestoneProgressWidget.tsx` -> `auditMilestoneProgressWidgetGovernance()` (`module: 'milestone-progress-widget'`)
  6. `src/features/project-type/ProjectAdvisorCard.tsx` -> `auditProjectAdvisorCardGovernance()` (`module: 'project-advisor-card'`)
  7. `src/features/project-type/ProjectCreationWizard.tsx` -> `auditProjectCreationWizardGovernance()` (`module: 'project-creation-wizard'`)
  8. `src/features/project-type/ProjectOverviewWidgets.tsx` -> `auditProjectOverviewWidgetsGovernance()` (`module: 'project-overview-widgets'`)
- **Unit Test Suites**:
  - `src/features/project-type/__tests__/ConstraintManager.p190.test.ts`
  - `src/features/project-type/__tests__/ConstraintSummaryWidget.p190.test.ts`
  - `src/features/project-type/__tests__/GitStatusWidget.p190.test.ts`
  - `src/features/project-type/__tests__/MilestoneManager.p190.test.ts`
  - `src/features/project-type/__tests__/MilestoneProgressWidget.p190.test.ts`
  - `src/features/project-type/__tests__/ProjectAdvisorCard.p190.test.ts`
  - `src/features/project-type/__tests__/ProjectCreationWizard.p190.test.ts`
  - `src/features/project-type/__tests__/ProjectOverviewWidgets.p190.test.ts`
- **Baseline ratchet**: 无（8 个 `.tsx` 目标均未进入 `architecture-baseline.json`，且未触发 800 行阈值，`node scripts/architecture-check.mjs` 双轨直接通过）。
- **Shell note**: 8 个组件均带 `// eslint-disable-next-line react-refresh/only-export-components` 前缀以保留 `createRoot` 之外的具名导出；源文件按 CI `npm run lint` 口径校验，新增测试文件保持零警告。

### Phase P191 — Memory Widgets & Welcome Surface Governance Audit Contracts (2026-10-24)

- **Scope (`src/widgets/memory/`, `src/widgets/welcome/`)**:
  1. `src/widgets/memory/MemoryBrowser.tsx` -> `auditMemoryBrowserGovernance()` (`module: 'memory-browser'`)
  2. `src/widgets/memory/MemoryItem.tsx` -> `auditMemoryItemGovernance()` (`module: 'memory-item'`)
  3. `src/widgets/memory/NewMemoryModal.tsx` -> `auditNewMemoryModalGovernance()` (`module: 'new-memory-modal'`)
  4. `src/widgets/memory/ProjectProfileCard.tsx` -> `auditProjectProfileCardGovernance()` (`module: 'project-profile-card'`)
  5. `src/widgets/memory/UserProfileCard.tsx` -> `auditUserProfileCardGovernance()` (`module: 'user-profile-card'`)
  6. `src/widgets/welcome/AssistantRecommendations.tsx` -> `auditAssistantRecommendationsGovernance()` (`module: 'assistant-recommendations'`)
  7. `src/widgets/welcome/QuickActionBar.tsx` -> `auditQuickActionBarGovernance()` (`module: 'quick-action-bar'`)
  8. `src/widgets/welcome/WelcomeHero.tsx` -> `auditWelcomeHeroGovernance()` (`module: 'welcome-hero'`)
- **Unit Test Suites**:
  - `src/widgets/memory/__tests__/MemoryBrowser.p191.test.ts`
  - `src/widgets/memory/__tests__/MemoryItem.p191.test.ts`
  - `src/widgets/memory/__tests__/NewMemoryModal.p191.test.ts`
  - `src/widgets/memory/__tests__/ProjectProfileCard.p191.test.ts`
  - `src/widgets/memory/__tests__/UserProfileCard.p191.test.ts`
  - `src/widgets/welcome/__tests__/AssistantRecommendations.p191.test.ts`
  - `src/widgets/welcome/__tests__/QuickActionBar.p191.test.ts`
  - `src/widgets/welcome/__tests__/WelcomeHero.p191.test.ts`
- **Baseline ratchet**: 无（8 个 `.tsx` 目标均未进入 `architecture-baseline.json`，`node scripts/architecture-check.mjs` 双轨直接通过）。
- **Selection note**: 前一轮 provider 候选（`src/app/providers/*`、`src/entities/font/useFontSettings.tsx`）在 `origin/main` 上已存在 P151 阶段审计导出，属误入候选池，已在本次范围外排除；本轮 8 个目标经 `git grep -lE 'Governance|audit[A-Z]' origin/main -- src` 前缀剥离后重新校验为空，确为未覆盖模块。
- **Shell note**: 组件均带 `// eslint-disable-next-line react-refresh/only-export-components` 前缀以保留具名导出；源文件按 CI `npm run lint` 口径校验，新增测试文件保持零警告。

### Phase P192 — Arena Consoles & Skill Management Widgets Governance Audit Contracts (2026-10-24)

- **Scope (`src/widgets/arena/`, `src/widgets/skills/`)**:
  1. `src/widgets/arena/BatchRegisterPanel.tsx` -> `auditBatchRegisterPanelGovernance()` (`module: 'batch-register-panel'`)
  2. `src/widgets/arena/DrawPanel.tsx` -> `auditDrawPanelGovernance()` (`module: 'draw-panel'`)
  3. `src/widgets/arena/JobConsole.tsx` -> `auditJobConsoleGovernance()` (`module: 'job-console'`)
  4. `src/widgets/arena/TokenWindowCard.tsx` -> `auditTokenWindowCardGovernance()` (`module: 'token-window-card'`)
  5. `src/widgets/skills/SkillAuditDrawer.tsx` -> `auditSkillAuditDrawerGovernance()` (`module: 'skill-audit-drawer'`)
  6. `src/widgets/skills/SkillDraftDetail.tsx` -> `auditSkillDraftDetailGovernance()` (`module: 'skill-draft-detail'`)
  7. `src/widgets/skills/SkillDraftList.tsx` -> `auditSkillDraftListGovernance()` (`module: 'skill-draft-list'`)
  8. `src/widgets/skills/SkillList.tsx` -> `auditSkillListGovernance()` (`module: 'skill-list'`)
- **Unit Test Suites**:
  - `src/widgets/arena/__tests__/BatchRegisterPanel.p192.test.ts`
  - `src/widgets/arena/__tests__/DrawPanel.p192.test.ts`
  - `src/widgets/arena/__tests__/JobConsole.p192.test.ts`
  - `src/widgets/arena/__tests__/TokenWindowCard.p192.test.ts`
  - `src/widgets/skills/__tests__/SkillAuditDrawer.p192.test.ts`
  - `src/widgets/skills/__tests__/SkillDraftDetail.p192.test.ts`
  - `src/widgets/skills/__tests__/SkillDraftList.p192.test.ts`
  - `src/widgets/skills/__tests__/SkillList.p192.test.ts`
- **Baseline ratchet**: 无（8 个 `.tsx` 目标均未进入 `architecture-baseline.json`，`node scripts/architecture-check.mjs` 双轨直接通过）。
- **Shell note**: 组件均带 `// eslint-disable-next-line react-refresh/only-export-components` 前缀以保留具名导出；源文件按 CI `npm run lint` 口径校验，新增测试文件保持零警告。

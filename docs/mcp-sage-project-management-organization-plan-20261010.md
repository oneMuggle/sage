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

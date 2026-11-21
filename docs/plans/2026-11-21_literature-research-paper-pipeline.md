# 文献调研与论文产出 Agent/Skill/工作流调研及 Sage 借鉴方案

> 日期：2026-11-21
> 状态：调研完成，待评审
> 定位：为 Sage 新增"文献调研 → 综述/论文产出"能力做前期调研与方案设计

## 0. 结论摘要

1. 行业已经从"给题目直接生成论文"收敛到**证据优先流水线 + 多层引用核验 + 人类把关**：检索 → 筛选 → 证据表 → 大纲 → 分节写作 → 存在性/claim 核验 → 评审 → 导出。
2. Sage **不需要重写**文档层、RAG 层和知识层。已有：Zotero 本地文献库（9 个 MCP 工具）、CNKI 浏览器通道与登录模板、`paper-writing` 技能、期刊模板子系统、LaTeX 子系统、Playbook v1.0、专家/编排框架、研究项目脚手架。
3. 真正缺三块：
   - **学术源适配层与统一文献模型**：目前只有 CNKI URL adapter，没有 arXiv / Semantic Scholar / Crossref / PubMed 的生产实现，也没有统一 `PaperRecord` 与去重；站点能力需要用**声明式 SiteProfile**承载（xueshu789 是首个实测样例），而不是逐站点写死代码。
   - **统一证据账本（EvidenceLedger）**：引用分散在 Word references、附件 ChunkCitation、Wiki S1/S2、专家 knowledge sources、Zotero BibTeX 等多套链路，没有"文献 ↔ 页码/图 ↔ 论断 ↔ 正文位置"的单一账本。
   - **Workflow 执行引擎**：Playbook v1.0 已实现阶段/产物/门禁/规则投影；Workflow v1.1 的设计（对话驱动 + Skill-like + 软硬门禁）已存在，但主树没有生产代码。
4. 建议按 **M0 学术源与统一文献模型 → M1 最小闭环（检索→证据→大纲→分章→存在性核验）→ M2 EvidenceLedger 与 claim 核验 → M3 产出层集成 → M4 中文源/PRISMA/评测** 推进。
5. 差异化在中文与正式文档：CNKI/万方/维普登录态、中文文献、GB/T 7714、Word 期刊/学位模板、LaTeX 项目，是英文开源工具（OpenAlex/S2/arXiv 为主）覆盖不到的。

## 1. 背景与目标

Sage 已具备对话、专家（specialist）、技能（SKILL.md）、编排、知识库 RAG、受控浏览器、Word/LaTeX/PPTX 文档工作台等基础设施，并已有三个随包学术技能：

- `backend/skills/skill_md/shipped/academic-search/`：基础检索模板（CNKI 默认，`web_fetch` + LLM 解析）。
- `backend/skills/skill_md/shipped/cnki-research/`：知网浏览器通道（登录态、SPA 等待、iframe、PDF 下载与校验、合规边界）。
- `backend/skills/skill_md/shipped/paper-writing/`：五步论文写作（大纲确认 → 分章落盘 → BibTeX/引用 key → `office_create` 生成 GB/T 7714 引用的 docx → `office_lint_word` 自检修复）。

另外，研究项目已有脚手架（`01_literature` / `02_experiments_and_data` / `03_manuscript` / `04_submission_and_rebuttal`，SAGE.md 内置"零幻觉引用铁律"），Playbook v1.0 已支持阶段、产物、退出条件与规则；Workflow v1.1 的设计文档在 `docs/superpowers/specs/2026-11-10-workflow-design.md`。

本调研的目标：

1. 梳理 2025–2026 年文献综述 / 论文产出 agent、skill、工作流的代表系统与主流架构。
2. 提炼可借鉴的工程经验与失败教训（引用幻觉、核验器可靠性、人类把关）。
3. 给出与 Sage 现有架构和设计偏好（对话驱动 + Skill-like markdown + 软/硬门禁分层 + 编排引擎驱动 + 双轨存储）吻合的落地方案。

**非目标**：做一个"一键自动发表"的全自动驾驶系统。领域综述（arXiv:2605.18661）的结论是：AI 在检索支撑、结构化、工具化环节可靠，在原创性判断、研究级实验与科学判断上仍脆弱；"更高的自动化会掩盖而非消除失败模式"，人类治理的协作模式最可信。

## 2. 行业谱系

### 2.1 全景梳理

| 类别 | 代表项目 | 核心做法 |
|---|---|---|
| 检索支撑的深度写作 | **STORM / Co-STORM**（Stanford OVAL） | 多视角提问 → 检索回答 → 大纲 → 带引用的长篇百科式文章；Co-STORM 支持人机圆桌与思维导图 |
| 文献问答与合成 | **PaperQA2**（FutureHouse）、**OpenScholar**、**Ai2 Scholar QA** | 对论文全文做 agentic RAG，段落级引用；OpenScholar 面向 4500 万篇开放论文，提出 ScholarQABench 基准 |
| 端到端论文写作 | **OpenDraft**、**PaperOrchestra**（Google）、**seele-scholar-agent**、**open-academic-paper-gen** | 多阶段 agent 流水线：检索 → 大纲 → 分节写作 → 引文核验 → 评审 → PDF/Word/LaTeX 导出 |
| 综述生成 | **SEER**、**SurveyX**、**AutoSurveyGPT**、**ARISE** | 递归大纲树 + 回溯修复（SEER）；22 个角色化 agent + rubric 迭代（ARISE） |
| Claude Code / Codex 技能包 | **academic-research-skills（ARS）**、**claude-scholar**、**cnki-skills** | 用 SKILL.md + 多 agent + 脚本把完整科研流程打包进 agent，带完整性门禁 |
| 自主科研系统 | **AI-Scientist v2/v3**、**Agent Laboratory**、**AI-Researcher**、**Sisyphus Academica** | 文献 → 想法 → 实验 → 论文 → 自评审的完整闭环；多数包含 GPU 实验环节 |
| 工具与数据层 | **arxiv/semantic scholar/OpenAlex/PubMed/Zotero MCP**、**paper-search-mcp** | 把学术检索、引用管理、PDF 解析能力做成 MCP 工具 |

维护较好的工具清单：

- [lit-review-agent-tools](https://github.com/brycewang-stanford/lit-review-agent-tools)：70+ 工具，按 search / screen / extract / read / synthesize / cite-check / write / review 八阶段分类。
- [Awesome-Auto-Research-Tools](https://github.com/handsome-rich/Awesome-Auto-Research-Tools)：按自主科研、深度调研、实验实现、学术写作分类。

### 2.2 值得细看的代表系统

**STORM（Stanford）**：把"写作前调研"显式化——模拟多个专家视角，各自提出问题，检索回答，再汇总成大纲与长文。论文（arXiv:2402.14207）显示多视角提问优于直接 RAG。Co-STORM 引入多个 agent 与主持人进行圆桌讨论、维护动态思维导图、允许用户随时插话。启示：**大纲质量取决于"先问对问题"，而不是直接生成目录**。

**PaperQA2 / OpenScholar**：把引用做成"检索段落 + 精确出处"的证据链。OpenScholar 的基准显示，无检索基线的引用幻觉率高达 78–98%（标题级），而检索支撑系统可达接近人类专家的引用准确率。启示：**引用只能来自本地文献池，不能让模型自由生成参考文献**。

**OpenDraft**：19 个 agent、6 个阶段（research / structure / compose / validate / refine / enhance），参考文献保留条件是"Crossref、OpenAlex、Semantic Scholar 至少两家能查到该 DOI"；同时提供 PDF/Word/LaTeX 导出，并以 Claude Skill 形态分发。启示：**多源交叉核验存在性是低成本、高收益的硬门禁**。

**open-academic-paper-gen**：把引用核验拆成三层——标记可解析、DOI/元数据可核对、被引论文确实支持该句（claim support）；证据表按论文逐行抽取（任务/方法/数据/指标/发现/局限），并带 PRISMA 计数与人工确认门。启示：**"存在"不等于"支持"，claim-level 核验必须单独一层**。

**SEER**：递归大纲树 + 父节点回溯修复（提升/降级/移动/合并/删除子节点）+ 各叶子并行写作 + 共享 PaperDB + 引文归一化 + LaTeX/PDF 导出；配套 `auto-survey-agent` Codex 技能，自带 `papers.jsonl`、质量门禁脚本与输出契约。启示：**长综述需要结构级修复能力，且技能应自带确定性脚本与输出契约**。

**academic-research-skills（ARS）**：四个模块（Deep Research 13 agent、Academic Paper 12 agent、Reviewer 7 agent、Pipeline 10 阶段），阶段 2.5 / 4.5 设不可跳过的完整性门禁（7 类 AI 研究失败模式清单），反谄媚协议、三层数据隔离、风格校准、Markdown/DOCX/LaTeX 输出。启示：**把"门禁"做成流程中的一等公民，并且默认 human-in-the-loop**。

**claude-scholar**：七阶段科研助理，集成 Zotero MCP、Obsidian 知识库、证据记录（Evidence Record）、主张强度与 Claim Promotion Gate、pubfig/pubtab 出版级图表。启示：**证据要成为可复用资产，主张要分级，不能一段文字里所有结论等权**。

**AI for Auto-Research 路线图**（arXiv:2605.18661）：四阶段八环节（Creation / Writing / Validation / Dissemination）的领域综述。核心结论：AI 在检索支撑、工具化任务上强，在真正新颖的想法、研究级实验与科学判断上脆弱；人类治理的协作模式最可信。启示：**产品定位应是"研究者副驾驶"，不是"自动投稿机"**。

### 2.3 中文文献生态

英文社区的系统几乎全部围绕 OpenAlex / Semantic Scholar / arXiv / PubMed。中文知网生态的接入大多是浏览器自动化：

- [cnki-mcp-server](https://pypi.org/project/cnki-mcp-server/)：搜索、详情、引用格式化、期刊浏览、BibTeX/RIS 导出。
- [cookjohn/cnki-skills](https://github.com/cookjohn/cnki-skills)：Claude Code skills + agent，经 Chrome DevTools MCP 完成搜索、翻页、详情、下载、Zotero / GB/T 7714 导出。
- [HUST CNKI Research MCP](https://github.com/graywind-labs/hust-cnki-research-mcp)：机构 SSO、授权 HTML 全文、PDF 下载。

这类方案共同依赖：登录态、浏览器自动化、验证码人工处理、机构权限。**这恰好是 Sage 受控浏览器（§159）、站点登录模板、凭据档案与会话探针的强项**，也是相对英文工具最清晰的差异化空间。

## 3. 可借鉴的架构模式

### 3.1 证据优先的流水线，而不是"直接写"

几乎所有可靠系统的共同结构：

```
Scoping → 多源检索 → 去重/筛选 → 证据抽取 → 主题/缺口分析
→ 大纲（可回溯修复）→ 分节写作（引用受限于文献池）
→ 引用核验（存在性 + claim support）→ 评审 → 组装/导出
```

写作发生在证据之后；每个阶段有可检查的中间产物（检索日志、文献池、证据表、大纲、草稿、核验报告）。这比"给一个题目直接生成论文"可靠一个数量级。

### 3.2 引用必须"先有池，后有引"

- 引用键（`[cite:KEY]`）只能解析到文献池中的记录；无法解析即视为幻觉。
- 存在性核验：DOI 在 Crossref / OpenAlex / Semantic Scholar 至少两家可查（2-of-3 共识）。
- 元数据核验：标题、作者、年份、页码与真实记录一致。
- claim 支持性核验：被引段落是否真的支持该句；有全文时定位到 PDF 页。

### 3.3 核验本身不可全信，要留出人工复核预算

2026 年的引用忠实度审计（arXiv:2607.20527）发现：同一批 agent 输出，因核验器严格程度不同，"不支持引用率"可在约 3%–18% 之间变化；不同核验器对"哪些该标记"的一致性只有 0.27–0.30。结论：**不要承诺"零幻觉"，要做有界、可解释、可复核的标记系统**——核验器给出分数与证据，人工按预算复核，而不是静默删除引用。

### 3.4 结构级修复优于一次性生成

SEER 的递归大纲树 + 父节点回溯，解决了长综述中的冗余、层级冲突与覆盖不均。工程上不必一步到位：先做"一次大纲 + 一次回溯整理"，再考虑多级递归。

### 3.5 技能自带脚本与输出契约

SEER 的 `auto-survey-agent`、ARS 的 pipeline 都在 SKILL.md 之外附带：

- 确定性脚本（检索、去重、质量门禁、渲染、导出）；
- 输出契约（`meta.json`、`papers.jsonl`、`outline.json`、`draft-validation.json` 等固定目录结构）；
- 可恢复的运行目录与轨迹（traces）。

让 agent 的自由发挥被"文件契约 + 脚本门禁"约束，而不是靠 prompt 祈祷。Sage 的 SKILL.md 规范（§28）已支持 `scripts/`、`references/`、`templates/`，可直接沿用。

### 3.6 人类把关点

成熟系统普遍在以下位置停下确认：研究问题与范围、纳入/排除标准与筛选结果、大纲、最终稿（以及任何会被标记为"结论"的主张）。这与 Sage 的计划确认（PR #3008/#3009）和 Playbook/专家的"AI 自主 + 人类最终裁决"哲学一致。

### 3.7 统一证据账本是共同趋势

PaperQA2/OpenScholar 的段落级引用、open-academic-paper-gen 的 claim-support 检查、claude-scholar 的 Evidence Record + Claim Promotion Gate，本质都是把"论断 ↔ 证据 ↔ 出处"做成可审计的结构。Sage 当前引用链路分散（见 §4.5），需要补一个统一账本。

## 4. Sage 现有能力盘点

### 4.1 文献输入层

| 模块 | 路径 | 能力 | 复用度 |
|---|---|---|---|
| `academic-search`（shipped） | `backend/skills/skill_md/shipped/academic-search/` | CNKI 默认；URL → `web_fetch` → LLM 解析为 Markdown 列表 | 中（骨架） |
| `cnki-research`（shipped） | `backend/skills/skill_md/shipped/cnki-research/` | 登录态、SPA 等待、iframe、PDF 下载校验、限速、验证码交还用户、合规边界 | 高 |
| builtin `AcademicSearchSkill` | `backend/skills/builtin/academic_search.py` | `BaseSkill` 封装"构造 URL → `web_fetch` → 可选问排序 → 组装解析 prompt" | 中 |
| 适配器注册表 | `backend/skills/builtin/academic_adapters.py` | `AcademicSiteAdapter` 协议 + `CNKIAdapter` + `register_site_adapter()`；仅注册 `cnki` | 中（扩展点） |
| Zotero 本地库 | `backend/zotero/client.py` | 只读 SQLite：search / iter / get_item / annotations / collections / read_pdf_fulltext / get_bibtex / items_by_tag | 高 |
| Zotero 索引 | `backend/zotero/ingest.py`、`service.py`、`wiki_export.py` | 每篇一个 chunk → `data/rag/zotero.json`；语义检索优先、SQL LIKE 降级；带 `sage:wiki` 标签导出为 wiki 文献页 | 高 |
| Zotero MCP | `backend/mcp/servers/zotero/server.py` | 9 工具：status / search / get_item / get_annotations / list_collections / get_bibtex / read_pdf / related / sync | 高 |
| 站点登录 | `backend/services/site_login_templates.py`、`site_login_jobs.py`、`site_session_probe.py` | CNKI / 万方 / 维普 / IEEE Xplore / SpringerLink 登录入口、后台登录任务、登录态探测；凭据加密档案 | 高 |
| 受控浏览器 | `backend/tools/browser_tool.py`、`services/browser_safety.py`、`domain/network_policy.py` | 10 个 `browser_*` 工具、持久 profile、iframe 扫描、下载、站点策略、敏感动作确认、审计 | 高 |
| PDF 精读 | `backend/services/attachment_pdf.py`、`attachment_rag.py`、`attachment_context.py` | 页标记、OCR、图表抽取、图注清单、`<attached_figures>`、RAG 页码反查 | 高 |
| 网络调研 | `backend/wiki/deep_research.py`、`orchestration/scout_deep.py`、`research_report.py` | 3–5 查询 → 多查询检索 → LLM 综合（≤10 来源）→ 结构化 `findings/sources/confidence/synthesis`；前端 `ResearchSummaryCard` | 高（可改学术源） |
| 文献索引 | `backend/wiki/literature_aggregator.py` | 扫描 `wiki/zotero/items/` 与 `wiki/literature/`，生成按年份分组的 `index.md`；Zotero 同步后自动触发 | 中 |
| 研究项目脚手架 | `backend/services/project_subtypes.py`、`project_archetype_scaffold.py`、`project_constraint_repo.py` | `literature_review` / `academic_paper` 等子类型；`01_literature`…`04_submission_and_rebuttal` 目录；SAGE.md 零幻觉引用铁律 | 高 |

**缺口**：arXiv / Semantic Scholar / Crossref / PubMed 无生产 adapter；无统一 `PaperRecord`、去重、筛选、结构化检索日志；没有"站点 profile"机制。`xueshu789`（学术资源站）尚未集成，但它已用 Sage 受控浏览器完成登录、检索、PDF 下载实测，作为**首个可插拔站点 profile 的样例**（见 §5.3.1）。

### 4.2 知识沉淀层

| 模块 | 路径 | 能力 | 复用度 |
|---|---|---|---|
| Wiki 管线 | `backend/wiki/ingest.py`、`embeddings.py`、`vectorstore*.py`、`rrf.py`、`search.py`、`chat.py` | 六步 ingest、JSON/HNSW 向量库、RRF 融合、CJK token 搜索、S1/S2 引用与会话问答 | 高 |
| 附件 RAG | `backend/services/attachment_rag.py`、`attachment_context.py` | `data/rag/attachments.json`、chunk 幂等替换、页级 `ChunkCitation`、fail-open | 高 |
| 项目资料向量 | `backend/services/project_material_indexer.py` | sqlite-vec 表、后台索引、`semantic_search(project_id, query, top_k)` | 高 |
| 知识绑定 | `backend/agents/knowledge_binding.py`、`knowledge_retriever.py` | 六类源：wiki_project / zotero_collection / project_material / workspace_fts / specialist_private / sage_docs；RRF 融合、单源隔离 | 高 |
| 专家知识 | `backend/chat/specialist_knowledge.py`、`specialist_prompt_composer.py` | `<knowledge_context>` 注入、`kind="knowledge"` 来源、无命中拒答 | 高 |

**缺口**：`zotero_collection` 已在类型里声明，但 `knowledge_retriever` 的默认 searchers 尚未接入，且 Zotero 语义检索结果不带 collection 键；缺少统一 EvidenceLedger。

### 4.3 产出层

| 模块 | 路径 | 能力 | 复用度 |
|---|---|---|---|
| `paper-writing`（shipped） | `backend/skills/skill_md/shipped/paper-writing/` | 五步论文写作；`office_create` 的 `format_spec`/`references`/`citations`；GB/T 7714；交叉引用；目录/图表清单；`office_lint_word`/`office_repair_word` | 高 |
| Office 生成 | `backend/tools/office_create_tool.py`、`office_update_tool.py`、`office_tool.py` | Word/Excel/PPT/PDF；格式、编号、页眉页脚、目录、图表索引；快照回滚 | 高 |
| 引用实现 | `backend/office/references.py`、`backend/office/word.py`、`backend/tools/office_bibtex_tool.py` | GB/T 7714-2015 顺序编码制 + APA 简化子集；按正文首现编号；`_resolve_references` 校验未定义/未引用 key；自动生成参考文献节 | 高 |
| 期刊模板子系统 | `backend/office/journal/`（parser / pandoc_adapter / generator / llm_adapter / validator / persistence）；工具 `office_journal_*`；前端 `src/features/journal/JournalPanel.tsx` | 从 `.doc/.docx` 抽取 `JournalSpec`；结构化填充；六类规则校验（body/heading font、line spacing、margins、headings、citations） | 高 |
| LaTeX 子系统 | `backend/office/latex/`（parser / scanner / template / filler / audit / compile / pdf_audit / compliance / diff / project）；9 个 `office_*latex*` 工具 | 容错解析、模板 Profile、源码审校、可选编译、PDF 审计、合规检查、latexdiff、项目 zip 导入 | 高 |
| Word 模板与规则 | `backend/office/word_template.py`、`word_lint.py`、`word_repair.py`、`word_render_audit.py`、`word_rulepack_*` | docxtpl 模板分析/填充、格式回读校验、确定性修复、渲染级审计、规范书规则库 | 高 |
| 图表与 PPT | `backend/office/charts.py`、`ppt.py`、`ppt_template.py`、`backend/design/content/systems/academic/DESIGN.md` | matplotlib/openpyxl 图表、CJK 字体回退、PPTX 模板；学术出版视觉系统 | 中–高 |
| PDF 导出与文档库 | `backend/office/export_pdf.py`、`generated_store.py`；`backend/data/artifact_repo.py` | LibreOffice/Word COM 导出；`office_documents` 与 `artifacts` 两套账 | 高 |

**缺口**：引用样式只支持 GB/T 7714 + APA 简化子集，没有 CSL/citeproc（IEEE/Elsevier/Springer 等需扩充）；Journal 子系统只生成本地 docx，不对接投稿系统；无 DOCX ↔ LaTeX 双向转换；`office_documents` 与 `artifacts` 两套账未统一。

### 4.4 编排与工作流层

| 模块 | 路径 | 能力 | 复用度 |
|---|---|---|---|
| 编排引擎 | `backend/orchestration/`（planner / router / executor / lane_registry / task_registry / team_registry / policy_engine / approval_tokens / report_schema / subagent_runner / chat_dispatcher / plan_preflight / templates / topology / workflow_mode / task_review） | lane/task/team 模型、策略引擎（retry/merge/approval）、ReviewReport、子代理、复杂度分类、计划预检、TDD/快速模式 | 高 |
| 聊天编排 | `backend/orchestration/chat_dispatcher.py`、`backend/tools/subagent_tool.py` | single/multi 判定、Planner 拆任务、`dispatch_subagents` 并行派发、`task_plan`/`task_progress`/`task_status` 事件、reviewer 复核环、lane 镜像 | 高 |
| 默认角色 | `backend/agents/profiles.py` | `researcher`（web + 浏览器）、`writer`（write_file + office）、`reviewer`、`coder` 等 | 高 |
| 专家模板 | `backend/services/specialist_templates/`（research / writing / office / presentation / coding / sage-guide） | persona v2、技能声明、知识绑定、工具白名单、记忆策略 | 高（框架） |
| Playbook v1.0 | `backend/services/playbook_*.py`、`playbook_builtin/research_grant.json`、`playbook_builtin/personal_knowledge.json` | 阶段、产物、退出条件、规则投影、里程碑、对话式编排、文档导入、分享；`research_grant` 已含 `literature_matrix` 产物与 `citation_strict` 规则 | 高 |
| Workflow v1.1（设计） | `docs/superpowers/specs/2026-11-10-workflow-design.md` | 对话驱动 + Skill-like + 软/硬门禁；Workflow = Playbook 超集（`stage_order`/`required_stages`/`recommended_specialists`/`inputs`/`outputs`/`gate`/阶段 `executor`）；阶段 = orchestration lane；运行目录 `<workspace>/.sage/workflow/<run_id>/<stage_id>/`（`outputs.json` + `files/` + `trace.jsonl`） | 设计可直接采用，**生产代码未落地** |

**注意**：研究专家 persona 声明了 `literature-review` / `fact-check` / `summarize-papers`，写作专家声明了 `polish-prose` / `structure-outline`，这些 SKILL.md **目前不存在**，属于"声明存在、实现缺失"。

### 4.5 缺口总结（按优先级）

**P0**
- 学术源适配层：arXiv / Semantic Scholar / Crossref / PubMed 的生产 adapter，统一 `PaperRecord`（标题/作者/年份/venue/DOI/arXiv ID/摘要/引用数/全文路径/来源），去重与结构化检索日志。
- Workflow 执行引擎：把 Workflow v1.1 的设计落地，或先扩展 Playbook v1.0 增加阶段 executor。

**P1**
- 统一 EvidenceLedger：文献 key ↔ 页码/图 ↔ 论断 ↔ 正文位置；把 Word references、附件 ChunkCitation、Wiki S1/S2、专家 knowledge sources、Zotero BibTeX 收敛为一个可审计账本。
- 引用真实性核验：DOI/标题/作者/年份与 Zotero/Crossref/S2 对照；`paper-writing` 目前只校验 key 是否定义/被引用，不校验外部真值。
- Zotero collection 知识绑定：补 searcher 与 collection 过滤，让"课题文献集合"成为专家/会话知识源。
- 系统化综述能力：`literature_aggregator` 只是按年份索引；缺 PRISMA、纳入/排除标准、质量评估、方法对比矩阵、研究空白归纳、引用网络。

**P2**
- CSL/citeproc 引用样式（IEEE/Elsevier/Springer 等）。
- `xueshu789` 合规评估与集成策略。
- DOCX ↔ LaTeX 双向转换。
- 文献站点改版稳定性：把站点解析策略放进可编辑 skill/markdown，而不是硬编码。

## 5. 建议方案

### 5.1 总体形态

采用"**Workflow v1.1 落地 + Skill-like 阶段定义 + 确定性脚本门禁 + 复用现有编排与产出层**"的形态，不引入 LangGraph/CrewAI 之类外部编排框架：

```
用户对话（对话驱动，阶段可暂停/重跑/跳过）
   ↓
Workflow：literature-research（skill-like markdown + scripts/ + references/）
   ├─ 检索阶段复用 academic-search / cnki-research / Zotero MCP / 新学术源 adapter
   ├─ 精读阶段复用 attachment_pdf / attachment_rag / page citation
   ├─ 写作阶段复用 paper-writing
   └─ 产出阶段复用 office/journal / office/latex / charts
   ↓
编排层 lanes：scoping → search → screen → evidence → outline → draft → verify → review → export
   ↓
数据层：Zotero（主库）+ PaperDB/EvidenceLedger（项目快照）+ 运行目录
   ↓
门禁层：确定性脚本（schema/引用/计数/格式）+ LLM 核验（claim support / rubric）
   ↓
产出层：Markdown / DOCX（paper-writing/journal）/ LaTeX / PDF + 核验报告
```

### 5.2 统一文献模型与证据账本

**不复制 Zotero**。Zotero 是用户既有文献库的事实来源；PaperDB 是项目级"物化视图 + 证据记录"，只存本次运行实际使用的子集与抽取结果。

建议新增表（迁移与现有 DB 版本管理一致）：

- `paper_records`：`paper_key`（DOI / arXiv ID / Zotero item key / CNKI 导出 ID）、标题、作者、年份、venue、摘要、URL、来源、语言、类型、全文路径、解析 Markdown、去重指纹、来源元数据。
- `paper_evidence`：`evidence_id`、`paper_key`、证据类型（任务/方法/数据/指标/发现/局限/引文）、文本、页码/段落/图号、原文片段、抽取模型、置信度。
- `paper_claims`：`claim_id`、草稿位置（section/paragraph/span）、论断文本、引用 key 列表、核验状态（supported / flagged / unsupported / unclear）、核验器与分数。
- `paper_query_log`：检索式、数据库、时间、结果数、去重数、纳入数、失败/降级原因（复现与 PRISMA 计数）。

**EvidenceLedger** 作为统一接口：任何引用（Word references、附件 ChunkCitation、Wiki S1/S2、专家 knowledge）都通过 `paper_key` 映射到证据记录；导出时按账本生成参考文献与核验报告。

去重优先级：DOI > arXiv ID > Zotero item key > 规范化标题 + 第一作者 + 年份。语义检索复用现有嵌入与 RRF。

### 5.3 检索适配层

| 适配器 | 方式 | 说明 |
|---|---|---|
| OpenAlex / Crossref / Semantic Scholar / arXiv | REST API | 首选，结构化、可缓存、可离线回放；新增到 `academic_adapters` 或独立 `backend/literature/adapters/` |
| CNKI / 万方 / 维普 / IEEE / SpringerLink | 受控浏览器 + 站点登录模板 | 复用 `cnki-research`、`site_login_templates`、`site_login_jobs`、`site_session_probe`、`credential_vault`；验证码/登录失效暂停并请求接管 |
| Zotero | 现有 MCP / `backend/zotero/*` | 个人文献库作为高质量子集；补 collection 过滤与知识绑定 |
| 用户 PDF 导入 | `attachment_pdf` / MinerU / OCR | 本地全文、页级证据、图表抽取 |
| `xueshu789`（学术资源站） | 受控浏览器 + SiteProfile | 已实测：卡号+密码登录 → `/dbList/1`；站内知网代理检索；行尾 `a.downloadlink` 下载 PDF。作为**首个可插拔站点示例**，通过 profile 适配，不写死代码；默认用户本地启用，仅使用本人账号/机构授权 |

所有检索记录 `paper_query_log`，包括失败与降级（如 Semantic Scholar 限流回退 OpenAlex）。

#### 5.3.1 站点适配协议（SiteProfile）：用配置适配，不写死代码

目标：新增一个文献站点 = **新增一份 profile（+ 可选一段 skill 说明）**，不改检索、证据、核验、产出各层代码。xueshu789 是第一个按此协议落地的实测样例。

**分层**

| 层 | 位置 | 作用 |
|---|---|---|
| 内置站点 | `backend/literature/sites/*.yaml` | CNKI / 万方 / 维普 / IEEE / SpringerLink 等随包 profile |
| 用户站点 | `~/.sage/literature_sites/*.yaml` | 用户自建/覆盖（如 xueshu789），按 `id` 覆盖内置 |
| 项目站点 | `<workspace>/.sage/literature_sites/*.yaml` | 单个项目专用 |
| 通用适配器 | `backend/literature/browser_adapter.py` | 解释 profile，调用 `browser_*` 工具完成 search/detail/download |
| 可选钩子 | profile 引用 `scripts/<site>.py` | 仅在声明式表达不了时使用（如下载 token 特殊处理） |

**SiteProfile 字段（最小集）**

```yaml
id: xueshu789
display_name: 学术资源站
home_url: https://www.xueshu789.cc/
domains: [xueshu789.cc]
access:
  mode: browser                 # browser | rest | hybrid
  login:
    method: form                # form | sso | qr | manual
    account_label: 您的卡号      # 仅用于提示，不存明文
    password_label: 您的密码
    logged_in_check:
      url_contains: /dbList/
      title_not_contains: 登录
capabilities: {search: true, detail: true, pdf_download: true, fulltext: true}
search:
  url_template: "https://www.xueshu789.cc/dbItem/1?kw={query}"   # 待实测校准
  wait_for: [".result-list"]
  pagination: {type: click_text, text: 下一页}
  result_fields:
    title: {selector: "TODO"}
    authors: {selector: "TODO"}
    source: {selector: "TODO"}
    year: {selector: "TODO"}
detail:
  open_by: click_text           # 点击结果标题进入详情
  fields: {abstract: "TODO", keywords: "TODO"}
pdf:
  entry: {selector: "a.downloadlink"}
  forbid: [CAJ]
  validate: {magic: "%PDF-", title_match: true}
rate_limit: {min_interval_s: 5, max_batch: 20}
compliance:
  note: 仅使用本人账号/机构授权；不绕过付费墙；验证码交还用户
  default_enabled: false
```

**三条设计约束**

1. **检索结果统一归一化**：无论站点是 API 还是浏览器，适配器只输出 `PaperRecord`（标题/作者/年份/venue/摘要/URL/DOI/全文路径/来源站点/检索式/时间），下游去重、证据、核验、写作完全不知道站点差异。
2. **站点差异只允许出现在三处**：profile 字段、skill 的 `references/site-profiles.md` 说明、可选的窄接口脚本。禁止在 pipeline 里写 `if site == "xueshu789"`。
3. **登录与下载沿用现有安全边界**：`browser_login` + 站点登录模板 + `credential_vault`；不代填密码、不导出 cookie、不绕过付费墙；验证码/滑块暂停并交还用户。

**profile 的三种生成方式**

- **手写**：按 schema 填 YAML；适合结构稳定的站点。
- **录制生成**（推荐给 xueshu789 这类站点）：用户在可见浏览器里演示一次"登录 → 搜索 → 点详情 → 下载"，Sage 记录 URL 迁移、`browser_snapshot`、ref/选择器与下载入口，生成 profile 草稿，人工确认后保存。这与现有 `skill_save`"把一次成功工具序列沉淀为技能草稿"的模式一致。
- **LLM 辅助**：把页面 snapshot 交给 LLM 起草 profile，再用一次真实检索做校验。

**profile 校验（硬门禁）**

- 保存前 dry-run 一次检索：结果数 > 0、必填字段非空、详情页可打开。
- 用保存的 snapshot/HTML 做离线 fixture 测试，站点改版时能快速定位哪个选择器失效。
- profile 带 `version` 与 `last_verified_at`；失败时提示"站点可能改版，请重新录制"。

### 5.4 流程阶段与门禁

| 阶段 | 软约束（给 LLM 的 Skill/Workflow 指引） | 硬门禁（确定性脚本） | 人工确认 |
|---|---|---|---|
| Scoping | 对话澄清问题、范围、语言比例、纳入标准 | schema 校验 | ✅ 范围确认 |
| Search | 多关键词、多库、引文链扩展 | 检索日志完整、最少来源数 | 可选 |
| Screen | 按纳入/排除标准筛选并说明理由 | 计数一致、重复记录为 0 | ✅ 筛选结果 |
| Evidence | 逐篇抽取证据，禁止跨论文臆测 | 必填字段完整、页码/段落可定位 | 可选 |
| Outline | 主题轴选择、覆盖检查；可选一次回溯整理 | 章节 schema、来源覆盖度 | ✅ 大纲确认 |
| Draft | 分节写作、`[cite:KEY]` 受限、先综合后比较 | 引用 key 全部可解析 | 否 |
| Verify | 存在性、元数据、claim support | DOI 2-of-3、元数据匹配、核验报告生成 | 复核标记项 |
| Review | 方法/覆盖/逻辑/写作 rubric 评审 | 评分与问题清单 schema | 可选 |
| Export | 参考文献只列实际引用、格式统一 | GB/T 7714 / APA / IEEE 规则检查 | 最终确认 |

门禁失败时流程暂停并给出可操作的修复建议；不允许"补写一段话糊弄过去"或"编造引用"。

### 5.5 产出层集成

- **Word（已有基础）**：`paper-writing` 已覆盖 `office_create`、GB/T 7714、交叉引用、目录/图表清单、`office_lint_word`/`office_repair_word`。本方案只需把"证据驱动的分章草稿 + 结构化唯一条目"按该技能的入参契约交接过去。
- **期刊模板**：复用 `office/journal/`（parser/generator/llm_adapter/validator）与 `office_journal_*` 工具，补常见中文期刊/学位论文模板；用六类规则做合规校验。
- **LaTeX**：复用 `office/latex/`（template/filler/audit/compile/pdf_audit/compliance/latexdiff）与 9 个工具，输出可编辑项目（`main.tex` + `references.bib` + `figures/`）。
- **图表**：复用 `office/charts.py`、Design Studio 与 §156 图表清单，保证正文有编号引用。
- **风格校准**：让用户提供 2–3 篇旧作，抽取句式、段落长度、术语偏好，形成可复用的写作画像（存记忆/项目资产）。

### 5.6 双轨存储与超集扩展

- **全局库**：Workflow/Playbook 库、领域 profile（自然科学/医学/社科/人文/工程/交叉）、综述模板、评审 rubric、引用样式、写作风格画像。
- **项目快照**：研究项目脚手架（`01_literature`…`04_submission_and_rebuttal`）+ `.sage/workflow/<run_id>/<stage_id>/` 运行目录 + PaperDB/EvidenceLedger 子集 + 导出文件。
- 现有 `academic-search` / `cnki-research` / `paper-writing` 保持可用并继续演进；新 `literature-research` 作为**流程编排层**引用它们，不替代、不改名、不破坏用户已有派生版本。

### 5.7 与 Sage 交互形态的结合

- 入口：对话中说"帮我做某个主题的文献调研/综述"，命中 `when_to_use` 自动激活，并提供 `/literature-research` slash 命令。
- 站点选择：对话中确认"这次用哪个文献源"（如 xueshu789 / 知网 / OpenAlex），选择写入运行目录便于复现；用户可保存默认站点偏好。加新站点时只需提供 profile，不需要改对话流程。
- 阶段推进：复用 `task_plan / task_progress / task_status` 事件驱动前端任务树；阶段产物以 artifact 形式可预览（大纲、证据表、核验报告）。
- 人工确认：复用现有计划确认与 `ask_user_question`，不新造表单流程。
- 失败处理：阶段失败可暂停、可重跑单个 lane、可回到上一阶段；运行目录持久化，跨会话可恢复。
- 专家形态：可打包为"文献调研专家"（research persona + 私有记忆 + 技能 + 知识绑定）。

## 6. 实施步骤（里程碑）

### M0：学术源与统一文献模型（1–2 周）

> **M0a 已完成（2026-11-21，分支 `feat/literature-research-pipeline`）**：
> `backend/literature/` 领域模型 + 三级 profile 加载器 + LLM 检索指导 +
> `ProfileBackedAdapter` + `xueshu789` profile 草稿。测试：
> `backend/tests/unit/test_literature_site_profiles.py`（24 例）。

- [x] 定义 `PaperRecord` schema（`backend/literature/models.py`）。
- [ ] 定义 `EvidenceRecord` / `ClaimRecord` schema 与迁移。
- [x] 定义 `SiteProfile` schema 与三级加载器（内置 / 用户 / 项目，按 `id` 覆盖）。
- [ ] 实现通用 `browser_adapter`（解释 profile：search/detail/download），以及"录制生成 profile 草稿"的最小流程（已实现 profile 解析 / URL 渲染 / LLM 指导；真实浏览器执行与录制留 M1）。
- [ ] 以 xueshu789 为首个样例：录制登录→检索→详情→下载，生成 profile 草稿并完成一次真实检索 + 一篇 PDF 下载验收（profile 草稿已随包分发，`status: draft`；选择器录制与实跑验收留 M1）。
- [ ] 实现 OpenAlex、Crossref、Semantic Scholar、arXiv 四个 REST adapter（缓存、限流、失败降级、离线回放）。
- [ ] 在 profile 注册表注册 CNKI 浏览器站点（复用 `cnki-research` 与站点登录模板）。
- [ ] 去重（DOI > arXiv ID > Zotero key > 标题+作者+年份）、规范化、BibTeX/RIS/CSL-JSON 导出。
- [ ] 钉住 `paper_query_log`，记录检索式/数据库/时间/结果数/失败原因。
- [ ] 补齐 Zotero collection 过滤与 `knowledge_retriever` 接入。
- [x] 单元测试：profile schema / URL 渲染 / 登录判定 / 三级覆盖 / 无效 profile / 适配器回退。
- [ ] 单元测试：去重优先级、元数据映射、限流降级、profile 离线 fixture（含 xueshu789 snapshot）。

### M1：Workflow 最小闭环 + literature-research v1（2–3 周）

> **M1a 已完成（2026-11-21，分支 `feat/literature-research-m1`）**：
> 运行目录 + JSONL 契约 + 确定性门禁 + Markdown/BibTeX 导出 + profile
> 浏览器执行器 + 录制 helper + CLI + `literature-research` shipped skill。
> 测试：`backend/tests/unit/test_literature_pipeline.py`（26 例，含
> 端到端合成闭环）。真实网络/编排 lane 实跑留 M1b。

- [ ] 落地 Workflow v1.1 的最小执行器（`workflow_spec` / `gate_eval` / `loader` / `store` / `artifacts` / `executor` / routes），或先扩展 Playbook v1.0 增加阶段 executor。
- [x] 新增 `literature-research` shipped skill（SKILL.md + `references/pipeline.md`），检索阶段统一走 `SiteProfile` 注册表（xueshu789 / CNKI / 学术 API 都是同一种站点），不改动现有技能行为。
- [x] 实现 scoping → search → screen → evidence → outline → draft → verify（仅存在性）→ export(Markdown) 的确定性骨架（run store / gates / export / CLI；语义检索与写作由 LLM 按 skill 执行）。
- [ ] 接入编排 lanes、阶段事件、运行目录与恢复；产物写入 `<workspace>/.sage/workflow/<run_id>/<stage_id>/`（M1b）。
- [x] 硬门禁：schema 校验、引用 key 解析、检索日志完整性、参考文献只列已引用。
- [x] 与 `paper-writing` 的交接契约：`build_handoff` 产出 `references` 条目 + 分章 Markdown 路径（docx 实跑留 M1b）。
- [x] 端到端测试：合成文献集跑通"检索日志→文献池→证据→大纲→草稿→门禁→导出"（真实 10–20 篇文献实跑留 M1b）。

### M2：EvidenceLedger 与引用核验（2 周）

- [ ] 统一 EvidenceLedger 接口，收敛 Word references、附件 ChunkCitation、Wiki S1/S2、专家 knowledge sources、Zotero BibTeX 的引用记录。
- [ ] 三层引用核验：标记解析、DOI/元数据 2-of-3、claim support（含 PDF 页定位）。
- [ ] 核验报告 UI（artifact）：支持、待复核、不支持、无法核验四态；不静默删除引用。
- [ ] Rubric 评审：方法、覆盖、逻辑、写作四维评分 + 问题清单；明确"模拟评审，非同行评审"。
- [ ] 引用样式：在 GB/T 7714 / APA 基础上评估 CSL/citeproc 或至少补 IEEE。

### M3：产出层集成（2–3 周）

- [ ] 与 `paper-writing` 深度集成：流水线输出直接喂给 `office_create` 的 `paragraphs`/`references`，复用 GB/T 7714、交叉引用、目录/图表清单、lint/repair。
- [ ] 期刊模板：复用 `office/journal/` 与 `office_journal_*`，内置常见中文期刊/学位论文模板。
- [ ] LaTeX 输出：复用 `office/latex/`，产出 `main.tex` + `references.bib` + `figures/`，打通编译与合规检查。
- [ ] 图表生成与编号引用；三线表/规范表样式。
- [ ] 写作风格校准（用户旧作样本 → 风格画像）。
- [ ] 统一 `office_documents` 与 `artifacts` 两套账的展示。

### M4：中文源、系统综述与评测（1–2 周）

- [ ] 中文源深度：CNKI/万方/维普的期刊、学位论文、会议、报纸类型；GB/T 7714 参考文献。
- [ ] PRISMA 模式（纳入/排除计数与流程图）。
- [ ] 补研究/写作专家 persona 已声明但缺失的 SKILL.md：`literature-review` / `fact-check` / `summarize-papers` / `polish-prose` / `structure-outline`。
- [ ] xueshu789 profile 回归：站点改版检测、snapshot fixture 更新、一次完整"检索→证据→综述草稿"验收。
- [ ] 站点点适配验收标准：新增任意站点只提交 profile（+ 可选说明），不改 pipeline 代码即可跑通检索与下载。
- [ ] 内部评测集：20 个查询的检索召回、引用准确率、claim 支持率、人工复核工作量。

## 7. 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| 知网/万方登录态与验证码 | 中文检索中断 | 复用受控浏览器接管与站点登录模板；失败暂停而非绕过；遵守站点条款 |
| 全文版权 | 不可分发 | 只存用户有权获取的全文与元数据；不内置共享库 |
| 引用幻觉 | 学术诚信 | 引用只来自文献池；存在性 + claim support 双层核验；人工复核预算 |
| 核验器自身不可靠 | 误报/漏报 | 四态标记而非二元判定；报告核验器与阈值；预留校准集 |
| Workflow v1.1 未落地 | 排期风险 | 先做 Playbook 扩展的最小闭环，再逐步替换为 Workflow 执行器 |
| 长流程成本与时长 | 用户等待、token 消耗 | 分层模型（筛选/抽取用小模型）；缓存；可恢复；后台任务 |
| 上下文膨胀 | 质量下降 | PaperDB 检索 + 证据表，而不是把全文塞进 prompt |
| Windows 7 / Python 3.8 分支 | 兼容性 | 复用现有依赖；新增库先评估 py38/pydantic v1 兼容；必要时降级 |
| 第三方站点/镜像（如 xueshu789） | 合规与稳定性 | 以 profile 形式提供、默认禁用、用户显式启用；仅使用本人账号/机构授权；不绕过付费墙；站点改版用 snapshot fixture 快速定位 |
| 产品定位误读 | 用户以为"可投稿" | UI 与文档明确"草稿/副驾驶"，最终判断由作者负责 |

## 8. 参考来源

- [lit-review-agent-tools](https://github.com/brycewang-stanford/lit-review-agent-tools)
- [Awesome-Auto-Research-Tools](https://github.com/handsome-rich/Awesome-Auto-Research-Tools)
- [STORM](https://github.com/stanford-oval/storm)；[论文 arXiv:2402.14207](https://arxiv.org/abs/2402.14207)
- [PaperQA2](https://github.com/Future-House/paper-qa)
- [OpenScholar 论文 arXiv:2411.14199](https://arxiv.org/abs/2411.14199)；[ScholarQABench](https://github.com/AkariAsai/ScholarQABench)
- [Ai2 Scholar QA 论文 arXiv:2504.10861](https://arxiv.org/abs/2504.10861)
- [OpenDraft](https://github.com/federicodeponte/opendraft)
- [PaperOrchestra](https://github.com/google-research/paper-orchestra)
- [SEER](https://github.com/CherYou/SEER)
- [open-academic-paper-gen](https://github.com/mmlong818/open-academic-paper-gen)
- [ARISE 论文 arXiv:2511.17689](https://arxiv.org/abs/2511.17689)
- [academic-research-skills](https://github.com/Imbad0202/academic-research-skills)
- [claude-scholar](https://github.com/Galaxy-Dawn/claude-scholar)
- [AI for Auto-Research 路线图 arXiv:2605.18661](https://arxiv.org/abs/2605.18661)
- [引用忠实度审计 arXiv:2607.20527](https://arxiv.org/html/2607.20527)
- [cnki-mcp-server](https://pypi.org/project/cnki-mcp-server/)；[cookjohn/cnki-skills](https://github.com/cookjohn/cnki-skills)
- [zotero-mcp](https://github.com/54yyyu/zotero-mcp)；[paper-search-mcp](https://github.com/openags/paper-search-mcp)

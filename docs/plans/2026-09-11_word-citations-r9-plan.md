# Word 引用体系 Round 9 实施计划（GB/T 7714 文献 + 文中标记 + 参考文献表 + BibTeX）

> 日期: 2026-09-11 · 分支: `feat/word-citations-gbt7714` · 基于 main @ c2102372
> 系列: Word 写作能力增强 P2（Round 7 版式 #622 / Round 8 内容元素 #635 的第三轮）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（GB/T 7714 formatter 与 BibTeX 解析均为确定性手写实现，
> 不引 citeproc-py/bibtexparser，避免双通道依赖矩阵变化与 py38 wheel 风险）。
> 冲突规避: **不触碰 `backend/office/journal/`**（#584 并行工作流刚收口且
> win7 侧已出 changelog，属他人活跃区域）；引用引擎先落 generate_docx 通路，
> journal 的 fill_from_content 集成留给 Round 10 协调。

## 背景（Round 8 合并后再分析）

1. Round 7/8 后 `generate_docx` 已具备版式与内容元素（题注/三线表/标题
   编号），但**引用仍是纯手工**：期刊论文的文中 `[1]` 标记与文末参考文献表
   靠 LLM 手写，编号重排与格式一致性无保证。
2. 并行工作流交付的 `backend/office/journal/`（#584）覆盖了"模板解析→
   填充→C 级格式校验"，但其 `JournalContent.references` 只是 `List[str]`
   ——没有结构化文献条目、没有确定性 GB/T 7714-2015 格式化、没有文中
   标记自动编号。引用引擎是两条通路（generate_docx / journal）共同的缺口。
3. Zotero/BibTeX 是用户文献的既有载体（Zotero 可导出 .bib），导入解析是
   引用体系的第一公里（`docs/superpowers/ideas/2026-07-10-zotero-integration.md`
   停留 Backlog，本轮先落 BibTeX 文件导入，不做 Zotero SQLite 直连）。

## 批次任务

### A. `backend/office/references.py`（新，纯逻辑零 docx 依赖）

- `ReferenceSpec`（pydantic，extra="forbid"）：
  `key`(必填，≤100)/`ref_type`(journal|book|thesis|conference|report|
  webpage|patent|standard|newspaper)/`title`(必填)/`authors`(≤50) /
  `year`/`source`(刊名|出版社)/`volume`/`issue`/`pages`/`publisher`/
  `address`/`url`/`doi`/`access_date`/`language`(zh|en，影响"等/et al")
- `format_gbt7714(ref) -> str`：GB/T 7714-2015 顺序编码制条目。
  类型码 [J]/[M]/[D]/[C]/[R]/[EB/OL]/[P]/[S]/[N]；作者 ≤3 全列、>3 取
  前三加"等"（en 加"et al"）；电子资源带 [引用日期] + URL/DOI。
  确定性输出、可单测（对照手工核验样例）。
- `format_apa(ref) -> str`：APA 第 7 版简表（author-year 复杂场景从简，
  文档标注简化范围）。

### B. 生成器集成（models.py + word.py + word_layout.py）

- `OfficeWordGenerateRequest.references: List[ReferenceSpec]`（≤200）+
  `citation_style: Literal["gbt7714", "apa"] = "gbt7714"`
- `WordParagraphSpec.citations: List[str]`（引用 key，≤10；与 heading
  互斥校验放生成期）→ 段落尾部上标标记，连续编号合并为 `[1-3]`，
  首次出现顺序即编号
- `WordFormatSpec.bibliography: BibliographySpec`（新模型：`heading_text`
  默认"参考文献"/`font_size_pt` 默认 10.5 五号/`hanging_indent_cm` 默认
  0.74 悬挂缩进）
- 未解析 key / 未被引用的条目 → `OfficeGenerateError` 确定性报错
  （key 列表进错误消息）；文末自动追加参考文献节（heading + 悬挂缩进
  条目段，"[N] 条目文本"）

### C. BibTeX 导入（`backend/office/bibtex.py` + REST + 工具）

- `parse_bibtex(text) -> List[ReferenceSpec]`：@article/@book/@inproceedings
  /@phdthesis/@mastersthesis/@techreport/@misc/@online；花括号剥离、
  `~/--` 规范化、作者 ` and ` 切分；key 取 entry key；未知 @type →
  misc；解析不出任何条目 → `OfficeParseError`
- REST：`POST /office/word/parse-bibtex`（body: `{text}`，response:
  `{references: [...]}`）
- 工具：`office_parse_bibtex`（READ risk，参数 `{text}`；LLM 拿到用户的
  .bib 内容后转结构化条目再进 office_create 的 references）

### D. 测试（`backend/tests/unit/office/test_references.py` +
`backend/tests/integration/test_office_word_citations.py`）

- formatter：GB/T 7714 各类型码样例（中文/英文、>3 作者截断、电子资源
  URL/DOI）、APA 基样例
- 生成：文中上标标记与合并区间、首现编号、参考文献节内容/悬挂缩进/
  样式、未解析 key 报错、未被引用报错、citation_style=apa
- BibTeX：各 entry 类型、花括号清理、作者切分、空输入报错
- 工具注册 + REST 路由 roundtrip
- 兼容性：不带 references/citations 的旧 payload 零变化

## Round 10 候选（Word 增强 P3）

- docx 格式 Linter（对照 FormatSpec/journal spec 校验产物 + 修复建议）
- journal fill_from_content 接入引用引擎（结构化 references 格式化后
  填充，替换 List[str] 手写）
- `paper-writing` / `report-writing` SKILL.md 技能（when_to_use 自动激活）
- Pillow 图片管线（压缩/转格式，main 通道可选懒加载）

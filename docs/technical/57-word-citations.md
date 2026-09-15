# 57 — Word 引用体系（Round 9：GB/T 7714 + 文中标记 + 参考文献表 + BibTeX）

> 日期: 2026-09-11 · 分支: `feat/word-citations-gbt7714` · 方案:
> `docs/plans/2026-09-11_word-citations-r9-plan.md`
> 系列: Word 写作能力增强 P2（Round 7 版式 #622 / Round 8 内容元素 #635）

## 1. 问题与定位

期刊论文/项目文档写作的硬缺口：文中 `[1]` 标记与文末参考文献表此前全靠
LLM 手写，编号重排与格式一致性无保证。并行工作流的 journal 子系统（#584）
已覆盖"模板解析→填充→C 级校验"，但 `JournalContent.references` 只是
`List[str]`——没有结构化条目与确定性格式化。本轮给 generate_docx 通路
补齐**结构化引用引擎**（journal 集成留 Round 10 协调，规避他人活跃区域）。

## 2. 方案

```
.bib 文本 ──parse_bibtex(bibtex.py, 手写解析)──▶ ReferenceSpec(models.py)
                                                    │
OfficeWordGenerateRequest.references ───────────────┤
paragraphs[].citations (key 回链) ──首现编号──▶ 文中上标 "[1-3]"（连续合并）
citation_style: gbt7714 | apa ──references.py──▶ 文末参考文献节（悬挂缩进）
```

- **`references.py`**（零 docx 依赖、零第三方依赖）：GB/T 7714-2015 顺序
  编码制 9 类类型码（[J]/[M]/[D]/[C]/[R]/[EB/OL]/[P]/[S]/[N]），>3 作者
  截断"等/et al"（language 缺省按 title CJK 自动判定）；APA 第 7 版简化
  子集。`compact_citation_marker` 合并连续编号（[1,2,3]→[1-3]）。
- **一致性确定性校验**：citations 引用未定义 key / 存在未被引用的条目 →
  `OfficeGenerateError`（key 列表进消息）。完全不带 citations 时全部
  条目入表（"只要文献表"需求），按请求顺序编号。
- **`bibtex.py`**：手写解析（不引 bibtexparser——双通道依赖矩阵 + py38
  wheel 风险），覆盖 8 类常用 entry；花括号剥除、`~`→空格、`--`→`-`；
  坏条目跳过不阻断，全部失败 → `OfficeParseError`→422。
- **接入面**：REST `POST /office/word/parse-bibtex`；LLM 工具
  `office_parse_bibtex`（READ、`requires_tool_context=False`——纯文本
  解析不触工作区）；writer profile 工具面 + 指南 + system prompt 同步。
- **`format_spec.bibliography`**：文献节标题文本/字号（默认五号 10.5pt）/
  悬挂缩进（默认 0.74cm）可配；文献节 heading 不参与多级标题编号。

## 3. Win7 对齐

新功能不 cherry-pick（31-win7-lts.md §2）；零新增依赖；代码沿用
typing.Optional 注解风格。

## 4. 测试

`tests/unit/office/test_references.py`（22 项）：GB/T 各类型码/截断/
语言自动判定/最小字段良构、APA、编号合并、BibTeX 类型映射/字段清理/
坏条目跳过/空输入。
`tests/integration/test_office_word_citations.py`（14 项）：上标与首现
编号、文献节排序/样式/悬挂缩进、编号互斥、一致性报错、APA 渲染、REST
roundtrip、工具 roundtrip、受管路径透传、旧 payload 兼容。

## 5. 后续（Round 10 候选）

docx 格式 Linter（对照 FormatSpec 校验产物）；journal fill_from_content
接入引用引擎；`paper-writing` / `report-writing` 技能；Pillow 图片管线。

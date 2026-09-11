# Word 版式引擎 Round 7 实施计划（FormatSpec —— "版式即配置"，Word 写作增强 P0）

> 日期: 2026-09-11 · 分支: `feat/word-format-spec-engine` · 基于 main @ 8bd0da4d
> 来源: Word 写作能力增强分析（项目文档/期刊论文/内部资料写作场景）—— P0 地基期。
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 但 office 栈在 win7 有捆绑（requirements-py38/bundled 含 python-docx），因此：
> ① 新代码沿用 `typing.Optional/List` 注解风格（ruff UP006/007/035 已禁用，
> 与 py38 分支共享注解习惯，降低未来 backport 成本）；② **零新增依赖**
> （纯 python-docx + oxml），不给双通道依赖矩阵增加变量。
> 冲突规避: 避开 feat-p11-embedding-distribution（memory/embedder 区域）与
> gateway（Round 6 刚落地）。

## 背景

`generate_docx`（backend/office/word.py:564）目前从**空白文档**堆叠标题/段落/
裸表格，格式仅两项全局字体（`set_doc_default_font`）。期刊论文、项目文档、
公文类写作都有硬性格式要求（页边距/行距/页眉页脚/页码/标题样式），这些目前
只能靠 LLM 在 prompt 里"口头约定"，生成后无法保证。模板填充（docxtpl）是唯一
版式保证，但要求"先有模板文件"。

本轮引入 **FormatSpec 版式引擎**：把格式要求结构化为可选的 `format_spec`
参数，`None` 时行为零变化（向后兼容），传入时由确定性代码注入 styles.xml /
document.xml——"版式即配置"，为后续（Round 8 题注/三线表、Round 9 引用、
Round 10 格式 Linter）打底。

## 批次任务

### A. `backend/office/word_layout.py`（新）

pydantic 模型（全部字段 Optional，None = 该项不设置）：

- `WordPageSetupSpec`: `size`('A4'|'letter') / `orientation`
  ('portrait'|'landscape') / `margins_cm`(top/bottom/left/right, 0~10)
- `WordBodyStyleSpec`: `font_size_pt`(1~72) / `line_spacing`(倍数 1.0~3.0) /
  `first_line_indent_cm`(0~5) / `space_after_pt`(0~48) / `align`
- `WordHeadingStyleSpec`: `font_size_pt` / `bold` / `color`(RGB hex) /
  `align` / `space_before_pt` / `space_after_pt`
- `WordHeaderFooterSpec`: `text`(≤200) / `align` / `page_number`(bool，
  仅 footer：居中 `PAGE` 域)
- `WordFormatSpec`: `page` / `body` / `headings`(h1/h2/h3) / `title` /
  `header` / `footer`，`extra="forbid"`

应用函数（纯 python-docx + OxmlElement，风格沿袭 word.py 的样式补丁套路）：

- `apply_format_spec(doc, spec)`：按序执行 page setup（`doc.sections[0]`）→
  Normal 样式补丁（字号/行距/首行缩进/段后距/对齐）→ Title / Heading 1-3
  样式补丁（含 `_patch_linked_character_styles` 字体链已由既有函数覆盖，
  本轮只动字号/加粗/颜色/间距/对齐）→ 页眉文本 → 页脚页码域
  （`w:fldSimple w:instr="PAGE"`，Word/WPS/LibreOffice 均渲染）。
- 缺失样式名 `KeyError` 静默跳过（与 `_STYLES_TO_PATCH` 容错一致）。

### B. 请求模型 + 生成器接入

- `models.py`: `OfficeWordGenerateRequest.format_spec:
  Optional[WordFormatSpec] = None`（模型定义放 models.py，保持
  `scripts/verify-office-paths.py` canary 的 "models 仅依赖 pydantic" 前提）。
- `word.py generate_docx`: `set_doc_default_font` 之后、写标题之前，若
  `req.format_spec` 非 None 则惰性 import `apply_format_spec` 并应用。

### C. Agent 工具 schema（`office_create_tool.py`）

- word 分支 `content.properties` 增加 `format_spec`（嵌套结构 JSON Schema +
  中文描述：页边距厘米/字号磅/行距倍数等，LLM 可从用户的格式要求直接映射）。
- 直通路径零改动：`content` dict → `OfficeWordGenerateRequest(**payload)`
  自动携带；`OfficeToolService.create` 委托路径同样透传。

### D. 测试（`backend/tests/integration/test_office_word_format_spec.py`）

- 向后兼容：不传 `format_spec` → 生成的 docx 节边距/样式与旧行为一致
- page setup：页边距 / 横向 / letter 断言（EMU 换算）
- body 样式：Normal 字号/行距/首行缩进/段后距回读断言
- heading 样式：h1-h3 字号/加粗/颜色回读断言
- 页眉文本回读；页脚含 PAGE 域（`w:fldSimple` instrText 断言）
- 校验：extra field 拒绝 / 负边距拒绝 / font_size 越界拒绝
- 工具链路：`OfficeCreateTool.execute`（word, tmp output_dir）带
  `format_spec` 端到端生成成功且样式生效

## Round 8 候选（Word 增强 P1）

- 图片管线：行内插图（插到指定段落位置而非文末）+ 题注自动编号（"图1"）
- 表格增强：三线表 / 合并单元格 / 表头跨页重复 / 表题注
- 多级标题自动编号（1 / 1.1 / 1.1.1 文本前缀方案或 numbering part）

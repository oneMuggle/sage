# Word 横排分节 Round 26 实施计划（部分页横排——宽表格/财务报表刚需）

> 日期: 2026-09-14 · 分支: `feat/word-section-breaks` · 基于 main @ cd3cbbf1
> 系列: Word/Office 写作能力增强第 17 轮
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 零新增依赖（python-docx add_section 原生能力）。

## 背景（Round 25 合并后再分析）

财务报表/宽表格页需要**横向纸张**，而整份文档其余部分仍是纵向——
这必须用 Word 分节（section）实现。R7 的 format_spec.page 只作用于
`sections[0]`（全文档），无法表达"第 N 段起横排"。

## 批次任务

### A. 模型（models.py）

- `WordSectionBreakSpec`: `start_paragraph`（ge=0，该 0-based 段落下标
  起进入新节）+ `page_setup: WordPageSetupSpec`（复用既有模型：
  orientation/size/margins_cm）
- `WordFormatSpec.section_breaks: List[WordSectionBreakSpec]`（≤20）

### B. 布局（word_layout.py）

- `_apply_page_setup` 参数化：接受 section（原 doc.sections[0] 调用点
  不变），核心逻辑（尺寸/方向/边距）抽出复用
- 新增 `apply_section_break(doc, page_setup) -> None`：
  `doc.add_section(WD_SECTION.NEW_PAGE)` + 对新节应用 page setup

### C. 生成器（word.py）

body 循环内维护 pending breaks（按 start_paragraph 升序）：写段落前
命中即 `apply_section_break`。多个 break 同点依序生效。

### D. 契约（工具 schema + types.ts）

`format_spec.section_breaks` 数组（start_paragraph + page_setup）。

### E. 测试（追加 `test_office_word_h4h5.py` 同族或新建
`test_office_word_sections.py`）

- 两节文档：sections[1].orientation == LANDSCAPE、宽>高、边距生效
- 第一节内容不受影响；分节处有分页语义
- start_paragraph 越界（>= 段落数）→ 分节在文末生效或跳过（锁定语义）
- 无 section_breaks 零变化；format_spec 校验（start_paragraph 负数拒绝）

## Round 27 候选

- TOC 域更新收尾（headless/COM）
- Pillow 进 main requirements（依赖评审）
- Excel 打印设置扩展（页眉行重复已有冻结；页边距按打印）

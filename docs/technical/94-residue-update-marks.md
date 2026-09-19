# 94 — residue 补全 + append_paragraphs 交叉引用（Round 60）

> 日期: 2026-09-19 · 分支: `fix/residue-and-update-marks`
> 系列: Word/Office 写作能力增强第 61 轮

## 1. 定位

两处收口缺口：① `cross_ref/residue` 正则只覆盖 fig/tbl——R57/R59 引入
的 fn/en 残渍不告警；② append_paragraphs 不解析交叉引用占位符。

## 2. 变更

- `word_lint._CROSS_REF_RESIDUE_RE` 扩为 `(fig|tbl|fn|en)`；
- `edit.py`：`_collect_caption_bookmarks`（域外扫描 SEQ 题注段构建
  文本→(书签, 显示) 映射，重复题注取首个）+ `_parse_cross_ref_text`
  （未知题注抛 KeyError）；append_paragraphs 预校验全部 spec 可解析后
  分段写入（text run + `append_ref_field` REF 域）——all-or-nothing；
- {{fn:}}/{{en:}} 追加需 part 追加语义（已存在 part 的编号续接），
  本轮不支持——写入被 residue lint 提示。

## 3. Win7 对齐与测试

不涉回流；零新增依赖。`test_residue_update_marks.py` 3 项：fn/en
残渍检出、REF 域解析（instr 精确匹配 + 回读"图1/表1"）、未知题注
all-or-nothing 零写入。

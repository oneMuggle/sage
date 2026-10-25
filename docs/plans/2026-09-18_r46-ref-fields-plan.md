# 交叉引用升级：REF 域 + 题注书签 Round 46 实施计划

> 日期: 2026-09-18 · 分支: `feat/word-ref-fields` · 基于 main @ 7367ca94
> 系列: Word/Office 写作能力增强第 47 轮（R45 占位符的原生化升级）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

R45 的占位符替换产物是纯文本"图N"——插图增删重排后正文引用不会跟随
（生成期一次性快照）。本轮把替换产物升级为 Word 原生交叉引用：
题注编号套书签，正文占位符生成 `REF 书签 \h` 复杂域（缓存"图N"）——
F9/COM 更新域后引用自动跟随题注重排；R39 的 COM 刷新通道
（Fields.Update）已覆盖 REF 域，零新增编排。

## 批次任务

### A. 题注书签（`word_layout.add_caption`）

- bookmarkStart/End 包住"图N"整体（label run + SEQ 域 + 编号 run），
  书签名 `_RefFig{n}` / `_RefTbl{n}`（编号确定生成；w:id 分别从
  100000/200000 起避免与用户书签冲突）。

### B. 占位符 → REF 域（`word.py`）

- `_resolve_cross_refs` 拆段化：返回 `[("text", s) | ("ref", bookmark,
  cached)]` 段列表（未命中 fail-fast 不变）；
- 正文循环：仅当段落含占位符时走分段写run路径（`doc.add_paragraph()` /
  `doc.add_heading("")` + 逐段 add_run / REF 域），无占位符段落保持
  既有单次 add_paragraph 路径（产物逐字节不变，零回归面）；标题
  numbering 前缀作为首个 text 段；
- `word_layout._append_ref_field(paragraph, bookmark, cached)`：
  begin + instrText ` REF _RefFig1 \h ` + separate + 缓存"图N" + end。

### C. 契约与文档

- schema content 描述、SKILL.md：占位符说明升级为"生成 Word 交叉
  引用域，更新域自动同步"；
- 技术文档 83 号、README 索引、CHANGELOG。

## 验证

- 新测试：REF 域结构（instr + 缓存 + 书签在题注段）、文本段保序、
  无占位符段落零变化、fail-fast 不变；R45 用例应全数继续通过
  （paragraph.text 含缓存 run 文本）。word 家族回归 + ruff。

## Round 47 候选

- Word COM 前端徽章细分（需前端协调）
- 期刊双栏模板/参考文献样式扩展（需与 journal 维护方协调）

# 83 — 交叉引用升级：REF 域 + 题注书签（Round 46）

> 日期: 2026-09-18 · 分支: `feat/word-ref-fields`
> 系列: Word/Office 写作能力增强第 47 轮（R45 占位符的原生化升级）

## 1. 定位

R45 的占位符替换产物是纯文本"图N"——插图增删重排后正文引用不会跟随
（生成期一次性快照）。本轮把产物升级为 Word 原生交叉引用：题注编号套
书签，正文占位符生成 `REF 书签 \h` 复杂域（缓存"图N"）——F9/COM 更新
域后引用自动跟随题注重排；R39 的 COM 刷新通道（Fields.Update）已覆盖
REF 域，零新增编排。

## 2. 变更

- `word_layout.add_caption`：bookmarkStart/End 包住"图N"整体（label +
  SEQ + 编号），书签名 `_RefFig{n}` / `_RefTbl{n}`（编号确定生成），
  w:id 分段（图 100000+、表 200000+）避免与用户书签冲突。
- `word_layout.append_ref_field`：REF 复杂域四件套（begin + instrText
  ` REF _RefFig1 \h ` + separate + 缓存"图N" + end）。
- `word.py`：`_resolve_cross_refs` → `_split_cross_ref_segments`
  （拆段为 `[("text",…)|("ref",书签,缓存)]`，未命中 fail-fast 不变）+
  `_write_cross_ref_segment`；正文循环**双路径**——有占位符走分段写
  run 路径（标题 numbering 前缀为首段），无占位符保持既有单次写入
  （产物零变化，零回归面）。
- 契约：schema content 描述、SKILL.md 升级为"Word 交叉引用域，更新域
  自动同步"语义；types.ts 零变更。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖。
`test_word_cross_refs.py` +2：REF 域结构（instr 精确匹配 + 题注段书签
在位 + 段落回读文本含缓存"图1"）、无占位符段落单 run 零变化；R45 的
4 项全部继续通过（回读文本兼容）。word 家族回归 + ruff 全绿。

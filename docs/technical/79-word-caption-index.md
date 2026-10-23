# 79 — 图目录/表目录（TOF 域 + SEQ 题注升级，Round 42）

> 日期: 2026-09-18 · 分支: `feat/word-caption-index`
> 系列: Word/Office 写作能力增强第 43 轮（R39-R41 TOC 真页码故事线的姊妹篇）

## 1. 定位

期刊论文/正式报告常要求"插图清单/表格清单"。R7 的题注是字面文本
"图N　标题"，而 Word 的收录机制（`TOC \c "图"`）只认含 **SEQ 域**的
题注段——字面文本无法被收录。本轮：题注编号升级为 SEQ 复杂域
（视觉/回读完全兼容），再支持 `figure_index` / `table_index` 插入
图/表目录域；R39 的 COM 刷新通道顺带把目录刷出真页码。

## 2. 变更

- `word_layout.add_caption`：编号改为 SEQ 复杂域（begin + instrText
  ` SEQ 图 \* ARABIC ` + separate + 缓存编号 + end）。fldChar 藏在
  run 内、缓存编号是普通 run → python-docx 回读文本与既有字面形态
  一致（"图1　标题"），lint 零改动通过；Word 语义上含 SEQ 的段落即
  题注条目，F9/COM 重执行按文档顺序重编号（与"无题注不占号"一致）。
- `WordIndexSpec`（heading_text/placeholder_text，extra=forbid）+
  `WordFormatSpec.figure_index / table_index`。
- `word_layout.insert_tof_field`：标题段（加粗居中 16pt，非 Heading）
  + fldChar 复杂域 ` TOC \h \z \c "图" ` + 缓存条目行（"图N　标题"
  无页码，与 R29 目录缓存同思路）+ 占位提示（空条目）+ 分页——
  图/表目录各自独占页。
- `word.py`：`_partition_images`/`images_by_position` 分桶计算前置到
  目录段之前；条目按正文编号顺序预收集（跨段落位置 + 文末钳制两段
  循环复刻正文 figure_no 守卫；表按 req.tables 顺序），保证缓存条目
  编号与正文题注严格一致。
- `toc_refresh`（COM）：TOC 逐个 Update 后追加 `doc.Fields.Update()`
  ——SEQ 重编号 + TOF 收录条目与页码一次完成；落盘条件放宽为
  "toc_count>0 或 field_count>0"（纯 TOF 文档也落盘）。
- `word_lint`：新增 `_iter_paragraphs_outside_fields`——TOC/TOF 缓存行
  （"图N　标题"）会被 caption/sequence 规则误判为题注重复，fldChar
  begin/end 之间的纯缓存段不参与规则。
- 契约：office_create schema format_spec 增 figure_index/table_index；
  types.ts 增 `WordIndexSpec` 与两字段；SKILL.md 插图清单/表格清单
  可发现化。

## 3. Win7 对齐与测试

新功能不 cherry-pick 到 release/win7（31-win7-lts.md §2）；零新增依赖。
`test_word_caption_index.py` 6 项：SEQ 结构（fldChar 三件套 + instr +
回读文本）、TOF 条目/占位、端到端生成（域指令 + 缓存条目 + 无题注
不占号）、lint 跳过缓存行；`test_toc_refresh.py` stub 增 Fields 断言
（no-op 语义同步为"无目录且无其他域"）。word 家族回归 + ruff 全绿。

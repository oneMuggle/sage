# repair 补 index 域插入 + SEQ 题注重排兼容 Round 48 实施计划

> 日期: 2026-09-18 · 分支: `feat/repair-index-fields` · 基于 main @ 06a98870
> 系列: Word/Office 写作能力增强第 49 轮（lint→repair 对 R42/R44 能力的闭环）
> Win7 对齐: **新功能，不 cherry-pick 到 release/win7**（31-win7-lts.md §2）。
> 依赖: 零新增。

## 背景

R44 给 lint 加了 figure_index/table_index 域在位规则，但 repair（R12 的
lint→修复→复检闭环）不会修它们——spec 声明了 index 而文档缺失时 lint
永远红。另发现一个 R42 交互缺陷：`_renumber_captions` 用 `para.text`
整体重写题注段，会把 R42 引入的 SEQ 域与书签**一并抹掉**（题注重排
触发即毁交叉引用/图表目录收录）。

## 批次任务

### A. repair：index/presence 修复（主项）

- 从文档自身扫描 SEQ 题注（域外"图N　标题"段）构建条目；
- 缺 figure_index/table_index 域时在目录域之后（无目录则文档首段前）
  插入 TOF 域（复用 `insert_tof_field` 的段落构造，经
  `insert_paragraph_before` 前插）；
- `repaired_rules` 记入 `figure_index/presence` / `table_index/presence`。

### B. SEQ 题注重排兼容（缺陷修复）

- `_renumber_captions`：携带 SEQ 域的题注段不再整体重写 `para.text`
  ——定位 separate 与 end 之间的纯数字缓存 run，仅改其文本；
  SEQ/bookmark 结构原样保留。

### C. lint：重复题注提示

- 同类题注文本（去编号后）重复 → `caption/duplicate` warning
  （交叉引用按题注文本匹配时指向首个，提示用户区分）。

### D. 测试与账目

- repair 三态：缺 index 修复插入 / SEQ 重排保结构 / 复检通过；
  lint 重复题注 warning；技术文档 84 号、CHANGELOG。

## 验证

- word_repair/lint/caption 家族回归 + ruff。

## Round 49 候选

- Word COM 前端徽章细分（需前端协调）
- REF 域书签幂等修复（repair 对损坏书签的重建）

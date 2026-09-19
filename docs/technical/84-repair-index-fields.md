# 84 — repair 补 index 域插入 + SEQ 题注重排兼容（Round 48）

> 日期: 2026-09-18 · 分支: `feat/repair-index-fields`
> 系列: Word/Office 写作能力增强第 49 轮（lint→repair 对 R42/R44 能力的闭环）

## 1. 定位

R44 给 lint 加了 figure_index/table_index 域在位规则，但 repair 不会修
它们——spec 声明了 index 而文档缺失时 lint 永远红。另发现 R42 交互
缺陷：`_renumber_captions` 用 `para.text` 整体重写题注段，会把 SEQ 域
与书签一并抹掉（题注重排触发即毁交叉引用/图表目录收录）。

## 2. 变更

- **repair index 插入**：从文档自身 SEQ 题注（域外扫描，与 lint 同款
  跳过）构建条目，缺域时在文档前部插入 TOF 域（复用 fldChar 构造，
  `insert_paragraph_before` 前插）；`repaired_rules` 记入
  `figure_index/presence` / `table_index/presence`。
- **SEQ 兼容重排**（缺陷修复）：`_renumber_captions` 对携带 SEQ 的
  题注段不再整体重写——定位 separate 与 end 之间的纯数字缓存 run，
  仅改其文本；SEQ/书签结构原样保留（交叉引用/图表目录不再被重排
  摧毁）。
- **lint `caption/duplicate`**（warning）：同类题注文本重复提示——
  交叉引用按题注文本匹配指向首个，提示用户区分；不阻断交付。

## 3. Win7 对齐与测试

纯校验/修复层变更；不涉回流。`test_word_repair_index.py` 3 项：缺失
index 修复插入（含条目复建）、SEQ 重排保结构（人为破坏编号 → 修复 →
域/书签在位且编号正确）、重复题注 warning；lint 家族回归全绿。

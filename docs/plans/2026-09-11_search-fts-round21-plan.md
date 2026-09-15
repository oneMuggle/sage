# 消息全文索引内部修复 Round 21 实施计划

> 日期: 2026-09-12 · 分支: `feat/search-messages-fts` · 基于 main @ c17cd8d5
> Win7 对齐: 内部修复（非用户可见新功能），不 cherry-pick 到 release/win7。

## 范围说明（原计划调整）

原计划将 REST `/search/messages` 升级为复用 FTS 索引。实施中发现既有
契约测试编码了 LIKE 子串语义（通配符字面匹配、has_more 探测），
与 FTS 分词语义存在行为分歧。**诚实取舍：端点保持 LIKE 原语义**
（契约测试即规格），本批只交付 message_search 内部的三处正确性修复；
FTS 端点升级留待专门设计（需重定义检索语义契约）。

## 交付内容（`backend/data/message_search.py`）

1. **FTS 路径角色过滤**：`role IN ('user', 'assistant')` —— tool/system
   行无检索价值（与 REST 端点原语义一致）
2. **LIKE 路径通配符转义**：`!` → `!!`、`%` → `!%`、`_` → `!_%`（ESCAPE '!'）
   —— 含 `%`/`_` 的查询不再被当作通配符
3. 测试回归：既有 14 例全绿

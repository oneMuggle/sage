# R165：ConventionManager 惯例管理单测补齐（2026-09-26）

- **上游文档**：parity-loop-sop；交互模式惯例提取（core/conventions）
- **范围**：后端 only，一个测试文件新增，零生产代码改动

## 0. 结论速览

`core/conventions.py`（313 行，ConventionManager——惯例 CRUD、上下文
注入、置信度衰减/升降级、统计）此前零测试。DB 用 `Database(":memory:")`
真实内存库（沿用 test_worktree_routes 模式），llm_client 传 None 走
mock 回退路径。

## 覆盖矩阵（约 16 例）

1. add/get 往返（is_active bool 还原）；2. update 白名单字段（非
白名单键被忽略、无有效键返回 False）；3. delete 命中/未命中；
4. get_active 全量与 category 过滤、confidence 降序；5.
get_context_prompt：空 → ""、非空 → "[CATEGORY] name: description"
行格式；6. decay：超期未更新 ×0.9 衰减、低于 MIN_CONFIDENCE 停用、
未超期不动；7. promote +0.15 封顶 1.0、demote −0.20 下限 0.0、
不存在 id → False；8. get_stats total/active/by_category；
9. Convention.to_dict 九键；10. learn_from_conversation 无 llm_client
→ []。

## 验证

- pytest 新文件；ruff 0.4.4 从仓库根跑（对齐 CI 口径）。

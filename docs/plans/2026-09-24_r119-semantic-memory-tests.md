# R119：SemanticMemory（语义记忆 SQLite+FTS5）单测补齐（2026-09-24）

- **上游文档**：parity-loop-sop；R21-B 导入去重 / P3 时间有效区既有成果
- **范围**：后端 only（backend/tests/unit/memory/test_semantic_memory.py
  新增，零生产代码改动）

## 0. 结论速览

`backend/memory/semantic.py`（653 行）是语义记忆的核心存储层：主表
`memories_semantic` + 独立 FTS5 表（jieba 分词、Python 侧显式同步、
LIKE+jieba 兜底）。此前仅 tokenizer 与 scoring 有测试，存储/检索层零
覆盖。本轮补 CRUD + 双搜索路径 + P3 失效语义的完整单测。

## 覆盖矩阵（约 22 例）

1. **save**：返回 UUID；get_by_id 可取回；默认摘要 = truncate_summary
   (content, 150)、显式 summary/tags 保留、tags JSON 往返为列表；
2. **摘要截断**：>150 字符 → 前 150 + "..."；
3. **search FTS 主路径**：中文（"用户喜欢火锅" 搜 "火锅"）与英文命中；
   非命中词 → FTS 空 → LIKE 兜底也空 → []；
4. **search 空查询** → get_recent 兜底（返回最近记忆）；
5. **session 隔离**：跨 session 检索互不可见（save 与 search 两个轴向）；
6. **tags 过滤**：search(tags=[...]) 只返回带标签行；
7. **get_recent**：created_at DESC 排序 + limit；session 过滤；
8. **get_by_id / exists_by_content**：存在/不存在两路径；
9. **delete**：返回 True/False；主表与 FTS 同步删除（删除后检索不再
   命中——FTS 空回退 LIKE 也空）；count 减少；
10. **invalidate（P3）**：检索不再命中（invalid_at 过滤）、count 排除、
    get_by_id 仍可见（审计语义）；重复 invalidate → False；
11. **count**：总数与会话过滤；invalidated 不计；
12. **update_tags**：tags 更新 + FTS 行同步（按新标签检索命中）；
    不存在 id → False；
13. **scope 轴**：save(scope='user') 后跨会话按 scope 检索可见；
    search(scope='project') 无 project_key → []（非法组合短路）。

## 测试工程约束

- `Database(":memory:")` + `init_db()`（沿用 test_worktree_routes 模式），
  不落盘、无跨用例污染；
- FTS5 在 CI/Linux 与本地 Windows 均可用（SQLite 内建）；
- 不直接断言 jieba 切分细节，只断言检索命中（跨版本稳定）。

## 验证

- pytest 新文件 + memory 邻近用例；ruff（CI 同版本 0.4.4）。

## 明确不做

- 不测 memories_vec 向量路径（依赖 embedding 服务，属集成域）；
- 不测 evolution 晋升回填（跨模块集成，FTS 回填已有幂等保证）。

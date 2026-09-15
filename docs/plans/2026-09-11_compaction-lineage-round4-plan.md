# 压缩谱系（Session Lineage）Round 4 实施计划（对标 hermes-agent）

> 日期: 2026-09-11 · 分支: `feat/compaction-lineage` · 基于 main @ 48567636
> 来源: hermes-agent 对标分析（session lineage / 可追溯压缩）
> Win7 对齐: 全部为**新功能**，不 cherry-pick 到 release/win7（31-win7-lts.md §2）。

## 背景

压缩（compaction）目前**就地删除**旧消息前缀、插入续接摘要——
压缩前的完整对话永久丢失，用户与 agent 都无法回看。这与
PHILOSOPHY.md「透明可控可回滚」冲突；hermes 用会话谱系
（parent/child lineage）让原始记录永远可溯。

## 方案

压缩时，把被删除的前缀消息**先归档进一个派生会话**，再执行原删除。
归档会话与压缩动作在同一事务——「历史已删、归档未写」不可接受
（与 M4 CRITICAL-1「历史已删、摘要未写」同一哲学）。

### A. `backend/data/session_lineage.py`（新）

- 表 `session_lineage`: id / child_id(归档会话) / parent_id(活会话) /
  reason / created_at
- `archive_prefix_in_transaction(cursor, session_id, delete_ids, reason)`:
  - 读原会话 title + 前缀消息
  - 创建归档会话行（新 id，title `"{原标题} · 压缩归档"`，
    `is_archived=1`，metadata 标 `lineage_archive_of`）
  - 逐条复制消息行（**新消息 id** 避免主键冲突，保留原 created_at 保序）
  - 写 lineage 行
- `list_archives(session_id)` / `get_parent(child_id)` 查询

### B. `backend/data/session_repo.py`

`replace_prefix_with_continuation` 在 DELETE 前调用 A 的归档
（同 cursor 同事务，整体回滚）。

### C. REST（`backend/api/legacy_session_routes.py`）

- `GET /sessions/{id}/lineage`: 列出该会话的压缩归档（含消息数、
  时间范围），归档会话本体用既有 `/sessions/{id}/messages` 读取

### D. 测试

- `backend/tests/unit/test_session_lineage.py`
- `backend/tests/integration/test_compaction_lineage.py`
  （压缩 → 归档会话存在且原文完整 → lineage 正确 → 压缩失败整体回滚）

## Round 5 候选

- docker 沙箱执行后端 / execute_code RPC 工具调用
- curator 第二块（LLM 巡检合并 + pin + provenance frontmatter）
- 消息网关 Telegram MVP / hex-legacy 双栈收敛

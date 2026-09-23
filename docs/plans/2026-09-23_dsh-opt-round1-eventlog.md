# DSH 对标优化·第一轮：会话事件日志地基（SE1）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r1-eventlog`，基线 main 830c3097）
- **系列定位**：新开 `dsh-opt` 对标系列（对标对象：DeepSeek Harness，
  `deepseek-harness` 仓库），与本文件同目录 `dsh-opt-index.md` 维护系列总账。
  编号约定：SE（Session Event）系。
- **上游文档**：PHILOSOPHY.md（透明可控 / 记忆优先）、
  docs/technical/35-session-compact-fork.md（现有 compaction 语义）
- **对标对象**：DeepSeek Harness "Model-visible ⟺ logged" 原则
  （append-only 会话事件日志为唯一事实源，模型可见历史/回放/UI 全部
  从日志投影派生；compaction 是日志上的一等事件而非旁路变异）。

## 0. 结论速览

sage 当前"模型可见历史"的唯一事实源是 `messages` 表，但
`replace_prefix_with_continuation`（backend/data/session_repo.py:607）
在压缩时会**删除**前缀行 —— 日志被就地变异，凡依赖"从历史重建"的
能力（投影、审计、回放、未来 fork/回滚）都建立在可变数据上。
本轮新增 append-only 的 `session_events` 事件日志作为唯一事实源地基：

1. `session_events` 表（per-session 单调 seq，幂等建表）；
2. `SessionEventRepository`（独立追加 + 同事务追加两种入口）；
3. 消息写入三咽喉点（`save` / `insert` /
   `replace_prefix_with_continuation`）同事务双写事件（best-effort，
   失败仅告警 —— 与既有 FTS 索引挂钩同款先例，session_repo.py:596）；
4. `backend/chat/event_projection.py` 纯函数投影
   `events_to_history(events)`，与 `db_rows_to_history` 语义逐条对齐；
5. **parity 测试**：同一会话经 MessageRepository 写入复杂消息序列
   （双 segment / tool 行 / 带 tool_calls 的 assistant / 空内容）后，
   「事件日志投影」与「messages 表投影」必须产出逐字节一致的历史。

本轮**不切换** `history_context.py` 的读取路径（零行为变更）；
切换与 compaction 的 surface-op 语义在 SE2 落地。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| SE1 | 会话历史唯一事实源可变（压缩删行），无事件日志 | `replace_prefix_with_continuation` DELETE 前缀行，重建/审计只能依赖派生会话谱系 | dsh：append-only 事件日志，"Model-visible ⟺ logged" | **P1** |

## 2. 设计（批次 A：SE1）

- **schema**（幂等，新旧库双路径安全）：

```sql
CREATE TABLE IF NOT EXISTS session_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    seq INTEGER NOT NULL,          -- per-session 单调递增，(session_id, seq) UNIQUE
    type TEXT NOT NULL,            -- 事件词表，SE1: message.appended / compaction.performed
    payload TEXT,                  -- JSON；message.appended 携带投影所需全字段
    surface_op TEXT,               -- 预留 SE2：compaction 的 replace(start_seq,end_seq) 语义
    created_at INTEGER NOT NULL,
    UNIQUE (session_id, seq),
    FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
)
```

  索引 `idx_session_events_session ON session_events(session_id, seq)`。
- **事件词表（SE1 子集）**：
  - `message.appended`：payload =
    `{id, role, content, subtype, segment_id, tool_calls, created_at}`
    （与 messages 行投影所需字段一一对应；reasoning_content 不入事件
    —— 投影语义本就剥离它）；
  - `compaction.performed`：payload =
    `{deleted_ids, continuation_id, removed_count, reason}`。
- **双写语义**：事件 INSERT 与消息写同一连接同一事务（先于 commit）；
  事件写入抛错时仅 `logger.warning` 并继续提交消息 —— 事件日志在本轮
  是增强性事实源，不允许阻断聊天（严格化与 fail-closed 在 SE2+ 评估）。
- **投影函数**：`events_to_history(events)` 复刻
  `db_rows_to_history` 的全部规则（段切片 / 角色白名单 / tool_calls
  跳过 / 空 content 跳过），未来 `history_context.py` 切换读取路径时
  二者必须可互换 —— parity 测试守门。

## 3. 批次 A 实施与验证记录

- **schema**：`session_events` 落位在 messages 迁移块之后、
  session_summaries 之前（幂等 CREATE TABLE IF NOT EXISTS + 索引，
  新旧库双路径安全，RT25 同款落位纪律）。
- **仓储**：`backend/data/session_event_repo.py` —— `SessionEvent` +
  `SessionEventRepository`；`append_with_cursor`（同事务追加，seq =
  会话内 MAX(seq)+1）与 `append`（独立事务）两种入口；仓储**不提供**
  delete/update（append-only 契约，测试断言无此入口）。
- **双写**：`session_repo.py` 五个咽喉点同事务落事件（best-effort，
  `# noqa: BLE001` 仅告警，与 FTS 索引挂钩同款降级）：
  `save` / `insert` / `replace_prefix_with_continuation`（压缩事件 +
  续接消息事件）/ `delete` / `retreat_segment`（`message.deleted`，
  段撤销若不落事件，投影会在已删除 separator 处继续切段 —— 实测踩坑
  后补上）。`delete` 先取 session_id 再删行（删后查不到）。
- **投影**：`backend/chat/event_projection.py` `events_to_history` ——
  语义与 `db_rows_to_history` 逐条对齐 + **折叠**（`message.deleted`
  id 与压缩 `deleted_ids` 不进当前视图；被排除的 separator 不参与
  切段扫描）。投影按 seq 回放，messages 表按 created_at 排序 ——
  二者在生产时钟单调下保持同序（测试内已注明该前提）。
- **已知边界（SE2 收口）**：`delete_by_session` 与 `fork_session`
  （原始 SQL 批量路径）暂不落事件；`surface_op` 列已预留。
- **测试**：+18 例（`test_session_event_repo.py` 8 例 +
  `test_event_projection.py` 10 例，含 5 组 parity：角色/tool_calls/
  空内容过滤、双段切片、insert 路径、压缩后 parity、删除/段撤销后
  parity）。
- **验证**：新测 18 例全绿；受影响回归 49 例全绿（session_repo /
  compaction_segment / history_context / message_search /
  chat_auto_compaction / compaction_lineage / chat_stream_persist /
  context_isolation_e2e，4 skip 为既有 Windows 子进程跳过项）；
  ruff 全过；`py38_compat_rewrite --check` 0 变更 + AST
  feature_version=(3,8) 解析通过；棘轮 baseline 同步
  （database.py 1840、session_repo.py 985，本提交内更新）。
- 前端零改动。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
- **回填**：（占位）

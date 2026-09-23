# DSH 对标优化·第二轮：事件日志读取切换 + 存量回填（SE2）

- **状态**：批次 A 交付中（分支 `feat-dshopt-r2-eventlog-read`，基线 origin/main a5a0d035）
- **系列定位**：`dsh-opt` 对标系列第 2 轮（总账 [dsh-opt-index.md](dsh-opt-index.md)）。
- **上游文档**：round1（SE1 事件日志地基，main #1421 / squash `1faaa49e`，
  win7 PR #1425）
- **对标对象**：DeepSeek Harness "Model-visible ⟺ logged" 的**读取侧**：
  模型可见历史从日志投影，而非对可变存储的反复重建。

## 0. 结论速览

SE1 落了事件日志与双写，但 `history_context.build_request_messages`
仍从 `messages` 表读取（SE1 刻意零行为变更）。本轮完成读取切换，三块：

1. **存量回填**：SE1 之前创建的会话没有事件日志，直接切换会让老会话
   "失忆"。新增 `backfill_session_events`（启动时、幂等、跳过已有事件
   的会话），挂在 `main.py` lifespan 的 `db.init_db()` 之后。
2. **fork 钩子**：`fork_session` 经 `_insert_forked_message_row` 原始
   SQL 复制行（SE1 已知边界）。让该函数返回新 id，fork 事务内逐条补
   `message.appended` 事件 —— 至此全部生产写入路径都有事件。
3. **读取切换**：`history_context.build_request_messages_from_events`；
   legacy producer（legacy_routes.py:3367）改为事件投影装配，事件为空
   且存在消息时**防御性回退**旧路径（回填竞态兜底）+ 告警。

附带：main 侧带回 SE1 在 win7 适配中发现的
`test_parity_after_segment_retreat` 时钟确定性修复（messages 按
created_at 排序 vs 投影按 seq，测试消息时间戳须锚定 separator 实际
落库时间）。

## 1. 差距矩阵

| # | 差距 | 证据 | 对标 | 优先级 |
| --- | --- | --- | --- | --- |
| SE2 | 事件日志已建但读取路径未切换；存量会话无事件；fork 路径不落事件 | legacy_routes.py:3367 仍传 `history_rows`；fork_session 原始 SQL 复制 | dsh：投影是历史唯一来源；迁移是存储内部细节 | **P1** |

## 2. 设计（批次 A：SE2）

- **backfill**（`backend/data/session_event_backfill.py`）：
  `SELECT DISTINCT session_id FROM messages WHERE NOT EXISTS(events)` →
  逐会话 `ORDER BY created_at ASC, rowid ASC` 全量补
  `message.appended`（payload 与双写钩子同构：id/role/content/subtype/
  segment_id/tool_calls/created_at）。幂等：有任何事件即跳过整个会话。
  lifespan 内 try/except 仅告警（回填失败不阻断启动）。
- **fork 钩子**：`_insert_forked_message_row` 返回新 id；fork 循环内
  `_append_session_event`（同事务、best-effort）。fork 复制行无
  subtype/segment（表默认值 0/NULL），payload 如实记录。
- **读取切换**：`build_request_messages_from_events(system, user,
  events, ...)` = `events_to_history(events)` → 与旧函数共享的装配内核
  （truncate / turn_limit / trailing_system 语义逐字节不变）。producer
  装配点改传事件；`history_rows` 保留给自动话题检测扫描（该消费不改）。
  回退条件：`events 为空 且 history_rows 非空` → 旧路径 + warning。

## 3. 批次 A 实施与验证记录

- **backfill**：`backend/data/session_event_backfill.py` ——
  `NOT EXISTS` 选出零事件会话，逐会话 `ORDER BY created_at ASC, rowid ASC`
  补 `message.appended`；幂等（二次运行零写入，测试锁定）。挂载点
  `main.py` lifespan `db.init_db()` 之后，try/except 仅告警。
- **fork 钩子**：`_insert_forked_message_row` 改为返回新消息 id
  （monkeypatch seam 兼容），fork 循环同事务补事件；payload.id 与
  messages 行 id 一致（parity 测试锁定）。
- **读取切换**：`history_context` 拆出 `_assemble_request_messages`
  装配内核，新增 `build_request_messages_from_events`（装配语义与旧
  入口逐字节一致，单测锁定）。producer（legacy_routes）装配点改为
  事件投影；回退条件 = 事件为空且表历史非空（回退 + warning）；
  `history_rows` 保留给自动话题检测（消费不变）。
- **顺带收获（win7 护栏）**：py38 compat 扫描暴露 legacy_routes.py
  四处存量 `X | Y` 注解（main CI 不跑 py38 护栏故从未暴露），本轮
  一并改写为 typing 形态并清理了 rewriter 造成的重复 import。
- **时钟确定性修复带回**：`test_parity_after_segment_retreat` 改用
  separator 实际落库 created_at 推导后续消息时间戳（win7 适配中
  发现该用例在毫秒级时序上脆弱，main 侧侥幸通过）。
- **验证**：新增 6 例（backfill 4 + fork parity 1 + 装配 parity 1），
  SE1 存量 18 例全绿；受影响回归 60 例全绿（session_repo /
  history_context / compaction / message_search / chat_stream_persist /
  compaction_lineage / chat_auto_compaction / context_isolation_e2e /
  session_fork_api），合计 84 例。ruff 全过；py38 护栏（compat_rewrite
  --check 0 变更 + AST feature_version=(3,8)）通过；棘轮 baseline
  同步（legacy_routes.py 5507 / main.py 1133 / session_repo.py 1009）。

## 4. 批次 B 实施与验证记录

（本轮为单批次交付，无批次 B）

## 5. 交付记录

- **main**：（PR 占位）
- **win7 对齐**：（cherry-pick 占位）
- **R1 §5 回填**：见下（随本轮合入）
- **R1 交付记录（回填）**：
  - main：PR #1421（squash `1faaa49e`，2026-09-23 merge，CI 12 项全绿，
    E2E 门禁 3 项全绿）。
  - win7：PR #1425（cherry-pick `1faaa49e` + win7 适配：save() 变量名、
    insert() 可选参数、advance_segment 单事务化、retreat 测试时钟确定性；
    merge SHA 待本轮回填）。

# 2026-11-05 长对话会话历史完整显示（非破坏性压缩）

## 背景与目标

### 现象

长对话后，会话页面只能看到最近一小段记录。界面本身并不按条数截断：

- 前端 `store.loadMessages` 以 `limit=100000` 拉取消息（`src/shared/lib/store.ts`）；
- `MessageList` 只在 `run_status === 'running'` 时渲染最近 60 条，非运行态自动展开全量。

根因在后端**自动上下文压缩**：达到阈值时，`MessageRepository.replace_prefix_with_continuation`
把旧消息**物理删除**，只保留最近 6 条（`DEFAULT_KEEP_RECENT`）并插入一条摘要续接行。
被删消息仅进入 `is_archived=1` 的派生「压缩归档」会话，主会话页面不可见。

### 实证

- `data/logs/sage_20261103.log`：`[M4] session=ce21ad04… 自动压缩完成: removed=10 after=7`
- `data/sage.db`：该会话现存 14 条，首条为 `[上下文已压缩] 此前对话摘要：…`，
  `compact_info={"before":16,"after":7,"removed":10}`；`session_lineage` 指向归档会话
  `0fd35079…`（「打招呼 · 压缩归档」），其中正是被移走的 10 条原文。

### 目标

1. **会话页面始终展示完整消息历史**：压缩不再删除消息行。
2. **LLM 上下文不膨胀**：模型仍只看到「摘要续接行 + 未压缩消息」，token 预算与现状一致。
3. **存量已压缩会话可回填**：升级后首次启动把历史归档前缀幂等恢复到主会话（仅展示，
   不进入 LLM 上下文）。
4. **修复归档查看的 100 条上限**：`sessionApi.getMessages` 未传 `limit`，后端默认按
   `created_at ASC LIMIT 100` 返回最早 100 条且无翻页。

## 技术方案

### 1. 消息新增 `compacted_at` 标记

- `messages` 表新增 `compacted_at INTEGER`：
  - `NULL` = 正常消息（进入 LLM 上下文）；
  - 非 `NULL` = 已压缩进摘要的展示历史（**不再**进入 LLM 上下文）。
- 建表语句 + `Database.init_db()` 惰性 `ALTER TABLE` 双进程防抖（沿用 R38/R81 列模式）。

### 2. 压缩改为非破坏

`MessageRepository.replace_prefix_with_continuation`：

- 前缀消息从 `DELETE` 改为 `UPDATE messages SET compacted_at = ? WHERE id = ?`；
- 仍插入摘要续接行（`compact_info` 口径不变）；
- 仍调用 `archive_prefix_in_transaction`（保留既有「查看压缩前原文」入口与旧数据兼容）；
- `sessions.message_count` 改为写入**实际行数**（`SELECT COUNT(*)`），而非上下文条数；
- 参数 `new_message_count` 失去意义，移除（同步更新唯一调用方与测试）。

### 3. LLM 上下文过滤 `compacted_at`

- `MessageRepository.get_active_segment()`：段切片后再剔除 `compacted_at IS NOT NULL`；
- `history_context.db_rows_to_history()`：同样剔除（请求边界双保险）；
- `chat/event_projection.events_to_history()`：跳过 payload 中 `compacted_at` 非空的
  appended 事件（fork 复制行的事件带该字段）；
- 压缩事件 `compaction.performed.deleted_ids` 语义保持（= 移出模型上下文的消息 id），
  事件投影对正常压缩会话的折叠行为不变。

### 4. fork / 版本切换保持标记

- `_insert_forked_message_row`：复制 `compacted_at`，事件 payload 携带该字段；
- 答案版本快照走动态列复制，天然保留 `compacted_at`（回归测试覆盖）。

### 5. 存量回填（一次性、幂等）

- `session_lineage` 新增 `needs_restore INTEGER DEFAULT 1`：
  - 旧库 `ALTER` 后既有行为 1 → 待回填；
  - 新式保留压缩创建归档时显式写 0（无需回填，避免下次启动重复复制）。
- 新增 `restore_compacted_history(db)`：把 `needs_restore=1` 的归档消息复制回父会话
  （新 id、保留原 `created_at`、`compacted_at = lineage.created_at`），重算父会话
  `message_count`，置 `needs_restore=0`；不写 `message.appended` 事件（展示行，
  非模型可见行）。
- `Database.init_db()` 末尾 best-effort 调用（异常仅告警，不阻断启动）。

### 6. 前端

- `sessionApi.getMessages(sessionId, limit = 100000)`，与 `store.loadMessages` 同口径；
  `ArchivesModal` 自动受益。运行态 60 条尾窗保持不变（避免流式重渲染）。

## 涉及文件

| 文件 | 改动 |
|------|------|
| `backend/data/database.py` | 建表列 + 惰性迁移 + 启动回填调用 |
| `backend/data/session_repo.py` | Message 模型/映射、非破坏压缩、active segment 过滤、fork 复制 |
| `backend/data/session_lineage.py` | `needs_restore` 列 + `restore_compacted_history` |
| `backend/api/chat_session_lifecycle.py` | `_persist_compaction` 适配新签名 |
| `backend/chat/history_context.py` | DB 行投影过滤 compacted |
| `backend/chat/event_projection.py` | appended 事件按 compacted_at 折叠 |
| `src/shared/api/sessionApi.ts` | `getMessages` 默认 limit=100000 |
| `docs/technical/35-session-compact-fork.md` | 归档非破坏压缩 + 回填语义 |

## 实施步骤

- [x] M1：schema + `Message` 模型/序列化（含迁移）
- [x] M2：非破坏压缩 + `get_active_segment` / `db_rows_to_history` 过滤
- [x] M3：fork 复制与事件投影（含 parity）
- [x] M4：存量归档回填（幂等）+ 启动接入
- [x] M5：前端 `getMessages` limit
- [x] M6：新增/更新测试、技术文档归档（`docs/technical/35-session-compact-fork.md` §1.1）

## 实施结果（2026-11-05）

- 后端：新增 `messages.compacted_at`（迁移 v11 main / v13 release-win7）+ `session_lineage.needs_restore`；
  压缩改为标记保留；legacy/hex 两条 LLM 历史路径均过滤压缩展示行。
- 存量数据验证（真实 `data/sage.db` 副本）：会话 `ce21ad04…` 由 14 条恢复为
  24 条（10 条 `compacted_at` 展示行），活跃上下文仍为 14 条；二次启动行数不变（幂等）。
- 测试：后端相关 137 例全绿（py38 + py310 双环境）；前端 `sessionApi` 及归档/
  尾窗/对账 22 例全绿；`tsc --noEmit`、`ruff`、py38 兼容扫描、架构棘轮均通过。
- 备注：worktree 内直接跑后端测试需 `PYTHONPATH=<worktree>/packages/sage-core:<worktree>`
  （共享 conda 环境的 `sage-core` 是 editable 指向主目录）；CI 从分支安装无此问题。

### 代码审查修复（2026-11-05 第二波）

外部 `code-reviewer` 代理复核，发现 1 HIGH + 6 MEDIUM，已全部解决：

- **HIGH** 网关外部通道会话回放压缩展示行进 LLM：`gateway/base.py` 改用
  `get_recent_messages` + 过滤 `compacted_at`。
- **MEDIUM** 审阅/知识提取同样泄漏：`review_queue.py` 改用 `get_active_segment`；
  `project_knowledge_extractor.py` 增加过滤。
- **MEDIUM** 排序 tie 致续接行与保留消息错位：`get_by_session` / `get_recent_messages`
  加 `rowid` 二级排序；`get_active_segment` 切换到尾部窗口，同时解决 100k 上限风险。
- **MEDIUM** 事件投影 parity：`save()` 与 `answer_version_repo` 的 `message.appended`
  事件 payload 都加 `compacted_at`。
- **MEDIUM** `archive_prefix_in_transaction` 默认参数易被误用：`needs_restore` 改为
  keyword-only 必填。
- **LOW** 回填计数在事务回滚路径被高估：改为 commit 成功后再累加。
- **LOW** 非破坏压缩的事务回滚测试被削弱：新增 `test_compaction_failure_rolls_back_marking_and_archive`。

最终验证：后端相关 214 例 + 前端 33 例全绿；`ruff` / `tsc --noEmit` / `scripts/architecture-check.mjs` / `check_py38_compat.py` 全通过；真实 `data/sage.db` 副本启动迁移回填幂等验证通过。

### 第二轮复核（2026-11-05）

- 复核确认 HIGH + 6 MEDIUM + 2 LOW 全部解决；
- 残留 1 MEDIUM：回填行与摘要 `created_at` 相同（连续毫秒）时摘要插进前缀中间。
  修复：`get_by_session` 排序增加一档 `(compacted_at IS NULL) ASC`，同一毫秒内压缩
  展示行优先；新增 `test_restore_orders_prefix_before_summary_on_timestamp_tie` 回归。
- 环境提示：`sage-core` 新增 `Message.compacted_at`，共享 conda 环境是 editable 指向
  主目录；本地跑 worktree 测试需 `PYTHONPATH=<worktree>/packages/sage-core:<worktree>`
  或在工作树内重装 `pip install -e packages/sage-core`（CI 从分支安装不受影响）。

## 测试计划

- 新增：压缩后原始行保留且 `compacted_at` 非空；续接行排序正确；
  `get_active_segment`/`db_rows_to_history` 不含压缩行；fork 保留标记且事件投影跳过；
  回填一次生效且再次启动不重复；旧库迁移幂等。
- 更新：`test_session_compact_api` / `test_chat_auto_compaction` /
  `test_session_lineage` 中按旧「删除」契约断言的行数与 `message_count`。
- 前端：`sessionApi.test.ts` 断言 `get_messages` 携带 `limit: 100000`。

## 风险评估与依赖

- **存储增长**：压缩后保留全部行，且归档仍复制一份。单条消息最多被归档一次，
  可接受；后续如确认无需归档可停用新归档写入。
- **长列表渲染**：非运行态全量渲染可能变慢（既有尾窗仍在 running 生效）；
  后续可做压缩前历史分组折叠，不在本次范围。
- **语义变化**：`sessions.message_count` 从「上下文条数」改为「实际行数」；
  依赖方（自动标题 `>0`、evolution `min_messages`）语义仍成立。
- **双分支**：先落 release/win7，验证后 cherry-pick main（改动集中在数据层，
  两分支同函数无分叉）。

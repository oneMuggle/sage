# 记忆系统 P0 优化计划

> 日期：2026-07-29
> 分支：`feat/memory-p0-optimization`（从 main 切出）
> 来源：对比 claw-code / hermes-agent / sage 三方记忆系统后的差距分析

## 背景与目标

对比调研发现，sage 记忆系统在架构完整度（六边形 + 三层记忆 + 单例化 + 进化调度）上优于 claw-code，但与 hermes-agent 相比存在若干**核心闭环缺陷**。本计划聚焦 P0 级问题（影响核心能力）+ 两个低成本一致性修复，全部为后端改动，文件归属互斥，可 4 路并行实施。

**目标**：

1. 修复工作记忆跨会话串味（WorkingMemory 不按 session 隔离）
2. 打通 legacy `/chat/stream` 路径的记忆写入（当前只有 hex 路径写记忆，一半对话数据丢失）
3. 启用已建但闲置的 FTS5 全文索引（替换 LIKE+jieba 慢扫描）
4. 修复分类/晋升路径的数据不一致（working 路径丢 id、晋升后 episodic 残留重复）
5. 为 hex 路径引入 system prompt frozen snapshot（提升 prefix cache 命中率）

**非目标**（留给后续计划）：provider 插件化、后台自审 fork、数据库加密、写入审批 gate、UI 改动。

## 涉及的文件与模块

| 工作流 | 独占文件（其他工作流禁触） |
|---|---|
| WS-A 记忆核心 | `backend/memory/working.py`、`backend/memory/manager.py`、`backend/memory/registry.py`、`backend/adapters/out/memory/adapter.py`、`backend/memory/consolidation.py` |
| WS-B FTS5 | `backend/data/database.py`、`backend/memory/semantic.py` |
| WS-C 集成 | `backend/api/legacy_routes.py`、`backend/application/services/chat_service.py` |
| WS-D 调度 | `backend/scheduler/evolution.py` |

共享只读：`backend/data/session_repo.py`、`backend/memory/episodic.py`、`backend/memory/extractor.py`、`backend/memory/vector_store.py`（只调用，不修改）。

## 技术方案

### WS-A：WorkingMemory 按 session_id 隔离 + 分类一致性（对应 P0-1 / P0-4 / P2-1）

**现状缺陷**：

- `registry.get_memory_manager()` 构造的 `WorkingMemory` 未传 `session_id`，全进程共享一个 deque，多会话串味。
- `working_memory_snapshot` 表写入 `session_id=NULL`，重启后无法区分会话。
- `memorize(memory_type='working')` 只塞 deque 不返回 id，且后续检索不可见。
- `manager._classify_memory_type`（importance≥8→semantic）与 `adapter.store` 默认行为（走 episodic）规则不一致。

**设计**：

1. `WorkingMemory` 改为 **session 感知**：内部 deque 元素携带 `session_id`；`add(session_id, message)`、`get_context(session_id)`、`clear(session_id)`、`total_tokens(session_id)`；全局容量约束（max_size=20 / max_tokens=4000）按 session 各自计数。
2. `_save_snapshot()` / `_load_snapshot()` 按 `session_id` 分行写入/恢复（session_id 列已存在则用，不存在则迁移加列）。
3. `MemoryManager` 公开方法全部追加可选 `session_id=None` 参数（**向后兼容**，不破坏现有调用）：
   - `memorize(content, memory_type='auto', importance=5, tags=None, session_id=None)`
   - `recall(query, limit=5, session_id=None)`
   - `compress(session_id=None)`
   - `search_memories(query, memory_type=None, limit=20, session_id=None)`：当 `memory_type in (None, 'working')` 时，结果并入当前 session 的工作记忆条目，标记 `memory_type='working'`、`source='working_memory'`（修复"working 检索不可见"）。
4. `memorize(memory_type='working')` 返回值：工作记忆条目无持久 id，统一返回 `f"wm:{session_id}:{seq}"` 合成 id（仅用于日志/回显，UI 删除路径不依赖它）。
5. 分类一致性：`_classify_memory_type` 与 `MemoryAdapter.store` 统一引用同一个模块级函数 `classify_memory_type(memory_type, importance, content)`（放在 `manager.py`），消除两处规则漂移。
6. `MemoryAdapter.retrieve/compress` 透传 `session_id`；`compress` 只压缩指定 session 的工作记忆。
7. `ConsolidationPipeline.consolidate` 接受 `session_id` 并透传。

**测试**（TDD，先写后实现）：

- `backend/tests/unit/test_memory_working.py` 扩展：双 session 隔离（A 加消息不影响 B 的 get_context/total_tokens）、按 session 快照持久化与恢复、按 session clear。
- 新增 `test_memorize_working_returns_id`、`test_search_includes_working_entries`。
- 新增 `test_classify_consistency`：`classify_memory_type` 与 adapter 实际落表一致。

### WS-B：FTS5 启用（对应 P0-5）

**现状缺陷**：`memories_semantic_fts` 虚表与触发器已在 `database.py` 建好但被注释禁用（注释称 "database disk image is malformed"），`SemanticMemory.search()` 实际走 `LIKE '%kw%' + jieba`，随数据量退化。

**设计**：

1. 诊断并修复 FTS5 损坏根因：改用 **独立 FTS5 表 + 显式同步**（不依赖可能写错的触发器列映射），INSERT/UPDATE/DELETE 触发器引用正确的 `rowid ↔ id` 映射；若现有表结构不支持稳定触发器，则在 `init_db` 中 **drop 重建** `memories_semantic_fts` 并回填。
2. `init_db` 增加 FTS 自愈：捕获 `database disk image is malformed`，drop 虚表 + 触发器后重建并回填，记 warning 日志。
3. `SemanticMemory.search()`：jieba 分词 → 组装 FTS5 MATCH 查询（多词 OR，短语用双引号）→ 命中不足时回退现有 LIKE+jieba 路径（保证可用性）。保留原有 importance/标签过滤。
4. 新增 `episodic` 不建 FTS（控制范围；episodic 走现有 LIKE+jieba）。
5. 回填迁移：`init_db` 末尾把 `memories_semantic` 现有行同步进 FTS 表（幂等，`INSERT OR IGNORE` / 先 delete 再 insert）。

**测试**（TDD）：

- 新增 `backend/tests/unit/test_semantic_fts.py`：中文短语命中、英文词命中、空查询回退、FTS 表损坏时自愈重建后仍可搜索、回填幂等。

### WS-C：统一记忆写入路径 + frozen snapshot（对应 P0-2 / P0-3）

**现状缺陷**：

- `legacy /chat/stream` producer 持久化 user/assistant 消息后**不触发** `MemoryExtractor`，只有 hex `ChatService.run_turn` 会写记忆。
- hex 路径每个 turn 重新组装 system prompt + 重新 retrieve 记忆，prefix cache 命中率低。

**设计**：

1. 把 `ChatService._extract_and_store_memory` 的核心逻辑抽成模块级可复用函数（放 `chat_service.py` 内，如 `extract_and_store_memory(memory_adapter, extractor, user_text, assistant_text, session_id, settings)`），`ChatService` 与 `legacy_routes` 共用。
2. `legacy_routes.py` 的 `/chat/stream` producer：在 assistant 消息持久化成功后，**best-effort** 调用该函数（异常只 warning，不破坏流；受 `app_settings.autoMemory` 开关控制，与 hex 行为一致）。
3. Frozen snapshot（hex 路径）：`ChatService` 增加 `self._system_prompt_snapshots: dict[session_id, str]`：
   - 首次 turn 组装完整 system prompt（静态段 + 记忆上下文段）后缓存；
   - 后续 turn 直接复用缓存字符串；
   - 失效点：会话压缩完成后（compaction 路径调用 `invalidate_session_snapshot(session_id)`）、`reset`。
   - 每 turn 动态 retrieve 的记忆上下文仍保留（hermes 做法是注入 user 消息；本次为降低风险**保持注入 system prompt 的位置不变**，但快照机制保证静态段稳定——即快照 = 静态段，动态记忆段每 turn 拼接在快照之后）。
4. 不改动 `MemoryExtractor`、`episodic.py`、`vector_store.py`。

**测试**（TDD）：

- 扩展/新增集成测试：legacy `/chat/stream` 完成后 `memories_episodic` 出现提取条目（mock LLM extractor 返回固定 facts；`autoMemory=false` 时不写）。
- 单元测试：snapshot 缓存命中（第二次 run_turn 不重新组装静态段）、compaction 后失效重建。

### WS-D：晋升软删 + 进化日志落表（对应 P2-5 / A5）

**现状缺陷**：

- `MemoryConsolidationTask` 把 episodic 提升到 semantic 后，原 episodic 行仍 `is_valid=1`，检索出现重复事实。
- `memories_evolution_log` 表已建但从未写入，无法追溯记忆级变更。

**设计**：

1. `MemoryConsolidationTask`：提升成功后把源 episodic 行 `is_valid=0`（软删，保留审计痕迹），同事务。
2. 三个会修改记忆的任务（`MemoryConsolidationTask` / `ImportanceReevaluationTask` / `MemoryPruningTask`）在每条变更后写 `memories_evolution_log`（字段按现有表结构：memory_id、change_type、old_value、new_value、task_name、created_at；先用 `PRAGMA table_info` 确认列名再写）。
3. 不改 `database.py`（表已存在）。

**测试**（TDD）：

- 扩展 `backend/tests/unit/`（或 integration）进化任务测试：晋升后 episodic 源行 `is_valid=0` 且 semantic 有新行；`memories_evolution_log` 出现对应记录（promote / decay / prune 各一条）。

## 实施步骤

- [x] M0：计划文档（本文件）+ feature 分支
- [x] M1（WS-A）：WorkingMemory session 隔离 + 分类一致性 + 单测
- [x] M2（WS-B）：FTS5 修复启用 + 自愈 + 回填 + 单测
- [x] M3（WS-C）：legacy 写入统一 + frozen snapshot + 测试
- [x] M4（WS-D）：晋升软删 + evolution_log 落表 + 测试
- [x] M5：集成验证——CI 等价全量 pytest（sage-backend 环境）**2529 passed, 0 failed**，coverage **89.67%**；全后端 ruff clean
- [x] M6：并行代码评审 + TDD 修复 3 个阻断（legacy `/chat` session 透传、drawio ToolPort、压缩签名）+ simplify 收尾 + 更新本文件

M1–M4 由 4 个 subagent 并行实施（文件归属互斥）；M5 由主线统一执行。

## 风险评估与依赖

| 风险 | 影响 | 缓解 |
|---|---|---|
| WS-A 改动 MemoryManager 公开签名 | WS-C 调用方编译/运行失败 | 只追加可选参数，向后兼容；WS-C 按本文件约定契约调用 |
| FTS5 重建触发器与 sqlite-vec 初始化交互 | init_db 失败 | WS-B 保持 sqlite-vec 初始化顺序不变，FTS 自愈包在 try/except |
| legacy 路径提取记忆增加每 turn 延迟 | 流式响应变慢 | best-effort + 在 assistant 落盘**之后**异步风格执行，失败只 warning |
| frozen snapshot 与设置热更新 | 用户改设置后 prompt 不更新 | 失效点挂在 compaction；设置变更属低频，本次接受（后续可挂 settings 变更事件） |
| 4 路并行 pytest 同时写临时 DB | 测试互相干扰 | 各测试用 pytest tmp_path 独立 DB；各 agent 只跑自己的测试文件，全量回归放 M5 |

## 依赖

- 无新增第三方依赖（FTS5 为 SQLite 内置）。
- 测试环境：`/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest`（main 分支 Python 3.11）。

## 实施记录（2026-07-29 完成）

### 产出统计

| 工作流 | 文件 | 新增测试 | 验证 |
|---|---|---|---|
| WS-A 记忆核心 | working/manager/registry/adapter/consolidation（5 改） | 42 用例 | 目标套件 85 passed |
| WS-B FTS5 | database/semantic（2 改） | 11 用例 | 新套件 11 passed + 邻域 68 passed |
| WS-C 集成 | chat_service/legacy_routes（2 改） | 15 用例 | 新套件 15 passed + 回归 61 passed |
| WS-D 调度 | evolution（1 改） | 11 用例 | 新套件 11 passed + 集成 7 passed |
| M5/M6 主线 | agent/chat_service/consolidation + 3 个对应测试（6 改） | 净增 2 用例 | **全量 2529 passed, 0 failed**；coverage **89.67%**；全后端 ruff clean；3 路复审确认阻断关闭 |

合计：11 个实现文件 + 10 个测试文件，约 +1500/−320 行；相对基线净增 81 个通过用例。4 路 subagent 并行实施（文件归属互斥），M5 主线集成，M6 通过 4 路初审 + 3 路定向复审关闭 3 个合并阻断，并完成 simplify 收尾。

### 与计划的偏差（实施中确认）

1. **WS-A**：`total_tokens` 保留为可读写的 int 属性（全局合计），per-session 查询用新增 `total_tokens_for(session_id)`；M6 评审发现 `core/legacy/agent.py` 仍读取全局属性且未透传 session，已改为 `get_context/add_to_working/total_tokens_for/consolidate` 全链路显式传 `session_id`。构造参数 `session_id=` 保留（语义降为“实例默认会话”），未绑定实例启动时不自动恢复 default 会话（与旧行为等价，旧实现 `WHERE session_id = NULL` 恒假事实上从不恢复）。
2. **WS-B**：malformed 根因为旧表是 **external-content FTS5**（同步协议被 plain DELETE 破坏 + rowid 漂移）；修复为独立存内容 FTS5 表 + **Python 侧显式同步**（不用触发器，因 jieba 无法进 SQL 触发器）；索引侧分词用 jieba `cut_for_search`（搜索引擎模式）解决中文短词命中长词。
3. **WS-C**：`autoMemory` 缺省取 True（与前端 defaultSettings 一致）；compaction 失效点挂在 `_persist_compaction` 唯一落盘出口（自动/手动压缩共用）；因 ChatService 由 DI 工厂按需构造，采用模块级 WeakSet 登记表广播失效。
4. **WS-D**：`memories_evolution_log` 真实列名与计划假设不同（`operation`/`before_content`/`after_content`/`reason`），按 PRAGMA 实际结构映射；prune 日志粒度为每规则批次一条。

### 交叉验证结论

- WS-D 晋升经 `SemanticMemory.save()`（evolution.py:854）→ WS-B 的显式 FTS 同步自动覆盖晋升行，WS-B 担心的"进程内 FTS 盲区"在晋升路径不成立。
- WS-A 的 session_id 透传 + WS-C 的 legacy 接线端到端打通：集成测试断言提取条目行级 `session_id` 落表通过。
- M6 评审阻断均已关闭：legacy `/chat` 不再落 default 工作记忆；hex 静态 prompt 使用真实 `ToolPort.list_tools()` 并复用 `DRAWIO_TOOL_PREFIX`；`ConsolidationPipeline.save_compressed()` 与 `EpisodicMemory.save()` 签名兼容，正向测试验证摘要落库且只清空目标 session。

### 遗留事项（后续计划）

| 优先级 | 事项 | 说明 |
|---|---|---|
| P1 | **created_at 毫秒/秒单位不一致（既有 bug）** | 仓储层写毫秒，evolution 三任务 WHERE 按秒比较 → 仓储写入的行永不被 pruning/衰减选中。修复需统一单位并处理存量数据，涉及 episodic.py 等多文件，独立成 PR |
| P2 | 快照字典无界增长 | `_system_prompt_snapshots` 按 session 累积；桌面量级可忽略，可加 LRU 或 delete_session 清理 |
| P2 | 快照与设置热更新 | 运行中改 endpoint 后静态段需压缩/重启才刷新；可挂 settings 变更事件调 `invalidate_session_snapshot` |
| P2 | WorkingMemory 持久化并发与效率 | `_save_snapshot` 为 DELETE+逐行 INSERT，当前同步桌面路径可用；后续可加 per-session lock/事务并改为增量写，`_evict_session` 可改 per-session deque |
| P2 | legacy 记忆 API 契约一致性 | `/memory/save` 仍直调 `MemoryManager`（不经 adapter safety scan）；working 合成 id 不支持 `/memory/delete`。均为既有兼容行为，需独立 API 设计后统一 |
| P2 | FTS 同步可观测性 | `_sync_fts_row` 失败会 warning 并由搜索回退 LIKE 保可用；后续可加 metric 与阈值触发 backfill |
| P2 | 晋升软删非严格单 ACID 事务 | `semantic.save()` 内部自 commit；去重检查兜底不丢数据，严格原子需改 semantic.py 事务边界 |
| P3 | legacy 提取对象复用 | `/chat/stream` 每轮构造 MemoryAdapter/HttpxLLMAdapter；桌面负载可接受，后续可接入 DI 生命周期复用连接池 |
| P3 | episodic FTS | 本次仅 semantic 建 FTS；episodic 仍走 LIKE+jieba，数据量大后可同法扩展 |


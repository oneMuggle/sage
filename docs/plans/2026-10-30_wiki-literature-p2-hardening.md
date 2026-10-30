# Wiki × 文献库 P2 收尾实施计划

> **状态：** 进行中（2026-10-30，worktree `feat/wiki-literature-p2`，基于 main `64a8e95be`）

**Goal:** 收尾 2026-10-30 审计列出的五项 P2：PDF FTS attachment itemID、Adamic-Adar 第 4 信号、文献聚合器接入 Zotero 输出、后台队列守护进程、HNSW 可选接线。

**Architecture:** 后端保持 py3.8/py3.10 双兼容（本分支先按 main py3.10 开发，完成后 cherry-pick 到 release/win7 用 py3.8 验证）；不新增必装依赖（HNSW 仍为可选）。

**Tech Stack:** FastAPI / pytest；React + Vitest；Zotero SQLite 只读。

---

## Task 1: PDF FTS 按附件 itemID 查询

**Files:** `backend/zotero/client.py`、`backend/tests/unit/zotero/test_client.py`

- [ ] 测试：fixture 把 fulltext 词挂到附件 itemID 10，`read_pdf_fulltext("ITEM1")` 仍返回 `deep learning`；ITEM2 的父条目自索引词仍可通过 legacy fallback 命中。
- [ ] 实现：新增 `_fulltext_item_ids(parent_item_id)` = `[parent] + itemAttachments.itemID where parentItemID=?`；`_get_fulltext_from_index` 按顺序尝试每个 ID，命中即返回。
- [ ] 跑 `pytest backend/tests/unit/zotero/test_client.py -q` 并提交。

## Task 2: Adamic-Adar 第 4 信号

**Files:** `backend/wiki/models.py`、`backend/wiki/graph.py`、`backend/tests/unit/test_graph_cache.py` 或新增 `backend/tests/unit/wiki/test_graph_adamic_adar.py`、`src/shared/types/wiki.ts`、`src/widgets/wiki/WikiGraphView.tsx`、`src/widgets/wiki/__tests__/WikiGraphView.test.tsx`

- [ ] 后端测试：三角形 a-b-c 生成 `adamic_adar` 双向边，权重 = `(1/log(2)) * 1.5`；无共同邻居不生成。
- [ ] 实现：`GraphSignal.AdamicAdar = "adamic_adar"`；`ADAMIC_ADAR_WEIGHT = 1.5`；基于无向邻居集合计算共同邻居 `sum(1/log(max(degree,2)))`，双向加边去重。
- [ ] 前端：类型加 `'AdamicAdar' | 'adamic_adar'`，配色 `#f59e0b`，`normalizeGraphSignal` 映射；测试覆盖。
- [ ] 跑后端 graph 测试 + 前端 WikiGraphView 测试并提交。

## Task 3: 文献聚合器接入 Zotero 输出

**Files:** `backend/wiki/literature_aggregator.py`、`backend/api/wiki_routes.py`、`backend/api/zotero_sync_routes.py`、`backend/tests/unit/test_literature_aggregator.py`、`backend/tests/unit/test_wiki_integration.py`

- [ ] 测试：构造 `wiki/zotero/items/K1.md`（Zotero 页面格式：`**Authors**: A, B.`、`Year: 2021 | Type: ...`、`## Abstract`），`generate_literature_review` 生成 `wiki/literature/index.md`，含标题/作者/年份/链接。
- [ ] 实现：扫描 `wiki/zotero/items/*.md` + `wiki/literature/*.md`（排除 `index.md`），解析 Zotero 正文元数据；输出改为 `wiki/literature/index.md`（graph 会跳过 index.md）。
- [ ] 接入：`_run_wiki_export` 成功后 best-effort 调用聚合器；新增 `POST /wiki/literature/review` 返回 `{path, count}` 供手动触发。
- [ ] 跑相关测试并提交。

## Task 4: 后台队列守护进程

**Files:** `backend/wiki/queue_worker.py`、`backend/wiki/queue_daemon.py`（新）、`backend/api/wiki_routes.py`、`backend/main.py`、`backend/tests/unit/wiki/test_queue_daemon.py`

- [ ] 测试：临时项目含 pending 任务，monkeypatch `process_pending`，`run_queue_daemon(max_cycles=1, poll_seconds=0)` 调用一次；无 pending 不调用。
- [ ] 实现：`queue_worker.queue_process_lock`（共享 LazyLock），路由改用它；daemon 每 60s 扫描 `ProjectRepository.list()` + recent projects，对含 `.llm-wiki/ingest-queue.json` 且 pending>0 的项目在锁内 `process_pending(limit=5)`；单项目异常不影响其他项目。
- [ ] main lifespan 创建 `app.state.wiki_queue_task`，shutdown 取消。
- [ ] 跑队列测试并提交。

## Task 5: HNSW 可选接线

**Files:** `backend/wiki/vectorstore_factory.py`（新）、`backend/wiki/ingest.py`、`backend/wiki/chat.py`、`backend/tests/unit/wiki/test_vectorstore_factory.py`

- [ ] 测试：默认 `SAGE_WIKI_VECTOR_BACKEND` 未设置 → JSON `VectorStore`；设置 `hnsw` 且 hnswlib 可导入 → `HNSWVectorStore`；非法值/导入失败 → 回退 JSON。
- [ ] 实现：`open_vector_store(project_root, dim)` 按环境变量选择，懒导入 HNSW；ingest/chat 改用工厂。
- [ ] 跑向量库测试并提交。

## 收尾

- [ ] main 环境全量相关回归：后端 pytest（py3.10）、前端 vitest、typecheck、ruff、architecture check。
- [ ] 技术文档更新（25 / 103 / 50）与计划勾选。
- [ ] 开 PR 到 main；合并后 cherry-pick 到 release/win7，py3.8 环境复验。
- [ ] P2 剩余观察项：真实 Zotero 库验证 PDF FTS、Win7 实机 reparse/HNSW 可用性。

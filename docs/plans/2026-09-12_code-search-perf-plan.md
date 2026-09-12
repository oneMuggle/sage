# Round 17 批次 E —— codebase_search 性能与可用性收尾

> 承接 #686（分块 v2）/ #693（混合检索）。检索质量到位后，本批收尾两处
> 体验短板：结果无法指导精确读文件、增量索引串行嵌入慢。

## 改动

### A. 结果透出 end_line（后端计算，零 schema 变更）
- `_search_workspace` 结果新增 `end_line = start_line + content.count("\n")`；
- 工具壳响应结构不变（多一个字段），代理可据此直接 `read_file(offset/limit)`
  或 `edit_file` 精确定位，省一次探测读。

### B. 嵌入批并行化
- `_embed_texts` 内分批（32/批）后改 `ThreadPoolExecutor` 并行提交，
  `max_workers = SAGE_INDEX_EMBED_CONCURRENCY`（默认 4，0/1 → 串行回退）；
- 结果按原批序拼接（executor.map 保序），嵌入语义不变；
- httpx 调用为 IO 密集，线程池收益约等于并发度。

### C. 单批重试容错
- 每批失败（网络抖动/429）重试 1 次（1s 退避）；二次失败跳过该批并在
  `_index_workspace` 返回值透出 `failed_chunks` 计数，不再让单批炸掉整轮索引。

## 测试（test_workspace_index.py 增补）
- 搜索结果含 end_line 且等于 start_line + 行数 - 1；
- 并行嵌入保序（monkeypatch 记录提交序/完成序，向量按原批对齐）；
- 第一批失败重试后成功 → 索引完整；连续失败 → 跳过并透出 failed_chunks。

## 不做
- 索引进程化/后台任务队列（现有同步工具调用模型不变）；
- 向量批大小调参。

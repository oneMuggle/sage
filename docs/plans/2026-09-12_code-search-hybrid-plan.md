# Round 17 批次 D —— codebase_search 混合检索（FTS5 关键词 + 向量 RRF 融合）

> 背景：分块 v2（#686）解决了「块切得差」，但检索侧仍是**纯向量**——
> 精确标识符（函数名/类名/常量名）的命中远弱于语义近邻，开发者按符号名搜代码
> 是最高频路径。本批给语义索引加 FTS5 关键词通道，双路 RRF 融合。

## 设计

### 索引侧（workspace_index.py）
- 新增 `chunks_fts` 虚表（FTS5, unicode61 tokenizer）：`path, start_line, content`；
  与 `chunks` 行同事务写入/删除（INSERT / DELETE path 同步）。
- `_index_workspace`：建表容错（sqlite 未编 FTS5 → `_fts_available=False` 降级纯向量）；
  chunker_version 复用为 FTS 重建信号（v2 内容写入时同步重建 FTS）。
- 文件级删除/清理路径同步删 FTS 行（`DELETE FROM chunks_fts WHERE path = ?`）。

### 查询侧
- `_search_workspace`：
  1. 向量路：现有余弦 top-N（N = limit*4 候选池）；
  2. 关键词路：query 规整为 FTS MATCH 语法（非字母数字拆词 + OR 连接，引号包原词组），
     FTS5 `bm25()` 排序取 top-N；FTS 不可用/查询空 → 跳过；
  3. 融合：RRF（`score = Σ 1/(60 + rank)`）按 `(path, start_line)` 归并去重，
     输出 top-limit，块文本以向量路结果为准（避免重复取行）。
- 响应结构不变（path/start_line/content/score），`score` 为 RRF 分（原语义仅内部排序用）。

### 兼容
- py3.8 纪律语法（typing.Optional 等）；旧索引库无 FTS 表 → 自动补建并全量重建一次
  （chunker_version 递增到 '3'）。

## 测试（test_workspace_index.py 增补）
- FTS 行随索引/删除/文件消失同步增删；
- 精确标识符 query 在融合结果中排到语义近似之前（RRF 生效）；
- FTS 不可用 monkeypatch（建表抛错）→ 降级纯向量且不抛；
- 旧库（无 FTS 表 + version='2'）→ 自动重建至 '3'；
- MATCH 语法规整：特殊字符不炸、CJK 单词串不被拆碎。

## 不做
- BM25 权重调参、语义+关键词分数加权（RRF 常数固定 k=60）；
- 向量库换型（仍是 sqlite blob + numpy 余弦）。

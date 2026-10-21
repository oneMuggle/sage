# FTS5 vs LIKE 基准测试（修订版 v2）

> 日期：2026-10-20（v2：2026-10-21）
> 分支：`fix/fts5-backfill-loop`（基于 main）
> 语料规模：10,000 条合成记忆
> 测试文件：`backend/tests/bench/test_episodic_fts_vs_like.py`
> 修订动机：v1 误诊了 "DevOps"/"数据库" 查询 FTS 命中为 0 的根因，本文档纠正分析

## 背景

PR #2125 / #2130 引入 Episodic FTS5 全文索引（`memories_episodic_fts`），作为
`_search_like()`（LIKE + jieba 回退）的加速路径。`search()` dispatcher 优先走 FTS5，
命中为空时回退 LIKE。

**v1 误诊（2026-10-20）**：首版基准显示 "DevOps"、"数据库" 两个查询 FTS 命中 0 而 LIKE
命中 50，被归因为"jieba 在 FTS5 tokenizer 中的行为与查询时的 `tokenize_for_search()` 不一致"。
建议"统一 tokenizer"。

**实际根因（2026-10-21 修正）**：FTS 索引未完整回填。`_backfill_fts()` 在 `__init__` 中
只被调用一次，且内部是单批 `LIMIT 500` 后直接返回——10000 条语料只有 500 行进入 FTS 索引，
后写入的"DevOps 部署流程"和"数据库优化方法"主题全部缺失。这不是 tokenizer 不一致，
而是 `_backfill_fts()` 的批处理逻辑没有循环补齐。

**修复**：
- `backend/memory/episodic.py` 中 `_backfill_fts()` 改为 `while True` 循环分批，
  每批 `_FTS_BACKFILL_BATCH=500` 行，每批 commit，直到所有缺失行补齐
- 暴露模块级 `sync_fts_row_for_id(conn, memory_id)` 供绕过 `save()` 的直写路径
  （如 `scheduler/evolution.py` 的 daily_summary INSERT）手动同步 FTS 行
- 新增回归测试 `test_backfill_indexes_more_than_500_rows`，插入 600 行存量验证
  全部入索引

## 测试方法

### 语料生成

- **规模**：10,000 条合成记忆（5 个主题 × 2000 条变体）
- **主题**：Python 编程技巧、FastAPI 开发实践、数据库优化方法、机器学习入门、DevOps 部署流程
- **内容模板**：中英文混合，含技术术语和中文描述
- **标签**：每条记忆随机 1-4 个标签（从 15 个候选池中采样）
- **存储**：SQLite 临时文件，`memories_episodic` 表 + `memories_episodic_fts` 虚表

### 查询集（8 个查询，覆盖不同选择性）

| # | Query | Label | 预期行为 |
|---|-------|-------|----------|
| 1 | `Python` | 单 token 常见 | 高命中，FTS ⊇ LIKE |
| 2 | `DevOps` | 单 token 稀有 | 高命中（修复后）|
| 3 | `FastAPI` | 英文 token | 高命中，FTS ⊇ LIKE |
| 4 | `数据库` | 中文双词 | 高命中（修复后）|
| 5 | `Python OR FastAPI` | 多 token OR | FTS5 OR 语法 |
| 6 | `机器学习` | 长尾短语 | 中等命中 |
| 7 | `xyznotexist` | 空命中 | 两路径都返回 0，FTS 显著更快 |
| 8 | `docker` | 标签命中 | FTS 命中 > 0（tags 列），LIKE == 0 |

### 测量方法

- 直接调用 `EpisodicMemory._search_fts()` 和 `_search_like()`（绕过 `search()` dispatcher）
- 每个查询跑 11 次，去掉首次 warm-up，取中位数
- **召回对比**用 `limit=10_000` 取全量（避免 BM25 vs importance DESC 排序差异导致的 top-50 子集错位）
- **延迟对比**用 `limit=50`（模拟生产 `search()` 默认 limit）
- 硬件：Linux x86_64, Python 3.10.20, SQLite 3.x
- 索引完整性断言：`fts_count == 10_000`（v1 未做此断言，漏检了 LIMIT 500 bug）

## 实测结果

| Query | Label | FTS median (ms) | LIKE median (ms) | Speedup | FTS hits | LIKE hits | FTS-only |
|-------|-------|-----------------|------------------|---------|----------|-----------|----------|
| `Python` | 单 token 常见 | 4.47 | 4.08 | 0.9x | 3403 | 2000 | 1403 |
| `DevOps` | 单 token 稀有 | 2.89 | 5.32 | 1.8x | 2000 | 2000 | 0 |
| `FastAPI` | 英文 token | 4.79 | 4.69 | 1.0x | 3371 | 2000 | 1371 |
| `数据库` | 中文双词 | 3.16 | 4.80 | 1.5x | 2000 | 2000 | 0 |
| `Python OR FastAPI` | 多 token OR | 6.48 | 4.87 | 0.8x | 5911 | 4000 | 1911 |
| `机器学习` | 长尾短语 | 6.48 | 7.07 | 1.1x | 3635 | 3635 | 0 |
| `xyznotexist` | 空命中 | 0.18 | 18.65 | **102.3x** | 0 | 0 | 0 |
| `docker` | 标签命中 | 5.85 | 17.49 | 3.0x | 1685 | 0 | 1685 |

**索引完整性：10000 / 10000 行入 FTS 索引**（修复前仅 500 行）

## 分析

### FTS5 的三项真实价值（修订后结论）

**v1 把 FTS5 当作"加速路径"，追求 ≥5× 加速比。实际上 FTS5 在 10k 行规模下的核心价值是
召回完整性，不是绝对延迟。**

1. **召回包含关系（FTS ⊇ LIKE，结构性优势）**

   FTS5 索引三列（content + summary + tags），LIKE 只搜 content + summary。所以 FTS 命中集
   是 LIKE 命中集的严格超集——上表 "FTS-only" 列即是 FTS 独有召回的行数。

   - `Python`：FTS 3403 vs LIKE 2000，FTS 多出 1403 行
     （这些行的 tags 里含 "python"，但 content/summary 不含）
   - `docker`：FTS 1685 vs LIKE 0，**完全结构性**——LIKE 永远找不到 tags-only 的命中
   - 修复前 "DevOps" / "数据库" 显示 FTS 0 vs LIKE 50 的"反常"现象，是 `_backfill_fts`
     LIMIT 500 bug 导致的**假象**，不是 tokenizer 不一致

2. **空命中短路（102.3×）**

   FTS5 在倒排索引里查不到 token 时立即返回空，LIKE 仍需全表扫描 10k 行。这是索引查找 vs
   全表扫描的本质差异，对"查无结果"场景体验提升最直接。

3. **BM25 排序 vs 静态排序**

   FTS5 用 BM25 排序（考虑词频 + 文档长度归一化），LIKE 用静态
   `importance DESC, access_count DESC, created_at DESC`。BM25 在高频查询上能更好
   地把相关结果推前，但这不在本基准的测量范围（需要 labeled relevance 才能评 NDCG）。

### 10k 行规模下延迟差异不显著

- 高频查询（Python / FastAPI / 数据库）FTS vs LIKE 仅 0.9-1.5×，LIKE ~4-5ms
- 多 token OR 甚至 FTS 更慢（0.8×）：FTS MATCH 解析复杂表达式 + rowid JOIN 的开销
  略高于 LIKE 的简单内存扫描
- 10k 行 SQLite LIKE 全表扫描本身很快，用户感知不到 5ms vs 7ms 的差异
- **100k+ 行时延迟优势才会真正显现**（LIKE 是 O(N)，FTS 是 O(log N) + 倒排表扫描）

### v1 误诊的教训

1. **缺索引完整性断言**：v1 没校验 `fts_count == total`，漏检了 `_backfill_fts` 单批
   LIMIT 500 后直接返回的 bug。10k 语料只有 500 行入索引，后续主题查询自然 0 命中
2. **错误归因**：看到 "DevOps" FTS 命中 0 就推断是 jieba tokenizer 不一致，但
   `_segment_for_index()` 用 `cut_for_search` 而 `tokenize_for_search()` 用 `cut`
   的不对称是**良性**的——`cut_for_search` 是 `cut` 的超集（更细粒度切分），
   索引 token 一定 ⊇ 查询 token
3. **`limit=50` 掩盖召回差异**：v1 用 limit=50 对比 FTS vs LIKE 命中数，无法看到
   FTS ⊇ LIKE 的包含关系，误以为两者召回"不一致"

## 结论

1. **FTS5 已接入生产**（PR #2125），作为 `search()` 的首选路径，空命中回退 LIKE
2. **FTS5 的核心价值是召回完整性**：tags 列独有召回 + BM25 排序，不是绝对延迟
3. **空命中短路是 FTS5 的唯一显著延迟优势**（102×），高频查询延迟差异不显著
4. **`_backfill_fts()` 已修复为循环分批**，10000/10000 行全部入索引
5. **v1 误诊的"tokenizer 不一致"实际不存在**：jieba `cut_for_search` ⊇ `cut` 是良性不对称
6. **100k+ 行规模时延迟优势才会显现**，建议未来扩语料重跑

## 后续优化方向

1. **扩语料到 100k / 1M 行**：验证 FTS5 的延迟优势在大规模语料下是否显著
2. **引入 labeled relevance 评测 NDCG**：验证 BM25 排序确实比静态排序更相关
3. **tags-only 查询路由优化**：query 形如单 token + 全英文时可直走 tags 列索引
   （不需要搜 content + summary）

## 复现方法

```bash
# 在 worktree fix-fts5-backfill-loop 中
conda run -n sage-backend \
  pytest backend/tests/bench/test_episodic_fts_vs_like.py -v -s
```

断言：
- fixture 级 `fts_count == 10000`（索引完整性）
- 召回包含关系：所有查询上 `like_ids.issubset(fts_ids)`
- tags-only 查询：`docker` FTS 命中 > 0，LIKE 命中 == 0
- 空命中快路径：`xyznotexist` FTS 加速 ≥ 5×

输出为 markdown 表格（可直接粘贴到本文档更新数据）。

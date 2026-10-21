"""FTS5 vs LIKE 性能基准测试

测量 EpisodicMemory._search_fts() 与 _search_like() 在不同查询选择性下的
**延迟差异**与**召回差异**。

使用方式（手动跑，不进 CI）：
    pytest backend/tests/bench/test_episodic_fts_vs_like.py -v -s

语料：10k 条合成记忆（5 个主题 × 2000 条变体），覆盖中英文混合内容。
查询集：8 个查询覆盖高/低选择性、单/多 token、中英文、空命中、标签命中。
测量：每查询 11 次，去首次 warm-up，取中位数。

断言（三条，全部是 FTS5 的真实价值而非臆测的加速比）：

1. **召回包含关系**：每个查询上 FTS 命中集 ⊇ LIKE 命中集。
   FTS 索引三列（content/summary/tags），LIKE 只搜 content+summary，
   所以 FTS 命中集是 LIKE 命中集的超集——这是 FTS5 的核心价值。
2. **标签召回**：tags-only 查询（"docker"）上 FTS 命中 > 0 而 LIKE 命中 == 0，
   证明标签召回能力差距是结构性的，不是随机的。
3. **空命中快路径**：无结果查询（"xyznotexist"）上 FTS 比 LIKE 快 ≥ 5×，
   这是索引查找 vs 全表扫描的本质差异。

另有 fixture 级断言：FTS 索引必须覆盖**全部** 10k 行。修复前
`_backfill_fts()` 是单批 `LIMIT 500` 后直接返回，只有 500 行入索引，
「DevOps」/「数据库」等后写入主题的查询命中为 0。

不强制断言「≥5× 加速」覆盖多数查询——10k 行规模下 LIKE 全表扫描本身
已足够快（~7-22ms），FTS 的优势不在绝对延迟而在召回覆盖与空命中短路。
语料再上一个数量级（100k+）时延迟优势才会显现。
"""

from __future__ import annotations

import json
import random
import statistics
import time
from typing import Any

import pytest

from backend.data.database import Database
from backend.memory.episodic import EpisodicMemory

# ============================================================================
# 语料生成
# ============================================================================

TOPICS = [
    "Python 编程技巧",
    "FastAPI 开发实践",
    "数据库优化方法",
    "机器学习入门",
    "DevOps 部署流程",
]

TAG_POOL = [
    "python", "fastapi", "sqlite", "ml", "docker", "git", "api",
    "db", "rest", "grpc", "test", "deploy", "monitor", "cache", "redis",
]

SESSION_IDS = [f"session-{i:03d}" for i in range(20)]


def _random_sentence(rng: random.Random, topic: str, idx: int) -> str:
    """生成一条合成记忆内容。"""
    templates = [
        f"{topic}的第{idx}条笔记：今天学到了新的方法和最佳实践",
        f"关于{topic}，记录一下关键步骤和注意事项",
        f"{topic}实践中遇到了一些问题，需要仔细调试和优化",
        f"总结了{topic}的最佳实践，分享给大家参考学习",
        f"深入研究{topic}，发现了很多有趣的细节和原理",
    ]
    return rng.choice(templates)


def generate_corpus(db: Database, n_topics: int = 5, variants_per: int = 2000, seed: int = 42) -> int:
    """插入合成记忆到已有的 memories_episodic 表。返回总条数。"""
    conn = db.get_connection()
    rng = random.Random(seed)
    topics = TOPICS[:n_topics]
    now_ts = int(time.time())
    total = 0

    # 先创建 sessions（外键引用）
    for sid in SESSION_IDS:
        conn.execute(
            "INSERT OR IGNORE INTO sessions (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
            (sid, f"Bench session {sid}", now_ts, now_ts),
        )
    conn.commit()

    for topic in topics:
        for i in range(variants_per):
            mem_id = f"syn-{topic[:2]}-{i:04d}"
            content = _random_sentence(rng, topic, i)
            tags = rng.sample(TAG_POOL, k=rng.randint(1, 4))
            importance = rng.randint(1, 10)
            session_id = rng.choice(SESSION_IDS)

            conn.execute(
                """INSERT INTO memories_episodic
                   (id, session_id, content, summary, memory_type, importance,
                    source, tags, created_at, access_count, is_valid, scope)
                   VALUES (?, ?, ?, ?, 'conversation', ?, 'auto', ?, ?, 0, 1, 'user')""",
                (mem_id, session_id, content, content[:50], importance, json.dumps(tags, ensure_ascii=False), now_ts),
            )
            total += 1

    conn.commit()
    return total


# ============================================================================
# 查询集
# ============================================================================

QUERIES = [
    ("单 token 常见", "Python"),
    ("单 token 稀有", "DevOps"),
    ("英文 token", "FastAPI"),
    ("中文双词", "数据库"),
    ("多 token OR", "Python OR FastAPI"),
    ("长尾短语", "机器学习"),
    ("空命中", "xyznotexist"),
    ("标签命中", "docker"),
]

# 期望 FTS 命中 0 的查询（空命中快路径测速用）
EMPTY_QUERIES = {"xyznotexist"}

# 期望 FTS 有命中但 LIKE 全 0 的查询（tags 列独有，LIKE 搜不到）
TAGS_ONLY_QUERIES = {"docker"}


# ============================================================================
# 基准测试
# ============================================================================


@pytest.fixture(scope="module")
def episodic_with_corpus(tmp_path_factory):
    """创建带 10k 条合成记忆的 EpisodicMemory 实例。"""
    tmp_dir = tmp_path_factory.mktemp("fts_bench")
    db_path = str(tmp_dir / "bench.db")

    # 1. 建表（init_db 创建所有表，包括 memories_episodic）
    db = Database(db_path)
    db.init_db()

    # 2. 插入 10k 合成数据
    total = generate_corpus(db)
    assert total == 10_000, f"Expected 10000, got {total}"

    # 3. 构造 EpisodicMemory（_init_fts 创建 FTS5 表 + 回填数据）
    episodic = EpisodicMemory(db)

    # 校验：全部 10k 行都必须进 FTS 索引
    # （修复前 _backfill_fts 单批 LIMIT 500，只有 500 行入索引）
    conn = db.get_connection()
    fts_count = conn.execute("SELECT COUNT(*) FROM memories_episodic_fts").fetchone()[0]
    assert fts_count == total, (
        f"FTS 索引应包含全部 {total} 行，实际 {fts_count} —— "
        f"_backfill_fts 循环回填可能已回退"
    )

    yield episodic, total

    db.close()


def _benchmark_fn(fn, n_runs: int = 11) -> tuple[float, list[float]]:
    """跑 n_runs 次，返回 (中位数 ms, 所有耗时 ms)。去首次 warm-up。"""
    times: list[float] = []
    for i in range(n_runs):
        t0 = time.perf_counter()
        fn()
        elapsed_ms = (time.perf_counter() - t0) * 1000
        if i > 0:  # 去首次 warm-up
            times.append(elapsed_ms)
    return statistics.median(times), times


class TestEpisodicFtsVsLike:
    """FTS5 vs LIKE 基准测试"""

    def test_fts_faster_than_like(self, episodic_with_corpus, capsys):
        """FTS5 相对 LIKE 的延迟与召回对比。

        断言聚焦 FTS5 的三项真实优势，而非臆测的加速比目标：
        1. 召回包含关系（FTS 命中 ⊇ LIKE 命中）
        2. tags 列独有召回（tags-only 查询 LIKE 必然 0）
        3. 空命中快路径（无结果时 FTS 显著更快）
        """
        episodic, total = episodic_with_corpus

        results: list[dict[str, Any]] = []
        empty_speedups: list[float] = []
        recall_violations: list[str] = []

        for label, query in QUERIES:
            fts_median, _ = _benchmark_fn(
                lambda q=query: episodic._search_fts(q, limit=50)
            )
            like_median, _ = _benchmark_fn(
                lambda q=query: episodic._search_like(q, limit=50)
            )

            # 召回对比（用高 limit 取全量，避免不同排序导致 top-50 子集不同）
            # FTS 用 BM25 排序，LIKE 用 importance DESC；各自的 top-50 自然
            # 是不同集合，但**全量上** FTS ⊇ LIKE（FTS 多索引了 tags 列）
            HIGH_LIMIT = 10_000
            fts_all = episodic._search_fts(query, limit=HIGH_LIMIT)
            like_all = episodic._search_like(query, limit=HIGH_LIMIT)
            fts_ids = {r["id"] for r in fts_all}
            like_ids = {r["id"] for r in like_all}
            if not like_ids.issubset(fts_ids):
                leaked = like_ids - fts_ids
                recall_violations.append(
                    f"{query!r}: LIKE 全量 {len(like_ids)} 条中有 "
                    f"{len(leaked)} 条不在 FTS 全量结果里"
                )

            speedup = like_median / fts_median if fts_median > 0 else float("inf")

            if query in EMPTY_QUERIES:
                empty_speedups.append(speedup)

            results.append({
                "label": label,
                "query": query,
                "fts_median_ms": round(fts_median, 2),
                "like_median_ms": round(like_median, 2),
                "speedup": round(speedup, 1),
                "fts_hits": len(fts_all),
                "like_hits": len(like_all),
                "fts_only": len(fts_ids - like_ids),
            })

        # 打印 markdown 表格
        print(f"\n\n## FTS5 vs LIKE 基准测试（语料 {total} 条）\n")  # noqa: T201
        print("| Query | Label | FTS median (ms) | LIKE median (ms) | Speedup | FTS hits | LIKE hits | FTS-only |")  # noqa: T201
        print("|-------|-------|-----------------|------------------|---------|----------|-----------|----------|")  # noqa: T201
        for r in results:
            print(  # noqa: T201
                f"| {r['query']} | {r['label']} | {r['fts_median_ms']} "
                f"| {r['like_median_ms']} | {r['speedup']}x "
                f"| {r['fts_hits']} | {r['like_hits']} | {r['fts_only']} |"
            )
        print(f"\n**索引完整性: {total}/{total} 行入 FTS 索引**\n")  # noqa: T201

        # 断言 1: 召回包含关系——LIKE 的每一条命中都必须在 FTS 结果里
        assert not recall_violations, (
            "FTS 召回未覆盖 LIKE 召回（不应发生，FTS 索引列是 LIKE 的超集）:\n"
            + "\n".join(recall_violations)
        )

        # 断言 2: tags 列独有召回
        tags_only = next(r for r in results if r["query"] in TAGS_ONLY_QUERIES)
        assert tags_only["fts_hits"] > 0, (
            f"tags-only 查询 {tags_only['query']!r} FTS 应有命中（tags 列已索引）"
        )
        assert tags_only["like_hits"] == 0, (
            f"tags-only 查询 {tags_only['query']!r} LIKE 命中应为 0"
            f"（LIKE 只搜 content+summary，不搜 tags），实际 {tags_only['like_hits']}"
        )

        # 断言 3: 空命中快路径
        assert empty_speedups, "应至少有一个空命中查询用于验证快路径"
        assert min(empty_speedups) >= 5.0, (
            f"空命中查询 FTS 加速仅 {min(empty_speedups):.1f}×，未达 5×"
        )

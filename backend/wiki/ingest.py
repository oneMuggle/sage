"""6 步 CoT Ingest 流程。

实现源文档的 LLM 驱动 ingest：复制 → 缓存检查 → Step1 分析 → Step2 写入 → 嵌入 → 更新缓存。

PR-3 Task 1 将 6 步拆为模块级 helper (``copy_to_raw`` / ``cache_get`` /
``analyze_source`` / ``generate_pages`` / ``embed_pages`` / ``cache_put``),
供同步 ``ingest_source`` (callback 进度) 和流式 ``ingest_source_stream``
(NDJSON 进度) 共享。
"""

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from . import frontmatter, llm_prompts
from .embeddings import EmbeddingConfig, build_embed_request, chunk_markdown, parse_embed_response
from .llm_context import LLMContext
from .models import Analysis, AnalysisConcept, AnalysisEntity, IngestProgress, IngestResult
from .vectorstore import VectorStore

logger = logging.getLogger(__name__)

# 常量
MAX_CONTENT_CHARS = 50_000  # 50KB
DEFAULT_EMBED_DIM = 1536


@dataclass
class IngestConfig:
    """Ingest 配置。"""

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embed_base_url: str
    embed_api_key: str
    embed_model: str
    embed_dim: int = DEFAULT_EMBED_DIM


@dataclass
class CacheEntry:
    """缓存条目。"""

    sha256: str
    wiki_page_path: str
    page_type: str


async def ingest_source(
    config: IngestConfig,
    project_root: Path,
    source_file_path: Path,
    llm_call: Callable[[List[dict], float], Any],
    http_post: Callable[[str, Dict[str, str], dict], Any],
    progress_callback: Optional[Callable[[IngestProgress], None]] = None,
) -> IngestResult:
    """Ingest 源文档。

    Args:
        config: Ingest 配置
        project_root: 项目根目录
        source_file_path: 源文件路径
        llm_call: LLM 调用函数 (messages, temperature) -> response_content
        http_post: HTTP POST 函数 (url, headers, body) -> response_body
        progress_callback: 进度回调

    Returns:
        IngestResult: Ingest 结果
    """

    def _report(stage: str, percent: int, message: Optional[str] = None) -> None:
        if progress_callback:
            progress_callback(IngestProgress(stage=stage, percent=percent, message=message))

    # Step 1: 复制源文件 (10%)
    _report("copy_source", 10, "复制源文件")
    target = copy_to_raw(project_root, source_file_path)
    source_path = f"raw/sources/{target.name}"

    # Step 2: SHA256 缓存检查
    _report("cache_check", 15, "检查缓存")
    cached = cache_get(project_root, target)
    if cached is not None:
        _report("completed", 100, "完成")
        return cached

    # Step 3: LLM 分析 (20%)
    _report("step1_analyze", 20, "Step 1: 分析源文档")
    analysis = await analyze_source(target, llm_call)

    # Step 4 + 5: LLM 写入 + 解析 frontmatter + 落盘 (45% → 70%)
    _report("step2_write", 45, "Step 2: 写入 Wiki 页面")
    wiki_file, page_type, wiki_content = await generate_pages(
        project_root, target, analysis, llm_call
    )
    wiki_page_path = f"wiki/sources/{wiki_file.name}"

    # Step 6: 嵌入 + 存储 (80%)
    _report("embedding", 80, "嵌入 Wiki 页面")
    await embed_pages(project_root, wiki_page_path, wiki_content, config, http_post)

    # Step 7: 更新缓存 (95%)
    _report("finalize", 95, "更新缓存")
    cache_put(project_root, target, wiki_page_path, page_type)

    _report("completed", 100, "完成")

    return IngestResult(
        source_path=source_path,
        wiki_page_path=wiki_page_path,
        page_type=page_type,
    )


# ---------------------------------------------------------------------------
# Module-level helpers (PR-3 Task 1 refactor)
# ---------------------------------------------------------------------------


async def copy_to_raw(project_root: Path, source_file: Path) -> Path:
    """复制源文件到 ``raw/sources/``。返回目标绝对路径。

    幂等:目标已存在则跳过(避免 LLM 重新生成时覆盖用户源文件)。
    """
    filename = source_file.name
    raw_sources_dir = project_root / "raw" / "sources"
    raw_sources_dir.mkdir(parents=True, exist_ok=True)
    dest_path = raw_sources_dir / filename

    if not dest_path.exists():
        dest_path.write_bytes(source_file.read_bytes())

    return dest_path


def cache_get(project_root: Path, target: Path) -> Optional[IngestResult]:
    """SHA256 缓存命中检查。

    命中时返回缓存的 ``IngestResult``(保留上次的 ``wiki_page_path`` + ``page_type``),
    miss 返回 ``None``。
    """
    source_path = f"raw/sources/{target.name}"
    content = target.read_text(encoding="utf-8", errors="ignore")[:MAX_CONTENT_CHARS]
    sha256 = _compute_sha256(content)

    cache = _load_cache(project_root)
    entry = cache.get(source_path)
    if entry is not None and entry.sha256 == sha256:
        return IngestResult(
            source_path=source_path,
            wiki_page_path=entry.wiki_page_path,
            page_type=entry.page_type,
        )
    return None


async def analyze_source(
    target: Path,
    llm_call: Callable[[List[dict], float], Any],
) -> Analysis:
    """Step 1: LLM 分析源内容,返回结构化 ``Analysis``。

    读取源内容、构造 Step1 prompt、调用 LLM、解析 JSON;
    解析失败时退化为空 ``Analysis``(与原 ``_parse_analysis_json`` 行为一致)。
    """
    content = target.read_text(encoding="utf-8", errors="ignore")[:MAX_CONTENT_CHARS]
    step1_prompt = llm_prompts.format_step1_prompt(content)
    messages = [
        {"role": "system", "content": "You are a JSON-only assistant. Output strict JSON."},
        {"role": "user", "content": step1_prompt},
    ]
    analysis_json = await llm_call(messages, temperature=0.0)
    return _parse_analysis_json(analysis_json)


async def generate_pages(
    project_root: Path,
    target: Path,
    analysis: Analysis,
    llm_call: Callable[[List[dict], float], Any],
) -> Tuple[Path, str, str]:
    """Step 2 + 5: LLM 写作 → 解析 frontmatter → 原子落盘到 ``wiki/sources/``。

    Returns:
        (wiki_file_path, page_type, wiki_content) — ``wiki_content`` 供 embed 阶段复用。
    """
    content = target.read_text(encoding="utf-8", errors="ignore")[:MAX_CONTENT_CHARS]
    filename = target.name
    slug = _slugify(filename)
    today = datetime.now(tz=timezone.utc).date().isoformat()  # noqa: DTZ011, UP017
    tags_csv = ", ".join(analysis.tags)
    related_links = " ".join(f"[[{topic}]]" for topic in analysis.related_topics[:8])

    step2_prompt = llm_prompts.format_step2_prompt(
        filename=filename,
        content=content,
        analysis=json.dumps(
            {
                "entities": [
                    {"name": e.name, "type": e.entity_type, "brief": e.brief}
                    for e in analysis.entities
                ],
                "concepts": [{"name": c.name, "brief": c.brief} for c in analysis.concepts],
                "tags": analysis.tags,
                "related_topics": analysis.related_topics,
                "summary": analysis.summary,
            },
            ensure_ascii=False,
        ),
        tags_csv=tags_csv,
        related_links=related_links,
        today=today,
    )

    messages = [{"role": "user", "content": step2_prompt}]
    raw_wiki_content = await llm_call(messages, temperature=0.3)

    # 解析 frontmatter + 序列化
    parsed = frontmatter.parse(raw_wiki_content)
    page_type = parsed.frontmatter.page_type or "source"
    wiki_content = frontmatter.serialize(parsed)

    # 原子写入 wiki 文件
    wiki_sources_dir = project_root / "wiki" / "sources"
    wiki_sources_dir.mkdir(parents=True, exist_ok=True)
    wiki_file = project_root / "wiki" / "sources" / f"{slug}.md"

    tmp_file = wiki_file.with_suffix(".md.tmp")
    tmp_file.write_text(wiki_content, encoding="utf-8")
    tmp_file.replace(wiki_file)

    return wiki_file, page_type, wiki_content


async def embed_pages(
    project_root: Path,
    wiki_page_path: str,
    wiki_content: str,
    config: IngestConfig,
    http_post: Callable[[str, Dict[str, str], dict], Any],
) -> None:
    """Step 6: 分块 → 调用 embed HTTP → upsert 到 VectorStore。

    无 chunk 时跳过(空文档场景)。
    """
    chunks = chunk_markdown(wiki_content, target_chunk_size=500)
    if not chunks:
        return

    embed_req = build_embed_request(
        EmbeddingConfig(
            base_url=config.embed_base_url,
            api_key=config.embed_api_key,
            model=config.embed_model,
            dim=config.embed_dim,
        ),
        chunks,
    )

    embed_response = await http_post(embed_req.url, embed_req.headers, embed_req.body)
    vectors = parse_embed_response(embed_response, config.embed_dim)

    vector_store = VectorStore.open(project_root, config.embed_dim)
    vector_store.upsert_chunks(
        wiki_page_path,
        [(idx, chunk, vec) for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=False))],
    )


def cache_put(
    project_root: Path,
    target: Path,
    wiki_page_path: str,
    page_type: str,
) -> None:
    """Step 7: 写入缓存条目(原子保存 ingest-cache.json)。

    同一 source_path 的旧条目会被覆盖(支持重新 ingest)。
    """
    source_path = f"raw/sources/{target.name}"
    content = target.read_text(encoding="utf-8", errors="ignore")[:MAX_CONTENT_CHARS]
    sha256 = _compute_sha256(content)

    cache = _load_cache(project_root)
    cache[source_path] = CacheEntry(
        sha256=sha256,
        wiki_page_path=wiki_page_path,
        page_type=page_type,
    )
    _save_cache(project_root, cache)


# ---------------------------------------------------------------------------
# Streaming variant (PR-3 Task 1)
# ---------------------------------------------------------------------------


async def ingest_source_stream(
    config: IngestConfig,
    project_root: Path,
    source_file: Path,
    ctx: LLMContext,
) -> AsyncIterator[bytes]:
    """Streaming variant of :func:`ingest_source`.

    Yields NDJSON progress lines(``\\n``-terminated UTF-8):

    .. code-block:: json

        {"event":"progress","data":{"stage":"...","percent":N,"message":"..."}}

    Stages(必须与 ``src/widgets/wiki/WikiIngestProgress.tsx::STAGE_LABELS`` 完全一致):

        started → copy_source → step1_analyze → step2_write → embedding → completed

    ``failed`` 阶段在异常路径发出(``percent=0``),随后 ``raise`` 让上层 FastAPI
    关闭流。
    """

    def emit(stage: str, percent: int, message: Optional[str] = None) -> bytes:
        return (
            json.dumps(
                {
                    "event": "progress",
                    "data": {"stage": stage, "percent": percent, "message": message},
                },
                ensure_ascii=False,
            )
            + "\n"
        ).encode("utf-8")

    try:
        yield emit("started", 0, "开始导入")

        target = await copy_to_raw(project_root, source_file)
        yield emit("copy_source", 10, f"复制到 {target.name}")

        cached = cache_get(project_root, target)
        if cached is not None:
            yield emit("completed", 100, f"缓存命中: {cached.wiki_page_path}")
            return

        yield emit("step1_analyze", 20, "LLM 分析中...")
        analysis = await analyze_source(target, ctx.llm_call)

        yield emit("step2_write", 50, "LLM 写作中...")
        wiki_file, page_type, wiki_content = await generate_pages(
            project_root, target, analysis, ctx.llm_call
        )
        wiki_page_path = f"wiki/sources/{wiki_file.name}"

        yield emit("embedding", 80, f"嵌入 {wiki_file.name}")
        await embed_pages(project_root, wiki_page_path, wiki_content, config, ctx.http_post)

        cache_put(project_root, target, wiki_page_path, page_type)
        yield emit("completed", 100, f"导入完成: {wiki_file.name}")
    except Exception as e:
        logger.exception("ingest_source_stream 失败")
        yield emit("failed", 0, str(e))
        raise


def _compute_sha256(content: str) -> str:
    """计算 SHA256。"""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _slugify(filename: str) -> str:
    """将文件名转换为 slug。"""
    # 去除扩展名
    name = re.sub(r"\.(md|txt|markdown)$", "", filename, flags=re.IGNORECASE)
    # 转小写，非字母数字 → -
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug or "untitled"


def _parse_analysis_json(content: str) -> Analysis:
    """解析 LLM 输出的分析 JSON。"""
    # 尝试提取 JSON（处理 ```json 代码块）
    content = content.strip()

    # 查找第一个 { 和最后一个 }
    start = content.find("{")
    end = content.rfind("}")

    json_str = content[start : end + 1] if start != -1 and end != -1 else content

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        # 解析失败，返回空分析
        return Analysis(entities=[], concepts=[], tags=[], related_topics=[], summary="")

    entities = [
        AnalysisEntity(
            name=e.get("name", ""),
            entity_type=e.get("type", ""),
            brief=e.get("brief", ""),
        )
        for e in data.get("entities", [])
    ]

    concepts = [
        AnalysisConcept(name=c.get("name", ""), brief=c.get("brief", ""))
        for c in data.get("concepts", [])
    ]

    return Analysis(
        entities=entities,
        concepts=concepts,
        tags=data.get("tags", []),
        related_topics=data.get("related_topics", []),
        summary=data.get("summary", ""),
    )


def _load_cache(project_root: Path) -> Dict[str, CacheEntry]:
    """加载 ingest 缓存。"""
    cache_file = project_root / ".llm-wiki" / "ingest-cache.json"

    if not cache_file.exists():
        return {}

    data = json.loads(cache_file.read_text(encoding="utf-8"))
    return {
        path: CacheEntry(
            sha256=entry["sha256"],
            wiki_page_path=entry["wiki_page_path"],
            page_type=entry["page_type"],
        )
        for path, entry in data.items()
    }


def _save_cache(project_root: Path, cache: Dict[str, CacheEntry]) -> None:
    """保存 ingest 缓存。"""
    cache_file = project_root / ".llm-wiki" / "ingest-cache.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        path: {
            "sha256": entry.sha256,
            "wiki_page_path": entry.wiki_page_path,
            "page_type": entry.page_type,
        }
        for path, entry in cache.items()
    }

    tmp_file = cache_file.with_suffix(".json.tmp")
    tmp_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp_file.replace(cache_file)

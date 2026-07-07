"""6 步 CoT Ingest 流程。

实现源文档的 LLM 驱动 ingest：复制 → 缓存检查 → Step1 分析 → Step2 写入 → 嵌入 → 更新缓存。
"""
from typing import Dict, List, Optional

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import frontmatter, llm_prompts
from .embeddings import EmbeddingConfig, build_embed_request, chunk_markdown, parse_embed_response
from .models import Analysis, AnalysisConcept, AnalysisEntity, IngestProgress, IngestResult
from .vectorstore import VectorStore

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
    filename = source_file_path.name
    raw_sources_dir = project_root / "raw" / "sources"
    raw_sources_dir.mkdir(parents=True, exist_ok=True)
    dest_path = raw_sources_dir / filename

    if not dest_path.exists():
        dest_path.write_bytes(source_file_path.read_bytes())

    source_path = f"raw/sources/{filename}"

    # Step 2: SHA256 缓存检查
    _report("cache_check", 15, "检查缓存")
    content = dest_path.read_text(encoding="utf-8", errors="ignore")[:MAX_CONTENT_CHARS]
    sha256 = _compute_sha256(content)

    cache = _load_cache(project_root)
    if source_path in cache and cache[source_path].sha256 == sha256:
        # 缓存命中
        return IngestResult(
            source_path=source_path,
            wiki_page_path=cache[source_path].wiki_page_path,
            page_type=cache[source_path].page_type,
        )

    # Step 3: LLM 分析 (20% → 40%)
    _report("step1_analyze", 20, "Step 1: 分析源文档")
    step1_prompt = llm_prompts.format_step1_prompt(content)
    messages = [
        {"role": "system", "content": "You are a JSON-only assistant. Output strict JSON."},
        {"role": "user", "content": step1_prompt},
    ]

    analysis_json = await llm_call(messages, temperature=0.0)
    analysis = _parse_analysis_json(analysis_json)

    # Step 4: LLM 写入 (45% → 70%)
    _report("step2_write", 45, "Step 2: 写入 Wiki 页面")
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
    wiki_content = await llm_call(messages, temperature=0.3)

    # Step 5: 解析 frontmatter + 写入 (70%)
    _report("finalize", 70, "写入 Wiki 文件")
    parsed = frontmatter.parse(wiki_content)
    page_type = parsed.frontmatter.page_type or "source"
    wiki_content = frontmatter.serialize(parsed)

    wiki_sources_dir = project_root / "wiki" / "sources"
    wiki_sources_dir.mkdir(parents=True, exist_ok=True)
    wiki_page_path = f"wiki/sources/{slug}.md"
    wiki_file = project_root / wiki_page_path

    # 原子写入
    tmp_file = wiki_file.with_suffix(".md.tmp")
    tmp_file.write_text(wiki_content, encoding="utf-8")
    tmp_file.replace(wiki_file)

    # Step 6: 嵌入 + 存储 (80% → 90%)
    _report("embedding", 80, "嵌入 Wiki 页面")
    chunks = chunk_markdown(wiki_content, target_chunk_size=500)

    if chunks:
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

        # 存储向量
        vector_store = VectorStore.open(project_root, config.embed_dim)
        vector_store.upsert_chunks(
            wiki_page_path,
            [
                (idx, chunk, vec)
                for idx, (chunk, vec) in enumerate(zip(chunks, vectors, strict=False))
            ],
        )

    # Step 7: 更新缓存 (95%)
    _report("finalize", 95, "更新缓存")
    cache[source_path] = CacheEntry(
        sha256=sha256,
        wiki_page_path=wiki_page_path,
        page_type=page_type,
    )
    _save_cache(project_root, cache)

    _report("completed", 100, "完成")

    return IngestResult(
        source_path=source_path,
        wiki_page_path=wiki_page_path,
        page_type=page_type,
    )


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

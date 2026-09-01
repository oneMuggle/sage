"""6 步 CoT Ingest 流程。

实现源文档的 LLM 驱动 ingest：复制 → 缓存检查 → Step1 分析 → Step2 写入 → 嵌入 → 更新缓存。

PR-3 Task 1 将 6 步拆为模块级 helper (``copy_to_raw`` / ``cache_get`` /
``analyze_source`` / ``generate_pages`` / ``embed_pages`` / ``cache_put``),
供同步 ``ingest_source`` (callback 进度) 和流式 ``ingest_source_stream``
(NDJSON 进度) 共享。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import stat
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Tuple

from . import frontmatter, llm_prompts
from .embeddings import EmbeddingConfig, build_embed_request, chunk_markdown, parse_embed_response
from .extract import (
    MAX_FILE_BYTES,
    FileTooLargeError,
    extract_text_for_ingest,
)
from .files import (
    _write_bytes_fd,
    secure_atomic_write_file,
    secure_delete_path,
    secure_open_file,
    secure_read_file,
    secure_read_file_bounded,
    secure_write_temp_bytes,
)
from .llm_context import LLMContext
from .models import Analysis, AnalysisConcept, AnalysisEntity, IngestProgress, IngestResult
from .vectorstore import VectorStore

logger = logging.getLogger(__name__)

INGEST_STREAM_ERROR_CODE = "wiki_ingest_failed"
INGEST_STREAM_ERROR_MESSAGE = "Wiki 导入失败"

# 常量
MAX_CONTENT_CHARS = 50_000  # 50KB
DEFAULT_EMBED_DIM = 1536


def _validated_logical_filename(filename: str) -> str:
    """Validate a leaf name used for derived ingest paths."""
    if not filename or filename in {".", ".."} or os.sep in filename or (
        os.altsep and os.altsep in filename
    ):
        raise ValueError("源文件名无效")
    return filename


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
    logical_filename: Optional[str] = None,
    source_content: Optional[bytes] = None,
    processed_content: Optional[str] = None,
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

    source_name = _validated_logical_filename(logical_filename or source_file_path.name)
    if source_content is None:
        source_content = secure_read_file_bounded(project_root, source_file_path, MAX_FILE_BYTES)
    elif len(source_content) > MAX_FILE_BYTES:
        raise FileTooLargeError(source_file_path, len(source_content), MAX_FILE_BYTES)

    # Step 1: 复制源文件 (10%)
    _report("copy_source", 10, "复制源文件")
    target = await copy_to_raw(
        project_root,
        source_file_path,
        logical_filename=source_name,
        source_content=source_content,
    )
    source_path = f"raw/sources/{source_name}"

    # Step 2: SHA256 缓存检查
    _report("cache_check", 15, "检查缓存")
    cached = cache_get(
        project_root,
        target,
        source_name=source_name,
        source_content=source_content,
    )
    if cached is not None:
        _report("completed", 100, "完成")
        return cached

    _report("step1_analyze", 20, "Step 1: 分析源文档")
    analysis = await analyze_source(
        target,
        llm_call,
        project_root,
        source_content=source_content,
        processed_content=processed_content,
    )

    # Step 4 + 5: LLM 写入 + 解析 frontmatter + 落盘 (45% → 70%)
    _report("step2_write", 45, "Step 2: 写入 Wiki 页面")
    wiki_file, page_type, wiki_content = await generate_pages(
        project_root,
        target,
        analysis,
        llm_call,
        source_name=source_name,
        source_content=source_content,
        processed_content=processed_content,
    )
    wiki_page_path = f"wiki/sources/{wiki_file.name}"

    # Step 6: 嵌入 + 存储 (80%)
    _report("embedding", 80, "嵌入 Wiki 页面")
    await embed_pages(project_root, wiki_page_path, wiki_content, config, http_post)

    # Step 7: 更新缓存 (95%)
    _report("finalize", 95, "更新缓存")
    cache_put(
        project_root,
        target,
        wiki_page_path,
        page_type,
        source_name=source_name,
        source_content=source_content,
    )

    _report("completed", 100, "完成")

    return IngestResult(
        source_path=source_path,
        wiki_page_path=wiki_page_path,
        page_type=page_type,
    )


# ---------------------------------------------------------------------------
# Module-level helpers (PR-3 Task 1 refactor)
# ---------------------------------------------------------------------------


async def copy_to_raw(
    project_root: Path,
    source_file: Path,
    logical_filename: Optional[str] = None,
    source_content: Optional[bytes] = None,
) -> Path:
    """复制源文件到 ``raw/sources/``，并拒绝 symlink/junction 越界。

    POSIX 上所有目标目录都通过 ``O_NOFOLLOW`` 的目录 fd 打开，目标文件以
    ``O_EXCL`` 创建，避免检查后再按路径写入的 TOCTOU。已有普通文件保持
    ingest 的幂等语义；已有符号链接（包括 broken link）一律失败。
    Windows 使用 ``lstat``、``O_EXCL`` 和 ``O_NOFOLLOW``（若平台提供）保护
    叶文件；Windows junction/目录替换无法由 Python 的标准 ``os.open`` 完整
    锁定，因此检测到平台缺少必要的 no-follow 能力时 fail-closed。
    """
    filename = _validated_logical_filename(logical_filename or source_file.name)
    try:
        source_root = project_root
        source_file.relative_to(project_root)
    except ValueError:
        # Keep the legacy helper usable for callers that provide an absolute
        # source outside the project; HTTP routes authorize containment first.
        source_root = source_file.parent
    source_content_provided = source_content is not None
    payload = source_content if source_content is not None else secure_read_file(source_root, source_file)
    raw_sources_dir = project_root / "raw" / "sources"
    dest_path = raw_sources_dir / filename

    if os.name == "posix":
        return _copy_to_raw_posix(project_root, filename, payload, dest_path, source_content_provided)
    return _copy_to_raw_windows(project_root, filename, payload, dest_path, source_content_provided)


def _directory_flags() -> int:
    return os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)


def _open_directory_child(parent_fd: int, name: str) -> int:
    """Open/create one directory component without following symlinks (POSIX)."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(name, _directory_flags() | nofollow, dir_fd=parent_fd)
    except FileNotFoundError:
        os.mkdir(name, 0o700, dir_fd=parent_fd)  # noqa: PTH102 — dirfd-relative mkdir is required
        return os.open(name, _directory_flags() | nofollow, dir_fd=parent_fd)


def _read_existing_raw_content(parent_fd: int, filename: str, target: Path) -> bytes:
    """Read an existing regular raw file through its held dirfd boundary."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(filename, os.O_RDONLY | nofollow, dir_fd=parent_fd)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError(f"Refusing non-file ingest target: {target}")
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        return b"".join(chunks)
    finally:
        os.close(fd)


def _copy_to_raw_posix(
    project_root: Path,
    filename: str,
    payload: bytes,
    dest_path: Path,
    source_content_provided: bool = False,
) -> Path:
    """Copy using a stable, no-follow directory-fd chain on POSIX."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        raise OSError("安全 ingest 需要 POSIX O_NOFOLLOW")
    root_fd = os.open(str(project_root), _directory_flags() | nofollow)
    try:
        raw_fd = _open_directory_child(root_fd, "raw")
        try:
            sources_fd = _open_directory_child(raw_fd, "sources")
            try:
                try:
                    fd = os.open(
                        filename,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                        0o600,
                        dir_fd=sources_fd,
                    )
                except FileExistsError:
                    # Do not resolve/read the existing path: lstat distinguishes a
                    # broken link from the ordinary file used by idempotent ingest.
                    mode = os.stat(filename, dir_fd=sources_fd, follow_symlinks=False).st_mode  # noqa: PTH116 — no-follow dirfd stat is required
                    if stat.S_ISLNK(mode):
                        raise OSError(f"Refusing ingest target symlink: {dest_path}")
                    if not stat.S_ISREG(mode):
                        raise OSError(f"Refusing non-file ingest target: {dest_path}")
                    if source_content_provided:
                        existing = _read_existing_raw_content(
                            sources_fd, filename, dest_path
                        )
                        if existing != payload:
                            raise ValueError(
                                "已有源文件内容与本次 ingest 输入不一致"
                            )
                    return dest_path
                _write_bytes_fd(fd, payload)
            finally:
                os.close(sources_fd)
        finally:
            os.close(raw_fd)
    finally:
        os.close(root_fd)
    return dest_path


def _copy_to_raw_windows(
    project_root: Path,
    filename: str,
    payload: bytes,
    dest_path: Path,
    source_content_provided: bool = False,
) -> Path:
    """Best-effort Windows leaf protection; reject unsupported no-follow APIs."""
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if not nofollow:
        # O_EXCL protects creation races, but cannot protect a directory junction
        # replacement. Never silently claim this is equivalent to POSIX safety.
        raise OSError("Windows 安全 ingest 不支持可靠的 no-follow 目录打开")
    raw_sources_dir = project_root / "raw" / "sources"
    for directory in (project_root, project_root / "raw", raw_sources_dir):
        mode = os.lstat(directory).st_mode if directory.exists() else None
        if mode is not None and stat.S_ISLNK(mode):
            raise OSError(f"Refusing ingest directory symlink: {directory}")
    raw_sources_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(
            str(dest_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow, 0o600
        )
    except FileExistsError:
        mode = os.lstat(dest_path).st_mode
        if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
            raise OSError(f"Refusing non-file ingest target: {dest_path}")
        return dest_path
    with os.fdopen(fd, "wb") as stream:
        stream.write(payload)
    return dest_path


def _bounded_source_content(
    project_root: Path, target: Path, source_content: Optional[bytes]
) -> bytes:
    """Obtain a stable source snapshot without exceeding the ingest cap."""
    if source_content is not None:
        if len(source_content) > MAX_FILE_BYTES:
            raise FileTooLargeError(target, len(source_content), MAX_FILE_BYTES)
        return source_content
    return secure_read_file_bounded(project_root, target, MAX_FILE_BYTES)


def _read_source_content(
    project_root: Path, target: Path, source_content: Optional[bytes] = None
) -> str:
    """Read immutable source bytes, using a held fd only for binary parsers."""
    payload = _bounded_source_content(project_root, target, source_content)
    suffix = target.suffix.lower()
    if suffix in {".md", ".markdown", ".txt"}:
        return payload.decode("utf-8", errors="ignore")

    snapshot = secure_write_temp_bytes(project_root, project_root / ".llm-wiki", suffix, payload)
    fd = -1
    try:
        fd = secure_open_file(project_root, snapshot)
        return extract_text_for_ingest(
            snapshot,
            opened_fd=fd,
            max_file_bytes=MAX_FILE_BYTES,
        )
    finally:
        if fd != -1:
            os.close(fd)
        with suppress(OSError):
            secure_delete_path(project_root, snapshot)


def _source_bytes_for_cache(
    project_root: Path, target: Path, source_content: Optional[bytes]
) -> bytes:
    """Return the complete bounded raw bytes used as cache identity."""
    if source_content is not None:
        if len(source_content) > MAX_FILE_BYTES:
            raise FileTooLargeError(target, len(source_content), MAX_FILE_BYTES)
        return source_content
    return secure_read_file_bounded(project_root, target, MAX_FILE_BYTES)


def _compute_source_sha256(content: bytes) -> str:
    """Compute cache identity from raw source bytes, never decoded text."""
    return hashlib.sha256(content).hexdigest()


def cache_get(
    project_root: Path,
    target: Path,
    source_name: Optional[str] = None,
    source_content: Optional[bytes] = None,
) -> Optional[IngestResult]:
    """SHA256 缓存命中检查。

    命中时返回缓存的 ``IngestResult``(保留上次的 ``wiki_page_path`` + ``page_type``),
    miss 返回 ``None``。
    """
    source_name = _validated_logical_filename(source_name or target.name)
    source_path = f"raw/sources/{source_name}"
    source_bytes = _source_bytes_for_cache(project_root, target, source_content)
    sha256 = _compute_source_sha256(source_bytes)

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
    project_root: Optional[Path] = None,
    source_content: Optional[bytes] = None,
    processed_content: Optional[str] = None,
) -> Analysis:
    """Step 1: LLM 分析源内容,返回结构化 ``Analysis``。

    读取源内容、构造 Step1 prompt、调用 LLM、解析 JSON;
    解析失败时退化为空 ``Analysis``(与原 ``_parse_analysis_json`` 行为一致)。
    """
    if project_root is None:
        content = extract_text_for_ingest(target)[:MAX_CONTENT_CHARS]
    elif processed_content is not None:
        content = processed_content[:MAX_CONTENT_CHARS]
    else:
        content = _read_source_content(
            project_root, target, source_content=source_content
        )[:MAX_CONTENT_CHARS]
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
    source_name: Optional[str] = None,
    source_content: Optional[bytes] = None,
    processed_content: Optional[str] = None,
) -> Tuple[Path, str, str]:
    """Step 2 + 5: LLM 写作 → 解析 frontmatter → 原子落盘到 ``wiki/sources/``。

    Returns:
        (wiki_file_path, page_type, wiki_content) — ``wiki_content`` 供 embed 阶段复用。
    """
    content = (
        processed_content
        if processed_content is not None
        else _read_source_content(project_root, target, source_content=source_content)
    )[:MAX_CONTENT_CHARS]
    filename = _validated_logical_filename(source_name or target.name)
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
    wiki_file = project_root / "wiki" / "sources" / f"{slug}.md"
    secure_atomic_write_file(project_root, wiki_file, wiki_content)

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
        [(idx, chunk, vec) for idx, (chunk, vec) in enumerate(zip(chunks, vectors))],  # noqa: B905 — strict keyword is unavailable on Python 3.8
    )


def cache_put(
    project_root: Path,
    target: Path,
    wiki_page_path: str,
    page_type: str,
    source_name: Optional[str] = None,
    source_content: Optional[bytes] = None,
) -> None:
    """Step 7: 写入缓存条目(原子保存 ingest-cache.json)。

    同一 source_path 的旧条目会被覆盖(支持重新 ingest)。
    """
    source_name = _validated_logical_filename(source_name or target.name)
    source_path = f"raw/sources/{source_name}"
    source_bytes = _source_bytes_for_cache(project_root, target, source_content)
    sha256 = _compute_source_sha256(source_bytes)

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
    logical_filename: Optional[str] = None,
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

    def emit(stage: str, percent: int, message: Optional[object] = None) -> bytes:
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

        source_name = _validated_logical_filename(logical_filename or source_file.name)
        source_content = secure_read_file_bounded(
            project_root, source_file, MAX_FILE_BYTES
        )
        target = await copy_to_raw(
            project_root,
            source_file,
            logical_filename=source_name,
            source_content=source_content,
        )
        yield emit("copy_source", 10, f"复制到 {source_name}")

        cached = cache_get(
            project_root,
            target,
            source_name=source_name,
            source_content=source_content,
        )
        if cached is not None:
            yield emit("completed", 100, f"缓存命中: {cached.wiki_page_path}")
            return

        yield emit("step1_analyze", 20, "LLM 分析中...")
        analysis = await analyze_source(
            target, ctx.llm_call, project_root, source_content=source_content
        )

        yield emit("step2_write", 50, "LLM 写作中...")
        wiki_file, page_type, wiki_content = await generate_pages(
            project_root,
            target,
            analysis,
            ctx.llm_call,
            source_name=source_name,
            source_content=source_content,
        )
        wiki_page_path = f"wiki/sources/{wiki_file.name}"

        yield emit("embedding", 80, f"嵌入 {wiki_file.name}")
        await embed_pages(project_root, wiki_page_path, wiki_content, config, ctx.http_post)

        cache_put(
            project_root,
            target,
            wiki_page_path,
            page_type,
            source_name=source_name,
            source_content=source_content,
        )
        yield emit("completed", 100, f"导入完成: {wiki_file.name}")
    except Exception as e:
        logger.error("ingest_source_stream failed: error_type=%s", type(e).__name__)
        yield emit(
            "failed",
            0,
            {"code": INGEST_STREAM_ERROR_CODE, "message": INGEST_STREAM_ERROR_MESSAGE},
        )
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
    try:
        data = json.loads(secure_read_file(project_root, cache_file).decode("utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError):
        logger.warning("加载 ingest 缓存失败: error_type=cache_read_failure")
        return {}
    if not isinstance(data, dict):
        return {}
    try:
        return {
            path: CacheEntry(
                sha256=entry["sha256"],
                wiki_page_path=entry["wiki_page_path"],
                page_type=entry["page_type"],
            )
            for path, entry in data.items()
        }
    except (KeyError, TypeError):
        logger.warning("加载 ingest 缓存失败: error_type=cache_schema_failure")
        return {}


def _save_cache(project_root: Path, cache: Dict[str, CacheEntry]) -> None:
    """保存 ingest 缓存。"""
    data = {
        path: {
            "sha256": entry.sha256,
            "wiki_page_path": entry.wiki_page_path,
            "page_type": entry.page_type,
        }
        for path, entry in cache.items()
    }

    secure_atomic_write_file(
        project_root,
        project_root / ".llm-wiki" / "ingest-cache.json",
        json.dumps(data, ensure_ascii=False, indent=2),
    )

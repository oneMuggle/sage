"""RAG 聊天流程。

实现混合检索（token + 向量）→ RRF 融合 → LLM 综合回答。
"""

import json
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

from . import llm_prompts
from .context_budget import ContextBudget, truncate_pages
from .embeddings import EmbeddingConfig, build_embed_request, parse_embed_response
from .llm_context import LLMContext
from .models import RetrievalStats, WikiChatOutcome
from .rrf import rrf_fuse
from .search import search_wiki
from .vectorstore import VectorStore

# 常量
DEFAULT_EMBED_DIM = 1536
RETRIEVAL_LIMIT = 20
FINAL_TOP_K = 5

logger = logging.getLogger(__name__)


@dataclass
class ChatConfig:
    """聊天配置。"""

    llm_base_url: str
    llm_api_key: str
    llm_model: str
    embed_base_url: str
    embed_api_key: str
    embed_model: str
    embed_dim: int = DEFAULT_EMBED_DIM
    max_tokens: int = 4096


async def chat_with_wiki(
    config: ChatConfig,
    project_root: Path,
    query: str,
    llm_call: Callable[[List[dict], float], Any],
    http_post: Callable[[str, Dict[str, str], dict], Any],
) -> WikiChatOutcome:
    """与 Wiki 聊天（非流式）。

    Args:
        config: 聊天配置
        project_root: 项目根目录
        query: 用户查询
        llm_call: LLM 调用函数
        http_post: HTTP POST 函数

    Returns:
        WikiChatOutcome: 聊天结果
    """
    # 构建聊天上下文
    context, citations, stats = await _build_chat_context(config, project_root, query, http_post)

    if not citations:
        return WikiChatOutcome(
            answer="未在 wiki 中找到相关内容",
            citations=[],
            stats=stats,
        )

    # 构建 prompt (与流式路径复用同一 helper, 保证 prompt 完全一致)
    ContextBudget.compute(config.max_tokens)
    messages = _build_rag_messages(query, context)

    # 调用 LLM
    answer = await llm_call(messages, temperature=0.3)

    return WikiChatOutcome(
        answer=answer,
        citations=citations,
        stats=stats,
    )


async def _build_chat_context(
    config: ChatConfig,
    project_root: Path,
    query: str,
    http_post: Callable[[str, Dict[str, str], dict], Any],
) -> Tuple[str, List[str], RetrievalStats]:
    """构建聊天上下文。

    Returns:
        tuple[str, list[str], RetrievalStats]: (context, citations, stats)
    """
    # Step 1: Token 搜索
    token_results = search_wiki(project_root, query, limit=RETRIEVAL_LIMIT)
    token_paths = [r.path for r in token_results.results]

    # Step 2: 向量搜索
    vector_paths = []
    try:
        embed_req = build_embed_request(
            EmbeddingConfig(
                base_url=config.embed_base_url,
                api_key=config.embed_api_key,
                model=config.embed_model,
                dim=config.embed_dim,
            ),
            [query],
        )

        embed_response = await http_post(embed_req.url, embed_req.headers, embed_req.body)
        query_vec = parse_embed_response(embed_response, config.embed_dim)[0]

        vector_store = VectorStore.open(project_root, config.embed_dim)
        vector_hits = vector_store.search(query_vec, limit=RETRIEVAL_LIMIT)
        vector_paths = [hit.page_path for hit in vector_hits]
    except Exception:
        # 向量搜索失败，仅使用 token 搜索
        pass

    # Step 3: RRF 融合
    fused = rrf_fuse(token_paths, vector_paths)
    fused_paths = [path for path, _ in fused[:FINAL_TOP_K]]

    # Step 4: 读取 Wiki 页面
    pages = []
    citations = []

    for path in fused_paths:
        wiki_file = project_root / path
        if wiki_file.exists():
            content = wiki_file.read_text(encoding="utf-8")
            pages.append((path, content))
            citations.append(path)

    # Step 5: Token 预算 + 截断
    budget = ContextBudget.compute(config.max_tokens)
    chunks = truncate_pages(pages, budget)

    # 构建上下文字符串
    context_parts = []
    total_tokens = 0

    for chunk in chunks:
        context_parts.append(f"\n--- 文件: {chunk.page_path} ---\n{chunk.content}\n")
        total_tokens += len(chunk.content) // 3

    context = "".join(context_parts)

    stats = RetrievalStats(
        token_hits=len(token_paths),
        vector_hits=len(vector_paths),
        fused_top_score=fused[0][1] if fused else 0.0,
        total_context_tokens=total_tokens,
    )

    return context, citations, stats


def _build_rag_messages(query: str, context: str) -> List[Dict[str, str]]:
    """构建 RAG prompt messages (system + user)。

    抽出供 ``chat_with_wiki`` 与 ``chat_with_wiki_stream`` 复用,
    保证非流式和流式路径使用完全一致的 prompt。
    """
    system_prompt = llm_prompts.format_rag_system(context)
    user_prompt = llm_prompts.format_rag_user_message(query)
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


async def chat_with_wiki_stream(
    config: ChatConfig,
    project_root: Path,
    query: str,
    ctx: LLMContext,
    temperature: float = 0.3,
) -> AsyncIterator[bytes]:
    """与 Wiki 聊天的流式变体 (NDJSON)。

    与 ``chat_with_wiki`` 共用 ``_build_chat_context`` (检索 + RRF + 截断),
    并复用 ``_build_rag_messages`` (prompt 构造), 仅把 LLM 调用从
    ``ctx.llm_call`` 替换为 ``ctx.llm_stream_call``。

    每条 yield 是 UTF-8 编码的 NDJSON 行, 以 ``\\n`` 结尾:

    - ``{"event": "chunk", "data": "<text>"}`` —— 每个 LLM delta 一条
    - ``{"event": "done", "data": {"citations": ["wiki/a.md", ...]}}`` —— 流末尾
    - ``{"event": "error", "data": "<msg>"}`` —— 仅在异常路径出现

    异常时先 yield 一条 error 行, 然后 re-raise, 让 FastAPI 关掉连接。
    """
    try:
        # 1. 检索 (与非流式完全相同)
        context, citations, _stats = await _build_chat_context(
            config,
            project_root,
            query,
            ctx.http_post,
        )

        if not citations:
            # 没有命中页面, 直接 done (无 chunk)。
            done_line = (
                json.dumps(
                    {"event": "done", "data": {"citations": []}},
                    ensure_ascii=False,
                )
                + "\n"
            )
            yield done_line.encode("utf-8")
            return

        # 2. 构建 prompt (与非流式完全相同)
        ContextBudget.compute(config.max_tokens)
        messages = _build_rag_messages(query, context)

        # 3. 流式调用 LLM
        async for delta in ctx.llm_stream_call(messages, temperature):
            chunk_line = (
                json.dumps(
                    {"event": "chunk", "data": delta},
                    ensure_ascii=False,
                )
                + "\n"
            )
            yield chunk_line.encode("utf-8")

        # 4. done 行带 citations
        done_line = (
            json.dumps(
                {"event": "done", "data": {"citations": citations}},
                ensure_ascii=False,
            )
            + "\n"
        )
        yield done_line.encode("utf-8")
    except Exception as e:
        logger.exception("chat_with_wiki_stream 失败")
        err_line = (
            json.dumps(
                {"event": "error", "data": str(e)},
                ensure_ascii=False,
            )
            + "\n"
        )
        yield err_line.encode("utf-8")
        raise

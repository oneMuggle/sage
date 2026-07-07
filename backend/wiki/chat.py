"""RAG 聊天流程。

实现混合检索（token + 向量）→ RRF 融合 → LLM 综合回答。
"""
from typing import Dict, List, Tuple

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import llm_prompts
from .context_budget import ContextBudget, truncate_pages
from .embeddings import EmbeddingConfig, build_embed_request, parse_embed_response
from .models import RetrievalStats, WikiChatOutcome
from .rrf import rrf_fuse
from .search import search_wiki
from .vectorstore import VectorStore

# 常量
DEFAULT_EMBED_DIM = 1536
RETRIEVAL_LIMIT = 20
FINAL_TOP_K = 5


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

    # 构建 prompt
    system_prompt = llm_prompts.format_rag_system(context)
    user_prompt = llm_prompts.format_rag_user_message(query)

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    # 调用 LLM
    ContextBudget.compute(config.max_tokens)
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

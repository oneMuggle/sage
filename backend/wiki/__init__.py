"""Wiki 子系统。

实现 LLM 驱动的知识库：Ingest、RAG Chat、知识图谱、级联删除、社区检测、图谱洞察、MCP Server、Deep Research、HNSW 向量索引、视觉描述。
"""

from .chat import ChatConfig, chat_with_wiki
from .community import CommunityInfo, detect_communities, get_communities_with_nodes
from .deep_research import ResearchTask, deep_research
from .embeddings import EmbeddingConfig
from .graph import GraphData, build_graph, get_graph_cached
from .ingest import IngestConfig, ingest_source
from .insights import (
    GraphInsights,
    KnowledgeGap,
    SurprisingConnection,
    analyze_graph,
)
from .lifecycle import cascade_delete_source
from .models import (
    Analysis,
    AnalysisConcept,
    AnalysisEntity,
    FileNode,
    GraphEdge,
    GraphNode,
    GraphSignal,
    IngestProgress,
    IngestResult,
    RetrievalStats,
    SearchResponse,
    SearchResult,
    WikiChatOutcome,
    WikiChatResponse,
    WikiPage,
    WikiProject,
)
from .search import search_wiki
from .vectorstore import VectorStore
from .vectorstore_hnsw import HNSWVectorStore
from .vision import (
    ImageCaption,
    VisionConfig,
    VisionProvider,
    caption_image,
    compute_image_hash,
    encode_image_base64,
)
from .vision_ingest import VisionIngestConfig, ingest_with_vision
from .web_search import SearchProvider, WebSearchResult, multi_query_search

# MCP Server 是可选的（需要额外安装 mcp 包）
try:
    from .mcp_server import run_wiki_mcp_server

    _MCP_AVAILABLE = True
except ImportError:
    run_wiki_mcp_server = None  # type: ignore
    _MCP_AVAILABLE = False

__all__ = [
    # Config
    "IngestConfig",
    "ChatConfig",
    "EmbeddingConfig",
    "VisionConfig",
    # Models
    "WikiProject",
    "FileNode",
    "WikiPage",
    "SearchResult",
    "SearchResponse",
    "IngestResult",
    "IngestProgress",
    "WikiChatResponse",
    "WikiChatOutcome",
    "RetrievalStats",
    "Analysis",
    "AnalysisEntity",
    "AnalysisConcept",
    "GraphData",
    "GraphNode",
    "GraphEdge",
    "GraphSignal",
    "CommunityInfo",
    "SurprisingConnection",
    "KnowledgeGap",
    "GraphInsights",
    "WebSearchResult",
    "SearchProvider",
    "ResearchTask",
    "ImageCaption",
    "VisionProvider",
    "VisionIngestConfig",
    # Functions
    "ingest_source",
    "chat_with_wiki",
    "search_wiki",
    "build_graph",
    "get_graph_cached",
    "cascade_delete_source",
    "detect_communities",
    "get_communities_with_nodes",
    "analyze_graph",
    "multi_query_search",
    "deep_research",
    "ingest_with_vision",
    "caption_image",
    "compute_image_hash",
    "encode_image_base64",
    "run_wiki_mcp_server",
    # Vector Stores
    "VectorStore",
    "HNSWVectorStore",
]

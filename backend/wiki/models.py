"""Wiki 领域模型。

定义 Wiki 子系统的核心数据结构，包括项目、文件、页面、搜索结果、图谱等。
"""
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


@dataclass
class WikiProject:
    """Wiki 项目。"""

    id: str
    name: str
    path: str  # 使用正斜杠


@dataclass
class FileNode:
    """文件树节点。"""

    name: str
    path: str
    is_dir: bool
    children: Optional[List["FileNode"]] = None


@dataclass
class WikiPage:
    """Wiki 页面。"""

    path: str
    content: str
    title: str


@dataclass
class SearchResult:
    """搜索结果。"""

    path: str
    title: str
    snippet: str
    score: float


@dataclass
class SearchResponse:
    """搜索响应。"""

    results: List[SearchResult]
    total: int


@dataclass
class IngestResult:
    """Ingest 结果。"""

    source_path: str  # 相对路径: "raw/sources/{filename}"
    wiki_page_path: str  # 相对路径: "wiki/sources/{slug}.md"
    page_type: str  # "source"/"entity"/...


@dataclass
class WikiChatResponse:
    """Wiki 聊天响应。"""

    answer: str
    citations: List[str]  # 引用的页面路径


class GraphSignal(str, Enum):
    """图谱边信号类型。"""

    DirectLink = "direct_link"
    SourceOverlap = "source_overlap"
    TypeAffinity = "type_affinity"


@dataclass
class GraphNode:
    """图谱节点。"""

    id: str  # 相对路径: "wiki/sources/albert-einstein.md"
    label: str  # frontmatter title 或文件名
    page_type: Optional[str] = None  # "source"/"entity"/"concept"/...
    sources: List[str] = field(default_factory=list)  # frontmatter sources:[]
    wikilinks: List[str] = field(default_factory=list)  # [[X]] 链接


@dataclass
class GraphEdge:
    """图谱边。"""

    source: str  # 节点 id
    target: str  # 节点 id
    signal: GraphSignal
    weight: float


@dataclass
class GraphData:
    """图谱数据。"""

    nodes: List[GraphNode]
    edges: List[GraphEdge]


# Ingest 进度相关


@dataclass
class IngestProgress:
    """Ingest 进度。"""

    stage: str  # "copy_source"|"step1_analyze"|"step2_write"|"embedding"|"finalize"
    percent: int  # 0-100
    message: Optional[str] = None


@dataclass
class AnalysisEntity:
    """分析实体。"""

    name: str
    entity_type: str = ""
    brief: str = ""


@dataclass
class AnalysisConcept:
    """分析概念。"""

    name: str
    brief: str = ""


@dataclass
class Analysis:
    """LLM 分析结果。"""

    entities: List[AnalysisEntity]
    concepts: List[AnalysisConcept]
    tags: List[str]
    related_topics: List[str]
    summary: str


# Chat 相关


@dataclass
class RetrievalStats:
    """检索统计。"""

    token_hits: int
    vector_hits: int
    fused_top_score: float
    total_context_tokens: int


@dataclass
class WikiChatOutcome:
    """Wiki 聊天结果。"""

    answer: str
    citations: List[str]
    stats: RetrievalStats

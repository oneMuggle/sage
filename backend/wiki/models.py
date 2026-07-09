"""Wiki 领域模型。

定义 Wiki 子系统的核心数据结构，包括项目、文件、页面、搜索结果、图谱等。
"""
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


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

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphNode":
        return cls(
            id=data["id"],
            label=data["label"],
            page_type=data.get("page_type"),
            sources=list(data.get("sources", [])),
            wikilinks=list(data.get("wikilinks", [])),
        )


@dataclass
class GraphEdge:
    """图谱边。"""

    source: str  # 节点 id
    target: str  # 节点 id
    signal: GraphSignal
    weight: float

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["signal"] = self.signal.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphEdge":
        return cls(
            source=data["source"],
            target=data["target"],
            signal=GraphSignal(data["signal"]),
            weight=data["weight"],
        )


@dataclass
class GraphData:
    """图谱数据。"""

    nodes: List[GraphNode]
    edges: List[GraphEdge]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to a JSON-compatible dict (for caching / IPC)."""
        return {
            "nodes": [n.to_dict() for n in self.nodes],
            "edges": [e.to_dict() for e in self.edges],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GraphData":
        """Deserialize from a dict (from cache JSON / IPC payload)."""
        return cls(
            nodes=[GraphNode.from_dict(n) for n in data.get("nodes", [])],
            edges=[GraphEdge.from_dict(e) for e in data.get("edges", [])],
        )


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

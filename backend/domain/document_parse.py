"""文档解析领域契约：纯数据 + Protocol，不依赖任何适配器。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

ENGINE_AUTO = "auto"
ENGINE_LOCAL = "local"
ENGINE_MINERU = "mineru"
ENGINE_CHOICES = (ENGINE_AUTO, ENGINE_LOCAL, ENGINE_MINERU)

OUTPUT_MARKDOWN = "markdown"
OUTPUT_STRUCTURED = "structured"
OUTPUT_DOCX = "docx"
OUTPUT_HTML = "html"
OUTPUT_CHOICES = (OUTPUT_MARKDOWN, OUTPUT_STRUCTURED, OUTPUT_DOCX, OUTPUT_HTML)

DEFAULT_MIN_QUALITY = 0.85
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_MAX_UPLOAD_MB = 25
DEFAULT_TIER = "standard"


@dataclass(frozen=True)
class MineruSettings:
    """MinerU 服务端配置（已解密；api_key 只允许停留在内存）。"""

    enabled: bool = False
    base_url: str = ""
    api_key: str = ""
    default_tier: str = DEFAULT_TIER
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS
    max_upload_mb: int = DEFAULT_MAX_UPLOAD_MB
    use_in_chat_attachment: bool = True
    min_quality_threshold: float = DEFAULT_MIN_QUALITY

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip())


@dataclass(frozen=True)
class ParseRequest:
    filename: str
    content_bytes: bytes
    engine_hint: str = ENGINE_AUTO
    output_format: str = OUTPUT_MARKDOWN
    page_range: Optional[str] = None
    tier: Optional[str] = None
    timeout_seconds: Optional[float] = None
    source_path: Optional[str] = None
    media_id: Optional[str] = None

    @property
    def extension(self) -> str:
        name = self.filename or ""
        if "." not in name:
            return ""
        return name.rsplit(".", 1)[-1].lower()

    def content_hash(self) -> str:
        return hashlib.sha256(self.content_bytes).hexdigest()


@dataclass(frozen=True)
class ParseResult:
    text: str
    engine_used: str
    structured: Optional[Dict[str, Any]] = None
    tier_used: Optional[str] = None
    quality_score: float = 1.0
    duration_ms: int = 0
    cached: bool = False
    warnings: List[str] = field(default_factory=list)
    media_url: Optional[str] = None
    assets: Dict[str, str] = field(default_factory=dict)

    def with_warning(self, warning: str) -> ParseResult:
        return ParseResult(
            text=self.text,
            engine_used=self.engine_used,
            structured=self.structured,
            tier_used=self.tier_used,
            quality_score=self.quality_score,
            duration_ms=self.duration_ms,
            cached=self.cached,
            warnings=[*self.warnings, warning],
            media_url=self.media_url,
            assets=dict(self.assets),
        )


@dataclass(frozen=True)
class EngineHealth:
    available: bool
    detail: str = ""
    server_tiers: Optional[List[str]] = None
    server_version: Optional[str] = None


class ParseEngine(Protocol):
    name: str

    async def parse(self, request: ParseRequest) -> ParseResult: ...

    async def health(self) -> EngineHealth: ...

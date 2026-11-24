"""文档解析装配：把领域契约、适配器与缓存组装成进程级单例。"""

from __future__ import annotations

import logging
from typing import Optional

from backend.adapters.out.document_parse.local_engine import LocalEngine
from backend.adapters.out.document_parse.mineru_client import MineruClient
from backend.adapters.out.document_parse.mineru_engine import MineruParseEngine
from backend.application.document_parse import DocumentParseService
from backend.domain.document_parse import MineruSettings, ParseEngine
from backend.services.document_parse.cache import SqliteParseCache
from backend.services.document_parse.config import load_mineru_settings
from backend.services.document_parse.queue import MineruBackgroundQueue

logger = logging.getLogger(__name__)

_service: Optional[DocumentParseService] = None
_queue: Optional[MineruBackgroundQueue] = None


def _build_mineru_engine(settings: MineruSettings) -> ParseEngine:
    client = MineruClient(
        settings.base_url,
        api_key=settings.api_key,
        timeout_seconds=settings.timeout_seconds,
    )
    return MineruParseEngine(client, tier=settings.default_tier)


def build_document_parse_service() -> DocumentParseService:
    return DocumentParseService(
        local=LocalEngine(),
        mineru_factory=_build_mineru_engine,
        cache=SqliteParseCache(),
        settings_loader=load_mineru_settings,
    )


def get_document_parse_service() -> DocumentParseService:
    global _service
    if _service is None:
        _service = build_document_parse_service()
    return _service


def reset_document_parse_service() -> None:
    global _service
    _service = None


def get_mineru_queue() -> MineruBackgroundQueue:
    global _queue
    if _queue is None:
        _queue = MineruBackgroundQueue(get_document_parse_service())
    return _queue


def reset_mineru_queue() -> None:
    global _queue
    _queue = None

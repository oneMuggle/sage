from __future__ import annotations

import asyncio

from backend.adapters.out.document_parse.mineru_errors import MineruTimeoutError
from backend.application.document_parse import CircuitBreaker, DocumentParseService
from backend.domain.document_parse import (
    EngineHealth,
    MineruSettings,
    ParseRequest,
    ParseResult,
)


class FakeEngine:
    def __init__(self, name, result=None, error=None):
        self.name = name
        self.result = result or ParseResult(text=name + " text", engine_used=name)
        self.error = error
        self.calls = 0

    async def parse(self, request):
        self.calls += 1
        if self.error:
            raise self.error
        return self.result

    async def health(self):
        return EngineHealth(available=True)


class MemoryCache:
    def __init__(self):
        self.data = {}

    def get(self, content_hash, engine):
        return self.data.get((content_hash, engine))

    def put(self, content_hash, engine, result):
        self.data[(content_hash, engine)] = result


def _service(local, mineru, settings, cache=None, breaker=None):
    return DocumentParseService(
        local=local,
        mineru_factory=lambda _settings: mineru,
        cache=cache or MemoryCache(),
        settings_loader=lambda: settings,
        breaker=breaker,
    )


def _run(service, request):
    return asyncio.run(service.parse(request))


def test_high_quality_local_does_not_escalate() -> None:
    local = FakeEngine(
        "local", ParseResult(text="ok", engine_used="local", quality_score=0.95)
    )
    mineru = FakeEngine("mineru")
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x"),
    )
    assert result.engine_used == "local"
    assert mineru.calls == 0


def test_low_quality_escalates_to_mineru() -> None:
    local = FakeEngine(
        "local", ParseResult(text="", engine_used="local", quality_score=0.2)
    )
    mineru = FakeEngine(
        "mineru", ParseResult(text="good", engine_used="mineru", tier_used="standard")
    )
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x"),
    )
    assert result.engine_used == "mineru"


def test_hint_local_never_calls_mineru() -> None:
    local = FakeEngine(
        "local", ParseResult(text="", engine_used="local", quality_score=0.0)
    )
    mineru = FakeEngine("mineru")
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x", engine_hint="local"),
    )
    assert result.engine_used == "local"
    assert mineru.calls == 0


def test_non_pdf_never_escalates() -> None:
    local = FakeEngine(
        "local", ParseResult(text="", engine_used="local", quality_score=0.0)
    )
    mineru = FakeEngine("mineru")
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.docx", content_bytes=b"x"),
    )
    assert mineru.calls == 0


def test_mineru_failure_falls_back_with_warning() -> None:
    local = FakeEngine(
        "local", ParseResult(text="low", engine_used="local", quality_score=0.1)
    )
    mineru = FakeEngine("mineru", error=MineruTimeoutError("timeout", "slow"))
    settings = MineruSettings(enabled=True, base_url="http://m:8000")
    result = _run(
        _service(local, mineru, settings),
        ParseRequest(filename="a.pdf", content_bytes=b"x"),
    )
    assert result.engine_used == "local"
    assert any(w.startswith("mineru_failed") for w in result.warnings)


def test_breaker_opens_after_three_failures() -> None:
    breaker = CircuitBreaker(threshold=3)
    for _ in range(3):
        breaker.record_failure()
    assert breaker.closed() is False


def test_cache_short_circuits_repeat_parse() -> None:
    local = FakeEngine("local", ParseResult(text="c", engine_used="local"))
    mineru = FakeEngine("mineru")
    cache = MemoryCache()
    service = _service(local, mineru, MineruSettings(), cache=cache)
    req = ParseRequest(filename="a.txt", content_bytes=b"same")
    _run(service, req)
    second = _run(service, req)
    assert second.cached is True
    assert local.calls == 1

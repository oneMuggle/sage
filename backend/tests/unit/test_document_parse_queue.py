from __future__ import annotations

import asyncio

from backend.domain.document_parse import ParseResult
from backend.services.document_parse.queue import MineruBackgroundQueue


class FakeService:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def parse(self, request):
        self.requests.append(request)
        return self.result


def test_queue_dedupes_and_completes() -> None:
    async def scenario() -> None:
        service = FakeService(ParseResult(text="m", engine_used="mineru"))
        queue = MineruBackgroundQueue(service)
        key = queue.submit(content=b"same", filename="a.pdf")
        assert queue.submit(content=b"same", filename="a.pdf") == key
        await asyncio.sleep(0.05)
        assert queue.get_status(key) == "completed"
        assert len(service.requests) == 1

    asyncio.run(scenario())


def test_queue_marks_failed_when_fallback() -> None:
    async def scenario() -> None:
        service = FakeService(
            ParseResult(text="l", engine_used="local", warnings=["mineru_failed"])
        )
        queue = MineruBackgroundQueue(service)
        key = queue.submit(content=b"x", filename="a.pdf")
        await asyncio.sleep(0.05)
        assert queue.get_status(key) == "failed"

    asyncio.run(scenario())

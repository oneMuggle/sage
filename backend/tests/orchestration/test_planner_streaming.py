import asyncio

from backend.orchestration.planner import Planner


class _FakeStreamingClient:
    def __init__(self):
        self.complete_calls = 0

    async def chat_stream_events(self, messages):
        yield ("reasoning_delta", "思考1")
        yield ("reasoning_delta", "思考2")
        yield ("content_delta", '{"tasks": []}')
        yield ("response", type("R", (), {"content": '{"tasks": []}'})())

    async def complete(self, prompt):
        self.complete_calls += 1
        return '{"tasks": []}'


def test_stream_decomposition_collects_content_and_reports_deltas():
    client = _FakeStreamingClient()
    planner = Planner(
        task_registry=object(),
        team_registry=object(),
        llm_client=client,
        auto_configure=False,
    )
    seen = []

    async def progress(kind, text):
        seen.append((kind, text))

    result = asyncio.run(planner._stream_decomposition("prompt", progress))
    assert result == '{"tasks": []}'
    assert ("reasoning", "思考1") in seen
    assert ("message", '{"tasks": []}') in seen
    assert client.complete_calls == 0


class _EmptyContentClient(_FakeStreamingClient):
    async def chat_stream_events(self, messages):
        yield ("reasoning_delta", "只有思考")


def test_decompose_falls_back_to_complete_when_stream_empty(monkeypatch):
    monkeypatch.setattr(
        Planner,
        "_build_decomposition_prompt",
        lambda self, request, context=None: "prompt",
    )
    client = _EmptyContentClient()
    planner = Planner(
        task_registry=object(),
        team_registry=object(),
        llm_client=client,
        auto_configure=False,
    )

    async def progress(kind, text):
        return None

    async def scenario():
        return await planner._decompose_with_llm("do it", progress=progress)

    tasks, _reasoning = asyncio.run(scenario())
    assert client.complete_calls == 1
    assert isinstance(tasks, list)

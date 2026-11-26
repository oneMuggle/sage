import asyncio

from backend.orchestration.planner import Planner


class _FakeStreamingClient:
    def __init__(self):
        self.complete_calls = 0
        self.stream_calls = 0

    async def chat_stream_events(self, messages):
        self.stream_calls += 1
        yield ("reasoning_delta", "思考1")
        yield ("reasoning_delta", "思考2")
        yield ("content_delta", '{"tasks": [')
        yield ("response", type("R", (), {"content": '{"tasks": []}'})())

    async def complete(self, prompt):
        self.complete_calls += 1
        return '{"tasks": []}'


def test_stream_decomposition_collects_content_without_raw_json_leak():
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
    # 原始 JSON 切片绝不应作为 message 进度透出（旧的逐 delta 行为）。
    assert ("message", '{"tasks": [') not in seen
    assert not any(kind == "message" and text.startswith('{"tasks"') for kind, text in seen)
    assert client.complete_calls == 0


class _LongContentClient(_FakeStreamingClient):
    async def chat_stream_events(self, messages):
        self.stream_calls += 1
        # 两段各 450 字 → 跨 400 / 800 两个里程碑
        yield ("content_delta", "a" * 450)
        yield ("content_delta", "b" * 450)
        yield ("response", type("R", (), {"content": "final"})())


def test_stream_decomposition_emits_draft_milestone_markers():
    client = _LongContentClient()
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
    assert result == "final"
    message_texts = [text for kind, text in seen if kind == "message"]
    # 仅有里程碑文案，且随长度单调递增，绝不透出原始内容
    assert message_texts, "expected at least one milestone marker"
    assert all(t.startswith("已生成计划草稿 · ") and t.endswith(" 字") for t in message_texts)
    assert not any("a" * 10 in t or "b" * 10 in t for t in message_texts)
    assert message_texts[0] == "已生成计划草稿 · 450 字"
    assert any("900" in t for t in message_texts)


class _EmptyContentClient(_FakeStreamingClient):
    async def chat_stream_events(self, messages):
        self.stream_calls += 1
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
    assert client.stream_calls == 1
    assert isinstance(tasks, list)

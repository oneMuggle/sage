import asyncio
import importlib
from pathlib import Path

# ``backend.wiki.__init__`` re-exports the ``deep_research`` *function*, which
# shadows the submodule attribute. Import via importlib to get the module
# object so its collaborators can be monkeypatched.
dr = importlib.import_module("backend.wiki.deep_research")


class _Task:
    topic = "topic"
    status = "pending"
    queries = []
    web_results = []
    synthesis = ""
    error = None


class _Provider:
    name = "fake"


def test_deep_research_emits_step_progress(monkeypatch):
    async def fake_queries(topic, llm_call):
        return ["q1", "q2"]

    async def fake_search(**kwargs):
        return [{"title": "t", "url": "u", "snippet": "s"}]

    async def fake_synth(topic, results, llm_call):
        return "# synthesis"

    monkeypatch.setattr(dr, "generate_search_queries", fake_queries)
    monkeypatch.setattr(dr, "multi_query_search", fake_search)
    monkeypatch.setattr(dr, "synthesize_research", fake_synth)

    progress = []

    async def on_progress(payload):
        progress.append(payload["text"])

    task = _Task()
    asyncio.run(
        dr.deep_research(
            task=task,
            project_root=Path(),
            search_provider=_Provider(),
            llm_call=lambda *args, **kwargs: None,
            auto_ingest=False,
            progress=on_progress,
        )
    )

    assert task.synthesis == "# synthesis"
    assert any("检索" in text for text in progress)
    assert any("搜索" in text for text in progress)
    assert any("综合" in text for text in progress)

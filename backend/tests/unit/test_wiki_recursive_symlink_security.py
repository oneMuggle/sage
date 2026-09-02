"""Regression tests for symlink-safe Wiki markdown traversal."""

from pathlib import Path
from typing import Tuple

import pytest

from backend.wiki.chat import ChatConfig, _build_chat_context
from backend.wiki.graph import build_graph
from backend.wiki.search import search_wiki


def _make_wiki_tree(tmp_path: Path) -> Tuple[Path, Path]:
    project = tmp_path / "project"
    wiki = project / "wiki"
    outside = tmp_path / "outside.md"
    wiki.mkdir(parents=True)
    (wiki / "legal.md").write_text("# Legal page\ninside marker", encoding="utf-8")
    outside.write_text("# Outside secret\nexternal marker", encoding="utf-8")
    (wiki / "leak.md").symlink_to(outside)
    outside_dir = tmp_path / "outside-dir"
    outside_dir.mkdir()
    (outside_dir / "nested.md").write_text(
        "# Nested secret\ndirectory marker", encoding="utf-8"
    )
    (wiki / "linked-dir").symlink_to(outside_dir, target_is_directory=True)
    return project, outside


def test_search_skips_symlink_files_and_directories(tmp_path: Path) -> None:
    project, _outside = _make_wiki_tree(tmp_path)

    result = search_wiki(project, "external secret")

    assert result.results == []


def test_graph_skips_symlink_files_and_directories(tmp_path: Path) -> None:
    project, _outside = _make_wiki_tree(tmp_path)

    graph = build_graph(project)

    assert [node.id for node in graph.nodes] == ["wiki/legal.md"]


@pytest.mark.asyncio()
async def test_chat_does_not_read_symlinked_wiki_page(tmp_path: Path) -> None:
    project, _outside = _make_wiki_tree(tmp_path)

    async def fail_embedding(*_args, **_kwargs):
        raise RuntimeError("embedding unavailable")

    context, citations, _stats = await _build_chat_context(
        ChatConfig(
            llm_base_url="http://unused",
            llm_api_key="unused",
            llm_model="unused",
            embed_base_url="http://unused",
            embed_api_key="unused",
            embed_model="unused",
        ),
        project,
        "external secret",
        fail_embedding,
    )

    assert context == ""
    assert citations == []

"""Regression tests for symlink-safe Wiki markdown traversal."""

import os
from pathlib import Path
from typing import Tuple

import pytest

from backend.wiki.chat import ChatConfig, _build_chat_context
from backend.wiki.graph import build_graph
from backend.wiki.search import search_wiki

pytestmark = pytest.mark.skipif(
    os.name == "nt",
    reason="递归 symlink 安全用例依赖 POSIX symlink 特权",
)


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


@pytest.mark.parametrize("allowed_paths", [None, set(), {"wiki/selected.md"}])
def test_search_filters_sources_before_limit(tmp_path: Path, allowed_paths) -> None:
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    (wiki / "selected.md").write_text("# Selected\nneedle", encoding="utf-8")
    for index in range(25):
        (wiki / f"excluded-{index}.md").write_text("# needle\nneedle " * 10, encoding="utf-8")

    result = search_wiki(tmp_path, "needle", limit=1, allowed_paths=allowed_paths)

    if allowed_paths is None:
        assert len(result.results) == 1
        assert result.results[0].path.startswith("wiki/excluded-")
        assert result == search_wiki(tmp_path, "needle", limit=1)
    else:
        assert [hit.path for hit in result.results] == sorted(allowed_paths)
        assert result.total == len(allowed_paths)


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

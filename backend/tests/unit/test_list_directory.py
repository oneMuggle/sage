"""Unit tests for list_directory_impl in backend.api.wiki_routes.

覆盖行为：
- 目录递归到 depth=10
- 过滤隐藏文件（以 . 开头）
- 目录排在文件前（按名字升序）
"""

from backend.api.wiki_routes import list_directory_impl


def test_list_directory_recursive_children(tmp_path):
    project = tmp_path / "wiki-project"
    wiki = project / "wiki"
    wiki.mkdir(parents=True)
    (wiki / "index.md").write_text("x")
    concepts = wiki / "concepts"
    concepts.mkdir()
    (concepts / "alpha.md").write_text("a")
    (concepts / "beta.md").write_text("b")
    (concepts / ".hidden").write_text("h")  # should be filtered

    result = list_directory_impl("wiki", str(project))

    wiki_node = result[0]
    assert wiki_node["name"] == "wiki"
    children_names = sorted(c["name"] for c in wiki_node["children"])
    assert children_names == ["concepts", "index.md"]

    concepts_node = next(c for c in wiki_node["children"] if c["name"] == "concepts")
    assert sorted(c["name"] for c in concepts_node["children"]) == ["alpha.md", "beta.md"]

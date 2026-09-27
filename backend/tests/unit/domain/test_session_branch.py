"""R141 — 会话分支树 SessionBranch 单元测试。

覆盖：建根/子节点/游标语义、根唯一与 id 冲突防御、switch_branch、
get_path_to_root（根在前/游标默认/悬空父/成环）、get_all_branches
（线性链/分叉/空树/悬空子）。
"""

from __future__ import annotations

import pytest

from backend.domain.session_branch import SessionBranch

pytestmark = pytest.mark.unit


def _branch_with_chain(*ids):
    """构造线性链 n0 → n1 → …，游标停在末节点。"""
    tree = SessionBranch(session_id="s1")
    for i, node_id in enumerate(ids):
        tree.add_node(ids[i - 1] if i else None, f"msg-{node_id}", node_id=node_id)
    return tree


# ---------------------------------------------------------------------------
# add_node
# ---------------------------------------------------------------------------


def test_add_root_on_empty_tree():
    tree = SessionBranch(session_id="s1")
    node = tree.add_node(None, "m1", node_id="n0")
    assert node.id == "n0"
    assert node.parent_id is None
    assert tree.root_node_id == "n0"
    assert tree.current_node_id == "n0"  # 游标随动


def test_second_root_rejected():
    tree = _branch_with_chain("n0")
    with pytest.raises(ValueError, match="second root"):
        tree.add_node(None, "m1", node_id="n1")


def test_add_child_appends_children_in_order_and_moves_cursor():
    tree = _branch_with_chain("n0")
    tree.add_node("n0", "m1", node_id="n1")
    tree.add_node("n0", "m2", node_id="n2")
    assert tree.nodes["n0"].children == ["n1", "n2"]
    assert tree.current_node_id == "n2"


def test_add_child_with_unknown_parent_rejected():
    tree = _branch_with_chain("n0")
    with pytest.raises(ValueError, match="Parent node"):
        tree.add_node("ghost", "m1", node_id="n1")


def test_duplicate_node_id_rejected():
    tree = _branch_with_chain("n0")
    with pytest.raises(ValueError, match="already exists"):
        tree.add_node("n0", "m1", node_id="n0")


def test_metadata_copied_not_aliased():
    tree = SessionBranch(session_id="s1")
    meta = {"ts": 1}
    node = tree.add_node(None, "m1", node_id="n0", metadata=meta)
    meta["ts"] = 999
    assert node.metadata == {"ts": 1}  # 拷贝而非引用


# ---------------------------------------------------------------------------
# switch_branch
# ---------------------------------------------------------------------------


def test_switch_branch_moves_cursor():
    tree = _branch_with_chain("n0", "n1")
    tree.switch_branch("n0")
    assert tree.current_node_id == "n0"


def test_switch_branch_unknown_node_rejected():
    tree = _branch_with_chain("n0")
    with pytest.raises(ValueError, match="not found"):
        tree.switch_branch("ghost")


# ---------------------------------------------------------------------------
# get_path_to_root
# ---------------------------------------------------------------------------


def test_path_to_root_root_first_from_explicit_node():
    tree = _branch_with_chain("n0", "n1", "n2")
    assert tree.get_path_to_root("n2") == ["n0", "n1", "n2"]


def test_path_to_root_defaults_to_cursor():
    tree = _branch_with_chain("n0", "n1")
    assert tree.get_path_to_root() == ["n0", "n1"]


def test_path_to_root_empty_tree_returns_empty():
    assert SessionBranch(session_id="s1").get_path_to_root() == []


def test_path_to_root_dangling_parent_rejected():
    tree = _branch_with_chain("n0")
    tree.nodes["n0"].parent_id = "ghost"  # 模拟数据损坏
    with pytest.raises(ValueError, match="Dangling"):
        tree.get_path_to_root()


def test_path_to_root_cycle_rejected():
    tree = _branch_with_chain("n0", "n1")
    tree.nodes["n0"].parent_id = "n1"  # 构造环
    with pytest.raises(ValueError, match="Cycle"):
        tree.get_path_to_root("n1")


# ---------------------------------------------------------------------------
# get_all_branches
# ---------------------------------------------------------------------------


def test_all_branches_linear_chain_single_path():
    tree = _branch_with_chain("n0", "n1", "n2")
    assert tree.get_all_branches() == [["n0", "n1", "n2"]]


def test_all_branches_fork_returns_two_paths():
    tree = _branch_with_chain("n0")
    tree.add_node("n0", "m1", node_id="n1")
    tree.add_node("n0", "m2", node_id="n2")
    branches = tree.get_all_branches()
    assert branches == [["n0", "n1"], ["n0", "n2"]]


def test_all_branches_empty_tree():
    assert SessionBranch(session_id="s1").get_all_branches() == []


def test_all_branches_dangling_child_rejected():
    tree = _branch_with_chain("n0")
    tree.nodes["n0"].children.append("ghost")  # 模拟数据损坏
    with pytest.raises(ValueError, match="Dangling"):
        tree.get_all_branches()

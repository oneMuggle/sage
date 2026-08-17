"""A24 会话分支树领域模型单测。

覆盖:
- ``add_node``:建根、挂子、游标自动移动、metadata 拷贝隔离;
  第二根 / 未知父 / id 冲突三条错误路径。
- ``switch_branch``:正常切换;未知节点抛 ``ValueError``。
- ``get_path_to_root``:根在前顺序;空树返空;显式 node_id;
  悬空父引用与成环检测。
- ``get_all_branches``:线性单分支;分叉多分支;空树返空。
"""

from __future__ import annotations

import pytest

from backend.domain.session_branch import SessionBranch, SessionNode

pytestmark = pytest.mark.unit


def _linear_branch() -> SessionBranch:
    """root → a → b 的线性树(确定性 id)。"""
    branch = SessionBranch(session_id="s1")
    branch.add_node(None, "msg-root", node_id="root")
    branch.add_node("root", "msg-a", node_id="a")
    branch.add_node("a", "msg-b", node_id="b")
    return branch


# ---------------------------------------------------------------------------
# add_node
# ---------------------------------------------------------------------------


def test_add_first_node_creates_root_and_moves_cursor():
    branch = SessionBranch(session_id="s1")
    node = branch.add_node(None, "msg-1", node_id="n1")

    assert isinstance(node, SessionNode)
    assert node.id == "n1"
    assert node.parent_id is None
    assert node.message_id == "msg-1"
    assert node.children == []
    assert node.metadata == {}
    assert branch.root_node_id == "n1"
    assert branch.current_node_id == "n1"
    assert branch.nodes["n1"] is node


def test_add_child_links_parent_and_moves_cursor():
    branch = _linear_branch()

    assert branch.nodes["root"].children == ["a"]
    assert branch.nodes["a"].children == ["b"]
    assert branch.nodes["a"].parent_id == "root"
    # 最后一次 add_node 移动游标到 b
    assert branch.current_node_id == "b"


def test_add_node_requires_caller_supplied_id():
    # 领域纯净性契约:id 由边界层生成,领域层不依赖随机源(uuid)
    branch = SessionBranch(session_id="s1")
    with pytest.raises(TypeError):
        branch.add_node(None, "msg-1")  # type: ignore[call-arg]


def test_add_node_copies_metadata_for_isolation():
    branch = SessionBranch(session_id="s1")
    meta = {"tag": "x"}
    node = branch.add_node(None, "msg-1", node_id="n1", metadata=meta)

    meta["tag"] = "mutated"
    assert node.metadata == {"tag": "x"}  # 不受外部 dict 变更影响


def test_add_node_rejects_second_root():
    branch = _linear_branch()
    with pytest.raises(ValueError, match="second root"):
        branch.add_node(None, "msg-other-root", node_id="r2")


def test_add_node_rejects_unknown_parent():
    branch = SessionBranch(session_id="s1")
    with pytest.raises(ValueError, match="Parent node ghost not found"):
        branch.add_node("ghost", "msg-x", node_id="x1")


def test_add_node_rejects_duplicate_node_id():
    branch = _linear_branch()
    with pytest.raises(ValueError, match="already exists"):
        branch.add_node("root", "msg-dup", node_id="a")


# ---------------------------------------------------------------------------
# switch_branch
# ---------------------------------------------------------------------------


def test_switch_branch_moves_cursor():
    branch = _linear_branch()
    branch.switch_branch("a")
    assert branch.current_node_id == "a"


def test_switch_branch_unknown_node_raises():
    branch = _linear_branch()
    with pytest.raises(ValueError, match="Node ghost not found"):
        branch.switch_branch("ghost")


# ---------------------------------------------------------------------------
# get_path_to_root
# ---------------------------------------------------------------------------


def test_get_path_to_root_returns_root_first_order():
    branch = _linear_branch()
    # 游标在 b
    assert branch.get_path_to_root() == ["root", "a", "b"]


def test_get_path_to_root_with_explicit_node_id():
    branch = _linear_branch()
    assert branch.get_path_to_root("a") == ["root", "a"]
    assert branch.get_path_to_root("root") == ["root"]


def test_get_path_to_root_empty_tree_returns_empty():
    branch = SessionBranch(session_id="s1")
    assert branch.get_path_to_root() == []


def test_get_path_to_root_dangling_parent_raises():
    branch = _linear_branch()
    # 手动把父引用改为不存在的节点,模拟数据损坏
    branch.nodes["b"].parent_id = "ghost"
    with pytest.raises(ValueError, match="Dangling parent reference ghost"):
        branch.get_path_to_root()


def test_get_path_to_root_cycle_raises():
    branch = _linear_branch()
    # 手动制造父指针环(a、b 互为父节点)
    branch.nodes["b"].parent_id = "a"
    branch.nodes["a"].parent_id = "b"
    with pytest.raises(ValueError, match="Cycle detected"):
        branch.get_path_to_root()


# ---------------------------------------------------------------------------
# get_all_branches
# ---------------------------------------------------------------------------


def test_get_all_branches_linear_single_branch():
    branch = _linear_branch()
    assert branch.get_all_branches() == [["root", "a", "b"]]


def test_get_all_branches_after_fork():
    branch = _linear_branch()
    # 从 a 分叉出第二个分支 c
    branch.add_node("a", "msg-c", node_id="c")

    branches = branch.get_all_branches()
    assert len(branches) == 2
    assert ["root", "a", "b"] in branches
    assert ["root", "a", "c"] in branches
    # 分叉点 a 有两个子
    assert branch.nodes["a"].children == ["b", "c"]


def test_get_all_branches_empty_tree_returns_empty():
    branch = SessionBranch(session_id="s1")
    assert branch.get_all_branches() == []


def test_get_all_branches_dangling_child_raises():
    branch = _linear_branch()
    # 手动制造悬空子引用
    branch.nodes["a"].children.append("ghost")
    with pytest.raises(ValueError, match="Dangling child reference ghost"):
        branch.get_all_branches()

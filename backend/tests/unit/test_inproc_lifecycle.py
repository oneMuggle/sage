"""Unit tests for InprocSkillAdapter lifecycle integration（归档 + 分类）。

用 4 个 builtin（search/writer/coder/travel）+ autouse 临时 DB；
reset_skill_adapter 保证 adapter 单例隔离。
"""

import pytest

import backend.adapters.out.skill.inproc as inproc_mod
from backend.adapters.out.skill.inproc import get_singleton


@pytest.fixture()
def adapter(reset_skill_adapter):
    return get_singleton()


def test_set_archived_and_is_archived(adapter):
    assert not adapter.is_archived("search")
    assert adapter.set_archived("search", True) is True
    assert adapter.is_archived("search")


def test_unarchive(adapter):
    adapter.set_archived("search", True)
    assert adapter.set_archived("search", False) is True
    assert not adapter.is_archived("search")


def test_set_archived_unknown_skill_returns_false(adapter):
    assert adapter.set_archived("no-such-skill", True) is False


def test_archive_persists_across_adapter_instances(adapter):
    """DB 真相：新 adapter 实例 hydrate 后仍归档（重启不丢）。"""
    adapter.set_archived("coder", True)
    inproc_mod._skill_adapter_singleton = None  # 强制重建
    assert get_singleton().is_archived("coder")


def test_lifecycle_map_active_stale_archived(adapter):
    adapter.bump_usage("search")  # 刚用 → active
    adapter.set_archived("coder", True)  # → archived
    m = adapter.lifecycle_map()
    assert m["search"] == "active"
    assert m["coder"] == "archived"
    assert m["travel"] == "stale"  # 从未用 → stale
    assert m["writer"] == "stale"


def test_list_skills_extended_includes_lifecycle(adapter):
    adapter.bump_usage("search")
    adapter.set_archived("coder", True)
    ext = {e["name"]: e for e in adapter.list_skills_extended()}
    assert ext["search"]["lifecycle"] == "active"
    assert ext["coder"]["lifecycle"] == "archived"
    assert ext["travel"]["lifecycle"] == "stale"

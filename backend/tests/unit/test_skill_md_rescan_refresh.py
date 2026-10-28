"""rescan 真正刷新已加载的 SKILL.md (缺口 #12 修正版)。

- 同路径 SKILL.md 内容变更 → hot_reload 成功, registry 替换, skipped 不增
- 同路径 SKILL.md 内容未变 → 静默 skip, 不进 skipped 列表
- 不同路径同名 SKILL.md → "duplicate_skillmd" (高优先级目录胜)
- 与 builtin 同名 → "builtin_conflict" (builtin 永远胜)
"""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from backend.adapters.out.skill.inproc import InprocSkillAdapter
from backend.skills.base import BaseSkill, SkillResult, SkillSchema
from backend.skills.registry import SkillRegistry
from backend.skills.skill_md.loader import SkillMdHotLoader
from backend.skills.skill_md.skill import SkillMdSkill

pytestmark = pytest.mark.unit


def _write_skill(tmp_path: Path, name: str, body: str) -> Path:
    d = tmp_path / name
    d.mkdir(parents=True, exist_ok=True)
    p = d / "SKILL.md"
    p.write_text(
        f"---\nname: {name}\ndescription: {name} skill\n---\n{body}\n",
        encoding="utf-8",
    )
    return p


class _Builtin(BaseSkill):
    """builtin 占位符 —— 与 SkillMdSkill 类型不同, 用于测试 builtin_conflict。"""

    def __init__(self, name):
        super().__init__()
        self._name = name

    def _build_schema(self) -> SkillSchema:
        return SkillSchema(
            name=self._name,
            description="builtin",
            triggers=[self._name],
            parameters={"type": "object", "properties": {}, "required": []},
        )

    def execute(self, params, context):
        return SkillResult(success=True, content="builtin")


def test_same_path_refresh_updates_registry_and_hash(tmp_path):
    """SKILL.md 内容变更后, rescan 触发 hot_reload, registry 里的 skill 拿到新 body。"""
    path = _write_skill(tmp_path, "refreshme", "BODY-V1")
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1
    assert skipped == 0

    # 修改文件内容
    path.write_text(
        "---\nname: refreshme\ndescription: refreshme skill\n---\nBODY-V2\n",
        encoding="utf-8",
    )

    loaded, skipped = loader.scan_and_load()
    assert loaded == 1, "refresh 后应计数为 1 次重新加载"
    assert skipped == 0, "同路径刷新不应记入 skipped"
    skill = registry.get("refreshme")
    assert isinstance(skill, SkillMdSkill)
    assert "BODY-V2" in skill._doc.body


def test_unchanged_same_path_is_silent_skip(tmp_path):
    """SKILL.md 内容未变 → 静默跳过, 不进 skipped 列表。"""
    _write_skill(tmp_path, "same", "STABLE")
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])
    loader.scan_and_load()

    # 第二次扫描: 同一份文件, 同一 loader 实例
    loaded, skipped = loader.scan_and_load()
    assert skipped == 0, "未变内容不应进入 skipped 列表"
    # loaded 可能是 1 (refresh 成功) 或 0 (无变化); 两者都算对
    assert loaded in (0, 1)


def test_different_path_same_name_is_duplicate(tmp_path):
    """两个不同目录有同名 SKILL.md → 高优先级目录胜, 低优先级记 duplicate_skillmd。"""
    high = tmp_path / "high"
    low = tmp_path / "low"
    high.mkdir()
    low.mkdir()
    (high / "dupe").mkdir()
    (high / "dupe" / "SKILL.md").write_text(
        "---\nname: dupe\ndescription: high\n---\nHIGH\n",
        encoding="utf-8",
    )
    (low / "dupe").mkdir()
    (low / "dupe" / "SKILL.md").write_text(
        "---\nname: dupe\ndescription: low\n---\nLOW\n",
        encoding="utf-8",
    )

    registry = SkillRegistry()
    # 高优先级目录在前
    loader = SkillMdHotLoader(registry, dirs=[high, low])
    loaded, skipped = loader.scan_and_load()

    assert loaded == 1
    assert skipped == 1
    assert any(
        s["name"] == "dupe" and s["reason"] == "duplicate_skillmd"
        for s in loader.skipped
    )
    skill = registry.get("dupe")
    assert isinstance(skill, SkillMdSkill)
    assert "HIGH" in skill._doc.body


def test_builtin_conflict_unchanged(tmp_path):
    """与 builtin 同名 → 'builtin_conflict' (行为不变)。"""
    _write_skill(tmp_path, "search", "some body")
    registry = SkillRegistry()
    registry.register(_Builtin("search"))
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])

    loaded, skipped = loader.scan_and_load()

    assert loaded == 0
    assert skipped == 1
    assert loader.skipped[0]["reason"] == "builtin_conflict"
    # builtin 永远胜
    assert not isinstance(registry.get("search"), SkillMdSkill)


def test_loaded_this_scan_tracking(tmp_path):
    """_loaded_this_scan 在每次 scan_and_load 开始时重置, 只记本次加载/刷新的名字。"""
    _write_skill(tmp_path, "alpha", "A")
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])

    loaded, _ = loader.scan_and_load()
    assert loaded == 1
    assert "alpha" in loader._loaded_this_scan

    # 第二次扫描 (内容未变) → _loaded_this_scan 应该为空 (静默跳过)
    loaded2, _ = loader.scan_and_load()
    assert loaded2 == 0
    assert loader._loaded_this_scan == []


def test_skip_counting_silent_skip_not_counted(tmp_path):
    """静默跳过 (内容未变) 不应增加 skipped 计数。"""
    _write_skill(tmp_path, "stable", "CONTENT")
    registry = SkillRegistry()
    loader = SkillMdHotLoader(registry, dirs=[tmp_path])

    # 首次扫描
    _, skipped1 = loader.scan_and_load()
    assert skipped1 == 0

    # 第二次扫描 — 内容未变, skipped 应该仍然是 0
    _, skipped2 = loader.scan_and_load()
    assert skipped2 == 0, "silent skip must not inflate skipped count"


def _make_adapter(tmp_path: Path, initial_dirs: list) -> InprocSkillAdapter:
    """构造一个持有 persistent loader 的最小 InprocSkillAdapter (绕过 __init__)。"""
    adapter = InprocSkillAdapter.__new__(InprocSkillAdapter)
    adapter._registry = SkillRegistry()
    adapter._settings_repo = None
    adapter._script_runner = MagicMock()
    adapter._script_runner._allowed_roots = list(initial_dirs)
    adapter._skill_dirs = list(initial_dirs)
    adapter._scan_lock = threading.Lock()
    adapter._skill_md_loader = SkillMdHotLoader(adapter._registry, dirs=initial_dirs)
    adapter._skill_md_loader.scan_and_load()
    return adapter


def test_topology_change_reuses_loader_without_false_duplicate(tmp_path):
    """目录拓扑变化 (新增 B) 时不得重建 loader。

    回归评审 HIGH: 若 rescan 重建 loader, _loaded_paths 丢失, 已加载技能会被
    误判为 duplicate_skillmd, 且再也无法 hot_reload。
    """
    dir_a = tmp_path / "a-skills"
    dir_b = tmp_path / "b-skills"
    dir_a.mkdir()
    dir_b.mkdir()
    path_a = _write_skill(dir_a, "keepme", "V1")
    _write_skill(dir_b, "newbie", "N1")

    adapter = _make_adapter(tmp_path, [dir_a])
    loader = adapter._skill_md_loader
    assert "keepme" in loader._loaded_paths
    assert str(path_a) in loader._file_hashes

    with patch(
        "backend.skills.skill_md.loader.discover_skill_md_dirs",
        return_value=[dir_a, dir_b],
    ), patch(
        "backend.skills.skill_md.loader._discover_shipped_dir",
        return_value=None,
    ):
        result = adapter.rescan_skill_mds()

    # (a) 已加载技能没有被误报为 duplicate_skillmd
    assert not any(s["name"] == "keepme" for s in result["skipped"])
    # (b) loader 未被重建: 路径/哈希缓存仍在, 新目录技能被追加
    assert adapter._skill_md_loader is loader
    assert "keepme" in loader._loaded_paths
    assert str(path_a) in loader._file_hashes
    assert "newbie" in loader._loaded_paths

    # (c) 编辑既有技能后, 下一次 rescan 仍能刷新 registry 中的 body
    path_a.write_text(
        "---\nname: keepme\ndescription: keepme skill\n---\nV2\n",
        encoding="utf-8",
    )
    with patch(
        "backend.skills.skill_md.loader.discover_skill_md_dirs",
        return_value=[dir_a, dir_b],
    ), patch(
        "backend.skills.skill_md.loader._discover_shipped_dir",
        return_value=None,
    ):
        result2 = adapter.rescan_skill_mds()

    skill = adapter._registry.get("keepme")
    assert isinstance(skill, SkillMdSkill)
    assert "V2" in skill._doc.body
    assert "keepme" in [item["name"] for item in result2["loaded"]]
    assert not any(s["name"] == "keepme" for s in result2["skipped"])

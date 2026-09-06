# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容，保留 typing 注解
"""L5 环境上下文 + 技能清单注入（backend/chat/env_context.py）单元测试。"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.chat.env_context import build_environment_block, build_skills_block

pytestmark = pytest.mark.unit


# ---- build_environment_block ----


def test_environment_block_contains_platform_date_workspace():
    block = build_environment_block(workspace_path="E:/tmp/ws")
    assert block.startswith("<environment>")
    assert "</environment>" in block
    assert "平台" in block
    assert "日期" in block
    assert "E:/tmp/ws" in block
    # 非 git 目录 → 无 Git 行
    assert "Git:" not in block


def test_environment_block_git_summary_with_repo(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    git("init")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "a.py").write_text("x", encoding="utf-8")
    git("add", ".")
    git("commit", "-m", "init")
    (repo / "b.py").write_text("y", encoding="utf-8")  # 未提交变更

    block = build_environment_block(workspace_path=str(repo))
    assert "Git:" in block
    assert "1 个未提交变更" in block


def test_environment_block_non_repo_omits_git(tmp_path: Path):
    plain = tmp_path / "plain"
    plain.mkdir()
    block = build_environment_block(workspace_path=str(plain))
    assert "Git:" not in block


# ---- build_skills_block ----


def test_skills_block_lists_name_and_description(monkeypatch):
    fake_specs = [
        SimpleNamespace(name="summarize", description="总结长文档"),
        SimpleNamespace(name="translate", description="翻译文本"),
    ]

    class _FakeSingleton:
        def list_skills(self):
            return fake_specs

    import backend.adapters.out.skill.inproc as inproc_mod

    monkeypatch.setattr(inproc_mod, "get_singleton", lambda: _FakeSingleton())
    block = build_skills_block()
    assert block.startswith("<available-skills>")
    assert "- /summarize：总结长文档" in block
    assert "- /translate：翻译文本" in block


def test_skills_block_empty_when_no_skills(monkeypatch):
    class _FakeSingleton:
        def list_skills(self):
            return []

    import backend.adapters.out.skill.inproc as inproc_mod

    monkeypatch.setattr(inproc_mod, "get_singleton", lambda: _FakeSingleton())
    assert build_skills_block() == ""


def test_skills_block_fail_safe_on_registry_error(monkeypatch):
    def _boom():
        raise RuntimeError("registry down")

    import backend.adapters.out.skill.inproc as inproc_mod

    monkeypatch.setattr(inproc_mod, "get_singleton", _boom)
    assert build_skills_block() == ""


def test_skills_block_truncates_at_char_budget(monkeypatch):
    fake_specs = [
        SimpleNamespace(name=f"s{i}", description="x" * 200) for i in range(30)
    ]

    class _FakeSingleton:
        def list_skills(self):
            return fake_specs

    import backend.adapters.out.skill.inproc as inproc_mod

    monkeypatch.setattr(inproc_mod, "get_singleton", lambda: _FakeSingleton())
    block = build_skills_block()
    assert len(block) < 4000
    assert "其余技能已省略" in block

"""workflow_mode 解析单元测试。

覆盖优先级：显式值 > 用户文本意图 > 环境变量 > 默认 "tdd"。
"""

from __future__ import annotations

import pytest

from backend.orchestration.workflow_mode import (
    DEFAULT_WORKFLOW_MODE,
    ENV_WORKFLOW_MODE,
    detect_from_text,
    env_workflow_mode,
    first_valid,
    resolve_workflow_mode,
)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch):
    """每个用例都从「环境变量未设置」开始。"""
    monkeypatch.delenv(ENV_WORKFLOW_MODE, raising=False)


class TestResolveWorkflowMode:
    """resolve_workflow_mode 的优先级链。"""

    def test_resolve_mode_default(self):
        """无任何输入 → 默认 "tdd"。"""
        assert resolve_workflow_mode() == DEFAULT_WORKFLOW_MODE == "tdd"

    def test_resolve_mode_env_override(self, monkeypatch):
        """SAGE_TDD_MODE=fast → "fast"。"""
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "fast")
        assert resolve_workflow_mode() == "fast"

    def test_resolve_mode_env_invalid_ignored(self, monkeypatch):
        """环境变量值非法 → 回落默认。"""
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "turbo")
        assert resolve_workflow_mode() == "tdd"

    def test_resolve_mode_user_text_fast(self):
        """用户文本 "跳过测试" → "fast"。"""
        assert resolve_workflow_mode(user_text="这个功能先跳过测试，快速实现") == "fast"

    def test_resolve_mode_user_text_tdd_overrides_env(self, monkeypatch):
        """用户显式说 TDD → 压过环境变量 fast。"""
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "fast")
        assert resolve_workflow_mode(user_text="这个用 TDD 做，先写测试") == "tdd"

    def test_resolve_mode_explicit_wins(self, monkeypatch):
        """显式值 > 环境变量 > 默认。"""
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "fast")
        assert resolve_workflow_mode(explicit="tdd") == "tdd"
        assert resolve_workflow_mode(explicit="fast") == "fast"

    def test_resolve_mode_explicit_invalid_falls_through(self, monkeypatch):
        """显式值非法 → 继续走文本/环境变量链。"""
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "fast")
        assert resolve_workflow_mode(explicit="bogus") == "fast"

    def test_resolve_mode_user_text_beats_env(self, monkeypatch):
        """用户文本 fast 压过环境变量 tdd。"""
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "tdd")
        assert resolve_workflow_mode(user_text="跳过测试，直接出原型") == "fast"

    def test_resolve_mode_env_case_insensitive(self, monkeypatch):
        """环境变量大小写不敏感。"""
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "FAST")
        assert resolve_workflow_mode() == "fast"


class TestDetectFromText:
    """用户文本意图识别。"""

    def test_detect_none_on_empty(self):
        assert detect_from_text(None) is None
        assert detect_from_text("") is None

    def test_detect_none_on_unrelated_text(self):
        assert detect_from_text("帮我实现一个导出按钮") is None

    def test_detect_fast_english(self):
        assert detect_from_text("skip tests for now") == "fast"

    def test_detect_tdd_english(self):
        assert detect_from_text("use test-driven development") == "tdd"

    def test_detect_fast_wins_over_tdd_word(self):
        """"不要写测试" 含 "写测试" 形态，须判 fast 而非 tdd。"""
        assert detect_from_text("不要写测试，先出原型") == "fast"


class TestEnvWorkflowMode:
    """环境变量读取。"""

    def test_env_unset_returns_none(self):
        assert env_workflow_mode() is None

    def test_env_valid(self, monkeypatch):
        monkeypatch.setenv(ENV_WORKFLOW_MODE, "tdd")
        assert env_workflow_mode() == "tdd"


class TestFirstValid:
    """first_valid 辅助函数。"""

    def test_skips_invalid(self):
        assert first_valid([None, "bogus", "fast"]) == "fast"

    def test_returns_none_when_empty(self):
        assert first_valid([None, "", "x"]) is None

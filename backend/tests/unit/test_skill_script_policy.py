"""T-3 技能脚本执行开关（fail-closed）单测。

覆盖 ``backend/skills/skill_md/script_policy.py`` 的判定口径：
仅显式 ``"1"`` 视为开启，其余一律拒绝；读取异常同样拒绝。
"""

from __future__ import annotations

import pytest

from backend.skills.skill_md.script_policy import (
    SETTINGS_KEY_ALLOW_SKILL_SCRIPTS,
    is_script_execution_allowed,
)


class _FakeRepo:
    """最小 SettingsRepository 替身。"""

    def __init__(self, value):
        self._value = value

    def get(self, key):
        assert key == SETTINGS_KEY_ALLOW_SKILL_SCRIPTS
        return self._value


class _BrokenRepo:
    """读取即抛异常的 repo（模拟 DB 故障）。"""

    def get(self, key):
        raise RuntimeError("database is locked")


def test_key_matches_settings_repository_whitelist():
    """开关 key 必须落在 SettingsRepository.KEYS 白名单里，否则后端返回 400。"""
    from backend.data.settings_repo import SettingsRepository

    assert SETTINGS_KEY_ALLOW_SKILL_SCRIPTS in SettingsRepository.KEYS


def test_missing_value_is_closed():
    """key 不存在 → 关闭（fail-closed）。"""
    assert is_script_execution_allowed(_FakeRepo(None)) is False


def test_explicit_zero_is_closed():
    """显式 "0" → 关闭。"""
    assert is_script_execution_allowed(_FakeRepo("0")) is False


def test_explicit_one_is_open():
    """显式 "1" → 开启。"""
    assert is_script_execution_allowed(_FakeRepo("1")) is True


@pytest.mark.parametrize("value", ["true", "yes", "on", " 1", "1 ", "", "2"])
def test_other_values_are_closed(value):
    """只有精确的 "1" 才开启，其余近似值一律关闭（不做宽松解析）。"""
    assert is_script_execution_allowed(_FakeRepo(value)) is False


def test_repo_failure_fails_closed():
    """DB 故障 → 关闭，不得因无法读取而放行外部脚本执行。"""
    assert is_script_execution_allowed(_BrokenRepo()) is False

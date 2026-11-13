import pytest

from backend.config import is_web_mode


def test_is_web_mode_returns_false_by_default(monkeypatch):
    monkeypatch.delenv("SAGE_WEB_MODE", raising=False)
    assert is_web_mode() is False


def test_is_web_mode_returns_true_when_env_set(monkeypatch):
    monkeypatch.setenv("SAGE_WEB_MODE", "1")
    assert is_web_mode() is True

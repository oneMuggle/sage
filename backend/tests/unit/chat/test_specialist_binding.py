# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""会话级专家绑定解析（M0 — 2026-11-03）。

覆盖：

- ``resolve_bound_specialist``：会话缺失 / 未绑定 / 专家禁用 → 主助手；
- ``resolve_effective_agent_id``：请求显式 agent_id 优先于会话绑定；
- ``validate_specialist_id``：API 边界校验（None 透传、空串解绑、未知 400）。
"""

from types import SimpleNamespace

import pytest

from backend.chat.specialist_binding import (
    PRIMARY_AGENT_ID,
    resolve_bound_specialist,
    resolve_effective_agent_id,
    validate_specialist_id,
)


class _FakeAgentRepo:
    def __init__(self, rows):
        self._rows = rows

    def get(self, agent_id):
        return self._rows.get(agent_id)


class _FakeSessionRepo:
    def __init__(self, session):
        self._session = session

    def get(self, session_id):
        return self._session


def _patch_repos(monkeypatch, *, agent_rows=None, session=None, agent_error=None):
    def _agent_repo():
        if agent_error is not None:
            raise agent_error
        return _FakeAgentRepo(agent_rows or {})

    monkeypatch.setattr("backend.data.agent_repo.AgentRepository", _agent_repo)
    monkeypatch.setattr(
        "backend.data.session_repo.SessionRepository",
        lambda: _FakeSessionRepo(session),
    )


WRITER_ROW = {"id": "writer", "enabled": True}
DISABLED_ROW = {"id": "retired", "enabled": False}


def test_bound_specialist_returns_valid_id(monkeypatch):
    _patch_repos(
        monkeypatch,
        agent_rows={"writer": WRITER_ROW},
        session=SimpleNamespace(specialist_id="writer"),
    )
    assert resolve_bound_specialist("s1") == "writer"


def test_bound_specialist_falls_back_when_disabled(monkeypatch):
    _patch_repos(
        monkeypatch,
        agent_rows={"retired": DISABLED_ROW},
        session=SimpleNamespace(specialist_id="retired"),
    )
    assert resolve_bound_specialist("s1") == PRIMARY_AGENT_ID


def test_bound_specialist_falls_back_when_missing(monkeypatch):
    _patch_repos(monkeypatch, agent_rows={}, session=SimpleNamespace(specialist_id="ghost"))
    assert resolve_bound_specialist("s1") == PRIMARY_AGENT_ID


def test_bound_specialist_falls_back_on_missing_session(monkeypatch):
    _patch_repos(monkeypatch, agent_rows={}, session=None)
    assert resolve_bound_specialist("s1") == PRIMARY_AGENT_ID


def test_bound_specialist_without_session_id_never_reads_db(monkeypatch):
    def _explode():
        raise AssertionError("SessionRepository 不应被调用")

    monkeypatch.setattr("backend.data.session_repo.SessionRepository", _explode)
    assert resolve_bound_specialist("") == PRIMARY_AGENT_ID


def test_bound_specialist_falls_back_on_repo_error(monkeypatch):
    _patch_repos(monkeypatch, agent_error=RuntimeError("db down"))
    assert resolve_bound_specialist("s1") == PRIMARY_AGENT_ID


def test_primary_binding_short_circuits(monkeypatch):
    def _explode():
        raise AssertionError("主助手无需查 agent 表")

    monkeypatch.setattr("backend.data.agent_repo.AgentRepository", _explode)
    monkeypatch.setattr(
        "backend.data.session_repo.SessionRepository",
        lambda: _FakeSessionRepo(SimpleNamespace(specialist_id="primary")),
    )
    assert resolve_bound_specialist("s1") == PRIMARY_AGENT_ID


def test_requested_agent_id_overrides_session_binding(monkeypatch):
    _patch_repos(
        monkeypatch,
        agent_rows={"writer": WRITER_ROW, "analyst": {"id": "analyst", "enabled": True}},
        session=SimpleNamespace(specialist_id="writer"),
    )
    assert resolve_effective_agent_id("s1", "analyst") == "analyst"


def test_requested_agent_id_falls_back_to_primary_when_unusable(monkeypatch):
    _patch_repos(
        monkeypatch,
        agent_rows={"retired": DISABLED_ROW},
        session=SimpleNamespace(specialist_id="writer"),
    )
    # 显式请求优先，但不可用时不回落到会话绑定，避免静默用错人设。
    assert resolve_effective_agent_id("s1", "retired") == PRIMARY_AGENT_ID


def test_validate_specialist_id_none_means_untouched():
    assert validate_specialist_id(None) is None


def test_validate_specialist_id_empty_means_unbind():
    assert validate_specialist_id("") == PRIMARY_AGENT_ID
    assert validate_specialist_id("   ") == PRIMARY_AGENT_ID


def test_validate_specialist_id_accepts_primary(monkeypatch):
    _patch_repos(monkeypatch, agent_rows={}, session=None)
    assert validate_specialist_id("primary") == PRIMARY_AGENT_ID


def test_validate_specialist_id_accepts_enabled_agent(monkeypatch):
    _patch_repos(monkeypatch, agent_rows={"writer": WRITER_ROW}, session=None)
    assert validate_specialist_id(" writer ") == "writer"


def test_validate_specialist_id_rejects_unknown_or_disabled(monkeypatch):
    _patch_repos(
        monkeypatch,
        agent_rows={"retired": DISABLED_ROW},
        session=None,
    )
    with pytest.raises(ValueError):
        validate_specialist_id("ghost")
    with pytest.raises(ValueError):
        validate_specialist_id("retired")

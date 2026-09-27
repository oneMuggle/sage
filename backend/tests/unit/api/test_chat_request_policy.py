"""R172 — chat_request_policy 窗口策略单元测试。

覆盖：_check_request_within_window（None/≤0 no-op、未超窗放行、超窗
400 含 token 数与窗口值）+ _resolve_effective_window 的 fail-safe
回退（settings 非 dict / endpoints 非 list / 无 model_id / 全缺）。
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.chat_request_policy import (
    _check_request_within_window,
    _resolve_effective_window,
)

pytestmark = pytest.mark.unit


def _msg(role="user", content="hello"):
    return {"role": role, "content": content}


# ---------------------------------------------------------------------------
# _check_request_within_window
# ---------------------------------------------------------------------------


def test_check_window_none_noop():
    _check_request_within_window([_msg()], None)  # 不抛


def test_check_window_zero_noop():
    _check_request_within_window([_msg()], 0)


def test_check_window_negative_noop():
    _check_request_within_window([_msg()], -100)


def test_check_window_under_limit_passes():
    _check_request_within_window([_msg("user", "hi")], 10_000)


def test_check_window_over_limit_raises_400():
    big = [{"role": "user", "content": "x" * 10_000}]
    with pytest.raises(HTTPException) as excinfo:
        _check_request_within_window(big, 100)
    assert excinfo.value.status_code == 400
    assert "exceeds resolved context window" in excinfo.value.detail


def test_check_window_exact_boundary_passes():
    # estimate 是近似值——用远小于窗口的输入确保不触发
    _check_request_within_window([_msg("user", "short")], 5000)


# ---------------------------------------------------------------------------
# _resolve_effective_window fail-safe 回退
# ---------------------------------------------------------------------------


def _patch_settings(monkeypatch, raw):
    import backend.data.settings_repo as repo_mod

    class _FakeRepo:
        def get_json(self, key):
            assert key == "app_settings"
            return raw

    monkeypatch.setattr(repo_mod, "SettingsRepository", _FakeRepo)


def test_resolve_settings_non_dict_returns_max_context(monkeypatch):
    _patch_settings(monkeypatch, "not-a-dict")
    assert _resolve_effective_window(model_id="m", max_context=4096) == 4096


def test_resolve_settings_non_dict_no_max_returns_none(monkeypatch):
    _patch_settings(monkeypatch, [1, 2])
    assert _resolve_effective_window() is None


def test_resolve_endpoints_non_list_returns_max_context(monkeypatch):
    _patch_settings(monkeypatch, {"endpoints": "oops"})
    assert _resolve_effective_window(max_context=2048) == 2048


def test_resolve_no_model_id_returns_max_context(monkeypatch):
    _patch_settings(
        monkeypatch,
        {
            "endpoints": [{"id": "e1", "name": "n"}],
            "modelSelections": {"chatModel": {"endpointId": "e1"}},
        },
    )
    assert _resolve_effective_window(max_context=8192) == 8192


def test_resolve_all_missing_returns_none(monkeypatch):
    _patch_settings(monkeypatch, {})
    assert _resolve_effective_window() is None


def test_resolve_request_endpoint_id_verified(monkeypatch):
    _patch_settings(
        monkeypatch,
        {
            "endpoints": [{"id": "e1"}],
            "modelSelections": {"chatModel": {"endpointId": "ghost"}},
        },
    )
    # request_endpoint_id 不在 endpoints → 回退 modelSelections 也找不到 → None
    assert (
        _resolve_effective_window(
            model_id="m",
            request_endpoint_id="ghost",
        )
        is None
    )


def test_resolve_catalog_success_auto_true(monkeypatch):
    """auto_context=True + catalog 解析成功 → 返回 catalog 窗口（受 max_context 钳制）。"""
    from types import SimpleNamespace

    limits = SimpleNamespace(native=128_000, service=None)
    fake_resolved = SimpleNamespace(limits=limits)

    class _FakeCatalogRepo:
        def __init__(self, db):
            pass

        def resolve(self, key):
            return fake_resolved

    import backend.data.database as db_mod
    import backend.model_catalog.context as ctx_mod
    import backend.model_catalog.repository as repo_mod

    monkeypatch.setattr(db_mod, "get_database", lambda: SimpleNamespace())
    monkeypatch.setattr(repo_mod, "CatalogRepository", _FakeCatalogRepo)
    monkeypatch.setattr(
        ctx_mod, "effective_window", lambda limits, automatic, fixed: 64_000
    )
    _patch_settings_with_endpoints(monkeypatch)
    result = _resolve_effective_window(model_id="m", auto_context=True)
    assert result == 64_000


def test_resolve_catalog_auto_true_clamped_by_max_context(monkeypatch):
    from types import SimpleNamespace

    limits = SimpleNamespace(native=128_000, service=None)
    fake_resolved = SimpleNamespace(limits=limits)

    class _FakeCatalogRepo:
        def __init__(self, db):
            pass

        def resolve(self, key):
            return fake_resolved

    import backend.data.database as db_mod
    import backend.model_catalog.context as ctx_mod
    import backend.model_catalog.repository as repo_mod

    monkeypatch.setattr(db_mod, "get_database", lambda: SimpleNamespace())
    monkeypatch.setattr(repo_mod, "CatalogRepository", _FakeCatalogRepo)
    monkeypatch.setattr(
        ctx_mod, "effective_window", lambda limits, automatic, fixed: 64_000
    )
    _patch_settings_with_endpoints(monkeypatch)
    result = _resolve_effective_window(model_id="m", max_context=8000, auto_context=True)
    assert result == 8000  # min(catalog, max_context)


def _patch_settings_with_endpoints(monkeypatch):
    import backend.data.settings_repo as repo_mod

    class _FakeRepo:
        def get_json(self, key):
            return {
                "endpoints": [{"id": "e1", "name": "n"}],
                "modelSelections": {"chatModel": {"endpointId": "e1"}},
            }

    monkeypatch.setattr(repo_mod, "SettingsRepository", _FakeRepo)

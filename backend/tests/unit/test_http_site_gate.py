"""HTTP 出网前的站点策略闸门（spec §5.5）。"""

import pytest

from backend.services import browser_safety
from backend.tools.http_site_gate import SiteGateVerdict, gate_http_url

pytestmark = pytest.mark.unit


@pytest.fixture()
def policy_store(monkeypatch):
    """用进程内 dict 替换持久仓储 —— 单测不得写真实 SettingsRepository。

    ``grant_site(..., "always"/"block")`` 会把策略写进用户设置库；这里换成
    内存 store，测试结束后不留下任何真实站点策略。
    """
    store = {}

    def _load():
        return {key: dict(value) for key, value in store.items()}

    def _save(policies):
        store.clear()
        store.update(policies)

    monkeypatch.setattr(browser_safety, "_load_policies", _load)
    monkeypatch.setattr(browser_safety, "_save_policies", _save)
    browser_safety.reset_site_policies_for_tests()
    yield store
    browser_safety.reset_site_policies_for_tests()
    browser_safety.reset_confirmations_for_tests()


def test_allow_verdict_passes(policy_store):
    browser_safety.grant_site("sess-1", "example.org", "session")
    verdict = gate_http_url("https://example.org/a", session_id="sess-1")
    assert isinstance(verdict, SiteGateVerdict)
    assert verdict.allowed is True
    assert verdict.reason == "allow"


def test_block_verdict_is_denied(policy_store):
    browser_safety.grant_site("sess-2", "blocked.example", "block")
    verdict = gate_http_url("https://blocked.example/a", session_id="sess-2")
    assert verdict.allowed is False
    assert verdict.reason == "block"


def test_confirm_verdict_registers_a_confirmation(policy_store):
    verdict = gate_http_url("https://unknown-site.example/a", session_id="sess-3")
    assert verdict.allowed is False
    assert verdict.reason == "confirm"
    assert verdict.confirmation_id
    assert verdict.domain == "unknown-site.example"

    pending = browser_safety.get_confirmation_registry().get(verdict.confirmation_id)
    assert pending is not None
    assert pending.domain == "unknown-site.example"


def test_url_without_host_is_allowed(policy_store):
    verdict = gate_http_url("about:blank", session_id="sess-4")
    assert verdict.allowed is True


# --- 接线断言：web_fetch / http_download 出口即受闸门约束 ---


def test_web_fetch_denies_blocked_site(policy_store, monkeypatch):
    import backend.tools.http_site_gate as gate_mod
    from backend.tools.web_tool import WebFetchTool

    monkeypatch.setattr(gate_mod, "gate_http_url", gate_http_url)
    browser_safety.grant_site("", "blocked.example", "block")
    result = WebFetchTool().execute(url="https://blocked.example/a")
    assert result.success is False
    assert "site_blocked" in (result.error or "")


def test_http_download_denies_blocked_site(policy_store, monkeypatch):
    import backend.tools.http_site_gate as gate_mod
    from backend.tools.download_tool import HttpDownloadTool

    monkeypatch.setattr(gate_mod, "gate_http_url", gate_http_url)
    browser_safety.grant_site("", "blocked.example", "block")
    result = HttpDownloadTool().execute(url="https://blocked.example/a.pdf")
    assert result.success is False
    assert "site_blocked" in (result.error or "")


def test_web_fetch_returns_needs_confirmation_for_unknown_site(
    policy_store, monkeypatch
):
    import backend.tools.http_site_gate as gate_mod
    from backend.tools.web_tool import WebFetchTool

    monkeypatch.setattr(gate_mod, "gate_http_url", gate_http_url)
    result = WebFetchTool().execute(url="https://unknown-site.example/a")
    assert result.success is False
    assert "needs_confirmation:" in (result.error or "")

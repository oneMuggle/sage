"""Firefox cookie 兼容性测试（对齐 release/win7 同名用例）。

main 上 ``normalize_cookie_for_cdp`` 已接入 web_render / 浏览器账号服务，
但此前没有任何单测；Firefox 的 ``Storage.setCookies`` 会拒绝 Chromium
特有字段，必须剥离后再注入。注意：main 的 ``_clean_cookie``（vault 入库
清洗）不主动填 ``sameSite``——Lax 默认值只在 CDP 注入边界
``normalize_cookie_for_cdp`` 补齐。
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from backend.tools.credential_vault import (
    _VAULT_ACCOUNT_PREFIX,
    KIND_COOKIE,
    _clean_cookie,
    encrypt_secret,
    merge_cdp_cookies,
    normalize_cookie_for_cdp,
)

pytestmark = pytest.mark.unit


def test_clean_cookie_preserves_explicit_samesite():
    """显式提供 sameSite 时保留原值。"""
    cookie = {
        "name": "session_id",
        "value": "abc123",
        "domain": ".example.com",
        "path": "/",
        "sameSite": "Strict",
    }
    cleaned = _clean_cookie(cookie, "example.com")
    assert cleaned is not None
    assert cleaned["sameSite"] == "Strict"


def test_normalize_cookie_for_cdp_strips_firefox_incompatible_fields():
    """normalize_cookie_for_cdp 剥离 Firefox 不支持的 Chromium 特有字段。"""
    cookie = {
        "name": "session_id",
        "value": "abc123",
        "domain": ".example.com",
        "path": "/",
        "expires": 1695123456,
        "secure": True,
        "httpOnly": True,
        "sameSite": "Lax",
        # Firefox 不支持的字段
        "priority": "high",
        "sameParty": True,
        "sourceScheme": "Secure",
        "partitionKey": {"topLevelSite": "https://example.com"},
    }
    normalized = normalize_cookie_for_cdp(cookie)
    # 标准字段保留
    assert normalized["name"] == "session_id"
    assert normalized["value"] == "abc123"
    assert normalized["domain"] == ".example.com"
    assert normalized["path"] == "/"
    assert normalized["expires"] == 1695123456
    assert normalized["secure"] is True
    assert normalized["httpOnly"] is True
    assert normalized["sameSite"] == "Lax"
    # Firefox 不支持的字段被剥离
    assert "priority" not in normalized
    assert "sameParty" not in normalized
    assert "sourceScheme" not in normalized
    assert "partitionKey" not in normalized


def test_normalize_cookie_for_cdp_defaults_samesite():
    """省略 sameSite 时默认填 Lax。"""
    cookie = {
        "name": "session_id",
        "value": "abc123",
        "domain": ".example.com",
        "path": "/",
    }
    normalized = normalize_cookie_for_cdp(cookie)
    assert normalized["sameSite"] == "Lax"


def test_normalize_cookie_for_cdp_does_not_mutate_input():
    """归一化不修改入参。"""
    cookie = {
        "name": "session_id",
        "value": "abc123",
        "domain": ".example.com",
        "path": "/",
    }
    normalized = normalize_cookie_for_cdp(cookie)
    assert "sameSite" not in cookie  # 原 dict 未被修改
    assert normalized["sameSite"] == "Lax"


def test_merge_cdp_cookies_handles_firefox_negative_expires():
    """Firefox Network.getCookies 对 session cookie 返回 expires=-1，
    merge_cdp_cookies 应识别为 session cookie 并照常合并。
    """
    firefox_cookies = [
        {
            "name": "session_id",
            "value": "abc123",
            "domain": ".example.com",
            "path": "/",
            "expires": -1,  # Firefox session cookie 标志
        }
    ]
    existing_cookies = [
        {
            "name": "old_cookie",
            "value": "old_value",
            "domain": ".example.com",
            "path": "/",
        }
    ]
    vault_entry = {
        "kind": KIND_COOKIE,
        "cookies_enc": encrypt_secret(
            json.dumps(existing_cookies), account=_VAULT_ACCOUNT_PREFIX + "example.com"
        ),
    }
    mock_vault = {"example.com": vault_entry}
    with pytest.MonkeyPatch.context() as m:
        m.setattr("backend.tools.credential_vault._load_vault", lambda repo: mock_vault)
        m.setattr(
            "backend.tools.credential_vault._save_vault", lambda repo, vault: None
        )
        m.setattr("backend.tools.credential_vault.encrypt_secret", encrypt_secret)

        changed = merge_cdp_cookies(
            "example.com",
            firefox_cookies,
            "https://example.com/page",
            repo=MagicMock(),
        )

    # session cookie 应该被合并
    assert "session_id" in changed

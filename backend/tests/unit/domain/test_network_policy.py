"""R136 — 网络访问策略领域模型单元测试。

覆盖：手写 hostname 提取（userinfo/端口/IPv6/空 host）、host 归一化、
`*.` 通配匹配与后缀混淆防御、pattern 校验（空/中间星/单段过宽）、
三模式注册门、check_host 准入（ONLINE/OFFLINE/INTRANET/坏 URL）、
allows_insecure_tls、insecure 覆盖校验、from_config 强转与回退、frozen。
"""

from __future__ import annotations

import pytest

from backend.domain.network_policy import (
    NetworkMode,
    NetworkPolicy,
    _extract_hostname,
    host_matches,
    normalize_host,
)

pytestmark = pytest.mark.unit


# ---------------------------------------------------------------------------
# _extract_hostname / normalize_host
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/path", "example.com"),
        ("https://example.com#frag", "example.com"),
        ("http://a.cnki.net/?q=1", "a.cnki.net"),
        ("http://user:pwd@host/path", "host"),
        ("http://[::1]:8080/path", "::1"),
        ("ftp://x", None),  # 无 :// 之外判断? ftp 有 —— 见下一条
        ("no-scheme", None),
        ("http:///path", None),
    ],
)
def test_extract_hostname(url, expected):
    if url == "ftp://x":
        assert _extract_hostname(url) == "x"  # scheme 无关，仅按 :// 切
        return
    assert _extract_hostname(url) == expected


def test_normalize_host_strips_lowercases_and_trailing_dot():
    assert normalize_host("  A.CNKI.net.  ") == "a.cnki.net"


# ---------------------------------------------------------------------------
# host_matches
# ---------------------------------------------------------------------------


def test_exact_match_after_normalization():
    assert host_matches("Example.COM.", "example.com") is True


def test_wildcard_matches_apex_and_subdomains():
    assert host_matches("cnki.net", "*.cnki.net") is True
    assert host_matches("a.cnki.net", "*.cnki.net") is True
    assert host_matches("x.y.cnki.net", "*.cnki.net") is True


def test_suffix_confusion_does_not_match():
    assert host_matches("evilcnki.net", "*.cnki.net") is False
    assert host_matches("cnki.net.evil.com", "*.cnki.net") is False


# ---------------------------------------------------------------------------
# pattern 校验（经构造器触发）
# ---------------------------------------------------------------------------


def test_empty_host_entry_rejected():
    with pytest.raises(ValueError, match="不能为空"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=["  "])


def test_wildcard_in_middle_rejected():
    with pytest.raises(ValueError, match="只支持"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=["a.*.net"])


def test_single_level_wildcard_rejected():
    with pytest.raises(ValueError, match="过宽"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=["*.net"])
    # "*." 经 rstrip(".") 归一为 "*"，走"非 *. 前缀"拒绝分支
    with pytest.raises(ValueError, match="只支持"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=["*."])


def test_double_wildcard_rejected():
    with pytest.raises(ValueError, match="只能出现一次"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=["*.*.net"])


# ---------------------------------------------------------------------------
# 三模式注册门
# ---------------------------------------------------------------------------


def test_search_enabled_only_online():
    assert NetworkPolicy(mode=NetworkMode.ONLINE).search_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.INTRANET).search_enabled() is False
    assert NetworkPolicy(mode=NetworkMode.OFFLINE).search_enabled() is False


def test_fetch_enabled_except_offline():
    assert NetworkPolicy(mode=NetworkMode.ONLINE).fetch_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.INTRANET).fetch_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.OFFLINE).fetch_enabled() is False


# ---------------------------------------------------------------------------
# check_host 准入
# ---------------------------------------------------------------------------


def test_online_mode_allows_any_host():
    policy = NetworkPolicy(mode=NetworkMode.ONLINE)
    assert policy.check_host("https://anything.example") is None


def test_offline_mode_rejects_everything():
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE, allowed_hosts=["*.cnki.net"])
    reason = policy.check_host("https://a.cnki.net/x")
    assert reason is not None
    assert "气隙" in reason


def test_intranet_allows_whitelisted_and_rejects_others():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET,
        allowed_hosts=["*.cnki.net", "internal.corp"],
    )
    assert policy.check_host("https://a.cnki.net/search?q=1") is None
    assert policy.check_host("https://internal.corp/x") is None
    reason = policy.check_host("https://evil.com/x")
    assert reason is not None
    assert "evil.com" in reason


def test_intranet_rejects_url_without_host():
    policy = NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=["*.cnki.net"])
    reason = policy.check_host("not-a-url")
    assert reason is not None
    assert "invalid_url" in reason


# ---------------------------------------------------------------------------
# allows_insecure_tls
# ---------------------------------------------------------------------------


def test_insecure_tls_requires_coverage_by_allowed_hosts():
    with pytest.raises(ValueError, match="未被 allowed_hosts 覆盖"):
        NetworkPolicy(
            mode=NetworkMode.INTRANET,
            allowed_hosts=["*.cnki.net"],
            insecure_tls_hosts=["internal.corp"],
        )


def test_allows_insecure_tls_hit_and_miss():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET,
        allowed_hosts=["*.corp.local"],
        insecure_tls_hosts=["nas.corp.local"],
    )
    assert policy.allows_insecure_tls("https://nas.corp.local/dav") is True
    assert policy.allows_insecure_tls("https://pc.corp.local") is False
    assert policy.allows_insecure_tls("not-a-url") is False


# ---------------------------------------------------------------------------
# from_config / frozen
# ---------------------------------------------------------------------------


def test_from_config_full_fields():
    policy = NetworkPolicy.from_config(
        {
            "mode": "intranet",
            "allowed_hosts": ["*.cnki.net"],
            "insecure_tls_hosts": ["a.cnki.net"],
        }
    )
    assert policy.mode == NetworkMode.INTRANET
    assert policy.allowed_hosts == ("*.cnki.net",)
    assert policy.insecure_tls_hosts == ("a.cnki.net",)


def test_from_config_missing_fields_fall_back_to_defaults():
    policy = NetworkPolicy.from_config({})
    assert policy.mode == NetworkMode.ONLINE
    assert policy.allowed_hosts == ()


def test_from_config_invalid_mode_raises():
    with pytest.raises(ValueError, match="hypernet"):
        NetworkPolicy.from_config({"mode": "hypernet"})


@pytest.mark.parametrize("bad", [{"allowed_hosts": {"a": 1}}, {"allowed_hosts": "a.internal"}, {"allowed_hosts": [1]}])
def test_from_config_coerces_hosts_strictly(bad):
    with pytest.raises(TypeError):
        NetworkPolicy.from_config(bad)


def test_policy_is_frozen():
    import dataclasses

    policy = NetworkPolicy()
    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.mode = NetworkMode.OFFLINE  # type: ignore[misc]

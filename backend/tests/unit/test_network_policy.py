"""NetworkPolicy 领域模型单元测试。"""

import pytest

from backend.domain.network_policy import (
    NetworkMode,
    NetworkPolicy,
    host_matches,
    normalize_host,
)

pytestmark = [pytest.mark.unit]


def test_default_is_online_with_no_hosts():
    policy = NetworkPolicy()
    assert policy.mode is NetworkMode.ONLINE
    assert policy.allowed_hosts == ()
    assert policy.insecure_tls_hosts == ()


def test_normalize_host_lowercases_and_strips_trailing_dot():
    assert normalize_host("A.CNKI.NET.") == "a.cnki.net"
    assert normalize_host("  Docs.Example.Internal  ") == "docs.example.internal"


def test_host_matches_exact():
    assert host_matches("docs.example.internal", "docs.example.internal") is True
    assert host_matches("other.example.internal", "docs.example.internal") is False


def test_host_matches_wildcard_covers_apex_and_all_depths():
    assert host_matches("cnki.net", "*.cnki.net") is True
    assert host_matches("a.cnki.net", "*.cnki.net") is True
    assert host_matches("b.a.cnki.net", "*.cnki.net") is True


def test_host_matches_wildcard_rejects_suffix_confusion():
    # evilcnki.net 不是 cnki.net 的子域，不能因字符串后缀相同就命中
    assert host_matches("evilcnki.net", "*.cnki.net") is False


@pytest.mark.parametrize("bad", ["*", "*.net", "*.", "*.internal", "a.*.net", "*cnki.net"])
def test_overbroad_or_malformed_wildcard_is_rejected(bad):
    with pytest.raises(ValueError, match="通配"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=(bad,))


def test_empty_host_entry_is_rejected():
    with pytest.raises(ValueError, match="不能为空"):
        NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("   ",))


def test_multi_label_wildcard_apex_is_accepted():
    policy = NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("*.a.b.c",))
    assert policy.check_host("https://x.a.b.c/p") is None


def test_insecure_tls_host_must_be_covered_by_allowed_hosts():
    with pytest.raises(ValueError, match="insecure_tls_hosts"):
        NetworkPolicy(
            mode=NetworkMode.INTRANET,
            allowed_hosts=("docs.example.internal",),
            insecure_tls_hosts=("other.example.internal",),
        )


def test_insecure_tls_host_covered_by_wildcard_is_accepted():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET,
        allowed_hosts=("*.example.internal",),
        insecure_tls_hosts=("docs.example.internal",),
    )
    assert policy.allows_insecure_tls("https://docs.example.internal/a") is True
    assert policy.allows_insecure_tls("https://other.internal/a") is False


def test_search_enabled_only_in_online():
    assert NetworkPolicy(mode=NetworkMode.ONLINE).search_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.INTRANET).search_enabled() is False
    assert NetworkPolicy(mode=NetworkMode.OFFLINE).search_enabled() is False


def test_fetch_enabled_in_online_and_intranet():
    assert NetworkPolicy(mode=NetworkMode.ONLINE).fetch_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.INTRANET).fetch_enabled() is True
    assert NetworkPolicy(mode=NetworkMode.OFFLINE).fetch_enabled() is False


def test_check_host_online_always_allows_ignoring_allowed_hosts():
    policy = NetworkPolicy(mode=NetworkMode.ONLINE, allowed_hosts=("only.example.internal",))
    assert policy.check_host("https://anything.example.com/p") is None


def test_check_host_intranet_allows_whitelisted():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET, allowed_hosts=("*.example-mirror.internal",)
    )
    assert policy.check_host("https://a.example-mirror.internal/p") is None


def test_check_host_intranet_rejects_non_whitelisted():
    policy = NetworkPolicy(
        mode=NetworkMode.INTRANET, allowed_hosts=("*.example-mirror.internal",)
    )
    reason = policy.check_host("https://evil.example.com/p")
    assert reason is not None
    assert "白名单" in reason


def test_check_host_intranet_with_empty_whitelist_rejects_everything():
    policy = NetworkPolicy(mode=NetworkMode.INTRANET)
    assert policy.check_host("https://anything.internal/p") is not None


def test_check_host_offline_rejects():
    policy = NetworkPolicy(mode=NetworkMode.OFFLINE, allowed_hosts=("a.internal",))
    assert policy.check_host("https://a.internal/p") is not None


def test_check_host_rejects_url_without_hostname():
    policy = NetworkPolicy(mode=NetworkMode.INTRANET, allowed_hosts=("a.internal",))
    assert policy.check_host("not-a-url") is not None


def test_from_config_reads_all_fields():
    policy = NetworkPolicy.from_config(
        {
            "mode": "intranet",
            "allowed_hosts": ["*.example.internal"],
            "insecure_tls_hosts": ["docs.example.internal"],
        }
    )
    assert policy.mode is NetworkMode.INTRANET
    assert policy.allowed_hosts == ("*.example.internal",)
    assert policy.insecure_tls_hosts == ("docs.example.internal",)


def test_from_config_missing_fields_fall_back_to_defaults():
    policy = NetworkPolicy.from_config({})
    assert policy.mode is NetworkMode.ONLINE
    assert policy.allowed_hosts == ()


def test_from_config_rejects_unknown_mode():
    with pytest.raises(ValueError, match="NetworkMode"):
        NetworkPolicy.from_config({"mode": "carrier-pigeon"})


@pytest.mark.parametrize("bad", [42, {"a": 1}, "docs.example.internal"])
def test_from_config_rejects_non_list_host_field(bad):
    """裸字符串也要拒：tuple("a.b") 会拆成单字符元组，静默污染白名单。"""
    with pytest.raises(TypeError, match="allowed_hosts"):
        NetworkPolicy.from_config({"allowed_hosts": bad})


def test_from_config_rejects_non_string_host_entry():
    with pytest.raises(TypeError, match="条目"):
        NetworkPolicy.from_config({"allowed_hosts": ["ok.internal", 5]})

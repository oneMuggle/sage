"""Unit tests for backend/services/arena_proxies.py (P2).

No network: HTTP calls run over httpx.MockTransport; relay interactions use
the module's local_proxy() seam (upstream URLs point at unroutable hosts —
alive/exit_ip tests inject transports).
"""

import httpx
import pytest

from backend.services import arena_proxies as ap
from backend.services.arena_proxies import (
    ArenaProxyError,
    ProxyApi,
    ProxyPool,
    ProxyProvider,
    display_proxy,
    proxy_sid,
    rebind,
)

# ── 4 格式凭据解析 ────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gw.example.com:8080:user:pass", ("gw.example.com", "8080", "user", "pass")),
        ("user:pass:gw.example.com:8080", ("gw.example.com", "8080", "user", "pass")),
        ("user:pass@gw.example.com:8080", ("gw.example.com", "8080", "user", "pass")),
        ("gw.example.com:8080@user:pass", ("gw.example.com", "8080", "user", "pass")),
        ("1.2.3.4:3128", ("1.2.3.4", "3128", "", "")),
    ],
)
def test_split_credentials_four_formats(raw, expected):
    assert ProxyPool.split_credentials(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "not-a-proxy", "host:port", "a:b:c:d:e", "host:99999:user:pass"],
)
def test_split_credentials_rejects_garbage(raw):
    assert ProxyPool.split_credentials(raw) is None


def test_split_credentials_ambiguous_prefers_host_port_first():
    # both readings valid (x.com:80:1.2.3.4:9090): first wins like the reference
    assert ProxyPool.split_credentials("x.com:80:1.2.3.4:9090") == (
        "x.com", "80", "1.2.3.4", "9090",
    )


# ── ProxyPool ─────────────────────────────────────────────────────────

def test_pool_parse_normalize_dedupe_and_errors():
    pool = ProxyPool(
        "gw1.example.com:8080:u1:p1\n"
        "u2:p2@gw2.example.com:8080, gw1.example.com:8080:u1:p1\n"
        ";;;   \n"
        "broken-line\t"
        "gw3.example.com:8080",
        protocol="http",
    )
    assert pool.count() == 3
    items = pool.items()
    assert items[0] == "http://u1:p1@gw1.example.com:8080"
    assert items[1] == "http://u2:p2@gw2.example.com:8080"
    assert items[2] == "http://gw3.example.com:8080"
    assert len(pool.errors) == 1
    assert "第 4 条" in pool.errors[0]  # deduped dup still consumed a line number
    assert pool.enabled() is True


def test_pool_url_passthrough_and_socks_protocol():
    pool = ProxyPool("socks5://u:p@1.2.3.4:1080 1.2.3.4:1080", protocol="socks5")
    items = pool.items()
    assert items[0] == "socks5://u:p@1.2.3.4:1080"
    assert items[1] == "socks5://1.2.3.4:1080"  # protocol param applied


def test_pool_rejects_bad_scheme():
    pool = ProxyPool("ftp://1.2.3.4:21")
    assert pool.count() == 0
    assert "协议" in pool.errors[0]


def test_pool_next_sequential_and_random():
    pool = ProxyPool("a.example:1 b.example:2 c.example:3")
    assert pool.next() == "http://a.example:1"
    assert pool.next() == "http://b.example:2"
    assert pool.next() == "http://c.example:3"
    assert pool.next() == "http://a.example:1"  # wraps

    rnd = ProxyPool("a.example:1 b.example:2", order="random")
    for _ in range(10):
        assert rnd.next() in rnd.items()


def test_pool_empty_next_raises():
    pool = ProxyPool("")
    assert pool.enabled() is False
    with pytest.raises(ArenaProxyError, match="代理池为空"):
        pool.next()


# ── ProxyApi 三形态 ────────────────────────────────────────────────────

def _api_with(handler):
    return ProxyApi(token="tok", transport=httpx.MockTransport(handler))


def test_api_fetch_dict_shape():
    api = _api_with(
        lambda req: httpx.Response(200, json={"success": True, "data": [{"ip": "1.2.3.4", "port": 8080}]})
    )
    assert api.fetch() == "http://1.2.3.4:8080"


def test_api_fetch_list_shape():
    api = _api_with(
        lambda req: httpx.Response(200, json={"success": True, "data": [["5.6.7.8", 3128]]})
    )
    assert api.fetch() == "http://5.6.7.8:3128"


def test_api_fetch_str_shape_and_socks():
    api = _api_with(
        lambda req: httpx.Response(200, json={"success": True, "data": "9.9.9.9:1080"})
    )
    api.protocol = "socks5"
    assert api.fetch() == "socks5://9.9.9.9:1080"


def test_api_fetch_error_payload():
    api = _api_with(lambda req: httpx.Response(200, json={"success": False, "msg": "quota"}))
    with pytest.raises(ArenaProxyError, match="代理接口失败"):
        api.fetch()


def test_api_fetch_non_json():
    api = _api_with(lambda req: httpx.Response(502, text="bad gateway"))
    with pytest.raises(ArenaProxyError, match="非 JSON"):
        api.fetch()


def test_api_requires_token():
    with pytest.raises(ArenaProxyError, match="Token 未填写"):
        ProxyApi(token="").fetch()


# ── 探测 / sid / rebind ───────────────────────────────────────────────

def test_exit_ip_and_fallback_display():
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url).startswith("https://api.ipify.org")
        return httpx.Response(200, json={"ip": "203.0.113.7"})

    assert ap.proxy_exit_ip("http://u:p@1.2.3.4:8080", transport=httpx.MockTransport(handler)) == "203.0.113.7"
    assert ap.proxy_exit_ip("") == "直连"
    # echo fails → falls back to showing the proxy host
    assert ap.proxy_exit_ip(
        "http://u:p@gw.example.com:8080", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    ) == "gw.example.com:8080"


def test_alive_lenient_dual_endpoint():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if "ipify" in str(request.url):
            return httpx.Response(503)  # transient failure on the first endpoint
        return httpx.Response(200, text="1.2.3.4")

    assert ap.proxy_alive("http://1.2.3.4:8080", transport=httpx.MockTransport(handler)) is True
    assert calls["n"] == 2
    assert ap.proxy_alive("") is True  # direct counts as alive
    assert ap.proxy_alive(
        "http://1.2.3.4:8080", transport=httpx.MockTransport(lambda r: httpx.Response(500))
    ) is False


def test_direct_exit_ip():
    def handler(request: httpx.Request) -> httpx.Response:
        if "ipify" in str(request.url):
            return httpx.Response(200, json={"ip": "198.51.100.9"})
        return httpx.Response(200, text="198.51.100.9")

    assert ap.direct_exit_ip(transport=httpx.MockTransport(handler)) == "198.51.100.9"
    assert ap.direct_exit_ip(transport=httpx.MockTransport(lambda r: httpx.Response(500))) == ""


def test_proxy_sid_and_rebind():
    url = "http://cust123-sid-Ab12Cd:pw@gw.example.com:8080"
    assert proxy_sid(url) == "Ab12Cd"
    assert proxy_sid("http://1.2.3.4:8080") == ""

    fresh = "gw.example.com:8080:cust999-sid-Ab12Cd:newpw\ngw.example.com:8080:other-sid-Zz9:pw"
    assert rebind(url, fresh) == "http://cust999-sid-Ab12Cd:newpw@gw.example.com:8080"
    assert rebind(url, "gw.example.com:8080:other-sid-Zz9:pw") == url  # sid gone → keep
    assert rebind("http://1.2.3.4:8080", fresh) == "http://1.2.3.4:8080"  # no sid


def test_display_proxy_masks_credentials():
    assert display_proxy("http://user:secret@1.2.3.4:8080") == "http://user:***@1.2.3.4:8080"
    assert display_proxy("http://1.2.3.4:8080") == "http://1.2.3.4:8080"
    assert display_proxy("") == ""


# ── ProxyProvider 门面 ─────────────────────────────────────────────────

def _provider(pool_text="", api=None, rotation="per_account"):
    pool = ProxyPool(pool_text) if pool_text else None
    return ProxyProvider(pool=pool, api=api, rotation=rotation)


def test_provider_pool_priority_over_api():
    api = _api_with(
        lambda req: httpx.Response(200, json={"success": True, "data": [{"ip": "9.9.9.9", "port": 3128}]})
    )
    provider = _provider(pool_text="a.example:1 b.example:2", api=api)
    assert provider.acquire() == "http://a.example:1"  # pool first
    assert provider.acquire() == "http://b.example:2"


def test_provider_falls_back_to_api():
    api = _api_with(
        lambda req: httpx.Response(200, json={"success": True, "data": [{"ip": "9.9.9.9", "port": 3128}]})
    )
    provider = _provider(api=api)
    assert provider.acquire() == "http://9.9.9.9:3128"


def test_provider_no_source_raises():
    with pytest.raises(ArenaProxyError, match="没有可用代理"):
        _provider().acquire()


def test_provider_exclude_sids():
    pool_text = (
        "gw.example.com:8080:u1-sid-AAA:p1\n"
        "gw.example.com:8080:u2-sid-BBB:p2\n"
        "gw.example.com:8080:u3-sid-CCC:p3"
    )
    provider = _provider(pool_text=pool_text)
    assert provider.acquire(exclude_sids={"AAA"}) == "http://u2-sid-BBB:p2@gw.example.com:8080"
    assert provider.acquire(exclude_sids={"AAA", "BBB"}) == "http://u3-sid-CCC:p3@gw.example.com:8080"
    with pytest.raises(ArenaProxyError, match="全部被排除"):
        provider.acquire(exclude_sids={"AAA", "BBB", "CCC"})


def test_provider_blacklist_quarantine():
    pool_text = "a.example:1:u-sid-AAA:p\nb.example:2:u-sid-BBB:p"
    provider = _provider(pool_text=pool_text)
    aaa = "http://u-sid-AAA:p@a.example:1"
    bbb = "http://u-sid-BBB:p@b.example:2"
    assert provider.acquire() == aaa
    provider.mark_bad(aaa, seconds=60)
    assert provider.acquire() == bbb
    provider.mark_bad(bbb, seconds=60)
    with pytest.raises(ArenaProxyError, match="全部被排除或拉黑"):
        provider.acquire()


def test_provider_blacklist_expiry():
    import time

    provider = _provider(pool_text="a.example:1:u-sid-AAA:p\nb.example:2:u-sid-BBB:p")
    aaa = "http://u-sid-AAA:p@a.example:1"
    provider.mark_bad(aaa, seconds=0.05)
    assert provider.acquire() == "http://u-sid-BBB:p@b.example:2"
    time.sleep(0.08)
    # cursor wrapped back to a; the blacklist expired → a is usable again
    assert provider.acquire() == aaa


def test_provider_per_wave_rotation():
    pool_text = "a.example:1\nb.example:2\nc.example:3"
    provider = _provider(pool_text=pool_text, rotation="per_wave")
    first = provider.acquire()
    assert first == "http://a.example:1"
    assert provider.acquire() == first  # same proxy within the wave
    provider.next_wave()
    assert provider.acquire() == "http://b.example:2"
    assert provider.acquire() == "http://b.example:2"


def test_provider_from_config():
    class Cfg:
        enabled = True
        pool_text = "a.example:1"
        api_url = ""
        api_token = ""
        country = ""
        protocol = "http"
        rotation = "per_account"
        order = "sequential"

    provider = ap.provider_from_config(Cfg())
    assert provider is not None
    assert provider.acquire() == "http://a.example:1"

    Cfg.enabled = False
    assert ap.provider_from_config(Cfg()) is None

    Cfg.enabled = True
    Cfg.pool_text = ""
    assert ap.provider_from_config(Cfg()) is None  # no pool AND no api

"""academic_adapters 单元测试。

覆盖:
1. CNKIAdapter.build_search_url() —— URL BASE / query 编码 / limit 生效
2. get_site_adapter("cnki") 命中,未知名抛 ValueError 列出可用项
3. register_site_adapter() 注入自定义 adapter,再用 get_site_adapter 取回
4. (经 AcademicSearchSkill.execute() 间接验证) AcademicSiteAdapter Protocol
   对真实实现类的 isinstance 检查通过
"""

from __future__ import annotations

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from backend.skills.builtin.academic_adapters import (
    CNKIAdapter,
    get_site_adapter,
    register_site_adapter,
)

pytestmark = pytest.mark.unit


# ============================================================================
# 1. CNKIAdapter.build_search_url
# ============================================================================


class TestCNKIAdapter:
    def test_build_url_uses_cnki_old_endpoint(self):
        url = CNKIAdapter().build_search_url("大语言模型 综述")
        parsed = urlparse(url)
        assert parsed.scheme == "https"
        assert parsed.netloc == "www.cnki.net"
        assert parsed.path == "/old/kns/brief/default_result.aspx"

    def test_build_url_encodes_query_chinese(self):
        url = CNKIAdapter().build_search_url("深度学习 综述")
        qs = parse_qs(urlparse(url).query)
        assert qs["Txt"] == ["深度学习 综述"]

    def test_build_url_default_limit_is_10(self):
        url = CNKIAdapter().build_search_url("机器学习")
        qs = parse_qs(urlparse(url).query)
        assert qs["t"] == ["10"]

    def test_build_url_respects_explicit_limit(self):
        url = CNKIAdapter().build_search_url("机器学习", limit=20)
        qs = parse_qs(urlparse(url).query)
        assert qs["t"] == ["20"]

    def test_build_url_has_required_cnki_params(self):
        url = CNKIAdapter().build_search_url("foo")
        qs = parse_qs(urlparse(url).query)
        assert qs["QueryID"] == ["0"]
        assert qs["PageName"] == ["ASP.brief_result_aspx"]
        assert qs["DbPrefix"] == ["SCDB"]
        assert qs["research"] == ["off"]


# ============================================================================
# 2. get_site_adapter / register_site_adapter
# ============================================================================


class TestAdapterRegistry:
    def test_get_known_adapter_returns_instance(self):
        adapter = get_site_adapter("cnki")
        assert isinstance(adapter, CNKIAdapter)
        assert adapter.name == "cnki"

    def test_get_unknown_adapter_raises_value_error_with_available(self):
        with pytest.raises(ValueError, match="pubmed"):
            get_site_adapter("pubmed")
        # 错误信息里也列出可用站点
        with pytest.raises(ValueError, match="cnki"):
            get_site_adapter("pubmed")

    def test_register_new_adapter_makes_it_resolvable(self):
        class _FakeAdapter:
            name = "test-fake"

            def build_search_url(self, query: str, **kwargs: Any) -> str:
                return f"https://test.example/search?q={query}"

        try:
            register_site_adapter(_FakeAdapter())  # type: ignore[arg-type]
            adapter = get_site_adapter("test-fake")
            url = adapter.build_search_url("hello")
            assert url == "https://test.example/search?q=hello"
        finally:
            # 清理:从 _DEFAULT_ADAPTERS 移除,避免污染其他测试
            from backend.skills.builtin import academic_adapters

            academic_adapters._DEFAULT_ADAPTERS.pop("test-fake", None)


# ============================================================================
# 3. AcademicSiteAdapter Protocol 的运行时检查
# ============================================================================


def test_cnki_adapter_satisfies_protocol():
    from backend.skills.builtin.academic_adapters import AcademicSiteAdapter

    assert isinstance(CNKIAdapter(), AcademicSiteAdapter)

"""``backend.api.llm_proxy_routes.build_upstream_url`` 纯函数单元测试。

设计背景:
  - 用户在「端点」UI 输入 baseURL(常见: ``https://api.openai.com/v1``)
  - 前端 ``fetchModels`` 固定请求 ``/v1/models``
  - 后端代理要把 baseURL + path 拼成上游 URL
  - 若 baseURL 已含 ``/v1`` 后缀,path 又以 ``/v1`` 开头,会拼成
    ``.../v1/v1/models`` 触发上游 404 (Invalid URL)。

修复策略(方案 A):
  在 ``build_upstream_url(provider_url, path)`` 里:
    1. 归一化 provider_url(去末尾 ``/``)
    2. 归一化 path(``posixpath.normpath('/' + path.lstrip('/'))``)
    3. 若 provider_url 以 ``/v1`` 结尾,且 normalized path 以 ``/v1/`` 开头
       (或 path == ``/v1``),剥掉 path 前导的 ``/v1`` 段。

覆盖场景:
  - 用户填 baseURL 含 ``/v1`` + 前端拉模型列表 → 不能变成 ``/v1/v1/models``
  - 用户填裸 host + 前端拉模型列表 → 行为不变(向后兼容)
  - 用户填 baseURL 含 ``/v1`` + 自定义 path(非 /v1) → path 应原样保留
  - query string 应原样附加
"""

from __future__ import annotations

from backend.api.llm_proxy_routes import build_upstream_url

# === RED 核心场景:用户最常见的配置 ===


def test_provider_url_with_v1_suffix_and_v1_models_path_does_not_duplicate():
    """用户填 ``https://apihub.agnes-ai.com/v1`` + 拉 ``/v1/models`` → 不能产生 ``/v1/v1/models``。

    这是用户当前报错: ``Invalid URL (GET /v1/v1/models)``。
    """
    url = build_upstream_url(
        provider_url="https://apihub.agnes-ai.com/v1",
        path="v1/models",
    )

    assert url == "https://apihub.agnes-ai.com/v1/models"


def test_provider_url_with_v1_suffix_and_chat_completions_path_does_not_duplicate():
    """同样的去重要对 ``/v1/chat/completions`` 生效。"""
    url = build_upstream_url(
        provider_url="https://api.openai.com/v1/",
        path="v1/chat/completions",
    )

    assert url == "https://api.openai.com/v1/chat/completions"


# === 向后兼容:裸 host 不能被新逻辑破坏 ===


def test_bare_host_provider_url_with_v1_models_path_still_works():
    """兼容已有集成测试 ``UPSTREAM = 'http://upstream.example.com'``(裸 host)。"""
    url = build_upstream_url(
        provider_url="http://upstream.example.com",
        path="v1/models",
    )

    assert url == "http://upstream.example.com/v1/models"


# === 非 /v1 路径:不应被错误剥前缀 ===


def test_provider_url_with_v1_suffix_and_non_v1_path_preserves_path():
    """若 path 不是 ``/v1`` 开头,即使 baseURL 含 ``/v1`` 也不应去重。"""
    url = build_upstream_url(
        provider_url="https://example.com/v1",
        path="custom/models",
    )

    assert url == "https://example.com/v1/custom/models"


# === query string ===


def test_query_string_is_appended():
    url = build_upstream_url(
        provider_url="https://api.openai.com/v1",
        path="v1/models",
        query="limit=10&after=foo",
    )

    assert url == "https://api.openai.com/v1/models?limit=10&after=foo"

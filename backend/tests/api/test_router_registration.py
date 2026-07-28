"""
路由注册回归测试

检测 app 上重复的 (methods, path) 路由注册，防止同一 router 被
``app.include_router`` 多次（M0 清理：wiki_router 曾被重复注册于
main.py:347-348）。

FastAPI ≥0.138 把 ``include_router`` 的 router 惰性包装为
``_IncludedRouter``（不出现在 app.routes 的 APIRoute 列表中），
因此这里递归展开包装后再做重复检测；旧版直接平铺 APIRoute 的
行为同样兼容。
"""

from collections import Counter

import pytest
from fastapi.routing import APIRoute

from backend.main import app

pytestmark = pytest.mark.unit


def _iter_effective_routes(routes, prefix=""):
    """扁平化路由列表：展开 ``_IncludedRouter`` 惰性包装为具体路由。

    Yields:
        ``(route, 累积前缀)`` 二元组。
    """
    for route in routes:
        if type(route).__name__ == "_IncludedRouter":
            context = getattr(route, "include_context", None)
            sub_prefix = (getattr(context, "prefix", "") or "") if context is not None else ""
            sub_router = getattr(route, "original_router", None)
            if sub_router is not None:
                yield from _iter_effective_routes(
                    sub_router.routes, prefix + sub_prefix
                )
        else:
            yield route, prefix


def _effective_key(route, prefix):
    """构造路由唯一键：(排序后的 methods 元组, 含前缀的完整 path)。"""
    return (tuple(sorted(route.methods or [])), prefix + route.path)


def test_no_duplicate_route_registrations():
    """app 中不应出现两个相同的 (methods, path) 注册。"""
    # Arrange
    counts = Counter(
        _effective_key(route, prefix)
        for route, prefix in _iter_effective_routes(app.routes)
        if isinstance(route, APIRoute)
    )
    # 扁平化健全性：至少应解析出 /health，防止内部结构变化导致静默通过
    assert counts, "路由扁平化失败：未解析出任何 APIRoute（检查 FastAPI 版本兼容性）"

    # Act
    duplicates = [
        (methods, path, count)
        for (methods, path), count in counts.items()
        if count > 1
    ]

    # Assert
    assert not duplicates, (
        f"检测到重复路由注册 (methods, path, 出现次数): {duplicates}"
    )

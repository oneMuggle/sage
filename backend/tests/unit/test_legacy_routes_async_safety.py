"""§1.2 修复配套测试 — 静态扫描 legacy_routes.py 的 async def handler 是否有 await。

背景：PR #294 §1.2 把 45 个 async handler 中 34 个无 await 的降级为 def。
本测试强制：所有顶层 `async def` 路由函数必须至少有一个 `await` 调用。
如果未来有人把有 await 的 async handler 误降级为 def,本测试会失败。

Why: FastAPI 对 `async def` handler 跑在事件循环线程,内部 sync 调用会阻塞同 loop 的
所有并发请求。对无 await 的纯同步 handler,降级为 `def` 让 FastAPI 自动用 threadpool。

How to apply: 当需要新增 async def handler 时,确保函数体内真的有 await 调用。
本测试仅检查 `async def`,不阻止 `def`(包括内部 helper)。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

# `async def` 但无 await 的 handler 是事件循环阻塞风险点。
# 本测试维护一份"必须 keep_async"的精确白名单(7 个,L580/L974/1015/1105/1284/1400/1763)。
# 所有其他 async def 必须有 await,否则应降级为 def。
KEEP_ASYNC_HANDLERS = frozenset(
    {
        "compact_session",  # L580 — M4 manual compact,内调 LLM
        "execute_skill",  # L974 — skill 执行,内调 LLM
        "execute_slash_command",  # L1015 — slash 命令,内调 LLM
        "import_skills",  # L1105 — 文件上传,内调 LLM
        "chat",  # L1284 — 主 chat 端点,内调 LLM 流
        "chat_stream_create",  # L1400 — SSE 流,内调 LLM 流
        "chat_stream_attach",  # L1763 — SSE 续接,内调事件流
    }
)


def _load_top_level_functions(src: str) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    """加载模块顶层函数定义。"""
    tree = ast.parse(src)
    return [
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    ]


def _has_await(func: ast.AsyncFunctionDef) -> bool:
    """检查 async 函数体内是否含 await 调用。"""
    return any(isinstance(node, ast.Await) for node in ast.walk(func))


def _is_router_endpoint(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """判断是否为 FastAPI 路由端点（顶层函数）。

    排除条件：函数名以 `_` 开头（私有 helper,不是 FastAPI 路由）。
    装饰器识别：扫描 @router.get/.post/.put/.delete/.patch 等。
    """
    if func.name.startswith("_"):
        return False
    for dec in func.decorator_list:
        if isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute):
            method = dec.func.attr
            if method in ("get", "post", "put", "delete", "patch"):
                return True
    return False


def test_async_handlers_must_have_await():
    """所有 async def 路由函数必须含至少一个 await,否则应降级为 def。"""
    src_path = Path("backend/api/legacy_routes.py")
    src = src_path.read_text(encoding="utf-8")
    funcs = _load_top_level_functions(src)

    async_endpoints = [
        f for f in funcs if isinstance(f, ast.AsyncFunctionDef) and _is_router_endpoint(f)
    ]

    # 找出无 await 的 async def — 应当为空集合（除非在白名单内）
    violations = [(f.name, f.lineno) for f in async_endpoints if not _has_await(f)]

    # 过滤白名单(7 个 keep_async handlers 实际都有 await — 白名单是冗余防御)
    real_violations = [(n, ln) for n, ln in violations if n not in KEEP_ASYNC_HANDLERS]

    assert not real_violations, (
        f"发现 {len(real_violations)} 个 async def handler 无 await — 应降级为 def:\n"
        + "\n".join(f"  {name} (line {ln})" for name, ln in real_violations)
    )


def test_keep_async_handlers_actually_async():
    """白名单中的 handler 必须是 async def。防止有人误降级它们。

    防御性:如果有人把 compact_session/chat/chat_stream_create 等改成 def,
    SSE/Stream 端点会立即失效。本测试守住这一边界。
    """
    src_path = Path("backend/api/legacy_routes.py")
    src = src_path.read_text(encoding="utf-8")
    funcs = _load_top_level_functions(src)
    name_to_func = {f.name: f for f in funcs}

    for keep_name in KEEP_ASYNC_HANDLERS:
        func = name_to_func.get(keep_name)
        assert func is not None, f"白名单 handler 不存在: {keep_name}"
        assert isinstance(func, ast.AsyncFunctionDef), (
            f"白名单 handler 应为 async def,实际是 def: {keep_name} (line {func.lineno})"
        )


def test_async_handler_count_matches_design():
    """legacy_routes.py 应有 7 个 async def handler(PR #294 §1.2 修复后)。"""
    src_path = Path("backend/api/legacy_routes.py")
    src = src_path.read_text(encoding="utf-8")
    funcs = _load_top_level_functions(src)
    async_endpoints = [
        f for f in funcs if isinstance(f, ast.AsyncFunctionDef) and _is_router_endpoint(f)
    ]

    # 修复后:7 个 keep_async (compact_session, execute_skill, execute_slash_command,
    # import_skills, chat, chat_stream_create, chat_stream_attach)
    assert len(async_endpoints) == 7, (
        f"legacy_routes 应有 7 个 async def handler,实际 {len(async_endpoints)}:\n"
        + "\n".join(f"  {f.name} (line {f.lineno})" for f in async_endpoints)
    )


def test_async_handlers_count_invariant_against_internal_helpers():
    """顶层 async def 之外的内部 helper (producer/event_generator) 不算路由。

    设计意图:chat_stream_create 内部定义 `async def producer()` 等 helper,
    这些 helper 不是 FastAPI 路由,统计时必须排除掉。
    """
    src_path = Path("backend/api/legacy_routes.py")
    src = src_path.read_text(encoding="utf-8")
    funcs = _load_top_level_functions(src)
    async_endpoints = [
        f for f in funcs if isinstance(f, ast.AsyncFunctionDef) and _is_router_endpoint(f)
    ]
    # 同样 7 个,跟 test_async_handler_count_matches_design 一致
    assert len(async_endpoints) == 7


if __name__ == "__main__":
    # 允许 `python backend/tests/unit/test_legacy_routes_async_safety.py` 直接跑
    pytest.main([__file__, "-v"])

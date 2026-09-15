"""
asyncio_compat.py — Python 3.8 asyncio 兼容垫片

``asyncio.to_thread`` 是 Python 3.9+ 新增 API；main 分支的 storage /
inproc tool / memory 适配层全部直接调用它。为了让 release/win7 与 main
共享同一份源码（而不是每处都改成 ``loop.run_in_executor``），这里在
py3.8 运行时把与 CPython 3.9 实现等价的 ``to_thread`` 注入 ``asyncio``。

py3.9+ 下 ``install()`` 是 no-op。
"""
import asyncio
import contextvars
import functools


async def to_thread(func, /, *args, **kwargs):  # type: ignore[no-untyped-def]
    """CPython 3.9 ``asyncio.to_thread`` 的逐行等价实现（含 contextvars 传播）。"""
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    func_call = functools.partial(ctx.run, func, *args, **kwargs)
    return await loop.run_in_executor(None, func_call)


def install() -> bool:
    """py3.8: 注入 ``asyncio.to_thread``；已存在则不动。返回是否执行了注入。"""
    if hasattr(asyncio, "to_thread"):
        return False
    asyncio.to_thread = to_thread  # type: ignore[attr-defined]
    return True


__all__ = ["to_thread", "install"]

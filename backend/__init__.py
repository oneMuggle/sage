
# Win7 (py3.8 + pydantic 1.x) 兼容垫片；pydantic 2.x 下 no-op。
try:
    from backend.compat.win7 import pydantic_compat as _pc

    _pc.install()
except Exception:  # pragma: no cover
    pass

# Win7 (py3.8) 兼容垫片：注入 asyncio.to_thread（3.9+ API）；py3.9+ 下 no-op。
try:
    from backend.compat.win7 import asyncio_compat as _ac

    _ac.install()
except Exception:  # pragma: no cover
    pass

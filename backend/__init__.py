
# Win7 (py3.8 + pydantic 1.x) 兼容垫片；pydantic 2.x 下 no-op。
try:
    from backend.compat.win7 import pydantic_compat as _pc

    _pc.install()
except Exception:  # pragma: no cover
    pass

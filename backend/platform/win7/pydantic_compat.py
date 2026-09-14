"""
pydantic_compat.py — pydantic 1.x (win7) / 2.x (main) 兼容垫片

在 win7 分支 Python 3.8 只能用 pydantic 1.10.13；
main 分支用 pydantic 2.5.0。两者 API 差异：
  - BaseModel: 1.x 用 Config, 2.x 用 model_config
  - validator: 1.x @validator, 2.x @field_validator
  - .dict() vs .model_dump()

本模块提供最小兼容层，让业务代码 `from platform.win7.pydantic_compat import BaseModelCompat`
即可在两分支同源。
"""
try:
    import pydantic
    PYDANTIC_V2 = int(pydantic.__version__.split(".")[0]) >= 2
except Exception:
    PYDANTIC_V2 = False

if PYDANTIC_V2:
    from pydantic import BaseModel as BaseModelCompat  # type: ignore
    from pydantic import field_validator  # type: ignore
    def model_to_dict(m):
        return m.model_dump()
else:
    from pydantic import BaseModel as BaseModelCompat  # type: ignore
    # 1.x 兼容：field_validator 回退到 validator
    try:
        from pydantic import validator as field_validator  # type: ignore
    except Exception:  # pragma: no cover
        field_validator = lambda *a, **kw: (lambda f: f)  # noqa: E731
    def model_to_dict(m):
        return m.dict()

__all__ = ["BaseModelCompat", "field_validator", "model_to_dict", "PYDANTIC_V2"]

"""
pydantic_compat.py — pydantic 1.x (win7 / py3.8) ↔ 2.x (main) 兼容垫片。

win7 分支锁定 Python 3.8.10 → 只能用 pydantic 1.10.13；main 用 2.5。
本模块在 **pydantic 1.x 运行时** 把 v2 的常用 API 以 monkey-patch 方式
挂到 BaseModel 上，使 main 的业务代码（model_dump / model_validate /
model_copy / ConfigDict / field_validator …）无需改写即可在 win7 运行。

在 pydantic 2.x 下本模块是空操作（no-op），因此 main ↔ win7 可共享同一份源码。

用法（任何使用 v2 API 的包在 __init__ 顶部）::

    from backend.compat.win7 import pydantic_compat  # noqa: F401
    pydantic_compat.install()

设计约束：
- 幂等：重复 install() 无副作用；
- 零 docx / fastapi 依赖：可被 scripts/verify-office-paths.py canary 导入；
- 不覆盖已存在属性：若未来 pydantic 1.x 自带同名方法则保留原实现。
"""
from __future__ import annotations

import json
from typing import Any, Dict

try:
    import pydantic
    from pydantic import BaseModel

    PYDANTIC_V2 = int(pydantic.VERSION.split(".")[0]) >= 2
except Exception:  # pragma: no cover - pydantic 缺失时保持可导入
    pydantic = None  # type: ignore
    BaseModel = object  # type: ignore
    PYDANTIC_V2 = False

_INSTALLED = False


# ── v2 → v1 name shims ──────────────────────────────────────────────────
if PYDANTIC_V2:
    from pydantic import ConfigDict, field_validator, model_validator  # type: ignore
else:
    from pydantic import root_validator as _root_validator  # type: ignore
    from pydantic import validator as _validator  # type: ignore

    def ConfigDict(**kwargs: Any) -> Dict[str, Any]:  # type: ignore  # noqa: N802
        """v1 下返回普通 dict；配合 install() 的 metaclass 钩子生效。"""
        return dict(kwargs)

    def field_validator(*fields: str, **kw: Any):  # type: ignore
        mode = kw.pop("mode", "after")
        if mode == "before":
            kw["pre"] = True
        kw.setdefault("allow_reuse", True)
        return _validator(*fields, **kw)

    def model_validator(*, mode: str = "after", **kw: Any):  # type: ignore
        kw.setdefault("allow_reuse", True)
        if mode == "before":
            kw["pre"] = True
        return _root_validator(**kw)


def _model_dump(self: Any, *, mode: str = "python", **kw: Any) -> Dict[str, Any]:
    if mode == "json":
        return json.loads(self.json(**kw))
    return self.dict(**kw)


def _model_dump_json(self: Any, **kw: Any) -> str:
    kw.pop("indent", None)
    return self.json(**kw)


def _model_copy(self: Any, *, update: Any = None, deep: bool = False) -> Any:
    return self.copy(update=update, deep=deep)


@classmethod  # type: ignore[misc]
def _model_validate(cls: Any, obj: Any, **_: Any) -> Any:
    if isinstance(obj, cls):
        return obj
    return cls.parse_obj(obj)


@classmethod  # type: ignore[misc]
def _model_validate_json(cls: Any, data: Any, **_: Any) -> Any:
    return cls.parse_raw(data)


@classmethod  # type: ignore[misc]
def _model_json_schema(cls: Any, **kw: Any) -> Dict[str, Any]:
    return cls.schema(**kw)


def _model_fields(cls: Any) -> Dict[str, Any]:
    return getattr(cls, "__fields__", {})


def install() -> bool:
    """在 pydantic 1.x 上安装 v2 兼容方法。返回是否执行了安装。"""
    global _INSTALLED
    if PYDANTIC_V2 or _INSTALLED or pydantic is None:
        return False

    patches = {
        "model_dump": _model_dump,
        "model_dump_json": _model_dump_json,
        "model_copy": _model_copy,
        "model_validate": _model_validate,
        "model_validate_json": _model_validate_json,
        "model_json_schema": _model_json_schema,
    }
    for name, fn in patches.items():
        if not hasattr(BaseModel, name):
            setattr(BaseModel, name, fn)
    if not hasattr(BaseModel, "model_fields"):
        try:
            type(BaseModel).model_fields = property(_model_fields)  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            pass

    # `model_config = ConfigDict(extra="forbid")` 在 v1 下需要转成 class Config
    meta = type(BaseModel)
    if not getattr(meta, "_win7_model_config_hook", False):
        orig_new = meta.__new__

        def __new__(mcs, name, bases, namespace, **kwargs):  # type: ignore[no-untyped-def]
            cfg = namespace.pop("model_config", None)
            if isinstance(cfg, dict) and cfg and "Config" not in namespace:
                namespace["Config"] = type("Config", (), dict(cfg))
            return orig_new(mcs, name, bases, namespace, **kwargs)

        meta.__new__ = staticmethod(__new__)  # type: ignore[assignment]
        meta._win7_model_config_hook = True  # type: ignore[attr-defined]

    _INSTALLED = True
    return True


def model_to_dict(m: Any) -> Dict[str, Any]:
    """两分支通用的 dump 入口。"""
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()


BaseModelCompat = BaseModel

__all__ = [
    "PYDANTIC_V2",
    "BaseModelCompat",
    "ConfigDict",
    "field_validator",
    "model_validator",
    "model_to_dict",
    "install",
]

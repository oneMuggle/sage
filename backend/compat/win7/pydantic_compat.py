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

import contextlib
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
    from pydantic import (
        root_validator as _root_validator,  # type: ignore
        validator as _validator,  # type: ignore
    )

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
def _model_construct(cls: Any, **kwargs: Any) -> Any:
    """Pydantic v2 `BaseModel.model_construct(**kw)` → v1 `cls.construct(**kw)`.

    v1 的 `construct` 不跑 validator — 行为与 v2 `model_construct` 一致
    (v2 `__init__` 才会跑 validator, v2 `model_construct` 也跳过). 用于
    单元测试需要构造一个**故意绕过校验**的实例的场景 (例如注入非法
    Literal 值来验证运行时守卫).
    """
    return cls.construct(**kwargs)


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


def _validation_error_error_count(self: Any) -> int:
    """Pydantic v2 `ValidationError.error_count()` → v1 `len(self.errors())`.

    v1 的 ValidationError 没有 `.error_count()` 方法, 业务代码用
    `exc.error_count()` 在 v1 上 AttributeError. 这层 shim 装到
    `pydantic.ValidationError` 上, 跨版本统一返回错误条数.
    """
    errors = getattr(self, "errors", None)
    if callable(errors):
        return len(errors())
    return 0


def install() -> bool:
    """在 pydantic 1.x 上安装 v2 兼容方法。返回是否执行了安装。"""
    global _INSTALLED
    if PYDANTIC_V2 or _INSTALLED or pydantic is None:
        return False

    patches = {
        "model_dump": _model_dump,
        "model_dump_json": _model_dump_json,
        "model_copy": _model_copy,
        "model_construct": _model_construct,
        "model_validate": _model_validate,
        "model_validate_json": _model_validate_json,
        "model_json_schema": _model_json_schema,
    }
    for name, fn in patches.items():
        if not hasattr(BaseModel, name):
            setattr(BaseModel, name, fn)
    if not hasattr(BaseModel, "model_fields"):
        with contextlib.suppress(Exception):  # pragma: no cover
            type(BaseModel).model_fields = property(_model_fields)  # type: ignore[attr-defined]

    # `model_config = ConfigDict(extra="forbid")` 在 v1 下需要转成 class Config
    meta = type(BaseModel)
    if not getattr(meta, "_win7_model_config_hook", False):
        orig_new = meta.__new__

        def __new__(mcs, name, bases, namespace, **kwargs):  # type: ignore[no-untyped-def]  # noqa: N807 — 替换 metaclass.__new__
            cfg = namespace.pop("model_config", None)
            if isinstance(cfg, dict) and cfg and "Config" not in namespace:
                namespace["Config"] = type("Config", (), dict(cfg))
            return orig_new(mcs, name, bases, namespace, **kwargs)

        meta.__new__ = staticmethod(__new__)  # type: ignore[assignment]
        meta._win7_model_config_hook = True  # type: ignore[attr-defined]

    # ── Field(pattern=...) → regex= shim (v2 → v1) ─────────────────────
    # pydantic v1 的 Field 接受 regex= 而非 pattern=. v2 业务代码用 pattern=,
    # v1 下被吞进 **extra 元数据不验证. 这里 monkey-patch pydantic.Field
    # 把 pattern 转译成 regex, 必须在任何 model 导入前完成 (backend/__init__.py
    # 调 install() 时已经早于业务 model 导入).
    _orig_field = pydantic.Field

    def _field_shim(*args: Any, **kwargs: Any) -> Any:
        if "pattern" in kwargs:
            kwargs.setdefault("regex", kwargs.pop("pattern"))
        return _orig_field(*args, **kwargs)

    pydantic.Field = _field_shim  # type: ignore[assignment]

    _INSTALLED = True

    # ── ValidationError.error_count() shim (v2 → v1) ──────────────────
    # v1 的 ValidationError 没有 `.error_count()` 方法, 业务代码在 v1 上
    # AttributeError. 给 ValidationError 类挂一个 `.error_count()` 装饰器
    # 走 `len(self.errors())` 即可跨版本一致.
    if not hasattr(pydantic.ValidationError, "error_count"):
        pydantic.ValidationError.error_count = _validation_error_error_count  # type: ignore[attr-defined]

    return True


def model_to_dict(m: Any) -> Dict[str, Any]:
    """两分支通用的 dump 入口。"""
    return m.model_dump() if hasattr(m, "model_dump") else m.dict()


BaseModelCompat = BaseModel

# ── Auto-install on import (win7 / pydantic v1 only) ─────────────────────────
#
# 历史教训 (2026-09-16): docstring 写 "用法（任何使用 v2 API 的包在 __init__
# 顶部 import 后调 install()）", 但实际项目里**没有任何一个调用点** → metaclass
# hook 没生效, `model_config = ConfigDict(extra="forbid")` / `model_validate`
# / `model_construct` 全部不工作, 导致 PR #892 CI py38 9 个 pytest 失败。
#
# 修复: 模块顶层自动 install(). 幂等 (`_INSTALLED` flag), main 分支 pydantic v2
# 下 install() 早返回 False, 不会污染 main。 任何 `from backend.compat.win7
# .pydantic_compat import ...` 都隐式触发 install。
install()

__all__ = [
    "PYDANTIC_V2",
    "BaseModelCompat",
    "ConfigDict",
    "field_validator",
    "install",
    "model_to_dict",
]

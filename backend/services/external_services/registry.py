"""外部服务注册表 —— 名称 / preferences 键双索引查找。"""

from __future__ import annotations

from typing import Dict, List, Optional

from backend.services.external_services.spec import ExternalServiceSpec

_SERVICES: Dict[str, ExternalServiceSpec] = {}
_builtins_loaded = False


def register_service(spec: ExternalServiceSpec) -> None:
    """注册（或覆盖）一个服务声明。"""
    _SERVICES[spec.name] = spec


def _ensure_builtins() -> None:
    global _builtins_loaded
    if _builtins_loaded:
        return
    _builtins_loaded = True
    # 惰性导入避免循环依赖；builtin 顶层调用 register_service 完成注册。
    from backend.services.external_services import builtin  # noqa: F401


def get_service(name: str) -> Optional[ExternalServiceSpec]:
    _ensure_builtins()
    return _SERVICES.get(name)


def get_by_preference_key(key: str) -> Optional[ExternalServiceSpec]:
    _ensure_builtins()
    for spec in _SERVICES.values():
        if spec.preference_key == key:
            return spec
    return None


def all_services() -> List[ExternalServiceSpec]:
    _ensure_builtins()
    return list(_SERVICES.values())

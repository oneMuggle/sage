"""外部服务声明模型 —— 纯数据，无 I/O、无副作用。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


@dataclass(frozen=True)
class SecretField:
    """需要字段级静态加密的 JSON 字段 → SecretBox 加密账户名。"""

    json_field: str
    account: str


@dataclass(frozen=True)
class EnvBinding:
    """环境变量覆盖：优先级高于 preferences 落库值。"""

    json_field: str
    env_var: str


#: 探活函数：入参为合并后的配置（含解密后的密钥），返回状态字典。
ProbeFn = Callable[[Dict[str, Any]], Awaitable[Dict[str, Any]]]


@dataclass(frozen=True)
class ExternalServiceSpec:
    """一个自托管外部服务的完整声明。"""

    name: str
    preference_key: str
    title: str = ""
    #: 状态路由挂在 /api/v1/<api_prefix>/status；空表示不暴露状态端点。
    api_prefix: str = ""
    defaults: Dict[str, Any] = field(default_factory=dict)
    #: 规范 JSON 键 → 兼容的历史键名（读取时按序回退）。
    aliases: Dict[str, List[str]] = field(default_factory=dict)
    env_bindings: List[EnvBinding] = field(default_factory=list)
    secret_fields: List[SecretField] = field(default_factory=list)
    probe: Optional[ProbeFn] = None

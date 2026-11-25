"""声明式外部服务注册表（MinerU / DrawIO / Zotero ...）。

服务配置、密钥字段、探活行为集中描述为 :class:`ExternalServiceSpec`，
各层（settings_repo / config / status 路由 / 前端卡片）按 spec 通用驱动，
新增服务只需在 ``builtin`` 中追加一个 spec 声明。
"""

from backend.services.external_services.registry import (
    all_services,
    get_by_preference_key,
    get_service,
    register_service,
)
from backend.services.external_services.spec import (
    EnvBinding,
    ExternalServiceSpec,
    SecretField,
)

__all__ = [
    "EnvBinding",
    "ExternalServiceSpec",
    "SecretField",
    "all_services",
    "get_by_preference_key",
    "get_service",
    "register_service",
]

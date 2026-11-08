"""会话标题专用模型的客户端工厂。

标题生成是高频、低价值的任务，用主聊天模型既慢又贵。本模块解析
``app_settings.titleModelId``，复用聊天端点凭据（provider / api_key /
base_url），仅覆盖 ``model`` 与 ``temperature``，构建一个轻量客户端。

放在 ``orchestration`` 层而非 ``chat.title_generator``：构建客户端需要
访问 adapters 层（``LLMClient``），而 ``application`` 层只能依赖更低层，
把工厂留在 ``chat`` 会让 ``application → chat → adapters`` 形成违规依赖链。
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

#: 标题模型 temperature —— 低温度让输出更稳定、更收敛。
TITLE_TEMPERATURE = 0.2


def load_title_llm_config() -> Optional[Dict[str, Any]]:
    """解析标题生成专用模型配置；未配置时返回 ``None``。

    专用模型复用聊天端点的凭据（provider / api_key / base_url），仅覆盖
    ``model`` 与 ``temperature`` —— 对应设置项 ``app_settings.titleModelId``
    （一个模型 id 字符串）。这样用户不必为标题单独配置端点，又能用小模型
    降低延迟与成本。
    """
    try:
        from backend.data.settings_canonicalizer import to_camel
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get_json("app_settings")
    except Exception as exc:  # DB 不可用 / 数据损坏 — 降级
        logger.warning("读取标题模型配置失败: %s", exc)
        return None

    if not isinstance(raw, dict):
        return None

    model_id = to_camel(raw).get("titleModelId")
    if not isinstance(model_id, str) or not model_id.strip():
        return None

    from backend.orchestration.llm_factory import load_llm_config_from_settings

    base = load_llm_config_from_settings()
    if base is None:
        return None

    cfg = dict(base)
    cfg["model"] = model_id.strip()
    cfg["temperature"] = TITLE_TEMPERATURE
    return cfg


class TitleModelFactory:
    """构建标题生成用的 LLM 客户端。

    优先使用 ``titleModelId`` 指定的专用模型；未配置或构建失败时回退到
    全局聊天模型；两者都不可用返回 ``None``（由 ``TitleGenerator``
    走启发式兜底）。
    """

    @staticmethod
    def build() -> Optional[Any]:
        from backend.orchestration.llm_factory import build_llm_client_from_settings

        cfg = load_title_llm_config()
        if cfg is not None:
            try:
                from backend.core.legacy.llm_client import LLMClient, LLMConfig

                return LLMClient(LLMConfig(**cfg))
            except Exception as exc:  # noqa: BLE001 — 构建失败回退主模型
                logger.warning("标题专用模型客户端构建失败，回退主模型: %s", exc)

        return build_llm_client_from_settings()

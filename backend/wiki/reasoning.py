"""Provider 推理模式适配。

将 reasoning mode（auto/off/low/medium/high/max）翻译为各 provider 的 API 参数。
参考 llm_wiki 的 reasoning-capabilities.ts。
"""

from __future__ import annotations

from typing import Any, Dict, List

# Provider → 支持的 reasoning 模式列表
REASONING_CAPABILITIES: Dict[str, List[str]] = {
    "openai": ["auto", "low", "medium", "high"],
    "anthropic": ["auto", "low", "medium", "high", "max"],
    "google": ["auto", "low", "medium", "high", "max"],
    "deepseek": ["auto", "high", "max"],
    "ollama": ["auto", "low", "medium", "high", "max"],
}

# 各任务的默认推理模式
INGEST_DEFAULT_MODE = "off"
CHAT_DEFAULT_MODE = "auto"

# mode → token 预算映射
_MODE_TOKEN_BUDGET: Dict[str, int] = {
    "low": 1024,
    "medium": 4096,
    "high": 10000,
    "max": 20000,
}


def get_supported_modes(provider: str) -> List[str]:
    """返回 provider 支持的推理模式列表。"""
    return REASONING_CAPABILITIES.get(provider, ["auto"])


def is_mode_supported(provider: str, mode: str) -> bool:
    """检查 mode 是否被 provider 支持。"""
    return mode in get_supported_modes(provider)


def normalize_mode(provider: str, mode: str) -> str:
    """将 mode 归一化为 provider 支持的值。

    不支持的 mode 降级为 "auto"。
    """
    supported = get_supported_modes(provider)
    if mode in supported:
        return mode
    return "auto"


def apply_reasoning_to_request(
    request_body: Dict[str, Any],
    provider: str,
    mode: str,
) -> Dict[str, Any]:
    """将 reasoning mode 翻译为 provider-specific API 参数，注入 request_body。

    Args:
        request_body: 原始请求体（会被就地修改并返回）
        provider: provider 名称（openai/anthropic/google/deepseek/ollama）
        mode: 推理模式（auto/off/low/medium/high/max）

    Returns:
        修改后的 request_body
    """
    if mode in ("off", "auto"):
        return request_body

    if not is_mode_supported(provider, mode):
        mode = normalize_mode(provider, mode)
        if mode in ("auto", "off"):
            return request_body

    budget = _MODE_TOKEN_BUDGET.get(mode, 4096)

    if provider == "openai":
        request_body["reasoning_effort"] = mode

    elif provider == "anthropic":
        request_body["thinking"] = {
            "type": "enabled",
            "budget_tokens": budget,
        }

    elif provider == "google":
        request_body["thinking_config"] = {"thinking_budget": budget}

    elif provider in ("deepseek", "ollama"):
        request_body["reasoning_effort"] = mode

    return request_body

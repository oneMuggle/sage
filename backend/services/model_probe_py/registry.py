"""Inspired by arena-model-probe/src/registry.js (Python 3.8 compatible)."""

from __future__ import annotations

import re
from typing import Dict, List, Pattern, Set


#: Model name family patterns: family name → regex of canonical model name patterns
MODEL_PATTERNS: Dict[str, Pattern] = {
    "gpt": re.compile(r"\bgpt[-\s]?\d|chatgpt|gpt-4o|gpt-5|gpt-6", re.IGNORECASE),
    "claude": re.compile(r"\bclaude[-\s]?(?:opus|sonnet|haiku|[\d-]+)", re.IGNORECASE),
    "gemini": re.compile(r"\bgemini[-\s]?(?:pro|ultra|nano|[\d.]+)", re.IGNORECASE),
    "llama": re.compile(r"\bllama[-\s]?[\d.]+", re.IGNORECASE),
    "deepseek": re.compile(r"\bdeepseek[-\s]?[cv]?\d", re.IGNORECASE),
    "qwen": re.compile(r"\bqwen[-\s]?[\d.]+", re.IGNORECASE),
    "mistral": re.compile(r"\bmistral[-\s]?(?:large|medium|small|[\d]+)", re.IGNORECASE),
}


#: JSON key names that carry model identifiers
#: Note: regex matches the bare key name (without surrounding quotes);
#: callers wrap key with quotes when matching full JSON tokens.
MODEL_KEY_RE: Pattern = re.compile(
    r"(?<![A-Za-z0-9_])(model|model_id|modelId|model_name|"
    r"served_model|upstream_model|resolved_model|base_model|"
    r"deployment|engine|model_slug|model_key|selected_model|"
    r"current_model|target_model|requested_model)(?![A-Za-z0-9_])",
    re.IGNORECASE,
)


#: JSON key names for token usage
USAGE_KEYS: Set[str] = {
    "input_tokens", "output_tokens", "total_tokens",
    "prompt_tokens", "completion_tokens",
    "inputTokens", "outputTokens", "totalTokens",
    "promptTokenCount", "candidatesTokenCount", "thoughtsTokenCount",
    "cache_creation_input_tokens", "cache_read_input_tokens",
}


#: HTTP header pattern for model fields
MODEL_HEADER_RE: Pattern = re.compile(r"^x-?(?:model|llm|ai)[-_]?model$", re.IGNORECASE)


#: Hostname → vendor family
HOST_VENDOR: Dict[str, str] = {
    "api.openai.com": "openai",
    "api.anthropic.com": "anthropic",
    "generativelanguage.googleapis.com": "google",
    "api.deepseek.com": "deepseek",
    "api.x.ai": "xai",
    "openrouter.ai": "openrouter",
    "api.groq.com": "groq",
    "api.together.xyz": "together",
    "api.mistral.ai": "mistral",
    "dashscope.aliyuncs.com": "alibaba",
    "api.moonshot.cn": "moonshot",
    "api.bigmodel.cn": "zhipu",
    "ark.cn-beijing.volces.com": "bytedance",
}


#: Protocol framing tokens per family (for fingerprinting when no model string exists)
FAMILY_PROTOCOLS: Dict[str, List[str]] = {
    "anthropic": [
        "message_start", "content_block_delta", "thinking_delta",
        "toolu_", "cache_creation_input_tokens", "cache_read_input_tokens",
    ],
    "openai": [
        "chatcmpl-", "system_fingerprint", '"object":"chat.completion.chunk"',
    ],
    "google": [
        "generateContent", "streamGenerateContent", "candidates",
        "safetyRatings", "promptFeedback",
    ],
}


_FRONTIER_FAMILIES = {"gpt", "claude", "gemini"}


def isFrontier(name: str) -> bool:
    """Return True if model name matches a known frontier family pattern."""
    if not isinstance(name, str) or not name:
        return False
    for family, pattern in MODEL_PATTERNS.items():
        if family in _FRONTIER_FAMILIES and pattern.search(name):
            return True
    return False
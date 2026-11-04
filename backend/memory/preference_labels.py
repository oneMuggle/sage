"""偏好维度 / 值的中文显示标签。

preferences 表保持机器键（``pref_response_length`` 等）不变 —— 其他消费方
（设置仓库、app_settings 等）仍按机器键读写。本模块只在把偏好写入
*人类可读* 字段（``user_profile`` 快照 / ``memories_semantic`` 内容 /
进化日志 ``after_state``）时使用，避免出现 "用户偏好 response_length:
detailed" 这类中英混合文本，前端截断后变成 "response_length:detai"。
"""

from __future__ import annotations

from typing import Dict

PREFERENCE_DIMENSION_LABELS: Dict[str, str] = {
    "response_length": "回复长度",
    "tone": "交互风格",
    "detail_level": "详细程度",
}

PREFERENCE_VALUE_LABELS: Dict[str, Dict[str, str]] = {
    "response_length": {
        "short": "简短",
        "medium": "适中",
        "long": "较长",
        "detailed": "详细",
    },
    "tone": {
        "friendly": "友好",
        "professional": "专业",
        "humorous": "幽默",
        "formal": "严肃",
    },
    "detail_level": {
        "brief": "简洁",
        "medium": "适中",
        "comprehensive": "全面",
    },
}


def format_preference(key: str, value: str) -> str:
    """把偏好键值翻译成人类可读字符串。

    未识别的 key / value 直接回落到原始值，保证向前兼容历史数据。
    示例:
        >>> format_preference("response_length", "detailed")
        '用户偏好回复长度: 详细'
        >>> format_preference("unknown_dim", "foo")
        '用户偏好unknown_dim: foo'
    """
    dim = PREFERENCE_DIMENSION_LABELS.get(key, key)
    val = PREFERENCE_VALUE_LABELS.get(key, {}).get(value, value)
    return f"用户偏好{dim}: {val}"

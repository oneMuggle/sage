"""
记忆摘要共享工具 (D2, P6)

此前 SemanticMemory 与 EpisodicMemory 各自维护一份逐字相同的
``_generate_summary`` 实现 (仅默认截断长度不同: 150/100), 存在漂移
风险。统一收敛到本模块; 两类仍保留同名方法做默认长度委托, 对既有
调用方与测试透明。

注意: ``scheduler/evolution.py`` 的 ``_generate_summary`` 是 LLM 驱动的
对话摘要, 与本截断式摘要语义不同, **不属于**本次收敛范围; 也与本模块
及 ``backend.memory.summary`` (SessionSummaryStore) 均无关联。
"""

from __future__ import annotations


def truncate_summary(content: str, max_length: int) -> str:
    """生成记忆摘要: 超长截断并追加省略号。

    Args:
        content: 原始内容
        max_length: 最大长度

    Returns:
        摘要文本
    """
    if len(content) <= max_length:
        return content
    return content[:max_length] + "..."

"""M2 配置化 — 从 ``config.yaml`` 的 ``tools:`` 段加载 ``ToolPolicy``。

yaml 文件不存在、解析失败或缺 ``tools:`` 段时均降级为 ``ToolPolicy()`` 默认值
（向后兼容旧部署）。该 helper 仿 ``main.py`` 中 ``ghm.yaml`` 加载模式。
"""

from __future__ import annotations
from typing import Union

from pathlib import Path

from backend.domain.tool_policy import ToolPolicy


def load_tool_policy_from_config(config_path: Union[str, Path]) -> ToolPolicy:
    """从 yaml 加载 ``tools:`` 段并构造 ``ToolPolicy``。

    - 文件不存在 → ``ToolPolicy()`` 默认
    - 解析失败 → ``ToolPolicy()`` 默认（不阻塞主流程）
    - ``tools:`` 段不存在 → ``ToolPolicy()`` 默认
    - 段内字段缺失 → 回退 dataclass 默认

    Returns:
        构造好的 ``ToolPolicy``（frozen）。
    """
    path = Path(config_path)
    try:
        if not path.is_file():
            return ToolPolicy()
        import yaml

        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, ImportError, Exception):  # noqa: BLE001
        return ToolPolicy()

    tools_section = raw.get("tools") if isinstance(raw, dict) else None
    if not isinstance(tools_section, dict):
        return ToolPolicy()
    return ToolPolicy.from_config(tools_section)

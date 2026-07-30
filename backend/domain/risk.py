"""工具风险分级领域模型（A1，来自 OpenWorker ``coworker/risk.py``）。

工具权限数据化的核心：风险是工具声明的固有副作用类别，权限引擎据此
裁决 allow / deny / ask-user，取代按工具名硬编码集合（旧模式的
``WRITE_TOOLS`` / ``SHELL_TOOL``）的做法。

有效风险的解析优先级：

1. 用户级覆盖 ``overrides``（A19 RiskOverride，缺省 ``None`` 不启用）
2. 工具注册时声明的 ``declared`` 风险（``BaseTool.risk`` → 注册表收集）
3. 内置工具按名兜底表（``_BASE``，覆盖未声明风险的历史/动态工具）
4. 元数据启发式（``requires_approval`` → EXTERNAL，如保守处理的 MCP 工具）
5. 兜底 READ

**领域纯净性**：本模块仅依赖标准库，不读文件/时钟/网络，不 import
任何 backend 内部模块。
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable, Dict, Mapping, Optional


class RiskClass(str, Enum):
    """工具副作用类别 — 驱动权限门禁的固有属性。"""

    READ = "read"  # 无副作用 — 始终放行
    WRITE_LOCAL = "write_local"  # 修改本地状态/工作区 — 路径受限 + 模式门禁
    EXEC = "exec"  # 执行命令 — 模式门禁
    EXTERNAL = "external"  # 副作用发生在机器之外（网络等） — 最严门禁


# 内置工具按名兜底表：工具自身未声明 risk 时按名分类。
# 与 backend/tools 各工具类的 ``risk`` 声明保持一致；新工具应优先在
# 类上声明 risk，此表仅作为历史/动态注册工具（如 MCP）的兜底。
WRITE_TOOLS = frozenset({"write_file", "memory_save"})
SHELL_TOOLS = frozenset({"terminal"})
EXTERNAL_TOOLS = frozenset({"web_search", "web_fetch"})

_BASE: Dict[str, RiskClass] = {
    **{name: RiskClass.WRITE_LOCAL for name in WRITE_TOOLS},
    **{name: RiskClass.EXEC for name in SHELL_TOOLS},
    **{name: RiskClass.EXTERNAL for name in EXTERNAL_TOOLS},
}

# 用户级风险覆盖解析器：tool name -> RiskClass（返回 None 表示交给后续
# 优先级解析）。A19 接线；在此之前调用方应始终传 None。
RiskOverrides = Callable[[str], Optional[RiskClass]]


def _requires_approval(metadata: Any) -> bool:
    """元数据启发式：对象属性或 Mapping 键 ``requires_approval``。"""
    if metadata is None:
        return False
    if isinstance(metadata, Mapping):
        return bool(metadata.get("requires_approval", False))
    return bool(getattr(metadata, "requires_approval", False))


def classify(
    tool_name: str,
    metadata: Any = None,
    overrides: Optional[RiskOverrides] = None,
    declared: Optional[Mapping[str, RiskClass]] = None,
) -> RiskClass:
    """解析工具调用的有效风险。

    优先级：用户覆盖 > 注册声明 > 按名兜底表 > 元数据启发式 > READ。

    Args:
        tool_name: 工具名称
        metadata:  工具元数据（对象或 dict）；``requires_approval`` 真值
                   且无更高优先级来源时判为 EXTERNAL
        overrides: 用户级覆盖解析器（A19），返回 None 表示不覆盖
        declared:  注册表收集的 {工具名: 声明风险} 映射

    Returns:
        有效 ``RiskClass``
    """
    if overrides is not None:
        override = overrides(tool_name)
        if override is not None:
            return override
    if declared is not None and tool_name in declared:
        return declared[tool_name]
    base = _BASE.get(tool_name)
    if base is not None:
        return base
    if _requires_approval(metadata):
        return RiskClass.EXTERNAL
    return RiskClass.READ


def is_consequential(risk: RiskClass) -> bool:
    """除纯读之外的风险都需要权限引擎介入。"""
    return risk is not RiskClass.READ

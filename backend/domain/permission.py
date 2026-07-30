"""权限模式领域模型（A1/A22，来自 OpenWorker ``coworker/permissions.py``）。

定义会话级权限模式与权限引擎的裁决结果 ``Decision``。模式决定引擎
对"有副作用"（consequential）工具调用的默认姿态：

- DISCUSS / PLAN：只读 — 任何 consequential 调用直接拒绝（不询问）
- INTERACTIVE：询问用户（默认模式）
- AUTO：完全放行（写入仍受 workspace 路径边界约束）
- CUSTOM：INTERACTIVE + 配置的 ``auto_allow_tools`` 自动放行

**领域纯净性**：本模块仅依赖标准库，不读文件/时钟/网络，不 import
任何 backend 内部模块。引擎实现位于
``backend.adapters.out.permission.permission_engine``。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class PermissionMode(str, Enum):
    """会话级权限模式。"""

    DISCUSS = "discuss"  # 只读会话：不编辑、不执行、不出网
    PLAN = "plan"  # 只读 + 规划契约（探索 → 提案 → 执行）
    INTERACTIVE = "interactive"  # 写/执行/出网前询问用户（默认）
    AUTO = "auto"  # 完全放行（路径边界仍生效）
    CUSTOM = "custom"  # interactive + 自动放行白名单工具


# 强制执行只读的模式集合。DISCUSS 与 PLAN 共享同一门禁；区别只在
# 意图 — PLAN 额外引导 agent 走 propose_plan 审批流。
READ_ONLY_MODES = frozenset({PermissionMode.DISCUSS, PermissionMode.PLAN})


@dataclass
class Decision:
    """权限引擎对单次工具调用的裁决。

    Attributes:
        allowed:    是否放行执行
        reason:     裁决理由（用于审计日志与 UI 展示）
        needs_user: True → 上层应挂起调用并路由到 UI 请求用户批准
        rule:       命中的常驻规则文本（便于审计溯源，缺省为空）
    """

    allowed: bool
    reason: str = ""
    needs_user: bool = False
    rule: str = ""

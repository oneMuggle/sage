# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""会话级专家绑定（M0 — 2026-11-03）。

会话通过 ``sessions.specialist_id`` 绑定一个专家（``agents.id``）。
绑定只决定"这个会话用谁的人设 / 工具白名单 / 模型 / 记忆策略"，
不触碰认证、工作区绑定、消息历史。

解析优先级（``/chat`` 与 ``/chat/stream`` 共用）::

    请求显式 agent_id  >  会话绑定的 specialist_id  >  'primary'（主助手）

无论 id 来自哪一层，都要过"存在 + 已启用"校验：专家被禁用或删除后
回落到主助手，而不是让会话静默失去人设（"切回主助手无残留"）。
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

#: 主助手（默认助手）的 agent id —— sessions.specialist_id 的缺省值。
PRIMARY_AGENT_ID = "primary"


def _is_usable_agent(agent_id: str) -> bool:
    """该 agent id 是否可用于当前会话（存在且已启用）。"""
    try:
        from backend.data.agent_repo import AgentRepository

        row = AgentRepository().get(agent_id)
    except Exception as exc:  # noqa: BLE001 — 校验失败按不可用处理
        logger.warning("专家绑定校验失败（按不可用处理）: %s", exc)
        return False
    if row is None:
        return False
    return bool(row.get("enabled", True))


def _validated(agent_id: Optional[str]) -> str:
    """校验 agent id；不可用 → 'primary'。"""
    if not agent_id:
        return PRIMARY_AGENT_ID
    if agent_id == PRIMARY_AGENT_ID:
        return PRIMARY_AGENT_ID
    if not _is_usable_agent(agent_id):
        logger.info("专家 %s 不存在或已禁用 → 回落主助手", agent_id)
        return PRIMARY_AGENT_ID
    return agent_id


def resolve_bound_specialist(session_id: str) -> str:
    """读会话绑定的专家 id；会话不存在 / 未绑定 / 不可用 → 'primary'。"""
    if not session_id:
        return PRIMARY_AGENT_ID
    try:
        from backend.data.session_repo import SessionRepository

        session = SessionRepository().get(session_id)
    except Exception as exc:  # noqa: BLE001 — 读失败回落主助手，不阻塞聊天
        logger.warning("读取会话专家绑定失败（回落主助手）: %s", exc)
        return PRIMARY_AGENT_ID
    if session is None:
        return PRIMARY_AGENT_ID
    return _validated(session.specialist_id)


def resolve_effective_agent_id(session_id: str, requested_agent_id: Optional[str]) -> str:
    """确定本次请求实际使用的 agent id。

    请求显式指定时以请求为准（向后兼容既有的 ``agent_id`` 传参路径），
    否则用会话绑定。
    """
    if requested_agent_id:
        return _validated(requested_agent_id)
    return resolve_bound_specialist(session_id)


# --------------------------------------------------------------------------- #
# 严格解析（技能作用域 fail-closed 专用）
#
# 普通聊天路径的解析是"容错优先"：读库失败回落主助手，绝不阻塞对话。
# 但技能作用域失败必须 fail-closed —— 「判定为专家」之后的任何解析异常
# 若降级为"不受限"，等于把全量技能库放给该专家（安全审查 HIGH）。
# 下面的函数把异常外抛给调用方，由调用方决定拒绝全部技能。
# --------------------------------------------------------------------------- #


def _validated_strict(agent_id: Optional[str]) -> str:
    """``_validated`` 的严格版：读取 / 校验异常一律外抛。

    专家不存在 / 已禁用仍返回 ``'primary'``（产品语义：回落主助手）。
    """
    if not agent_id or agent_id == PRIMARY_AGENT_ID:
        return PRIMARY_AGENT_ID
    from backend.data.agent_repo import AgentRepository

    row = AgentRepository().get(agent_id)  # 读取异常外抛
    if row is None:
        logger.info("专家 %s 不存在 → 回落主助手", agent_id)
        return PRIMARY_AGENT_ID
    if not row.get("enabled", True):
        logger.info("专家 %s 已禁用 → 回落主助手", agent_id)
        return PRIMARY_AGENT_ID
    return agent_id


def resolve_bound_specialist_strict(session_id: str) -> str:
    """读会话绑定的专家 id；读取 / 校验异常外抛。

    仅供技能作用域等 fail-closed 场景使用；普通聊天路径继续用
    ``resolve_bound_specialist``（读失败回落主助手，保证对话可用）。
    """
    if not session_id:
        return PRIMARY_AGENT_ID
    from backend.data.session_repo import SessionRepository

    session = SessionRepository().get(session_id)  # 读取异常外抛
    if session is None:
        return PRIMARY_AGENT_ID
    return _validated_strict(session.specialist_id)


def resolve_effective_agent_id_strict(
    session_id: str, requested_agent_id: Optional[str]
) -> str:
    """``resolve_effective_agent_id`` 的严格版：解析 / 校验异常外抛。"""
    if requested_agent_id:
        return _validated_strict(requested_agent_id)
    return resolve_bound_specialist_strict(session_id)


def validate_specialist_id(raw: Optional[str]) -> Optional[str]:
    """校验 API 传入的专家 id。

    返回规范化后的 id；``None`` 表示"未指定"（调用方保持原值不变）。
    空串等价于 'primary'（解绑 → 主助手）。

    Raises:
        ValueError: id 不存在或已禁用。
    """
    if raw is None:
        return None
    candidate = str(raw).strip()
    if not candidate:
        return PRIMARY_AGENT_ID
    if candidate == PRIMARY_AGENT_ID:
        return PRIMARY_AGENT_ID
    if not _is_usable_agent(candidate):
        raise ValueError(f"专家不存在或已禁用: {candidate}")
    return candidate

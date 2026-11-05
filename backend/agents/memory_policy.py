"""M3-Task 3 — 专家记忆策略（spec §7.1 最小实现）。

``agents.memory_policy``（JSON 列，M0 已存在，见 ``profiles.py``）解析为
强类型模型，锁定四个契约字段：

- ``read_scopes``：允许读取的记忆归属；缺 ``specialist`` 时读侧剔除
  私有行（仅共享层可见）。
- ``write_scope``：自动抽取记忆的归属。``specialist`` → 写当前专家
  （``agent_id=当前专家``）；``project`` / ``user`` → 写共享层
  （``agent_id=NULL``）。M3 仅区分「私有 vs 共享」两档。
- ``auto_extract``：是否允许聊天自动抽取写记忆（消费方在 Task 4）。
- ``retention_days``：保留天数；``None`` = 永久。M3 只做模型与解析，
  清理任务由后续里程碑消费。

Pydantic v1/v2 双兼容（与 ``KnowledgeBinding`` 同模式）：

- ``class Config: extra = "forbid"``（``ConfigDict`` 在 v1 下被静默忽略）；
- 类型注解全部 ``from typing import ...``（py38 无 ``list[...]`` 泛型）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Literal, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

#: ``read_scopes`` / ``write_scope`` 的合法取值。
VALID_SCOPE_VALUES: Tuple[str, ...] = ("specialist", "project", "user")

#: 未配置策略时的读归属（与 M3 前行为一致：全可见）。
DEFAULT_READ_SCOPES: Tuple[str, ...] = ("specialist", "project", "user")

MemoryScopeValue = Literal["specialist", "project", "user"]


class MemoryPolicy(BaseModel):
    """一个专家的记忆策略（JSON 列反序列化目标）。"""

    read_scopes: List[MemoryScopeValue] = Field(
        default_factory=lambda: list(DEFAULT_READ_SCOPES),
        description="允许读取的记忆归属；缺 specialist → 私有行不可见。",
    )
    write_scope: MemoryScopeValue = Field(
        default="specialist",
        description="自动抽取写归属：specialist → 当前专家私有；其余 → 共享。",
    )
    auto_extract: bool = Field(
        default=True, description="是否允许聊天自动抽取写记忆。",
    )
    retention_days: Optional[int] = Field(
        default=None, ge=1, description="保留天数；None = 永久保留。",
    )

    class Config:  # noqa: D401 — Pydantic v1/v2 双兼容配置
        extra = "forbid"


def _validate(model_cls: Any, data: Any) -> Any:
    """pydantic v2 优先 ``model_validate``，v1 回退 ``parse_obj``。"""
    validate = getattr(model_cls, "model_validate", None)
    if validate is not None:
        return validate(data)
    return model_cls.parse_obj(data)


def parse_memory_policy(raw: Any) -> MemoryPolicy:  # noqa: PLR0911 — 防御性 fail-fast 各分支返回
    """把 ``agents.memory_policy`` 的原始值规范化为 :class:`MemoryPolicy`。

    接受 ``None``（默认策略）、:class:`MemoryPolicy` 实例、``dict``、
    以及 JSON 字符串（DB 列的历史形态）。任何非法输入（坏 JSON、
    未知键、非法枚举值）都**降级为默认策略并告警** —— 坏配置不能
    击穿会话主链路。
    """
    if isinstance(raw, MemoryPolicy):
        return raw
    if raw is None:
        return MemoryPolicy()
    data: Any = raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return MemoryPolicy()
        try:
            data = json.loads(text)
        except (TypeError, ValueError) as exc:
            logger.warning(f"memory_policy JSON 解析失败，使用默认策略: {exc}")
            return MemoryPolicy()
    if not data:
        return MemoryPolicy()
    try:
        return _validate(MemoryPolicy, data)
    except Exception as exc:  # noqa: BLE001 — 配置错误降级，不阻塞会话
        logger.warning(f"memory_policy 校验失败，使用默认策略: {exc}")
        return MemoryPolicy()


def resolve_write_agent_id(
    policy: Optional[MemoryPolicy], current_agent_id: Optional[str]
) -> Optional[str]:
    """按策略决定自动抽取写入的 ``agent_id``。

    ``write_scope="specialist"`` → 当前专家（私有）；其余 → ``None``
    （共享层）。``current_agent_id`` 为空时恒为 ``None``。
    """
    if not current_agent_id:
        return None
    if policy is None or policy.write_scope == "specialist":
        return str(current_agent_id)
    return None


def includes_private_reads(policy: Optional[MemoryPolicy]) -> bool:
    """读归属是否包含 ``specialist``（即私有行是否可见）。"""
    if policy is None:
        return True
    return "specialist" in policy.read_scopes


__all__ = [
    "DEFAULT_READ_SCOPES",
    "MemoryPolicy",
    "MemoryScopeValue",
    "VALID_SCOPE_VALUES",
    "includes_private_reads",
    "parse_memory_policy",
    "resolve_write_agent_id",
]

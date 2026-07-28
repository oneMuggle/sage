"""工具审批闸口（M1 工具安全加固）。

当 ``PermissionEnforcer`` 判定某次工具调用 ``needs_approval`` 时，agent 循环
通过本模块挂起执行：

1. agent 侧调用 ``ApprovalGate.request(req, timeout)`` —— 注册一个 Future 并
   await（agent 流在 await 之前先 yield permission_request 事件给前端）。
2. 前端收到事件渲染对话框，用户点击后 POST /api/v1/permissions/{id}/answer。
3. 路由调用 ``ApprovalGate.answer(request_id, approved, remember)`` 解析 Future，
   agent 循环被唤醒继续执行或拒绝。
4. 超时未应答 → ``ApprovalAnswer(False, False, "timeout")``（fail-closed）。

单例装配遵循 ``backend.services.scheduler`` 的模式：``init_permission_gate()``
在 ``main.py`` lifespan 中调用一次，``get_permission_gate()`` 供路由 / agent
取用；未初始化时返回 ``None``，调用方按 default-deny 处理。

并发模型：sage 后端单事件循环，gate 的 dict 操作均在循环线程内，无需加锁。
``answer()`` 可能从路由 handler（同循环）调用，``request()`` 在 agent task 内
await——Future 跨 task 解析是 asyncio 的常规用法。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: 单个参数值的最大展示长度（超出截断）
ARG_VALUE_MAX_CHARS = 200

#: 命中即脱敏的参数名模式（键名包含这些词的值一律替换为 ***）
_SECRET_KEY_RE = re.compile(r"(key|token|password|secret|credential|auth)", re.IGNORECASE)

#: 未指定超时时的默认等待秒数（5 分钟，与 claw-code 审批超时一致）
DEFAULT_APPROVAL_TIMEOUT_S = 300.0


def summarize_tool_args(args: Optional[Dict[str, Any]]) -> str:
    """把工具参数压成可展示的 JSON 字符串。

    - 键名匹配 key/token/password/secret/credential/auth 的值 → ``"***"``
    - 其余值字符串化后截断到 ``ARG_VALUE_MAX_CHARS``
    - 整体再兜底截断到 1000 字符，防止极端参数撑爆流事件
    """
    if not args:
        return "{}"
    clean: Dict[str, Any] = {}
    for key, value in args.items():
        key_str = str(key)
        if _SECRET_KEY_RE.search(key_str):
            clean[key_str] = "***"
            continue
        if isinstance(value, str):
            text = value
        else:
            try:
                text = json.dumps(value, ensure_ascii=False, default=str)
            except (TypeError, ValueError):
                text = str(value)
        if len(text) > ARG_VALUE_MAX_CHARS:
            text = text[:ARG_VALUE_MAX_CHARS] + "…(已截断)"
        clean[key_str] = text
    summary = json.dumps(clean, ensure_ascii=False)
    if len(summary) > 1000:
        summary = summary[:1000] + "…(已截断)"
    return summary


@dataclass(frozen=True)
class ApprovalAnswer:
    """审批应答（不可变）。

    Attributes:
        approved:    用户是否批准。
        remember:    是否把该决定持久化为规则（精确工具名 allow/deny）。
        answered_by: 应答来源——``"gui"`` / ``"timeout"`` / ``"default-deny"``。
    """

    approved: bool
    remember: bool
    answered_by: str


@dataclass(frozen=True)
class ApprovalRequest:
    """一次待审批的工具调用（不可变）。

    Attributes:
        request_id:   UUID，前端应答时回传。
        tool_name:    工具名（remember 时作为规则的精确 pattern）。
        args_summary: 已脱敏 + 截断的参数 JSON 字符串。
        risk:         风险等级（bash 校验结果或 "safe"）。
        message:      展示给用户的完整原因（来自 PermissionDecision.reason）。
        created_at:   创建时间（epoch 秒）。
    """

    request_id: str
    tool_name: str
    args_summary: str
    risk: str
    message: str
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        """流事件 / REST 响应共用的 JSON 形态。"""
        return {
            "request_id": self.request_id,
            "tool_name": self.tool_name,
            "args_summary": self.args_summary,
            "risk": self.risk,
            "message": self.message,
            "created_at": self.created_at,
        }

    @classmethod
    def create(
        cls,
        tool_name: str,
        args: Optional[Dict[str, Any]],
        risk: str,
        message: str,
    ) -> ApprovalRequest:
        """工厂：生成 UUID + 时间戳 + 脱敏参数摘要。"""
        return cls(
            request_id=str(uuid.uuid4()),
            tool_name=tool_name,
            args_summary=summarize_tool_args(args),
            risk=risk,
            message=message,
            created_at=time.time(),
        )


class ApprovalGate:
    """挂起 / 解析待审批请求的闸口。"""

    def __init__(self) -> None:
        self._pending: Dict[str, Tuple[ApprovalRequest, asyncio.Future[ApprovalAnswer]]] = {}

    async def request(
        self, req: ApprovalRequest, timeout: float = DEFAULT_APPROVAL_TIMEOUT_S
    ) -> ApprovalAnswer:
        """注册 req 并等待应答；超时返回 default-deny。

        调用方（agent 循环）负责在 await 本方法**之前**把 permission_request
        事件推入流，否则前端无从知晓该请求。
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[ApprovalAnswer] = loop.create_future()
        self._pending[req.request_id] = (req, future)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        # noqa 说明: py3.8 (Win7 LTS) 下 asyncio.TimeoutError 是
        # concurrent.futures.TimeoutError, 与内建 TimeoutError 不同源;
        # 必须捕获 asyncio.TimeoutError 才能在两个版本上都 default-deny。
        except asyncio.TimeoutError:  # noqa: UP041
            logger.info("审批请求超时 default-deny: request_id=%s tool=%s", req.request_id, req.tool_name)
            return ApprovalAnswer(approved=False, remember=False, answered_by="timeout")
        finally:
            self._pending.pop(req.request_id, None)

    def answer(self, request_id: str, approved: bool, remember: bool = False) -> bool:
        """解析一个挂起的请求。

        Returns:
            True 表示成功解析；False 表示 id 未知 / 已过期 / 已解析。
        """
        entry = self._pending.get(request_id)
        if entry is None:
            return False
        _req, future = entry
        if future.done():
            return False
        future.set_result(
            ApprovalAnswer(approved=approved, remember=remember, answered_by="gui")
        )
        return True

    def pending(self) -> List[ApprovalRequest]:
        """当前所有挂起请求（快照，按注册顺序）。"""
        return [req for req, future in self._pending.values() if not future.done()]

    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """按 id 查挂起请求；未知返回 None。"""
        entry = self._pending.get(request_id)
        return entry[0] if entry is not None else None

    def clear(self) -> None:
        """清空所有挂起请求（测试 / 关闭时用；未解析的 Future 保持挂起由 GC 回收）。"""
        self._pending.clear()


# ---------------------------------------------------------------------------
# 单例装配（与 backend.services.scheduler 相同模式）
# ---------------------------------------------------------------------------

_global_gate: Optional[ApprovalGate] = None


def init_permission_gate() -> ApprovalGate:
    """初始化全局 gate（main.py lifespan 启动时调用一次）。"""
    global _global_gate
    _global_gate = ApprovalGate()
    return _global_gate


def get_permission_gate() -> Optional[ApprovalGate]:
    """取全局 gate；未初始化返回 None（调用方 default-deny）。"""
    return _global_gate


def reset_permission_gate() -> None:
    """重置全局 gate（仅供测试隔离使用）。"""
    global _global_gate
    _global_gate = None


__all__ = [
    "ApprovalAnswer",
    "ApprovalRequest",
    "ApprovalGate",
    "DEFAULT_APPROVAL_TIMEOUT_S",
    "ARG_VALUE_MAX_CHARS",
    "summarize_tool_args",
    "init_permission_gate",
    "get_permission_gate",
    "reset_permission_gate",
]

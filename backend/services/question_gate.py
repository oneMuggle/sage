"""用户提问闸口（M2 part B: AskUserQuestion）。

当 agent 循环遇到 ``ask_user_question`` 工具调用时，通过本模块挂起执行：

1. agent 侧调用 ``UserQuestionGate.request(req, timeout)`` —— 注册一个 Future
   并 await（agent 流在 await 之前先 yield ask_user_question 事件给前端）。
2. 前端收到事件渲染 QuestionDialog，用户选择/填写后
   POST /api/v1/questions/{id}/answer。
3. 路由调用 ``UserQuestionGate.answer(request_id, answers, custom)`` 解析
   Future，agent 循环被唤醒，把应答注入工具执行并继续。
4. 超时未应答 → ``QuestionAnswer(answers=(), custom=None, answered_by="timeout")``
   —— 与审批闸口的 fail-closed 不同，这里是 **fail-open-ish**：超时不阻塞
   agent，工具返回"用户未回答，请自行决定合理默认值"的软结果，循环继续。

单例装配与 ``backend.services.permission_gate`` 完全同构：
``init_question_gate()`` 在 ``main.py`` lifespan 中调用一次，
``get_question_gate()`` 供路由 / agent 取用；未初始化时返回 ``None``，
调用方按"无人应答"处理（同样不挂起）。

并发模型：sage 后端单事件循环，gate 的 dict 操作均在循环线程内，无需加锁。
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

#: 未指定超时时的默认等待秒数（5 分钟，与审批闸口一致）
DEFAULT_QUESTION_TIMEOUT_S = 300.0


@dataclass(frozen=True)
class QuestionAnswer:
    """提问应答（不可变）。

    Attributes:
        answers:    用户选中的选项 label 元组（multi_select 时可多项）。
        custom:     "其他"自由文本（可单独提交，也可与选项并存）。
        answered_by: 应答来源——``"gui"`` / ``"timeout"``。
    """

    answers: Tuple[str, ...]
    custom: Optional[str]
    answered_by: str


@dataclass(frozen=True)
class QuestionRequest:
    """一次待应答的用户提问（不可变）。

    Attributes:
        request_id:   UUID，前端应答时回传。
        question:     展示给用户的完整问题文本。
        header:       可选的短标签（UI chip，如"输出格式"）。
        options:      选项列表，每项 ``{"label": str, "description": str|None}``。
        multi_select: 是否允许多选。
        created_at:   创建时间（epoch 秒）。
    """

    request_id: str
    question: str
    header: Optional[str]
    options: Tuple[Dict[str, Any], ...]
    multi_select: bool
    created_at: float

    def to_dict(self) -> Dict[str, Any]:
        """流事件 / REST 响应共用的 JSON 形态（前端契约，改动需同步前端 agent）。"""
        return {
            "request_id": self.request_id,
            "question": self.question,
            "header": self.header,
            "options": [dict(opt) for opt in self.options],
            "multi_select": self.multi_select,
            "created_at": self.created_at,
        }

    @classmethod
    def create(
        cls,
        question: str,
        options: Sequence[Dict[str, Any]],
        header: Optional[str] = None,
        multi_select: bool = False,
    ) -> QuestionRequest:
        """工厂：生成 UUID + 时间戳，规范化选项。

        防御性规范化（校验层的二道防线）：非字符串 description / header
        一律落为 None——绝不让畸形载荷穿透到前端渲染层炸 UI。
        """
        normalized: Tuple[Dict[str, Any], ...] = tuple(
            {
                "label": str(opt.get("label", "")),
                "description": (
                    opt["description"] if isinstance(opt.get("description"), str) else None
                ),
            }
            for opt in options
        )
        return cls(
            request_id=str(uuid.uuid4()),
            question=question,
            header=header if isinstance(header, str) else None,
            options=normalized,
            multi_select=bool(multi_select),
            created_at=time.time(),
        )


class UserQuestionGate:
    """挂起 / 解析待应答提问的闸口（ApprovalGate 同构）。"""

    def __init__(self) -> None:
        self._pending: Dict[str, Tuple[QuestionRequest, asyncio.Future[QuestionAnswer]]] = {}

    async def request(
        self, req: QuestionRequest, timeout: float = DEFAULT_QUESTION_TIMEOUT_S
    ) -> QuestionAnswer:
        """注册 req 并等待应答；超时返回空应答（answered_by="timeout"）。

        调用方（agent 循环）负责在 await 本方法**之前**把 ask_user_question
        事件推入流，否则前端无从知晓该请求。
        """
        loop = asyncio.get_running_loop()
        future: asyncio.Future[QuestionAnswer] = loop.create_future()
        self._pending[req.request_id] = (req, future)
        try:
            return await asyncio.wait_for(future, timeout=timeout)
        # noqa 说明: py3.8 (Win7 LTS) 下 asyncio.TimeoutError 是
        # concurrent.futures.TimeoutError, 与内建 TimeoutError 不同源;
        # 必须捕获 asyncio.TimeoutError 才能在两个版本上都走超时分支。
        except asyncio.TimeoutError:  # noqa: UP041
            logger.info(
                "用户提问超时，返回空应答: request_id=%s", req.request_id
            )
            return QuestionAnswer(answers=(), custom=None, answered_by="timeout")
        finally:
            self._pending.pop(req.request_id, None)

    def answer(
        self,
        request_id: str,
        answers: Sequence[str],
        custom: Optional[str] = None,
    ) -> bool:
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
            QuestionAnswer(
                answers=tuple(str(a) for a in answers),
                custom=custom,
                answered_by="gui",
            )
        )
        return True

    def pending(self) -> List[QuestionRequest]:
        """当前所有挂起请求（快照，按注册顺序）。"""
        return [req for req, future in self._pending.values() if not future.done()]

    def get_request(self, request_id: str) -> Optional[QuestionRequest]:
        """按 id 查挂起请求；未知返回 None。"""
        entry = self._pending.get(request_id)
        return entry[0] if entry is not None else None

    def clear(self) -> None:
        """清空所有挂起请求（测试 / 关闭时用）。"""
        self._pending.clear()


# ---------------------------------------------------------------------------
# 单例装配（与 backend.services.permission_gate 相同模式）
# ---------------------------------------------------------------------------

_global_gate: Optional[UserQuestionGate] = None


def init_question_gate() -> UserQuestionGate:
    """初始化全局 gate（main.py lifespan 启动时调用一次）。"""
    global _global_gate
    _global_gate = UserQuestionGate()
    return _global_gate


def get_question_gate() -> Optional[UserQuestionGate]:
    """取全局 gate；未初始化返回 None（调用方按"无人应答"处理）。"""
    return _global_gate


def reset_question_gate() -> None:
    """重置全局 gate（仅供测试隔离使用）。"""
    global _global_gate
    _global_gate = None


__all__ = [
    "QuestionAnswer",
    "QuestionRequest",
    "UserQuestionGate",
    "DEFAULT_QUESTION_TIMEOUT_S",
    "init_question_gate",
    "get_question_gate",
    "reset_question_gate",
]

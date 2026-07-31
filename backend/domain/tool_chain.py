"""工具链追踪领域模型（纯，零外部依赖）。

A19 Tool Chain Tracking：追踪一次 agent run 内的工具调用序列——每个
工具的名称、参数、状态、结果摘要与耗时，为前端侧边栏实时进度可视化
提供数据。

**领域纯净性**：本模块不读时钟（``time.monotonic`` 属 I/O，归集成层
边界）。``started_at`` / ``finished_at`` 单调时间戳由调用方（agent
run_loop 集成层）传入，``duration_ms`` 由传入时间戳计算得出。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

# 结果摘要截断长度：前端侧边栏只显示摘要，全量结果走 chat 消息流。
RESULT_SUMMARY_LIMIT = 200
# 错误信息截断长度。
ERROR_MESSAGE_LIMIT = 500


class ToolStepStatus(str, Enum):
    """工具步骤状态。"""

    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class ToolStep:
    """工具链中的单个步骤（一次工具调用）。

    Attributes:
        step_id:       链内自增序号（从 1 开始）
        tool_name:     工具名（如 ``bash`` / ``calculator``）
        args:          调用参数（LLM 生成的原始参数字典的浅拷贝）
        status:        步骤状态（PENDING/RUNNING/DONE/ERROR）
        result:        结果摘要（截断至 ``RESULT_SUMMARY_LIMIT``）
        duration_ms:   执行耗时（毫秒，由调用方传入的时间戳计算）
        started_at:    单调时间戳（秒，调用方传入，仅用于计算耗时）
        finished_at:   单调时间戳（秒，调用方传入）
        error_message: 失败时的错误描述（截断至 ``ERROR_MESSAGE_LIMIT``）
    """

    step_id: int
    tool_name: str
    args: Dict[str, Any] = field(default_factory=dict)
    status: ToolStepStatus = ToolStepStatus.PENDING
    result: str = ""
    duration_ms: float = 0.0
    started_at: float = 0.0
    finished_at: float = 0.0
    error_message: str = ""

    @property
    def is_error(self) -> bool:
        return self.status is ToolStepStatus.ERROR

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好的字典（前端事件载荷形状）。

        单调时间戳（started_at/finished_at）对前端无意义，不下发。
        """
        return {
            "step_id": self.step_id,
            "tool_name": self.tool_name,
            "args": self.args,
            "status": self.status.value,
            "result": self.result,
            "duration_ms": round(self.duration_ms, 1),
            "error_message": self.error_message,
        }


@dataclass
class ToolChain:
    """一次 agent run 的工具调用链。

    Attributes:
        chain_id:     链唯一 ID（由集成层生成，如 uuid）
        description:  链描述（前端标题）
        steps:        步骤列表（按调用顺序追加）
        current_step: 当前运行中步骤的 step_id（0 表示无运行中步骤）
    """

    chain_id: str
    description: str = ""
    steps: List[ToolStep] = field(default_factory=list)
    current_step: int = 0

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def completed_steps(self) -> int:
        """已完成步骤数（DONE 与 ERROR 都算终结）。"""
        return sum(
            1
            for s in self.steps
            if s.status in (ToolStepStatus.DONE, ToolStepStatus.ERROR)
        )

    @property
    def progress(self) -> float:
        """完成进度（0.0 ~ 1.0）。无步骤时为 0.0。"""
        if not self.steps:
            return 0.0
        return self.completed_steps / len(self.steps)

    def to_dict(self) -> Dict[str, Any]:
        """序列化为 JSON 友好的字典（前端事件载荷形状）。"""
        return {
            "chain_id": self.chain_id,
            "description": self.description,
            "steps": [s.to_dict() for s in self.steps],
            "current_step": self.current_step,
            "total_steps": self.total_steps,
            "completed_steps": self.completed_steps,
            "progress": round(self.progress, 4),
        }


class ToolChainTracker:
    """单次 run 的工具链追踪器（状态可变，非线程安全）。

    由 agent run_loop 集成层持有：每次工具调用分发前 ``start_step``、
    观察到结果后 ``complete_step``，每步变更后将 ``chain.to_dict()``
    快照作为事件载荷推送给前端。

    领域层不读时钟：``now`` 为调用方传入的单调时间戳（秒）。
    """

    def __init__(self, chain_id: str, description: str = "Tool Execution") -> None:
        self._chain = ToolChain(chain_id=chain_id, description=description)

    @property
    def chain(self) -> ToolChain:
        return self._chain

    def start_step(
        self, tool_name: str, args: Dict[str, Any], *, now: float
    ) -> ToolStep:
        """登记一个开始执行的工具步骤，返回新建步骤。

        ``args`` 做浅拷贝，避免 LLM 参数字典后续被就地修改污染快照。
        """
        step = ToolStep(
            step_id=len(self._chain.steps) + 1,
            tool_name=tool_name,
            args=dict(args),
            status=ToolStepStatus.RUNNING,
            started_at=now,
        )
        self._chain.steps.append(step)
        self._chain.current_step = step.step_id
        return step

    def complete_step(
        self,
        step_id: int,
        result: str,
        *,
        is_error: bool = False,
        now: float,
    ) -> Optional[ToolStep]:
        """登记步骤执行结果。返回被更新的步骤；step_id 不存在时返回 None。"""
        for step in self._chain.steps:
            if step.step_id != step_id:
                continue
            step.status = ToolStepStatus.ERROR if is_error else ToolStepStatus.DONE
            step.finished_at = now
            step.duration_ms = max(0.0, (now - step.started_at) * 1000.0)
            step.result = _truncate(result, RESULT_SUMMARY_LIMIT)
            if is_error:
                step.error_message = result[:ERROR_MESSAGE_LIMIT]
            if self._chain.current_step == step_id:
                self._chain.current_step = 0
            return step
        return None


def _truncate(text: str, limit: int) -> str:
    """截断长文本并加省略号标记（换行折叠为空格，侧边栏单行显示）。"""
    flat = text.replace("\n", " ")
    if len(flat) <= limit:
        return flat
    return flat[:limit] + "…"

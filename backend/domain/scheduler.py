"""Domain entities, ports and business exceptions for scheduled tasks."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Protocol


class ScheduledTaskNotFoundError(KeyError):
    """Raised when a scheduled task ID does not exist."""


class ScheduledTaskValidationError(ValueError):
    """Raised when scheduled-task input or ownership validation fails."""


@dataclass
class ScheduledTask:
    """Persisted scheduled task (mirrors ``src/shared/api/types.ts``).

    存放于领域层：``SchedulerService``（服务层）与定时任务执行器（应用层）
    都要引用它，下沉到 domain 才能满足六边形依赖方向。
    """

    id: str
    name: str
    type: Literal["once", "recurring"]
    schedule: Dict[str, Any]
    session_id: str
    content: str
    enabled: bool
    created_at: int
    last_run: Optional[int] = None
    next_run: Optional[int] = None
    last_attempt: Optional[int] = None
    last_status: str = "never"
    last_error: Optional[str] = None
    run_count: int = 0
    max_runs: Optional[int] = None
    mode: Literal["execute", "deliver"] = "deliver"
    last_result_message_id: Optional[str] = None
    last_duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> ScheduledTask:
        return cls(
            id=str(raw["id"]),
            name=str(raw["name"]),
            type=raw["type"],  # type: ignore[arg-type]
            schedule=dict(raw["schedule"]),
            session_id=str(raw["session_id"]),
            content=str(raw["content"]),
            enabled=bool(raw["enabled"]),
            created_at=int(raw["created_at"]),
            last_run=int(raw["last_run"]) if raw.get("last_run") is not None else None,
            next_run=int(raw["next_run"]) if raw.get("next_run") is not None else None,
            last_attempt=raw.get("last_attempt"),
            last_status=str(raw.get("last_status", "succeeded" if raw.get("last_run") else "never")),
            last_error=raw.get("last_error"),
            run_count=int(raw.get("run_count", 0) or 0),
            max_runs=int(raw["max_runs"]) if raw.get("max_runs") is not None else None,
            mode=raw.get("mode", "deliver"),  # type: ignore[arg-type]
            last_result_message_id=raw.get("last_result_message_id"),
            last_duration_ms=int(raw["last_duration_ms"]) if raw.get("last_duration_ms") is not None else None,
        )


@dataclass(frozen=True)
class RunOutcome:
    """执行结果，由注入的 ``TaskRunner`` 返回。

    ``error`` 永远为脱敏固定文案，不携带原始异常文本，避免路径/类名/
    凭据泄露（参见方案 §3.8）。
    """

    status: Literal["succeeded", "failed"]
    message_id: Optional[str] = None
    duration_ms: int = 0
    error: Optional[str] = None


TaskRunner = Callable[[ScheduledTask], RunOutcome]


class SchedulerServicePort(Protocol):
    """Minimal scheduler contract consumed by the LLM tools."""

    def add_task(
        self,
        name: str,
        task_type: str,
        schedule: Dict[str, Any],
        session_id: str,
        content: str,
        enabled: bool = True,
        max_runs: Optional[int] = None,
        mode: str = "execute",
    ) -> Any:
        ...

    def list_tasks(self) -> List[Any]:
        ...

    def delete_task(
        self,
        task_id: str,
        expected_session_id: Optional[str] = None,
    ) -> None:
        ...

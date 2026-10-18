"""
闲时自主目标执行系统 — 数据模型定义

该模块定义了自主目标系统的核心数据结构：
- Goal: 用户定义的目标
- Checkpoint: 可验证的检查点
- ExecutionRound: 执行轮次记录
- TimeWindow: 时间窗口配置
- ExecutionBudget: 执行预算配置
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional


class GoalStatus(str, Enum):
    """目标状态"""
    PENDING = "pending"          # 等待执行
    RUNNING = "running"          # 执行中
    PAUSED = "paused"            # 暂停（用户手动或预算暂停）
    COMPLETED = "completed"      # 已完成
    FAILED = "failed"            # 失败
    CANCELLED = "cancelled"      # 已取消


class PricingTier(str, Enum):
    """定价等级"""
    PEAK = "peak"                # 高峰 1.0x
    STANDARD = "standard"        # 平峰 0.7x
    OFF_PEAK = "off_peak"        # 闲时 0.5x
    DYNAMIC = "dynamic"          # 动态定价


class CheckpointType(str, Enum):
    """检查点类型"""
    FILE = "file"                # 文件检查（存在、行数、内容匹配）
    COMMAND = "command"          # 命令执行检查（测试通过、覆盖率达标）
    CODE = "code"                # 代码质量检查（无 lint 错误、无循环依赖）
    CUSTOM = "custom"            # 用户自定义检查


class DegradationLevel(str, Enum):
    """降级等级"""
    NONE = "none"                            # 无降级
    MODEL_DOWNGRADE = "model_downgrade"      # 降级模型
    TASK_SIMPLIFY = "task_simplify"          # 简化任务
    STOPPED = "stopped"                      # 已停止


@dataclass
class TimeWindow:
    """时间窗口配置"""
    off_peak_start: str = "22:00"          # 闲时开始时间 (HH:MM)
    off_peak_end: str = "06:00"            # 闲时结束时间 (HH:MM)
    weekends_off_peak: bool = True         # 周末是否全天闲时
    holidays: List[str] = field(default_factory=list)  # 节假日列表 (YYYY-MM-DD)
    min_pricing_tier: PricingTier = PricingTier.OFF_PEAK  # 最低定价等级要求
    timezone: str = "Asia/Shanghai"        # 时区

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 存储）"""
        return {
            "off_peak_start": self.off_peak_start,
            "off_peak_end": self.off_peak_end,
            "weekends_off_peak": self.weekends_off_peak,
            "holidays": self.holidays,
            "min_pricing_tier": self.min_pricing_tier.value,
            "timezone": self.timezone,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TimeWindow:
        """从字典创建"""
        return cls(
            off_peak_start=data.get("off_peak_start", "22:00"),
            off_peak_end=data.get("off_peak_end", "06:00"),
            weekends_off_peak=data.get("weekends_off_peak", True),
            holidays=data.get("holidays", []),
            min_pricing_tier=PricingTier(data.get("min_pricing_tier", "off_peak")),
            timezone=data.get("timezone", "Asia/Shanghai"),
        )


@dataclass
class ExecutionBudget:
    """执行预算"""
    max_rounds: int = 10                   # 最大轮次
    max_hours: float = 8.0                 # 最大执行时间（小时）
    max_tokens: int = 1_000_000            # 最大 token 消耗
    stop_on_failure: bool = False          # 失败时是否立即停止

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "max_rounds": self.max_rounds,
            "max_hours": self.max_hours,
            "max_tokens": self.max_tokens,
            "stop_on_failure": self.stop_on_failure,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionBudget:
        """从字典创建"""
        return cls(
            max_rounds=data.get("max_rounds", 10),
            max_hours=data.get("max_hours", 8.0),
            max_tokens=data.get("max_tokens", 1_000_000),
            stop_on_failure=data.get("stop_on_failure", False),
        )


@dataclass
class Checkpoint:
    """检查点"""
    id: str                                # 检查点唯一 ID
    type: CheckpointType                   # 检查点类型
    description: str                       # 描述（如"测试覆盖率 >= 80%"）
    verification_command: Optional[str] = None  # 验证命令（如 pytest --cov=...）
    file_path: Optional[str] = None        # 文件路径（文件检查用）
    expected_pattern: Optional[str] = None # 期望模式（正则表达式或字面量）
    verified: bool = False                 # 是否已验证
    verified_at: Optional[datetime] = None # 验证时间

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "type": self.type.value,
            "description": self.description,
            "verification_command": self.verification_command,
            "file_path": self.file_path,
            "expected_pattern": self.expected_pattern,
            "verified": self.verified,
            "verified_at": self.verified_at.isoformat() if self.verified_at else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Checkpoint:
        """从字典创建"""
        verified_at = None
        if data.get("verified_at"):
            verified_at = datetime.fromisoformat(data["verified_at"])

        return cls(
            id=data["id"],
            type=CheckpointType(data["type"]),
            description=data["description"],
            verification_command=data.get("verification_command"),
            file_path=data.get("file_path"),
            expected_pattern=data.get("expected_pattern"),
            verified=data.get("verified", False),
            verified_at=verified_at,
        )


@dataclass
class ExecutionRound:
    """执行轮次"""
    round_number: int                      # 轮次编号
    started_at: datetime                   # 开始时间
    completed_at: Optional[datetime] = None  # 完成时间
    tasks_executed: int = 0                # 执行的任务数
    tasks_succeeded: int = 0               # 成功的任务数
    tasks_failed: int = 0                  # 失败的任务数
    tokens_used: int = 0                   # 消耗的 token 数
    checkpoints_verified: int = 0          # 验证的检查点数
    degradation_level: DegradationLevel = DegradationLevel.NONE  # 降级等级
    error_message: Optional[str] = None    # 错误信息
    llm_review: Optional[str] = None       # LLM 审查意见

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "round_number": self.round_number,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "tasks_executed": self.tasks_executed,
            "tasks_succeeded": self.tasks_succeeded,
            "tasks_failed": self.tasks_failed,
            "tokens_used": self.tokens_used,
            "checkpoints_verified": self.checkpoints_verified,
            "degradation_level": self.degradation_level.value,
            "error_message": self.error_message,
            "llm_review": self.llm_review,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionRound:
        """从字典创建"""
        return cls(
            round_number=data["round_number"],
            started_at=datetime.fromisoformat(data["started_at"]),
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            tasks_executed=data.get("tasks_executed", 0),
            tasks_succeeded=data.get("tasks_succeeded", 0),
            tasks_failed=data.get("tasks_failed", 0),
            tokens_used=data.get("tokens_used", 0),
            checkpoints_verified=data.get("checkpoints_verified", 0),
            degradation_level=DegradationLevel(data.get("degradation_level", "none")),
            error_message=data.get("error_message"),
            llm_review=data.get("llm_review"),
        )


@dataclass
class Goal:
    """自主目标"""
    id: str                                # 目标唯一 ID
    name: str                              # 目标名称
    description: str                       # 目标描述
    status: GoalStatus = GoalStatus.PENDING  # 状态
    session_id: Optional[str] = None       # 关联的聊天会话 ID

    # 配置
    time_window: TimeWindow = field(default_factory=TimeWindow)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)

    # 检查点
    checkpoints: List[Checkpoint] = field(default_factory=list)

    # 执行历史
    rounds: List[ExecutionRound] = field(default_factory=list)
    current_round: int = 0                 # 当前轮次

    # 元数据
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None  # 开始执行时间
    completed_at: Optional[datetime] = None  # 完成时间
    total_tokens_used: int = 0             # 总 token 消耗
    completion_percentage: float = 0.0     # 完成百分比

    # 降级与错误
    degradation_level: DegradationLevel = DegradationLevel.NONE
    last_error: Optional[str] = None       # 最后错误信息

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "status": self.status.value,
            "session_id": self.session_id,
            "time_window": self.time_window.to_dict(),
            "budget": self.budget.to_dict(),
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "rounds": [r.to_dict() for r in self.rounds],
            "current_round": self.current_round,
            "created_at": self.created_at.isoformat(),
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "total_tokens_used": self.total_tokens_used,
            "completion_percentage": self.completion_percentage,
            "degradation_level": self.degradation_level.value,
            "last_error": self.last_error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Goal:
        """从字典创建"""
        return cls(
            id=data["id"],
            name=data["name"],
            description=data["description"],
            status=GoalStatus(data.get("status", "pending")),
            session_id=data.get("session_id"),
            time_window=TimeWindow.from_dict(data.get("time_window", {})),
            budget=ExecutionBudget.from_dict(data.get("budget", {})),
            checkpoints=[Checkpoint.from_dict(c) for c in data.get("checkpoints", [])],
            rounds=[ExecutionRound.from_dict(r) for r in data.get("rounds", [])],
            current_round=data.get("current_round", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.utcnow(),  # noqa: DTZ003
            started_at=datetime.fromisoformat(data["started_at"]) if data.get("started_at") else None,
            completed_at=datetime.fromisoformat(data["completed_at"]) if data.get("completed_at") else None,
            total_tokens_used=data.get("total_tokens_used", 0),
            completion_percentage=data.get("completion_percentage", 0.0),
            degradation_level=DegradationLevel(data.get("degradation_level", "none")),
            last_error=data.get("last_error"),
        )

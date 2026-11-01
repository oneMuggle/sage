"""动态迭代预算与进度审计（2026-10-31）。

把固定 ``max_iterations`` 拆成两层：

- **安全预算（硬）**：token / 墙钟 / 工具调用数，由调用方（run_loop / dispatcher）约束；
- **迭代预算（软）**：按任务复杂度分级初始化，到达检查点后由本模块审计
  "卡死 vs 确实需要更多步"，决定自动延长或带证据停止。

本模块保持纯函数：不读数据库、不发事件，便于单测。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, replace
from typing import Any, Dict, List, Literal, Optional, Sequence, Set, Tuple

BudgetLevel = Literal["simple", "medium", "complex", "long"]
BudgetAction = Literal["extend", "stop"]
BudgetStopReason = Literal["stuck", "no_progress", "extension_limit", "hard_cap"]

#: 会改工作区/产出产物的工具 —— 命中即视为"有进展"。与前端
#: FILE_CHANGE_TOOLS / office 产物工具保持同源语义。
_FILE_CHANGE_TOOLS = frozenset(
    {
        "write_file",
        "edit_file",
        "apply_patch",
        "office_create",
        "office_update",
        "office_restore",
        "office_fill_word_template",
        "office_fill_ppt_template",
        "office_fill_latex_template",
        "office_generate_pdf",
        "office_compile_latex",
    }
)

#: 生成新产物的工具（用于 progress_signals 的产物计数）。
_ARTIFACT_TOOLS = frozenset(
    {
        "office_create",
        "office_generate_pdf",
        "office_compile_latex",
    }
)

#: 工具错误结果的内容前缀（messages 里没有 is_error 字段，只能按文案判定）。
_ERROR_MARKERS = (
    "[错误]",
    "[工具错误]",
    "[参数错误]",
    "[拦截]",
    "hook 拒绝",
    "工具执行失败",
)

#: 复杂度关键词 —— 只做加权，不单独决定等级。
_COMPLEX_KEYWORDS = re.compile(
    r"重构|迁移|实现|设计|全量|端到端|长任务|批量|整个项目|"
    r"refactor|migrat|implement|design|end-to-end",
    re.IGNORECASE,
)


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class BudgetConfig:
    """动态预算参数。全部可经 env 覆盖，便于测试与运维排障。"""

    simple_budget: int = 20
    medium_budget: int = 80
    complex_budget: int = 200
    long_budget: int = 400
    hard_cap: int = 1000
    extension_ratio: float = 0.5
    min_extension: int = 30
    max_extension: int = 200
    max_extensions: int = 3
    window: int = 8
    repeat_soft: int = 3
    repeat_hard: int = 5
    no_progress_threshold: int = 6
    error_streak_threshold: int = 3

    @classmethod
    def from_settings(cls, settings: Any) -> BudgetConfig:
        """以 env 为基线，用设置页 ``OrchSettings`` 覆盖未由 env 指定的项。

        优先级：环境变量 > 设置页 > 代码默认（env 保留 CI/运维覆盖能力）。
        ``settings`` 允许为 None 或缺少新字段的旧测试替身。
        """
        base = cls.from_env()

        def _override(env_name: str, attr: str, current: int, minimum: int) -> int:
            if env_name in os.environ:
                return current
            value = getattr(settings, attr, None) if settings is not None else None
            if isinstance(value, int) and not isinstance(value, bool):
                return max(minimum, int(value))
            return current

        return replace(
            base,
            simple_budget=_override(
                "SAGE_DYNAMIC_BUDGET_SIMPLE", "budget_simple", base.simple_budget, 1
            ),
            medium_budget=_override(
                "SAGE_DYNAMIC_BUDGET_MEDIUM", "budget_medium", base.medium_budget, 1
            ),
            complex_budget=_override(
                "SAGE_DYNAMIC_BUDGET_COMPLEX", "budget_complex", base.complex_budget, 1
            ),
            long_budget=_override(
                "SAGE_DYNAMIC_BUDGET_LONG", "budget_long", base.long_budget, 1
            ),
            hard_cap=_override(
                "SAGE_DYNAMIC_BUDGET_HARD_CAP", "budget_hard_cap", base.hard_cap, 1
            ),
            max_extensions=_override(
                "SAGE_DYNAMIC_BUDGET_MAX_EXTENSIONS",
                "budget_max_extensions",
                base.max_extensions,
                0,
            ),
        )

    @classmethod
    def from_env(cls) -> BudgetConfig:
        return cls(
            simple_budget=_env_int("SAGE_DYNAMIC_BUDGET_SIMPLE", 20),
            medium_budget=_env_int("SAGE_DYNAMIC_BUDGET_MEDIUM", 80),
            complex_budget=_env_int("SAGE_DYNAMIC_BUDGET_COMPLEX", 200),
            long_budget=_env_int("SAGE_DYNAMIC_BUDGET_LONG", 400),
            hard_cap=_env_int("SAGE_DYNAMIC_BUDGET_HARD_CAP", 1000),
            extension_ratio=_env_float("SAGE_DYNAMIC_BUDGET_EXTENSION_RATIO", 0.5),
            min_extension=_env_int("SAGE_DYNAMIC_BUDGET_MIN_EXTENSION", 30),
            max_extension=_env_int("SAGE_DYNAMIC_BUDGET_MAX_EXTENSION", 200),
            max_extensions=_env_int("SAGE_DYNAMIC_BUDGET_MAX_EXTENSIONS", 3),
            window=_env_int("SAGE_DYNAMIC_BUDGET_WINDOW", 8),
            # 与 run_loop 现有复读守卫共用同一组 env，口径一致。
            repeat_soft=_env_int("SAGE_TOOL_REPEAT_SOFT_LIMIT", 3),
            repeat_hard=_env_int("SAGE_TOOL_REPEAT_HARD_LIMIT", 5),
            no_progress_threshold=_env_int("SAGE_DYNAMIC_BUDGET_NO_PROGRESS", 6),
            error_streak_threshold=_env_int("SAGE_DYNAMIC_BUDGET_ERROR_STREAK", 3),
        )


@dataclass(frozen=True)
class StepRecord:
    """单个 ReAct step 的进度快照（从 messages 增量推导）。"""

    index: int
    signatures: Tuple[str, ...] = ()
    result_hashes: Tuple[str, ...] = ()
    content_chars: int = 0
    file_changes: int = 0
    artifacts: int = 0
    error_hashes: Tuple[str, ...] = ()
    todo_updates: int = 0
    productive: bool = False


@dataclass(frozen=True)
class BudgetAudit:
    stuck_score: float
    progress_signals: int
    reasons: Tuple[str, ...] = ()
    max_repeat: int = 0
    cycle_detected: bool = False
    error_streak: int = 0
    no_progress_steps: int = 0


@dataclass(frozen=True)
class BudgetDecision:
    action: BudgetAction
    next_budget: int
    reason: str
    audit: BudgetAudit


def _canonical_arguments(arguments: Any) -> str:
    try:
        if isinstance(arguments, str):
            parsed = json.loads(arguments)
            return json.dumps(parsed, sort_keys=True, ensure_ascii=False)
        return json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str)
    except (json.JSONDecodeError, TypeError, ValueError):
        return str(arguments)


def tool_signature(name: str, arguments: Any) -> str:
    """规范化工具调用签名（工具名 + 排序后的参数 JSON）。"""
    return f"{name}:{_canonical_arguments(arguments)}"


def _hash_text(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def estimate_initial_budget(
    message: str,
    *,
    has_attachments: bool = False,
    project_bound: bool = False,
    plan_mode: bool = False,
    long_task: bool = False,
    profile_floor: Optional[int] = None,
    config: Optional[BudgetConfig] = None,
) -> Tuple[int, BudgetLevel]:
    """按任务信号估算初始迭代预算。

    零额外 LLM 调用，纯启发式；分类不确定时偏向 medium，避免误杀。
    ``profile_floor`` 作为下限参与取最大值，不把用户已配置的预算降回去。
    """
    cfg = config or BudgetConfig()
    text = message or ""
    score = 0
    if len(text) > 500:
        score += 10
    if has_attachments:
        score += 10
    if project_bound:
        score += 10
    if plan_mode:
        score += 30
    if long_task:
        score += 50
    keyword_hits = len(_COMPLEX_KEYWORDS.findall(text))
    if keyword_hits:
        # 单关键词只升到 medium；多个强信号（重构+迁移+设计…）累计到 complex。
        score += min(45, 15 * keyword_hits)

    if long_task:
        level: BudgetLevel = "long"
    elif score >= 45:
        level = "complex"
    elif score >= 15:
        level = "medium"
    else:
        level = "simple"

    budget = {
        "simple": cfg.simple_budget,
        "medium": cfg.medium_budget,
        "complex": cfg.complex_budget,
        "long": cfg.long_budget,
    }[level]

    if profile_floor is not None and profile_floor > budget:
        budget = profile_floor
    budget = max(1, min(int(budget), cfg.hard_cap))
    return budget, level


def build_step_record(
    index: int,
    messages: Sequence[Any],
    seen_result_hashes: Set[str],
) -> StepRecord:
    """从某个 step 新增的 messages 推导 StepRecord。

    - assistant 消息里的 tool_calls → 签名 / 文件变更 / 产物 / todo；
    - tool 消息 → 结果哈希（新哈希才算进展）与错误标记；
    - assistant 正文长度 → 内容产出。

    ``seen_result_hashes`` 会被原地更新（跨 step 全局去重）。
    """
    signatures: List[str] = []
    result_hashes: List[str] = []
    error_hashes: List[str] = []
    content_chars = 0
    file_changes = 0
    artifacts = 0
    todo_updates = 0

    for message in messages:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "assistant":
            content = message.get("content")
            if isinstance(content, str):
                content_chars += len(content)
            for tool_call in message.get("tool_calls") or []:
                if not isinstance(tool_call, dict):
                    continue
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    continue
                name = function.get("name")
                if not isinstance(name, str) or not name:
                    continue
                signatures.append(tool_signature(name, function.get("arguments")))
                if name in _FILE_CHANGE_TOOLS:
                    file_changes += 1
                if name in _ARTIFACT_TOOLS:
                    artifacts += 1
                if name == "todo_write":
                    todo_updates += 1
        elif role == "tool":
            content = message.get("content")
            if isinstance(content, str):
                text = content
            else:
                text = json.dumps(content, ensure_ascii=False, default=str)
            digest = _hash_text(text)
            if digest not in seen_result_hashes:
                seen_result_hashes.add(digest)
                result_hashes.append(digest)
            if any(marker in text for marker in _ERROR_MARKERS):
                error_hashes.append(digest)

    productive = bool(
        signatures
        and (file_changes or artifacts or todo_updates)
        or result_hashes
        or content_chars > 0
    )
    return StepRecord(
        index=index,
        signatures=tuple(signatures),
        result_hashes=tuple(result_hashes),
        content_chars=content_chars,
        file_changes=file_changes,
        artifacts=artifacts,
        error_hashes=tuple(error_hashes),
        todo_updates=todo_updates,
        productive=productive,
    )


def _detect_cycle(step_signatures: Sequence[Tuple[str, ...]]) -> bool:
    flat: List[str] = [signature for step in step_signatures for signature in step]
    for period in (2, 3):
        if len(flat) >= period * 2:
            tail = flat[-period * 2 :]
            if tail[:period] == tail[period:]:
                return True
    return False


def _error_streak(records: Sequence[StepRecord]) -> int:
    streak = 0
    target: Optional[Set[str]] = None
    for record in reversed(records):
        if not record.error_hashes:
            break
        if target is None:
            target = set(record.error_hashes)
            streak = 1
        elif any(digest in target for digest in record.error_hashes):
            streak += 1
        else:
            break
    return streak


def _trailing_no_progress(records: Sequence[StepRecord]) -> int:
    count = 0
    for record in reversed(records):
        if record.productive:
            break
        count += 1
    return count


def audit_window(
    records: Sequence[StepRecord],
    config: Optional[BudgetConfig] = None,
) -> BudgetAudit:
    """审计最近窗口内的进度，给出 stuck 分数与进展信号。"""
    cfg = config or BudgetConfig()
    recent = list(records)[-max(1, cfg.window) :]
    if not recent:
        return BudgetAudit(stuck_score=0.0, progress_signals=0, reasons=("no_history",))

    repeat_counts: Dict[str, int] = {}
    for record in recent:
        for signature in record.signatures:
            repeat_counts[signature] = repeat_counts.get(signature, 0) + 1
    max_repeat = max(repeat_counts.values(), default=0)

    cycle_detected = _detect_cycle([record.signatures for record in recent])
    error_streak = _error_streak(recent)
    no_progress_steps = _trailing_no_progress(recent)

    progress_signals = sum(
        record.file_changes + record.artifacts + record.todo_updates
        for record in recent
    )
    progress_signals += sum(len(record.result_hashes) for record in recent)
    if any(record.content_chars > 0 for record in recent):
        progress_signals += 1

    reasons: List[str] = []
    stuck_score = 0.0
    if cfg.repeat_hard > 0 and max_repeat >= cfg.repeat_hard:
        stuck_score = 1.0
        reasons.append(f"repeat_hard={max_repeat}")
    elif cfg.repeat_soft > 0 and max_repeat >= cfg.repeat_soft:
        stuck_score = max(stuck_score, 0.6 + 0.1 * (max_repeat - cfg.repeat_soft))
        reasons.append(f"repeat_soft={max_repeat}")
    if cycle_detected:
        stuck_score = max(stuck_score, 0.85)
        reasons.append("cycle_detected")
    if error_streak >= cfg.error_streak_threshold:
        stuck_score = max(stuck_score, 0.8)
        reasons.append(f"error_streak={error_streak}")
    if no_progress_steps >= cfg.no_progress_threshold:
        stuck_score = max(stuck_score, 0.75)
        reasons.append(f"no_progress={no_progress_steps}")
    elif no_progress_steps >= max(2, cfg.no_progress_threshold - 2):
        stuck_score = max(stuck_score, 0.55)
        reasons.append(f"slow_progress={no_progress_steps}")

    return BudgetAudit(
        stuck_score=min(1.0, round(stuck_score, 3)),
        progress_signals=progress_signals,
        reasons=tuple(reasons),
        max_repeat=max_repeat,
        cycle_detected=cycle_detected,
        error_streak=error_streak,
        no_progress_steps=no_progress_steps,
    )


def decide_budget(
    current_budget: int,
    audit: BudgetAudit,
    extension_count: int,
    config: Optional[BudgetConfig] = None,
) -> BudgetDecision:
    """根据审计结果决定延长还是停止。"""
    cfg = config or BudgetConfig()
    if audit.stuck_score >= 0.7:
        return BudgetDecision("stop", current_budget, "stuck", audit)
    if extension_count >= cfg.max_extensions:
        return BudgetDecision("stop", current_budget, "extension_limit", audit)
    if audit.progress_signals <= 0:
        return BudgetDecision("stop", current_budget, "no_progress", audit)

    chunk = int(current_budget * cfg.extension_ratio)
    chunk = max(cfg.min_extension, min(cfg.max_extension, chunk))
    next_budget = min(cfg.hard_cap, max(current_budget + 1, current_budget + chunk))
    if next_budget <= current_budget:
        return BudgetDecision("stop", current_budget, "hard_cap", audit)
    return BudgetDecision("extend", next_budget, "progress", audit)


def build_budget_info(
    *,
    level: BudgetLevel,
    previous_budget: int,
    next_budget: int,
    extensions: int,
    audit: BudgetAudit,
) -> Dict[str, Any]:
    """构造随 ITERATION_CHECKPOINT 事件下发的 UI 载荷。"""
    return {
        "level": level,
        "previous_budget": previous_budget,
        "next_budget": next_budget,
        "extensions": extensions,
        "stuck_score": audit.stuck_score,
        "progress_signals": audit.progress_signals,
        "reasons": list(audit.reasons),
    }


__all__ = [
    "BudgetAction",
    "BudgetAudit",
    "BudgetConfig",
    "BudgetDecision",
    "BudgetLevel",
    "BudgetStopReason",
    "StepRecord",
    "audit_window",
    "build_budget_info",
    "build_step_record",
    "decide_budget",
    "estimate_initial_budget",
    "tool_signature",
]

"""LLM 重试配置的单一真相源 (Single Source of Truth).

本模块集中定义:
1. ``RETRY_DEFAULTS`` — 四个重试参数的后端默认值（前端 DEFAULT_SETTINGS 须与之对齐）
2. ``RetrySettings`` — 解析后的不可变配置对象（含来源标注）
3. ``resolve_retry_settings(raw)`` — 统一的解析函数：
   - ``to_camel()`` 归一化入参键名（消除 snake_case 残留不可见问题）
   - ``env`` > ``app_settings`` > ``RETRY_DEFAULTS`` 三级优先级
   - 类型/范围校验失败时 ``logger.warning`` 并回退默认（绝不静默丢弃）
   - ``base_delay_s <= max_delay_s`` 交叉校验

调用方:
- ``backend.core.legacy.llm_client._retry_settings()`` — 运行时重试参数
- ``backend.chat.env_context.build_configuration_summary_block()`` — LLM 配置摘要

设计约束:
- Python 3.8 兼容（win7 分支）: 只用 ``typing.Dict`` / ``typing.Optional`` /
  ``typing.Mapping`` / ``typing.Tuple``, 禁止 PEP 585 / PEP 604
- ``to_camel`` 惰性导入避免模块加载期循环依赖
- 不依赖 pydantic（避免 v1/v2 双分支适配）
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 默认值（单一真相源）
# ---------------------------------------------------------------------------
# 2026-11-03: 从 3/1.0/15.0/180 调整到 5/2.0/60.0/300。
# 理由:
# - max_attempts 3→5: 含首次 = 4 次重试, 覆盖瞬时抖动/网关 502
# - base_delay 1.0→2.0: 1s 对刚超时 60s 的上游等于无退避
# - max_delay 15.0→60.0: 与 llmProxyTimeoutS 默认 60s 同量级;
#   同时消除与前端 DEFAULT_SETTINGS 30.0 的漂移 (两边都统一到 60.0)
# - total_budget 180→300: 5 次 × 60s 在途 = 300s; 预算须 ≥ 在途总量

RETRY_DEFAULTS: Dict[str, Any] = {
    "llmRetryMaxAttempts": 5,
    "llmRetryBaseDelayS": 2.0,
    "llmRetryMaxDelayS": 60.0,
    "llmRetryTotalBudgetS": 300,
}

#: 四个重试键的有序列表（遍历时保持稳定的输出顺序）
RETRY_KEYS: Tuple[str, ...] = (
    "llmRetryMaxAttempts",
    "llmRetryBaseDelayS",
    "llmRetryMaxDelayS",
    "llmRetryTotalBudgetS",
)

#: 各键的取值域（闭区间）—— 写入侧拒绝与运行时回退共用同一份定义。
#: 上限用于挡住明显笔误 / 失控配置（如 maxAttempts=5000 会把请求挂住数小时）。
RETRY_RANGES: Dict[str, Tuple[float, float]] = {
    "llmRetryMaxAttempts": (1, 100),
    "llmRetryBaseDelayS": (0.0, 600.0),
    "llmRetryMaxDelayS": (1.0, 3600.0),
    "llmRetryTotalBudgetS": (0.0, 86400.0),
}

#: 环境变量名 → camelCase 键名映射
_ENV_TO_KEY: Dict[str, str] = {
    "SAGE_LLM_RETRY_MAX_ATTEMPTS": "llmRetryMaxAttempts",
    "SAGE_LLM_RETRY_BASE_DELAY_S": "llmRetryBaseDelayS",
    "SAGE_LLM_RETRY_MAX_DELAY_S": "llmRetryMaxDelayS",
    "SAGE_LLM_RETRY_TOTAL_BUDGET_S": "llmRetryTotalBudgetS",
}


# ---------------------------------------------------------------------------
# RetrySettings 数据类
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RetrySettings:
    """解析后的重试配置（不可变）.

    Attributes:
        max_attempts: 最大尝试次数（含首次请求）；>= 1
        base_delay_s: 指数退避基数（秒）；>= 0
        max_delay_s: 单次退避上限（秒）；>= 1.0
        total_budget_s: 自动重试总时长预算（秒）；0 = 不限
        sources: 每个键的来源标注 — "app_settings" | "env" | "default"
    """

    max_attempts: int
    base_delay_s: float
    max_delay_s: float
    total_budget_s: float
    sources: Mapping[str, str]


class RetrySettingsValueError(ValueError):
    """重试参数取值非法 —— ``field`` 携带出错的键名。

    HTTP 层据此把 ``detail.field`` 指向具体键；异常消息本身含用户输入的原始
    值，**不得**直接序列化进 HTTP 响应（沿用
    ``classify_settings_validation_error`` 的脱敏约定）。
    """

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


# ---------------------------------------------------------------------------
# 解析函数
# ---------------------------------------------------------------------------


def _to_camel(value: Any) -> Any:
    """惰性导入 ``to_camel`` 以避免模块加载期循环依赖."""
    from backend.data.settings_canonicalizer import to_camel

    return to_camel(value)


def _coerce_int(value: Any) -> Optional[int]:
    """尝试把 value 转成 int。接受 int / 整数值 float / 数字字符串。

    返回 None 表示无法转换。
    """
    if isinstance(value, bool):
        # bool 是 int 子类，但不应被接受为重试次数
        return None
    if isinstance(value, int):
        return value

    candidate: Optional[float] = None
    if isinstance(value, float):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = float(value)
        except ValueError:
            candidate = None
    # NaN / inf 必须拒绝：NaN 与任意数比较恒为 False 会绕过取值域检查，
    # 且 int(nan) / int(inf) 分别抛 ValueError / OverflowError。
    if candidate is None or not math.isfinite(candidate):
        return None
    return int(candidate) if candidate == int(candidate) else None


def _coerce_float(value: Any) -> Optional[float]:
    """尝试把 value 转成 float。接受 int / float / 数字字符串。

    返回 None 表示无法转换（含 NaN / inf / 超出 float 范围的巨整数）。
    """
    if isinstance(value, bool):
        return None
    candidate: Optional[float] = None
    if isinstance(value, int):  # noqa: UP038 - py38 运行时 isinstance 不支持 X | Y
        # Python int 无上限（JSON 可解析出 10**400），float() 会抛 OverflowError。
        try:
            candidate = float(value)
        except OverflowError:
            candidate = None
    elif isinstance(value, float):
        candidate = value
    elif isinstance(value, str):
        try:
            candidate = float(value)
        except ValueError:
            candidate = None
    if candidate is None or not math.isfinite(candidate):
        return None
    return candidate


def _validate_one(
    key: str,
    raw: Any,
    source: str,
    effective_defaults: Mapping[str, Any],
) -> Tuple[Any, str]:
    """校验单个重试参数；非法则 warning + 回退默认。

    返回 ``(值, 来源)``。来源在回退时置为 ``"default"``。
    """
    lower, upper = RETRY_RANGES[key]
    if key == "llmRetryMaxAttempts":
        coerced = _coerce_int(raw)
        kind = "整数"
    else:
        coerced = _coerce_float(raw)
        kind = "数值"
    if coerced is None or coerced < lower or coerced > upper:
        logger.warning(
            "%s=%r 无效 (须为 %s 到 %s 之间的%s, 来源=%s), 回退默认 %s",
            key,
            raw,
            lower,
            upper,
            kind,
            source,
            effective_defaults[key],
        )
        return effective_defaults[key], "default"
    return coerced, source


def validate_retry_values(
    values: Mapping[str, Any],
    effective_values: Optional[Mapping[str, Any]] = None,
) -> None:
    """校验重试参数取值域；非法抛 ``ValueError``（消息含字段名）。

    与 ``resolve_retry_settings`` 共用同一套 coerce 逻辑和取值域定义，
    区别只在失败语义：写入侧直接拒绝，运行时回退默认 + warning。

    只校验 ``values`` 里实际存在的键 —— 缺失的键走默认值，无需校验。

    ``effective_values`` 提供存量/合并后的值，仅用于 ``base_delay <= max_delay``
    交叉校验的另一半。交叉校验只在本次 payload 至少包含这对键之一时触发，
    这样历史存量的非法配对不会把用户锁死（改无关字段仍可提交）。
    """
    if not values or not isinstance(values, Mapping):
        return
    try:
        normalized = _to_camel(dict(values))
    except Exception:
        normalized = dict(values)
    if not isinstance(normalized, dict):
        return

    validated: Dict[str, float] = {}
    for key in RETRY_KEYS:
        if key not in normalized:
            continue
        raw = normalized[key]
        lower, upper = RETRY_RANGES[key]
        if key == "llmRetryMaxAttempts":
            coerced = _coerce_int(raw)
            kind = "整数"
        else:
            coerced = _coerce_float(raw)
            kind = "数值"
        if coerced is None:
            raise RetrySettingsValueError(key, f"{key} 必须是{kind}: {raw!r}")
        if coerced < lower or coerced > upper:
            raise RetrySettingsValueError(
                key, f"{key} 必须在 {lower} 到 {upper} 之间: {raw!r}"
            )
        validated[key] = float(coerced)

    _validate_base_vs_max(normalized, validated, effective_values)


def _validate_base_vs_max(
    payload: Mapping[str, Any],
    validated: Mapping[str, float],
    effective_values: Optional[Mapping[str, Any]],
) -> None:
    """写入侧交叉校验 ``base_delay_s <= max_delay_s``.

    运行时遇到 base > max 会静默回退默认值 —— 若写入侧不拦，用户会看到
    "已自定义"徽章但实际不生效，正是本模块要消除的那类不可见回退。
    """
    pair_keys = ("llmRetryBaseDelayS", "llmRetryMaxDelayS")
    if not any(key in payload for key in pair_keys):
        return

    merged: Dict[str, Any] = {}
    if effective_values and isinstance(effective_values, Mapping):
        try:
            merged.update(_to_camel(dict(effective_values)))
        except Exception:
            merged.update(dict(effective_values))
    merged.update(payload)

    base = _effective_for_cross_check("llmRetryBaseDelayS", merged, validated)
    max_delay = _effective_for_cross_check("llmRetryMaxDelayS", merged, validated)
    if base is None or max_delay is None:
        # 另一半本身非法/缺失 —— 交由逐键校验或运行时回退处理。
        return
    if base > max_delay:
        field = (
            "llmRetryBaseDelayS"
            if "llmRetryBaseDelayS" in payload
            else "llmRetryMaxDelayS"
        )
        raise RetrySettingsValueError(
            field,
            f"llmRetryBaseDelayS({base}) 不得大于 llmRetryMaxDelayS({max_delay})",
        )


def _effective_for_cross_check(
    key: str,
    merged: Mapping[str, Any],
    validated: Mapping[str, float],
) -> Optional[float]:
    """取交叉校验用的有效值，口径与运行时 ``resolve_retry_settings`` 一致.

    本次 payload 已通过逐键校验的值直接用；缺失或存量值越界时回退默认 ——
    运行时同样会回退默认，因此这里不应对一个实际不会生效的存量值报错。
    """
    if key in validated:
        return validated[key]
    candidate = _coerce_float(merged.get(key, RETRY_DEFAULTS[key]))
    if candidate is None:
        return None
    lower, upper = RETRY_RANGES[key]
    if candidate < lower or candidate > upper:
        return float(RETRY_DEFAULTS[key])
    return candidate


def resolve_retry_settings(
    raw_app_settings: Optional[Mapping[str, Any]],
    defaults: Optional[Mapping[str, Any]] = None,
) -> RetrySettings:
    """解析重试配置：env > app_settings > defaults (或 RETRY_DEFAULTS).

    参数:
        raw_app_settings: 原始的 app_settings dict（可以是 camelCase 或 snake_case
            键名，本函数会用 to_camel() 归一化）。None 视为空 dict。
        defaults: 自定义默认值（用于测试 monkeypatch 或 llm_client 兼容层）。
            None 时使用模块级 ``RETRY_DEFAULTS``。

    返回:
        RetrySettings 实例，包含解析后的值和来源标注。

    行为:
        - 类型/范围不合法时 ``logger.warning`` 并回退到该键的默认值
        - ``base_delay_s > max_delay_s`` 时两者都回退默认并记 warning
        - 永不抛异常
    """
    effective_defaults = dict(defaults) if defaults else dict(RETRY_DEFAULTS)
    # 1. 归一化键名
    if raw_app_settings and isinstance(raw_app_settings, Mapping):
        try:
            normalized = _to_camel(dict(raw_app_settings))
        except Exception as exc:
            # to_camel 不应抛；真抛了也不能静默丢弃全部 app_settings。
            logger.warning("to_camel(app_settings) 失败, 重试参数全部回退默认: %s", exc)
            normalized = {}
    else:
        normalized = {}

    if not isinstance(normalized, dict):
        normalized = {}

    sources: Dict[str, str] = {}
    values: Dict[str, Any] = {}

    # 2. 逐键解析: env > app_settings > default
    # env 优先级最高：用于调试/测试覆盖，确保环境变量能压过 DB 中的值。
    for key in RETRY_KEYS:
        app_val = normalized.get(key)
        env_name = next(
            (k for k, v in _ENV_TO_KEY.items() if v == key), None
        )
        env_val = os.environ.get(env_name, "").strip() if env_name else ""

        if env_val:
            values[key] = env_val
            sources[key] = "env"
        elif app_val is not None:
            values[key] = app_val
            sources[key] = "app_settings"
        else:
            values[key] = effective_defaults[key]
            sources[key] = "default"

    # 3. 类型/范围校验（与写入侧 validate_retry_values 共用同一份取值域）
    for key in RETRY_KEYS:
        value, source = _validate_one(
            key, values[key], sources[key], effective_defaults
        )
        values[key] = value
        sources[key] = source

    max_attempts = int(values["llmRetryMaxAttempts"])
    base_delay_s = float(values["llmRetryBaseDelayS"])
    max_delay_s = float(values["llmRetryMaxDelayS"])
    total_budget_s = float(values["llmRetryTotalBudgetS"])

    # 4. 交叉校验: base_delay_s <= max_delay_s
    if base_delay_s > max_delay_s:
        logger.warning(
            "llmRetryBaseDelayS(%s) > llmRetryMaxDelayS(%s), 二者回退默认",
            base_delay_s,
            max_delay_s,
        )
        base_delay_s = effective_defaults["llmRetryBaseDelayS"]
        max_delay_s = effective_defaults["llmRetryMaxDelayS"]
        sources["llmRetryBaseDelayS"] = "default"
        sources["llmRetryMaxDelayS"] = "default"

    return RetrySettings(
        max_attempts=max_attempts,
        base_delay_s=base_delay_s,
        max_delay_s=max_delay_s,
        total_budget_s=total_budget_s,
        sources=sources,
    )

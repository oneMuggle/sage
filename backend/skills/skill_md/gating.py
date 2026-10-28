"""SKILL.md 条件加载门控（v2）。

评估技能是否满足加载条件：
- requires.bins: 依赖的二进制工具（如 git/docker）
- requires.env: 依赖的环境变量
- requires.config: 依赖的配置键
- os: 平台过滤（macos/linux/windows）
- always: 跳过门控，始终加载

设计要点：
- GatingContext 快照环境状态，避免重复 syscall
- evaluate_gating 是纯函数，易测试
- 门控失败 → loader 静默 skip + INFO 日志（不抛异常）
- always=True 跳过门控，但仍记录 GatingResult（诊断用）
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, FrozenSet, List, Optional, Set, Tuple

if TYPE_CHECKING:
    from backend.data.settings_repo import SettingsRepository

    from .skill import SkillMdDocument


@dataclass(frozen=True)
class GatingContext:
    """门控评估所需的环境快照。"""

    platform: str
    available_bins: FrozenSet[str]
    available_env: FrozenSet[str]
    available_config: FrozenSet[str]
    # settings 白名单键快照。空集 = 未取到快照 -- 此时无法区分
    # "键不存在" 和 "键不在白名单", 一律报 missing config。
    # 作为最后一个字段 + 默认值, 保持所有现有 keyword-arg 构造点向后兼容。
    known_config: FrozenSet[str] = frozenset()

    @classmethod
    def from_env(
        cls,
        platform: Optional[str] = None,
        bin_whitelist: Optional[List[str]] = None,
        settings_repo: Optional[SettingsRepository] = None,
    ) -> GatingContext:
        """从当前环境构造 GatingContext。

        Args:
            platform: 平台名称（None = 自动检测 sys.platform）
            bin_whitelist: 要探测的二进制列表（None = 不探测，空集）
            settings_repo: settings 仓储（None = 不读配置，available_config 为空）
        """
        if platform is None:
            if sys.platform.startswith("darwin"):
                platform = "macos"
            elif sys.platform.startswith("win"):
                platform = "windows"
            else:
                platform = "linux"

        # 探测二进制
        available_bins: Set[str] = set()
        if bin_whitelist:
            for bin_name in bin_whitelist:
                if shutil.which(bin_name) is not None:
                    available_bins.add(bin_name)

        return cls(
            platform=platform,
            available_bins=frozenset(available_bins),
            available_env=frozenset(os.environ.keys()),
            available_config=_read_present_config(settings_repo),
            known_config=_known_config_keys(),
        )


def _known_config_keys() -> FrozenSet[str]:
    """返回 settings 白名单键集合（模块级常量，不依赖 DB 连接）。"""
    from backend.data.settings_repo import SettingsRepository

    return frozenset(SettingsRepository.KEYS)


def _read_present_config(
    settings_repo: Optional[SettingsRepository],
) -> FrozenSet[str]:
    """返回"当前有值"的 settings 键集合。

    settings_repo 为 None（无 DB / 测试环境）-> 空集。
    单键读取失败不阻断整体快照 -- 门控只是加载条件，读不到就当作
    "没有配置"，技能被跳过，而不是让整个加载流程炸掉。
    """
    if settings_repo is None:
        return frozenset()
    present: Set[str] = set()
    for key in _known_config_keys():
        try:
            value = settings_repo.get(key)
        except Exception:  # noqa: BLE001 -- 快照失败降级为"缺配置"
            continue
        if value:
            present.add(key)
    return frozenset(present)


@dataclass(frozen=True)
class GatingResult:
    """门控评估结果。"""

    allowed: bool
    reasons: Tuple[str, ...] = ()
    always_override: bool = False


def evaluate_gating(doc: SkillMdDocument, ctx: GatingContext) -> GatingResult:
    """评估单个 skill 是否满足加载条件。

    纯函数，不抛异常。门控失败时返回 allowed=False + reasons 列表。
    如果 doc.always=True，跳过门控，返回 allowed=True + always_override=True。

    Args:
        doc: SKILL.md 文档（含 requires/os/always 字段）
        ctx: 环境快照（平台/二进制/环境变量/配置）

    Returns:
        GatingResult: 评估结果
    """
    reasons: List[str] = []

    # always=True 跳过门控
    if doc.always:
        # 仍然检查平台（always 不跳过平台过滤）
        if doc.os and ctx.platform not in doc.os:
            reasons.append(f"platform mismatch: {ctx.platform} not in {doc.os}")
            return GatingResult(
                allowed=False,
                reasons=tuple(reasons),
                always_override=False,
            )
        return GatingResult(
            allowed=True,
            reasons=(),
            always_override=True,
        )

    # 平台过滤
    if doc.os and ctx.platform not in doc.os:
        reasons.append(f"platform mismatch: {ctx.platform} not in {doc.os}")

    # requires.bins 检查
    for bin_name in doc.requires.bins:
        if bin_name not in ctx.available_bins:
            reasons.append(f"missing bin: {bin_name}")

    # requires.env 检查
    for env_name in doc.requires.env:
        if env_name not in ctx.available_env:
            reasons.append(f"missing env: {env_name}")

    # requires.config 检查 -- 键未知 (不在 settings 白名单) 报
    # "unknown config key"; 键已知但没值报 "missing config"。
    for config_key in doc.requires.config:
        if config_key in ctx.available_config:
            continue
        if ctx.known_config and config_key not in ctx.known_config:
            reasons.append(
                f"unknown config key: {config_key} (not in settings whitelist)"
            )
        else:
            reasons.append(f"missing config: {config_key}")

    allowed = len(reasons) == 0
    return GatingResult(
        allowed=allowed,
        reasons=tuple(reasons),
        always_override=False,
    )


def build_gating_context(
    platform: Optional[str] = None,
    bin_whitelist: Optional[List[str]] = None,
    settings_repo: Optional[SettingsRepository] = None,
) -> GatingContext:
    """构造门控上下文。bin 探测开销由调用方控制。

    这是 GatingContext.from_env 的别名，方便测试使用。
    """
    return GatingContext.from_env(
        platform=platform,
        bin_whitelist=bin_whitelist,
        settings_repo=settings_repo,
    )

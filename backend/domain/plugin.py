# ruff: noqa: UP006, UP007, UP035, UP045
"""插件内核契约（纯领域模型，无 I/O）。

本模块只定义**数据与规则**，不含任何运行时行为，供 ``backend.ports.plugin``
与 ``backend.application.kernel.*`` 共同依赖。

对齐参照：DeepSeek Harness 的 Cordis 插件模型（``Provider`` 能力声明、
``Fiber`` 生命周期状态机）。这里只借语义，不引入其框架或实现。

设计约束：

- 不读文件、不读时钟、不建连接（领域纯净性）；
- 不 import ``backend.adapters`` / 任何 I/O 框架；
- 文件行数受 ``architecture-policy.json`` 的 ``maxContractLines`` (300) 约束。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# --------------------------------------------------------------------------- #
# 常量与校验
# --------------------------------------------------------------------------- #

# 注意：``backend/tests/unit/test_domain_models.py`` 的领域纯净性守卫只允许
# dataclasses / enum / typing / abc / collections / __future__ / uuid /
# datetime / asyncio / time，因此这里**不能用 re**，校验一律用字符串原语实现。

MAX_PLUGIN_ID_LENGTH = 100
MAX_CAPABILITY_NAME_LENGTH = 100

_PLUGIN_ID_EDGE = frozenset("abcdefghijklmnopqrstuvwxyz0123456789")
_PLUGIN_ID_CHARS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789._-")
_CAP_EDGE = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")
_CAP_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")
_VERSION_TAIL = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-")
_ASCII_DIGITS = frozenset("0123456789")


def _has_edges_and_chars(value: str, edge: frozenset, chars: frozenset) -> bool:
    """首尾必须是 ``edge`` 中的字符，中间只能是 ``chars`` 中的字符。"""
    if not value:
        return False
    if value[0] not in edge or value[-1] not in edge:
        return False
    return all(ch in chars for ch in value)


def _is_semver(value: str) -> bool:
    """``1.2.3`` / ``1.2.3-rc.1`` / ``1.2.3+build.5`` 判定（无正则）。"""
    if not value:
        return False
    core = value
    for sep in ("+", "-"):
        idx = core.find(sep)
        if idx == -1:
            continue
        tail = core[idx + 1:]
        if not tail or not all(ch in _VERSION_TAIL for ch in tail):
            return False
        core = core[:idx]
    parts = core.split(".")
    if len(parts) != 3:
        return False
    return all(part and all(ch in _ASCII_DIGITS for ch in part) for part in parts)


class PluginContractError(ValueError):
    """插件契约违规（id / 能力名 / 版本格式不合法）。"""


def validate_plugin_id(value: str) -> str:
    """校验插件标识符，返回原值；违规抛 :class:`PluginContractError`。

    规则：小写字母或数字开头结尾，允许 ``.`` ``_`` ``-`` 连接，长度 1..100。
    """
    if not isinstance(value, str) or not value:
        raise PluginContractError("plugin_id 必须是非空字符串")
    if len(value) > MAX_PLUGIN_ID_LENGTH:
        raise PluginContractError(
            f"plugin_id 过长（{len(value)} > {MAX_PLUGIN_ID_LENGTH}）"
        )
    if not _has_edges_and_chars(value, _PLUGIN_ID_EDGE, _PLUGIN_ID_CHARS):
        raise PluginContractError(
            f"plugin_id 非法: {value!r}（小写字母/数字开头结尾，允许 . _ -）"
        )
    return value


def validate_capability_name(value: str) -> str:
    """校验能力名（工具名 / 服务名 / hook 名），返回原值。"""
    if not isinstance(value, str) or not value:
        raise PluginContractError("capability name 必须是非空字符串")
    if len(value) > MAX_CAPABILITY_NAME_LENGTH:
        raise PluginContractError(
            f"capability name 过长（{len(value)} > {MAX_CAPABILITY_NAME_LENGTH}）"
        )
    if not _has_edges_and_chars(value, _CAP_EDGE, _CAP_CHARS):
        raise PluginContractError(
            f"capability name 非法: {value!r}（字母/数字开头结尾，允许 . _ -）"
        )
    return value


def validate_version(value: str) -> str:
    """校验语义化版本（``1.2.3`` / ``1.2.3-rc.1``），返回原值。"""
    if not isinstance(value, str) or not _is_semver(value):
        raise PluginContractError(f"version 必须是语义化版本: {value!r}")
    return value


# --------------------------------------------------------------------------- #
# 枚举
# --------------------------------------------------------------------------- #


class ProviderKind(str, Enum):
    """插件能提供的八类能力。

    ``SERVICE`` 对应 Cordis 的命名服务（``ctx.tools`` / ``ctx.llm``），
    是插件之间互相注入的最小单位；其余为 sage 原生能力类型。
    """

    TOOL = "tool"
    SKILL = "skill"
    HOOK = "hook"
    COMMAND = "command"
    MCP = "mcp"
    SERVICE = "service"
    UI = "ui"
    AGENT = "agent"


class TrustLevel(str, Enum):
    """插件来源信任等级（决定默认加载策略）。"""

    BUILTIN = "builtin"
    VERIFIED = "verified"
    PERSONAL = "personal"


class FiberState(str, Enum):
    """插件实例的运行时状态（对应 Cordis 的 Fiber 状态机）。"""

    PENDING = "pending"
    LOADING = "loading"
    ACTIVE = "active"
    FAILED = "failed"
    UNLOADING = "unloading"
    DISPOSED = "disposed"

    @property
    def is_terminal(self) -> bool:
        """``FAILED`` 与 ``DISPOSED`` 不会被调度器继续推进（需显式 restart）。"""
        return self in (FiberState.FAILED, FiberState.DISPOSED)

    @property
    def is_running(self) -> bool:
        """正在运行（``LOADING`` 或 ``ACTIVE``）。"""
        return self in (FiberState.LOADING, FiberState.ACTIVE)


# --------------------------------------------------------------------------- #
# 能力声明
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class CapabilityDecl:
    """一条能力声明：谁（plugin）提供了什么（kind + name）。

    ``CapabilityDecl`` 只描述"声明"，不持有实现对象——实现由内核注册表持有，
    便于把声明序列化进清单、索引与审计日志。
    """

    plugin_id: str
    kind: ProviderKind
    name: str
    description: str = ""
    version: str = "1.0.0"

    def __post_init__(self) -> None:
        validate_plugin_id(self.plugin_id)
        if not isinstance(self.kind, ProviderKind):
            raise PluginContractError(f"kind 必须是 ProviderKind: {self.kind!r}")
        validate_capability_name(self.name)
        validate_version(self.version)
        if self.description and len(self.description) > 500:
            raise PluginContractError("description 过长（> 500）")

    @property
    def qualified_name(self) -> str:
        """全局唯一标识，形如 ``my-plugin/greet``。"""
        return f"{self.plugin_id}/{self.name}"

    def matches(self, kind: Optional[ProviderKind] = None, name: Optional[str] = None) -> bool:
        """按可选维度匹配，供注册表过滤使用。"""
        if kind is not None and self.kind is not kind:
            return False
        return name is None or self.name == name

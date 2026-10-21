# ruff: noqa: UP006, UP007, UP035
"""工具装配的三层配置与四预设（R81）。

本模块延续 R80 的机制/声明分离：它只处理 bundle **名字**，不 import
``backend.tools``，因此可以在不加载 94 个工具实现的情况下解析配置、
筛选 bundle，并为 CLI 导出「解析后的配置」。

分层顺序由低到高为::

    builtin < ~/.sage/harness.yaml < <workspace>/.sage/harness.yaml
    < SAGE_HARNESS_PRESET < patch

生产路径默认 ``strict=False`` —— 任何坏配置只产生 warning 并被忽略；
``CLI check`` 使用 ``strict=True``，把同一套校验变成明确的失败。
文件不存在是正常状态：此时使用 ``standard``，与 R80 以前的全量装配一致。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

HARNESS_DIR_NAME = ".sage"
HARNESS_FILE_NAME = "harness.yaml"
HARNESS_HOME_ENV = "SAGE_HARNESS_HOME"
HARNESS_PRESET_ENV = "SAGE_HARNESS_PRESET"
HARNESS_WORKSPACE_ENV = "SAGE_WORKSPACE"
DEFAULT_PRESET = "standard"

_ALLOWED_KEYS = frozenset({"preset", "bundles", "flags"})

__all__ = [
    "DEFAULT_PRESET",
    "HARNESS_DIR_NAME",
    "HARNESS_FILE_NAME",
    "HARNESS_HOME_ENV",
    "HARNESS_PRESET_ENV",
    "HARNESS_WORKSPACE_ENV",
    "PRESETS",
    "PRESET_NAMES",
    "HarnessConfig",
    "HarnessConfigError",
    "Preset",
    "clear_harness_cache",
    "default_harness_config",
    "load_harness_config",
    "preset_view",
    "presets_view",
    "project_harness_path",
    "resolved_view",
    "select_bundles",
    "user_harness_path",
]


class HarnessConfigError(ValueError):
    """harness 配置非法（仅 ``strict=True`` 时抛出）。"""


@dataclass(frozen=True)
class Preset:
    """一种产品形态的静态声明。

    Attributes:
        name: 预设名，出现在配置与 CLI 输出中。
        description: 给人看的用途说明。
        excluded_bundles: 相对全量 bundle 清单排除的名字。安装顺序仍由
            ``backend.tools.tool_bundles.BUNDLES`` 决定，预设不重排顺序。
        flags: 预设附带的已声明标志（键值对元组）。R81 只负责记录/导出，
            具体行为接入随后续轮次完成。
    """

    name: str
    description: str
    excluded_bundles: Tuple[str, ...] = ()
    flags: Tuple[Tuple[str, Any], ...] = ()

    @property
    def flag_values(self) -> Dict[str, Any]:
        """以普通 dict 形式返回预设 flags（每次返回新对象）。"""
        return dict(self.flags)


PRESETS: Dict[str, Preset] = {
    "standard": Preset(
        name="standard",
        description="桌面默认形态：安装全部内置 tool bundle。",
    ),
    "focus": Preset(
        name="focus",
        description="长会话聚焦形态：去掉 Office、浏览器、多模态与设计工具面。",
        excluded_bundles=(
            "office_core",
            "office_pdf",
            "office_template",
            "office_analysis",
            "office_journal",
            "office_quality",
            "browser",
            "multimodal",
            "design",
        ),
        flags=(("context", "compact"),),
    ),
    "headless": Preset(
        name="headless",
        description="无人值守形态：不安装会阻塞等待用户回答的工具面。",
        excluded_bundles=("ask_user",),
        flags=(("interactive", False),),
    ),
    "dev": Preset(
        name="dev",
        description="插件开发形态：工具面与 standard 相同，并声明 dev 标志。",
        flags=(("dev", True),),
    ),
}
PRESET_NAMES: Tuple[str, ...] = tuple(PRESETS)


@dataclass
class HarnessConfig:
    """各层合并后的 bundle 选择配置。"""

    preset: str = DEFAULT_PRESET
    bundle_overrides: Dict[str, bool] = field(default_factory=dict)
    flags: Dict[str, Any] = field(default_factory=dict)
    sources: Tuple[str, ...] = ("builtin",)
    warnings: Tuple[str, ...] = ()

    @property
    def preset_definition(self) -> Preset:
        """返回当前预设定义；防御性地把异常名字回退到 standard。"""
        return PRESETS.get(self.preset, PRESETS[DEFAULT_PRESET])

    def bundle_enabled(self, name: str) -> bool:
        """判断某个 bundle 在「预设 + 覆盖」叠加后是否启用。"""
        if name in self.bundle_overrides:
            return self.bundle_overrides[name]
        return name not in self.preset_definition.excluded_bundles

    def skipped_reason(self, name: str) -> Optional[str]:
        """返回 bundle 被排除的原因（``override`` / ``preset``）。"""
        if self.bundle_enabled(name):
            return None
        return "override" if name in self.bundle_overrides else "preset"


@dataclass
class _MergeState:
    preset: str = DEFAULT_PRESET
    bundle_overrides: Dict[str, bool] = field(default_factory=dict)
    flag_overrides: Dict[str, Any] = field(default_factory=dict)


_CacheKey = Tuple[str, int, str, int, str, Tuple[str, ...]]
_CACHE: Dict[_CacheKey, HarnessConfig] = {}


def default_harness_config() -> HarnessConfig:
    """构造无任何外部配置时的默认结果。"""
    return HarnessConfig()


def clear_harness_cache() -> None:
    """清空已解析配置的进程内 mtime 缓存。"""
    _CACHE.clear()


def _environment(environ: Optional[Mapping[str, str]]) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def _user_root(
    user_home: Optional[Any],
    environ: Mapping[str, str],
) -> Path:
    if user_home is not None:
        return Path(user_home).expanduser()
    configured = environ.get(HARNESS_HOME_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home()


def _workspace_root(
    workspace: Optional[Any],
    environ: Mapping[str, str],
) -> Path:
    if workspace is not None:
        return Path(workspace).expanduser()
    configured = environ.get(HARNESS_WORKSPACE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.cwd()


def user_harness_path(
    user_home: Optional[Any] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Path:
    """用户层配置文件路径：``<home>/.sage/harness.yaml``。"""
    return _user_root(user_home, _environment(environ)) / HARNESS_DIR_NAME / HARNESS_FILE_NAME


def project_harness_path(
    workspace: Optional[Any] = None,
    *,
    environ: Optional[Mapping[str, str]] = None,
) -> Path:
    """项目层配置文件路径：``<workspace>/.sage/harness.yaml``。"""
    env = _environment(environ)
    return _workspace_root(workspace, env) / HARNESS_DIR_NAME / HARNESS_FILE_NAME


def _same_path(first: Path, second: Path) -> bool:
    return os.path.normcase(str(first.absolute())) == os.path.normcase(str(second.absolute()))


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return -1


def _copy_config(config: HarnessConfig) -> HarnessConfig:
    return HarnessConfig(
        preset=config.preset,
        bundle_overrides=dict(config.bundle_overrides),
        flags=dict(config.flags),
        sources=tuple(config.sources),
        warnings=tuple(config.warnings),
    )


def _issue(message: str, warnings: List[str], *, strict: bool) -> None:
    if strict:
        raise HarnessConfigError(message)
    warnings.append(message)
    logger.warning("%s", message)


def _read_yaml_layer(
    path: Path,
    warnings: List[str],
    *,
    strict: bool,
) -> Optional[Any]:
    if not path.exists():
        return None
    if not path.is_file():
        _issue(f"harness 配置不是普通文件，已忽略：{path}", warnings, strict=strict)
        return {}

    try:
        import yaml

        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 生产加载必须 fail-open
        message = f"harness 配置读取失败，已忽略：{path}（{type(exc).__name__}: {exc}）"
        if strict:
            raise HarnessConfigError(message) from exc
        _issue(message, warnings, strict=False)
        return {}

    return {} if loaded is None else loaded


def _apply_layer(
    raw: Any,
    source: str,
    state: _MergeState,
    warnings: List[str],
    *,
    known_bundles: Optional[Sequence[str]],
    strict: bool,
) -> None:
    if not isinstance(raw, Mapping):
        _issue(f"harness 配置顶层必须是映射，已忽略：{source}", warnings, strict=strict)
        return

    for key in raw:
        if key not in _ALLOWED_KEYS:
            _issue(f"harness 配置含未知顶层键 {key!r}，已忽略：{source}", warnings, strict=strict)

    _apply_preset(raw, source, state, warnings, strict=strict)
    _apply_bundles(raw, source, state, warnings, known_bundles=known_bundles, strict=strict)
    _apply_flags(raw, source, state, warnings, strict=strict)


def _apply_preset(
    raw: Mapping[Any, Any],
    source: str,
    state: _MergeState,
    warnings: List[str],
    *,
    strict: bool,
) -> None:
    if "preset" not in raw or raw["preset"] is None:
        return
    value = raw["preset"]
    if isinstance(value, str) and value.strip() in PRESETS:
        state.preset = value.strip()
        return
    _issue(f"harness 配置含未知 preset {value!r}，已忽略：{source}", warnings, strict=strict)


def _apply_bundles(
    raw: Mapping[Any, Any],
    source: str,
    state: _MergeState,
    warnings: List[str],
    *,
    known_bundles: Optional[Sequence[str]],
    strict: bool,
) -> None:
    if "bundles" not in raw or raw["bundles"] is None:
        return
    value = raw["bundles"]
    if not isinstance(value, Mapping):
        _issue(f"harness 配置的 bundles 必须是映射，已忽略：{source}", warnings, strict=strict)
        return

    known = None if known_bundles is None else set(known_bundles)
    for name, enabled in value.items():
        if not isinstance(name, str) or not name.strip():
            _issue(
                f"harness 配置含非法 bundle 名 {name!r}，已忽略：{source}",
                warnings,
                strict=strict,
            )
            continue
        bundle_name = name.strip()
        if not isinstance(enabled, bool):
            _issue(
                f"harness bundle {bundle_name!r} 的开关必须是布尔值，已忽略：{source}",
                warnings,
                strict=strict,
            )
            continue
        if known is not None and bundle_name not in known:
            _issue(
                f"harness 配置含未知 bundle {bundle_name!r}，已忽略：{source}",
                warnings,
                strict=strict,
            )
            continue
        state.bundle_overrides[bundle_name] = enabled


def _apply_flags(
    raw: Mapping[Any, Any],
    source: str,
    state: _MergeState,
    warnings: List[str],
    *,
    strict: bool,
) -> None:
    if "flags" not in raw or raw["flags"] is None:
        return
    value = raw["flags"]
    if not isinstance(value, Mapping):
        _issue(f"harness 配置的 flags 必须是映射，已忽略：{source}", warnings, strict=strict)
        return

    for name, flag_value in value.items():
        if not isinstance(name, str) or not name.strip():
            _issue(
                f"harness 配置含非法 flag 名 {name!r}，已忽略：{source}",
                warnings,
                strict=strict,
            )
            continue
        state.flag_overrides[name.strip()] = flag_value


def load_harness_config(
    *,
    workspace: Optional[Any] = None,
    user_home: Optional[Any] = None,
    patch: Optional[Mapping[str, Any]] = None,
    environ: Optional[Mapping[str, str]] = None,
    known_bundles: Optional[Sequence[str]] = None,
    strict: bool = False,
) -> HarnessConfig:
    """加载并合并 harness 三层配置。

    Args:
        workspace: 项目根目录；缺省依次取 ``SAGE_WORKSPACE``、当前目录。
        user_home: 用户主目录；缺省依次取 ``SAGE_HARNESS_HOME``、系统主目录。
        patch: 最高优先级的内存配置（CLI ``--patch`` / 程序化调用）。
        environ: 环境变量映射，主要供测试注入。
        known_bundles: 已知 bundle 名；提供后未知名字会被警告/报错并丢弃。
        strict: ``True`` 时任何非法项都抛 :class:`HarnessConfigError`。

    Returns:
        合并后的 :class:`HarnessConfig`。返回值是独立副本，可安全修改。
    """
    env = _environment(environ)
    user_path = user_harness_path(user_home, environ=env)
    project_path = project_harness_path(workspace, environ=env)
    env_preset = env.get(HARNESS_PRESET_ENV, "").strip()
    known_marker = () if known_bundles is None else tuple(known_bundles)

    cache_key: Optional[_CacheKey] = None
    if patch is None and not strict:
        cache_key = (
            str(user_path),
            _mtime_ns(user_path),
            str(project_path),
            _mtime_ns(project_path),
            env_preset,
            known_marker,
        )
        cached = _CACHE.get(cache_key)
        if cached is not None:
            return _copy_config(cached)

    warnings: List[str] = []
    sources: List[str] = ["builtin"]
    state = _MergeState()

    user_raw = _read_yaml_layer(user_path, warnings, strict=strict)
    if user_raw is not None:
        source = str(user_path)
        sources.append(source)
        _apply_layer(
            user_raw,
            source,
            state,
            warnings,
            known_bundles=known_bundles,
            strict=strict,
        )

    if not _same_path(user_path, project_path):
        project_raw = _read_yaml_layer(project_path, warnings, strict=strict)
        if project_raw is not None:
            source = str(project_path)
            sources.append(source)
            _apply_layer(
                project_raw,
                source,
                state,
                warnings,
                known_bundles=known_bundles,
                strict=strict,
            )

    if env_preset:
        source = f"env:{HARNESS_PRESET_ENV}"
        sources.append(source)
        _apply_layer(
            {"preset": env_preset},
            source,
            state,
            warnings,
            known_bundles=known_bundles,
            strict=strict,
        )

    if patch is not None:
        sources.append("patch")
        _apply_layer(
            patch,
            "patch",
            state,
            warnings,
            known_bundles=known_bundles,
            strict=strict,
        )

    flags = PRESETS[state.preset].flag_values
    flags.update(state.flag_overrides)
    config = HarnessConfig(
        preset=state.preset,
        bundle_overrides=dict(state.bundle_overrides),
        flags=flags,
        sources=tuple(sources),
        warnings=tuple(warnings),
    )

    if cache_key is not None:
        _CACHE[cache_key] = _copy_config(config)
    return _copy_config(config)


def select_bundles(
    all_names: Sequence[str],
    config: HarnessConfig,
) -> Tuple[str, ...]:
    """按原声明顺序筛出启用的 bundle 名。"""
    return tuple(name for name in all_names if config.bundle_enabled(name))


def preset_view(preset: Preset) -> Dict[str, Any]:
    """单个预设的 JSON 友好视图。"""
    return {
        "name": preset.name,
        "description": preset.description,
        "excluded_bundles": list(preset.excluded_bundles),
        "flags": preset.flag_values,
    }


def presets_view() -> List[Dict[str, Any]]:
    """四预设目录的 JSON 友好视图（保持产品顺序）。"""
    return [preset_view(PRESETS[name]) for name in PRESET_NAMES]


def resolved_view(
    config: HarnessConfig,
    all_names: Sequence[str],
) -> Dict[str, Any]:
    """构造供 ``dump-config`` 使用的解析后配置视图。"""
    selected: List[str] = []
    skipped: List[Dict[str, str]] = []
    for name in all_names:
        if config.bundle_enabled(name):
            selected.append(name)
        else:
            skipped.append(
                {
                    "name": name,
                    "reason": "override" if name in config.bundle_overrides else "preset",
                }
            )

    return {
        "preset": config.preset,
        "description": config.preset_definition.description,
        "flags": dict(config.flags),
        "bundle_overrides": dict(config.bundle_overrides),
        "bundles": {
            "selected": selected,
            "skipped": skipped,
        },
        "sources": list(config.sources),
        "warnings": list(config.warnings),
    }

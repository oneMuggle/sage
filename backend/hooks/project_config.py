"""项目级钩子配置 (Phase 4): ``<workspace>/.sage/hooks.json``。

设计目标: 让团队把统一策略 (如「禁止 rm -rf」「提交前必须 lint」) 提交到
仓库, 每个成员打开项目即生效。

**安全模型** (项目级 hook 是"执行仓库里携带的代码", 必须按不可信输入对待):

1. **信任门禁 (fail-closed)** —— 未显式信任的工作区, 其 ``.sage/hooks.json``
   一律不加载。信任记录存于 preferences ``hooks_trusted_workspaces``。
   默认不信任, 用户需显式授权 (REST 端点 / 设置页)。
2. **命令路径约束** —— 命令中显式出现的文件路径 (含 ``/`` 或 ``\\``) 必须
   落在 workspace 内, 且不得含 ``..`` 穿越。无路径分隔符的命令名 (如 ``ruff``)
   经 PATH 解析, 放行 —— 拦截它们意义不大且会误伤。
3. **不遮蔽用户规则** —— 合并顺序为 project 在前、user 在后, 二者共存;
   项目配置无法删除或覆盖用户自定义 hook (合并层保证, 见 ``merger.py``)。

配置文件形状::

    {
        "version": 1,
        "hooks": [
            {"event": "pre_tool_use", "matcher": "bash",
             "command": "scripts/check-dangerous.sh", "timeout_seconds": 5}
        ]
    }
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, List, Optional, Set

from backend.hooks.config import HookConfig, HookConfigError, validate_hooks

logger = logging.getLogger(__name__)

#: 项目级配置相对工作区根目录的路径
PROJECT_CONFIG_REL_PATH = ".sage/hooks.json"
#: preferences 中记录已信任工作区绝对路径的键 (JSON 字符串数组)
TRUSTED_WORKSPACES_KEY = "hooks_trusted_workspaces"
#: 支持的配置版本 (仅接受此版本, 避免未来格式变更被静默误读)
SUPPORTED_VERSION = 1
#: 项目级 hook 数量上限 (与用户级共用 MAX_HOOKS 语义, 但独立计数)
MAX_PROJECT_HOOKS = 20


# ── 信任记录 ─────────────────────────────────────────────────────────


def _normalize_workspace(workspace: str) -> str:
    """把工作区路径规范化为绝对路径 (解析 symlink, 去尾斜杠)。"""
    return os.path.realpath(str(workspace))


def load_trusted_workspaces(settings_repo: Any) -> Set[str]:
    """读取已信任工作区集合 (fail-open → 空集合)。"""
    try:
        raw = settings_repo.get_json(TRUSTED_WORKSPACES_KEY)
    except Exception as exc:  # pragma: no cover — 防御性
        logger.warning("hooks: failed to read trusted workspaces (fail-closed): %s", exc)
        return set()
    if not isinstance(raw, list):
        return set()
    return {str(item) for item in raw if isinstance(item, str) and item}


def is_workspace_trusted(settings_repo: Any, workspace: str) -> bool:
    """判断工作区是否已被显式信任 (未信任 → 项目 hook 不加载)。"""
    if not workspace:
        return False
    return _normalize_workspace(workspace) in load_trusted_workspaces(settings_repo)


def trust_workspace(settings_repo: Any, workspace: str) -> None:
    """把工作区加入信任列表 (幂等)。"""
    normalized = _normalize_workspace(workspace)
    trusted = load_trusted_workspaces(settings_repo)
    if normalized in trusted:
        return
    trusted.add(normalized)
    settings_repo.set_json(TRUSTED_WORKSPACES_KEY, sorted(trusted))


def untrust_workspace(settings_repo: Any, workspace: str) -> None:
    """把工作区移出信任列表 (幂等)。"""
    normalized = _normalize_workspace(workspace)
    trusted = load_trusted_workspaces(settings_repo)
    if normalized not in trusted:
        return
    trusted.discard(normalized)
    settings_repo.set_json(TRUSTED_WORKSPACES_KEY, sorted(trusted))


# ── 命令路径约束 ─────────────────────────────────────────────────────


def _command_path_is_safe(command: str, workspace: str) -> bool:
    """校验命令中显式路径是否落在 workspace 内。

    只检查看起来像路径的 token (含 ``/`` 或 ``\\``)。经 PATH 解析的裸命令名
    (``ruff`` / ``prettier``) 放行 —— 它们是用户在系统上安装的工具。

    拒绝: 绝对路径在 workspace 之外; 含 ``..`` 的相对路径逃逸。
    """
    if not command:
        return False
    ws_real = _normalize_workspace(workspace)
    # 逐 token 粗切 (引号内的路径不单独处理 —— 保守起见一并检查)
    for raw_token in command.replace("'", " ").replace('"', " ").split():
        token = raw_token.strip()
        if not token or ("/" not in token and "\\" not in token):
            continue
        # 剥离 CLI 选项前缀 (--config=path 形式取等号右侧)
        if token.startswith("-"):
            token = token.lstrip("-")
            if "=" in token:
                token = token.split("=", 1)[1]
        if not token or ("/" not in token and "\\" not in token):
            continue

        if Path(token).is_absolute():
            resolved = os.path.realpath(token)
            if not (resolved == ws_real or resolved.startswith(ws_real + os.sep)):
                logger.warning(
                    "hooks: project hook references absolute path outside workspace: %s", token
                )
                return False
        elif ".." in token.split("/"):
            logger.warning("hooks: project hook references parent path: %s", token)
            return False
    return True


# ── 加载与校验 ───────────────────────────────────────────────────────


def _read_project_config(workspace: str) -> Optional[Any]:
    """读取 ``<workspace>/.sage/hooks.json``, 不存在 → None。"""
    config_path = Path(workspace) / PROJECT_CONFIG_REL_PATH
    if not config_path.is_file():
        return None
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("hooks: project config unreadable (ignored): %s — %s", config_path, exc)
        return None


def validate_project_hooks(raw: Any, workspace: str) -> List[HookConfig]:
    """校验项目级配置, 返回 HookConfig 列表。

    结构非法 / 版本不支持 / 命令路径越界 → 抛 ``HookConfigError``。
    调用方 (``load_project_hooks``) 捕获后降级为空列表 (fail-open 到"不加载",
    而非"加载部分") —— 半加载的项目策略比不加载更危险。
    """
    if not isinstance(raw, dict):
        raise HookConfigError(f"project config must be a JSON object, got {type(raw).__name__}")

    version = raw.get("version", SUPPORTED_VERSION)
    if version != SUPPORTED_VERSION:
        raise HookConfigError(f"unsupported project config version: {version!r}")

    hooks_raw = raw.get("hooks", [])
    if not isinstance(hooks_raw, list):
        raise HookConfigError("project config 'hooks' must be a list")
    if len(hooks_raw) > MAX_PROJECT_HOOKS:
        raise HookConfigError(f"too many project hooks: {len(hooks_raw)} > {MAX_PROJECT_HOOKS}")

    configs = validate_hooks(hooks_raw)  # 复用用户级严格校验

    for idx, cfg in enumerate(configs):
        if cfg.hook_type == "shell" and not _command_path_is_safe(cfg.command, workspace):
            raise HookConfigError(
                f"project hooks[{idx}].command references a path outside the workspace"
            )
        # 项目级不允许内联 python handler —— 那是内置钩子专用,
        # 允许任意 dotted path 等于允许仓库加载任意模块
        if cfg.hook_type == "python" and not cfg.builtin_id:
            raise HookConfigError(
                f"project hooks[{idx}].hook_type 'python' requires a builtin_id"
            )

    return configs


def load_project_hooks(
    workspace: Optional[str],
    settings_repo: Any = None,
) -> List[HookConfig]:
    """加载项目级钩子 (信任门禁 + fail-open)。

    返回空列表的情形 (全部记 debug/warning):
    - 无 workspace / 配置文件不存在
    - 工作区未被信任 (fail-closed, 记 warning 提醒用户可显式授权)
    - 配置非法或命令路径越界
    - settings 读失败
    """
    if not workspace:
        return []
    try:
        if settings_repo is None:
            from backend.data.settings_repo import SettingsRepository

            settings_repo = SettingsRepository()

        raw = _read_project_config(workspace)
        if raw is None:
            return []

        if not is_workspace_trusted(settings_repo, workspace):
            logger.warning(
                "hooks: project config found at %s but workspace is not trusted — "
                "hooks not loaded (grant trust to enable)",
                os.path.join(workspace, PROJECT_CONFIG_REL_PATH),
            )
            return []

        return validate_project_hooks(raw, workspace)
    except HookConfigError as exc:
        logger.warning("hooks: invalid project config ignored: %s", exc)
        return []
    except Exception as exc:  # pragma: no cover — 防御性
        logger.warning("hooks: project config load failed (fail-open): %s", exc)
        return []

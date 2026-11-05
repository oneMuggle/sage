# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""专家私有技能目录发现（M1，spec §5.2）。

约定路径::

    ~/.sage/specialists/<agent_id>/skills/<skill-name>/SKILL.md

- ``SAGE_SPECIALISTS_DIR`` 环境变量可覆盖根目录（测试 / 运维隔离）。
- 每个专家的私有技能以 ``specialist__<agent_id>__<name>`` 前缀注册进
  全局技能注册表，避免不同专家 / 全局技能同名互相覆盖。
- 目录发现全部 fail-safe：权限错误、符号链接、非法 agent_id 一律跳过，
  绝不阻断 adapter 构造（与 ``discover_skill_md_dirs`` 同契约）。

安全:
- agent_id 必须匹配 ``^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$``，防止 ``..``
  路径穿越。
- ``skills`` 目录本身为符号链接时跳过；SKILL.md 读取端另有
  ``O_NOFOLLOW`` 硬化（``skill_md.loader._read_no_follow``）。
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

from backend.domain.skill_scope import resolve_skill_allowlist

logger = logging.getLogger(__name__)

#: 私有技能名统一前缀；完整形式 ``specialist__<agent_id>__<skill>``
SPECIALIST_SKILL_PREFIX = "specialist__"

#: 前缀与原始技能名之间的分隔符
SPECIALIST_SKILL_SEPARATOR = "__"

_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")


def specialists_root() -> Path:
    """专家数据根目录：``$SAGE_SPECIALISTS_DIR`` 优先，否则 ``~/.sage/specialists``。"""
    env = os.environ.get("SAGE_SPECIALISTS_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    return Path.home() / ".sage" / "specialists"


def skill_name_prefix(agent_id: str) -> str:
    """返回某专家私有技能的注册名前缀（含结尾分隔符）。"""
    return f"{SPECIALIST_SKILL_PREFIX}{agent_id}{SPECIALIST_SKILL_SEPARATOR}"


def is_agent_id_safe(agent_id: str) -> bool:
    """agent_id 是否可安全用作目录名（防路径穿越 / 隐藏目录）。"""
    return bool(agent_id) and bool(_AGENT_ID_RE.match(agent_id))


def discover_specialist_skill_dirs() -> List[Tuple[str, Path]]:
    """扫描 ``~/.sage/specialists/*/skills``，返回 ``[(agent_id, dir)]``。

    仅返回确实存在的目录；符号链接、隐藏目录、非法 agent_id 一律跳过。
    任何 IO 错误都降级为空列表/部分结果（绝不外抛）。
    """
    root = specialists_root()
    try:
        if not root.is_dir():
            return []
        entries = sorted(root.iterdir())
    except OSError as exc:
        logger.warning("专家目录枚举失败，跳过私有技能: %s", exc)
        return []

    result: List[Tuple[str, Path]] = []
    for entry in entries:
        try:
            if entry.name.startswith(".") or entry.is_symlink():
                continue
            if not entry.is_dir() or not is_agent_id_safe(entry.name):
                continue
            skills_dir = entry / "skills"
            if skills_dir.is_dir() and not skills_dir.is_symlink():
                result.append((entry.name, skills_dir))
        except OSError as exc:  # noqa: BLE001 — 单个目录故障不影响其他专家
            logger.warning("专家私有技能目录检查失败 (%s): %s", entry.name, exc)
    return result


def agent_id_from_private_skill(skill_name: str) -> Optional[str]:
    """从私有技能注册名反解 agent_id；非私有技能返回 ``None``。"""
    if not skill_name.startswith(SPECIALIST_SKILL_PREFIX):
        return None
    rest = skill_name[len(SPECIALIST_SKILL_PREFIX) :]
    agent_id, separator, short_name = rest.partition(SPECIALIST_SKILL_SEPARATOR)
    if not separator or not agent_id or not short_name:
        return None
    return agent_id


def resolve_specialist_allowlist(
    patterns: Optional[Iterable[str]],
    available_names: Iterable[str],
    agent_id: Optional[str],
) -> Optional[Set[str]]:
    """专家会话的技能允许集（M1，spec §5.2）。

    公开技能按 ``patterns`` 过滤（与 ``resolve_skill_allowlist`` 同语义），
    在此基础上并入**本人**私有技能：

    - 私有技能只有在 ``patterns`` 命中其短名（如 ``polish-prose`` 或
      ``polish-*``）时才入集；``patterns`` 为空/None 时本人私有技能全部可见；
    - 同名遮蔽：本人私有 ``review`` 命中时，全局 ``review`` 从允许集移除
      （spec §5.2「专家私有 > 全局」）；
    - 其他专家的私有技能永远不进入允许集。

    Returns:
        ``None`` = 公开技能不受限且本人无私有技能；否则为具体允许集。
    """
    names = set(available_names)
    prefix = skill_name_prefix(agent_id) if agent_id and is_agent_id_safe(agent_id) else ""
    private_all = {n for n in names if n.startswith(SPECIALIST_SKILL_PREFIX)}
    public_names = names - private_all
    own_private = {
        full: full[len(prefix) :] for full in private_all if prefix and full.startswith(prefix)
    }

    resolved = resolve_skill_allowlist(patterns, public_names)
    if resolved is None:
        if not own_private:
            return None
        return set(public_names) | set(own_private)

    cleaned = [
        p.strip() for p in (patterns or []) if isinstance(p, str) and p.strip()
    ]
    for full, short in own_private.items():
        for pattern in cleaned:
            matched = short.startswith(pattern[:-1]) if pattern.endswith("*") else short == pattern
            if matched:
                resolved.add(full)
                break
        # 同名遮蔽：私有 > 全局（spec §5.2）
        resolved.discard(short)
    return resolved


__all__ = [
    "SPECIALIST_SKILL_PREFIX",
    "SPECIALIST_SKILL_SEPARATOR",
    "agent_id_from_private_skill",
    "discover_specialist_skill_dirs",
    "is_agent_id_safe",
    "resolve_specialist_allowlist",
    "skill_name_prefix",
    "specialists_root",
]

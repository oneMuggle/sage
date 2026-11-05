# ruff: noqa: UP006, UP007, UP035, UP045 — release/win7 Python 3.8 兼容
"""内置专家模板库（M4-Task 2，spec §9 模板库）。

5 套内置模板以目录形式存放于 ``specialist_templates/<template_id>/``，
每套即一个 v2 格式 ``persona.md``（与用户专家包同格式，单一真相源）。

公共 API：

- ``list_templates()`` — 返回模板元数据列表（不含 system_prompt 正文）
- ``get_template_dir(template_id)`` — 模板目录路径（非法 id / 不存在返回 None）
- ``instantiate_template(template_id)`` — 一键物化专家，复用导入管线，
  生成 ``specialist-<template_id>-<6hex>`` id，``source=builtin``，
  失败整体回滚（目录 + agents 行）
"""

from __future__ import annotations

import logging
import re
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

logger = logging.getLogger(__name__)

#: 模板根目录（PyInstaller 打包时需通过 ``datas`` 把目录一并复制；
#: Task 5 在 scripts/backend.spec 补齐）。
_TEMPLATES_DIR = Path(__file__).resolve().parent / "specialist_templates"

#: 模板 id 合法字符集（仅小写字母/数字/下划线/连字符，首字符必须字母或数字）
_TEMPLATE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

#: 展示顺序（与 spec §M4 模板清单一致），其余模板按 name 排序追加
_TEMPLATE_ORDER = ("writing", "research", "coding", "presentation", "office")

#: 默认头像（模板未声明 persona_ui.avatar 时使用）
_DEFAULT_AVATAR = "🧑‍💼"

#: 模板 persona.md 最大大小（与导入器一致：1 MiB）
_MAX_PERSONA_BYTES = 1 * 1024 * 1024


# --------------------------------------------------------------------------- #
# 内部辅助
# --------------------------------------------------------------------------- #


def _parse_frontmatter(persona_md: Path) -> Dict[str, Any]:
    """读取 ``persona.md`` 的 YAML frontmatter 并返回解析后的 dict。

    失败返回空 dict（不抛错——模板缺失字段由物化阶段补默认值）。
    """
    if persona_md.stat().st_size > _MAX_PERSONA_BYTES:
        logger.warning(
            "模板 %s 超过 %d 字节上限，跳过 frontmatter",
            persona_md,
            _MAX_PERSONA_BYTES,
        )
        return {}
    try:
        text = persona_md.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("模板 %s 读取失败: %s", persona_md, exc)
        return {}
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        data = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        logger.warning("模板 %s frontmatter 解析失败: %s", persona_md, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _template_dirs() -> List[Path]:
    """返回模板目录按 ``_TEMPLATE_ORDER`` 排序后的路径列表。"""
    if not _TEMPLATES_DIR.is_dir():
        return []
    entries = []
    for entry in _TEMPLATES_DIR.iterdir():
        try:
            if entry.is_dir() and _TEMPLATE_ID_RE.match(entry.name):
                entries.append(entry)
        except OSError:
            continue
    order_index = {name: idx for idx, name in enumerate(_TEMPLATE_ORDER)}
    return sorted(
        entries,
        key=lambda p: (order_index.get(p.name, len(order_index)), p.name),
    )


# --------------------------------------------------------------------------- #
# 公共 API
# --------------------------------------------------------------------------- #


def list_templates() -> List[Dict[str, Any]]:
    """返回内置模板元数据列表（不含 system_prompt 正文）。

    返回的每一项形如::

        {
            "id": "writing",
            "name": "写作专家",
            "tagline": "专业写作助手",
            "avatar": "📝",
            "description": "...",
            "skill_count": 3,
        }

    顺序由 ``_TEMPLATE_ORDER`` 决定，未列出的模板按 name 排序追加。
    """
    result: List[Dict[str, Any]] = []
    for dir_ in _template_dirs():
        persona_md = dir_ / "persona.md"
        if not persona_md.is_file():
            continue
        meta = _parse_frontmatter(persona_md)
        persona_ui = meta.get("persona_ui")
        if not isinstance(persona_ui, dict):
            persona_ui = {}
        skills = meta.get("skills")
        skills_count = len(skills) if isinstance(skills, list) else 0

        result.append(
            {
                "id": dir_.name,
                "name": str(meta.get("name") or dir_.name),
                "tagline": str(
                    meta.get("tagline") or persona_ui.get("tagline") or ""
                ),
                "avatar": str(
                    meta.get("avatar") or persona_ui.get("avatar") or _DEFAULT_AVATAR
                ),
                "description": str(meta.get("description") or ""),
                "skill_count": skills_count,
            }
        )
    return result


def get_template_dir(template_id: str) -> Optional[Path]:
    """返回模板目录路径；id 非法或模板不存在均返回 ``None``。"""
    if not isinstance(template_id, str) or not _TEMPLATE_ID_RE.match(template_id):
        return None
    dir_ = _TEMPLATES_DIR / template_id
    try:
        if not dir_.is_dir() or not (dir_ / "persona.md").is_file():
            return None
    except OSError:
        return None
    return dir_


def instantiate_template(template_id: str) -> Dict[str, Any]:
    """从内置模板一键创建专家。

    行为:

    - ``agent_id = specialist-<template_id>-<6hex>``（6 位随机 hex 防冲突）
    - ``source=builtin``（显式覆盖，不信任模板内部 source 字段）
    - 失败整体回滚（目录 + agents 行由 importer 处理）
    - 成功后返回 ``{"id", "name", "template_id", "dropped_bindings"}``

    Raises:
        ValueError: 模板不存在 / id 非法 / 物化失败
    """
    template_dir = get_template_dir(template_id)
    if template_dir is None:
        raise ValueError(f"模板不存在: {template_id}")

    from backend.services.specialist_importer import install_specialist_from_dir

    new_id = f"specialist-{template_id}-{secrets.token_hex(3)}"
    try:
        result = install_specialist_from_dir(
            template_dir,
            requested_id=new_id,
            source_override="builtin",
        )
    except ValueError as exc:
        raise ValueError(f"模板物化失败 ({template_id}): {exc}") from exc
    except Exception as exc:  # noqa: BLE001 — 兜底外抛为 ValueError
        raise ValueError(f"模板物化失败 ({template_id}): {exc}") from exc

    result["template_id"] = template_id
    return result


__all__ = ["list_templates", "get_template_dir", "instantiate_template"]

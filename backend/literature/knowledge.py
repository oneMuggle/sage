"""站点知识的 sidecar 读写与合并（spec §3.1）。

机器写入的站点经验与后端清单**不进主 profile YAML**，而是写同目录的
sidecar 文件：

- ``<site_id>.notes.yaml``
- ``<site_id>.backends.yaml``

原因：主 YAML 是「人手写配置」，``yaml.safe_dump`` 会毁掉用户手写注释；
sidecar 天然分离「人手写」与「机器追加」。

合并规则：主 YAML 为人写基线，sidecar 按 ``id`` 覆盖同 id 条目，其余追加。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import yaml

from .models import SiteBackend, SiteNote, SiteProfileError
from .run_store import atomic_write_text

logger = logging.getLogger(__name__)

NOTES_SIDECAR_SUFFIX = ".notes.yaml"
BACKENDS_SIDECAR_SUFFIX = ".backends.yaml"


def is_sidecar_filename(name: str) -> bool:
    """判断文件名是否是 sidecar（而非站点 profile 主文件）。"""
    text = str(name or "")
    return text.endswith(NOTES_SIDECAR_SUFFIX) or text.endswith(BACKENDS_SIDECAR_SUFFIX)


def sidecar_path(sites_dir: Path, site_id: str, kind: str) -> Path:
    """返回 sidecar 路径；``kind`` 取 ``"notes"`` 或 ``"backends"``。"""
    suffix = NOTES_SIDECAR_SUFFIX if kind == "notes" else BACKENDS_SIDECAR_SUFFIX
    return Path(sites_dir) / f"{site_id}{suffix}"


def read_sidecar(path: Path) -> Dict[str, Any]:
    """读 sidecar YAML；损坏时抛 ``SiteProfileError``（不静默忽略）。"""
    target = Path(path)
    if not target.is_file():
        return {}
    try:
        raw = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise SiteProfileError(f"sidecar YAML 解析失败 {target}: {exc}") from exc
    except OSError as exc:
        raise SiteProfileError(f"sidecar 读取失败 {target}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SiteProfileError(f"sidecar 根节点必须是对象: {target}")
    return raw


def write_sidecar(path: Path, payload: Dict[str, Any]) -> None:
    """原子写 sidecar YAML（保留人手写主文件不动）。"""
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    atomic_write_text(Path(path), text)


def merge_notes(
    base: Sequence[SiteNote], extra: Sequence[SiteNote]
) -> Tuple[SiteNote, ...]:
    """按 id 合并；``extra`` 覆盖 ``base`` 的同 id 条目。"""
    merged: Dict[str, SiteNote] = {}
    order: List[str] = []
    for note in list(base) + list(extra):
        if note.id not in merged:
            order.append(note.id)
        merged[note.id] = note
    return tuple(merged[key] for key in order)


def merge_backends(
    base: Sequence[SiteBackend], extra: Sequence[SiteBackend]
) -> Tuple[SiteBackend, ...]:
    """按 id 合并；``extra`` 覆盖 ``base`` 的同 id 条目。"""
    merged: Dict[str, SiteBackend] = {}
    order: List[str] = []
    for backend in list(base) + list(extra):
        if backend.id not in merged:
            order.append(backend.id)
        merged[backend.id] = backend
    return tuple(merged[key] for key in order)

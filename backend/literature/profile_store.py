"""三级站点 profile 存储：内置 < 用户 < 项目（后者覆盖前者）。"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, NamedTuple, Optional, Sequence

import yaml

from .knowledge import (
    is_sidecar_filename,
    merge_backends,
    merge_notes,
    read_sidecar,
    sidecar_path,
)
from .models import SiteProfile, SiteProfileError, parse_backends, parse_notes, profile_from_dict

logger = logging.getLogger(__name__)

_YAML_SUFFIXES = frozenset({".yaml", ".yml"})


class ProfileRoot(NamedTuple):
    path: Path
    layer: str


def user_sites_dir() -> Path:
    """用户层站点目录（``$SAGE_LITERATURE_SITES_DIR`` 或 ``~/.sage/literature_sites``）。"""
    env_dir = os.environ.get("SAGE_LITERATURE_SITES_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    return Path.home() / ".sage" / "literature_sites"


class SiteProfileStore:
    """从多个根目录加载 profile；同 id 以更晚的根（项目）为准。"""

    def __init__(self, roots: Sequence[ProfileRoot]):
        self._roots = list(roots)
        self._profiles: Optional[Dict[str, SiteProfile]] = None
        self._errors: Dict[str, SiteProfileError] = {}

    @classmethod
    def default(cls) -> SiteProfileStore:
        return cls(
            [
                ProfileRoot(Path(__file__).parent / "sites", "builtin"),
                ProfileRoot(user_sites_dir(), "user"),
                ProfileRoot(Path.cwd() / ".sage" / "literature_sites", "project"),
            ]
        )

    def reload(self) -> None:
        self._profiles = None
        self._errors = {}

    def discover(self) -> Dict[str, SiteProfile]:
        if self._profiles is not None:
            return dict(self._profiles)

        profiles: Dict[str, SiteProfile] = {}
        errors: Dict[str, SiteProfileError] = {}

        for root in self._roots:
            if not root.path.is_dir():
                continue
            try:
                entries = sorted(root.path.iterdir())
            except OSError as exc:
                logger.warning("读取站点 profile 目录失败 %s: %s", root.path, exc)
                continue

            for path in entries:
                if path.name.startswith(".") or path.suffix.lower() not in _YAML_SUFFIXES:
                    continue
                if is_sidecar_filename(path.name):
                    # sidecar 不是站点 profile 主文件；它随主 profile 一起合并
                    continue
                if not path.is_file():
                    continue
                try:
                    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
                    profile = profile_from_dict(
                        raw, source_path=str(path), source_layer=root.layer
                    )
                except SiteProfileError as exc:
                    errors[path.stem] = exc
                    logger.warning("跳过无效站点 profile %s: %s", path, exc)
                    continue
                except yaml.YAMLError as exc:
                    errors[path.stem] = SiteProfileError(f"YAML 解析失败: {exc}")
                    logger.warning("跳过无法解析的站点 profile %s: %s", path, exc)
                    continue
                except OSError as exc:
                    errors[path.stem] = SiteProfileError(f"读取失败: {exc}")
                    logger.warning("读取站点 profile 失败 %s: %s", path, exc)
                    continue
                try:
                    profile = _merge_sidecars(profile, path.parent)
                except SiteProfileError as exc:
                    errors[path.stem] = exc
                    logger.warning("站点 profile sidecar 无效 %s: %s", path, exc)
                    continue
                profiles[profile.id] = profile

        self._profiles = profiles
        self._errors = errors
        return dict(profiles)

    def get(self, site_id: str) -> SiteProfile:
        self.discover()
        if site_id in self._errors:
            raise SiteProfileError(
                f"站点 {site_id!r} 的 profile 无效: {self._errors[site_id]}"
            )
        assert self._profiles is not None
        try:
            return self._profiles[site_id]
        except KeyError:
            raise SiteProfileError(
                f"未找到站点 profile: {site_id!r}. Available: {sorted(self._profiles)}"
            ) from None

    def list_ids(self) -> List[str]:
        self.discover()
        assert self._profiles is not None
        return sorted(self._profiles)


def _merge_sidecars(profile: SiteProfile, directory: Path) -> SiteProfile:
    """把同目录的 notes / backends sidecar 合并进 profile。"""
    notes_raw = read_sidecar(sidecar_path(directory, profile.id, "notes"))
    backends_raw = read_sidecar(sidecar_path(directory, profile.id, "backends"))
    if not notes_raw and not backends_raw:
        return profile
    notes = parse_notes(notes_raw.get("notes"))
    backends = parse_backends(backends_raw.get("backends"))
    return replace(
        profile,
        notes=merge_notes(profile.notes, notes),
        backends=merge_backends(profile.backends, backends),
    )


_DEFAULT_STORE: Optional[SiteProfileStore] = None


def get_default_store() -> SiteProfileStore:
    global _DEFAULT_STORE
    if _DEFAULT_STORE is None:
        _DEFAULT_STORE = SiteProfileStore.default()
    return _DEFAULT_STORE


def reset_default_store() -> None:
    global _DEFAULT_STORE
    _DEFAULT_STORE = None

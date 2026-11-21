"""把人工/agent 观测到的页面事实写成 draft profile YAML。"""

from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

import yaml

from .models import SiteProfile, profile_from_dict
from .run_store import atomic_write_text


def _with_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = copy.deepcopy(raw)
    data.setdefault("status", "draft")
    data.setdefault("version", "0.1.0")
    data.setdefault(
        "last_verified_at",
        datetime.now(timezone.utc).strftime("%Y-%m-%d"),  # noqa: UP017 — py38 兼容
    )
    data.setdefault(
        "compliance", {"note": "仅本人账号/机构授权", "default_enabled": False}
    )
    return data


def profile_draft_from_observation(raw: Dict[str, Any]) -> str:
    data = _with_defaults(raw)
    profile_from_dict(data)
    return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)


def write_profile_draft(raw: Dict[str, Any], out_path: Path) -> SiteProfile:
    data = _with_defaults(raw)
    profile = profile_from_dict(data)
    atomic_write_text(
        Path(out_path), yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
    )
    return profile

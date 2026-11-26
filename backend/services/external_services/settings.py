"""服务配置合并：defaults ← preferences（已解密） ← env，按 spec 声明驱动。"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Mapping, Optional

from backend.services.external_services.spec import ExternalServiceSpec


def merge_service_settings(
    spec: ExternalServiceSpec,
    stored: Mapping[str, Any],
    environ: Mapping[str, str],
) -> Dict[str, Any]:
    """三层合并服务配置。返回未做类型转换的原始值字典。"""
    values: Dict[str, Any] = dict(spec.defaults)
    if isinstance(stored, Mapping):
        for canonical in list(spec.defaults) + list(spec.aliases):
            if canonical in stored:
                values[canonical] = stored[canonical]
                continue
            for alias in spec.aliases.get(canonical, []):
                if alias in stored:
                    values[canonical] = stored[alias]
                    break
    for binding in spec.env_bindings:
        raw = (environ.get(binding.env_var) or "").strip()
        if raw:
            values[binding.json_field] = raw
    return values


def read_stored_settings(spec: ExternalServiceSpec) -> Dict[str, Any]:
    """读取 preferences 中该服务的 JSON blob（SecretBox 已在 repo 层解密）。"""
    try:
        from backend.data.settings_repo import SettingsRepository

        raw = SettingsRepository().get(spec.preference_key)
        if not raw:
            return {}
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001 — 配置读取失败退回默认值
        return {}


def load_service_settings(
    spec: ExternalServiceSpec,
    environ: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    env = os.environ if environ is None else environ
    return merge_service_settings(spec, read_stored_settings(spec), env)

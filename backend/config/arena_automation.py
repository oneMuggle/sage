"""Configuration model for the arena automation feature."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

#: Default config file, next to config.yaml in backend/config/
DEFAULT_CONFIG_PATH = Path(__file__).parent / "arena_automation.yaml"


class ArenaAutomationConfig(BaseModel):
    """All values read from arena_automation.yaml at startup."""

    enabled: bool = False
    max_accounts: int = Field(default=5, ge=1, le=20)
    max_concurrent_sessions: int = Field(default=2, ge=1, le=10)
    mail_provider: str = "mailtm"
    mail_api_key: Optional[str] = None
    account_idle_timeout_sec: int = 300
    probe_evidence_cap: int = 500
    failure_isolation_threshold: int = 3
    manual_captcha_timeout_sec: int = 180
    probe_backend: str = "python"  # "python" or "node"

    class Config:  # Pydantic v1 compat — also works in v2
        extra = "forbid"


def load_arena_automation_config(path: Optional[Path] = None) -> ArenaAutomationConfig:
    """Read arena_automation.yaml; any failure falls back to defaults (disabled).

    Fail-safe by design: a malformed config file must never block backend
    startup, and the feature must stay off unless explicitly enabled.
    """
    cfg_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    try:
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return ArenaAutomationConfig()
    except OSError as exc:
        logger.warning("arena_automation.yaml 读取失败（使用默认配置）: %s", exc)
        return ArenaAutomationConfig()
    except yaml.YAMLError as exc:
        logger.warning("arena_automation.yaml 解析失败（使用默认配置）: %s", exc)
        return ArenaAutomationConfig()
    if not isinstance(raw, dict):
        logger.warning("arena_automation.yaml 顶层不是映射（使用默认配置）")
        return ArenaAutomationConfig()
    try:
        return ArenaAutomationConfig(**raw)
    except ValidationError as exc:
        logger.warning("arena_automation.yaml 字段非法（使用默认配置）: %s", exc)
        return ArenaAutomationConfig()

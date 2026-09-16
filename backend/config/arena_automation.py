"""Configuration model for the arena automation feature."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


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
